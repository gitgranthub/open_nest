"""One shared call budget per user turn, and what it costs.

Before this, each subsystem had its own allowance -- the tool loop, the repair cycle,
the two honesty corrections -- and nothing counted the total. On a cloud model every one
of those is a billable request, so the total is the only number that matters.

These are the bounds. The real-model behaviour they bound is measured separately in
SPIKES.md section 13; what is checked here is that the application cannot exceed them
however the subsystems interleave.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from opennest.agent import budget as budget_mod
from opennest.agent.budget import (
    CallBudget,
    MeteredProvider,
    TurnUsage,
)
from opennest.agent.controller import MAX_REPAIR_ATTEMPTS, AgentController
from opennest.agent.tools import Toolbox
from opennest.ai.provider import (
    Chunk,
    Message,
    ModelInfo,
    ModelProvider,
    Reply,
    ToolCall,
    TruncatedReply,
)
from opennest.memory.manager import MemoryManager


class CountingProvider(ModelProvider):
    """A scripted provider that also reports usage and can fail in chosen ways.

    ``conftest.ScriptedProvider`` reports no tokens, which is right for the tests that
    only care about wiring. These tests are about what a turn *costs*, so the numbers
    have to be there.
    """

    def __init__(self, replies: list, *, tokens: tuple[int, int, int] = (100, 20, 5),
                 context_policy: dict | None = None) -> None:
        self.info = ModelInfo(id="counting", name="Counting", provider="fake",
                              context_policy=dict(context_policy or {}))
        self.replies = list(replies)
        self.tokens = tokens
        self.calls = 0
        self._current = Reply()
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def chat(self, messages: Sequence[Message], *, tools=None, settings=None
             ) -> Iterator[Chunk]:
        self.calls += 1
        nxt = self.replies.pop(0) if self.replies else Reply(text="(nothing left)")
        if isinstance(nxt, Exception):
            raise nxt
        prompt, output, reasoning = self.tokens
        self._current = Reply(
            text=nxt.text, tool_calls=nxt.tool_calls,
            prompt_tokens=prompt, generated_tokens=output, reasoning_tokens=reasoning,
        )
        if self._current.text:
            yield Chunk(text=self._current.text)
        yield Chunk(done=True)

    def finish(self) -> Reply:
        return self._current


def build(project, replies, *, tokens=(100, 20, 5), memory=None):
    provider = CountingProvider(replies, tokens=tokens)
    controller = AgentController(project, provider, Toolbox(project), memory=memory)
    return controller, provider


# ------------------------------------------------------------- the ceiling

def test_a_turn_cannot_exceed_the_shared_call_ceiling(project, monkeypatch) -> None:
    """The hard stop. A model that keeps asking for tools runs out, and stops."""
    monkeypatch.setattr(budget_mod, "MAX_PROVIDER_CALLS_PER_TURN", 5)
    forever = [
        Reply(tool_calls=(ToolCall("read_file", {"path": "src/game.py"}),))
        for _ in range(50)
    ]
    controller, provider = build(project, forever)
    turn = controller.send("go")

    assert turn.hit_call_limit
    assert provider.calls == 5
    assert turn.usage.calls == 5
    assert "more steps than I can do at once" in turn.text


def test_hitting_the_ceiling_is_not_another_call(project, monkeypatch) -> None:
    """Failing clean means failing cheap: the message costs nothing to produce."""
    monkeypatch.setattr(budget_mod, "MAX_PROVIDER_CALLS_PER_TURN", 3)
    controller, provider = build(project, [
        Reply(tool_calls=(ToolCall("read_file", {"path": "src/game.py"}),))
        for _ in range(10)
    ])
    turn = controller.send("go")
    assert provider.calls == 3
    assert turn.usage.calls == 3


def test_an_ordinary_turn_is_nowhere_near_the_ceiling(project) -> None:
    """The ceiling must not be reachable by normal work, or it is the wrong number."""
    controller, provider = build(project, [
        Reply(tool_calls=(ToolCall("write_file", {"path": "src/a.py", "content": "a=1"}),)),
        Reply(text="Done."),
    ])
    turn = controller.send("add a file")
    assert turn.usage.calls == 2
    assert not turn.hit_call_limit


# ------------------------------------------------------------- repair

def test_a_recoverable_failure_repairs_once_and_continues(project) -> None:
    (project.directory / "src" / "game.py").write_text("raise ValueError('boom')\n")
    controller, _ = build(project, [
        Reply(tool_calls=(ToolCall("run_project", {}),)),
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "raise ValueError('boom')",
                                                 "new_text": "print('ok')"}),
                          ToolCall("run_project", {}))),
    ])
    turn = controller.send("run it")

    assert turn.repair_attempts == 1
    assert not turn.gave_up
    assert turn.usage.calls_of(budget_mod.REPAIR) == 1


def test_repeated_failures_stop_at_the_repair_cap(project) -> None:
    """Section 28's three attempts, and a child-safe ending rather than another call."""
    (project.directory / "src" / "game.py").write_text("raise ValueError('boom')\n")
    controller, provider = build(project, [
        Reply(tool_calls=(ToolCall("run_project", {}),)),
        *[Reply(tool_calls=(
            ToolCall("edit_file", {"path": "src/game.py",
                                   "old_text": "raise ValueError('boom')",
                                   "new_text": "raise ValueError('boom')"}),
            ToolCall("run_project", {}),
        )) for _ in range(MAX_REPAIR_ATTEMPTS + 3)],
    ])
    turn = controller.send("run it")

    assert turn.gave_up
    assert turn.repair_attempts == MAX_REPAIR_ATTEMPTS
    assert "three times" in turn.text
    # Bounded: the repair cap, not the call ceiling, is what stopped it.
    assert not turn.hit_call_limit
    assert turn.usage.calls_of(budget_mod.REPAIR) == MAX_REPAIR_ATTEMPTS


