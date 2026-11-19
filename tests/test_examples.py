import os
import tempfile
import unittest

from helpers import session
from test_cli import run

from zenform import config, examples, model


class Bundled(unittest.TestCase):
    def test_the_expected_examples_ship(self):
        self.assertEqual([e.name for e in examples.bundled()], ["developer", "minimal", "research"])

    def test_every_example_is_valid_described_and_applies_cleanly(self):
        for e in examples.bundled():
            with self.subTest(example=e.name):
                spec = config.load_config(e.path)
                self.assertEqual(model.validate_spec(spec), [])
                self.assertEqual(model.warnings(spec), [])  # labels short, at most 9 essentials, no duplicates
                self.assertTrue(e.description, "needs a description in zenform.toml")
                new, _ = model.apply_layout(session(), spec)
                self.assertEqual(model.check(new, spec), [])

    def test_examples_use_no_private_hosts(self):
        for e in examples.bundled():
            spec = config.load_config(e.path)
            pins = spec["essentials"] + [p for f in spec["folders"] for p in f["pins"]]
            for p in pins:
                self.assertTrue(p["url"].startswith("https://"), p)
                self.assertNotIn("example", p["url"])  # real public sites, so icons can resolve


class Discover(unittest.TestCase):
    def make(self, root, name):
        d = os.path.join(root, name)
        os.makedirs(d)
        with open(os.path.join(d, "zenform.toml"), "w") as f:
            f.write('workspace = "W"\n')
        return d

    def test_a_config_directory_is_one_entry(self):
        with tempfile.TemporaryDirectory() as root:
            d = self.make(root, "mine")
            self.assertEqual(examples.discover([d]), [examples.Entry("mine", d)])

    def test_a_folder_of_configs_gives_each_in_name_order(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(root, "b")
            self.make(root, "a")
            os.makedirs(os.path.join(root, "not-a-config"))
            self.assertEqual([e.name for e in examples.discover([root])], ["a", "b"])

    def test_several_paths_are_concatenated_and_nothing_found_is_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            a = self.make(root, "a")
            b = self.make(root, "b")
            self.assertEqual([e.name for e in examples.discover([b, a])], ["b", "a"])
            with self.assertRaises(SystemExit):
                examples.discover([os.path.join(root, "missing")])
            os.makedirs(os.path.join(root, "empty"))
            with self.assertRaises(SystemExit):
                examples.discover([os.path.join(root, "empty")])


class Copy(unittest.TestCase):
    def test_copies_an_example_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "mine")
            examples.copy_bundled("developer", out)
            self.assertTrue(os.path.exists(os.path.join(out, "folders", "10-code.toml")))
            self.assertEqual(config.load_config(out)["workspace"], "Work")
            with self.assertRaises(SystemExit):
                examples.copy_bundled("developer", out)
            with self.assertRaises(SystemExit):
                examples.copy_bundled("nope", os.path.join(root, "x"))


class Cli(unittest.TestCase):
    def test_examples_lists_with_descriptions(self):
        code, out, _ = run("examples")
        self.assertEqual(code, 0)
        for name in ("developer", "minimal", "research"):
            self.assertIn(name, out)
        self.assertIn("Four essentials", out)

    def test_examples_copy_needs_out(self):
        code, _, err = run("examples", "minimal")
        self.assertNotEqual(code, 0)
        self.assertIn("--out", err)
        with tempfile.TemporaryDirectory() as root:
            code, out, _ = run("examples", "minimal", "--out", os.path.join(root, "c"))
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(os.path.join(root, "c", "zenform.toml")))


if __name__ == "__main__":
    unittest.main()
