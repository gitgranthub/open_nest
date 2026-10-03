"""The owner's eagle game, asked for the way the work order asks for it, through the real app.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/graphics/eagle_walk.py <label> [model-id] [project ...]

Phase 13C's acceptance run (PHASE_13C work order sections 18-20). A Game project with the
owner's eagle picture in Assets -- the real brand eagle, 128x128 with transparency -- and
the work order's own sequence of requests, each sent through the Workbench's own ``_send``
with the Fast Path, VersionHistory, memory and the Toolbox wired as MainWindow wires them;
then Run Game in the panel, the other scenarios, an Undo, and Run Game again. A second
project attaches the picture to "Use this image for the player." as a drop onto the chat
would.

For every step it keeps what a reader needs to judge it: the chat as the child saw it,
every tool call Gary made with its arguments and result, the playtest's verdict and what
the scene said it drew, the still the test took and the frame the panel showed, and
whether the chat carried code or tool syntax. It grades nothing about looks; the pictures
are for a person to look at. ``model-id`` defaults to the local 4B; a cloud id
(claude-sonnet, claude-haiku, openai-gpt) uses the Keychain's key and the network.

Writes ``results/<label>.json`` and ``results/<label>/*.png``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.router import build_provider, default_model_id, get_entry  # noqa: E402
from opennest.fastpath.kinds import games  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.graphics import source as scene_source  # noqa: E402
from opennest.memory.manager import MemoryManager  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from opennest.ui.workbench import Workbench  # noqa: E402
from opennest.versioning.checkpoint import VersionHistory  # noqa: E402

EAGLE = REPO / "assets/open_nest_asset_delivery/03_eagle_animation/frames_128/eagle_01.png"
RUN, UNDO, ADD, ATTACH = "<run game>", "<undo>", "<add eagle.png>", "<attach eagle.png>"

SCRIPTS = {
    "Eagle Town": [
        ADD,
        "Make a game where I fly an eagle over a town and avoid cars.",
        "Use my eagle picture as the player.",
        "Make the cars look like cars.",
        "Build out the background into a little town with a sky and road. Make it feel "
        "like a clean modern mobile game.",
        RUN,
        "Add three cars to the road.",
        "Add buildings and clouds in the background.",
        "Put coins along the road.",
        "Make everything look more colorful and friendly.",
        RUN,
        UNDO,
        RUN,
    ],
    "Picture Swap": [
        ATTACH,
        "Use this image for the player.",
        RUN,
    ],
}

LEAK = re.compile(r"edit_file|write_file|read_file|run_project|game_object|old_text|"
                  r"new_text|<tool_call>|\"name\"\s*:|```|\\n")
CODE = re.compile(r"^\s*(?:[A-Za-z_][\w.]*\s*[-+]?=\s*\S|pygame\.\w|scene\.\w|def |"
                  r"for .* in |while .*:|if .*:\s*$|import \w)", re.MULTILINE)


def wait_idle(app, bench, timeout=900) -> None:
    deadline = time.monotonic() + timeout
    while bench._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


def scene_of(project) -> list[str]:
    source = project.entrypoint_path.read_text(encoding="utf-8")
    facts = games.facts_of(source)
    return scene_source.describe(scene_source.read(source), facts.get("player"))


def calls_since(controller, start: int) -> list[dict]:
    """Every tool call in the history since ``start``, with what it returned."""
    # Paired in order: each reply's calls are followed by their results, and a model's
    # call ids repeat from one reply to the next ("call_0" every time).
    found, waiting = [], []
    for message in controller.history[start:]:
        for call in message.tool_calls:
            arguments = call.arguments
            if isinstance(arguments, dict) and "new_text" in arguments:
                arguments = {**arguments, "new_text": arguments["new_text"][:400]}
            record = {"name": call.name, "arguments": arguments, "result": ""}
            found.append(record)
            waiting.append(record)
        if message.role == "tool" and waiting:
            waiting.pop(0)["result"] = (message.content or "")[:700]
    return found


def run_step(project, controller, bench, app, step: str, out_dir: Path, index: int) -> dict:
    record: dict = {"step": step}
    before = len(bench._transcript.toPlainText())
    started = time.monotonic()
    if step in (ADD, ATTACH):
        picture = Path(tempfile.mkdtemp()) / "eagle.png"
        shutil.copy(EAGLE, picture)
        bench._ask_what_it_is = lambda source: "asset"
        bench._add([picture], attach=step == ATTACH)
        record["kind"] = "asset"
    elif step == RUN:
        bench._run()
        wait_idle(app, bench, 60)
        shown = time.monotonic()
        while time.monotonic() - shown < 2.5:
            app.processEvents()
            time.sleep(0.02)
        game = bench._game
        frame = game.current_frame() if game is not None else None
        record.update({"kind": "run", "game_running": bool(game is not None and game.running),
                       "panel": bench._output.toPlainText()[:300]})
        if frame is not None:
            image = QImage(frame.data, frame.width, frame.height, frame.width * 4,
                           QImage.Format.Format_RGB32)
            path = out_dir / f"{index:02d}_run.png"
            image.save(str(path))
            record["frame"] = str(path.relative_to(HERE))
        bench._stop()
        app.processEvents()
    elif step == UNDO:
        bench._undo()
        app.processEvents()
        record["kind"] = "undo"
    else:
        finished = []
        real = bench._turn_finished
        bench._turn_finished = lambda turn, real=real: (finished.append(turn), real(turn))[1]
        history_at = len(controller.history)
        bench._input.setText(step)
        bench._send()
        wait_idle(app, bench)
        bench._turn_finished = real
        turn = finished[0] if finished else None
        fp = (turn.fastpath or {}) if turn else {}
        record.update({
            "kind": "turn",
            "route": fp.get("route"), "recipe": fp.get("recipe"), "result": fp.get("result"),
            "plan": fp.get("plan"),
            "provider_calls": turn.usage.calls if turn else None,
            "tool_calls": calls_since(controller, history_at),
            "changed": sorted({p for _, r in turn.tool_results for p in r.changed_files})
            if turn else [],
            "playtests": [{"verdict": t.verdict, "scene": list(t.scene)}
                          for t in turn.playtests] if turn else [],
            "gave_up": turn.gave_up if turn else None,
        })
        still = project.directory / ".opennest/tmp/playtest.png"
        if turn and turn.playtests and turn.playtests[-1].still and still.is_file():
            path = out_dir / f"{index:02d}_{slug(step)}.png"
            shutil.copy(still, path)
            record["still"] = str(path.relative_to(HERE))
    record["seconds"] = round(time.monotonic() - started, 1)
    record["chat"] = bench._transcript.toPlainText()[before:].strip()
    gary = record["chat"].split("Gary:", 1)[-1] if "Gary:" in record["chat"] else ""
    record["leaks"] = sorted(set(LEAK.findall(gary)))
    record["code_lines"] = len(CODE.findall(gary))
    record["scene"] = scene_of(project) if project.entrypoint_path.is_file() else []
    record["source"] = project.entrypoint_path.read_text(encoding="utf-8") \
        if project.entrypoint_path.is_file() else ""
    return record


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "eagle_walk"
    model = sys.argv[2] if len(sys.argv) > 2 else default_model_id()
    only = set(sys.argv[3:])
    app = QApplication([])
    provider = build_provider(model, allow_cloud=not get_entry(model).info.is_local)
    provider.load()
    out_dir = HERE / "results" / label
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for name, script in SCRIPTS.items():
        if only and name not in only:
            continue
        root = Path(tempfile.mkdtemp(prefix="eagle-"))
        project = create_project(name, "games", root=root)
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
        print(f"\n===== {name} ({model})", flush=True)
        for index, step in enumerate(script):
            record = run_step(project, controller, bench, app, step, out_dir,
                              len(out) + index)
            record["project"] = name
            out.append(record)
            print(f"\n--- {step}  ({record['seconds']} s)", flush=True)
            for key in ("route", "recipe", "result", "plan", "provider_calls", "changed",
                        "gave_up", "game_running", "frame", "still", "leaks", "code_lines"):
                if record.get(key) not in (None, [], ""):
                    print(f"    {key}: {record[key]}", flush=True)
            for call in record.get("tool_calls", []):
                print(f"    call {call['name']}: {json.dumps(call['arguments'])[:300]}",
                      flush=True)
                print(f"      -> {call['result'][:200]}", flush=True)
            for test in record.get("playtests", []):
                drew = ", ".join(f"{s['name']}({s['look']})" for s in test["scene"])
                print(f"    playtest {test['verdict']}: {drew}", flush=True)
            print("    scene: " + " | ".join(record["scene"]), flush=True)
            print("    " + record["chat"].replace("\n", "\n    "), flush=True)
        bench.release()
        bench.close()
        shutil.rmtree(root, ignore_errors=True)
    (HERE / "results" / f"{label}.json").write_text(json.dumps(out, indent=1) + "\n")
    print("\nwritten", HERE / "results" / f"{label}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
