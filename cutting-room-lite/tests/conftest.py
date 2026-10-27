import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cutting_room_lite import media  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every test runs with the network shut: any real request fails the test loudly."""
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("a test tried to use the network")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)


@pytest.fixture(scope="session")
def assets(tmp_path_factory):
    """A 40 s click track and a placeholder cover, made once with ffmpeg."""
    d = tmp_path_factory.mktemp("assets")
    media.run(media.make_synthetic_song(str(d / "song.wav"), 40.0, 120.0))
    media.run(media.make_placeholder_cover(str(d / "cover.png")))
    media.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "40", str(d / "silent.wav")])
    return d


def pixel(video, t, x, y):
    """RGB of one pixel of a video at time t, via ffmpeg (no imaging library needed)."""
    import subprocess

    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-vf", f"crop=2:2:{x}:{y},format=rgb24",
         "-frames:v", "1", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    return tuple(out[:3])


def near(rgb, want, tol=14):
    return all(abs(a - b) <= tol for a, b in zip(rgb, want))
