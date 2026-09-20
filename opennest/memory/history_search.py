"""Looking something up before saying "I don't remember".

WORKORDER_01 section 15A:

    If a user references an older decision that is not present in the active thread, the
    agent may search project_bible.md, project_state.md, conversation summaries,
    archived thread history before telling the child that it does not remember.

NOT A TOOL
----------
The obvious implementation is a ``search_memory`` tool. It is the wrong one here.

Phase 1 measured tool selection falling from 94% to 75% when a fifth tool was added, and
the dominant failure was the model reaching for a lookup tool instead of acting
(SPIKES.md section 4). The same reasoning that removed ``list_project_files`` applies
exactly: the application can do this lookup deterministically, faster, and without
spending a turn on it.

So Open Nest searches *for* the model. When a message refers to something earlier --
"like we talked about", "the thing we decided" -- the matching lines are found here and
injected into the system prompt alongside the bible, the same way the file list is. The
model never chooses to search and cannot fail to.

Matching is word overlap, not relevance ranking. There is no index, no embedding, and no
model call; a project's memory is a handful of small files and the child's phrasing
usually reuses the words they used the first time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from opennest.conversations import archive
from opennest.memory import project_bible, project_state
from opennest.projects.manager import Project

#: Phrases that mean "you should already know this". Deliberately narrow: searching when
#: the child did not refer to the past adds noise to the prompt for no reason.
CUES = (
    "we talked about", "we discussed", "talked about before", "like before",
    "we decided", "we agreed", "you said", "i said", "i told you", "we said",
    "remember", "earlier", "last time", "before we", "as we", "what did we",
    "used to", "we had", "already",
)

#: Words too common to narrow anything down.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "at", "for",
    "with", "from", "by", "as", "is", "are", "was", "were", "be", "do", "does", "did",
    "it", "its", "this", "that", "we", "i", "you", "my", "our", "your", "me",
    "what", "when", "how", "why", "can", "could", "should", "would", "will", "shall",
    "now", "then", "about", "like", "want", "make", "let", "lets", "add", "again",
    "remember", "talked", "discussed", "said", "decided", "agreed", "before", "earlier",
    "last", "time", "already", "thing", "things", "back", "next", "also", "some", "more",
})

_WORD = re.compile(r"[a-z0-9]+")

#: Archived threads are searched newest-first and only this far back. A long-running
#: project can hold many threads and the bible is meant to be where durable things live.
MAX_THREADS_SEARCHED = 5

MAX_LINE_CHARS = 300


@dataclass(frozen=True)
class Hit:
    source: str
    text: str


def looks_like_a_memory_question(text: str) -> bool:
    lowered = (text or "").lower()
    return any(cue in lowered for cue in CUES)


def search(project: Project, query: str, *, limit: int = 6) -> list[Hit]:
    """Lines from project memory that share meaningful words with ``query``."""
    wanted = _keywords(query)
    if not wanted:
        return []

    scored: list[tuple[int, int, Hit]] = []
    for order, (source, line) in enumerate(_candidates(project)):
        overlap = len(wanted & _keywords(line))
        if overlap:
            scored.append((overlap, -order, Hit(source=source, text=line)))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    seen: set[str] = set()
    hits: list[Hit] = []
    for _, _, hit in scored:
        key = hit.text.lower()
        if key in seen:
            continue
        seen.add(key)
        hits.append(hit)
        if len(hits) >= limit:
            break
    return hits


def as_context(hits: list[Hit]) -> str:
    """Render hits for the system prompt, or an empty string when there are none."""
    if not hits:
        return ""
    lines = [
        "FROM EARLIER IN THIS PROJECT",
        "They are referring to something from before. This is what the project's notes "
        "say about it -- treat it as true and do not ask them to repeat it:",
    ]
    lines.extend(f"- {hit.text} ({hit.source})" for hit in hits)
    return "\n".join(lines)


def _candidates(project: Project):
    """(source, line) pairs, most authoritative first."""
    for reader, source in (
        (project_bible.path_for(project), project_bible.FILENAME),
        (project_state.path_for(project), project_state.FILENAME),
    ):
        yield from _lines_of(_read(reader), source)

    numbers = archive.thread_numbers(project)
    for number in reversed(numbers[-MAX_THREADS_SEARCHED:]):
        summary = archive.read_summary(project, number)
        yield from _lines_of(summary, f"{archive.thread_name(number)}_summary.md")

    for number in reversed(numbers[-MAX_THREADS_SEARCHED:]):
        for message in archive.read_thread(project, number):
            if message.role not in ("user", "assistant") or not message.content:
                continue
            yield from _lines_of(message.content, f"{archive.thread_name(number)}.jsonl")


def _read(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _lines_of(text: str, source: str):
    for line in text.splitlines():
        cleaned = line.strip().lstrip("#-*").strip()
        if len(cleaned) < 4:
            continue
        yield source, cleaned[:MAX_LINE_CHARS]


def _keywords(text: str) -> set[str]:
    return {
        word for word in _WORD.findall((text or "").lower())
        if word not in _STOPWORDS and len(word) > 2
    }
