"""A whole-file change, as the small anchored edits a person -- or a model -- would make.

An operation produces the file it wants. Applying that as one replacement of the whole
file would work, and it would also put a giant ``edit_file`` call into the conversation
history for the model to imitate on the next turn -- the exact shape Phase 2 measured a
4B model failing at. So the difference is cut into hunks: each is a few lines, each
carries just enough surrounding context to occur exactly once, and each goes through
``edit_file`` like any other edit.
"""

from __future__ import annotations

import difflib


def hunks(before: str, after: str) -> list[tuple[str, str]]:
    """``(old_text, new_text)`` pairs that turn ``before`` into ``after``, in order.

    Applied first to last. Each ``old_text`` is unique in the file *as it stands when
    that hunk is applied*, so ``edit_file``'s exactly-once rule holds at every step.
    A pure insertion carries the line above it as its anchor, because ``edit_file``
    needs something to find.
    """
    if before == after:
        return []
    a = before.split("\n")
    b = after.split("\n")
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    opcodes = [op for op in matcher.get_opcodes() if op[0] != "equal"]

    result: list[tuple[str, str]] = []
    current = list(a)
    # Offset between positions in the original and in the file as edited so far.
    shift = 0
    for _tag, i1, i2, j1, j2 in opcodes:
        start, end = i1 + shift, i2 + shift
        replacement = b[j1:j2]
        lo, hi = start, end
        if lo == hi or not replacement:
            # A pure insertion has nothing to find, and a pure deletion replaced by ""
            # would leave its newline behind. Either way, carry the line above as the
            # anchor -- or the line below, at the very top.
            if lo > 0:
                lo -= 1
            else:
                hi += 1
        old, new = _window(current, lo, hi, start, end, replacement)
        while "\n".join(current).count(old) != 1:
            if lo > 0:
                lo -= 1
            elif hi < len(current):
                hi += 1
            else:
                break
            old, new = _window(current, lo, hi, start, end, replacement)
        result.append((old, new))
        current = current[:start] + replacement + current[end:]
        shift += len(replacement) - (i2 - i1)
    return result


def _window(lines: list[str], lo: int, hi: int, start: int, end: int,
            replacement: list[str]) -> tuple[str, str]:
    old = "\n".join(lines[lo:hi])
    new = "\n".join(lines[lo:start] + replacement + lines[end:hi])
    return old, new


def apply(text: str, pairs: list[tuple[str, str]]) -> str:
    """What ``edit_file`` would leave, for tests: each old_text replaced once, in order."""
    for old, new in pairs:
        assert text.count(old) == 1, old
        text = text.replace(old, new, 1)
    return text
