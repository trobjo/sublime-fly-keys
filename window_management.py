from typing import Optional, Union

import sublime
import sublime_plugin
from sublime_plugin import WindowCommand
from sublime import QueryOperator, View, active_window
from sublime_api import view_cached_substr as substr  # pyright: ignore


class FocusViewCommand(WindowCommand):
    """
    The missing command for switching focus from side bar to view
    """

    def run(self) -> None:
        w = self.window
        active_group = w.active_group()
        if (sheet := w.active_sheet_in_group(active_group)) is None:
            return
        if sheet.is_semi_transient():
            sheet.close()
            return

        w.focus_sheet(sheet)


def word_boundary_regex(v: View):
    return f"{v.settings().get('word_separators')} \n\t"


class BufferListener(sublime_plugin.ViewEventListener):
    # thanks to Odatnurd from Sublime Discord
    # useful for relative line numbers, build_or_rebuild_ws_for_buffer
    @classmethod
    def applies_to_primary_view_only(cls) -> bool:
        """
        :returns: Whether this listener should apply only to the primary view
                  for a file or all of its clones as well.
        """
        return False

    def on_load(self):
        v = self.view
        self.separators = word_boundary_regex(v)

    def on_query_context(
        self, key: str, operator: QueryOperator, operand: str, match_all: bool
    ) -> Optional[bool]:
        v = self.view
        if key == "clipboard_newline":
            clip = sublime.get_clipboard() or " "
            return (clip[-1] == "\n") is operand

        if key == "word_boundary":
            try:
                separators: str = self.separators
            except AttributeError:
                separators = self.separators = word_boundary_regex(v)

            for reg in v.sel():
                a = reg.begin()
                b = reg.end()
                mysubstr: str = substr(v.id(), a - 1, b + 1)
                length = len(mysubstr)

                startindex = 1 if a != 0 else 0
                endindex = length - 1 if b != v.size() else length

                start_boundary = (a != 0 and mysubstr[0] in separators) or a == 0
                end_boundary = (
                    b != v.size() and mysubstr[length - 1] in separators
                ) or b == v.size()
                if not start_boundary:
                    return False is operand
                if not end_boundary:
                    return False is operand

                for i in range(startindex, endindex):
                    if mysubstr[i] in separators:
                        return False is operand

            return True is operand

        if key == "side_bar_visible":
            return active_window().is_sidebar_visible() is operand
        if key == "folded_regions":
            lhs = len(v.folded_regions())
            if operator == sublime.OP_EQUAL:
                return lhs == operand
            if operator == sublime.OP_NOT_EQUAL:
                return lhs != operand
