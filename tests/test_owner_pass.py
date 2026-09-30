"""The owner's first real test of Phase 13, and what it found (SPIKES.md section 27).

A Game project begun with Start Empty; "build a game that's an eagle flying over cars";
every ``edit_file`` written out as text in the chat and never run; the game on screen
still the Basic Game's orange square; and Gary saying "The eagle is now flying back and
forth" and "I see the eagle is missing". Then a plan whose first step was "done" when
nothing had changed, a starter added underneath it, and "next" carrying on regardless.

These tests pin each piece of the correction: a project with nothing in it is given its
starting files when a request needs them (and Blank only when the child names a game);
a tool call written as text is run, never shown; Gary reads what really happened rather
than his own earlier sentences; he is told what Open Nest has checked about the files,
the game on screen and the last message; "is now" and "I see" are caught when nothing
changed and nothing was seen; a plan step is done only when a file changed for it, and
"next" looks at the project before it carries on; and the Project panel says which files
the last message changed, and shows their code when clicked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent import evidence  # noqa: E402
from opennest.agent.controller import (  # noqa: E402
    AgentController,
    Plan,
    PlannedStep,
    is_question,
    presentable,
    project_state,
)
from opennest.agent.tools import Step, Toolbox  # noqa: E402
from opennest.ai.mlx_provider import reply_from_completion  # noqa: E402
from opennest.ai.provider import Reply, ToolCall  # noqa: E402
from opennest.execution import playtest  # noqa: E402
from opennest.fastpath.kinds import games  # noqa: E402
from opennest.projects.manager import create_project, source_fingerprint  # noqa: E402
from tests.conftest import ScriptedProvider  # noqa: E402

INPUTS = Path(__file__).resolve().parents[1] / "benchmarks" / "fastpath" / "inputs"

#: The owner's own words, and the 4B model's own reply to them, from the project archive.
OWNER_ASKED = ("Hi Gary. build a game that s an eagle flying over cars parked in a "
               "dealership. the dealership is called Trent Motors.")
WRITTEN_OUT = (
    "I'll add the eagle flying across the screen with simple left-right movement.\n\n"
    "```python\nedit_file(\n  path=\"src/game.py\",\n"
    "  old_text=\"    # Game loop\\n    for event in pygame.event.get():\\n\",\n"
    "  new_text=\"    # Game loop\\n    eagle_x = eagle_x + 5\\n\"\n)\n```"
)


def make(project, replies):
    provider = ScriptedProvider(replies)
    return AgentController(project, provider, Toolbox(project)), provider


def passing(controller, *verdicts):
    remaining = iter(verdicts or [playtest.PASSED] * 8)
    controller.toolbox.playtest = lambda: playtest.Playtest(next(remaining),
                                                            entry="src/game.py", frames=90)


@pytest.fixture
def empty_game(tmp_path):
    return create_project("Trent Motors", "games", starter_id=None, root=tmp_path)


# --------------------------------------------------- a call written out as text

def test_a_call_written_as_python_is_run_and_never_shown() -> None:
    reply = reply_from_completion(WRITTEN_OUT)
    assert [call.name for call in reply.tool_calls] == ["edit_file"]
    arguments = reply.tool_calls[0].arguments
    assert arguments["path"] == "src/game.py"
    # A Python string, read by Python: the escaped newline is a real one, as meant.
    assert arguments["old_text"] == "    # Game loop\n    for event in pygame.event.get():\n"
    assert reply.text == ("I'll add the eagle flying across the screen with simple "
                          "left-right movement.")
    assert not reply.dropped_tool_call


def test_a_written_call_cut_off_is_dropped_and_said_so() -> None:
    reply = reply_from_completion('I will add it.\nedit_file(path="src/game.py", '
                                  'old_text="x = 1\\n')
    assert reply.text == "I will add it." and reply.tool_calls == ()
    assert reply.dropped_tool_call


def test_a_written_call_with_a_value_that_is_not_plain_is_not_run() -> None:
    reply = reply_from_completion("edit_file(path=PATH, old_text='a', new_text='b')")
    assert reply.tool_calls == () and reply.dropped_tool_call and reply.text == ""


def test_prose_that_only_names_a_tool_is_left_alone() -> None:
    text = "I used edit_file to change the speed. The loop (the part that repeats) runs."
    reply = reply_from_completion(text)
    assert reply.text == text and reply.tool_calls == () and not reply.dropped_tool_call


def test_a_native_call_still_wins_over_one_in_the_prose() -> None:
    raw = ('<tool_call>{"name": "run_project", "arguments": {}}</tool_call>\n'
           'Next I could read_file("src/game.py").')
    reply = reply_from_completion(raw)
    assert [call.name for call in reply.tool_calls] == ["run_project"]
    assert "read_file" not in reply.text


def test_a_written_call_reaches_the_toolbox_through_the_ordinary_loop(project) -> None:
    written = reply_from_completion('Changing the speed.\nedit_file(path="src/game.py", '
                                    'old_text="PLAYER_SPEED = 5", new_text="PLAYER_SPEED = 9")')
    controller, _ = make(project, [written, Reply(text="The square moves faster.")])
    passing(controller)
    turn = controller.send("make the square faster")
    assert turn.tool_results[0][1].changed_files == ("src/game.py",)
    assert "PLAYER_SPEED = 9" in project.entrypoint_path.read_text()
    assert "edit_file" not in turn.text


def test_the_chat_never_carries_a_page_of_code_or_a_calls_arguments() -> None:
    long_block = "Here it is:\n```python\n" + "\n".join(f"x{i} = {i}" for i in range(12)) \
        + "\n```\nPress Run Game."
    assert presentable(long_block) == "Here it is:\nPress Run Game."
    short = "I made a variable:\n```python\nPLAYER_SPEED = 8\n```"
    assert presentable(short) == short
    assert presentable('Done.\n  old_text="a",\n  "new_text": "b"') == "Done."


# ------------------------------------------------- an empty project, and Blank

def test_an_empty_game_project_is_set_up_when_the_child_asks_for_a_game(empty_game) -> None:
    controller, provider = make(empty_game, [Reply(text="Here's a start.")])
    steps: list[Step] = []
    turn = controller.send(OWNER_ASKED, on_progress=steps.append)

    assert empty_game.entrypoint_path.is_file()
    assert turn.scaffolded == ("src/game.py",)
    assert turn.text.startswith("There was nothing in the project yet, so I started it "
                                "from the Basic Game")
    created = [s for s in steps if s.kind == "changed"]
    assert created and created[0].created and created[0].path == "src/game.py"
    # Gary's first sight of the project already has the file in it.
    assert "src/game.py is exactly the Basic Game starter" in provider.system_prompt
    # And it is not Gary's change: the honesty guard does not count it for him.
    assert all(not r.changed_files for _, r in turn.tool_results)


def test_a_question_in_an_empty_project_is_answered_not_built_for(empty_game) -> None:
    controller, provider = make(empty_game, [Reply(text="Tell me what to make.")])
    turn = controller.send("everything ok? what do i do now")
    assert not empty_game.entrypoint_path.exists() and turn.scaffolded == ()
    assert "There is no src/game.py yet" in provider.system_prompt


@pytest.mark.parametrize("text,asking", [
    ("what do I do now", True), ("how do I play this?", True),
    ("everything ok? what do i do now", True), ("where is the code", True),
    ("can you make me a game where an eagle flies?", False),
    ("make me a game where an eagle flies over cars", False),
    ("add another car", False),
])
def test_asking_is_told_from_asking_for(text, asking) -> None:
    assert is_question(text) is asking


def test_blank_stays_blank_until_the_child_names_a_game(tmp_path) -> None:
    blank = create_project("Blank Eagle", "blank", root=tmp_path)
    controller, _ = make(blank, [Reply(text="What would you like it to be?"),
                                 Reply(text="Here's a start.")])
    controller.send("make something with an eagle in it")
    assert not blank.entrypoint_path.exists()
    turn = controller.send("make me a game where an eagle flies over cars")
    assert turn.scaffolded == ("src/main.py",)
    assert "pygame" in blank.entrypoint_path.read_text()
    assert turn.text.startswith("There was nothing in the project yet, so I started it "
                                "as a game")


def test_a_project_with_files_is_never_given_a_starter(project) -> None:
    before = project.entrypoint_path.read_text()
    controller, _ = make(project, [Reply(text="Sure.")])
    turn = controller.send("make me a game where an eagle flies over cars")
    assert turn.scaffolded == () and project.entrypoint_path.read_text() == before


# ---------------------------------------------------- the history Gary reads

def test_a_caught_claim_is_not_left_for_the_next_turn_to_believe(project) -> None:
    claim = Reply(text="I added the eagle (a white circle). Now the eagle flies back and "
                       "forth.")
    controller, provider = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "# nowhere",
                                                 "new_text": "# x"}),)),
        claim, claim, Reply(text="What would you like?"),
    ])
    turn = controller.send("Make a game where an eagle flies over cars")
    assert "white circle" not in turn.text
    history = [m.content for m in controller.history[1:]]
    assert not any("white circle" in text for text in history)
    assert not any("You did not actually change" in text for text in history)
    # The calls and their results stay: they are what happened.
    assert any(m.role == "tool" for m in controller.history)
    assert controller.history[-1].content == turn.text
    controller.send("what now?")
    assert not any("white circle" in m.content for m in provider.calls[-1])


def test_gary_is_told_what_the_last_message_really_changed(project) -> None:
    controller, provider = make(project, [Reply(text="Here's how."), Reply(text="Ok.")])
    controller.send("how do I make it faster?")
    controller.send("what now?")
    assert "Last time, no file changed -- so nothing described in that reply was made." \
        in provider.system_prompt


def test_an_undo_or_a_starter_added_by_hand_is_passed_on(project) -> None:
    controller, provider = make(project, [Reply(text="Ok.")])
    controller.note_outside_change("Undo went back to the version saved as “Before”")
    controller.send("what now?")
    assert "Undo went back to the version saved as" in provider.system_prompt
    assert controller._outside == []            # said once, then it is history


# ------------------------------------------------------ what Open Nest has checked

def test_the_starter_the_game_still_is_and_what_is_in_it(project) -> None:
    state = project_state(project, toolbox=Toolbox(project))
    assert "src/game.py is exactly the Basic Game starter, unchanged" in state
    assert "the orange square, moved with the arrow keys" in state
    assert "the arrow keys (hold down): moves player; Escape (press): quits the game" in state


def test_controls_come_from_the_code_not_from_what_games_usually_do() -> None:
    source = ("import pygame\nkeys = pygame.key.get_pressed()\n"
              "if keys[pygame.K_a]:\n    eagle.x -= 3\nif keys[pygame.K_d]:\n    eagle.x += 3\n"
              "for event in pygame.event.get():\n"
              "    if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:\n"
              "        poop = 1\n")
    assert games.controls_read(source) == ["A (hold down): moves eagle",
                                           "D (hold down): moves eagle",
                                           "Space (press): changes poop"]
    assert games.controls_read("print('hi')\n") == []
    assert games.controls_read("if (:\n") is None


def test_unreadable_controls_are_said_to_be_unreadable(project) -> None:
    project.entrypoint_path.write_text("import pygame\nif (:\n")
    assert "Its controls cannot be read" in project_state(project)


class _Alive:
    def poll(self):
        return None


class _Output:
    stopped = False


def test_a_game_on_screen_older_than_the_files_is_called_older(project) -> None:
    from opennest.execution.python_runner import RunResult

    toolbox = Toolbox(project)
    toolbox.last_run = RunResult(exit_code=None, stdout="", stderr="", seconds=4.0,
                                 timed_out=False, still_running=True, process=_Alive(),
                                 output=_Output())
    toolbox.last_run_files = source_fingerprint(project.directory)
    assert "running, and it is the current code" in project_state(project, toolbox=toolbox)
    game = project.entrypoint_path
    game.write_text(game.read_text().replace("PLAYER_SPEED = 5", "PLAYER_SPEED = 9"))
    assert "an OLDER version" in project_state(project, toolbox=toolbox)


def test_a_test_result_is_only_given_while_it_is_about_this_code(project) -> None:
    toolbox = Toolbox(project)
    toolbox.last_playtest = playtest.Playtest(playtest.PASSED, entry="src/game.py", frames=90)
    toolbox.last_playtest_files = source_fingerprint(project.directory)
    assert "last test of this exact code" in project_state(project, toolbox=toolbox)
    game = project.entrypoint_path
    game.write_text(game.read_text() + "\n# changed\n")
    assert "changed since Open Nest last tested" in project_state(project, toolbox=toolbox)


def test_a_stopped_game_is_not_said_to_be_running(project) -> None:
    from opennest.execution.python_runner import RunResult

    class Gone:
        def poll(self):
            return 0

    run = RunResult(exit_code=None, stdout="", stderr="", seconds=4.0, timed_out=False,
                    still_running=True, process=Gone(), output=_Output())
    assert "it has stopped since" in project_state(project, run)


def test_the_guide_is_the_workbench_as_it_is() -> None:
    from opennest.projects.profiles import get_profile

    text = evidence.guide(get_profile("games"))
    for part in ("Run Game", "click inside the game", "Tab", "Undo", "Save a Version",
                 "Flight Deck", "+ Add to Project", "ASSETS", "no Publish or Share",
                 "Pop out", "Put back"):
        assert part in text, part
    assert "Compile" in evidence.guide(get_profile("arduino"))


# ---------------------------------------------------------- claims with no evidence

_LOOP = ("I'm going to add the eagle with a position, a size and a colour now.\n\n"
         "I'll now add the eagle with the three pieces above the loop and below the fill.\n\n"
         ) * 3


def test_a_reply_that_loops_is_split_into_steps_not_relayed(project) -> None:
    """The owner-test walk: the same paragraphs until the output cap, and no call."""
    plan = Reply(text="Add an eagle that flies across the top\nAdd parked cars along the "
                      "bottom")
    controller, provider = make(project, [Reply(text=_LOOP), plan,
                                          Reply(text="I'll add the eagle.")])
    turn = controller.send("build a game that's an eagle flying over cars in a dealership")
    assert turn.reduced and turn.fastpath["plan"][0] == "Add an eagle that flies across the top"
    assert _LOOP.split("\n\n")[0] not in turn.text


def test_a_denial_does_not_cover_work_said_to_be_under_way(project) -> None:
    measured = ("I haven't changed any file yet. Let me fix that. I'm adding the eagle with "
                "a defined position, size, and color.")
    controller, provider = make(project, [Reply(text=measured), Reply(text="Nothing yet.")])
    controller.send("add an eagle")
    assert "did not actually change any file" in provider.calls[-1][-1].content
    honest = "I haven't changed anything -- I made a mistake reading the file."
    controller, provider = make(project, [Reply(text=honest)])
    controller.send("add an eagle")
    assert len(provider.calls) == 1                       # still exempt, as in Phase 12.1


def test_is_now_with_nothing_changed_is_caught_even_after_a_denial(project) -> None:
    measured = ("I haven't changed any file yet. I'm adding the eagle and cars to the game. "
                "The eagle is now flying from left to right over the parked cars.")
    controller, provider = make(project, [Reply(text=measured),
                                          Reply(text="There's no eagle in the game yet.")])
    turn = controller.send("everything ok? what do i do now")
    assert "now flying" not in turn.text
    # A question: the correction fits an answer -- no "call edit_file", there are no tools.
    correction = provider.calls[-1][-1].content
    assert correction.startswith("Nothing in this project has changed lately")
    assert "edit_file" not in correction


def test_is_now_twice_for_a_question_gets_what_the_project_has(project) -> None:
    claim = Reply(text="The eagle is now flying back and forth across the screen.")
    controller, _ = make(project, [claim, claim])
    turn = controller.send("everything ok? what do i do now")
    assert "eagle" not in turn.text.lower()
    assert turn.text == ("I haven't changed anything in the game yet. Right now: The player "
                         "is the orange square, moved with the arrow keys. Nothing else is in "
                         "the game yet. To play it, press Run Game and click inside the game "
                         "so it gets the keys.")


def test_is_now_after_a_real_change_is_not_a_claim(project) -> None:
    controller, provider = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 9"}),)),
        Reply(text="The square is now faster."),
        Reply(text="It is now faster, yes."),
    ])
    passing(controller)
    controller.send("make it faster")
    turn = controller.send("is it faster?")             # the turn before changed a file
    assert turn.text == "It is now faster, yes." and len(provider.calls) == 3


def test_i_see_is_caught_when_nothing_was_shown(project) -> None:
    controller, provider = make(project, [
        Reply(text="I see the eagle is missing."),
        Reply(text="The code still has only the starter's square, so the eagle isn't in "
                   "it yet."),
    ])
    turn = controller.send("there is no eagle. just an orange square")
    assert turn.text.startswith("The code still has only the starter's square")
    assert "You cannot see the game" in provider.calls[-1][-1].content


def test_i_see_what_you_mean_is_not_a_look(project) -> None:
    controller, provider = make(project, [Reply(text="I see, you want it red.")])
    controller.send("i want red")
    assert len(provider.calls) == 1


# -------------------------------------------------------------- plans and "next"

def _plan(controller, *texts, offered=True):
    controller._plan = Plan(request="an eagle game", steps=[PlannedStep(t) for t in texts],
                            files=source_fingerprint(controller.project.directory),
                            offered=offered)
    return controller._plan


def test_a_step_that_did_not_land_is_not_done_and_is_offered_again(project) -> None:
    controller, provider = make(project, [Reply(text="I'll add the eagle."),
                                          Reply(text="Trying again.")])
    plan = _plan(controller, "Add a flying eagle", "Make it poop on the cars")
    turn = controller.send("next")
    assert plan.steps[0].status == "not_done"
    assert turn.text.startswith("Step 1 of 2: Add a flying eagle.")
    assert turn.text.endswith("That step didn't get made, so I haven't moved on to step 2. "
                              "Want me to try it again, or would you rather change something "
                              "else?")
    turn = controller.send("yes")
    assert turn.text.startswith("Step 1 of 2 didn't get made last time, so I'm trying it "
                                "again: Add a flying eagle.")
    assert provider.calls[-1][-1].content == "Add a flying eagle"


def test_a_step_that_landed_is_done_and_the_next_one_is_offered(project) -> None:
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 9"}),)),
        Reply(text="Faster now."),
    ])
    passing(controller)
    plan = _plan(controller, "Make the player faster", "Add cars")
    turn = controller.send("keep going")
    assert [s.status for s in plan.steps] == ["done", "todo"]
    assert turn.text.endswith("Next is step 2 of 2: “Add cars”. Want me to keep going?")


def test_next_looks_at_the_project_first_when_it_changed_underneath(project) -> None:
    controller, provider = make(project, [Reply(text="Ok.")])
    _plan(controller, "Add a flying eagle")
    game = project.entrypoint_path
    game.write_text(game.read_text() + "\n# the child changed this\n")
    controller.note_outside_change("The Basic Game starter was added from the Project panel")
    turn = controller.send("next")
    assert turn.text.startswith("Your project changed since the last step (The Basic Game "
                                "starter was added from the Project panel), so I looked at it "
                                "again and I'm working from what's there now.")
    assert "Do only step 1, against the files as they are now" in provider.system_prompt


def test_a_question_between_a_change_and_next_does_not_hide_the_change(project) -> None:
    controller, provider = make(project, [Reply(text="Arrow keys."), Reply(text="Ok.")])
    _plan(controller, "Add a flying eagle")
    game = project.entrypoint_path
    game.write_text(game.read_text() + "\n# undone\n")
    controller.note_outside_change("Undo went back to the version saved as \u201cX\u201d")
    controller.send("how do I play?")
    turn = controller.send("next")
    assert turn.text.startswith("Your project changed since the last step (Undo went back")


def test_an_undo_of_a_done_step_makes_it_not_done(project) -> None:
    controller, _ = make(project, [Reply(text="Ok.")])
    plan = _plan(controller, "Make the player faster", "Add cars")
    before = source_fingerprint(project.directory)
    game = project.entrypoint_path
    original = game.read_text()
    game.write_text(original.replace("PLAYER_SPEED = 5", "PLAYER_SPEED = 9"))
    plan.steps[0].status, plan.steps[0].before = "done", before
    plan.files = source_fingerprint(project.directory)
    game.write_text(original)                       # what Undo does to the bytes
    turn = controller.send("next")
    assert turn.text.startswith("Your project is back to how it was before step 1, so that "
                                "step isn't done any more. Step 1 of 2: Make the player faster.")


# --------------------------------------------------------------- the Workbench

@pytest.fixture
def bench(qt_app, project):
    from opennest.ui.workbench import Workbench

    widget = Workbench(project, AgentController(project, ScriptedProvider([]),
                                                Toolbox(project)))
    widget.show()
    yield widget
    widget.close()


def _item(bench, name):
    for index in range(bench._files.count()):
        if bench._files.item(index).text() == name:
            return bench._files.item(index)
    raise AssertionError(f"{name} is not in the Project panel")


def test_what_the_last_message_changed_is_marked_in_the_project_panel(bench) -> None:
    from opennest.ui.workbench import MARK_ROLE

    game = bench.project.entrypoint_path
    content = game.read_text().replace("PLAYER_SPEED = 5", "PLAYER_SPEED = 9")
    game.write_text(content)
    bench._progress(Step("changed", "changed src/game.py", path="src/game.py",
                         content=content, changed_lines=(4,)))
    (bench.project.directory / "src" / "eagle.py").write_text("EAGLE = 1\n")
    bench._progress(Step("changed", "created src/eagle.py", path="src/eagle.py",
                         content="EAGLE = 1\n", created=True))
    assert _item(bench, "src/game.py").data(MARK_ROLE) == "changed"
    assert _item(bench, "src/eagle.py").data(MARK_ROLE) == "new"
    assert "Changed in your last message" in _item(bench, "src/game.py").toolTip()


def test_clicking_a_file_shows_its_code_with_the_changed_lines_marked(bench) -> None:
    game = bench.project.entrypoint_path
    content = game.read_text().replace("PLAYER_SPEED = 5", "PLAYER_SPEED = 9")
    game.write_text(content)
    line = content.split("\n").index("PLAYER_SPEED = 9")
    bench._progress(Step("changed", "changed src/game.py", path="src/game.py",
                         content=content, changed_lines=(line,)))
    bench._panel_text("something else")
    bench._open_file(_item(bench, "src/game.py"))
    assert bench._output.toPlainText() == content
    assert bench._code_caption.text() == "src/game.py — 1 line changed in your last message"
    assert len(bench._output.extraSelections()) == 1


def test_a_file_not_changed_lately_is_shown_plainly(bench) -> None:
    bench._open_file(_item(bench, "src/game.py"))
    assert bench._code_caption.text() == "src/game.py"
    assert bench._output.extraSelections() == []


def test_undo_clears_the_marks_and_tells_gary(bench, monkeypatch) -> None:
    from opennest.ui.workbench import MARK_ROLE

    noted = []
    monkeypatch.setattr(bench.controller, "note_outside_change",
                        lambda what, **_: noted.append(what))

    class Restored:
        label = "Before Gary made changes"

    class Versions:
        can_undo = True

        def undo(self):
            return Restored()

    bench.versions = Versions()
    bench._recent = {"src/game.py": Step("changed", "", path="src/game.py", content="x")}
    bench._undo()
    assert _item(bench, "src/game.py").data(MARK_ROLE) is None
    assert noted == ["Undo went back to the version saved as “Before Gary made "
                     "changes”"]


def test_adding_a_starter_by_hand_marks_it_new_and_tells_gary(qt_app, tmp_path,
                                                               monkeypatch) -> None:
    from opennest.ui.workbench import MARK_ROLE, Workbench

    project = create_project("Empty", "games", starter_id=None, root=tmp_path)
    widget = Workbench(project, AgentController(project, ScriptedProvider([]),
                                                Toolbox(project)))
    noted = []
    monkeypatch.setattr(widget.controller, "note_outside_change", noted.append)
    try:
        widget._add_starter("pygame_basic")
        assert _item(widget, "src/game.py").data(MARK_ROLE) == "new"
        assert noted == ["The Basic Game starter was added from the Project panel"]
    finally:
        widget.close()


# ------------------------------------------------ a question is answered, not built

def test_a_question_is_answered_with_no_tools_and_no_building_prompt(project) -> None:
    controller, provider = make(project, [Reply(text="Press Run Game, then the arrows.")])
    turn = controller.send("how do I play this?")
    assert turn.answered and provider.tools_offered[-1] == []
    assert "THEY ASKED A QUESTION" in provider.system_prompt
    assert "A thing in the game needs three pieces" not in provider.system_prompt
    assert "the arrow keys (hold down): moves player" in provider.system_prompt
    # And the next message is back to the ordinary prompt with its tools.
    controller.provider.replies.append(Reply(text="Ok."))
    controller.send("make the square faster")
    assert provider.tools_offered[-1] and "THEY ASKED A QUESTION" not in provider.system_prompt


def test_a_call_written_into_an_answer_is_not_run(project) -> None:
    before = project.entrypoint_path.read_text()
    written = reply_from_completion('Sure.\nedit_file(path="src/game.py", '
                                    'old_text="PLAYER_SPEED = 5", new_text="PLAYER_SPEED = 9")')
    controller, _ = make(project, [written])
    turn = controller.send("what are the controls?")
    assert project.entrypoint_path.read_text() == before and turn.tool_results == []
    assert turn.text == "Sure."


def test_a_question_never_reaches_a_recipe(project) -> None:
    asked = []

    class Router:
        # Recorded, not raised: the controller catches whatever the Fast Path raises, so
        # a raising stand-in could never fail this test (HANDOFF section 4's vacuous-
        # assertion traps).
        def handle(self, *args, **kwargs):
            asked.append(args)
            raise RuntimeError("should not be asked")

    controller, _ = make(project, [Reply(text="The arrow keys move the square.")])
    controller.fastpath = Router()
    turn = controller.send("what are the controls?")
    assert turn.text == "The arrow keys move the square." and asked == []


def test_an_answer_naming_a_thing_the_code_has_not_got_is_corrected(project) -> None:
    controller, provider = make(project, [
        Reply(text="Sure, I can help."),
        Reply(text="Use the arrow keys to move the eagle. It flies over the cars below."),
        Reply(text="The arrow keys move the orange square. There's no eagle yet."),
    ])
    controller.send("make a game where an eagle flies over the cars")   # asked for them
    turn = controller.send("how do I play this?")
    assert turn.text == "The arrow keys move the orange square. There's no eagle yet."
    correction = provider.calls[-1][-1].content
    assert correction.startswith("Answer this again: \u201chow do I play this?\u201d. "
                                 "Do not say the game has a")
    assert "Right now, from the code: The player is the orange square" in correction


def test_a_thing_the_code_does_have_is_not_questioned(project) -> None:
    game = project.entrypoint_path
    game.write_text(game.read_text() + "\neagle = pygame.Rect(0, 0, 10, 10)\n")
    controller, provider = make(project, [Reply(text="Ok."),
                                          Reply(text="Arrow keys move the square; the eagle "
                                                     "sits at the top.")])
    controller.send("i like the eagle")
    controller.send("how do I play this?")
    assert len(provider.calls) == 2


def test_a_promise_with_nothing_done_is_split_into_steps(project) -> None:
    controller, _ = make(project, [
        Reply(text="I'll add the eagle, poop, and cars now. I'll do that now."),
        Reply(text="Add an eagle across the top\nAdd parked cars along the bottom"),
        Reply(text="Starting."),
    ])
    turn = controller.send("make the eagle drop poop and put five cars along the bottom")
    assert turn.reduced and "I'll do that now" not in turn.text


def test_a_question_back_to_the_child_is_a_fair_way_to_end(project) -> None:
    controller, provider = make(project, [Reply(text="I'll add it -- what colour should "
                                                     "the eagle be?")])
    turn = controller.send("add an eagle")
    assert not turn.reduced and len(provider.calls) == 1


def test_a_thing_named_after_only_the_starter_was_set_up_is_still_caught(empty_game) -> None:
    controller, provider = make(empty_game, [
        Reply(text="Look for the eagle moving back and forth over the parked cars."),
        Reply(text="There's no eagle in the game yet -- want me to start on it?"),
    ])
    turn = controller.send(OWNER_ASKED)
    assert "Look for the eagle" not in turn.text
    # A request turn: the correction says the thing is not there and how to make it
    # (Phase 13C); an answer turn keeps "Do not say the game has a...".
    assert "its files have none" in provider.calls[1][-1].content


def test_a_promise_in_an_answer_is_made_an_offer(project) -> None:
    controller, _ = make(project, [Reply(text="There's no eagle yet. I'll add the eagle now.")])
    turn = controller.send("why is there no eagle?")
    assert turn.text == "There's no eagle yet. I'll add the eagle now.\n\nWant me to go ahead?"


# ------------------------------------------------------- in the code, never drawn

_EAGLE_ONLY_MADE = ("player = pygame.Rect(WIDTH // 2, HEIGHT // 2, PLAYER_SIZE, PLAYER_SIZE)",
                    "eagle = pygame.Rect(400, 300, 20, 30)\n"
                    "player = pygame.Rect(WIDTH // 2, HEIGHT // 2, PLAYER_SIZE, PLAYER_SIZE)")


def test_a_thing_made_but_never_drawn_is_said_to_be_off_screen(project) -> None:
    game = project.entrypoint_path
    game.write_text(game.read_text().replace(*_EAGLE_ONLY_MADE))
    source = game.read_text()
    assert evidence.undrawn(source, {"eagle"}) == ["eagle"]
    drawn = source.replace("    pygame.draw.rect(screen, PLAYER_COLOUR, player)",
                           "    pygame.draw.rect(screen, PLAYER_COLOUR, player)\n"
                           "    pygame.draw.rect(screen, (250, 250, 250), eagle)")
    assert evidence.undrawn(drawn, {"eagle"}) == []
    assert "The code has eagle in it, but nothing draws it" in project_state(
        project, asked=["eagle"])


def test_a_step_whose_thing_is_not_drawn_is_not_done(project) -> None:
    old, new = _EAGLE_ONLY_MADE
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py", "old_text": old,
                                                 "new_text": new}),)),
        Reply(text="Look for the eagle. It's there."),
    ])
    passing(controller)
    plan = _plan(controller, "Add an eagle to the screen", "Make the eagle fly")
    turn = controller.send("next")
    assert plan.steps[0].status == "not_done"
    assert turn.text.endswith("The eagle is in the code now, but nothing draws it yet, so it "
                              "isn't on screen. I haven't moved on to step 2. Want me to try "
                              "it again?")


def test_a_reply_that_loops_after_a_real_change_is_replaced_with_what_happened(project) -> None:
    loop = "Look for the eagle.\nIt's there.\nBut it doesn't move.\n" * 4
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 9"}),)),
        Reply(text=loop),
    ])
    passing(controller)
    turn = controller.send("make it faster")
    assert turn.text == "I changed src/game.py."


def test_a_plan_step_is_never_planned_again(project) -> None:
    controller, provider = make(project, [
        Reply(text="I'll do it.", dropped_tool_call=True),    # cut off: nothing changed
        Reply(text="Should never be asked."),
    ])
    plan = _plan(controller, "Drop poop when space is pressed", "Park five cars")
    turn = controller.send("next")
    assert len(provider.calls) == 1 and not turn.reduced
    assert [s.text for s in plan.steps] == ["Drop poop when space is pressed", "Park five cars"]
    assert plan.steps[0].status == "not_done"


def test_a_promise_in_an_answer_offers_the_waiting_step(project) -> None:
    controller, _ = make(project, [Reply(text="The eagle isn't in yet. I'll add it now.")])
    _plan(controller, "Add an eagle", "Add cars", offered=False)
    turn = controller.send("what do I do now?")
    assert turn.text.endswith("Want me to start on step 1, \u201cAdd an eagle\u201d?")
    assert controller._plan.offered


def test_work_said_to_be_under_way_in_an_answer_is_caught(tmp_path) -> None:
    blank = create_project("Blank", "blank", root=tmp_path)
    measured = ("I'll set up the basic file for you.\n\nCreating src/main.py with a "
                "placeholder.\n\nLook for it in the project files. It's there now.")
    controller, provider = make(blank, [Reply(text=measured),
                                        Reply(text="There's nothing here yet. Tell me what "
                                                   "you'd like to make.")])
    turn = controller.send("what do I do now?")
    assert "Creating" not in turn.text and not blank.entrypoint_path.exists()
    assert provider.calls[-1][-1].content.startswith("Nothing in this project has changed")


def test_clicking_a_file_while_the_game_plays_keeps_the_game_one_click_away(bench) -> None:
    from types import SimpleNamespace

    from opennest.ui.workbench import SHOW_GAME

    bench._live_run = SimpleNamespace(live=None, process=None)
    bench._game.show()
    bench._open_file(_item(bench, "src/game.py"))
    assert bench._game.isHidden() and bench._output.toPlainText().startswith('"""A tiny game')
    assert bench._code_button.text() == SHOW_GAME and not bench._code_button.isHidden()
    bench._toggle_code()
    assert not bench._game.isHidden()
    assert bench._code_button.isHidden()      # no turn's code to offer instead


