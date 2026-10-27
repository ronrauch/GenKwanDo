"""Command line. Every command that could reach a network is a dry run unless you pass --go."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import core, media, pipeline, recover
from .config import APP_NAME, VERSION, about_text
from .core import Refusal


def _print_plan(m: dict) -> None:
    mode = "DRY RUN (nothing sent)" if m.get("dry_run") else "SUBMITTED"
    print(f"\n{mode} · {m.get('recipe', m.get('lane'))} · {m.get('width')}x{m.get('height')} @ {m.get('fps')} fps")
    if "windows" in m:
        print(f"frames {m['first']}-{m['last']} · {len(m['windows'])} window(s)")
        for i, w in enumerate(m["windows"]):
            print(f"  w{i:02d}: plate frames {w['src_start']}-{w['src_end']} (+{w['freeze']} frozen) = {w['length']} f")
        print(m["estimate"])
        print(f"prompt: {m['prompt']}")
    for k in ("lane_note", "note"):
        if m.get(k):
            print(m[k])
    print(f"run folder: {m['run_dir']}")
    if m.get("dry_run"):
        print("To submit for real, add --go (Comfy Cloud also needs COMFY_API_KEY). Start with --probe.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="plate-doctor", description=f"{APP_NAME}: a VFX bench for one plate.",
                                epilog=about_text(), formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    p.add_argument("--about", action="store_true", help="print the About block")
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("demo", help="make a synthetic plate + matte + ground truth (no assets, no network)")
    d.add_argument("--workdir", default="workspace/demo")

    r = sub.add_parser("remove", help="REMOVE: clean plate (dry run unless --go)")
    r.add_argument("plate"); r.add_argument("matte", help="matte video or PNG folder, white = remove")
    r.add_argument("--prompt-location", help="the EMPTY set: place, furniture, surfaces, light")
    r.add_argument("--prompt", help="the whole positive prompt, verbatim")
    r.add_argument("--empty", help="what is left empty, e.g. chair")
    r.add_argument("--frames", help="a-b inclusive, 0-based (default: all)")
    r.add_argument("--probe", action="store_true", help="9 frames only")
    r.add_argument("--probe-at", type=int)
    r.add_argument("--seed", type=int, default=43); r.add_argument("--dilation", type=int, default=15)
    r.add_argument("--shot"); r.add_argument("--out", default="workspace/runs")
    r.add_argument("--silent-audio", action="store_true", help="plate without audio (UNPROVEN)")
    r.add_argument("--go", action="store_true", help="actually submit (needs credentials)")
    r.add_argument("--transport", choices=["sdk", "http"], default="sdk")

    c = sub.add_parser("recover", help="RECOVER: SDR to HDR EXR (dry run unless --go)")
    c.add_argument("plate"); c.add_argument("--lane", choices=["graph", "ltx-api"], default="graph",
                   help="graph = local LTX-2.3 HDR IC-LoRA (open weights); ltx-api = hosted PARTNER SERVICE")
    c.add_argument("--graph", help="path to your copy of the upstream HDR workflow (default: the fetch-graph copy)")
    c.add_argument("--exposure", type=float, default=7.1); c.add_argument("--seed", type=int, default=42)
    c.add_argument("--shot"); c.add_argument("--out", default="workspace/runs")
    c.add_argument("--go", action="store_true"); c.add_argument("--transport", choices=["sdk", "http"], default="sdk")
    c.add_argument("--partner-service-ok", action="store_true", help="confirm use of the hosted partner service")

    g = sub.add_parser("fetch-graph", help="put your copy of Lightricks' HDR workflow where RECOVER reads it")
    g.add_argument("--from", dest="src", help="path to the downloaded workflow, or an explicit https URL to the raw file")

    f = sub.add_parser("reflect", help="add a glossy surface's reflection to a matte (needs numpy)")
    f.add_argument("plate"); f.add_argument("matte"); f.add_argument("--out", required=True)

    v = sub.add_parser("vanish", help="make the before/after 'vanish' wipe clip")
    v.add_argument("before"); v.add_argument("after"); v.add_argument("--out", required=True)

    i = sub.add_parser("inspect", help="check a plate and matte: refusals, per-frame coverage")
    i.add_argument("plate"); i.add_argument("matte")

    s = sub.add_parser("serve", help="the local web UI (127.0.0.1 only)")
    s.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    s.add_argument("--workspace", default="workspace")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.about:
        print(about_text())
        return 0
    try:
        if args.cmd == "demo":
            info = media.make_demo(Path(args.workdir))
            print(json.dumps(info, indent=1))
        elif args.cmd == "remove":
            _print_plan(pipeline.remove_run(
                Path(args.plate), Path(args.matte), location=args.prompt_location, prompt=args.prompt, empty=args.empty,
                frames=args.frames, probe=args.probe, probe_at=args.probe_at, seed=args.seed, dilation=args.dilation,
                shot=args.shot, out=Path(args.out), silent_audio=args.silent_audio, go=args.go, transport=args.transport))
        elif args.cmd == "recover":
            _print_plan(pipeline.recover_run(Path(args.plate), lane=args.lane, hdr_graph=Path(args.graph) if args.graph else None,
                                             out=Path(args.out), shot=args.shot,
                                             exposure=args.exposure, seed=args.seed, go=args.go,
                                             transport=args.transport, partner_ok=args.partner_service_ok))
        elif args.cmd == "fetch-graph":
            if not args.src:
                print(recover.FETCH_HELP)
                return 2
            print(f"saved {recover.fetch_graph(args.src)}")
        elif args.cmd == "reflect":
            info = media.probe_media(Path(args.plate))
            frames = media.mirror_reflection(media.read_matte(Path(args.matte), info["width"], info["height"]),
                                             info["width"], info["height"])
            media.encode_matte(frames, info["width"], info["height"], Path(args.out), info["fps"])
            print(f"wrote {args.out} ({len(frames)} frames)")
        elif args.cmd == "vanish":
            media.vanish(Path(args.before), Path(args.after), Path(args.out))
            print(f"wrote {args.out}")
        elif args.cmd == "inspect":
            info = media.probe_media(Path(args.plate))
            print(json.dumps({k: str(v) for k, v in info.items()}))
            for msg in media.check_plate(info):
                print("REFUSAL:", msg)
            m = media.read_matte(Path(args.matte), info["width"], info["height"])
            print(f"matte frames {len(m)}, plate frames {info['frames']}, empty frames {core.empty_frames(m)}")
        elif args.cmd == "serve":
            from . import server
            server.serve(args.port, Path(args.workspace))
        else:
            build_parser().print_help()
            return 2
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
