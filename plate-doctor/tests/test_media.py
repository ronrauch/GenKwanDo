"""Media + pipeline against a synthetic plate. Needs ffmpeg/ffprobe; skips cleanly without. No network."""
import json
import shutil
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plate_doctor import core, media, pipeline  # noqa: E402
from plate_doctor.core import Refusal  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class SyntheticDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.demo = media.make_demo(cls.dir / "demo")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_demo_plate_passes_the_plate_rules(self):
        info = media.probe_media(Path(self.demo["plate"]))
        self.assertEqual((info["width"], info["height"], info["frames"]), (640, 352, 49))
        self.assertTrue(info["audio"])
        self.assertEqual(media.check_plate(info), [])

    def test_plate_rules_refuse_bad_plates(self):
        base = dict(width=640, height=352, fps=24, vfr=False, frames=10, audio=True)
        self.assertTrue(media.check_plate(dict(base, width=650)))
        self.assertTrue(media.check_plate(dict(base, vfr=True)))
        self.assertTrue(media.check_plate(dict(base, audio=False)))
        self.assertEqual(media.check_plate(dict(base, audio=False), silent_audio=True), [])

    def test_matte_roundtrips_losslessly_and_is_never_empty(self):
        info = media.probe_media(Path(self.demo["plate"]))
        m = media.read_matte(Path(self.demo["matte"]), info["width"], info["height"])
        self.assertEqual(len(m), 49)
        self.assertEqual(core.empty_frames(m), [])
        self.assertTrue(all(set(f) <= {0, 255} for f in m))

    def test_png_folder_matte_keeps_frame_order(self):
        # write 3 distinct 8x8 mattes as PNG with ffmpeg, name them out of lexical order, read them back in order
        d = self.dir / "pngs"
        d.mkdir()
        for i, fill in enumerate((0x00, 0x80, 0xFF)):
            raw = bytes([fill] * 64)
            name = d / f"f{i}.png" if i != 1 else d / "f1.png"
            p = media.subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "8x8",
                                      "-i", "-", "-frames:v", "1", str(name)], input=raw, check=True)
        m = media.read_matte(d, 8, 8)
        self.assertEqual([f[0] for f in m], [0, 255, 255])         # thresholded: 0x80 is white
        (d / ("ab" * 16 + ".png")).write_bytes(b"x")
        with self.assertRaises(Refusal):
            media.read_matte(d, 8, 8)

    def test_window_cut_has_exactly_the_planned_frames_and_audio(self):
        info = media.probe_media(Path(self.demo["plate"]))
        w, = core.plan_windows(10, 14, info["frames"])
        out = self.dir / "w.mp4"
        media.cut_plate_window(Path(self.demo["plate"]), out, w, info["fps"])
        got = media.probe_media(out)
        self.assertEqual(got["frames"], w["length"])
        self.assertTrue(got["audio"])

    def test_vanish_clip_has_the_right_length_and_the_wipe_changes_pixels(self):
        out = self.dir / "vanish.mp4"
        media.vanish(Path(self.demo["plate"]), Path(self.demo["truth"]), out)
        self.assertEqual(media.probe_media(out)["frames"], 49)
        # frame 0: nothing revealed yet (== before); last frame: after is revealed on the left, so they differ
        def frame(path, n):
            return media.subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{n})",
                                         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                                        capture_output=True, check=True).stdout
        plate_last, truth_last, van_last = (frame(p, 47) for p in (self.demo["plate"], self.demo["truth"], out))
        w = 640

        def region(raw, x0, x1, y0=150, y1=300):
            return b"".join(raw[r * w + x0: r * w + x1] for r in range(y0, y1))

        def diff(a, b):                       # mean absolute pixel difference (h264 is lossy, so never exact)
            return sum(abs(x - y) for x, y in zip(a, b)) / len(a)

        # at frame 47 the wipe has passed x=614: the left shows AFTER (truth), the box on the far right is still BEFORE
        self.assertLess(diff(region(van_last, 0, 100), region(truth_last, 0, 100)), 6)
        self.assertLess(diff(region(van_last, 622, 640), region(plate_last, 622, 640)),
                        diff(region(van_last, 622, 640), region(truth_last, 622, 640)))
        self.assertGreater(diff(region(plate_last, 622, 640), region(truth_last, 622, 640)), 20,
                           "the demo box must actually differ from the truth")

    def test_vanish_refuses_clips_of_different_sizes(self):
        other = self.dir / "other.mp4"
        media.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x192:r=24:d=1",
                   "-pix_fmt", "yuv420p", str(other)])
        with self.assertRaises(Refusal):
            media.vanish(Path(self.demo["plate"]), other, self.dir / "x.mp4")

    def test_remove_dry_run_writes_windows_graphs_and_sends_nothing(self):
        def no_network(*a, **k):
            raise AssertionError("a dry run touched the network")
        with mock.patch.object(urllib.request, "urlopen", no_network):
            m = pipeline.remove_run(Path(self.demo["plate"]), Path(self.demo["matte"]), location="a plain room",
                                    probe=True, out=self.dir / "runs")
        self.assertTrue(m["dry_run"])
        self.assertEqual(len(m["windows"]), 1)
        w = m["windows"][0]
        self.assertEqual(w["length"], 9)
        g = json.loads(Path(w["graph"]).read_text())
        self.assertEqual(g["51"]["inputs"]["length"], 9)
        self.assertEqual(g["10"]["inputs"]["file"], "w00_plate.mp4")
        self.assertEqual(media.probe_media(Path(w["plate"]))["frames"], 9)
        self.assertEqual(media.probe_media(Path(w["matte"]))["frames"], 9)
        saved = json.loads((Path(m["run_dir"]) / "run.json").read_text())
        self.assertTrue(saved["dry_run"])
        self.assertIn("PLACEHOLDER", saved["estimate"])

    def test_remove_refuses_an_empty_matte_frame_before_cutting_anything(self):
        info = media.probe_media(Path(self.demo["plate"]))
        frames = media.read_matte(Path(self.demo["matte"]), info["width"], info["height"])
        frames[20] = bytes(len(frames[20]))                        # blank one frame
        bad = self.dir / "bad_matte.mp4"
        media.encode_matte(frames, info["width"], info["height"], bad, info["fps"])
        with self.assertRaises(Refusal) as ctx:
            pipeline.remove_run(Path(self.demo["plate"]), bad, location="x", frames="16-24", out=self.dir / "runs2")
        self.assertIn("20", str(ctx.exception))
        self.assertFalse((self.dir / "runs2").exists(), "nothing may be written when the matte is refused")

    def test_remove_refuses_a_matte_of_the_wrong_length(self):
        info = media.probe_media(Path(self.demo["plate"]))
        frames = media.read_matte(Path(self.demo["matte"]), info["width"], info["height"])[:30]
        short = self.dir / "short_matte.mp4"
        media.encode_matte(frames, info["width"], info["height"], short, info["fps"])
        with self.assertRaises(Refusal):
            pipeline.remove_run(Path(self.demo["plate"]), short, location="x", out=self.dir / "runs3")

    def test_remove_without_a_description_of_the_empty_set_is_refused(self):
        with self.assertRaises(Refusal):
            pipeline.remove_run(Path(self.demo["plate"]), Path(self.demo["matte"]), out=self.dir / "runs4")


if __name__ == "__main__":
    unittest.main()
