"""Putting a project on GitHub, and the pull-request policy -- WORKORDER_01 section 29A.

Section 29A's chain, and the one rule that matters most in it:

    local autosave -> local Git commit -> background push to private GitHub repository

The push is the *last* link and the only one that can fail for reasons outside this Mac,
so it is the only one allowed to be slow. Nothing here blocks a child: a checkpoint is
saved locally and the push is handed to :mod:`opennest.github.push_queue`.

**The PR policy's three modes are section 35A's, not invented ones.** "Save them
normally" (the default), "Create a review branch", and "Create a GitHub Pull Request".
Section 29A adds the reason the middle one exists: parent review, and safer large
refactors, "without adding visible complexity to the child's normal experience".

**A review branch is created before the change, never after.** Section 29A's diagram
branches first, and the alternative is worse than it looks: committing to ``main`` and
then moving the branch means rewinding ``main``, and this codebase deliberately has no
reset anywhere (``git_manager.restore`` is append-only for the same reason). Branching
first also makes section 29A's "small successful modifications can remain ordinary local
commits" fall out for free -- a small change is fast-forwarded back into ``main`` and the
branch disappears.

**What counts as "large" is a heuristic and is labelled as one.** :data:`LARGE_FILES`
and :data:`LARGE_LINES` were not measured; nobody has watched a child's session and
counted. It is deterministic -- computed from the diff, never asked of the model -- but
the thresholds are a guess, in the same way ``history_search.CUES`` is a guess. Measure
it before trusting it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opennest.github import api, auth
from opennest.github.push_queue import Outcome, PushQueue
from opennest.github.transport import GitHubError, Transport
from opennest.github.transport import default as default_transport
from opennest.security.permissions import (
    PR_POLICIES,
    PR_POLICY_BRANCH,
    PR_POLICY_NORMAL,
    PR_POLICY_PULL_REQUEST,
)
from opennest.versioning import git_manager

#: Section 35A's three modes. Defined in ``security.permissions`` with the field they
#: validate and aliased here, so there is one list rather than two that can drift.
POLICY_NORMAL = PR_POLICY_NORMAL
POLICY_BRANCH = PR_POLICY_BRANCH
POLICY_PULL_REQUEST = PR_POLICY_PULL_REQUEST
POLICIES = PR_POLICIES

#: A change touching this many files, or this many added-plus-removed lines, is "large".
#: Unmeasured -- see the module docstring.
LARGE_FILES = 3
LARGE_LINES = 120

#: Where a review branch's name comes from. Section 29A's example is
#: ``buildlab/feature-powerups``.
BRANCH_PREFIX = "opennest"

#: The line in the generated .gitignore that keeps chat archives local. Section 38:
#: "no full AI conversation archives unless explicitly enabled by the parent".
CONVERSATIONS_IGNORE = ".opennest/conversations/"


@dataclass(frozen=True)
class Readiness:
    """Whether backup can run, and the one sentence explaining why not."""

    ready: bool
    reason: str = ""


def readiness(controls, credentials) -> Readiness:
    """Whether a project may be backed up right now.

    Three separate facts with three different remedies, kept separate for the same
    reason ``router.why_unavailable`` keeps the cloud ones separate: a parent needs to
    know which thing to go and fix.
    """
    if not auth.configured():
        return Readiness(
            False,
            "This version of Open Nest was not built with GitHub backup.",
        )
    if not controls.github_private_backup:
        return Readiness(False, "GitHub backup is turned off in Parent Settings.")
    if not auth.connected(credentials):
        return Readiness(False, "No GitHub account is connected yet.")
    if not git_manager.git_available():
        return Readiness(False, "Git is not installed on this Mac.")
    return Readiness(True)


def policy_of(controls) -> str:
    value = getattr(controls, "github_pr_policy", POLICY_NORMAL)
    return value if value in POLICIES else POLICY_NORMAL


# --------------------------------------------------------------- the repository

def ensure_repository(
    project,
    credentials,
    *,
    transport: Transport | None = None,
) -> api.Repository:
    """Make sure this project has a private GitHub repository and a remote.

    Idempotent: an existing repository is adopted rather than treated as a clash, so
    reopening a project or running setup again does not break the backup.
    """
    token = credentials.get_github_token()
    if not token:
        raise GitHubError("No GitHub account is connected.")
    carrier = transport if transport is not None else default_transport()
    repository = api.create_repository(token, project.name, carrier)
    if not repository.clone_url:
        raise GitHubError("GitHub did not say where the new repository is.")
    # The clean URL, with no credential in it. SPIKES.md section 17.
    git_manager.set_remote(project.directory, repository.clone_url)
    return repository


# --------------------------------------------------------------- the PR policy

def review_branch_name(project_dir: Path, controls) -> str:
    """The branch an upcoming AI change should happen on, or "" for none."""
    if policy_of(controls) == POLICY_NORMAL:
        return ""
    existing = set(git_manager.branches(project_dir))
    number = 1
    while f"{BRANCH_PREFIX}/change-{number}" in existing:
        number += 1
    return f"{BRANCH_PREFIX}/change-{number}"


def begin_change(project_dir: Path, controls) -> str:
    """Start a review branch if the policy calls for one. Returns its name, or "".

    Called before an AI change. Never raises into the turn: a backup arrangement that
    cannot be set up must not stop a child from asking for something.
    """
    if policy_of(controls) == POLICY_NORMAL:
        return ""
    if not git_manager.is_repo(project_dir):
        return ""
    try:
        base = git_manager.current_branch(project_dir)
        if base != "main":
            # Already on a review branch -- a previous change is still open. Stay there
            # rather than nesting branches off each other.
            return base
        return git_manager.create_branch(project_dir, review_branch_name(project_dir, controls))
    except git_manager.GitError:
        return ""


def is_large(files: int, lines: int) -> bool:
    return files >= LARGE_FILES or lines >= LARGE_LINES


@dataclass(frozen=True)
class ChangeResult:
    """What happened to a change under the policy. For a parent, never for a child."""

    #: The branch the work ended up on. "main" when it was folded back.
    branch: str = "main"
    large: bool = False
    pull_request: api.PullRequest | None = None
    #: Set when the policy could not be carried out. The work is still saved locally.
    problem: str = ""


def finish_change(
    project,
    branch: str,
    controls,
    credentials,
    *,
    queue: PushQueue | None = None,
    transport: Transport | None = None,
) -> ChangeResult:
    """Apply the PR policy now that the change is committed.

    A small change is folded back into ``main`` and the branch removed, which is
    section 29A's "small successful modifications can remain ordinary local commits". A
    large one stays on its branch, is queued for push, and gets a pull request when the
    policy says so.
    """
    project_dir = project.directory
    if not branch or branch == "main" or not git_manager.is_repo(project_dir):
        return ChangeResult()

    files, lines = git_manager.diff_numstat(project_dir, "main", branch)
    large = is_large(files, lines)

    if not large:
        try:
            git_manager.switch_branch(project_dir, "main")
            git_manager.merge_fast_forward(project_dir, branch)
            git_manager.delete_branch(project_dir, branch)
        except git_manager.GitError as exc:
            # The work is committed on the branch either way; nothing is lost.
            return ChangeResult(branch=branch, large=False, problem=str(exc))
        return ChangeResult(branch="main", large=False)

    if queue is not None:
        queue.enqueue(project_dir, branch)
        queue.enqueue(project_dir, "main")

    if policy_of(controls) != POLICY_PULL_REQUEST:
        return ChangeResult(branch=branch, large=True)

    # A pull request needs the branch to be on GitHub first, so this is the one part of
    # the policy that cannot be queued for later.
    token = credentials.get_github_token()
    if not token:
        return ChangeResult(branch=branch, large=True, problem="No GitHub account is connected.")
    try:
        repository = ensure_repository(project, credentials, transport=transport)
        git_manager.push(project_dir, token, branch="main")
        git_manager.push(project_dir, token, branch=branch)
        pull = api.create_pull_request(
            token,
            repository.full_name,
            transport if transport is not None else default_transport(),
            head=branch,
            base="main",
            title=f"Open Nest: changes to {project.name}",
            body=(
                f"Open Nest made a large change to **{project.name}** "
                f"({files} file{'s' if files != 1 else ''}, {lines} lines).\n\n"
                "This pull request exists so a parent can look before it becomes part "
                "of the project."
            ),
        )
    except (GitHubError, git_manager.GitError) as exc:
        if queue is not None:
            queue.enqueue(project_dir, branch)
        return ChangeResult(branch=branch, large=True, problem=str(exc))
    return ChangeResult(branch=branch, large=True, pull_request=pull)


# --------------------------------------------------------------- pushing

def after_checkpoint(
    project,
    controls,
    credentials,
    queue: PushQueue,
) -> bool:
    """Queue a backup for a project that has just saved a checkpoint.

    Returns whether anything was queued. Deliberately does not push: section 34 wants
    the child's next action to start immediately, and a push takes as long as it takes.
    """
    if not readiness(controls, credentials).ready:
        return False
    branch = git_manager.current_branch(project.directory)
    if not branch:
        return False
    queue.enqueue(project.directory, branch)
    return True


def drain(credentials, queue: PushQueue) -> Outcome:
    """Send whatever is waiting. Safe to call when nothing is connected."""
    token = credentials.get_github_token()
    if not token:
        return Outcome()
    return queue.drain(token)


# --------------------------------------------------------------- section 38

def apply_conversation_policy(project_dir: Path, include: bool) -> bool:
    """Keep chat archives out of the backup, or let them in.

    Section 29A offers this as a setting and section 38 sets its default to No. The
    mechanism is the generated ``.gitignore`` rather than anything new: an archive that
    is never committed cannot be pushed, and a parent who turns this on is choosing to
    version their child's conversations with the project.

    Returns whether the file changed.
    """
    gitignore = Path(project_dir) / ".gitignore"
    try:
        text = gitignore.read_text(encoding="utf-8")
    except OSError:
        return False

    lines = text.splitlines()
    present = any(line.strip() == CONVERSATIONS_IGNORE for line in lines)
    if include and present:
        kept = [line for line in lines if line.strip() != CONVERSATIONS_IGNORE]
        gitignore.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return True
    if not include and not present:
        gitignore.write_text(
            text.rstrip("\n") + f"\n{CONVERSATIONS_IGNORE}\n", encoding="utf-8"
        )
        return True
    return False
