"""Pushes waiting for the internet -- WORKORDER_01 section 34, DoD 48-50.

    local autosave -> local Git commit -> background push to private GitHub repository

Section 29A draws that chain and then says the important part: "A temporary loss of
internet should never block local development. Queue pushes and retry later." DoD 48-50
is the same requirement written as a scenario -- connectivity drops, the child keeps
working and committing, and when it comes back the queue resumes "without disrupting the
child's project".

Four decisions here are not obvious from the code.

**One entry per project and branch, not one per commit.** A push sends whatever the
branch points at, so two queued pushes for the same branch are the same push. Queueing
per commit would mean a child who worked offline all afternoon comes back to forty
identical pushes, thirty-nine of which are no-ops. Re-queueing an existing entry resets
its backoff instead, because new work is evidence the project is live.

**Being offline is the only thing worth retrying.** A rejected push and a blocked one
are not transient: retrying them on a timer produces the same failure and, for a
credential, repeats the same warning forever. Those leave the queue and are reported;
:class:`~opennest.versioning.git_manager.Offline` is the one that waits.

**The queue holds no secret and is checked for it.** Project paths and branch names
only. The token comes from the Keychain at the moment of the push and is never written
here -- the same reason ``installation.json`` and ``settings.json`` both run the
scanner over themselves before saving.

**Nothing here imports Qt.** The queue is ordinary Python with an injected clock, so the
retry logic is testable without a display or a timer. ``ui/github_sync.py`` is the thin
Qt object that drives it on a worker thread.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from opennest import paths
from opennest.versioning import git_manager
from opennest.versioning.git_manager import GitError, Offline, SecretsFound
from opennest.versioning.secret_scanner import scan_text

#: How long to wait after each failed attempt, in seconds. Ends at an hour: a Mac that
#: has been offline for six hours is probably in a drawer, and hammering a dead link
#: every thirty seconds costs battery and tells nobody anything.
BACKOFF_SECONDS: tuple[int, ...] = (30, 120, 300, 900, 1800, 3600)

#: Entries older than this are dropped. A push that has been failing for a fortnight is
#: not going to start working, and the project is safe on this Mac regardless -- which
#: is the whole premise of section 34.
MAX_AGE_SECONDS = 14 * 24 * 3600


@dataclass
class QueuedPush:
    """One project waiting to be backed up."""

    project_dir: str
    branch: str
    repository: str = ""
    queued_at: float = 0.0
    attempts: int = 0
    #: When the next attempt may happen. Advanced by the backoff schedule.
    ready_at: float = 0.0
    #: The last failure, already scrubbed. For diagnostics, never for a child.
    last_error: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.project_dir, self.branch)

    def ready(self, now: float) -> bool:
        return now >= self.ready_at

    def as_dict(self) -> dict:
        return {
            "project_dir": self.project_dir,
            "branch": self.branch,
            "repository": self.repository,
            "queued_at": self.queued_at,
            "attempts": self.attempts,
            "ready_at": self.ready_at,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, raw: object) -> QueuedPush | None:
        if not isinstance(raw, dict):
            return None
        project = raw.get("project_dir")
        branch = raw.get("branch")
        if not isinstance(project, str) or not isinstance(branch, str):
            return None
        if not project or not branch:
            return None
        return cls(
            project_dir=project,
            branch=branch,
            repository=raw.get("repository") if isinstance(raw.get("repository"), str) else "",
            queued_at=_as_float(raw.get("queued_at")),
            attempts=_as_int(raw.get("attempts")),
            ready_at=_as_float(raw.get("ready_at")),
            last_error=raw.get("last_error") if isinstance(raw.get("last_error"), str) else "",
        )


@dataclass(frozen=True)
class Outcome:
    """What one drain did. The UI reports only what a parent needs to act on."""

    pushed: tuple[str, ...] = ()
    #: Still queued, waiting for the internet.
    waiting: tuple[str, ...] = ()
    #: (project name, message) for failures a parent has to see -- a blocked
    #: credential, or a rejected push. Never shown to the child.
    problems: tuple[tuple[str, str], ...] = ()

    @property
    def quiet(self) -> bool:
        """True when nothing happened worth telling anyone about."""
        return not self.pushed and not self.problems


@dataclass
class PushQueue:
    """The queue itself. Persisted, because the internet might be back tomorrow."""

    path: Path | None = None
    entries: list = field(default_factory=list)
    #: Injected so tests do not wait out a real backoff.
    clock: Callable[[], float] = time.time

    # -- persistence --------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None, *, clock: Callable[[], float] = time.time) -> PushQueue:
        target = Path(path) if path is not None else paths.push_queue_file()
        queue = cls(path=target, clock=clock)
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A missing queue is the ordinary case. A damaged one loses queued pushes,
            # which costs a delay and never a project: the next checkpoint re-queues.
            return queue
        items = raw.get("pushes") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            return queue
        for item in items:
            entry = QueuedPush.from_dict(item)
            if entry is not None:
                queue.entries.append(entry)
        queue._expire()
        return queue

    def save(self, path: Path | None = None) -> Path:
        target = Path(path) if path is not None else (self.path or paths.push_queue_file())
        payload = {"pushes": [entry.as_dict() for entry in self.entries]}
        _reject_credentials(payload)
        target.parent.mkdir(parents=True, exist_ok=True)
        scratch = target.with_suffix(target.suffix + ".tmp")
        scratch.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        scratch.replace(target)
        self.path = target
        return target

    # -- queueing -----------------------------------------------------------

    def enqueue(self, project_dir: Path, branch: str, repository: str = "") -> QueuedPush:
        """Add a project, or refresh the one already waiting.

        Refreshing resets the backoff: a new checkpoint means the child is working now,
        and making them wait out an hour-long backoff earned while the Wi-Fi was off is
        the wrong behaviour.
        """
        now = self.clock()
        key = (str(project_dir), branch)
        for entry in self.entries:
            if entry.key == key:
                entry.attempts = 0
                entry.ready_at = now
                entry.last_error = ""
                if repository:
                    entry.repository = repository
                return entry
        entry = QueuedPush(
            project_dir=str(project_dir),
            branch=branch,
            repository=repository,
            queued_at=now,
            ready_at=now,
        )
        self.entries.append(entry)
        return entry

    def remove(self, project_dir: Path, branch: str) -> bool:
        key = (str(project_dir), branch)
        before = len(self.entries)
        self.entries = [entry for entry in self.entries if entry.key != key]
        return len(self.entries) != before

    def pending(self) -> tuple[QueuedPush, ...]:
        return tuple(self.entries)

    def due(self) -> tuple[QueuedPush, ...]:
        now = self.clock()
        return tuple(entry for entry in self.entries if entry.ready(now))

    def __len__(self) -> int:
        return len(self.entries)

    # -- draining -----------------------------------------------------------

    def drain(self, token: str, *, pusher=None) -> Outcome:
        """Try every push that is due. Never raises.

        ``pusher`` is injected by the test suite; in the application it is
        ``git_manager.push``. A failure here must never reach the child, because a
        backup problem is not something they did or can fix.
        """
        send = pusher if pusher is not None else git_manager.push
        self._expire()

        pushed: list[str] = []
        waiting: list[str] = []
        problems: list[tuple[str, str]] = []
        survivors: list[QueuedPush] = []

        for entry in self.entries:
            name = Path(entry.project_dir).name
            if not entry.ready(self.clock()):
                waiting.append(name)
                survivors.append(entry)
                continue
            if not Path(entry.project_dir).is_dir():
                # The project was moved or deleted. Nothing to push, and nothing wrong.
                continue

            try:
                send(Path(entry.project_dir), token, branch=entry.branch)
            except Offline as exc:
                entry.attempts += 1
                entry.last_error = str(exc)
                entry.ready_at = self.clock() + _backoff(entry.attempts)
                waiting.append(name)
                survivors.append(entry)
            except SecretsFound as exc:
                # Section 29A: block the push, notify the parent, do not log the
                # credential. Dropped rather than retried -- the next checkpoint
                # re-queues it, so a parent who fixes the file gets their backup, and
                # one who does not is told again rather than never.
                problems.append((name, str(exc)))
            except GitError as exc:
                problems.append((name, str(exc)))
            else:
                pushed.append(name)

        self.entries = survivors
        return Outcome(tuple(pushed), tuple(waiting), tuple(problems))

    # -- internals ----------------------------------------------------------

    def _expire(self) -> None:
        now = self.clock()
        self.entries = [
            entry
            for entry in self.entries
            if not entry.queued_at or now - entry.queued_at < MAX_AGE_SECONDS
        ]


def _backoff(attempts: int) -> int:
    index = min(max(attempts, 1) - 1, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[index]


def _reject_credentials(payload: dict) -> None:
    """Stop a token reaching the queue file.

    Nothing puts one there, which is why it is worth checking: the failure guarded
    against is a future change that caches "the token we pushed with" alongside the
    entry. Section 22 lists JSON configuration by name.
    """
    findings = scan_text(json.dumps(payload, indent=2), "push_queue.json")
    if findings:
        raise ValueError(
            "Open Nest refused to save the backup queue because something in it looks "
            "like a password or key. Tokens belong in the macOS Keychain."
        )


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    return float(value) if isinstance(value, (int, float)) else 0.0


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    return value if isinstance(value, int) else 0
