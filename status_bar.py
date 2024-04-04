from typing import List

import sublime
import sublime_plugin
from sublime import View, Window
from sublime_api import buffer_primary_view  # pyright: ignore
from sublime_api import buffer_views  # pyright: ignore
from sublime_api import settings_get  # pyright: ignore
from sublime_api import settings_set  # pyright: ignore
from sublime_api import sheet_close  # pyright: ignore
from sublime_api import sheet_file_name  # pyright: ignore
from sublime_api import sheet_view  # pyright: ignore
from sublime_api import view_buffer_id  # pyright: ignore
from sublime_api import view_element  # pyright: ignore
from sublime_api import view_get_name  # pyright: ignore
from sublime_api import view_get_status  # pyright: ignore
from sublime_api import view_is_dirty  # pyright: ignore
from sublime_api import view_is_primary  # pyright: ignore
from sublime_api import view_is_scratch  # pyright: ignore
from sublime_api import view_selection_clear  # pyright: ignore
from sublime_api import window_focus_view  # pyright: ignore
from sublime_api import view_set_scratch  # pyright: ignore
from sublime_api import view_set_status  # pyright: ignore
from sublime_api import view_set_viewport_position  # pyright: ignore
from sublime_api import view_settings  # pyright: ignore
from sublime_api import view_sheet_id  # pyright: ignore
from sublime_api import view_viewport_position  # pyright: ignore
from sublime_api import view_window  # pyright: ignore
from sublime_api import window_active_view  # pyright: ignore
from sublime_api import window_close_file  # pyright: ignore
from sublime_api import window_focus_sheet  # pyright: ignore
from sublime_api import window_get_sheet_index  # pyright: ignore
from sublime_api import window_select_sheets  # pyright: ignore
from sublime_api import window_selected_sheets  # pyright: ignore
from sublime_api import window_set_layout  # pyright: ignore
from sublime_api import window_set_ui_element_visible  # pyright: ignore
from sublime_api import window_sheets  # pyright: ignore
from sublime_api import window_views  # pyright: ignore
from sublime_api import view_selection_add_region as add_region  # pyright: ignore
from sublime_api import window_move_sheets_to_group as move_sheets  # pyright: ignore
from sublime_plugin import EventListener, ViewEventListener

from .base import NUMBERS, selections

GROUP = 0
CALLBACKFN = None
DIRTY_ICON = "⭕"


MAX_KEYS = 5
MAX_CACHE_SIZE = 10
base_layout = {"cells": [[0, 0, 1, 1]], "cols": [0.0, 1.0], "rows": [0.0, 1.0]}
TRANSIENT = False


class SelectSingleSheetCommand(sublime_plugin.WindowCommand):
    def run(self):
        win_id = self.window.id()

        if (view_id := window_active_view(win_id)) == 0:
            return

        sheet_id = view_sheet_id(view_id)
        move_sheets(win_id, [sheet_id], GROUP, 0, True)

        primary = min(buffer_views(view_buffer_id(view_id)))
        if primary != view_id:
            # capture the cursors from the old view and move them to the new
            viewport_pos = view_viewport_position(view_id)

            view_selection_clear(primary)
            for cursor in selections(view_id):
                add_region(primary, cursor.a, cursor.b, cursor.xpos)
            view_set_viewport_position(primary, viewport_pos, True)

        close_non_primary(win_id, 0)
        set_tab_status(win_id, sheet_id, view_id)


class SelectToRightByIndexCommand(sublime_plugin.WindowCommand):
    def run(self, index: int):
        win_id = self.window.id()

        sheets: List[int] = window_sheets(win_id)
        if len(sheets) - 1 < index:
            return

        new_sheet = sheets[index]
        window_select_sheets(win_id, [sheets[0], new_sheet])
        window_focus_sheet(win_id, new_sheet)


def set_dirty_status(view_id: int) -> None:
    if (win_id := view_window(view_id)) == 0:
        return

    active_id = window_active_view(win_id)

    if (current := view_get_status(active_id, "directions")) == "":
        set_tab_status(win_id, view_sheet_id(active_id), active_id)
        return

    was_dirty = current[0] == DIRTY_ICON
    is_dirty = view_is_dirty(view_id)
    if is_dirty == was_dirty:
        return

    if is_dirty:
        view_set_status(active_id, "directions", f"{DIRTY_ICON} {current}")
    else:
        view_set_status(active_id, "directions", current[2:])


def sheet_name_for_buffer(sheet_id: int) -> str:
    view_id = sheet_view(sheet_id)
    settings_id = view_settings(view_id)
    buffer_name = settings_get(settings_id, "buffer_name")
    if not buffer_name:
        buffer_name = sheet_file_name(sheet_id).split("/")[-1] or view_get_name(view_id)
        if not buffer_name:
            return "New File"
        settings_set(settings_id, "buffer_name", buffer_name)
    return buffer_name


