"""Agent loop behaviour, driven by a scripted provider.

A fake provider keeps these tests deterministic and fast. Real-model behaviour was
measured separately in Phase 1; what matters here is that the loop wires tools correctly,
refreshes state, and honours the repair cap.

The provider and the project fixture live in conftest.py, shared with test_rollover.py.
"""

from __future__ import annotations

import pytest

from opennest.agent import budget as budget_mod
from opennest.agent.controller import (
    MAX_REPAIR_ATTEMPTS,
    AgentController,
    Turn,
    build_system_prompt,
    project_state,
)
from opennest.agent.tools import Toolbox
from opennest.ai.provider import Reply, ToolCall
from opennest.execution import playtest
from opennest.security.process_sandbox import sandbox_available
from tests.conftest import ScriptedProvider

#: See tests/test_tools.py: run_project fails closed without the process sandbox, so a
#: test that starts a project skips rather than fails when it cannot be applied.
needs_sandbox = pytest.mark.skipif(
    not sandbox_available(), reason="the process sandbox cannot be applied here"
)


def make(project, replies, build_style="build"):
    provider = ScriptedProvider(replies)
    return AgentController(project, provider, Toolbox(project), build_style=build_style), provider


def test_system_prompt_contains_all_five_parts(project) -> None:
    prompt = build_system_prompt(project, build_style="teach")
    assert "You are Gary, the project helper inside Open Nest" in prompt  # base
    assert "PROJECT TYPE: GAME" in prompt                        # profile
    assert "BUILD STYLE: BUILD IT AND TEACH ME" in prompt        # style
    assert "Use your tools to actually change" in prompt         # tool rules
    assert "CURRENT PROJECT" in prompt                           # state


def test_project_state_lists_files_so_no_tool_is_needed(project) -> None:
    state = project_state(project)
    assert "game.py" in state
    assert "you already know these" in state


def test_project_state_names_the_packages_that_exist(project) -> None:
    """The base prompt tells it to stop rather than install, so it must know what it has."""
    state = project_state(project)
    assert "pygame" in state
    assert "there are no others" in state


def test_project_state_hides_internal_directories(project) -> None:
    (project.internal_dir / "project_bible.md").write_text("internal")
    assert ".opennest" not in project_state(project)


def test_plain_reply_needs_no_tools(project) -> None:
    controller, provider = make(project, [Reply(text="Hello.")])
    turn = controller.send("hi")
    assert turn.text == "Hello." and turn.tool_results == []
    assert len(provider.calls) == 1


def test_only_profile_tools_are_offered(project) -> None:
    controller, provider = make(project, [Reply(text="ok")])
    controller.send("hi")
    offered = {t["function"]["name"] for t in provider.tools_offered[0]}
    assert offered == {"read_file", "edit_file", "write_file", "run_project"}
    assert "list_project_files" not in offered


def test_tool_call_is_executed_and_fed_back(project) -> None:
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("write_file", {"path": "src/a.py", "content": "a=1"}),)),
        Reply(text="Done."),
    ])
    turn = controller.send("make a file")
    assert (project.directory / "src" / "a.py").read_text() == "a=1"
    assert turn.text == "Done."
    assert any(r.ok for _, r in turn.tool_results)


def test_tool_name_with_parens_still_dispatches(project) -> None:
    """Phase 1 saw models emit run_project(); it must not be treated as unknown."""
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("write_file()", {"path": "src/b.py", "content": "b=1"}),)),
        Reply(text="ok"),
    ])
    controller.send("write it")
    assert (project.directory / "src" / "b.py").exists()


def test_file_list_is_refreshed_after_a_write(project) -> None:
    controller, provider = make(project, [
        Reply(tool_calls=(ToolCall("write_file", {"path": "src/fresh.py", "content": "x=1"}),)),
        Reply(text="done"),
    ])
    controller.send("add a file")
    assert "fresh.py" in provider.calls[-1][0].content


@needs_sandbox
def test_failed_run_triggers_repair_and_succeeds(project) -> None:
    (project.directory / "src" / "game.py").write_text("raise ValueError('boom')\n")
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("run_project", {}),)),
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "raise ValueError('boom')",
                                                 "new_text": "print('ok')"}),
                          ToolCall("run_project", {}))),
        Reply(text="Fixed it."),
    ])
    turn = controller.send("run it")
    assert turn.repair_attempts == 1
    assert not turn.gave_up


