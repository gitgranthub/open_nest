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

import contextlib
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from opennest.versioning.secret_scanner import (
    MAX_SCAN_BYTES,
    Finding,
    explain,
    scan_paths,
    scan_text,
)

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


# --------------------------------------------------------------- remotes (Phase 9)
#
# WORKORDER_01 section 29A's GitHub half. Everything below needs the parent's token,
# and the rules it follows are measured rather than assumed (SPIKES.md section 17):
#
# - The remote URL carries **no userinfo**. The token goes to git through GIT_ASKPASS
#   and an environment set for one subprocess.
# - ``credential.helper`` is cleared on every authenticated call. macOS ships
#   ``osxkeychain`` globally, and letting it cache the token would leave a copy in a
#   store Open Nest does not own and cannot clear when a parent presses Disconnect.
# - ``http.lowSpeedLimit``/``lowSpeedTime`` are set because a connection that
#   establishes and then goes silent hangs git **forever** -- measured, not guessed.

#: The username half of the Basic credential. GitHub ignores it for a token, but
#: something has to be sent, and this is the conventional value.
GIT_USERNAME = "x-access-token"

#: Bytes per second, sustained over this many seconds, below which git gives up. Set
#: because there is no timeout otherwise: a server that accepts the connection and never
#: answers held a push open past 180 s in SPIKES.md section 17. Tolerant of a slow link,
#: intolerant of a dead one -- and a false abort costs one retry, not any data.
LOW_SPEED_BYTES = 1000
LOW_SPEED_SECONDS = 30

#: Backstop for the connect phase, which low-speed does not cover: an unanswered SYN
#: takes 75 s to fail on macOS. Generous enough for a first push of a project with
#: assets in it.
PUSH_TIMEOUT_SECONDS = 300

#: Branch prefix for section 29A's review branches (its example is
#: ``buildlab/feature-powerups``).
BRANCH_PREFIX = "opennest"


class PushRejected(GitError):
    """The remote refused the push. Distinct from being offline."""


class Offline(GitError):
    """GitHub could not be reached. An ordinary state, not a fault (section 34)."""


def askpass_helper() -> Path:
    """The script git calls to obtain the credential. Holds no secret itself."""
    return Path(__file__).resolve().parent.parent / "github" / "askpass.sh"


def has_remote(project_dir: Path, name: str = "origin") -> bool:
    output = _run(project_dir, "remote", check=False)
    return name in output.split()


def remote_url(project_dir: Path, name: str = "origin") -> str:
    return _run(project_dir, "remote", "get-url", name, check=False).strip()


def set_remote(project_dir: Path, url: str, name: str = "origin") -> None:
    """Point ``origin`` at a repository.

    Refuses a URL with credentials in it. Nothing in Open Nest builds one, which is
    exactly why the check is here: the leak this guards against is a future change that
    embeds the token "just to get the push working", and SPIKES.md section 17 measured
    that writing the token into ``.git/config``.
    """
    if "@" in url.split("//", 1)[-1].split("/", 1)[0]:
        raise GitError(
            "Open Nest refused to save that backup address because it contains a "
            "sign-in detail. The token belongs in the Keychain."
        )
    if has_remote(project_dir, name):
        _run(project_dir, "remote", "set-url", name, url)
    else:
        _run(project_dir, "remote", "add", name, url)


def current_branch(project_dir: Path) -> str:
    name = _run(project_dir, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    return "" if name in ("", "HEAD") else name


def create_branch(project_dir: Path, name: str) -> str:
    """Start a branch from the current position and switch to it."""
    _run(project_dir, "checkout", "-b", name)
    return name


def switch_branch(project_dir: Path, name: str) -> None:
    _run(project_dir, "checkout", name)


def branches(project_dir: Path) -> list[str]:
    """Every local branch name."""
    output = _run(project_dir, "branch", "--format=%(refname:short)", check=False)
    return [line.strip() for line in output.splitlines() if line.strip()]


def merge_fast_forward(project_dir: Path, branch: str) -> None:
    """Fold ``branch`` into the current one, refusing anything but a fast-forward.

    ``--ff-only`` on purpose: a merge commit or a conflict here would mean the two
    branches had genuinely diverged, and resolving that is not something this should
    attempt on a child's project behind their back.
    """
    _run(project_dir, "merge", "--ff-only", branch)


def delete_branch(project_dir: Path, name: str, *, force: bool = False) -> None:
    """Remove a local branch. ``-d`` unless forced, so unmerged work survives."""
    _run(project_dir, "branch", "-D" if force else "-d", name, check=False)


def diff_numstat(project_dir: Path, base: str, head: str) -> tuple[int, int]:
    """``(files, lines)`` changed between two refs.

    Deterministic, and deliberately not a question for the model -- the same reasoning
    ``execution/outputs.py`` follows for "which picture did this run make?". Comparing
    two trees cannot be wrong about what changed.
    """
    output = _run(project_dir, "diff", "--numstat", f"{base}..{head}", check=False)
    files = 0
    lines = 0
    for row in output.splitlines():
        parts = row.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        for count in parts[:2]:
            if count.isdigit():
                lines += int(count)
    return files, lines


def branch_exists(project_dir: Path, name: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(project_dir), "rev-parse", "--verify", f"refs/heads/{name}"],
        capture_output=True,
        timeout=30,
    )
    return result.returncode == 0


