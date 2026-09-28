"""Research: what Open Nest can read about an analysis and its data, and what it adds.

The research prompt's first rule is "never state a finding you have not computed", and it
shapes everything here. An operation never says what the data shows: it writes code that
computes it, the verification runs that code, and the reply quotes what the run printed.
The chart's title is computed the same way -- "Basil has the highest average height" is
written by the code from the numbers, not by anyone guessing at them.

The columns are facts, read from the CSV the analysis will actually open (the first one
in ``data/``, in the order the starter's ``find_a_table`` sorts them). Which column the
child means is decided by their own words first -- "height" finds ``height_cm`` -- and
only when that is ambiguous is the model asked, from the real column names and nothing
else. A child with no data yet gets Gary, who asks for some.
"""

from __future__ import annotations

import ast
import csv
import json
import re
from pathlib import Path

from opennest.agent.tools import ToolResult
from opennest.ai.provider import ToolCall
from opennest.execution import outputs
from opennest.fastpath.classifier import OTHER, Option
from opennest.fastpath.kinds import (
    Change,
    Context,
    Facts,
    NeedsAnswer,
    NotApplicable,
    confident,
)

#: The Research starter's analysis file. The file actually read is the project's own
#: entry point -- the one its Run button runs -- which in a Research project is this and
#: in a Blank project that became a data project is ``src/main.py``.
ENTRY = "src/analysis.py"
_TIME_WORDS = re.compile(r"(^|_|\b)(day|date|time|week|month|year|step|trial|round|hour|"
                         r"minute|second|session|visit|lesson|when)s?($|_|\b)", re.IGNORECASE)
_MAX_ROWS_READ = 5000
#: A time column whose text sorts into time order: an ISO date, with or without a time.
#: Anything else that is not a number -- "Jan", "Mon", "week one" -- sorts alphabetically,
#: so it is kept in the order the data was written down.
_ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")


# ----------------------------------------------------------------------------- facts

