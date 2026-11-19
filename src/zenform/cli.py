"""The zenform command line: doctor, dump, plan, apply, rollback."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from zenform import TESTED_ZEN, __version__, config, model, mozlz4, preview, profile
from zenform.favicons import Favicons


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


def _plan(args, prof: str):
    cfg = config.find_config(args.config)
    spec = config.load_config(cfg)
    session = _load_session(prof)
    icons = None if args.no_favicons else Favicons(prof)
    new, ops = model.apply_layout(session, spec, reset_pins=args.reset_pins, favicons=icons)
    return cfg, spec, session, new, ops


def cmd_doctor(args) -> int:
    ok = True

    def line(mark, text):
        nonlocal ok
        ok = ok and mark != "FAIL"
        print(f"{mark:5} {text}")

    line("ok", f"zenform {__version__}, Python {sys.version.split()[0]}")
    try:
        prof = args.profile or profile.default_profile()
        line("ok", f"profile: {prof}")
    except SystemExit as e:
        line("FAIL", str(e))
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
    line(
        "warn" if profile.zen_running() else "ok",
        "Zen is running: close it before `apply`" if profile.zen_running() else "Zen is closed",
    )
    try:
        session = _load_session(prof)
        names = ", ".join(model.workspace_names(session)) or "none"
        pinned = sum(1 for t in session["tabs"] if t.get("pinned") and not t.get("zenIsEmpty"))
        line("ok", f"session readable: {pinned} pins, {len(session['folders'])} folders, workspaces: {names}")
    except (SystemExit, ValueError) as e:
        line("FAIL", f"session: {e}")
    backups = os.path.join(prof, profile.BACKUPS)
    line("ok", f"{len(os.listdir(backups)) if os.path.isdir(backups) else 0} backup(s) in {profile.BACKUPS}/")
    try:
        cfg = config.find_config(args.config)
        spec = config.load_config(cfg)
        problems = model.validate_spec(spec)
        line("FAIL" if problems else "ok", f"config {cfg}: " + ("; ".join(problems) if problems else "valid"))
        for w in model.warnings(spec):
            line("warn", w)
    except SystemExit as e:
        line("warn", f"config: {e}")
    return 0 if ok else 1


def cmd_dump(args) -> int:
    prof = args.profile or profile.default_profile()
    session = _load_session(prof)
    names = model.workspace_names(session)
    ws = args.workspace or (names[0] if len(names) == 1 else None)
    if not ws:
        raise SystemExit(f"Several workspaces ({', '.join(names)}); pass --workspace.")
    written = config.write_config(config.current_spec(session, ws), args.out, force=args.force)
    print(f"Wrote {len(written)} files to {args.out}:")
    for p in written:
        print(f"  {os.path.relpath(p, args.out)}")
    return 0


def cmd_plan(args) -> int:
    prof = args.profile or profile.default_profile()
    _, spec, _, _, ops = _plan(args, prof)
    warns = model.warnings(spec)
    if args.json:
        print(
            json.dumps(
                {"workspace": spec["workspace"], "changes": ops, "warnings": warns},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
        print(model.render_plan(ops))
        print("\nThis is a plan; nothing was written. Close Zen, then run `zenform apply`.")
    return 2 if args.exit_code and model.changes(ops) else 0


def cmd_apply(args) -> int:
    prof = args.profile or profile.default_profile()
    _, spec, _, new, ops = _plan(args, prof)
    for w in model.warnings(spec):
        print(f"warning: {w}", file=sys.stderr)
    print(model.render_plan(ops))
    if profile.zen_running() and not args.force_running:
        raise SystemExit("\nZen is open. Quit it first (it rewrites the file when it quits), then run again.")
    problems = model.check(new, spec)
    if problems:
        raise SystemExit("\nThe result does not match the config, nothing written:\n  " + "\n  ".join(problems))
    session_path = os.path.join(prof, profile.SESSION)
    saved = profile.backup(prof)
    tmp = session_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(mozlz4.encode(new))
    os.replace(tmp, session_path)
    after = model.check(mozlz4.read(session_path), spec)
    if after:
        shutil.copy2(saved, session_path)
        raise SystemExit("\nRead-back check failed, backup restored:\n  " + "\n  ".join(after))
    print(f"\nWritten and read back. Backup: {saved}\nUndo: zenform rollback (with Zen closed)")
    return 0


def cmd_preview(args) -> int:
    """Show the new layout in a separate Zen on a throwaway profile. The real profile is only read."""
    prof = args.profile or profile.default_profile()
    _, spec, _, new, ops = _plan(args, prof)
    for w in model.warnings(spec):
        print(f"warning: {w}", file=sys.stderr)
    print(model.render_plan(ops))
    problems = model.check(new, spec)
    if problems:
        raise SystemExit("\nThe result does not match the config, nothing prepared:\n  " + "\n  ".join(problems))
    pdir = args.preview_profile or preview.default_preview_profile()
    preview.check_safe(pdir, prof)
    if preview.instance_running(pdir):
        raise SystemExit(f"\nA preview window is already open on {pdir}. Close it first, then run preview again.")
    binary = None if args.no_launch else preview.zen_binary()
    if not args.no_launch and not binary:
        raise SystemExit(f"\nCould not find the Zen binary. Set ${preview.ENV_BIN}, or use --no-launch.")
    copied = preview.prepare(prof, new, pdir)
    extra = f" (with {', '.join(copied)} from your profile)" if copied else ""
    print(f"\nPreview profile ready at {pdir}{extra}.")
    if args.no_launch:
        print("Open it with: " + " ".join(f'"{c}"' if " " in c else c for c in preview.command("<zen binary>", pdir)))
        return 0
    preview.launch(binary, pdir)
    print(
        "Opened a separate Zen window on it; your real Zen was not touched.\n"
        "Pages there are signed out. Close the window when done, then run `zenform apply` (Zen closed) to make it real."
    )
    return 0


def cmd_rollback(args) -> int:
    prof = args.profile or profile.default_profile()
    if profile.zen_running() and not args.force_running:
        raise SystemExit("Zen is open. Quit it first (it rewrites the file when it quits).")
    backup = profile.newest_backup(prof)
    if not backup:
        raise SystemExit("No backup to restore.")
    shutil.copy2(backup, os.path.join(prof, profile.SESSION))
    print(f"Restored {backup}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="zenform", description="Zen browser as code: plan and apply your sidebar from files."
    )
    ap.add_argument("--version", action="version", version=f"zenform {__version__}")
    ap.add_argument("--config", help="the config directory (default: $ZENFORM_CONFIG, else the current directory)")
    ap.add_argument("--profile", help="a Zen profile folder (default: the one Zen starts with)")
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
        p.add_argument("--no-favicons", action="store_true", help="do not fill in missing pin icons")
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
    v.add_argument("--reset-pins", action="store_true", help="also send each pin back to its home page")
    v.add_argument("--no-favicons", action="store_true", help="do not fill in missing pin icons")
    v.set_defaults(fn=cmd_preview)

    r = sub.add_parser("rollback", help="restore the newest backup (Zen must be closed)")
    r.add_argument("--force-running", action="store_true", help="do not refuse while Zen is open")
    r.set_defaults(fn=cmd_rollback)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)
