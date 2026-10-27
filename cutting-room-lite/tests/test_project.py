import json
import shutil

import pytest

from cutting_room_lite import media
from cutting_room_lite.project import Project, ProjectError
from conftest import near, needs_ffmpeg, pixel

pytestmark = needs_ffmpeg

PERFS = [
    {"id": "singer", "role": "singer", "x": 60, "y": 300, "w": 500},
    {"id": "drummer", "role": "drums", "x": 688, "y": 300, "w": 500, "verb": "strikes the kit on the beat"},
]


@pytest.fixture
def whole(tmp_path, assets):
    """A project with a cover and a song and NO performer layers (the whole cover is animated as one)."""
    pr = Project(tmp_path / "p")
    pr.set_cover(assets / "cover.png")
    pr.set_song(assets / "song.wav")
    pr.configure(name="t", slice_start=0, slice_length=30)
    pr.plan()
    return pr


@pytest.fixture
def layered(tmp_path, assets):
    pr = Project(tmp_path / "p")
    pr.set_cover(assets / "cover.png")
    pr.set_song(assets / "song.wav")
    media.run(media.make_color_image(str(tmp_path / "singer.png"), "red"))
    media.run(media.make_color_image(str(tmp_path / "drummer.png"), "blue"))
    pr.configure(name="t", slice_start=0, slice_length=30, performers=PERFS)
    pr.set_performer_image("singer", tmp_path / "singer.png")
    pr.set_performer_image("drummer", tmp_path / "drummer.png")
    pr.plan()
    return pr


def test_whole_cover_plans_three_windows_with_one_track(whole):
    wins = whole.state["windows"]
    assert len(wins) == 3 and list(wins[0]["tracks"]) == ["cover"]
    assert "sings the vocal" in wins[0]["tracks"]["cover"]["prompt"]


def test_cover_is_squared_and_song_probed(whole):
    assert media.probe_duration(str(whole.path(whole.state["song"]))) == pytest.approx(40, abs=0.1)
    assert whole.state["song_duration"] == pytest.approx(40, abs=0.1)
    assert (whole.root / "media" / "cover.png").exists()


def test_dry_run_writes_graph_and_exact_audio_chunk_and_sends_nothing(whole):
    take = whole.render(1, "cover", runner=None)
    assert take["state"] == "dry-run" and take["video"] is None
    tdir = whole.root / "takes" / "cover" / "w1"
    graph = json.loads((tdir / "t001.graph.json").read_text())
    assert graph["8"]["inputs"]["length"] == 241
    assert graph["15"]["inputs"]["image"] == ["20", 0]                 # guide = previous window's last frame
    assert media.probe_duration(str(tdir / "t001_chunk.wav")) == pytest.approx(241 / 24, abs=0.03)


def test_reroll_makes_a_new_take_with_a_new_seed(whole):
    a, b = whole.render(0, "cover"), whole.render(0, "cover")
    assert (a["id"], b["id"]) == ("t001", "t002") and a["seed"] != b["seed"]
    assert whole.seed_for("cover", 0, 1) == a["seed"]                  # seeds are reproducible


def test_a_dry_run_take_cannot_be_approved(whole):
    t = whole.render(0, "cover")
    with pytest.raises(ProjectError, match="dry-run"):
        whole.approve(0, "cover", t["id"])


def test_slice_past_the_end_of_the_song_is_refused(whole):
    whole.configure(slice_start=20, slice_length=30)
    with pytest.raises(ProjectError, match="past the end"):
        whole.plan()


def test_replan_keeps_takes_when_nothing_changed_and_drops_them_when_the_slice_moves(whole):
    whole.render(0, "cover")
    whole.plan()
    assert len(whole.state["windows"][0]["tracks"]["cover"]["takes"]) == 1
    whole.configure(slice_start=2)
    whole.plan()
    assert whole.state["windows"][0]["tracks"]["cover"]["takes"] == []


def test_performers_get_their_own_prompts_images_and_tracks(layered):
    t = layered.state["windows"][0]["tracks"]
    assert set(t) == {"singer", "drummer"}
    assert "sings the vocal" in t["singer"]["prompt"]
    assert "drums part heard in <Audio 1>" in t["drummer"]["prompt"] and "strikes the kit" in t["drummer"]["prompt"]
    assert any("unproven" in n for n in t["drummer"]["notes"])
    assert t["singer"]["image"] == "media/performers/singer.png"


def test_each_performer_renders_with_its_own_clean_image_as_the_reference(layered):
    layered.render(0, "singer")
    layered.render(0, "drummer")
    g = json.loads((layered.root / "takes" / "drummer" / "w0" / "t001.graph.json").read_text())
    assert g["6"]["inputs"]["image"] == "drummer.png" and "drums part" in g["8"]["inputs"]["prompt"]
    assert g["17"]["inputs"]["filename_prefix"].startswith("cutting-room-lite/t_drummer_w0")


def test_an_instrument_can_be_driven_by_its_stem_and_a_quiet_stem_is_flagged(layered, assets):
    stems = layered.root.parent / "stems"
    stems.mkdir()
    shutil.copy(assets / "silent.wav", stems / "drums.wav")
    shutil.copy(assets / "song.wav", stems / "vocals.wav")
    assert layered.set_stems(stems) == ["drums", "vocals"]
    layered.plan()
    t = layered.state["windows"][0]["tracks"]
    assert any("quiet" in n for n in t["drummer"]["notes"]) and not any("quiet" in n for n in t["singer"]["notes"])
    layered.render(0, "drummer")
    chunk = layered.root / "takes" / "drummer" / "w0" / "t001_chunk.wav"
    assert media.stem_active(str(chunk), 0, 5) is False                 # the chunk came from the silent drums stem


