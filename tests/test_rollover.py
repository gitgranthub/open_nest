"""Thread rollover: the context budget, the archive, and DoD 39-43.

WORKORDER_01 section 15A and the Definition of Done scenario in section 42. The
behaviour being proved is that a conversation can run past its budget, hand over to a new
thread, and carry on knowing what was decided -- without the child seeing any of it.

Everything here uses the scripted provider from conftest.py and a deliberately low
rollover threshold, so the whole sequence runs in milliseconds and always the same way.
Whether the *model* writes a good handoff is a separate, measured question; whether the
application rolls over correctly is this one.
"""

from __future__ import annotations

import pytest

from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.ai.provider import Message, Reply, ToolCall
from opennest.ai.router import load_catalogue
from opennest.conversations import archive, rollover
from opennest.conversations.context_budget import (
    ContextBudget,
    ContextPolicy,
    estimate_tokens,
    fit,
)
from opennest.memory import project_bible, project_state
from opennest.memory.manager import MemoryManager
from opennest.projects.manager import read_manifest
from tests.conftest import ScriptedProvider

#: A threshold low enough that two ordinary turns cross it, with the estimate backstop
#: parked far away so the two triggers can be tested independently.
LOW_THRESHOLD = ContextPolicy(
    max_context_tokens=100_000, rollover_threshold=300, memory_reserved_tokens=200
)

HANDOFF_REPLY = Reply(text=(
    "DECISIONS:\n"
    "- Asteroids get faster over time\n"
    "- Save the boss level for later, do not build it yet\n"
    "\n"
    "NOW:\n"
    "Making the asteroids harder to dodge."
))


def build(project, replies, *, policy=LOW_THRESHOLD):
    provider = ScriptedProvider(replies)
    memory = MemoryManager(project=project, policy=policy)
    controller = AgentController(project, provider, Toolbox(project), memory=memory)
    return controller, provider, memory


# --------------------------------------------------------------------------- budget

def test_a_policy_is_read_from_the_model_catalogue() -> None:
    """The budget is configuration, never hard-coded (WORKORDER_01 section 3)."""
    entry = next(e for e in load_catalogue() if e.info.id == "qwen3-4b-instruct")
    policy = ContextPolicy.for_model(entry.info)
    assert policy.max_context_tokens == 16000
    assert policy.rollover_threshold == 12000


def test_every_configured_model_rolls_over_before_its_limit() -> None:
    for entry in load_catalogue():
        policy = ContextPolicy.for_model(entry.info)
        assert policy.rollover_threshold < policy.max_context_tokens, entry.info.id
        assert 0 < policy.memory_reserved_tokens < policy.rollover_threshold, entry.info.id


def test_an_incoherent_policy_is_repaired_rather_than_obeyed() -> None:
    """A threshold at or above the limit would mean never rolling over in time."""
    from opennest.ai.provider import ModelInfo

    broken = ModelInfo(id="x", name="X", provider="fake", context_policy={
        "max_context_tokens": 8000, "rollover_threshold": 9000, "memory_reserved_tokens": 0,
    })
    policy = ContextPolicy.for_model(broken)
    assert policy.rollover_threshold < policy.max_context_tokens
    assert 0 < policy.memory_reserved_tokens < policy.rollover_threshold


def test_the_provider_report_is_used_rather_than_a_guess() -> None:
    budget = ContextBudget(LOW_THRESHOLD)
    budget.observe(Reply(text="hi", prompt_tokens=280, generated_tokens=25))
    assert budget.tokens_used([]) == 305
    assert budget.should_roll_over([])


def test_nothing_reported_falls_back_to_an_estimate() -> None:
    budget = ContextBudget(LOW_THRESHOLD)
    messages = [Message(role="user", content="x" * 4000)]
    assert budget.tokens_used(messages) == 1000
    assert not budget.should_roll_over(messages)  # well under the backstop


def test_the_estimate_backstop_fires_before_the_hard_limit() -> None:
    """Even with a provider that reports nothing, the window must not be overrun."""
    policy = ContextPolicy(
        max_context_tokens=1000, rollover_threshold=800, memory_reserved_tokens=200
    )
    budget = ContextBudget(policy)
    assert budget.should_roll_over([Message(role="user", content="x" * 3300)])


def test_a_memory_block_is_trimmed_on_line_boundaries() -> None:
    text = "\n".join(f"line number {n}" for n in range(200))
    trimmed = fit(text, 50)
    assert estimate_tokens(trimmed) <= 50
    assert trimmed.startswith("line number 0")
    assert not trimmed.endswith("line numb")


def test_a_transcript_keeps_its_most_recent_lines() -> None:
    """Memory is trimmed from the end; a conversation is trimmed from the front."""
    text = "\n".join(f"Child: message {n}" for n in range(200))
    trimmed = fit(text, 50, keep="end")
    assert estimate_tokens(trimmed) <= 50
    assert trimmed.endswith("Child: message 199")


# --------------------------------------------------------------------------- archive

