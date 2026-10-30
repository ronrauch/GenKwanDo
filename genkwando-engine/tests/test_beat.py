import math

import pytest

from cutting_room_lite import beat as B
from cutting_room_lite import media
from cutting_room_lite.players import PlayerError, parse_performers
from cutting_room_lite.project import Project, ProjectError
from conftest import make_hits, near, needs_ffmpeg, pixel

FPS = 24
BOX = (60, 300, 500)
CANVAS = 1248


# ---- onset detection on synthetic stems ----------------------------------------------------------------

@needs_ffmpeg
@pytest.mark.parametrize("kind,effect", [("kick", "pulse"), ("snare", "flash")])
def test_onsets_land_on_the_hits_within_25ms(tmp_path, kind, effect):
    stem = tmp_path / f"{kind}.wav"
    want = make_hits(stem, kind, seconds=4.0, bpm=120, offset=0.25)
    got = B.analyze(str(stem), 0, 4.0, effect)["onsets"]
    assert len(got) == len(want) == 8
    assert all(abs(g - w) <= 0.025 for g, w in zip(got, want)), (got, want)


@needs_ffmpeg
def test_a_silent_stem_has_no_onsets_and_a_flat_envelope(assets):
    info = B.analyze(str(assets / "silent.wav"), 0, 4.0, "pulse")
    assert info["onsets"] == [] and set(info["envelope"]) == {0.0} and info["frames"] == 96


@needs_ffmpeg
def test_the_slice_start_is_respected(tmp_path):
    stem = tmp_path / "k.wav"
    make_hits(stem, "kick", seconds=6.0, bpm=120, offset=0.25)
    got = B.analyze(str(stem), 2.0, 2.0, "pulse")["onsets"]      # hits at 2.25, 2.75, 3.25, 3.75 -> 0.25, ...
    assert len(got) == 4 and abs(got[0] - 0.25) <= 0.025


@needs_ffmpeg
def test_envelope_follows_a_swelling_stem(tmp_path):
    stem = tmp_path / "h.wav"
    make_hits(stem, "hum", seconds=4.0)
    env = B.analyze(str(stem), 0, 4.0, "glow")["envelope"]
    assert len(env) == 96 and all(0 <= e <= 1 for e in env) and max(env) > 0.9
    assert env[12] > 1.5 * env[36] and env[60] > 1.5 * env[36]   # swells at 0.5 s, dips at 1.5 s, swells again


def test_hop_rms_and_detector_on_plain_numbers():
    flat = [0.0] * 40
    burst = [0.0] * 10 + [0.5, 0.4, 0.3, 0.2] + [0.0] * 26
    assert B.detect_onsets(flat) == []
    assert len(B.detect_onsets(burst)) == 1
    assert B.hop_rms([0, 0, 0, 0] * 64) == [0.0] * 1


# ---- frame transforms: deterministic, decaying, clamped ----------------------------------------------

def pulse(onsets=(0.25, 0.75), strength=1.0, decay=0.18, frames=48):
    return B.frame_transforms("pulse", strength, decay, list(onsets), [0.0] * frames, FPS, frames, BOX, CANVAS)


def test_pulse_is_flat_then_peaks_on_the_hit_frame_then_decays():
    z = [t.zoom for t in pulse()]
    assert z[:6] == [1.0] * 6                              # nothing before the first hit (frame 6)
    assert z[6] == pytest.approx(1.3)                      # full strength on the hit frame
    assert all(a > b for a, b in zip(z[6:17], z[7:18]))    # strictly settling between hits
    assert z[17] < 1.03                                    # almost settled
    assert z[18] == pytest.approx(1.3)                     # second hit at 0.75 s = frame 18


def test_transforms_are_deterministic():
    assert pulse() == pulse()
    a = B.frame_transforms("flash", 0.8, 0.1, [0.5], [0.0] * 48, FPS, 48, BOX, CANVAS)
    assert a == B.frame_transforms("flash", 0.8, 0.1, [0.5], [0.0] * 48, FPS, 48, BOX, CANVAS)