def _read_table(path: Path) -> dict | None:
    """Columns, which are numbers, how many rows, and how many different text values."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))[: _MAX_ROWS_READ + 1]
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    if len(rows) < 2 or not rows[0]:
        return None
    header = [name.strip() for name in rows[0]]
    body = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    numeric, distinct, ordered = [], {}, []
    for index, name in enumerate(header):
        cells = [row[index].strip() for row in body if index < len(row) and row[index].strip()]
        try:
            [float(cell) for cell in cells]
            is_number = bool(cells)
        except ValueError:
            is_number = False
        if is_number:
            numeric.append(name)
        if is_number or (cells and all(_ISO_TIME.match(cell) for cell in cells)):
            ordered.append(name)
        distinct[name] = len(set(cells))
    return {"file": path.name, "columns": header, "numeric": numeric,
            "rows": len(body), "distinct": distinct, "ordered": ordered}


def entry_path(project) -> str:
    return f"src/{project.manifest.entrypoint}"


def facts(project, attachments=()) -> Facts:
    entry = entry_path(project)
    values: dict = {"entry": entry}
    data = project.directory / "data"
    tables = sorted(data.glob("*.csv")) if data.is_dir() else []
    if tables:
        values["table"] = _read_table(tables[0])
    file = project.directory / entry
    if not file.is_file():
        return Facts(values)
    source = file.read_text(encoding="utf-8")
    values["source"] = source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return Facts(values)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "matplotlib.pyplot":
                    values["plt"] = alias.asname or alias.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
            node.targets[0], ast.Name
        ):
            name = node.targets[0].id
            value = node.value
            if (isinstance(value, ast.Call) and getattr(value.func, "id", "") == "Path"
                    and value.args and isinstance(value.args[0], ast.Constant)
                    and ("CHART" in name or "OUTPUT" in name)):
                values["chart_dir"] = name
                values["chart_folder"] = value.args[0].value
        elif isinstance(node, ast.If) and node.orelse and isinstance(node.test, ast.Compare) \
                and isinstance(node.test.ops[0], ast.Is) \
                and isinstance(node.test.comparators[0], ast.Constant) \
                and node.test.comparators[0].value is None:
            # ``if table is None: ... else: <the analysis>`` -- new work goes at the end of
            # the else, where it runs whenever there is data.
            values["anchor"] = node.orelse[-1].end_lineno
            values["indent"] = " " * node.orelse[0].col_offset
            for stmt in node.orelse:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call) and \
                        getattr(stmt.value.func, "attr", "") == "read_csv" and \
                        isinstance(stmt.targets[0], ast.Name):
                    values["frame"] = stmt.targets[0].id
    return Facts(values)


def where(facts: Facts) -> str:
    notes = ["WHAT IS IN THIS PROJECT RIGHT NOW"]
    table = facts.get("table")
    if table:
        numeric = set(table["numeric"])
        described = ", ".join(f"{name} ({'numbers' if name in numeric else 'text'})"
                              for name in table["columns"])
        notes.append(f"- data/{table['file']}: {table['rows']} rows. Columns: {described}. "
                     "Use these exact column names.")
    if facts.has("anchor"):
        notes.append(f"- In {facts.get('entry')}, new analysis goes at the end of the else: "
                     f"block that starts with reading the CSV (after line "
                     f"{facts.get('anchor')}), indented {len(facts.get('indent'))} spaces, "
                     f"using the DataFrame called {facts.get('frame', 'frame')}.")
    if facts.has("chart_dir"):
        notes.append(f"- Save charts with figure.savefig({facts.get('chart_dir')} / \"name.png\").")
    return "\n".join(notes) if len(notes) > 1 else ""


# ------------------------------------------------------------------------ columns

def _require(facts: Facts, *names: str) -> None:
    if not facts.has("table"):
        raise NeedsAnswer("there is no data file in the project yet")
    missing = facts.missing(names)
    if missing:
        raise NotApplicable(f"the analysis does not have: {', '.join(missing)}")


#: Everyday words for what a column measures. Only ever used to find a column that
#: exists; a synonym for a column that is not there finds nothing.
_SYNONYMS = {
    "tall": "height", "taller": "height", "tallest": "height", "high": "height",
    "heavy": "weight", "heavier": "weight", "heaviest": "weight",
    "hot": "temp", "hotter": "temp", "cold": "temp", "colder": "temp", "warm": "temp",
    "temperature": "temp", "wet": "rain", "rainy": "rain", "rainfall": "rain",
    "old": "age", "older": "age", "long": "length", "longer": "length",
    "far": "distance", "fast": "speed", "faster": "speed", "watered": "water",
}


def _mentioned(request: str, candidates: list[str]) -> list[str]:
    """Columns the child named, by any word of the column's name ("height" -> height_cm)."""
    words = set(re.findall(r"[a-z]+", request.lower()))
    words |= {_SYNONYMS[word] for word in words if word in _SYNONYMS}
    stems = {word[:-1] if word.endswith("s") and len(word) > 4 else word for word in words}
    found = []
    for name in candidates:
        parts = [part for part in re.split(r"[^a-z]+", name.lower()) if len(part) >= 3]
        if any(part in words or part in stems or part[:4] in words for part in parts):
            found.append(name)
    return found


def _pick(ctx: Context, question: str, candidates: list[str], *,
          exclude: tuple[str, ...] = ()) -> str:
    """One column: the child's words, else the only one, else a closed question."""
    candidates = [name for name in candidates if name not in exclude]
    if not candidates:
        raise NotApplicable("no column of the right kind")
    named = _mentioned(ctx.request, candidates)
    if len(named) == 1:
        return named[0]
    if len(candidates) == 1:
        return candidates[0]
    if ctx.choose is None:
        raise NotApplicable("no model to ask which column")
    pool = named if len(named) > 1 else candidates
    if len(pool) > 24:
        raise NotApplicable("too many columns to ask about")
    options = [Option(name, name) for name in pool]
    options.append(Option(OTHER, "none of these, or it does not say"))
    answer = confident(ctx.choose(question, options))
    if answer is None or answer == OTHER:
        raise NotApplicable("not sure which column")
    return answer


