"""Path confinement for everything the AI touches.

WORKORDER_01 section 18: "All paths must resolve inside the current project directory."
Section 19: no arbitrary filesystem access, no reading the home directory, no Keychain.

This module is the single choke point for Open Nest's *own* file tools. Every tool
resolves its path through :func:`resolve_in_project`, which is the only function
permitted to turn a model-supplied string into a real filesystem path.

The threat model is not a malicious child. It is a 4B model that writes a
plausible-looking ``../../.ssh/id_rsa`` because something in its training data did, and a
symlink that resolves somewhere unexpected.

WHAT THIS IS NOT
----------------
This is **not** an OS sandbox. It constrains paths that pass through Open Nest's tool
layer, and nothing else. It cannot constrain code that Open Nest *runs*.

Any generated or spawned process -- a child's game, an analysis script, anything the model
writes -- executes outside this module's reach and must be confined separately by the
process sandbox, which denies network access and filesystem writes outside the project at
the kernel level. That process sandbox is the real outer security boundary; this module is
a correctness guard on one interior surface. Treating it as the whole defence would be a
mistake: a single ``open("/etc/passwd")`` inside a generated script bypasses every check
here.

See ``scripts/offline.sh`` for the enforced boundary and SPIKES.md section 1 for its
verification.

KNOWN LIMITATION -- TOCTOU
--------------------------
:func:`resolve_in_project` validates a path and returns it; the caller opens it
afterwards. Between those two moments a symlink could in principle be swapped, so a
validated path is not guaranteed to still point where it did. Under the stated threat
model -- a confused model, not hostile local code that can race the process -- this is
accepted rather than fixed.

Hardening it later means resolving and holding an open file descriptor inside this module
(``os.open`` with ``O_NOFOLLOW``, then ``openat`` relative to a directory descriptor) and
handing callers the descriptor rather than a path. That would change every tool's
signature, so it is deliberately deferred until the threat model calls for it.
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
#:
#: Compared case-insensitively -- see :func:`_casefold_parts`.
PROTECTED_DIRS = frozenset({PROJECT_INTERNAL_DIRNAME, ".git"})

#: Files that may be neither read nor written. Reading is blocked as well as writing,
#: because the harm from a credential file is in it being read and then echoed into a
#: reply, a prompt, a commit, or project memory.
#:
#: Open Nest keeps its own secrets in the macOS Keychain (WORKORDER_01 section 22), so
#: nothing here should exist in a well-formed project. It exists for the case where a
#: child or parent puts one there anyway.
SECRET_NAMES = frozenset({".env", ".envrc", ".netrc", ".npmrc", ".pypirc", ".htpasswd"})

#: Prefixes catching the whole ``.env`` family: .env.local, .env.production, and so on.
SECRET_PREFIXES = (".env.",)

#: Readable, but never writable. Open Nest generates these and relies on their contents.
WRITE_PROTECTED_NAMES = frozenset({".gitignore", ".gitattributes"})


def _casefold_parts(path: Path) -> set[str]:
    """Path components, lowercased for comparison.

    macOS filesystems are case-insensitive by default, so ``.GIT/HEAD`` opens exactly the
    same file as ``.git/HEAD`` while a case-sensitive Python comparison sees two different
    strings. That gap was a real bypass: every protected directory was reachable simply by
    changing the case. Comparing casefolded closes it, and on the rarer case-sensitive
    volume it only means refusing a file that merely looks protected -- a harmless
    false positive.
    """
    return {part.casefold() for part in path.parts}


def _is_secret_name(name: str) -> bool:
    lowered = name.casefold()
    return lowered in SECRET_NAMES or lowered.startswith(SECRET_PREFIXES)


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

    protected_hit = _casefold_parts(relative) & {d.casefold() for d in PROTECTED_DIRS}
    if protected_hit:
        raise PathNotAllowed(
            f"{relative.parts[0]!r} is used by Open Nest and cannot be opened or changed."
        )

    # Secrets are blocked in both directions: reading one is how it ends up quoted into
    # a reply, a prompt, or a commit.
    if _is_secret_name(relative.name):
        raise PathNotAllowed(
            f"{relative.name!r} can hold passwords or keys, so Open Nest will not open it."
        )

    if for_write and relative.name.casefold() in {
        n.casefold() for n in WRITE_PROTECTED_NAMES
    }:
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
        if _casefold_parts(relative) & {d.casefold() for d in PROTECTED_DIRS}:
            continue
        if _is_secret_name(relative.name):
            continue
        # Dotfiles generally are not the child's work, and listing them invites the model
        # to ask about them. Hiding is presentation, not protection -- the checks above
        # are what actually deny access.
        if any(part.startswith(".") for part in relative.parts):
            continue
        if "__pycache__" in relative.parts:
            continue
        found.append(str(relative))
    return found
