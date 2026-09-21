"""Noticing that a new version of Open Nest exists — decision D9.

**This module never modifies the application's Git checkout.** It does not pull, merge,
fetch into the repository, reset, stash or check anything out. It asks the remote what
its newest commit is, compares that to the one running, and says what it found. That is
the whole of the capability, and the boundary is deliberate: a one-click in-app updater
is a separate product feature, and the traps in it (local modifications, a moved model
pin implying gigabytes, restarting an app whose code changed underneath it) are not
Phase 8's to absorb.

Three things follow from D9, all of them decisions rather than implementation details:

**Checking is a parent action, not a project action.** ``external_requests`` governs
whether a *child's project* may reach the network while it runs, and it is the wrong
gate: this is the application contacting its own source, on a parent's explicit press,
from behind the parent PIN in Settings. Pressing the button is the permission, so there
is no new switch. Nothing here runs on launch, on a timer, or in the background.

**``git ls-remote`` is the whole network call.** It is read-only by construction -- it
writes nothing into ``.git``, unlike ``git fetch`` -- and it needs no credentials
against a public repository, which is why this does not wait on D1.

**Being offline is an answer, not an error.** Open Nest is offline-first; a parent who
checks on a train should be told the check could not reach GitHub, in those words.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from opennest import paths

#: Long enough for a slow connection, short enough that a parent does not think it hung.
TIMEOUT_SECONDS = 20

#: What a parent does about an update. Phase 8 tells them; it does not do it for them.
NEXT_STEP = (
    "To update, quit Open Nest and run this in Terminal, in the Open Nest folder:\n\n"
    "    git pull\n\n"
    "The next time Open Nest starts it will finish the update by itself."
)


@dataclass(frozen=True)
class UpdateStatus:
    """What a check found. ``available`` is only True when that is actually known."""

    #: ``current`` | ``available`` | ``unknown``
    outcome: str
    summary: str
    detail: str = ""
    local_commit: str = ""
    remote_commit: str = ""

    @property
    def available(self) -> bool:
        return self.outcome == "available"

    @property
    def checked(self) -> bool:
        """False when the remote could not be reached, so nothing was learned."""
        return self.outcome != "unknown"


def check(repo_root: Path | None = None, *, timeout: float = TIMEOUT_SECONDS) -> UpdateStatus:
    """Ask the remote whether it has moved. Touches nothing on disk."""
    root = Path(repo_root) if repo_root is not None else paths.repo_root()

    if not (root / ".git").exists():
        return UpdateStatus(
            "unknown",
            "Open Nest cannot check for updates.",
            "This copy was not installed with Git, so there is nothing to compare "
            "against.",
        )

    local = _local_commit(root, timeout)
    if local is None:
        return UpdateStatus(
            "unknown",
            "Open Nest could not work out which version is running.",
            "Git did not answer. Nothing was changed.",
        )

    branch = _current_branch(root, timeout) or "HEAD"
    reached, remote = _remote_commit(root, branch, timeout)
    if not reached:
        return UpdateStatus(
            "unknown",
            "Open Nest could not reach GitHub.",
            "The check needs the internet. Nothing was changed, and Open Nest works "
            "normally offline.",
            local_commit=local,
        )
    if remote is None:
        # GitHub answered; it simply has no such branch. Saying "could not reach
        # GitHub" here would blame the network for something the network did fine --
        # found by the Phase 8 acceptance pass, on a branch not yet pushed.
        return UpdateStatus(
            "unknown",
            "Open Nest could not check this version.",
            f"GitHub has no copy of \"{branch}\", which is the version this Mac is "
            f"running. Nothing was changed.",
            local_commit=local,
        )

    if remote == local:
        return UpdateStatus(
            "current",
            "Open Nest is up to date.",
            f"Running {_short(local)}.",
            local_commit=local,
            remote_commit=remote,
        )

    return UpdateStatus(
        "available",
        "An update to Open Nest is available.",
        f"This Mac is running {_short(local)}; the newest is {_short(remote)}.\n\n"
        + NEXT_STEP,
        local_commit=local,
        remote_commit=remote,
    )


# --------------------------------------------------------------------------- internals

def _git(root: Path, *args: str, timeout: float) -> str | None:
    """Run one read-only git command. Returns None rather than raising.

    Every caller here passes a command that only reads. Nothing in this module is
    allowed to write to the repository, and keeping them all behind one helper is what
    makes that reviewable at a glance.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip()


def _local_commit(root: Path, timeout: float) -> str | None:
    return _git(root, "rev-parse", "HEAD", timeout=timeout) or None


def _current_branch(root: Path, timeout: float) -> str | None:
    name = _git(root, "rev-parse", "--abbrev-ref", "HEAD", timeout=timeout)
    return None if not name or name == "HEAD" else name


def _remote_commit(root: Path, branch: str, timeout: float) -> tuple:
    """``(reached, commit)`` for the remote's tip of ``branch``.

    Via ``ls-remote``, which writes nothing into ``.git`` -- unlike ``git fetch``.

    The two halves are separate answers because ``ls-remote`` **exits 0 with empty
    output** for a branch the remote does not have. Collapsing that into "no commit"
    made the check report a network failure on a perfectly connected machine.
    """
    output = _git(root, "ls-remote", "origin", branch, timeout=timeout)
    if output is None:
        return False, None
    if not output.strip():
        return True, None
    first = output.splitlines()[0].split()
    return True, (first[0] if first else None)


def _short(commit: str) -> str:
    return commit[:8] if commit else "an unknown version"