def _groups(table: dict) -> list[str]:
    """Text columns that sort rows into a handful of groups."""
    numeric = set(table["numeric"])
    return [name for name in table["columns"] if name not in numeric
            and 1 < table["distinct"].get(name, 0) <= 12
            and not _is_time(name)]


#: Units of time. On their own they name when a row was ("hour"); beside another word
#: they are how much of something there was ("sunshine_hours", "hours_slept").
_TIME_UNITS = frozenset({"hour", "minute", "second"})


def _is_time(name: str) -> bool:
    """Whether a column says when each row was, rather than measuring something.

    Measured on the Phase 12 walk's own data: "sunshine_hours" was read as a second time
    column, so there was no single time axis and the sunshine was left out of "what
    changed the most" altogether.
    """
    if not _TIME_WORDS.search(name):
        return False
    parts = [part for part in re.split(r"[^a-z]+", name.lower()) if part]
    words = {part[:-1] if part.endswith("s") else part for part in parts}
    return not (len(parts) > 1 and words & _TIME_UNITS
                and not _TIME_WORDS.search("_".join(sorted(words - _TIME_UNITS))))


def _times(table: dict) -> list[str]:
    return [name for name in table["columns"] if _is_time(name)]


def _in_time_order(table: dict, column: str | None) -> bool:
    """Whether sorting by this column puts the rows in time order: numbers and ISO dates."""
    return column is not None and column in table.get("ordered", ())


def _ordered(frame: str, column: str, in_order: bool) -> str:
    """The rows first to last: sorted by the column when that is time order, else as
    they were written down."""
    return f"{frame}.sort_values({_q(column)})" if in_order else frame


def _best_group(ctx: Context, table: dict, groups: list[str], time: str | None) -> str:
    """The group a chart should split by: the one the child named, else the one that
    identifies each thing being followed -- exactly one row per group per time, like
    each plant on each day -- else the one with the fewest groups."""
    named = _mentioned(ctx.request, groups)
    if len(named) == 1:
        return named[0]
    if time:
        followed = [g for g in groups
                    if table["distinct"][g] * table["distinct"].get(time, 0) == table["rows"]]
        if len(followed) == 1:
            return followed[0]
    return min(groups, key=lambda g: table["distinct"][g])


def _q(name: str) -> str:
    """A column name as a Python string literal."""
    return json.dumps(name)


def _file_name(*parts: str) -> str:
    return "_".join(re.sub(r"[^a-z0-9]+", "_", part.lower()).strip("_") for part in parts) \
        + ".png"


def _save(ctx: Context, name: str) -> list[str]:
    plt = ctx.facts.get("plt", "plt")
    folder = ctx.facts.get("chart_dir")
    return [
        "figure.tight_layout()",
        f"{folder}.mkdir(exist_ok=True)",
        f"figure.savefig({folder} / {_q(name)})",
        f"{plt}.close(figure)",
        f'print(f"Chart saved to {{{folder} / {_q(name)}}}")',
    ]


def _insert(ctx: Context, block: list[str]) -> str:
    source = ctx.facts.get("source")
    lines = source.split("\n")
    indent = ctx.facts.get("indent")
    at = ctx.facts.get("anchor")
    lines[at:at] = [""] + [(indent + line) if line else "" for line in block]
    return "\n".join(lines)


