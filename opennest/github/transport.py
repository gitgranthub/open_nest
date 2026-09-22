"""How Open Nest reaches the GitHub API, and how it is replaced in tests.

The same decision ``ai/cloud.py`` made, for the same reason: a provider is handed
something that turns a request into a response, so the whole of Phase 9 can be tested
without opening a socket. No test in this suite reaches the network, and adding GitHub
backup did not change that.

No SDK. Section 29A needs four calls -- device code, token, ``GET /user``, create repo,
create PR -- and PyGithub would pull a dependency tree onto a work-managed machine to
save very little. ``requests`` is already an application dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

#: Long enough for a slow connection, short enough that a parent does not think the
#: window has frozen. The device-flow poll interval is longer than this by design.
TIMEOUT_SECONDS = 20


class GitHubError(Exception):
    """A GitHub request failed, phrased for a parent.

    Never carries the token. :func:`opennest.ai.cloud.redact` is applied to any server
    text before it reaches here, because an exception message ends up in a dialog and
    eventually in a bug report -- section 22 names logs explicitly.
    """

    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class OfflineError(GitHubError):
    """GitHub could not be reached at all.

    Distinct from every other failure on purpose: section 34 makes being offline an
    ordinary state rather than an error, so the queue retries this and gives up on the
    rest.
    """


@dataclass(frozen=True)
class Response:
    status: int
    body: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Transport(Protocol):
    """Swapped wholesale in tests."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Response: ...


class RequestsTransport:
    """The real one."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Response:
        import requests

        try:
            response = requests.request(
                method,
                url,
                headers={"Accept": "application/json", **(headers or {})},
                json=body,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout as exc:
            raise OfflineError(
                "GitHub did not answer in time. Open Nest will try again later."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise OfflineError(
                "Open Nest could not reach GitHub. It will try again when this Mac is "
                "back online."
            ) from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {"data": payload}
        return Response(response.status_code, payload)


def default() -> Transport:
    return RequestsTransport()


def raise_for_error(response: Response, *, token: str | None = None) -> None:
    """Turn a failed response into something a parent can act on.

    Lives here rather than in ``auth`` or ``api`` because both need it and it is about
    HTTP rather than about either one. Every message is run through
    :func:`opennest.ai.cloud.redact` first: an exception message ends up in a dialog, a
    traceback and eventually a bug report, and section 22 names logs explicitly.
    """
    if response.ok:
        return

    from opennest.ai.cloud import redact

    body = response.body
    described = _text(body.get("error_description")) or _text(body.get("message"))
    error = _text(body.get("error"))
    detail = redact(described, token) if described else ""

    if error == "incorrect_client_credentials":
        raise GitHubError(
            "GitHub did not recognise this copy of Open Nest. A parent cannot fix this "
            "-- it needs a new version of the application.",
            status=response.status,
        )
    if response.status == 401:
        raise GitHubError(
            "The GitHub connection is no longer valid. A parent can reconnect in "
            "Settings.",
            status=401,
        )
    if response.status == 403:
        # Distinguished from 401 deliberately. Phase 6 learned this the hard way in
        # ai/cloud.py: telling a parent their good credential was rejected, when the
        # real problem was a permission, sends them to fix the wrong thing.
        raise GitHubError(
            "GitHub refused the request. "
            + (detail or "The account may not have permission for this."),
            status=403,
        )
    if response.status == 404:
        raise GitHubError(
            "GitHub could not find that." + (f"\n\n{detail}" if detail else ""),
            status=404,
        )

    raise GitHubError(
        "GitHub could not complete that request." + (f"\n\n{detail}" if detail else ""),
        status=response.status,
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
