import base64
import os
import sqlite3
import tempfile
import unittest

from helpers import session

from zenform import model
from zenform.favicons import Favicons

PNG = b"\x89PNG\r\n\x1a\n"


def png(tag: str) -> bytes:
    return PNG + tag.encode()


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def make_db(icons, pages=()):
    """icons: (id, icon_url, width, root, data); pages: (page_url, [icon ids])."""
    d = tempfile.mkdtemp()
    con = sqlite3.connect(os.path.join(d, "favicons.sqlite"))
    con.executescript(
        """
        create table moz_icons (id integer primary key, icon_url text, width integer, root integer, data blob);
        create table moz_pages_w_icons (id integer primary key, page_url text);
        create table moz_icons_to_pages (page_id integer, icon_id integer);"""
    )
    con.executemany("insert into moz_icons values (?,?,?,?,?)", icons)
    for n, (page, ids) in enumerate(pages, start=1):
        con.execute("insert into moz_pages_w_icons values (?,?)", (n, page))
        con.executemany("insert into moz_icons_to_pages values (?,?)", [(n, i) for i in ids])
    con.commit()
    con.close()
    return d


def docs_site():
    """One host, two products, each with its own icon folder (like docs.google.com)."""
    return make_db(
        [
            (1, "https://docs.example/docs/icon.png", 32, 0, png("docs")),
            (2, "https://docs.example/sheets/icon.png", 32, 0, png("sheets")),
        ],
        [("https://docs.example/document/d/1", [1]), ("https://docs.example/spreadsheets/d/2", [2])],
    )


class Matching(unittest.TestCase):
    def test_the_very_page_is_tier_3_and_a_fragment_is_ignored(self):
        f = Favicons(
            make_db([(1, "https://mail.example/i.png", 32, 0, png("gmail"))], [("https://mail.example/mail/u/0/", [1])])
        )
        for url in (
            "https://mail.example/mail/u/0/",
            "https://mail.example/mail/u/0/#inbox",
            "https://mail.example/mail/u/0",
        ):
            m = f.find(url)
            self.assertEqual((m.tier, m.uri), (3, "data:image/png;base64," + b64(png("gmail"))), url)

    def test_the_closest_page_that_shares_a_path_is_tier_2(self):
        f = Favicons(docs_site())
        self.assertEqual(f.find("https://docs.example/document/").uri.split(",")[1], b64(png("docs")))
        self.assertEqual(f.find("https://docs.example/spreadsheets/").uri.split(",")[1], b64(png("sheets")))
        self.assertEqual(f.find("https://docs.example/document/d/other").tier, 2)

    def test_several_products_on_one_host_are_not_guessed_between(self):
        # The old behaviour gave /, and every unseen path, an arbitrary one of these. Blank beats wrong.
        f = Favicons(docs_site())
        self.assertIsNone(f.find("https://docs.example/"))
        self.assertIsNone(f.find("https://docs.example/presentation/"))

    def test_a_host_with_one_icon_source_answers_for_any_path_as_tier_1(self):
        f = Favicons(make_db([(1, "https://gh.example/i.svg", 0, 0, b"<svg/>")], [("https://gh.example/pulls", [1])]))
        m = f.find("https://gh.example/somewhere/else")
        self.assertEqual((m.tier, m.uri.split(";")[0]), (1, "data:image/svg+xml"))

    def test_different_hosts_never_share_an_icon(self):
        f = Favicons(
            make_db(
                [
                    (1, "https://a.example/i.png", 32, 0, png("mail")),
                    (2, "https://b.example/i.png", 32, 0, png("calendar")),
                ],
                [("https://a.example/", [1]), ("https://b.example/", [2])],
            )
        )
        self.assertNotEqual(f.find("https://a.example/").uri, f.find("https://b.example/").uri)

    def test_a_sites_root_icon_is_used_only_when_it_is_unambiguous(self):
        one = Favicons(make_db([(1, "https://r.example/favicon.ico", 16, 1, b"\x00\x00\x01\x00icon")]))
        self.assertEqual(one.find("https://r.example/anything").uri.split(",")[0], "data:image/x-icon;base64")
        two = Favicons(
            make_db(
                [
                    (1, "https://r.example/favicon.ico", 16, 1, b"\x00\x00\x01\x00a"),
                    (2, "https://cdn.r.example/x/favicon.ico", 16, 1, b"\x00\x00\x01\x00b"),
                ]
            )
        )
        self.assertIsNotNone(two.find("https://r.example/x"))  # both are r.example origin? no: separate origins
        self.assertIsNone(Favicons(make_db([])).find("https://r.example/"))

    def test_picks_the_size_nearest_32_then_the_newest(self):
        sizes = make_db(
            [
                (1, "https://s.example/a.png", 16, 0, png("16")),
                (2, "https://s.example/b.png", 32, 0, png("32")),
                (3, "https://s.example/c.png", 192, 0, png("192")),
            ],
            [("https://s.example/p", [1, 2, 3])],
        )
        self.assertEqual(Favicons(sizes).find("https://s.example/p").uri.split(",")[1], b64(png("32")))
        daily = make_db(  # Google Calendar's icon changes every day; the same size, so the newest wins
            [
                (5, "https://c.example/cal/cal_19.png", 192, 0, png("19")),
                (9, "https://c.example/cal/cal_20.png", 192, 0, png("20")),
            ],
            [("https://c.example/cal/week", [5, 9])],
        )
        self.assertEqual(Favicons(daily).find("https://c.example/cal/week").uri.split(",")[1], b64(png("20")))

    def test_unreadable_or_oversized_icons_are_ignored(self):
        f = Favicons(
            make_db(
                [
                    (1, "https://x.example/a", 32, 0, b"not an image"),
                    (2, "https://x.example/b", 32, 0, PNG + b"z" * 200_000),
                ],
                [("https://x.example/", [1, 2])],
            )
        )
        self.assertIsNone(f.find("https://x.example/"))

    def test_no_database_is_fine(self):
        self.assertIsNone(Favicons(tempfile.mkdtemp()).find("https://x.example/"))
        self.assertIsNone(Favicons(None).find("https://x.example/"))


