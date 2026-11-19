"""The mozlz4 container Firefox and Zen use for session files, with a small pure-Python LZ4 block codec.

Layout: b"mozLz40\\0" + little-endian uint32 uncompressed size + one LZ4 block. The reader handles any block. The
writer emits the simplest valid one (a single literals-only sequence): it is a little larger than a compressed file,
and Zen compresses it again the next time it saves.
"""

from __future__ import annotations

import json
import struct

MAGIC = b"mozLz40\0"


def lz4_decompress(src: bytes, size: int) -> bytes:
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i : i + lit]
        i += lit
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        length = token & 15
        if length == 15:
            while True:
                b = src[i]
                i += 1
                length += b
                if b != 255:
                    break
        length += 4
        start = len(out) - offset
        if offset == 0 or start < 0:
            raise ValueError("corrupt LZ4 block (bad offset)")
        if offset >= length:
            out += out[start : start + length]
        else:  # overlapping copy
            for k in range(length):
                out.append(out[start + k])
    if len(out) != size:
        raise ValueError(f"corrupt LZ4 block (expected {size} bytes, got {len(out)})")
    return bytes(out)


def lz4_compress(data: bytes) -> bytes:
    """One literals-only sequence: valid LZ4, no compression."""
    n = len(data)
    out = bytearray()
    if n < 15:
        out.append(n << 4)
    else:
        out.append(0xF0)
        rest = n - 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    out += data
    return bytes(out)


def read(path: str):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:8] != MAGIC:
        raise ValueError(f"{path} is not a mozlz4 file")
    size = struct.unpack("<I", raw[8:12])[0]
    return json.loads(lz4_decompress(raw[12:], size))


def encode(obj) -> bytes:
    data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return MAGIC + struct.pack("<I", len(data)) + lz4_compress(data)
