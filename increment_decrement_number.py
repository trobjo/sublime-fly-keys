import re

import sublime_plugin
from sublime import Edit, Region, set_timeout_async


class NumberCommand(sublime_plugin.TextCommand):
    def op(self, value: int) -> int:
        return value

    def save(self):
        self.view.run_command("save")

    def find_pt(
        self, line: str, start: int, stop: int, forward: bool, digit: bool
    ) -> int:
        for i in range(start, stop, 1 if forward else -1):
            if line[i].isdigit() == digit:
                return i
        return stop

    def run(self, edit: Edit) -> None:
        buf = self.view
        selection = buf.sel()
        for region in reversed(selection):
            if not region.empty():
                mystr = buf.substr(region)
                if mystr.isdigit() or mystr.startswith("-") and mystr[1:].isdigit():
                    continue
                if reg_list := [
                    Region(m.start() + region.begin(), m.end() + region.begin())
                    for m in re.finditer(r"-?\d+", buf.substr(region))
                ]:
                    selection.subtract(region)
                    selection.add_all(reg_list)  # pyright:ignore
                    continue

            if not (line := buf.substr(buf.full_line(region.b))):

                continue

            line_no, column = buf.rowcol(region.b)

            left_end = self.find_pt(line, column, -1, False, True)
            left_begin = self.find_pt(line, left_end, -1, False, False)

            right_begin = self.find_pt(line, column, len(line), True, True)
            right_end = self.find_pt(line, right_begin, len(line), True, False)

            if left_begin == left_end and right_begin == right_end:
                continue

            if left_end == right_begin:
                left_pos = left_begin + 1
                right_pos = right_end
            elif left_begin == left_end == -1 and right_begin != right_end:
                left_pos = right_begin
                right_pos = right_end
            elif right_begin == right_end == len(line) and left_begin != left_end:
                left_pos = left_begin + 1
                right_pos = left_end + 1

            elif right_begin - column < column - left_end:
                left_pos = right_begin
                right_pos = right_end
            else:
                left_pos = left_begin + 1
                right_pos = left_end + 1

            if left_pos >= 1 and line[left_pos - 1] == "-":
                left_pos -= 1

            pos_begin = buf.text_point(line_no, left_pos)
            pos_end = buf.text_point(line_no, right_pos)
            selection.subtract(region)
            selection.add(Region(pos_begin, pos_end))

        for region in selection:
            try:
                value = int(buf.substr(region))
                buf.replace(edit, region, str(self.op(value)))
            except ValueError:
                pass

        if buf.settings().get(key="save_after_number_change", default=False):
            set_timeout_async(self.save, 0)


class IncrementCommand(NumberCommand):
    def op(self, value: int) -> int:
        return value + 1


class DecrementCommand(NumberCommand):
    def op(self, value: int) -> int:
        return value - 1
