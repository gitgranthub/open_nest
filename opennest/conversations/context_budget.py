"""How much context a thread has used, and when to hand over.

WORKORDER_01 section 15A: every model defines its own budget, and

    Do not wait until the model's absolute context-window limit is reached.
    Roll over earlier while there is sufficient context to create a high-quality handoff.

That is the whole reason there are two numbers. ``max_context_tokens`` is the wall;
``rollover_threshold`` is where Open Nest acts, with enough room left to ask the model for
a good handoff summary. The policies live in ``config/models.json`` because model
behaviour must never be hard-coded (section 3), and a test enforces that the threshold is
below the limit.

MEASURING
---------
``Reply`` carries ``prompt_tokens`` and ``generated_tokens`` straight from the provider,
so the normal path needs no tokeniser at all -- the model just told us what the prompt
cost. :func:`estimate_tokens` is the fallback for a provider that reports nothing, and it
is crude on purpose: four characters per token, no tokeniser loaded, no pretence of
precision.

Because the estimate can be wrong in either direction, it is not used to trigger an
ordinary rollover. It only drives a backstop: if even the crude estimate says the thread
is approaching the hard limit, roll over regardless of what was reported. Ground truth
where it exists, a guard rail where it does not.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from opennest.ai.provider import Message, ModelInfo, Reply

#: English prose and code both land near four characters per token for the tokenisers
#: these models use. Good enough for a backstop, not good enough for anything else.
CHARS_PER_TOKEN = 4

#: Used when a model has no policy configured. Matches the smallest local model's, so an
#: unconfigured model errs towards rolling over too early rather than too late.
FALLBACK_MAX_TOKENS = 8000

#: Where the threshold lands when a policy gives a limit but no sensible threshold.
DEFAULT_THRESHOLD_FRACTION = 0.75


@dataclass(frozen=True)
class ContextPolicy:
    """One model's conversation budget."""

    max_context_tokens: int = FALLBACK_MAX_TOKENS
    rollover_threshold: int = int(FALLBACK_MAX_TOKENS * DEFAULT_THRESHOLD_FRACTION)
    memory_reserved_tokens: int = 2000

    @property
    def backstop(self) -> int:
        """The point past which the estimate alone forces a rollover."""
        return max(1, self.max_context_tokens - self.memory_reserved_tokens)

    @classmethod
    def for_model(cls, info: ModelInfo) -> ContextPolicy:
        """Read a model's policy, repairing anything incoherent rather than trusting it.

        A policy whose threshold is at or above its limit would mean never rolling over
        until the model refuses the prompt, which is the failure section 15A is written
        to prevent. Configuration should not be able to cause that.
        """
        raw = info.context_policy or {}
        maximum = int(raw.get("max_context_tokens") or FALLBACK_MAX_TOKENS)
        threshold = int(raw.get("rollover_threshold") or 0)
        if not 0 < threshold < maximum:
            threshold = int(maximum * DEFAULT_THRESHOLD_FRACTION)
        reserved = int(raw.get("memory_reserved_tokens") or 0)
        if not 0 < reserved < threshold:
            reserved = max(1, threshold // 4)
        return cls(
            max_context_tokens=maximum,
            rollover_threshold=threshold,
            memory_reserved_tokens=reserved,
        )


def estimate_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def estimate_messages(messages: Sequence[Message]) -> int:
    return sum(estimate_tokens(message.content or "") for message in messages)


def fit(text: str, max_tokens: int, *, keep: str = "start") -> str:
    """Trim ``text`` to a budget, dropping whole lines.

    Cutting lines rather than characters keeps a Markdown memory block readable: a bible
    that stops mid-sentence reads like the model made something up.

    ``keep="start"`` for memory, where the most important sections are written first;
    ``keep="end"`` for a transcript, where the most recent exchange matters most.
    """
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text

    lines = text.splitlines()
    if keep == "end":
        lines = list(reversed(lines))

    kept: list[str] = []
    used = 0
    for line in lines:
        cost = estimate_tokens(line) + 1
        if used + cost > max_tokens:
            break
        kept.append(line)
        used += cost

    if keep == "end":
        kept.reverse()
    return "\n".join(kept)


@dataclass
class ContextBudget:
    """Tracks one thread's context use against its model's policy."""

    policy: ContextPolicy = ContextPolicy()
    #: Prompt + generated tokens the provider reported for the most recent generation.
    reported: int = 0

    def observe(self, reply: Reply | None) -> None:
        if reply is None or not reply.prompt_tokens:
            return
        self.reported = reply.prompt_tokens + reply.generated_tokens

    def reset(self) -> None:
        self.reported = 0

    def tokens_used(self, messages: Sequence[Message]) -> int:
        """Best available figure: what the provider said, else the estimate."""
        return self.reported or estimate_messages(messages)

    def should_roll_over(self, messages: Sequence[Message]) -> bool:
        if self.reported and self.reported >= self.policy.rollover_threshold:
            return True
        return estimate_messages(messages) >= self.policy.backstop
