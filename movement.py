import re
import time

from sublime import Edit
from sublime_api import view_selection_add_point as add_point  # pyright: ignore
from sublime_api import view_selection_add_region as add_region  # pyright: ignore
from sublime_api import view_show_point as show_point  # pyright: ignore
from sublime_plugin import TextCommand

from .base import buffer_slice, selections


class NavigateWordCommand(TextCommand):
    whitespace = re.compile(r"\S+")

    def run(
        self, _, forward: bool = True, whole_words: bool = False, extend: bool = False
    ):
        v = self.view
        s = v.sel()
        if len(s) < 1:
            return

        if whole_words:
            rgx = self.whitespace
        else:
            word_separators = re.escape(v.settings().get("word_separators"))
            rgx = re.compile(f"[^{word_separators}\\s]+")

        vid = v.id()
        pts = []


        b_iter = buffer_slice(v, forward, chunksize=1000)
        b_iter.send(None)
        for a, b in s:
            mend = b
            while (match := b_iter.send((mend, rgx)))[0] is not None:
                mstart, mend = match
                if mstart == b and (mend == a or (extend and forward is (a > mend))):
                    continue

                shrink = a != b and forward is (a > b)
                if extend:
                    a = b if shrink and (forward is (mstart > a) or b == mstart) else a
                    b = mstart if shrink and a != b else mend
                else:
                    a = mstart if b != mstart or shrink else a
                    b = mend

                break
            pts.append((a, b))

        s.clear()
        for start, end in pts:
            add_region(vid, start, end, -1)

        show_point(vid, s[-1 if forward else 0].b, True, True, False)


class NavigateParagraphCommand(TextCommand):
    forward = re.compile(r"(\n[\t ]*){2,}", re.MULTILINE)
    backward = re.compile(r"\S(?=[\t ]*\n\n)", re.MULTILINE)

    backpat = re.compile(r"\S\s*\n")

    f_extend = re.compile(r"\S\n(?=\n[\t ]*)")
    b_extend = re.compile(r".(?=\n\n)", re.MULTILINE)

    shrink_f = re.compile(r"\n\n(?=[\t ]*\S)")
    shrink_b = re.compile(r"\n(?=\n\S)", re.MULTILINE)

    sels = set()
    then = time.time()

    prev_forward = True

    def run(self, _: Edit, forward: bool, extend: bool, force_paragraph: bool = False):
        v = self.view
        vid = v.id()
        s = selections(vid)
        current_sels = {r.b for r in s}
        now = time.time()
        check_line_ends = (
            not force_paragraph
            and all(v.line(r.a).b == v.line(r.b).b for r in s)
            and (
                (now - self.then >= 1 or self.prev_forward != forward)
                or bool(self.sels - current_sels)
            )
        )
        self.prev_forward = forward
        self.then = now

        b_f = buffer_slice(v, True, True)
        b_f.send(None)

        b_b = buffer_slice(v, False, True)
        b_b.send(None)

        if check_line_ends:
            if forward:
                regs = [(r.begin(), v.line(r.b).b, r.b) for r in s]
            else:
                regs = []
                for r in s:
                    line = v.line(r.b)
                    end = b_b.send((line.b, self.backpat))[0] - 1
                    start = end if end < line.a else max(r.end(), end)
                    regs.append((start, end, r.b))
            check_line_ends = any(b != c for _, b, c in regs)

        if check_line_ends:
            regs = [(a, b) for (a, b, _) in regs]
            pass

        elif forward and extend:
            regs = [
                b_f.send((r.b, self.shrink_f if r.a > r.b else self.f_extend))
                for r in s
            ]
        elif forward and not extend:
            regs = [b_f.send((r.b, self.forward)) for r in s]
        elif not forward and extend:
            regs = [
                b_b.send(
                    (r.b, self.shrink_b if v.line(r.a).b < r.end() else self.b_extend)
                )
                for r in s
            ]
        else:  # not forward and not extend
            regs = [b_b.send((r.b, self.backward)) for r in s]

        regs = [(m, n) for (m, n) in regs if n is not None]
        if not regs:
            return

        v.sel().clear()

        if extend and forward and not check_line_ends:
            regs = [
                (r.end() if r.a > r.b else v.line(r.begin()).a, m[1])
                for (r, m) in zip(s, regs)
            ]
        elif extend and not forward and not check_line_ends:
            regs = [
                (r.begin() if v.line(r.a).b < r.end() else r.end(), m[1])
                for (r, m) in zip(s, regs)
            ]

        if extend:
            for cursor in regs:
                add_region(vid, *cursor, 0.0)
        else:
            for cursor in regs:
                add_point(v.view_id, cursor[1])

        v.show(regs[-1][1], show_surrounds=True, keep_to_left=True)
