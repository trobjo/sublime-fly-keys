import sublime
import sublime_plugin

from os import path
import bisect
import datetime
import re
import string

interesting_regions = {}
timeout = datetime.datetime.now()
WORDCHARS = r'[-\._\w]+'

class AddLineCommand(sublime_plugin.TextCommand):
    def run(self, edit, forward):
        buf = self.view
        selections = buf.sel()
        for region in reversed(selections):

            cur_line_num = buf.full_line(region.begin())
            cur_line = buf.substr(cur_line_num)
            cur_indent = len(cur_line) - len(cur_line.lstrip())

            if forward == True:
                target_line_offset = cur_line_num.end()
                target_line = buf.line(cur_line_num.end() + 1)
                while target_line.b - target_line.a < 1 and target_line.b < buf.size():
                    target_line = buf.line(target_line.b + 1)

            else:
                target_line_offset = cur_line_num.begin()
                target_line = buf.line(cur_line_num.begin() - 1)
                while target_line.b - target_line.a < 1 and target_line.a > 1:
                    target_line = buf.line(target_line.a - 1)

            target_line = buf.substr(target_line)
            target_indent = len(target_line) - len(target_line.lstrip())

            if target_indent > cur_indent:
                indent = target_indent
            else:
                indent = cur_indent

            selections.subtract(region)
            buf.insert(edit, target_line_offset, ' ' * indent + '\n')
            selections.add(target_line_offset + indent)

        buf.settings().set(key="block_caret", value=False)
        buf.settings().set(key="command_mode", value=False)



class ClearSelectionCommand(sublime_plugin.TextCommand):
    def run(self, _, forward):
        buf = self.view
        for region in buf.sel():
            buf.sel().subtract(region)
            if forward == True:
                _, col = buf.rowcol(region.end())
                if col == 0:
                    reg = region.end() - 1
                else:
                    reg = region.end()
            else:
                reg = region.begin()
            buf.sel().add(reg)
            buf.show(reg, False)

class CopyInFindInFilesCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        sel = buf.sel()
        line = buf.line(sel[0])
        line_content = buf.substr(line)

        if line_content.startswith('/'):
            sublime.set_clipboard(line_content[:-1])
            return

        line_match = re.match(r"^\s+\d+", line_content)
        if line_match:
            offset = line_match.end() + 2
            sublime.set_clipboard(line_content[offset:])
            return


class CreateRegionFromSelectionsCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        sel = buf.sel()
        line_beg = buf.full_line(sel[0]).begin()
        line_end = buf.full_line(sel[-1]).end()
        sel.clear()
        sel.add(sublime.Region(line_beg, line_end))

class DeleteSmartCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        buf = self.view
        for region in reversed(buf.sel()):
            if region.empty():
                if region.a == buf.size():
                    reg = buf.full_line(region.begin() -1)
                else:
                    reg = buf.full_line(region.begin())
            else:
                begin_line, _ = buf.rowcol(region.begin())
                end_line, col = buf.rowcol(region.end())
                if col != 0:
                    end_line += 1
                reg_beg = buf.text_point(begin_line, 0)
                reg_end = buf.text_point(end_line, 0) - 1
                reg = sublime.Region(reg_beg, reg_end + 1)
            buf.erase(edit, reg)



class ExpandSelectionToSentenceCommand(sublime_plugin.TextCommand):
    # TODO: Add foward command to go forward and backward selction of sentences
    def run(self, _):
        view = self.view
        # whitespace = '\t\n\x0b\x0c\r ' # Equivalent to string.whitespace
        oldSelRegions = list(view.sel())
        view.sel().clear()
        for thisregion in oldSelRegions:
            thisRegionBegin = thisregion.begin() - 1
            while ((view.substr(thisRegionBegin) not in ".") and (thisRegionBegin >= 0)):
                thisRegionBegin -= 1
            thisRegionBegin += 1
        while((view.substr(thisRegionBegin) in string.whitespace) and (thisRegionBegin < view.size())):
            thisRegionBegin += 1

        thisRegionEnd = thisregion.end()
        while((view.substr(thisRegionEnd) not in ".") and (thisRegionEnd < view.size())):
            thisRegionEnd += 1

        if(thisRegionBegin != thisRegionEnd):
            view.sel().add(sublime.Region(thisRegionBegin, thisRegionEnd+1))
        else:
            view.sel().add(sublime.Region(thisRegionBegin, thisRegionBegin))


