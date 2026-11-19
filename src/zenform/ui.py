"""Terminal styling: colour and symbols that switch off cleanly when they would only be noise.

Colour is on for a real terminal, off when output is piped, when NO_COLOR is set or TERM is dumb, and can be forced
with FORCE_COLOR or --color always. Symbols fall back to ASCII on a terminal that is not UTF-8.
"""

from __future__ import annotations

import os
import shutil
import sys

CODES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "gray": "90",
}

SYMBOLS = {
    # name: (unicode, ascii)
    "ok": ("✓", "ok"),
    "warn": ("!", "!"),
    "fail": ("✗", "x"),
    "add": ("+", "+"),
    "change": ("~", "~"),
    "remove": ("−", "-"),
    "keep": ("=", "="),
    "arrow": ("→", "->"),
    "dot": ("·", "-"),
    "on": ("●", "*"),
    "off": ("○", "o"),
    "rule": ("─", "-"),
}


class UI:
    def __init__(self, stream=None, mode: str = "auto"):
        self.stream = stream if stream is not None else sys.stdout
        if mode == "always":
            self.color = True
        elif mode == "never":
            self.color = False
        else:
            tty = getattr(self.stream, "isatty", lambda: False)()
            self.color = bool(os.environ.get("FORCE_COLOR")) or (
                tty and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
            )
        encoding = (getattr(self.stream, "encoding", None) or "").lower()
        self.unicode = encoding.startswith("utf") and os.environ.get("TERM") != "linux"

    @property
    def width(self) -> int:
        return max(40, min(shutil.get_terminal_size((100, 24)).columns, 120))

    def paint(self, text: str, *styles: str) -> str:
        if not self.color or not styles:
            return text
        return f"\x1b[{';'.join(CODES[s] for s in styles)}m{text}\x1b[0m"

    def sym(self, name: str) -> str:
        return SYMBOLS[name][0 if self.unicode else 1]

    # shorthands
    def bold(self, t):
        return self.paint(t, "bold")

    def dim(self, t):
        return self.paint(t, "dim")

    def red(self, t):
        return self.paint(t, "red")

    def green(self, t):
        return self.paint(t, "green")

    def yellow(self, t):
        return self.paint(t, "yellow")

    def cyan(self, t):
        return self.paint(t, "cyan")

    def heading(self, t):
        return self.paint(t, "bold", "cyan")

    def rule(self, n: int | None = None) -> str:
        return self.dim(self.sym("rule") * (n or min(self.width, 60)))

    def status(self, kind: str, text: str) -> str:
        """A check-list line: ok / warn / fail."""
        style = {"ok": "green", "warn": "yellow", "fail": "red"}[kind]
        return f"{self.paint(self.sym(kind), style, 'bold')} {text}"

    def clip(self, text: str, room: int) -> str:
        if len(text) <= room:
            return text
        return text[: max(room - 1, 1)] + ("…" if self.unicode else "~")
