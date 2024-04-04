import re

from collections import defaultdict
from typing import Dict, List

import sublime_plugin
from sublime import Edit, Region, View
from sublime_api import view_cached_substr as substr  # pyright: ignore
from sublime_api import view_size  # pyright: ignore
from sublime_api import view_line_from_point as line_from_point  # pyright: ignore
from sublime_api import view_selection_add_point as add_point  # pyright: ignore
from sublime_api import view_selection_add_point as add_pt  # pyright: ignore
from sublime_api import view_selection_add_region as add_region  # pyright: ignore
from sublime_api import view_selection_get as ith_selection  # pyright: ignore
from sublime_api import view_selection_size as selection_length  # pyright: ignore
from sublime_api import (  # pyright: ignore
    view_selection_subtract_region as subtract_region,
)
from sublime_api import view_show_point as show_point  # pyright: ignore
from sublime_plugin import TextCommand

from .base import buffer_slice, selections

class ClearSelectionCommand(sublime_plugin.TextCommand):
    def run(self, _, forward: bool = True) -> None:
        v = self.view
        vid = v.view_id
        regs = selections(v.view_id)
        v.sel().clear()
        for pt in [p.end() for p in regs] if forward else [p.begin() for p in regs]:
            add_pt(vid, pt)



class AlignCursors(TextCommand):
    def run(self, edit: Edit):
        v = self.view
        max_point = max(v.rowcol(r.b)[1] for r in v.sel()) or 0

        for cursor in reversed(v.sel()):
            _, point = v.rowcol(cursor.b)
            if point < max_point:
                v.insert(edit, cursor.b, " " * (max_point - point))


view_directions = {}


class SmarterSelectLines(TextCommand):
    def run(self, edit, forward: bool, force_expand=False, follow_column=False):
        v = self.view
        vid = v.id()
        s = selections(vid)
        reg_lines = {}
        nextlines = {}

        for r in s:
            l = line_from_point(vid, r.b)
            nextlines[l.a - 1 if forward else l.b + 1] = l
            reg_lines[r.a, r.b] = l

        if len(nextlines) == 0:
            return

        global view_directions
        if len(nextlines) == 1 or force_expand:
            view_directions[vid] = forward

        elif view_directions.get(vid, not forward) is not forward:
            l = v.line(s[0 if forward else -1])
            for r in s:
                if l.a <= r.begin() <= l.b and l.a <= r.end() <= l.b:
                    subtract_region(vid, r.a, r.b)
            v.show(v.sel()[0 if forward else -1])

            return

        hardeol = any(r.begin() != v.line(r.begin()).a for r in s) and all(
            r.end() == v.line(r.end()).b for r in s
        )
        columns = []
        size = view_size(vid)
        for (a, b), line in reg_lines.items():
            offset_end = b - line.a
            offset_start = a - line.a
            while line.b <= size and line.a >= 0:
                line = nextlines.get(line.b) or nextlines.setdefault(
                    line.b,
                    line_from_point(vid, line.b + 1 if forward else line.a - 1),
                )
                if hardeol:
                    columns.append((line.b - abs(a - b), line.b))
                    break

                if not follow_column:
                    start = min(line.a + offset_start, line.b)
                    end = min(line.b, line.a + offset_end)
                    columns.append((start, end))
                    break

                if follow_column and len(line) >= max(offset_start, offset_end):
                    columns.append((line.a + offset_start, line.a + offset_end))
                    break

        for r in columns:
            add_region(vid, r[0], r[1], -1)

        v.show(v.sel()[-1 if forward else 0])


class SubtractSelectionCommand(TextCommand):
    def run(self, _, last=False) -> None:
        selections = self.view.sel()
        if len(selections) > 1:
            sel = -1 if last else 0
            selections.subtract(selections[sel])
            self.view.show(selections[sel].b, True)


class RecordSelectionsCommand(TextCommand):
    recorded_selections = {}

    def run(self, edit, retrieve: bool = False):
        vi = self.view.id()
        if retrieve:
            for r in self.recorded_selections.get(vi, []):
                add_region(vi, r[0], r[1], 0.0)
        else:
            sels = self.view.sel()
            self.recorded_selections[vi] = [(r.a, r.b) for r in sels]


class FindNextWholeCommand(TextCommand):
    """Ensures word boundaries are respected when looking for the next word"""

    def run(self, edit, forward: bool = True):
        v: View = self.view
        v.run_command("clear_selection", args={"forward": True})
        v.run_command("find_under_expand")
        if forward:
            v.run_command("find_next")
        else:
            v.run_command("find_prev")