def test_threads_are_numbered_sequentially(project) -> None:
    assert archive.next_thread_number(project) == 1
    archive.write_thread(project, 1, [Message(role="user", content="hello")])
    assert archive.next_thread_number(project) == 2


def test_an_existing_thread_is_never_overwritten(project) -> None:
    """A conversation is the one thing in a project that cannot be reconstructed."""
    archive.write_thread(project, 1, [Message(role="user", content="first")])
    with pytest.raises(archive.ArchiveError):
        archive.write_thread(project, 1, [Message(role="user", content="second")])
    assert "first" in archive.thread_path(project, 1).read_text()


def test_a_thread_round_trips(project) -> None:
    original = [
        Message(role="user", content="make it faster"),
        Message(role="assistant", content="", tool_calls=(
            ToolCall("edit_file", {"path": "src/game.py"}, "call_0"),
        )),
        Message(role="tool", name="edit_file", tool_call_id="call_0", content="done"),
    ]
    archive.write_thread(project, 1, original)
    restored = archive.read_thread(project, 1)
    assert [m.role for m in restored] == ["user", "assistant", "tool"]
    assert restored[1].tool_calls[0].name == "edit_file"


def test_the_system_prompt_is_not_archived(project) -> None:
    """It is regenerated from the project and is the largest message in the thread."""
    archive.write_thread(project, 1, [
        Message(role="system", content="SECRET SAUCE SYSTEM PROMPT"),
        Message(role="user", content="hello"),
    ])
    assert "SECRET SAUCE" not in archive.thread_path(project, 1).read_text()


def test_a_pasted_credential_is_not_archived(project) -> None:
    """Section 15A: no tokens in project memory, and chat is project memory."""
    archive.write_thread(project, 1, [
        Message(role="user", content="my key is ghp_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"),
        Message(role="user", content="make the ship blue"),
    ])
    text = archive.thread_path(project, 1).read_text()
    assert "ghp_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBB" not in text
    assert "make the ship blue" in text


def test_a_damaged_line_does_not_lose_the_conversation(project) -> None:
    archive.conversations_dir(project).mkdir(parents=True, exist_ok=True)
    archive.thread_path(project, 1).write_text(
        '{"role": "user", "content": "kept"}\nnot json at all\n'
    )
    assert [m.content for m in archive.read_thread(project, 1)] == ["kept"]


# ------------------------------------------------------------------- handoff parsing

def test_a_handoff_is_parsed_from_the_two_headings() -> None:
    parsed = rollover.parse_handoff(HANDOFF_REPLY.text)
    assert parsed.from_model
    assert parsed.decisions[0] == "Asteroids get faster over time"
    assert parsed.now == "Making the asteroids harder to dodge."


def test_chatter_around_the_headings_is_ignored() -> None:
    parsed = rollover.parse_handoff(
        "Sure, here is the note you asked for.\n\n"
        "DECISIONS:\n- Dark blue background\n\nNOW:\nAdding a score.\n\nHope that helps!"
    )
    assert parsed.decisions == ("Dark blue background",)
    assert parsed.now == "Adding a score."


def test_the_template_echoed_back_is_not_treated_as_content() -> None:
    """A small model sometimes repeats the instructions instead of answering."""
    parsed = rollover.parse_handoff(
        "DECISIONS:\n"
        "- One line for each thing that was decided and should still be true later.\n"
        "- Only what was actually decided in the conversation below. Invent nothing.\n"
    )
    assert parsed.decisions == ()


def test_an_unusable_reply_produces_no_handoff() -> None:
    assert not rollover.parse_handoff("I'm sorry, I can't do that.").from_model


def test_files_touched_is_read_off_the_tool_calls() -> None:
    conversation = [
        Message(role="assistant", tool_calls=(
            ToolCall("write_file", {"path": "src/game.py"}),
            ToolCall("read_file", {"path": "src/settings.py"}),
        )),
    ]
    assert rollover.files_touched(conversation) == ["src/game.py"]


# ------------------------------------------------------------------ the DoD scenario

def test_the_thread_rolls_over_and_the_new_one_remembers(project) -> None:
    """DoD 39-43, start to finish.

    The child keeps working, the thread crosses its threshold, Open Nest updates memory
    and archives the conversation, and the next thing they say is understood using the
    project's memory rather than the conversation that is now gone.
    """
    controller, provider, _ = build(project, [
        Reply(text="Done - they speed up as you go.", prompt_tokens=100),
        Reply(text="Okay, the boss level can wait.", prompt_tokens=500),
        HANDOFF_REPLY,
        Reply(text="Adding the boss level now."),
    ])

    # 39. Enough conversation that the thread approaches its threshold.
    controller.send("Make the asteroids get faster over time.")
    turn = controller.send("Save the boss level idea for later. Do not build it yet.")

    # 40. Memory is updated and thread_v01 is archived.
    assert turn.rolled_over
    assert archive.thread_path(project, 1).is_file()
    assert archive.summary_path(project, 1).is_file()
    bible = project_bible.path_for(project).read_text()
    assert "boss level" in bible
    assert "faster over time" in bible

    # 41. thread_v02 begins, and survives a restart because it is in the manifest.
    assert read_manifest(project.directory).active_thread == 2
    assert len(controller.history) == 1, "a new thread starts with the bootstrap alone"

    # 42. The child notices nothing and carries on.
    assert turn.text == "Okay, the boss level can wait."
    controller.send("Now let's add a boss level like we talked about before.")

    # 43. The new thread understands, without the original conversation.
    prompt = provider.system_prompt
    assert "boss level" in prompt
    assert not any("faster over time" in m.content for m in controller.history[1:])


