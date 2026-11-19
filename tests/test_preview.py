"""zenform preview: a separate Zen on a throwaway profile. The live profile must only ever be read."""

import hashlib
import os
import tempfile
import unittest
from unittest import mock

from helpers import SPEC, session
from test_cli import run

from zenform import config, model, mozlz4, preview, profile


def tree_hash(root):
    h = hashlib.sha256()
    for d, _, files in sorted(os.walk(root)):
        for f in sorted(files):
            p = os.path.join(d, f)
            h.update(p.encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class Prepare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.live = os.path.join(self.tmp.name, "live")
        self.pdir = os.path.join(self.tmp.name, "preview")
        os.makedirs(os.path.join(self.live, "chrome"))
        for name, body in {
            "prefs.js": b"user_pref('a', 1);",
            "zen-themes.json": b"{}",
            "cookies.sqlite": b"SECRET-COOKIES",
            "logins.json": b"SECRET-LOGINS",
            "places.sqlite": b"HISTORY",
            "key4.db": b"SECRET-KEYS",
        }.items():
            with open(os.path.join(self.live, name), "wb") as f:
                f.write(body)
        with open(os.path.join(self.live, "chrome", "userChrome.css"), "w") as f:
            f.write("/* mod */")

    def test_writes_the_new_session_and_copies_only_the_allowlist(self):
        new, _ = model.apply_layout(session(), SPEC)
        copied = preview.prepare(self.live, new, self.pdir)
        self.assertEqual(mozlz4.read(os.path.join(self.pdir, profile.SESSION)), new)
        self.assertEqual(sorted(copied), ["chrome/", "prefs.js", "zen-themes.json"])
        present = set(os.listdir(self.pdir))
        for secret in ("cookies.sqlite", "logins.json", "places.sqlite", "key4.db"):
            self.assertNotIn(secret, present)
        self.assertTrue(os.path.exists(os.path.join(self.pdir, "chrome", "userChrome.css")))
        self.assertIn("user.js", present)

    def test_the_live_profile_is_not_changed(self):
        before = tree_hash(self.live)
        preview.prepare(self.live, session(), self.pdir)
        self.assertEqual(tree_hash(self.live), before)

    def test_a_second_preview_replaces_the_first_and_leaves_no_stale_session(self):
        preview.prepare(self.live, session(), self.pdir)
        for stale in ("sessionstore.jsonlz4", "sessionCheckpoints.json"):
            with open(os.path.join(self.pdir, stale), "w") as f:
                f.write("old")
        os.makedirs(os.path.join(self.pdir, "sessionstore-backups"))
        newer = session()
        newer["spaces"][0]["name"] = "Other"
        preview.prepare(self.live, newer, self.pdir)
        self.assertEqual(mozlz4.read(os.path.join(self.pdir, profile.SESSION))["spaces"][0]["name"], "Other")
        for stale in ("sessionstore.jsonlz4", "sessionCheckpoints.json", "sessionstore-backups"):
            self.assertFalse(os.path.exists(os.path.join(self.pdir, stale)))


class Safety(unittest.TestCase):
    def test_refuses_the_live_profile_and_zens_own_data_folder(self):
        with tempfile.TemporaryDirectory() as d:
            zen = os.path.join(d, "zen")
            live = os.path.join(zen, "Profiles", "abc.Default")
            os.makedirs(live)
            with mock.patch.object(profile, "data_dir", return_value=zen):
                with self.assertRaises(SystemExit):
                    preview.check_safe(live, live)
                with self.assertRaises(SystemExit):
                    preview.check_safe(os.path.join(zen, "Profiles", "other"), live)
                with self.assertRaises(SystemExit):
                    preview.check_safe(zen, live)
                preview.check_safe(os.path.join(d, "elsewhere"), live)  # fine

    def test_instance_running_looks_for_the_profile_in_the_command_line(self):
        ps = "/Applications/Zen.app/Contents/MacOS/zen -profile /tmp/p1 -no-remote\n/bin/other\n"
        with mock.patch.object(preview.subprocess, "run", return_value=mock.Mock(stdout=ps)):
            self.assertTrue(preview.instance_running("/tmp/p1"))
            self.assertFalse(preview.instance_running("/tmp/p2"))

    def test_default_profile_honours_the_environment(self):
        with mock.patch.dict(os.environ, {preview.ENV_PROFILE: "/somewhere/preview"}):
            self.assertEqual(preview.default_preview_profile(), "/somewhere/preview")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(preview.default_preview_profile().endswith(".zenform-preview-profile"))


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.live = os.path.join(self.tmp.name, "zen", "Profiles", "live")
        self.cfg = os.path.join(self.tmp.name, "config")
        self.pdir = os.path.join(self.tmp.name, "preview")
        os.makedirs(self.live)
        with open(os.path.join(self.live, profile.SESSION), "wb") as f:
            f.write(mozlz4.encode(session()))
        config.write_config(config.current_spec(session(), "Work"), self.cfg)
        # relabel a pin in the config, so there is something to preview
        path = os.path.join(self.cfg, "folders", "10-docs.toml")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("Wiki page", "Wiki"))
        self.args = ["--profile", self.live, "--config", self.cfg]
        for patcher in (
            mock.patch.object(profile, "data_dir", return_value=os.path.join(self.tmp.name, "zen")),
            mock.patch.object(preview, "instance_running", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_no_launch_prepares_the_profile_and_does_not_open_zen(self):
        before = tree_hash(self.live)
        with mock.patch.object(preview, "launch") as launch:
            code, out, err = run(*self.args, "preview", "--no-launch", "--no-favicons", "--preview-profile", self.pdir)
        self.assertEqual(code, 0, out + err)
        launch.assert_not_called()
        got = mozlz4.read(os.path.join(self.pdir, profile.SESSION))
        self.assertTrue(any(t.get("zenStaticLabel") == "Wiki" for t in got["tabs"]))
        self.assertEqual(tree_hash(self.live), before)  # the real session is untouched
        self.assertIn("Wiki", out)

    def test_works_while_the_real_zen_is_running_and_launches_a_separate_instance(self):
        with (
            mock.patch.object(profile, "zen_running", return_value=True),
            mock.patch.object(preview, "zen_binary", return_value="/zen"),
            mock.patch.object(preview, "launch") as launch,
        ):
            code, out, err = run(*self.args, "preview", "--no-favicons", "--preview-profile", self.pdir)
        self.assertEqual(code, 0, out + err)
        launch.assert_called_once_with("/zen", self.pdir)
        self.assertIn("real Zen was not touched", out)

    def test_command_line_is_a_separate_instance_on_the_preview_profile(self):
        self.assertEqual(preview.command("/zen", "/p"), ["/zen", "-profile", "/p", "-no-remote"])

    def test_refuses_to_use_the_live_profile_as_the_preview_profile(self):
        code, _, err = run(*self.args, "preview", "--no-launch", "--no-favicons", "--preview-profile", self.live)
        self.assertNotEqual(code, 0)
        self.assertIn("refusing", err)

    def test_refuses_while_a_preview_window_is_open(self):
        with mock.patch.object(preview, "instance_running", return_value=True):
            code, _, err = run(*self.args, "preview", "--no-launch", "--no-favicons", "--preview-profile", self.pdir)
        self.assertNotEqual(code, 0)
        self.assertIn("already open", err)
        self.assertFalse(os.path.exists(os.path.join(self.pdir, profile.SESSION)))

    def test_missing_zen_binary_is_a_clear_error(self):
        with mock.patch.object(preview, "zen_binary", return_value=None):
            code, _, err = run(*self.args, "preview", "--no-favicons", "--preview-profile", self.pdir)
        self.assertNotEqual(code, 0)
        self.assertIn("Zen binary", err)


if __name__ == "__main__":
    unittest.main()