class SetReadOnly(sublime_plugin.EventListener):
    def on_new_async(self, view):
        if view.name() == 'Find Results':
            view.set_read_only(True)

class FindInFilesGotoCommand(sublime_plugin.TextCommand):

    def run(self, _):
        view = self.view
        if view.name() == "Find Results":
            line_no = self.get_line_no()
            file_name = self.get_file()
            if line_no is not None and file_name is not None:
                caretpos = view.sel()[0].begin()
                (_,col) = view.rowcol(caretpos)
                file_loc = "%s:%s:%s" % (file_name, line_no, col -6)
                view.window().open_file(file_loc, sublime.ENCODED_POSITION)
            elif file_name is not None:
                view.window().open_file(file_name)

    def get_line_no(self):
        view = self.view
        if len(view.sel()) == 1:
            line_text = view.substr(view.line(view.sel()[0]))
            match = re.match(r"\s*(\d+).+", line_text)
            if match:
                return match.group(1)
        return None

    def get_file(self):
        view = self.view
        if len(view.sel()) == 1:
            line = view.line(view.sel()[0])
            while line.begin() > 0:
                line_text = view.substr(line)
                match = re.match(r"(.+):$", line_text)
                if match:
                    if path.exists(match.group(1)):
                        return match.group(1)
                line = view.line(line.begin() - 1)
        return None

prev_buf_id = 0
pos_begin = 0
allow_extend = False
ought_to_extend = False
should_change_to_bol = False



class Halla(sublime_plugin.EventListener):
    def on_new_async(self, view):
        print('hhhhhhhhhhhhhhhhhhhhhhhhh')
        if view.element() == "exec:output":
            print('hhhhhhhhhhhhhhhhhhhhhhhhh')
        if view.element() == "output:output":
            print('hhhhhhhhhhhhhhhhhhhhhhhhh')
        if view.element() == "console:input":
            print('hhhhhhhhhhhhhhhhhhhhhhhhh')
        if view.element() == "goto_anything:input":
            print('hhhhhhhhhhhhhhhhhhhhhhhhh')

class SampleListener(sublime_plugin.EventListener):
    def on_query_context(self, view, key, _, operand, __):
        global allow_extend
        global ought_to_extend
        global should_change_to_bol
        if key in ("goto_anything:input"):
            lhs = view.element() == "goto_anything:input"
            if view.element() == "goto_anything:input":
                if ought_to_extend == True:
                    allow_extend = True
                should_change_to_bol = True
            else:
                allow_extend = False
            rhs = bool(operand)

            return lhs == rhs if operand != sublime.OP_EQUAL else lhs != rhs
        return None

    def on_activated(self, _):
        global prev_buf_id
        global pos_begin
        global allow_extend
        global should_change_to_bol
        if allow_extend == True:
            allow_extend = False
            v = sublime.active_window().active_view()
            if prev_buf_id == v.id():
                end = v.full_line(v.sel()[0].end()).end()
                v.sel().add(sublime.Region(pos_begin,end))
        elif should_change_to_bol:
            v = sublime.active_window().active_view()
            end = v.full_line(v.sel()[0].end()).end()
            should_change_to_bol = False
            next_res, next_res_end = v.find(r'\S|^$|^\s+$', v.sel()[0].end())
            v.sel().clear()
            v.sel().add(sublime.Region(next_res,next_res))

    def on_deactivated_async(self, _):
        global prev_buf_id
        global pos_begin
        global ought_to_extend
        v = sublime.active_window().active_view()
        has_selection = v.sel()[0].empty()
        if not has_selection:
            prev_buf_id = v.id()
            pos, _ = v.sel()[0]
            pos_begin = pos
            ought_to_extend = True
        else:
            ought_to_extend = False


class NumberCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        buf = self.view
        selection = buf.sel()
        for region in selection:
            if region.empty() == False:
                mystr = buf.substr(region)
                if mystr.isdigit() or mystr.startswith('-') and mystr[1:].isdigit():
                    continue
                selection.subtract(region)
                reg_list = [sublime.Region(m.start() + region.begin(), m.end() + region.begin()) for m in re.finditer(r'-?\d+', buf.substr(region))]
                for maybe_digit in reg_list:
                    selection.add(maybe_digit)
            else:
                line, column = buf.rowcol(region.begin())
                cur_line = buf.substr(buf.full_line(buf.text_point(line,-1)))
                line_length = len(cur_line)
                start_pos = None
                end_pos = None
                to_the_right = line_length - column
                to_the_left = line_length - (line_length - column) + 0

                if cur_line[column].isdigit() or (cur_line[column] == '-' and cur_line[column + 1].isdigit()):
                    first_char_is_digit = True
                else:
                    first_char_is_digit = False

                for i in range(to_the_right):
                    i_pointer = column + i
                    if cur_line[i_pointer].isdigit() or (not end_pos and cur_line[i_pointer] == '-' and cur_line[i_pointer + 1].isdigit()):

                        if not start_pos and first_char_is_digit == False:
                            start_pos = i_pointer

                        end_pos = i_pointer

                    elif end_pos:
                        break

                if not start_pos:
                    for j in range(to_the_left):
                        j_pointer = column - j
                        if cur_line[j_pointer].isdigit() or (cur_line[j_pointer] == '-' and cur_line[j_pointer + 1].isdigit()):

                            if not end_pos:
                                end_pos = j_pointer

                            start_pos = j_pointer

                        elif start_pos:
                            break

                if start_pos is not None and end_pos is not None:
                    selection.subtract(region)
                    selection.add(sublime.Region(buf.text_point(line, start_pos), buf.text_point(line, end_pos + 1)))

        for region in selection:
            try:
                value = int(buf.substr(region))
                buf.replace(edit, region, str(self.op(value)))
            except ValueError:
                    pass


class IncrementCommand(NumberCommand):
    def op(self, value):
          return value + 1

class DecrementCommand(NumberCommand):
    def op(self, value):
          return value - 1


class InsertModeCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        buf = self.view
        for region in reversed(buf.sel()):
            if region.empty():
                continue
            buf.erase(edit, region)
        buf.settings().set(key="block_caret", value=False)
        buf.settings().set(key="command_mode", value=False)


class CommandModeCommand(sublime_plugin.WindowCommand):
    def run(self):
        buf = sublime.active_window().active_view()
        buf.settings().set(key="block_caret", value=True)
        buf.settings().set(key="command_mode", value=True)
        buf.window().run_command('hide_panel')
        buf.window().run_command('hide_popup')


class InsertBeforeOrAfterCommand(sublime_plugin.TextCommand):
    def run(self, _, after=False):
        buf = self.view
        selections = buf.sel()
        for region in selections:

            if region.empty():
                if len(selections) == 1:
                    return
                selections.subtract(region)

            if after == True:
                reg = region.end() + 1
            else:
                reg = region.begin() - 1

            selections.subtract(region)
            selections.add(reg)

        buf.settings().set(key="block_caret", value=False)
        buf.settings().set(key="command_mode", value=False)



def build_or_rebuild_ws_for_view(view, immediate: bool):
    global interesting_regions
    global timeout
    if (datetime.datetime.now() - timeout).total_seconds() > 2 or immediate == True:
        interesting_regions[view] = {}
        try:
            whitespaces = view.find_all(r'\n\n *\S')
            first, last = zip(*[(-2, -1)] + [(first, last -1) for first, last in whitespaces] + [(view.size() + 1, view.size() + 1)])
            interesting_regions[view]['first'] = first
            interesting_regions[view]['last'] = last
        except ValueError:
            pass
    timeout = datetime.datetime.now()