def test_repair_gives_up_after_three_attempts(project) -> None:
    """WORKORDER_01 section 28: cap automatic repairs, then explain."""
    (project.directory / "src" / "game.py").write_text("raise ValueError('boom')\n")
    always_failing = [Reply(tool_calls=(ToolCall("run_project", {}),))] + [
        Reply(tool_calls=(
            ToolCall("edit_file", {"path": "src/game.py",
                                   "old_text": "raise ValueError('boom')",
                                   "new_text": "raise ValueError('boom')"}),
            ToolCall("run_project", {}),
        )) for _ in range(MAX_REPAIR_ATTEMPTS + 2)
    ]
    controller, _ = make(project, always_failing)
    turn = controller.send("run it")
    assert turn.gave_up
    assert turn.repair_attempts == MAX_REPAIR_ATTEMPTS
    assert "three times" in turn.text


def test_refused_tool_does_not_stop_the_turn(project) -> None:
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("read_file", {"path": "../../escape.txt"}),)),
        Reply(text="I cannot reach that."),
    ])
    turn = controller.send("read outside")
    assert not turn.tool_results[0][1].ok
    assert turn.text == "I cannot reach that."


def test_build_and_teach_styles_differ(project) -> None:
    assert "JUST BUILD IT" in build_system_prompt(project, build_style="build")
    assert "TEACH ME" in build_system_prompt(project, build_style="teach")


def test_claiming_a_change_without_writing_is_challenged(project) -> None:
    """Phase 2 saw the model report an edit it never made. The app must not relay that."""
    controller, provider = make(project, [
        Reply(tool_calls=(ToolCall("read_file", {"path": "src/game.py"}),)),
        Reply(text="I increased the player speed from 5 to 8."),
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 8"}),)),
        Reply(text="Done - the speed is now 8."),
    ])
    controller.send("make the player faster")
    assert "PLAYER_SPEED = 8" in (project.directory / "src" / "game.py").read_text()
    assert any("did not actually change" in m.content for m in provider.calls[-1])


def test_honest_reply_with_no_change_is_not_challenged(project) -> None:
    """Only a false claim triggers the pushback, not an ordinary answer."""
    controller, provider = make(project, [Reply(text="That file uses arrow keys to move.")])
    turn = controller.send("how does the player move?")
    assert turn.text.startswith("That file uses")
    assert len(provider.calls) == 1


def test_claim_after_a_real_write_is_accepted(project) -> None:
    controller, provider = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 9"}),)),
        Reply(text="I increased the player speed to 9."),
    ])
    turn = controller.send("faster please")
    assert turn.text == "I increased the player speed to 9."
    assert len(provider.calls) == 2


# ------------------------------------------- Phase 12.1: the claim that survived once

#: Verbatim from the Phase 12.1 dispatch walk (SPIKES.md section 21). Every edit_file in
#: that turn was refused, ``src/game.py`` was byte-identical before and after, and this
#: is what the child was told.
_MEASURED_CLAIM = (
    "I'll build the spaceship and asteroid game from scratch with clean, working code.\n"
    "I replaced the old player movement with spaceship movement and added asteroid "
    "avoidance. The spaceship is white, moves with arrow keys, and the red asteroid "
    "moves left."
)


def test_a_repeated_false_claim_is_not_relayed_to_the_child(project) -> None:
    """The correction is one shot, and the claim came back through it.

    Phase 12.1 drove the real interface: the model claimed a change, was corrected, said
    the same thing again, and the application passed it on word for word. A child was
    told about a white spaceship and a red asteroid that had never been written.
    """
    controller, provider = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "# not in the file",
                                                 "new_text": "# whatever"}),)),
        Reply(text=_MEASURED_CLAIM),
        Reply(text=_MEASURED_CLAIM),
    ])
    turn = controller.send("Make a game where a spaceship moves around and avoids asteroids.")

    assert not any(result.changed_files for _, result in turn.tool_results)
    assert "spaceship" not in turn.text.lower()
    assert "haven't changed that yet" in turn.text
    # What is blocking is named, the tool's own model-facing wording is not, and no
    # cause is asserted that the application did not actually check.
    assert "didn't match the file cleanly" in turn.text
    assert "copy the line you want to change" not in turn.text
    # Still exactly one correction: the fix is about what happens after it, not about
    # spending more provider calls arguing.
    assert sum("did not actually change" in m.content
               for call in provider.calls for m in call if m.role == "user") == 1


