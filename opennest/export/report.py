"""A Research project's report: its question, charts, findings and sources on 8 x 10 pages.

PHASE_12_HANDOFF section 7 asked for the chart and ``findings.md`` "composed into a PDF"
with no new dependency, and this is that: matplotlib's own PDF backend, the PNGs the
analysis drew, and the project's Markdown. SPIKES.md section 34 has the measurements
behind the numbers below.

**The pages are worked out by arithmetic, then drawn.** Every word is measured from the
font's unhinted outlines (the same at any resolution), every chart's size comes from its
pixels and dpi, and which page each thing lands on is decided before anything is drawn.
So "Page 2 of 3" is known when page 2 is drawn, and the page count for a fixed input is
a number a test can pin.

**What goes in is what the project says.** The Markdown is the child's or Gary's. The
starter's instructions and its ``<!-- comments -->`` are not, so a section still holding
only those is left out, and the caller is told so (:attr:`Report.notes`). The charts are
the ones the caller names -- in the Workbench, the ones the analysis drew when the report
was made -- so a stale chart cannot slip in.

**The look is data in the project**, ``src/report.toml`` beside ``matplotlibrc``, so "make
the title bigger" or "put the charts first" is one line. A project without one gets the
same defaults (:data:`STARTER_LAYOUT`).

**Preview and export are one thing.** :func:`build` returns PDF bytes. The Workbench shows
those bytes and Export PDF writes those bytes; there is no second renderer to disagree.
"""

from __future__ import annotations

import io
import logging
import os
import re
import unicodedata
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from functools import lru_cache
from pathlib import Path

import tomllib

from opennest import paths

# -- the page -------------------------------------------------------------------------
#
# Points throughout (72 to the inch). 8 x 10 inches is the owner's page.

PAGE_WIDTH = 8.0 * 72
PAGE_HEIGHT = 10.0 * 72
SIDE_MARGIN = 54.0                   # 0.75 in
TOP_MARGIN = 54.0
BOTTOM_MARGIN = 66.0                 # room for the footer inside it
CONTENT_WIDTH = PAGE_WIDTH - 2 * SIDE_MARGIN          # 6.5 in
CONTENT_TOP = PAGE_HEIGHT - TOP_MARGIN
CONTENT_BOTTOM = BOTTOM_MARGIN
CONTENT_HEIGHT = CONTENT_TOP - CONTENT_BOTTOM         # 600 pt, 8.33 in
HEADER_BASELINE = PAGE_HEIGHT - 33.0
HEADER_RULE = PAGE_HEIGHT - 40.0
FOOTER_BASELINE = 34.0

#: A chart that would not fit in what is left of a page may be made this much smaller to
#: stay on it, rather than leave a gap and start a new page. Measured (SPIKES.md section
#: 34): five ordinary charts took 7 pages at 1.0 (never smaller) and 4 at 0.85, two to a
#: page; the weather report went from 5 pages to 4, its first chart staying beside the
#: question at 87% rather than 91%. 0.7 changed nothing more.
KEEP_ON_PAGE = 0.85
#: The caption under a chart, and the space between it and what follows.
CAPTION_HEIGHT = 20.0
#: A chart drawn smaller than this is said, so the child can draw it as several charts.
SMALL_CHART = 0.7

#: Charts are the analysis's PNGs, which the child's code wrote: bounded like everything
#: else from that process. Far beyond any real chart (a 7 x 10 in figure at 150 dpi is
#: 1.6 million pixels), and far below what would hurt the application to decode.
MAX_CHART_PIXELS = 40_000_000
MAX_CHART_BYTES = 30_000_000
#: A Markdown file this big is not a report section.
MAX_TEXT_BYTES = 200_000

#: The default resolution of a picture that does not say: the house savefig.dpi.
DEFAULT_DPI = 150.0

# -- the type ---------------------------------------------------------------------------
#
# The chart's own chain (the starter's matplotlibrc), so the page and the charts read as
# one document, then a font that has the rest of Unicode. Families that are not installed
# are dropped before matplotlib sees them, because naming one makes it warn every time.

SANS_CHAIN = ("Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans", "Arial Unicode MS")
MONO_CHAIN = ("Menlo", "DejaVu Sans Mono")

#: The parts of a report, in their default order.
SECTIONS = ("question", "charts", "findings", "sources")
SECTION_FILES = {"question": "question.md", "findings": "findings.md",
                 "sources": "sources.md"}
#: Where the layout lives, relative to the project.
LAYOUT_FILE = "src/report.toml"
#: The heading over the charts, which have no Markdown of their own.
CHARTS_HEADING = "Charts"

TITLE_SIZES = (12.0, 48.0)
TEXT_SIZES = (8.0, 16.0)

#: The research starter's own ``report.toml``: what the file holds when it is new, and so
#: the one place its defaults are written down (a test holds :class:`Layout` to it).
STARTER_DIR = paths.package_root() / "projects" / "starters" / "research_basic"
STARTER_LAYOUT = STARTER_DIR / "report.toml"


class ReportError(Exception):
    """No report can be made, said for the child."""


@dataclass(frozen=True)
class Layout:
    """``src/report.toml``, checked."""

    title: str = ""
    author: str = ""
    title_size: float = 26.0
    text_size: float = 11.0
    order: tuple[str, ...] = SECTIONS
    charts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    """A made report. ``pdf`` is the whole file; everything else is about it."""

    pdf: bytes
    pages: int
    title: str
    #: Project-relative paths of the charts in it, in the order they appear.
    charts: tuple[str, ...]
    #: Which of :data:`SECTIONS` are in it, in order.
    sections: tuple[str, ...]
    #: What the child should know: what was left out and why, what was adjusted.
    notes: tuple[str, ...]
    #: Every piece of text the PDF was made from, by project-relative path, so what leaves
    #: the project can be scanned for credentials before it does (``export.save``).
    words: tuple[tuple[str, str], ...] = ()
    #: Where each part starts, as (part, page number).
    starts: tuple[tuple[str, int], ...] = ()
    #: Each chart as (path, page number, the scale it is printed at).
    placements: tuple[tuple[str, int, float], ...] = ()


