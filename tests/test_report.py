"""A Research project's report: the page model, what goes in, and the PDF it makes.

The pages are decided by arithmetic before anything is drawn, so a fixed input has a fixed
page count and these tests pin it. The charts here are synthetic PNGs the sizes of the real
ones the weather analysis draws (SPIKES.md section 34): 7.2 x 4.5 in and 8.2 x 10.2 in at
150 dpi, the house savefig size.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from opennest.export import report
from opennest.projects.manager import create_project

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TODAY = date(2026, 10, 11)

QUESTION = """# The question

What are you trying to find out?

## My question

Was the summer of 2025 at our house really hotter than the rest of the year?

## What I think the answer is

<!-- A guess before you look is worth writing down. -->
I think July was the hottest month.
"""

FINDINGS = """# What I found

## The answer so far

<!-- One or two sentences. What does the data actually say? -->
Yes. The **average high** went from 32.4 °F in January to 83.7 °F in July. It cost $5 and
$6 to run, which is not maths.

## What surprised me

- The coldest night was -8.9 °F.
- August was the wettest month.

## What I am still not sure about

Say what the data cannot tell you as well as what it can. A finding with an honest limit
on it is worth more than one without.
"""

SOURCES = """# Where the data came from

| File | Where it came from | When I got it |
|---|---|---|
| home_weather_station_2025.csv | Our weather station, from its app | January 2, 2026 |
| | | |
"""


def _picture(path: Path, size: tuple[int, int], *, dpi: float = 150.0, alpha=False) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "RGBA" if alpha else "RGB"
    Image.new(mode, size, (185, 106, 22, 128) if alpha else (185, 106, 22)).save(
        path, dpi=(dpi, dpi))


@pytest.fixture
def study(tmp_path):
    """A research project with its question, findings and sources written, and the three
    charts the weather analysis draws -- the order it draws them in."""
    project = create_project("Weather Study", "research", root=tmp_path)
    src = project.directory / "src"
    (src / "question.md").write_text(QUESTION, encoding="utf-8")
    (src / "findings.md").write_text(FINDINGS, encoding="utf-8")
    (src / "sources.md").write_text(SOURCES, encoding="utf-8")
    charts = project.directory / "charts"
    _picture(charts / "chart.png", (1074, 670))
    _picture(charts / "weather_dashboard.png", (1223, 1525))
    _picture(charts / "rain_by_month.png", (1075, 670))
    return project


DRAWN = ["charts/chart.png", "charts/weather_dashboard.png", "charts/rain_by_month.png"]


def _build(project, charts=DRAWN):
    return report.build(project.directory, project.name, charts, today=TODAY)


def _opened(pdf: bytes):
    """The PDF in Qt's PDF engine -- a reader that is not matplotlib."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtWidgets import QApplication

    # A QApplication, as conftest's qt_app makes: a bare QGuiApplication made here first
    # would be the session's, and every widget test after this one would abort on it.
    QApplication.instance() or QApplication([])
    data = QByteArray(pdf)
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    document = QPdfDocument()
    document.load(buffer)
    return document, buffer, data


def _words(pdf: bytes) -> str:
    document, _buffer, _data = _opened(pdf)
    return "\n".join(document.getAllText(page).text() for page in range(document.pageCount()))


# -- the page model --------------------------------------------------------------------

def test_the_page_count_for_a_fixed_input_is_fixed(study) -> None:
    made = _build(study)
    assert made.pages == 3
    assert made.sections == ("question", "charts", "findings", "sources")
    assert made.starts == (("question", 1), ("charts", 1), ("findings", 3), ("sources", 3))
    # The first chart fits beside the question at the page's width (0.908 of drawn); the
    # dashboard is taller than a page, so it has one of its own, made to fit; the third
    # starts the next page, and the findings follow it.
    assert made.placements == (("charts/chart.png", 1, 0.908),
                               ("charts/weather_dashboard.png", 2, 0.792),
                               ("charts/rain_by_month.png", 3, 0.907))
    assert _build(study).placements == made.placements, "the same input, the same pages"


def test_a_chart_is_never_made_bigger_than_it_was_drawn(study) -> None:
    _picture(study.directory / "charts" / "small.png", (300, 200))
    made = _build(study, ["charts/small.png"])
    assert made.placements == (("charts/small.png", 1, 1.0),)


def test_a_chart_taller_than_a_page_gets_a_page_of_its_own_and_is_said(study) -> None:
    _picture(study.directory / "charts" / "tall.png", (1000, 4000))
    made = _build(study, ["charts/chart.png", "charts/tall.png"])
    (_first, (_path, page, scale)) = made.placements
    assert page == 2 and scale < report.SMALL_CHART
    # Never split: one placement, on one page.
    assert [p for p in made.placements if p[0] == "charts/tall.png"] == [
        ("charts/tall.png", 2, scale)]
    assert any("tall.png is taller than a page" in note for note in made.notes)


