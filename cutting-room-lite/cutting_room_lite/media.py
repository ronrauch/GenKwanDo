"""ffmpeg helpers. Every command is built by a pure function (testable) and run by `run`."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .planner import FPS

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aif", ".aiff"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class MediaError(RuntimeError):
    pass


def run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=capture, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-600:]
        raise MediaError(f"{cmd[0]} failed ({proc.returncode}): {tail}")
    return proc


# --- command builders -------------------------------------------------------------------------------

def square_cover_cmd(src: str, dst: str, size: int = 1248) -> list[str]:
    """Centre-crop the cover to a square at the render size (album covers are square already)."""
    vf = f"scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}"
    return [FFMPEG, "-y", "-i", src, "-vf", vf, "-frames:v", "1", dst]


def trim_audio_cmd(src: str, dst: str, start: float, dur: float) -> list[str]:
    """Cut the song chunk for one window: stereo, 48 kHz, 16-bit wav."""
    return [
        FFMPEG, "-y", "-ss", f"{max(start, 0):.6f}", "-t", f"{dur:.6f}", "-i", src,
        "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", dst,
    ]


def last_frame_cmd(video: str, dst: str) -> list[str]:
    """Write the final frame of a take as a png (seek near the end, keep overwriting one file)."""
    return [FFMPEG, "-y", "-sseof", "-0.5", "-i", video, "-update", "1", "-q:v", "1", dst]


def segment_cmd(src: str, dst: str, drop_first: bool, fps: int = FPS, size: int = 1248) -> list[str]:
    """Normalise one take for the cut: fixed fps and size, no audio, first frame dropped when it repeats the guide."""
    vf = [f"fps={fps}", f"scale={size}:{size}"]
    if drop_first:
        vf.append("select='gte(n,1)',setpts=N/FRAME_RATE/TB")
    vf.append("format=yuv420p")
    return [FFMPEG, "-y", "-i", src, "-an", "-vf", ",".join(vf), "-c:v", "libx264", "-crf", "14", "-preset", "medium", dst]


def concat_list_text(segments: list[str]) -> str:
    return "".join(f"file '{Path(s).as_posix()}'\n" for s in segments)


def track_cmd(list_file: str, dst: str) -> list[str]:
    """Join one performer's normalised window segments into a full-length track (stream copy)."""
    return [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", dst]


def comp_cmd(backdrop: str, layers: list[dict], dst: str, frames: int, size: int = 1248, fps: int = FPS) -> list[str]:
    """COMP: overlay each layer on the cover backdrop.

    Video layer: dicts with video, x, y, w, and optionally matte (a png, white = performer) and feather (px).
    Beat layer: dicts with still (the object image), x, y, w, optionally matte, and beat = {zoom, angle,
    bright, dx, dy}: one value per frame (see beat.py). The still is pulsed, rotated, brightened and moved with
    ffmpeg expressions, so it costs nothing and needs no GPU.
    The cover stays as the backdrop, so a performer that is not animated simply stays as it is on the cover.
    """
    from .beat import pw_expr

    cmd = [FFMPEG, "-y", "-loop", "1", "-framerate", str(fps), "-i", backdrop]
    chains = [f"[0:v]scale={size}:{size},format=rgba[b0]"]
    idx = 1
    for n, ly in enumerate(layers, start=1):
        beat = ly.get("beat")
        w = ly["w"]
        if beat:
            cmd += ["-loop", "1", "-framerate", str(fps), "-i", ly["still"]]
        else:
            cmd += ["-i", ly["video"]]
        vi = idx
        idx += 1
        if beat:
            z = pw_expr(beat["zoom"], "on")
            zp = f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{w}:fps={fps}"
            rot = f"rotate=a='{pw_expr(beat['angle'])}':ow=iw:oh=ih"
            bright = pw_expr(beat["bright"])
            chains.append(f"[{vi}:v]scale={w}:{w},{zp},{rot}:c=none,eq=brightness='{bright}':eval=frame,format=rgba[v{n}]")
            # a beat layer always has a matte (white if none), so the rotated corners come out transparent
            if ly.get("matte"):
                cmd += ["-loop", "1", "-framerate", str(fps), "-i", ly["matte"]]
            else:
                cmd += ["-f", "lavfi", "-i", f"color=c=white:s={w}x{w}:r={fps}"]
            mi = idx
            idx += 1
            chains.append(f"[{mi}:v]scale={w}:{w},{zp},{rot}:c=black,format=gray[m{n}]")
            chains.append(f"[v{n}][m{n}]alphamerge[a{n}]")
            ox = f"{ly['x']}+{pw_expr(beat['dx'])}"
            oy = f"{ly['y']}+{pw_expr(beat['dy'])}"
            chains.append(f"[b{n - 1}][a{n}]overlay=x='{ox}':y='{oy}':eval=frame:format=auto:shortest=0[b{n}]")
            continue
        chains.append(f"[{vi}:v]scale={w}:{w},format=rgba[v{n}]")
        src = f"v{n}"
        if ly.get("matte"):
            cmd += ["-loop", "1", "-framerate", str(fps), "-i", ly["matte"]]
            mi = idx
            idx += 1
            blur = f",gblur=sigma={ly['feather']}" if ly.get("feather") else ""
            chains.append(f"[{mi}:v]scale={w}:{w},format=gray{blur}[m{n}]")
            chains.append(f"[v{n}][m{n}]alphamerge[a{n}]")
            src = f"a{n}"
        chains.append(f"[b{n - 1}][{src}]overlay=x={ly['x']}:y={ly['y']}:format=auto:shortest=0[b{n}]")
    chains.append(f"[b{len(layers)}]format=yuv420p[out]")
    cmd += ["-filter_complex", ";".join(chains), "-map", "[out]", "-frames:v", str(frames),
            "-c:v", "libx264", "-crf", "14", "-r", str(fps), dst]
    return cmd


def mux_cmd(video: str, song: str, slice_start: float, slice_len: float, dst: str) -> list[str]:
    """ASSEMBLE: lay the ORIGINAL song slice under the finished picture."""
    return [
        FFMPEG, "-y", "-i", video, "-ss", f"{slice_start:.6f}", "-t", f"{slice_len:.6f}", "-i", song,
        "-map", "0:v:0", "-map", "1:a:0", "-t", f"{slice_len:.6f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart", dst,
    ]


def alpha_matte_cmd(src: str, dst: str) -> list[str]:
    """SPLIT helper: the alpha channel of a clean performer png becomes a matte (white = performer)."""
    return [FFMPEG, "-y", "-i", src, "-vf", "alphaextract", "-frames:v", "1", dst]


def flatten_cmd(src: str, dst: str, size: int = 1248) -> list[str]:
    """SPLIT helper: flatten a transparent performer png over black so H3 gets a plain RGB reference."""
    fc = f"[1:v]scale={size}:{size},format=rgba[fg];[0:v][fg]overlay=format=auto,format=rgb24"
    return [FFMPEG, "-y", "-f", "lavfi", "-i", f"color=c=black:s={size}x{size}", "-i", src,
            "-filter_complex", fc, "-frames:v", "1", dst]


def beat_overlay_cmd(video: str, dst: str, bpm: float, first_beat_s: float = 0.0) -> list[str]:
    """Burn a flashing corner box on every beat so a human can judge hits against the beat (drummer test)."""
    period = 60.0 / bpm
    expr = f"lt(mod(max(t-{first_beat_s:.4f},0),{period:.5f}),0.08)*gte(t,{first_beat_s:.4f})"
    vf = f"drawbox=x=24:y=24:w=96:h=96:color=red@0.9:t=fill:enable='{expr}'"
    return [FFMPEG, "-y", "-i", video, "-vf", vf, "-c:v", "libx264", "-crf", "18", "-c:a", "copy", dst]


# --- probes and analysis ----------------------------------------------------------------------------

def has_alpha(path: str) -> bool:
    out = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt",
               "-of", "default=nw=1:nk=1", path])
    fmt = out.stdout.strip()
    return fmt.startswith(("rgba", "bgra", "argb", "abgr", "yuva", "gbrap", "ya", "pal8")) and fmt != "pal8"