def test_strength_scales_the_effect_and_zero_is_off():
    assert max(t.zoom for t in pulse(strength=0.5)) == pytest.approx(1.15)
    assert all(t == B.Transform() for t in pulse(strength=0.0))
    assert max(t.zoom for t in pulse(strength=9.0)) == pytest.approx(1.3)   # strength is capped at 1


def test_decay_sets_how_fast_it_settles():
    fast = [t.zoom for t in pulse(decay=0.05)]
    slow = [t.zoom for t in pulse(decay=0.5)]
    assert fast[10] < slow[10]


def test_flash_brightens_and_shakes_on_the_hit_then_settles():
    t = B.frame_transforms("flash", 1.0, 0.10, [0.5], [0.0] * 48, FPS, 48, BOX, CANVAS)
    assert t[11].brightness == 0.0 and t[12].brightness == pytest.approx(0.5)  # 0.6 capped by the 0.5 clamp
    assert (t[12].dx, t[12].dy) != (0.0, 0.0) and abs(t[12].dx) <= 14 and abs(t[12].dy) <= 14
    assert abs(t[24].dx) < 0.1 and t[24].brightness < 0.01


def test_glow_follows_the_envelope_and_releases():
    env = [0.0] * 5 + [0.2, 0.5, 0.9, 1.0] + [0.0] * 20
    t = B.frame_transforms("glow", 1.0, 0.25, [], env, FPS, len(env), BOX, CANVAS)
    b = [x.brightness for x in t]
    assert b[:5] == [0.0] * 5 and b[5] < b[6] < b[7] < b[8]
    assert b[8] == pytest.approx(0.35) and b[9] < b[8] and b[-1] < 0.02


def test_sway_rotates_and_drifts_only_while_the_stem_is_loud():
    env = [0.0] * 10 + [1.0] * 24 + [0.0] * 14
    t = B.frame_transforms("sway", 1.0, 0.3, [], env, FPS, len(env), BOX, CANVAS)
    assert all(x.angle == 0 and x.dx == 0 for x in t[:10])
    assert max(abs(x.angle) for x in t[10:34]) > 0.05 and max(abs(x.dx) for x in t[10:34]) > 8


def test_clamp_keeps_the_square_on_the_cover():
    corner = B.clamp_transform(B.Transform(zoom=9, angle=3, brightness=2, dx=-500, dy=-500), (0, 0, 500), CANVAS)
    assert (corner.dx, corner.dy) == (0, 0) and corner.zoom == B.MAX_ZOOM
    assert corner.angle == B.MAX_ANGLE and corner.brightness == B.MAX_BRIGHT
    far = B.clamp_transform(B.Transform(dx=900, dy=900), (700, 700, 500), CANVAS)
    assert (far.dx, far.dy) == (48, 48)                       # 1248 - 700 - 500
    for effect in B.EFFECTS:
        for tr in B.frame_transforms(effect, 1.0, 0.0, [0.1 * i for i in range(1, 9)], [1.0] * 48, FPS, 48, (0, 0, 1248), CANVAS):
            assert tr.dx == 0 and tr.dy == 0                    # a full-canvas layer cannot move at all


def test_unknown_effect_is_refused():
    with pytest.raises(B.BeatError):
        B.frame_transforms("wobble", 1, 0, [], [], FPS, 4, BOX, CANVAS)


def test_pw_expr_is_shallow_and_collapses_constants():
    assert B.pw_expr([0.0] * 50) == "0"
    e = B.pw_expr([i / 100 for i in range(720)])
    assert e.count("if(") == 719 and len(e) < 25000
    depth = best = 0
    for tok in e.replace("if(", "\x00").replace(")", "\x01"):
        depth += tok == "\x00"
        best = max(best, depth)
        depth -= tok == "\x01" and 0
    assert e.startswith("if(lt(n,360),")


# ---- performer validation -----------------------------------------------------------------------------

def test_beat_performer_defaults_and_validation():
    p = parse_performers([{"role": "beat", "stem": "drums"}])[0]
    assert (p.lane, p.effect, p.strength, p.decay) == ("comp", "pulse", 0.6, 0.0) and p.verb == ""
    assert parse_performers([{"role": "beat", "stem": "bass"}])[0].effect == "sway"
    assert parse_performers([{"role": "beat", "stem": "other"}])[0].effect == "glow"
    assert parse_performers([{"role": "beat", "stem": "drums", "effect": "flash", "strength": 1, "decay": 0.2}])[0].effect == "flash"
    for bad in ({"effect": "wobble"}, {"strength": 1.5}, {"strength": -0.1}, {"decay": 9}):
        with pytest.raises(PlayerError):
            parse_performers([{"role": "beat", **bad}])
    with pytest.raises(PlayerError):
        parse_performers([{"role": "drums", "verb": "plays", "lane": "comp"}])   # only a beat object uses comp


