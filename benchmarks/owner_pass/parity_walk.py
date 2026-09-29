"""The cross-preset parity pass: the owner-test fixes, checked beyond Games.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 SDL_VIDEODRIVER=dummy \
        .venv/bin/python benchmarks/owner_pass/parity_walk.py [label] [project ...]

The owner's parity list, per preset: build or change it, ask about it, ask how to use
Open Nest for it, and check that the answers come from the project as it is, that no
tool syntax or code reaches the chat, that changed files are marked in the Project panel
and open in Build / Preview when clicked, and that an Undo or a change by hand is noticed
by a plan. Website, Research (with a real CSV), Arduino (compiled with the real toolchain
once a board is chosen), Raspberry Pi, and Blank begun with five different intents.

Same wiring and driving as ``owner_walk.py`` -- the real Workbench, VersionHistory,
memory, the Fast Path and the real model, off the GUI thread -- plus the steps a child
takes with the mouse: adding a data file, choosing a board, clicking a file, changing a
file by hand. Writes ``results/<label>.json``; ``summarise.py`` reads it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from owner_walk import CODE, LEAK, facts_of, pending_plan, wait_idle  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.router import build_provider  # noqa: E402
from opennest.assets import manager as assets  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.memory.manager import MemoryManager  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from opennest.ui.workbench import MARK_ROLE, Workbench  # noqa: E402
from opennest.versioning.checkpoint import VersionHistory  # noqa: E402

INPUTS = HERE.parent / "fastpath" / "inputs"
RUN, UNDO, CLICK, NEXT = "<run>", "<undo>", "<click a changed file>", "<next, if planned>"
UNDO_NEXT = "<undo, then next>"


def data(name: str) -> tuple:
    return ("<add data>", INPUTS / name)


def board(fqbn: str) -> tuple:
    return ("<choose board>", fqbn)


def hand_edit(path: str, old: str, new: str) -> tuple:
    return ("<change a file by hand>", path, old, new)


HELP = ["What did you change?", "How do I save this version?", "Why isn't this working?"]

SCRIPTS = [
    ("Dino Site", "website", None, [
        "What do I do now?",
        "Make me a website about dinosaurs.",
        CLICK, RUN,
        "Add a section about fossils.",
        CLICK,
        "How do I preview this?",
        "Where is the code?",
        "Why didn't that section show up?",
        "make the page have a menu at the top, a gallery with five dinosaur cards, and a "
        "quiz at the bottom",
        NEXT, UNDO_NEXT,
        "How do I undo that?",
        *HELP,
        "What do I do now?",
    ]),
    ("Weather Study", "research", "default", [
        data("weather.csv"),
        "What's in my data?",
        "Graph this.",
        CLICK,
        "Where is my chart?",
        "What changed the most?",
        "What did you actually change?",
        RUN,
        "How do I run this?",
        "How do I undo that?",
        "Why isn't this working?",
        "What do I do now?",
    ]),
    ("Blinky", "arduino", "default", [
        "Make the LED blink.",
        "What pin am I using?",
        "How do I run this?",
        RUN,
        board("arduino:avr:uno"),
        RUN,
        "Did it work on my board?",
        "What does the Send to Board button do?",
        "Where is the code?",
        "make it blink faster",
        CLICK,
        "What do I do next?",
        "How do I save this version?",
    ]),
    ("Robot Car", "raspberry_pi", "default", [
        "Blink an LED.",
        "How do I test this?",
        RUN,
        "What does this project do right now?",
        "Is the light blinking on my Pi?",
        "make it blink 10 times",
        CLICK,
        hand_edit("src/main.py", "LED_PIN = 17", "LED_PIN = 22"),
        "What pin is the LED on?",
        "Where is the code?",
        "What did you change?",
        "What do I do now?",
    ]),
    ("Blank Game", "blank", None, ["Make me a game.", RUN, "How do I run this?"]),
    ("Blank Website", "blank", None, ["Make me a website.", RUN, "How do I see it?"]),
    ("Blank Data", "blank", None, [data("plants.csv"), "Analyze this CSV.", RUN,
                                   "Where is my chart?"]),
    ("Blank Arduino", "blank", None, ["Write an Arduino project.", RUN,
                                      "How do I upload this?"]),
    ("Blank Pi", "blank", None, ["Make a Pi project.", RUN, "How do I test this?"]),
]


def marks(bench) -> list:
    out = []
    for widget in (bench._files, bench._assets):
        for i in range(widget.count()):
            item = widget.item(i)
            out.append(f"{item.text()}{' [' + item.data(MARK_ROLE) + ']' if item.data(MARK_ROLE) else ''}")
    return out


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "parity"
    only = set(sys.argv[2:])
    app = QApplication([])
    provider = build_provider("qwen3-4b-instruct")
    provider.load()
    out = []
    for name, profile, starter, script in SCRIPTS:
        if only and name not in only:
            continue
        root = Path(tempfile.mkdtemp(prefix="parity-"))
        kwargs = {} if starter == "default" else {"starter_id": starter}
        project = create_project(name, profile, root=root, **kwargs)
        versions = VersionHistory(project)
        versions.start()
        controller = AgentController(
            project, provider, Toolbox(project), build_style=project.manifest.build_style,
            versions=versions, memory=MemoryManager.for_provider(project, provider,
                                                                 versions=versions),
            fastpath=FastPathRouter())
        bench = Workbench(project, controller, versions)
        bench.resize(1280, 820)
        bench.show()
        app.processEvents()
        print(f"\n===== {name} ({profile}, starter={starter})", flush=True)
        for step in script:
            before = len(bench._transcript.toPlainText())
            started = time.monotonic()
            shown = step if isinstance(step, str) else step[0]
            record: dict = {"project": name, "step": shown}
            message = None
            if step == NEXT or step == UNDO_NEXT:
                if not pending_plan(controller):
                    record["skipped"] = "no plan waiting"
                    out.append(record)
                    print(f"\n--- {shown}: skipped, no plan waiting", flush=True)
                    continue
                if step == UNDO_NEXT:
                    bench._undo()
                    app.processEvents()
                    record["changed_by"] = "undo"
                message = "next"
            elif isinstance(step, tuple) and step[0] == "<add data>":
                asset = assets.import_file(project, step[1])
                bench.refresh_files()
                controller.refresh_state()
                record.update(kind="setup", added=asset.path)
            elif isinstance(step, tuple) and step[0] == "<choose board>":
                project.manifest.arduino_board = step[1]
                project.save()
                bench._refresh_boards()
                record.update(kind="setup", board=step[1])
            elif isinstance(step, tuple) and step[0] == "<change a file by hand>":
                target = project.directory / step[1]
                target.write_text(target.read_text(encoding="utf-8").replace(step[2], step[3]),
                                  encoding="utf-8")
                bench.refresh_files()
                record.update(kind="setup", hand_edit=f"{step[1]}: {step[2]} -> {step[3]}")
            elif step == CLICK:
                marked = [bench._files.item(i) for i in range(bench._files.count())
                          if bench._files.item(i).data(MARK_ROLE)]
                item = marked[-1] if marked else (bench._files.item(0)
                                                  if bench._files.count() else None)
                if item is None:
                    record.update(kind="click", clicked=None)
                else:
                    bench._open_file(item)
                    app.processEvents()
                    try:
                        text = (project.directory / item.text()).read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        text = None           # a picture: shown as one, not as text
                    record.update(kind="click", clicked=item.text(),
                                  caption=(bench._code_caption.text() if text is not None
                                           else bench._chart_caption.text()),
                                  shows_the_file=(bench._output.toPlainText() == text
                                                  if text is not None
                                                  else not bench._chart.isHidden()),
                                  lines_marked=len(bench._output.extraSelections()),
                                  button=(bench._code_button.text()
                                          if not bench._code_button.isHidden() else ""))
            elif step == RUN:
                bench._run()
                wait_idle(app, bench, 150)
                pause = time.monotonic()
                while time.monotonic() - pause < 2.0:
                    app.processEvents()
                    time.sleep(0.02)
                game = bench._game
                record.update(
                    kind="run",
                    page_visible=bool(bench._web is not None and not bench._web.isHidden()),
                    game_running=bool(game is not None and game.running),
                    chart=(bench._chart_caption.text()
                           if not bench._chart_caption.isHidden() else ""),
                    panel=bench._output.toPlainText()[:400])
                if game is not None and game.running:
                    bench._stop()
                    app.processEvents()
            elif step == UNDO:
                bench._undo()
                app.processEvents()
                record["kind"] = "undo"
            else:
                message = step
            if message is not None:
                finished = []
                real = bench._turn_finished
                bench._turn_finished = lambda turn, real=real: (finished.append(turn),
                                                                real(turn))[1]
                bench._input.setText(message)
                bench._send()
                wait_idle(app, bench)
                bench._turn_finished = real
                turn = finished[0] if finished else None
                fp = (turn.fastpath or {}) if turn else {}
                record.update({
                    "kind": "turn", "message": message,
                    "answered": bool(turn and turn.answered),
                    "route": fp.get("route"), "recipe": fp.get("recipe"),
                    "result": fp.get("result"), "plan": fp.get("plan"),
                    "calls": turn.usage.calls if turn else None,
                    "tools": [(n, r.ok, r.reason) for n, r in turn.tool_results] if turn
                    else [],
                    "changed": sorted({p for _, r in turn.tool_results
                                       for p in r.changed_files}
                                      | set(turn.scaffolded)) if turn else [],
                    "code_caption": (bench._code_caption.text()
                                     if not bench._code_caption.isHidden() else ""),
                })
            record["seconds"] = round(time.monotonic() - started, 1)
            record["chat"] = bench._transcript.toPlainText()[before:].strip()
            record["leaks"] = sorted(set(LEAK.findall(record["chat"])))
            gary = record["chat"].split("Gary:", 1)[-1] if "Gary:" in record["chat"] else ""
            record["code_lines"] = len(CODE.findall(gary))
            record["panel_marks"] = marks(bench)
            record["facts"] = facts_of(project)
            record["plan_waiting"] = pending_plan(controller)
            out.append(record)
            print(f"\n--- {record.get('message') or shown}  ({record['seconds']} s)", flush=True)
            for key in ("answered", "route", "recipe", "result", "plan", "calls", "tools",
                        "changed", "added", "board", "hand_edit", "clicked", "caption",
                        "shows_the_file", "lines_marked", "button", "page_visible",
                        "game_running", "chart", "panel", "leaks", "code_lines",
                        "panel_marks", "plan_waiting", "changed_by"):
                if record.get(key) not in (None, [], "", False):
                    print(f"    {key}: {record[key]}", flush=True)
            print(f"    files: {record['facts']['src']}", flush=True)
            print("    " + record["chat"].replace("\n", "\n    "), flush=True)
        bench.release()
        bench.close()
        shutil.rmtree(root, ignore_errors=True)
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    (results / f"{label}.json").write_text(json.dumps(out, indent=1) + "\n")
    print("\nwritten", results / f"{label}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
