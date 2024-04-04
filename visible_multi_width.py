import sublime
import sublime_plugin
from sublime_api import view_element  # pyright: ignore
from sublime_api import view_selection_size  # pyright: ignore
from sublime_api import view_window  # pyright: ignore

from .base import cursor_animate

# Related reading:
#     https://forum.sublimetext.com/t/difference-when-multiple-selection/58087
#
# This simple plugin makes it easier to visualize when there is more than one
# cursor active in the current file (particularly when one or more of them may
# be outside the visible area of the file) by changing the state of the cursor.
#
# In this example the cursor is made wider when there is more than one, but
# this could be customized to use any number of settings.


class GiantCursorEventListener(sublime_plugin.EventListener):
    multi = {}

    def on_selection_modified_async(self, view: sublime.View):
        vid = view.view_id
        if view_element(vid) != "" or view_window(vid) == 0:
            return

        n = view_selection_size(vid) > 1
        if n is not self.multi.get(vid, -1):
            cursor_animate(view, n, duration=0.08)
            self.multi[vid] = n


