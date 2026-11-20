"""The config directory: reading it into a spec, and writing the current browser state out as one.

    zenform.toml        workspace = "Work"          which workspace; keep_folders = [...]
    essentials.toml     pins = [ {label, url}, ]    the icon tiles
    folders/NN-name.toml  name = "MRs"              one file per pinned folder, in file-name order
                          pins = [ {label, url}, ]
    loose.toml          pins = [ ... ]              optional: pins outside any folder, after the folders

Unknown keys are errors, so a typo does not silently do nothing.
"""

from __future__ import annotations

import json
import os
import re
import tomllib

from zenform import model

ROOT_KEYS = {"workspace", "keep_folders", "description"}
PINS_KEYS = {"pins"}
FOLDER_KEYS = {"name", "collapsed", "pins"}
PIN_KEYS = {"label", "url"}


def _load(path: str, allowed: set[str]) -> dict:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"{path}: not valid TOML: {e}") from None
    unknown = set(data) - allowed
    if unknown:
        raise SystemExit(f"{path}: unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}")
    for pin in data.get("pins", []):
        bad = set(pin) - PIN_KEYS
        if bad:
            raise SystemExit(f"{path}: a pin has unknown key(s) {sorted(bad)}; allowed: {sorted(PIN_KEYS)}")
    return data


def find_config(arg: str | None) -> str:
    path = arg or os.environ.get("ZENFORM_CONFIG") or os.getcwd()
    if not os.path.isfile(os.path.join(path, "zenform.toml")):
        raise SystemExit(f"No zenform.toml in {path}. Pass --config DIR or set ZENFORM_CONFIG (see `zenform dump`).")
    return path


def load_config(path: str) -> dict:
    root = _load(os.path.join(path, "zenform.toml"), ROOT_KEYS)
    spec: dict = {
        "workspace": root.get("workspace"),
        "keep_folders": root.get("keep_folders", []),
        "essentials": [],
        "folders": [],
        "pins": [],
    }
    ess = os.path.join(path, "essentials.toml")
    if os.path.isfile(ess):
        spec["essentials"] = _load(ess, PINS_KEYS).get("pins", [])
    folders = os.path.join(path, "folders")
    if os.path.isdir(folders):
        for name in sorted(os.listdir(folders)):
            if name.endswith(".toml"):
                f = _load(os.path.join(folders, name), FOLDER_KEYS)
                if not f.get("name"):
                    raise SystemExit(f'{os.path.join(folders, name)}: a folder needs name = "..."')
                spec["folders"].append(f)
    loose = os.path.join(path, "loose.toml")
    if os.path.isfile(loose):
        spec["pins"] = _load(loose, PINS_KEYS).get("pins", [])
    return spec


# --- writing ----------------------------------------------------------------------------------------


def _s(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _pins_block(pins: list[dict]) -> str:
    if not pins:
        return "pins = []\n"
    width = max(len(_s(p["label"])) for p in pins)
    rows = [f"  {{label = {_s(p['label']) + ',':<{width + 1}} url = {_s(p['url'])}}}," for p in pins]
    return "pins = [\n" + "\n".join(rows) + "\n]\n"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "folder"


def current_spec(session: dict, workspace: str) -> dict:
    """The session's pins for one workspace, as a spec."""
    ws = model.workspace_id(session, workspace)
    tabs = session["tabs"]

    def pin(t):
        return {"label": model.tab_label(t), "url": model.home_url(t)}

    folders = []
    for f in session.get("folders", []):
        if f.get("workspaceId") == ws:
            pins = [pin(t) for t in tabs if t.get("groupId") == f["id"] and not t.get("zenIsEmpty")]
            folders.append({"name": f["name"], "pins": pins})
    return {
        "workspace": workspace,
        "keep_folders": [],
        "essentials": [pin(t) for t in tabs if t.get("zenEssential")],
        "folders": folders,
        "pins": [
            pin(t)
            for t in tabs
            if t.get("pinned")
            and not t.get("zenEssential")
            and t.get("zenWorkspace") == ws
            and not t.get("groupId")
            and not t.get("zenIsEmpty")
        ],
    }


def write_config(spec: dict, outdir: str, *, force: bool = False) -> list[str]:
    """Write a spec as a config directory. Refuses to overwrite an existing one unless force."""
    if os.path.exists(os.path.join(outdir, "zenform.toml")) and not force:
        raise SystemExit(f"{outdir} already has a zenform.toml; use --force to overwrite.")
    os.makedirs(os.path.join(outdir, "folders"), exist_ok=True)
    for old in os.listdir(os.path.join(outdir, "folders")):
        if old.endswith(".toml"):
            os.unlink(os.path.join(outdir, "folders", old))
    written = []

    def put(rel: str, text: str) -> None:
        path = os.path.join(outdir, rel)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        written.append(path)

    keep = ", ".join(_s(n) for n in spec.get("keep_folders", []))
    put(
        "zenform.toml",
        f"# zenform config: `zenform plan` shows what applying it would change; `zenform apply` does it (Zen closed).\n"
        f"workspace = {_s(spec['workspace'])}\n\n"
        f"# Folders zenform never touches (Zen manages these itself).\n"
        f"keep_folders = [{keep}]\n",
    )
    put(
        "essentials.toml",
        "# The icon tiles. label: 14 characters or fewer. url: the pin's home page.\n"
        + _pins_block(spec["essentials"]),
    )
    for i, f in enumerate(spec["folders"], start=1):
        put(
            f"folders/{i * 10:02d}-{_slug(f['name'])}.toml",
            f"name = {_s(f['name'])}\n\n" + _pins_block(f["pins"]),
        )
    if spec.get("pins"):
        put("loose.toml", "# Pins outside any folder, shown after the folders.\n" + _pins_block(spec["pins"]))
    return written
