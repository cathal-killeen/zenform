"""The zenform command line: doctor, dump, plan, apply, preview, examples, tour, rollback."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from zenform import TESTED_ZEN, __version__, config, examples, model, mozlz4, preview, profile, render, tour
from zenform.favicons import Favicons
from zenform.ui import UI


def _load_session(prof: str) -> dict:
    path = os.path.join(prof, profile.SESSION)
    if not os.path.exists(path):
        raise SystemExit(f"No {profile.SESSION} in {prof}. Has Zen been opened with this profile?")
    try:
        session = mozlz4.read(path)
    except ValueError:  # Zen may be mid-write; try once more
        time.sleep(0.5)
        session = mozlz4.read(path)
    problems = model.check_session_shape(session)
    if problems:
        raise SystemExit(
            "This session file does not look like the format zenform knows:\n  "
            + "\n  ".join(problems)
            + "\nRun `zenform doctor`; Zen may have changed its format."
        )
    return session


def _plan(args, prof: str, *, fresh_icons: bool = False):
    cfg = config.find_config(args.config)
    spec = config.load_config(cfg)
    session = _load_session(prof)
    icons = None if args.no_favicons else Favicons(prof)
    fresh = fresh_icons or getattr(args, "redo_icons", False)
    new, ops = model.apply_layout(session, spec, reset_pins=args.reset_pins, favicons=icons, fresh_icons=fresh)
    return cfg, spec, session, new, ops


def _warn(args, spec: dict) -> None:
    for w in model.warnings(spec):
        print(args.ui_err.status("warn", w), file=sys.stderr)


def _title(ui: UI, name: str, detail: str = "") -> str:
    return f"{ui.heading('zenform ' + name)}" + (f"  {ui.dim(detail)}" if detail else "")


def cmd_doctor(args) -> int:
    ui = args.ui
    ok = True

    def line(kind, text):
        nonlocal ok
        ok = ok and kind != "fail"
        print(ui.status(kind, text))

    print(_title(ui, "doctor") + "\n")
    line("ok", f"zenform {__version__}, Python {sys.version.split()[0]}")
    try:
        prof = args.profile or profile.default_profile()
        line("ok", f"profile: {prof}")
    except SystemExit as e:
        line("fail", str(e))
        return 1
    version = profile.zen_version()
    if version is None:
        line("warn", "could not read the installed Zen version")
    elif version in TESTED_ZEN:
        line("ok", f"Zen {version} (tested)")
    else:
        line(
            "warn",
            f"Zen {version} has not been tested (tested: {', '.join(TESTED_ZEN)}); plan output is still safe to read",
        )
    running = profile.zen_running()
    line("warn" if running else "ok", "Zen is running: close it before `apply`" if running else "Zen is closed")
    try:
        session = _load_session(prof)
        names = ", ".join(model.workspace_names(session)) or "none"
        pinned = sum(1 for t in session["tabs"] if t.get("pinned") and not t.get("zenIsEmpty"))
        line("ok", f"session readable: {pinned} pins, {len(session['folders'])} folders, workspaces: {names}")
    except (SystemExit, ValueError) as e:
        line("fail", f"session: {e}")
    backups = os.path.join(prof, profile.BACKUPS)
    line("ok", f"{len(os.listdir(backups)) if os.path.isdir(backups) else 0} backup(s) in {profile.BACKUPS}/")
    try:
        cfg = config.find_config(args.config)
        spec = config.load_config(cfg)
        problems = model.validate_spec(spec)
        line("fail" if problems else "ok", f"config {cfg}: " + ("; ".join(problems) if problems else "valid"))
        for w in model.warnings(spec):
            line("warn", w)
    except SystemExit as e:
        line("warn", f"config: {e}")
    return 0 if ok else 1


def cmd_dump(args) -> int:
    ui = args.ui
    prof = args.profile or profile.default_profile()
    session = _load_session(prof)
    names = model.workspace_names(session)
    ws = args.workspace or (names[0] if len(names) == 1 else None)
    if not ws:
        raise SystemExit(f"Several workspaces ({', '.join(names)}); pass --workspace.")
    written = config.write_config(config.current_spec(session, ws), args.out, force=args.force)
    print(ui.status("ok", f"wrote {len(written)} files to {ui.bold(args.out)}"))
    for p in written:
        print(f"  {ui.dim(os.path.relpath(p, args.out))}")
    print(ui.dim(f"\nEdit them, then: zenform --config {args.out} plan"))
    return 0


def cmd_plan(args) -> int:
    ui = args.ui
    prof = args.profile or profile.default_profile()
    _, spec, _, _, ops = _plan(args, prof)
    if args.json:
        print(
            json.dumps(
                {"workspace": spec["workspace"], "changes": ops, "warnings": model.warnings(spec)},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        _warn(args, spec)
        print(_title(ui, "plan") + "\n")
        print(render.render_plan(ops, ui, spec["workspace"]))
        print(ui.dim("\nA plan only: nothing was written. Quit Zen, then run `zenform apply`."))
    return 2 if args.exit_code and model.changes(ops) else 0


def cmd_apply(args) -> int:
    ui = args.ui
    prof = args.profile or profile.default_profile()
    _, spec, _, new, ops = _plan(args, prof)
    _warn(args, spec)
    print(_title(ui, "apply") + "\n")
    print(render.render_plan(ops, ui, spec["workspace"]) + "\n")
    if profile.zen_running() and not args.force_running:
        raise SystemExit("Zen is open. Quit it first (it rewrites the file when it quits), then run again.")
    problems = model.check(new, spec)
    if problems:
        raise SystemExit("The result does not match the config, nothing written:\n  " + "\n  ".join(problems))
    session_path = os.path.join(prof, profile.SESSION)
    saved = profile.backup(prof)
    print(ui.status("ok", f"backed up to {ui.dim(saved)}"))
    tmp = session_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(mozlz4.encode(new))
    os.replace(tmp, session_path)
    after = model.check(mozlz4.read(session_path), spec)
    if after:
        shutil.copy2(saved, session_path)
        raise SystemExit("Read-back check failed, backup restored:\n  " + "\n  ".join(after))
    print(ui.status("ok", "written, and read back to check"))
    print(ui.dim("\nUndo with: zenform rollback  (Zen closed)"))
    return 0


def _preview_session(new: dict, args) -> dict:
    return new if args.keep_tabs else preview.sidebar_only(new)


def cmd_preview(args) -> int:
    """Show the new layout in a separate Zen on a throwaway profile. The real profile is only read."""
    ui = args.ui
    prof = args.profile or profile.default_profile()
    _, spec, _, new, ops = _plan(
        args, prof, fresh_icons=True
    )  # throwaway: show the page-accurate icons, not stored ones
    _warn(args, spec)
    print(_title(ui, "preview") + "\n")
    print(render.render_plan(ops, ui, spec["workspace"]) + "\n")
    problems = model.check(new, spec)
    if problems:
        raise SystemExit("The result does not match the config, nothing prepared:\n  " + "\n  ".join(problems))
    pdir = args.preview_profile or preview.default_preview_profile()
    preview.check_safe(pdir, prof)
    if preview.instance_running(pdir):
        raise SystemExit(f"A preview window is already open on {pdir}. Close it first, then run preview again.")
    binary = None if args.no_launch else preview.zen_binary()
    if not args.no_launch and not binary:
        raise SystemExit(f"Could not find the Zen binary. Set ${preview.ENV_BIN}, or use --no-launch.")
    copied = preview.prepare(prof, _preview_session(new, args), pdir)
    extra = ui.dim(f"  (with {', '.join(copied)} from your profile)") if copied else ""
    print(ui.status("ok", f"preview profile ready at {ui.bold(pdir)}{extra}"))
    if args.no_launch:
        cmd = " ".join(f'"{c}"' if " " in c else c for c in preview.command("<zen binary>", pdir))
        print(ui.dim(f"  open it with: {cmd}"))
        return 0
    preview.launch(binary, pdir)
    print(ui.status("ok", "opened a separate Zen window; your real Zen was not touched"))
    print(ui.dim("  Pages there are signed out. Close the window when done, then `zenform apply` (Zen closed)."))
    return 0


def _interactive() -> bool:
    return sys.stdin.isatty()


def _fit_workspace(spec: dict, session: dict, requested: str | None, out=print) -> dict:
    """Examples name a workspace of their own; show them in yours (the only one, or --workspace)."""
    names = model.workspace_names(session)
    if requested:
        return {**spec, "workspace": requested}
    if spec.get("workspace") not in names and len(names) == 1:
        out(f"  (workspace {spec.get('workspace')!r} shown in {names[0]!r}, your only workspace)")
        return {**spec, "workspace": names[0]}
    return spec


def _resolve_tour_paths(paths: list[str]) -> list[str]:
    """A name that is not a path but is a bundled example means that example."""
    bundled = {e.name: e.path for e in examples.bundled()}
    return [p if os.path.exists(os.path.expanduser(p)) or p not in bundled else bundled[p] for p in paths]


def _size(path: str) -> str:
    spec = config.load_config(path)
    pins = sum(len(f.get("pins", [])) for f in spec["folders"]) + len(spec["pins"])
    return f"{len(spec['essentials'])} essentials, {len(spec['folders'])} folders, {pins} pins"


def cmd_examples(args) -> int:
    ui = args.ui
    entries = examples.bundled()
    if args.name:
        if not args.out:
            raise SystemExit("Pass --out DIR to copy an example there.")
        out = examples.copy_bundled(args.name, args.out)
        print(ui.status("ok", f"copied the {ui.bold(args.name)} example to {out}"))
        print(ui.dim(f"  Edit it, then: zenform --config {out} preview"))
        return 0
    print(_title(ui, "examples") + "\n")
    width = max(len(e.name) for e in entries)
    for e in entries:
        print(f"  {ui.heading(f'{e.name:<{width}}')}  {e.description}")
        print(f"  {' ' * width}  {ui.dim(_size(e.path))}")
    print(ui.dim("\nSee them one after another: zenform tour     Start from one: zenform examples NAME --out DIR"))
    return 0


def _dots(ui: UI, i: int, n: int) -> str:
    return " ".join(ui.cyan(ui.sym("on")) if k == i else ui.dim(ui.sym("off")) for k in range(n))


def cmd_tour(args) -> int:
    """Preview several configs in turn (the bundled examples by default), each in the preview window."""
    ui = args.ui
    if not _interactive():
        raise SystemExit("tour is interactive (it waits for Enter between configs): run it in a terminal.")
    prof = args.profile or profile.default_profile()
    session = _load_session(prof)
    entries = examples.discover(_resolve_tour_paths(args.paths) if args.paths else [examples.ROOT])
    pdir = args.preview_profile or preview.default_preview_profile()
    preview.check_safe(pdir, prof)
    if preview.instance_running(pdir):
        raise SystemExit(f"A preview window is already open on {pdir}. Close it first, then run tour again.")
    binary = preview.zen_binary()
    if not binary:
        raise SystemExit(f"Could not find the Zen binary. Set ${preview.ENV_BIN}.")
    icons = None if args.no_favicons else Favicons(prof)

    def show(entry, i, n):
        spec = _fit_workspace(config.load_config(entry.path), session, args.workspace, out=lambda m: print(ui.dim(m)))
        new, ops = model.apply_layout(session, spec, favicons=icons, fresh_icons=True)
        problems = model.check(new, spec)
        if problems:
            raise SystemExit(f"{entry.name}: the result does not match the config:\n  " + "\n  ".join(problems))
        preview.prepare(prof, _preview_session(new, args), pdir)
        proc = preview.launch(binary, pdir)
        print(f"\n{_dots(ui, i, n)}  {ui.heading(entry.name)}  {ui.dim(f'{i + 1}/{n}')}")
        if entry.description:
            print(f"  {entry.description}")
        print(f"  {ui.dim('against your layout:')} {render.summary(ops, ui)}")
        return lambda: preview.stop(proc, pdir)

    n = len(entries)
    intro = (
        f"{_title(ui, 'tour')}  {ui.dim(f'{n} layout(s)')}\n"
        f"{ui.dim('Enter')} next   {ui.dim('p')} previous   {ui.dim(f'1-{n}')} jump   {ui.dim('q')} quit"
    )
    prompt = f"  {ui.cyan('›' if ui.unicode else '>')} "
    tour.run_tour(entries, show, lambda _p: input(prompt), out=print, intro=intro)
    print(ui.status("ok", "done; your real Zen was not touched"))
    return 0


def cmd_rollback(args) -> int:
    ui = args.ui
    prof = args.profile or profile.default_profile()
    if profile.zen_running() and not args.force_running:
        raise SystemExit("Zen is open. Quit it first (it rewrites the file when it quits).")
    backup = profile.newest_backup(prof)
    if not backup:
        raise SystemExit("No backup to restore.")
    shutil.copy2(backup, os.path.join(prof, profile.SESSION))
    print(ui.status("ok", f"restored {ui.dim(backup)}"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="zenform", description="Zen browser as code: plan and apply your sidebar from files."
    )
    ap.add_argument("--version", action="version", version=f"zenform {__version__}")
    ap.add_argument("--config", help="the config directory (default: $ZENFORM_CONFIG, else the current directory)")
    ap.add_argument("--profile", help="a Zen profile folder (default: the one Zen starts with)")
    ap.add_argument(
        "--color", choices=("auto", "always", "never"), default="auto", help="colour the output (default: auto)"
    )
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check the profile, the Zen version, the session format and the config").set_defaults(
        fn=cmd_doctor
    )

    d = sub.add_parser("dump", help="write the current pins as a config directory (start here)")
    d.add_argument("--out", required=True, help="directory to write the config to")
    d.add_argument("--workspace", help="the workspace (default: the only one)")
    d.add_argument("--force", action="store_true", help="overwrite an existing config")
    d.set_defaults(fn=cmd_dump)

    for name, fn, helptext in (
        ("plan", cmd_plan, "show what applying would change; writes nothing"),
        ("apply", cmd_apply, "apply the config (Zen must be closed); backs up first"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--reset-pins", action="store_true", help="also send each pin back to its home page")
        p.add_argument("--no-favicons", action="store_true", help="do not fill in or correct pin icons")
        p.add_argument(
            "--redo-icons",
            action="store_true",
            help="ignore the icons pins already have: use the page's own, or leave blank until opened",
        )
        if name == "plan":
            p.add_argument("--json", action="store_true", help="print the plan as JSON")
            p.add_argument("--exit-code", action="store_true", help="exit 2 if there is anything to change")
        else:
            p.add_argument("--force-running", action="store_true", help="do not refuse while Zen is open")
        p.set_defaults(fn=fn)

    v = sub.add_parser("preview", help="show the new layout in a separate Zen window; your real profile is untouched")
    v.add_argument(
        "--preview-profile",
        help=f"folder for the preview profile (default: ${preview.ENV_PROFILE}, else ~/.zenform-preview-profile)",
    )
    v.add_argument("--no-launch", action="store_true", help="prepare the preview profile but do not open Zen")
    v.add_argument("--keep-tabs", action="store_true", help="also show your open tabs (default: the sidebar only)")
    v.add_argument("--reset-pins", action="store_true", help="also send each pin back to its home page")
    v.add_argument("--no-favicons", action="store_true", help="do not fill in or correct pin icons")
    v.set_defaults(fn=cmd_preview)

    ex = sub.add_parser("examples", help="list the bundled example configs, or copy one to start from")
    ex.add_argument("name", nargs="?", help="an example to copy (with --out)")
    ex.add_argument("--out", help="directory to copy the example to")
    ex.set_defaults(fn=cmd_examples)

    t = sub.add_parser("tour", help="preview several configs in turn (the bundled examples by default)")
    t.add_argument("paths", nargs="*", help="config directories, folders of them, or bundled example names")
    t.add_argument("--preview-profile", help="folder for the preview profile (as for preview)")
    t.add_argument("--workspace", help="show each config in this workspace (default: your only one)")
    t.add_argument("--keep-tabs", action="store_true", help="also show your open tabs (default: the sidebar only)")
    t.add_argument("--no-favicons", action="store_true", help="do not fill in or correct pin icons")
    t.set_defaults(fn=cmd_tour)

    r = sub.add_parser("rollback", help="restore the newest backup (Zen must be closed)")
    r.add_argument("--force-running", action="store_true", help="do not refuse while Zen is open")
    r.set_defaults(fn=cmd_rollback)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.ui = UI(sys.stdout, args.color)
    args.ui_err = UI(sys.stderr, args.color)
    try:
        return args.fn(args)
    except SystemExit as e:
        if isinstance(e.code, str):  # our own errors: say it once, plainly, in red
            print(f"{args.ui_err.red(args.ui_err.sym('fail'))} {e.code.strip()}", file=sys.stderr)
            return 1
        raise
