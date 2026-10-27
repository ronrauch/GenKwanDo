"""RECOVER: SDR plate to a gradeable HDR EXR sequence.

Primary lane: the local LTX-2.3 HDR IC-LoRA graph. This repo does NOT ship Lightricks' workflow (ComfyUI-LTXVideo is
under the LTX-2 Community License Agreement): `fetch_graph` copies or downloads the user's own copy into
graphs/fetched/, and `ui_to_api` converts that copy to API format, dropping notes and dead branches.
Optional lane (PARTNER SERVICE, not open weights): the hosted api.ltx.video /v2/video-to-video-hdr endpoint.

Everything network-capable here takes an injectable opener so tests never touch the network.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.request
import zipfile
from pathlib import Path

from .core import GRAPHS, Refusal

UPSTREAM_REPO = "https://github.com/Lightricks/ComfyUI-LTXVideo"
UPSTREAM_GRAPH = "LTX-2.3_ICLoRA_HDR_Distilled.json"        # under the repo's LTX-2.3 example workflows
FETCHED_DIR = GRAPHS / "fetched"                              # gitignored: never part of this repo
FETCH_HELP = (f"RECOVER needs Lightricks' HDR workflow, which this repo does not ship (it is under the LTX-2 Community "
              f"License Agreement). Download {UPSTREAM_GRAPH} from the LTX-2.3 example workflows in {UPSTREAM_REPO}, "
              "then run:  python3 -m plate_doctor fetch-graph --from /path/to/" + UPSTREAM_GRAPH)
SKIP_TYPES = {"Note", "MarkdownNote"}
ROOT_TYPES = {"SaveVideo", "LTXVHDRDecodePostprocess"}      # the nodes that make files; everything else must feed them
LTX_BASE = "https://api.ltx.video"
HOSTED_LIMITS = [(1920 * 1088, 181), (2560 * 1440, 101), (3840 * 2160, 41)]   # (max pixels, max frames)


# ---------------------------------------------------------------------------------------------- UI graph to API

def ui_to_api(ui: dict, roots: set[str] = ROOT_TYPES) -> dict:
    """Convert a ComfyUI save-format graph to API format.

    Widget inputs consume `widgets_values` in order (a widget input that is also linked still consumes its slot);
    linked inputs become [origin id, origin slot]; upload buttons and notes are dropped; then every node that does
    not feed a `roots` node (dead branches such as unused API-key encoders) is pruned. Raises if a link points at
    a node that did not survive."""
    nodes = {n["id"]: n for n in ui["nodes"] if n["type"] not in SKIP_TYPES and n.get("mode", 0) == 0}
    links = {l[0]: l for l in ui["links"]}
    api: dict[str, dict] = {}
    for nid, n in nodes.items():
        vals = list(n.get("widgets_values") or [])
        vi = 0
        inputs: dict = {}
        for inp in n.get("inputs", []):
            is_widget = "widget" in inp
            val = None
            if is_widget:
                val = vals[vi] if vi < len(vals) else None
                vi += 1
            if inp.get("link") is not None:
                lk = links[inp["link"]]
                inputs[inp["name"]] = [str(lk[1]), lk[2]]
            elif is_widget and inp.get("type") != "IMAGEUPLOAD":
                inputs[inp["name"]] = val
        api[str(nid)] = {"class_type": n["type"], "inputs": inputs}

    keep: set[str] = set()
    stack = [k for k, v in api.items() if v["class_type"] in roots]
    while stack:
        k = stack.pop()
        if k in keep:
            continue
        keep.add(k)
        for v in api[k]["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                if v[0] not in api:
                    raise ValueError(f"node {k} reads from node {v[0]}, which is not in the converted graph")
                stack.append(v[0])
    return {k: api[k] for k in sorted(keep, key=int)}


def fetched_graph_path() -> Path:
    return FETCHED_DIR / UPSTREAM_GRAPH


def fetch_graph(source: str, dest: Path | None = None, opener=urllib.request.urlopen) -> Path:
    """Put the user's copy of the upstream HDR workflow where RECOVER reads it. `source` is a local file path or an
    explicit http(s) URL (the only network call here, and only when you pass a URL). The file must be a ComfyUI
    save-format graph. Nothing about its content is rewritten."""
    dest = Path(dest) if dest else fetched_graph_path()
    if source.startswith(("http://", "https://")):
        with opener(urllib.request.Request(source), timeout=60) as r:
            raw = r.read()
    else:
        src = Path(source).expanduser()
        if not src.is_file():
            raise Refusal(f"{src} does not exist. {FETCH_HELP}")
        raw = src.read_bytes()
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise Refusal(f"that is not JSON ({exc}); a GitHub HTML page will do this. Use the raw file.") from exc
    if not (isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("links"), list)):
        raise Refusal("that JSON is not a ComfyUI save-format workflow (no nodes/links lists)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def load_hdr_api_graph(path: Path | None = None) -> dict:
    """The HDR graph in API format, read from the user's fetched copy (or an explicit path)."""
    p = Path(path) if path else fetched_graph_path()
    if not p.is_file():
        raise Refusal(FETCH_HELP)
    return ui_to_api(json.loads(p.read_text()))


