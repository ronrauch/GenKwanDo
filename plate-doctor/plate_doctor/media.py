"""Media I/O: ffmpeg + stdlib only. numpy is optional and used in two clearly marked places (reflect, stitch)."""
from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from . import core
from .core import Refusal


def need_ffmpeg() -> None:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise Refusal("ffmpeg and ffprobe are required (brew install ffmpeg / apt install ffmpeg)")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def probe_media(path: Path) -> dict:
    """width, height, fps (Fraction), exact decoded frame count, vfr flag, audio present."""
    need_ffmpeg()
    info = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                          capture_output=True, text=True).stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not v:
        raise Refusal(f"{path}: no video stream")
    frames = run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                  "stream=nb_read_frames", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    rate = Fraction(v["r_frame_rate"])
    avg = Fraction(v.get("avg_frame_rate") or v["r_frame_rate"])
    return dict(width=int(v["width"]), height=int(v["height"]), fps=rate, vfr=bool(avg) and avg != rate,
                frames=int(frames.split(",")[0]), audio=any(s["codec_type"] == "audio" for s in info["streams"]))


def check_plate(info: dict, silent_audio: bool = False) -> list[str]:
    """Refusals for a plate, as messages (empty list = fine). The same rules the proven recipe lives by."""
    out = []
    if info["width"] % 32 or info["height"] % 32:
        out.append(f"plate is {info['width']}x{info['height']}; LTX wants both sides divisible by 32 "
                   "(e.g. 1280x544, 1920x1088). Scale or pad the plate first.")
    if info["vfr"]:
        out.append("variable frame rate plate; conform it to a constant rate first")
    if not info["audio"] and not silent_audio:
        out.append("the plate has no audio track. The recipe encodes it (VAEEncodeAudio into LTXVSetAudioRefTokens, "
                   "load-bearing). Use a plate with audio, or pass --silent-audio (UNPROVEN).")
    return out


# ---------------------------------------------------------------------------------------------- mattes

def read_gray(path: Path, width: int | None = None, height: int | None = None) -> tuple[list[bytes], int, int]:
    """Decode a video to a list of gray frames (bytes, W*H each)."""
    info = probe_media(path)
    w, h = info["width"], info["height"]
    raw = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
              capture_output=True).stdout
    size = w * h
    return [raw[i:i + size] for i in range(0, len(raw) - size + 1, size)], w, h


def read_matte(src: Path, width: int, height: int) -> list[bytes]:
    """Thresholded gray frames, white = remove. A video, or a folder of PNGs in frame order (hash names refused)."""
    need_ffmpeg()
    src = Path(src)
    if src.is_dir():
        names = core.order_matte_pngs([p.name for p in src.iterdir()])
        if not names:
            raise Refusal(f"{src}: no PNGs")
        blob = b"".join((src / n).read_bytes() for n in names)
        raw = run(["ffmpeg", "-v", "error", "-f", "image2pipe", "-c:v", "png", "-i", "-", "-f", "rawvideo",
                   "-pix_fmt", "gray", "-"], input=blob, capture_output=True).stdout
        count = len(names)
        if len(raw) != count * width * height:
            raise Refusal(f"matte PNGs do not decode to {count} frames of {width}x{height}")
        frames = [raw[i * width * height:(i + 1) * width * height] for i in range(count)]
    else:
        frames, w, h = read_gray(src)
        if (w, h) != (width, height):
            raise Refusal(f"matte is {w}x{h}, plate is {width}x{height}")
    return [core.binarize(f) for f in frames]


def encode_matte(frames: list[bytes], width: int, height: int, path: Path, fps: Fraction) -> None:
    """Lossless mask video as proven: x264 crf 0, yuv444p. A lossy matte jitters at its edge."""
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{width}x{height}",
                          "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "0", "-preset", "veryfast",
                          "-pix_fmt", "yuv444p", str(path)], stdin=subprocess.PIPE)
    p.communicate(b"".join(frames))
    if p.returncode:
        raise RuntimeError(f"ffmpeg failed encoding {path}")