def test_the_child_is_never_told_the_thread_rolled_over(project) -> None:
    """Section 15A: no "context window full", no "New Chat"."""
    streamed: list[str] = []
    controller, _, _ = build(project, [
        Reply(text="Done.", prompt_tokens=500),
        HANDOFF_REPLY,
        Reply(text="Sure."),
    ])
    turn = controller.send("Make it harder.", on_text=streamed.append)
    controller.send("Thanks.", on_text=streamed.append)

    spoken = (turn.text + " ".join(streamed)).lower()
    for word in ("context", "thread", "rollover", "roll over", "new chat", "summar"):
        assert word not in spoken


def test_a_chat_only_turn_does_not_rewrite_the_state_file(project) -> None:
    """Section 15A: do not rewrite memory after every trivial chat message."""
    controller, _, _ = build(project, [Reply(text="It uses the arrow keys.")])
    controller.send("how does the ship move?")
    assert not project_state.path_for(project).exists()


def test_a_turn_that_changes_a_file_does_rewrite_it(project) -> None:
    controller, _, _ = build(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 8"}),)),
        Reply(text="Done."),
    ])
    controller.send("faster please")
    assert "src/game.py" in project_state.path_for(project).read_text()


def test_a_rollover_does_not_disturb_the_project(project) -> None:
    controller, _, _ = build(project, [
        Reply(text="Done.", prompt_tokens=500),
        HANDOFF_REPLY,
    ])
    before = project.entrypoint_path.read_text()
    controller.send("Make it harder.")
    assert project.entrypoint_path.read_text() == before


def test_memory_outlives_the_controller(project) -> None:
    """A second session gets the bible even though the conversation is gone."""
    first, _, _ = build(project, [
        Reply(text="Done.", prompt_tokens=500),
        HANDOFF_REPLY,
    ])
    first.send("Save the boss level idea for later.")

    second, provider, _ = build(project, [Reply(text="Sure.")])
    second.send("What next?")
    assert "boss level" in provider.system_prompt


def test_the_model_failing_to_summarise_does_not_break_the_rollover(project) -> None:
    """Section 15A: memory must never be entirely model-generated."""
    controller, _, _ = build(project, [
        Reply(text="Done.", prompt_tokens=500),
        Reply(text="I'm sorry, I can't do that."),
        Reply(text="Sure."),
    ])
    turn = controller.send("Make the asteroids faster.")

    assert turn.rolled_over
    summary = archive.read_summary(project, 1)
    assert "Make the asteroids faster" in summary
    assert "the model did not provide one" in summary


def test_closing_a_project_archives_the_thread(project) -> None:
    """A session boundary is a thread boundary, so short sessions still remember."""
    controller, _, _ = build(
        project,
        [Reply(text="Done."), HANDOFF_REPLY],
        policy=ContextPolicy(max_context_tokens=100_000, rollover_threshold=99_000,
                             memory_reserved_tokens=500),
    )
    controller.send("Save the boss level idea for later.")
    assert not archive.thread_path(project, 1).exists()

    controller.close()
    assert archive.thread_path(project, 1).is_file()
    assert "boss level" in project_bible.path_for(project).read_text()


def test_quitting_skips_the_model_but_still_archives(project) -> None:
    """Command-Q must be instant; the handoff falls back to what the app knows."""
    controller, provider, _ = build(
        project,
        [Reply(text="Done.")],
        policy=ContextPolicy(max_context_tokens=100_000, rollover_threshold=99_000,
                             memory_reserved_tokens=500),
    )
    controller.send("Make the ship blue.")
    calls_before = len(provider.calls)

    controller.close(summarise=False)
    assert len(provider.calls) == calls_before
    assert archive.thread_path(project, 1).is_file()
    assert "Make the ship blue" in archive.read_summary(project, 1)


def test_closing_an_untouched_project_archives_nothing(project) -> None:
    controller, _, _ = build(project, [])
    controller.close()
    assert archive.thread_numbers(project) == []
    assert read_manifest(project.directory).active_thread == 1


def test_the_agent_still_works_with_no_memory_at_all(project) -> None:
    """Memory is optional, exactly as versioning is."""
    provider = ScriptedProvider([Reply(text="Fine.", prompt_tokens=99_999)])
    controller = AgentController(project, provider, Toolbox(project))
    turn = controller.send("hello")
    assert turn.text == "Fine."
    assert not turn.rolled_over
    assert archive.thread_numbers(project) == []