def test_beat_objects_are_labelled_as_effects_not_instruments():
    p = parse_performers([{"role": "beat"}])[0]
    from cutting_room_lite.players import notes_for
    n = notes_for(p, True)
    assert len(n) == 1 and "visual effect" in n[0] and "Not a played instrument" in n[0]
    assert "NOT" not in p.to_dict()["status"] and "not a played instrument" in p.to_dict()["status"]


# ---- COMP: the pixels move on a hit and settle between hits -----------------------------------------

@pytest.fixture
def object_still(tmp_path):
    """A 500px green square with a 120px red object in the middle (so zoom has somewhere to grow)."""
    img = tmp_path / "obj.png"
    media.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=500x500", "-vf",
               "drawbox=x=190:y=190:w=120:h=120:color=red:t=fill", "-frames:v", "1", str(img)])
    cover = tmp_path / "cover.png"
    media.run(media.make_color_image(str(cover), "gray", 1248))
    return img, cover


def comp_with(tmp_path, object_still, effect, onsets, frames=36, strength=1.0, decay=0.18):
    img, cover = object_still
    trs = B.frame_transforms(effect, strength, decay, onsets, [0.0] * frames, FPS, frames, BOX, CANVAS)
    layer = {"still": str(img), "x": 60, "y": 300, "w": 500, "matte": None,
             "beat": {"zoom": [t.zoom for t in trs], "angle": [t.angle for t in trs], "bright": [t.brightness for t in trs],
                      "dx": [t.dx for t in trs], "dy": [t.dy for t in trs]}}
    out = tmp_path / f"comp_{effect}.mp4"
    media.run(media.comp_cmd(str(cover), [layer], str(out), frames, 1248))
    return out


def at(f):
    return f / FPS + 0.01


@needs_ffmpeg
def test_pulse_grows_on_the_hit_and_settles_between_hits(tmp_path, object_still):
    out = comp_with(tmp_path, object_still, "pulse", [5 / FPS])           # a hit on frame 5
    probe = (380, 550)                                                    # 70 px right of the object's centre
    assert near(pixel(out, at(3), *probe), (0, 128, 0), 20)               # before the hit: the green around the object
    assert near(pixel(out, at(5), *probe), (255, 0, 0), 30)               # on the hit: the object has grown over it
    assert near(pixel(out, at(6), *probe), (255, 0, 0), 30)               # still big a frame later
    assert near(pixel(out, at(22), *probe), (0, 128, 0), 20)              # settled back between hits
    assert near(pixel(out, at(5), 310, 550), (255, 0, 0), 30)             # the object itself stays red


@needs_ffmpeg
def test_flash_brightens_on_the_hit_and_settles(tmp_path, object_still):
    out = comp_with(tmp_path, object_still, "flash", [5 / FPS], decay=0.10)
    probe = (90, 700)                                                     # inside the green, away from the shake edge
    base = pixel(out, at(2), *probe)[1]
    assert pixel(out, at(5), *probe)[1] > base + 40                       # brighter on the hit
    assert abs(pixel(out, at(30), *probe)[1] - base) < 6                  # settled


@needs_ffmpeg
def test_a_shift_moves_the_layer_on_the_cover(tmp_path, object_still):
    img, cover = object_still
    frames = 12
    layer = {"still": str(img), "x": 60, "y": 300, "w": 500, "matte": None,
             "beat": {"zoom": [1.0] * frames, "angle": [0.0] * frames, "bright": [0.0] * frames,
                      "dx": [0.0] * 5 + [40.0] * 7, "dy": [0.0] * frames}}
    out = tmp_path / "shift.mp4"
    media.run(media.comp_cmd(str(cover), [layer], str(out), frames, 1248))
    assert near(pixel(out, at(2), 70, 700), (0, 128, 0), 20)             # layer's left edge is at x=60
    assert near(pixel(out, at(8), 70, 700), (128, 128, 128), 20)         # shifted right by 40: the cover shows again
    assert near(pixel(out, at(8), 110, 700), (0, 128, 0), 20)


