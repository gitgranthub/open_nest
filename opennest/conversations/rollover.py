"""Handing one conversation thread over to the next, invisibly.

WORKORDER_01 section 15A gives the sequence, and this module is it:

1. Complete the current interaction normally  -- the caller does this; rollover only ever
   runs *after* a turn has finished and the child has already read the reply.
2. Update ``project_bible.md``
3. Update ``project_state.md``
4. Generate a concise thread handoff summary
5. Save the completed conversation
6. Start a new internal conversation thread
7. Load the project memory into the new thread   -- the caller, by rebuilding its prompt.
8. Continue naturally

    The child should not have to press "New Chat." Do not interrupt them with
    "Your context window is full."

Nothing in this module produces child-facing text. That is not an oversight; it is the
requirement.

ONE MODEL CALL, AND A FALLBACK THAT DOES NOT NEED ONE
-----------------------------------------------------
Only step 4 needs the model, and it gets a single call with no tools -- offering tools to
a summariser invites a 4B model to start editing files instead of summarising. The reply
is plain prose under two headings rather than JSON, because Phase 2 measured this model
emitting unparseable structured output when asked to produce anything elaborate
(SPIKES.md section 8).

Parsing is lenient, and when it yields nothing the summary is built from facts the
application already has. Section 15A requires that fallback in its own right: memory must
never be entirely model-generated. It also means a rollover cannot fail because the model
had a bad turn.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from opennest import paths
from opennest.agent.tools import normalise_tool_name
from opennest.ai.provider import Message, ModelProvider, ProviderError, Settings
from opennest.conversations import archive
from opennest.conversations.context_budget import ContextPolicy, fit
from opennest.memory import compactor, project_bible, project_state
from opennest.memory.project_state import StateNotes
from opennest.projects.manager import Project

HANDOFF_PROMPT_FILE = "handoff.txt"

#: A handoff is a summary. More than this and it is a transcript by another name.
MAX_DECISIONS = 12
MAX_NOW_LINES = 2
MAX_LINE_CHARS = 200

#: A handoff note is a dozen short lines. Capping generation keeps the pause between a
#: child's turns short, and stops a model that ignored the format from rambling.
MAX_HANDOFF_TOKENS = 400

_DECISIONS_HEADING = "decisions"
_NOW_HEADING = "now"


@dataclass(frozen=True)
class Handoff:
    """The semantic half of a handoff summary."""

    decisions: tuple[str, ...] = ()
    now: str = ""
    #: False when the model gave nothing usable and the application filled in instead.
    from_model: bool = False


@dataclass(frozen=True)
class RolloverResult:
    happened: bool = False
    archived_thread: int | None = None
    new_thread: int | None = None
    handoff: Handoff | None = None
    notes: StateNotes = StateNotes()


def perform(
    project: Project,
    provider: ModelProvider | None,
    messages: Sequence[Message],
    *,
    policy: ContextPolicy,
    notes: StateNotes | None = None,
    checkpoint_label: str | None = None,
) -> RolloverResult:
    """Run the whole section 15A sequence. Returns what happened, and never raises.

    A rollover that fails must not take the child's session with it, so every step that
    can fail is contained. The worst outcome is that memory is a little out of date.
    """
    conversation = [m for m in messages if m.role != "system"]
    if not any(m.role == "user" for m in conversation):
        return RolloverResult(notes=notes or StateNotes())

    number = archive.next_thread_number(project, at_least=project.manifest.active_thread)
    handoff = summarise(project, provider, conversation, policy=policy)

    # 2. The bible: durable knowledge, deduplicated and compacted as it goes in.
    bible = project_bible.load(project)
    bible.set_goal(_first_request(conversation))
    compactor.add_decisions(bible, list(handoff.decisions))
    compactor.trim(bible)
    project_bible.save(project, bible)

    # 3. The state: the task carries over, so the new thread knows what it was doing.
    updated_notes = StateNotes(
        current_task=handoff.now or (notes.current_task if notes else ""),
        problems=notes.problems if notes else (),
    )
    project_state.save(
        project, notes=updated_notes, checkpoint_label=checkpoint_label
    )

    # 5. The conversation itself, then its readable summary.
    try:
        archive.write_thread(project, number, conversation)
    except archive.ArchiveError:
        # The number was taken. Never overwrite a conversation; take the next one.
        number = archive.next_thread_number(project, at_least=number + 1)
        try:
            archive.write_thread(project, number, conversation)
        except archive.ArchiveError:
            return RolloverResult(notes=updated_notes)

    archive.write_summary(
        project, number, render_summary(project, number, handoff, conversation)
    )

    # 6. The new thread is recorded in the manifest, so it survives a restart.
    project.manifest.active_thread = number + 1
    project.save()

    return RolloverResult(
        happened=True,
        archived_thread=number,
        new_thread=number + 1,
        handoff=handoff,
        notes=updated_notes,
    )


def summarise(
    project: Project,
    provider: ModelProvider | None,
    conversation: Sequence[Message],
    *,
    policy: ContextPolicy,
) -> Handoff:
    """Ask the model for a handoff note, falling back to facts if it does not give one."""
    transcript = render_transcript(conversation)
    if provider is not None and transcript:
        budget = max(policy.max_context_tokens - policy.memory_reserved_tokens, 1)
        request = [
            Message(role="system", content=_handoff_prompt()),
            Message(
                role="user",
                content=(
                    "CONVERSATION\n"
                    + fit(transcript, budget, keep="end")
                    + "\n\nWrite the handoff note now."
                ),
            ),
        ]
        settings = Settings(temperature=0.0, max_tokens=MAX_HANDOFF_TOKENS)
        try:
            for _ in provider.chat(request, tools=None, settings=settings):
                pass
            parsed = parse_handoff(provider.finish().text)
        except (ProviderError, OSError, ValueError):
            parsed = Handoff()
        if parsed.decisions or parsed.now:
            return parsed

    return Handoff(now=_last_request(conversation), from_model=False)


def parse_handoff(text: str) -> Handoff:
    """Pull the two headings out of the reply. Anything else is ignored."""
    decisions: list[str] = []
    now: list[str] = []
    target: list[str] | None = None
    instructions = _instruction_lines()

    for raw in (text or "").splitlines():
        line = raw.strip()
        heading = line.rstrip(":").strip().casefold()
        if heading == _DECISIONS_HEADING:
            target = decisions
            continue
        if heading == _NOW_HEADING:
            target = now
            continue
        if target is None:
            continue

        # A blank line ends a section. Without this, a closing pleasantry after the last
        # heading -- "Hope that helps!" -- becomes the project's current task, and ends
        # up in the prompt as though the child had said it. A leading blank before the
        # first entry is just formatting, so it does not count.
        if not line:
            if target:
                target = None
            continue

        cleaned = line.lstrip("-*0123456789.").strip()
        # A small model sometimes copies the template back instead of answering.
        if not cleaned or cleaned.casefold() in instructions:
            continue
        target.append(cleaned[:MAX_LINE_CHARS])

    return Handoff(
        decisions=tuple(decisions[:MAX_DECISIONS]),
        now=" ".join(now[:MAX_NOW_LINES]).strip(),
        from_model=bool(decisions or now),
    )


def render_transcript(conversation: Sequence[Message]) -> str:
    """The conversation as plain text: what was said, not how tools were called.

    Tool traffic is left out deliberately. The handoff is about decisions, and a 4B model
    given a transcript full of JSON arguments summarises the JSON.
    """
    lines = []
    for message in conversation:
        if message.role == "user" and message.content:
            lines.append(f"Child: {message.content.strip()}")
        elif message.role == "assistant" and message.content:
            lines.append(f"Assistant: {message.content.strip()}")
    return "\n".join(lines)


def render_summary(
    project: Project,
    number: int,
    handoff: Handoff,
    conversation: Sequence[Message],
) -> str:
    """Deterministic facts first, then whatever the model contributed."""
    exchanges = sum(1 for m in conversation if m.role == "user")
    touched = files_touched(conversation)

    lines = [
        f"# {project.name} -- thread {number} handoff",
        "",
        "## What happened",
        f"- Exchanges: {exchanges}",
    ]
    if touched:
        lines.append("- Files changed: " + ", ".join(touched))
    if not handoff.from_model:
        lines.append("- Summary written by Open Nest (the model did not provide one).")

    if handoff.decisions:
        lines += ["", "## Decisions", *(f"- {d}" for d in handoff.decisions)]
    if handoff.now:
        lines += ["", "## Where we left off", handoff.now]
    return "\n".join(lines)


def files_touched(conversation: Sequence[Message]) -> list[str]:
    """Which files the assistant actually wrote, read straight off the tool calls."""
    found: list[str] = []
    for message in conversation:
        for call in message.tool_calls:
            if normalise_tool_name(call.name) not in ("write_file", "edit_file"):
                continue
            arguments = call.arguments
            path = arguments.get("path") if isinstance(arguments, dict) else None
            if path and path not in found:
                found.append(str(path))
    return found


def _first_request(conversation: Sequence[Message]) -> str:
    for message in conversation:
        if message.role == "user" and message.content.strip():
            return message.content.strip()[:300]
    return ""


def _last_request(conversation: Sequence[Message]) -> str:
    for message in reversed(conversation):
        if message.role == "user" and message.content.strip():
            return message.content.strip()[:MAX_LINE_CHARS]
    return ""


@lru_cache(maxsize=1)
def _handoff_prompt() -> str:
    return (paths.prompts_dir() / HANDOFF_PROMPT_FILE).read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _instruction_lines() -> frozenset[str]:
    """The prompt's own lines, so a model echoing them back is filtered out."""
    return frozenset(
        line.strip().lstrip("-*").strip().casefold()
        for line in _handoff_prompt().splitlines()
        if line.strip()
    )