def unpushed_commits(project_dir: Path, branch: str, remote: str = "origin") -> list[str]:
    """Commits on ``branch`` that the remote does not have yet.

    With no remote-tracking refs -- a first push -- this is every commit, which is
    correct: all of them are about to be sent.
    """
    output = _run(
        project_dir,
        "rev-list",
        branch,
        "--not",
        f"--remotes={remote}",
        check=False,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def scan_commits(project_dir: Path, commits: list[str]) -> list[Finding]:
    """Secret-scan the file contents introduced by these commits.

    Section 29A asks for scanning before commits **and** before pushes, and they are
    genuinely different questions. ``commit()`` scans the working tree, so it cannot see
    a credential that was committed and then deleted -- the file is gone, the blob is
    not, and a push sends the blob. So this reads the blobs out of the commits
    themselves rather than looking at the checkout.
    """
    findings: list[Finding] = []
    for commit_ref in commits:
        listing = _run(
            project_dir,
            "diff-tree",
            "-r",
            "--no-commit-id",
            "--name-only",
            "--diff-filter=AM",
            commit_ref,
            check=False,
        )
        for relative in (line.strip() for line in listing.splitlines()):
            if not relative:
                continue
            try:
                size = _run(
                    project_dir, "cat-file", "-s", f"{commit_ref}:{relative}",
                    check=False,
                ).strip()
                if size and int(size) > MAX_SCAN_BYTES:
                    continue
            except (ValueError, GitError):
                pass
            try:
                blob = _run(project_dir, "show", f"{commit_ref}:{relative}", check=False)
            except GitError:
                continue
            findings.extend(scan_text(blob, relative))
    return findings


def push(
    project_dir: Path,
    token: str,
    *,
    branch: str = "",
    remote: str = "origin",
    set_upstream: bool = True,
    timeout: float = PUSH_TIMEOUT_SECONDS,
) -> str:
    """Send a branch to the remote, scanning what is about to leave first.

    The token is passed through the environment of this one subprocess and appears in no
    file and no argument. Raises :class:`Offline` when the remote could not be reached
    -- the push queue retries that and nothing else.
    """
    project_dir = Path(project_dir)
    target = branch or current_branch(project_dir)
    if not target:
        raise GitError("This project has no branch to back up yet.")

    findings = scan_commits(project_dir, unpushed_commits(project_dir, target, remote))
    if findings:
        raise SecretsFound(findings)

    argv = [
        "git",
        "-C", str(project_dir),
        # Nothing may cache this credential. See the note above.
        "-c", "credential.helper=",
        "-c", f"http.lowSpeedLimit={LOW_SPEED_BYTES}",
        "-c", f"http.lowSpeedTime={LOW_SPEED_SECONDS}",
        "push",
    ]
    if set_upstream:
        argv.append("--set-upstream")
    argv += [remote, target]

    helper = askpass_helper()
    if not os.access(helper, os.X_OK):
        # Git executes this, so the bit matters. It is set in the repository and git
        # preserves it on clone, which is how the product ships -- but a wheel build
        # does not, so this repairs it rather than failing on a file that is present.
        with contextlib.suppress(OSError):
            helper.chmod(0o700)
    if not os.access(helper, os.X_OK):
        raise GitError(
            "Open Nest cannot back up to GitHub because part of the application is "
            f"missing or cannot be run ({helper.name}). Repair Installation in "
            "Settings will restore it."
        )

    environment = {
        **os.environ,
        "GIT_ASKPASS": str(helper),
        "OPEN_NEST_GIT_USER": GIT_USERNAME,
        "OPEN_NEST_GIT_TOKEN": token,
        # A queued push runs with nobody watching. A git that stopped to ask for a
        # username on a terminal would hang the retry loop for as long as the app runs.
        "GIT_TERMINAL_PROMPT": "0",
    }

    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env=environment
        )
    except subprocess.TimeoutExpired as exc:
        raise Offline(
            "The backup to GitHub took too long and was stopped. Open Nest will try "
            "again later."
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"Open Nest could not back this project up: {exc}") from exc

    if result.returncode == 0:
        return target

    detail = _scrub((result.stderr or result.stdout).strip(), token)
    if _looks_offline(detail):
        raise Offline(
            "Open Nest could not reach GitHub, so this project is still only saved on "
            "this Mac. It will be backed up when the internet comes back."
        )
    if "authentication failed" in detail.lower() or "403" in detail:
        raise PushRejected(
            "GitHub would not accept the backup. A parent may need to reconnect "
            "GitHub in Settings."
        )
    raise PushRejected(
        "Open Nest could not back this project up to GitHub.\n\n"
        + "\n".join(detail.splitlines()[-5:])
    )


def _scrub(text: str, token: str) -> str:
    """Remove the token from git's output before anyone sees it.

    git does not normally echo a credential, and ``osxkeychain`` being disabled means
    there is no helper to quote one back. This exists for the case where a future git,
    or a proxy in between, does.
    """
    cleaned = text or ""
    if token:
        cleaned = cleaned.replace(token, "[token removed]")
        if len(token) > 12:
            cleaned = cleaned.replace(token[:12], "[token removed]")
    return cleaned


def _looks_offline(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        phrase in lowered
        for phrase in (
            "could not resolve host",
            "failed to connect",
            "could not resolve proxy",
            "operation too slow",
            "connection timed out",
            "network is unreachable",
            "network is down",
            "temporary failure in name resolution",
            "ssl_connect",
            "timed out",
        )
    )
