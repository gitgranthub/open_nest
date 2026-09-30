"""The shipped recipes: data, one file each, under ``opennest/recipes/<profile>/``.

A recipe is a known pattern and what it takes to apply it -- not a block of code to paste.
Each one says:

- which **intent** it answers, and the one line the classifier is shown for it
- which **facts** the project must have for the deterministic operation to apply
  ("there is a player speed constant"), because a recipe written for the starter's shape
  must step aside once the child's code has moved away from it
- the **operation** that makes the change, or none, for a recipe that only guides
- the **guide**: the strategy, in words Gary can act on, when Gary is the one writing it
- how it is **verified**, and what is **reported** once it has been
- optionally, **words the child must have used** -- only for a recipe the classifier was
  measured confusing with something it is not. A veto, never a trigger: missing words
  send the message to Gary; present words make nothing more likely

Validated strictly when loaded, the way ``models.catalog`` is: an unknown key is an
error, not a silently ignored typo, because a recipe that quietly lost its ``verify``
list would report success on nothing. Which operations and checks exist is code; a test
cross-checks every recipe against them (``tests/test_fastpath.py``).

Each profile directory also has an ``index.json``: what the child is building, in the
words the classifier is given, the description of "other", and the order the options
are listed in. The order is data rather than a sort, because it decides which letter
each option gets and the classifier's orderings are defined relative to it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from opennest import paths
from opennest.fastpath.classifier import OTHER, Option

RECIPE_KEYS = frozenset({
    "id", "intent", "describe", "requires", "op", "params", "guide", "guide_scene",
    "verify", "report", "teach", "whole", "attachment_confirms", "attachment_covers",
    "needs_words", "not_words", "_note",
})
INDEX_KEYS = frozenset({"profile", "building", "other", "order", "_note"})


def guide_for(recipe: Recipe, tools) -> str:
    """The recipe's strategy for a project with these tools."""
    return recipe.guide_scene if recipe.guide_scene and "game_object" in tools else \
        recipe.guide


class RecipeError(Exception):
    """A shipped recipe file is malformed. A packaging defect, never a child's problem."""


@dataclass(frozen=True)
class Recipe:
    id: str
    profile: str
    intent: str
    #: The one line the classifier sees for this option.
    describe: str
    #: Facts the deterministic operation needs. Empty for a guide-only recipe.
    requires: tuple[str, ...] = ()
    #: The operation in ``fastpath.kinds.<profile>.OPS``, or None to guide only.
    op: str | None = None
    params: dict = field(default_factory=dict)
    #: The strategy, for Gary, when Gary writes the change.
    guide: str = ""
    #: The same strategy for a project that has the graphics layer's game_object tool
    #: (Phase 13C): things to see are made with it, not with drawing code. Empty when the
    #: guide does not depend on it.
    guide_scene: str = ""
    #: Checks in ``fastpath.verifier`` that must pass before success is reported.
    verify: tuple[str, ...] = ()
    #: What the child is told, from values the operation measured. ``$name`` fields.
    #: Several phrasings of the same facts, one chosen per change, so Gary does not say
    #: the identical sentence every time the same kind of change is made.
    report: tuple[str, ...] = ()
    #: One more sentence for "Build it and teach me".
    teach: str = ""
    #: A whole-game recipe: several parts by design, so the "exactly one change?" gate
    #: does not apply -- measured, it stopped both of Phase 12's whole-game asks. It is
    #: held to near-certainty instead (router.WHOLE_MIN_SCORE).
    whole: bool = False
    #: A picture recipe: an image attached to *this* message is itself the evidence that
    #: this is the change meant, so with the intent certain the gate is not asked. Only
    #: ever an attachment, which is a fact -- never a file that merely exists.
    attachment_confirms: bool = False
    #: Other intents that, with a picture attached to the message, mean this same
    #: capability -- "make my eagle look like this" is the player's look *and* a picture.
    attachment_covers: tuple[str, ...] = ()
    #: A regular expression the message -- or the one before it -- must match before
    #: this recipe is taken at all. Empty for almost every recipe.
    needs_words: str = ""
    #: A regular expression that, matched in *this* message, means the recipe is not
    #: what was asked -- it would do one small part of it and drop the rest. Empty for
    #: almost every recipe.
    not_words: str = ""

    @property
    def deterministic(self) -> bool:
        return self.op is not None

    def mentioned(self, request: str, previous: str | None = None) -> bool:
        """Whether the child's own words say what this recipe is about.

        The message before counts ("show me that on a chart" after "which plant grew the
        most?") -- except for a whole game, which must be asked for in this message:
        measured, "make this the player" straight after "i want a game where..." was read
        as a whole new game at 1.00, and would have been built over the child's work.
        """
        if self.not_words and re.search(self.not_words, request, re.IGNORECASE):
            return False
        if not self.needs_words:
            return True
        text = request if self.whole else f"{previous or ''}\n{request}"
        return re.search(self.needs_words, text, re.IGNORECASE) is not None


@dataclass(frozen=True)
class ProfileRecipes:
    profile: str
    building: str
    other: str
    recipes: tuple[Recipe, ...]

    def options(self) -> list[Option]:
        """The classifier's options, in index order, ending with "other"."""
        return [Option(r.intent, r.describe) for r in self.recipes] + [
            Option(OTHER, self.other)
        ]

    def for_intent(self, intent: str) -> Recipe | None:
        return next((r for r in self.recipes if r.intent == intent), None)