def test_a_comment_is_not_a_thing_in_the_game(project) -> None:
    game = project.entrypoint_path
    game.write_text("# the eagle flies over the cars\n" + game.read_text())
    controller, provider = make(project, [
        Reply(text="Ok."),
        Reply(text="The cars are parked below."),
        Reply(text="There are no cars in the game yet."),
    ])
    controller.send("make a game where an eagle flies over the cars")
    turn = controller.send("everything ok?")
    assert turn.text == "There are no cars in the game yet."


def test_an_edit_that_changes_nothing_is_not_a_change(project) -> None:
    toolbox = Toolbox(project)
    before = project.entrypoint_path.read_text()
    result = toolbox.dispatch("edit_file", {"path": "src/game.py",
                                            "old_text": "PLAYER_SPEED = 5",
                                            "new_text": "PLAYER_SPEED = 5"})
    assert not result.ok and result.reason == "no_change" and result.changed_files == ()
    assert project.entrypoint_path.read_text() == before


def test_a_step_that_did_not_land_says_so_once(project) -> None:
    miss = Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                    "old_text": "NOT THERE", "new_text": "x"}),))
    controller, _ = make(project, [miss, miss, miss])
    _plan(controller, "Add an eagle", "Add cars")
    turn = controller.send("next")
    assert "Say it again" not in turn.text and "one small piece" not in turn.text
    assert turn.text == ("Step 1 of 2: Add an eagle.\n\nI haven't changed that yet. My edit "
                         "didn't match the file cleanly, so I left it alone.\n\nThat step "
                         "didn't get made, so I haven't moved on to step 2. Want me to try it "
                         "again, or would you rather change something else?")


