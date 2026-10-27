"""RECOVER (graph conversion, EXR paths, hosted client with a fake opener) and the submit gate. No network."""
import io
import json
import sys
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plate_doctor import recover, submit  # noqa: E402
from plate_doctor.core import Refusal  # noqa: E402
from tests.fixtures import hdr_like_ui_graph  # noqa: E402


class UiToApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = hdr_like_ui_graph()
        cls.api = recover.ui_to_api(cls.ui)

    def test_notes_muted_nodes_and_dead_branches_are_dropped(self):
        classes = {v["class_type"] for v in self.api.values()}
        for gone in ("Note", "MutedThing", "GemmaAPITextEncode", "PrimitiveString"):
            self.assertNotIn(gone, classes)
        self.assertEqual(classes, {"LoadVideo", "GetVideoComponents", "GetImageSize", "EmptyLTXVLatentVideo",
                                   "LTXVHDRDecodePostprocess", "CreateVideo", "SaveVideo"})

    def test_every_link_points_at_a_surviving_node(self):
        for nid, node in self.api.items():
            for name, v in node["inputs"].items():
                if isinstance(v, list):
                    self.assertIn(v[0], self.api, f"{nid}.{name} -> {v}")

    def test_widgets_land_on_the_right_inputs(self):
        by_cls = {v["class_type"]: v["inputs"] for v in self.api.values()}
        self.assertEqual(by_cls["LTXVHDRDecodePostprocess"]["exposure"], 7.1)
        self.assertEqual(by_cls["LTXVHDRDecodePostprocess"]["save_exr"], True)
        self.assertEqual(by_cls["LTXVHDRDecodePostprocess"]["output_dir"], "output/old")
        self.assertEqual(by_cls["SaveVideo"]["codec"], "auto")
        self.assertEqual(by_cls["LoadVideo"]["file"], "x.mp4")
        self.assertNotIn("upload", by_cls["LoadVideo"])         # the upload button is UI-only

    def test_a_linked_widget_input_uses_the_link_but_still_consumes_its_value_slot(self):
        empty = next(v for v in self.api.values() if v["class_type"] == "EmptyLTXVLatentVideo")["inputs"]
        self.assertEqual(empty["width"], ["4", 0])              # linked: the 999 widget value is ignored
        self.assertEqual(empty["height"], 32)                   # the NEXT widget value is not shifted onto width
        self.assertEqual(empty["batch_size"], 1)

    def test_patch_sets_plate_exr_dir_and_fps_without_mutating(self):
        before = json.dumps(self.api, sort_keys=True)
        g = recover.patch_hdr_graph(self.api, plate_name="p.mp4", fps=25.0, exr_dir="output/run1", seed=9)
        self.assertEqual(json.dumps(self.api, sort_keys=True), before)
        by_cls = {v["class_type"]: v["inputs"] for v in g.values()}
        self.assertEqual(by_cls["LoadVideo"]["file"], "p.mp4")
        self.assertEqual(by_cls["LTXVHDRDecodePostprocess"]["output_dir"], "output/run1")
        self.assertEqual(by_cls["CreateVideo"]["fps"], 25.0)

    def test_a_graph_without_the_expected_nodes_is_a_clear_error(self):
        g = json.loads(json.dumps(self.api))
        for k in [k for k, v in g.items() if v["class_type"] == "LoadVideo"]:
            del g[k]
        with self.assertRaises(ValueError):
            recover.patch_hdr_graph(g, plate_name="p", fps=24, exr_dir="o")

    def test_a_link_to_a_missing_node_is_an_error(self):
        ui = hdr_like_ui_graph()
        ui["nodes"] = [n for n in ui["nodes"] if n["type"] != "GetVideoComponents"]
        with self.assertRaises(ValueError):
            recover.ui_to_api(ui)


