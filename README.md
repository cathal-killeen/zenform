# zenform

**Zen browser as code.** Keep your sidebar (Essentials, pinned folders, pinned tabs, labels and icons) in small, readable files. See what applying them would change, then apply.

```console
$ zenform plan
  + 117 Exports  [Now]  https://tracker.example.com/browse/APP-117
  ~ 'Inbox - me@example.com - Mail' -> 'Mail'  [essentials]
  - unpin 'Old pin' (becomes an ordinary tab)
  icons: 1 filled from the favicon database

This is a plan; nothing was written. Close Zen, then run `zenform apply`.
```

> **Status: alpha, and unofficial.** zenform is an independent tool and is not affiliated with Zen Browser. It edits an
> undocumented file that Zen can change in any release; see [Safety](#safety). Tested on macOS with Zen 1.24.3b.

## Why

- **Sync with git or a synced folder.** Your browser setup becomes a few text files you can version, review and share between machines. Syncing config files is safe; syncing the browser's own state files is not.
- **Readable.** One file per concern, TOML, one pin per line, so a diff shows exactly what changed.
- **Works with AI agents.** `dump` gives an agent the current state in the same format it edits, `plan --json` is a safe dry run it can read, and it never needs to touch your live profile. See [AGENTS.md](AGENTS.md).

## Install

```console
uv tool install zenform     # or: pipx install zenform
```

Python 3.11 or newer, no other dependencies. From source: `uv tool install git+https://github.com/cathal-killeen/zenform`.

## Use

```console
zenform dump --out ~/zen-config     # write your current pins as a config directory (start here)
$EDITOR ~/zen-config/folders/10-*.toml
export ZENFORM_CONFIG=~/zen-config  # or pass --config, or run from inside the directory
zenform plan                        # what would change; writes nothing
zenform preview                     # see it: opens a separate Zen window on a throwaway profile
# quit Zen, then:
zenform apply                       # backs up, writes, reads back to check
zenform rollback                    # undo the last apply (Zen closed)
zenform doctor                      # profile, Zen version, session format, config
```

## The config

```
zen-config/
  zenform.toml          workspace = "Work"; keep_folders = ["Pull Requests"]
  essentials.toml       the icon tiles
  folders/
    10-code.toml        name = "Code"; pins = [ ... ]   (folders appear in file-name order)
    20-tickets.toml
  loose.toml            optional: pins outside any folder
```

```toml
# folders/10-code.toml
name = "Code"

pins = [
  {label = "app MRs", url = "https://git.example.com/team/app/-/merge_requests"},
  {label = "api MRs", url = "https://git.example.com/team/api/-/merge_requests"},
]
```

- **label**: what the sidebar shows; keep it to 14 characters or fewer (zenform warns).
- **url**: the pin's *home page*. A pin Zen already has with the same home URL keeps its history and icon, so reuse the URL `dump` printed for pins you keep.
- **keep_folders**: folders zenform leaves exactly as they are (for example folders Zen manages itself).
- Unknown keys are errors, so a typo does not silently do nothing.

See [`examples/config`](examples/config).

## Preview before you apply

`zenform preview` applies your config to a copy of your *current* session in a separate preview profile, then opens a
second Zen window on it (`-no-remote`, like a dev run of an extension). Your real Zen can stay open, and nothing in your
real profile is written.

- The preview profile defaults to `~/.zenform-preview-profile`; change it with `--preview-profile` or
  `ZENFORM_PREVIEW_PROFILE`. It is rebuilt on every preview, and zenform refuses to use a real Zen profile as one.
- To look like your Zen it copies `prefs.js`, `containers.json`, `zen-themes.json`, `zen-keyboard-shortcuts.json` and
  `chrome/` from your profile. Never cookies, logins, history or extensions, so pages in the preview are signed out.
- `--no-launch` only prepares the profile and prints how to open it. If the Zen binary is not found, set `ZENFORM_ZEN_BIN`.
- Close the preview window before running `preview` again, then quit your real Zen and `apply` to make it real.

## What apply does and does not do

- Pins in the config are created, relabelled or moved. A pin the config no longer lists becomes an **ordinary tab; nothing is closed**. Open tabs are never edited.
- A pin with no icon is given one from your profile's favicon database (sites you have visited), so it is not blank until its page loads. If the site was never visited, it stays blank until opened once.
- Only the workspace named in `zenform.toml` is managed. Essentials span workspaces, so they are always managed.

## Safety

Zen keeps pins in `zen-sessions.jsonlz4` and rewrites it while running and on quit. So:

- `apply` **refuses to run while Zen is open**, backs the file up to `zenform-backups/` in the profile first, checks the result before writing and reads it back after, and restores the backup itself if that check fails.
- `plan`, `dump` and `preview` never write to your profile. The favicon database is read from a copy.
- The format is undocumented ([what we know](docs/session-format.md)). `doctor` warns on a Zen version that has not been tested, and every command refuses a session file that does not have the expected shape.
- Do not put real session files in a public repo: they contain your tab history.

## Agents

Point an agent at the config directory and [AGENTS.md](AGENTS.md). The loop is: `zenform dump` for the current state, edit the files, `zenform plan --json` to check, and leave the `apply` to you.

## Development

```console
PYTHONPATH=src python3 -W error -m unittest discover -s tests
uvx ruff check .
```

Standard library only, on purpose: it has to work on a bare machine, and a tool that edits your browser should be easy to audit.

## License

MIT
