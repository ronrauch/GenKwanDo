import pytest

from cutting_room_lite.planner import FPS, PlanError, plan_windows, total_deliver_frames


def test_thirty_seconds_is_three_even_windows():
    w = plan_windows(0, 30)
    assert len(w) == 3
    assert [x.deliver_frames for x in w] == [240, 240, 240]
    assert total_deliver_frames(w) == 720


def test_later_windows_render_one_guide_frame_and_start_audio_a_frame_early():
    w = plan_windows(0, 30)
    assert [x.render_frames for x in w] == [240, 241, 241]
    assert [x.drop_first for x in w] == [False, True, True]
    assert w[0].audio_start_s == 0
    assert w[1].audio_start_s == pytest.approx(10 - 1 / FPS, abs=1e-5)
    assert w[1].audio_dur_s == pytest.approx(241 / FPS, abs=1e-5)


def test_windows_tile_the_slice_without_gaps():
    w = plan_windows(12.5, 31)
    assert total_deliver_frames(w) == round(31 * FPS)
    for a, b in zip(w, w[1:]):
        assert b.start_s == pytest.approx(a.start_s + a.deliver_frames / FPS, abs=1e-5)
    assert w[0].start_s == 12.5


def test_remainder_frames_go_to_the_earlier_windows():
    w = plan_windows(0, 30.04)  # 721 frames over 3 windows
    assert [x.deliver_frames for x in w] == [241, 240, 240]


def test_short_slice_is_one_window():
    w = plan_windows(3, 6)
    assert len(w) == 1 and not w[0].drop_first and w[0].render_frames == 144


def test_longest_window_stays_inside_the_proven_limit():
    for length in (30, 25, 45, 61):
        for win in plan_windows(0, length):
            assert win.render_frames / FPS <= 12.4


@pytest.mark.parametrize("start,length,window", [(-1, 30, 10), (0, 0, 10), (0, -5, 10), (0, 30, 0), (0, 30, 13)])
def test_bad_input_is_rejected(start, length, window):
    with pytest.raises(PlanError):
        plan_windows(start, length, window_s=window)
