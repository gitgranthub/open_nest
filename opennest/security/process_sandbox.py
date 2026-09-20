"""The outer security boundary: confining code that Open Nest runs.

``opennest.security.sandbox`` constrains paths passing through Open Nest's own file
tools. It cannot constrain a *process*. The moment a generated script runs, a single
``open("/etc/passwd")`` or ``urllib.request.urlopen(...)`` sidesteps every check there.

This module is what actually holds. Every child project runs under macOS Seatbelt with:

- **no network at all** -- WORKORDER_01 section 25 makes external requests a
  parent-controlled permission, so the default is off;
- **writes confined** to the project directory and temporary space;
- reads left alone, because a project legitimately reads the Python standard library,
  fonts and frameworks, and the risks that matter here are exfiltration and damage.

Verified in Phase 1 (SPIKES.md section 1) against a Python process rather than ``curl``:
raw sockets, DNS and HTTPS are all refused, and writes outside the project fail. A Pygame
window still opens normally under these restrictions.

FAIL CLOSED
-----------
If the sandbox cannot be applied, Open Nest refuses to run the project rather than
running it unconfined. Running a model's generated code with full user privileges is
exactly what WORKORDER_01 section 19 forbids, and silently degrading to that would be
worse than an error a parent can read.

``sandbox-exec`` is marked deprecated by Apple. It is present and functional on supported
versions; :func:`sandbox_available` is the check, and replacing the mechanism later means
changing only this file.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"


class SandboxUnavailable(Exception):
    """The process sandbox could not be applied, so nothing was run."""


def sandbox_available() -> bool:
    return sys.platform == "darwin" and os.path.isfile(SANDBOX_EXEC)


def build_profile(project_dir: Path, *, allow_network: bool = False) -> str:
    """A Seatbelt profile confining one project run.

    ``allow_network`` exists for the parent permission in WORKORDER_01 section 25. It is
    off by default and nothing in V1 turns it on.
    """
    writable = [Path(project_dir).resolve(strict=True)]
    for extra in (os.environ.get("TMPDIR"), "/private/tmp", "/private/var/folders"):
        if extra:
            writable.append(Path(extra))

    allow_write = "\n".join(f'    (subpath "{_quote(path)}")' for path in writable)
    network_rule = "" if allow_network else "(deny network*)"

    return f"""(version 1)
(allow default)

; A child's project has no business on the network. Parent-controlled, off by default.
{network_rule}

; Writes only where the project owns the bytes.
(deny file-write*)
(allow file-write*
{allow_write}
    (literal "/dev/null")
    (literal "/dev/stdout")
    (literal "/dev/stderr")
    (regex #"^/dev/tty"))
"""


def wrap(
    command: Sequence[str],
    project_dir: Path,
    *,
    allow_network: bool = False,
) -> list[str]:
    """Return ``command`` wrapped so it runs confined.

    Raises :class:`SandboxUnavailable` rather than returning the bare command, so a
    caller cannot accidentally run a project unconfined by ignoring a return value.
    """
    if not sandbox_available():
        raise SandboxUnavailable(
            "Open Nest could not start the safety sandbox, so it did not run the "
            "project. Projects are never run without it."
        )
    profile = build_profile(project_dir, allow_network=allow_network)
    return [SANDBOX_EXEC, "-p", profile, *command]


def _quote(path: Path) -> str:
    """Escape a path for a Seatbelt string literal."""
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def describe() -> str:
    """One line for diagnostics and the installation health check."""
    if not sandbox_available():
        return "Process sandbox: UNAVAILABLE (projects will refuse to run)"
    return f"Process sandbox: {SANDBOX_EXEC} (network denied, writes confined)"