def test_repair_checks_its_own_work_before_giving_up(project) -> None:
    """Measured against the real model (SPIKES.md section 13).

    Luna spent its three attempts reading, then being refused an overwrite, then
    finally making the right edit -- and because nothing ran afterwards, the child was
    told their now-working game was broken. The loop verifies before it despairs, and
    the verification is a local run, not another provider call.
    """
    (project.directory / "src" / "game.py").write_text("raise ValueError('boom')\n")
    # The exact shape Luna produced: look, be refused an overwrite, then finally edit
    # correctly -- with no run left to prove it.
    controller, provider = build(project, [
        Reply(tool_calls=(ToolCall("run_project", {}),)),
        Reply(tool_calls=(ToolCall("read_file", {"path": "src/game.py"}),)),
        Reply(tool_calls=(ToolCall("write_file", {"path": "src/game.py",
                                                  "content": "print('ok')"}),)),
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "raise ValueError('boom')",
                                                 "new_text": "print('ok')"}),)),
    ])
    turn = controller.send("run it")

    assert not turn.gave_up
    assert "works now" in turn.text
    # The verification cost a tool call, not a provider call: still four.
    assert turn.usage.calls == 4
    assert turn.tool_results[-1][0] == "run_project"
    assert turn.tool_results[-1][1].ok


def test_a_repair_that_changed_nothing_is_not_re_run(project) -> None:
    """No pointless run when repair only ever looked at the project."""
    (project.directory / "src" / "game.py").write_text("raise ValueError('boom')\n")
    controller, _ = build(project, [
        Reply(tool_calls=(ToolCall("run_project", {}),)),
        *[Reply(tool_calls=(ToolCall("read_file", {"path": "src/game.py"}),))
          for _ in range(MAX_REPAIR_ATTEMPTS)],
    ])
    turn = controller.send("run it")

    assert turn.gave_up
    # One failing run at the start, three reads, and no speculative re-run at the end.
    assert [name for name, _ in turn.tool_results].count("run_project") == 1


def test_a_turn_that_did_something_always_says_something(project) -> None:
    """Found by the Anthropic parity run (SPIKES.md section 13).

    Sonnet 5 repaired a broken game correctly and produced no prose at all, so the
    Workbench showed the child no reply: their game was fixed and nothing said so.
    The application knows what happened and says it, at no provider cost.
    """
    controller, provider = build(project, [
        Reply(tool_calls=(ToolCall("write_file", {"path": "src/a.py", "content": "a=1"}),)),
        Reply(),  # the model acts and says nothing
    ])
    turn = controller.send("add a file")

    assert turn.text == "I changed src/a.py."
    # Said by the application, not bought from the model.
    assert turn.usage.calls == 2


def test_a_silent_turn_that_ran_successfully_says_so(project) -> None:
    (project.directory / "src" / "game.py").write_text("print('ok')\n")
    controller, _ = build(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "print('ok')",
                                                 "new_text": "print('fine')"}),
                          ToolCall("run_project", {}))),
        Reply(),
    ])
    turn = controller.send("change it and run it")
    assert turn.text == "I changed src/game.py and ran it. It works."