# ------------------------------------------------------------- the other project types

def test_clicking_a_file_on_a_website_keeps_the_page_one_click_away(qt_app, tmp_path) -> None:
    from opennest.ui.workbench import SHOW_PAGE, Workbench

    project = create_project("Dog Club", "website", root=tmp_path)
    widget = Workbench(project, AgentController(project, ScriptedProvider([]),
                                                Toolbox(project)))
    try:
        widget.show()
        assert not widget._web.isHidden()
        widget._open_file(_item(widget, "src/index.html"))
        assert widget._web.isHidden() and "<html" in widget._output.toPlainText().lower()
        assert widget._code_button.text() == SHOW_PAGE
        widget._toggle_code()
        assert not widget._web.isHidden()
        widget._open_file(_item(widget, "src/styles.css"))
        widget._web.show_page = lambda url: True
        widget._preview()                           # Preview always brings the page back
        assert not widget._web.isHidden()
    finally:
        widget.release()
        widget.close()


def test_blank_game_is_played_in_the_panel(tmp_path) -> None:
    from opennest.projects.manager import plays_in_panel

    blank = create_project("Blank", "blank", root=tmp_path)
    assert not plays_in_panel(blank)
    blank.entrypoint_path.write_text("print('hello')\n")
    assert not plays_in_panel(blank)
    blank.entrypoint_path.write_text("import pygame\n")
    assert plays_in_panel(blank)
    assert not plays_in_panel(create_project("Site", "website", root=tmp_path))