def cut_plate_window(plate: Path, out: Path, w: dict, fps: Fraction, silent: bool = False) -> None:
    """One window of the plate: real frames src_start..src_end then `freeze` copies of the last one, h264 + AAC.
    silent=True synthesizes silence (UNPROVEN: the audio feeds a load-bearing node)."""
    n_real = w["src_end"] - w["src_start"] + 1
    t0, t_real, t_all = (w["src_start"] / fps, n_real / fps, w["length"] / fps)
    vf = f"trim=start_frame={w['src_start']}:end_frame={w['src_end'] + 1},setpts=PTS-STARTPTS"
    if w["freeze"]:
        vf += f",tpad=stop_mode=clone:stop={w['freeze']}"
    if not silent:
        ain, amap = [], "0:a:0"
        af = f"atrim=start={float(t0):.6f}:end={float(t0 + t_real):.6f},asetpts=PTS-STARTPTS,apad=whole_dur={float(t_all):.6f}"
    else:
        ain, amap = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"], "1:a:0"
        af = f"atrim=end={float(t_all):.6f}"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(plate), *ain, "-map", "0:v:0", "-map", amap, "-vf", vf, "-af", af,
         "-frames:v", str(w["length"]), "-r", str(fps), "-c:v", "libx264", "-crf", "12", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{float(t_all):.6f}", str(out)])
    got = probe_media(out)["frames"]
    if got != w["length"]:
        raise RuntimeError(f"{out.name}: {got} frames cut, expected {w['length']}")


# ---------------------------------------------------------------------------------------------- vanish

def vanish(before: Path, after: Path, out: Path) -> None:
    """The shareable 'vanish' clip: a vertical wipe sweeps left to right and the subject disappears behind it.
    ffmpeg blend with a per-frame expression; no numpy. Both clips must match in size; the shorter one rules."""
    need_ffmpeg()
    a, b = probe_media(before), probe_media(after)
    if (a["width"], a["height"]) != (b["width"], b["height"]):
        raise Refusal(f"before is {a['width']}x{a['height']} but after is {b['width']}x{b['height']}")
    frames = min(a["frames"], b["frames"])
    dur = max(frames / float(a["fps"]), 1e-3)
    expr = f"if(lt(X,W*T/{dur:.6f}),B,A)"        # A = before (first input), B = after (second input)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(before), "-i", str(after), "-filter_complex",
         f"[0:v][1:v]blend=all_expr='{expr}':shortest=1,format=yuv420p[v]", "-map", "[v]", "-frames:v", str(frames),
         "-r", str(a["fps"]), "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", str(out)])


def browser_proxy(src: Path, dest: Path, max_width: int = 960) -> Path:
    """A small h264 mp4 a browser can always play and seek (ProRes / odd codecs / huge plates are not)."""
    need_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-vf", f"scale='min({max_width},iw)':-2",
         "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         str(dest)])
    return dest


# ---------------------------------------------------------------------------------------------- synthetic demo