def test_perfcap_lane_refuses_to_render(layered):
    layered.configure(performers=[{**PERFS[0]}, {**PERFS[1], "lane": "perfcap"}])
    layered.plan()
    with pytest.raises(ProjectError, match="not built"):
        layered.render(0, "drummer")


def test_a_performer_without_an_image_cannot_render(tmp_path, assets):
    pr = Project(tmp_path / "p")
    pr.set_cover(assets / "cover.png")
    pr.set_song(assets / "song.wav")
    pr.configure(performers=[PERFS[0]])
    pr.plan()
    with pytest.raises(ProjectError, match="no clean image"):
        pr.render(0, "singer")


class FakeRunner:
    """Stands in for the Comfy runner: writes a flat clip of the planned length, records its inputs."""

    def __init__(self):
        self.calls = []

    def run_window(self, graph, inputs, out_path, graph_path=None):
        self.calls.append({fi.node_id: fi.path for fi in inputs})
        media.run(media.make_placeholder_take(out_path, graph["8"]["inputs"]["length"], size=graph["8"]["inputs"]["width"]))
        return "fake"


def test_live_path_chains_windows_from_the_last_frame_of_the_approved_take(whole):
    r = FakeRunner()
    t0 = whole.render(0, "cover", r)
    assert t0["state"] == "done" and t0["frames"] == 240 and t0["error"] is None
    with pytest.raises(ProjectError, match="approve a take"):
        whole.render(1, "cover", r)
    whole.approve(0, "cover", t0["id"])
    t1 = whole.render(1, "cover", r)
    assert t1["state"] == "done" and t1["frames"] == 241
    assert set(r.calls[1]) == {"6", "7", "20"} and r.calls[1]["20"].endswith("_guide.png")
    assert (whole.root / "takes" / "cover" / "w1" / "t001_guide.png").exists()
    assert set(r.calls[0]) == {"6", "7"}


def test_a_short_render_is_flagged(whole):
    class Short(FakeRunner):
        def run_window(self, graph, inputs, out_path, graph_path=None):
            media.run(media.make_placeholder_take(out_path, 100, size=64))
    assert "rendered 100 frames" in whole.render(0, "cover", Short())["error"]


def test_a_failed_render_keeps_a_record(whole):
    class Boom(FakeRunner):
        def run_window(self, *a, **k):
            raise RuntimeError("402 insufficient credits")
    t = whole.render(0, "cover", Boom())
    assert t["state"] == "failed" and "402" in t["error"]


def test_assemble_refuses_until_every_window_is_approved(whole):
    with pytest.raises(ProjectError, match="no approved take"):
        whole.assemble()


def test_whole_cover_assembles_to_exactly_the_slice(whole):
    for k in range(3):
        whole.approve(k, "cover", whole.add_placeholder_take(k, "cover")["id"])
    info = whole.assemble()
    assert info["placeholder"] and info["file"] == "out/final_PLACEHOLDER.mp4" and info["composed"] == []
    assert info["frames"] == info["expected_frames"] == 720
    assert info["duration"] == pytest.approx(30.0, abs=0.05)
    assert whole.public()["ready_to_assemble"]


def test_layers_are_composed_back_over_the_cover_at_their_layout(layered):
    for k in range(3):
        layered.approve(k, "singer", layered.add_placeholder_take(k, "singer", "red")["id"])
        layered.approve(k, "drummer", layered.add_placeholder_take(k, "drummer", "blue")["id"])
    info = layered.assemble()
    assert sorted(info["composed"]) == ["drummer", "singer"] and info["frames"] == 720
    video = layered.root / info["file"]
    assert near(pixel(video, 5, 120, 500), (255, 0, 0))      # singer square
    assert near(pixel(video, 20, 900, 500), (0, 0, 255))     # drummer square, in a later window too
    assert not near(pixel(video, 5, 620, 40), (255, 0, 0))   # cover outside both squares is untouched


def test_a_performer_left_off_stays_static_on_the_cover(layered):
    layered.configure(performers=[PERFS[0], {**PERFS[1], "enabled": False}])
    layered.plan()
    for k in range(3):
        layered.approve(k, "singer", layered.add_placeholder_take(k, "singer", "red")["id"])
    info = layered.assemble()
    assert info["composed"] == ["singer"] and info["left_static"] == ["drummer"]
    assert not near(pixel(layered.root / info["file"], 5, 900, 500), (0, 0, 255))


def test_a_clean_image_with_alpha_becomes_a_matte_and_an_rgb_reference(tmp_path, assets):
    pr = Project(tmp_path / "p")
    pr.set_cover(assets / "cover.png")
    pr.configure(performers=[PERFS[0]])
    rgba = tmp_path / "a.png"
    media.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=200x200,format=rgba", "-vf",
               "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(X,100),255,0)'", "-frames:v", "1", str(rgba)])
    pr.set_performer_image("singer", rgba)
    entry = pr.state["performers"][0]
    assert entry["matte"] == "media/performers/singer_matte.png" and entry["image"] == "media/performers/singer.png"
    assert not media.has_alpha(str(pr.path(entry["image"])))
    assert pixel(pr.path(entry["matte"]), 0, 100, 600)[0] > 240 and pixel(pr.path(entry["matte"]), 0, 1100, 600)[0] < 15


def test_bad_inputs_are_refused(tmp_path, assets):
    pr = Project(tmp_path / "p")
    with pytest.raises(ProjectError):
        pr.set_cover(assets / "song.wav")
    with pytest.raises(ProjectError):
        pr.set_song(assets / "cover.png")
    with pytest.raises(ProjectError, match="first"):
        pr.set_performer_image("nobody", assets / "cover.png")
    with pytest.raises(ProjectError):
        pr.configure(cover_type="album")