# =============================================================================== layout

def read_layout(project_dir: Path) -> tuple[Layout, list[str], str]:
    """The project's layout, what was wrong with it, and the file's text ("" if none).

    A mistake never stops the report: a bad value gets its default and is named, the way a
    child would want a typo in a school report's settings handled.
    """
    path = Path(project_dir) / LAYOUT_FILE
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return Layout(), ["report.toml could not be read, so the report uses the usual "
                          "layout."], ""
    if not text:
        return Layout(), [], ""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        where = re.search(r"line (\d+)", str(exc))
        at = f" on line {where.group(1)}" if where else ""
        return Layout(), [f"report.toml has a mistake{at}, so the report uses the usual "
                          f"layout until it is fixed."], text
    notes: list[str] = []
    values: dict = {}
    known = {f for f in Layout.__dataclass_fields__}
    for key in raw:
        if key not in known:
            notes.append(f"report.toml: Open Nest does not know “{key}”, so it "
                         f"was left alone.")
    for key in ("title", "author"):
        if key in raw:
            if isinstance(raw[key], str):
                values[key] = " ".join(raw[key].split())
            else:
                notes.append(f"report.toml: {key} has to be words in quotes, so it was "
                             f"left out.")
    for key, (low, high) in (("title_size", TITLE_SIZES), ("text_size", TEXT_SIZES)):
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int | float):
            notes.append(f"report.toml: {key} has to be a number, so "
                         f"{getattr(Layout, key):g} was used.")
            continue
        clamped = min(max(float(value), low), high)
        if clamped != value:
            notes.append(f"report.toml: {key} can be {low:g} to {high:g}, so {clamped:g} "
                         f"was used.")
        values[key] = clamped
    if "order" in raw:
        order = raw["order"]
        if not isinstance(order, list) or not all(isinstance(p, str) for p in order):
            notes.append("report.toml: order has to be a list like [\"question\", "
                         "\"charts\"], so the usual order was used.")
        else:
            parts = []
            for part in order:
                name = part.strip().lower()
                if name not in SECTIONS:
                    notes.append(f"report.toml: there is no part called “{part}” "
                                 f"(the parts are {', '.join(SECTIONS)}).")
                elif name not in parts:
                    parts.append(name)
            values["order"] = tuple(parts)
    if "charts" in raw:
        charts = raw["charts"]
        if not isinstance(charts, list) or not all(isinstance(c, str) for c in charts):
            notes.append("report.toml: charts has to be a list of file names, so every "
                         "chart is in.")
        else:
            values["charts"] = tuple(c.strip() for c in charts if c.strip())
    return replace(Layout(), **values), notes, text


def ensure_layout_file(project_dir: Path) -> bool:
    """Copy the starter's ``report.toml`` into ``src/`` if there is none. True if it
    was written now -- a project made before the file was in the research starter."""
    path = Path(project_dir) / LAYOUT_FILE
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STARTER_LAYOUT.read_text(encoding="utf-8"), encoding="utf-8")
    return True


# ============================================================================= markdown
#
# The subset a child's report uses: headings, paragraphs, lists, tables, code, rules,
# **bold**, *italic*, `code` and [links](...). Not a Markdown implementation, and it does
# not try to be: anything else is printed as the words it is.

@dataclass(frozen=True)
class Block:
    kind: str               # heading | paragraph | item | table | code | rule | quote
    text: str = ""
    level: int = 0          # a heading's level, or a list item's depth
    marker: str = ""        # a list item's bullet or number
    rows: tuple[tuple[str, ...], ...] = ()   # a table's, header first


