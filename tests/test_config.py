import os
import tempfile
import unittest

from helpers import SPEC, session

from zenform import config, model


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class Load(unittest.TestCase):
    def test_loads_a_config_directory_in_file_name_order(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "zenform.toml", 'workspace = "Work"\nkeep_folders = ["PRs"]\n')
            write(d, "essentials.toml", 'pins = [ {label = "Mail", url = "https://mail/"} ]\n')
            write(d, "folders/20-b.toml", 'name = "B"\npins = [ {label = "b1", url = "https://b/"} ]\n')
            write(d, "folders/10-a.toml", 'name = "A"\ncollapsed = true\npins = []\n')
            write(d, "loose.toml", 'pins = [ {label = "L", url = "https://l/"} ]\n')
            spec = config.load_config(d)
        self.assertEqual(spec["workspace"], "Work")
        self.assertEqual(spec["keep_folders"], ["PRs"])
        self.assertEqual([f["name"] for f in spec["folders"]], ["A", "B"])
        self.assertTrue(spec["folders"][0]["collapsed"])
        self.assertEqual(spec["pins"], [{"label": "L", "url": "https://l/"}])

    def test_unknown_keys_are_errors_not_silence(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "zenform.toml", 'workspace = "Work"\nworkspce = "typo"\n')
            with self.assertRaises(SystemExit) as cm:
                config.load_config(d)
            self.assertIn("workspce", str(cm.exception))
        with tempfile.TemporaryDirectory() as d:
            write(d, "zenform.toml", 'workspace = "Work"\n')
            write(d, "essentials.toml", 'pins = [ {label = "x", url = "u", icon = "i"} ]\n')
            with self.assertRaises(SystemExit):
                config.load_config(d)

    def test_a_folder_without_a_name_and_bad_toml_are_errors(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "zenform.toml", 'workspace = "Work"\n')
            write(d, "folders/10-x.toml", "pins = []\n")
            with self.assertRaises(SystemExit):
                config.load_config(d)
        with tempfile.TemporaryDirectory() as d:
            write(d, "zenform.toml", "workspace = \n")
            with self.assertRaises(SystemExit):
                config.load_config(d)

    def test_find_config_needs_zenform_toml(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                config.find_config(d)
            write(d, "zenform.toml", 'workspace = "W"\n')
            self.assertEqual(config.find_config(d), d)


class Dump(unittest.TestCase):
    def test_dump_then_load_gives_the_same_pins(self):
        s = session()
        with tempfile.TemporaryDirectory() as d:
            config.write_config(config.current_spec(s, "Work"), d)
            spec = config.load_config(d)
        self.assertEqual(spec["essentials"], [{"label": "Inbox - long title", "url": "https://mail/"}])
        self.assertEqual(spec["folders"], [{"name": "Docs", "pins": [{"label": "Wiki page", "url": "https://wiki/"}]}])
        self.assertEqual(spec["pins"], [{"label": "Old pin", "url": "https://old/"}])

    def test_a_dumped_config_applies_to_no_structural_change(self):
        s = session()
        with tempfile.TemporaryDirectory() as d:
            config.write_config(config.current_spec(s, "Work"), d)
            spec = config.load_config(d)
        new, ops = model.apply_layout(s, spec)
        self.assertEqual(model.changes(ops), [])
        self.assertEqual(model.check(new, spec), [])

    def test_dump_refuses_to_overwrite_without_force(self):
        s = session()
        with tempfile.TemporaryDirectory() as d:
            config.write_config(config.current_spec(s, "Work"), d)
            with self.assertRaises(SystemExit):
                config.write_config(config.current_spec(s, "Work"), d)
            config.write_config(config.current_spec(s, "Work"), d, force=True)

    def test_dump_survives_awkward_labels(self):
        s = session()
        s["tabs"][2]["zenStaticLabel"] = 'quote " back\\slash 🗃️ é'
        with tempfile.TemporaryDirectory() as d:
            config.write_config(config.current_spec(s, "Work"), d)
            spec = config.load_config(d)
        self.assertEqual(spec["folders"][0]["pins"][0]["label"], 'quote " back\\slash 🗃️ é')

    def test_spec_fixture_is_valid(self):
        self.assertEqual(model.validate_spec(SPEC), [])


if __name__ == "__main__":
    unittest.main()