def _change(ctx: Context, block: list[str], marker: str, values: dict,
            chart: str | None = None) -> Change:
    folder = ctx.facts.get("chart_folder", "charts")
    values = {"table": ctx.facts.get("table")["file"], **values}
    if chart:
        values["chart"] = f"{folder}/{chart}"
    return Change(files={ctx.facts.get("entry"): _insert(ctx, block)}, values=values,
                  expect={"marker": marker, "chart": f"{folder}/{chart}" if chart else None})


# ------------------------------------------------------------------------ operations

def run_only(ctx: Context) -> Change:
    """Describe the data: run the analysis as it is and report what it printed."""
    _require(ctx.facts)
    return Change(files={}, values={"table": ctx.facts.get("table")["file"]},
                  expect={"marker": None, "chart": None})


def chart(ctx: Context) -> Change:
    """A chart, written in full: labelled axes, a title computed from the numbers."""
    _require(ctx.facts, "anchor", "frame", "chart_dir")
    kind = ctx.params["chart"]
    table = ctx.facts.get("table")
    frame, plt = ctx.facts.get("frame"), ctx.facts.get("plt", "plt")
    numbers = table["numeric"]
    if not numbers:
        raise NotApplicable("the data has no number columns to chart")

    if kind == "bar":
        group = _pick(ctx, "Which column holds the groups to compare?", _groups(table))
        value = _pick(ctx, "Which number should each bar show?", numbers)
        repeated = table["distinct"].get(group, 0) < table["rows"]
        how = "Average " if repeated else ""
        name = _file_name(value, "by", group)
        block = [
            f"# Bar chart: {how.lower()}{value} for each {group}.",
            (f"summary = {frame}.groupby({_q(group)})[{_q(value)}].mean()" if repeated else
             f"summary = {frame}.set_index({_q(group)})[{_q(value)}]"),
            "summary = summary.sort_values(ascending=False)",
            f'print("\\n{how}{value} for each {group}:")',
            "print(summary.round(2).to_string())",
            f"figure, axes = {plt}.subplots()",
            "bars = axes.bar(summary.index.astype(str), summary.values)",
            'axes.bar_label(bars, fmt="%.1f", padding=3)',
            f"axes.set_xlabel({_q(group)})",
            f"axes.set_ylabel({_q(how + value)})",
            f'axes.set_title(f"{{summary.index[0]}} has the highest {how.lower()}{value}")',
            f'{plt}.setp(axes.get_xticklabels(), rotation=30, ha="right")',
        ] + _save(ctx, name)
        marker = f"{how}{value} for each {group}:"
        values = {"what": f"a bar chart of {how.lower()}{value} for each {group}"}
    elif kind == "line":
        times = _times(table) or [c for c in table["columns"] if c in numbers]
        x = _pick(ctx, "Which column goes along the bottom, like time?", times)
        y = _pick(ctx, "Which number should the line show?", numbers, exclude=(x,))
        groups = [g for g in _groups(table) if g != x]
        repeats = table["distinct"].get(x, 0) < table["rows"]
        # Month names and weekdays sort alphabetically, so they keep the data's order.
        in_order = _in_time_order(table, x)
        name = _file_name(y, "over", x)
        block = [f"# Line chart: how {y} changed over {x}."]
        if repeats and groups:
            group = _best_group(ctx, table, groups, x)
            block += [
                f"figure, axes = {plt}.subplots()",
                f"for name, rows in {frame}.groupby({_q(group)}):",
            ] + ([f"    rows = rows.sort_values({_q(x)})"] if in_order else []) + [
                f'    axes.plot(rows[{_q(x)}], rows[{_q(y)}], marker="o", label=str(name))',
                f"axes.legend(title={_q(group)})",
                f"latest = {_ordered(frame, x, in_order)}.groupby({_q(group)})[{_q(y)}].last()",
                f'print("\\nThe last {y} for each {group}:")',
                "print(latest.sort_values(ascending=False).round(2).to_string())",
            ]
            values = {"what": f"a line chart of {y} over {x}, one line for each {group}"}
            marker = f"The last {y} for each {group}:"
        else:
            block += [
                (f"trend = {frame}.groupby({_q(x)}{'' if in_order else ', sort=False'})"
                 f"[{_q(y)}].mean()" if repeats else
                 f"trend = {frame}.set_index({_q(x)})[{_q(y)}]"
                 + (".sort_index()" if in_order else "")),
                f"figure, axes = {plt}.subplots()",
                'axes.plot(trend.index, trend.values, marker="o")',
                f'print("\\n{y} over {x}: from", round(trend.iloc[0], 2), "to", '
                f"round(trend.iloc[-1], 2))",
            ]
            values = {"what": f"a line chart of {y} over {x}"}
            marker = f"{y} over {x}: from"
        block += [f"axes.set_xlabel({_q(x)})", f"axes.set_ylabel({_q(y)})",
                  f'axes.set_title("How {y} changed over {x}")'] + _save(ctx, name)
    elif kind == "scatter":
        x = _pick(ctx, "Which number goes along the bottom?", numbers)
        y = _pick(ctx, "Which number goes up the side?", numbers, exclude=(x,))
        name = _file_name(y, "against", x)
        block = [
            f"# Scatter plot: does {y} go with {x}?",
            f"figure, axes = {plt}.subplots()",
            f"axes.scatter({frame}[{_q(x)}], {frame}[{_q(y)}], alpha=0.8)",
            f"together = {frame}[{_q(x)}].corr({frame}[{_q(y)}])",
            f'print(f"\\nHow closely {y} and {x} move together: {{together:.2f}}")',
            'print("(1 is perfectly together, 0 is not at all, -1 is perfectly opposite.)")',
            'print("Moving together does not show that one causes the other.")',
            f"axes.set_xlabel({_q(x)})",
            f"axes.set_ylabel({_q(y)})",
            f'axes.set_title(f"{y} against {x} (r = {{together:.2f}})")',
        ] + _save(ctx, name)
        marker = f"How closely {y} and {x} move together:"
        values = {"what": f"a scatter plot of {y} against {x}"}
    elif kind == "histogram":
        value = _pick(ctx, "Which number should be counted up?", numbers)
        name = _file_name(value, "spread")
        block = [
            f"# Histogram: how {value} is spread out.",
            f"figure, axes = {plt}.subplots()",
            f'axes.hist({frame}[{_q(value)}].dropna(), bins="auto")',
            f"middle = {frame}[{_q(value)}].mean()",
            # "0.4" is matplotlib's own grey scale: a muted line, and no colour literal
            # that could disagree with the project's matplotlibrc.
            'axes.axvline(middle, linestyle="--", color="0.4")',
            f'print(f"\\n{value}: lowest {{{frame}[{_q(value)}].min()}}, highest '
            f'{{{frame}[{_q(value)}].max()}}, average {{middle:.2f}}")',
            f"axes.set_xlabel({_q(value)})",
            'axes.set_ylabel("How many rows")',
            f'axes.set_title(f"How {value} is spread out (average {{middle:.1f}})")',
        ] + _save(ctx, name)
        marker = f"{value}: lowest"
        values = {"what": f"a histogram of {value}"}
    else:
        raise NotApplicable(f"no chart called {kind}")
    return _change(ctx, block, marker, values, chart=name)


