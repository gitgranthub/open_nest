"""Can Gary change the report -- and did this pass's Research prompt changes cost anything?

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/report/report_turns.py <label> [--model=<id>] [--conditions=before,after]
        [--groups=report,inreport,charts,questions]

Every message is one turn on a fresh copy of one Research project: the owner's weather CSV
(``assets/test_data``), a question, findings and sources written, an analysis drawing three
charts, and that analysis run once, as the child would have before asking. The real
controller, Toolbox, Fast Path, version history and model.

Conditions:

- **before** -- the product without this pass's Gary changes: no report note beside the
  message, the Fast Path offered every message, no report line in the screen guide, and
  the research prompt as committed at HEAD (before the previous pass's colour, figsize and
  date lines). The project still has src/report.toml, so the file is there to be found.
- **after** -- as built.

The goals were written down before the first run, below, and are checked from the files:

- **report** -- each says what src/report.toml must hold afterwards; analysis.py and the
  .md files must be unchanged, and the file must still read without a mistake.
- **charts** -- ordinary chart requests, for the research prompt: the analysis must run
  and draw afterwards, report.toml untouched, and a colour named only where asked
  (Open Nest takes out an unasked one, and says so in the tool result -- counted).
- **inreport** -- a report message that is about a chart: the analysis's title must
  change and still run, and report.toml must not.
- **questions** -- answered with the real button ("Export PDF"), and nothing changed.

Writes ``results/<label>.json``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from opennest.agent import controller as controller_module  # noqa: E402
from opennest.agent import evidence  # noqa: E402
from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.router import build_provider, default_model_id  # noqa: E402
from opennest.assets import manager as assets  # noqa: E402
from opennest.export import report  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.projects import profiles  # noqa: E402
from opennest.projects.manager import create_project, open_project  # noqa: E402
from opennest.versioning.checkpoint import VersionHistory  # noqa: E402

CSV = REPO / "assets" / "test_data" / "home_weather_station_2025.csv"
INPUTS = HERE / "inputs"


def layout_of(directory: Path):
    layout, notes, _text = report.read_layout(directory)
    return layout, notes


#: (message, goal on the layout afterwards, what the goal is in words)
REPORT = [
    ("make the title of my report bigger",
     lambda lay: lay.title_size > 26, "title_size > 26"),
    ("can you put the charts first in my report",
     lambda lay: lay.order[:1] == ("charts",) and set(lay.order) == set(report.SECTIONS),
     "order starts with charts, all four parts kept"),
    ("put my name on the report, my name is Sam",
     lambda lay: lay.author == "Sam", "author = Sam"),
    ("call my report Our Garden Weather",
     lambda lay: lay.title == "Our Garden Weather", "title = Our Garden Weather"),
    ("take the sources out of the report",
     lambda lay: "sources" not in lay.order and len(lay.order) == 3, "order without sources"),
    ("make the words in the report smaller",
     lambda lay: lay.text_size < 11, "text_size < 11"),
    ("only put the rain chart in the report",
     lambda lay: len(lay.charts) == 1 and "rain" in lay.charts[0], "charts = the rain chart"),
]

#: A message about the report that is a change to a chart: the analysis, not the layout --
#: (message, the words the chart's title must have afterwards). Added with the note's
#: second wording, which says so (SPIKES.md section 34F).
IN_REPORT = [
    ("the rain chart in my report should be called Rain by month", "Rain by month"),
    ("the temperature chart in my report needs a label on the side saying degrees",
     "degrees"),
]

#: (message, whether the child asked for a colour)
CHARTS = [
    ("make a chart of how the temperature changed over the year", False),
    ("show the rain for each month as a bar chart", False),
    ("make the humidity line green", True),
    ("make a dashboard of the weather with temperature, humidity and wind", False),
]

QUESTIONS = [
    "how do I save my report as a pdf?",
    "can I print my report?",
]

_NO_MATCH = re.compile(r"(?!x)x")


def before_condition() -> dict:
    """Switch this pass's Gary changes off; returns what to put back."""
    head_prompt = subprocess.run(["git", "show", "HEAD:opennest/prompts/research.txt"],
                                 cwd=REPO, capture_output=True, text=True,
                                 check=True).stdout.strip()
    saved = {"about": controller_module._ABOUT_REPORT, "line": evidence._report_line,
             "prompt": profiles.Profile.system_prompt}
    original = profiles.Profile.system_prompt

    def system_prompt(self):
        return head_prompt if self.id == "research" else original(self)

    controller_module._ABOUT_REPORT = _NO_MATCH
    evidence._report_line = lambda profile: ""
    profiles.Profile.system_prompt = system_prompt
    return saved


def restore(saved: dict) -> None:
    controller_module._ABOUT_REPORT = saved["about"]
    evidence._report_line = saved["line"]
    profiles.Profile.system_prompt = saved["prompt"]


def base_project(root: Path):
    project = create_project("Weather Study", "research", root=root)
    assets.import_file(project, CSV)
    for name in ("question.md", "findings.md", "sources.md", "analysis.py"):
        shutil.copy(INPUTS / name, project.directory / "src" / name)
    versions = VersionHistory(project)
    versions.start()
    versions.save("ready")
    ran = Toolbox(project).dispatch("run_project", {})
    assert ran.ok and len(ran.made_files) == 3, ran.content
    versions.save("ran")
    return project


