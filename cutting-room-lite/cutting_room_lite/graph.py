"""Build the ComfyUI API graph for one H3 window from the scrubbed template.

Every window is its own job so a single window can be re-rolled. Window 0 uses the cover as both the
reference picture and the frame-0 guide. Later windows keep the cover as the reference (identity) but guide
frame 0 with the LAST frame of the previous approved take, which the renderer extracts with ffmpeg
(the same thing the proven graph did in-graph with ImageFromBatch).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .planner import FPS, Window

TEMPLATE_PATH = Path(__file__).parent / "graphs" / "h3_ref2va_window.template.json"
GUIDE_NODE = "20"  # LoadImage for the previous window's last frame (window > 0 only)

REQUIRED_CLASSES = {
    "1": "UNETLoader",
    "6": "LoadImage",
    "7": "LoadAudio",
    "8": "MiniMaxH3ReferenceToVideo",
    "9": "RandomNoise",
    "15": "MiniMaxH3AddGuide",
    "17": "SaveVideo",
}


def load_template() -> dict:
    graph = json.loads(TEMPLATE_PATH.read_text())
    for node_id, cls in REQUIRED_CLASSES.items():
        found = graph.get(node_id, {}).get("class_type")
        if found != cls:
            raise ValueError(f"template node {node_id} should be {cls}, found {found}")
    return graph


def build_window_graph(
    window: Window,
    *,
    cover_name: str,
    audio_name: str,
    prompt: str,
    seed: int,
    project: str = "project",
    guide_name: str | None = None,
    size: int = 1248,
    fps: int = FPS,
) -> dict:
    """Return the API graph for one window.

    cover_name / audio_name / guide_name are the names the files have in ComfyUI's input store.
    guide_name is required for windows after the first.
    """
    if window.index > 0 and not guide_name:
        raise ValueError(f"window {window.index} needs guide_name (last frame of window {window.index - 1})")

    graph = copy.deepcopy(load_template())
    graph["6"]["inputs"]["image"] = cover_name
    graph["7"]["inputs"]["audio"] = audio_name
    node = graph["8"]["inputs"]
    node["prompt"] = prompt
    node["width"] = size
    node["height"] = size
    node["length"] = window.render_frames
    graph["9"]["inputs"]["noise_seed"] = int(seed)
    graph["16"]["inputs"]["fps"] = fps
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project)[:40] or "project"
    graph["17"]["inputs"]["filename_prefix"] = f"cutting-room-lite/{safe}_w{window.index}_s{int(seed)}"

    if window.index > 0:
        graph[GUIDE_NODE] = {
            "class_type": "LoadImage",
            "inputs": {"image": guide_name},
            "_meta": {"title": f"Last frame of window {window.index - 1} (guide)"},
        }
        graph["15"]["inputs"]["image"] = [GUIDE_NODE, 0]
    return graph


def describe(graph: dict) -> dict:
    """A short summary the UI and the dry-run print instead of the whole graph."""
    n8 = graph["8"]["inputs"]
    return {
        "nodes": len(graph),
        "cover": graph["6"]["inputs"]["image"],
        "guide": graph.get(GUIDE_NODE, {}).get("inputs", {}).get("image"),
        "audio": graph["7"]["inputs"]["audio"],
        "frames": n8["length"],
        "size": f"{n8['width']}x{n8['height']}",
        "seed": graph["9"]["inputs"]["noise_seed"],
        "steps": graph["11"]["inputs"]["steps"],
        "sampler": graph["10"]["inputs"]["sampler_name"],
        "unet": graph["1"]["inputs"]["unet_name"],
        "lora": graph["2"]["inputs"]["lora_name"],
        "prefix": graph["17"]["inputs"]["filename_prefix"],
    }
