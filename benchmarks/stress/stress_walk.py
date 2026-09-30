"""The cross-preset stress pass: one interaction model, every preset, four models.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 SDL_VIDEODRIVER=dummy \
        .venv/bin/python benchmarks/stress/stress_walk.py <label> [model-id] [project ...]

After Phase 13C: the same three kinds of message -- a build or change request, a question
about the project, a question about how to use Open Nest -- in Website, Research, Arduino,
Raspberry Pi and Blank begun five ways, driven through the real Workbench exactly as
``owner_pass/parity_walk.py`` drives it (VersionHistory, memory, the Fast Path and the
Toolbox wired as MainWindow wires them), plus the mouse steps a child takes: adding a data
file, choosing a board, clicking a changed file, pressing Run / Preview / Compile, Undo,
changing a file by hand.

``model-id`` defaults to the local 4B; a cloud id (openai-gpt, claude-sonnet) uses the
Keychain's key and the network, and -- as in the app -- gets no Fast Path, because only
a local model can score its closed questions.

For every step it keeps what a reader needs to check Gary against: the chat as the child
saw it, the tools the turn was offered, every call with its arguments and result, what
changed, what the Fast Path did, the provider's token counts, and the project's own files
afterwards. It grades nothing; ``summarise.py`` lays it out. Writes
``results/<label>.json``.
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
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "benchmarks" / "owner_pass"))
sys.path.insert(0, str(REPO / "benchmarks" / "graphics"))

from eagle_walk import calls_since  # noqa: E402
from owner_walk import CODE, LEAK, pending_plan, wait_idle  # noqa: E402
from parity_walk import marks  # noqa: E402
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

INPUTS = HERE / "inputs"
LOCAL = ("qwen3-4b-instruct", "qwen3-8b")
RUN, UNDO, CLICK = "<run>", "<undo>", "<click a changed file>"


def data(name: str) -> tuple:
    return ("<add data>", INPUTS / name)


def board(fqbn: str) -> tuple:
    return ("<choose board>", fqbn)


def hand_edit(path: str, old: str, new: str) -> tuple:
    return ("<change a file by hand>", path, old, new)


#: (name, profile, starter, steps). Natural child wording, not recipe phrasings.
SCRIPTS = [
    ("Dino Site", "website", None, [
        "Make me a website about dinosaurs.",
        CLICK, RUN,
        "Add a section about fossils.",
        "Make the header feel brighter and more fun.",
        "How do I preview this?",
        "Where is the code?",
        "Why didn't that section show up?",
        "add a button that says Roar and put three fun facts in the fossils part",
        UNDO,
        "What do I do now?",
    ]),
    ("Garden Growth", "research", "default", [
        data("garden.csv"),
        "What is in my data?",
        "Graph this.",
        CLICK,
        "Tell me what changed the most.",
        "Add a chart and explain the biggest change.",
        "Where is my chart?",
        "What did you actually change?",
        "What do I do now?",
    ]),
    ("Blinky", "arduino", "default", [
        "Make the LED blink.",
        board("arduino:avr:uno"),
        RUN,
        "Make it blink faster.",
        "What pin am I using?",
        "How do I run or upload this?",
        "What does the Send to Board button do?",
        "Where is the code?",
        UNDO,
        "What do I do next?",
    ]),
    ("Pi Light", "raspberry_pi", "default", [
        "Blink an LED.",
        "Make it stay on for two seconds.",
        RUN,
        "How do I test this?",
        "What does this project do right now?",
        "Is the light on my Pi blinking?",
        hand_edit("src/main.py", "LED_PIN = 17", "LED_PIN = 27"),
        "Where is the code?",
        "What do I do now?",
    ]),
    ("Blank Site", "blank", None, ["What do I do now?", "Make me a simple website.",
                                   "What do I do now?"]),
    ("Blank Data", "blank", None, [data("garden.csv"), "Analyze this CSV.", RUN,
                                   "Where is my chart?"]),
    ("Blank Sketch", "blank", None, ["Make an Arduino project that blinks an LED.",
                                     "What do I do now?"]),
    ("Blank Pi", "blank", None, ["Make a Raspberry Pi project.", RUN, "How do I test this?"]),
    ("Blank Game", "blank", None, ["Make a game.", "Add some cars that I have to dodge.",
                                   RUN, "What do I do now?"]),
]


def snapshot(project) -> dict[str, str]:
    """Every small text file in the project that is the child's, and every picture."""
    found = {}
    for path in sorted(project.directory.rglob("*")):
        relative = path.relative_to(project.directory)
        if not path.is_file() or relative.parts[0] in (".git", ".opennest") or \
                relative.name == "scene.py":
            continue
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif"):
            found[str(relative)] = f"<picture, {path.stat().st_size} bytes>"
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if len(text) < 20000:
            found[str(relative)] = text
    return found


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "stress"
    model = sys.argv[2] if len(sys.argv) > 2 else "qwen3-4b-instruct"
    only = set(sys.argv[3:])
    app = QApplication([])
    provider = build_provider(model, allow_cloud=model not in LOCAL)
    provider.load()
    # Every reply the model gave, before any correction replaced it: the settled history
    # keeps only what the child was told, so this is the one place the raw words survive.
    raw: list[str] = []
    finish = provider.finish

    def recorded():
        reply = finish()
        raw.append((reply.text or "")[:800] + "".join(
            f" [call {call.name}]" for call in reply.tool_calls))
        return reply

    provider.finish = recorded
    out = []
    for name, profile, starter, script in SCRIPTS:
        if only and name not in only:
            continue
        root = Path(tempfile.mkdtemp(prefix="stress-"))
        kwargs = {} if starter == "default" else {"starter_id": starter}
        project = create_project(name, profile, root=root, **kwargs)
        versions = VersionHistory(project)
        versions.start()
        toolbox = Toolbox(project)
        controller = AgentController(
            project, provider, toolbox, build_style=project.manifest.build_style,
            versions=versions, memory=MemoryManager.for_provider(project, provider,
                                                                 versions=versions),
            fastpath=FastPathRouter())
        bench = Workbench(project, controller, versions)
        bench.resize(1280, 820)
        bench.show()
        app.processEvents()
        print(f"\n===== {name} ({profile}, starter={starter}, {model})", flush=True)
        for step in script:
            before = len(bench._transcript.toPlainText())
            started = time.monotonic()
            shown = step if isinstance(step, str) else step[0]
            record: dict = {"project": name, "profile": profile, "model": model,
                            "step": shown}
            message = None
            if isinstance(step, tuple) and step[0] == "<add data>":
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
                                  lines_marked=len(bench._output.extraSelections()))
            elif step == RUN:
                bench._run()
                wait_idle(app, bench, 150)
                pause = time.monotonic()
                while time.monotonic() - pause < 2.0:
                    app.processEvents()
                    time.sleep(0.02)
                game = bench._game
                record.update(
                    kind="run", button=bench._run_button.text(),
                    page_visible=bool(bench._web is not None and not bench._web.isHidden()),
                    game_running=bool(game is not None and game.running),
                    chart=(bench._chart_caption.text()
                           if not bench._chart_caption.isHidden() else ""),
                    panel=bench._output.toPlainText()[:500])
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
                offered = list(toolbox.allowed)
                history_at = len(controller.history)
                raw.clear()
                bench._input.setText(message)
                bench._send()
                wait_idle(app, bench)
                bench._turn_finished = real
                turn = finished[0] if finished else None
                fp = (turn.fastpath or {}) if turn else {}
                usage = turn.usage if turn else None
                record.update({
                    "kind": "turn", "message": message, "offered": offered,
                    "answered": bool(turn and turn.answered),
                    "route": fp.get("route"), "recipe": fp.get("recipe"),
                    "result": fp.get("result"), "plan": fp.get("plan"),
                    "calls": usage.calls if usage else None,
                    "input_tokens": usage.input_tokens if usage else 0,
                    "output_tokens": usage.output_tokens if usage else 0,
                    "tools": [(n, r.ok, r.reason) for n, r in turn.tool_results] if turn
                    else [],
                    "tool_calls": calls_since(controller, history_at),
                    "changed": sorted({p for _, r in turn.tool_results
                                       for p in r.changed_files}
                                      | set(turn.scaffolded)) if turn else [],
                    "gave_up": turn.gave_up if turn else None,
                    "playtests": [t.verdict for t in turn.playtests] if turn else [],
                    "raw_replies": list(raw),
                })
            record["seconds"] = round(time.monotonic() - started, 1)
            record["chat"] = bench._transcript.toPlainText()[before:].strip()
            gary = record["chat"].split("Gary:", 1)[-1] if "Gary:" in record["chat"] else ""
            record["leaks"] = sorted(set(LEAK.findall(gary)))
            record["code_lines"] = len(CODE.findall(gary))
            record["panel_marks"] = marks(bench)
            record["files"] = snapshot(project)
            record["plan_waiting"] = pending_plan(controller)
            out.append(record)
            print(f"\n--- {record.get('message') or shown}  ({record['seconds']} s)", flush=True)
            for key in ("offered", "answered", "route", "recipe", "result", "plan", "calls",
                        "input_tokens", "output_tokens", "tools", "changed", "playtests",
                        "gave_up", "added", "board", "hand_edit", "clicked", "caption",
                        "shows_the_file", "lines_marked", "button", "page_visible",
                        "game_running", "chart", "panel", "leaks", "code_lines",
                        "panel_marks", "plan_waiting"):
                if record.get(key) not in (None, [], "", False, 0):
                    print(f"    {key}: {record[key]}", flush=True)
            for call in record.get("tool_calls", []):
                print(f"    call {call['name']}: {json.dumps(call['arguments'])[:240]}",
                      flush=True)
                print(f"      -> {call['result'][:200]}", flush=True)
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
