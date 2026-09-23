"""Draining the push queue without the child ever waiting for it.

WORKORDER_01 section 34: "GitHub synchronization should also be non-blocking." Section
29A says the same thing from the other end -- "A temporary loss of internet should never
block local development."

This is the Qt half of :mod:`opennest.github.push_queue`, and it is deliberately thin.
All the retry logic, the backoff and the decisions about what is worth reporting live in
the queue, which has no Qt in it and is tested without a display. What is here is a
thread and a timer.

Two things worth knowing:

**A push failure never reaches the child.** A backup problem is not something they did
or can fix, and a dialog about GitHub in the middle of building a game is exactly the
"visible complexity" section 29A warns against. Only a blocked credential surfaces, and
it surfaces to a parent.

**The timer is slow on purpose.** Sixty seconds between sweeps, and the queue's own
backoff is what actually spaces out retries -- measured at up to an hour. A tighter
timer would not make a push succeed sooner; it would just wake the radio.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from opennest.github import backup
from opennest.github.push_queue import Outcome, PushQueue
from opennest.ui.worker import run_in_thread

#: How often the queue is swept. The backoff inside the queue is the real spacing.
SWEEP_SECONDS = 60


@dataclass(frozen=True)
class BackupStatus:
    """What backup is doing, said two different ways on purpose.

    A child may see *that* their work is backed up; a parent may see the detail. The
    split was set by the developer and it is the reason this carries two strings rather
    than one. ``child`` never mentions a queue depth, a repository, a branch, a commit
    count or a push failure -- section 29A's "no visible complexity" applies to them,
    and none of those are theirs to act on. ``parent`` is the version for Parent
    Settings, where the person reading it turned backup on and can do something about it.

    ``state`` is a :func:`opennest.ui.common.status_row` state, so the dot colour follows
    the same vocabulary as LOCAL AI and CLOUD.
    """

    state: str
    child: str
    parent: str


class SyncWorker(QObject):
    """One drain of the queue, off the UI thread."""

    finished = Signal(object)  # push_queue.Outcome
    failed = Signal(str)

    def __init__(self, credentials, queue: PushQueue) -> None:
        super().__init__()
        self.credentials = credentials
        self.queue = queue

    def run(self) -> None:
        try:
            outcome = backup.drain(self.credentials, self.queue)
            self.queue.save()
        except Exception as exc:  # noqa: BLE001 - a backup must not crash the app
            self.failed.emit(f"Backup could not run: {exc}")
        else:
            self.finished.emit(outcome)


class GitHubSync(QObject):
    """Owns the queue and keeps it moving.

    ``on_problem`` is called with (project name, message) for the failures a parent has
    to see. Everything else is silent by design.
    """

    def __init__(
        self,
        parent: QObject,
        *,
        credentials,
        controls,
        queue: PushQueue | None = None,
        on_problem: Callable[[str, str], None] | None = None,
        on_status: Callable[[BackupStatus], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.credentials = credentials
        self.controls = controls
        self.queue = queue if queue is not None else PushQueue.load()
        self.on_problem = on_problem
        #: Called whenever the backup state may have moved, so a status line can follow
        #: it. Separate from ``on_problem``, which is the parent-only failure channel:
        #: this one is allowed to reach the child and therefore says much less.
        self.on_status = on_status
        self._running = False
        self._timer = QTimer(self)
        self._timer.setInterval(SWEEP_SECONDS * 1000)
        self._timer.timeout.connect(self.sweep)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Begin sweeping, if there is any point.

        Checked once here and again on every sweep: a parent can connect GitHub while
        the app is running, and can turn backup off again just as easily.
        """
        self._timer.start()
        self.sweep()
        self._announce()

    def stop(self) -> None:
        self._timer.stop()

    # -- what to show -------------------------------------------------------

    def status(self) -> BackupStatus:
        """Where the backup stands, for the two audiences that may see it.

        "Waiting for internet" is a **verified** claim rather than a guess, and that is
        why the never-attempted case is worded differently. ``PushQueue.drain`` keeps an
        entry only when the push raised ``Offline``; a rejected push and a
        secret-blocked one are dropped and reported to a parent instead, because a timer
        cannot fix either. So an entry that has been tried and is still queued really is
        waiting on the network. An entry queued moments ago and not yet swept has not
        failed at anything, so it just says it is waiting.

        Likewise "Complete" is only said when the queue is genuinely empty *and* backup
        is set up -- brand and status language must never imply a state Open Nest has
        not actually established.
        """
        pending = self.queue.pending()
        if not backup.readiness(self.controls, self.credentials).ready:
            return BackupStatus(
                "idle", "Not set up",
                "GitHub backup is not set up, so projects stay on this Mac only.",
            )
        if not pending:
            return BackupStatus(
                "ready", "Complete",
                "Everything is backed up.",
            )
        count = len(pending)
        projects = "project is" if count == 1 else "projects are"
        if any(entry.attempts for entry in pending):
            return BackupStatus(
                "working", "Waiting for internet",
                f"{count} {projects} waiting to back up.\n"
                "They will sync when the internet connection returns.",
            )
        return BackupStatus(
            "working", "Waiting",
            f"{count} {projects} waiting to back up.",
        )

    # -- queueing -----------------------------------------------------------

    def queue_project(self, project) -> bool:
        """Note that a project has new work to back up."""
        queued = backup.after_checkpoint(
            project, self.controls, self.credentials, self.queue
        )
        if queued:
            self.queue.save()
            self._announce()
        return queued

    def flush(self, project) -> None:
        """Queue and immediately try, for a clean close.

        Synchronous on purpose: the app is shutting down, so there is no UI left to keep
        responsive and no later sweep to rely on. Failure is fine -- the queue is
        persisted, and section 34's promise is that the work is safe locally either way.
        """
        if not self.queue_project(project):
            return
        try:
            backup.drain(self.credentials, self.queue)
        except Exception:  # noqa: BLE001 - quitting must not fail
            pass
        finally:
            with contextlib.suppress(Exception):
                self.queue.save()

    # -- sweeping -----------------------------------------------------------

    def sweep(self) -> None:
        """Try whatever is due, on a worker thread."""
        if self._running or not len(self.queue):
            return
        if not backup.readiness(self.controls, self.credentials).ready:
            return
        self._running = True
        worker = SyncWorker(self.credentials, self.queue)
        worker.finished.connect(self._done)
        worker.failed.connect(self._problem)
        run_in_thread(self, worker)

    def _done(self, outcome: Outcome) -> None:
        self._running = False
        self._announce()
        if self.on_problem is None:
            return
        for name, message in outcome.problems:
            self.on_problem(name, message)

    def _problem(self, message: str) -> None:
        self._running = False
        self._announce()
        # Not surfaced. An unexpected backup failure is a diagnostics matter, and
        # interrupting a child with it would be worse than the failure.

    def _announce(self) -> None:
        """Tell whoever is showing the status that it may have moved."""
        if self.on_status is not None:
            self.on_status(self.status())
