"""Keep a Research project's charts in the project's colours, whatever Gary writes.

The house style lives in ``matplotlibrc`` and every plain chart call picks it up. A model
told "never name a colour" still does, sometimes: the owner's weather dashboard came back
with ``color="red"``, ``"blue"``, ``"green"`` on every line, and that is what made it look
like stock matplotlib. A prompt rule is a request; this is the application checking.

When Gary writes chart code, a colour he **newly** named in a series call is taken out
before the file is saved, unless the child's own message asked for a colour. The code
keeps working, and each line draws in the next palette colour. Colours already in the
file are left alone, so something the child asked for earlier survives later edits.

Only literal colour strings in the ``color=`` / ``c=`` of a chart call are touched, and
only a rewrite that still compiles is kept -- the fallback is always the text as written.
"""

from __future__ import annotations

import ast
import re
from collections import Counter

#: Calls that draw a series. Decorations (axvline, text, annotate) are not here: a grey
#: guide line is a design choice, not a series that should take the next palette colour.
CHART_CALLS = frozenset({
    "plot", "bar", "barh", "scatter", "hist", "fill_between", "stackplot", "step",
    "errorbar", "lineplot", "barplot", "scatterplot", "histplot", "boxplot",
    "violinplot", "kdeplot", "regplot", "countplot", "pointplot", "areaplot",
})
COLOUR_KEYWORDS = frozenset({"color", "c"})

#: The names a model reaches for. Neutrals (black, white, grey) are left alone on
#: purpose: they are how a guide or an outline is drawn, not a series colour.
COLOUR_NAMES = frozenset({
    "red", "blue", "green", "orange", "purple", "yellow", "pink", "brown", "cyan",
    "magenta", "navy", "teal", "gold", "crimson", "indigo", "violet", "maroon", "olive",
    "lime", "salmon", "coral", "tomato", "orchid", "turquoise", "tan", "khaki",
    "skyblue", "steelblue", "royalblue", "lightblue", "darkblue", "lightgreen",
    "darkgreen", "forestgreen", "darkred", "darkorange", "firebrick", "seagreen",
    "limegreen", "slateblue", "dodgerblue", "hotpink", "deeppink", "mediumpurple",
})
_HEX = re.compile(r"^#(?:[0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)
_ASKED = re.compile(r"colou?r|#[0-9a-f]{3,6}\b", re.IGNORECASE)
#: A colour named in the child's message, as a word: "red" is asked for in "make it red",
#: not in "the hundred hottest days" or "I'm bored".
_NAMED = re.compile(r"\b(?:" + "|".join(sorted(COLOUR_NAMES, key=len, reverse=True))
                    + r")\b", re.IGNORECASE)


#: matplotlib's named palettes. Measured (SPIKES.md section 34F): asked for a dashboard,
#: Gary Smart wrote color="tab:blue", "tab:green", "tab:red" -- stock matplotlib again,
#: past a list that only knew plain names. Their greys are neutrals, like "grey".
_PALETTE_NAME = re.compile(r"^(?:tab|xkcd):(?!.*\b(?:gr[ae]y|black|white)\b).+$")


def _is_series_colour(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return text in COLOUR_NAMES or bool(_HEX.match(text)) or bool(_PALETTE_NAME.match(text))


def _occurrences(source: str) -> list[tuple[str, str, ast.keyword]]:
    """(call name, colour, keyword node) for every literal series colour in the source."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in CHART_CALLS:
            continue
        for keyword in node.keywords:
            if (keyword.arg in COLOUR_KEYWORDS and isinstance(keyword.value, ast.Constant)
                    and _is_series_colour(keyword.value.value)):
                found.append((name, keyword.value.value.strip().lower(), keyword))
    return found


def _offsets(source: str) -> list[int]:
    starts, total = [], 0
    for line in source.splitlines(keepends=True):
        starts.append(total)
        total += len(line.encode("utf-8"))
    return starts


def _cut(raw: bytes, begin: int, end: int) -> tuple[int, int]:
    """Widen a keyword's span to take its comma with it, so the call stays well formed."""
    after = end
    while after < len(raw) and raw[after:after + 1] in b" \t\r\n":
        after += 1
    if raw[after:after + 1] == b",":
        after += 1
        while after < len(raw) and raw[after:after + 1] in b" \t":
            after += 1
        return begin, after
    back = begin
    while back > 0 and raw[back - 1:back] in b" \t\r\n":
        back -= 1
    if back > 0 and raw[back - 1:back] == b",":
        return back - 1, end
    return begin, end


def keep_house_colours(before: str, after: str, asked: str = "") -> tuple[str, list[str]]:
    """``after`` without the series colours Gary newly named, and what was taken out.

    ``before`` is the file as it was (empty for a new file); ``asked`` is the child's
    message this turn. Returns ``after`` unchanged when the child asked for a colour,
    when nothing new was named, or when the result would not compile.
    """
    if _ASKED.search(asked or "") or _NAMED.search(asked or ""):
        return after, []
    already = Counter((name, colour) for name, colour, _ in _occurrences(before))
    doomed = []
    for name, colour, keyword in _occurrences(after):
        if already[(name, colour)] > 0:
            already[(name, colour)] -= 1
        else:
            doomed.append((colour, keyword))
    if not doomed:
        return after, []

    raw = after.encode("utf-8")
    starts = _offsets(after)
    spans = []
    for _, keyword in doomed:
        begin = starts[keyword.lineno - 1] + keyword.col_offset
        end = starts[keyword.end_lineno - 1] + keyword.end_col_offset
        spans.append(_cut(raw, begin, end))
    for begin, end in sorted(spans, reverse=True):
        raw = raw[:begin] + raw[end:]
    updated = raw.decode("utf-8")
    try:
        compile(updated, "<chart>", "exec")
    except (SyntaxError, ValueError):
        return after, []
    return updated, sorted({colour for colour, _ in doomed})


def note(removed: list[str]) -> str:
    """What the tool result says, so Gary does not tell the child he chose those colours."""
    names = ", ".join(repr(colour) for colour in removed)
    return (f" Note: Open Nest took out the colour{'s' if len(removed) > 1 else ''} "
            f"{names} you named, so the chart draws in the project's own palette. Do not "
            f"say you chose them. If the child asks for a colour, you can add it then.")
