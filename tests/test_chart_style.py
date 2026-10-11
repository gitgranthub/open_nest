"""Gary's chart code is kept in the project's palette by the application, not the prompt."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from opennest.agent.chart_style import keep_house_colours
from opennest.agent.tools import Toolbox
from opennest.projects.manager import create_project

DASHBOARD = '''import seaborn as sns
sns.lineplot(data=frame, x="date", y="temp_high_f", label="High", color="red")
sns.lineplot(data=frame, x="date", y="temp_low_f", color="blue", label="Low")
sns.lineplot(
    data=frame,
    y="wind",
    color="green",
)
plt.plot(x, y, "o-", c="#ff00aa")
'''


def test_new_series_colours_come_out_and_the_code_still_runs() -> None:
    fixed, removed = keep_house_colours("", DASHBOARD)
    assert removed == ["#ff00aa", "blue", "green", "red"]
    assert "color=" not in fixed and "c=" not in fixed
    ast.parse(fixed)
    assert 'label="High")' in fixed and 'color="blue", label' not in fixed


def test_a_colour_the_child_asked_for_stays() -> None:
    kept, removed = keep_house_colours("", DASHBOARD, "make the high line red")
    assert kept == DASHBOARD and removed == []
    kept, removed = keep_house_colours("", DASHBOARD, "use a different colour please")
    assert kept == DASHBOARD and removed == []


def test_matplotlibs_named_palettes_are_colours_too() -> None:
    """Gary Smart's dashboard: tab:blue, tab:green, tab:red (SPIKES.md section 34F)."""
    code = ('sns.lineplot(data=f, x="date", y="t", color="tab:blue")\n'
            'sns.lineplot(data=f, x="date", y="h", color="xkcd:sky blue")\n'
            'axes.plot(x, y, color="tab:gray")\n')
    fixed, removed = keep_house_colours("", code)
    assert removed == ["tab:blue", "xkcd:sky blue"]
    assert 'color="tab:gray"' in fixed, "a grey is a neutral, whichever palette it is from"
    ast.parse(fixed)


def test_a_colour_inside_another_word_was_not_asked_for() -> None:
    for message in ("chart the hundred hottest days", "i'm bored, show the wind",
                    "rain covered the garden", "the station's stand"):
        fixed, removed = keep_house_colours("", DASHBOARD, message)
        assert removed == ["#ff00aa", "blue", "green", "red"], message


def test_only_what_is_new_is_touched() -> None:
    """A colour already in the file -- one the child asked for last week -- survives an
    unrelated edit; the one added now does not."""
    before = 'plt.plot(x, y, color="red")\n'
    after = before + 'plt.plot(x, w, color="teal")\n'
    fixed, removed = keep_house_colours(before, after)
    assert removed == ["teal"]
    assert fixed.count('color="red"') == 1 and "teal" not in fixed


def test_neutrals_decorations_and_numbers_are_left_alone() -> None:
    code = ('plt.plot(x, y, color="black")\naxes.axvline(3, color="red")\n'
            'axes.scatter(x, y, c=values)\naxes.bar(a, b, color=palette[0])\n')
    assert keep_house_colours("", code) == (code, [])


def test_code_that_does_not_parse_is_left_alone() -> None:
    code = "plt.plot(x, y, color='red'"
    assert keep_house_colours("", code) == (code, [])


def test_the_tools_do_it_for_a_research_project_and_say_so(tmp_path: Path) -> None:
    project = create_project("Weather", "research", root=tmp_path)
    box = Toolbox(project)
    box.message = ("make me a dashboard of the weather", ())
    result = box.dispatch("write_file", {"path": "src/dash.py", "content": DASHBOARD})
    assert result.ok and "Open Nest took out" in result.content
    target = project.directory / "src" / "dash.py"
    assert "color=" not in target.read_text(encoding="utf-8")

    box.message = ("make the wind line green", ())
    edit = box.dispatch("edit_file", {"path": "src/dash.py",
                                      "old_text": '    y="wind",\n',
                                      "new_text": '    y="wind",\n    color="green",\n'})
    assert edit.ok and 'color="green"' in target.read_text(encoding="utf-8")


def test_other_kinds_of_project_are_not_touched(tmp_path: Path) -> None:
    project = create_project("Arcade", "games", root=tmp_path)
    Toolbox(project).dispatch("write_file", {"path": "src/art.py", "content": DASHBOARD})
    written = (project.directory / "src" / "art.py").read_text(encoding="utf-8")
    assert 'color="red"' in written


@pytest.mark.parametrize("name", ["date", "Date_Recorded", "timestamp"])
def test_the_starter_turns_date_columns_into_dates(name: str) -> None:
    import pandas as pd

    from opennest.projects import starters

    kit = next(k for k in starters.load_starters() if k.id == "research_basic")
    tree = ast.parse((kit.directory / "analysis.py").read_text(encoding="utf-8"))
    func = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "read_dates")
    scope: dict = {"pd": pd}
    exec(compile(ast.Module([func], []), "x", "exec"), scope)
    frame = pd.DataFrame({name: ["2025-01-01", "2025-01-02"], "note": ["a", "b"]})
    scope["read_dates"](frame)
    assert str(frame[name].dtype).startswith("datetime64")
    assert not str(frame["note"].dtype).startswith("datetime64")
