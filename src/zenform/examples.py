"""The example configs shipped inside the package, and finding config directories to tour."""

from __future__ import annotations

import os
import shutil
import tomllib
from typing import NamedTuple

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "example_configs")


class Entry(NamedTuple):
    name: str
    path: str

    @property
    def description(self) -> str:
        try:
            with open(os.path.join(self.path, "zenform.toml"), "rb") as fh:
                return tomllib.load(fh).get("description", "")
        except (OSError, tomllib.TOMLDecodeError):
            return ""


def _is_config(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "zenform.toml"))


def discover(paths: list[str]) -> list[Entry]:
    """Each path is a config directory, or a folder of config directories (taken in name order)."""
    entries: list[Entry] = []
    for raw in paths:
        path = os.path.abspath(os.path.expanduser(raw))
        if _is_config(path):
            entries.append(Entry(os.path.basename(path), path))
            continue
        found = [
            Entry(name, os.path.join(path, name))
            for name in (sorted(os.listdir(path)) if os.path.isdir(path) else [])
            if _is_config(os.path.join(path, name))
        ]
        if not found:
            raise SystemExit(f"{raw}: not a config directory (no zenform.toml) and holds none.")
        entries.extend(found)
    return entries


def bundled() -> list[Entry]:
    return discover([ROOT])


def copy_bundled(name: str, out: str) -> str:
    """Copy one bundled example to `out` so it can be edited. Refuses to overwrite an existing config."""
    match = next((e for e in bundled() if e.name == name), None)
    if match is None:
        raise SystemExit(f"No bundled example named {name!r}; try: {', '.join(e.name for e in bundled())}")
    if os.path.exists(os.path.join(out, "zenform.toml")):
        raise SystemExit(f"{out} already has a zenform.toml; refusing to overwrite it.")
    shutil.copytree(match.path, out, dirs_exist_ok=True)
    return out
