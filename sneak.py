import enum
import re
from typing import Callable, Optional, Tuple

import sublime_plugin
from sublime import NO_UNDO, Edit, PhantomLayout, PopupFlags, Region, Selection
from sublime_api import view_selection_add_point as add_point  # pyright: ignore
from sublime_api import view_selection_add_region as add_region  # pyright: ignore

from .base import NUMBERS, buffer_slice, cursor_animate

error = "region.redish"
success = "region.bluish"
NOFLAG = 0


class SneakStatus(enum.IntFlag):
    NONE = 0
    REPEAT = 1
    HAS_MATCH = 2
    NEW_SEARCH = 4
    WAITING = 8
    END_OF_BUFFER = 16


def get_html(color: str, size: str = "1rem", bold: bool = False) -> str:
    return f"""<body
        style="
            font-size: {size};
            {"font-weight: bold;" if bold else ""}
            padding: 0;
            margin: 0;
            border-width: 0;
            color:{color};
        ">
        {{char}}</body>"""


class SneakCommand(sublime_plugin.TextCommand):
    def execute(
        self,
        search_string: str,
        forward: bool,
        extend: bool,
        offset: int,
        escape_regex: bool,
    ) -> Tuple[bool, Callable]:
        v = self.view
        vid = v.view_id

        s = v.sel()
        if not forward:
            search_string = search_string[::-1]

        flags = NOFLAG
        if search_string.islower():  # smartcase
            flags |= re.IGNORECASE
        if escape_regex:
            search_string = re.escape(search_string)
        rgx = re.compile(search_string, flags)

        vid = v.id()
        b_iter = buffer_slice(v, forward)
        b_iter.send(None)

        cursors = []
        seen = set()
        for _, end in s if forward else reversed(s):
            end += offset
            while (m := b_iter.send((end, rgx)))[0] is not None:
                start, end = m
                if start not in seen:
                    seen.add(start)
                    cursors.append(m)
                    break

        if not cursors:
            return False, lambda: None

        if forward and extend:
            cursors = [(r.begin(), a) for r, (a, _) in zip(s, cursors)]
        elif not forward and extend:
            cursors = [(r.end(), b) for r, (_, b) in zip(reversed(s), cursors)]
        elif forward and not extend:
            cursors = [(a, a) for (a, _) in cursors]
        elif not forward and not extend:
            cursors = [(b, b) for (_, b) in cursors]

        s.clear()
        for cursor in cursors:
            add_region(vid, *cursor, -1)

        highlights = []
        num_highlights = len(NUMBERS) if len(s) == 1 else 1
        for _, end in s:
            for _ in range(num_highlights):
                end += 1 if forward else -1
                m = b_iter.send((end, rgx))
                if m[0] is None:
                    break
                highlights.append(m)
                end = max(*m) if forward else min(*m)

        color: str = v.style_for_scope(success)["foreground"]
        regs = [Region(*h) for h in highlights]

        def highlight_func():
            if len(s) == 1:
                base_html = get_html(color, "1.2rem", bold=True)
                for reg, number in zip(regs, NUMBERS):
                    content = base_html.format(char=number)
                    v.add_phantom("sneak.phantoms", reg, content, PhantomLayout.INLINE)

                v.settings().set("sneak.matches", highlights)

            v.add_regions("sneak.regions", regs, success, "", NO_UNDO)

        return True, highlight_func

    def reset_all(self):
        v = self.view
        s = v.settings()
        s.erase("sneak.waiting")
        s.erase("sneak.match")

        s.erase("sneak.matches")

        v.erase_phantoms("sneak.phantoms")
        v.erase_regions("sneak.regions")

    def run(
        self,
        _: Edit,
        forward: Optional[bool] = None,
        extend: Optional[bool] = None,
        character: str = "",
        keep: int = 0,
        animate_cursor: bool = True,
        escape_regex: bool = True,
    ) -> None:
        status: SneakStatus = SneakStatus.NONE

        v = self.view
        sels: Selection = v.sel()
        s = v.settings()

        if len(sels) < 1:
            add_point(v.view_id, 1)

        last_search: str = s.get("sneak.search", "")  # pyright: ignore
        search_string = last_search[:keep]
        search_string += character

        if last_search == search_string:
            status |= SneakStatus.REPEAT

        if len(search_string) < keep:
            status |= SneakStatus.WAITING

        if len(search_string) == 0:
            status |= SneakStatus.NEW_SEARCH | SneakStatus.WAITING

        if forward is None:
            forward: bool = s.get("sneak.forward", True)  # pyright: ignore
        if extend is None:
            extend: bool = s.get("sneak.extend", True)  # pyright: ignore

        highlight_func = lambda: None
        if not status & SneakStatus.NEW_SEARCH:
            # offset ensures we start looking at the correct place
            # we force move the cursor if repeating, otherwise stay
            if forward:
                offset = 1 if status & SneakStatus.REPEAT else 0
            else:
                # when moving backwards through the buffer, we need a special offset
                offset = -1 if status & SneakStatus.REPEAT else len(search_string)

            found_match, highlight_func = self.execute(
                search_string, forward, extend, offset, escape_regex
            )

            if found_match:
                status |= SneakStatus.HAS_MATCH
            else:
                status |= SneakStatus.END_OF_BUFFER

            if animate_cursor:
                cursor_animate(v, duration=0.2)

        if status & SneakStatus.WAITING:
            arrow: str = f"{search_string}_❯" if forward else f"❮{search_string}_"
        else:
            arrow: str = f"{search_string}❯" if forward else f"❮{search_string}"

        style = error if status & SneakStatus.END_OF_BUFFER else success
        color: str = v.style_for_scope(style)["foreground"]  # pyright: ignore

        # check if we have cursors in view
        for __, b in v.sel():
            if v.text_to_window(b)[0]:
                break

        # ensures the popup is shown in the right place
        # due to the reset function
        v.erase_phantoms("sneak.phantoms")
        highlight_func()

        v.show_at_center(b, False)

        v.show_popup(
            get_html(color, bold=extend).format(char=arrow),
            flags=PopupFlags.HIDE_ON_CHARACTER_EVENT,
            location=b,
            on_hide=self.reset_all,
        )
        # popup hides the previous popup, i.e. running cancel functions.

        v.erase_phantoms("sneak.phantoms")
        highlight_func()

        s.set("sneak.search", search_string)
        s.set("sneak.forward", forward)
        s.set("sneak.extend", extend)

        s.set("sneak.match", bool(status & SneakStatus.HAS_MATCH))
        s.set("sneak.waiting", bool(status & SneakStatus.WAITING))


class SneakNthMatchCommand(sublime_plugin.TextCommand):
    def run(self, _, match: int) -> None:
        v = self.view
        vid = v.view_id
        sels: Selection = v.sel()

        matches = self.view.settings().get("sneak.matches") or []
        if len(matches) <= match:
            cursor_animate(v, duration=0.2)
            v.hide_popup()  # remove highlights
            return

        region = sels[0]
        num: Tuple[int, int] = matches[match]
        pt = min(num)

        start = region.a if v.settings().get("sneak.extend") else pt

        sels.clear()
        add_region(vid, start, pt, -1)

        if not v.text_to_window(num[1])[0]:
            v.show_at_center(num[1], False)
        cursor_animate(v, duration=0.2)