def test_two_ordinary_charts_share_a_page_rather_than_one_each(study, monkeypatch) -> None:
    """Five charts the house size share pages two at a time, the second made a little
    smaller to stay (KEEP_ON_PAGE); a chart that could never be made smaller would take a
    page each (SPIKES.md section 34: 7 pages against 4 on the weather report)."""
    names = []
    for n in range(5):
        _picture(study.directory / "charts" / f"c{n}.png", (1075, 670))
        names.append(f"charts/c{n}.png")
    (study.directory / "src" / "report.toml").write_text('order = ["charts"]\n')
    made = _build(study, names)
    assert made.pages == 3
    assert [page for _path, page, _scale in made.placements] == [1, 2, 2, 3, 3]
    assert [scale for _path, _page, scale in made.placements] == [
        0.907, 0.907, 0.808, 0.907, 0.808]
    assert min(scale for *_rest, scale in made.placements) >= 0.907 * report.KEEP_ON_PAGE

    monkeypatch.setattr(report, "KEEP_ON_PAGE", 1.0)
    assert _build(study, names).pages == 5


def test_lines_never_run_past_the_margin() -> None:
    words = report._words("A long sentence about the weather station " * 20
                          + "https://example.org/a/very/long/address/that/cannot/break/" * 3)
    for line in report.wrap(words, 11.0, report.CONTENT_WIDTH):
        last = line[-1]
        assert last.x + report._width(last.text, last.style, 11.0) <= \
            report.CONTENT_WIDTH + 0.01


# -- what goes in ------------------------------------------------------------------------

def test_the_starters_words_are_left_out_and_that_is_said(tmp_path) -> None:
    project = create_project("Untouched", "research", root=tmp_path)
    _picture(project.directory / "charts" / "chart.png", (1074, 670))
    made = report.build(project.directory, project.name, ["charts/chart.png"], today=TODAY)
    assert made.sections == ("charts",)
    assert "question.md, findings.md and sources.md still have only the starter's words " \
        "in them, so they are not in the report yet." in made.notes
    words = _words(made.pdf)
    assert "What are you trying to find out" not in words
    assert "honest limit" not in words


def test_only_their_own_words_are_kept(study) -> None:
    blocks = report.own_words("findings.md", FINDINGS)
    kinds = [(block.kind, block.text) for block in blocks]
    assert ("heading", "What I am still not sure about") not in kinds, \
        "a heading with only the starter's words under it goes"
    assert ("heading", "What surprised me") in kinds
    assert [b.text for b in blocks if b.kind == "item"] == [
        "The coldest night was -8.9 °F.", "August was the wettest month."]
    table = next(b for b in report.own_words("sources.md", SOURCES) if b.kind == "table")
    assert len(table.rows) == 2, "the empty row the starter ships is not a source"


def test_nothing_of_theirs_is_no_report(tmp_path) -> None:
    project = create_project("Empty", "research", root=tmp_path)
    with pytest.raises(report.ReportError, match="nothing to put in a report") as refused:
        report.build(project.directory, project.name, [], today=TODAY)
    assert "The analysis drew no charts" in str(refused.value)
    assert "still have only the starter's words" in str(refused.value)


def test_the_words_are_text_in_the_pdf_and_dollars_are_not_maths(study) -> None:
    words = _words(_build(study).pdf)
    assert "Was the summer of 2025 at our house really hotter" in words
    assert "$5 and" in words and "$6 to run" in words
    assert "home_weather_station_2025.csv" in words
    assert "Page 1 of 3" in words and "Made with Open Nest" in words


def test_what_no_font_can_draw_is_left_out_and_said(study) -> None:
    findings = study.directory / "src" / "findings.md"
    findings.write_text(FINDINGS.replace("as I guessed", "") + "\nIt rained a lot \U0001F327.\n",
                        encoding="utf-8")
    made = _build(study)
    assert "\U0001F327" in " ".join(made.notes)
    assert "It rained a lot" in _words(made.pdf)


def test_a_chart_that_is_not_a_picture_or_not_in_the_project_is_left_out(study,
                                                                          tmp_path) -> None:
    (study.directory / "charts" / "broken.png").write_bytes(b"not a png")
    outside = tmp_path / "outside.png"
    _picture(outside, (100, 100))
    (study.directory / "charts" / "link.png").symlink_to(outside)
    made = _build(study, ["charts/broken.png", "charts/link.png", "charts/chart.png"])
    assert made.charts == ("charts/chart.png",)
    assert sum("could not be opened as a picture" in note for note in made.notes) == 2