@pytest.mark.parametrize("profile,entry", [("website", "src/index.html"),
                                           ("research", "src/analysis.py"),
                                           ("raspberry_pi", "src/main.py"),
                                           ("arduino", "src/project/project.ino")])
def test_every_typed_project_started_empty_is_set_up_on_its_first_request(
        tmp_path, profile, entry) -> None:
    project = create_project("Empty", profile, starter_id=None, root=tmp_path)
    controller, provider = make(project, [Reply(text="Here's a start.")])
    turn = controller.send("make me something about my dog")
    assert (project.directory / entry).is_file(), profile
    assert entry in turn.scaffolded
    assert "There was nothing in the project yet, so I started it from the" in turn.text


@pytest.mark.parametrize("profile", ["website", "research", "raspberry_pi", "arduino"])
def test_every_project_type_answers_a_question_from_its_own_screen(project, tmp_path,
                                                                   profile) -> None:
    typed = create_project("Q", profile, root=tmp_path)
    controller, provider = make(typed, [Reply(text="Here's how.")])
    turn = controller.send("what do I do now?")
    assert turn.answered and provider.tools_offered[-1] == []
    assert "OPEN NEST -- THE SCREEN THEY SEE" in provider.system_prompt
    assert typed.profile.run_label in provider.system_prompt
    assert "WHAT OPEN NEST HAS CHECKED" in provider.system_prompt



