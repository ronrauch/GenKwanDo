import json
import threading
import urllib.error
import urllib.request

import pytest

from genkwando_engine import ATTRIBUTION, about, cli
from genkwando_engine.server import make_server
from conftest import needs_ffmpeg

REAL_OPEN = urllib.request.OpenerDirector.open  # conftest blocks the network; the local app server is not the network


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", REAL_OPEN)
    srv = make_server(tmp_path / "p", port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base
    srv.shutdown()


def call(base, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET",
                                 headers={} if raw is not None else {"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback only, never a proxy
    try:
        with opener.open(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_page_and_about(served):
    code, html = call(served, "/")
    assert code == 200 and b"Pick the cover" in html and b"EXAMPLE OUTPUT SLOT" in html and b"Go" in html
    about_ = json.loads(call(served, "/api/about")[1])
    assert about_["live"] is False and about_["attribution"] == ATTRIBUTION
    assert any("--go" in g for g in about_["gate"])


def test_the_media_route_cannot_leave_the_project(served):
    for p in ("/media/../project.json", "/media/%2e%2e/project.json", "/media/uploads/../../x", "/media/project.json"):
        assert call(served, p)[0] in (400, 404)


@needs_ffmpeg
def test_make_yours_flow_over_http_dry_run(served, assets):
    cover, song = (assets / "cover.png").read_bytes(), (assets / "song.wav").read_bytes()
    assert call(served, "/api/upload?kind=cover&name=c.png", raw=cover)[0] == 200
    assert call(served, "/api/upload?kind=song&name=s.wav", raw=song)[0] == 200
    peaks = json.loads(call(served, "/api/wave")[1])
    assert len(peaks["peaks"]) > 100 and peaks["duration"] == pytest.approx(40, abs=0.1)
    plan = json.loads(call(served, "/api/plan", {})[1])
    assert plan["count"] == 3
    code, body = call(served, "/api/render", {"w": 0, "p": "cover"})
    out = json.loads(body)
    assert code == 200 and out["dry_run"] is True and out["take"]["state"] == "dry-run"
    graph = json.loads(call(served, "/api/graph?w=0&p=cover&take=t001")[1])
    assert graph["8"]["class_type"] == "MiniMaxH3ReferenceToVideo" and graph["8"]["inputs"]["length"] == 240
    code, body = call(served, "/api/placeholder", {"w": 0, "p": "cover"})
    assert code == 200
    proj = json.loads(call(served, "/api/approve", {"w": 0, "p": "cover", "take": "t002"})[1])
    assert proj["windows"][0]["tracks"]["cover"]["approved"] == "t002"
    code, body = call(served, "/api/assemble", {})
    assert code == 400 and b"no approved take" in body


@needs_ffmpeg
def test_layers_over_http(served, assets):
    call(served, "/api/upload?kind=cover&name=c.png", raw=(assets / "cover.png").read_bytes())
    code, body = call(served, "/api/config", {"performers": [{"id": "singer", "role": "singer", "x": 0, "y": 0, "w": 600}]})
    assert code == 200
    code, body = call(served, "/api/upload?kind=performer&id=singer&name=p.png", raw=(assets / "cover.png").read_bytes())
    assert code == 200 and json.loads(body)["performers"][0]["image"] == "media/performers/singer.png"
    assert call(served, "/api/config", {"performers": [{"id": "d", "role": "drums"}]})[0] == 400  # no verb


def test_bad_requests_are_400_not_crashes(served):
    assert call(served, "/api/upload?kind=nope&name=x", raw=b"x")[0] == 400
    assert call(served, "/api/render", {"w": 0, "p": "cover"})[0] == 400  # nothing planned yet
    assert call(served, "/api/nothing", {})[0] == 404


def test_the_server_stays_dry_with_go_but_no_key(tmp_path, monkeypatch):
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", REAL_OPEN)
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    srv = make_server(tmp_path / "p", port=0, go=True, backend="cloud", api_key=None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        a = json.loads(call(f"http://127.0.0.1:{srv.server_address[1]}", "/api/about")[1])
        assert a["live"] is False and any("COMFY_API_KEY" in g for g in a["gate"])
    finally:
        srv.shutdown()


def test_cli_about_and_plan(capsys):
    assert cli.main(["--about"]) == 0
    assert ATTRIBUTION in capsys.readouterr().out and ATTRIBUTION in about()
    assert cli.main(["plan", "--length", "30"]) == 0
    assert "3 windows" in capsys.readouterr().out


@needs_ffmpeg
def test_cli_render_is_a_dry_run_by_default_and_prints_the_plan_first(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    root = str(tmp_path / "p")
    assert cli.main(["synthetic", "--root", root]) == 0
    capsys.readouterr()
    assert cli.main(["render", "--root", root]) == 0
    out = capsys.readouterr().out
    assert out.index("DRY RUN") < out.index("plan: 3 windows x 2 performer(s)") < out.index("singer w0: t001 dry-run")
    assert "dry run complete" in out


@needs_ffmpeg
def test_cli_go_without_a_key_stays_dry(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    root = str(tmp_path / "p")
    cli.main(["synthetic", "--root", root])
    capsys.readouterr()
    assert cli.main(["render", "--root", root, "--go", "--window", "0", "--performer", "singer"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "COMFY_API_KEY is not set" in out and "drummer" not in out.split("plan:")[1].split("singer w0")[1]


@needs_ffmpeg
def test_drummer_test_prepares_one_window_and_stays_dry(tmp_path, assets, capsys, monkeypatch):
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    root = str(tmp_path / "d")
    assert cli.main(["drummer-test", "--root", root, "--cover", str(assets / "cover.png"),
                     "--song", str(assets / "song.wav"), "--bpm", "120"]) == 0
    out = capsys.readouterr().out
    assert "1 windows x 1 performer(s)" in out and "dry-run" in out and "no video" in out
