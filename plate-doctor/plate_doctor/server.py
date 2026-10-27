"""The local web UI: stdlib http.server, one HTML page, bound to 127.0.0.1 only.

The server never submits anything to Comfy: the UI's Go button is the dry run (plan + prep + graphs on disk).
A real submit is the CLI with --go. Files reach the browser only through tokens the server itself registered.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import socket
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import core, media, pipeline, recover
from .config import ATTRIBUTION, APP_NAME, VERSION, YEAR
from .core import Refusal

WEB = Path(__file__).resolve().parent.parent / "web"
ERRORS: list[str] = []          # background_errors: anything that failed while nobody was looking


class State:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.tokens: dict[str, Path] = {}

    def register(self, path: Path) -> str:
        path = Path(path).resolve()
        tok = hashlib.sha1(str(path).encode()).hexdigest()[:16]
        self.tokens[tok] = path
        return f"/media/{tok}{path.suffix}"

    def stage(self, src: Path, label: str) -> str:
        """Register a browser-playable copy of src (always a small h264 proxy)."""
        proxy = self.workspace / "proxies" / f"{label}_{hashlib.sha1(str(Path(src).resolve()).encode()).hexdigest()[:8]}.mp4"
        if not proxy.exists():
            media.browser_proxy(Path(src), proxy)
        return self.register(proxy)


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PlateDoctor/" + VERSION

        def log_message(self, fmt, *args):      # quiet
            pass

        # ------------------------------------------------------------------ helpers
        def _json(self, obj, code=200):
            body = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def _file(self, path: Path):
            size = path.stat().st_size
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            rng = self.headers.get("Range")
            start, end, code = 0, size - 1, 200
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else 0
                end = int(b) if b else size - 1
                end = min(end, size - 1)
                code = 206
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        # ------------------------------------------------------------------ routes
        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._file(WEB / "index.html")
            if path == "/api/state":
                return self._json(dict(app=APP_NAME, version=VERSION, year=YEAR, attribution=ATTRIBUTION,
                                       workspace=str(state.workspace), ffmpeg=bool(shutil.which("ffmpeg")),
                                       comfy_key_set=bool(os.environ.get("COMFY_API_KEY")),
                                       ltx_key_set=bool(os.environ.get("LTX_API_KEY"))))
            if path == "/api/selfcheck":
                checks = {"ffmpeg": {"ok": bool(shutil.which("ffmpeg"))},
                          "recipe_wiring": {"ok": _wiring_ok()},
                          "background_errors": {"ok": not ERRORS, "detail": ERRORS[-3:]}}
                return self._json({"ok": all(c["ok"] for c in checks.values()), "checks": checks})
            if path.startswith("/media/"):
                tok = Path(path[7:]).stem
                p = state.tokens.get(tok)
                if not p or not p.exists():
                    return self._json({"error": "unknown media"}, 404)
                return self._file(p)
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            try:
                b = self._body()
                path = self.path
                if path == "/api/demo":
                    info = media.make_demo(state.workspace / "demo")
                    info["before_url"] = state.stage(Path(info["plate"]), "demo_before")
                    info["after_url"] = state.stage(Path(info["truth"]), "demo_truth")
                    return self._json(info)
                if path == "/api/inspect":
                    info = media.probe_media(Path(b["plate"]))
                    m = media.read_matte(Path(b["matte"]), info["width"], info["height"])
                    return self._json(dict(
                        plate={k: str(v) for k, v in info.items()}, refusals=media.check_plate(info),
                        matte_frames=len(m), empty_frames=core.empty_frames(m),
                        coverage=[round(core.coverage(f), 4) for f in m[:200]]))
                if path == "/api/plan":
                    m = pipeline.remove_run(
                        Path(b["plate"]), Path(b["matte"]), location=b.get("location"), empty=b.get("empty") or None,
                        frames=b.get("frames") or None, probe=bool(b.get("probe")), seed=int(b.get("seed", 43)),
                        dilation=int(b.get("dilation", 15)), out=state.workspace / "runs", go=False)
                    m["before_url"] = state.stage(Path(b["plate"]), "before")
                    return self._json(m)
                if path == "/api/stage":
                    return self._json({"url": state.stage(Path(b["path"]), b.get("label", "clip"))})
                if path == "/api/vanish":
                    out = state.workspace / "vanish" / "vanish.mp4"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    media.vanish(Path(b["before"]), Path(b["after"]), out)
                    return self._json({"url": state.register(out), "path": str(out)})
                if path == "/api/recover-plan":
                    m = pipeline.recover_run(Path(b["plate"]), lane=b.get("lane", "graph"),
                                             out=state.workspace / "runs", go=False)
                    return self._json(m)
                self._json({"error": "not found"}, 404)
            except Refusal as exc:
                self._json({"refused": str(exc)}, 422)
            except (KeyError, ValueError, FileNotFoundError) as exc:
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)
            except Exception as exc:        # noqa: BLE001 - surfaced in /api/selfcheck, not swallowed
                ERRORS.append(f"{type(exc).__name__}: {exc}")
                traceback.print_exc()
                self._json({"error": "internal error, see server log"}, 500)

    return Handler


def _wiring_ok() -> bool:
    try:
        core.patch_remove_graph(core.load_remove_recipe(), plate_name="p", matte_name="m", width=640, height=352,
                                length=9, fps=24.0, prompt="x", seed=1, dilation=1, prefix="x")
        return True
    except Exception:
        return False


def pick_port(preferred: int) -> int:
    if preferred:
        return preferred
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(port: int, workspace: Path) -> None:
    state = State(workspace)
    port = pick_port(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    print(f"{APP_NAME} {VERSION} on http://127.0.0.1:{port}  (workspace {state.workspace})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
