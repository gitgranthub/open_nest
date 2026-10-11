"""What Gary is told about the report, and when.

The layout is data in the project (src/report.toml), so a change to the report is one line.
Gary is told so beside a message about the report and only then (HANDOFF section 4), with
the file as it is; the Research recipes, which change the analysis, step aside for it. The
screen guide names the two buttons, so "how do I save it as a PDF?" is answered with them.
Measured on the real models: SPIKES.md section 34.
"""

from __future__ import annotations

from opennest.agent import controller as controller_module
from opennest.agent import evidence
from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.ai.provider import Reply
from opennest.export import report
from opennest.fastpath.router import FastPathResult
from opennest.projects.manager import create_project
from opennest.projects.profiles import get_profile
from tests.conftest import ScriptedProvider


class AskedFastPath:
    """The Fast Path, saying no to everything and remembering what it was asked."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def handle(self, project, toolbox, request, **_kwargs) -> FastPathResult:
        self.asked.append(request)
        return FastPathResult(route="normal")


def _controller(project):
    provider = ScriptedProvider([Reply(text="Done.")] * 6)
    fastpath = AskedFastPath()
    return AgentController(project, provider, Toolbox(project), fastpath=fastpath), \
        provider, fastpath


def _sent(provider) -> str:
    """What the last request carried as the child's message."""
    return [m.content for m in provider.calls[-1] if m.role == "user"][-1]


def test_a_message_about_the_report_carries_the_layout_and_skips_the_recipes(tmp_path) -> None:
    project = create_project("Weather", "research", root=tmp_path)
    controller, provider, fastpath = _controller(project)
    controller.send("make the title of my report bigger")
    assert fastpath.asked == [], "no recipe edits report.toml; they change the analysis"
    sent = _sent(provider)
    assert sent.startswith("make the title of my report bigger\n\n(Open Nest: this is "
                           "about their report")
    assert 'title_size = 26' in sent and "src/report.toml" in sent
    # Beside the message for this turn only: what is kept is what the child said.
    kept = [m.content for m in controller.history if m.role == "user"]
    assert kept[-1] == "make the title of my report bigger"


def test_any_other_message_is_as_it_was(tmp_path) -> None:
    project = create_project("Weather", "research", root=tmp_path)
    controller, provider, fastpath = _controller(project)
    controller.send("make the chart title bigger")
    assert fastpath.asked == ["make the chart title bigger"]
    assert "report.toml" not in _sent(provider)


def test_which_report_messages_are_about_its_layout() -> None:
    """A change to a chart in the report is a change to the analysis (SPIKES.md 34F)."""
    about = controller_module._ABOUT_REPORT
    itself = controller_module._CHART_ITSELF
    layout = ["make the title of my report bigger", "put the charts first in my report",
              "only put the rain chart in the report", "take the sources out of the report",
              "put my name on the report", "make the words in the pdf smaller"]
    chart = ["the rain chart in my report should be called Rain by month",
             "change the title of the rain chart in my report",
             "the temperature chart in my report needs a label on the side",
             "make the lines in the report's chart thicker"]
    for message in layout:
        assert about.search(message) and not itself.search(message), message
    for message in chart:
        assert about.search(message) and itself.search(message), message


def test_a_change_to_a_chart_in_the_report_goes_as_it_always_went(tmp_path) -> None:
    project = create_project("Weather", "research", root=tmp_path)
    controller, provider, fastpath = _controller(project)
    controller.send("the rain chart in my report should be called Rain by month")
    assert fastpath.asked, "the Research recipes may take it, as before"
    assert "report.toml" not in _sent(provider)


def test_a_question_about_the_report_is_answered_not_edited(tmp_path) -> None:
    project = create_project("Weather", "research", root=tmp_path)
    controller, provider, _fastpath = _controller(project)
    controller.send("how do I save my report as a pdf?")
    assert controller_module.REPORT_GUIDE.split("{")[0] not in _sent(provider)
    assert provider.tools_offered[-1] == [], "a question gets no tools"
    assert "“Export PDF…” opens a save window" in provider.system_prompt


