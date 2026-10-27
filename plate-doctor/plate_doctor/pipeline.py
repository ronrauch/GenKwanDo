"""The two runs. Each is a dry run unless `go` is true, and a dry run still does all the local work:
plan, prep (cut the window plates, window mattes, write the graphs), so you can inspect exactly what would be sent.
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
from pathlib import Path

from . import core, media, recover, submit
from .config import ATTRIBUTION, HDR_RECIPE_NAME, RECIPE_NAME, VERSION
from .core import Refusal


def next_run_dir(base: Path, stem: str) -> Path:
    v = 1
    while (base / f"{stem}_v{v:03d}").exists():
        v += 1
    return base / f"{stem}_v{v:03d}"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save(rd: Path, manifest: dict) -> None:
    (rd / "run.json").write_text(json.dumps(manifest, indent=1, default=str))


def plan_remove(plate: Path, matte: Path, *, frames: str | None = None, probe: bool = False,
                probe_at: int | None = None, silent_audio: bool = False) -> dict:
    """Everything decided before any file is cut: plate facts, refusals, frame range, windows. Raises Refusal."""
    plate, matte = Path(plate), Path(matte)
    info = media.probe_media(plate)
    problems = media.check_plate(info, silent_audio)
    if problems:
        raise Refusal("REFUSED: " + " | ".join(problems))
    W, H, fps, N = info["width"], info["height"], info["fps"], info["frames"]
    first, last = core.parse_frames(frames) if frames else (0, N - 1)
    matte_frames = media.read_matte(matte, W, H)
    if len(matte_frames) == N:
        offset = 0
    elif len(matte_frames) == last - first + 1:
        offset = first
    else:
        raise Refusal(f"REFUSED: matte has {len(matte_frames)} frames; it must match the plate ({N}) or the "
                      f"selection ({last - first + 1})")
    if probe:
        first, last = core.probe_range(first, last, at=probe_at)
    core.require_matte_ok(matte_frames[first - offset: last - offset + 1], first, last)
    windows = (core.plan_windows(first, last, N, max_len=core.next_8n1(last - first + 1)) if probe
               else core.plan_windows(first, last, N))
    for w in windows:
        lo, hi = w["src_start"] - offset, w["src_end"] - offset
        if lo < 0 or hi >= len(matte_frames):
            raise Refusal(f"REFUSED: window {w['src_start']}-{w['src_end']} needs matte frames the matte does not "
                          "have; give a full-length matte or a selection whose 8n+1 window fits it")
    return dict(info=info, width=W, height=H, fps=fps, plate_frames=N, first=first, last=last, windows=windows,
                matte_frames=matte_frames, matte_offset=offset, probe=probe)


def remove_run(plate: Path, matte: Path, *, location: str | None = None, prompt: str | None = None,
               empty: str | None = None, frames: str | None = None, probe: bool = False, probe_at: int | None = None,
               seed: int = 43, dilation: int = 15, shot: str | None = None, out: Path, silent_audio: bool = False,
               go: bool = False, transport: str = "sdk", env=None, submit_fn=submit.submit_graph) -> dict:
    """REMOVE: take what is under a white matte out of the plate and rebuild the set behind it."""
    if not (prompt or location):
        raise Refusal("describe the EMPTY set with --prompt-location (never write 'remove the person')")
    p = plan_remove(plate, matte, frames=frames, probe=probe, probe_at=probe_at, silent_audio=silent_audio)
    text = prompt or core.build_prompt(location, empty)
    shot = shot or re.sub(r"[^A-Za-z0-9_-]+", "_", Path(plate).stem)
    stem = f"{shot}_f{p['first']:04d}-{p['last']:04d}{'_PROBE' if probe else ''}{'' if go else '_DRYRUN'}"
    rd = next_run_dir(Path(out), stem)
    (rd / "inputs").mkdir(parents=True)
    recipe = core.load_remove_recipe()
    manifest = dict(app="plate-doctor", version=VERSION, recipe=RECIPE_NAME, attribution=ATTRIBUTION, created=_now(),
                    dry_run=not go, plate=str(plate), matte=str(matte), first=p["first"], last=p["last"],
                    width=p["width"], height=p["height"], fps=str(p["fps"]), prompt=text, seed=seed,
                    dilation=dilation, estimate=core.estimate_report(p["windows"]), windows=[])
    for i, w in enumerate(p["windows"]):
        name = f"w{i:02d}"
        plate_w, matte_w, graph_w = (rd / "inputs" / f"{name}_plate.mp4", rd / "inputs" / f"{name}_matte.mp4",
                                     rd / "inputs" / f"{name}_graph.api.json")
        media.cut_plate_window(Path(plate), plate_w, w, p["fps"], silent=silent_audio)
        real = [p["matte_frames"][f - p["matte_offset"]] for f in range(w["src_start"], w["src_end"] + 1)]
        real += [real[-1]] * w["freeze"]
        media.encode_matte(real, p["width"], p["height"], matte_w, p["fps"])
        graph = core.patch_remove_graph(recipe, plate_name=plate_w.name, matte_name=matte_w.name, width=p["width"],
                                        height=p["height"], length=w["length"], fps=float(p["fps"]), prompt=text,
                                        seed=seed, dilation=dilation, prefix=f"PlateDoctor/{rd.name}/{name}")
        graph_w.write_text(json.dumps(graph, indent=1))
        manifest["windows"].append(dict(w, plate=str(plate_w), matte=str(matte_w), graph=str(graph_w)))
    _save(rd, manifest)
    manifest["run_dir"] = str(rd)
    if not go:
        return manifest
    # ---- real submit: refused by submit.require_go unless --go AND credentials are present
    for i, w in enumerate(manifest["windows"]):
        res = submit_fn(Path(w["graph"]), {("10", "file"): Path(w["plate"]), ("20", "file"): Path(w["matte"])},
                        ["81", "92"], rd / "windows" / f"w{i:02d}", go=go, transport=transport, env=env)
        w["result"] = res
        _save(rd, {k: v for k, v in manifest.items() if k != "run_dir"})
    if len(manifest["windows"]) == 1:
        manifest["note"] = "single window: RAW and BLEND are in windows/w00/. Judge RAW."
    else:
        manifest["note"] = ("multi-window: crossfade the per-window RAW clips with media.stitch_windows "
                            "(needs numpy); window outputs are in windows/wNN/.")
    _save(rd, {k: v for k, v in manifest.items() if k != "run_dir"})
    return manifest


def recover_run(plate: Path, *, lane: str = "graph", out: Path, shot: str | None = None, exposure: float = 7.1,
                seed: int = 42, go: bool = False, transport: str = "sdk", partner_ok: bool = False, env=None,
                submit_fn=submit.submit_graph, hosted_fn=recover.hosted_hdr) -> dict:
    """RECOVER: SDR to HDR EXR. lane 'graph' = local LTX-2.3 HDR IC-LoRA (open weights, the default);
    lane 'ltx-api' = hosted partner service (needs --partner-service-ok, LTX_API_KEY and --go)."""
    import os
    env = os.environ if env is None else env
    plate = Path(plate)
    info = media.probe_media(plate)
    shot = shot or re.sub(r"[^A-Za-z0-9_-]+", "_", plate.stem)
    rd = next_run_dir(Path(out), f"{shot}_RECOVER_{lane}{'' if go else '_DRYRUN'}")
    rd.mkdir(parents=True)
    manifest = dict(app="plate-doctor", version=VERSION, lane=lane, attribution=ATTRIBUTION, created=_now(),
                    dry_run=not go, plate=str(plate), width=info["width"], height=info["height"],
                    fps=str(info["fps"]), frames=info["frames"], exr_dir=str(rd / "exr"))
    if lane == "ltx-api":
        manifest["partner_service"] = True
        problems = recover.check_hosted_limits(info["width"], info["height"], info["frames"])
        if problems:
            raise Refusal("REFUSED: " + " | ".join(problems))
        manifest["lane_note"] = ("PARTNER SERVICE: api.ltx.video is hosted and billed by its vendor; it is not "
                                 "open weights and does not qualify for an Open Weights Only category.")
        _save(rd, manifest)
        if not go:
            manifest["run_dir"] = str(rd)
            return manifest
        if not partner_ok:
            raise Refusal("the hosted lane is a partner service: pass --partner-service-ok to confirm.")
        key = env.get("LTX_API_KEY")
        if not key:
            raise Refusal("LTX_API_KEY is not set. Nothing was sent.")
        result = hosted_fn(plate, key)
        manifest["hosted_result"] = {"status": result.get("status"), "exr_frames_url": recover.exr_zip_url(result)}
        _save(rd, manifest)
        manifest["run_dir"] = str(rd)
        return manifest
    if lane != "graph":
        raise Refusal(f"unknown lane {lane!r} (graph or ltx-api)")
    api = recover.load_hdr_api_graph()
    graph = recover.patch_hdr_graph(api, plate_name=plate.name, fps=float(info["fps"]), exr_dir=f"output/{rd.name}",
                                    exposure=exposure, seed=seed)
    gpath = rd / "hdr_graph.api.json"
    gpath.write_text(json.dumps(graph, indent=1))
    manifest.update(graph=str(gpath), recipe=HDR_RECIPE_NAME,
                    note=("The graph renders the closest 8n+1 frames of the plate. EXRs are written by "
                          "LTXVHDRDecodePostprocess on the ComfyUI machine under output/<run>/; set "
                          "OPENCV_IO_ENABLE_OPENEXR=1 before launching ComfyUI. UNPROVEN as an API-converted graph."))
    _save(rd, manifest)
    manifest["run_dir"] = str(rd)
    if not go:
        return manifest
    load_id = recover._only(graph, "LoadVideo")
    res = submit_fn(gpath, {(load_id, "file"): plate}, [recover._only(graph, "SaveVideo")], rd / "preview", go=go,
                    transport=transport, env=env)
    manifest["result"] = res
    _save(rd, {k: v for k, v in manifest.items() if k != "run_dir"})
    return manifest
