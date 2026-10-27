"""Pure logic: frame math, window planning, prompts, graph patching, matte ordering and checks.

No ffmpeg, no network, no third-party packages. Everything a paid run depends on is here, so it is all tested.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

GRAPHS = Path(__file__).resolve().parent.parent / "graphs"
REMOVE_RECIPE = GRAPHS / "ltx25-cleanplate.api.json"

MAX_WINDOW = 121        # 8n+1 ceiling per job: the recipe's window and what fits a 30-minute job cap
MIN_OVERLAP = 32        # crossfade region between windows on long shots
PROBE_FRAMES = 9        # a probe renders 9 frames, you look, then you run the range

PROMPT_HEAD = "An empty clean plate of the exact same location."
PROMPT_TAIL = ("No people, no humans, no figures, no faces, no heads, no shoulders. "
               "Static empty set, identical camera move, cinematic film grain.")

# Node ids the tool writes and the class each must be. A recipe that moved them fails here, not on the GPU.
NODE_ROLES = {"10": "LoadVideo", "20": "LoadVideo", "23": "LTXVDilateVideoMask", "40": "CLIPTextEncode",
              "42": "LTXVConditioning", "51": "EmptyLTXVLatentVideo", "53": "LTXVSetAudioRefTokens",
              "54": "LTXAddVideoICLoRAGuideAdvanced", "62": "RandomNoise", "81": "SaveVideo", "92": "SaveVideo"}


class Refusal(Exception):
    """A deliberate refusal: the message says what is wrong and what to do about it."""


# ---------------------------------------------------------------------------------------------- frames

def next_8n1(n: int) -> int:
    """Smallest 8n+1 frame count >= n. LTX's latent grid is 8 frames + 1."""
    return 1 + 8 * math.ceil(max(n - 1, 0) / 8)


def parse_frames(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", text or "")
    if not m:
        raise ValueError(f"--frames wants a-b (inclusive, 0-based plate frames), got {text!r}")
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) is not None else a
    if b < a:
        raise ValueError(f"--frames {text}: the end is before the start")
    return a, b


def plan_windows(first: int, last: int, plate_frames: int, max_len: int = MAX_WINDOW,
                 min_overlap: int = MIN_OVERLAP) -> list[dict]:
    """Windows covering plate frames first..last inclusive.

    Each window: src_start/src_end = real plate frames, freeze = copies of the last real frame appended to reach
    8n+1, length = frames the model renders. A short range grows to 8n+1 with real frames after it, then before it,
    then by freezing. A long range becomes max_len windows spread evenly with overlaps >= min_overlap."""
    if first < 0 or last >= plate_frames or last < first:
        raise ValueError(f"frames {first}-{last} are outside the plate's 0-{plate_frames - 1}")
    n = last - first + 1
    if n <= max_len:
        length = next_8n1(n)
        extra = length - n
        after = min(extra, plate_frames - 1 - last)
        before = min(extra - after, first)
        return [dict(src_start=first - before, src_end=last + after, freeze=extra - after - before, length=length)]
    k = 1 + math.ceil((n - max_len) / (max_len - min_overlap))
    starts = [first + int(i * (n - max_len) / (k - 1) + 0.5) for i in range(k)]
    return [dict(src_start=s, src_end=s + max_len - 1, freeze=0, length=max_len) for s in starts]


def probe_range(first: int, last: int, n: int = PROBE_FRAMES, at: int | None = None) -> tuple[int, int]:
    """The n frames a probe renders: centred in the selection, or starting at `at`."""
    if last - first + 1 <= n:
        return first, last
    start = at if at is not None else (first + last) // 2 - n // 2
    start = max(first, min(start, last - n + 1))
    return start, start + n - 1


def stitch_plan(windows: list[dict], first: int, last: int) -> dict[int, dict[int, tuple[int, float]]]:
    """For every output frame: {window index: (frame inside that window, weight)}. Windows fold in order and each
    overlap is a linear crossfade, so the weights of a frame always sum to 1."""
    weights: dict[int, dict[int, float]] = {}
    prev_end = None
    for wi, w in enumerate(windows):
        s, e = w["src_start"], w["src_end"]
        for f in range(s, e + 1):
            if prev_end is not None and f <= prev_end:
                a = (f - s + 1) / (prev_end - s + 2)
                weights[f] = {k: v * (1 - a) for k, v in weights[f].items()}
                weights[f][wi] = a
            else:
                weights[f] = {wi: 1.0}
        prev_end = e
    return {f: {wi: (f - windows[wi]["src_start"], wt) for wi, wt in weights[f].items()}
            for f in range(first, last + 1)}


