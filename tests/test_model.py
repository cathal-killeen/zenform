import json
import unittest

from helpers import SPEC, WS, session, tab

from zenform import model, render
from zenform.ui import UI


class Apply(unittest.TestCase):
    def test_result_matches_the_config(self):
        new, _ = model.apply_layout(session(), SPEC)
        self.assertEqual(model.check(new, SPEC), [])

    def test_existing_pin_keeps_its_history_and_gets_the_label(self):
        new, _ = model.apply_layout(session(), SPEC)
        mail = next(t for t in new["tabs"] if model.home_url(t) == "https://mail/")
        self.assertEqual(mail["zenStaticLabel"], "Mail")
        self.assertEqual((mail["index"], len(mail["entries"])), (2, 2))

    def test_reset_pins_goes_home(self):
        new, _ = model.apply_layout(session(), SPEC, reset_pins=True)
        mail = next(t for t in new["tabs"] if model.home_url(t) == "https://mail/")
        self.assertEqual((mail["index"], len(mail["entries"])), (1, 1))

    def test_unlisted_pin_becomes_an_ordinary_tab(self):
        new, ops = model.apply_layout(session(), SPEC)
        old = next(t for t in new["tabs"] if t["entries"][0]["url"] == "https://old/")
        self.assertFalse(old["pinned"])
        for key in ("groupId", "zenStaticLabel"):
            self.assertNotIn(key, old)
        self.assertIn({"op": "unpin", "label": "Old pin", "url": "https://old/"}, ops)

    def test_open_tabs_are_left_alone(self):
        new, _ = model.apply_layout(session(), SPEC)
        self.assertIn({"entries": [{"url": "https://open/"}], "pinned": False, "index": 1}, new["tabs"])

    def test_folder_keeps_its_id_and_collapsed_state_and_a_new_one_chains_after_it(self):
        new, _ = model.apply_layout(session(), SPEC)
        docs, fresh = new["folders"]
        self.assertEqual((docs["id"], docs["collapsed"]), ("g1", True))
        self.assertEqual(fresh["prevSiblingInfo"], {"type": "group", "id": "g1"})
        self.assertEqual([g["id"] for g in new["groups"]], [f["id"] for f in new["folders"]])
        for f in new["folders"]:
            ph = [t for t in new["tabs"] if t.get("groupId") == f["id"] and t.get("zenIsEmpty")]
            self.assertEqual([t["zenSyncId"] for t in ph], f["emptyTabIds"])

    def test_removed_folder_goes_and_its_pins_are_unpinned(self):
        spec = {"workspace": "Work", "essentials": [], "folders": []}
        new, ops = model.apply_layout(session(), spec)
        self.assertEqual((new["folders"], new["groups"]), ([], []))
        self.assertFalse(any(t.get("zenIsEmpty") for t in new["tabs"]))
        self.assertFalse(any(t.get("pinned") for t in new["tabs"]))
        self.assertIn({"op": "remove_folder", "folder": "Docs"}, ops)

    def test_applying_twice_changes_nothing_more(self):
        once, _ = model.apply_layout(session(), SPEC)
        twice, ops = model.apply_layout(once, SPEC)
        self.assertEqual(once, twice)
        self.assertEqual(model.changes(ops), [])

    def test_input_is_not_changed(self):
        s = session()
        before = json.dumps(s, sort_keys=True)
        model.apply_layout(s, SPEC)
        self.assertEqual(json.dumps(s, sort_keys=True), before)

    def test_unknown_workspace_is_an_error(self):
        with self.assertRaises(SystemExit):
            model.apply_layout(session(), {**SPEC, "workspace": "Nope"})

    def test_ops_say_what_happens(self):
        _, ops = model.apply_layout(session(), SPEC)
        kinds = {(o["op"], o.get("label") or o.get("to")) for o in ops}
        self.assertIn(("relabel", "Mail"), kinds)
        self.assertIn(("relabel", "Wiki"), kinds)
        self.assertIn(("add", "Fresh"), kinds)
        self.assertIn("Fresh", render.render_plan(ops, UI(mode="never")))


