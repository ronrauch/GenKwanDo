import pytest

from cutting_room_lite.players import PlayerError, layout_of, notes_for, parse_performers, whole_cover
from cutting_room_lite.prompts import COVER_TYPES, pick_player_prompt, pick_prompt


@pytest.mark.parametrize("kind", COVER_TYPES)
def test_every_prompt_addresses_the_cover_and_the_song(kind):
    p = pick_prompt(kind)
    assert "<Picture 1>" in p and "<Audio 1>" in p
    assert "no text" in p


def test_performer_sings_only_when_there_are_vocals():
    assert "sings the vocal" in pick_prompt("performer", has_vocals=True)
    mute = pick_prompt("performer", has_vocals=False)
    assert "no singing" in mute and "sings the vocal" not in mute


def test_covers_without_a_face_do_not_ask_for_singing():
    assert "sing" not in pick_prompt("object").lower()
    assert "sing" not in pick_prompt("landscape").lower()


def test_style_and_extra_are_included():
    p = pick_prompt("performer", style="warm key", extra="No smoke.")
    assert "warm key" in p and p.endswith("No smoke.")


def test_unknown_cover_type_raises():
    with pytest.raises(ValueError):
        pick_prompt("album")


def test_player_prompt_names_the_part_and_keeps_hands_in_frame():
    p = pick_player_prompt("drums", "strikes the kit, sticks on every snare.")
    assert "drums part heard in <Audio 1>" in p and "sticks on every snare." in p
    assert "Hands and the instrument stay in frame" in p and "<Picture 1>" in p


def test_singer_defaults_to_the_audio_driven_lane_and_vocals_stem():
    p = parse_performers([{"role": "singer"}])[0]
    assert (p.lane, p.stem, p.audio, p.id) == ("h3-audio", "vocals", "mix", "p1")


def test_instrument_defaults_to_the_unproven_prompt_lane_and_its_stem():
    p = parse_performers([{"role": "keys", "verb": "plays chords"}])[0]
    assert (p.lane, p.stem, p.audio) == ("h3", "piano", "stem")


def test_an_instrument_is_never_labelled_audio_driven_and_a_singer_never_prompt_driven():
    assert parse_performers([{"role": "drums", "verb": "plays", "lane": "h3-audio"}])[0].lane == "h3"
    assert parse_performers([{"role": "singer", "lane": "h3"}])[0].lane == "h3-audio"


def test_validation():
    for bad in (
        [{"role": "kazoo"}],
        [{"role": "drums", "verb": "plays", "lane": "magic"}],
        [{"role": "drums"}],                                           # instrument without a verb
        [{"role": "singer", "stem": "kazoo"}],
        [{"role": "singer", "x": 1000, "w": 500}],                     # square runs off the 1248 cover
        [{"role": "singer", "audio": "radio"}],
        [{"id": "a", "role": "singer"}, {"id": "a", "role": "singer"}],
    ):
        with pytest.raises(PlayerError):
            parse_performers(bad)


def test_perfcap_needs_no_verb_and_is_flagged_not_built():
    p = parse_performers([{"role": "drums", "lane": "perfcap"}])[0]
    assert any("not built" in n for n in notes_for(p, True))


def test_instrument_notes_say_unproven_and_quiet_stems_are_flagged():
    p = parse_performers([{"role": "guitar", "verb": "strums"}])[0]
    n = notes_for(p, False)
    assert any("unproven" in x for x in n) and any("quiet" in x for x in n)
    assert notes_for(parse_performers([{"role": "singer"}])[0], None) == []


def test_layout_and_whole_cover_stand_in():
    assert layout_of(parse_performers([{"role": "singer", "x": 10, "y": 20, "w": 300}])[0], 1248) == (10, 20, 300)
    wc = whole_cover(1248, "media/cover.png")
    assert wc.role == "cover" and layout_of(wc, 1248) == (0, 0, 1248)
