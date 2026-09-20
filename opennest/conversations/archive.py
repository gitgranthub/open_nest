"""Completed conversation threads, kept inside the project.

WORKORDER_01 section 15A:

    .opennest/conversations/
      thread_v01.jsonl
      thread_v01_summary.md
      thread_v02.jsonl

"Use proper sequential numbering rather than overwriting previous threads." That is
enforced here rather than trusted: :func:`write_thread` refuses an existing file outright.
A conversation is the only part of a project that cannot be reconstructed from anything
else, so the failure mode worth designing against is silently clobbering one.

The archive is gitignored (see ``versioning.git_manager.GITIGNORE``) -- conversations stay
on this Mac by default, per section 38 -- while the memory files distilled from it are
versioned. Both are still secret-scanned on the way in: a child can paste a key into chat
just as easily as into a file, and a whole JSONL line is dropped if it contains one, so a
message with a credential in it is simply not archived.

The system message is not archived. It is regenerated from the project on every load, it
is the largest message in the thread, and it is not conversation.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from opennest.ai.provider import Message, ToolCall
from opennest.memory.safety import write_memory_file
from opennest.projects.manager import Project

DIRNAME = "conversations"


class ArchiveError(Exception):
    """A thread could not be archived."""


def conversations_dir(project: Project) -> Path:
    return project.internal_dir / DIRNAME


def thread_name(number: int) -> str:
    return f"thread_v{number:02d}"


def thread_path(project: Project, number: int) -> Path:
    return conversations_dir(project) / f"{thread_name(number)}.jsonl"


def summary_path(project: Project, number: int) -> Path:
    return conversations_dir(project) / f"{thread_name(number)}_summary.md"


def thread_numbers(project: Project) -> list[int]:
    """Every archived thread number, ascending."""
    directory = conversations_dir(project)
    if not directory.is_dir():
        return []
    found = []
    for path in directory.glob("thread_v*.jsonl"):
        try:
            found.append(int(path.stem.removeprefix("thread_v")))
        except ValueError:
            continue  # Something else in the folder; not ours to interpret.
    return sorted(found)


def next_thread_number(project: Project, at_least: int = 1) -> int:
    """The first unused number, never below ``at_least``."""
    existing = thread_numbers(project)
    highest = max(existing) if existing else 0
    return max(at_least, highest + 1)


def write_thread(project: Project, number: int, messages: Sequence[Message]) -> Path:
    """Archive a completed thread. Refuses to overwrite an existing one."""
    target = thread_path(project, number)
    if target.exists():
        raise ArchiveError(f"{target.name} already exists and will not be overwritten.")
    body = "\n".join(
        json.dumps(_to_json(message), ensure_ascii=False)
        for message in messages
        if message.role != "system"
    )
    write_memory_file(target, body + "\n" if body else "")
    return target


def read_thread(project: Project, number: int) -> list[Message]:
    try:
        text = thread_path(project, number).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    messages = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            messages.append(_from_json(json.loads(line)))
        except (ValueError, TypeError):
            continue  # One damaged line must not lose the rest of the conversation.
    return messages


def write_summary(project: Project, number: int, text: str) -> Path:
    target = summary_path(project, number)
    write_memory_file(target, text.rstrip() + "\n")
    return target


def read_summary(project: Project, number: int) -> str:
    try:
        return summary_path(project, number).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def latest_summary(project: Project) -> str:
    """The most recent handoff summary, which is the one a new thread needs."""
    for number in reversed(thread_numbers(project)):
        summary = read_summary(project, number)
        if summary.strip():
            return summary
    return ""


def _to_json(message: Message) -> dict:
    payload: dict = {"role": message.role, "content": message.content}
    if message.name:
        payload["name"] = message.name
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            {"name": call.name, "arguments": call.arguments, "id": call.id}
            for call in message.tool_calls
        ]
    return payload


def _from_json(raw: dict) -> Message:
    calls = tuple(
        ToolCall(
            name=item.get("name", ""),
            arguments=item.get("arguments", {}),
            id=item.get("id", ""),
        )
        for item in raw.get("tool_calls", [])
    )
    return Message(
        role=raw.get("role", "user"),
        content=raw.get("content", ""),
        tool_calls=calls,
        tool_call_id=raw.get("tool_call_id", ""),
        name=raw.get("name", ""),
    )
