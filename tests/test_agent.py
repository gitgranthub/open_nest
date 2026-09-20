"""Agent loop behaviour, driven by a scripted provider.

A fake provider keeps these tests deterministic and fast. Real-model behaviour was
measured separately in Phase 1; what matters here is that the loop wires tools correctly,
refreshes state, and honours the repair cap.

The provider and the project fixture live in conftest.py, shared with test_rollover.py.
"""

from __future__ import annotations

import pytest

from opennest.agent.controller import (
    MAX_REPAIR_ATTEMPTS,
    AgentController,
    build_system_prompt,
    project_state,
)
from opennest.agent.tools import Toolbox
from opennest.ai.provider import Reply, ToolCall
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
    assert "You are the Assistant inside Open Nest" in prompt   # base
    assert "PROJECT TYPE: GAME" in prompt                        # profile
    assert "BUILD STYLE: BUILD IT AND TEACH ME" in prompt        # style
    assert "Use your tools to actually change" in prompt         # tool rules
    assert "CURRENT PROJECT" in prompt                           # state


def test_project_state_lists_files_so_no_tool_is_needed(project) -> None:
    state = project_state(project)
    assert "game.py" in state
    assert "you already know these" in state


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
