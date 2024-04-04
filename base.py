import re
import time
from re import Pattern
from typing import Generator, List, Optional, Tuple, Union

from sublime import Region, View
from sublime_api import settings_set  # pyright: ignore
from sublime_api import view_selection_get  # pyright: ignore
from sublime_api import view_selection_size  # pyright: ignore
from sublime_api import view_settings  # pyright: ignore
from sublime_api import window_views  # pyright: ignore
from sublime_api import view_cached_substr as substr  # pyright: ignore
from sublime_plugin import sublime  # pyright: ignore

HIGHLIGHT_REGIONS = "highlight_regions"

cursor_steps = [1, 2, 3, 4]
NUMBERS = ["➊", "➋", "➌", "➍", "➎", "➏", "➐", "➑", "➒", "🄌"]


mutex = False
queue = False


def has_space_and_alnum(s):
    return any(char.isspace() for char in s) and any(char.isalnum() for char in s)


def selection_has_space_and_alnum(vid, sel):
    return any(has_space_and_alnum(substr(vid, r.a, r.b)) for r in sel if r.a != r.b)


def max_views(win_id) -> int:
    view_ids = sorted(window_views(win_id, True))
    return view_ids[-1]


def cursor_animate(v: View, grow: Optional[bool] = None, duration: float = 0.1):
    global mutex
    global queue
    queue = True
    if mutex:
        return
    mutex = True
    set_id = view_settings(v.view_id)
    grow = grow if grow is not None else view_selection_size(v.view_id) > 1
    steps = cursor_steps if grow else cursor_steps[::-1]
    timestep = duration / len(steps)

    def async_animate():
        global mutex
        global queue
        queue = False
        i = 0
        while i < len(steps):
            time.sleep(timestep)
            step = steps[i]
            settings_set(set_id, "caret_extra_width", step)
            if queue:
                i = 0
                queue = False
            else:
                i+= 1
        mutex = False

    sublime.set_timeout_async(async_animate, 0)


def selections(vid: int, reverse: bool = False) -> List[Region]:
    n = view_selection_size(vid)
    if reverse:
        return [view_selection_get(vid, i) for i in range(n - 1, -1, -1)]
    else:
        return [view_selection_get(vid, i) for i in range(n)]


def buffer_slice(
    v: View,
    forward: bool,
    default_yield_border: bool = False,
    respect_folds: bool = True,
    chunksize: int = 10_000,
) -> Generator[Union[Tuple[None, None], Tuple[int, int]], Tuple[int, Pattern], None]:
    vid = v.id()

    first = 0
    last = v.size()

    if default_yield_border:
        default_yield = (last, last) if forward else (first, first)
    else:
        default_yield = (None, None)

    unfolded = []
    if respect_folds:
        for fold_start, fold_end in v.folded_regions():
            unfolded.append((first, fold_start))
            first = fold_end
    unfolded.append((first, last))

    index, pattern = yield (None, None)
    if not isinstance(pattern, Pattern):
        raise Exception("the pattern is not a Pattern", pattern)

    regions = []
    pt = -1
    for a, b in unfolded:
        while pt < b:
            pt = min((index if index > a else last), b, v.line(a + chunksize).b)
            regions.append((a, pt))
            a = pt

    buffers = {}

    if not forward:
        regions = regions[::-1]

    def get_chunk(idx: int) -> Tuple[str, int, int]:
        if forward:
            start, end = next((start, end) for start, end in regions if idx < end)
        else:
            start, end = next((start, end) for start, end in regions if idx > start)

        if not (piece := buffers.get(start)):
            piece = substr(vid, start, end)
            if not forward:
                piece = piece[::-1]
            buffers[start] = piece
        return piece, start, end

    while True:
        while not forward and index <= 0:
            index, new_pattern = yield default_yield
        while forward and index >= last:
            index, new_pattern = yield default_yield
        piece, start, end = get_chunk(index)
        offset = (index - start) if forward else (end - index)
        for m in re.finditer(pattern, piece[offset:]):
            if forward:
                mstart = start + offset + m.start()
                mend = start + offset + m.end()
            else:
                mstart = end - offset - m.start()
                mend = end - offset - m.end()

            index, new_pattern = yield (mstart, mend)
            if index != mend or new_pattern != pattern:  # new region
                pattern = new_pattern
                break

        else:
            index = end + 1 if forward else start - 1
