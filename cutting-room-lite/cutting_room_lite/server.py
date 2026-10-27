"""The local web app: stdlib http.server serving one page and a small JSON API. Binds to 127.0.0.1 only."""
from __future__ import annotations

import json
import mimetypes
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import ATTRIBUTION, VERSION, YEAR, media
from .comfy_client import GateError, gate_reasons, get_runner
from .players import LANE_STATUS, ROLE_STEM, ROLES, STEMS
from .project import Project, ProjectError
from .prompts import COVER_LABELS

WEB = Path(__file__).parent / "web"
MAX_UPLOAD = 300 * 1024 * 1024
SERVED_DIRS = ("media", "takes", "out")


class App:
    """Everything the handler needs: the project, the gate settings and a lock."""

    def __init__(self, root, go=False, backend="cloud", transport="auto", api_key=None):
        self.project = Project(root)
        self.go, self.backend, self.transport, self.api_key = go, backend, transport, api_key
        self.lock = threading.RLock()
        self.busy: str | None = None

    @property
    def live(self) -> bool:
        return not gate_reasons(self.backend, self.go, self.api_key)

    def runner(self):
        """A runner when the gate is open, else None (dry run). Raises GateError for a bad transport."""
        if not self.live:
            return None
        return get_runner(self.transport, self.backend, self.go, self.api_key)

    def about(self) -> dict:
        return {
            "version": VERSION, "year": YEAR, "attribution": ATTRIBUTION,
            "live": self.live, "backend": self.backend, "transport": self.transport,
            "gate": gate_reasons(self.backend, self.go, self.api_key),
            "cover_types": COVER_LABELS, "stems": list(STEMS), "lanes": LANE_STATUS,
            "roles": list(ROLES), "role_stem": ROLE_STEM,
        }


def make_server(root, host="127.0.0.1", port=0, **kw) -> ThreadingHTTPServer:
    app = App(root, **kw)

    class Handler(BaseHTTPRequestHandler):
        server_version = "CuttingRoomLite/" + VERSION

        def log_message(self, fmt, *args):  # quiet
            pass

        # ---- plumbing ----
        def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode())

        def _err(self, msg: str, code=400):
            self._json({"error": msg}, code)

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD:
                raise ProjectError("upload too large")
            return self.rfile.read(n) if n else b""

        def _payload(self) -> dict:
            raw = self._body()
            return json.loads(raw.decode() or "{}")

        def _file(self, path: Path):
            if not path.is_file():
                return self._err("not found", 404)
            data = path.read_bytes()
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            rng = self.headers.get("Range")
            m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
            if m and (m.group(1) or m.group(2)):
                size = len(data)
                a = int(m.group(1)) if m.group(1) else max(size - int(m.group(2)), 0)
                b = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
                b = min(b, size - 1)
                return self._send(206, data[a:b + 1], ctype,
                                  {"Content-Range": f"bytes {a}-{b}/{size}", "Accept-Ranges": "bytes"})
            self._send(200, data, ctype, {"Accept-Ranges": "bytes"})

        # ---- GET ----
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query)
            p = url.path
            try:
                if p in ("/", "/index.html"):
                    return self._file(WEB / "index.html")
                if p.startswith("/assets/"):
                    return self._file(WEB / "assets" / Path(p).name)
                if p == "/api/about":
                    return self._json(app.about())
                if p == "/api/project":
                    return self._json(app.project.public())
                if p == "/api/wave":
                    song = app.project.state["song"]
                    if not song:
                        return self._err("no song yet")
                    return self._json({"peaks": media.wave_peaks(str(app.project.path(song))),
                                       "duration": app.project.state["song_duration"]})
                if p == "/api/graph":
                    k, pid, take = int(q["w"][0]), q["p"][0], q.get("take", [None])[0]
                    track = app.project.state["windows"][k]["tracks"][pid]
                    t = next((t for t in track["takes"] if t["id"] == take), None) if take else None
                    if t and t.get("graph"):
                        return self._file(app.project.path(t["graph"]))
                    return self._json(app.project.build_graph(k, pid, len(track["takes"]) + 1))
                if p.startswith("/media/"):
                    rel = Path(urllib.parse.unquote(p[len("/media/"):]))
                    if rel.parts and rel.parts[0] in SERVED_DIRS and ".." not in rel.parts:
                        return self._file(app.project.root / rel)
                return self._err("not found", 404)
            except (ProjectError, KeyError, IndexError, ValueError) as exc:
                self._err(str(exc))

        # ---- POST ----
        def do_POST(self):
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query)
            p = url.path
            try:
                with app.lock:
                    return self._post(p, q)
            except GateError as exc:
                self._err(str(exc), 403)
            except media.MediaError as exc:
                self._err(f"ffmpeg: {exc}", 500)
            except (ProjectError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
                self._err(str(exc))

        def _post(self, p: str, q: dict):
            pr = app.project
            if p == "/api/upload":
                kind = q.get("kind", [""])[0]
                name = Path(q.get("name", ["upload"])[0]).name
                up = pr.root / "uploads"
                up.mkdir(exist_ok=True)
                tmp = up / name
                tmp.write_bytes(self._body())
                if kind == "cover":
                    pr.set_cover(tmp)
                elif kind == "song":
                    pr.set_song(tmp)
                elif kind in ("performer", "matte"):
                    pr.set_performer_image(q.get("id", [""])[0], tmp, matte=(kind == "matte"))
                else:
                    return self._err("kind must be cover, song, performer or matte")
                return self._json(pr.public())
            payload = self._payload()
            if p == "/api/config":
                pr.configure(**{k: payload.get(k) for k in (
                    "name", "cover_type", "has_vocals", "style", "extra", "window_s",
                    "slice_start", "slice_length", "performers") if k in payload})
                return self._json(pr.public())
            if p == "/api/plan":
                wins = pr.plan()
                return self._json({"windows": wins, "count": len(wins)})
            if p == "/api/render":
                k, pid = int(payload["w"]), str(payload["p"])
                runner = app.runner()
                take = pr.render(k, pid, runner)
                return self._json({"take": take, "dry_run": runner is None})
            if p == "/api/approve":
                pr.approve(int(payload["w"]), str(payload["p"]), str(payload["take"]))
                return self._json(pr.public())
            if p == "/api/placeholder":
                if app.live:
                    return self._err("placeholder takes are for dry-run testing only", 403)
                return self._json({"take": pr.add_placeholder_take(int(payload["w"]), str(payload["p"]),
                                                                    payload.get("color"))})
            if p == "/api/assemble":
                return self._json(pr.assemble())
            return self._err("not found", 404)

    return ThreadingHTTPServer((host, port), Handler)