def group_summary(ctx: Context) -> Change:
    """The average of a number for each group, or how many rows each group has."""
    _require(ctx.facts, "anchor", "frame")
    table = ctx.facts.get("table")
    frame = ctx.facts.get("frame")
    group = _pick(ctx, "Which column holds the groups?", _groups(table))
    if ctx.params.get("measure") == "count":
        block = [f"# How many rows there are for each {group}.",
                 f"counts = {frame}[{_q(group)}].value_counts()",
                 f'print("\\nHow many rows for each {group}:")',
                 "print(counts.to_string())"]
        return _change(ctx, block, f"How many rows for each {group}:",
                       {"what": f"a count of the rows for each {group}"})
    value = _pick(ctx, "Which number should be averaged?", table["numeric"])
    block = [f"# The average {value} for each {group}.",
             f"averages = {frame}.groupby({_q(group)})[{_q(value)}].mean()",
             f'print("\\nAverage {value} for each {group}:")',
             "print(averages.sort_values(ascending=False).round(2).to_string())"]
    return _change(ctx, block, f"Average {value} for each {group}:",
                   {"what": f"the average {value} for each {group}"})


def biggest_change(ctx: Context) -> Change:
    """What changed the most from first to last -- computed, printed, and charted."""
    _require(ctx.facts, "anchor", "frame", "chart_dir")
    table = ctx.facts.get("table")
    frame, plt = ctx.facts.get("frame"), ctx.facts.get("plt", "plt")
    numbers = [n for n in table["numeric"] if not _is_time(n)]
    times = _times(table)
    time = times[0] if len(times) == 1 else None
    # Measured on the Phase 12 walk's own data: sorting "Jan".."Dec" alphabetically made
    # "the first month to the last" April to September, and the finding was wrong.
    order = _ordered(frame, time, _in_time_order(table, time)) if time else frame
    since = f"the first {time} to the last" if time else "the first row to the last"
    groups = _groups(table)
    if groups and numbers:
        group = _best_group(ctx, table, groups, time)
        value = _pick(ctx, "Which number might have changed?", numbers)
        name = _file_name(value, "change", "by", group)
        block = [
            f"# What changed the most: {value} from {since}, for each {group}.",
            f"ordered = {order}",
            f"changes = ordered.groupby({_q(group)})[{_q(value)}].agg(",
            "    lambda values: values.iloc[-1] - values.iloc[0])",
            "changes = changes.sort_values(ascending=False)",
            f'print("\\nHow much {value} changed from {since}:")',
            "print(changes.round(2).to_string())",
            'print(f"The biggest change was {changes.index[0]}: {changes.iloc[0]:+.2f}")',
            f"figure, axes = {plt}.subplots()",
            "bars = axes.bar(changes.index.astype(str), changes.values)",
            'axes.bar_label(bars, fmt="%+.1f", padding=3)',
            f"axes.set_xlabel({_q(group)})",
            f"axes.set_ylabel({_q('Change in ' + value)})",
            'axes.set_title(f"{changes.index[0]} changed the most")',
        ] + _save(ctx, name)
        marker = f"How much {value} changed from {since}:"
        what = f"how much {value} changed for each {group}"
    elif numbers:
        name = _file_name("change", "by", "column")
        block = [
            f"# What changed the most: every number column, from {since}.",
            f"ordered = {order}",
            f"numbers = ordered[{json.dumps(numbers)}]",
            "changes = numbers.iloc[-1] - numbers.iloc[0]",
            "changes = changes.reindex(changes.abs().sort_values(ascending=False).index)",
            f'print("\\nHow much each column changed from {since}:")',
            "print(changes.round(2).to_string())",
            'print(f"The biggest change was {changes.index[0]}: {changes.iloc[0]:+.2f}")',
            f"figure, axes = {plt}.subplots()",
            "bars = axes.bar(changes.index.astype(str), changes.values)",
            'axes.bar_label(bars, fmt="%+.1f", padding=3)',
            'axes.set_xlabel("Column")',
            'axes.set_ylabel("Change")',
            'axes.set_title(f"{changes.index[0]} changed the most")',
        ] + _save(ctx, name)
        marker = f"How much each column changed from {since}:"
        what = "how much each number column changed"
    else:
        raise NotApplicable("the data has no number columns")
    return _change(ctx, block, marker, {"what": what}, chart=name)


