"""Window planner: split a song slice into H3 render windows.

H3 renders a bounded number of seconds per job (the proven graph ran ~12.4 s windows), so a 30 s slice
becomes 3 windows of ~10 s. Windows after the first start from the LAST frame of the previous window, so
each one renders one extra leading frame (the guide frame) that assembly drops again; its audio chunk
starts one frame early to match.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

FPS = 24
DEFAULT_WINDOW_S = 10.0   # target window length
HARD_MAX_WINDOW_S = 12.4  # longest window seen working in the proven two-window graph


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Window:
    index: int
    start_s: float          # where this window's DELIVERED frames start, in song time
    deliver_frames: int     # frames that end up in the cut
    render_frames: int      # frames H3 renders (deliver + 1 guide frame for index > 0)
    audio_start_s: float    # start of the audio chunk fed to H3 (one frame early for index > 0)
    audio_dur_s: float      # length of that chunk = render_frames / fps
    drop_first: bool        # assembly drops the first rendered frame (the repeated guide frame)

    @property
    def deliver_s(self) -> float:
        return self.deliver_frames / FPS

    def to_dict(self) -> dict:
        d = asdict(self)
        d["deliver_s"] = round(self.deliver_s, 4)
        return d


def plan_windows(
    slice_start: float,
    slice_len: float,
    fps: int = FPS,
    window_s: float = DEFAULT_WINDOW_S,
    hard_max_s: float = HARD_MAX_WINDOW_S,
) -> list[Window]:
    """Split [slice_start, slice_start + slice_len) into near-equal windows whose frames sum exactly."""
    if slice_start < 0:
        raise PlanError("slice start must be >= 0")
    if slice_len <= 0:
        raise PlanError("slice length must be > 0")
    if window_s <= 0 or window_s > hard_max_s:
        raise PlanError(f"window length must be in (0, {hard_max_s}] s")

    total = round(slice_len * fps)
    if total < 1:
        raise PlanError("slice is shorter than one frame")
    # aim for windows near window_s, then add windows until even the longest one (plus its guide frame) fits
    count = max(1, round(total / (window_s * fps)))
    while math.ceil(total / count) + 1 > hard_max_s * fps + 1e-9:
        count += 1
    base, extra = divmod(total, count)
    sizes = [base + (1 if i < extra else 0) for i in range(count)]  # earlier windows take the remainder

    windows: list[Window] = []
    done = 0
    for i, deliver in enumerate(sizes):
        lead = 1 if i > 0 else 0
        render = deliver + lead
        if render / fps > hard_max_s + 1e-9:
            raise PlanError(f"window {i} would render {render / fps:.2f} s, over the {hard_max_s} s limit")
        start = slice_start + done / fps
        windows.append(
            Window(
                index=i,
                start_s=round(start, 6),
                deliver_frames=deliver,
                render_frames=render,
                audio_start_s=round(start - lead / fps, 6),
                audio_dur_s=round(render / fps, 6),
                drop_first=bool(lead),
            )
        )
        done += deliver
    return windows


def total_deliver_frames(windows: list[Window]) -> int:
    return sum(w.deliver_frames for w in windows)