def test_an_empty_reply_after_the_correction_does_not_let_the_claim_through(project) -> None:
    """The check must read what the child is told, not what this reply said.

    ``turn.text`` only takes a reply's text when that text is non-empty, so a model that
    answers the correction with **nothing** leaves the previous reply's claim standing as
    Gary's words. Checking ``reply.text`` sees an empty string, finds no claim, and
    relays the sentence unexamined -- which is how the first verification walk still put
    "I replaced the old player movement" in front of a child with the one-shot fix
    already in place.
    """
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "# not in the file",
                                                 "new_text": "# whatever"}),)),
        Reply(text=_MEASURED_CLAIM),
        Reply(text=""),
    ])
    turn = controller.send("Make a game where a spaceship moves around and avoids asteroids.")
    assert "spaceship" not in turn.text.lower()
    assert "haven't changed that yet" in turn.text


def test_the_correction_is_still_allowed_to_work(project) -> None:
    """Replacing the text is the last resort, not the first move.

    The pushback earns one round trip, and a model that takes it and makes the real edit
    must be reported as having made it. Losing this would trade a lie for a different
    lie.
    """
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "# not in the file",
                                                 "new_text": "# whatever"}),)),
        Reply(text=_MEASURED_CLAIM),
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 8"}),)),
        Reply(text="I increased the speed to 8."),
    ])
    turn = controller.send("faster please")
    assert "PLAYER_SPEED = 8" in (project.directory / "src" / "game.py").read_text()
    assert turn.text == "I increased the speed to 8."


def test_the_contracted_and_progressive_claims_the_model_really_used(project) -> None:
    """``i increased`` was covered and ``i've increased`` was not, and the model said both.

    Steps 27 and 29 of the walk were never challenged at all, because the hand-written
    phrase list happened to hold the past simple of these verbs and not the present
    perfect or the progressive.
    """
    for said in ("I've increased asteroid speed to 3.0 for faster movement.",
                 "I'm adding image loading for the spaceship.",
                 "I am creating the score counter now.",
                 "I have written the new level file."):
        assert AgentController._claimed_a_change_it_did_not_make(Turn(), said), said


def test_a_plain_denial_is_never_treated_as_a_claim(project) -> None:
    """The permitted outcome, including when it contains a claim verb.

    The correction asks the model to "say plainly that you have not changed anything
    yet". A compliant answer must not then be scored as a fresh lie -- and an honest
    admission often carries one of the verbs: "I made a mistake".
    """
    for said in ("I haven't changed anything yet. The asteroid speed is not updated.",
                 "I haven't changed anything -- I made a mistake reading the file.",
                 "I have not changed the speed yet.",
                 "I can't reach that file, so I did not change it.",
                 "Nothing changed. Tell me which line you mean."):
        assert not AgentController._claimed_a_change_it_did_not_make(Turn(), said), said


def test_a_suggestion_about_what_to_do_next_is_not_a_claim(project) -> None:
    """Future and modal forms are deliberately absent from the phrase set.

    The Games prompt asks Gary to suggest one thing to try next, so flagging "I'll add a
    score" would make the honest turn look like the dishonest one.
    """
    controller, provider = make(project, [
        Reply(text="That works. I'll add a score next if you want one."),
    ])
    turn = controller.send("what next?")
    assert turn.text.startswith("That works.")
    assert len(provider.calls) == 1


def test_research_asking_for_missing_data_is_left_alone(project) -> None:
    """The one profile that was behaving well must keep behaving well.

    PHASE_12_HANDOFF section 8: "act when the requested mutation is actionable, ask when
    required information is genuinely missing". Asking is not a claim and must not be
    replaced with one.
    """
    controller, provider = make(project, [
        Reply(text="What data do you want graphed? Point me to the file."),
    ])
    turn = controller.send("Graph this and tell me what changed the most.")
    assert turn.text.startswith("What data")
    assert len(provider.calls) == 1


# --------------------------------------------------------- checkpoints around a turn

def _versions(project):
    from opennest.versioning.checkpoint import VersionHistory
    versions = VersionHistory(project)
    versions.start()
    return versions


