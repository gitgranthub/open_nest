"""One budget for everything a single user turn is allowed to spend.

Before this, each subsystem had its own allowance: the tool loop could iterate eight
times, the repair loop three, the two honesty corrections once each, and a rollover
happened whenever the threshold said so. Nothing counted the total, so a bad turn could
stack them -- and on a cloud model every one of those is a billable request against a
parent's card.

So there is **one** ceiling per turn and every provider call spends from it, whatever
asked for it. :class:`MeteredProvider` is how: it wraps the real provider and is handed
to the controller, the memory manager and the rollover machinery alike. None of them
needed changing, because all three already take a ``ModelProvider`` -- which is the
payoff for section 21's single interface.

WHY TWELVE
----------
Measured, not guessed (SPIKES.md section 13). The longest legitimate flow is a change
that does not work first time:

    read (1), edit (2), run fails (3), repair edit (4), run fails (5),
    repair edit (6), run works (7), final reply (8)

plus one honesty correction (9) and a rollover (10). Twelve leaves headroom over that
without letting a confused model run indefinitely. At the ~1,050 input tokens a real
turn measured on ``gpt-5.6-luna``, a turn that somehow hit the ceiling costs a few
cents -- deliberately not so tight that ordinary hard work fails, because the real
spend limit belongs on the API key, where a parent sets it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from opennest.ai.provider import (
    Chunk,
    Message,
    ModelProvider,
    ProviderError,
    Reply,
    Settings,
)

#: Every provider call in one user turn, from every subsystem, shares this.
MAX_PROVIDER_CALLS_PER_TURN = 12

#: What asked for a call. Used for reporting, never for a separate allowance.
PRIMARY = "primary"
REPAIR = "repair"
CORRECTION = "correction"
RECOVERY = "recovery"
ROLLOVER = "rollover"


class BudgetExhausted(ProviderError):
    """The turn ran out of provider calls. Ends the turn; never retried."""


@dataclass
class CallRecord:
    """One provider call, as the service reported it.

    Created when the request is dispatched and filled in when it answers. Mutable for
    that reason: a call that fails half-way through still happened, still counts
    against the turn, and may still have been billed -- it just never reported a
    number, so its tokens stay zero rather than being guessed at.
    """

    kind: str
    input_tokens: int = 0
    output_tokens: int = 0
    #: Of ``output_tokens``, the part spent reasoning where the service says so.
    reasoning_tokens: int = 0
    #: False until the service answered. A dispatched call that never settled is one
    #: that errored mid-stream.
    settled: bool = False


@dataclass
class TurnUsage:
    """What one user turn actually cost.

    Every figure is provider-reported. Nothing here is inferred from the length of the
    reply -- a reasoning model's bill has no relationship to what appeared on screen,
    which is the whole reason this exists.
    """

    records: list[CallRecord] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return len(self.records)

    @property
    def input_tokens(self) -> int:
        return sum(record.input_tokens for record in self.records)

    @property
    def output_tokens(self) -> int:
        return sum(record.output_tokens for record in self.records)

    @property
    def reasoning_tokens(self) -> int:
        return sum(record.reasoning_tokens for record in self.records)

    def calls_of(self, kind: str) -> int:
        return sum(1 for record in self.records if record.kind == kind)

    @property
    def by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.kind] = counts.get(record.kind, 0) + 1
        return counts

    def summary(self) -> str:
        """One line for a log or a diagnostic. Never shown to a child."""
        parts = ", ".join(f"{kind}x{count}" for kind, count in sorted(self.by_kind.items()))
        return (
            f"{self.calls} call(s) [{parts or 'none'}]  "
            f"{self.input_tokens} in / {self.output_tokens} out"
            + (f" ({self.reasoning_tokens} reasoning)" if self.reasoning_tokens else "")
        )


@dataclass
class CallBudget:
    """How many provider calls this turn has left, and what it has spent."""

    #: Read at construction rather than bound as a class default, so the ceiling is
    #: whatever the module says *now* -- which is what lets a test lower it to 2 and
    #: exercise the exhausted path without a fifty-call fixture.
    limit: int = field(default_factory=lambda: MAX_PROVIDER_CALLS_PER_TURN)
    usage: TurnUsage = field(default_factory=TurnUsage)

    @property
    def spent(self) -> int:
        return self.usage.calls

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def check(self) -> None:
        if self.exhausted:
            raise BudgetExhausted(
                f"This turn already used its {self.limit} allowed requests."
            )

    def begin(self, kind: str) -> CallRecord:
        """Spend a call, before the request goes out.

        Counted on dispatch rather than on completion, because a call that fails
        half-way through is still a call. Counting only successes made a failing call
        free -- and a free failure is one a retry loop can repeat without ever
        exhausting anything, which is the opposite of what a ceiling is for.
        """
        self.check()
        record = CallRecord(kind=kind)
        self.usage.records.append(record)
        return record

    def settle(self, record: CallRecord, reply: Reply | None) -> None:
        record.input_tokens = getattr(reply, "prompt_tokens", 0) or 0
        record.output_tokens = getattr(reply, "generated_tokens", 0) or 0
        record.reasoning_tokens = getattr(reply, "reasoning_tokens", 0) or 0
        record.settled = True


class MeteredProvider(ModelProvider):
    """A provider that spends from a :class:`CallBudget` on every call.

    Wrapping rather than threading a budget parameter through every caller is what lets
    rollover be counted without ``conversations/rollover.py`` knowing a budget exists.
    It takes a ``ModelProvider``; it now gets one that counts.

    ``kind`` labels whatever comes next. It is deliberately a plain attribute the caller
    sets before a call rather than an argument: ``chat`` has a fixed signature that the
    memory and rollover layers also call, and they must not have to care.
    """

    def __init__(self, inner: ModelProvider, budget: CallBudget,
                 *, kind: str = PRIMARY) -> None:
        self.inner = inner
        self.budget = budget
        self.kind = kind

    @property
    def info(self):
        return self.inner.info

    @property
    def is_loaded(self) -> bool:
        return self.inner.is_loaded

    def load(self) -> None:
        self.inner.load()

    def unload(self) -> None:
        self.inner.unload()

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict] | None = None,
        settings: Settings | None = None,
    ) -> Iterator[Chunk]:
        # Spent before the request goes out, so an exhausted turn costs nothing and a
        # call that dies mid-stream still counts.
        self._pending = self.budget.begin(self.kind)
        yield from self.inner.chat(messages, tools=tools, settings=settings)

    def finish(self) -> Reply:
        reply = self.inner.finish()
        record = getattr(self, "_pending", None)
        if record is not None:
            self.budget.settle(record, reply)
            self._pending = None
        return reply
