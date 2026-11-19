# What zenform knows about Zen's session file

Zen keeps its sidebar (Essentials, pinned folders, pinned tabs) in `zen-sessions.jsonlz4` in the profile. This is
undocumented and can change in any Zen release. Everything below was found by reading real files, and is the reason
`zenform doctor` checks versions. Last checked against **Zen 1.24.3b** (Firefox platform 2026-11), macOS.

## The file

`mozLz40\0` (8 bytes) + little-endian uint32 uncompressed size + one LZ4 block of UTF-8 JSON. Zen rewrites it while
running and when it quits, so edits are only safe with Zen closed.

Top-level keys: `lastCollected`, `tabs`, `folders`, `splitViewData`, `groups`, `spaces`.

- `spaces[]` the workspaces: `{uuid, name, theme, containerTabId, ...}`.
- `folders[]` pinned folders: `{id, name, collapsed, workspaceId, prevSiblingInfo, emptyTabIds, ...}`. A folder's
  order is a linked list: `prevSiblingInfo` is `null` for the first and `{"type": "group", "id": <previous>}` after.
- `groups[]` a parallel list with the same ids: `{id, name, color, collapsed, ...}`.

## Tabs (`tabs[]`)

A pinned tab is an ordinary tab entry with extra `zen*` fields:

| Field | Meaning |
|---|---|
| `pinned` | true for any pin, Essentials included |
| `zenEssential` | true for an Essential (then `zenWorkspace` is `null`: Essentials span workspaces) |
| `zenWorkspace` | workspace uuid for a non-essential pin |
| `groupId` | the folder a pin is in (absent for a loose pin) |
| `zenStaticLabel` | the user-set label shown in the sidebar |
| `zenSyncId` | `<ms-timestamp>-<uuid>` |
| `_zenPinnedInitialState` | `{entry: {url, title}, image}`: the pin's home page; what "reset pin" returns to |
| `image` | the tab's icon as a `data:` URI |
| `entries[]`, `index` | the history of the tab and where it is in it (1-based) |

- **Home URL vs current page.** `entries[index-1]` is where the pin is now; `_zenPinnedInitialState.entry.url` is its
  home. zenform identifies a pin by its home URL, so a pin keeps its history and icon across applies.
- **Folders hold an empty placeholder tab** (`zenIsEmpty: true`, `about:blank`) whose `zenSyncId` is listed in the
  folder's `emptyTabIds`. Zen needs it; zenform keeps or creates it.
- **Order** is the order of `tabs[]`: Essentials, then each folder's placeholder and pins, then the rest.
- **Icons.** A pin Zen has not loaded has `image: null` and shows a blank icon until its page is opened. zenform fills
  both `image` and `_zenPinnedInitialState.image` from `favicons.sqlite`.

## Not in this file

- Bookmarks (`places.sqlite`) are unrelated to pins.
- `zen-live-folders.jsonlz4` holds Zen's live folders. zenform does not manage them; list a folder in
  `keep_folders` to leave it exactly as it is.
- Open (unpinned) tabs are in this file too but zenform never edits them. A pin the config drops is unpinned, not
  closed.

## Favicons

`favicons.sqlite`: `moz_icons` (blob in `data`, `width`, `root`), `moz_pages_w_icons` (`page_url`),
`moz_icons_to_pages`. Lookup: the same page, else the closest page on the same site (longest shared path prefix),
else the site's root icon. Read from a copy, never the original.
