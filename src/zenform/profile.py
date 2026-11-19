"""Finding the Zen profile, knowing whether Zen is running, and backing the session file up."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time

SESSION = "zen-sessions.jsonlz4"
BACKUPS = "zenform-backups"


def data_dir() -> str:
    """Where Zen keeps profiles.ini. Only macOS has been tested."""
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/zen")
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("APPDATA", ""), "zen")
    flatpak = os.path.expanduser("~/.var/app/app.zen_browser.zen/.zen")
    return flatpak if os.path.isdir(flatpak) else os.path.expanduser("~/.zen")


def default_profile() -> str:
    """The profile Zen starts with: the install's Default, else the profile flagged Default=1."""
    base = data_dir()
    ini = os.path.join(base, "profiles.ini")
    if not os.path.exists(ini):
        raise SystemExit(f"No profiles.ini in {base}; pass --profile.")
    sections: dict[str, dict[str, str]] = {}
    section = None
    with open(ini, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("["):
                section = line.strip("[]")
                sections.setdefault(section, {})
            elif "=" in line and section:
                k, v = line.split("=", 1)
                sections[section][k] = v
    install_default = flagged = None
    for name, kv in sections.items():
        if name.startswith("Install") and "Default" in kv:
            install_default = kv["Default"]
        if name.startswith("Profile"):
            if kv.get("Default") == "1":
                flagged = kv.get("Path")
    rel = install_default or flagged
    path = os.path.join(base, rel) if rel else None
    if not path or not os.path.isdir(path):
        raise SystemExit("Could not find the Zen profile; pass --profile.")
    return path


def zen_running() -> bool:
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq zen.exe"], capture_output=True, text=True).stdout
            return "zen.exe" in out
        ps = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    for line in ps.splitlines():
        first = line.split(" -", 1)[0]
        if "/Contents/MacOS/zen" in first or first.endswith(("/zen", "/zen-bin")):
            return True
    return False


def zen_version() -> str | None:
    """The installed app's version (macOS), or None."""
    for app in ("/Applications/Zen.app", os.path.expanduser("~/Applications/Zen.app")):
        plist = os.path.join(app, "Contents", "Info.plist")
        if os.path.exists(plist):
            with open(plist, "rb") as fh:
                return plistlib.load(fh).get("CFBundleShortVersionString")
    return None


def backup(profile: str) -> str:
    folder = os.path.join(profile, BACKUPS)
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, f"{SESSION}.{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(os.path.join(profile, SESSION), dest)
    return dest


def newest_backup(profile: str) -> str | None:
    folder = os.path.join(profile, BACKUPS)
    files = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    return os.path.join(folder, files[-1]) if files else None
