"""The owner's test04, replayed message for message through the real Workbench.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/owner_test04/replay.py <label> [model-id] [test04|maze]

The owner's own live test on 2026-10-02 (a Game project, the local 4B): a greeting, "what
should I do first?", a whole night-forest shooter in one sentence, then their own monster
picture and six tree pictures, added between messages exactly as they were, with the
owner's own words -- typos kept. Wired as MainWindow wires it (VersionHistory, memory,
the Fast Path, the Toolbox) and driven through the Workbench's own ``_send``, ``_add`` and
``_run``. Not wrapped in scripts/offline.sh: Seatbelt does not nest.

The pictures are the owner's, in ``assets/test_builds/`` (not in git), and so are the
frames drawn from them: ``results/<label>/*.png`` is ignored, and the JSON and log -- the
chat, calls, corrections and code -- are what is kept. Point ``TEST04_PICTURES`` elsewhere
to use another copy.

What it keeps, for a reader: the chat as the child saw it; every message the turn added
to Gary's history -- his drafts, every tool call and result, and every correction Open
Nest sent him -- so a reply can be traced to what produced it; the files changed; the
playtest; what the scene drew; the panel's frame at the end. It grades nothing.

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
from opennest.assets import manager as assets  # noqa: E402
from opennest.fastpath.kinds import games  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.graphics import source as scene_source  # noqa: E402
from opennest.memory.manager import MemoryManager  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from opennest.ui.workbench import Workbench  # noqa: E402
from opennest.versioning.checkpoint import VersionHistory  # noqa: E402

PICTURES = Path(os.environ.get("TEST04_PICTURES", REPO / "assets/test_builds"))
RUN = "<run game>"
MONSTER = ("<add>", ["blue_monster.png"])
TREES = ("<add>", [f"tree_0{n}.png" for n in range(1, 7)])

#: The owner's messages, verbatim, with the pictures added where they were added.
TEST04 = [
    "Hi Gary",
    "What should I do first? any ideas for me?",
    "Let's make this a game in the woods at night. A first person shooter. We have to "
    "shoot monsters hiding behind trees. Make this game",
    MONSTER,
    "I added the monster image now. I wills also give you tree images. the player must be "
    "walking forward through the trees and the monster will hide behind the trees.",
    TREES,
    "I added tree images now... this should allow you to make the forest we walk through",
    "your job is to  replace the `shapes` or `drawing` with the correct pictures I added",
    "Gary, whay is a tree moving? You are not making a good game.",
    RUN,
]

#: The owner's next test (2026-10-03, ``Maze_test01``): the "Maze" idea card, their
#: monster picture, and a top-down maze asked for four ways.
MAZE = [
    MONSTER,
    "Make a maze game to find the monster I added",
    "make this a top down view of a maze you create, no road... the player gets coins when "
    "they reach the monster at the end of the maze",
    "create a maze",
    "Gary! you didn't create a real maze. The problem is the monster is just floating in the "
    "sky and there is a random building and road. There needs to be a maze!",
    RUN,
]

THREADS = {"test04": TEST04, "maze": MAZE}

LEAK = re.compile(r"edit_file|write_file|read_file|run_project|game_object|old_text|"
                  r"new_text|<tool_call>|\"name\"\s*:|```|\\n")


def wait_idle(app, bench, timeout=1200) -> None:
    deadline = time.monotonic() + timeout
    while bench._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)


def scene_of(project) -> list[str]:
    source = project.entrypoint_path.read_text(encoding="utf-8")
    facts = games.facts_of(source)
    return scene_source.describe(scene_source.read(source), facts.get("player"))


def messages_since(controller, start: int) -> list[dict]:
    """Everything the turn added to Gary's history: drafts, calls, results, corrections."""
    out = []
    for message in controller.history[start:]:
        entry = {"role": message.role, "content": (message.content or "")[:1500]}
        if message.tool_calls:
            entry["calls"] = [{"name": call.name, "arguments": call.arguments}
                              for call in message.tool_calls]
        out.append(entry)
    return out


