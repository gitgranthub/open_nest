"""Saved versions, in the child's vocabulary.

WORKORDER_01 section 29A and DESIGN_DOC.md section 7. The child sees *checkpoints* they
can go back to. They never see a commit, a ref, or the word Git.

This module is the only thing the UI and the agent talk to. Everything underneath is in
:mod:`opennest.versioning.git_manager`.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from opennest.projects.manager import Project
from opennest.versioning import git_manager
from opennest.versioning.git_manager import Checkpoint, GitError, SecretsFound

#: Marker written while a project is open, removed on a clean close. Its presence at
#: startup means the last session ended abruptly.
SESSION_FILE = "session.json"

#: Events worth saving at (WORKORDER_01 section 29A: not after every keystroke).
LABEL_CREATED = "Project created"
LABEL_BEFORE_CHANGE = "Before the assistant made changes"
LABEL_AFTER_CHANGE = "Assistant made changes"
LABEL_WORKING = "Working version"
LABEL_RECOVERED = "Recovered after Open Nest closed unexpectedly"


@dataclass(frozen=True)
class RecoveryReport:
    """What startup found and did. Only surfaced when something actually happened."""

    recovered: bool
    checkpoint: str | None = None
    message: str = ""


class VersionHistory:
    """Saved versions for one project."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.directory = project.directory

    # -- lifecycle ----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return git_manager.git_available()

    def start(self, author_name: str | None = None, author_email: str | None = None) -> None:
        """Make sure the project can be versioned. Safe on every open."""
        if not self.enabled:
            return
        created = git_manager.ensure_repo(
            self.directory,
            author_name=author_name or git_manager.DEFAULT_AUTHOR_NAME,
            author_email=author_email or git_manager.DEFAULT_AUTHOR_EMAIL,
        )
        if created:
            self.save(LABEL_CREATED)
        self._mark_session_open()

    def finish(self) -> None:
        """Called on a clean close: save anything outstanding, clear the crash marker."""
        if not self.enabled:
            return
        # A failed final save must not stop the app from closing.
        with contextlib.suppress(GitError):
            self.save(LABEL_WORKING)
        self._session_path().unlink(missing_ok=True)

    # -- saving -------------------------------------------------------------

    def save(self, label: str) -> str | None:
        """Save a checkpoint if anything changed. Returns its ref, or None."""
        if not self.enabled or not git_manager.is_repo(self.directory):
            return None
        return git_manager.commit(self.directory, label)

    def save_quietly(self, label: str) -> str | None:
        """Save, but never let versioning break the thing the child is doing.

        A secret being found is the one case that must still surface, because silently
        not saving would be worse than the interruption.
        """
        try:
            return self.save(label)
        except SecretsFound:
            raise
        except GitError:
            return None

    # -- going back ---------------------------------------------------------

    def checkpoints(self, limit: int = 50) -> list[Checkpoint]:
        return git_manager.history(self.directory, limit=limit)

    @property
    def can_undo(self) -> bool:
        """True when there is an earlier version to go back to."""
        return len(self.checkpoints(limit=2)) >= 2

    def undo(self) -> Checkpoint | None:
        """Go back to the version before the most recent saved change.

        Returns the checkpoint restored to, or None when there is nothing earlier.
        """
        recent = self.checkpoints(limit=2)
        if len(recent) < 2:
            return None
        target = recent[1]
        git_manager.restore(self.directory, target.ref, f"Went back to: {target.label}")
        return target

    def restore(self, checkpoint: Checkpoint) -> None:
        git_manager.restore(
            self.directory, checkpoint.ref, f"Went back to: {checkpoint.label}"
        )

    def file_at(self, checkpoint: Checkpoint, relative_path: str) -> str | None:
        return git_manager.file_at(self.directory, checkpoint.ref, relative_path)

    # -- crash recovery -----------------------------------------------------

    def _session_path(self) -> Path:
        return self.project.internal_dir / SESSION_FILE

    def _mark_session_open(self) -> None:
        self.project.internal_dir.mkdir(parents=True, exist_ok=True)
        payload = {"opened": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._session_path().write_text(json.dumps(payload), encoding="utf-8")

    def was_interrupted(self) -> bool:
        return self._session_path().is_file()

    def recover(self) -> RecoveryReport:
        """Deal with a session that ended abruptly.

        Uncommitted work from a crash is saved as its own checkpoint rather than
        discarded -- the child's last few minutes of work are the most valuable thing in
        the project, and they can still step back past it if they want to.

        WORKORDER_01 section 29A: do not expose recovery mechanics unless something
        actually needs attention, so an uneventful recovery reports nothing.
        """
        if not self.enabled or not self.was_interrupted():
            return RecoveryReport(recovered=False)

        if not git_manager.is_repo(self.directory) or not git_manager.has_changes(
            self.directory
        ):
            return RecoveryReport(recovered=False)

        ref = self.save_quietly(LABEL_RECOVERED)
        if ref is None:
            return RecoveryReport(recovered=False)
        return RecoveryReport(
            recovered=True,
            checkpoint=ref,
            message="Your project was recovered.",
        )
