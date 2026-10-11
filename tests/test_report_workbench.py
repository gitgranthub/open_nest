"""The report in the Workbench: Show the report and Export PDF, beside the chart.

Real runs: the analysis is the research starter's, run under the process sandbox as Run
Analysis runs it, on a small table; the save dialog is replaced (a modal dialog blocks
forever offscreen, HANDOFF section 4) by one that answers with a path, or cancels.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.provider import Reply  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from tests.conftest import ScriptedProvider  # noqa: E402

TABLE = "month,rain_mm\n" + "".join(f"{m},{r}\n" for m, r in (
    ("Jan", 31), ("Feb", 22), ("Mar", 5), ("Apr", 48), ("May", 40), ("Jun", 37)))

FINDINGS = """# What I found

## The answer so far

April was the wettest month, with 48 mm of rain.
"""


def _spin(predicate, timeout_ms: int = 60000) -> bool:
    """The real event loop until ``predicate`` holds (tests/test_worker.py's reason)."""
    from PySide6.QtCore import QEventLoop, QTimer

    waited = 0
    while waited < timeout_ms and not predicate():
        loop = QEventLoop()
        QTimer.singleShot(25, loop.quit)
        loop.exec()
        waited += 25
    return bool(predicate())


def _settled(bench) -> None:
    assert _spin(lambda: bench._thread is None), "the report never finished"
    _spin(lambda: False, 100)


def _with_data(project):
    (project.directory / "data").mkdir(exist_ok=True)
    (project.directory / "data" / "rain.csv").write_text(TABLE, encoding="utf-8")
    (project.directory / "src" / "findings.md").write_text(FINDINGS, encoding="utf-8")
    return project


@pytest.fixture(scope="session")
def font_cache(tmp_path_factory):
    """A project's matplotlib font cache, built once. Each project keeps its own
    (``python_runner.MATPLOTLIB_CACHE``), so a project's first run builds one -- about
    six seconds, against half a second warm (SPIKES.md section 34). Copied into each
    test's project, so the suite pays it once."""
    from opennest.execution.python_runner import MATPLOTLIB_CACHE

    project = _with_data(create_project("Warm", "research",
                                        root=tmp_path_factory.mktemp("warm")))
    assert Toolbox(project).dispatch("run_project", {}).ok
    return project.directory / MATPLOTLIB_CACHE


@pytest.fixture
def research(tmp_path, font_cache):
    import shutil

    from opennest.execution.python_runner import MATPLOTLIB_CACHE

    project = _with_data(create_project("Rain Study", "research", root=tmp_path / "projects"))
    shutil.copytree(font_cache, project.directory / MATPLOTLIB_CACHE, dirs_exist_ok=True)
    return project


def _bench(project):
    from opennest.ui.workbench import Workbench

    controller = AgentController(project, ScriptedProvider([Reply(text="ok")] * 4),
                                 Toolbox(project))
    widget = Workbench(project, controller)
    widget.resize(1180, 760)
    widget.show()
    return widget


@pytest.fixture
def bench(qt_app, research):
    widget = _bench(research)
    yield widget
    _spin(lambda: widget._thread is None, 30000)
    widget.release()
    widget.close()


def _chat(bench) -> str:
    return bench._transcript.toPlainText()


def _report_shown(bench) -> None:
    bench._toggle_report()
    _settled(bench)
    assert not bench._report_view.isHidden(), _chat(bench)


def test_the_report_buttons_are_beside_the_chart_in_research_only(qt_app, bench,
                                                                  tmp_path) -> None:
    from opennest.ui import workbench

    assert not bench._report_button.isHidden() and not bench._export_button.isHidden()
    assert bench._export_button.text() == workbench.EXPORT_PDF
    game = _bench(create_project("Arcade", "games", root=tmp_path / "games"))
    try:
        assert game._report_view is None
    finally:
        game.release()
        game.close()


def test_show_the_report_runs_the_analysis_and_shows_the_pdfs_own_pages(bench) -> None:
    from opennest.ui import workbench

    _report_shown(bench)
    report = bench._report
    assert report is not None and report.charts == ("charts/chart.png",)
    assert bench._report_view.page_count() == report.pages >= 1
    assert not bench._report_view.page_image(0).isNull()
    assert bench._chart.isHidden() and bench._output.isHidden()
    assert f"{report.pages} page" in bench._report_caption.text()
    # What the report left out is said beside it, not hidden.
    assert "question.md and sources.md still have only the starter's words" in \
        bench._report_notes.text()
    assert bench._report_button.text() == workbench.HIDE_REPORT

    bench._toggle_report()
    assert bench._report_view.isHidden()
    assert not bench._chart.isHidden() and not bench._output.isHidden()
    assert bench._report_button.text() == workbench.SHOW_REPORT


def test_export_writes_only_the_chosen_file_and_says_what_was_checked(bench,
                                                                       tmp_path) -> None:
    folder = tmp_path / "Documents"
    folder.mkdir()
    target = folder / "Rain Study report.pdf"
    asked = []

    def dialog(name):
        asked.append(name)
        return str(target)

    bench._choose_destination = dialog
    _report_shown(bench)
    shown = bench._report.pdf
    bench._export()
    _settled(bench)
    assert asked == ["Rain Study report.pdf"]
    assert sorted(p.name for p in folder.iterdir()) == ["Rain Study report.pdf"]
    assert target.read_bytes() == shown, "what is saved is what was on screen"
    assert f"Saved “Rain Study report.pdf” in Documents. {bench._report.pages}" \
        in _chat(bench)
    assert any("exported the report" in event for event in bench.controller._events), \
        "Gary is told, so he can answer whether it saved"


def test_cancelling_the_save_dialog_writes_nothing_and_claims_nothing(bench,
                                                                      tmp_path) -> None:
    bench._choose_destination = lambda name: None
    bench._export()
    _settled(bench)
    assert not bench._report_view.isHidden(), "the report was made and shown first"
    assert "Saved" not in _chat(bench) and "not saved" not in _chat(bench)


def test_an_unwritable_folder_is_said_and_saved_is_never_claimed(bench, tmp_path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    bench._choose_destination = lambda name: str(locked / name)
    try:
        bench._export()
        _settled(bench)
    finally:
        locked.chmod(0o700)
    assert list(locked.iterdir()) == []
    assert "The report was not saved. Open Nest can't save in “locked”" in \
        _chat(bench)
    assert "Saved “" not in _chat(bench)


def test_a_key_in_the_findings_is_said_before_any_save_window(bench, tmp_path) -> None:
    findings = bench.project.directory / "src" / "findings.md"
    findings.write_text(FINDINGS + "\nmy key sk-ant-api03-" + "Q" * 40 + "\n",
                        encoding="utf-8")
    asked = []
    bench._choose_destination = lambda name: asked.append(name) or str(tmp_path / name)
    bench._export()
    _settled(bench)
    assert asked == [], "nobody is asked where to save a report that will not be saved"
    assert "The report was not saved, because something in it looks like a password" in \
        _chat(bench)
    assert "QQQQ" not in _chat(bench)
    assert not list(tmp_path.glob("*.pdf"))


def test_a_broken_analysis_makes_no_report_and_says_so(bench, tmp_path) -> None:
    analysis = bench.project.directory / "src" / "analysis.py"
    analysis.write_text("raise SystemExit('the rain table is wrong')\n", encoding="utf-8")
    bench._choose_destination = lambda name: str(tmp_path / name)
    bench._export()
    _settled(bench)
    assert bench._report_view.isHidden()
    assert "There is no report yet: the analysis stopped with an error" in _chat(bench)
    assert not list(tmp_path.glob("*.pdf"))


def test_export_after_a_change_makes_the_report_again(bench, tmp_path) -> None:
    from tests.test_report import _words

    _report_shown(bench)
    findings = bench.project.directory / "src" / "findings.md"
    findings.write_text(FINDINGS.replace("April", "Spring, April"), encoding="utf-8")
    target = tmp_path / "again.pdf"
    bench._choose_destination = lambda name: str(target)
    bench._export()
    _settled(bench)
    assert "Spring, April was the wettest month" in _words(target.read_bytes())


def test_anything_else_in_the_panel_puts_the_report_away(bench) -> None:
    _report_shown(bench)
    bench._panel_text("Stopped.")
    assert bench._report_view.isHidden() and bench._report_view.page_count() == 0
    assert bench._output.toPlainText() == "Stopped."
