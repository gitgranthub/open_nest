"""Per project type: what Open Nest can read about the code, and the small changes it makes.

Each module here (``games``, ``website``, ``research``, ``arduino``, ``raspberry_pi``)
provides the same three things:

- ``facts(project, attachments)`` -- deterministic facts about the project's files, read
  with a parser, never asked of a model: where the game loop is, what the speed
  constant is called, which columns the CSV has, which pins the sketch uses.
- ``OPS`` -- the operations a recipe may name. Each takes a :class:`Context` and
  returns a :class:`Change` (the new text of each file it touches, and the values the
  report will state), or raises :class:`NotApplicable` when this project is not the shape
  the operation was written for.
- ``CHECKS`` -- what can be verified about this kind of project afterwards.
- ``verifiable(project)`` -- whether this project can run the check those recipes
  depend on (a playtest, a run, a compile). A recipe only makes a change itself where
  it can; anywhere else -- a game written into a Blank project, which has no headless
  test -- it becomes guidance for Gary.

An operation never writes a file. It returns text; the executor applies it through the
Toolbox, so every path check and syntax gate a model's edit meets, this meets too.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from opennest.fastpath.classifier import Classification, Option


class NotApplicable(Exception):
    """This project is not the shape the operation was written for. Gary takes over.

    The message is for the record and for Gary's guidance, never for the child.
    """


class NeedsAnswer(NotApplicable):
    """The change needs something only the child knows -- a pin, a picture.

    Not a failure of the recipe: it is the recipe knowing what must never be guessed.
    Gary asks.
    """


class AlreadyDone(NotApplicable):
    """The project is already exactly what was asked -- the asteroids already zigzag.

    Not a reason to step aside: handed to Gary, he edited code that was fine (the owner's
    first test drive). Open Nest says so itself, with nothing changed. The message *is*
    for the child, and is read from the file, never guessed.
    """


@dataclass
class Facts:
    """What is known about the project, by name. Absent means not found, never guessed."""

    values: dict[str, Any] = field(default_factory=dict)

    def has(self, name: str) -> bool:
        return self.values.get(name) is not None

    def get(self, name: str, default: Any = None) -> Any:
        value = self.values.get(name)
        return default if value is None else value

    def missing(self, names: Sequence[str]) -> list[str]:
        return [name for name in names if not self.has(name)]


#: Asks the model a closed question about one detail: (question, options, request).
Chooser = Callable[[str, Sequence[Option]], Classification | None]


@dataclass
class Context:
    project: Any
    facts: Facts
    request: str
    params: dict
    #: Closed questions to the model about a detail of the request. None when no model
    #: can answer, in which case an operation that needs one does not apply.
    choose: Chooser | None = None
    attachments: tuple = ()
    previous: str | None = None


@dataclass
class Change:
    """What an operation wants the files to become, and what it will say about it."""

    #: Relative path -> the complete new text. Only files that change.
    files: dict[str, str]
    #: Values for the recipe's report and teach templates.
    values: dict[str, str] = field(default_factory=dict)
    #: What verification should expect, in terms the checks understand.
    expect: dict[str, Any] = field(default_factory=dict)
    #: Tool calls to make instead of (or as well as) ``files``: ``(tool, arguments)``,
    #: dispatched through the Toolbox exactly as a model's call would be. Phase 13C: a
    #: recipe that changes a game's look calls ``game_object`` rather than writing the
    #: scene kit into the conversation as edits.
    calls: list[tuple[str, dict]] = field(default_factory=list)
    #: The files those calls may change, so they can be put back exactly.
    touches: tuple[str, ...] = ()


#: Below this share, or with any ordering disagreeing, a detail is treated as unknown.
SLOT_MIN_SCORE = 0.8


def confident(answer: Classification | None) -> str | None:
    """The chosen option's name when the model was sure of a detail, else None."""
    if answer is None or answer.agreement < 1.0 or answer.score < SLOT_MIN_SCORE:
        return None
    return answer.name


#: The project types the Fast Path understands, and the module for each.
KINDS = ("games", "website", "research", "arduino", "raspberry_pi")


def kind_for(profile: str | None):
    """The module for a profile, or None when the Fast Path has nothing for it."""
    if profile not in KINDS:
        return None
    import importlib

    return importlib.import_module(f"opennest.fastpath.kinds.{profile}")


# -- which family a project's files are -----------------------------------------------
#
# A project made as a Game, a Website and so on is that family by definition. A Blank
# ("Something Else") project has no family to begin with, and it gains one from what is
# actually in its files: an index.html makes it a website, a main.py that imports pygame
# makes it a game. Each sign looks at exactly the files that family's own facts read, so
# a family is offered only when its facts could find something -- and only that
# family's options are put to the classifier, never every recipe there is.

_IMPORT = re.compile(r"^\s*(?:import|from)\s+([\w.]+)", re.MULTILINE)


def _entry_imports(project) -> set[str]:
    """Top-level package names the project's entry file imports, anywhere in it."""
    try:
        text = project.entrypoint_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    return {name.split(".")[0] for name in _IMPORT.findall(text)}


def _has_data(project) -> bool:
    data = project.directory / "data"
    return data.is_dir() and any(data.glob("*.csv"))


def _has_sketch(project) -> bool:
    src = project.directory / "src"
    return src.is_dir() and any(src.rglob("*.ino"))


_SIGNS = (
    ("website", lambda p, imports: (p.directory / "src" / "index.html").is_file()),
    ("games", lambda p, imports: "pygame" in imports),
    ("research", lambda p, imports: "pandas" in imports and _has_data(p)),
    ("raspberry_pi", lambda p, imports: bool({"RPi", "gpiozero"} & imports)),
    ("arduino", lambda p, imports: _has_sketch(p)),
)


def family_for(project) -> tuple[str | None, str]:
    """Which family of recipes applies to this project, and why -- or None, and why not.

    Read from the files every time: a Blank project that gains an index.html this turn
    is a website on the next. Two families at once is not guessed between.
    """
    profile = project.profile.id
    if profile in KINDS:
        return profile, "the project type"
    if profile != "blank":
        return None, "no recipes for this kind of project"
    imports = _entry_imports(project)
    found = [name for name, sign in _SIGNS if sign(project, imports)]
    if len(found) == 1:
        return found[0], f"its files are a {found[0].replace('_', ' ')} project"
    if not found:
        return None, "nothing in its files says what kind of project it is yet"
    return None, f"its files look like more than one kind of project ({', '.join(found)})"