class Keep(unittest.TestCase):
    def kept_session(self):
        s = session()
        ph = model.new_placeholder("g2", WS)
        pr = tab("https://github/pull/44", label="PR 44 long title", group="g2")
        s["tabs"] += [ph, pr]
        s["folders"].append(
            {
                "id": "g2",
                "name": "Pull Requests",
                "collapsed": False,
                "emptyTabIds": [ph["zenSyncId"]],
                "prevSiblingInfo": {"type": "group", "id": "g1"},
                "workspaceId": WS,
            }
        )
        s["groups"].append({"id": "g2", "name": "Pull Requests", "collapsed": False})
        return s

    def test_a_kept_folder_is_left_exactly_alone(self):
        s = self.kept_session()
        spec = {**SPEC, "keep_folders": ["Pull Requests"]}
        new, ops = model.apply_layout(s, spec)
        self.assertEqual(
            [t for t in s["tabs"] if t.get("groupId") == "g2"],
            [t for t in new["tabs"] if t.get("groupId") == "g2"],
        )
        self.assertTrue(any(g["id"] == "g2" for g in new["groups"]))
        self.assertEqual(model.check(new, spec), [])
        self.assertIn({"op": "keep_folder", "folder": "Pull Requests"}, ops)

    def test_kept_folder_goes_last_and_chains_after_the_others(self):
        spec = {**SPEC, "keep_folders": ["Pull Requests"]}
        new, _ = model.apply_layout(self.kept_session(), spec)
        self.assertEqual([f["name"] for f in new["folders"]], ["Docs", "New", "Pull Requests"])
        self.assertEqual(new["folders"][2]["prevSiblingInfo"], {"type": "group", "id": new["folders"][1]["id"]})

    def test_without_keep_the_folder_is_removed(self):
        new, _ = model.apply_layout(self.kept_session(), SPEC)
        self.assertEqual([f["name"] for f in new["folders"]], ["Docs", "New"])

    def test_keeping_a_folder_that_does_not_exist_is_harmless(self):
        spec = {**SPEC, "keep_folders": ["Nope"]}
        new, ops = model.apply_layout(session(), spec)
        self.assertEqual(model.check(new, spec), [])
        self.assertIn({"op": "keep_missing", "folder": "Nope"}, ops)

    def test_applying_twice_with_a_kept_folder_changes_nothing_more(self):
        spec = {**SPEC, "keep_folders": ["Pull Requests"]}
        once, _ = model.apply_layout(self.kept_session(), spec)
        twice, _ = model.apply_layout(once, spec)
        self.assertEqual(once, twice)


class Spec(unittest.TestCase):
    def test_problems(self):
        self.assertTrue(model.validate_spec({"essentials": [{"label": "x"}]}))
        self.assertTrue(model.validate_spec({"workspace": "w", "folders": [{"name": "a"}, {"name": "a"}]}))
        self.assertTrue(model.validate_spec({"workspace": "w", "keep_folders": ["a"], "folders": [{"name": "a"}]}))

    def test_warnings(self):
        spec = {"workspace": "w", "essentials": [{"label": "a" * 20, "url": "u"}, {"label": "b", "url": "u"}]}
        self.assertEqual(len(model.warnings(spec)), 2)
        ten = {"workspace": "w", "essentials": [{"label": str(i), "url": f"u{i}"} for i in range(10)]}
        self.assertEqual(len(model.warnings(ten)), 1)
        nine = {"workspace": "w", "essentials": [{"label": str(i), "url": f"u{i}"} for i in range(9)]}
        self.assertEqual(model.warnings(nine), [])

    def test_session_shape(self):
        self.assertEqual(model.check_session_shape(session()), [])
        self.assertTrue(model.check_session_shape({"tabs": []}))


if __name__ == "__main__":
    unittest.main()
