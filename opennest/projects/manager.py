"""Creating, listing and opening projects.

Directory layout (WORKORDER_01 section 11):

    Asteroid Game/
      .opennest/      internal memory and conversation archive
      src/            source the child and the AI work on
      assets/         imported images, sounds, documents
      data/           datasets
      docs/           notes
      project.json    manifest (section 31)

Manifest writes are atomic: a crash mid-save must not leave a project unopenable.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from opennest import paths
from opennest.projects import starters as starter_kits
from opennest.projects.profiles import Profile, get_profile
from opennest.versioning.autosave import atomic_write_text

MANIFEST_NAME = "project.json"
SUBDIRECTORIES = ("src", "assets", "data", "docs")

#: Characters that are awkward in a filename on macOS or in a shell.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ProjectError(Exception):
    """Something went wrong creating or opening a project, in plain language."""


@dataclass
class Manifest:
    """WORKORDER_01 section 31. Never holds secrets."""

    name: str
    profile: str
    created: str
    entrypoint: str
    model: str | None = None
    build_style: str = "build"
    assets_directory: str = "assets"
    schema_version: int = 1
    active_thread: int = 1
    last_successful_run: str | None = None
    git_enabled: bool = False
    github_backup: bool = False
    #: Which Arduino board this project is for, as an arduino-cli FQBN. Stays None until
    #: the child picks one: WORKORDER_01 section 8 forbids inventing hardware details,
    #: and guessing a board is guessing every pin on it.
    arduino_board: str | None = None
    #: Which starter kit this project was created from, and at what version. ``None``
    #: means nothing is recorded -- either the child started empty, or the project
    #: predates Phase 11. The two are deliberately not distinguished: an old project's
    #: files might be a Phase 0 template or might be entirely the child's by now, and
    #: guessing which would be telling Gary something nobody measured. Silence is the
    #: honest answer, and it is also exactly what he saw before Phase 11.
    starter_id: str | None = None
    starter_version: int | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> Manifest:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})


@dataclass
class Project:
    directory: Path
    manifest: Manifest
    _profile: Profile | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def profile(self) -> Profile:
        if self._profile is None:
            self._profile = get_profile(self.manifest.profile)
        return self._profile

    @property
    def internal_dir(self) -> Path:
        return paths.project_internal_dir(self.directory)

    @property
    def entrypoint_path(self) -> Path:
        return self.directory / "src" / self.manifest.entrypoint

    def save(self) -> None:
        write_manifest(self.directory, self.manifest)


def safe_directory_name(name: str) -> str:
    """Turn a child's project name into something safe to put on disk."""
    cleaned = _UNSAFE.sub("", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise ProjectError("That project name cannot be used. Try letters and numbers.")
    return cleaned[:80]


def write_manifest(directory: Path, manifest: Manifest) -> None:
    """Write project.json atomically. A half-written manifest makes a project unopenable."""
    payload = json.dumps(asdict(manifest), indent=2) + "\n"
    atomic_write_text(Path(directory) / MANIFEST_NAME, payload)


def read_manifest(directory: Path) -> Manifest:
    target = Path(directory) / MANIFEST_NAME
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProjectError(f"{Path(directory).name} is missing its project file.") from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{Path(directory).name} has a damaged project file.") from exc
    return Manifest.from_dict(raw)


class _ProfileDefault:
    """Sentinel: "whichever kit this profile begins with"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "PROFILE_DEFAULT"


#: Passed as ``starter_id`` to mean the profile's own default. ``None`` means the
#: opposite and is not the same thing: it is the child choosing to start empty.
PROFILE_DEFAULT = _ProfileDefault()


def resolve_starter(profile: Profile, starter_id) -> starter_kits.Starter | None:
    """Turn a caller's choice into a kit, or None for empty.

    Raises :class:`ProjectError` for a kit this profile does not offer, which is a
    programming mistake rather than something a child can cause -- the pickers are built
    from ``profile.starters``.
    """
    if starter_id is PROFILE_DEFAULT:
        return starter_kits.default_starter(profile)
    if starter_id is None:
        return None
    if starter_id not in profile.starters:
        offered = ", ".join(profile.starters) or "none"
        raise ProjectError(
            f"A {profile.name} project has no starter called {starter_id!r}. "
            f"It offers: {offered}."
        )
    return starter_kits.get_starter(starter_id)


def create_project(
    name: str,
    profile_id: str,
    *,
    model: str | None = None,
    build_style: str = "build",
    starter_id=PROFILE_DEFAULT,
    root: Path | None = None,
) -> Project:
    """Create a project directory, manifest and -- unless asked not to -- starter files.

    ``starter_id`` is the profile's default when omitted, ``None`` to start empty, or
    the id of one of the kits the profile offers.
    """
    profile = get_profile(profile_id)

    # Resolved before anything is created. A profile naming a kit that is not installed
    # is a packaging fault, and it used to pass silently: four of the five profiles made
    # a project containing nothing but project.json, with the manifest pointing at an
    # entrypoint that was never copied in. Nothing noticed for seven phases, which is
    # the argument for failing loudly -- and for failing here, before a half-made
    # directory exists to block the child retrying the same name.
    try:
        starter = resolve_starter(profile, starter_id)
        if starter is not None:
            starter_kits.source_files(starter)
    except starter_kits.StarterError as exc:
        raise ProjectError(str(exc)) from exc

    projects_root = Path(root) if root else paths.projects_root()
    projects_root.mkdir(parents=True, exist_ok=True)

    directory = projects_root / safe_directory_name(name)
    if directory.exists():
        raise ProjectError(f"A project called {directory.name!r} already exists.")

    directory.mkdir(parents=True)
    for sub in SUBDIRECTORIES:
        (directory / sub).mkdir()
    paths.project_internal_dir(directory).mkdir()

    if starter is not None:
        starter_kits.apply(starter, directory / "src")

    manifest = Manifest(
        name=name,
        profile=profile.id,
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        entrypoint=profile.entrypoint,
        model=model,
        build_style=build_style,
        starter_id=starter.id if starter else None,
        starter_version=starter.version if starter else None,
    )
    write_manifest(directory, manifest)
    return Project(directory=directory, manifest=manifest, _profile=profile)


def add_starter(project: Project, starter_id: str) -> tuple[str, ...]:
    """Add a kit to an existing project, and record that it is there.

    The one-click offer behind an empty Workbench. It refuses rather than merges if any
    of the kit's files already exist -- :func:`opennest.projects.starters.apply` is
    where that is enforced, so no caller can skip it.
    """
    try:
        starter = resolve_starter(project.profile, starter_id)
        if starter is None:
            raise ProjectError("There is no starter to add.")
        written = starter_kits.apply(starter, project.directory / "src")
    except starter_kits.StarterError as exc:
        raise ProjectError(str(exc)) from exc
    project.manifest.starter_id = starter.id
    project.manifest.starter_version = starter.version
    project.save()
    return written


def open_project(directory: Path) -> Project:
    directory = Path(directory)
    if not directory.is_dir():
        raise ProjectError(f"{directory.name} could not be found.")
    return Project(directory=directory, manifest=read_manifest(directory))


def list_projects(root: Path | None = None) -> list[Project]:
    """Every openable project, most recently changed first."""
    projects_root = Path(root) if root else paths.projects_root()
    if not projects_root.is_dir():
        return []
    found: list[Project] = []
    for entry in projects_root.iterdir():
        if not entry.is_dir() or not (entry / MANIFEST_NAME).is_file():
            continue
        try:
            found.append(open_project(entry))
        except ProjectError:
            continue  # A damaged project should not hide the working ones.
    found.sort(key=lambda p: p.directory.stat().st_mtime, reverse=True)
    return found
