import re
from math import floor
from os import getenv, path
from typing import Dict, List, Optional, Tuple

import sublime
import sublime_plugin
from sublime import Region, View, Window, active_window  # pyright: ignore
from sublime_api import settings_get_default  # pyright: ignore
from sublime_api import view_fold_region  # pyright: ignore
from sublime_api import view_settings  # pyright: ignore
from sublime_api import view_window  # pyright: ignore
from sublime_api import window_active_panel  # pyright: ignore
from sublime_api import window_active_sheet  # pyright: ignore
from sublime_api import window_close_file  # pyright: ignore
from sublime_api import window_focus_sheet  # pyright: ignore
from sublime_api import window_active_view  # pyright: ignore
from sublime_api import window_focus_view  # pyright: ignore
from sublime_api import view_selection_clear  # pyright: ignore
from sublime_api import window_get_sheet_index  # pyright: ignore
from sublime_api import window_run_command  # pyright: ignore
from sublime_api import window_selected_sheets  # pyright: ignore
from sublime_api import window_views  # pyright: ignore
from sublime_api import view_cached_substr as substr  # pyright: ignore
from sublime_api import view_selection_add_region as add_region  # pyright: ignore
from sublime_api import view_set_viewport_position as set_vp  # pyright: ignore
from sublime_api import window_move_sheets_to_group as move_sheets  # pyright: ignore
from sublime_plugin import EventListener, TextCommand

from .base import max_views, selection_has_space_and_alnum, selections
from .cut_copy_paste import setClipboard

HOME: str = getenv("HOME")  # pyright: ignore
GROUP = 0
HEADERLINE = 1

save_cursors: Dict[int, List[Region]] = {}


def issearch(v: Optional[View]) -> bool:
    if v is None:
        return False
    return v.name() == "Find Results"


def file_with_loc(view: sublime.View, file_name: str) -> str:
    reg = view.sel()[0]
    line_no = get_line_no(view, reg)
    if file_name is None:
        return ""

    if line_no is not None:
        col = max(1, view.rowcol(reg.b)[1] - 6)
        file_loc = f"{file_name}:{line_no}:{col}"
    else:
        file_loc = f"{file_name}:1:1"

    return file_loc


def get_line_no(view: sublime.View, region: sublime.Region):
    line_text = view.substr(view.line(region))
    match = re.match(r"\s*(\d+):.+", line_text)
    if match:
        return match.group(1)
    return None


def get_file(view: sublime.View, region: sublime.Region):
    line = view.line(region)
    if line.empty() or line.b + 1 == view.size() or line.a == 1:
        return None, None
    while line.begin() > 1:
        line_text = view.substr(line)
        match = re.match(r"^(\S.+):$", line_text)
        if match:
            normalized_path = match.group(1).replace("~", HOME)
            if path.exists(normalized_path):
                return normalized_path, line
        line = view.line(line.begin() - 1)
    return None, None


def set_location(view: View, top: int):
    reg = view.sel()[0]
    vid = view.id()

    settings_id = view_settings(view.id())

    lh = view.line_height()
    viewport_extent = view.viewport_extent()[1]

    available_lines = floor(viewport_extent / lh) - HEADERLINE
    scroll_lines: int = min(
        floor(available_lines / 2),
        settings_get_default(settings_id, "scroll_context_lines", 0),
    )

    foldable_lines = view.lines(Region(top, reg.b))

    view.unfold(view.folded_regions())
    if (result := len(foldable_lines) - (available_lines - scroll_lines)) >= 0:
        view_fold_region(vid, Region(top, foldable_lines[result].b))

    lp_top = settings_get_default(settings_id, "line_padding_top", 0)
    viewport_top = view.text_to_layout(top)[1] - lp_top
    view.set_viewport_position((0.0, viewport_top))


