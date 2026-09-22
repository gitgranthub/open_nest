"""The GitHub REST calls Phase 9 needs: a private repository, and a pull request.

WORKORDER_01 section 29A, and section 38's list of what GitHub backup defaults to.

**Private is not a default here, it is the only option.** Section 29A says "Private
should be the default for child-created projects" and "Do not automatically make
repositories public"; :func:`create_repository` passes ``private: true`` unconditionally
and there is no parameter to change it. A default can be overridden by a caller that
means well and a flag that arrives from a config file; a constant cannot. Making a
child's repository public is a decision for a person on github.com, not for this
application.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from opennest.github.auth import headers
from opennest.github.transport import GitHubError, Transport, raise_for_error

API = "https://api.github.com"

#: Section 29A's example is ``BuildLab-Asteroid-Game``. Same shape, our name.
REPO_PREFIX = "OpenNest"

#: GitHub allows letters, digits, hyphen, underscore and dot. Everything else in a
#: child's project name -- spaces, apostrophes, emoji -- becomes a hyphen.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_RUNS = re.compile(r"-{2,}")

#: GitHub's own limit.
MAX_NAME = 100


@dataclass(frozen=True)
class Repository:
    """A repository that exists on GitHub."""

    full_name: str
    clone_url: str
    private: bool
    html_url: str = ""
    default_branch: str = "main"

    @property
    def owner(self) -> str:
        return self.full_name.split("/")[0] if "/" in self.full_name else ""


@dataclass(frozen=True)
class PullRequest:
    number: int
    html_url: str
    title: str


def repository_name(project_name: str) -> str:
    """A GitHub-legal repository name for a child's project.

    ``My Asteroid Game!`` becomes ``OpenNest-My-Asteroid-Game``. The prefix means a
    parent looking at their repository list can tell which ones came from here.
    """
    cleaned = _UNSAFE.sub("-", (project_name or "").strip())
    cleaned = _RUNS.sub("-", cleaned).strip("-._")
    if not cleaned:
        cleaned = "Project"
    name = f"{REPO_PREFIX}-{cleaned}"
    return name[:MAX_NAME].rstrip("-._")


def create_repository(
    token: str,
    project_name: str,
    transport: Transport,
    *,
    description: str = "",
) -> Repository:
    """Create a private repository for a project, or return the existing one.

    "Already exists" is treated as success rather than as an error. A parent who runs
    setup again, or opens a project on a second Mac, should get their backup working --
    not a failure about a repository that is exactly the one wanted.
    """
    name = repository_name(project_name)
    response = transport.request(
        "POST",
        f"{API}/user/repos",
        headers=headers(token),
        body={
            "name": name,
            # Section 29A. Not a parameter, not a setting, not overridable.
            "private": True,
            "description": description or f"Open Nest backup of {project_name}.",
            "auto_init": False,
            "has_issues": False,
            "has_wiki": False,
            "has_projects": False,
        },
    )
    if response.status == 422 and _already_exists(response.body):
        existing = find_repository(token, name, transport)
        if existing is not None:
            return existing
    raise_for_error(response, token=token)
    return _repository(response.body)


def find_repository(token: str, name: str, transport: Transport) -> Repository | None:
    """Look up ``name`` under the authenticated account. None when it is not there."""
    login = _login(token, transport)
    if not login:
        return None
    response = transport.request(
        "GET", f"{API}/repos/{login}/{name}", headers=headers(token)
    )
    if response.status == 404:
        return None
    raise_for_error(response, token=token)
    return _repository(response.body)


def create_pull_request(
    token: str,
    full_name: str,
    transport: Transport,
    *,
    head: str,
    base: str,
    title: str,
    body: str = "",
) -> PullRequest:
    """Open a pull request for a review branch (section 29A's PR policy)."""
    response = transport.request(
        "POST",
        f"{API}/repos/{full_name}/pulls",
        headers=headers(token),
        body={"head": head, "base": base, "title": title, "body": body},
    )
    raise_for_error(response, token=token)
    number = response.body.get("number")
    if not isinstance(number, int):
        raise GitHubError("GitHub did not say which pull request it created.")
    return PullRequest(
        number=number,
        html_url=_text(response.body.get("html_url")),
        title=_text(response.body.get("title")) or title,
    )


def delete_repository(token: str, full_name: str, transport: Transport) -> bool:
    """Remove a repository. Only used to clean up after a verification run.

    Not reachable from the application: nothing in Open Nest's UI deletes a child's
    backup, and the ``repo`` scope does not grant ``delete_repo`` anyway, so this needs
    a token that was deliberately given more. It exists so SPIKES.md section 17's real
    run does not leave litter on a real account.
    """
    response = transport.request(
        "DELETE", f"{API}/repos/{full_name}", headers=headers(token)
    )
    if response.status == 404:
        return False
    raise_for_error(response, token=token)
    return True


# --------------------------------------------------------------------------- internals

def _login(token: str, transport: Transport) -> str:
    response = transport.request("GET", f"{API}/user", headers=headers(token))
    raise_for_error(response, token=token)
    return _text(response.body.get("login"))


def _already_exists(body: dict) -> bool:
    errors = body.get("errors")
    if not isinstance(errors, list):
        return False
    return any(
        isinstance(item, dict) and "already exists" in str(item.get("message", "")).lower()
        for item in errors
    )


def _repository(body: dict) -> Repository:
    return Repository(
        full_name=_text(body.get("full_name")),
        clone_url=_text(body.get("clone_url")),
        private=bool(body.get("private")),
        html_url=_text(body.get("html_url")),
        default_branch=_text(body.get("default_branch")) or "main",
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