def files_of(directory: Path) -> dict[str, str]:
    out = {}
    for path in sorted((directory / "src").rglob("*")):
        if path.is_file():
            out[str(path.relative_to(directory))] = path.read_text(encoding="utf-8",
                                                                    errors="replace")
    return out


def one_turn(base: Path, provider, message: str) -> tuple:
    work = Path(tempfile.mkdtemp(prefix="report-turn-"))
    copy = work / base.name
    shutil.copytree(base, copy)
    project = open_project(copy)
    versions = VersionHistory(project)
    versions.start()
    toolbox = Toolbox(project)
    controller = AgentController(project, provider, toolbox, versions=versions,
                                 fastpath=FastPathRouter())
    # The analysis ran once before the message, as it would have in the Workbench.
    toolbox.dispatch("run_project", {})
    before = files_of(copy)
    started = time.monotonic()
    turn = controller.send(message)
    seconds = time.monotonic() - started
    after = files_of(copy)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    calls = [(name, (result.changed_files or ()), result.ok,
              "took out" if "Open Nest took out" in (result.content or "") else "")
             for name, result in turn.tool_results]
    return project, turn, seconds, before, after, changed, calls


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "report"
    options = dict(arg[2:].split("=", 1) for arg in sys.argv[2:] if arg.startswith("--"))
    model = options.get("model", default_model_id())
    conditions = options.get("conditions", "before,after").split(",")
    groups = options.get("groups", "report,inreport,charts,questions").split(",")
    provider = build_provider(model)
    provider.load()
    root = Path(tempfile.mkdtemp(prefix="report-base-"))
    base = base_project(root).directory
    results = []
    for condition in conditions:
        saved = before_condition() if condition == "before" else None
        try:
            cases = []
            if "report" in groups:
                cases += [("report", m, g, w) for m, g, w in REPORT]
            if "inreport" in groups:
                cases += [("inreport", m, words, "") for m, words in IN_REPORT]
            if "charts" in groups:
                cases += [("charts", m, asked, "") for m, asked in CHARTS]
            if "questions" in groups:
                cases += [("questions", m, None, "") for m in QUESTIONS]
            for group, message, goal, words in cases:
                project, turn, seconds, before, after, changed, calls = one_turn(
                    base, provider, message)
                record = {"condition": condition, "group": group, "message": message,
                          "model": model, "seconds": round(seconds, 1),
                          "route": (turn.fastpath or {}).get("route", "gary"),
                          "recipe": (turn.fastpath or {}).get("recipe"),
                          "calls": calls, "changed": changed, "reply": turn.text}
                if group == "report":
                    layout, notes = layout_of(project.directory)
                    untouched = not any(name.endswith((".py", ".md")) for name in changed)
                    record.update(goal=words, layout=repr(layout), layout_notes=notes,
                                  met=bool(goal(layout)) and untouched and not notes,
                                  only_report_toml=changed == ["src/report.toml"])
                elif group == "inreport":
                    check = Toolbox(project).dispatch("run_project", {})
                    code = after.get("src/analysis.py", "")
                    # Newly there, in a changed analysis: the fixture's own comment already
                    # says "Rain by month", so presence alone passed whatever Gary did
                    # (found on report_fast5; SPIKES.md section 34F scores those by hand).
                    was = before.get("src/analysis.py", "").lower().count(goal.lower())
                    added = code.lower().count(goal.lower()) > was
                    record.update(runs=bool(check.ok), goal_added=added,
                                  report_toml_touched="src/report.toml" in changed,
                                  met=bool(check.ok and added and "src/analysis.py" in changed
                                           and "src/report.toml" not in changed))
                elif group == "charts":
                    check = Toolbox(project).dispatch("run_project", {})
                    code = after.get("src/analysis.py", "")
                    named = sorted(set(re.findall(r"colou?r\s*=\s*['\"]([^'\"]+)['\"]",
                                                  code)) - set(re.findall(
                        r"colou?r\s*=\s*['\"]([^'\"]+)['\"]", before.get("src/analysis.py", ""))))
                    record.update(runs=bool(check.ok), drew=list(check.made_files),
                                  named_colours=named,
                                  took_out=any(c[3] for c in calls),
                                  report_toml_touched="src/report.toml" in changed,
                                  acted=bool(changed),
                                  met=bool(check.ok and check.made_files and changed
                                           and "src/report.toml" not in changed
                                           and (not goal or "green" in code)))
                else:
                    record.update(says_export="export pdf" in (turn.text or "").lower(),
                                  met="export pdf" in (turn.text or "").lower()
                                  and not changed)
                results.append(record)
                mark = "MET " if record.get("met") else "miss"
                print(f"[{condition:6}] {mark} {group:9} {message!r:70.70} "
                      f"{record['route']:>7} {record['seconds']:>5}s changed={changed}",
                      flush=True)
        finally:
            if saved is not None:
                restore(saved)
    out = HERE / "results" / f"{label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    for condition in conditions:
        for group in groups:
            rows = [r for r in results if r["condition"] == condition and r["group"] == group]
            if rows:
                print(f"{condition:6} {group:9} met {sum(r['met'] for r in rows)}/{len(rows)}")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
