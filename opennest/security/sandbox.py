"""Path confinement for everything the AI touches.

WORKORDER_01 section 18: "All paths must resolve inside the current project directory."
Section 19: no arbitrary filesystem access, no reading the home directory, no Keychain.

This module is the single choke point. Every tool resolves its path through
:func:`resolve_in_project`, which is the only function permitted to turn a model-supplied
string into a real filesystem path.

The threat here is not a malicious child. It is a 4B model that writes a plausible-looking
``../../.ssh/id_rsa`` because something in its training data did, and a symlink that
resolves somewhere unexpected.
"""

from __future__ import annotations

import os
from pathlib import Path

from opennest.paths import PROJECT_INTERNAL_DIRNAME


class PathNotAllowed(Exception):
    """A requested path resolves outside the project, or into a protected area."""


#: Directories the AI may never read or write, even though they live inside the project.
#: ``.opennest`` is internal memory the memory manager owns; ``.git`` is version history
#: the version manager owns. A model editing either corrupts state it cannot reason about.
PROTECTED_DIRS = frozenset({PROJECT_INTERNAL_DIRNAME, ".git"})

#: Never writable regardless of location.
PROTECTED_NAMES = frozenset({".gitignore", ".env"})


def resolve_in_project(project_dir: Path, requested: str, *, for_write: bool = False) -> Path:
    """Resolve ``requested`` to a real path inside ``project_dir``.

    Raises :class:`PathNotAllowed` for anything that escapes, is absolute, targets a
    protected area, or resolves through a symlink to somewhere outside.

    Returns an absolute path. The file need not exist -- callers creating files rely on
    that -- but every existing component of it is checked.
    """
    if not requested or not requested.strip():
        raise PathNotAllowed("No file name was given.")

    text = requested.strip()

    if os.path.isabs(text) or text.startswith("~"):
        raise PathNotAllowed(
            f"{text!r} is a full path. Files are named relative to the project, "
            f"like 'game.py' or 'src/game.py'."
        )

    # Reject NUL and other control characters outright rather than letting the OS decide.
    if any(ord(ch) < 32 for ch in text):
        raise PathNotAllowed("That file name contains characters that are not allowed.")

    root = Path(project_dir).resolve(strict=True)
    candidate = (root / text).resolve()

    # resolve() follows symlinks, so this catches both ../ traversal and a symlink
    # inside the project that points outside it.
    if candidate != root and root not in candidate.parents:
        raise PathNotAllowed(
            f"{text!r} is outside the project. Everything has to stay inside this project's folder."
        )

    if candidate == root:
        raise PathNotAllowed("That is the project folder itself, not a file in it.")

    relative = candidate.relative_to(root)
    if set(relative.parts) & PROTECTED_DIRS:
        raise PathNotAllowed(f"{relative.parts[0]!r} is used by Open Nest and cannot be changed.")

    if for_write and relative.name in PROTECTED_NAMES:
        raise PathNotAllowed(f"{relative.name!r} cannot be changed.")

    return candidate


def is_within_project(project_dir: Path, path: Path) -> bool:
    """Whether an already-resolved path lies inside the project. Used for assertions."""
    try:
        root = Path(project_dir).resolve(strict=True)
        target = Path(path).resolve()
    except OSError:
        return False
    return target == root or root in target.parents


def visible_files(project_dir: Path, *, limit: int = 400) -> list[str]:
    """Project-relative paths the child and the AI are allowed to see.

    This is what gets injected into the model's context instead of offering a
    ``list_project_files`` tool -- see SPIKES.md section 4. Deterministic application
    knowledge, not something the model has to go and ask for.
    """
    root = Path(project_dir).resolve(strict=True)
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(found) >= limit:
            break
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if set(relative.parts) & PROTECTED_DIRS:
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        if "__pycache__" in relative.parts:
            continue
        found.append(str(relative))
    return found