def test_only_a_project_with_a_report_gets_the_note(tmp_path) -> None:
    project = create_project("Arcade", "games", root=tmp_path)
    controller, provider, _fastpath = _controller(project)
    controller.send("make a report card screen when the game ends")
    assert "report.toml" not in _sent(provider)


def test_an_older_project_is_given_the_file_to_change(tmp_path) -> None:
    project = create_project("Older", "research", root=tmp_path)
    layout_file = project.directory / report.LAYOUT_FILE
    layout_file.unlink()
    controller, provider, _fastpath = _controller(project)
    controller.send("put my name on the report, it's Sam")
    assert layout_file.is_file()
    assert 'author = ""' in _sent(provider)


def test_the_screen_guide_names_the_report_buttons_for_research_only() -> None:
    research = evidence.guide(get_profile("research"))
    assert "“Show the report”" in research and "“Export PDF…”" in research
    assert "never the project" in research
    for other in ("games", "website", "arduino", "blank"):
        assert "Export PDF" not in evidence.guide(get_profile(other))


# -- a report that needs charts made (the owner's weather3, SPIKES.md section 34G) --------

WEATHER3 = "Make a weather report dashboard report with a few modern visualizations of the " \
    "data analyzed."


def test_a_report_that_needs_charts_made_is_the_analysiss_work() -> None:
    def route(message):
        reported = controller_module._ABOUT_REPORT.search(message) and \
            not controller_module._CHART_ITSELF.search(message)
        draws = reported and controller_module._MAKES_CHARTS.search(message) and \
            not controller_module._ARRANGES_CHARTS.search(message)
        return "draw" if draws else ("layout" if reported else "none")

    for message in (WEATHER3, "make me a report with charts of the temperature, the rain "
                    "and the wind", "I want a dashboard report of my weather data with a "
                    "few charts", "add a chart of the wind to my report"):
        assert route(message) == "draw", message
    for message in ("make the title of my report bigger", "put the charts first in my report",
                    "only put the rain chart in the report", "call my report Our Garden",
                    "take the rain chart out of the report", "make the words in the report "
                    "smaller"):
        assert route(message) == "layout", message


def test_the_owners_message_gets_the_analysis_not_the_layout(tmp_path) -> None:
    project = create_project("weather3", "research", root=tmp_path)
    controller, provider, fastpath = _controller(project)
    controller.send(WEATHER3)
    assert fastpath.asked == [WEATHER3], "chart requests go through the recipes, as always"
    sent = _sent(provider)
    assert "needs no change for this" in sent and "draw(frame, numbers, table.name)" in sent
    assert "title_size" not in sent, "not the layout file"