class OnPins(unittest.TestCase):
    MAIL = "https://mail.example/mail/"
    CAL = "https://cal.example/week"

    def favicons(self):
        return Favicons(
            make_db(
                [
                    (1, "https://mail.example/m.png", 32, 0, png("gmail")),
                    (2, "https://cal.example/c.png", 32, 0, png("calendar")),
                    (3, "https://docs.example/d/x.png", 32, 0, png("docs")),
                    (4, "https://docs.example/s/x.png", 32, 0, png("sheets")),
                ],
                [
                    (self.MAIL, [1]),
                    (self.CAL, [2]),
                    ("https://docs.example/document/d/1", [3]),
                    ("https://docs.example/spreadsheets/d/2", [4]),
                ],
            )
        )

    def run_apply(self, stored, pins):
        """A session whose only pin is Mail at MAIL holding `stored`, and a layout of `pins` (label, url)."""
        s = session()
        mail = s["tabs"][0]
        mail["image"] = mail["_zenPinnedInitialState"]["image"] = stored
        mail["_zenPinnedInitialState"]["entry"]["url"] = self.MAIL
        spec = {"workspace": "Work", "essentials": [{"label": k, "url": u} for k, u in pins]}
        new, ops = model.apply_layout(s, spec, favicons=self.favicons())
        by = {model.tab_label(t): t for t in new["tabs"] if t.get("zenEssential")}
        return by, next(o for o in ops if o["op"] == "icons")

    def test_a_generic_stored_icon_is_replaced_by_the_pages_own(self):
        by, icons = self.run_apply("data:image/png;base64," + b64(png("generic-G")), [("Mail", self.MAIL)])
        self.assertEqual(by["Mail"]["image"], "data:image/png;base64," + b64(png("gmail")))
        self.assertEqual(by["Mail"]["image"], by["Mail"]["_zenPinnedInitialState"]["image"])
        self.assertEqual((icons["replaced"], icons["filled"]), (1, 0))

    def test_services_on_different_hosts_get_different_icons(self):
        by, icons = self.run_apply("data:image/png;base64,X", [("Mail", self.MAIL), ("Cal", self.CAL)])
        self.assertEqual(by["Cal"]["image"], "data:image/png;base64," + b64(png("calendar")))
        self.assertNotEqual(by["Cal"]["image"], by["Mail"]["image"])
        self.assertEqual(icons["filled"], 1)

    def test_an_ambiguous_host_stays_blank_rather_than_wrong(self):
        by, icons = self.run_apply(
            "data:image/png;base64,X",
            [("Mail", self.MAIL), ("Docs", "https://docs.example/"), ("Never", "https://never.example/")],
        )
        self.assertIsNone(by["Docs"]["_zenPinnedInitialState"]["image"])
        self.assertIsNone(by["Never"]["_zenPinnedInitialState"]["image"])
        self.assertEqual(sorted(icons["missing"]), ["Docs", "Never"])

    def test_a_pin_under_the_products_own_path_gets_that_products_icon(self):
        pins = [("Mail", self.MAIL), ("Sheets", "https://docs.example/spreadsheets/")]
        by, _ = self.run_apply("data:image/png;base64,X", pins)
        self.assertEqual(by["Sheets"]["image"], "data:image/png;base64," + b64(png("sheets")))

    def test_a_stored_icon_is_kept_when_nothing_trustworthy_is_known(self):
        s = session()
        s["tabs"][0]["image"] = s["tabs"][0]["_zenPinnedInitialState"]["image"] = "data:image/png;base64,KEEP"
        spec = {"workspace": "Work", "essentials": [{"label": "Mail", "url": "https://mail/"}]}
        new, ops = model.apply_layout(s, spec, favicons=self.favicons())  # https://mail/ is unknown to the database
        self.assertEqual(next(t for t in new["tabs"] if t.get("zenEssential"))["image"], "data:image/png;base64,KEEP")
        icons = next(o for o in ops if o["op"] == "icons")
        self.assertEqual(icons, {"op": "icons", "filled": 0, "replaced": 0, "cleared": [], "missing": []})

    def fresh(self, stored, pins):
        s = session()
        mail = s["tabs"][0]
        mail["image"] = mail["_zenPinnedInitialState"]["image"] = stored
        mail["_zenPinnedInitialState"]["entry"]["url"] = self.MAIL
        spec = {"workspace": "Work", "essentials": [{"label": k, "url": u} for k, u in pins]}
        new, ops = model.apply_layout(s, spec, favicons=self.favicons(), fresh_icons=True)
        by = {model.tab_label(t): t for t in new["tabs"] if t.get("zenEssential")}
        return by, next(o for o in ops if o["op"] == "icons")

    def test_redo_icons_drops_a_stored_icon_that_nothing_can_vouch_for(self):
        # A stored icon on a host with several products is exactly what the old, looser lookup got wrong.
        by, icons = self.fresh("data:image/png;base64,WRONG", [("Docs", "https://docs.example/")])
        self.assertIsNone(by["Docs"]["_zenPinnedInitialState"]["image"])
        self.assertNotIn("image", by["Docs"])
        self.assertEqual(icons["cleared"] or icons["missing"], ["Docs"])

    def test_redo_icons_still_uses_the_pages_own_icon_where_it_is_known(self):
        by, icons = self.fresh("data:image/png;base64,WRONG", [("Mail", self.MAIL)])
        self.assertEqual(by["Mail"]["image"], "data:image/png;base64," + b64(png("gmail")))
        self.assertEqual((icons["replaced"], icons["cleared"]), (1, []))

    def test_without_redo_icons_a_stored_icon_survives_an_unknown_page(self):
        s = session()
        s["tabs"][0]["image"] = s["tabs"][0]["_zenPinnedInitialState"]["image"] = "data:image/png;base64,KEEP"
        spec = {"workspace": "Work", "essentials": [{"label": "Mail", "url": "https://mail/"}]}
        kept, _ = model.apply_layout(s, spec, favicons=self.favicons())
        self.assertEqual(next(t for t in kept["tabs"] if t.get("zenEssential"))["image"], "data:image/png;base64,KEEP")
        gone, ops = model.apply_layout(s, spec, favicons=self.favicons(), fresh_icons=True)
        self.assertIsNone(next(t for t in gone["tabs"] if t.get("zenEssential"))["_zenPinnedInitialState"]["image"])
        self.assertEqual(next(o for o in ops if o["op"] == "icons")["cleared"], ["Mail"])

    def test_applying_twice_changes_no_icons(self):
        pins = [("Mail", self.MAIL), ("Cal", self.CAL)]
        by, _ = self.run_apply("data:image/png;base64,X", pins)
        s = session()
        s["tabs"] = list(by.values()) + s["tabs"][1:]
        spec = {"workspace": "Work", "essentials": [{"label": k, "url": u} for k, u in pins]}
        _, ops = model.apply_layout(s, spec, favicons=self.favicons())
        icons = next(o for o in ops if o["op"] == "icons")
        self.assertEqual((icons["filled"], icons["replaced"], icons["missing"]), (0, 0, []))


if __name__ == "__main__":
    unittest.main()
