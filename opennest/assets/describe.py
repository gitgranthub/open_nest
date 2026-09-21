"""What can honestly be said about an imported file.

WORKORDER_01 section 13:

    Models without native vision should receive derived text or metadata rather than
    pretending they saw the image.

This module is where "derived text or metadata" is given a definition, and the line it
draws is this: **the application may state facts about the file; it may never state
facts about the picture.**

A PNG header yields its real format, its pixel dimensions and whether it has an alpha
channel. Those are facts, they are checkable, and they are exactly what a model needs in
order to *use* the image -- the size to scale a sprite to, and whether to reach for
``convert_alpha``. What the image depicts is not in the header and is not derivable, so
nothing here says it. The filename is the child's word for the file, not evidence about
its contents.

Every description therefore carries :attr:`Description.readable`: whether anything has
actually read the file's contents. A CSV is readable -- the model can call ``read_file``
and see all of it. A PNG, a sound and a PDF are not, and the context block says so out
loud rather than letting a summary stand in for the thing.

Unknowns are reported as unknown. A WebP variant this module cannot parse yields a
description without dimensions, never an invented pair of numbers.

NO NEW DEPENDENCY
-----------------
Dimensions are read from file headers with :mod:`struct`, not with Pillow. Pillow is in
``requirements/projects.txt`` -- a package child *projects* may import -- not in the
application's own ``base.txt``, and adding an imaging library to the application to read
two integers out of a 33-byte header is not a trade worth making on a machine where every
dependency is licensing surface.
"""

from __future__ import annotations

import csv
import io
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from opennest.assets import kinds

#: Enough of a file to find its header in, for the overwhelmingly common case. Read on
#: every prompt build, so it is kept small.
HEAD_BYTES = 64 * 1024

#: A camera JPEG puts an EXIF thumbnail in front of the frame header, and several APP
#: segments of ~64 KB each will push it past :data:`HEAD_BYTES`. When the first read
#: yields no dimensions, one deeper read is tried before giving up -- the cost is paid
#: only by the files that need it, and "size could not be read" on an ordinary holiday
#: photo would be an honest answer to a question that has a real one.
DEEP_SCAN_BYTES = 4 * 1024 * 1024

#: Rows are counted by streaming, which is cheap, but not without limit: the context
#: block is rebuilt every turn and a very large table is not worth re-counting each time.
MAX_COUNTED_BYTES = 10_000_000

#: JSON is only parsed when it is small enough that doing so on every turn is free.
MAX_PARSED_JSON_BYTES = 2_000_000

#: JPEG start-of-frame markers, which carry the dimensions. 0xC4, 0xC8 and 0xCC are
#: Huffman/arithmetic tables that happen to fall in the same range and are not frames.
_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


@dataclass(frozen=True)
class Description:
    """One line of derived fact about a file, and whether anyone has read it."""

    kind: str
    #: Plain text, e.g. "PNG image, 64x64 pixels, has transparency". Never a claim about
    #: what the file depicts or means.
    summary: str
    #: True when the contents can be read as text -- by the model, with ``read_file``.
    #: False means nothing has seen inside this file, and the prompt must say so.
    readable: bool = True


@dataclass(frozen=True)
class ImageHeader:
    """What a file header gives up. ``None`` means "could not be determined"."""

    format: str
    width: int | None = None
    height: int | None = None
    has_alpha: bool | None = None


def describe(path: Path, kind: str | None = None) -> Description:
    """Derive what can be said about a file on disk."""
    path = Path(path)
    head = _head(path)
    kind = kind or kinds.classify(path.name, head)

    if kind == kinds.IMAGE:
        return Description(kind, _describe_image(path, head), readable=False)
    if kind == kinds.AUDIO:
        return Description(kind, f"a sound file ({_size(path)})", readable=False)
    if kind == kinds.DATA:
        return _describe_data(path)
    if kind == kinds.DOCUMENT:
        return _describe_document(path)
    if kind == kinds.CODE:
        return Description(kind, f"{path.suffix.lstrip('.') or 'source'} code, "
                                 f"{_line_count(path)}")
    return Description(kinds.OTHER, f"a file ({_size(path)})", readable=False)


# -- images ------------------------------------------------------------------

def _describe_image(path: Path, head: bytes) -> str:
    header = read_image_header(head)
    if header is None:
        return f"an image file ({_size(path)}), format not recognised"

    # A camera JPEG carries EXIF thumbnails in front of the frame header, and enough of
    # them push it past HEAD_BYTES. Rather than report a real photo's size as unknown,
    # try once more with a bigger read -- paid only by the files that need it.
    if header.width is None and path.stat().st_size > len(head):
        deeper = _head(path, DEEP_SCAN_BYTES)
        header = read_image_header(deeper) or header

    parts = [f"{header.format} image"]
    if header.width and header.height:
        parts.append(f"{header.width}x{header.height} pixels")
    else:
        # Said out loud, because a missing size is a fact the model should know rather
        # than a gap it might fill in.
        parts.append("size could not be read")
    if header.has_alpha is True:
        parts.append("has transparency")
    elif header.has_alpha is False:
        parts.append("no transparency")
    return ", ".join(parts)


def read_image_header(data: bytes) -> ImageHeader | None:
    """Format, dimensions and transparency from an image's leading bytes.

    Returns ``None`` when the bytes are not a recognised image. Any field that cannot be
    determined is left as ``None`` -- this function does not estimate.
    """
    name = kinds.image_format(data)
    if name is None:
        return None
    reader = {
        "PNG": _png, "JPEG": _jpeg, "GIF": _gif, "BMP": _bmp, "WebP": _webp,
    }[name]
    try:
        return reader(data)
    except (struct.error, IndexError, ValueError):
        # A truncated or malformed header is a fact about the file, not a crash.
        return ImageHeader(format=name)


