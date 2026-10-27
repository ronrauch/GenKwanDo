"""A project: one cover (backdrop + performer layers), one song, one slice, its windows and their takes.

Stages: SPLIT (clean image per performer, supplied by you in v0.1) -> ANIMATE (per performer, per window)
-> COMP (overlay the animated performers back on the cover) -> ASSEMBLE (original song under the picture).
With no performers defined, the whole cover is animated as one performer and there is no comp stage.
State lives in project.json.
"""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

from . import graph as graphmod
from . import media
from .comfy_client import FileInput
from .planner import FPS, Window, plan_windows, total_deliver_frames
from .players import Performer, layout_of, notes_for, parse_performers, whole_cover
from .prompts import COVER_TYPES, pick_player_prompt, pick_prompt

DEFAULTS = {
    "name": "my-cover",
    "size": 1248,
    "slice": {"start": 0.0, "length": 30.0},
    "cover_type": "performer",   # only used when the whole cover is animated as one
    "has_vocals": True,
    "style": "",
    "extra": "",
    "performers": [],
    "window_s": 10.0,
    "cover": None,        # relative path of the squared cover (the backdrop)
    "song": None,
    "song_duration": None,
    "stems": {},          # stem name -> relative path
    "windows": [],        # each: timing + "tracks": {performer id: {prompt, takes, approved, notes}}
}