def _only(graph: dict, cls: str, optional: bool = False) -> str | None:
    ids = [k for k, v in graph.items() if v["class_type"] == cls]
    if optional and not ids:
        return None
    if len(ids) != 1:
        raise ValueError(f"expected exactly one {cls} in the HDR graph, found {len(ids)}")
    return ids[0]


def patch_hdr_graph(graph: dict, *, plate_name: str, fps: float, exr_dir: str, exr_prefix: str = "frame",
                    exposure: float = 7.1, seed: int = 42) -> dict:
    """The HDR graph with one plate and one EXR destination. Never mutates its input."""
    g = json.loads(json.dumps(graph))
    g[_only(g, "LoadVideo")]["inputs"]["file"] = plate_name
    dec = g[_only(g, "LTXVHDRDecodePostprocess")]["inputs"]
    dec.update(save_exr=True, output_dir=exr_dir, filename_prefix=exr_prefix, exposure=exposure)
    if (cv := _only(g, "CreateVideo", optional=True)):
        g[cv]["inputs"]["fps"] = float(fps)
    if (rn := _only(g, "RandomNoise", optional=True)):
        g[rn]["inputs"]["noise_seed"] = seed
    return g


# ---------------------------------------------------------------------------------------------- EXR sequences

def list_exr_sequence(folder: Path) -> list[Path]:
    """EXR frames in frame order with a contiguity check. Content-hash names are refused (their sort order is not
    frame order) and a gap in the numbering is a refusal naming the missing frames."""
    files = [p for p in Path(folder).iterdir() if p.suffix.lower() == ".exr"]
    if any(re.fullmatch(r"[0-9a-f]{32,}", p.stem) for p in files):
        raise Refusal(f"{folder} holds content-hash EXR names: sorted order is not frame order")
    numbered = []
    for p in files:
        m = re.search(r"(\d+)$", p.stem)
        if not m:
            raise Refusal(f"{p.name}: no trailing frame number")
        numbered.append((int(m.group(1)), p))
    numbered.sort()
    nums = [n for n, _ in numbered]
    if len(set(nums)) != len(nums):
        raise Refusal("duplicate frame numbers in the EXR sequence")
    if nums:
        missing = sorted(set(range(nums[0], nums[-1] + 1)) - set(nums))
        if missing:
            raise Refusal(f"EXR sequence has gaps: missing frames {missing[:12]}{'...' if len(missing) > 12 else ''}")
    return [p for _, p in numbered]


def normalize_exr_names(src: Path, dest: Path, shot: str, start: int = 1001) -> list[Path]:
    """Copy a sequence to <dest>/<shot>_hdr.<NNNN>.exr, numbered from `start` (the VFX convention is 1001)."""
    import shutil
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for i, p in enumerate(list_exr_sequence(src)):
        t = dest / f"{shot}_hdr.{start + i:04d}.exr"
        shutil.copyfile(p, t)
        out.append(t)
    return out


def safe_extract_exr_zip(zip_path: Path, dest: Path) -> list[Path]:
    """Extract only .exr members, refusing absolute paths and '..' (zip-slip)."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            target = (dest / name).resolve()
            if Path(name).is_absolute() or ".." in Path(name).parts or dest not in target.parents:
                raise Refusal(f"zip member {name!r} would land outside the destination")
            if not name.lower().endswith(".exr"):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
            out.append(target)
    return out


# ---------------------------------------------------------------------------------------------- hosted API (PARTNER)

def check_hosted_limits(width: int, height: int, frames: int) -> list[str]:
    px = width * height
    for max_px, max_f in HOSTED_LIMITS:
        if px <= max_px:
            return [] if frames <= max_f else [f"hosted API takes at most {max_f} frames at {width}x{height}, got {frames}"]
    return [f"{width}x{height} is above 4K; the hosted API does not take it"]


def exr_zip_url(result: dict) -> str:
    """The result URL is NESTED: result.exr_frames_url, not top level."""
    url = (result.get("result") or {}).get("exr_frames_url")
    if not url:
        raise Refusal("hosted job finished but result.exr_frames_url is missing")
    return url


def hosted_hdr(video: Path, key: str, *, opener=urllib.request.urlopen, sleep=time.sleep, poll_s: float = 5.0,
               max_wait_s: float = 1800.0) -> dict:
    """PARTNER SERVICE (not open weights, bills the user's LTX credits). POST /v2/video-to-video-hdr then poll.
    Written from the lab's notes, UNTESTED against the network in this repo."""
    data_uri = "data:video/mp4;base64," + base64.b64encode(Path(video).read_bytes()).decode()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def call(method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(LTX_BASE + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        with opener(req, timeout=120) as r:
            return json.loads(r.read())

    job = call("POST", "/v2/video-to-video-hdr", {"video_uri": data_uri})
    jid = job.get("id")
    if not jid:
        raise Refusal(f"hosted API gave no job id: {job}")
    waited = 0.0
    while waited <= max_wait_s:
        res = call("GET", f"/v2/video-to-video-hdr/{jid}")
        if res.get("status") == "completed":
            return res
        if res.get("status") in ("failed", "error", "cancelled"):
            raise Refusal(f"hosted job {jid} ended as {res.get('status')}")
        sleep(poll_s)
        waited += poll_s
    raise Refusal(f"hosted job {jid} still not complete after {max_wait_s:.0f} s")