_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def parse_markdown(text: str) -> list[Block]:
    """Blocks, in order. Comments are gone; line breaks inside a paragraph are spaces."""
    text = _COMMENT.sub("", text.replace("\r\n", "\n"))
    blocks: list[Block] = []
    paragraph: list[str] = []
    lines = text.split("\n")

    def close() -> None:
        if paragraph:
            joined = " ".join(part.strip() for part in paragraph).strip()
            if joined:
                quote = all(part.lstrip().startswith(">") for part in paragraph)
                if quote:
                    joined = " ".join(p.lstrip()[1:].strip() for p in paragraph).strip()
                blocks.append(Block("quote" if quote else "paragraph", joined))
            paragraph.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            close()
            code = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index].rstrip())
                index += 1
            blocks.append(Block("code", "\n".join(code)))
            index += 1
            continue
        if not stripped:
            close()
        elif heading := _HEADING.match(stripped):
            close()
            blocks.append(Block("heading", heading.group(2), level=len(heading.group(1))))
        elif _RULE.match(stripped) and not paragraph:
            blocks.append(Block("rule"))
        elif stripped.startswith("|"):
            close()
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = lines[index].strip()
                if not _TABLE_SEPARATOR.match(row):
                    cells = row.strip("|").split("|")
                    rows.append(tuple(cell.strip() for cell in cells))
                index += 1
            blocks.append(Block("table", rows=tuple(rows)))
            continue
        elif (item := _BULLET.match(line)) or (item := _NUMBERED.match(line)):
            close()
            depth = min(len(item.group(1).expandtabs(4)) // 2, 3)
            marker = "•" if item.re is _BULLET else f"{item.group(2)}."
            words = [item.groups()[-1]]
            # A wrapped item continues on indented lines that are not new items.
            while index + 1 < len(lines) and lines[index + 1].startswith((" ", "\t")) \
                    and lines[index + 1].strip() and not _BULLET.match(lines[index + 1]) \
                    and not _NUMBERED.match(lines[index + 1]):
                index += 1
                words.append(lines[index].strip())
            blocks.append(Block("item", " ".join(words), level=depth, marker=marker))
        else:
            paragraph.append(line)
        index += 1
    close()
    return blocks


def _key(block: Block) -> str:
    """What a block says, ignoring spacing and case: how template text is recognised."""
    words = block.text if block.kind != "table" else " | ".join(" ".join(r) for r in block.rows)
    return " ".join(words.split()).casefold()


@lru_cache(maxsize=8)
def _starter_keys(name: str) -> frozenset[str]:
    """Everything the research starter's own copy of ``name`` says, block by block."""
    path = STARTER_DIR / name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    return frozenset(_key(b) for b in parse_markdown(text) if b.kind != "heading")


def own_words(name: str, text: str) -> list[Block]:
    """The blocks of ``text`` that are not the starter's: what the child (or Gary) wrote.

    A paragraph the starter shipped is its instructions, not a finding. A table row with
    nothing in it says nothing, and a table with no rows left is gone. A heading stays
    only while something of their own is under it.
    """
    template = _starter_keys(name)
    kept: list[Block] = []
    for block in parse_markdown(text):
        if block.kind == "table":
            header, *body = block.rows or ((),)
            body = [row for row in body if any(cell for cell in row)]
            if not body:
                continue
            block = replace(block, rows=(header, *body))
        elif block.kind not in ("heading", "rule") and _key(block) in template:
            continue
        kept.append(block)
    # Headings with nothing of theirs under them, from the end back.
    result: list[Block] = []
    below: int | None = None    # level of the shallowest heading-free content below
    for block in reversed(kept):
        if block.kind == "heading":
            if below is None or below <= block.level:
                continue
            result.append(block)
            below = block.level
        elif block.kind == "rule":
            if below is not None:
                result.append(block)
        else:
            result.append(block)
            below = 99
    result.reverse()
    # A rule left first or last, or two in a row, is not separating anything.
    tidy = [b for i, b in enumerate(result) if b.kind != "rule" or (
        0 < i < len(result) - 1 and result[i + 1].kind != "rule")]
    return tidy


# =============================================================================== fonts

@lru_cache(maxsize=1)
def _matplotlib():
    """matplotlib, imported once and kept inside Open Nest's own cache.

    The application never imported matplotlib before reports. Left to itself it writes its
    font cache to ``~/.matplotlib``, outside ``OPENNEST_HOME`` (HANDOFF section 2: every
    write the dev setup makes is under ``.opennest-sandbox/``).
    """
    if "MPLCONFIGDIR" not in os.environ:
        cache = paths.cache_dir() / "matplotlib"
        cache.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(cache)
    import matplotlib

    matplotlib.use("Agg", force=False)
    # The Unicode fallback has no bold, which matplotlib says on every bold heading. It
    # falls back to the regular face, which is right, so the saying is noise.
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    return matplotlib


@lru_cache(maxsize=4)
def _installed(chain: tuple[str, ...]) -> tuple[str, ...]:
    _matplotlib()
    from matplotlib import font_manager

    found = []
    for family in chain:
        try:
            font_manager.findfont(font_manager.FontProperties(family=family),
                                  fallback_to_default=False)
        except ValueError:
            continue
        found.append(family)
    return tuple(found) or ("DejaVu Sans",)


@lru_cache(maxsize=64)
def _font(style: str, size: float):
    _matplotlib()
    from matplotlib.font_manager import FontProperties

    if style == "mono":
        return FontProperties(family=list(_installed(MONO_CHAIN)), size=size)
    return FontProperties(family=list(_installed(SANS_CHAIN)), size=size,
                          weight="bold" if style == "bold" else "normal",
                          style="italic" if style == "italic" else "normal")


@lru_cache(maxsize=1)
def _coverage_fonts():
    _matplotlib()
    from matplotlib import font_manager
    from matplotlib.ft2font import FT2Font

    fonts = []
    for family in _installed(SANS_CHAIN) + _installed(MONO_CHAIN):
        path = font_manager.findfont(font_manager.FontProperties(family=family))
        fonts.append(FT2Font(path))
    return fonts


@lru_cache(maxsize=4096)
def _printable(character: str) -> bool:
    if character.isspace():
        return True
    if ord(character) < 0x250:
        return unicodedata.category(character) != "Cc"
    return any(font.get_char_index(ord(character)) for font in _coverage_fonts())


def printable(text: str) -> tuple[str, str]:
    """``text`` without what no installed font can draw, and what was taken out.

    An emoji or a script none of the fonts have would print as an empty box and make
    matplotlib warn on every page; leaving it out and saying so is the honest version. The
    invisible ones -- an emoji's variation selector, a joiner, a control character -- go
    without being named, because naming them shows nothing.
    """
    missing = "".join(dict.fromkeys(c for c in text if not _printable(c)))
    if not missing:
        return text, ""
    kept = "".join(c for c in text if c not in missing)
    named = "".join(c for c in missing if unicodedata.category(c) not in _INVISIBLE)
    return kept, named


_INVISIBLE = frozenset({"Mn", "Me", "Cf", "Cc", "Co", "Cn", "Cs"})


@lru_cache(maxsize=20000)
def _width(text: str, style: str, size: float) -> float:
    """Width in points, from the outlines -- what the PDF draws, at any resolution."""
    _matplotlib()
    from matplotlib.textpath import text_to_path

    if not text:
        return 0.0
    width, _height, _descent = text_to_path.get_text_width_height_descent(
        text, _font(style, size), ismath=False)
    return width


@lru_cache(maxsize=64)
def _space(style: str, size: float) -> float:
    return _width("x x", style, size) - _width("xx", style, size)


# ================================================================================ text

#: Inline marks: **bold**, __bold__, `code`, *italic*, ![picture](...), [link](url).
_INLINE = re.compile(r"\*\*(?P<b>.+?)\*\*|__(?P<b2>.+?)__|`(?P<m>[^`]+)`|"
                     r"(?<![\w*])\*(?P<i>[^*\s][^*]*?)\*(?![\w*])|"
                     r"!\[(?P<alt>[^\]]*)\]\([^)]*\)|\[(?P<lt>[^\]]+)\]\((?P<url>[^)\s]+)\)")


def _runs(text: str) -> list[tuple[str, str]]:
    """(text, style) runs for one block's words."""
    runs: list[tuple[str, str]] = []
    at = 0
    for match in _INLINE.finditer(text):
        if match.start() > at:
            runs.append((text[at:match.start()], ""))
        if match.group("b") or match.group("b2"):
            runs.append((match.group("b") or match.group("b2"), "bold"))
        elif match.group("m"):
            runs.append((match.group("m"), "mono"))
        elif match.group("i"):
            runs.append((match.group("i"), "italic"))
        elif match.group("alt") is not None:
            runs.append((match.group("alt"), ""))
        else:
            label, url = match.group("lt"), match.group("url")
            runs.append((label if label == url else f"{label} ({url})", ""))
        at = match.end()
    if at < len(text):
        runs.append((text[at:], ""))
    return runs


@dataclass(frozen=True)
class Word:
    text: str
    style: str
    spaced: bool            # whether a space comes before it


def _words(text: str, style: str = "") -> list[Word]:
    words: list[Word] = []
    pending_space = False
    for chunk, run_style in _runs(text):
        chosen = style if style and run_style in ("", "italic") else run_style or style
        for piece in re.split(r"(\s+)", chunk):
            if not piece:
                continue
            if piece.isspace():
                pending_space = True
                continue
            words.append(Word(piece, chosen, pending_space and bool(words)))
            pending_space = False
    return words


@dataclass(frozen=True)
class Segment:
    """Words of one style on one line, drawn as one string at ``x``."""

    x: float
    text: str
    style: str


def _break_word(word: Word, size: float, width: float) -> list[Word]:
    """A word longer than a whole line (a web address), cut into pieces that fit."""
    pieces, current = [], ""
    for character in word.text:
        if current and _width(current + character, word.style, size) > width:
            pieces.append(current)
            current = ""
        current += character
    pieces.append(current)
    return [Word(piece, word.style, word.spaced and i == 0) for i, piece in enumerate(pieces)]


def wrap(words: Sequence[Word], size: float, width: float) -> list[list[Segment]]:
    """Greedy line breaking on measured widths. Deterministic: same words, same lines."""
    lines: list[list[tuple[float, Word]]] = [[]]
    x = 0.0
    queue = deque(words)
    while queue:
        word = queue.popleft()
        w = _width(word.text, word.style, size)
        if w > width and len(word.text) > 1:
            # One character wider than the line (a narrow table cell) is placed as it is.
            queue.extendleft(reversed(_break_word(word, size, width)))
            continue
        gap = _space(word.style, size) if word.spaced and lines[-1] else 0.0
        if lines[-1] and x + gap + w > width:
            lines.append([])
            x, gap = 0.0, 0.0
        lines[-1].append((x + gap, word))
        x += gap + w
    result = []
    for line in lines:
        segments: list[Segment] = []
        for x, word in line:
            if segments and segments[-1].style == word.style:
                last = segments[-1]
                joiner = " " if word.spaced else ""
                segments[-1] = Segment(last.x, last.text + joiner + word.text, last.style)
            else:
                segments.append(Segment(x, word.text, word.style))
        result.append(segments)
    return [line for line in result if line]


# ============================================================================ the flow

@dataclass(frozen=True)
class Text:
    """One line of text, ``baseline`` points below the top of its chunk."""

    x: float
    baseline: float
    segments: tuple[Segment, ...]
    size: float
    colour: str


@dataclass(frozen=True)
class Line:
    x0: float
    x1: float
    y: float                # below the top of its chunk
    colour: str
    width: float = 0.6


@dataclass(frozen=True)
class Bar:
    x: float
    y: float                # top, below the top of its chunk
    width: float
    height: float
    colour: str


@dataclass
class Chunk:
    """Something that is never split across pages. ``height`` excludes ``space_before``,
    which is dropped at the top of a page."""

    height: float
    space_before: float = 0.0
    marks: list = field(default_factory=list)
    keep_with_next: bool = False
    chart: Chart | None = None
    part: str = ""          # the report part this chunk begins, if it begins one


@dataclass(frozen=True)
class Chart:
    path: str               # project-relative
    pixels: tuple[int, int]
    dpi: float
    number: int

    @property
    def natural(self) -> tuple[float, float]:
        width, height = self.pixels
        return width / self.dpi * 72.0, height / self.dpi * 72.0

    def page_scale(self) -> float:
        """The scale it is printed at on a page of its own: never larger than drawn."""
        width, height = self.natural
        return min(1.0, CONTENT_WIDTH / width, (CONTENT_HEIGHT - CAPTION_HEIGHT) / height)


@dataclass(frozen=True)
class Placed:
    chunk: Chunk
    top: float              # page coordinates, points from the bottom
    scale: float = 1.0      # a chart's


class Style:
    """Sizes for one text size. Everything scales with ``text_size``."""

    def __init__(self, layout: Layout, palette) -> None:
        self.layout = layout
        self.palette = palette
        size = layout.text_size
        self.body = size
        self.leading = 1.42
        self.paragraph_gap = size * 0.55
        self.headings = {1: size * 1.5, 2: size * 1.18, 3: size * 1.0}
        self.heading_gap = {1: size * 1.6, 2: size * 1.1, 3: size * 0.9}
        self.small = max(size * 0.8, 7.5)
        self.indent = size * 1.5


def _text_chunks(lines: list[list[Segment]], size: float, colour: str, *, x: float = 0.0,
                 leading: float, gap_before: float, marker: Segment | None = None,
                 bold: bool = False) -> list[Chunk]:
    """A paragraph's lines as chunks: never one line alone at the foot or head of a page
    (no widows or orphans), so a paragraph of three lines or fewer stays whole."""
    height = size * leading
    ascent = size * 0.95 + (height - size * 1.2) / 2
    rows = []
    for number, segments in enumerate(lines):
        if bold:
            segments = [Segment(s.x, s.text, "bold" if s.style != "mono" else "mono")
                        for s in segments]
        marks = [Text(x, ascent, tuple(segments), size, colour)]
        if number == 0 and marker is not None:
            marks.append(Text(x - marker.x, ascent, (Segment(0, marker.text, ""),), size,
                              colour))
        rows.append(marks)
    count = len(rows)
    if count <= 3:
        groups = [list(range(count))]
    else:
        groups = [[0, 1], *[[i] for i in range(2, count - 2)], [count - 2, count - 1]]
    chunks = []
    for index, group in enumerate(groups):
        marks = []
        for offset, row in enumerate(group):
            for mark in rows[row]:
                marks.append(replace(mark, baseline=mark.baseline + offset * height))
        chunks.append(Chunk(height * len(group), gap_before if index == 0 else 0.0, marks))
    return chunks


def _table_chunks(block: Block, style: Style) -> list[Chunk]:
    size = style.body * 0.92
    colour = style.palette.text
    columns = max(len(row) for row in block.rows)
    rows = [tuple(row) + ("",) * (columns - len(row)) for row in block.rows]
    widths = _column_widths(rows, size, pad := 5.0)
    lefts = [sum(widths[:i]) for i in range(columns)]
    height = size * style.leading
    ascent = size * 0.95 + (height - size * 1.2) / 2
    chunks = []
    for number, row in enumerate(rows):
        header = number == 0
        cell_lines = [wrap(_words(cell, "bold" if header else ""), size,
                           widths[i] - 2 * pad) or [[]] for i, cell in enumerate(row)]
        tallest = max(len(lines) for lines in cell_lines)
        marks: list = []
        for i, lines in enumerate(cell_lines):
            for line_number, segments in enumerate(lines):
                if segments:
                    marks.append(Text(lefts[i] + pad, pad + ascent + line_number * height,
                                      tuple(segments), size, colour))
        row_height = tallest * height + 2 * pad
        marks.append(Line(0, CONTENT_WIDTH, row_height, style.palette.border,
                          0.9 if header else 0.5))
        chunks.append(Chunk(row_height, style.paragraph_gap if header else 0.0, marks,
                            keep_with_next=header))
    return chunks


def _column_widths(rows: list[tuple[str, ...]], size: float, pad: float) -> list[float]:
    """Each column gets its longest word (so a file name is not cut in two), then the rest
    of the width goes where the words are, in proportion to how much each column says."""
    columns = list(zip(*rows, strict=True))
    least = [max([_width(word, "bold", size) for cell in column for word in cell.split()]
                 + [24.0]) + 2 * pad for column in columns]
    if sum(least) >= CONTENT_WIDTH:
        return [width * CONTENT_WIDTH / sum(least) for width in least]
    wants = [max(_width(cell, "", size) for cell in column) + 2 * pad for column in columns]
    extra = [max(want - low, 0.0) for want, low in zip(wants, least, strict=True)]
    spare = CONTENT_WIDTH - sum(least)
    if sum(extra) <= spare:
        # Everything fits on one line; the last column takes what is left over.
        widths = [low + more for low, more in zip(least, extra, strict=True)]
        widths[-1] += spare - sum(extra)
        return widths
    return [low + spare * more / sum(extra) for low, more in zip(least, extra, strict=True)]


def _block_chunks(block: Block, style: Style) -> list[Chunk]:
    palette = style.palette
    if block.kind == "heading":
        level = min(block.level, 3)
        size = style.headings[level]
        lines = wrap(_words(block.text, "bold"), size, CONTENT_WIDTH)
        heading = _stack(_text_chunks(lines, size, palette.text, leading=1.25,
                                      gap_before=style.heading_gap[level], bold=True))
        heading.height += size * 0.25
        heading.keep_with_next = True
        return [heading]
    if block.kind == "rule":
        return [Chunk(style.body, style.paragraph_gap,
                      [Line(0, CONTENT_WIDTH, style.body / 2, palette.border)])]
    if block.kind == "table":
        return _table_chunks(block, style)
    if block.kind == "code":
        size = style.body * 0.88
        lines = []
        for raw in block.text.split("\n") or [""]:
            words = [Word(raw, "mono", False)] if raw else []
            lines.extend(wrap(words, size, CONTENT_WIDTH - style.indent) or [[]])
        lines = [line or [Segment(0, "", "mono")] for line in lines]
        return _text_chunks(lines, size, palette.text, x=style.indent, leading=1.3,
                            gap_before=style.paragraph_gap)
    size = style.body
    indent = 0.0
    marker = None
    words_style = ""
    colour = palette.text
    if block.kind == "item":
        indent = style.indent * (block.level + 1)
        marker = Segment(style.indent * 0.95, block.marker, "")
    elif block.kind == "quote":
        indent = style.indent
        words_style = "italic"
        colour = palette.text_muted
    lines = wrap(_words(block.text, words_style), size, CONTENT_WIDTH - indent)
    gap = style.paragraph_gap * (0.45 if block.kind == "item" else 1.0)
    return _text_chunks(lines, size, colour, x=indent, leading=style.leading,
                        gap_before=gap, marker=marker)


def _stack(chunks: list[Chunk]) -> Chunk:
    """Chunks made one, each one's marks moved down by the heights above it."""
    marks, offset = [], 0.0
    for chunk in chunks:
        marks.extend(_moved(mark, offset) for mark in chunk.marks)
        offset += chunk.height
    return Chunk(offset, chunks[0].space_before if chunks else 0.0, marks)


def _moved(mark, offset: float):
    if isinstance(mark, Text):
        return replace(mark, baseline=mark.baseline + offset)
    return replace(mark, y=mark.y + offset)          # a Line or a Bar


def _title_chunks(title: str, byline: str, style: Style) -> list[Chunk]:
    palette = style.palette
    size = style.layout.title_size
    lines = wrap(_words(title, "bold"), size, CONTENT_WIDTH)
    stacked = _stack(_text_chunks(lines, size, palette.text, leading=1.15, gap_before=0.0,
                                  bold=True))
    marks, height = stacked.marks, stacked.height
    if byline:
        small = style.body * 0.95
        line_height = small * 1.5
        marks.append(Text(0, height + small * 0.6 + small * 0.95,
                          tuple(wrap(_words(byline), small, CONTENT_WIDTH)[0]), small,
                          palette.text_muted))
        height += small * 0.6 + line_height
    # The one amber thing on the page: a short bar under the title, an indicator lamp
    # rather than a band (brand guide sections 25 and 26).
    marks.append(Bar(0, height + 8.0, 44.0, 3.0, palette.accent))
    height += 8.0 + 3.0 + 6.0
    return [Chunk(height, 0.0, marks, keep_with_next=True)]


def _chart_chunk(chart: Chart, style: Style) -> Chunk:
    """A chart's caption; the picture itself is sized when its page is known."""
    label = f"Chart {chart.number}"
    after = _width(label, "bold", style.small) + style.small * 0.8
    caption = Text(0, CAPTION_HEIGHT - 7.0, (Segment(0, label, "bold"),
                                             Segment(after, Path(chart.path).name, "mono")),
                   style.small, style.palette.text_muted)
    return Chunk(0.0, style.paragraph_gap * 1.4, [caption], chart=chart)


def _fits(chunk: Chunk, room: float, *, first: bool) -> tuple[bool, float, float]:
    """Whether ``chunk`` fits in ``room`` (points), at what scale, and the height it takes
    with the space before it. ``first``: it would be first on its page, so no space."""
    gap = 0.0 if first else chunk.space_before
    if chunk.chart is None:
        return gap + chunk.height <= room, 1.0, gap + chunk.height
    scale = chunk.chart.page_scale()
    natural = chunk.chart.natural[1]
    if gap + natural * scale + CAPTION_HEIGHT > room:
        shrunk = (room - gap - CAPTION_HEIGHT) / natural
        if shrunk < scale * KEEP_ON_PAGE:
            return False, scale, gap + natural * scale + CAPTION_HEIGHT
        scale = shrunk
    return True, scale, gap + natural * scale + CAPTION_HEIGHT


def paginate(chunks: Sequence[Chunk]) -> list[list[Placed]]:
    """Which page each chunk lands on, and where. The whole of pagination.

    - Text is never split inside a chunk, and space is dropped at the top of a page.
    - A chunk that keeps with the next (a title, a heading, a table's header row) goes to
      a new page with it rather than be left alone at the foot of one.
    - A chart is never split and never enlarged. It is made to fit the page's width. If
      what is left of the page is too short it may be made up to :data:`KEEP_ON_PAGE`
      smaller to stay, and otherwise it starts the next page. One taller than a whole
      page is made to fit a page of its own.
    - Something that does not fit even on an empty page is put there anyway: a page is
      never left empty and nothing is dropped.
    """
    pages: list[list[Placed]] = [[]]
    top = CONTENT_TOP
    for index, chunk in enumerate(chunks):
        # This chunk, and the ones it keeps with, have to fit from here.
        room = top - CONTENT_BOTTOM
        first = not pages[-1]
        used = 0.0
        for later in chunks[index:]:
            fits, _scale, height = _fits(later, room - used, first=first and later is chunk)
            if not fits:
                break
            used += height
            if not later.keep_with_next:
                break
        if not fits and not first:
            pages.append([])
            top = CONTENT_TOP
            first = True
        _fit, scale, height = _fits(chunk, top - CONTENT_BOTTOM, first=first)
        pages[-1].append(Placed(chunk, top - (0.0 if first else chunk.space_before), scale))
        top -= height
    return [page for page in pages if page] or [[]]


# ============================================================================== drawing

def _draw(pages: list[list[Placed]], title: str, palette, project_dir: Path,
          metadata: dict) -> bytes:
    matplotlib = _matplotlib()
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    def text(figure, x, y, s, style, size, colour, **kw):
        figure.text(x / PAGE_WIDTH, y / PAGE_HEIGHT, s, fontproperties=_font(style, size),
                    color=colour, parse_math=False, va="baseline", **kw)

    def hairline(figure, x0, x1, y, colour, width):
        figure.add_artist(Line2D([x0 / PAGE_WIDTH, x1 / PAGE_WIDTH],
                                 [y / PAGE_HEIGHT, y / PAGE_HEIGHT],
                                 transform=figure.transFigure, color=colour,
                                 linewidth=width, solid_capstyle="butt"))

    buffer = io.BytesIO()
    settings = {"pdf.fonttype": 42, "savefig.bbox": None, "savefig.pad_inches": 0,
                "savefig.dpi": 72, "savefig.transparent": False, "pdf.compression": 6}
    total = len(pages)
    header = _fit_line(title, "", 8.5, CONTENT_WIDTH * 0.8)
    with matplotlib.rc_context(settings), PdfPages(buffer, metadata=metadata) as pdf:
        for number, page in enumerate(pages, start=1):
            figure = Figure(figsize=(PAGE_WIDTH / 72, PAGE_HEIGHT / 72), dpi=72,
                            facecolor=palette.surface)
            if number > 1:
                text(figure, SIDE_MARGIN, HEADER_BASELINE, header, "", 8.5,
                     palette.text_muted)
                hairline(figure, SIDE_MARGIN, PAGE_WIDTH - SIDE_MARGIN, HEADER_RULE,
                         palette.border, 0.6)
            text(figure, SIDE_MARGIN, FOOTER_BASELINE, "Made with Open Nest", "mono", 7.5,
                 palette.text_muted)
            text(figure, PAGE_WIDTH - SIDE_MARGIN, FOOTER_BASELINE,
                 f"Page {number} of {total}", "", 8.5, palette.text_muted, ha="right")
            for placed in page:
                top, left = placed.top, SIDE_MARGIN
                chart = placed.chunk.chart
                if chart is not None:
                    # The picture, then its caption under it, both from its left edge.
                    width, height = (v * placed.scale for v in chart.natural)
                    left = SIDE_MARGIN + (CONTENT_WIDTH - width) / 2
                    axes = figure.add_axes((left / PAGE_WIDTH, (top - height) / PAGE_HEIGHT,
                                            width / PAGE_WIDTH, height / PAGE_HEIGHT))
                    # "none": the PNG's own pixels go into the PDF unresampled, and the
                    # viewer or printer scales them (SPIKES.md section 34).
                    axes.imshow(_pixels(project_dir / chart.path, palette.surface),
                                interpolation="none", aspect="auto")
                    axes.set_axis_off()
                    top -= height
                for mark in placed.chunk.marks:
                    if isinstance(mark, Text):
                        for segment in mark.segments:
                            text(figure, left + mark.x + segment.x, top - mark.baseline,
                                 segment.text, segment.style, mark.size, mark.colour)
                    elif isinstance(mark, Line):
                        hairline(figure, left + mark.x0, left + mark.x1, top - mark.y,
                                 mark.colour, mark.width)
                    elif isinstance(mark, Bar):
                        figure.add_artist(Rectangle(
                            ((left + mark.x) / PAGE_WIDTH,
                             (top - mark.y - mark.height) / PAGE_HEIGHT),
                            mark.width / PAGE_WIDTH, mark.height / PAGE_HEIGHT,
                            transform=figure.transFigure, facecolor=mark.colour,
                            edgecolor="none"))
            pdf.savefig(figure)
    return buffer.getvalue()


def _fit_line(text: str, style: str, size: float, width: float) -> str:
    if _width(text, style, size) <= width:
        return text
    while text and _width(text + "…", style, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _pixels(path: Path, paper: str):
    """A chart's pixels, laid on the paper if it has see-through parts."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        image.load()
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            ground = Image.new("RGBA", rgba.size, paper)
            ground.alpha_composite(rgba)
            return np.asarray(ground.convert("RGB"))
        return np.asarray(image.convert("RGB"))


# =============================================================================== build

def _read_text(project_dir: Path, name: str) -> tuple[str | None, str]:
    """``src/<name>``, or the project's top level if Gary put it there."""
    for relative in (f"src/{name}", name):
        path = Path(project_dir) / relative
        if path.is_file() and not path.is_symlink():
            if path.stat().st_size > MAX_TEXT_BYTES:
                raise ReportError(f"{relative} is too long to put in a report "
                                  f"(over {MAX_TEXT_BYTES // 1000} KB).")
            try:
                return path.read_text(encoding="utf-8"), relative
            except (OSError, UnicodeDecodeError):
                return None, relative
    return None, f"src/{name}"


def _chart(project_dir: Path, relative: str, number: int) -> Chart | None:
    from PIL import Image

    root = Path(project_dir).resolve()
    path = (root / relative)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if path.is_symlink() or not resolved.is_file() or \
            resolved.stat().st_size > MAX_CHART_BYTES:
        return None
    try:
        with Image.open(resolved) as image:
            width, height = image.size
            dpi = image.info.get("dpi", (DEFAULT_DPI, DEFAULT_DPI))[0] or DEFAULT_DPI
    except Exception:  # noqa: BLE001 - whatever a broken picture raises, it is not a chart
        return None
    if width * height > MAX_CHART_PIXELS or width < 1 or height < 1:
        return None
    return Chart(relative, (width, height), float(dpi), number)


def choose_charts(drawn: Sequence[str], layout: Layout) -> tuple[list[str], list[str]]:
    """The charts in the report, in order, and what to say about the ones that are not.

    ``drawn`` is in the order the analysis drew them. ``layout.charts`` may choose and
    order them by file name, with or without ``charts/`` and ``.png``.
    """
    if not layout.charts:
        return list(drawn), []
    by_name: dict[str, str] = {}
    for relative in drawn:
        path = Path(relative)
        for key in (relative, path.name, path.stem):
            by_name.setdefault(key.casefold(), relative)
    chosen, notes = [], []
    for name in layout.charts:
        found = by_name.get(name.casefold()) or by_name.get(Path(name).name.casefold())
        if found is None:
            notes.append(f"report.toml names {name}, which the analysis did not draw this "
                         f"time, so it is not in the report.")
        elif found not in chosen:
            chosen.append(found)
    return chosen, notes


def inputs_state(project_dir: Path, charts: Sequence[str]) -> tuple:
    """What a report is made from, as it is now: every file under ``src/``, ``assets/``
    and ``data/`` and the report's charts, by size and time changed. While this reads the
    same, the report on screen is still the project's -- the data folder included, which
    ``source_fingerprint`` leaves out and a report depends on."""
    root = Path(project_dir)
    entries = []
    found = [root / chart for chart in charts]
    for folder in ("src", "assets", "data"):
        if (root / folder).is_dir():
            found.extend(sorted((root / folder).rglob("*")))
    for path in found:
        if "__pycache__" in path.parts:
            continue
        try:
            if path.is_file():
                status = path.stat()
                entries.append((str(path.relative_to(root)), status.st_size,
                                status.st_mtime_ns))
        except (OSError, ValueError):
            continue
    return tuple(entries)


def build(project_dir: Path, project_name: str, charts: Sequence[str], *,
          today: date | None = None) -> Report:
    """Make the report. ``charts`` are project-relative, in the order they were drawn.

    Raises :class:`ReportError` when there is nothing of the child's to put in it.
    """
    from opennest.ui.theme import LIGHT

    project_dir = Path(project_dir)
    layout, notes, layout_text = read_layout(project_dir)
    style = Style(layout, LIGHT)
    words: list[tuple[str, str]] = []
    if layout_text:
        words.append((LAYOUT_FILE, layout_text))

    title = layout.title or project_name
    when = today or date.today()
    byline = f"{when:%B} {when.day}, {when.year}"
    if layout.author:
        byline = f"By {layout.author}  ·  {byline}"
    left_out = ""
    title, missing = printable(title)
    byline, missing_byline = printable(byline)
    left_out += missing + missing_byline

    chosen, chart_notes = choose_charts(charts, layout)
    notes.extend(chart_notes)
    loaded: list[Chart] = []
    for relative in chosen:
        chart = _chart(project_dir, relative, len(loaded) + 1)
        if chart is None:
            notes.append(f"{relative} could not be opened as a picture, so it is not in "
                         f"the report.")
        else:
            loaded.append(chart)

    chunks: list[Chunk] = _title_chunks(title or "Report", byline, style)
    included: list[str] = []
    untouched: list[str] = []
    for part in layout.order:
        if part == "charts":
            if not loaded:
                notes.append("The analysis drew no charts, so the report has none."
                             if not charts else "None of the charts could go in.")
                continue
            heading = _block_chunks(Block("heading", CHARTS_HEADING, level=1), style)
            heading[0].part = part
            chunks.extend(heading)
            for chart in loaded:
                chunks.append(_chart_chunk(chart, style))
                if chart.page_scale() < SMALL_CHART:
                    notes.append(f"{Path(chart.path).name} is taller than a page, so it is "
                                 f"printed at {chart.page_scale():.0%} of its size. Drawn "
                                 f"as several charts, it would print bigger.")
            included.append(part)
            continue
        name = SECTION_FILES[part]
        text, relative = _read_text(project_dir, name)
        if text is None:
            notes.append(f"There is no {name}, so the report has no {part}.")
            continue
        words.append((relative, text))
        clean, missing = printable(text)
        left_out += missing
        blocks = own_words(name, clean)
        if not blocks:
            untouched.append(name)
            continue
        part_chunks = [chunk for block in blocks for chunk in _block_chunks(block, style)]
        part_chunks[0].part = part
        chunks.extend(part_chunks)
        included.append(part)

    if untouched:
        one = len(untouched) == 1
        names = untouched[0] if one else f"{', '.join(untouched[:-1])} and {untouched[-1]}"
        notes.append(f"{names} {'still has' if one else 'still have'} only the starter's "
                     f"words in {'it' if one else 'them'}, so {'it is' if one else 'they are'} "
                     f"not in the report yet.")
    if not included:
        # Said from what happened, so it is true whatever report.toml left out.
        raise ReportError(" ".join(["There is nothing to put in a report yet.", *notes,
                                    "Run the analysis on some data, or write what you "
                                    "found in findings.md."]))
    if left_out:
        shown = " ".join(dict.fromkeys(left_out))
        notes.append(f"The report leaves out {shown}, which Open Nest cannot print.")

    pages = paginate(chunks)
    starts, placements = [], []
    for number, page in enumerate(pages, start=1):
        for placed in page:
            if placed.chunk.part:
                starts.append((placed.chunk.part, number))
            if placed.chunk.chart is not None:
                placements.append((placed.chunk.chart.path, number, round(placed.scale, 3)))
    # No author unless the child put their name in report.toml: a PDF goes to other
    # people, and the child's name is theirs to add.
    metadata = {"Title": title or "Report", "Creator": "Open Nest"}
    if layout.author:
        metadata["Author"] = layout.author
    pdf = _draw(pages, title or "Report", LIGHT, project_dir, metadata)
    return Report(pdf=pdf, pages=len(pages), title=title or "Report",
                  charts=tuple(chart.path for chart in loaded), sections=tuple(included),
                  notes=tuple(notes), words=tuple(words), starts=tuple(starts),
                  placements=tuple(placements))
