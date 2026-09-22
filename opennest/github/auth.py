"""Connecting the parent's GitHub account -- decision D1, resolved as OAuth device flow.

WORKORDER_01 section 29A: "Prefer secure OAuth/device authorization where possible
rather than asking users to paste a long-lived GitHub password or personal access
token." Section 35A lists the same preference order and says the account is the
parent's.

D1 had three candidates and the other two were rejected for measured reasons:

- **The ``gh`` CLI.** Measured on the development machine: ``gh auth status`` reports
  whichever account happens to be logged in -- ambient state the wizard never chose and
  cannot see. Open Nest would display "Connected as X" for a fact it does not own,
  could not revoke a token it never held, and on a parent's Mac ``gh`` is a Homebrew
  developer tool that is very probably absent. Open Nest never shells to ``gh``.
- **A personal access token.** Works, but section 29A says to avoid it unless nothing
  better is supported, and something better is.

What device flow costs, recorded rather than hidden: a **classic OAuth App with the
``repo`` scope reaches every repository the parent can see**, including organisation
repositories, because classic OAuth Apps have no per-repository scoping. Accepted as a
documented V1 trade-off by developer direction. The tightening option is a GitHub App
with an installation scoped to only the repositories Open Nest creates; that is future
security-hardening work and deliberately not Phase 9.

**The token lives in the Keychain and nowhere else.** Not in ``installation.json``, not
in ``settings.json``, not in ``.git/config``, not in argv, not in a log. SPIKES.md
section 17 measures the ``.git/config`` half rather than asserting it, because the
obvious remote URL leaks and needed to be shown to leak.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from opennest.github.transport import (
    GitHubError,
    OfflineError,
    Transport,
    raise_for_error,
)

#: Open Nest's registered OAuth App. Public by design -- a device-flow client ID ships
#: inside every copy of the application and is not a secret, which is exactly why device
#: flow suits a desktop app distributed to other people's Macs. There is no client
#: secret, because device flow does not use one.
#:
#: When this is empty Open Nest says GitHub backup is unavailable and offers no connect
#: button: nothing here fakes a connection. Registered and verified in Phase 9 --
#: SPIKES.md section 17C is the real device-flow run against this client ID.
CLIENT_ID = "Ov23li7JhMufrSxhqCDs"

#: Section 29A needs to create private repositories, push to them, and open pull
#: requests. ``repo`` is the one classic scope that covers those three. Nothing asks for
#: ``delete_repo``, ``admin:org`` or ``user`` -- the minimal grant rule from HANDOFF
#: section 5 applies to an OAuth scope as much as to a serial port.
SCOPE = "repo"

DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"

#: GitHub's grant type for device flow, spelled exactly as the RFC requires.
GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

#: A floor under the poll interval. GitHub returns one (5 s today) and answers
#: ``slow_down`` if it is ignored; this stops a bad value producing a hot loop.
MINIMUM_INTERVAL = 5


@dataclass(frozen=True)
class DeviceCode:
    """What the parent has to be shown, and what Open Nest polls with.

    ``user_code`` is what they type at ``verification_uri``. ``device_code`` is the
    secret half and is never displayed -- it is not a lasting credential, but showing it
    would teach a parent that codes on this screen are for typing in.
    """

    user_code: str
    verification_uri: str
    device_code: str
    interval: int = MINIMUM_INTERVAL
    expires_in: int = 900

    @property
    def instructions(self) -> str:
        return (
            f"1. Open {self.verification_uri} in a browser.\n"
            f"2. Sign in to the parent's GitHub account.\n"
            f"3. Enter this code:  {self.user_code}\n"
            f"4. Approve Open Nest, then come back here."
        )


@dataclass(frozen=True)
class Pending:
    """The parent has not finished approving yet. Keep waiting."""

    #: Seconds to wait before asking again. GitHub raises this via ``slow_down``.
    interval: int = MINIMUM_INTERVAL


@dataclass(frozen=True)
class Connected:
    """Approved. The token is already in the Keychain by the time this exists.

    Deliberately carries the account login and **not** the token: a result object gets
    logged, repr'd into a traceback, and passed around a UI layer.
    """

    login: str


def configured() -> bool:
    """Whether this build has an OAuth App to connect with.

    False means the GitHub feature is genuinely unavailable, and the UI says so. Phase 8
    set the precedent: ``installation.json`` carried ``github_enabled`` as always-False
    and the wizard stated plainly that backup was not available, rather than showing a
    button that could not work.
    """
    return bool(CLIENT_ID)


def begin(transport: Transport) -> DeviceCode:
    """Ask GitHub for a code the parent can approve."""
    if not configured():
        raise GitHubError(
            "This copy of Open Nest was not built with GitHub backup, so there is "
            "nothing to connect to."
        )
    response = transport.request(
        "POST",
        DEVICE_CODE_URL,
        body={"client_id": CLIENT_ID, "scope": SCOPE},
    )
    raise_for_error(response)
    body = response.body
    code = _text(body.get("user_code"))
    device = _text(body.get("device_code"))
    if not code or not device:
        raise GitHubError("GitHub did not send a sign-in code. Nothing was changed.")
    return DeviceCode(
        user_code=code,
        verification_uri=_text(body.get("verification_uri")) or "https://github.com/login/device",
        device_code=device,
        interval=max(_number(body.get("interval"), MINIMUM_INTERVAL), MINIMUM_INTERVAL),
        expires_in=_number(body.get("expires_in"), 900),
    )


def poll(code: DeviceCode, transport: Transport, credentials) -> Pending | Connected:
    """Ask once whether the parent has approved yet.

    One attempt per call, so the caller owns the waiting. A UI has to stay responsive
    and be cancellable while a parent is off in a browser, and a helper that blocks for
    fifteen minutes cannot be either.
    """
    response = transport.request(
        "POST",
        ACCESS_TOKEN_URL,
        body={
            "client_id": CLIENT_ID,
            "device_code": code.device_code,
            "grant_type": GRANT_TYPE,
        },
    )
    body = response.body
    error = _text(body.get("error"))

    if error == "authorization_pending":
        return Pending(code.interval)
    if error == "slow_down":
        # GitHub tells us how much slower; its own docs add five seconds.
        return Pending(max(_number(body.get("interval"), code.interval + 5), code.interval + 5))
    if error == "expired_token":
        raise GitHubError(
            "That sign-in code expired before it was approved. Press Connect again to "
            "get a new one."
        )
    if error == "access_denied":
        raise GitHubError(
            "The GitHub sign-in was declined, so nothing was connected."
        )
    if error:
        # The device-flow token endpoint answers **HTTP 200 with an error in the body**,
        # so ``raise_for_error`` sees a successful response and returns without raising.
        # Anything unrecognised has to be raised here or it falls through to the
        # no-token branch below and reports the wrong thing entirely.
        described = _text(body.get("error_description"))
        raise GitHubError(
            "GitHub could not finish the sign-in."
            + (f"\n\n{described}" if described else f"\n\n({error})")
        )

    token = _text(body.get("access_token"))
    if not token:
        raise_for_error(response)
        raise GitHubError("GitHub approved the sign-in but sent no token.")

    # Saved before the account lookup: the token is the thing worth keeping, and a
    # failed `GET /user` should not throw away an approval the parent just gave.
    credentials.save_github_token(token)
    return Connected(login=account(credentials, transport) or "")


def account(credentials, transport: Transport) -> str | None:
    """The login of the connected account, or None when nothing is connected.

    Asked of GitHub rather than remembered, so "Connected as X" is something Open Nest
    actually knows. A token the parent revoked on github.com stops answering here, which
    is the case ambient ``gh`` authentication could never report honestly.
    """
    token = credentials.get_github_token()
    if not token:
        return None
    try:
        response = transport.request("GET", USER_URL, headers=headers(token))
    except OfflineError:
        return None
    if response.status == 401:
        return None
    raise_for_error(response, token=token)
    return _text(response.body.get("login")) or None


def connected(credentials) -> bool:
    """Whether a token is stored. Does not reach the network.

    Used where a dialog must not block -- the Settings page drawing itself, for one.
    ``account()`` is the authoritative answer and needs the internet.
    """
    return credentials.has_github_token()


def disconnect(credentials) -> bool:
    """Forget the token. Returns whether there was one.

    Real, unlike a ``gh``-based connection: Open Nest holds this token, so removing it
    removes the access. What it cannot do is revoke the grant on GitHub's side -- that
    is a button on github.com, and :data:`REVOKE_HINT` is what a parent is told.
    """
    return credentials.delete_github_token()


REVOKE_HINT = (
    "Open Nest has forgotten the GitHub connection on this Mac. To also remove Open "
    "Nest's access on GitHub itself, visit:\n\n"
    "    https://github.com/settings/applications"
)


def headers(token: str) -> dict[str, str]:
    """Authorisation for an API call. The only place a token becomes a header."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def wait_for_approval(
    code: DeviceCode,
    transport: Transport,
    credentials,
    *,
    should_continue=None,
    sleep=time.sleep,
) -> Connected | None:
    """Poll until the parent approves, declines, or the caller gives up.

    Returns None when ``should_continue`` stops being true -- a cancelled connection is
    not a failure. ``sleep`` is injected so a test does not spend the real interval.
    """
    deadline = time.monotonic() + code.expires_in
    interval = code.interval
    while time.monotonic() < deadline:
        if should_continue is not None and not should_continue():
            return None
        outcome = poll(code, transport, credentials)
        if isinstance(outcome, Connected):
            return outcome
        interval = outcome.interval
        sleep(interval)
    raise GitHubError(
        "That sign-in code expired before it was approved. Press Connect again to get "
        "a new one."
    )


# --------------------------------------------------------------------------- internals

def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return fallback
    return fallback
