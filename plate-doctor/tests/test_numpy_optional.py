"""The two steps that use numpy (reflect, stitch). Skipped cleanly where numpy or ffmpeg is missing."""
import shutil
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plate_doctor import media  # noqa: E402

try:
    import numpy as np
except ImportError:                                   # pragma: no cover
    np = None
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@unittest.skipUnless(np is not None, "numpy not installed")
class Reflect(unittest.TestCase):
    def test_the_silhouette_is_mirrored_below_the_contact_line(self):
        m = np.zeros((32, 32), np.uint8)
        m[4:16, 10:15] = 255                          # a person standing on row 15
        out = np.frombuffer(media.mirror_reflection([m.tobytes()], 32, 32)[0], np.uint8).reshape(32, 32)
        self.assertTrue((out[4:16, 10:15] == 255).all(), "the original matte must stay")
        self.assertEqual(out[20, 12], 255, "the reflection is added below the contact line")
        self.assertEqual(out[0, 12], 0, "nothing is added above the person")
        self.assertEqual(out[20, 28], 0, "the reflection stays near the silhouette")

    def test_an_empty_frame_is_left_alone(self):
        blank = bytes(32 * 32)
        self.assertEqual(media.mirror_reflection([blank], 32, 32)[0], blank)


@unittest.skipUnless(np is not None and HAVE_FFMPEG, "numpy or ffmpeg missing")
class Stitch(unittest.TestCase):
    def test_overlap_is_a_linear_crossfade_from_one_window_to_the_next(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            clips = []
            for name, color in (("a", "red"), ("b", "blue")):
                p = d / f"{name}.mp4"
                media.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=24:d=1",
                           "-frames:v", "16", "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv444p", str(p)])
                clips.append(p)
            windows = [dict(src_start=0, src_end=15, freeze=0, length=16),
                       dict(src_start=8, src_end=23, freeze=0, length=16)]
            out = d / "out.mp4"
            media.stitch_windows(clips, windows, 0, 23, 64, 64, out, Fraction(24))
            raw = media.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            capture_output=True).stdout
            frames = np.frombuffer(raw, np.uint8).reshape(-1, 64, 64, 3).astype(float)
            self.assertEqual(len(frames), 24)
            red = frames[:, :, :, 0].mean(axis=(1, 2))
            blue = frames[:, :, :, 2].mean(axis=(1, 2))
            self.assertGreater(red[0], 200)                         # first frames are window A (red)
            self.assertGreater(blue[23], 200)                       # last frames are window B (blue)
            self.assertTrue(all(red[i] >= red[i + 1] - 3 for i in range(7, 16)), "red fades out across the overlap")
            self.assertTrue(all(blue[i] <= blue[i + 1] + 3 for i in range(7, 16)), "blue fades in across the overlap")


if __name__ == "__main__":
    unittest.main()