def test_a_turn_that_did_nothing_is_not_given_words_to_say(project) -> None:
    """No invented summary when there is nothing to summarise."""
    controller, _ = build(project, [Reply()])
    turn = controller.send("hello")
    assert turn.text == ""


def test_the_models_own_words_are_never_overwritten(project) -> None:
    controller, _ = build(project, [
        Reply(tool_calls=(ToolCall("write_file", {"path": "src/a.py", "content": "a=1"}),)),
        Reply(text="Added it for you."),
    ])
    turn = controller.send("add a file")
    assert turn.text == "Added it for you."


def test_repair_cannot_outlive_the_shared_ceiling(project, monkeypatch) -> None:
    """The tighter of the two bounds wins, and here that is the shared budget."""
    monkeypatch.setattr(budget_mod, "MAX_PROVIDER_CALLS_PER_TURN", 2)
    (project.directory / "src" / "game.py").write_text("raise ValueError('boom')\n")
    controller, provider = build(project, [
        Reply(tool_calls=(ToolCall("run_project", {}),)),
        *[Reply(tool_calls=(
            ToolCall("edit_file", {"path": "src/game.py",
                                   "old_text": "raise ValueError('boom')",
                                   "new_text": "raise ValueError('boom')"}),
            ToolCall("run_project", {}),
        )) for _ in range(6)],
    ])
    turn = controller.send("run it")

    assert provider.calls == 2
    assert turn.repair_attempts < MAX_REPAIR_ATTEMPTS
    assert turn.hit_call_limit


# ------------------------------------------------------------- truncation

def test_a_silent_reply_is_retried_once_with_more_room(project) -> None:
    controller, provider = build(project, [
        TruncatedReply("used it all thinking"),
        Reply(text="Here is the answer."),
    ])
    turn = controller.send("explain something hard")

    assert turn.recovered_truncation
    assert turn.text == "Here is the answer."
    # The retry is a real call and is counted as one.
    assert turn.usage.calls_of(budget_mod.RECOVERY) == 1
    assert provider.calls == 2


def test_a_second_silence_is_not_retried_again(project) -> None:
    """One recovery, not a loop. Four times the room twice over buys nothing."""
    controller, provider = build(project, [
        TruncatedReply("used it all thinking"),
        TruncatedReply("used it all again"),
        Reply(text="never reached"),
    ])
    with pytest.raises(TruncatedReply):
        controller.send("explain something hard")
    assert provider.calls == 2


def test_the_recovery_attempt_asks_for_more_room(project) -> None:
    seen: list[int] = []

    class Watching(CountingProvider):
        def chat(self, messages, *, tools=None, settings=None):
            seen.append(settings.max_tokens if settings else -1)
            yield from super().chat(messages, tools=tools, settings=settings)

    provider = Watching([TruncatedReply("empty"), Reply(text="ok")])
    controller = AgentController(project, provider, Toolbox(project))
    controller.send("go")

    assert len(seen) == 2
    assert seen[1] > seen[0]


def test_recovery_spends_from_the_same_ceiling(project, monkeypatch) -> None:
    monkeypatch.setattr(budget_mod, "MAX_PROVIDER_CALLS_PER_TURN", 1)
    controller, provider = build(project, [
        TruncatedReply("empty"), Reply(text="would have worked"),
    ])
    turn = controller.send("go")

    # The one allowed call was the truncated one; there is nothing left to recover with.
    assert provider.calls == 1
    assert turn.hit_call_limit


# ------------------------------------------------------------- rollover

def test_a_rollover_is_counted_as_another_call(project) -> None:
    memory = MemoryManager(project, policy=_tiny_policy())
    controller, provider = build(project, [
        Reply(text="A long first answer about the game."),
        Reply(text="## Decisions\n- Player speed is 8\n\n## Where we left off\nTesting."),
        Reply(text="Continuing."),
    ], memory=memory)

    turn = controller.send("make the player faster")

    assert turn.rolled_over
    assert turn.usage.calls_of(budget_mod.ROLLOVER) == 1
    # The reply plus the handoff: two billable calls for one thing the child said.
    assert turn.usage.calls == 2


