"""What an imported file is, and where it belongs.

WORKORDER_01 section 12 asks the application to work out whether an upload is reference
material, a project asset, data, or source code -- and to let the child change that
answer. Section 11 fixes where each lands: a project owns ``src``, ``assets``, ``data``
and ``docs``, and an imported file is copied into one of them.

Two separate questions, deliberately kept apart:

**Kind** is what the file *is* -- an image, a table, some code. It is decided from the
file's own bytes where that is possible, because a child renaming ``photo.jpg`` to
``ship.png`` is entirely likely and the description must not claim a format the file does
not have. Kind decides how the file gets described (:mod:`opennest.assets.describe`).

**Role** is what the file is *for* -- section 12's four-way classification. It decides
which directory the file is copied into, and it is the part the child can override. The
same PNG is a sprite in a game and a reference photo in a Raspberry Pi project; nothing
in the bytes can tell them apart, so the application guesses and offers to be corrected.
"""

from __future__ import annotations

from pathlib import Path

# -- kinds -------------------------------------------------------------------
#
# These strings are the same vocabulary ``profiles.json`` uses for ``asset_types``, so a
# profile and an imported file describe a picture with the same word.

IMAGE = "image"
AUDIO = "audio"
DATA = "data"
CODE = "code"
DOCUMENT = "document"
OTHER = "other"

EXTENSIONS: dict[str, str] = {
    # Images (section 10)
    ".png": IMAGE, ".jpg": IMAGE, ".jpeg": IMAGE, ".webp": IMAGE, ".gif": IMAGE,
    ".bmp": IMAGE,
    # Sounds. Games use these; no other profile lists them.
    ".wav": AUDIO, ".mp3": AUDIO, ".ogg": AUDIO, ".aiff": AUDIO, ".aif": AUDIO,
    ".m4a": AUDIO, ".flac": AUDIO,
    # Data
    ".csv": DATA, ".tsv": DATA, ".json": DATA, ".jsonl": DATA, ".yaml": DATA,
    ".yml": DATA,
    # Code, including the configuration files section 10 groups with it
    ".py": CODE, ".js": CODE, ".ts": CODE, ".html": CODE, ".css": CODE, ".ino": CODE,
    ".c": CODE, ".cpp": CODE, ".h": CODE, ".sh": CODE, ".toml": CODE, ".ini": CODE,
    ".cfg": CODE,
    # Documents
    ".txt": DOCUMENT, ".md": DOCUMENT, ".pdf": DOCUMENT, ".rtf": DOCUMENT,
}

#: Leading bytes that identify an image regardless of what the file is called. Only
#: images are sniffed: getting an image's format wrong means describing a picture with
#: dimensions read out of the wrong header, which is the one mistake section 13 is about.
IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"BM", "BMP"),
)


def image_format(head: bytes) -> str | None:
    """The image format these bytes actually are, or None if they are not an image."""
    for signature, name in IMAGE_SIGNATURES:
        if head.startswith(signature):
            return name
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WebP"
    return None


def classify(filename: str, head: bytes = b"") -> str:
    """The kind of file this is. Bytes win over the name when they disagree."""
    if image_format(head) is not None:
        return IMAGE
    suffix = Path(filename).suffix.lower()
    kind = EXTENSIONS.get(suffix, OTHER)
    # An extension claiming to be an image that the bytes do not support is not one.
    # Saying "PNG image" about a text file would be exactly the invention section 13
    # forbids, so it degrades to a plain file rather than guessing.
    if kind == IMAGE and head and image_format(head) is None:
        return OTHER
    return kind


# -- roles -------------------------------------------------------------------
#
# Section 12's four classifications, with the child-facing wording DESIGN_DOC.md asks
# for. The work order's own labels are in the comments.

ASSET = "asset"          # "Project asset"
REFERENCE = "reference"  # "Reference material"
DATASET = "data"         # "Data"
SOURCE = "code"          # "Source code"

ROLES = (ASSET, DATASET, REFERENCE, SOURCE)

ROLE_LABELS: dict[str, str] = {
    ASSET: "Use it in the project",
    DATASET: "Data to work with",
    REFERENCE: "Something to look at",
    SOURCE: "Code",
}

#: Section 11: an imported file is copied into the project, into one of its directories.
ROLE_DIRECTORIES: dict[str, str] = {
    ASSET: "assets",
    DATASET: "data",
    REFERENCE: "docs",
    SOURCE: "src",
}

#: The directories that make up section 11's Asset Library -- everything an import can
#: land in except ``src``, which is the project's own code rather than something added
#: to it. One definition, shared by the asset listing and by ``project_bible``.
LIBRARY_DIRECTORIES: tuple[str, ...] = ("assets", "data", "docs")

_DEFAULT_ROLES: dict[str, str] = {
    IMAGE: ASSET,
    AUDIO: ASSET,
    DATA: DATASET,
    CODE: SOURCE,
    DOCUMENT: REFERENCE,
    OTHER: REFERENCE,
}


def default_role(kind: str) -> str:
    """The role to offer first. A picture is usually art; a PDF is usually to read.

    A guess, not a ruling -- an image can just as easily be a wiring photo. The child
    changes it in one click, which is why the guess is allowed to be this simple.
    """
    return _DEFAULT_ROLES.get(kind, REFERENCE)


def directory_for(role: str) -> str:
    return ROLE_DIRECTORIES.get(role, ROLE_DIRECTORIES[REFERENCE])