# ---------------------------------------------------------------------------------------------- prompt

def build_prompt(location: str, empty: str | None = None) -> str:
    """The proven prompt shape: describe the EMPTY set. Never 'remove the person': the IC-LoRA paints people back
    from leftover shadow and contact cues."""
    loc = location.strip().rstrip(".").strip()
    if not loc:
        raise ValueError("describe the empty set (place, furniture, surfaces, light)")
    emptied = f"Completely empty {empty.strip()}." if empty else "Completely empty."
    return f"{PROMPT_HEAD} {loc}. {emptied} {PROMPT_TAIL}"


# ---------------------------------------------------------------------------------------------- graph

def load_remove_recipe(path: Path = REMOVE_RECIPE) -> dict:
    return json.loads(Path(path).read_text())


def patch_remove_graph(recipe: dict, *, plate_name: str, matte_name: str, width: int, height: int, length: int,
                       fps: float, prompt: str, seed: int, dilation: int, prefix: str) -> dict:
    """The recipe with one window's values. Never mutates the recipe; keeps only nodes (`extra` is metadata and
    the Cloud rejects a non-node key). Refuses a recipe whose node ids moved or whose load-bearing audio-ref wire
    was 'corrected'."""
    g = {k: json.loads(json.dumps(v)) for k, v in recipe.items() if isinstance(v, dict) and "class_type" in v}
    for nid, cls in NODE_ROLES.items():
        if g.get(nid, {}).get("class_type") != cls:
            raise ValueError(f"recipe node {nid} is {g.get(nid, {}).get('class_type')}, expected {cls}")
    for side in ("positive", "negative"):
        if str(g["54"]["inputs"][side][0]) != "53":
            raise ValueError("node 54 must take its conditioning from node 53 LTXVSetAudioRefTokens "
                             "(bypassing it hallucinated a person into the empty set)")
    g["10"]["inputs"]["file"] = plate_name
    g["20"]["inputs"]["file"] = matte_name
    g["23"]["inputs"]["spatial_radius"] = dilation
    g["40"]["inputs"]["text"] = prompt
    g["42"]["inputs"]["frame_rate"] = float(fps)
    g["51"]["inputs"].update(width=width, height=height, length=length)
    g["62"]["inputs"]["noise_seed"] = seed
    g["81"]["inputs"]["filename_prefix"] = f"{prefix}/RAW"
    g["92"]["inputs"]["filename_prefix"] = f"{prefix}/BLEND"
    return g


# ---------------------------------------------------------------------------------------------- matte

def order_matte_pngs(names: list[str]) -> list[str]:
    """Frame order for a folder of matte PNGs. Content-hash names are refused: their sort order is NOT frame
    order, and a hash-sorted matte once came out frame-scrambled. Order by the job that wrote them, then rename."""
    hashed = [n for n in names if re.fullmatch(r"[0-9a-f]{32,}", Path(n).stem)]
    if hashed:
        raise Refusal(f"matte folder holds content-hash names ({hashed[0]}...): their sorted order is not frame "
                      "order. Rename them by frame (f0000.png, f0001.png ...) from the job's own output order first.")
    key = lambda n: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", n)]
    return sorted((n for n in names if n.lower().endswith(".png")), key=key)


THRESHOLD = bytes(255 if i > 127 else 0 for i in range(256))   # white = remove


def binarize(frame: bytes) -> bytes:
    return frame.translate(THRESHOLD)


def coverage(frame: bytes) -> float:
    """Fraction of the frame that is matte (white), after thresholding."""
    return binarize(frame).count(255) / max(len(frame), 1)


def empty_frames(frames: list[bytes]) -> list[int]:
    """Frames whose matte is entirely black. Check PER FRAME: a file count calls an empty matte a pass."""
    return [i for i, f in enumerate(frames) if 255 not in binarize(f)]


def require_matte_ok(frames: list[bytes], first: int, last: int) -> None:
    """Refuse a matte that is empty on any frame about to be rendered (an empty frame renders nothing removed)."""
    bad = [first + i for i in empty_frames(frames)]
    if bad:
        raise Refusal(f"the matte is EMPTY on frames {bad[:12]}{'...' if len(bad) > 12 else ''}. "
                      "Fix the matte (white = remove) on those frames; nothing was sent anywhere.")


def estimate_report(windows: list[dict]) -> str:
    """No invented numbers: the repo ships no measured price. docs/COST.md says how to measure."""
    return (f"{len(windows)} window(s), {sum(w['length'] for w in windows)} frame(s) rendered. "
            "Cost estimate: PLACEHOLDER (not measured in this repo). Run a 9-frame probe first and read the bill; "
            "see docs/COST.md.")