class SmarterFindUnderExpand(TextCommand):
    def run(
        self, _, forward: bool = True, skip: bool = False, find_all: bool = False
    ) -> None:
        v = self.view
        vid = self.view.id()
        s = self.view.sel()
        word_separators = re.escape(v.settings().get("word_separators"))
        word_start = f"(^|\\b(?<=[{word_separators}\\s]))"
        word_end = f"((?=[{word_separators}\\s])|\\b|$)"

        b_iter_f = buffer_slice(v, forward)
        b_iter_f.send(None)

        first = max(s[0].begin() - 1, 0)
        last = min(s[-1].end() + 1, v.size())

        buf = f"\a{substr(vid, first, last)}\a"

        words: Dict[str, List[Region]] = defaultdict(list)
        compiled_regexes = {}
        for reg in s if forward else reversed(s):
            if reg.a == reg.b:
                continue
            surroundings = buf[reg.begin() - first : reg.end() + 2 - first]
            if not forward:
                surroundings = surroundings[::-1]

            word = surroundings[1:-1]
            words[word].append(reg)

            if word not in compiled_regexes:
                compiled_regexes[word] = re.compile(
                    word_start + re.escape(word) + word_end
                )

            regex = compiled_regexes[word]

            if not regex.search(surroundings):
                compiled_regexes[word] = re.compile(re.escape(word))

        for word, regs in words.items():
            a, b = regs[-1]
            idx = (0, 0) if find_all else (b, a) if (a > b) is forward else (a, b)
            revert = all(reg.a > reg.b for reg in regs) is forward

            while (idx := b_iter_f.send((idx[1], compiled_regexes[word])))[0]:
                add_region(vid, *(idx[::-1] if revert else idx), 0.0)
                if skip:
                    subtract_region(vid, a, b)
                if not find_all:
                    break

        show_point(vid, s[-1 if forward else 0].b, True, False, True)


class MultipleCursorsFromSelectionCommand(TextCommand):
    def run(self, _, after: bool = False) -> None:
        v = self.view
        vi = v.id()
        selections = [ith_selection(vi, i) for i in range(0, selection_length(vi))]
        if all(r.a == r.b for r in selections):
            return
        pts = []
        for r in selections:
            line = v.line(r.begin())
            while line.a < r.end() and line.b <= v.size():
                pts.append(line.b if after else line.a)
                line = v.line(line.b + 1)

        v.sel().clear()
        for pt in pts:
            add_point(vi, pt)


class RevertSelectionCommand(TextCommand):
    def run(self, _) -> None:
        buf = self.view
        sel = buf.sel()
        if all(r.a == r.b for r in sel):
            _, viewport_y = buf.viewport_extent()
            _, view_y_begin = buf.viewport_position()
            view_y_end = view_y_begin + viewport_y

            _, first_cur_y = buf.text_to_layout(sel[0].b)
            if view_y_begin < first_cur_y < view_y_end:
                buf.show(sel[-1].b, True)
            else:
                buf.show(sel[0].b, True)

        else:
            for reg in sel:
                if reg.empty():
                    continue
                region = Region(reg.b, reg.a)
                sel.subtract(reg)
                sel.add(region)

            buf.show(sel[-1].b, True)


class SingleSelectionCommand(TextCommand):
    def run(self, _, index: int = 0) -> None:
        buf = self.view
        reg = buf.sel()[index]
        buf.sel().clear()
        buf.sel().add(reg)
        buf.show_at_center(reg.b)


class SmartFindWordCommand(sublime_plugin.TextCommand):
    def run(self, _) -> None:
        v = self.view
        vid = v.view_id
        s = selections(vid)
        word_separators = re.escape(v.settings().get("word_separators"))
        word = re.compile(f"[^{word_separators}\\s]+")

        b_iter = buffer_slice(v, True)
        b_iter.send(None)

        b_iterb = buffer_slice(v, False)
        b_iterb.send(None)
        pts = []
        for reg in s:
            caret = reg.b

            candidatef_priority = 0
            candidateb_priority = 0

            b_end, b_start = b_iterb.send((caret, word))
            f_start, f_end = b_iter.send((caret, word))
            if f_start is None and b_end is None:
                continue

            current_line_end = v.full_line(caret).b

            if f_start is not None and current_line_end == v.full_line(f_start).b:
                candidatef_priority += 1

            if b_end is not None and current_line_end == v.full_line(b_end).b:
                candidateb_priority += 1

            if candidateb_priority > candidatef_priority:
                candidate = (b_start, b_end)
            elif candidateb_priority < candidatef_priority:
                candidate = (f_start, f_end)
            elif b_end == f_start:
                candidate = (b_start, f_end)
            elif (caret - b_end) < (f_start - caret):
                candidate = (b_start, b_end)
            else:
                candidate = (f_start, f_end)
            pts.append(candidate)

        if not pts:
            return

        self.view.sel().clear()
        for a, b in pts:
            add_region(vid, a, b, -1)
