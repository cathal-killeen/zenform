"""Step through several configs, previewing each one in turn.

The loop only knows how to show an entry, ask what next, and close the window; zenform's CLI supplies those, so the
loop is easy to test without a browser. It wraps around: after the last config comes the first.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence


def next_index(answer: str, i: int, n: int) -> int | None:
    """Where to go from entry `i` of `n` after `answer`, or None to stop."""
    a = answer.strip().lower()
    if a in ("q", "quit", "exit"):
        return None
    if a in ("p", "prev", "previous", "b", "back"):
        return (i - 1) % n
    if a.isdigit() and 1 <= int(a) <= n:
        return int(a) - 1
    return (i + 1) % n  # Enter, n, anything else


def run_tour(
    entries: Sequence,
    show: Callable[[object, int, int], Callable[[], None]],
    ask: Callable[[str], str],
    out: Callable[[str], None] = print,
) -> None:
    """`show(entry, i, n)` prepares and opens the preview and returns a function that closes it."""
    n = len(entries)
    if n == 0:
        raise SystemExit("Nothing to tour.")
    out(f"Touring {n} config(s): Enter = next, p = previous, 1-{n} = jump, q = quit.\n")
    i = 0
    while True:
        close = show(entries[i], i, n)
        try:
            answer = ask("  > ")
        except (EOFError, KeyboardInterrupt):
            answer = "q"
            out("")
        finally:
            close()
        target = next_index(answer, i, n)
        if target is None:
            return
        i = target
