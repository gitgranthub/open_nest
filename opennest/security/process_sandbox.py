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

Note that the check is a *probe*, not a file-existence test, because Seatbelt cannot be
nested. See :func:`sandbox_available`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

#: The cheapest profile that still proves a profile can be applied at all.
_PROBE_PROFILE = "(version 1)(allow default)"

#: Probed once per process. None means "not yet asked".
_available: bool | None = None


class SandboxUnavailable(Exception):
    """The process sandbox could not be applied, so nothing was run."""


def sandbox_available() -> bool:
    """Whether the sandbox can actually be applied -- attempted, not assumed.

    Checking that ``/usr/bin/sandbox-exec`` exists is not the same question. Seatbelt
    profiles **cannot be nested**: inside an existing sandbox, applying another fails
    with ``sandbox_apply: Operation not permitted`` even though the binary is right
    there. That is not hypothetical -- it is what happens when the test suite is run
    under ``scripts/offline.sh``, which is itself a Seatbelt sandbox.

    So the capability is established by exercising it once and caching the answer. It is
    deliberately not an environment variable or a configuration flag: this decides
    whether a model's generated code runs at all, and anything a process can set about
    itself is the wrong input to that decision.
    """
    global _available
    if _available is None:
        _available = _probe()
    return _available


def _probe() -> bool:
    if sys.platform != "darwin" or not os.path.isfile(SANDBOX_EXEC):
        return False
    try:
        result = subprocess.run(
            [SANDBOX_EXEC, "-p", _PROBE_PROFILE, "/usr/bin/true"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


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
