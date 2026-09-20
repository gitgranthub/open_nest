"""Look for credentials before anything is committed.

WORKORDER_01 section 29A requires secret scanning before commits and pushes. Pulled
forward from the GitHub phase because Phase 3 is where committing starts, and a
credential that reaches Git history is far harder to remove than one that was never
written -- rewriting history is not something a child, or this application, should have
to do.

Deliberately conservative. A false positive costs one clear message; a miss puts a real
key in a permanent record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Patterns for credentials with recognisable shapes. Names are child/parent-readable
#: because they appear in the message shown when a commit is blocked.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("an Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("a GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("a Google API key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("a private key file", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "a password or secret written into the code",
        re.compile(
            r"""(?ix)
            \b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)
            \s*[:=]\s*
            ["'][^"'\s]{8,}["']
            """
        ),
    ),
)

#: Obvious placeholders. Blocking these would train everyone to ignore the warning.
_PLACEHOLDERS = re.compile(
    r"(?i)(your[_-]?(api[_-]?)?key|xxx+|\.{3,}|example|placeholder|changeme|<[^>]+>|"
    r"sk-ant-api03-\.\.\.|test[_-]?key|dummy|fake|redacted|do-not-read)"
)

#: Files big enough to be data rather than code are skipped; scanning a CSV of a million
#: rows for a password pattern is slow and produces noise.
MAX_SCAN_BYTES = 2_000_000


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    description: str

    def describe(self) -> str:
        return f"{self.path} line {self.line} looks like {self.description}"


def scan_text(text: str, path: str = "") -> list[Finding]:
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if _PLACEHOLDERS.search(line):
            continue
        for description, pattern in PATTERNS:
            if pattern.search(line):
                findings.append(Finding(path, number, description))
                break
    return findings


def scan_paths(root: Path, relative_paths: list[str]) -> list[Finding]:
    """Scan the given project-relative files. Binary and oversized files are skipped."""
    findings: list[Finding] = []
    for relative in relative_paths:
        target = Path(root) / relative
        try:
            if not target.is_file() or target.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # Not text; nothing to read a key out of.
        findings.extend(scan_text(text, relative))
    return findings


def explain(findings: list[Finding]) -> str:
    """A message for a parent, naming the file but never quoting the credential."""
    lines = [
        "Open Nest did not save a version of this project, because something in it "
        "looks like a password or key:",
        "",
    ]
    lines.extend(f"  {finding.describe()}" for finding in findings[:10])
    if len(findings) > 10:
        lines.append(f"  ...and {len(findings) - 10} more")
    lines += [
        "",
        "Keys should never be written inside a project. A parent can add them in "
        "Settings, where they are kept in the macOS Keychain.",
    ]
    return "\n".join(lines)
