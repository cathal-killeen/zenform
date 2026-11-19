import os
import struct
import tempfile
import unittest

import helpers  # noqa: F401  (puts src/ on the path)

from zenform import mozlz4


class Lz4(unittest.TestCase):
    def test_roundtrip_small_and_large(self):
        for n in (0, 1, 14, 15, 16, 254, 255, 270, 100_000):
            data = os.urandom(n)
            self.assertEqual(mozlz4.lz4_decompress(mozlz4.lz4_compress(data), n), data)

    def test_reads_a_block_with_matches(self):
        # "abc" as literals, then a 9-byte match at offset 3 (overlapping), then an empty literals-only end
        block = bytes([0x35]) + b"abc" + struct.pack("<H", 3) + bytes([0x00])
        self.assertEqual(mozlz4.lz4_decompress(block, 12), b"abcabcabcabc")

    def test_wrong_size_is_an_error(self):
        with self.assertRaises(ValueError):
            mozlz4.lz4_decompress(mozlz4.lz4_compress(b"hello"), 6)

    def test_mozlz4_roundtrip(self):
        obj = {"a": [1, 2, {"b": "é🗃"}]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.jsonlz4")
            with open(path, "wb") as f:
                f.write(mozlz4.encode(obj))
            self.assertEqual(mozlz4.read(path), obj)

    def test_rejects_other_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x")
            with open(path, "wb") as f:
                f.write(b"not a session")
            with self.assertRaises(ValueError):
                mozlz4.read(path)


if __name__ == "__main__":
    unittest.main()
