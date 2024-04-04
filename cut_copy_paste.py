import subprocess
from typing import Iterator, List, Tuple

import sublime
from sublime import Edit, Region, RegionFlags, Selection, View
from sublime_api import set_clipboard  # pyright: ignore
from sublime_api import set_timeout  # pyright: ignore
from sublime_api import view_add_regions  # pyright: ignore
from sublime_api import view_erase_regions  # pyright: ignore
from sublime_api import view_insert  # pyright: ignore
from sublime_api import view_selection_clear  # pyright: ignore
from sublime_api import view_show_region  # pyright: ignore
from sublime_api import view_cached_substr as ssubstr  # pyright: ignore
from sublime_api import view_erase as erase  # pyright: ignore
from sublime_api import view_full_line_from_point as full_line  # pyright: ignore
from sublime_api import view_selection_add_point as add_pt  # pyright: ignore
from sublime_plugin import TextCommand

from .base import selections


class SmartDuplicateLineCommand(TextCommand):
    """Ensures the cursors are put correctly on the next lines"""

    def run(self, edit: Edit):
        vid = self.view.id()
        sels = selections(vid)
        regions = {}
        for reg in sels:
            if reg.a == reg.b:
                line = full_line(vid, reg.b)
                regions[line.a] = line
            else:
                regions[reg.a] = reg

        linelist = [regions[key] for key in sorted(regions)]

        to_add = [linelist[0].a]
        for i in range(len(linelist) - 1):
            thisline = linelist[i]
            nextline = linelist[i + 1]
            if thisline.b != nextline.a:
                to_add.append(thisline.b)
                to_add.append(nextline.a)
        to_add.append(linelist[-1].b)

        for i in range(len(to_add) - 1, 0, -2):
            a = to_add[i]
            b = to_add[i - 1]
            view_insert(vid, edit.edit_token, min(a, b), ssubstr(vid, a, b))
        view_show_region(vid, Region(linelist[0].a, linelist[-1].b), True, True, False)


def highlight_regions(view_id, regions):
    name = "highlight_regions"
    color = "markup.inserted"

    view_add_regions(
        view_id, name, regions, color, "", RegionFlags.NONE, [], "", None, None
    )
    set_timeout(lambda: view_erase_regions(view_id, name), 250)


contiguous_regions = lambda content: all(
    content[i].b == content[i + 1].a for i in range(len(content) - 1)
)


class SmartCopyCommand(TextCommand):
    timer = 0

    def run(self, edit, whole_line: bool = False, cut: bool = False) -> None:
        v: View = self.view
        vid = v.id()
        sel = v.sel()

        if whole_line:
            regs = [r.b if l.a <= r.b <= l.b else l.a for r in sel for l in v.lines(r)]
            sel.clear()
            sel.add_all(regs)

        lines = set()
        content: List[Region] = []

        all_empty = True
        for r in sel:
            if r.a != r.b:
                all_empty = False
                content.append(r)
            elif (line := full_line(vid, r.b)).a not in lines:
                lines.add(line.a)
                content.append(line)

        clip = ("" if all_empty else "\n").join(ssubstr(vid, r.a, r.b) for r in content)

        if cut:
            for reg in reversed(content):
                v.erase(edit, reg)

        v.show(v.sel()[-1].b, False)

        if clip.isspace():
            return
        self.timer += 1

        def copy_to_clipboard():
            self.timer -= 1
            if self.timer == 0:
                set_clipboard(clip)
                sublime.active_window().status_message(f"Copied {len(clip)} characters")

        set_timeout(copy_to_clipboard, 50)

        if cut:
            return

        highlight_regions(vid, content)

        if all_empty and contiguous_regions(content):
            keep_pointer = int(v.sel()[-1].b)
            view_selection_clear(vid)
            add_pt(vid, keep_pointer)


