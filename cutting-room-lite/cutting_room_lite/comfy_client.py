"""Talking to ComfyUI, behind a spend gate.

Nothing in this module touches the network unless the gate is open. The gate opens only when:
  * the caller passed an explicit go flag (`--go` on the CLI and the server), and
  * for the cloud backend, COMFY_API_KEY is set.
A local ComfyUI needs the go flag but no key.

Two transports, same gate:
  sdk   the official Comfy Python SDK (`pip install comfy-sdk`), the documented primary path. Optional extra.
  http  raw HTTP with urllib (stdlib), the fallback when the SDK is not installed.

Both submit paths are written from the public docs and are UNTESTED against the network in this version.
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

CLOUD_URL = "https://cloud.comfy.org"
LOCAL_URL = "http://127.0.0.1:8188"
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv")


class GateError(RuntimeError):
    """The spend gate is closed. The message says why."""


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileInput:
    """A local file to hand to a node input (a LoadImage 'image' or a LoadAudio 'audio')."""
    node_id: str
    input_name: str
    path: str


def gate_reasons(backend: str, go: bool, api_key: str | None) -> list[str]:
    """Why the gate is closed; an empty list means it is open."""
    if backend not in ("cloud", "local"):
        return [f"unknown backend {backend!r} (use cloud or local)"]
    reasons = []
    if not go:
        reasons.append("--go was not given (dry run)")
    if backend == "cloud" and not api_key:
        reasons.append("COMFY_API_KEY is not set")
    return reasons


def require_live(backend: str, go: bool, api_key: str | None) -> None:
    reasons = gate_reasons(backend, go, api_key)
    if reasons:
        raise GateError("spend gate closed: " + "; ".join(reasons))


def sdk_available() -> bool:
    try:
        import comfy_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def base_url(backend: str) -> str:
    env = os.environ.get("COMFY_BASE_URL", "").strip()
    if env:
        return env.rstrip("/")
    return CLOUD_URL if backend == "cloud" else LOCAL_URL


# --- shared helpers ---------------------------------------------------------------------------------

def _multipart(field: str, path: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    name = Path(path).name
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    head = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{name}\"\r\n"
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode()
    tail = (
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n"
    ).encode()
    return head + Path(path).read_bytes() + tail, f"multipart/form-data; boundary={boundary}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _pick_video(outputs: dict) -> dict | None:
    """First video file in a ComfyUI `outputs` object (any node, any key)."""
    for node_out in (outputs or {}).values():
        if not isinstance(node_out, dict):
            continue
        for items in node_out.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and str(item.get("filename", "")).lower().endswith(VIDEO_EXTS):
                    return item
    return None


# --- runners ----------------------------------------------------------------------------------------

class HttpRunner:
    """Raw HTTP fallback (stdlib only)."""

    def __init__(self, backend: str, go: bool, api_key: str | None, poll_s: float = 5.0, timeout_s: float = 1800.0):
        self.backend, self.go, self.api_key = backend, go, api_key
        self.poll_s, self.timeout_s = poll_s, timeout_s
        self.root = base_url(backend)
        self.api = "/api" if backend == "cloud" else ""

    def _open(self, req: urllib.request.Request, opener=None):
        require_live(self.backend, self.go, self.api_key)
        if self.api_key:
            req.add_header("X-API-Key", self.api_key)
        return (opener or urllib.request).open(req, timeout=120)

    def _json(self, path: str, data: dict | None = None) -> dict:
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.root + path, data=body,
                                     headers={"Content-Type": "application/json"} if body else {})
        try:
            with self._open(req) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as err:
            raise RenderError(f"{path}: HTTP {err.code} {err.read().decode()[:300]}") from err

    def upload(self, path: str) -> str:
        """Upload an image or audio file; returns the name ComfyUI knows it by.

        UNPROVEN for audio on Comfy Cloud: the docs describe this endpoint for images.
        """
        body, ctype = _multipart("image", path)
        req = urllib.request.Request(self.root + self.api + "/upload/image", data=body, headers={"Content-Type": ctype})
        try:
            with self._open(req) as resp:
                return json.loads(resp.read().decode())["name"]
        except urllib.error.HTTPError as err:
            raise RenderError(f"upload {Path(path).name}: HTTP {err.code} {err.read().decode()[:300]}") from err

    def run_window(self, graph: dict, inputs: list[FileInput], out_path: str, graph_path: str | None = None) -> str:
        require_live(self.backend, self.go, self.api_key)
        for fi in inputs:
            graph[fi.node_id]["inputs"][fi.input_name] = self.upload(fi.path)
        resp = self._json(self.api + "/prompt", {"prompt": graph})
        if resp.get("node_errors"):
            raise RenderError(f"node errors: {json.dumps(resp['node_errors'])[:400]}")
        prompt_id = resp["prompt_id"]
        outputs = self._wait(prompt_id)
        video = _pick_video(outputs)
        if not video:
            raise RenderError(f"job {prompt_id} finished with no video output")
        self._download(video, out_path)
        return prompt_id

    def _wait(self, prompt_id: str) -> dict:
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            if self.backend == "cloud":
                st = self._json(f"/api/job/{prompt_id}/status").get("status")
                if st == "completed":
                    return self._json(f"/api/jobs/{prompt_id}").get("outputs", {})
                if st in ("error", "cancelled"):
                    raise RenderError(f"job {prompt_id} ended as {st}")
            else:
                hist = self._json(f"/history/{prompt_id}").get(prompt_id)
                if hist and hist.get("outputs"):
                    return hist["outputs"]
            time.sleep(self.poll_s)
        raise RenderError(f"job {prompt_id} did not finish within {self.timeout_s:.0f} s")

    def _download(self, item: dict, out_path: str) -> None:
        q = urllib.parse.urlencode({
            "filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output"),
        })
        url = f"{self.root}{self.api}/view?{q}"
        req = urllib.request.Request(url)
        try:
            resp = self._open(req, urllib.request.build_opener(_NoRedirect))
        except urllib.error.HTTPError as err:
            if err.code in (301, 302, 303, 307, 308) and err.headers.get("Location"):
                # signed storage URL: fetch it WITHOUT our API key
                resp = urllib.request.urlopen(urllib.request.Request(err.headers["Location"]), timeout=300)
            else:
                raise RenderError(f"download: HTTP {err.code}") from err
        with resp, open(out_path, "wb") as fh:
            while chunk := resp.read(1 << 20):
                fh.write(chunk)


class SdkRunner:
    """The official Comfy Python SDK path (`pip install comfy-sdk`). Documented primary route; UNTESTED here."""

    def __init__(self, backend: str, go: bool, api_key: str | None):
        self.backend, self.go, self.api_key = backend, go, api_key

    def run_window(self, graph: dict, inputs: list[FileInput], out_path: str, graph_path: str | None = None) -> str:
        require_live(self.backend, self.go, self.api_key)
        from comfy_sdk import Comfy  # optional dependency, imported only when the gate is open

        if not graph_path:
            raise RenderError("the SDK path needs the graph on disk (graph_path)")
        Path(graph_path).write_text(json.dumps(graph, indent=1))
        # base URL comes from COMFY_BASE_URL (unset = Comfy Cloud); a local ComfyUI needs no key
        client = Comfy(api_key=self.api_key) if self.api_key else Comfy()
        wf = client.workflows.from_file(graph_path)
        for fi in inputs:
            wf.set_input(fi.node_id, fi.input_name, client.assets.from_file(fi.path))
        job = client.run(wf)  # submits and waits for a terminal state; raises JobFailed on failure
        outputs = job.get_outputs("17")  # SaveVideo node in the template
        if not outputs:
            raise RenderError("job finished with no output on the SaveVideo node")
        outputs[0].to_file(out_path)
        return str(getattr(outputs[0], "job_id", "") or "")


def get_runner(transport: str, backend: str, go: bool, api_key: str | None):
    """Open the gate (or raise GateError) and return a runner. transport: sdk | http | auto."""
    require_live(backend, go, api_key)
    if transport == "auto":
        transport = "sdk" if sdk_available() else "http"
    if transport == "sdk":
        if not sdk_available():
            raise GateError("transport sdk requested but comfy-sdk is not installed (pip install comfy-sdk)")
        return SdkRunner(backend, go, api_key)
    if transport == "http":
        return HttpRunner(backend, go, api_key)
    raise GateError(f"unknown transport {transport!r} (use sdk, http or auto)")
