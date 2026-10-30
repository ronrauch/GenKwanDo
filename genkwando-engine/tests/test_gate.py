import json
import sys
import types

import pytest

from genkwando_engine import comfy_client as C
from genkwando_engine.comfy_client import FileInput, GateError


def test_gate_reasons():
    assert C.gate_reasons("cloud", False, None) == ["--go was not given (dry run)", "COMFY_API_KEY is not set"]
    assert C.gate_reasons("cloud", True, None) == ["COMFY_API_KEY is not set"]
    assert C.gate_reasons("cloud", False, "k") == ["--go was not given (dry run)"]
    assert C.gate_reasons("cloud", True, "k") == []
    assert C.gate_reasons("local", True, None) == []  # a local ComfyUI needs --go but no key
    assert C.gate_reasons("moon", True, "k")


@pytest.mark.parametrize("go,key", [(False, None), (False, "k"), (True, None)])
def test_cloud_runner_is_refused_unless_go_and_key(go, key):
    with pytest.raises(GateError):
        C.get_runner("http", "cloud", go, key)


def test_runners_refuse_to_run_even_if_built_directly():
    inputs = [FileInput("6", "image", "x.png")]
    with pytest.raises(GateError):
        C.HttpRunner("cloud", False, "k").run_window({}, inputs, "out.mp4")
    with pytest.raises(GateError):
        C.SdkRunner("cloud", True, None).run_window({}, inputs, "out.mp4", "g.json")


def test_sdk_transport_without_the_sdk_is_a_clear_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "comfy_sdk", None)  # makes `import comfy_sdk` fail
    assert not C.sdk_available()
    with pytest.raises(GateError, match="comfy-sdk"):
        C.get_runner("sdk", "cloud", True, "k")
    assert isinstance(C.get_runner("auto", "cloud", True, "k"), C.HttpRunner)  # auto falls back to http


def test_auto_prefers_the_sdk_when_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "comfy_sdk", types.ModuleType("comfy_sdk"))
    assert isinstance(C.get_runner("auto", "cloud", True, "k"), C.SdkRunner)


def test_http_orchestration_with_the_network_stubbed(monkeypatch, tmp_path):
    """Upload -> patch graph -> submit -> wait -> download, with every network call replaced."""
    r = C.HttpRunner("local", True, None)
    sent = {}
    monkeypatch.setattr(r, "upload", lambda p: "uploaded_" + p.split("/")[-1])
    monkeypatch.setattr(r, "_json", lambda path, data=None: sent.update(path=path, graph=data["prompt"]) or {"prompt_id": "abc"})
    monkeypatch.setattr(r, "_wait", lambda pid: {"17": {"images": [{"filename": "a.mp4", "subfolder": "", "type": "output"}]}})
    got = {}
    monkeypatch.setattr(r, "_download", lambda item, out: got.update(item=item, out=out))
    graph = {"6": {"inputs": {"image": "x"}}, "7": {"inputs": {"audio": "y"}}}
    pid = r.run_window(graph, [FileInput("6", "image", "/tmp/cover.png"), FileInput("7", "audio", "/tmp/c.wav")], str(tmp_path / "o.mp4"))
    assert pid == "abc" and sent["path"] == "/prompt"
    assert sent["graph"]["6"]["inputs"]["image"] == "uploaded_cover.png"
    assert sent["graph"]["7"]["inputs"]["audio"] == "uploaded_c.wav"
    assert got["item"]["filename"] == "a.mp4"


def test_cloud_paths_use_the_api_prefix():
    assert C.HttpRunner("cloud", True, "k").api == "/api"
    assert C.HttpRunner("local", True, None).api == ""


def test_pick_video_finds_a_video_in_any_node_output():
    outs = {"3": {"images": [{"filename": "a.png"}]}, "17": {"images": [{"filename": "v.mp4"}], "animated": [True]}}
    assert C._pick_video(outs)["filename"] == "v.mp4"
    assert C._pick_video({"3": {"images": [{"filename": "a.png"}]}}) is None


def test_sdk_orchestration_with_a_fake_sdk(monkeypatch, tmp_path):
    """Checks our calls against the documented SDK surface (client.workflows / assets / run / get_outputs)."""
    calls = []

    class Out:
        job_id = "j1"

        def to_file(self, path):
            calls.append(("to_file", path))

    class Job:
        def get_outputs(self, node):
            calls.append(("get_outputs", node))
            return [Out()]

    class WF:
        def set_input(self, node, name, asset):
            calls.append(("set_input", node, name, asset))

    class Client:
        def __init__(self, api_key=None):
            calls.append(("init", api_key))
            self.workflows = types.SimpleNamespace(from_file=lambda p: calls.append(("from_file", p)) or WF())
            self.assets = types.SimpleNamespace(from_file=lambda p: "asset:" + p)

        def run(self, wf):
            calls.append(("run",))
            return Job()

    fake = types.ModuleType("comfy_sdk")
    fake.Comfy = Client
    monkeypatch.setitem(sys.modules, "comfy_sdk", fake)
    gp = tmp_path / "g.json"
    pid = C.SdkRunner("cloud", True, "key").run_window({"1": {}}, [FileInput("6", "image", "c.png")], str(tmp_path / "o.mp4"), str(gp))
    assert pid == "j1" and json.loads(gp.read_text()) == {"1": {}}
    assert ("init", "key") in calls and ("set_input", "6", "image", "asset:c.png") in calls
    assert ("get_outputs", "17") in calls and ("to_file", str(tmp_path / "o.mp4")) in calls