class CopyInFindInFilesCommand(sublime_plugin.TextCommand):
    def run(self, _) -> None:
        v: View = self.view
        sel = v.sel()
        line = v.line(sel[0])
        line_content = v.substr(line)

        if not line_content.startswith(" "):
            setClipboard(line_content[:-1])
        elif line_match := re.match(r"^\s+\d+", line_content):
            offset = line_match.end() + 2
            setClipboard(line_content[offset:])


def restore_views(active_view_id: int):
    w = sublime.active_window()
    win_id = w.id()

    views: Dict[str, List[Tuple[int, int]]] = w.settings().get("ViewsBeforeSearch", {})
    w.settings().erase("ViewsBeforeSearch")

    active = w.settings().get("active_sheet")
    w.settings().erase("active_sheet")
    if not active:
        return

    prior_sheets = w.settings().get("prior_sheets", {})
    w.settings().erase("prior_sheets")

    viewport_pos = w.settings().get("wiewp_pos", {})
    w.settings().erase("wiewp_pos")

    sheetlist = [prior_sheets[key] for key in sorted(prior_sheets)]
    move_sheets(win_id, sheetlist, GROUP, 0, True)
    window_focus_sheet(win_id, active)

    for vid in window_views(win_id, False):
        if vid == active_view_id:
            window_focus_view(win_id, vid)
        elif regs := views.get(str(vid)):
            view_selection_clear(vid)
            for reg in regs:
                add_region(vid, *reg, -1)
            set_vp(vid, viewport_pos[str(vid)], False)
        else:
            window_close_file(win_id, vid, None)


class GotoSearchResultCommand(TextCommand):
    def run(self, _, new_tab=False) -> None:
        v = self.view
        if (w := v.window()) is None:
            return

        params = sublime.ENCODED_POSITION
        if new_tab:
            params |= sublime.ADD_TO_SELECTION

        file_name, file_name_header = get_file(v, v.sel()[0])
        if not file_name or file_name_header is None:
            return
        file = file_with_loc(v, file_name)

        w.settings().set("new_view", True)
        w.open_file(fname=file, flags=params, group=-1)

        if issearch(v):
            v.close()
        elif (panel := w.active_panel()) == "output.find_results":
            w.run_command("hide_panel", {"panel": panel})


class FindResultsListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return settings.get("find_results")

    def on_selection_modified(self):
        v = self.view

        if (window := v.window()) is None:
            return

        params = sublime.ENCODED_POSITION
        own_buffer = issearch(v)
        if own_buffer:
            params |= sublime.ADD_TO_SELECTION | sublime.CLEAR_TO_RIGHT
        else:
            params |= sublime.TRANSIENT

        for r in selections(v.view_id)[1:]:
            v.sel().subtract(r)

        file_name, file_name_header = get_file(v, v.sel()[0])
        if not file_name or file_name_header is None:
            return
        file = file_with_loc(v, file_name)
        set_location(v, file_name_header.b)
        window.open_file(fname=file, flags=params, group=0)

        if own_buffer:
            window.focus_view(v)

    def on_modified(self):
        v = self.view
        w = v.window()
        if w is None:
            return
        win_id = w.id()
        sheets = {
            str(window_get_sheet_index(win_id, sid)[1]): sid
            for sid in window_selected_sheets(win_id)
        }
        active_sheet = window_active_sheet(win_id)

        w.settings().set(key="active_sheet", value=active_sheet)
        w.settings().set(key="prior_sheets", value=sheets)

        views = [v for v in w.views() if not issearch(v)]
        v_n_s = {str(v.id()): [tuple(reg) for reg in v.sel()] for v in views}
        vps = {str(v.id()): v.viewport_position() for v in views}
        w.settings().set(key="ViewsBeforeSearch", value=v_n_s)
        w.settings().set(key="wiewp_pos", value=vps)

        sublime.set_timeout_async(lambda: w.focus_view(v), 10)
        return

        b = 0
        s = v.sel()
        symbols = v.symbol_regions()
        folded = []

        for symbol in symbols:
            a = symbol.region.a
            if b != 0:
                folded.append(Region(b + 1, a - 2))
            b = symbol.region.b
            s.add(a)

        last = v.line(v.size() - 1)
        folded.append(Region(b, last.a - 1))
        v.fold(folded)
        s.add(v.full_line(1))

    def on_deactivated(self):
        v = self.view
        if (w := v.window()) is None:
            return

        if w.active_panel() != "output.find_results" or v.name() != "Find Results":
            new_view_id = 0
            if w.settings().get("new_view", False):
                w.settings().erase("new_view")
                new_view_id = window_active_view(w.id())

            restore_views(new_view_id)


