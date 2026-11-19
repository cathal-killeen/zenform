import os
import sqlite3
import tempfile
import unittest

from helpers import session

from zenform import model
from zenform.favicons import Favicons

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


def b64(b):
    import base64

    return base64.b64encode(b).decode()


def profile_dir():
    d = tempfile.mkdtemp()
    con = sqlite3.connect(os.path.join(d, "favicons.sqlite"))
    con.executescript(
        """
        create table moz_icons (id integer primary key, icon_url text, width integer, root integer, data blob);
        create table moz_pages_w_icons (id integer primary key, page_url text);
        create table moz_icons_to_pages (page_id integer, icon_id integer);"""
    )
    con.executemany(
        "insert into moz_icons values (?,?,?,?,?)",
        [
            (1, "https://jira.example/fav.png", 32, 0, PNG),
            (2, "https://jira.example/wiki.png", 32, 0, PNG + b"wiki"),
            (3, "https://other.example/favicon.ico", 16, 1, b"\x00\x00\x01\x00" + b"i" * 8),
            (4, "https://bad.example/x", 16, 0, b"not an image"),
        ],
    )
    con.executemany(
        "insert into moz_pages_w_icons values (?,?)",
        [
            (1, "https://jira.example/browse/APP-1"),
            (2, "https://jira.example/wiki/spaces/DOCS"),
            (4, "https://bad.example/"),
        ],
    )
    con.executemany("insert into moz_icons_to_pages values (?,?)", [(1, 1), (2, 2), (4, 4)])
    con.commit()
    con.close()
    return d


class Icons(unittest.TestCase):
    def test_closest_page_on_the_same_site_wins(self):
        f = Favicons(profile_dir())
        self.assertIn(b64(PNG + b"wiki"), f.find("https://jira.example/wiki/spaces/OTHER"))
        self.assertIn(b64(PNG), f.find("https://jira.example/browse/APP-999"))

    def test_site_root_icon_is_the_last_resort_and_mime_is_sniffed(self):
        self.assertTrue(
            Favicons(profile_dir()).find("https://other.example/anything").startswith("data:image/x-icon;base64,")
        )

    def test_unknown_site_or_unreadable_data_is_none(self):
        f = Favicons(profile_dir())
        self.assertIsNone(f.find("https://never.example/"))
        self.assertIsNone(f.find("https://bad.example/"))

    def test_no_database_is_fine(self):
        self.assertIsNone(Favicons(tempfile.mkdtemp()).find("https://x.example/"))
        self.assertIsNone(Favicons(None).find("https://x.example/"))

    def test_new_pins_get_icons_and_existing_icons_are_kept(self):
        s = session()
        s["tabs"][0]["image"] = s["tabs"][0]["_zenPinnedInitialState"]["image"] = "data:image/png;base64,KEEP"
        spec = {
            "workspace": "Work",
            "essentials": [
                {"label": "Mail", "url": "https://mail/"},
                {"label": "Jira", "url": "https://jira.example/browse/APP-5"},
                {"label": "Nowhere", "url": "https://never.example/"},
            ],
        }
        new, ops = model.apply_layout(s, spec, favicons=Favicons(profile_dir()))
        by = {model.tab_label(t): t for t in new["tabs"] if t.get("zenEssential")}
        self.assertEqual(by["Mail"]["image"], "data:image/png;base64,KEEP")
        self.assertTrue(by["Jira"]["image"].startswith("data:image/png;base64,"))
        self.assertEqual(by["Jira"]["image"], by["Jira"]["_zenPinnedInitialState"]["image"])
        self.assertIsNone(by["Nowhere"]["_zenPinnedInitialState"]["image"])
        self.assertIn({"op": "icons", "filled": 1, "missing": ["Nowhere"]}, ops)


if __name__ == "__main__":
    unittest.main()
