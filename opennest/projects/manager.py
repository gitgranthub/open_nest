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
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from opennest import paths
from opennest.projects.profiles import Profile, get_profile

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
    """Write project.json atomically so a crash cannot corrupt it."""
    target = Path(directory) / MANIFEST_NAME
    payload = json.dumps(asdict(manifest), indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(dir=str(directory), prefix=".manifest-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def read_manifest(directory: Path) -> Manifest:
    target = Path(directory) / MANIFEST_NAME
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProjectError(f"{Path(directory).name} is missing its project file.") from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{Path(directory).name} has a damaged project file.") from exc
    return Manifest.from_dict(raw)


def template_dir(profile: Profile) -> Path:
    return paths.package_root() / "projects" / "templates" / profile.starter_template


def create_project(
    name: str,
    profile_id: str,
    *,
    model: str | None = None,
    build_style: str = "build",
    root: Path | None = None,
) -> Project:
    """Create a project directory, manifest and starter files."""
    profile = get_profile(profile_id)
    projects_root = Path(root) if root else paths.projects_root()
    projects_root.mkdir(parents=True, exist_ok=True)

    directory = projects_root / safe_directory_name(name)
    if directory.exists():
        raise ProjectError(f"A project called {directory.name!r} already exists.")

    directory.mkdir(parents=True)
    for sub in SUBDIRECTORIES:
        (directory / sub).mkdir()
    paths.project_internal_dir(directory).mkdir()

    source = template_dir(profile)
    if source.is_dir():
        shutil.copytree(source, directory / "src", dirs_exist_ok=True)

    manifest = Manifest(
        name=name,
        profile=profile.id,
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        entrypoint=profile.entrypoint,
        model=model,
        build_style=build_style,
    )
    write_manifest(directory, manifest)
    return Project(directory=directory, manifest=manifest, _profile=profile)


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
