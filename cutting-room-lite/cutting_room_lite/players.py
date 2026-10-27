"""Performers: the layers of a cover. A backdrop plus N performers, each a clean image with a role and a stem.

The pipeline is  SPLIT -> ANIMATE per performer per window -> COMP back over the cover -> ASSEMBLE.

  SPLIT    v0.1: you supply one clean image per performer (a first frame with the performer alone). Splitting a
           cover automatically (an image-edit model plus a matte) is a documented stretch, NOT built.
  ANIMATE  singer  -> the H3 audio-driven graph (the proven recipe: clean image + song as ref_audio).
           others  -> a prompt that describes the part (lane "h3", UNPROVEN) or a performance-capture render
                      (lane "perfcap", documented only, NOT built).
  COMP     each animated performer is overlaid on the cover at its position and scale, through a matte or alpha.

House rule: an audio model moves a face, never sticks or hands. Instrument performers are the unproven lane.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

ROLES = ("singer", "drums", "bass", "guitar", "keys")
ROLE_STEM = {"singer": "vocals", "drums": "drums", "bass": "bass", "guitar": "guitar", "keys": "piano"}
STEMS = ("vocals", "drums", "bass", "guitar", "piano", "other")  # the six stems of a 6-stem separation
LANES = ("h3-audio", "h3", "perfcap")

LANE_STATUS = {
    "h3-audio": "H3 audio-driven (the recipe proven for a singing close-up)",
    "h3": "prompt-driven in H3 (UNPROVEN: run the drummer test first)",
    "perfcap": "performance-capture lane (NOT BUILT in v0.1, documented only)",
}


class PlayerError(ValueError):
    pass


@dataclass(frozen=True)
class Performer:
    id: str
    role: str                      # singer | drums | bass | guitar | keys   ("cover" = the whole-cover stand-in)
    stem: str
    lane: str = "h3-audio"
    verb: str = ""                 # what they do, for instrument roles
    person: str = ""               # who they are on the cover, in words
    image: str | None = None       # project-relative path of the clean (square) image
    matte: str | None = None       # project-relative path of a matte (white = performer), or None
    x: int = 0                     # top-left of the performer's square on the cover canvas
    y: int = 0
    w: int = 0                     # side of that square, in canvas pixels (0 = whole canvas)
    feather: float = 2.0           # matte edge softening, in pixels
    audio: str = "mix"             # which audio drives H3: "mix" (the song slice) or "stem" (the stem slice)
    enabled: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = LANE_STATUS[self.lane]
        return d


def parse_performers(raw: list[dict] | None, canvas: int = 1248) -> list[Performer]:
    """Validate the performers list from the UI or a performers.json file."""
    out: list[Performer] = []
    seen: set[str] = set()
    for i, item in enumerate(raw or []):
        pid = "".join(c for c in str(item.get("id") or f"p{i + 1}") if c.isalnum() or c in "-_")[:24]
        if not pid:
            raise PlayerError("performer id must contain letters or digits")
        role = str(item.get("role", "")).strip().lower()
        if role not in ROLES:
            raise PlayerError(f"performer {pid}: role must be one of {', '.join(ROLES)}")
        stem = str(item.get("stem") or ROLE_STEM[role]).strip().lower()
        if stem not in STEMS:
            raise PlayerError(f"performer {pid}: stem must be one of {', '.join(STEMS)}")
        lane = str(item.get("lane") or ("h3-audio" if role == "singer" else "h3")).strip().lower()
        if lane not in LANES:
            raise PlayerError(f"performer {pid}: lane must be one of {', '.join(LANES)}")
        if role == "singer" and lane == "h3":
            lane = "h3-audio"                      # a singer is always the audio-driven graph
        if role != "singer" and lane == "h3-audio":
            lane = "h3"                            # an instrument is never claimed to be audio-driven
        verb = str(item.get("verb", "")).strip()
        if role != "singer" and lane == "h3" and not verb:
            raise PlayerError(f"performer {pid}: an instrument performer needs a verb (what they do)")
        w = int(item.get("w") or 0)
        x, y = int(item.get("x") or 0), int(item.get("y") or 0)
        if w < 0 or x < 0 or y < 0 or (w and (x + w > canvas or y + w > canvas)):
            raise PlayerError(f"performer {pid}: the square (x={x}, y={y}, w={w}) must sit inside the {canvas}px cover")
        audio = str(item.get("audio") or ("mix" if role == "singer" else "stem")).strip().lower()
        if audio not in ("mix", "stem"):
            raise PlayerError(f"performer {pid}: audio must be mix or stem")
        if pid in seen:
            raise PlayerError(f"duplicate performer id {pid}")
        seen.add(pid)
        out.append(Performer(
            id=pid, role=role, stem=stem, lane=lane, verb=verb, person=str(item.get("person", "")).strip(),
            image=item.get("image") or None, matte=item.get("matte") or None, x=x, y=y, w=w,
            feather=float(item.get("feather", 2.0)), audio=audio, enabled=bool(item.get("enabled", True)),
        ))
    return out


def whole_cover(canvas: int, image: str | None) -> Performer:
    """The stand-in used when a cover has no performer layers: the whole cover is animated as one."""
    return Performer(id="cover", role="cover", stem="vocals", lane="h3-audio", image=image, x=0, y=0, w=canvas)


def layout_of(p: Performer, canvas: int) -> tuple[int, int, int]:
    return p.x, p.y, (p.w or canvas)


def notes_for(p: Performer, stem_active: bool | None) -> list[str]:
    """Flags the UI shows next to a performer's window: what is not being done."""
    notes = []
    if p.lane == "perfcap":
        notes.append(f"{p.id} ({p.role}): needs a performance-capture render; not built, left static on the cover")
    elif p.role not in ("singer", "cover"):
        notes.append(f"{p.id} ({p.role}): prompt-driven only, unproven")
    if stem_active is False:
        notes.append(f"{p.id}: its stem is quiet in this window")
    return notes