def test_a_see_through_chart_is_laid_on_the_paper(study) -> None:
    _picture(study.directory / "charts" / "clear.png", (400, 300), alpha=True)
    pixels = report._pixels(study.directory / "charts" / "clear.png", "#F2EFE8")
    assert pixels.shape == (300, 400, 3)


# -- the layout file ---------------------------------------------------------------------

def test_the_starter_layout_file_is_the_default_layout(tmp_path) -> None:
    project = create_project("New", "research", root=tmp_path)
    assert (project.directory / report.LAYOUT_FILE).is_file(), "it ships in the starter"
    layout, notes, _text = report.read_layout(project.directory)
    assert layout == report.Layout() and notes == []


def test_the_layout_moves_the_parts_and_changes_the_title(study) -> None:
    (study.directory / "src" / "report.toml").write_text(
        'title = "Our Garden Weather"\nauthor = "Sam"\ntitle_size = 36\n'
        'order = ["charts", "findings"]\n', encoding="utf-8")
    made = _build(study)
    assert made.sections == ("charts", "findings")
    assert made.starts[0] == ("charts", 1)
    words = _words(made.pdf)
    assert "Our Garden Weather" in words and "By Sam" in words
    assert "Was the summer" not in words, "the question was left out"


def test_the_charts_line_chooses_and_orders_them(study) -> None:
    (study.directory / "src" / "report.toml").write_text(
        'charts = ["rain_by_month.png", "chart", "old_chart.png"]\n', encoding="utf-8")
    made = _build(study)
    assert made.charts == ("charts/rain_by_month.png", "charts/chart.png")
    assert any("old_chart.png, which the analysis did not draw" in n for n in made.notes)


def test_a_mistake_in_the_layout_gets_the_usual_layout_and_is_said(study) -> None:
    layout_file = study.directory / "src" / "report.toml"
    layout_file.write_text('title = "Unfinished\n', encoding="utf-8")
    made = _build(study)
    assert made.sections == report.SECTIONS
    assert any("report.toml has a mistake on line 1" in n for n in made.notes)

    layout_file.write_text('title_size = "big"\ntext_size = 99\norder = ["charts", "pictures"]\n'
                           'colour = "red"\n', encoding="utf-8")
    layout, notes, _text = report.read_layout(study.directory)
    assert layout.title_size == 26 and layout.text_size == 16
    assert layout.order == ("charts",)
    assert any("title_size has to be a number" in n for n in notes)
    assert any("text_size can be 8 to 16, so 16 was used" in n for n in notes)
    assert any("no part called “pictures”" in n for n in notes)
    assert any("does not know “colour”" in n for n in notes)


def test_an_older_project_gets_the_layout_file_only_when_asked(tmp_path) -> None:
    project = create_project("Older", "research", root=tmp_path)
    layout_file = project.directory / report.LAYOUT_FILE
    layout_file.unlink()
    assert report.read_layout(project.directory)[0] == report.Layout()
    assert report.ensure_layout_file(project.directory) is True
    assert layout_file.read_text(encoding="utf-8") == \
        report.STARTER_LAYOUT.read_text(encoding="utf-8")
    assert report.ensure_layout_file(project.directory) is False


# -- the PDF -----------------------------------------------------------------------------

def test_the_pdf_opens_in_another_reader_at_eight_by_ten(study) -> None:
    from PySide6.QtPdf import QPdfDocument

    made = _build(study)
    assert made.pdf.startswith(b"%PDF-")
    document, _buffer, _data = _opened(made.pdf)
    assert document.status() == QPdfDocument.Status.Ready
    assert document.pageCount() == made.pages
    for page in range(document.pageCount()):
        size = document.pagePointSize(page)
        assert (round(size.width()), round(size.height())) == (576, 720)


def test_the_charts_go_in_at_their_own_resolution(study) -> None:
    """Embedded unresampled -- the viewer or printer scales them, so 150 dpi drawn at 80%
    prints at about 190 dpi rather than being thinned to the page's 72."""
    pdf = _build(study).pdf
    assert b"/Width 1223" in pdf and b"/Height 1525" in pdf


def test_matplotlib_keeps_its_cache_inside_open_nest(tmp_path) -> None:
    import subprocess
    import sys

    env = {**os.environ, "OPENNEST_HOME": str(tmp_path / "home")}
    env.pop("MPLCONFIGDIR", None)
    code = ("from opennest.export import report; report._matplotlib(); import os; "
            "print(os.environ['MPLCONFIGDIR'])")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          env=env, cwd=Path(__file__).resolve().parent.parent, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(tmp_path / "home" / "cache" / "matplotlib")
