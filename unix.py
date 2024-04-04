import os
import re
import shutil
import time
from subprocess import PIPE, Popen
from typing import Dict, List, Optional

import sublime
import sublime_plugin
from sublime import Edit, Region
from sublime_api import view_cached_substr as ssubstr  # pyright: ignore
from sublime_api import view_insert  # pyright: ignore


def get_items(commands: Dict) -> List[str]:
    return [
        k
        for k, _ in sorted(
            commands.items(), key=lambda item: item[1]["access_time"], reverse=True
        )
    ]


class RecentUnixCommandsCommand(sublime_plugin.WindowCommand):
    def run(self, index: int = -1):
        w = self.window

        commands: Dict = w.settings().get("unix_commands") or {}
        if not commands:
            w.status_message("No UNIX commands in cache")
            return

        items = get_items(commands)
        pretty_items = [f"{i}: {j}" for i, j in enumerate(items, start=1)]

        def run_cmd(idx):
            if idx == -1:  # user pressed escape
                return
            proc = items[idx]
            args = commands[proc]
            args.pop("access_time")
            args["proc"] = proc
            w.run_command("run_unix", args=args)

        if index == -1:
            w.show_quick_panel(pretty_items, run_cmd)
        else:
            run_cmd(index)


class ProcInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, initial_text):
        self._initial_text = initial_text

    def initial_text(self):
        return self._initial_text

    def validate(self, name):
        return len(name) > 0


class ClearUnixCache(sublime_plugin.WindowCommand):
    def run(self):
        self.window.settings().erase("unix_commands")


def most_recent_cmd(w: sublime.Window) -> str:
    commands = w.settings().get("unix_commands") or {}
    items = get_items(commands)
    return items[0]


def cmd_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


class RunUnixCommand(sublime_plugin.TextCommand):

    def input(self, args):
        if "proc" not in args:
            if (w := sublime.active_window()) is None:
                return

            most_recent = most_recent_cmd(w)
            return ProcInputHandler(most_recent)

    def input_description(self) -> str:
        return "Run:"

    def run(
        self,
        edit: Edit,
        proc: Optional[str] = None,
        whole_buffer: bool = False,
        error_regex: Optional[str] = None,
    ):

        w = self.view.window()
        v = self.view
        if w is None:
            return

        if proc is None:
            return

        processes = []

        for lst in proc.split("|"):
            tokens = [token for token in lst.split(" ") if token] or [""]
            cmd = tokens[0]
            if not cmd_exists(cmd):
                w.status_message(f'"{cmd}" does not exist')
                return

            processes.append(tokens)

        vid = self.view.id()
        v = self.view

        w.run_command("hide_panel", {"panel": f"output.unixfail"})

        sels = [Region(0, v.size())] if whole_buffer else v.sel()

        error_lines = []

        unix_commands = w.settings().get("unix_commands") or {}
        unix_commands[proc] = {
            "access_time": time.time(),
            "error_regex": error_regex,
            "whole_buffer": whole_buffer,
        }
        w.settings().set("unix_commands", unix_commands)

        for reg in reversed(sels):

            indata = ssubstr(vid, reg.a, reg.b)

            folder = w.extract_variables().get("file_path", None) or os.getenv("HOME")
            for proclist in processes:
                p = Popen(
                    proclist,
                    stdout=PIPE,
                    stdin=PIPE,
                    stderr=PIPE,
                    text=True,
                    cwd=folder,
                )
                stdout_data, stderr_data = p.communicate(
                    input=indata if indata else None
                )
                indata = stdout_data

            if stderr_data:
                panel = w.create_output_panel("unixfail")
                panel.set_read_only(False)
                panel.settings().set("gutter", False)
                panel.run_command("append", {"characters": stderr_data})
                w.run_command("show_panel", {"panel": f"output.unixfail"})
                panel.set_read_only(True)

                if error_regex is not None:
                    match = re.search(error_regex, stderr_data)
                    if match:
                        row, column = map(int, match.groups())
                        tp = v.text_point(row - 1, column)
                        error_lines.append(tp)

            if stdout_data:
                v.erase(edit, reg)
                view_insert(vid, edit.edit_token, reg.begin(), stdout_data.rstrip())

        if error_lines:
            v.sel().clear()
            v.sel().add_all(error_lines)
            v.show_at_center(error_lines[0])
