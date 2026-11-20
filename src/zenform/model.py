"""The layout and the session: applying one to the other.

`apply_layout(session, spec)` is pure: it returns a new session and a list of operations (dicts), and never
touches the input. The operations are the plan; `render.render_plan` turns them into text, `plan --json`
prints them as is.

A spec is what config.load_config builds from the files:

    {"workspace": "Work", "keep_folders": [...], "essentials": [pin], "folders": [{"name", "pins", "collapsed"?}],
     "pins": [pin]}                      # pin = {"label": ..., "url": ...}; "pins" are loose pins, after the folders
"""

from __future__ import annotations

import copy
import time
import uuid

from zenform.favicons import Favicons

MAX_LABEL = 14  # the sidebar cuts a pin's label off about here
ESSENTIALS_GRID = 9  # a 3x3 grid; more still works, as a fourth row

# Operations that change something (the others, like icons, only inform).
CHANGING = {"add", "relabel", "move", "unpin", "remove_folder"}


# --- reading a session ----------------------------------------------------------------------------


def home_url(tab: dict) -> str:
    """The page a pin goes back to: Zen's own record of it, else the page it is on."""
    init = (tab.get("_zenPinnedInitialState") or {}).get("entry") or {}
    if init.get("url"):
        return init["url"]
    entries = tab.get("entries") or [{}]
    i = (tab.get("index") or 1) - 1
    return (entries[i] if 0 <= i < len(entries) else entries[-1]).get("url", "")


def tab_label(tab: dict) -> str:
    if tab.get("zenStaticLabel"):
        return tab["zenStaticLabel"]
    init = (tab.get("_zenPinnedInitialState") or {}).get("entry") or {}
    return init.get("title") or home_url(tab)


def workspace_names(session: dict) -> list[str]:
    return [s.get("name", "?") for s in session.get("spaces", [])]


def workspace_id(session: dict, name: str) -> str:
    for space in session.get("spaces", []):
        if space.get("name") == name:
            return space["uuid"]
    raise SystemExit(f"No workspace named {name!r} in the session (it has: {', '.join(workspace_names(session))}).")


def check_session_shape(session: dict) -> list[str]:
    """What a session must have for zenform to work on it; an empty list means it looks right."""
    problems = [f"missing key {k!r}" for k in ("tabs", "folders", "groups", "spaces") if k not in session]
    for t in session.get("tabs", [])[:50]:
        if t.get("pinned") and "zenEssential" not in t:
            problems.append("a pinned tab has no zenEssential field (Zen's format may have changed)")
            break
    return problems


# --- building session entries ---------------------------------------------------------------------


def new_sync_id() -> str:
    return f"{int(time.time() * 1000)}-{uuid.uuid4()}"


def _base_tab(url: str, *, workspace, group) -> dict:
    return {
        "lastAccessed": int(time.time() * 1000),
        "pinned": True,
        "hidden": False,
        **({"groupId": group} if group else {}),
        "zenWorkspace": workspace,
        "zenSyncId": new_sync_id(),
        "zenPinnedIcon": None,
        "zenHasStaticIcon": False,
        "zenGlanceId": None,
        "zenIsGlance": False,
        "zenLiveFolderItemId": None,
        "searchMode": None,
        "userContextId": 0,
        "attributes": {},
        "index": 1,
        "userTypedValue": "",
        "userTypedClear": 0,
    }


def new_pin(label: str, url: str, *, essential: bool, group, workspace) -> dict:
    return {
        **_base_tab(url, workspace=None if essential else workspace, group=group),
        "entries": [{"url": url, "title": label}],
        "zenEssential": essential,
        "zenDefaultUserContextId": "true",
        "zenIsEmpty": False,
        "zenStaticLabel": label,
        "_zenPinnedInitialState": {"entry": {"url": url, "title": label}, "image": None},
    }


def new_placeholder(group: str, workspace: str) -> dict:
    return {
        **_base_tab("about:blank", workspace=workspace, group=group),
        "entries": [{"url": "about:blank"}],
        "zenEssential": False,
        "zenDefaultUserContextId": None,
        "zenIsEmpty": True,
        "_zenPinnedInitialState": {"entry": {"url": "about:blank"}, "image": None},
    }


def unpin(tab: dict) -> None:
    tab["pinned"] = False
    tab["zenEssential"] = False
    for key in ("groupId", "zenStaticLabel", "_zenPinnedInitialState"):
        tab.pop(key, None)
    tab["zenHasStaticIcon"] = False


# --- checking a spec ------------------------------------------------------------------------------


def _all_pins(spec: dict):
    for e in spec.get("essentials", []):
        yield "essentials", e
    for f in spec.get("folders", []):
        for p in f.get("pins", []):
            yield f.get("name", "?"), p
    for p in spec.get("pins", []):
        yield "pins", p


