"""The little bit of Markdown that project memory actually uses.

Memory files are Markdown because a parent may open them and because WORKORDER_01
section 15A shows them that way. They are also *parsed* back by the application, so the
shape has to be predictable: a title line, then ``## Section`` headings, then lines.

Nothing here is a general Markdown parser and it should not become one. It handles the
documents Open Nest writes itself.
"""

from __future__ import annotations

import re

_HEADING = re.compile(r"^##\s+(.+?)\s*$")


def split_sections(text: str) -> dict[str, list[str]]:
    """``## Heading`` to its lines, in the order they appear.

    Anything before the first heading -- the title -- is dropped, because the title is
    regenerated from the project name rather than round-tripped.
    """
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            current = sections.setdefault(match.group(1), [])
            continue
        if current is not None:
            current.append(line.rstrip())
    return {name: _trimmed(lines) for name, lines in sections.items()}


def render_sections(title: str, sections: dict[str, list[str]], order: tuple[str, ...]) -> str:
    """The inverse of :func:`split_sections`. Empty sections are left out."""
    parts = [f"# {title}"] if title else []
    names = [n for n in order if n in sections] + [n for n in sections if n not in order]
    for name in names:
        lines = _trimmed(sections.get(name, []))
        if not lines:
            continue
        parts.append(f"## {name}\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


def bullets(lines: list[str]) -> list[str]:
    """Just the ``- item`` entries of a section, with the marker removed."""
    found = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            found.append(stripped[2:].strip())
    return found


def as_bullet(text: str) -> str:
    stripped = text.strip().lstrip("-*").strip()
    return f"- {stripped}"


def normalise(text: str) -> str:
    """A comparison key for deduplicating bullets that differ only cosmetically."""
    return " ".join(text.lower().replace("-", " ").split()).strip(" .")


def _trimmed(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]
