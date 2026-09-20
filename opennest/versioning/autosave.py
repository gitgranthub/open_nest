"""Saving without anyone pressing Save.

WORKORDER_01 section 29A: "Use atomic file writes where practical so a crash or power
loss does not leave important project metadata partially written. Maintain a dirty-state
tracker so the application does not unnecessarily rewrite unchanged files."

Source files are already on disk the moment a tool writes them. What needs care is the
metadata that makes a project *openable* -- the manifest above all. A half-written
project.json turns a child's work into an error message, so it is never written in
place.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write a file so it is either the old contents or the new ones, never half of each.

    Writes to a temporary file in the same directory -- same filesystem, so the rename is
    atomic -- fsyncs it, then replaces. ``os.replace`` is atomic on POSIX.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding=encoding) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


@dataclass
class DirtyTracker:
    """Remembers what changed, so unchanged files are not rewritten.

    Deliberately simple: a set of names and a flag. The expensive thing to avoid is
    rewriting metadata and creating empty checkpoints, not micro-optimising file IO.
    """

    _paths: set[str] = field(default_factory=set)

    def touch(self, *relative_paths: str) -> None:
        self._paths.update(p for p in relative_paths if p)

    @property
    def is_dirty(self) -> bool:
        return bool(self._paths)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._paths))

    def clear(self) -> None:
        self._paths.clear()

    def __len__(self) -> int:
        return len(self._paths)