def test_a_thing_made_again_every_frame_is_said_to_be_stuck(project) -> None:
    game = project.entrypoint_path
    source = game.read_text().replace(
        "    player.clamp_ip(screen.get_rect())",
        "    player.clamp_ip(screen.get_rect())\n    eagle = pygame.Rect(300, 200, 30, 30)\n"
        "    eagle.x += 3")
    game.write_text(source)
    assert evidence.made_every_frame(source, {"eagle"}) == ["eagle"]
    assert evidence.made_every_frame(game.read_text().replace(
        "    eagle = pygame.Rect(300, 200, 30, 30)\n", ""), {"eagle"}) == []
    assert "The eagle is made again inside the game loop every frame" in project_state(
        project, asked=["eagle"])



def test_a_blank_game_is_checked_for_things_it_has_not_got(tmp_path) -> None:
    blank = create_project("Blank", "blank", root=tmp_path)
    controller, provider = make(blank, [
        Reply(text="Here's a start."),
        Reply(text="Eagle now flies with the arrow keys."),
        Reply(text="The orange square moves with the arrow keys; there's no eagle yet."),
    ])
    controller.send("make me a game where an eagle flies over cars")
    assert blank.entrypoint_path.is_file()
    turn = controller.send("how do I play it?")
    assert turn.text.startswith("The orange square moves")
    assert "Do not say the game has a" in provider.calls[-1][-1].content



