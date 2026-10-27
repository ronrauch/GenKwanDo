"""CLI gating, the RECOVER run, the attribution rule, and the open-source scrub. No network, no spend."""
import ast
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plate_doctor import cli, config, media, pipeline  # noqa: E402
from plate_doctor import recover as recover_mod  # noqa: E402
from plate_doctor.core import Refusal  # noqa: E402
from tests.fixtures import hdr_like_ui_graph  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class CliGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.demo = media.make_demo(cls.dir / "demo")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_remove_without_go_is_a_dry_run_that_never_touches_the_network(self):
        with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network!")), \
             mock.patch.dict(sys.modules, {"comfy_sdk": None}):          # importing the SDK would fail the test
            code, out, err = run_cli("remove", self.demo["plate"], self.demo["matte"], "--prompt-location",
                                     "a plain room", "--probe", "--out", str(self.dir / "r1"))
        self.assertEqual(code, 0, err)
        self.assertIn("DRY RUN (nothing sent)", out)
        self.assertIn("1 window(s)", out)
        self.assertIn("PLACEHOLDER", out)

    def test_go_without_credentials_is_refused_before_anything_is_sent(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("COMFY_")}
        with mock.patch.dict("os.environ", env, clear=True), \
             mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network!")):
            code, out, err = run_cli("remove", self.demo["plate"], self.demo["matte"], "--prompt-location", "x",
                                     "--probe", "--go", "--out", str(self.dir / "r2"))
        self.assertEqual(code, 3)
        self.assertIn("COMFY_API_KEY", err)

    def test_recover_graph_lane_dry_run_writes_the_api_graph(self):
        fixture = self.dir / "hdr_fixture.json"
        fixture.write_text(json.dumps(hdr_like_ui_graph()))
        code, out, err = run_cli("recover", self.demo["plate"], "--graph", str(fixture), "--out", str(self.dir / "r3"))
        self.assertEqual(code, 0, err)
        gp = next((self.dir / "r3").rglob("hdr_graph.api.json"))
        g = json.loads(gp.read_text())
        loads = [v for v in g.values() if v["class_type"] == "LoadVideo"]
        self.assertEqual(loads[0]["inputs"]["file"], "demo_plate.mp4")

    def test_recover_without_a_fetched_graph_says_how_to_get_it(self):
        code, out, err = run_cli("recover", self.demo["plate"], "--graph", str(self.dir / "absent.json"),
                                 "--out", str(self.dir / "r3b"))
        self.assertEqual(code, 3)
        self.assertIn("fetch-graph", err)

    def test_fetch_graph_command_without_a_source_prints_the_manual_step(self):
        code, out, err = run_cli("fetch-graph")
        self.assertEqual(code, 2)
        self.assertIn(recover_mod.UPSTREAM_GRAPH, out)

    def test_hosted_lane_is_a_partner_service_and_needs_three_things(self):
        m = pipeline.recover_run(Path(self.demo["plate"]), lane="ltx-api", out=self.dir / "r4")
        self.assertTrue(m["partner_service"])
        self.assertIn("not open weights", m["lane_note"])
        with self.assertRaises(Refusal):                                   # --go without the partner flag
            pipeline.recover_run(Path(self.demo["plate"]), lane="ltx-api", out=self.dir / "r5", go=True, env={})
        with self.assertRaises(Refusal):                                   # flag but no key
            pipeline.recover_run(Path(self.demo["plate"]), lane="ltx-api", out=self.dir / "r6", go=True,
                                 partner_ok=True, env={})
        called = []
        m = pipeline.recover_run(Path(self.demo["plate"]), lane="ltx-api", out=self.dir / "r7", go=True,
                                 partner_ok=True, env={"LTX_API_KEY": "k"},
                                 hosted_fn=lambda v, k: called.append(k) or
                                 {"status": "completed", "result": {"exr_frames_url": "https://x/z.zip"}})
        self.assertEqual(called, ["k"])
        self.assertEqual(m["hosted_result"]["exr_frames_url"], "https://x/z.zip")

    def test_remove_with_go_submits_each_window_through_the_gate(self):
        calls = []
        env = {"COMFY_API_KEY": "k"}
        pipeline.remove_run(Path(self.demo["plate"]), Path(self.demo["matte"]), location="a room", probe=True,
                            go=True, env=env, out=self.dir / "r8",
                            submit_fn=lambda g, ins, outs, od, **kw: calls.append((sorted(ins), outs, kw["go"])) or
                            {"transport": "fake", "files": []})
        self.assertEqual(calls, [([("10", "file"), ("20", "file")], ["81", "92"], True)])

    def test_about_and_version(self):
        code, out, _ = run_cli("--about")
        self.assertEqual(code, 0)
        self.assertIn(config.ATTRIBUTION, out)


