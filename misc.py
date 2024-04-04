from typing import Union

import sublime
import sublime_plugin
from sublime import Region, View, active_window
from sublime_api import view_selection_add_point as add_pt
from sublime_plugin import WindowCommand

from .base import selections


class HoverCommand(sublime_plugin.TextCommand):
    def run(self, _):
        view = self.view
        sublime_plugin.on_hover(view.id(), view.sel()[-1].b, sublime.HOVER_TEXT)


class CaretContextCommand(sublime_plugin.TextCommand):
    def run(self, _):
        v = self.view
        if len(v.sel()) == 0:
            return
        caret = v.sel()[-1].b
        v.show(caret)


class ClearSelectionCommand(sublime_plugin.TextCommand):
    def run(self, _, forward: bool = True) -> None:
        v = self.view
        vid = v.view_id
        regs = selections(v.view_id)
        v.sel().clear()
        for pt in [p.end() for p in regs] if forward else [p.begin() for p in regs]:
            add_pt(vid, pt)


class CreateRegionFromSelectionsCommand(sublime_plugin.TextCommand):
    def run(self, _) -> None:
        buf = self.view
        sel = buf.sel()
        line_beg = buf.full_line(sel[0]).begin()
        line_end = buf.full_line(sel[-1]).end()
        sel.clear()
        sel.add(Region(line_beg, line_end))


class RemoveBuildOutputCommand(WindowCommand):
    def run(self) -> None:
        view: Union[View, None] = active_window().active_view()
        if view is None:
            return
        view.erase_regions("exec")
        active_window().run_command("hide_panel")
        active_window().run_command("cancel_build")


class EofCommand(WindowCommand):
    def run(self):
        w = self.window
        view: Union[View, None] = w.active_view()
        if view is None:
            return
        w.focus_view(view)
        view.run_command(cmd="move_to", args={"to": "eof", "extend": False})