def test_a_thing_named_again_after_its_correction_is_not_relayed(project) -> None:
    controller, _ = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 7"}),)),
        Reply(text="The eagle is now flying with the arrow keys."),
        Reply(text="The eagle flies left and right now."),
    ])
    passing(controller)
    turn = controller.send("make a game where an eagle flies over the cars")
    assert "eagle" not in turn.text.lower()
    assert turn.text.startswith("I changed src/game.py.")
    assert "Right now: The player is the orange square" in turn.text



def test_things_gary_drew_under_his_own_names_are_not_said_to_be_absent(project) -> None:
    game = project.entrypoint_path
    game.write_text(game.read_text().replace(
        "    pygame.draw.rect(screen, PLAYER_COLOUR, player)",
        "    pygame.draw.rect(screen, PLAYER_COLOUR, player)\n"
        "    for i in range(5):\n"
        "        pygame.draw.rect(screen, (100, 100, 100), (i * 100, 430, 60, 40))"))
    about = evidence.describe_game(project)
    assert "Nothing else is in the game yet" not in about
    assert "It draws other things too" in about
    assert "Nothing else is in the game yet" in evidence.describe_game(
        create_project("Plain", "games", root=project.directory.parent))


# ------------------------------------------------------------ the parity pass

def test_a_run_that_drew_a_chart_did_something(tmp_path) -> None:
    """Measured: "Graph this." ran the Research starter, which drew charts/chart.png, and
    the turn was planned into steps and reported as having changed nothing."""
    from opennest.assets import manager as assets

    research = create_project("Weather", "research", root=tmp_path)
    assets.import_file(research, INPUTS / "weather.csv")
    controller, provider = make(research, [Reply(tool_calls=(ToolCall("run_project", {}),)),
                                           Reply(text="")])
    from opennest.security.process_sandbox import sandbox_available

    if not sandbox_available():
        pytest.skip("the process sandbox cannot be applied here")
    turn = controller.send("graph this")
    made = turn.tool_results[0][1].made_files
    assert made and made[0].startswith("charts/")
    assert not turn.reduced and f"It drew {made[0]}." in turn.text
    state = project_state(research, toolbox=controller.toolbox)
    assert f"{made[0]} (drawn by the last run)" in state


def test_each_preset_is_described_from_its_own_files(tmp_path) -> None:
    from opennest.assets import manager as assets

    site = create_project("Site", "website", root=tmp_path)
    (site.directory / "src" / "index.html").write_text(
        "<h1>Dino World</h1><section><h2>Fossils</h2><img src='assets/trex.png'></section>")
    state = project_state(site, toolbox=Toolbox(site))
    assert "1 section; headings “Dino World”; “Fossils”" in state
    assert "not in the project, so they appear broken: assets/trex.png" in state
    assert "Nobody in Open Nest can see the page" in state

    sketch = create_project("Blink", "arduino", root=tmp_path)
    state = project_state(sketch, toolbox=Toolbox(sketch))
    assert "LED_PIN = LED_BUILTIN (the board's own light, no wire)" in state
    assert "No board is chosen yet" in state and "Nothing in Open Nest can see or test" in state

    pi = create_project("Car", "raspberry_pi", root=tmp_path)
    main = pi.entrypoint_path
    main.write_text(main.read_text().replace("LED_PIN = 17", "LED_PIN = 22"))
    state = project_state(pi, toolbox=Toolbox(pi))
    assert "BCM pin 22" in state and "Nothing has run on a real Raspberry Pi" in state

    research = create_project("Weather", "research", root=tmp_path)
    assets.import_file(research, INPUTS / "weather.csv")
    state = project_state(research, toolbox=Toolbox(research))
    assert "data/weather.csv, read from the file: 180 rows" in state
    assert "city (Leeds, Seville, Oslo)" in state and "No chart exists yet" in state