def _png(data: bytes) -> ImageHeader:
    # IHDR is required to be the first chunk: length(4) "IHDR" width(4) height(4)
    # bit depth(1) colour type(1).
    if len(data) < 26 or data[12:16] != b"IHDR":
        return ImageHeader("PNG")
    width, height = struct.unpack(">II", data[16:24])
    colour_type = data[25]
    # 4 is greyscale+alpha and 6 is RGBA. A palette image (3) is transparent only if it
    # carries a tRNS chunk, which can sit anywhere before the pixel data.
    has_alpha = colour_type in (4, 6) or (colour_type == 3 and b"tRNS" in data)
    return ImageHeader("PNG", width, height, has_alpha)


def _jpeg(data: bytes) -> ImageHeader:
    # JPEG has no alpha channel at all, so that answer is known without parsing.
    index = 2
    limit = len(data)
    while index + 9 < limit:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        segment = struct.unpack(">H", data[index + 2:index + 4])[0]
        if marker in _SOF_MARKERS:
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return ImageHeader("JPEG", width, height, False)
        if segment < 2:
            break
        index += 2 + segment
    return ImageHeader("JPEG", has_alpha=False)


def _gif(data: bytes) -> ImageHeader:
    # Transparency is per-frame, in a Graphic Control Extension rather than the header,
    # so it is left unknown instead of guessed.
    width, height = struct.unpack("<HH", data[6:10])
    return ImageHeader("GIF", width, height)


def _bmp(data: bytes) -> ImageHeader:
    if len(data) < 26:
        return ImageHeader("BMP")
    width, height = struct.unpack("<ii", data[18:26])
    return ImageHeader("BMP", abs(width), abs(height))


def _webp(data: bytes) -> ImageHeader:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return ImageHeader("WebP", width, height, bool(data[20] & 0x10))
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return ImageHeader("WebP", width, height, bool((bits >> 28) & 1))
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return ImageHeader("WebP", width, height, False)
    return ImageHeader("WebP")


# -- tables and structured data ----------------------------------------------

def _describe_data(path: Path) -> Description:
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        return Description(kinds.DATA, _describe_table(path))
    if suffix in (".json", ".jsonl"):
        return Description(kinds.DATA, _describe_json(path))
    return Description(kinds.DATA, f"a data file ({_size(path)}, {_line_count(path)})")


def _describe_table(path: Path) -> str:
    """Column names and a row count -- what a question about a table starts from.

    The model can still ``read_file`` the whole thing. This exists because "which
    columns are in here" is the first thing it needs and the cheapest thing to provide.
    """
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
            reader = csv.reader(stream, delimiter=delimiter)
            header = next(reader, None)
            if header is None:
                return "an empty table"
            rows = sum(1 for _ in reader) if path.stat().st_size <= MAX_COUNTED_BYTES else None
    except OSError:
        return f"a table ({_size(path)})"

    columns = ", ".join(name.strip() for name in header if name.strip())
    counted = f"{rows} rows" if rows is not None else "too large to count rows"
    return f"a table with columns: {columns} ({counted})"


def _describe_json(path: Path) -> str:
    if path.suffix.lower() == ".jsonl":
        return f"one JSON record per line ({_line_count(path)})"
    if path.stat().st_size > MAX_PARSED_JSON_BYTES:
        return f"a JSON file ({_size(path)})"
    try:
        parsed = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return f"a JSON file ({_size(path)}), which could not be parsed"
    if isinstance(parsed, dict):
        keys = ", ".join(str(key) for key in list(parsed)[:12])
        return f"a JSON object with keys: {keys}" if keys else "an empty JSON object"
    if isinstance(parsed, list):
        return f"a JSON list of {len(parsed)} items"
    return f"a JSON file holding a single {type(parsed).__name__}"


# -- documents ---------------------------------------------------------------

def _describe_document(path: Path) -> Description:
    if path.suffix.lower() == ".pdf":
        # Open Nest has no PDF text extractor, and adding one is a dependency this phase
        # does not need. So a PDF is honestly an unread file: the block says nobody has
        # looked inside it, which is better than a page count standing in for content.
        return Description(kinds.DOCUMENT, f"a PDF document ({_size(path)})", readable=False)
    if path.suffix.lower() in (".rtf", ".doc", ".docx"):
        return Description(
            kinds.DOCUMENT, f"a word-processor document ({_size(path)})", readable=False
        )
    return Description(kinds.DOCUMENT, f"text, {_line_count(path)}")


# -- small shared pieces -----------------------------------------------------

def _head(path: Path, count: int = HEAD_BYTES) -> bytes:
    try:
        with path.open("rb") as stream:
            return stream.read(count)
    except OSError:
        return b""


def _size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "unknown size"
    for unit, step in (("MB", 1_000_000), ("KB", 1_000)):
        if size >= step:
            return f"{size / step:.1f} {unit}"
    return f"{size} bytes"


def _line_count(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_COUNTED_BYTES:
            return _size(path)
        with path.open("rb") as stream:
            lines = sum(1 for _ in io.TextIOWrapper(stream, encoding="utf-8", errors="replace"))
    except OSError:
        return _size(path)
    return "1 line" if lines == 1 else f"{lines} lines"
