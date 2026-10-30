import subprocess

import pytest

from genkwando_engine import media
from conftest import near, needs_ffmpeg, pixel


def test_square_cover_crops_to_the_render_size():
    cmd = media.square_cover_cmd("in.jpg", "out.png", 1248)
    assert "scale=1248:1248:force_original_aspect_ratio=increase,crop=1248:1248" in cmd


def test_trim_audio_command_cuts_the_window_as_48k_stereo_wav():
    cmd = media.trim_audio_cmd("song.mp3", "w1.wav", 9.958333, 10.041667)
    assert cmd[cmd.index("-ss") + 1] == "9.958333" and cmd[cmd.index("-t") + 1] == "10.041667"
    assert cmd[cmd.index("-ar") + 1] == "48000" and cmd[cmd.index("-ac") + 1] == "2" and cmd[-1] == "w1.wav"
    assert media.trim_audio_cmd("s.mp3", "o.wav", -3, 1)[3] == "0.000000"  # never a negative seek


def test_segment_drops_the_repeated_guide_frame_only_on_later_windows():
    assert "select='gte(n,1)'" in " ".join(media.segment_cmd("a.mp4", "b.mp4", True))
    assert "select" not in " ".join(media.segment_cmd("a.mp4", "b.mp4", False))


def test_mux_lays_the_original_song_slice_under_the_picture():
    cmd = media.mux_cmd("pic.mp4", "song.mp3", 12.5, 30, "out.mp4")
    assert cmd[cmd.index("-ss") + 1] == "12.500000" and "song.mp3" in cmd
    assert cmd.count("-t") == 2 and "1:a:0" in cmd


def test_comp_filter_chain_overlays_each_layer_through_its_matte():
    cmd = media.comp_cmd("cover.png", [
        {"video": "a.mp4", "x": 60, "y": 300, "w": 500, "matte": "a_matte.png", "feather": 2},
        {"video": "b.mp4", "x": 688, "y": 300, "w": 500},
    ], "comp.mp4", 720)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "alphamerge" in fc and fc.count("overlay=") == 2
    assert "overlay=x=60:y=300" in fc and "overlay=x=688:y=300" in fc
    assert "[b2]format=yuv420p[out]" in fc and cmd[cmd.index("-frames:v") + 1] == "720"
    assert fc.count("alphamerge") == 1  # only the layer with a matte


def test_beat_overlay_flashes_every_beat():
    cmd = media.beat_overlay_cmd("t.mp4", "o.mp4", 120, 0.25)
    vf = cmd[cmd.index("-vf") + 1]
    assert "mod(max(t-0.2500,0),0.50000)" in vf and "drawbox" in vf


def test_concat_list_quotes_paths_with_spaces():
    assert media.concat_list_text(["/a b/seg0.mp4"]) == "file '/a b/seg0.mp4'\n"


@needs_ffmpeg
def test_waveform_peaks(assets):
    peaks = media.wave_peaks(str(assets / "song.wav"), bins=200)
    assert len(peaks) == 200 and max(peaks) > 0.3 and all(0 <= p <= 1 for p in peaks)
    assert media.probe_duration(str(assets / "song.wav")) == pytest.approx(40.0, abs=0.1)


@needs_ffmpeg
def test_stem_activity_tells_playing_from_silent(assets):
    assert media.stem_active(str(assets / "song.wav"), 0, 5) is True
    assert media.stem_active(str(assets / "silent.wav"), 0, 5) is False


@needs_ffmpeg
def test_has_alpha_and_alpha_matte_round_trip(tmp_path):
    rgba = tmp_path / "a.png"
    # left half opaque red, right half transparent
    media.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64,format=rgba",
               "-vf", "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(X,32),255,0)'", "-frames:v", "1", str(rgba)])
    rgb = tmp_path / "b.png"
    media.run(media.make_color_image(str(rgb), "blue", 64))
    assert media.has_alpha(str(rgba)) and not media.has_alpha(str(rgb))
    matte = tmp_path / "m.png"
    media.run(media.alpha_matte_cmd(str(rgba), str(matte)))
    assert pixel(matte, 0, 8, 30)[0] > 240 and pixel(matte, 0, 56, 30)[0] < 15


@needs_ffmpeg
def test_comp_puts_each_performer_at_its_position_and_the_matte_cuts_it(tmp_path):
    """SPLIT -> COMP with synthetic layers: red singer, blue drummer, flat grey cover, matte on the singer."""
    cover, a, b, matte = (tmp_path / n for n in ("cover.png", "a.mp4", "b.mp4", "m.png"))
    media.run(media.make_color_image(str(cover), "gray", 1248))
    media.run(media.make_placeholder_take(str(a), 24, size=500, color="red"))
    media.run(media.make_placeholder_take(str(b), 24, size=500, color="blue"))
    media.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=white:s=500x500", "-vf",
               "drawbox=x=250:y=0:w=250:h=500:color=black:t=fill", "-frames:v", "1", str(matte)])  # right half cut
    out = tmp_path / "comp.mp4"
    media.run(media.comp_cmd(str(cover), [
        {"video": str(a), "x": 60, "y": 300, "w": 500, "matte": str(matte), "feather": 0},
        {"video": str(b), "x": 688, "y": 300, "w": 500},
    ], str(out), 24, 1248))
    assert media.probe_frames(str(out)) == 24
    assert near(pixel(out, 0.3, 120, 500), (255, 0, 0))        # singer, inside the matte
    assert near(pixel(out, 0.3, 500, 500), (128, 128, 128))    # singer's square, matted OUT: the cover shows
    assert near(pixel(out, 0.3, 900, 500), (0, 0, 255))        # drummer, no matte, plain overlay
    assert near(pixel(out, 0.3, 20, 20), (128, 128, 128))      # untouched cover
