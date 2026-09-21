"""``project_bible.md`` -- what stays true about a project.

WORKORDER_01 section 15A. The bible holds durable knowledge: the goal, the decisions, the
rules the child set, the things that must not change. It outlives any one conversation,
which is what makes DoD 43 possible -- a new thread that understands the project without
replaying the old one.

WHO WRITES WHAT
---------------
Section 15A is emphatic that memory must not be entirely model-generated, and Phase 1
measured the same principle from the other direction: things the application knows for
certain should never be asked of a 4B model.

So the sections have owners:

===================== =========== ==============================================
Section               Written by  Source
===================== =========== ==============================================
Project               application manifest, profile
Assets                application the files actually on disk
Goal                  model       the first thing the child asked for
Decisions             model       handoff summaries, deduplicated
Future Ideas          model       handoff summaries
Superseded Decisions  application the compactor, when a decision is replaced
===================== =========== ==============================================

The application's sections are rewritten wholesale on every save, so they cannot drift
from reality. The model's sections are only ever appended to, so a good decision is never
silently lost -- only moved, by the compactor, and only with a trace.

The file is versioned in Git (it is part of project continuity), unlike the conversation
archive, which is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from opennest.assets import kinds
from opennest.memory import markdown
from opennest.memory.safety import write_memory_file
from opennest.projects.manager import Project

FILENAME = "project_bible.md"

#: Order sections are rendered in. Anything unrecognised is kept and rendered last, so a
#: parent who adds a section of their own does not lose it on the next save.
SECTION_ORDER = (
    "Project",
    "Goal",
    "Decisions",
    "Assets",
    "Future Ideas",
    "Superseded Decisions",
)

#: Rewritten from fact on every save. Never model-authored.
DETERMINISTIC_SECTIONS = ("Project", "Assets")

GOAL = "Goal"
DECISIONS = "Decisions"
FUTURE_IDEAS = "Future Ideas"
SUPERSEDED = "Superseded Decisions"

#: Directories whose contents count as project assets (section 15A: "asset roles").
#: Shared with the asset layer so the bible's Asset Library and the one the child sees
#: are the same list -- section 11's example holds a wiring PDF next to a sprite, and
#: reference material is imported into ``docs``.
ASSET_DIRS = kinds.LIBRARY_DIRECTORIES


@dataclass
class Bible:
    """One project's durable knowledge."""

    title: str = ""
    sections: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """True when nothing a model contributed is in here yet.

        The deterministic sections are always present once the file exists, so their
        presence says nothing about whether the project has accumulated any memory.
        """
        return not any(
            self.sections.get(name) for name in (GOAL, DECISIONS, FUTURE_IDEAS, SUPERSEDED)
        )

    def lines(self, section: str) -> list[str]:
        return list(self.sections.get(section, []))

    def bullets(self, section: str) -> list[str]:
        return markdown.bullets(self.sections.get(section, []))

    def set_section(self, section: str, lines: list[str]) -> None:
        self.sections[section] = list(lines)

    def add_bullets(self, section: str, items: list[str]) -> list[str]:
        """Append bullets that are not already there. Returns the ones actually added.

        Deduplication is cosmetic-insensitive: a 4B model restates the same decision with
        different punctuation every time it is asked, and an accumulating bible is the
        thing section 15A explicitly does not want.
        """
        existing = {markdown.normalise(b) for b in self.bullets(section)}
        added: list[str] = []
        current = self.sections.setdefault(section, [])
        for item in items:
            text = item.strip()
            key = markdown.normalise(text)
            if not key or key in existing:
                continue
            existing.add(key)
            current.append(markdown.as_bullet(text))
            added.append(text)
        return added

    def set_goal(self, text: str) -> bool:
        """Record the goal if there is not one yet. Returns whether it was written.

        The goal is set once, from the first thing the child asked for. Letting it be
        rewritten every rollover would mean the project's purpose drifts towards whatever
        was most recently discussed.
        """
        cleaned = " ".join(text.split()).strip()
        if not cleaned or self.sections.get(GOAL):
            return False
        self.sections[GOAL] = [cleaned]
        return True

    def render(self, *, skip: tuple[str, ...] = ()) -> str:
        sections = {k: v for k, v in self.sections.items() if k not in skip}
        return markdown.render_sections(self.title, sections, SECTION_ORDER)

    def render_for_prompt(self) -> str:
        """The bible as the model should see it: current truths only.

        ``Superseded Decisions`` is left out. It exists so a person reading the file can
        see what changed and when, which is what section 15A's example is for -- but a
        model handed a list of things that are no longer true will act on some of them,
        and it costs tokens to say so. The file keeps the record; the prompt gets the
        truth.
        """
        return self.render(skip=(SUPERSEDED,))


def path_for(project: Project) -> Path:
    return project.internal_dir / FILENAME


def parse(text: str, title: str = "") -> Bible:
    return Bible(title=title, sections=markdown.split_sections(text))


def load(project: Project) -> Bible:
    """Read the bible, or return an empty one. A damaged file is never fatal."""
    title = f"{project.name} -- Project Bible"
    target = path_for(project)
    try:
        return parse(target.read_text(encoding="utf-8"), title)
    except (OSError, UnicodeDecodeError):
        return Bible(title=title)


def save(project: Project, bible: Bible) -> Path:
    """Refresh the application-owned sections, then write atomically and secret-scanned."""
    bible.title = f"{project.name} -- Project Bible"
    refresh_facts(project, bible)
    target = path_for(project)
    write_memory_file(target, bible.render())
    return target


def refresh_facts(project: Project, bible: Bible) -> None:
    """Rewrite the sections the application owns from what is actually true now."""
    manifest = project.manifest
    facts = [
        f"- Name: {project.name}",
        f"- Type: {project.profile.name}",
        f"- Entry point: src/{manifest.entrypoint}",
        f"- Started: {manifest.created}",
    ]
    if manifest.model:
        facts.append(f"- Built with: {manifest.model}")
    bible.set_section("Project", facts)

    assets = _assets(project)
    bible.set_section("Assets", [f"- {name}" for name in assets] if assets else [])


def _assets(project: Project, limit: int = 60) -> list[str]:
    """Project-relative paths of imported assets and data files."""
    found: list[str] = []
    for directory in ASSET_DIRS:
        root = project.directory / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if len(found) >= limit:
                return found
            if path.is_file() and not path.name.startswith("."):
                found.append(str(path.relative_to(project.directory)))
    return found
