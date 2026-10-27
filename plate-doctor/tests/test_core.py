"""Pure logic: frames, windows, prompt, graph patching, matte checks. No ffmpeg, no network.

    python3 -m unittest discover -s tests -t .
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plate_doctor import core  # noqa: E402
from plate_doctor.core import Refusal  # noqa: E402


class FrameMath(unittest.TestCase):
    def test_next_8n1_rounds_up_to_the_ltx_grid(self):
        self.assertEqual([core.next_8n1(n) for n in (1, 2, 9, 10, 57, 58, 121)], [1, 9, 9, 17, 57, 65, 121])

    def test_parse_frames_is_inclusive_and_strict(self):
        self.assertEqual(core.parse_frames("8-16"), (8, 16))
        self.assertEqual(core.parse_frames("12"), (12, 12))
        for bad in ("16-8", "a-b", "", "1-2-3"):
            with self.assertRaises(ValueError):
                core.parse_frames(bad)


class Windows(unittest.TestCase):
    def test_short_range_grows_to_8n1_with_real_frames_after_then_before(self):
        w, = core.plan_windows(10, 14, 100)                    # 5 frames -> 9
        self.assertEqual((w["src_start"], w["src_end"], w["freeze"], w["length"]), (10, 18, 0, 9))
        w, = core.plan_windows(96, 99, 100)                    # no frames after: grow backwards
        self.assertEqual((w["src_start"], w["src_end"], w["freeze"], w["length"]), (91, 99, 0, 9))

    def test_short_plate_freezes_the_last_frame(self):
        w, = core.plan_windows(0, 3, 4)                        # 4-frame plate cannot reach 9 with real frames
        self.assertEqual((w["src_start"], w["src_end"], w["freeze"], w["length"]), (0, 3, 5, 9))

    def test_long_range_windows_cover_everything_with_overlap(self):
        for n in (122, 200, 295, 500):
            ws = core.plan_windows(0, n - 1, n)
            self.assertTrue(all(w["length"] == core.MAX_WINDOW for w in ws))
            self.assertEqual(ws[0]["src_start"], 0)
            self.assertEqual(ws[-1]["src_end"], n - 1)
            for a, b in zip(ws, ws[1:]):
                self.assertGreaterEqual(a["src_end"] - b["src_start"] + 1, core.MIN_OVERLAP, f"overlap on {n} f")

    def test_range_outside_the_plate_is_an_error(self):
        for first, last in ((-1, 5), (0, 100), (9, 3)):
            with self.assertRaises(ValueError):
                core.plan_windows(first, last, 100)

    def test_probe_is_nine_frames_centred_or_placed(self):
        self.assertEqual(core.probe_range(0, 99), (45, 53))
        self.assertEqual(core.probe_range(0, 99, at=2), (2, 10))
        self.assertEqual(core.probe_range(0, 99, at=500), (91, 99))
        self.assertEqual(core.probe_range(4, 8), (4, 8))

    def test_stitch_weights_always_sum_to_one(self):
        ws = core.plan_windows(0, 294, 295)
        plan = core.stitch_plan(ws, 0, 294)
        for f, parts in plan.items():
            self.assertAlmostEqual(sum(wt for _, wt in parts.values()), 1.0, places=9, msg=f"frame {f}")
            for wi, (idx, _) in parts.items():
                self.assertTrue(0 <= idx < ws[wi]["length"])


class Prompt(unittest.TestCase):
    def test_prompt_describes_the_empty_set_and_never_says_remove(self):
        p = core.build_prompt("A bright room with a wooden chair.", empty="chair")
        self.assertIn("Completely empty chair.", p)
        self.assertIn("No people", p)
        self.assertNotIn("remove", p.lower())

    def test_empty_location_is_rejected(self):
        with self.assertRaises(ValueError):
            core.build_prompt("  ")


class GraphPatch(unittest.TestCase):
    kw = dict(plate_name="p.mp4", matte_name="m.mp4", width=640, height=352, length=9, fps=24.0, prompt="x",
              seed=7, dilation=11, prefix="PD/run")

    def test_patch_sets_every_window_value_and_keeps_only_nodes(self):
        recipe = core.load_remove_recipe()
        before = json.dumps(recipe, sort_keys=True)
        g = core.patch_remove_graph(recipe, **self.kw)
        self.assertEqual(json.dumps(recipe, sort_keys=True), before, "the recipe must not be mutated")
        self.assertNotIn("extra", g)
        self.assertEqual(g["10"]["inputs"]["file"], "p.mp4")
        self.assertEqual(g["20"]["inputs"]["file"], "m.mp4")
        self.assertEqual(g["51"]["inputs"]["length"], 9)
        self.assertEqual(g["62"]["inputs"]["noise_seed"], 7)
        self.assertEqual(g["81"]["inputs"]["filename_prefix"], "PD/run/RAW")
        self.assertEqual(g["92"]["inputs"]["filename_prefix"], "PD/run/BLEND")

    def test_the_shipped_recipe_keeps_the_load_bearing_wires(self):
        g = core.load_remove_recipe()
        self.assertEqual(g["54"]["inputs"]["positive"][0], "53")
        self.assertEqual(g["54"]["inputs"]["negative"][0], "53")
        self.assertEqual(g["90"]["inputs"]["image_b"][0], "50")

    def test_a_corrected_audio_ref_wire_is_refused(self):
        g = core.load_remove_recipe()
        g["54"]["inputs"]["positive"] = ["42", 0]              # the vendor example's wiring
        with self.assertRaises(ValueError):
            core.patch_remove_graph(g, **self.kw)

    def test_a_moved_node_is_refused(self):
        g = core.load_remove_recipe()
        g["51"]["class_type"] = "EmptyImage"
        with self.assertRaises(ValueError):
            core.patch_remove_graph(g, **self.kw)


class Matte(unittest.TestCase):
    def test_frames_are_ordered_numerically_not_alphabetically(self):
        names = ["f10.png", "f2.png", "f1.png", "readme.txt", "f0.png"]
        self.assertEqual(core.order_matte_pngs(names), ["f0.png", "f1.png", "f2.png", "f10.png"])

    def test_content_hash_names_are_refused(self):
        with self.assertRaises(Refusal):
            core.order_matte_pngs(["0f" * 32 + ".png", "f1.png"])

    def test_threshold_and_coverage(self):
        frame = bytes([0, 100, 128, 255])
        self.assertEqual(core.binarize(frame), bytes([0, 0, 255, 255]))
        self.assertEqual(core.coverage(frame), 0.5)

    def test_empty_frames_are_found_per_frame_and_refused(self):
        good, empty = bytes([0, 255, 0, 0]), bytes([0, 0, 0, 50])     # 50 is below the threshold
        self.assertEqual(core.empty_frames([good, empty, good, empty]), [1, 3])
        with self.assertRaises(Refusal) as ctx:
            core.require_matte_ok([good, empty], first=20, last=21)
        self.assertIn("21", str(ctx.exception))
        core.require_matte_ok([good, good], first=0, last=1)           # no raise


if __name__ == "__main__":
    unittest.main()