def test_charts_nobody_drew_are_refused_in_report_toml(tmp_path) -> None:
    project = create_project("weather3", "research", root=tmp_path)
    (project.directory / "charts").mkdir()
    (project.directory / "charts" / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    box = Toolbox(project)
    refused = box.dispatch("edit_file", {"path": "src/report.toml", "old_text": "charts = []",
                                         "new_text": 'charts = ["chart1.png", "chart2.png"]'})
    assert not refused.ok
    assert "not saved" in refused.content and "chart1.png and chart2.png" in refused.content
    assert "it has drawn charts/chart.png" in refused.content
    assert "charts = []" in (project.directory / "src" / "report.toml").read_text()

    broken = box.dispatch("edit_file", {"path": "src/report.toml", "old_text": 'title = ""',
                                        "new_text": 'title = "Unfinished'})
    assert not broken.ok and "mistake on line" in broken.content

    fine = box.dispatch("edit_file", {"path": "src/report.toml", "old_text": "charts = []",
                                      "new_text": 'charts = ["chart.png"]'})
    assert fine.ok


def test_other_projects_toml_files_are_not_checked(tmp_path) -> None:
    project = create_project("Arcade", "games", root=tmp_path)
    written = Toolbox(project).dispatch("write_file", {"path": "src/report.toml",
                                                       "content": 'charts = ["x.png"]\n'})
    assert written.ok


# -- a Research analysis is run after a change, as a game is tested (SPIKES.md 34G) -------

def _analysis_project(tmp_path):
    import shutil  # noqa: F401 - kept beside its use

    project = create_project("weather3", "research", root=tmp_path)
    data = project.directory / "data"
    data.mkdir(exist_ok=True)
    (data / "rain.csv").write_text("month,rain_mm\nJan,31\nFeb,22\nMar,5\n", encoding="utf-8")
    return project


ANCHOR = "        draw(frame, numbers, table.name)"


def _adds(code: str):
    from opennest.ai.provider import ToolCall

    return Reply(tool_calls=(ToolCall("edit_file", {"path": "src/analysis.py",
                                                    "old_text": ANCHOR,
                                                    "new_text": ANCHOR + "\n" + code}),))


def test_a_change_nobody_ran_is_run_and_its_failure_sent_back(tmp_path) -> None:
    from opennest.ai.provider import ToolCall

    project = _analysis_project(tmp_path)
    broken = "        sns.lineplott(data=frame)"   # a typo: the analysis now fails
    provider = ScriptedProvider([
        _adds(broken),
        Reply(text="I added a chart."),                     # stops without running it
        Reply(tool_calls=(ToolCall("edit_file", {"path": "src/analysis.py",
                                                 "old_text": broken, "new_text": ""}),)),
        Reply(tool_calls=(ToolCall("run_project", {}),)),
        Reply(text="Fixed, and it runs."),
    ])
    controller = AgentController(project, provider, Toolbox(project))
    turn = controller.send("add a wind chart to my analysis")
    runs = [result for name, result in turn.tool_results if name == "run_project"]
    assert not runs[0].ok, "Open Nest ran it after the change"
    assert any("Open Nest ran the analysis after your change, and it failed" in m.content
               for m in provider.calls[2] if m.role == "user")
    assert runs[-1].ok and turn.text == "Fixed, and it runs."
    assert not turn.gave_up


def test_a_change_that_stays_broken_is_said_as_it_is(tmp_path) -> None:
    project = _analysis_project(tmp_path)
    provider = ScriptedProvider([_adds("        sns.lineplott(data=frame)"),
                                 *[Reply(text="The chart now shows the wind.")] * 4])
    controller = AgentController(project, provider, Toolbox(project))
    turn = controller.send("add a wind chart to my analysis")
    assert turn.gave_up
    assert turn.text.startswith("I changed the analysis, but when Open Nest ran it, it "
                                "stopped with an error")
    assert "now shows the wind" not in turn.text


def test_a_change_that_was_run_and_worked_is_not_run_again(tmp_path) -> None:
    from opennest.ai.provider import ToolCall

    project = _analysis_project(tmp_path)
    provider = ScriptedProvider([_adds("        print('more')"),
                                 Reply(tool_calls=(ToolCall("run_project", {}),)),
                                 Reply(text="Done.")])
    controller = AgentController(project, provider, Toolbox(project))
    turn = controller.send("print more in my analysis")
    assert [name for name, _ in turn.tool_results].count("run_project") == 1
    assert turn.text == "Done."


def test_the_starter_has_seaborn_ready() -> None:
    """The research prompt says seaborn is there; the starter did not import it, and Gary
    Smart's sns.lineplot crashed the analysis (SPIKES.md section 34G)."""
    from opennest.projects import starters

    kit = next(k for k in starters.load_starters() if k.id == "research_basic")
    code = (kit.directory / "analysis.py").read_text(encoding="utf-8")
    assert "import seaborn as sns" in code and "set_theme" not in code.split("import seaborn")[1]


def test_a_line_already_wrong_does_not_block_another_change(tmp_path) -> None:
    """weather3 as the owner left it: report.toml already names chart1-3.png."""
    project = create_project("weather3", "research", root=tmp_path)
    layout = project.directory / "src" / "report.toml"
    layout.write_text(layout.read_text().replace(
        "charts = []", 'charts = ["chart1.png", "chart2.png"]'), encoding="utf-8")
    box = Toolbox(project)
    bigger = box.dispatch("edit_file", {"path": "src/report.toml", "old_text": "title_size = 26",
                                        "new_text": "title_size = 34"})
    assert bigger.ok, bigger.content
    worse = box.dispatch("edit_file", {"path": "src/report.toml", "old_text": 'author = ""',
                                       "new_text": 'author = 7'})
    assert not worse.ok and "author has to be words in quotes" in worse.content
