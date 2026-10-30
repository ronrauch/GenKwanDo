"""Beat objects: a still instrument object (drum, speaker, amp, vinyl) that pulses to its stem.

This is a VISUAL EFFECT on a still image, applied in the COMP stage. It is not a played instrument: nothing is
rendered, nothing is sent anywhere, no GPU is used. Players (hands on instruments) stay the unproven lane.

Pipeline: ffmpeg decodes the stem to PCM (band-filtered for the effect) -> per-hop RMS energy (stdlib) ->
onsets (log-energy rises) and a per-frame envelope -> per-frame transforms (zoom, angle, brightness, dx, dy)
-> clamped so the layer's square never leaves the cover -> turned into ffmpeg expressions by media.comp_cmd.

Effects (strength 0..1, decay in seconds; 0 decay = the effect's default):
  pulse  kick:    scale pulse on each hit, exponential decay
  flash  snare:   brightness flash plus a small shake on each hit
  sway   bass:    rotation and drift that follow the stem's envelope
  glow   held:    brightness (and a hint of scale) that follows the stem's envelope
"""
from __future__ import annotations

import array
import math
import subprocess
from dataclasses import dataclass

FPS = 24
EFFECTS = ("pulse", "flash", "sway", "glow")
DEFAULT_DECAY = {"pulse": 0.18, "flash": 0.10, "sway": 0.30, "glow": 0.25}
DEFAULT_EFFECT_FOR_STEM = {"drums": "pulse", "bass": "sway"}  # anything else defaults to glow
BAND_FILTER = {"pulse": "lowpass=f=180", "flash": "highpass=f=1500", "sway": "lowpass=f=250", "glow": "lowpass=f=250"}

RATE = 22050
HOP = 256                       # samples per energy hop (about 11.6 ms)
HOP_S = HOP / RATE

# clamps: the layer's square must never leave the cover, and effects stay tasteful
MAX_ZOOM = 1.5
MAX_ANGLE = 0.2                 # radians
MAX_BRIGHT = 0.5


class BeatError(RuntimeError):
    pass


@dataclass(frozen=True)
class Transform:
    zoom: float = 1.0           # >= 1 (the pulse grows the object inside its square)
    angle: float = 0.0          # radians
    brightness: float = 0.0
    dx: float = 0.0             # pixels, canvas space
    dy: float = 0.0


def default_effect(stem: str) -> str:
    return DEFAULT_EFFECT_FOR_STEM.get(stem, "glow")


# ---- audio analysis (stdlib only) --------------------------------------------------------------------

