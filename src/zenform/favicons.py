"""Icons for pins, from the profile's favicons.sqlite (read from a copy, never the original).

Firefox records the icon of every page you visited. For a pin we want the icon of *that* page, and failing that
something that is certainly right; a blank icon beats a wrong one (Zen fills a blank one in when the page loads). So
`find` returns a match only when it is trustworthy, and says how trustworthy:

    tier 3  the very page (the URL without its #fragment)
    tier 2  the closest page on the site that shares a path with it (/calendar/... for /calendar/u/0/r)
    tier 1  the site's one icon: every icon known for the site comes from the same place

Several products can live on one host (docs.google.com holds Docs, Sheets and Slides), so a site whose icons come from
more than one place gives no answer unless a page under the pin's own path was visited.
"""

from __future__ import annotations

import base64
import os
import shutil
import sqlite3
import tempfile
import urllib.parse
from typing import NamedTuple


def sniff_mime(b: bytes) -> str | None:
    if b[:4] == b"\x89PNG":
        return "image/png"
    if b[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    if b[:3] == b"GIF":
        return "image/gif"
    if b[:2] == b"\xff\xd8":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    head = b[:200].lstrip().lower()
    if head.startswith((b"<svg", b"<?xml")):
        return "image/svg+xml"
    return None


def _origin(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def _segments(url: str) -> list[str]:
    return [x for x in urllib.parse.urlsplit(url).path.split("/") if x]


def _norm(url: str) -> str:
    return urllib.parse.urldefrag(url)[0].rstrip("/")


def _source(icon_url: str) -> str:
    """Where an icon is served from: its host and folder (the file name varies, e.g. per day)."""
    u = urllib.parse.urlsplit(icon_url)
    return u.netloc + u.path.rsplit("/", 1)[0]


class Icon(NamedTuple):
    page: str  # the page it belongs to (for a site's root icon: the icon's own URL)
    icon_url: str
    width: int
    id: int  # newer icons have higher ids
    data: bytes


class Match(NamedTuple):
    uri: str  # a data: URI
    tier: int


def _best(group: list[Icon]) -> Icon:
    """The size nearest 32px (the sidebar shows 16 to 32), then the newest."""
    return max(group, key=lambda i: (-abs((i.width or 32) - 32), i.id))


class Favicons:
    MAX_BYTES = 150_000

    def __init__(self, profile: str | None):
        self.pages: dict[str, list[Icon]] = {}
        self.roots: dict[str, list[Icon]] = {}
        src = os.path.join(profile, "favicons.sqlite") if profile else ""
        if not src or not os.path.exists(src):
            return
        with tempfile.TemporaryDirectory() as tmp:  # a copy: Zen may hold the original open
            for suffix in ("", "-wal"):
                if os.path.exists(src + suffix):
                    shutil.copy2(src + suffix, os.path.join(tmp, "favicons.sqlite" + suffix))
            con = sqlite3.connect(os.path.join(tmp, "favicons.sqlite"))
            try:
                pages = con.execute(
                    "select p.page_url, i.icon_url, i.width, i.id, i.data from moz_pages_w_icons p "
                    "join moz_icons_to_pages ip on ip.page_id = p.id join moz_icons i on i.id = ip.icon_id "
                    "where i.data is not null"
                ).fetchall()
                roots = con.execute(
                    "select icon_url, icon_url, width, id, data from moz_icons where root = 1 and data is not null"
                ).fetchall()
            except sqlite3.Error:
                pages, roots = [], []
            finally:
                con.close()
        for store, rows in ((self.pages, pages), (self.roots, roots)):
            for page, icon_url, width, icon_id, data in rows:
                if data and len(data) <= self.MAX_BYTES and sniff_mime(data):
                    store.setdefault(_origin(page), []).append(Icon(page, icon_url, width or 0, icon_id, bytes(data)))

    @staticmethod
    def _match(icon: Icon, tier: int) -> Match:
        return Match(f"data:{sniff_mime(icon.data)};base64,{base64.b64encode(icon.data).decode()}", tier)

    def find(self, url: str) -> Match | None:
        origin = _origin(url)
        pages = self.pages.get(origin)
        if pages:
            target, want = _norm(url), _segments(url)
            exact = [i for i in pages if _norm(i.page) == target]
            if exact:
                return self._match(_best(exact), 3)
            best, group = 0, []
            for i in pages:
                common = 0
                for a, b in zip(want, _segments(i.page), strict=False):
                    if a != b:
                        break
                    common += 1
                if common > best:
                    best, group = common, [i]
                elif common == best and common > 0:
                    group.append(i)
            if best >= 1:
                return self._match(_best(group), 2)
            if len({_source(i.icon_url) for i in pages}) == 1:
                return self._match(_best(pages), 1)
            return None  # several products on one host and nothing under this path: do not guess
        roots = self.roots.get(origin)
        if roots and len({_source(i.icon_url) for i in roots}) == 1:
            return self._match(_best(roots), 1)
        return None
