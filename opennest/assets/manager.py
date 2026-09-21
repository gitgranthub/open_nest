"""Bringing a child's own files into a project, and telling the model about them.

WORKORDER_01 sections 10-13.

COPY-IN, ALWAYS
---------------
Section 11: "Do not depend on the original location of a user's file after import."
An imported file is *copied* into the project and belongs to it from that moment. The
child can move, rename or delete the original, empty the Downloads folder, or unplug the
drive it came from, and the project still runs. Nothing anywhere stores the source path.

NOT A TOOL
----------
Section 18 lists ``list_assets()`` and ``read_text_asset()`` among the candidate tools.
Neither is built, for the reason ``list_project_files`` is not built (SPIKES.md section
4): a fifth tool cost 19 points of tool-selection accuracy, and the dominant failure was
the model reaching for a lookup instead of acting. The application knows what has been
imported, so it says so in the prompt -- the same treatment the file list gets, and the
same treatment Phase 4 gave memory retrieval. ``read_text_asset`` needs no replacement
at all: an imported CSV is a file in the project and ``read_file`` already reads it.

So the tool set stays four wide, and :func:`context_block` is how an asset reaches the
model.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from opennest.ai import provider as provider_module
from opennest.ai.provider import ModelInfo
from opennest.assets import describe, kinds
from opennest.projects.manager import Project
from opennest.security.sandbox import PathNotAllowed, resolve_in_project
from opennest.versioning.autosave import atomic_write_bytes

#: Everything section 10 describes is small. This cap exists so a mis-drop -- a video, a
#: disk image -- fails with a sentence rather than by copying gigabytes into a project
#: that is also a Git repository.
MAX_IMPORT_BYTES = 25_000_000

#: Assets named in the prompt. Generous, but bounded: the block is rebuilt every turn.
MAX_LISTED = 40

#: Characters that are awkward in a filename on macOS or in a shell. Matches the rule
#: :mod:`opennest.projects.manager` applies to project names.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class AssetError(Exception):
    """An import was refused, phrased for the child to read."""


@dataclass(frozen=True)
class Asset:
    """One file the child has added to the project."""

    #: Project-relative, e.g. ``assets/spaceship.png``. The only location that matters.
    path: str
    kind: str
    role: str
    #: Derived fact, never a claim about content. See :mod:`opennest.assets.describe`.
    summary: str
    #: Whether anything has actually read what is inside the file.
    readable: bool = True

    @property
    def name(self) -> str:
        return Path(self.path).name


# -- importing ---------------------------------------------------------------

def import_file(project: Project, source: Path, *, role: str | None = None) -> Asset:
    """Copy a file into the project and return what it became.

    ``role`` is section 12's classification. Left unset the application guesses from the
    file's kind; the child can pass a different one, which is the override section 12
    requires.
    """
    source = Path(source)
    if source.is_dir():
        raise AssetError(
            f"{source.name} is a folder. Add the files inside it instead."
        )
    if not source.is_file():
        raise AssetError(f"{source.name} could not be found.")

    size = source.stat().st_size
    if size > MAX_IMPORT_BYTES:
        raise AssetError(
            f"{source.name} is too big to add to a project "
            f"({size / 1_000_000:.0f} MB). The limit is {MAX_IMPORT_BYTES // 1_000_000} MB."
        )

    name = safe_name(source.name)
    head = _head(source)
    kind = kinds.classify(name, head)
    role = role if role in kinds.ROLES else kinds.default_role(kind)

    relative = _free_path(project, kinds.directory_for(role), name)
    try:
        destination = resolve_in_project(project.directory, relative, for_write=True)
    except PathNotAllowed as exc:
        # The destination is composed here rather than supplied, so this should be
        # unreachable -- it stays as the same single choke point every other write uses.
        raise AssetError(str(exc)) from exc

    atomic_write_bytes(destination, source.read_bytes())

    described = describe.describe(destination, kind)
    return Asset(
        path=relative,
        kind=kind,
        role=role,
        summary=described.summary,
        readable=described.readable,
    )


def safe_name(filename: str) -> str:
    """A filename that is safe to write into a project, or a refusal.

    Directory components are dropped: what is imported is a file, and a name carrying
    ``../`` is not a name.
    """
    cleaned = _UNSAFE.sub("", Path(filename).name).strip()
    if not cleaned or cleaned in (".", ".."):
        raise AssetError("That file's name cannot be used in a project.")
    if cleaned.startswith("."):
        # Hidden files are hidden from the child's file list too, so importing one
        # produces a file they cannot see. Several of them are also credential files.
        raise AssetError(
            f"{cleaned} is a hidden file, so it cannot be added to a project."
        )
    return cleaned[:120]


def _free_path(project: Project, directory: str, name: str) -> str:
    """A project-relative path in ``directory`` that nothing occupies yet.

    Importing never overwrites. ``write_file`` refuses to overwrite for the same reason
    (Phase 2): silently replacing something a child is relying on is a worse outcome
    than a second file with an obvious name.
    """
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate = name
    counter = 2
    while (project.directory / directory / candidate).exists():
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    return f"{directory}/{candidate}"


def _head(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            return stream.read(64)
    except OSError:
        return b""


# -- listing -----------------------------------------------------------------

def list_assets(project: Project) -> list[Asset]:
    """Everything the child has added, described from what is on disk right now.

    Derived live rather than recorded at import time, for the reason
    ``project_bible.refresh_facts`` rebuilds its sections from disk: a stored description
    can drift from the file it describes, and a file header costs microseconds to read.
    """
    by_directory = {kinds.directory_for(role): role for role in kinds.ROLES}
    found: list[Asset] = []
    for directory in kinds.LIBRARY_DIRECTORIES:
        role = by_directory.get(directory, kinds.REFERENCE)
        root = project.directory / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if len(found) >= MAX_LISTED:
                return found
            if not path.is_file() or path.name.startswith("."):
                continue
            described = describe.describe(path)
            found.append(
                Asset(
                    path=str(path.relative_to(project.directory)),
                    kind=described.kind,
                    role=role,
                    summary=described.summary,
                    readable=described.readable,
                )
            )
    return found


# -- what the model is told --------------------------------------------------

def can_interpret(asset: Asset, model: ModelInfo | None) -> bool:
    """Whether anything in this configuration can actually read the file's contents.

    Text is readable by definition -- the model calls ``read_file``. A picture depends
    on the model, which is section 13's ``model.supports_images`` and is why this is a
    lookup rather than a constant: adding a vision model to ``models.json`` is a data
    edit, and an image stops being unreadable the moment one is in use.

    A PDF or a sound file is unreadable here for a different reason -- Open Nest has no
    way to extract either, so no model can be offered one.

    **A vision model is not enough on its own.** ``supports_images`` says the model
    could see a picture if it were given one; ``IMAGE_INPUT_IMPLEMENTED`` says whether
    Open Nest actually sends any. Until both are true the honest answer is no, and the
    second one is currently False -- see the note on that constant for what went wrong
    when only the first was checked.
    """
    if asset.readable:
        return True
    if asset.kind == kinds.IMAGE:
        if not provider_module.IMAGE_INPUT_IMPLEMENTED:
            return False
        return bool(model is not None and model.supports_images)
    return False


def context_block(
    project: Project,
    model: ModelInfo | None = None,
    attached: Sequence[Asset] = (),
) -> str:
    """The assets half of the prompt: what exists, what was just attached, what is unread.

    Empty when the project has no assets, so an ordinary project's prompt is unchanged.
    """
    assets = list_assets(project)
    if not assets:
        return ""

    lines = [
        "FILES THEY HAVE ADDED TO THIS PROJECT",
        "These are real files in the project. Use them from these paths.",
    ]
    lines.extend(f"- {asset.path} -- {asset.summary}" for asset in assets)

    attached_paths = [asset.path for asset in attached]
    if attached_paths:
        lines.append("")
        lines.append(
            "They attached this to the message you are answering: "
            + ", ".join(attached_paths)
        )

    unreadable = [a for a in assets if not can_interpret(a, model)]
    if unreadable:
        lines.append("")
        lines.append("NOBODY HAS LOOKED INSIDE THESE FILES")
        lines.extend(f"  {asset.path}" for asset in unreadable)
        lines.append(
            "You have not seen what is in these. Never describe one and never guess: a "
            "file's name is not a description of its contents. If they tell you what one "
            "is, believe them and use it. If it matters and they have not said, ask. "
            "What you do know is listed above -- the kind of file, its size, and where "
            "it is -- and that is enough to use them from those paths."
        )
    return "\n".join(lines)


# -- catching the model describing what it cannot see ------------------------
#
# Measured, not assumed. SPIKES.md section 10 ran the shipped prompt against the real
# model with a deliberately suggestive filename. The honesty block fixed the useful half
# -- the model now answers "how big is my picture?" from the facts it was given instead
# of trying to read a PNG as text -- but it did not stop invention. Asked "does the
# dragon in my picture have wings?", the model answered "Yes, the dragon in the picture
# has wings. I see them clearly."
#
# So the prompt is necessary and not sufficient, and this is the Phase 2 pattern applied
# to the measured failure: the application checks rather than trusts.
#
# Two signals, both narrow on purpose:

#: A first-person claim to have *looked*. A model that was never given pixels saying "I
#: see them" is wrong no matter what the child called the file -- the same unambiguous
#: shape as "I increased" in the change check. The trailing clause keeps it away from
#: "I see what you mean" and from "I can see that from its file name".
_CLAIMS_SIGHT = re.compile(
    r"\b(?:i (?:can |could )?see|i'?ve seen|i have seen|i looked at|looking at)\b"
    r"[^.!?]{0,40}?"
    r"(?:\b(?:image|picture|png|jpe?g|photo|drawing|sprite|them)\b|\bit\b(?!['’]))",
    re.I,
)

#: Filename words that carry no content, so using one is never invention.
#:
#: Two kinds, and the first kind is the one that matters. ``red-dragon-with-wings``
#: yields "with", and a reply containing the word "with" is not evidence of anything --
#: an accusation triggered by an English function word would be worse than the failure
#: it guards against. Ordinary words come first, filename noise second.
_EMPTY_NAME_WORDS = frozenset({
    # Function words that turn up in filenames and everywhere else.
    "the", "and", "but", "for", "with", "without", "from", "into", "onto", "over",
    "under", "that", "this", "these", "those", "not", "all", "any", "one", "two",
    "out", "its", "his", "her", "our", "your", "their", "mine", "then", "than",
    "when", "what", "who", "how", "why", "are", "was", "were", "has", "had", "have",
    "can", "will", "just", "some", "more", "most", "very", "really", "here", "there",
    # Filename noise: says nothing about what is in the file.
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "img", "image", "images", "pic",
    "picture", "pictures", "photo", "photos", "file", "files", "copy", "final",
    "new", "old", "screenshot", "untitled", "download", "version", "draft", "edit",
    "edited", "test", "temp", "asset", "assets", "sample", "example", "export",
    "output", "scan", "doc", "data",
})


def invented_description(
    reply: str, said: str, unread: Sequence[Asset]
) -> str | None:
    """The file the reply describes without having seen it, or ``None``.

    Deliberately narrow, because a false accusation mid-conversation is worse than the
    failure it guards against. Three things are explicitly *not* invention:

    - **Naming the file.** "I can't describe what's in red-dragon.png" is the right
      answer. Literal mentions are removed before anything is looked for.
    - **Repeating the child.** The context block tells the model to believe them when
      they say what a file is, so a word the child used is theirs, not invented.
    - **Anything about a file that was actually read.** Only ``unread`` is considered.
    """
    if not unread:
        return None

    # Only genuine file references are removed: the path, the filename, and the bare
    # stem with its separators intact. Deliberately NOT the de-hyphenated form -- for
    # red-dragon-with-wings.png that is the prose "red dragon with wings", which is the
    # invention itself, not a reference to the file.
    cleaned = reply
    for asset in unread:
        for literal in (asset.path, asset.name, Path(asset.path).stem):
            if literal:
                cleaned = re.sub(re.escape(literal), " ", cleaned, flags=re.I)

    if _CLAIMS_SIGHT.search(cleaned):
        return unread[0].path

    said_words = set(re.findall(r"[a-z]+", said.lower()))
    lowered = cleaned.lower()
    for asset in unread:
        for word in _name_words(asset):
            if word not in said_words and re.search(rf"\b{re.escape(word)}\b", lowered):
                return asset.path
    return None


def _name_words(asset: Asset) -> set[str]:
    """Content words a filename offers up, e.g. red-dragon-with-wings -> red, dragon."""
    stem = Path(asset.path).stem.lower()
    return {
        word for word in re.split(r"[^a-z]+", stem)
        if len(word) > 2 and word not in _EMPTY_NAME_WORDS
    }


def unread_assets(project: Project, model: ModelInfo | None) -> list[Asset]:
    """Imported files nothing has looked inside, for this model."""
    return [a for a in list_assets(project) if not can_interpret(a, model)]


# -- what the child is told --------------------------------------------------

def import_message(
    asset: Asset,
    model: ModelInfo | None = None,
    alternatives: Sequence[ModelInfo] = (),
) -> str:
    """What to say after an import. Section 13: tell the user clearly, and offer a model.

    ``alternatives`` are models that *can* read this kind of file and are usable now --
    see :func:`opennest.ai.router.models_that_can_read`. When there are none, the message
    is the limitation on its own rather than a suggestion the child cannot act on.
    """
    lines = [f"{asset.name} is in your project."]
    if can_interpret(asset, model):
        return lines[0]

    lines.append("")
    if asset.kind == kinds.IMAGE:
        who = model.name if model else "This AI"
        lines.append(
            f"{who} cannot see pictures, so it will not know what this one shows. It "
            f"does know where the file is and what size it is ({asset.summary}), so it "
            f"can still use it in your project."
        )
    else:
        lines.append(
            f"Open Nest cannot read what is inside this kind of file, so the assistant "
            f"will not know what {asset.name} says."
        )

    if alternatives:
        capable = alternatives[0]
        lines.append("")
        lines.append(f"{capable.name} can read it. You can choose it for this project.")
    return "\n".join(lines)