class HejSampleListener(sublime_plugin.EventListener):
    def on_modified_async(self, view):
        if view.element() is None:
            try:
                global interesting_regions
                del interesting_regions[view]
            except KeyError:
                pass
            sublime.set_timeout(lambda: build_or_rebuild_ws_for_view(view, immediate=False), 2000)

    def on_load_async(self, view):
        if view not in interesting_regions and view.element() is None:
            build_or_rebuild_ws_for_view(view, immediate=True)

class NavigateByParagraphForwardCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        region = buf.sel()[-1].begin()
        try:
            myregs = interesting_regions[buf]['last']
        except KeyError:
            build_or_rebuild_ws_for_view(buf, immediate=True)
            myregs = interesting_regions[buf]['last']
        bisect_res = bisect.bisect(myregs, region)
        sel_end = myregs[bisect_res]
        reg = sublime.Region(sel_end)
        buf.sel().clear()
        buf.sel().add(reg)
        buf.show(reg, False)


class NavigateByParagraphBackwardCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        region = buf.sel()[0].begin()
        try:
            myregs = interesting_regions[buf]['last']
        except KeyError:
            build_or_rebuild_ws_for_view(buf, immediate=True)
            myregs = interesting_regions[buf]['last']
        bisect_res = bisect.bisect(myregs, region - 1)
        sel_end = myregs[bisect_res -1 ]
        reg = sublime.Region(sel_end)
        buf.sel().clear()
        buf.sel().add(reg)
        buf.show(reg, False)


class ExtendedExpandSelectionToParagraphForwardCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        regs_dict = {}
        for region in buf.sel():

            try:
                first = interesting_regions[buf]['first']
            except KeyError:
                build_or_rebuild_ws_for_view(buf, immediate=True)
                first = interesting_regions[buf]['first']

            if region.b > region.a:
                bisect_res = bisect.bisect(first, region.b)
                sel_begin = region.a
                sel_end = first[bisect_res] + 2

            elif region.a > region.b:
                bisect_res = bisect.bisect(first, region.b)
                sel_end = first[bisect_res] + 2
                if region.a == sel_end or sel_end - 3 == region.a:
                    sel_end = region.a
                    sel_begin = region.b
                else:
                    sel_begin = region.a
                    buf.sel().subtract(region)

            elif region.a == region.b:
                bisect_res = bisect.bisect(first, region.b -2)
                sel_begin = first[bisect_res -1] + 2
                sel_end = first[bisect_res] + 2

            regs_dict[sel_begin] = sel_end

        buf.sel().add_all([sublime.Region(begin,end) for begin,end in regs_dict.items()])
        buf.show(buf.sel()[-1], False)


class ExtendedExpandSelectionToParagraphBackwardCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        regs_dict = {}
        for region in buf.sel():

            try:
                first = interesting_regions[buf]['first']
            except KeyError:
                build_or_rebuild_ws_for_view(buf, immediate=True)
                first = interesting_regions[buf]['first']

            if region.b > region.a:
                bisect_end = bisect.bisect(first, region.b - 3)
                sel_end = first[bisect_end -1] + 2
                if region.a == sel_end:
                    sel_end = region.a
                    sel_begin = region.b
                else:
                    sel_begin = region.a
                    buf.sel().subtract(region)

            elif region.a > region.b:
                sel_begin = region.a
                bisect_end = bisect.bisect(first, region.b - 3)
                if bisect_end == 0:
                    sel_end = -1
                else:
                    sel_end = first[bisect_end -1] + 2

            elif region.b == region.a:
                bisect_end = bisect.bisect(first, region.b - 2)
                sel_end = first[bisect_end -1] + 2
                sel_begin = first[bisect_end] + 2

            regs_dict[sel_begin] = sel_end

        buf.sel().add_all([sublime.Region(begin, end) for begin,end in regs_dict.items()])
        buf.show(buf.sel()[0], False)


class MultipleCursorsFromSelectionCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        reg_list = []
        for region in buf.sel():
            reg_begin = region.begin() - 1
            buffer = buf.substr(sublime.Region(reg_begin, region.end()))
            if reg_begin <= 1:
                reg_begin += 1
                reg_list.append(-2)
            reg_list += [sublime.Region(m.start() + reg_begin) for m in re.finditer(r'\S.*\n', buffer)]
        buf.sel().clear()
        buf.sel().add_all(reg_list)

class SingleSelectionLastCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        reg = buf.sel()[-1]
        buf.sel().clear()
        buf.sel().add(reg)
        buf.show(reg, True)


class SmartFindWordCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        reg = buf.sel()[-1]
        if not reg.empty():
            return

        cur_line_in_points_beg, cur_line_in_points_end = buf.line(reg)

        str_after_cur = buf.substr(reg.begin())
        if str_after_cur.isalpha():
            return

        str_before_cur = buf.substr(reg.begin() -1)
        if str_before_cur.isalpha():
            return

        rev_reg = sublime.Region(cur_line_in_points_beg, reg.begin())
        rev_reg_str = buf.substr(rev_reg)
        i = 0
        rev_beg = -1
        for char in reversed(rev_reg_str):
            if rev_beg == -1:
                if (char.isalnum() or char == '_'):
                    rev_beg = i
                    break
            i += 1

        forw_reg_str = ''
        if rev_beg > 1 or rev_beg == -1:
            forw_reg = sublime.Region(cur_line_in_points_end, reg.begin())
            forw_reg_str = buf.substr(forw_reg)
        if len(forw_reg_str) > 0:
            j = 0
            forw_beg = -1
            for char in forw_reg_str:
                if forw_beg == -1:
                    if (char.isalnum() or char == '_'):
                        forw_beg = j
                        break
                j += 1

            if forw_beg != -1 and rev_beg == -1:
                pos = reg.a + forw_beg
            elif forw_beg < rev_beg:
                pos = reg.a + forw_beg
            elif rev_beg != -1:
                pos = reg.a - rev_beg
            else:
                return
        else:
            pos = reg.a - rev_beg

        buf.sel().subtract(buf.sel()[-1])
        buf.sel().add(sublime.Region(pos))



class SmartPasteCommand(sublime_plugin.TextCommand):

    def find_indent(self, cur_line_num, cur_line) -> int:
        buf = self.view
        clipboard = sublime.get_clipboard()
        if len(cur_line) == 0 and clipboard.startswith(' '):
            lines_above, _ = buf.line(cur_line_num.begin())
            for line in range(lines_above):
                line += 1
                prev_line = buf.substr(buf.line(cur_line_num.begin() - line))
                if prev_line.startswith(' '):
                    break
            indent = len(prev_line) - len(prev_line.lstrip())
        else:
            indent = len(cur_line) - len(cur_line.lstrip())
        return indent


    def run(self, edit):
        buf = self.view
        selections = buf.sel()
        clipboard = sublime.get_clipboard()
        clips = clipboard.splitlines()

        if clipboard.endswith('\n'):
            has_final_newline = True
        else:
            has_final_newline = False

        if len(clips) == len(selections):
            for region, cliplet in zip(reversed(selections), reversed(clips)):

                cur_line_num = buf.line(region.begin())
                cur_line = buf.substr(cur_line_num)

                if has_final_newline:
                    insert_pos, _ = buf.line(region.begin())
                    indent = self.find_indent(cur_line_num, cur_line)
                    insert_string = " " * indent + cliplet.lstrip() + '\n'
                else:
                    insert_string = cliplet
                    insert_pos = region.begin()

                if region.empty() == False:
                    buf.erase(edit, region)
                elif has_final_newline and len(selections) > 1:
                    if region.a == buf.size():
                        reg = buf.full_line(region.begin() -1)
                    else:
                        reg = buf.full_line(region.begin())
                    buf.erase(edit, reg)


                buf.insert(edit, insert_pos, insert_string)

        elif len(clips) > len(selections):
            for region in reversed(selections):

                cur_line_num = buf.line(region.begin())
                cur_line = buf.substr(cur_line_num)

                insert_pos, _ = buf.line(region.begin())
                above_indent = self.find_indent(cur_line_num, cur_line)
                insert_string = ''
                initial_indent = None
                for line in clips:
                    deindented_line = line.lstrip().rstrip()
                    cur_indent = len(line) - len(deindented_line)
                    if initial_indent == None:
                        initial_indent = cur_indent
                    this_indent = above_indent + cur_indent - initial_indent
                    insert_string += " " * this_indent  + deindented_line + '\n'
                print(repr(insert_string))

                if region.empty() == False:
                    buf.erase(edit, region)

                buf.insert(edit, insert_pos, insert_string)
        elif len(clips) < len(selections):
            contiguous_regions = []
            cur_line_beg, cur_line_end = buf.line(selections[0])
            hem_list = [cur_line_beg]
            for i in range(1, len(selections)):
                next_line_beg, next_line_end = buf.line(selections[i])
                print('next_line_beg', next_line_beg)
                print('cur_line_end',cur_line_end)
                if cur_line_end + 1 == next_line_beg:
                    cur_line_beg, cur_line_end = buf.line(selections[i])
                    print('hallo')
                else:
                    prev_line_beg, prev_line_end = buf.line(selections[i-1])
                    hem_list.append(prev_line_end)
                    contiguous_regions.append(hem_list)
                    hem_list = [prev_line_beg]
                    print('no')
                    # sublime.Region()
                i+=1
                print(i)

            print(contiguous_regions)
            for reg in contiguous_regions:
                selections.add(sublime.Region(reg[0], reg[1]))


            return
            for region in reversed(selections):

                cur_line_num = buf.line(region.begin())
                cur_line = buf.substr(cur_line_num)

                if has_final_newline:
                    insert_pos, _ = buf.line(region.begin())
                    above_indent = self.find_indent(cur_line_num, cur_line)
                    insert_string = ''
                    initial_indent = None
                    for line in clips:
                        deindented_line = line.lstrip().rstrip()
                        cur_indent = len(line) - len(deindented_line)
                        if initial_indent == None:
                            initial_indent = cur_indent
                        this_indent = above_indent + cur_indent - initial_indent
                        insert_string += " " * this_indent  + deindented_line + '\n'
                else:
                    insert_pos = region.begin()
                    insert_string = clipboard

                print(repr(insert_string))
                if region.empty() == False:
                    buf.erase(edit, region)
                elif has_final_newline:
                    if region.a == buf.size():
                        reg = buf.full_line(region.begin() -1)
                    else:
                        reg = buf.full_line(region.begin())
                    buf.erase(edit, reg)

                buf.insert(edit, insert_pos, insert_string)