class SmartPasteCutNewlinesAndWhitespaceCommand(TextCommand):
    def run(self, edit: Edit) -> None:
        v: View = self.view

        wschar = " " if v.settings().get("translate_tabs_to_spaces") else "\t"
        sels: Selection = v.sel()

        result = subprocess.run(["wl-paste", "-n"], stdout=subprocess.PIPE, text=True)
        clipboard = result.stdout

        clips = [c.strip() for c in clipboard.splitlines() if c.strip()]
        clip_pos: List[Tuple[int, int]] = [(len(clips[-1]), len(clips[-1]) + 1)]

        for clip in reversed(clips[:-1]):
            clip_pos.append((len(clip) + 1 + clip_pos[-1][0], len(clip) + 1))

        rev_sel: Iterator[Region] = reversed(sels)
        for reg in rev_sel:
            if not reg.empty():
                v.erase(edit, reg)
            v.insert(edit, reg.a, wschar.join(clips))

        rev_sel_new: Iterator[Region] = reversed(sels)
        for reg in rev_sel_new:
            sels.add_all(
                Region(reg.begin() - pos[0], reg.begin() - pos[0] + pos[1] - 1)
                for pos in clip_pos
            )

        v.show(v.sel()[-1].b, False)


class SmartPasteCutWhitespaceCommand(TextCommand):
    def run(self, edit: Edit):
        v: View = self.view

        result = subprocess.run(["wl-paste", "-n"], stdout=subprocess.PIPE, text=True)
        clipboard = result.stdout

        stripped_clipboard = clipboard.strip()
        s: Selection = v.sel()
        for r in reversed(s):
            v.erase(edit, r)
            v.insert(edit, r.begin(), stripped_clipboard)


def selections_match_clipboard(vi: int, s: Selection, clips: List[str]) -> bool:
    if len(clips) == len(s):
        return True
    # ensures we can insert with multiple selections
    return len(clips) == len(set(ssubstr(vi, r.a, r.b) for r in s))


class SmartPasteCommand(TextCommand):
    def run(self, edit: Edit, strip_whitespace: bool = False) -> None:
        v: View = self.view

        if v.is_read_only():
            sublime.status_message("View is read-only")
            return

        if v.settings().get("translate_tabs_to_spaces"):
            wschar = " "
            tabsize: int = v.settings().get("tab_size")
        else:
            wschar = "\t"
            tabsize = 1

        s: Selection = v.sel()

        if not (clipboard := sublime.get_clipboard()):
            return

        clips = clipboard.splitlines()
        length = len(clips)

        indent_lengths = [int((len(l) - len(l.lstrip()))) for l in clips if l] or [0]
        base_indent = min(indent_lengths)
        lines = [c[base_indent:] for c in clips]

        delim = " " if strip_whitespace else "\n"

        def getclip(_: int, i: int) -> str:
            return clips[i % length]

        def indented_line(target_indent: int, i: int) -> str:
            return wschar * target_indent + lines[i % length]

        def whole_clipboard(target_indent, _: int) -> str:
            return delim.join(indented_line(target_indent, i) for i in range(length))

        selections_match = selections_match_clipboard(v.id(), s, clips)

        if clipboard.endswith("\n") and not strip_whitespace:
            indentfunc = indented_line if selections_match else whole_clipboard
            for i, r in enumerate(s):
                line = v.line(r.b)
                insert_pos = line.a
                indent_level = v.indentation_level(r.b)
                insert_string = indentfunc(indent_level * tabsize, i)
                s.subtract(r)

                v.insert(edit, insert_pos, delim)
                v.insert(edit, insert_pos, insert_string)

                caret_line_pos = r.b - line.a
                insert_line_len = v.line(insert_pos).b - insert_pos
                s.add(min(caret_line_pos, insert_line_len) + insert_pos)
        else:
            indentfunc = getclip if selections_match else whole_clipboard
            for i, r in enumerate(s):
                if r.a != r.b:
                    erase(v.id(), edit.edit_token, r)
                insert_string = indentfunc(0, i)
                v.insert(edit, r.begin(), insert_string)

        v.show(v.sel()[-1].b, False)