def validate_spec(spec: dict) -> list[str]:
    problems = []
    if not spec.get("workspace"):
        problems.append('the config needs workspace = "..." in zenform.toml')
    for f in spec.get("folders", []):
        if not f.get("name"):
            problems.append("a folder has no name")
    for _, it in _all_pins(spec):
        if not it.get("label") or not it.get("url"):
            problems.append(f"every pin needs a label and a url: {it}")
    names = [f.get("name") for f in spec.get("folders", [])]
    if len(set(names)) != len(names):
        problems.append("two folders have the same name")
    both = set(names) & set(spec.get("keep_folders", []))
    if both:
        problems.append(f"folders both defined and in keep_folders: {sorted(both)}")
    return problems


def warnings(spec: dict) -> list[str]:
    out = []
    seen: dict[str, str] = {}
    if len(spec.get("essentials", [])) > ESSENTIALS_GRID:
        out.append(f"{len(spec['essentials'])} essentials: more than the {ESSENTIALS_GRID} of a 3x3 grid")
    for where, it in _all_pins(spec):
        if len(it["label"]) > MAX_LABEL:
            out.append(
                f"label {it['label']!r} ({where}) is {len(it['label'])} characters; the sidebar shows about {MAX_LABEL}"
            )
        if it["url"] in seen:
            out.append(f"{it['url']} is pinned twice ({seen[it['url']]} and {where})")
        seen[it["url"]] = where
    return out


# --- applying -------------------------------------------------------------------------------------


def apply_layout(
    session: dict,
    spec: dict,
    *,
    reset_pins: bool = False,
    favicons: Favicons | None = None,
    fresh_icons: bool = False,
):
    """Return (new_session, ops). Pure: the input is not changed."""
    problems = validate_spec(spec)
    if problems:
        raise SystemExit("Config problems:\n  " + "\n  ".join(problems))
    s = copy.deepcopy(session)
    ws = workspace_id(s, spec["workspace"])
    tabs: list[dict] = s["tabs"]
    ops: list[dict] = []

    old_folders = {f["name"]: f for f in s.get("folders", []) if f.get("workspaceId") == ws}
    kept = {n: old_folders[n] for n in spec.get("keep_folders", []) if n in old_folders}
    kept_ids = {f["id"] for f in kept.values()}
    for n in spec.get("keep_folders", []):
        if n not in old_folders:
            ops.append({"op": "keep_missing", "folder": n})

    def in_scope(t):  # what the config owns: essentials, and this workspace's pins outside kept folders
        return (
            t.get("pinned")
            and t.get("groupId") not in kept_ids
            and (t.get("zenEssential") or t.get("zenWorkspace") == ws)
        )

    pool = [t for t in tabs if in_scope(t) and not t.get("zenIsEmpty")]
    placeholders = [t for t in tabs if in_scope(t) and t.get("zenIsEmpty")]
    used: set[int] = set()
    icons_filled: list[str] = []  # had none, now has one
    icons_replaced: list[str] = []  # had a different one (often a sign-in page's generic icon); the page's own wins
    icons_cleared: list[str] = []  # fresh_icons: had one, none can be trusted, so it is dropped
    icons_missing: list[str] = []  # none known and nothing trustworthy to use

    def give_icon(t, label, url):
        init = t.setdefault("_zenPinnedInitialState", {"entry": {"url": url, "title": label}, "image": None})
        prior = init.get("image") or t.get("image")
        image = prior
        if favicons is not None:
            match = favicons.find(url)
            if match:
                if match.uri != prior:
                    (icons_replaced if prior else icons_filled).append(label)
                image = match.uri
            elif fresh_icons:  # distrust what is stored: keep an icon only if the page's own can be found
                image = None
                (icons_cleared if prior else icons_missing).append(label)
            elif not prior:
                icons_missing.append(label)
        init["image"] = image
        t["image"] = image
        if image is None:
            t.pop("image", None)

    def take(url):
        for t in pool:
            if id(t) not in used and home_url(t) == url:
                used.add(id(t))
                return t
        return None

    def place(label, url, *, essential, group, where):
        t = take(url)
        if t is None:
            t = new_pin(label, url, essential=essential, group=group, workspace=ws)
            ops.append({"op": "add", "where": where, "label": label, "url": url})
        else:
            old = tab_label(t)
            moved = bool(t.get("zenEssential")) != essential or t.get("groupId") != group
            if old != label:
                ops.append({"op": "relabel", "where": where, "from": old, "to": label, "url": url})
            elif moved:
                ops.append({"op": "move", "where": where, "label": label, "url": url})
            t["zenStaticLabel"] = label
            t["zenEssential"] = essential
            t["zenWorkspace"] = None if essential else ws
            if group:
                t["groupId"] = group
            else:
                t.pop("groupId", None)
            if reset_pins:
                t["entries"] = [{"url": url, "title": label}]
                t["index"] = 1
        t["pinned"] = True
        give_icon(t, label, url)
        return t

    ordered: list[dict] = []
    for e in spec.get("essentials", []):
        ordered.append(place(e["label"], e["url"], essential=True, group=None, where="essentials"))

    # Folders: reuse one with the same name (and its collapsed state), else make it.
    old_groups = {g["id"]: g for g in s.get("groups", [])}
    keep_ids: set[str] = set()
    new_folders: list[dict] = []
    new_groups: list[dict] = []
    prev = None
    for f in spec.get("folders", []):
        old = old_folders.get(f["name"])
        fid = old["id"] if old else f"{int(time.time() * 1000)}-{len(new_folders) + 1}"
        keep_ids.add(fid)
        collapsed = f.get("collapsed", old["collapsed"] if old else False)
        ph = next((p for p in placeholders if p.get("groupId") == fid), None)
        if ph is None:
            ph = new_placeholder(fid, ws)
        ordered.append(ph)
        for p in f.get("pins", []):
            ordered.append(place(p["label"], p["url"], essential=False, group=fid, where=f["name"]))
        folder = (
            dict(old)
            if old
            else {
                "pinned": True,
                "splitViewGroup": False,
                "id": fid,
                "name": f["name"],
                "saveOnWindowClose": True,
                "parentId": None,
                "userIcon": "",
                "workspaceId": ws,
            }
        )
        folder.update(
            collapsed=collapsed,
            emptyTabIds=[ph["zenSyncId"]],
            prevSiblingInfo={"type": "group", "id": prev} if prev else None,
        )
        new_folders.append(folder)
        group = (
            dict(old_groups[fid])
            if fid in old_groups
            else {
                "pinned": True,
                "splitView": False,
                "id": fid,
                "name": f["name"],
                "color": "zen-workspace-color",
                "saveOnWindowClose": True,
            }
        )
        group["collapsed"] = collapsed
        new_groups.append(group)
        prev = fid
    for p in spec.get("pins", []):
        ordered.append(place(p["label"], p["url"], essential=False, group=None, where="pins"))

    # Folders named in keep_folders come last, exactly as they were.
    for name, old in kept.items():
        ops.append({"op": "keep_folder", "folder": name})
        ordered.extend(t for t in tabs if t.get("groupId") == old["id"])
        folder = dict(old)
        folder["prevSiblingInfo"] = {"type": "group", "id": prev} if prev else None
        new_folders.append(folder)
        new_groups.append(
            dict(old_groups[old["id"]])
            if old["id"] in old_groups
            else {
                "pinned": True,
                "splitView": False,
                "id": old["id"],
                "name": name,
                "color": "zen-workspace-color",
                "collapsed": old.get("collapsed", False),
                "saveOnWindowClose": True,
            }
        )
        prev = old["id"]

    if favicons is not None:
        ops.append(
            {
                "op": "icons",
                "filled": len(icons_filled),
                "replaced": len(icons_replaced),
                "cleared": icons_cleared,
                "missing": icons_missing,
            }
        )

    # Everything the config owned and no longer lists becomes an ordinary tab.
    for t in pool:
        if id(t) not in used:
            ops.append({"op": "unpin", "label": tab_label(t), "url": home_url(t)})
            unpin(t)
    for n, f in old_folders.items():
        if f["id"] not in keep_ids and f["id"] not in kept_ids:
            ops.append({"op": "remove_folder", "folder": n})
    gone = {id(p) for p in placeholders if p.get("groupId") not in keep_ids}  # kept folders are not in placeholders
    in_ordered = {id(t) for t in ordered}
    rest = [t for t in tabs if id(t) not in gone and id(t) not in in_ordered]
    s["tabs"] = ordered + rest
    ours = {f["id"] for f in old_folders.values()}
    s["folders"] = [f for f in s.get("folders", []) if f.get("workspaceId") != ws] + new_folders
    s["groups"] = [g for g in s.get("groups", []) if g["id"] not in ours] + new_groups
    return s, ops