def make_versioned(project, replies):
    from opennest.versioning import git_manager
    if not git_manager.git_available():
        pytest.skip("git not available")
    provider = ScriptedProvider(replies)
    versions = _versions(project)
    controller = AgentController(
        project, provider, Toolbox(project), versions=versions
    )
    return controller, versions


def test_a_turn_that_changes_files_saves_a_checkpoint(project) -> None:
    controller, versions = make_versioned(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 8"}),)),
        Reply(text="Done."),
    ])
    before = len(versions.checkpoints())
    turn = controller.send("faster")
    assert turn.checkpoint is not None
    assert len(versions.checkpoints()) > before


def test_a_turn_that_changes_nothing_saves_no_checkpoint(project) -> None:
    """Section 29A: do not commit after every keystroke."""
    controller, versions = make_versioned(project, [Reply(text="It uses arrow keys.")])
    before = len(versions.checkpoints())
    turn = controller.send("how does it move?")
    assert turn.checkpoint is None
    assert len(versions.checkpoints()) == before


def test_undo_after_a_turn_restores_what_the_child_had(project) -> None:
    """The end-to-end promise: the assistant changed it, undo puts it back."""
    controller, versions = make_versioned(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 999"}),)),
        Reply(text="Done."),
    ])
    controller.send("much faster")
    assert "PLAYER_SPEED = 999" in project.entrypoint_path.read_text()

    versions.undo()
    assert "PLAYER_SPEED = 5" in project.entrypoint_path.read_text()


def test_the_agent_works_without_versioning(project) -> None:
    """Git is optional; the assistant must not depend on it."""
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 7"}),)),
        Reply(text="ok"),
    ])
    turn = controller.send("faster")
    assert turn.checkpoint is None
    assert "PLAYER_SPEED = 7" in project.entrypoint_path.read_text()


# ------------------------------------------- the headless playtest after a change
#
# Phase 12.4. The loop is driven here with a stubbed playtest, so every branch is fast
# and deterministic; tests/test_playtest.py runs the real harness, and the last test
# below runs both together.

def _write(n: int) -> Reply:
    """A reply that changes the project: a new file each time, so write_file accepts it."""
    return Reply(tool_calls=(ToolCall("write_file", {"path": f"src/part_{n}.py",
                                                     "content": f"PART = {n}\n"}),))


def _verdicts(controller, *verdicts):
    """Make the playtest answer these verdicts in order; returns the list of calls."""
    remaining = iter(verdicts)
    calls: list[str] = []

    def fake():
        verdict = next(remaining)
        calls.append(verdict)
        return playtest.Playtest(
            verdict, entry="src/game.py", frames=90, during="space",
            error="NameError: name 'rock' is not defined" if verdict == playtest.CRASHED
            else "",
        )

    controller.toolbox.playtest = fake
    return calls


def _last_instruction(provider, call: int) -> str:
    return [m for m in provider.calls[call] if m.role == "user"][-1].content


def test_a_frozen_game_is_sent_back_and_the_fix_is_accepted(project) -> None:
    controller, provider = make(project, [
        _write(1), Reply(text="The asteroids fall now."),
        _write(2), Reply(text="Fixed it -- they really fall now."),
    ])
    calls = _verdicts(controller, playtest.FROZEN, playtest.PASSED)

    turn = controller.send("make the asteroids fall")

    assert calls == [playtest.FROZEN, playtest.PASSED]
    assert [t.verdict for t in turn.playtests] == calls
    assert turn.repair_attempts == 1 and not turn.gave_up
    assert turn.text == "Fixed it -- they really fall now."
    feedback = _last_instruction(provider, 2)
    assert "every one was exactly the same picture" in feedback
    assert "Open Nest will test it again" in feedback


def test_a_crash_the_model_never_ran_is_caught_and_its_error_handed_over(project) -> None:
    """All ten crashes in the Phase 12.3 sample were in games nobody ran."""
    controller, provider = make(project, [
        _write(1), Reply(text="Added rocks."), _write(2), Reply(text="Fixed."),
    ])
    _verdicts(controller, playtest.CRASHED, playtest.PASSED)
    turn = controller.send("add rocks")
    assert not any(name == "run_project" for name, _ in turn.tool_results)
    assert "NameError: name 'rock' is not defined" in _last_instruction(provider, 2)
    assert turn.repair_attempts == 1 and not turn.gave_up


