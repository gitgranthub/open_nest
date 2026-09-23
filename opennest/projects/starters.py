"""Starter kits: the known-good files a project can begin from.

A starter kit is a directory of real files shipped with Open Nest, described by a
``starter.json`` manifest beside them. Applying one copies those files into a project's
``src/`` and records in the manifest which kit it was and at what version.

Three things about this are deliberate.

**A starter is files on disk, never something a model generates.** Asking the model to
write the foundation every time would make the first thing a child sees depend on the
network, the provider, the temperature and the day. A starter is the same every time,
works offline, costs nothing, and can be tested. What Gary is for is changing it
afterwards, and once it has been copied those are the child's files -- nothing here is
protected boilerplate.

**A starter is optional, and "empty" has to really be empty.** Every profile may offer
one or more kits and every profile can also be started with nothing at all. Before Phase
11 a template was applied unconditionally, so there was no way to begin from a blank
directory; a profile now declares a default (``starter_default``) and the child can
always choose otherwise.

**Applying one never overwrites work.** :func:`apply` refuses if any file it would write
already exists, so the one-click "add a starter later" offer cannot destroy what a child
has already made. The refusal is the mechanism, not a dialog somewhere above it.

This replaces the Phase 0 ``starter_template`` field, which named a directory and nothing
else. The directory moved from ``projects/templates/`` to ``projects/starters/`` when it
gained a manifest.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from opennest import paths

MANIFEST_NAME = "starter.json"

#: Keys every manifest must carry. Anything else is ignored, so a manifest may be
#: annotated with ``_note`` fields the way the rest of the configuration is.
REQUIRED_FIELDS = ("id", "profile", "name", "description", "entry_point", "version")


class StarterError(Exception):
    """A starter kit could not be read or applied, in plain language."""


@dataclass(frozen=True)
class Starter:
    """One kit, as its manifest describes it."""

    id: str
    profile: str
    name: str
    description: str
    #: The file a child should look at first. Must match the profile's entrypoint, so
    #: that ``src/<entry_point>`` is what the run or preview action targets.
    entry_point: str
    #: Bumped when the shipped files change. Recorded in the project manifest so Gary
    #: is told which foundation a project actually has, rather than guessing from
    #: filenames.
    version: int
    #: Every file this kit writes, relative to the project's ``src/``. Declared rather
    #: than discovered: a kit that quietly gains a file is a kit whose tests no longer
    #: describe it.
    files: tuple[str, ...]
    #: Directories to create even though they hold no shipped file -- a website's
    #: ``assets/`` is a place to put things, and an empty directory cannot be committed.
    directories: tuple[str, ...]
    directory: Path


def starters_root() -> Path:
    return paths.package_root() / "projects" / "starters"


def _read_manifest(directory: Path) -> Starter:
    manifest = directory / MANIFEST_NAME
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StarterError(f"The starter in {directory.name} has no {MANIFEST_NAME}.") from exc
    except json.JSONDecodeError as exc:
        raise StarterError(f"The starter in {directory.name} has a damaged manifest.") from exc
    if not isinstance(raw, dict):
        raise StarterError(f"The starter in {directory.name} has a damaged manifest.")

    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise StarterError(
            f"The starter in {directory.name} is missing {', '.join(sorted(missing))}."
        )
    try:
        version = int(raw["version"])
    except (TypeError, ValueError) as exc:
        raise StarterError(f"The starter in {directory.name} has a damaged version.") from exc

    return Starter(
        id=str(raw["id"]),
        profile=str(raw["profile"]),
        name=str(raw["name"]),
        description=str(raw["description"]),
        entry_point=str(raw["entry_point"]),
        version=version,
        files=tuple(str(name) for name in raw.get("files", ())),
        directories=tuple(str(name) for name in raw.get("directories", ())),
        directory=directory,
    )


@lru_cache(maxsize=1)
def load_starters(root: Path | None = None) -> tuple[Starter, ...]:
    """Every kit installed with this copy of Open Nest, by directory name."""
    base = Path(root) if root is not None else starters_root()
    if not base.is_dir():
        return ()
    found = []
    for directory in sorted(base.iterdir()):
        if directory.is_dir() and (directory / MANIFEST_NAME).is_file():
            found.append(_read_manifest(directory))
    return tuple(found)


def get_starter(starter_id: str) -> Starter:
    for starter in load_starters():
        if starter.id == starter_id:
            return starter
    known = ", ".join(s.id for s in load_starters()) or "none"
    raise StarterError(
        f"Open Nest is missing the starter files for {starter_id!r}. This is a problem "
        f"with the installation, not with anything you did. (Installed: {known}.)"
    )


def starters_for(profile) -> tuple[Starter, ...]:
    """The kits a profile offers, in the order it lists them."""
    return tuple(get_starter(starter_id) for starter_id in profile.starters)


def default_starter(profile) -> Starter | None:
    """What this profile begins with when nobody chooses.

    ``None`` means empty, which is what Blank uses: section 7 of the Phase 11 work order
    asks that starting there stay genuinely blank. It is data on the profile rather than
    a branch here, so a profile that changes its mind changes ``profiles.json``.
    """
    if profile.starter_default is None:
        return None
    return get_starter(profile.starter_default)


# --------------------------------------------------------------------------- applying

def source_files(starter: Starter) -> tuple[Path, ...]:
    """Where each declared file actually lives. Raises if one is not installed."""
    resolved = []
    for name in starter.files:
        path = starter.directory / name
        if not path.is_file():
            raise StarterError(
                f"The {starter.name} starter is missing {name}. This is a problem with "
                f"the installation, not with anything you did."
            )
        resolved.append(path)
    return tuple(resolved)


def would_overwrite(starter: Starter, destination: Path) -> tuple[str, ...]:
    """Which of this kit's files already exist at the destination.

    Non-empty means :func:`apply` will refuse. Offering a one-click starter that
    silently replaced a child's work would be the worst bug in the product, so the
    check is here rather than in whichever button happens to call it.
    """
    destination = Path(destination)
    return tuple(name for name in starter.files if (destination / name).exists())


def apply(starter: Starter, destination: Path) -> tuple[str, ...]:
    """Copy one kit into a project's ``src/``. Returns the files written.

    Never overwrites. ``starter.json`` itself is not copied -- it describes the kit to
    Open Nest, and a child opening their project should see the files they were given
    and nothing about how they arrived.
    """
    destination = Path(destination)
    clash = would_overwrite(starter, destination)
    if clash:
        raise StarterError(
            f"There is already a {clash[0]} in this project, so the {starter.name} "
            f"starter was not added. Ask {_assistant()} to help instead."
        )

    sources = source_files(starter)
    destination.mkdir(parents=True, exist_ok=True)
    for name in starter.directories:
        (destination / name).mkdir(parents=True, exist_ok=True)
    for name, source in zip(starter.files, sources):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # copyfile rather than copy2: the shipped file's mode and timestamps belong to
        # the installation, and a child's new file should look new.
        shutil.copyfile(source, target)
    return starter.files


def _assistant() -> str:
    from opennest import ASSISTANT_NAME

    return ASSISTANT_NAME


# --------------------------------------------------------------------------- state

def has_own_files(source_dir: Path) -> bool:
    """Whether a project's ``src/`` holds anything a child would call their work.

    Used to decide whether the "add a starter" offer is safe to show. Deliberately
    generous about what counts: a dotfile or a ``__pycache__`` is not work, and anything
    else is.
    """
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return False
    for entry in source_dir.rglob("*"):
        if entry.name.startswith("."):
            continue
        if "__pycache__" in entry.parts:
            continue
        if entry.is_file():
            return True
    return False
