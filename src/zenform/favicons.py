"""Icons for pins, from the profile's favicons.sqlite (read from a copy, never the original)."""

from __future__ import annotations

import base64
import os
import shutil
import sqlite3
import tempfile
import urllib.parse


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


class Favicons:
    """Find an icon by page URL, then by the closest page on the same site, then by the site's root icon."""

    MAX_BYTES = 150_000

    def __init__(self, profile: str | None):
        self.by_origin: dict[str, list[tuple[str, int, bytes]]] = {}
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
                    "select p.page_url, i.width, i.data from moz_pages_w_icons p "
                    "join moz_icons_to_pages ip on ip.page_id = p.id join moz_icons i on i.id = ip.icon_id "
                    "where i.data is not null"
                ).fetchall()
                roots = con.execute(
                    "select icon_url, width, data from moz_icons where root = 1 and data is not null"
                ).fetchall()
            except sqlite3.Error:
                pages, roots = [], []
            finally:
                con.close()
        for page_url, width, data in pages + roots:
            if data and len(data) <= self.MAX_BYTES and sniff_mime(data):
                self.by_origin.setdefault(_origin(page_url), []).append((page_url, width or 0, bytes(data)))

    def find(self, url: str) -> str | None:
        cands = self.by_origin.get(_origin(url))
        if not cands:
            return None
        want = _segments(url)

        def score(c):
            common = 0
            for a, b in zip(want, _segments(c[0]), strict=False):
                if a != b:
                    break
                common += 1
            return (c[0] == url, common, min(c[1] or 32, 64))

        data = max(cands, key=score)[2]
        return f"data:{sniff_mime(data)};base64,{base64.b64encode(data).decode()}"