def pcm_cmd(src: str, start: float, length: float, effect: str) -> list[str]:
    """ffmpeg command that writes mono 16-bit PCM of the slice, band-filtered for the effect, to stdout."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(start, 0):.6f}", "-t", f"{length:.6f}", "-i", src, "-vn", "-ac", "1"]
    if BAND_FILTER.get(effect):
        cmd += ["-af", BAND_FILTER[effect]]
    return cmd + ["-ar", str(RATE), "-f", "s16le", "-"]


def decode_pcm(src: str, start: float, length: float, effect: str) -> array.array:
    proc = subprocess.run(pcm_cmd(src, start, length, effect), capture_output=True)
    if proc.returncode != 0:
        raise BeatError(f"could not decode {src}: {proc.stderr.decode()[-300:]}")
    samples = array.array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    return samples


def hop_rms(samples, hop: int = HOP) -> list[float]:
    """RMS (0..1) of each hop of samples."""
    out = []
    for i in range(len(samples) // hop):
        chunk = samples[i * hop:(i + 1) * hop]
        out.append(math.sqrt(sum(c * c for c in chunk) / hop) / 32768.0)
    return out


def detect_onsets(energy: list[float], hop_s: float = HOP_S, min_gap: float = 0.09,
                  rise: float = 0.8, floor_frac: float = 0.12) -> list[float]:
    """Onset times in seconds: a hop whose log-energy jumps by `rise` or more, strong enough against the peak.

    Greedy by strength with a minimum gap, so a decaying hit is counted once. A silent stem gives [].
    """
    if len(energy) < 3:
        return []
    peak = max(energy)
    if peak < 1e-4:
        return []
    logs = [math.log(e + 1e-5) for e in energy]
    cands = []
    for i in range(1, len(energy)):
        flux = logs[i] - max(logs[i - 1], logs[i - 2] if i > 1 else logs[i - 1])
        loud = max(energy[i], energy[i + 1] if i + 1 < len(energy) else 0.0)
        if flux >= rise and loud >= floor_frac * peak:
            cands.append((flux, i))
    chosen: list[float] = []
    for flux, i in sorted(cands, reverse=True):
        t = i * hop_s
        if all(abs(t - c) >= min_gap for c in chosen):
            chosen.append(t)
    return sorted(round(t, 4) for t in chosen)


def frame_envelope(energy: list[float], hop_s: float, fps: int, frames: int) -> list[float]:
    """Mean energy per video frame, normalised by its 95th percentile and clipped to 0..1."""
    raw = []
    for f in range(frames):
        a, b = int(f / fps / hop_s), max(int(math.ceil((f + 1) / fps / hop_s)), int(f / fps / hop_s) + 1)
        seg = energy[a:b]
        raw.append(sum(seg) / len(seg) if seg else 0.0)
    ref = sorted(raw)[int(0.95 * (len(raw) - 1))] if raw else 0.0
    if ref < 1e-4:
        return [0.0] * frames
    return [min(1.0, r / ref) for r in raw]


def analyze(src: str, start: float, length: float, effect: str, fps: int = FPS) -> dict:
    """Onsets (seconds from the slice start) and a per-frame envelope for one stem."""
    frames = round(length * fps)
    energy = hop_rms(decode_pcm(src, start, length, effect))
    return {"onsets": detect_onsets(energy), "envelope": frame_envelope(energy, HOP_S, fps, frames), "frames": frames}


# ---- transforms ---------------------------------------------------------------------------------------

def hit_curve(onsets: list[float], fps: int, frames: int, decay: float) -> list[float]:
    """1.0 on the frame of a hit, decaying exponentially (time constant `decay`), summed and capped at 1."""
    curve = [0.0] * frames
    k = 1.0 / (fps * decay)
    for t in onsets:
        f0 = round(t * fps)
        f = f0
        while 0 <= f < frames:
            v = math.exp(-(f - f0) * k)
            if v < 1e-3:
                break
            curve[f] += v
            f += 1
    return [min(1.0, c) for c in curve]


def release_envelope(env: list[float], fps: int, decay: float) -> list[float]:
    """Instant attack, exponential release: the follower used by sway and glow."""
    out, prev, k = [], 0.0, math.exp(-1.0 / (fps * decay))
    for e in env:
        prev = max(e, prev * k)
        out.append(prev)
    return out


def clamp_transform(tr: Transform, box: tuple[int, int, int], canvas: int) -> Transform:
    """Keep every value in range and the layer's square (x, y, w) fully inside the cover."""
    x, y, w = box
    dx = min(max(tr.dx, -x), canvas - x - w)
    dy = min(max(tr.dy, -y), canvas - y - w)
    return Transform(
        zoom=round(min(max(tr.zoom, 1.0), MAX_ZOOM), 4),
        angle=round(min(max(tr.angle, -MAX_ANGLE), MAX_ANGLE), 4),
        brightness=round(min(max(tr.brightness, -MAX_BRIGHT), MAX_BRIGHT), 4),
        dx=round(dx, 2),
        dy=round(dy, 2),
    )


def frame_transforms(effect: str, strength: float, decay: float, onsets: list[float], envelope: list[float],
                     fps: int, frames: int, box: tuple[int, int, int], canvas: int) -> list[Transform]:
    """The per-frame transforms for one beat layer. Deterministic: the same inputs give the same frames."""
    if effect not in EFFECTS:
        raise BeatError(f"effect must be one of {', '.join(EFFECTS)}")
    s = min(max(float(strength), 0.0), 1.0)
    decay = decay if decay and decay > 0 else DEFAULT_DECAY[effect]
    out: list[Transform] = []
    if effect in ("pulse", "flash"):
        hits = hit_curve(onsets, fps, frames, decay)
        for f in range(frames):
            a = hits[f]
            if effect == "pulse":
                tr = Transform(zoom=1.0 + 0.30 * s * a)
            else:
                tr = Transform(brightness=0.6 * s * a,
                               dx=14.0 * s * a * math.sin(f * 2.399963),
                               dy=14.0 * s * a * math.sin(f * 1.7 + 0.5))
            out.append(clamp_transform(tr, box, canvas))
        return out
    env = release_envelope(envelope + [0.0] * (frames - len(envelope)), fps, decay)[:frames]
    for f in range(frames):
        e, t = env[f], f / fps
        if effect == "sway":
            tr = Transform(angle=0.10 * s * e * math.sin(2 * math.pi * 1.2 * t),
                           dx=18.0 * s * e * math.sin(2 * math.pi * 1.2 * t + 1.0))
        else:
            tr = Transform(zoom=1.0 + 0.04 * s * e, brightness=0.35 * s * e)
        out.append(clamp_transform(tr, box, canvas))
    return out


# ---- ffmpeg expressions -------------------------------------------------------------------------------

def pw_expr(values: list[float], var: str = "n") -> str:
    """A balanced if() tree that returns values[var]. Depth is log2(N), so 720 frames stay parseable."""
    vals = [round(float(v), 4) for v in values]
    if not vals:
        return "0"
    if all(v == vals[0] for v in vals):
        return f"{vals[0]:g}"

    def build(lo: int, hi: int) -> str:  # [lo, hi)
        if hi - lo == 1:
            return f"{vals[lo]:g}"
        if all(v == vals[lo] for v in vals[lo:hi]):
            return f"{vals[lo]:g}"
        mid = (lo + hi) // 2
        return f"if(lt({var},{mid}),{build(lo, mid)},{build(mid, hi)})"

    return build(0, len(vals))