def check(session: dict, spec: dict) -> list[str]:
    """After writing: does the session say what the config says?"""
    ws = workspace_id(session, spec["workspace"])
    errs = []
    ess = [(tab_label(t), home_url(t)) for t in session["tabs"] if t.get("zenEssential")]
    want = [(e["label"], e["url"]) for e in spec.get("essentials", [])]
    if ess != want:
        errs.append(f"essentials differ: {ess} != {want}")
    folders = {f["name"]: f for f in session.get("folders", []) if f.get("workspaceId") == ws}
    for f in spec.get("folders", []):
        fo = folders.get(f["name"])
        if not fo:
            errs.append(f"folder {f['name']} missing")
            continue
        got = [
            (tab_label(t), home_url(t))
            for t in session["tabs"]
            if t.get("groupId") == fo["id"] and not t.get("zenIsEmpty")
        ]
        exp = [(p["label"], p["url"]) for p in f.get("pins", [])]
        if got != exp:
            errs.append(f"folder {f['name']} differs: {got} != {exp}")
        if not any(t.get("zenSyncId") in fo["emptyTabIds"] for t in session["tabs"]):
            errs.append(f"folder {f['name']} lost its placeholder")
    extra = set(folders) - {f["name"] for f in spec.get("folders", [])} - set(spec.get("keep_folders", []))
    if extra:
        errs.append(f"unexpected folders: {sorted(extra)}")
    return errs


def changes(ops: list[dict]) -> list[dict]:
    return [o for o in ops if o["op"] in CHANGING]