def probe_duration(path: str) -> float:
    out = run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    return float(out.stdout.strip())


def probe_frames(path: str) -> int:
    out = run([FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0",
               "-show_entries", "stream=nb_read_frames", "-of", "default=nw=1:nk=1", path])
    return int(out.stdout.strip())


def wave_peaks(path: str, bins: int = 1200, rate: int = 4000) -> list[float]:
    """Peak amplitude (0..1) per bin, from a mono signed-8-bit decode piped out of ffmpeg."""
    proc = subprocess.run(
        [FFMPEG, "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "s8", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise MediaError("could not decode audio for the waveform")
    samples = memoryview(proc.stdout).cast("b")
    n = len(samples)
    bins = max(1, min(bins, n))
    step = n / bins
    peaks = []
    for i in range(bins):
        chunk = samples[int(i * step): max(int((i + 1) * step), int(i * step) + 1)]
        peaks.append(min(1.0, max(max(chunk), -min(chunk)) / 127.0))
    return peaks


def stem_active(stem_path: str, start: float, dur: float, threshold_db: float = -45.0) -> bool:
    """True when the stem's mean level in [start, start+dur) is above the threshold (the stem is playing)."""
    proc = subprocess.run(
        [FFMPEG, "-v", "info", "-ss", f"{start:.4f}", "-t", f"{dur:.4f}", "-i", stem_path,
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", proc.stderr)
    if not m or m.group(1) == "-inf":
        return False
    return float(m.group(1)) > threshold_db


# --- synthetic assets for tests and the local smoke run -------------------------------------------

def make_synthetic_song(dst: str, seconds: float = 40.0, bpm: float = 120.0) -> list[str]:
    """A click track over a low sine. Not music; just something with a waveform and a beat."""
    period = 60.0 / bpm
    # commas inside a lavfi expression must be escaped or ffmpeg reads them as filter separators
    expr = f"0.25*sin(2*PI*110*t)+0.7*lt(mod(t\\,{period:.5f})\\,0.02)*sin(2*PI*1800*t)"
    return [FFMPEG, "-y", "-f", "lavfi", "-i", f"aevalsrc={expr}:s=48000:d={seconds}", "-ac", "2", dst]


def make_color_image(dst: str, color: str, size: int = 1248) -> list[str]:
    """A flat colour square: a stand-in clean performer image for tests."""
    return [FFMPEG, "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}x{size}", "-frames:v", "1", dst]


def make_placeholder_cover(dst: str, size: int = 1248) -> list[str]:
    """A test pattern square with a PLACEHOLDER banner. Never a real cover."""
    vf = f"drawbox=x=0:y={size // 2 - 60}:w={size}:h=120:color=black@0.8:t=fill"
    return [FFMPEG, "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}x{size}:rate=1", "-vf", vf, "-frames:v", "1", dst]


def make_placeholder_take(dst: str, frames: int, fps: int = FPS, size: int = 1248, color: str | None = None) -> list[str]:
    """A test-pattern clip standing in for a take, so assembly can be exercised without H3.

    color: a flat colour instead of the test pattern (used by the comp tests to find a layer by pixel).
    """
    src = f"color=c={color}:s={size}x{size}:r={fps}" if color else f"testsrc2=size={size}x{size}:rate={fps}"
    return [FFMPEG, "-y", "-f", "lavfi", "-i", src,
            "-frames:v", str(frames), "-pix_fmt", "yuv420p", "-c:v", "libx264", dst]
