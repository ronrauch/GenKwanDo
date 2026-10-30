"""Prompt picker: one H3 prompt per cover type.

H3's reference-to-video prompt addresses the cover as <Picture 1> and the song chunk as <Audio 1>.
The performer prompt follows the wording of the graph that was proven for a singing close-up; the other
two are written for covers with no face and are untested.
"""
from __future__ import annotations

COVER_TYPES = ("performer", "object", "landscape")

COVER_LABELS = {
    "performer": "Performer (a face or a band on the cover)",
    "object": "Object (a still life, an instrument, a product)",
    "landscape": "Landscape / abstract (scenery, pattern, typography)",
}

_HEAD = (
    "Use <Picture 1> as the exact framing, lighting and background, and use <Audio 1> exactly as it is "
    "as the only sound. Every bit of audio must be in order."
)

_PERFORMER_SINGS = (
    "The performer sings the vocal in <Audio 1> with restrained intensity: lips and jaw match every word "
    "and sustained note, mouth opening moderately, never exaggerated. Slow head drift, small turns, eyes "
    "closing on the long held notes, a downward tilt on phrases, then looking back toward the lens. "
    "Voice in sync. No gestures, shoulders still."
)
_PERFORMER_MUTE = (
    "The performer listens and moves with the music, no singing: slow head drift, small turns, eyes "
    "closing on long notes, a downward tilt on phrases, then looking back toward the lens. "
    "No gestures, shoulders still."
)
_OBJECT = (
    "The subject stays the same object and does not change shape. The music moves the scene around it: "
    "light shifts on the beat, slow dust and haze drift, a gentle push-in that breathes with the rhythm."
)
_LANDSCAPE = (
    "Keep the composition of <Picture 1>. The scene breathes with the rhythm: clouds, water, grain or "
    "pattern drift and pulse with the music, a slow parallax drift, light swelling on the downbeats."
)
_TAIL = "Locked-off camera unless stated, no cuts, no text, no other people."

_PLAYER = (
    "The performer plays the {role} part heard in <Audio 1>: {verb}. Movement lands on the beats of "
    "<Audio 1>. Hands and the instrument stay in frame, the instrument does not change shape. "
    "Head and shoulders stay calm. This is a prompt-driven performance and is UNPROVEN."
)


def pick_prompt(
    cover_type: str,
    has_vocals: bool = True,
    style: str = "",
    players_clause: str = "",
    extra: str = "",
) -> str:
    """Return the full H3 prompt for a cover type.

    style: free text about look and era ("1970s film close-up, warm tungsten key, fine grain").
    players_clause: the sentence from players.clause_for_window.
    extra: anything the user wants appended, verbatim.
    """
    if cover_type not in COVER_TYPES:
        raise ValueError(f"cover_type must be one of {', '.join(COVER_TYPES)}")
    if cover_type == "performer":
        body = _PERFORMER_SINGS if has_vocals else _PERFORMER_MUTE
    elif cover_type == "object":
        body = _OBJECT
    else:
        body = _LANDSCAPE
    pieces = [_HEAD, style.strip(), body, players_clause.strip(), _TAIL, extra.strip()]
    return " ".join(p for p in pieces if p)


def pick_player_prompt(role: str, verb: str, style: str = "", extra: str = "") -> str:
    """Prompt for an instrument performer (drums, bass, guitar, keys). UNPROVEN: see docs/DRUMMER-TEST.md."""
    body = _PLAYER.replace(" This is a prompt-driven performance and is UNPROVEN.", "").format(role=role, verb=verb.rstrip("."))
    return " ".join(p for p in [_HEAD, style.strip(), body, _TAIL, extra.strip()] if p)
