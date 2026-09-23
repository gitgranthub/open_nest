"""The updateable half of the model catalogue.

Section 28 of the Phase 11 work order: a small remote metadata file, controlled by the
Open Nest project, that can revise which models are recommended without shipping a new
application. Metadata, never model hosting -- it describes what exists; the weights come
from where they always came from.

Four properties this is built around, each of which is a way it must not hurt anybody:

**Being offline is a normal answer, not an error** (section 46). Every failure here --
no network, a 404, a timeout, a truncated body, a payload that will not parse -- results
in the same thing: nothing changes and the bundled catalogue is used.

**No launch ever waits on this** (section 45). Nothing in this module is called during
startup. A refresh happens when a parent presses a button, and what the rest of Open Nest
reads is :func:`cached`, which touches one local file.

**A refresh downloads metadata, never a model** (section 30). The body is capped at a
size a catalogue could not plausibly exceed, and the only thing a successful refresh
changes is a list of choices.

**The URL is a constant, and only https** (section 29). A catalogue cannot name the
place the next catalogue comes from, so there is no way to walk this off somewhere else.

No catalogue is published yet, which makes the not-available path the live one and the
success path the tested one. That is recorded rather than hidden: see
:data:`CATALOG_URL`.
"""

from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

#: Where an Open Nest catalogue would be published. The repository is the project's own
#: and is public -- the update check in ``setup/updates.py`` already depends on that,
#: verified in SPIKES.md section 17E. **Nothing is published at this path yet**, so in
#: this release a refresh answers "no catalogue" and the bundled list stands. That is
#: the designed fallback rather than a fault, and it is the code path every installation
#: currently takes.
CATALOG_URL = (
    "https://raw.githubusercontent.com/gitgranthub/open_nest/main/catalog/models.json"
)

#: A catalogue is a few kilobytes of metadata. This is two orders of magnitude of room
#: and still small enough that a hostile or broken server cannot make Open Nest read a
#: large file into memory.
MAX_BYTES = 1_000_000

#: Short. A parent is watching, and the honest answer when a server is slow is the
#: bundled list rather than a spinner.
TIMEOUT_SECONDS = 10

#: How long a cached catalogue is treated as current. Section 45 asks for a reasonable
#: interval and leaves the number to implementation; a day matches how often a model
#: recommendation could plausibly change, and staleness costs nothing because the cache
#: is used either way.
MAX_AGE_SECONDS = 24 * 60 * 60

CACHE_FILENAME = "model_catalog.json"


@dataclass(frozen=True)
class RefreshResult:
    """What a refresh did, in terms a parent can be told."""

    ok: bool
    message: str
    #: ``updated`` | ``unchanged`` | ``unavailable`` | ``rejected``
    outcome: str = "unavailable"
    payload: dict | None = None


def cache_file() -> Path:
    from opennest import paths

    return paths.app_support_dir() / CACHE_FILENAME


def cached() -> dict | None:
    """The last good catalogue, or None.

    Never raises. A cache that will not parse is treated as absent and left on disk for
    somebody to look at -- the same stance ``setup/state.py`` takes with a damaged
    installation record, and for the same reason: nothing here has a destructive step.
    """
    path = cache_file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def cache_age_seconds() -> float | None:
    """How old the cached catalogue is, or None when there is not one."""
    try:
        return max(0.0, time.time() - cache_file().stat().st_mtime)
    except OSError:
        return None


def is_stale() -> bool:
    age = cache_age_seconds()
    return age is None or age > MAX_AGE_SECONDS


def refresh(*, url: str | None = None, fetch=None) -> RefreshResult:
    """Ask for a newer catalogue. Called only when somebody presses a button.

    ``fetch`` is injectable for the same reason the GitHub transport is: no test in this
    suite may depend on a server being reachable, and section 51 says so directly.
    """
    target = url or CATALOG_URL
    if not target.lower().startswith("https://"):
        # Belt and braces around a constant, so that a future edit making this
        # configurable cannot quietly make it plaintext.
        return RefreshResult(False, "The model list can only be checked over https.",
                             "rejected")

    getter = fetch or _http_get
    try:
        body = getter(target, TIMEOUT_SECONDS, MAX_BYTES)
    except Exception:
        # Deliberately broad. Every way this can fail -- DNS, TLS, a captive portal, a
        # 404 because nothing is published -- means the same thing to a parent.
        return RefreshResult(
            False, "You're offline. Using the saved model list.", "unavailable"
        )

    if body is None:
        return RefreshResult(
            False, "You're offline. Using the saved model list.", "unavailable"
        )

    try:
        payload = json.loads(body)
    except ValueError:
        return RefreshResult(False, "The model list could not be read.", "rejected")
    if not isinstance(payload, dict):
        return RefreshResult(False, "The model list could not be read.", "rejected")

    from opennest.models.catalog import CatalogError, validate

    try:
        kept, refused = validate(payload)
    except CatalogError as exc:
        return RefreshResult(False, str(exc), "rejected")

    unchanged = cached() == payload
    _write_cache(payload)
    if unchanged:
        return RefreshResult(True, "Your model list is up to date.", "unchanged", payload)

    note = "Model list updated."
    if refused:
        # Said out loud rather than swallowed: fewer models than the server offered is
        # something a parent should hear about once.
        note += f" {len(refused)} entries were not understood and were ignored."
    return RefreshResult(True, note, "updated", payload)


def _write_cache(payload: dict) -> None:
    from opennest.versioning.autosave import atomic_write_text

    path = cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")


def forget() -> None:
    """Drop the cached catalogue. Used by Repair, and by tests."""
    with contextlib.suppress(OSError):
        cache_file().unlink()


def _http_get(url: str, timeout: int, max_bytes: int) -> str | None:
    """One GET, capped. The only outbound request this module makes."""
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OpenNest"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            return None
        # Read one byte past the cap so an oversized body is detected rather than
        # silently truncated into something that might still parse.
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        return None
    return body.decode("utf-8", "replace")
