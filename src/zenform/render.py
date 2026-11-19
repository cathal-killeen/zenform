"""Turning plan operations into text for people. (`plan --json` prints the operations themselves.)"""

from __future__ import annotations

from zenform.ui import UI

PIN_OPS = ("add", "relabel", "move")


def _short(url: str) -> str:
    return url.removeprefix("https://").removeprefix("http://").removeprefix("www.")


def counts(ops: list[dict]) -> dict[str, int]:
    kinds = [o["op"] for o in ops]
    return {
        "added": kinds.count("add"),
        "relabelled": kinds.count("relabel"),
        "moved": kinds.count("move"),
        "unpinned": kinds.count("unpin"),
        "folders removed": kinds.count("remove_folder"),
    }


def summary(ops: list[dict], ui: UI) -> str:
    c = counts(ops)
    style = {
        "added": ui.green,
        "relabelled": ui.yellow,
        "moved": ui.yellow,
        "unpinned": ui.red,
        "folders removed": ui.red,
    }
    parts = [style[k](f"{n} {k}") for k, n in c.items() if n]
    return f"  {ui.dim(ui.sym('dot'))}  ".join(parts) if parts else ui.dim("nothing to change")


def _pin_line(o: dict, ui: UI, room: int) -> str:
    if o["op"] == "add":
        url = ui.dim(ui.clip(_short(o["url"]), room - len(o["label"]) - 8))
        return f"  {ui.green(ui.sym('add'))} {ui.bold(o['label'])}  {url}"
    if o["op"] == "relabel":
        old = ui.dim(ui.clip(o["from"], 34))
        return f"  {ui.yellow(ui.sym('change'))} {old} {ui.dim(ui.sym('arrow'))} {ui.bold(o['to'])}"
    return f"  {ui.yellow(ui.sym('change'))} {ui.bold(o['label'])}  {ui.dim('moved here')}"


def render_plan(ops: list[dict], ui: UI, workspace: str | None = None) -> str:
    room = ui.width
    lines: list[str] = []
    if workspace:
        lines.append(f"{ui.dim('workspace')} {ui.bold(workspace)}\n")

    # pins added, relabelled or moved, grouped by where they sit, in sidebar order
    groups: dict[str, list[dict]] = {}
    for o in ops:
        if o["op"] in PIN_OPS:
            groups.setdefault(o["where"], []).append(o)
    for where, items in groups.items():
        title = "Essentials" if where == "essentials" else "Loose pins" if where == "pins" else where
        lines.append(ui.heading(title))
        lines.extend(_pin_line(o, ui, room) for o in items)
        lines.append("")

    unpinned = [o for o in ops if o["op"] == "unpin"]
    if unpinned:
        lines.append(ui.heading("Unpinned") + ui.dim("  (the tab stays open as an ordinary tab)"))
        lines.extend(f"  {ui.red(ui.sym('remove'))} {o['label']}" for o in unpinned)
        lines.append("")
    removed = [o for o in ops if o["op"] == "remove_folder"]
    if removed:
        lines.append(ui.heading("Folders removed"))
        lines.extend(f"  {ui.red(ui.sym('remove'))} {o['folder']}" for o in removed)
        lines.append("")
    kept = [o for o in ops if o["op"] == "keep_folder"]
    if kept:
        lines.append(ui.heading("Left as they are"))
        lines.extend(f"  {ui.dim(ui.sym('keep'))} {o['folder']}" for o in kept)
        lines.append("")
    for o in ops:
        if o["op"] == "keep_missing":
            lines.append(ui.status("warn", f"keep_folders: no folder {o['folder']!r} in Zen; ignored"))

    for o in ops:
        if o["op"] == "icons":
            bits = []
            if o["filled"]:
                bits.append(ui.green(f"{o['filled']} filled"))
            if o["replaced"]:
                bits.append(ui.yellow(f"{o['replaced']} replaced"))
            if o.get("cleared"):
                bits.append(ui.yellow(f"{len(o['cleared'])} cleared") + ui.dim(" (no trustworthy icon known)"))
            if o["missing"]:
                bits.append(ui.dim("blank until opened: ") + ", ".join(o["missing"]))
            if bits:
                lines.append(f"{ui.heading('Icons')}  " + f"  {ui.dim(ui.sym('dot'))}  ".join(bits))
                lines.append("")

    lines.append(ui.rule())
    lines.append(summary(ops, ui))
    return "\n".join(lines)
