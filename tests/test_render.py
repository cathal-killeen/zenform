import io
import re
import unittest
from unittest import mock

from helpers import SPEC, session
from test_cli import run

from zenform import model, render
from zenform.ui import UI

ANSI = re.compile(r"\x1b\[[0-9;]*m")


class Ui(unittest.TestCase):
    def test_colour_is_off_for_a_pipe_and_on_when_forced(self):
        self.assertFalse(UI(io.StringIO()).color)
        self.assertEqual(UI(mode="never").paint("x", "red"), "x")
        self.assertEqual(UI(mode="always").paint("x", "red"), "\x1b[31mx\x1b[0m")
        self.assertEqual(UI(mode="always").paint("x", "bold", "cyan"), "\x1b[1;36mx\x1b[0m")

    def test_no_color_and_dumb_terminals_win_over_a_tty(self):
        tty = mock.Mock(isatty=lambda: True, encoding="utf-8")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(UI(tty).color)
        with mock.patch.dict("os.environ", {"NO_COLOR": "1"}, clear=True):
            self.assertFalse(UI(tty).color)
        with mock.patch.dict("os.environ", {"TERM": "dumb"}, clear=True):
            self.assertFalse(UI(tty).color)
        with mock.patch.dict("os.environ", {"FORCE_COLOR": "1"}, clear=True):
            self.assertTrue(UI(io.StringIO()).color)

    def test_symbols_fall_back_to_ascii_without_utf8(self):
        ascii_ui = UI(mock.Mock(isatty=lambda: True, encoding="ascii"))
        utf = UI(mock.Mock(isatty=lambda: True, encoding="UTF-8"))
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual((ascii_ui.sym("ok"), ascii_ui.sym("arrow")), ("ok", "->"))
            self.assertEqual((utf.sym("ok"), utf.sym("arrow")), ("✓", "→"))

    def test_clip(self):
        ui = UI(mode="never")
        self.assertEqual(ui.clip("short", 10), "short")
        self.assertEqual(len(ui.clip("x" * 50, 10)), 10)


class Plan(unittest.TestCase):
    def ops(self):
        _, ops = model.apply_layout(session(), SPEC)
        return ops

    def test_groups_by_where_they_sit_and_summarises(self):
        out = render.render_plan(self.ops(), UI(mode="never"), "Work")
        for text in ("workspace Work", "Essentials", "Docs", "New", "Mail", "Fresh", "Unpinned", "Old pin", "added"):
            self.assertIn(text, out)
        self.assertLess(out.index("Essentials"), out.index("New"))  # sidebar order
        self.assertNotIn("\x1b", out)

    def test_with_colour_the_kinds_of_change_look_different(self):
        out = render.render_plan(self.ops(), UI(mode="always"))
        self.assertIn("\x1b[32m", out)  # green: added
        self.assertIn("\x1b[33m", out)  # yellow: relabelled
        self.assertIn("\x1b[31m", out)  # red: unpinned
        self.assertEqual(ANSI.sub("", out), render.render_plan(self.ops(), UI(mode="never")))  # same words, plus colour

    def test_nothing_to_change(self):
        once, _ = model.apply_layout(session(), SPEC)
        _, ops = model.apply_layout(once, SPEC)
        self.assertIn("nothing to change", render.render_plan(ops, UI(mode="never")))

    def test_kept_folders_and_icon_notes_are_shown(self):
        ops = [{"op": "keep_folder", "folder": "PRs"}, {"op": "icons", "filled": 2, "replaced": 1, "missing": ["A"]}]
        out = render.render_plan(ops, UI(mode="never"))
        self.assertIn("Left as they are", out)
        self.assertIn("2 filled", out)
        self.assertIn("1 replaced", out)
        self.assertIn("blank until opened: A", out)

    def test_counts(self):
        c = render.counts(self.ops())
        self.assertGreaterEqual(c["added"], 1)
        self.assertGreaterEqual(c["unpinned"], 1)


class OnTheCommandLine(unittest.TestCase):
    def test_piped_output_has_no_escape_codes_unless_asked(self):
        code, out, _ = run("examples")
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b", out)
        code, out, _ = run("--color", "always", "examples")
        self.assertIn("\x1b[", out)
        self.assertEqual(len(re.findall(r"\d+ essentials", ANSI.sub("", out))), 3)  # each example shows its size

    def test_errors_are_reported_once_on_stderr_with_exit_1(self):
        code, out, err = run("--config", "/nonexistent", "plan")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("No zenform.toml", err)


if __name__ == "__main__":
    unittest.main()
