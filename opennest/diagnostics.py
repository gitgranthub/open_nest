"""The diagnostic report behind "Export Diagnostic Log".

WORKORDER_01 section 33 asks for internal logs for debugging and for an export button
for support, and is explicit about what must never be in them: API keys, passwords,
Keychain contents, GitHub credentials.

Open Nest has no logging subsystem yet -- nothing writes a log file, so there is nothing
to leak from one. What this builds instead is a report composed *at the moment it is
asked for*, from live state: where things are on disk, whether the sandbox works, what
is in the model catalogue, and which switches are set. That is what a person debugging
an installation actually needs, and it has a property a log file does not: there is no
accumulated history to audit, so "no key has ever been written to a log" is a property
of the design rather than a promise about past behaviour.

Two rules hold it to that:

- **Credentials are reported as a yes or a no, never as a value.** ``has_key`` returns a
  boolean and that boolean is all that appears.
- **The finished text is scanned before it is returned.** :func:`report` runs the same
  secret scanner that guards Git commits over its own output, so a future section that
  accidentally interpolates something credential-shaped is redacted rather than shipped.
  ``test_the_diagnostic_report_never_contains_a_key`` saves a real-looking key first and
  then checks.
"""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone

from opennest import APP_NAME, __version__, paths
from opennest.ai import cloud, router
from opennest.security import keychain, permissions, process_sandbox


def report(
    controls: permissions.ParentControls | None = None,
    credentials: keychain.Credentials | None = None,
) -> str:
    """The whole report, scrubbed. Safe to write to a file and email to support."""
    controls = controls if controls is not None else permissions.current()
    store = credentials or keychain.default()

    lines: list[str] = [
        f"{APP_NAME} diagnostic report",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "This report contains no API keys, passwords or Keychain contents.",
        "",
    ]
    lines += _section("Version", _version_lines())
    lines += _section("Locations", paths.paths_report().splitlines()[1:])
    lines += _section("Security", _security_lines(store))
    lines += _section("Parent controls", _controls_lines(controls))
    lines += _section("Models", _model_lines())

    # The report describes a Keychain; it must never quote one. Scanned rather than
    # trusted, for the same reason memory files are.
    return cloud.redact("\n".join(lines))


def _section(title: str, body: list[str]) -> list[str]:
    return [title.upper(), *(f"  {line.strip()}" for line in body if line.strip()), ""]


def _version_lines() -> list[str]:
    return [
        f"{APP_NAME} {__version__}",
        f"Python {sys.version.split()[0]}",
        f"{platform.system()} {platform.release()} ({platform.machine()})",
        f"Mode: {'contained' if paths.is_contained() else 'standard macOS locations'}",
    ]


def _security_lines(store: keychain.Credentials) -> list[str]:
    lines = [process_sandbox.describe()]
    lines.append(
        "Keychain: reachable" if store.available() else "Keychain: NOT reachable"
    )
    lines.append(
        "Parent PIN: set" if store.parent_pin_set() else "Parent PIN: not set"
    )
    # Configured or not. Never the key, never a prefix of it, never its length.
    for status in store.statuses():
        lines.append(f"{status.label} API key: {status.summary}")
    return lines


def _controls_lines(controls: permissions.ParentControls) -> list[str]:
    lines = [
        f"Cloud AI: {'on' if controls.allow_cloud_ai else 'off'}",
        f"Ask before cloud AI: {'yes' if controls.ask_before_cloud_ai else 'no'}",
    ]
    for gate in permissions.GATES:
        state = permissions.STATE_LABELS[controls.state(gate.name)]
        lines.append(f"{gate.label}: {state}")
    return lines


def _model_lines() -> list[str]:
    lines = []
    try:
        catalogue = router.load_catalogue()
    except Exception as exc:  # A broken models.json is exactly what a report should say.
        return [f"models.json could not be read: {type(exc).__name__}"]
    for entry in catalogue:
        where = "internet" if entry.info.requires_internet else "this Mac"
        verified = "verified" if entry.verified else "unverified"
        lines.append(f"{entry.info.id}: {entry.info.provider}, {where}, {verified}")
    try:
        lines.append(f"Default local model: {router.default_model_id()}")
    except Exception:
        lines.append("Default local model: not configured")
    return lines


def write_report(destination, **kwargs) -> str:
    """Write the report to a path and return what was written."""
    from pathlib import Path

    text = report(**kwargs)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return text
