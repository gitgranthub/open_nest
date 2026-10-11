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