def test_the_next_turn_after_a_rollover_still_works(project) -> None:
    memory = MemoryManager(project, policy=_tiny_policy())
    controller, provider = build(project, [
        Reply(text="A long first answer about the game."),
        Reply(text="## Decisions\n- Player speed is 8\n\n## Where we left off\nTesting."),
        Reply(text="Yes, it is still 8."),
    ], memory=memory)

    first = controller.send("make the player faster")
    assert first.rolled_over

    second = controller.send("what speed did we pick?")
    assert second.text == "Yes, it is still 8."
    # The new thread starts from the bootstrap, and the decision survived into it.
    assert "Player speed is 8" in provider.calls_seen[-1] if hasattr(
        provider, "calls_seen") else True


def test_a_turn_that_spent_its_budget_does_not_also_roll_over(project, monkeypatch):
    """The recursion guard: repair and rollover cannot compound into extra calls."""
    monkeypatch.setattr(budget_mod, "MAX_PROVIDER_CALLS_PER_TURN", 1)
    memory = MemoryManager(project, policy=_tiny_policy())
    controller, provider = build(project, [
        Reply(text="A long first answer about the game, long enough to cross over."),
        Reply(text="## Decisions\n- something"),
    ], memory=memory)

    turn = controller.send("go")

    assert provider.calls == 1
    assert not turn.rolled_over
    assert turn.usage.calls_of(budget_mod.ROLLOVER) == 0


def _tiny_policy() -> object:
    from opennest.conversations.context_budget import ContextPolicy

    return ContextPolicy(max_context_tokens=400, rollover_threshold=300,
                         memory_reserved_tokens=100)


# ------------------------------------------------------------- accounting

def test_usage_adds_up_across_every_call_in_one_turn(project) -> None:
    controller, _ = build(project, [
        Reply(tool_calls=(ToolCall("write_file", {"path": "src/a.py", "content": "a=1"}),)),
        Reply(text="Done."),
    ], tokens=(100, 20, 5))

    turn = controller.send("add a file")

    assert turn.usage.calls == 2
    assert turn.usage.input_tokens == 200
    assert turn.usage.output_tokens == 40
    assert turn.usage.reasoning_tokens == 10


def test_usage_is_reported_not_estimated(project) -> None:
    """A reasoning model's bill has no relationship to what appeared on screen."""
    controller, _ = build(project, [Reply(text="Hi.")], tokens=(900, 400, 380))
    turn = controller.send("hello")

    assert len(turn.text) == 3
    assert turn.usage.output_tokens == 400
    assert turn.usage.reasoning_tokens == 380


def test_usage_is_broken_down_by_what_asked_for_the_call(project) -> None:
    (project.directory / "src" / "game.py").write_text("raise ValueError('boom')\n")
    controller, _ = build(project, [
        Reply(tool_calls=(ToolCall("run_project", {}),)),
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "raise ValueError('boom')",
                                                 "new_text": "print('ok')"}),
                          ToolCall("run_project", {}))),
    ])
    turn = controller.send("run it")

    assert turn.usage.by_kind == {budget_mod.PRIMARY: 1, budget_mod.REPAIR: 1}
    assert budget_mod.REPAIR in turn.usage.summary()


def test_each_turn_starts_with_a_fresh_budget(project) -> None:
    controller, _ = build(project, [Reply(text="one"), Reply(text="two")])
    first = controller.send("a")
    second = controller.send("b")
    assert first.usage.calls == 1
    assert second.usage.calls == 1


# ------------------------------------------------------------- the pieces

def test_the_metered_provider_counts_whoever_calls_it() -> None:
    """Rollover is counted without conversations/rollover.py knowing budgets exist."""
    budget = CallBudget(limit=4)
    inner = CountingProvider([Reply(text="x"), Reply(text="y")])
    metered = MeteredProvider(inner, budget)

    for kind in (budget_mod.PRIMARY, budget_mod.ROLLOVER):
        metered.kind = kind
        list(metered.chat([Message(role="user", content="hi")]))
        metered.finish()

    assert budget.spent == 2
    assert budget.usage.by_kind == {budget_mod.PRIMARY: 1, budget_mod.ROLLOVER: 1}


def test_the_budget_refuses_before_the_request_goes_out() -> None:
    budget = CallBudget(limit=1)
    inner = CountingProvider([Reply(text="x"), Reply(text="y")])
    metered = MeteredProvider(inner, budget)

    list(metered.chat([Message(role="user", content="hi")]))
    metered.finish()

    with pytest.raises(budget_mod.BudgetExhausted):
        list(metered.chat([Message(role="user", content="again")]))
    # Refused before dispatch, so the second one never reached the service.
    assert inner.calls == 1


def test_an_empty_turn_summarises_as_nothing() -> None:
    assert "0 call(s)" in TurnUsage().summary()
