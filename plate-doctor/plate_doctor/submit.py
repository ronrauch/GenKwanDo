"""The ONLY module that can reach a network or spend money, and it refuses unless told to.

Gate: nothing is sent unless `go=True` AND (for Comfy Cloud) COMFY_API_KEY is set. Default everywhere else is a dry
run. Transport: the official `comfy_sdk` is the primary path (pip install comfy-sdk, optional); raw HTTP is the
fallback. Both are written from the public docs and are UNTESTED against the network in this repo.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .core import Refusal

CLOUD_URL = "https://cloud.comfy.org"


class SDKMissing(Refusal):
    pass


def base_url(env) -> str:
    return (env.get("COMFY_BASE_URL") or "").strip().rstrip("/") or CLOUD_URL


def is_local(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host in ("127.0.0.1", "localhost", "::1")


def require_go(*, go: bool, env=None) -> str:
    """Raise Refusal unless a real submit is explicitly requested and credentialed. Returns the base URL."""
    env = os.environ if env is None else env
    if not go:
        raise Refusal("dry run: nothing was sent. Pass --go to submit (Comfy Cloud also needs COMFY_API_KEY).")
    url = base_url(env)
    if not is_local(url) and not env.get("COMFY_API_KEY"):
        raise Refusal("--go needs COMFY_API_KEY for Comfy Cloud (or COMFY_BASE_URL=http://127.0.0.1:8188 for a "
                      "local ComfyUI). Nothing was sent.")
    return url


def submit_graph(graph_path: Path, inputs: dict, output_nodes: list[str], out_dir: Path, *, go: bool,
                 transport: str = "sdk", env=None, opener=urllib.request.urlopen) -> dict:
    """Run one API-format graph. `inputs` maps (node id, input name) to a local file that is uploaded and bound.
    Returns {"transport", "job_id", "files": [paths]}."""
    env = os.environ if env is None else env
    url = require_go(go=go, env=env)
    out_dir.mkdir(parents=True, exist_ok=True)
    if transport == "sdk":
        return _via_sdk(graph_path, inputs, output_nodes, out_dir, env, url)
    if transport == "http":
        return _via_http(graph_path, inputs, output_nodes, out_dir, env, url, opener)
    raise Refusal(f"unknown transport {transport!r} (sdk or http)")


def _via_sdk(graph_path, inputs, output_nodes, out_dir, env, url) -> dict:
    try:
        from comfy_sdk import Comfy
    except ImportError as exc:
        raise SDKMissing("the official SDK is not installed. pip install comfy-sdk (Python 3.10+), "
                         "or rerun with --transport http for the raw-HTTP fallback.") from exc
    key = env.get("COMFY_API_KEY")
    client = Comfy(api_key=key) if key else Comfy()          # base URL comes from COMFY_BASE_URL, not an argument
    wf = client.workflows.from_file(str(graph_path))
    for (node, name), path in inputs.items():
        wf.set_input(node, name, client.assets.from_file(str(path)))
    job = client.run(wf)                                     # submits and waits for a terminal state
    job.result()                                             # raises JobFailed with node-level detail
    files = []
    for node in output_nodes:
        for output in job.get_outputs(node):
            target = out_dir / output.name
            output.to_file(str(target))
            files.append(str(target))
    return {"transport": "sdk", "job_id": getattr(job, "id", None), "files": files}


def _headers(env, extra=None) -> dict:
    h = dict(extra or {})
    if env.get("COMFY_API_KEY"):
        h["X-API-Key"] = env["COMFY_API_KEY"]
    return h


def _via_http(graph_path, inputs, output_nodes, out_dir, env, url, opener) -> dict:
    graph = json.loads(Path(graph_path).read_text())
    graph = {k: v for k, v in graph.items() if isinstance(v, dict) and "class_type" in v}
    for (node, name), path in inputs.items():
        graph[node]["inputs"][name] = _upload(Path(path), url, env, opener)
    body = json.dumps({"prompt": graph, "client_id": uuid.uuid4().hex}).encode()
    req = urllib.request.Request(url + "/api/prompt", data=body, method="POST",
                                 headers=_headers(env, {"Content-Type": "application/json"}))
    with opener(req, timeout=120) as r:
        pid = json.loads(r.read()).get("prompt_id")
    if not pid:
        raise Refusal("submit returned no prompt_id")
    hist = None
    for _ in range(3600):                                    # poll /history until the job is recorded
        with opener(urllib.request.Request(f"{url}/api/history/{pid}", headers=_headers(env)), timeout=60) as r:
            data = json.loads(r.read())
        if pid in data and data[pid].get("outputs") is not None and data[pid].get("status", {}).get("completed", True):
            hist = data[pid]
            break
        time.sleep(2)
    if hist is None:
        raise Refusal(f"job {pid} did not finish")
    files = []
    for node in output_nodes:
        for item in _output_items(hist["outputs"].get(node, {})):
            q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                        "type": item.get("type", "output")})
            with opener(urllib.request.Request(f"{url}/api/view?{q}", headers=_headers(env)), timeout=600) as r:
                target = out_dir / item["filename"]
                target.write_bytes(r.read())
                files.append(str(target))
    return {"transport": "http", "job_id": pid, "files": files}


def _output_items(node_out: dict) -> list[dict]:
    return [i for key in ("videos", "images", "gifs") for i in node_out.get(key, [])]


def _upload(path: Path, url: str, env, opener) -> str:
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: video/mp4\r\n\r\n").encode() + path.read_bytes() + \
           f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\ninput\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url + "/api/upload/image", data=body, method="POST",
                                 headers=_headers(env, {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
    with opener(req, timeout=600) as r:
        return json.loads(r.read())["name"]
