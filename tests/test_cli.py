"""The command line, against a throwaway profile that holds a synthetic session."""

import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from helpers import session

from zenform import cli, mozlz4, profile


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if isinstance(e.code, str):
                err.write(e.code)
    return code, out.getvalue(), err.getvalue()


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prof = os.path.join(self.tmp.name, "profile")
        self.cfg = os.path.join(self.tmp.name, "config")
        os.makedirs(self.prof)
        with open(os.path.join(self.prof, profile.SESSION), "wb") as f:
            f.write(mozlz4.encode(session()))
        patcher = mock.patch.object(profile, "zen_running", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = ["--profile", self.prof, "--config", self.cfg]

    def dump(self):
        return run("--profile", self.prof, "dump", "--out", self.cfg)

    def test_dump_plan_apply_rollback(self):
        code, out, _ = self.dump()
        self.assertEqual(code, 0, out)
        # edit the dumped config: relabel the Docs pin
        path = os.path.join(self.cfg, "folders", "10-docs.toml")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("Wiki page", "Wiki"))

        code, out, _ = run(*self.base, "plan", "--no-favicons", "--exit-code")
        self.assertEqual(code, 2)
        self.assertIn("Wiki", out)

        before = pathlib.Path(self.prof, profile.SESSION).read_bytes()
        code, out, err = run(*self.base, "apply", "--no-favicons")
        self.assertEqual(code, 0, out + err)
        after = mozlz4.read(os.path.join(self.prof, profile.SESSION))
        self.assertTrue(any(t.get("zenStaticLabel") == "Wiki" for t in after["tabs"]))

        code, out, _ = run(*self.base, "plan", "--no-favicons", "--exit-code")
        self.assertEqual(code, 0, out)  # nothing left to change

        code, out, err = run(*self.base, "rollback")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(pathlib.Path(self.prof, profile.SESSION).read_bytes(), before)

    def test_plan_json_is_machine_readable(self):
        self.dump()
        code, out, _ = run(*self.base, "plan", "--json", "--no-favicons")
        data = json.loads(out)
        self.assertEqual((code, data["workspace"]), (0, "Work"))
        self.assertEqual(data["changes"], [])

    def test_plan_writes_nothing(self):
        self.dump()
        path = os.path.join(self.prof, profile.SESSION)
        before = pathlib.Path(path).read_bytes()
        run(*self.base, "plan", "--no-favicons")
        self.assertEqual(pathlib.Path(path).read_bytes(), before)

    def test_apply_refuses_while_zen_is_running(self):
        self.dump()
        with mock.patch.object(profile, "zen_running", return_value=True):
            code, _, err = run(*self.base, "apply", "--no-favicons")
        self.assertNotEqual(code, 0)
        self.assertIn("Zen is open", err)
        self.assertFalse(os.path.isdir(os.path.join(self.prof, profile.BACKUPS)))

    def test_an_unknown_session_format_is_refused_with_a_pointer_to_doctor(self):
        with open(os.path.join(self.prof, profile.SESSION), "wb") as f:
            f.write(mozlz4.encode({"something": "else"}))
        code, _, err = run("--profile", self.prof, "dump", "--out", self.cfg)
        self.assertNotEqual(code, 0)
        self.assertIn("doctor", err)

    def test_doctor_reports(self):
        self.dump()
        code, out, _ = run(*self.base, "doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("session readable", out)
        self.assertIn("valid", out)

    def test_rollback_without_a_backup_says_so(self):
        code, _, err = run(*self.base, "rollback")
        self.assertNotEqual(code, 0)
        self.assertIn("No backup", err)


if __name__ == "__main__":
    unittest.main()
