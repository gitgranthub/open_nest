"""``project_state.md`` -- what is true about the project right now.

WORKORDER_01 section 15A. Where the bible is durable, this file is current: the files
that exist, the packages in play, what is being worked on, what is broken.

WHY IT IS NOT INJECTED INTO THE PROMPT
--------------------------------------
Section 15A lists ``project_state.md`` as part of the new-thread bootstrap. Open Nest
composes that bootstrap from the *live* equivalent instead --
``agent.controller.project_state()`` already injects the current file list and the last
run result straight from the application, and has since Phase 2.

Reading the same facts back off disk would put them in the prompt twice and would make
them slightly stale, since the file is written at the end of a turn and the prompt is
built at the start of the next one. So the bootstrap does contain the project's current
state; it is generated rather than loaded.

What the live block does *not* know is the semantic part -- the current task and any open
problem carried across a rollover. :func:`carried_notes` returns exactly that, and that is
what goes into the prompt alongside the bible.

The file itself is still written, because it is versioned with the project, a parent can
read it, and :mod:`opennest.memory.history_search` searches it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opennest.execution.python_runner import RunResult
from opennest.memory import markdown
from opennest.memory.safety import write_memory_file
from opennest.projects.manager import Project
from opennest.security.sandbox import visible_files

FILENAME = "project_state.md"

SECTION_ORDER = (
    "Current Files",
    "Dependencies",
    "Current Task",
    "Known Problems",
    "Last Successful Run",
    "Saved Versions",
)

CURRENT_TASK = "Current Task"
KNOWN_PROBLEMS = "Known Problems"

NOTHING_WRONG = "None."

#: A traceback is for the repair loop, not for permanent memory. Keep enough to recognise
#: the problem later and no more.
MAX_PROBLEM_CHARS = 500


@dataclass(frozen=True)
class StateNotes:
    """The semantic half: carried across rollovers, not derivable from the project."""

    current_task: str = ""
    problems: tuple[str, ...] = ()


def path_for(project: Project) -> Path:
    return project.internal_dir / FILENAME


def render(
    project: Project,
    *,
    notes: StateNotes | None = None,
    last_run: RunResult | None = None,
    checkpoint_label: str | None = None,
) -> str:
    """Compose the document. Every section except the notes comes from fact."""
    notes = notes or StateNotes()
    sections: dict[str, list[str]] = {}

    files = visible_files(project.directory)
    sections["Current Files"] = [f"- {name}" for name in files] or ["- (no files yet)"]

    packages = project.profile.packages
    sections["Dependencies"] = [f"- {name}" for name in packages] if packages else []

    if notes.current_task:
        sections[CURRENT_TASK] = [notes.current_task]

    problems = list(notes.problems)
    if last_run is not None and not last_run.ok:
        problems.append(
            "The last run failed:\n" + last_run.failure_text[:MAX_PROBLEM_CHARS].strip()
        )
    sections[KNOWN_PROBLEMS] = [f"- {p}" for p in problems] if problems else [NOTHING_WRONG]

    last_success = project.manifest.last_successful_run
    if last_run is not None and last_run.ok:
        sections["Last Successful Run"] = ["It ran and worked."]
    elif last_success:
        sections["Last Successful Run"] = [f"It last worked on {last_success}."]

    if checkpoint_label:
        sections["Saved Versions"] = [f"- Most recent: {checkpoint_label}"]

    return markdown.render_sections(
        f"{project.name} -- Current State", sections, SECTION_ORDER
    )


def save(
    project: Project,
    *,
    notes: StateNotes | None = None,
    last_run: RunResult | None = None,
    checkpoint_label: str | None = None,
) -> Path:
    target = path_for(project)
    write_memory_file(
        target,
        render(project, notes=notes, last_run=last_run, checkpoint_label=checkpoint_label),
    )
    return target


def load_notes(project: Project) -> StateNotes:
    """Read back the semantic sections so they survive closing the application."""
    try:
        text = path_for(project).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return StateNotes()
    sections = markdown.split_sections(text)
    task = " ".join(sections.get(CURRENT_TASK, [])).strip()
    problems = tuple(
        p for p in markdown.bullets(sections.get(KNOWN_PROBLEMS, [])) if p != NOTHING_WRONG
    )
    return StateNotes(current_task=task, problems=problems)


def carried_notes(notes: StateNotes) -> str:
    """The part of the state a fresh thread cannot work out for itself."""
    lines = []
    if notes.current_task:
        lines.append(f"What we were working on: {notes.current_task}")
    if notes.problems:
        lines.append("Still not right:")
        lines.extend(f"- {problem}" for problem in notes.problems)
    return "\n".join(lines)