def set_tab_status(win_id: int, sheet_id: int, view_id: int):
    status_elements = []
    if view_is_dirty(view_id):
        status_elements.append(DIRTY_ICON)

    status_elements.append(sheet_name_for_buffer(sheet_id))

    if len((named_sheets := window_selected_sheets(win_id))) == 1:
        named_sheets = (vi for vi in window_sheets(win_id) if vi != sheet_id)

    joined = "  ".join(
        f"{keycap} {sheet_name_for_buffer(vi)}"
        for keycap, vi in zip(NUMBERS[:MAX_KEYS], named_sheets)
        if sheet_id != vi
    )
    if joined:
        status_elements.append(joined)

    status = "  ".join(status_elements)
    for vi in window_views(win_id, TRANSIENT):
        view_set_status(vi, "directions", status)


def prune_views(win_id):
    """closes all extra buffers"""
    all_sheets: List[int] = window_sheets(win_id)
    idx = len(all_sheets) - 1
    if idx < MAX_CACHE_SIZE:
        return
    selected_sheets = window_selected_sheets(win_id)
    visible_buffers = [view_buffer_id(sheet_view(sid)) for sid in selected_sheets]
    while idx >= MAX_CACHE_SIZE and all_sheets:
        sid = all_sheets[-1]

        v = sheet_view(sid)
        if not view_is_dirty(v) and view_buffer_id(v) not in visible_buffers:
            sheet_close(sid, CALLBACKFN)
            idx -= 1
        all_sheets.remove(sid)


def close_non_primary(win_id, active_id: int):
    sheets = {
        window_get_sheet_index(win_id, sid)[1]: sid
        for sid in window_selected_sheets(win_id)
    }

    visible_views = {idx: sheet_view(sid) for idx, sid in sheets.items()}
    visible_prims = {v for v in visible_views.values() if view_is_primary(v)}

    views_to_show = {}
    active_view = window_active_view(win_id) if active_id == 0 else active_id
    sheet_id = 0
    for index, view_id in visible_views.items():
        if prim_view := buffer_primary_view(view_buffer_id(view_id)):
            if prim_view in visible_prims:
                views_to_show[index] = view_id
            else:
                views_to_show[index] = prim_view
            if view_id == active_view:
                sheet_id = view_sheet_id(views_to_show[index])

    if sheet_id == 0:
        return

    remove = set()
    keep = set()
    all_views = window_views(win_id, TRANSIENT)
    for av in all_views:
        if (
            view_is_primary(av)
            or av in views_to_show.values()
            or av in visible_views.values()
        ):
            keep.add(av)
        else:
            remove.add(av)

    if len(remove) != 0:
        non_scratch_buffers = [vid for vid in keep if not view_is_scratch(vid)]

        for v in non_scratch_buffers:
            view_set_scratch(v, True)

        for vid in remove:
            window_close_file(win_id, vid, CALLBACKFN)

        for ns in non_scratch_buffers:
            view_set_scratch(ns, False)

    new_sheets = {index: view_sheet_id(views_to_show[index]) for index in views_to_show}
    sheetlist = [new_sheets[key] for key in sorted(new_sheets)]
    move_sheets(win_id, sheetlist, GROUP, 0, True)


class SetViewStatus(ViewEventListener):
    # thanks to Odatnurd from Sublime Discord
    # useful for relative line numbers, build_or_rebuild_ws_for_buffer
    @classmethod
    def applies_to_primary_view_only(cls) -> bool:
        """
        :returns: Whether this listener should apply only to the primary view
                  for a file or all of its clones as well.
        """
        return False

    def on_modified_async(self):
        set_dirty_status(self.view.view_id)

    def on_post_save(self):
        set_dirty_status(self.view.view_id)
        sublime.set_timeout(lambda: sublime.status_message("\0"), 0)


class SetWindowStatus(EventListener):
    def on_activated_async(self, view):
        view_id = view.view_id

        if view_element(view_id) != "" or (win_id := view_window(view_id)) == 0:
            return

        sheet_id = view_sheet_id(view_id)
        set_tab_status(win_id, sheet_id, view_id)
        prune_views(win_id)
        close_non_primary(win_id, view.id())

    def on_load_project_async(self, window: Window):
        win_id = window.id()
        window_set_layout(win_id, base_layout)
        window_set_ui_element_visible(win_id, 4, False, False)

    def on_new_window_async(self, window: Window):
        win_id = window.id()
        window_set_layout(win_id, base_layout)
        window_set_ui_element_visible(win_id, 4, False, False)

    def on_init(self, views: List[View]):
        windows = {view_window(v.view_id) for v in views}
        windows.discard(0)
        for win_id in windows:
            window_set_layout(win_id, base_layout)
            window_set_ui_element_visible(win_id, 4, False, False)