def test_a_blank_project_says_what_it_cannot_do_for_what_it_has_become(tmp_path) -> None:
    blank = create_project("Blank", "blank", root=tmp_path)
    (blank.directory / "src" / "index.html").write_text("<h1>Hi</h1>")
    assert "cannot show a web page. A Website project can" in project_state(blank)


def test_clicking_a_chart_shows_the_picture(qt_app, tmp_path) -> None:
    import shutil as _shutil

    from opennest.ui.workbench import Workbench

    research = create_project("Weather", "research", root=tmp_path)
    (research.directory / "charts").mkdir()
    _shutil.copy(Path(__file__).resolve().parents[1] / "assets" / "nest_bw.png",
                 research.directory / "charts" / "chart.png")
    widget = Workbench(research, AgentController(research, ScriptedProvider([]),
                                                 Toolbox(research)))
    try:
        widget.show()
        widget._open_file(_item(widget, "charts/chart.png"))
        assert not widget._chart.isHidden()
        assert widget._chart_caption.text().startswith("charts/chart.png")
    finally:
        widget.release()
        widget.close()


def test_an_undo_marks_the_reply_it_took_back(project) -> None:
    controller, provider = make(project, [Reply(text="The gallery is added."),
                                          Reply(text="Ok.")])
    controller.send("add a gallery")
    controller.note_outside_change("Undo went back to X", undone=True)
    assert "the change described here is no longer in the files" in \
        controller.history[-1].content
    turn = controller.send("what now?")
    assert "[Open Nest" not in turn.text


def test_i_see_as_an_opening_is_dropped() -> None:
    assert presentable("I see. The section is in index.html.") == \
        "The section is in index.html."
    assert presentable("I see the problem.") == "I see the problem."   # the guard's job


def test_promises_are_read_as_a_pattern() -> None:
    from opennest.agent.replies import promises

    for said in ("Let me create the basic structure.", "I'll edit index.html now.",
                 "I'm going to draw a chart."):
        assert promises(said), said
    assert not promises("You could add a chart next.")



def test_an_answer_about_a_real_earlier_change_is_not_pulled_up(project) -> None:
    """Measured on the parity walk: "I added the Fossils section" -- true, a recipe had
    just done it -- was "corrected" with "Call edit_file now" in a turn with no tools."""
    controller, provider = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 9"}),)),
        Reply(text="Faster now."),
        Reply(text="I increased the player speed from 5 to 9."),
    ])
    passing(controller)
    controller.send("make it faster")
    turn = controller.send("what did you change?")
    assert turn.text == "I increased the player speed from 5 to 9." and len(provider.calls) == 3


def test_a_website_is_checked_for_things_its_page_has_not_got(tmp_path) -> None:
    site = create_project("Dino", "website", root=tmp_path)
    controller, provider = make(site, [
        Reply(text="Here's a start."),
        Reply(text="The gallery is in the page with five dinosaur cards."),
        Reply(text="There's no gallery on the page yet."),
    ])
    controller.send("add a gallery with five dinosaur cards")
    controller.note_outside_change("Undo went back to X", undone=True)
    turn = controller.send("why can't I see it?")
    assert "no gallery" in turn.text
    correction = provider.calls[-1][-1].content
    assert "Do not say the project has a" in correction and "its files have none" in correction
    assert "Right now the page has" in correction


def test_blank_becomes_a_data_or_pi_project_and_says_what_it_cannot_become(tmp_path) -> None:
    data = create_project("D", "blank", root=tmp_path / "d")
    controller, _ = make(data, [Reply(text="Here's a start.")])
    turn = controller.send("Analyze this CSV.")
    assert "import pandas" in data.entrypoint_path.read_text()
    assert (data.directory / "src" / "matplotlibrc").is_file()
    assert turn.text.startswith("There was nothing in the project yet, so I started it as a "
                                "data project")

    pi = create_project("P", "blank", root=tmp_path / "p")
    controller, _ = make(pi, [Reply(text="Here's a start.")])
    controller.send("Make a Pi project.")
    assert "LED_PIN = 17" in pi.entrypoint_path.read_text()

    for said, kind in (("Make me a website.", "Website"),
                       ("Write an Arduino project.", "Arduino")):
        blank = create_project(kind, "blank", root=tmp_path / kind)
        controller, provider = make(blank, [])
        turn = controller.send(said)
        assert turn.routed and provider.calls == [] and not blank.entrypoint_path.exists()
        assert f"start {'an' if kind == 'Arduino' else 'a'} {kind} project instead" in turn.text


def test_a_compile_claimed_with_nothing_compiled_is_caught(tmp_path) -> None:
    sketch = create_project("Blink", "arduino", root=tmp_path)
    controller, provider = make(sketch, [
        Reply(tool_calls=(ToolCall("edit_file", {
            "path": "src/project/project.ino",
            "old_text": "const unsigned long ON_MILLISECONDS = 500;",
            "new_text": "const unsigned long ON_MILLISECONDS = 100;"}),)),
        Reply(text="I compiled the project. The LED now blinks every 100ms."),
        Reply(text="The LED stays on for 100ms now. Press Compile to check it."),
    ])
    turn = controller.send("make the light stay on shorter")
    assert "I compiled" not in turn.text
    assert provider.calls[-1][-1].content.startswith("Nothing was run, compiled or tested")


def test_a_file_changed_between_messages_is_noticed(project) -> None:
    controller, provider = make(project, [Reply(text="Ok."), Reply(text="Ok.")])
    controller.send("hello")
    game = project.entrypoint_path
    game.write_text(game.read_text().replace("PLAYER_SPEED = 5", "PLAYER_SPEED = 2"))
    controller.send("how fast is the square?")
    assert "src/game.py changed since your last reply, and not by you" in \
        provider.system_prompt


def test_an_answer_gets_the_checked_facts_beside_the_question(project) -> None:
    controller, provider = make(project, [Reply(text="The arrow keys.")])
    controller.send("how do I play this?")
    sent = provider.calls[-1][-1].content
    assert sent.startswith("how do I play this?\n\n(WHAT OPEN NEST HAS CHECKED:")
    assert "the arrow keys (hold down)" in sent
    assert controller.history[1].content == "how do I play this?"   # kept as said


def test_a_bare_json_call_is_read_and_never_shown() -> None:
    raw = ('I will now edit it.\n\n{"name": "edit_file", "arguments": {"path": "src/main.py",'
           ' "old_text": "BLINKS = 3", "new_text": "BLINKS = 10"}}\n\nWant me to go ahead?')
    reply = reply_from_completion(raw)
    assert [c.name for c in reply.tool_calls] == ["edit_file"]
    assert "edit_file" not in reply.text and "Want me to go ahead?" in reply.text
    assert presentable('{"name": "edit_file", "arguments": {}}\nOk.') == "Ok."


