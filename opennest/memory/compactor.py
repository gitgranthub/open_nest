"""Keeping the bible from becoming a transcript.

WORKORDER_01 section 15A: "The goal is not endless accumulation... Remove or mark
obsolete details when later decisions supersede them."

Two mechanisms, both deliberately mechanical. Neither calls a model.

**Supersede.** When a new decision is *about the same thing* as an existing one, the old
one moves to ``## Superseded Decisions`` rather than being deleted. This is the example
section 15A gives -- player speed was 5, then 8 -- and it is the case that actually
matters, because a stale rule the model still believes is worse than no rule.

Sameness is judged by subject: the first few meaningful words, with numbers removed. That
last part is the whole trick. "Player speed is 5" and "Player speed is 8" are the same
decision precisely because the number changed, so a subject that kept the number would
never match the case this exists for.

**Trim.** Superseded entries and future ideas are capped, oldest dropped first. Live
decisions, the goal, and the application's own sections are never dropped -- if the bible
grows past what fits in a prompt, the *prompt* is trimmed at render time
(``conversations.context_budget.fit``) and the file keeps the record. Losing a decision
to save tokens would defeat the point of having a bible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from opennest.memory import markdown
from opennest.memory.project_bible import DECISIONS, FUTURE_IDEAS, SUPERSEDED, Bible

#: Once a decision has been replaced it is kept for a while as a record, then let go.
MAX_SUPERSEDED = 20

#: Ideas nobody has acted on for a long time are not decisions.
MAX_FUTURE_IDEAS = 30

#: How many meaningful words identify what a decision is about.
SUBJECT_WORDS = 3

#: Words that carry no subject information. Kept short on purpose: an aggressive list
#: makes unrelated decisions collide and silently supersede each other.
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "with", "from", "by", "as",
    "and", "or", "but", "if", "then", "than", "so",
    "do", "does", "did", "not", "no", "never", "always",
    "should", "shall", "will", "would", "can", "could", "must", "may", "might",
    "it", "its", "this", "that", "these", "those", "we", "i", "you", "he", "she", "they",
    "please", "just", "now", "yet", "still", "also", "any", "some",
})


@dataclass
class CompactionReport:
    """What compaction did, for logging and tests."""

    added: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.superseded or self.dropped)


def subject(text: str) -> tuple[str, ...]:
    """What a decision is about: its first few meaningful words, numbers removed."""
    words = [
        word for word in markdown.normalise(text).split()
        if word not in _STOPWORDS and not word.isdigit()
    ]
    return tuple(words[:SUBJECT_WORDS])


def same_subject(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    """Whether two subjects are about the same thing.

    Prefix comparison rather than equality, because a restatement is usually longer than
    the original: "Player speed is 5" reduces to ("player", "speed") while "Player speed
    is 8 after play testing" reduces to ("player", "speed", "after"). Requiring equality
    would miss exactly the case supersession exists for.

    Two words minimum. One word in common is a topic, not a subject -- superseding
    "Shooting is allowed" with "Shooting sounds are too loud" would lose a live decision.
    """
    shortest = min(len(left), len(right))
    if shortest < 2:
        return False
    return left[:shortest] == right[:shortest]


def add_decisions(bible: Bible, items: list[str]) -> CompactionReport:
    """Add decisions, moving anything they replace into ``Superseded Decisions``."""
    report = CompactionReport()
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        report.superseded.extend(_supersede_conflicts(bible, cleaned))
        report.added.extend(bible.add_bullets(DECISIONS, [cleaned]))
    report.dropped.extend(trim(bible))
    return report


def trim(bible: Bible) -> list[str]:
    """Enforce the caps on the sections that are allowed to lose entries."""
    dropped: list[str] = []
    dropped.extend(_cap(bible, SUPERSEDED, MAX_SUPERSEDED))
    dropped.extend(_cap(bible, FUTURE_IDEAS, MAX_FUTURE_IDEAS))
    return dropped


def _supersede_conflicts(bible: Bible, incoming: str) -> list[str]:
    """Move existing decisions with the same subject into ``Superseded Decisions``."""
    incoming_subject = subject(incoming)
    if not incoming_subject:
        return []

    incoming_key = markdown.normalise(incoming)
    keep: list[str] = []
    moved: list[str] = []
    for existing in bible.bullets(DECISIONS):
        matches = same_subject(subject(existing), incoming_subject)
        if matches and markdown.normalise(existing) != incoming_key:
            moved.append(existing)
        else:
            keep.append(existing)

    if not moved:
        return []

    bible.set_section(DECISIONS, [markdown.as_bullet(item) for item in keep])
    bible.add_bullets(SUPERSEDED, moved)
    return moved


def _cap(bible: Bible, section: str, limit: int) -> list[str]:
    items = bible.bullets(section)
    if len(items) <= limit:
        return []
    dropped = items[: len(items) - limit]
    bible.set_section(section, [markdown.as_bullet(item) for item in items[-limit:]])
    return dropped
