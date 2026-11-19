# AGENTS.md

Two audiences: an agent **using** zenform to change someone's Zen sidebar, and an agent **developing** zenform.

## Using zenform (customising someone's pins)

You prepare a reviewed change to the config files. **Never run `zenform apply` (or `rollback`) on the live profile**:
Zen must be closed and the user decides when. Everything else is safe.

1. `zenform doctor`: profile found, Zen version tested, session readable, config valid.
2. `zenform dump --out <tmp>` if there is no config yet; otherwise read the existing config directory.
3. Edit the TOML files. Rules:
   - `label`: 14 characters or fewer, specific, no emoji, no site name. Tickets: number first (`117 Exports`).
   - `url`: the *landing page the user uses* (an MR list, a board), not whatever was open. To keep a pin's history
     and icon, reuse the home URL exactly as `dump` printed it.
   - One pin per line, in sidebar order. Folders are files; their order is the file-name order (`10-`, `20-`).
   - No one-off pages (a single MR, a chat, a draft document), no duplicate URLs, at most 9 essentials (3x3 grid).
   - Do not list a folder that is in `keep_folders`; do not touch it.
4. `zenform plan --json --no-favicons` and read `changes`: `add`, `relabel`, `move`, `unpin`, `remove_folder`.
   `unpin` is not a close: the tab stays open as an ordinary tab. Show the user the plan as text (`zenform plan`).
5. To let the user see it first, `zenform preview` opens a separate Zen window on a throwaway profile; your real
   profile is untouched. It pops up a window, so run it only when the user asks; `zenform preview --no-launch` only
   prepares the profile and is always safe.
6. Stop. Tell the user to quit Zen and run `zenform apply`; `zenform rollback` undoes it.

Unknown keys in the config are errors by design. If `plan` fails, read the message: it names the file and the key.

## Developing zenform

- **Standard library only.** No runtime dependencies (`dependencies = []`). It carries its own LZ4 block codec and
  reads TOML with `tomllib`. Keep it that way; a tool that edits a browser's files must be auditable.
- **`model.apply_layout` is pure**: it returns a new session and a list of operation dicts and must not mutate its
  input. Anything that touches the filesystem lives in `profile.py`, `config.py` or `cli.py`.
- **Safety invariants** (each has a test; do not weaken them): `preview` only ever writes to its own profile (never a real Zen profile, never
  cookies or logins); `apply` refuses while Zen runs; it backs up before
  writing; it checks the result before and after; it never closes or deletes an open tab; `plan`/`dump` never write;
  `keep_folders` are left byte-for-byte alone; applying the same config twice changes nothing.
- **Fixtures are synthetic** (`tests/helpers.py`). Never commit a real session file or a real favicon database: they
  hold browsing history. Real ones go in `tests/fixtures/private/` (git-ignored).
- **When Zen's format changes**, update `docs/session-format.md` first, then the code, then `TESTED_ZEN` in
  `src/zenform/__init__.py`. `check_session_shape` should fail loudly rather than guess.
- Run: `PYTHONPATH=src python3 -W error -m unittest discover -s tests` and `uvx ruff check .`.