class FetchGraph(unittest.TestCase):
    """RECOVER reads the user's copy of the upstream workflow: nothing of Lightricks' is shipped."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_vendored_upstream_graph_in_the_repo(self):
        root = Path(__file__).resolve().parent.parent
        self.assertFalse((root / "graphs" / "ltx23-hdr-iclora.ui.json").exists())
        shipped = {p.name for p in (root / "graphs").iterdir() if p.is_file()}
        self.assertEqual(shipped, {"ltx25-cleanplate.api.json"})

    def test_missing_copy_gives_exact_instructions(self):
        with self.assertRaises(Refusal) as ctx:
            recover.load_hdr_api_graph(self.d / "nope.json")
        msg = str(ctx.exception)
        self.assertIn(recover.UPSTREAM_GRAPH, msg)
        self.assertIn("github.com/Lightricks/ComfyUI-LTXVideo", msg)
        self.assertIn("fetch-graph", msg)

    def test_local_copy_is_validated_and_copied_unchanged(self):
        src = self.d / "dl.json"
        src.write_text(json.dumps(hdr_like_ui_graph()))
        dest = recover.fetch_graph(str(src), dest=self.d / "out" / "g.json")
        self.assertEqual(dest.read_bytes(), src.read_bytes())
        self.assertIn("SaveVideo", {v["class_type"] for v in recover.load_hdr_api_graph(dest).values()})

    def test_html_or_wrong_json_is_refused(self):
        bad = self.d / "page.html"
        bad.write_text("<html>GitHub</html>")
        with self.assertRaises(Refusal):
            recover.fetch_graph(str(bad), dest=self.d / "g.json")
        other = self.d / "api.json"
        other.write_text(json.dumps({"1": {"class_type": "X", "inputs": {}}}))
        with self.assertRaises(Refusal):
            recover.fetch_graph(str(other), dest=self.d / "g.json")
        self.assertFalse((self.d / "g.json").exists())

    def test_url_source_goes_through_the_injected_opener_only(self):
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        seen = []
        def opener(req, timeout=0):
            seen.append(req.full_url)
            return Resp(json.dumps(hdr_like_ui_graph()).encode())
        dest = recover.fetch_graph("https://example.invalid/raw/g.json", dest=self.d / "g.json", opener=opener)
        self.assertEqual(seen, ["https://example.invalid/raw/g.json"])
        self.assertTrue(dest.exists())


class ExrPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, *names):
        for n in names:
            (self.d / n).write_bytes(b"EXR")

    def test_frames_sort_numerically_and_must_be_contiguous(self):
        self.touch("frame_00010.exr", "frame_00002.exr", "frame_00003.exr")
        with self.assertRaises(Refusal) as ctx:
            recover.list_exr_sequence(self.d)
        self.assertIn("4", str(ctx.exception))
        self.touch(*(f"frame_{i:05d}.exr" for i in range(4, 10)))
        names = [p.name for p in recover.list_exr_sequence(self.d)]
        self.assertEqual(names[0], "frame_00002.exr")
        self.assertEqual(names[-1], "frame_00010.exr")

    def test_hash_named_and_unnumbered_files_are_refused(self):
        self.touch("ab" * 16 + ".exr")
        with self.assertRaises(Refusal):
            recover.list_exr_sequence(self.d)
        for p in self.d.iterdir():
            p.unlink()
        self.touch("beauty.exr")
        with self.assertRaises(Refusal):
            recover.list_exr_sequence(self.d)

    def test_normalize_renames_from_1001(self):
        self.touch("frame_00000.exr", "frame_00001.exr")
        out = recover.normalize_exr_names(self.d, self.d / "out", "shotA")
        self.assertEqual([p.name for p in out], ["shotA_hdr.1001.exr", "shotA_hdr.1002.exr"])

    def test_zip_extract_keeps_only_exr_and_blocks_zip_slip(self):
        z = self.d / "ok.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("frames/f_0001.exr", b"1")
            f.writestr("readme.txt", b"no")
        out = recover.safe_extract_exr_zip(z, self.d / "x")
        self.assertEqual([p.name for p in out], ["f_0001.exr"])
        evil = self.d / "evil.zip"
        with zipfile.ZipFile(evil, "w") as f:
            f.writestr("../escape.exr", b"1")
        with self.assertRaises(Refusal):
            recover.safe_extract_exr_zip(evil, self.d / "y")
        self.assertFalse((self.d / "escape.exr").exists())


class HostedPartnerLane(unittest.TestCase):
    def test_limits(self):
        self.assertEqual(recover.check_hosted_limits(1920, 1080, 181), [])
        self.assertTrue(recover.check_hosted_limits(1920, 1080, 182))
        self.assertTrue(recover.check_hosted_limits(3840, 2160, 42))
        self.assertTrue(recover.check_hosted_limits(7680, 4320, 1))

    def test_result_url_is_read_from_the_nested_key(self):
        self.assertEqual(recover.exr_zip_url({"result": {"exr_frames_url": "https://x/f.zip"}}), "https://x/f.zip")
        with self.assertRaises(Refusal):
            recover.exr_zip_url({"exr_frames_url": "https://x/f.zip"})          # top level is the known trap

    def test_flow_with_a_fake_opener_posts_then_polls_until_completed(self):
        calls = []
        replies = iter([{"id": "job1"}, {"status": "running"}, {"status": "completed", "result": {"exr_frames_url": "u"}}])

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout=0):
            calls.append((req.get_method(), req.full_url, req.headers.get("Authorization")))
            return Resp(json.dumps(next(replies)).encode())

        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"video")
            f.flush()
            res = recover.hosted_hdr(Path(f.name), "KEY", opener=opener, sleep=lambda s: None)
        self.assertEqual(res["status"], "completed")
        self.assertEqual([c[0] for c in calls], ["POST", "GET", "GET"])
        self.assertTrue(all(c[2] == "Bearer KEY" for c in calls))
        self.assertTrue(calls[0][1].endswith("/v2/video-to-video-hdr"))


class SubmitGate(unittest.TestCase):
    def test_no_go_means_no_send_and_no_sdk_import(self):
        with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network!")):
            with self.assertRaises(Refusal):
                submit.submit_graph(Path("g.json"), {}, ["81"], Path(tempfile.gettempdir()) / "pd_x", go=False, env={})

    def test_go_on_cloud_needs_a_key(self):
        with self.assertRaises(Refusal) as ctx:
            submit.require_go(go=True, env={})
        self.assertIn("COMFY_API_KEY", str(ctx.exception))
        self.assertEqual(submit.require_go(go=True, env={"COMFY_API_KEY": "k"}), submit.CLOUD_URL)

    def test_a_local_comfyui_needs_go_but_not_a_key(self):
        self.assertEqual(submit.require_go(go=True, env={"COMFY_BASE_URL": "http://127.0.0.1:8188/"}),
                         "http://127.0.0.1:8188")
        with self.assertRaises(Refusal):
            submit.require_go(go=False, env={"COMFY_BASE_URL": "http://127.0.0.1:8188"})

    def test_a_remote_base_url_still_needs_a_key(self):
        with self.assertRaises(Refusal):
            submit.require_go(go=True, env={"COMFY_BASE_URL": "https://demo.run.comfy.app"})

    def test_missing_sdk_is_a_clear_refusal_not_a_crash(self):
        with mock.patch.dict(sys.modules, {"comfy_sdk": None}):          # makes `from comfy_sdk import Comfy` fail
            with self.assertRaises(submit.SDKMissing) as ctx:
                submit.submit_graph(Path("g.json"), {}, ["81"], Path(tempfile.gettempdir()) / "pd_y", go=True,
                                    transport="sdk", env={"COMFY_API_KEY": "k"})
        self.assertIn("pip install comfy-sdk", str(ctx.exception))
        self.assertIn("--transport http", str(ctx.exception))

    def test_sdk_path_uses_the_documented_calls(self):
        out = Path(tempfile.mkdtemp())
        graph = out / "g.json"
        graph.write_text("{}")
        plate = out / "p.mp4"
        plate.write_bytes(b"x")
        output = mock.Mock()
        output.name = "RAW_00001.mp4"
        job = mock.Mock()
        job.get_outputs.return_value = [output]
        client = mock.Mock()
        client.run.return_value = job
        sdk = mock.Mock(Comfy=mock.Mock(return_value=client))
        with mock.patch.dict(sys.modules, {"comfy_sdk": sdk}):
            res = submit.submit_graph(graph, {("10", "file"): plate}, ["81"], out / "o", go=True, transport="sdk",
                                      env={"COMFY_API_KEY": "k"})
        sdk.Comfy.assert_called_once_with(api_key="k")
        client.workflows.from_file.assert_called_once_with(str(graph))
        client.assets.from_file.assert_called_once_with(str(plate))
        client.workflows.from_file.return_value.set_input.assert_called_once_with(
            "10", "file", client.assets.from_file.return_value)
        job.get_outputs.assert_called_once_with("81")
        output.to_file.assert_called_once_with(str(out / "o" / "RAW_00001.mp4"))
        self.assertEqual(res["transport"], "sdk")

    def test_http_fallback_uploads_posts_polls_and_downloads(self):
        out = Path(tempfile.mkdtemp())
        graph = out / "g.json"
        graph.write_text(json.dumps({"10": {"class_type": "LoadVideo", "inputs": {"file": "old"}}, "extra": {"x": 1}}))
        plate = out / "p.mp4"
        plate.write_bytes(b"x")
        seen = []

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout=0):
            url = req.full_url
            seen.append((req.get_method(), url, req.headers.get("X-api-key")))
            if url.endswith("/api/upload/image"):
                return Resp(json.dumps({"name": "hashed.mp4"}).encode())
            if url.endswith("/api/prompt"):
                sent = json.loads(req.data)
                self.assertEqual(sent["prompt"]["10"]["inputs"]["file"], "hashed.mp4")
                self.assertNotIn("extra", sent["prompt"])
                return Resp(json.dumps({"prompt_id": "pid"}).encode())
            if "/api/history/" in url:
                return Resp(json.dumps({"pid": {"outputs": {"81": {"images": [{"filename": "r.mp4", "type": "output"}]}},
                                                "status": {"completed": True}}}).encode())
            return Resp(b"VIDEO")                                            # /api/view

        res = submit.submit_graph(graph, {("10", "file"): plate}, ["81"], out / "o", go=True, transport="http",
                                  env={"COMFY_API_KEY": "k"}, opener=opener)
        self.assertEqual((out / "o" / "r.mp4").read_bytes(), b"VIDEO")
        self.assertEqual(res["job_id"], "pid")
        self.assertTrue(all(s[2] == "k" for s in seen))


if __name__ == "__main__":
    unittest.main()