# ---- the project: a beat-only cover assembles with no render at all -----------------------------------

@needs_ffmpeg
def test_beat_only_project_assembles_without_any_render(tmp_path, assets):
    stems = tmp_path / "stems"
    stems.mkdir()
    make_hits(stems / "drums.wav", "kick", seconds=40.0, bpm=120, offset=0.25)
    media.run(media.make_color_image(str(tmp_path / "drum.png"), "red"))
    pr = Project(tmp_path / "p")
    pr.set_cover(assets / "cover.png")
    pr.set_song(assets / "song.wav")
    pr.set_stems(stems)
    pr.configure(name="b", slice_start=0, slice_length=30,
                 performers=[{"id": "drum", "role": "beat", "stem": "drums", "effect": "pulse", "strength": 0.8,
                              "x": 60, "y": 300, "w": 500}])
    pr.set_performer_image("drum", tmp_path / "drum.png")
    wins = pr.plan()
    assert wins[0]["tracks"] == {}                                        # no prompt, no takes, no render
    with pytest.raises(ProjectError, match="never rendered"):
        pr.render(0, "drum")
    assert pr.public()["ready_to_assemble"]
    info = pr.assemble()
    assert info["file"] == "out/final.mp4" and not info["placeholder"]    # no placeholder: nothing stood in for H3
    assert info["frames"] == info["expected_frames"] == 720 and info["duration"] == pytest.approx(30.0, abs=0.05)
    assert info["beat"]["drum"]["effect"] == "pulse" and info["beat"]["drum"]["from_stem"] is True
    assert len(info["beat"]["drum"]["onsets"]) == 60                      # a hit every half second from 0.25 s
    assert info["composed"] == [] and info["left_static"] == []
    video = pr.root / info["file"]
    assert media.probe_frames(str(video)) == 720


@needs_ffmpeg
def test_a_beat_object_can_ride_the_mix_when_there_is_no_stem(tmp_path, assets):
    media.run(media.make_color_image(str(tmp_path / "o.png"), "red"))
    pr = Project(tmp_path / "p")
    pr.set_cover(assets / "cover.png")
    pr.set_song(assets / "song.wav")
    pr.configure(slice_start=0, slice_length=10,
                 performers=[{"id": "spk", "role": "beat", "stem": "other", "x": 0, "y": 0, "w": 400}])
    pr.set_performer_image("spk", tmp_path / "o.png")
    pr.plan()
    info = pr.assemble()
    assert info["beat"]["spk"]["effect"] == "glow" and info["beat"]["spk"]["from_stem"] is False


@needs_ffmpeg
def test_beat_objects_mix_with_a_rendered_performer(tmp_path, assets):
    stems = tmp_path / "stems"
    stems.mkdir()
    make_hits(stems / "drums.wav", "kick", seconds=40.0)
    for n, c in (("s", "blue"), ("d", "red")):
        media.run(media.make_color_image(str(tmp_path / f"{n}.png"), c))
    pr = Project(tmp_path / "p")
    pr.set_cover(assets / "cover.png")
    pr.set_song(assets / "song.wav")
    pr.set_stems(stems)
    pr.configure(slice_start=0, slice_length=30, performers=[
        {"id": "singer", "role": "singer", "x": 60, "y": 300, "w": 400},
        {"id": "kick", "role": "beat", "stem": "drums", "x": 700, "y": 300, "w": 400}])
    pr.set_performer_image("singer", tmp_path / "s.png")
    pr.set_performer_image("kick", tmp_path / "d.png")
    pr.plan()
    assert not pr.public()["ready_to_assemble"]                           # the singer still needs approved takes
    for k in range(3):
        pr.approve(k, "singer", pr.add_placeholder_take(k, "singer", "blue")["id"])
    info = pr.assemble()
    assert info["composed"] == ["singer"] and list(info["beat"]) == ["kick"] and info["placeholder"]
    assert info["frames"] == 720
