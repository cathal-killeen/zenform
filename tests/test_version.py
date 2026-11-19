import os
import tomllib
import unittest

import helpers  # noqa: F401  (puts src/ on the path)

import zenform


class Version(unittest.TestCase):
    def test_package_version_matches_pyproject(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pyproject.toml")
        with open(path, "rb") as f:
            self.assertEqual(tomllib.load(f)["project"]["version"], zenform.__version__)


if __name__ == "__main__":
    unittest.main()