def test_compiling_without_a_board_is_said_to_the_child(qt_app, tmp_path,
                                                        monkeypatch) -> None:
    from opennest.execution import arduino
    from opennest.ui.workbench import Workbench

    monkeypatch.setattr(arduino, "available", lambda: True)
    monkeypatch.setattr(arduino, "boards", lambda: [])
    sketch = create_project("Blink", "arduino", root=tmp_path)
    widget = Workbench(sketch, AgentController(sketch, ScriptedProvider([]),
                                               Toolbox(sketch)))
    try:
        widget._run()
        said = widget._output.toPlainText()
        assert said.startswith("Choose which Arduino you have first")
        assert "Ask the child" not in said
    finally:
        widget.release()
        widget.close()


def test_a_page_turn_that_points_at_a_missing_picture_says_so(tmp_path) -> None:
    site = create_project("Dino", "website", root=tmp_path)
    page = site.directory / "src" / "index.html"
    old = page.read_text().split("\n")[0]
    controller, _ = make(site, [
        Reply(tool_calls=(ToolCall("edit_file", {
            "path": "src/index.html", "old_text": old,
            "new_text": old + "\n<img src=\"../assets/dinosaurs.jpg\" alt=\"dinos\">"}),)),
        Reply(text="The picture shows a T-Rex."),
    ])
    turn = controller.send("add a picture of dinosaurs")
    assert "The page now points at ../assets/dinosaurs.jpg, which is not in the project" \
        in turn.text


def test_a_menu_is_a_nav_on_a_page(tmp_path) -> None:
    site = create_project("Dino", "website", root=tmp_path)
    page = site.directory / "src" / "index.html"
    page.write_text("<nav><a href='#a'>About</a></nav><h1>Dinos</h1>")
    controller, provider = make(site, [Reply(text="Ok."),
                                       Reply(text="The menu is at the top of the page.")])
    controller.send("give it a menu at the top")
    turn = controller.send("where is the menu?")
    assert turn.text == "The menu is at the top of the page." and len(provider.calls) == 2


def test_numbers_no_analysis_printed_are_pulled_up(tmp_path) -> None:
    from opennest.assets import manager as assets

    research = create_project("Weather", "research", root=tmp_path)
    assets.import_file(research, INPUTS / "weather.csv")
    controller, provider = make(research, [
        Reply(text="Leeds averages 14.5 degrees and Oslo 19.0."),
        Reply(text="The temperatures go from 3.9 to 31.5; run it to see averages."),
    ])
    turn = controller.send("what's the warmest city?")
    assert "14.5" not in turn.text and "3.9 to 31.5" in turn.text
    correction = provider.calls[-1][-1].content
    assert correction.startswith("Answer this again") and "14.5" not in correction
    # A range worked out from the checked facts is not a guess.
    controller, provider = make(research, [Reply(text="Temperatures span 27.6 degrees.")])
    controller.send("how much does the temperature vary?")
    assert len(provider.calls) == 1


def test_a_chart_described_is_a_picture_nobody_looked_at() -> None:
    from opennest.agent.replies import CLAIMED_SIGHT

    assert any(phrase in "the chart shows average temperature by city" for phrase in
               CLAIMED_SIGHT)



def test_a_page_gallery_without_a_heading_is_still_described(tmp_path) -> None:
    site = create_project("Dino", "website", root=tmp_path)
    (site.directory / "src" / "index.html").write_text(
        "<h1>Dinos</h1><div id='gallery'><figure><img src='a.png'></figure>"
        "<figure><img src='b.png'></figure></div>")
    state = project_state(site, toolbox=Toolbox(site))
    assert "2 figures, 2 pictures; element ids gallery" in state


def test_a_look_claimed_twice_is_replaced_with_what_happened(project) -> None:
    controller, _ = make(project, [Reply(text="I see the square is orange."),
                                   Reply(text="I can see it is orange.")])
    turn = controller.send("is the square orange?")
    assert "see" not in turn.text.lower()



def test_a_change_a_few_turns_back_still_counts_as_lately(project) -> None:
    controller, provider = make(project, [
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py",
                                                 "old_text": "PLAYER_SPEED = 5",
                                                 "new_text": "PLAYER_SPEED = 9"}),)),
        Reply(text="Faster now."),
        Reply(text="Press Undo at the bottom."),
        Reply(text="I increased the player speed from 5 to 9."),
    ])
    passing(controller)
    controller.send("make it faster")
    controller.send("how do I undo that?")
    turn = controller.send("what did you change?")
    assert turn.text == "I increased the player speed from 5 to 9." and len(provider.calls) == 4



def test_plural_things_need_no_determiner() -> None:
    from opennest.agent.replies import child_nouns

    assert {"eagle", "cars"} <= child_nouns("make me a game where an eagle flies over cars")
    assert "dinosaurs" in child_nouns("a website about dinosaurs")
    assert "keys" not in child_nouns("move it with keys")      # not a thing a game has


def test_where_a_scene_is_is_not_a_thing_and_described_plurals_are() -> None:
    """The 13C worlds walk (SPIKES.md section 28M): "the deep sea" made "deep" a thing, so
    Gary was corrected into "The deep is not in the game"; "full of little stars" made
    nothing, so "the black sky with stars" -- there were none -- went unchecked."""
    from opennest.agent.replies import child_nouns

    sea = child_nouns("Make it look like the deep sea: dark blue water, sand on the bottom")
    assert not sea & {"deep", "sea", "water"}
    stars = child_nouns("Make the background a black sky full of little stars, with a big "
                        "purple planet.")
    assert {"stars", "planet"} <= stars
    assert child_nouns("make a game where I fly over big red cars") == {"cars"}


def test_what_a_tool_told_gary_is_not_said_to_the_child() -> None:
    """The 13C worlds walk (SPIKES.md section 28M): Qwen3 8B copied game_object's result
    into its reply, tool name and all."""
    from opennest.agent.replies import presentable

    reply = ("I added a fish. It is orange and stays still. It does not react to keys -- "
             "anything the game should do when a key is pressed is edit_file. Open Nest "
             "tests the game after this turn, and the test says what the scene really drew.")
    assert presentable(reply) == "I added a fish. It is orange and stays still."
    assert presentable("I used game_object to draw the sky.") == ""
    kept = "Press Run Game to see the new sky.\n- a blue sky\n- green grass"
    assert presentable(kept) == kept


@pytest.mark.parametrize("written", [
    '<tool_call>{"name": "edit_file", "arguments": {"path": "src/game.py"}}</tool_call>',
    '{"name": "game_object", "arguments": {"name": "sky", "drawing": "sky"}}',
    'edit_file(path="src/game.py", old_text="a", new_text="b")',
    "<think>The child wants a sky, so I should call game_object first.</think>",
    "Next I'll call game_object with name sky.",
])
def test_every_models_reply_meets_the_same_filters(project, written) -> None:
    """Claude, OpenAI and the local model: one boundary for all of them. The protocol
    filters used to live in the local provider alone, so a cloud model that wrote a call
    out as text, or left its reasoning in, would have had it shown in the chat."""
    provider = ScriptedProvider([Reply(text=f"The sky is ready.\n{written}\nPress Run Game.")])
    turn = AgentController(project, provider, Toolbox(project)).send("what is in my game?")
    assert "The sky is ready." in turn.text and "Press Run Game." in turn.text
    for leak in ("tool_call", "edit_file", "game_object", "<think>", '"name"', "old_text"):
        assert leak not in turn.text, turn.text