def test_a_game_that_keeps_failing_is_sent_back_at_most_three_times(project) -> None:
    replies = [_write(0), Reply(text="Done!")]
    for n in range(1, MAX_REPAIR_ATTEMPTS + 3):
        replies += [_write(n), Reply(text="Fixed!")]
    controller, _ = make(project, replies)
    _verdicts(controller, *[playtest.FROZEN] * 10)

    turn = controller.send("make it move")

    assert turn.repair_attempts == MAX_REPAIR_ATTEMPTS
    assert len(turn.playtests) == MAX_REPAIR_ATTEMPTS + 1
    assert turn.gave_up
    assert "nothing on screen moved" in turn.text and "Fixed!" not in turn.text


def test_an_answer_that_changes_nothing_is_pulled_up_not_tested_again(project) -> None:
    """Measured: handed the traceback, the model said it had fixed it and called no tool.

    Nothing is fixed, so the same code is never run again -- but the model is told so,
    and that spends an attempt, so a model that keeps narrating runs out like any other.
    """
    claim = Reply(text="I added the import for random at the top of the file.")
    controller, provider = make(project, [_write(1), Reply(text="Done!"), claim, claim, claim])
    _verdicts(controller, playtest.CRASHED)

    turn = controller.send("make it move")

    assert len(turn.playtests) == 1
    assert turn.repair_attempts == MAX_REPAIR_ATTEMPTS and turn.gave_up
    assert len(provider.calls) == 2 + MAX_REPAIR_ATTEMPTS
    assert "You did not change any file" in _last_instruction(provider, 3)
    assert "stops with the error above" in _last_instruction(provider, 3)
    assert "stopped with an error" in turn.text
    assert "import for random" not in turn.text


def test_pulled_up_the_model_can_still_make_the_fix(project) -> None:
    controller, _ = make(project, [
        _write(1), Reply(text="Done!"),
        Reply(text="I added the import."),
        _write(2), Reply(text="Now it really is imported."),
    ])
    _verdicts(controller, playtest.CRASHED, playtest.PASSED)

    turn = controller.send("make it move")

    assert [t.verdict for t in turn.playtests] == [playtest.CRASHED, playtest.PASSED]
    assert turn.repair_attempts == 2 and not turn.gave_up
    assert turn.text == "Now it really is imported."


def test_a_passing_game_costs_no_extra_call(project) -> None:
    controller, provider = make(project, [_write(1), Reply(text="Done.")])
    _verdicts(controller, playtest.PASSED)
    turn = controller.send("add a part")
    assert len(provider.calls) == 2 and turn.repair_attempts == 0
    assert turn.text == "Done." and not turn.gave_up


def test_a_turn_that_changes_nothing_is_not_tested(project) -> None:
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("read_file", {"path": "src/game.py"}),)),
        Reply(text="It has a square you can move."),
    ])
    calls = _verdicts(controller)
    controller.send("what does my game do?")
    assert calls == []


@pytest.mark.parametrize("verdict", [playtest.NO_WINDOW, playtest.INCONCLUSIVE,
                                     playtest.UNAVAILABLE])
def test_a_result_that_is_not_a_failure_is_never_repaired(project, verdict) -> None:
    controller, provider = make(project, [_write(1), Reply(text="Done.")])
    _verdicts(controller, verdict)
    turn = controller.send("change it")
    assert turn.repair_attempts == 0 and not turn.gave_up and len(provider.calls) == 2


def test_playtest_repairs_spend_from_the_turn_budget(project) -> None:
    controller, _ = make(project, [
        _write(1), Reply(text="Done."), _write(2), Reply(text="Fixed."),
    ])
    _verdicts(controller, playtest.FROZEN, playtest.PASSED)
    turn = controller.send("make it move")
    assert turn.usage.calls == 4
    assert turn.usage.calls_of(budget_mod.REPAIR) == 1


def test_every_failure_has_something_to_tell_the_child() -> None:
    from opennest.agent.controller import _PLAYTEST_GAVE_UP
    assert set(_PLAYTEST_GAVE_UP) == playtest.FAILURES


@needs_sandbox
def test_a_crash_after_a_playtest_repair_gets_only_what_is_left(project) -> None:
    """One repair budget per turn: the crash repair does not start again at three."""
    crash = ToolCall("edit_file", {
        "path": "src/game.py",
        "old_text": '"""A tiny game to build on. Change the numbers and see what happens."""',
        "new_text": "raise ValueError('boom')",
    })
    run = Reply(tool_calls=(ToolCall("run_project", {}),))
    controller, _ = make(project, [
        _write(1), Reply(text="Done."),
        Reply(tool_calls=(crash, ToolCall("run_project", {}))),
        run, run, run, run,
    ])
    _verdicts(controller, playtest.FROZEN)

    turn = controller.send("make it move")

    assert turn.repair_attempts == MAX_REPAIR_ATTEMPTS
    assert turn.gave_up


