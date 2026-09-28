"""A turn as it happens: the steps Open Nest reports, and where the Workbench shows them.

The owner's first test drive asked for a build panel that shows the real code being
built, and updates in the chat -- thinking, building a script -- instead of a silent
eagle. The steps are the application's own report of what it is doing (``tools.Step``);
Gary's words are not streamed, because the honesty guard may still replace them.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Step, Toolbox, changed_lines  # noqa: E402
from opennest.ai.provider import Reply, ToolCall  # noqa: E402
from opennest.execution import playtest  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from tests.conftest import ScriptedProvider  # noqa: E402


def watched(project):
    toolbox = Toolbox(project)
    steps: list[Step] = []
    toolbox.observer = steps.append
    return toolbox, steps


def _edit(old: str, new: str) -> Reply:
    return Reply(tool_calls=(ToolCall("edit_file", {"path": "src/game.py", "old_text": old,
                                                    "new_text": new}),))


def _passing(*_args, **_kwargs):
    return playtest.Playtest(playtest.PASSED, entry="src/game.py", frames=90,
                             moved_by_itself=True, responded_to=("right",))


# ----------------------------------------------------------------------- toolbox

def test_an_edit_reports_itself_and_then_the_file_as_it_now_is(project) -> None:
    toolbox, steps = watched(project)
    result = toolbox.dispatch("edit_file", {"path": "src/game.py",
                                            "old_text": "PLAYER_SPEED = 5",
                                            "new_text": "PLAYER_SPEED = 9"})
    assert result.ok
    assert [s.kind for s in steps] == ["tool", "changed"]
    assert steps[0].text == "changing src/game.py"
    changed = steps[1]
    assert changed.content == project.entrypoint_path.read_text()
    line = changed.content.split("\n")[changed.changed_lines[0]]
    assert changed.changed_lines == (changed.changed_lines[0],) and line == "PLAYER_SPEED = 9"
    assert not changed.created


def test_a_new_file_is_created_not_changed(project) -> None:
    toolbox, steps = watched(project)
    toolbox.dispatch("write_file", {"path": "src/eagle.py", "content": "EAGLE = 1\n"})
    assert [s.text for s in steps] == ["creating src/eagle.py", "created src/eagle.py"]
    assert steps[1].created and steps[1].changed_lines == ()


def test_a_refused_edit_says_nothing_changed(project) -> None:
    toolbox, steps = watched(project)
    toolbox.dispatch("edit_file", {"path": "src/game.py", "old_text": "NOT THERE",
                                   "new_text": "x"})
    assert [s.kind for s in steps] == ["tool", "refused"]
    assert "left as it was" in steps[1].text


def test_a_path_outside_the_project_is_not_repeated_to_the_child(project) -> None:
    toolbox, steps = watched(project)
    toolbox.dispatch("read_file", {"path": "../../etc/passwd"})
    assert steps[0].text == "reading a file" and "passwd" not in steps[0].text


def test_a_broken_observer_never_breaks_a_tool(project) -> None:
    toolbox = Toolbox(project)

    def explode(_step):
        raise RuntimeError("the window went away")

    toolbox.observer = explode
    assert toolbox.dispatch("read_file", {"path": "src/game.py"}).ok


def test_changed_lines_are_the_new_ones() -> None:
    assert changed_lines("a\nb\nc", "a\nB\nc\nd") == (1, 3)
    assert changed_lines(None, "new") == ()


# --------------------------------------------------------------------- controller

def test_a_turn_reports_thinking_each_change_and_each_test(project) -> None:
    provider = ScriptedProvider([_edit("PLAYER_SPEED = 5", "PLAYER_SPEED = 9"),
                                 Reply(text="It is faster now.")])
    toolbox = Toolbox(project)
    toolbox.playtest = lambda: (toolbox.report(Step("testing", "testing the game")),
                                _passing())[1]
    controller = AgentController(project, provider, toolbox)
    steps: list[Step] = []
    controller.send("make it faster", on_progress=steps.append)
    kinds = [s.kind for s in steps]
    assert kinds[0] == "thinking" and "changed" in kinds and "testing" in kinds
    assert kinds.index("changed") < kinds.index("testing")
    assert toolbox.observer is None                    # for that one turn only


def test_a_recipe_turn_reports_the_recipe_and_its_edit(project) -> None:
    from tests.test_fastpath import YES, FakeScorer, ScoringProvider, describe

    provider = ScoringProvider([], FakeScorer(describe("games", "change_player_speed"),
                                              YES, "faster"))
    toolbox = Toolbox(project)
    toolbox.playtest = _passing
    controller = AgentController(project, provider, toolbox, fastpath=FastPathRouter())
    steps: list[Step] = []
    controller.send("Make the player move faster.", on_progress=steps.append)
    assert [s.kind for s in steps if s.kind in ("recipe", "changed")] == ["recipe", "changed"]
    assert "PLAYER_SPEED = 8" in next(s for s in steps if s.kind == "changed").content


def test_a_rolled_back_recipe_shows_the_file_put_back(project) -> None:
    from tests.test_fastpath import YES, FakeScorer, ScoringProvider, describe

    before = project.entrypoint_path.read_text()
    provider = ScoringProvider([Reply(text="Let me look.")],
                               FakeScorer(describe("games", "change_player_speed"), YES,
                                          "faster"))
    toolbox = Toolbox(project)
    toolbox.playtest = lambda: playtest.Playtest(playtest.CRASHED, entry="src/game.py",
                                                 error="boom")
    controller = AgentController(project, provider, toolbox, fastpath=FastPathRouter())
    steps: list[Step] = []
    controller.send("Make the player move faster.", on_progress=steps.append)
    undone = [s for s in steps if s.kind == "undone"]
    assert undone and undone[0].content == before


# ---------------------------------------------------------------------- workbench

@pytest.fixture
def bench(qt_app, project):
    from opennest.ui.workbench import Workbench

    widget = Workbench(project, AgentController(project, ScriptedProvider([]),
                                                Toolbox(project)))
    widget.show()
    yield widget
    widget.close()


def test_a_step_is_said_in_the_chat_once_and_beside_the_eagle(bench) -> None:
    bench._last_step = ""
    for _ in range(3):             # a recipe's several hunks to one file
        bench._progress(Step("tool", "changing src/game.py", path="src/game.py"))
    chat = bench._transcript.toPlainText()
    assert chat.count("changing src/game.py") == 1
    assert bench._activity_text.text() == "Gary is changing src/game.py…"


def test_a_changed_file_is_shown_with_its_new_lines_marked(bench) -> None:
    content = "A = 1\nB = 2\nC = 3\n"
    bench._progress(Step("changed", "changed src/game.py", path="src/game.py",
                         content=content, changed_lines=(1,)))
    assert bench._output.toPlainText() == content
    assert bench._code_caption.text() == "src/game.py — 1 line changed"
    marks = bench._output.extraSelections()
    assert len(marks) == 1 and marks[0].cursor.block().text() == "B = 2"
    assert "changed src/game.py" not in bench._transcript.toPlainText()
    bench._panel_text("something else")                 # a later message clears it
    assert bench._code_caption.isHidden() and bench._output.extraSelections() == []


def test_a_website_shows_the_code_while_building_and_the_page_after(qt_app, tmp_path) -> None:
    from opennest.ui.workbench import Workbench

    project = create_project("Site", "website", root=tmp_path)
    widget = Workbench(project, AgentController(project, ScriptedProvider([]),
                                                Toolbox(project)))
    widget.show()
    try:
        page = (project.directory / "src/index.html").read_text()
        widget._progress(Step("changed", "changed src/index.html", path="src/index.html",
                              content=page, changed_lines=(3,)))
        assert widget._web.isHidden() and widget._output.toPlainText() == page
        widget._page_back()
        assert not widget._web.isHidden()
    finally:
        widget.close()


def test_something_that_happened_is_said_in_the_chat_not_beside_the_eagle(bench) -> None:
    bench._progress(Step("tool", "changing src/game.py", path="src/game.py"))
    bench._progress(Step("refused", "that change didn't fit src/game.py, so it was left "
                                    "as it was", path="src/game.py"))
    assert bench._activity_text.text() == "Gary is changing src/game.py\u2026"
    assert "didn't fit src/game.py" in bench._transcript.toPlainText()


def test_after_a_run_the_result_shows_first_and_the_code_is_one_click_away(bench) -> None:
    """Research and Arduino end a turn by running or compiling, and that result used to
    replace the code for good. Now every project type ends with both, one click apart."""
    from opennest.agent.controller import Turn
    from opennest.agent.tools import ToolResult
    from opennest.execution.python_runner import RunResult
    from opennest.ui.workbench import SHOW_CODE, SHOW_RESULT

    bench._turn_code = bench._run_view = None
    code = "A = 1\nB = 2\n"
    bench._progress(Step("changed", "changed src/game.py", path="src/game.py",
                         content=code, changed_lines=(1,)))
    run = RunResult(exit_code=0, stdout="How much each column changed", stderr="",
                    seconds=0.2, timed_out=False)
    bench._turn_finished(Turn(text="Done.", tool_results=[
        ("run_project", ToolResult(True, "ran", run=run))]))

    assert bench._output.toPlainText() == "How much each column changed"
    assert bench._code_button.text() == SHOW_CODE and not bench._code_button.isHidden()
    bench._code_button.click()
    assert bench._output.toPlainText() == code and len(bench._output.extraSelections()) == 1
    assert bench._code_button.text() == SHOW_RESULT and not bench._code_button.isHidden()
    bench._code_button.click()
    assert bench._output.toPlainText() == "How much each column changed"
    bench._panel_text("an unrelated message")          # nothing stale is left offered
    assert bench._code_button.isHidden()


def test_a_turn_that_ran_nothing_ends_on_the_code_with_no_toggle(bench) -> None:
    from opennest.agent.controller import Turn

    bench._turn_code = bench._run_view = None
    bench._progress(Step("changed", "changed src/game.py", path="src/game.py",
                         content="A = 2\n", changed_lines=(0,)))
    bench._turn_finished(Turn(text="Done."))
    assert bench._output.toPlainText() == "A = 2\n" and bench._code_button.isHidden()


def _png(path):
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes([20, 30, 40]) * 8 for _ in range(6))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 6, 8, 2,
                                                                        0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_a_game_changed_and_tested_shows_how_the_test_saw_it(bench, project) -> None:
    from opennest.agent.controller import Turn

    _png(project.directory / playtest.STILL)
    tested = playtest.Playtest(playtest.PASSED, entry="src/game.py", frames=90,
                               still=playtest.STILL)
    bench._turn_finished(Turn(text="Done.", checkpoint="abc123", playtests=[tested]))
    assert not bench._chart.isHidden()
    assert "tested it, with no window" in bench._chart_caption.text()


def test_no_picture_of_a_test_that_failed_or_a_turn_that_changed_nothing(bench,
                                                                        project) -> None:
    from opennest.agent.controller import Turn

    _png(project.directory / playtest.STILL)
    crashed = playtest.Playtest(playtest.CRASHED, entry="src/game.py", error="boom")
    bench._turn_finished(Turn(text="It broke.", checkpoint="abc123", playtests=[crashed]))
    assert bench._chart.isHidden()
    passed = playtest.Playtest(playtest.PASSED, entry="src/game.py", still=playtest.STILL)
    bench._turn_finished(Turn(text="Nothing to do.", checkpoint=None, playtests=[passed]))
    assert bench._chart.isHidden()
