"""Git, kept out of sight.

WORKORDER_01 section 29A. Every project is a Git repository, and the child never has to
know. No command here is ever shown to them; the child-facing vocabulary lives in
:mod:`opennest.versioning.checkpoint`.

Two rules this module exists to enforce:

- **Identity stays local to the project.** Git config is written with ``git -C <project>
  config``, never ``--global``. Open Nest must not quietly change how a parent's other
  repositories are attributed.
- **Nothing is committed without a secret scan.** A credential in Git history is far
  harder to remove than one that was never written.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from opennest.versioning.secret_scanner import Finding, explain, scan_paths

#: Commit messages are prefixed so Open Nest's own checkpoints are identifiable in a
#: history a parent might later look at.
COMMIT_PREFIX = "Open Nest:"

#: Used until the setup wizard (Phase 8) collects a real identity.
DEFAULT_AUTHOR_NAME = "Open Nest"
DEFAULT_AUTHOR_EMAIL = "opennest@localhost"

GITIGNORE = """# Written by Open Nest.

# Python
__pycache__/
*.py[cod]
.venv/
venv/

# Caches and temporary files
.DS_Store
*.tmp
.opennest/tmp/
.opennest/session.json

# Conversation archives stay on this Mac by default (WORKORDER_01 section 38).
# Project memory itself is versioned: it is part of project continuity.
.opennest/conversations/

# Never commit credentials. Open Nest keeps its own in the macOS Keychain.
.env
.env.*
.envrc
.netrc
*.pem
*.key
id_rsa
credentials.json

# Local model files
*.safetensors
*.gguf
models/
"""


class GitError(Exception):
    """A Git operation failed, phrased for a person rather than a developer."""


class SecretsFound(GitError):
    """A commit was refused because the project contains something key-shaped."""

    def __init__(self, findings: list[Finding]) -> None:
        super().__init__(explain(findings))
        self.findings = findings


@dataclass(frozen=True)
class Checkpoint:
    """One saved version, in terms a child-facing screen can use."""

    ref: str
    label: str
    when: datetime

    @property
    def short_ref(self) -> str:
        return self.ref[:8]


def git_available() -> bool:
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _run(project_dir: Path, *args: str, check: bool = True) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"Open Nest could not save a version of this project: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise GitError(
            "Open Nest could not save a version of this project.\n\n"
            + "\n".join(detail[-5:])
        )
    return result.stdout


def is_repo(project_dir: Path) -> bool:
    return (Path(project_dir) / ".git").is_dir()


def ensure_repo(
    project_dir: Path,
    *,
    author_name: str = DEFAULT_AUTHOR_NAME,
    author_email: str = DEFAULT_AUTHOR_EMAIL,
) -> bool:
    """Initialise the project as a repository if it is not one. Returns True if created.

    Identity is written into the project's own config, never the user's global config.
    """
    project_dir = Path(project_dir)
    gitignore = project_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE, encoding="utf-8")

    if is_repo(project_dir):
        return False

    _run(project_dir, "init", "--initial-branch=main")
    _run(project_dir, "config", "user.name", author_name)
    _run(project_dir, "config", "user.email", author_email)
    # A child's project is theirs; never sign or rewrite on their behalf.
    _run(project_dir, "config", "commit.gpgsign", "false")
    return True


def changed_files(project_dir: Path) -> list[str]:
    """Project-relative paths that differ from the last commit, including new files."""
    output = _run(project_dir, "status", "--porcelain=v1", "-z")
    paths: list[str] = []
    for entry in output.split("\0"):
        if len(entry) > 3:
            paths.append(entry[3:])
    return paths


def has_changes(project_dir: Path) -> bool:
    return bool(changed_files(project_dir))


def commit(project_dir: Path, label: str, *, allow_empty: bool = False) -> str | None:
    """Save a checkpoint. Returns the commit ref, or None when there was nothing to save.

    Refuses if the project contains anything credential-shaped.
    """
    pending = changed_files(project_dir)
    if not pending and not allow_empty:
        return None

    findings = scan_paths(Path(project_dir), pending)
    if findings:
        raise SecretsFound(findings)

    _run(project_dir, "add", "-A")
    args = ["commit", "-m", f"{COMMIT_PREFIX} {label}"]
    if allow_empty:
        args.append("--allow-empty")
    _run(project_dir, *args)
    return _run(project_dir, "rev-parse", "HEAD").strip()


def history(project_dir: Path, limit: int = 50) -> list[Checkpoint]:
    """Saved versions, newest first."""
    if not is_repo(project_dir):
        return []
    output = _run(
        project_dir,
        "log",
        f"--max-count={limit}",
        "--format=%H%x1f%s%x1f%cI",
        check=False,
    )
    checkpoints: list[Checkpoint] = []
    for line in output.strip().splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        ref, subject, stamp = parts
        if subject.startswith(COMMIT_PREFIX):
            label = subject[len(COMMIT_PREFIX):].strip()
        else:
            label = subject
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            when = datetime.now(timezone.utc)
        checkpoints.append(Checkpoint(ref=ref, label=label, when=when))
    return checkpoints


def restore(project_dir: Path, ref: str, label: str) -> str | None:
    """Bring the project's files back to an earlier checkpoint.

    Implemented as *forward* motion: the old files are restored and saved as a new
    checkpoint. Nothing is discarded, so a restore can itself be undone. WORKORDER_01
    section 29A wants "restore the version from before we added power-ups", not
    ``git reset --hard``, and an append-only history is what makes that safe.
    """
    if not is_repo(project_dir):
        raise GitError("This project does not have any saved versions yet.")

    # Stash anything uncommitted first, so restoring never silently loses current work.
    if has_changes(project_dir):
        commit(project_dir, "Work in progress before going back")

    # read-tree, not `checkout <ref> -- .`: checkout only restores paths that exist at
    # `ref`, so a file *added* after the checkpoint survives it, and `git clean` will not
    # remove that file either because it is tracked. read-tree sets index and working
    # tree to exactly the checkpoint's tree, which is what "go back to that version"
    # means. HEAD is untouched, so the commit below moves history forward.
    _run(project_dir, "read-tree", "-u", "--reset", ref)
    _run(project_dir, "clean", "-fd", check=False)
    return commit(project_dir, label, allow_empty=True)


def file_at(project_dir: Path, ref: str, relative_path: str) -> str | None:
    """Contents of one file as it was at a checkpoint, or None if it did not exist."""
    try:
        return _run(project_dir, "show", f"{ref}:{relative_path}")
    except GitError:
        return None
