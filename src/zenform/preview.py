"""Preview a config in a separate Zen instance on its own profile, so the real profile is never touched.

`prepare` writes the new session into the preview profile (plus a few look-and-feel files from the real one) and
`launch` starts a second Zen on it with `-no-remote`, the way web-ext does for a dev run. The real Zen can stay open.

Never copied from the real profile: cookies, logins, history, bookmarks, extensions. The preview shows the layout, not
your accounts, so pages in it are signed out.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

from zenform import mozlz4, profile

ENV_PROFILE = "ZENFORM_PREVIEW_PROFILE"
ENV_BIN = "ZENFORM_ZEN_BIN"

# Copied so the preview looks like your Zen (theme, sidebar, toolbar, shortcuts). An allowlist, never a denylist.
COPY_FILES = ("prefs.js", "containers.json", "zen-themes.json", "zen-keyboard-shortcuts.json")
COPY_DIRS = ("chrome",)

# What a previous preview left that would make Zen restore old tabs instead of the new session.
STALE = (
    "zen-sessions.jsonlz4",
    "zen-sessions-backup",
    "sessionstore.jsonlz4",
    "sessionstore-backups",
    "sessionCheckpoints.json",
)

USER_JS = """\
// Written by `zenform preview`: keeps the preview window free of first-run prompts and updates.
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("app.update.auto", false);
user_pref("app.update.enabled", false);
"""


def default_preview_profile() -> str:
    return os.environ.get(ENV_PROFILE) or os.path.expanduser("~/.zenform-preview-profile")


def zen_binary() -> str | None:
    candidates = [
        os.environ.get(ENV_BIN),
        "/Applications/Zen.app/Contents/MacOS/zen",
        os.path.expanduser("~/Applications/Zen.app/Contents/MacOS/zen"),
        shutil.which("zen"),
        shutil.which("zen-bin"),
    ]
    return next((c for c in candidates if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)


def check_safe(preview: str, live: str) -> None:
    """Refuse to ever use the real profile, or any profile Zen itself registers, as the preview profile."""
    p, lv = os.path.realpath(preview), os.path.realpath(live)
    zen_dir = os.path.realpath(profile.data_dir())
    if p == lv or os.path.commonpath([p, zen_dir]) == zen_dir:
        raise SystemExit(
            f"{preview} is a real Zen profile (or inside Zen's own data folder); refusing to overwrite it.\n"
            f"Use another folder: --preview-profile PATH or ${ENV_PROFILE}."
        )


def instance_running(preview: str) -> bool:
    """Is a Zen already running on this profile? (Its command line names the profile folder.)"""
    try:
        ps = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    path = os.path.realpath(preview)
    return any(" -profile" in line and (preview in line or path in line) for line in ps.splitlines())


def prepare(live: str, session: dict, preview: str) -> list[str]:
    """Make `preview` hold `session` and the allowlisted look-and-feel files. The live profile is only read."""
    os.makedirs(preview, exist_ok=True)
    for name in STALE:
        path = os.path.join(preview, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.unlink(path)
    copied = []
    for name in COPY_FILES:
        src = os.path.join(live, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(preview, name))
            copied.append(name)
    for name in COPY_DIRS:
        src = os.path.join(live, name)
        if os.path.isdir(src):
            dest = os.path.join(preview, name)
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(src, dest)
            copied.append(name + "/")
    with open(os.path.join(preview, "user.js"), "w", encoding="utf-8") as fh:
        fh.write(USER_JS)
    target = os.path.join(preview, profile.SESSION)
    with open(target + ".tmp", "wb") as fh:
        fh.write(mozlz4.encode(session))
    os.replace(target + ".tmp", target)
    return copied


def stop(proc: subprocess.Popen, preview: str, timeout: float = 30.0) -> None:
    """Close a preview window: ask Zen to quit (it saves its session), wait, and kill it only if it will not."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    end = time.monotonic() + timeout
    while instance_running(preview) and time.monotonic() < end:  # helper processes can outlive the main one
        time.sleep(0.2)


def command(binary: str, preview: str) -> list[str]:
    return [binary, "-profile", preview, "-no-remote"]


def launch(binary: str, preview: str) -> subprocess.Popen:
    return subprocess.Popen(
        command(binary, preview),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