OPS = {
    "run_only": run_only,
    "chart": chart,
    "group_summary": group_summary,
    "biggest_change": biggest_change,
}


# ------------------------------------------------------------------------ checks

def _run(ctx):
    """Run the analysis once, through the Toolbox, and keep what it produced."""
    def run():
        before = outputs.snapshot(ctx.project.directory)
        call = ToolCall(name="run_project", arguments={}, id="fastpath_run")
        result: ToolResult = ctx.toolbox.dispatch(call.name, call.arguments)
        written = outputs.images_written(ctx.project.directory, before)
        ctx.once("calls", list)
        ctx._cache["calls"].append((call, result))
        return {"result": result, "images": written,
                "stdout": result.run.stdout if result.run is not None else ""}
    return ctx.once("run", run)


def _check_runs(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    ran = _run(ctx)
    result = ran["result"]
    if result.run is None:
        return Check("runs_clean", UNAVAILABLE, result.content[:200])
    if result.ok:
        return Check("runs_clean", PASS)
    return Check("runs_clean", FAIL, result.content[-800:])


def _check_chart(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    wanted = ctx.expect.get("chart")
    ran = _run(ctx)
    if ran["result"].run is None:
        return Check("chart_written", UNAVAILABLE, "the analysis could not be run")
    if wanted and any(path == wanted or path.endswith("/" + wanted) or path.endswith(wanted)
                      for path in ran["images"]):
        return Check("chart_written", PASS, wanted)
    return Check("chart_written", FAIL, f"{wanted} was not written")


def _check_printed(ctx):
    """The new code printed its result -- and that text is what the child will read."""
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    ran = _run(ctx)
    stdout = ran["stdout"]
    if ran["result"].run is None:
        return Check("printed_result", UNAVAILABLE, "the analysis could not be run")
    marker = ctx.expect.get("marker")
    lines = stdout.strip("\n").split("\n")
    if marker is None:
        # The analysis as it stands: its first paragraph is the description.
        excerpt = []
        for line in lines[:10]:
            if excerpt and not line.strip():
                break
            excerpt.append(line)
    else:
        start = next((i for i, line in enumerate(lines) if marker in line), None)
        if start is None:
            return Check("printed_result", FAIL, f"it never printed {marker!r}")
        excerpt = []
        for line in lines[start:start + 14]:
            if excerpt and (not line.strip() or line.startswith("Chart saved")):
                break
            excerpt.append(line)
    ctx._cache["excerpt"] = "\n".join(excerpt)
    return Check("printed_result", PASS, excerpt[0][:120] if excerpt else "")


CHECKS = {
    "runs_clean": _check_runs,
    "chart_written": _check_chart,
    "printed_result": _check_printed,
}


#: How a change Gary makes here is checked, for his context (router._context).
CHECKED = ("Run the analysis with run_project after changing it, and say only what it "
           "printed.")


def verifiable(project) -> bool:
    """Whether this project can run its analysis -- the check every one of these needs."""
    return project.profile.can_run and "run_project" in project.profile.tools


def confirmation(verification, project=None) -> str:
    """What the run printed, quoted exactly. Never a summary of it."""
    from opennest.fastpath.verifier import PASS

    if verification.status_of("runs_clean") != PASS:
        button = getattr(getattr(project, "profile", None), "run_label", "Run Analysis")
        return f"I haven't been able to run it here, so press {button} to see the result."
    excerpt = verification.evidence.get("excerpt", "")
    if not excerpt:
        return "I ran it and it finished cleanly."
    quoted = "\n".join(f"    {line}" for line in excerpt.split("\n"))
    return f"I ran it, and it printed:\n\n{quoted}"


def brief(facts: Facts) -> str:
    """What the classifier is told about the project, from the facts alone."""
    table = facts.get("table")
    if not table:
        return "There is no data file in the project yet."
    return (f"The data is {table['file']}, {table['rows']} rows, with columns "
            f"{', '.join(table['columns'])}. The analysis already draws one chart.")