class SplitSelectionIntoLinesWholeWordsCommand(sublime_plugin.TextCommand):
    def run(self, view):
        buf = self.view
        selections = buf.sel()
        for region in reversed(selections):
            if region.empty():
                continue

            contents = buf.substr(region)
            begin = region.begin()
            word_boundaries = [sublime.Region(m.start() + begin, m.end() + begin) for m in re.finditer(WORDCHARS, contents)]
            if word_boundaries != []:
                selections.subtract(region)
                selections.add_all(word_boundaries)


class UndoFindUnderExpandCommand(sublime_plugin.TextCommand):
    def run(self, _):
        buf = self.view
        selection = buf.sel()

        if len(selection) == 1:
            buf.show(selection[0], True)
            return

        selected_word = buf.substr(selection[-1])
        min_point = selection[0].begin()
        max_point = selection[-1].end()

        res = buf.find(selected_word, start_pt=max_point)
        if res.begin() != -1:
            selection.subtract(selection[-1])
            buf.show(selection[-1], True)
            return

        reg = sublime.Region(min_point, max_point)
        all_regs = [min_point +  m.end() for m in re.finditer(selected_word, buf.substr(reg))]

        i = 0
        for region in selection:
            if region.end() < all_regs[i]:
                # Consider a continue statement here instead.
                # Depends on what strategy works best
                selection.subtract(region)
                buf.show(selection[i-1], True)
                return
            elif region.end() > all_regs[i]:
                selection.subtract(selection[i-1])
                buf.show(selection[i-2], True)
                return
            i += 1

        selection.subtract(selection[-1])
        buf.show(selection[-1], True)

class SubtractFirstSelectionCommand(sublime_plugin.TextCommand):
    def run(self, _):
        selections = self.view.sel()
        selections.subtract(selections[0])
        self.view.show(selections[0], True)