@needs_sandbox
def test_the_real_playtest_catches_a_frozen_game_and_accepts_the_fix(project) -> None:
    """End to end: a real edit freezes the starter, the real harness sees it, and the
    real harness passes the repair."""
    def speed(old: str, new: str) -> Reply:
        return Reply(tool_calls=(ToolCall("edit_file", {
            "path": "src/game.py", "old_text": f"PLAYER_SPEED = {old}",
            "new_text": f"PLAYER_SPEED = {new}",
        }),))

    controller, provider = make(project, [
        speed("5", "0"), Reply(text="Done."),
        speed("0", "5"), Reply(text="It moves again."),
    ])
    turn = controller.send("make the player slower")

    assert [t.verdict for t in turn.playtests] == [playtest.FROZEN, playtest.PASSED]
    assert turn.repair_attempts == 1 and turn.text == "It moves again."
    assert "same picture" in _last_instruction(provider, 2)
    # The headless test never touches the game on the child's screen.
    assert controller.toolbox.last_run is None


# ------------------------------------ two fallbacks Phase 12.4 showed to be wrong

@pytest.mark.parametrize("prose", ["", "I'll add a second square that slides."])
def test_a_tool_call_the_model_never_finished_is_answered_honestly(project, prose) -> None:
    """The provider keeps the raw protocol off the screen; the controller says why."""
    controller, provider = make(project, [Reply(text=prose, dropped_tool_call=True)])
    calls = _verdicts(controller)

    turn = controller.send("add a second square that slides on its own")

    assert turn.text.startswith("I haven't changed anything yet.")
    assert "<tool_call>" not in turn.text and "second square" not in turn.text
    assert len(provider.calls) == 1 and calls == []


def test_a_dropped_call_after_a_real_change_does_not_hide_the_change(project) -> None:
    controller, _ = make(project, [_write(1), Reply(text="", dropped_tool_call=True)])
    _verdicts(controller, playtest.PASSED)
    turn = controller.send("add a part")
    assert turn.text == "I changed src/part_1.py."


@needs_sandbox
def test_a_game_that_only_launched_is_said_to_have_started_not_to_work(project) -> None:
    """``RunResult.ok`` for a game means it survived four seconds. That is all it says."""
    controller, _ = make(project, [
        Reply(tool_calls=(
            ToolCall("edit_file", {"path": "src/game.py", "old_text": "PLAYER_SPEED = 5",
                                   "new_text": "PLAYER_SPEED = 6"}),
            ToolCall("run_project", {}),
        )),
        Reply(),  # acts, says nothing
    ])
    _verdicts(controller, playtest.PASSED)
    try:
        turn = controller.send("make the player a bit faster")
    finally:
        controller.toolbox.stop_running()
    assert turn.text == "I changed src/game.py and started it."
    assert "works" not in turn.text


@needs_sandbox
def test_a_crash_repair_that_only_got_the_game_launched_says_it_starts(project) -> None:
    game = project.entrypoint_path
    game.write_text("raise ValueError('boom')\n" + game.read_text(encoding="utf-8"))

    def speed(old: str, new: str) -> Reply:
        return Reply(tool_calls=(ToolCall("edit_file", {
            "path": "src/game.py", "old_text": f"PLAYER_SPEED = {old}",
            "new_text": f"PLAYER_SPEED = {new}"}),))

    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("run_project", {}),)),
        # Three repairs that change the file and never run it, the first one the fix:
        # the case _repair_actually_worked exists for.
        Reply(tool_calls=(ToolCall("edit_file", {
            "path": "src/game.py", "old_text": "raise ValueError('boom')\n",
            "new_text": ""}),)),
        speed("5", "6"),
        speed("6", "7"),
    ])
    _verdicts(controller, playtest.PASSED)
    try:
        turn = controller.send("run it")
    finally:
        controller.toolbox.stop_running()
    assert turn.text.startswith("That took a few tries, but it starts now.")
    assert "works" not in turn.text
