import os
import tempfile
import unittest
from unittest import mock

from helpers import session
from test_cli import run

from zenform import cli, mozlz4, preview, profile, tour


class NextIndex(unittest.TestCase):
    def test_answers(self):
        n = 3
        self.assertEqual(tour.next_index("", 0, n), 1)  # Enter
        self.assertEqual(tour.next_index("n", 2, n), 0)  # wraps
        self.assertEqual(tour.next_index("p", 0, n), 2)  # wraps backwards
        self.assertEqual(tour.next_index("2", 0, n), 1)  # jump
        self.assertEqual(tour.next_index("9", 0, n), 1)  # out of range: just next
        self.assertIsNone(tour.next_index("q", 1, n))
        self.assertIsNone(tour.next_index(" Quit ", 1, n))


class Loop(unittest.TestCase):
    def drive(self, answers, entries=("a", "b", "c")):
        log = []

        def show(entry, i, n):
            log.append(f"open {entry}")
            return lambda: log.append(f"close {entry}")

        answers = iter(answers)
        tour.run_tour(list(entries), show, lambda prompt: next(answers), out=lambda s: None)
        return log

    def test_enter_steps_forward_and_wraps_and_each_window_is_closed_before_the_next(self):
        log = self.drive(["", "", "", "q"])
        self.assertEqual(log, ["open a", "close a", "open b", "close b", "open c", "close c", "open a", "close a"])

    def test_previous_and_jump(self):
        log = self.drive(["p", "2", "q"])
        self.assertEqual(log, ["open a", "close a", "open c", "close c", "open b", "close b"])

    def test_end_of_input_quits_and_still_closes_the_window(self):
        def show(entry, i, n):
            return lambda: closed.append(entry)

        closed = []

        def ask(prompt):
            raise EOFError

        tour.run_tour(["a"], show, ask, out=lambda s: None)
        self.assertEqual(closed, ["a"])

    def test_nothing_to_tour_is_an_error(self):
        with self.assertRaises(SystemExit):
            tour.run_tour([], lambda *a: None, input)


class FitWorkspace(unittest.TestCase):
    def test_cases(self):
        s = session()  # one workspace: "Work"
        self.assertEqual(cli._fit_workspace({"workspace": "Other"}, s, None, out=lambda m: None)["workspace"], "Work")
        self.assertEqual(cli._fit_workspace({"workspace": "Work"}, s, None)["workspace"], "Work")
        self.assertEqual(cli._fit_workspace({"workspace": "Work"}, s, "Forced")["workspace"], "Forced")
        two = session()
        two["spaces"].append({"uuid": "{ws-2}", "name": "Home"})
        self.assertEqual(
            cli._fit_workspace({"workspace": "Other"}, two, None)["workspace"], "Other"
        )  # ambiguous: leave


class FakeProc:
    def __init__(self):
        self.stopped = False


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.live = os.path.join(self.tmp.name, "zen", "Profiles", "live")
        self.pdir = os.path.join(self.tmp.name, "preview")
        os.makedirs(self.live)
        with open(os.path.join(self.live, profile.SESSION), "wb") as f:
            f.write(mozlz4.encode(session()))
        self.events = []
        patches = [
            mock.patch.object(profile, "data_dir", return_value=os.path.join(self.tmp.name, "zen")),
            mock.patch.object(preview, "instance_running", return_value=False),
            mock.patch.object(preview, "zen_binary", return_value="/zen"),
            mock.patch.object(cli, "_interactive", return_value=True),
            mock.patch.object(preview, "launch", side_effect=self.fake_launch),
            mock.patch.object(preview, "stop", side_effect=self.fake_stop),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.base = ["--profile", self.live]

    def pinned_labels(self):
        s = mozlz4.read(os.path.join(self.pdir, profile.SESSION))
        return {t.get("zenStaticLabel") for t in s["tabs"] if t.get("pinned") and not t.get("zenIsEmpty")}

    def fake_launch(self, binary, pdir):
        self.events.append(("launch", sorted(self.pinned_labels())))
        return FakeProc()

    def fake_stop(self, proc, pdir, timeout=30.0):
        self.events.append(("stop",))

    def tour(self, answers, *paths):
        with mock.patch("builtins.input", side_effect=answers):
            return run(*self.base, "tour", "--no-favicons", "--preview-profile", self.pdir, *paths)

    def test_cycles_through_the_examples_and_each_preview_shows_that_layout(self):
        code, out, err = self.tour(["", "q"], "minimal", "developer")
        self.assertEqual(code, 0, out + err)
        kinds = [e[0] for e in self.events]
        self.assertEqual(kinds, ["launch", "stop", "launch", "stop"])  # one window at a time
        self.assertEqual(self.events[0][1], ["Calendar", "Docs", "Mail", "Notes"])  # minimal
        self.assertIn("GitHub", self.events[2][1])  # developer
        self.assertIn("minimal", out)
        self.assertIn("developer", out)
        self.assertIn("1/2", out)
        self.assertIn("2/2", out)
        self.assertIn("real Zen was not touched", out)

    def test_defaults_to_all_bundled_examples_and_wraps(self):
        code, out, _ = self.tour(["", "", "", "q"])
        self.assertEqual(code, 0)
        self.assertEqual(
            [e for e in self.events if e[0] == "launch"].__len__(), 4
        )  # 3 examples, then back to the first

    def test_the_live_session_is_never_written(self):
        path = os.path.join(self.live, profile.SESSION)
        with open(path, "rb") as f:
            before = f.read()
        self.tour(["", "q"], "minimal", "developer")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_refuses_without_a_terminal_and_while_a_preview_is_open(self):
        with mock.patch.object(cli, "_interactive", return_value=False):
            code, _, err = self.tour([], "minimal")
        self.assertNotEqual(code, 0)
        self.assertIn("interactive", err)
        with mock.patch.object(preview, "instance_running", return_value=True):
            code, _, err = self.tour([], "minimal")
        self.assertNotEqual(code, 0)
        self.assertIn("already open", err)


if __name__ == "__main__":
    unittest.main()
