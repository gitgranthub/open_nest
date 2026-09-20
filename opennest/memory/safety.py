"""Every write to project memory goes through here.

WORKORDER_01 section 15A: "The system must not store API keys, passwords, Keychain
contents, tokens, private credentials inside project-memory Markdown files."

The existing secret scanner already runs before a commit. That is too late for memory:
``project_bible.md`` is versioned, so a credential written into it *becomes* a commit,
and a conversation archive can hold a key a child pasted into chat even though it never
reached a source file.

So this module is the single choke point, the way ``security.sandbox.resolve_in_project``
is for tool paths. It removes the offending line rather than refusing the whole write:
memory must never become the reason a child's turn fails, and a bible missing one line is
better than no bible at all. The caller is told what was dropped so it can be logged.
"""

from __future__ import annotations

from pathlib import Path

from opennest.versioning.autosave import atomic_write_text
from opennest.versioning.secret_scanner import Finding, scan_text


def redact(text: str, path: str = "") -> tuple[str, list[Finding]]:
    """Drop any line that looks like a credential. Returns the safe text and what went."""
    findings = scan_text(text, path)
    if not findings:
        return text, []
    removed = {finding.line for finding in findings}
    kept = [
        line for number, line in enumerate(text.splitlines(), start=1)
        if number not in removed
    ]
    safe = "\n".join(kept)
    if text.endswith("\n") and safe:
        safe += "\n"
    return safe, findings


def write_memory_file(path: Path, text: str) -> list[Finding]:
    """Scan, then write atomically. A half-written bible is worse than none."""
    path = Path(path)
    safe, findings = redact(text, path.name)
    atomic_write_text(path, safe)
    return findings
