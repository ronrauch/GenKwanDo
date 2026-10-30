"""Command line: serve the app, plan, render (dry run unless --go), assemble, and the day-1 drummer test."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import VERSION, about, media
from .comfy_client import GateError, gate_reasons, get_runner
from .planner import plan_windows
from .project import Project, ProjectError

DRUMMER = {
    "id": "drummer",
    "role": "drums",
    "stem": "drums",
    "person": "the drummer",
    "verb": "strikes the drum kit in time with the beat, sticks landing on every kick and snare",
    "lane": "h3",
    "audio": "mix",
}


def _gate_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--go", action="store_true",
                   help="allow real submits (spends credits). Without it everything is a dry run.")
    p.add_argument("--backend", choices=["cloud", "local"], default="cloud")
    p.add_argument("--transport", choices=["auto", "sdk", "http"], default="auto",
                   help="sdk = official comfy-sdk (optional extra); http = stdlib fallback; auto = sdk if installed")


def _api_key() -> str | None:
    return os.environ.get("COMFY_API_KEY") or None


def gate_banner(args) -> str:
    reasons = gate_reasons(args.backend, args.go, _api_key())
    if reasons:
        return "DRY RUN, nothing will be sent (" + "; ".join(reasons) + ")"
    return f"LIVE: {args.backend} via {args.transport}. Submits spend credits."


def print_plan(project: Project, args) -> None:
    wins = project.state["windows"]
    frames = sum(w["deliver_frames"] for w in wins)
    perfs = project.effective()
    print(f"{gate_banner(args)}")
    print(f"plan: {len(wins)} windows x {len(perfs)} performer(s), {frames} frames ({frames / 24:.2f} s) "
          f"at {project.state['size']}x{project.state['size']}, 24 fps")
    for p in perfs:
        print(f"  performer {p.id}: role {p.role}, lane {p.lane}" + ("" if p.image else "  (NO CLEAN IMAGE YET)"))
    for w in wins:
        takes = sum(len(t["takes"]) for t in w["tracks"].values())
        print(f"  w{w['index']}: song {w['start_s']:.2f}s  deliver {w['deliver_frames']}f  render {w['render_frames']}f  "
              f"audio {w['audio_start_s']:.3f}+{w['audio_dur_s']:.3f}s  takes {takes}")


def cmd_serve(args) -> int:
    from .server import make_server

    srv = make_server(args.root, args.host, args.port, go=args.go, backend=args.backend,
                      transport=args.transport, api_key=_api_key())
    print(gate_banner(args))
    print(f"Cutting Room Lite on http://{args.host}:{srv.server_address[1]}  (project: {args.root})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_plan(args) -> int:
    wins = plan_windows(args.start, args.length, window_s=args.window_s)
    print(f"{len(wins)} windows")
    for w in wins:
        print(w.to_dict())
    return 0


def _load(args) -> Project:
    pr = Project(args.root)
    if not pr.state["windows"]:
        pr.plan()
    return pr


def cmd_render(args) -> int:
    pr = _load(args)
    pr.plan()
    print_plan(pr, args)
    runner = None
    if gate_reasons(args.backend, args.go, _api_key()) == []:
        runner = get_runner(args.transport, args.backend, args.go, _api_key())
    targets = [args.window] if args.window is not None else range(len(pr.state["windows"]))
    for p in pr.effective():
        if args.performer and p.id != args.performer:
            continue
        if p.role == "beat":
            print(f"skip {p.id}: a beat object is a COMP effect, nothing to render")
            continue
        if p.lane == "perfcap" or not p.image:
            print(f"skip {p.id}: " + ("performance-capture lane is not built" if p.lane == "perfcap" else "no clean image"))
            continue
        for k in targets:
            take = pr.render(k, p.id, runner)
            print(f"{p.id} w{k}: {take['id']} {take['state']} seed {take['seed']}"
                  + (f"  ERROR {take['error']}" if take["error"] else ""))
    if runner is None:
        print("dry run complete: graphs and audio chunks written under takes/")
    return 0


def cmd_assemble(args) -> int:
    info = Project(args.root).assemble()
    print(info)
    return 0


def cmd_synthetic(args) -> int:
    """Make a test song, a placeholder cover and two placeholder performers (no network, no H3)."""
    root = Path(args.root)
    src = root / "synthetic"
    src.mkdir(parents=True, exist_ok=True)
    media.run(media.make_synthetic_song(str(src / "click-track.wav"), 40.0, 120.0))
    media.run(media.make_placeholder_cover(str(src / "placeholder-cover.png")))
    media.run(media.make_color_image(str(src / "placeholder-singer.png"), "0x2a9d8f"))
    media.run(media.make_color_image(str(src / "placeholder-drummer.png"), "0xe76f51"))
    pr = Project(root)
    pr.set_cover(src / "placeholder-cover.png")
    pr.set_song(src / "click-track.wav")
    pr.configure(name="synthetic-test", slice_start=0, slice_length=30, performers=[
        {"id": "singer", "role": "singer", "x": 60, "y": 300, "w": 500},
        {"id": "drummer", "role": "drums", "x": 688, "y": 300, "w": 500, "verb": "strikes the kit on the beat"},
    ])
    pr.set_performer_image("singer", src / "placeholder-singer.png")
    pr.set_performer_image("drummer", src / "placeholder-drummer.png")
    pr.plan()
    print(f"synthetic project ready in {root}")
    return 0


def cmd_drummer_test(args) -> int:
    """Day-1 test: one window, one drummer, judge the sticks against the beat. See docs/DRUMMER-TEST.md."""
    pr = Project(args.root)
    pr.set_cover(args.cover)
    pr.set_song(args.song)
    pr.configure(name="drummer-test", performers=[DRUMMER],
                 slice_start=args.start, slice_length=args.length, window_s=args.length)
    pr.set_performer_image("drummer", args.cover)  # the test image is the drummer, framed as you want it rendered
    pr.plan()
    print_plan(pr, args)
    runner = None
    if gate_reasons(args.backend, args.go, _api_key()) == []:
        runner = get_runner(args.transport, args.backend, args.go, _api_key())
    take = pr.render(0, "drummer", runner)
    print(f"{take['id']}: {take['state']}  {take['video'] or '(no video: dry run)'}")
    if take.get("video"):
        out = Path(args.root) / "takes" / "drummer" / "w0" / f"{take['id']}_beats.mp4"
        media.run(media.beat_overlay_cmd(str(pr.path(take["video"])), str(out), args.bpm, args.first_beat))
        print(f"beat overlay: {out}  (red box flashes on each beat; judge the sticks against it)")
    return 0


def cmd_beat_overlay(args) -> int:
    media.run(media.beat_overlay_cmd(args.video, args.out, args.bpm, args.first_beat))
    print(args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cutting-room-lite", description=__doc__)
    ap.add_argument("--version", action="version", version=f"cutting-room-lite {VERSION}")
    ap.add_argument("--about", action="store_true", help="print the attribution block")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--root", default="project")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8800)
    _gate_args(s)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("plan", help="print the window plan for a slice")
    s.add_argument("--start", type=float, default=0.0)
    s.add_argument("--length", type=float, default=30.0)
    s.add_argument("--window-s", type=float, default=10.0)
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("render", help="render windows (dry run unless --go)")
    s.add_argument("--root", default="project")
    s.add_argument("--window", type=int, default=None, help="one window index (default: all)")
    s.add_argument("--performer", default=None, help="one performer id (default: all)")
    _gate_args(s)
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("assemble", help="cut approved takes together under the original song slice")
    s.add_argument("--root", default="project")
    s.set_defaults(fn=cmd_assemble)

    s = sub.add_parser("synthetic", help="make a synthetic test project (click track + placeholder cover)")
    s.add_argument("--root", default="project")
    s.set_defaults(fn=cmd_synthetic)

    s = sub.add_parser("drummer-test", help="day-1 test: one drummer window, beat overlay to judge it")
    s.add_argument("--root", default="drummer-test")
    s.add_argument("--cover", required=True)
    s.add_argument("--song", required=True)
    s.add_argument("--start", type=float, default=0.0)
    s.add_argument("--length", type=float, default=10.0)
    s.add_argument("--bpm", type=float, required=True)
    s.add_argument("--first-beat", type=float, default=0.0)
    _gate_args(s)
    s.set_defaults(fn=cmd_drummer_test)

    s = sub.add_parser("beat-overlay", help="burn a beat flasher onto a clip")
    s.add_argument("video")
    s.add_argument("out")
    s.add_argument("--bpm", type=float, required=True)
    s.add_argument("--first-beat", type=float, default=0.0)
    s.set_defaults(fn=cmd_beat_overlay)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.about:
        print(about())
        return 0
    if not getattr(args, "fn", None):
        ap.print_help()
        return 0
    try:
        return args.fn(args)
    except (ProjectError, GateError, media.MediaError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