class AttributionRule(unittest.TestCase):
    """Ron decides the credit line at ship: it is ONE constant, and nothing else may hard-code a credit."""

    def test_the_credit_lives_in_one_constant_and_is_a_todo(self):
        self.assertTrue(config.ATTRIBUTION.startswith("TODO"))

    def test_no_file_hard_codes_a_builder_credit(self):
        banned = re.compile(r"built by (the )?secret lab|built by ron|ronrauch\.com", re.I)
        for p in self._files():
            self.assertIsNone(banned.search(p.read_text(errors="ignore")), f"{p} hard-codes a credit")

    def test_readme_and_license_carry_the_marked_placeholder(self):
        for name in ("README.md", "LICENSE"):
            self.assertIn("TODO: credit line, decided at ship", (ROOT / name).read_text(), name)

    def test_the_credit_constant_is_read_by_the_about_surfaces(self):
        self.assertIn("ATTRIBUTION", (ROOT / "plate_doctor" / "server.py").read_text())
        self.assertIn("ATTRIBUTION", (ROOT / "plate_doctor" / "pipeline.py").read_text())
        self.assertIn("about_text", (ROOT / "plate_doctor" / "cli.py").read_text())

    @staticmethod
    def _files():
        return [p for p in ROOT.rglob("*") if p.is_file() and "workspace" not in p.parts and "__pycache__" not in p.parts
                and p.suffix in {".py", ".md", ".json", ".html", ".txt"} and p.name != "test_cli_repo.py"]


class LicenceText(unittest.TestCase):
    """The LTX models and Lightricks' workflows are under the LTX-2 Community License, never Apache."""
    WRONG = "apa" + "che"                                  # built up so this file does not trip its own scan

    def test_no_file_claims_the_wrong_licence(self):
        for p in AttributionRule._files():
            self.assertNotIn(self.WRONG, p.read_text(errors="ignore").lower(), f"{p.name} mentions {self.WRONG}")

    def test_readme_license_and_models_doc_point_at_the_ltx_licence_without_summarizing_it(self):
        for name in ("README.md", "LICENSE", "docs/MODELS.md"):
            text = (ROOT / name).read_text()
            self.assertIn("LTX-2 Community License Agreement", text, name)
            self.assertIn("github.com/Lightricks/ComfyUI-LTXVideo", text, name)

    def test_the_recipe_provenance_says_it_is_our_own(self):
        g = json.loads((ROOT / "graphs" / "ltx25-cleanplate.api.json").read_text())
        prov = g["extra"]["plate_doctor"]["provenance"]
        self.assertIn("Original Secret Lab recipe", prov)
        self.assertIn("not a vendor example", prov)


class OpenSourceScrub(unittest.TestCase):
    """No personal paths, no private contacts, no show or project names anywhere in the repo."""
    BAD = re.compile(r"/Users/|ronrauch|rauch123|hboprod|Dr\.? ?Evil|villain|\bDSL\b|DTF|B-Watch|BWATCH|LucidLink|"
                     r"secret-lab-studios|Superbean", re.I)

    def test_nothing_private_ships(self):
        for p in ROOT.rglob("*"):
            if not p.is_file() or "workspace" in p.parts or "__pycache__" in p.parts or p.name == "test_cli_repo.py":
                continue
            if p.suffix in {".py", ".md", ".json", ".html", ".txt"} or p.name == "LICENSE":
                hit = self.BAD.search(p.read_text(errors="ignore"))
                self.assertIsNone(hit, f"{p.relative_to(ROOT)} contains {hit.group(0) if hit else ''!r}")

    def test_only_the_stdlib_is_required(self):
        imported = set()
        for p in (ROOT / "plate_doctor").glob("*.py"):
            for node in ast.walk(ast.parse(p.read_text())):
                if isinstance(node, ast.Import):
                    imported |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported.add(node.module.split(".")[0])
        third_party = imported - set(sys.stdlib_module_names) - {"plate_doctor"}
        self.assertLessEqual(third_party, {"numpy", "comfy_sdk"},
                             f"unexpected third-party imports: {third_party - {'numpy', 'comfy_sdk'}}")


if __name__ == "__main__":
    unittest.main()