def recipes_dir() -> Path:
    return paths.package_root() / "recipes"


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecipeError(f"{path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise RecipeError(f"{path.name}: not an object")
    return data


def _text(value, name: str, path: Path) -> str:
    """A string, or a list of lines joined -- JSON has no multi-line strings."""
    if isinstance(value, list) and all(isinstance(line, str) for line in value):
        return "\n".join(value)
    if isinstance(value, str):
        return value
    raise RecipeError(f"{path.name}: {name} must be text or a list of lines")


def _pattern(raw: dict, key: str, path: Path) -> str:
    """``needs_words`` or ``not_words``: one pattern, or a list of alternatives."""
    words = raw.get(key, "")
    if isinstance(words, list) and all(isinstance(w, str) and w for w in words):
        # One alternative per line, so each can carry its own reason in review.
        words = "|".join(f"(?:{word})" for word in words)
    if not isinstance(words, str):
        raise RecipeError(f"{path.name}: {key} must be a pattern or a list of them")
    try:
        re.compile(words)
    except re.error as exc:
        raise RecipeError(f"{path.name}: {key} is not a pattern: {exc}") from exc
    return words


def _phrasings(value, path: Path) -> tuple[str, ...]:
    """A report is one phrasing or a list of alternatives -- never lines to be joined."""
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list) and value and all(isinstance(v, str) and v for v in value):
        return tuple(value)
    raise RecipeError(f"{path.name}: report must be text or a list of phrasings")


def _recipe(path: Path, profile: str) -> Recipe:
    raw = _read(path)
    unknown = set(raw) - RECIPE_KEYS
    if unknown:
        raise RecipeError(f"{path.name}: unknown keys {sorted(unknown)}")
    for key in ("id", "intent", "describe"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise RecipeError(f"{path.name}: {key} is required")
    if raw["intent"] == OTHER:
        raise RecipeError(f"{path.name}: '{OTHER}' is reserved for the fallback")
    op = raw.get("op")
    if op is not None and not isinstance(op, str):
        raise RecipeError(f"{path.name}: op must be a name or null")
    verify = tuple(raw.get("verify", ()))
    if op is not None and not verify:
        # Every fast-path action needs a verification plan. A deterministic recipe with
        # nothing to check would report success because an edit was applied.
        raise RecipeError(f"{path.name}: a recipe with an operation must say how it is verified")
    if op is not None and not raw.get("report"):
        raise RecipeError(f"{path.name}: a recipe with an operation must say what it reports")
    if not raw.get("guide"):
        raise RecipeError(f"{path.name}: every recipe needs a guide for when Gary writes it")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        raise RecipeError(f"{path.name}: params must be an object")
    needs_words = _pattern(raw, "needs_words", path)
    not_words = _pattern(raw, "not_words", path)
    return Recipe(
        id=raw["id"],
        profile=profile,
        intent=raw["intent"],
        describe=raw["describe"].strip(),
        requires=tuple(raw.get("requires", ())),
        op=op,
        params=params,
        guide=_text(raw["guide"], "guide", path),
        guide_scene=_text(raw.get("guide_scene", ""), "guide_scene", path),
        verify=verify,
        report=_phrasings(raw.get("report", ""), path),
        teach=_text(raw.get("teach", ""), "teach", path),
        whole=bool(raw.get("whole", False)),
        attachment_confirms=bool(raw.get("attachment_confirms", False)),
        attachment_covers=tuple(raw.get("attachment_covers", ())),
        needs_words=needs_words,
        not_words=not_words,
    )


def load_profile(profile: str, root: Path | None = None) -> ProfileRecipes | None:
    """The recipes for one profile, or None when the profile has none."""
    directory = (root or recipes_dir()) / profile
    index_path = directory / "index.json"
    if not index_path.is_file():
        return None
    index = _read(index_path)
    unknown = set(index) - INDEX_KEYS
    if unknown:
        raise RecipeError(f"{profile}/index.json: unknown keys {sorted(unknown)}")
    if index.get("profile") != profile:
        raise RecipeError(f"{profile}/index.json: profile must be {profile!r}")

    found = {}
    for path in sorted(directory.glob("*.json")):
        if path.name == "index.json":
            continue
        recipe = _recipe(path, profile)
        if recipe.id in found:
            raise RecipeError(f"{profile}: duplicate recipe id {recipe.id}")
        found[recipe.id] = recipe

    order = index.get("order", [])
    if sorted(order) != sorted(found) or len(set(order)) != len(order):
        raise RecipeError(
            f"{profile}/index.json: order must list every recipe exactly once "
            f"(missing {sorted(set(found) - set(order))}, "
            f"unknown {sorted(set(order) - set(found))})"
        )
    recipes = tuple(found[recipe_id] for recipe_id in order)
    intents = [r.intent for r in recipes]
    if len(set(intents)) != len(intents):
        raise RecipeError(f"{profile}: two recipes answer the same intent")
    for recipe in recipes:
        unknown_covers = set(recipe.attachment_covers) - set(intents)
        if unknown_covers:
            raise RecipeError(f"{recipe.id}: attachment_covers names no recipe: "
                              f"{sorted(unknown_covers)}")
    # One letter per option, and "other" takes one.
    if len(recipes) + 1 > 26:
        raise RecipeError(f"{profile}: more options than letters")
    return ProfileRecipes(
        profile=profile,
        building=str(index.get("building", "")).strip(),
        other=str(index.get("other", "")).strip(),
        recipes=recipes,
    )


class RecipeRegistry:
    """Every profile's recipes, loaded once."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or recipes_dir()
        self._profiles: dict[str, ProfileRecipes | None] = {}

    def for_profile(self, profile: str) -> ProfileRecipes | None:
        if profile not in self._profiles:
            self._profiles[profile] = load_profile(profile, self.root)
        return self._profiles[profile]

    def profiles(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if (p / "index.json").is_file())