class BetterFindCommand(TextCommand):
    def run(self, _, **kwargs) -> None:
        v = self.view
        if (w := v.window()) is None:
            return

        vid = v.id()
        sel = selections(vid)
        in_selection = selection_has_space_and_alnum(vid, sel)

        global save_cursors
        save_cursors[vid] = sel

        # revert selections to make search not start at the next match
        for reg in sel:
            add_region(vid, reg.end(), reg.begin(), reg.xpos)

        args = {
            "panel": "incremental_find",
            "in_selection": in_selection,
            "pattern": "" if in_selection else substr(vid, sel[-1].a, sel[-1].b),
        }
        args.update(kwargs)

        w.run_command(cmd="show_panel", args=args)


class HidePanelListener(sublime_plugin.ViewEventListener):
    hide_panels = ["incremental_find", "find_in_files", "find"]

    def on_activated(self):
        if (w := self.view.window()) is not None:
            win_id = w.id()
            if window_active_panel(win_id) in self.hide_panels:
                window_run_command(win_id, "hide_panel", {"cancel": True})


class IncrementalFindListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return settings.get("is_find_widget")

    def on_activated(self):
        pv = self.view
        if (av := active_window().active_view()) is None:
            return

        vid = av.id()
        sel = selections(vid)
        in_selection = selection_has_space_and_alnum(vid, sel)
        pv.settings().set("in_selection", in_selection)

    def on_deactivated(self):
        if (w := self.view.window()) is None:
            return

        if (v := w.active_view()) is None:
            return
        vi = v.id()

        global save_cursors
        cursors_in_view = save_cursors.pop(vi, None)
        if not cursors_in_view:
            return

        # we have no way of determining how the panel was closed, but if it was canceled
        # sublime will put it at the first position
        last = v.sel()[-1]
        if (
            last.b == cursors_in_view[-1].begin()
            and last.a == cursors_in_view[-1].begin()
        ):
            v.sel().clear()
            for cursor in cursors_in_view:
                add_region(vi, cursor.a, cursor.b, cursor.xpos)


class RegisterListeners(EventListener):
    registered_views = set()
    wanted_elements = {
        "incremental_find:input": IncrementalFindListener,
        "find_in_files:output": FindResultsListener,
    }

    def register_panels(self, win_id: int) -> None:
        local_views: Dict[int, str] = {}
        for i in range(max_views(win_id)):
            view = View(i)
            element = view.element()
            if element in list(self.wanted_elements):
                local_views[view.id()] = view.element()

        for view_id, elementstr in local_views.items():
            if view_id not in self.registered_views:
                self.registered_views.add(view_id)

                view_listener = self.wanted_elements[elementstr](View(view_id))

                if not (sublime_plugin.view_event_listeners.get(view_id)):
                    sublime_plugin.view_event_listeners[view_id] = []

                sublime_plugin.view_event_listeners[view_id].append(view_listener)

    def on_new_window(self, window: Window):
        win_id = window.id()
        self.register_panels(win_id)

    def on_init(self, views: List[View]):
        windows = {view_window(v.view_id) for v in views}
        windows.discard(0)

        for win_id in windows:
            self.register_panels(win_id)