def run_step(project, controller, bench, app, step, out_dir: Path, index: int) -> dict:
    record: dict = {"step": step if isinstance(step, str) else f"add {', '.join(step[1])}"}
    before = len(bench._transcript.toPlainText())
    started = time.monotonic()
    if isinstance(step, tuple):
        staging = Path(tempfile.mkdtemp())
        paths = []
        for name in step[1]:
            shutil.copy(PICTURES / name, staging / name)
            paths.append(staging / name)
        bench._ask_what_it_is = lambda source, count=1: "asset"
        bench._add(paths, attach=False)
        # A model that can see looks at them first, on a worker (SPIKES.md section 32).
        wait_idle(app, bench, 300)
        record["kind"] = "asset"
        record["seen"] = {a.path: a.seen for a in assets.list_assets(project) if a.seen}
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
    else:
        finished = []
        real = bench._turn_finished
        bench._turn_finished = lambda turn, real=real: (finished.append(turn), real(turn))[1]
        history_at = len(controller.history)
        raw: list[dict] = []
        settle = controller._settle_history
        # The turn's history is reduced to what the child read before it ends; keep the
        # drafts and corrections first, so a reply can be traced to what produced it.
        controller._settle_history = lambda start, shown, settle=settle: (
            raw.extend(messages_since(controller, start)), settle(start, shown))[1]
        bench._input.setText(step)
        bench._send()
        wait_idle(app, bench)
        bench._turn_finished = real
        controller._settle_history = settle
        turn = finished[0] if finished else None
        fp = (turn.fastpath or {}) if turn else {}
        record.update({
            "kind": "turn",
            "route": fp.get("route"), "recipe": fp.get("recipe"), "result": fp.get("result"),
            "plan": fp.get("plan"),
            "provider_calls": turn.usage.calls if turn else None,
            "hit_call_limit": turn.hit_call_limit if turn else None,
            "history": raw or messages_since(controller, history_at),
            "results": [{"tool": tool, "ok": result.ok, "reason": result.reason,
                         "content": (result.content or "")[:900]}
                        for tool, result in turn.tool_results] if turn else [],
            "changed": sorted({p for _, r in turn.tool_results for p in r.changed_files})
            if turn else [],
            "playtests": [{"verdict": t.verdict, "scene": list(t.scene)}
                          for t in turn.playtests] if turn else [],
            "gave_up": turn.gave_up if turn else None,
        })
        still = project.directory / ".opennest/tmp/playtest.png"
        if turn and turn.playtests and turn.playtests[-1].still and still.is_file():
            path = out_dir / f"{index:02d}_turn.png"
            shutil.copy(still, path)
            record["still"] = str(path.relative_to(HERE))
    record["seconds"] = round(time.monotonic() - started, 1)
    record["chat"] = bench._transcript.toPlainText()[before:].strip()
    gary = record["chat"].split("Gary:", 1)[-1] if "Gary:" in record["chat"] else ""
    record["leaks"] = sorted(set(LEAK.findall(gary)))
    record["scene"] = scene_of(project) if project.entrypoint_path.is_file() else []
    record["source"] = project.entrypoint_path.read_text(encoding="utf-8") \
        if project.entrypoint_path.is_file() else ""
    return record


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "replay"
    # The model that ships (Gary Fast since SPIKES.md section 32); every round before
    # vision_vl4b was Qwen3 4B, named explicitly.
    model = sys.argv[2] if len(sys.argv) > 2 else default_model_id()
    script = THREADS[sys.argv[3] if len(sys.argv) > 3 else "test04"]
    app = QApplication([])
    provider = build_provider(model, allow_cloud=not get_entry(model).info.is_local)
    provider.load()
    out_dir = HERE / "results" / label
    out_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="test04-"))
    project = create_project("test04", "games", root=root)
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
    print(f"\n===== test04 ({model})", flush=True)
    out = []
    for index, step in enumerate(script):
        record = run_step(project, controller, bench, app, step, out_dir, index)
        out.append(record)
        print(f"\n--- {record['step']}  ({record['seconds']} s)", flush=True)
        for key in ("route", "recipe", "result", "plan", "provider_calls", "hit_call_limit",
                    "changed", "gave_up", "game_running", "frame", "still", "leaks", "seen"):
            if record.get(key) not in (None, [], "", False):
                print(f"    {key}: {record[key]}", flush=True)
        for entry in record.get("history", []):
            if entry.get("calls"):
                for call in entry["calls"]:
                    print(f"    call {call['name']}: {json.dumps(call['arguments'])[:400]}",
                          flush=True)
                if entry["content"].strip():
                    print(f"      (with text) {entry['content'][:200]!r}", flush=True)
            elif entry["role"] == "tool":
                print(f"      -> {entry['content'][:300]}", flush=True)
            elif entry["role"] == "user" and entry is not record["history"][0]:
                print(f"    OPEN NEST: {entry['content'][:400]}", flush=True)
            elif entry["role"] == "assistant":
                print(f"    draft: {entry['content'][:400]!r}", flush=True)
        for test in record.get("playtests", []):
            drew = ", ".join(f"{s['name']}({s['look']})" for s in test["scene"])
            print(f"    playtest {test['verdict']}: {drew}", flush=True)
        print("    scene: " + " | ".join(record["scene"]), flush=True)
        print("    " + record["chat"].replace("\n", "\n    "), flush=True)
    (HERE / "results" / f"{label}.json").write_text(json.dumps(out, indent=1) + "\n")
    bench.release()
    bench.close()
    shutil.rmtree(root, ignore_errors=True)
    print("\nwritten", HERE / "results" / f"{label}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