class ProjectError(RuntimeError):
    pass


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.file = self.root / "project.json"
        self.state = json.loads(json.dumps(DEFAULTS))
        if self.file.exists():
            self.state.update(json.loads(self.file.read_text()))

    def save(self) -> None:
        self.file.write_text(json.dumps(self.state, indent=1))

    def path(self, rel: str) -> Path:
        return self.root / rel

    # ---- SPLIT: inputs ----
    def set_cover(self, src: str | Path) -> None:
        if Path(src).suffix.lower() not in media.IMAGE_EXTS:
            raise ProjectError("the cover must be an image (png, jpg, webp)")
        (self.root / "media").mkdir(exist_ok=True)
        dst = self.root / "media" / "cover.png"
        media.run(media.square_cover_cmd(str(src), str(dst), self.state["size"]))
        self.state["cover"] = "media/cover.png"
        self.save()

    def set_song(self, src: str | Path) -> None:
        ext = Path(src).suffix.lower()
        if ext not in media.AUDIO_EXTS:
            raise ProjectError("the song must be an audio file (mp3, wav, m4a, flac)")
        (self.root / "media").mkdir(exist_ok=True)
        dst = self.root / "media" / f"song{ext}"
        if Path(src).resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        self.state["song"] = f"media/song{ext}"
        self.state["song_duration"] = round(media.probe_duration(str(dst)), 3)
        self.save()

    def set_stems(self, stem_dir: str | Path) -> list[str]:
        """Register stem files named <stem>.wav|mp3|flac (vocals, drums, bass, guitar, piano, other)."""
        (self.root / "media" / "stems").mkdir(parents=True, exist_ok=True)
        self.state["stems"] = {}
        for p in sorted(Path(stem_dir).iterdir()):
            if p.suffix.lower() in media.AUDIO_EXTS:
                dst = self.root / "media" / "stems" / p.name
                shutil.copyfile(p, dst)
                self.state["stems"][p.stem.lower()] = f"media/stems/{p.name}"
        self.save()
        return sorted(self.state["stems"])

    def performers(self) -> list[Performer]:
        return parse_performers(self.state["performers"], self.state["size"])

    def effective(self) -> list[Performer]:
        """The performers to animate: the layers, or the whole cover as one when there are none."""
        perfs = self.performers()
        return perfs or [whole_cover(self.state["size"], self.state["cover"])]

    def _performer(self, pid: str) -> Performer:
        for p in self.effective():
            if p.id == pid:
                return p
        raise ProjectError(f"no performer {pid!r}")

    def set_performer_image(self, pid: str, src: str | Path, matte: bool = False) -> None:
        """Attach the clean image (or the matte) for a performer.

        A clean image with an alpha channel also yields the matte (alpha -> white = performer) and is flattened
        over black for H3, which wants a plain RGB reference.
        """
        perfs = self.state["performers"]
        entry = next((p for p in perfs if p.get("id") == pid), None)
        if entry is None:
            raise ProjectError(f"add performer {pid!r} first")
        if Path(src).suffix.lower() not in media.IMAGE_EXTS:
            raise ProjectError("the image must be png, jpg or webp")
        d = self.root / "media" / "performers"
        d.mkdir(parents=True, exist_ok=True)
        size = self.state["size"]
        sq = d / f"{pid}_square.png"
        media.run(media.square_cover_cmd(str(src), str(sq), size))
        if matte:
            m = d / f"{pid}_matte.png"
            media.run([media.FFMPEG, "-y", "-i", str(sq), "-vf", "format=gray", "-frames:v", "1", str(m)])
            entry["matte"] = str(m.relative_to(self.root))
        else:
            rgb = d / f"{pid}.png"
            if media.has_alpha(str(sq)):
                m = d / f"{pid}_matte.png"
                media.run(media.alpha_matte_cmd(str(sq), str(m)))
                media.run(media.flatten_cmd(str(sq), str(rgb), size))
                entry["matte"] = str(m.relative_to(self.root))
            else:
                shutil.copyfile(sq, rgb)
            entry["image"] = str(rgb.relative_to(self.root))
        self.save()

    def configure(self, **kw) -> None:
        for key in ("name", "cover_type", "has_vocals", "style", "extra", "window_s"):
            if key in kw and kw[key] is not None:
                self.state[key] = kw[key]
        if self.state["cover_type"] not in COVER_TYPES:
            raise ProjectError(f"cover_type must be one of {', '.join(COVER_TYPES)}")
        if kw.get("performers") is not None:
            keep = {p["id"]: p for p in self.state["performers"]}
            raw = []
            for item in kw["performers"]:
                old = keep.get(item.get("id"), {})
                raw.append({**item, "image": item.get("image") or old.get("image"),
                            "matte": item.get("matte") or old.get("matte")})
            self.state["performers"] = [p.to_dict() for p in parse_performers(raw, self.state["size"])]
        if kw.get("slice_start") is not None:
            self.state["slice"]["start"] = float(kw["slice_start"])
        if kw.get("slice_length") is not None:
            self.state["slice"]["length"] = float(kw["slice_length"])
        self.save()

    # ---- planning ----
    def _audio_source(self, p: Performer) -> str:
        """The audio file that drives H3 for this performer: its stem when asked and available, else the mix."""
        rel = self.state["stems"].get(p.stem) if p.audio == "stem" else None
        return str(self.path(rel or self.state["song"]))

    def _stem_active(self, p: Performer, w: Window) -> bool | None:
        rel = self.state["stems"].get(p.stem)
        return media.stem_active(str(self.path(rel)), w.start_s, w.deliver_s) if rel else None

    def prompt_for(self, p: Performer) -> str:
        s = self.state
        if p.role == "cover":
            return pick_prompt(s["cover_type"], s["has_vocals"], s["style"], "", s["extra"])
        if p.role == "singer":
            return pick_prompt("performer", True, s["style"], "", s["extra"])
        return pick_player_prompt(p.role, p.verb, s["style"], s["extra"])

    def plan(self) -> list[dict]:
        """(Re)plan the windows and every performer's prompt. Takes survive only where nothing changed."""
        sl = self.state["slice"]
        song_len = self.state["song_duration"]
        if song_len is not None and sl["start"] + sl["length"] > song_len + 1e-6:
            raise ProjectError(f"the slice runs past the end of the song ({song_len:.1f} s)")
        wins = plan_windows(sl["start"], sl["length"], window_s=self.state["window_s"])
        old = {w["index"]: w for w in self.state["windows"]}
        out = []
        for w in wins:
            entry = w.to_dict()
            entry["tracks"] = {}
            prev_tracks = old.get(w.index, {}).get("tracks", {})
            same_time = bool(old.get(w.index)) and all(
                old[w.index].get(k) == entry[k] for k in ("start_s", "render_frames"))
            for p in self.effective():
                prompt = self.prompt_for(p)
                prev = prev_tracks.get(p.id)
                keep = same_time and prev and prev.get("prompt") == prompt and prev.get("image") == p.image
                entry["tracks"][p.id] = {
                    "prompt": prompt,
                    "image": p.image,
                    "notes": notes_for(p, self._stem_active(p, w)),
                    "takes": prev["takes"] if keep else [],
                    "approved": prev.get("approved") if keep else None,
                }
            out.append(entry)
        self.state["windows"] = out
        self.save()
        return out

    # ---- seeds, graphs ----
    def seed_for(self, pid: str, k: int, n: int) -> int:
        return random.Random(f"{self.state['name']}:{pid}:{k}:{n}").randrange(2**48)

    def _window(self, k: int) -> dict:
        try:
            return self.state["windows"][k]
        except IndexError:
            raise ProjectError(f"no window {k}; plan first") from None

    def _track(self, k: int, pid: str) -> dict:
        try:
            return self._window(k)["tracks"][pid]
        except KeyError:
            raise ProjectError(f"window {k} has no track for performer {pid!r}") from None

    def window_obj(self, k: int) -> Window:
        w = self._window(k)
        return Window(w["index"], w["start_s"], w["deliver_frames"], w["render_frames"],
                      w["audio_start_s"], w["audio_dur_s"], w["drop_first"])

    def build_graph(self, k: int, pid: str, n: int, ref_name=None, audio_name=None, guide_name=None) -> dict:
        return graphmod.build_window_graph(
            self.window_obj(k),
            cover_name=ref_name or f"{pid}.png",
            audio_name=audio_name or f"{pid}_w{k}_chunk.wav",
            guide_name=guide_name or (f"{pid}_w{k}_guide.png" if k > 0 else None),
            prompt=self._track(k, pid)["prompt"],
            seed=self.seed_for(pid, k, n),
            project=f"{self.state['name']}_{pid}",
            size=self.state["size"],
        )

    # ---- ANIMATE ----
    def render(self, k: int, pid: str, runner=None) -> dict:
        """Render one performer's window k. runner=None is a DRY RUN: it writes the graph and the audio chunk only."""
        p = self._performer(pid)
        if p.lane == "perfcap":
            raise ProjectError(f"{pid}: the performance-capture lane is not built in this version")
        if not p.image:
            raise ProjectError(f"performer {pid} has no clean image yet" if p.role != "cover"
                               else "pick a cover first")
        if not self.state["song"]:
            raise ProjectError("pick a song first")
        win, track = self._window(k), self._track(k, pid)
        n = len(track["takes"]) + 1
        take_id = f"t{n:03d}"
        tdir = self.root / "takes" / pid / f"w{k}"
        tdir.mkdir(parents=True, exist_ok=True)

        chunk = tdir / f"{take_id}_chunk.wav"
        media.run(media.trim_audio_cmd(self._audio_source(p), str(chunk), win["audio_start_s"], win["audio_dur_s"]))
        graph = self.build_graph(k, pid, n)
        graph_file = tdir / f"{take_id}.graph.json"
        graph_file.write_text(json.dumps(graph, indent=1))
        take = {"id": take_id, "seed": self.seed_for(pid, k, n), "state": "dry-run", "video": None,
                "graph": str(graph_file.relative_to(self.root)), "error": None, "frames": None,
                "summary": graphmod.describe(graph)}

        guide_png = None
        if k > 0:
            prev = self.approved_take(k - 1, pid)
            if prev and prev.get("video"):
                guide_png = tdir / f"{take_id}_guide.png"
                if runner is not None:
                    media.run(media.last_frame_cmd(str(self.path(prev["video"])), str(guide_png)))
            elif runner is not None:
                raise ProjectError(f"approve a take for {pid}, window {k - 1} first: "
                                   f"window {k} starts from its last frame")

        if runner is not None:
            inputs = [FileInput("6", "image", str(self.path(p.image))), FileInput("7", "audio", str(chunk))]
            if guide_png is not None:
                inputs.append(FileInput(graphmod.GUIDE_NODE, "image", str(guide_png)))
            out = tdir / f"{take_id}.mp4"
            try:
                runner.run_window(graph, inputs, str(out), graph_path=str(graph_file))
                take.update(state="done", video=str(out.relative_to(self.root)))
                take["frames"] = media.probe_frames(str(out))
                if abs(take["frames"] - win["render_frames"]) > 2:
                    take["error"] = (f"rendered {take['frames']} frames, planned {win['render_frames']}: "
                                     "check audio/video length before approving")
            except Exception as exc:  # keep the take record so the UI can show what happened
                take.update(state="failed", error=str(exc))
        track["takes"].append(take)
        self.save()
        return take

    def add_placeholder_take(self, k: int, pid: str, color: str | None = None) -> dict:
        """A flat test clip standing in for a take, to exercise approve, comp and assemble without H3."""
        win, track = self._window(k), self._track(k, pid)
        n = len(track["takes"]) + 1
        tdir = self.root / "takes" / pid / f"w{k}"
        tdir.mkdir(parents=True, exist_ok=True)
        out = tdir / f"t{n:03d}_PLACEHOLDER.mp4"
        media.run(media.make_placeholder_take(str(out), win["render_frames"], size=self.state["size"], color=color))
        take = {"id": f"t{n:03d}", "seed": None, "state": "placeholder", "video": str(out.relative_to(self.root)),
                "graph": None, "error": None, "frames": win["render_frames"], "summary": None}
        track["takes"].append(take)
        self.save()
        return take

    def approved_take(self, k: int, pid: str) -> dict | None:
        track = self._track(k, pid)
        return next((t for t in track["takes"] if t["id"] == track["approved"]), None)

    def approve(self, k: int, pid: str, take_id: str) -> None:
        track = self._track(k, pid)
        take = next((t for t in track["takes"] if t["id"] == take_id), None)
        if not take:
            raise ProjectError(f"{pid}, window {k} has no take {take_id}")
        if not take.get("video"):
            raise ProjectError("a dry-run take has no video to approve")
        track["approved"] = take_id
        self.save()

    # ---- COMP + ASSEMBLE ----
    def _track_video(self, p: Performer) -> tuple[str, bool]:
        """Join one performer's approved windows into one full-length track. Returns (path, placeholder?)."""
        placeholder = False
        seg_dir = self.root / "out" / "segments" / p.id
        seg_dir.mkdir(parents=True, exist_ok=True)
        segs = []
        for w in self.state["windows"]:
            take = self.approved_take(w["index"], p.id)
            if not take or not take.get("video"):
                raise ProjectError(f"{p.id}: window {w['index']} has no approved take")
            placeholder = placeholder or take["state"] == "placeholder"
            seg = seg_dir / f"seg{w['index']}.mp4"
            media.run(media.segment_cmd(str(self.path(take["video"])), str(seg), w["drop_first"], FPS, self.state["size"]))
            segs.append(str(seg))
        listing = seg_dir / "concat.txt"
        listing.write_text(media.concat_list_text(segs))
        track = self.root / "out" / f"track_{p.id}.mp4"
        media.run(media.track_cmd(str(listing), str(track)))
        return str(track), placeholder

    def assemble(self) -> dict:
        if not self.state["windows"]:
            raise ProjectError("plan the windows first")
        perfs = [p for p in self.effective() if p.enabled and p.lane != "perfcap"]
        if not perfs:
            raise ProjectError("no performer is enabled and animatable")
        size = self.state["size"]
        tracks, placeholder = {}, False
        for p in perfs:
            tracks[p.id], ph = self._track_video(p)
            placeholder = placeholder or ph
        sl = self.state["slice"]
        frames = total_deliver_frames([self.window_obj(w["index"]) for w in self.state["windows"]])
        if len(perfs) == 1 and perfs[0].role == "cover":
            picture = tracks["cover"]  # whole cover animated as one: nothing to comp
        else:
            layers = []
            for p in perfs:
                x, y, w = layout_of(p, size)
                layers.append({"video": tracks[p.id], "x": x, "y": y, "w": w,
                               "matte": str(self.path(p.matte)) if p.matte else None, "feather": p.feather})
            picture = str(self.root / "out" / "comp.mp4")
            media.run(media.comp_cmd(str(self.path(self.state["cover"])), layers, picture, frames, size))
        name = "final_PLACEHOLDER.mp4" if placeholder else "final.mp4"
        dst = self.root / "out" / name
        media.run(media.mux_cmd(picture, str(self.path(self.state["song"])), sl["start"], sl["length"], str(dst)))
        return {"file": str(dst.relative_to(self.root)), "placeholder": placeholder,
                "frames": media.probe_frames(str(dst)), "expected_frames": frames,
                "duration": round(media.probe_duration(str(dst)), 3),
                "composed": [p.id for p in perfs if p.role != "cover"],
                "left_static": [p.id for p in self.performers() if p not in perfs]}

    def all_approved(self) -> bool:
        wins = self.state["windows"]
        perfs = [p for p in self.effective() if p.enabled and p.lane != "perfcap"]
        return bool(wins and perfs) and all(w["tracks"][p.id]["approved"] for w in wins for p in perfs)

    def public(self) -> dict:
        s = json.loads(json.dumps(self.state))
        s["cover_url"] = "/media/" + s["cover"] if s["cover"] else None
        s["song_url"] = "/media/" + s["song"] if s["song"] else None
        s["effective"] = [p.to_dict() for p in self.effective()]
        s["ready_to_assemble"] = self.all_approved()
        return s