def make_demo(workdir: Path, width: int = 640, height: int = 352, fps: int = 24, frames: int = 49) -> dict:
    """A synthetic plate, its matte, and the ground-truth clean background. Generated in memory with no assets:
    a gradient room with a checker floor and a bright 'performer' box crossing the frame, plus a tone track.
    TRUTH is the background without the box: ground truth for the wipe mechanics, NOT a Plate Doctor result."""
    need_ffmpeg()
    workdir.mkdir(parents=True, exist_ok=True)
    bg_rows = []
    for y in range(height):
        base = 40 + int(70 * y / height)
        if y > height * 0.7:                                    # a checker "floor"
            row = b"".join(bytes((base + (25 if ((x // 32) + (y // 16)) % 2 else 0), base // 2 + 20, base // 3 + 30))
                           for x in range(width))
        else:
            row = bytes((base, base // 2 + 25, base // 3 + 45)) * width
        bg_rows.append(row)
    box_w, box_h, box_y = 96, 200, height - 232
    color = bytes((235, 200, 60))
    plate, truth, matte = [], [], []
    for f in range(frames):
        # the box always keeps >= 8 visible columns, so the demo matte is never empty on any frame
        x0 = int((width + box_w - 16) * f / max(frames - 1, 1)) - (box_w - 8)
        a, b = max(x0, 0), min(x0 + box_w, width)
        rows, mrows = [], []
        for y in range(height):
            row = bg_rows[y]
            if box_y <= y < box_y + box_h and b > a:
                row = row[:a * 3] + color * (b - a) + row[b * 3:]
                mrow = bytes(a) + b"\xff" * (b - a) + bytes(width - b)
            else:
                mrow = bytes(width)
            rows.append(row)
            mrows.append(mrow)
        plate.append(b"".join(rows))
        truth.append(b"".join(bg_rows))
        matte.append(b"".join(mrows))

    def write_rgb(frames_: list[bytes], out: Path, audio: bool) -> None:
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
               "-r", str(fps), "-i", "-"]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=44100:duration={frames / fps:.4f}",
                    "-c:a", "aac", "-b:a", "128k", "-shortest"]
        cmd += ["-c:v", "libx264", "-crf", "12", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        p.communicate(b"".join(frames_))
        if p.returncode:
            raise RuntimeError(f"ffmpeg failed writing {out}")

    paths = dict(plate=workdir / "demo_plate.mp4", truth=workdir / "demo_truth.mp4", matte=workdir / "demo_matte.mp4")
    write_rgb(plate, paths["plate"], audio=True)
    write_rgb(truth, paths["truth"], audio=False)
    encode_matte(matte, width, height, paths["matte"], Fraction(fps))
    return {k: str(v) for k, v in paths.items()} | dict(width=width, height=height, fps=fps, frames=frames)


# ---------------------------------------------------------------------------------------------- optional numpy

def _numpy():
    try:
        import numpy as np
        return np
    except ImportError:
        raise Refusal("this step needs numpy (pip install numpy); the rest of Plate Doctor does not")


def mirror_reflection(frames: list[bytes], width: int, height: int, pct: float = 90, box: int = 9) -> list[bytes]:
    """Add a glossy surface's reflection to a person matte (optional numpy). Per frame: the contact line is the
    pct-th percentile of per-column mask bottoms; the silhouette is mirrored below it, grown by a box x box max
    filter, and unioned with the matte. A person matte alone misses the reflection and the model paints it back."""
    np = _numpy()
    out = []
    half = box // 2
    for fb in frames:
        m = (np.frombuffer(fb, np.uint8).reshape(height, width) > 127)
        cols = m.any(axis=0)
        if not cols.any():
            out.append(fb)
            continue
        bottoms = height - 1 - np.argmax(m[::-1, cols], axis=0)
        y0 = int(np.percentile(bottoms, pct))
        mir = np.zeros_like(m)
        ys = np.arange(y0 + 1, height)
        src = 2 * y0 - ys
        ok = src >= 0
        mir[ys[ok]] = m[src[ok]]
        g = mir.copy()                                        # separable box max filter
        for d in range(1, half + 1):
            g[d:, :] |= mir[:-d, :]
            g[:-d, :] |= mir[d:, :]
        h = g.copy()
        for d in range(1, half + 1):
            h[:, d:] |= g[:, :-d]
            h[:, :-d] |= g[:, d:]
        out.append(((m | h).astype(np.uint8) * 255).tobytes())
    return out


def stitch_windows(window_clips: list[Path], windows: list[dict], first: int, last: int, width: int, height: int,
                   out: Path, fps: Fraction) -> None:
    """Crossfade rendered windows into one clip using core.stitch_plan (optional numpy)."""
    np = _numpy()
    plan = core.stitch_plan(windows, first, last)
    stacks = []
    for clip in window_clips:
        raw = run(["ffmpeg", "-v", "error", "-i", str(clip), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                  capture_output=True).stdout
        stacks.append(np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3))
    blob = bytearray()
    for f in range(first, last + 1):
        acc = sum(stacks[wi][i].astype(np.float32) * wt for wi, (i, wt) in plan[f].items())
        blob += np.clip(acc + 0.5, 0, 255).astype(np.uint8).tobytes()
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                          "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(out)],
                         stdin=subprocess.PIPE)
    p.communicate(bytes(blob))
    if p.returncode:
        raise RuntimeError(f"ffmpeg failed writing {out}")
