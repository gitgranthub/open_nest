"""The same primitives, different worlds: does Gary compose them, or does the kit decide?

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/graphics/scenes_walk.py <label> [model-id] [project ...]

Phase 13C's finish line: the graphics layer gives Gary better building blocks; it does not
decide the game for him. Four children ask for four different worlds -- under the sea, in
space, on a farm, a snowy town at night -- in four fresh Game projects, through the real
Workbench exactly as ``eagle_walk.py`` drives it (the Fast Path, VersionHistory, memory and
the Toolbox wired as MainWindow wires them), and Run Game's frame is kept for each.

Nothing was added to the kit or to game_object for any of them: no jellyfish, rocket,
barn or snowman exists anywhere in Open Nest. Whatever is on screen is Gary's choice of
the same twelve generic drawings, the basic shapes, colours, sizes, places, layers and
motions -- or a Fast Path recipe calling the same tool. It grades nothing about looks;
the frames are for a person to judge. Writes ``results/<label>.json`` and
``results/<label>/*.png``.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from eagle_walk import RUN, run_step  # noqa: E402  (sets the offscreen platform first)
from PySide6.QtWidgets import QApplication  # noqa: E402

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.router import build_provider  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.memory.manager import MemoryManager  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from opennest.ui.workbench import Workbench  # noqa: E402
from opennest.versioning.checkpoint import VersionHistory  # noqa: E402

SCRIPTS = {
    "Under the Sea": [
        "Make an underwater game where I swim around as a fish and avoid jellyfish.",
        "Make it look like the deep sea: dark blue water, sand on the bottom, green "
        "seaweed and bubbles floating up.",
        RUN,
    ],
    "Space Run": [
        "Make a space game where I fly a rocket and dodge asteroids.",
        "Make the background a black sky full of little stars, with a big purple planet.",
        RUN,
    ],
    "Apple Farm": [
        "Make a farm game where I walk around and collect apples.",
        "Give it a sunny blue sky, green grass along the bottom, a red barn and some "
        "trees.",
        RUN,
    ],
    "Snowy Night": [
        "Make a game where I drive a little car around a town at night.",
        "Make it a snowy night: a dark sky, white snow on the ground, houses with lit "
        "windows and a big yellow moon.",
        RUN,
    ],
    # A Blank ("Something Else") project whose files have become the Basic Game: offered
    # game_object since SPIKES.md section 28L. It has no headless test, so nothing here
    # is checked but what Run Game shows.
    "Blank Garden": [
        "Make it a sunny day in a garden: a blue sky, green grass along the bottom, a "
        "tree and some clouds.",
        RUN,
    ],
}

#: Projects made as Blank, with the Basic Game as their src/main.py.
BLANK = {"Blank Garden"}
STARTER = HERE.parents[1] / "opennest/projects/starters/pygame_basic/game.py"


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "scenes"
    model = sys.argv[2] if len(sys.argv) > 2 else "qwen3-4b-instruct"
    only = set(sys.argv[3:])
    app = QApplication.instance() or QApplication([])
    provider = build_provider(model, allow_cloud=model not in (
        "qwen3-4b-instruct", "qwen3-8b"))
    provider.load()
    out_dir = HERE / "results" / label
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for name, script in SCRIPTS.items():
        if only and name not in only:
            continue
        root = Path(tempfile.mkdtemp(prefix="scenes-"))
        project = create_project(name, "blank" if name in BLANK else "games", root=root)
        if name in BLANK:
            project.entrypoint_path.parent.mkdir(parents=True, exist_ok=True)
            project.entrypoint_path.write_text(STARTER.read_text(encoding="utf-8"))
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
        started = time.monotonic()
        for index, step in enumerate(script):
            record = run_step(project, controller, bench, app, step, out_dir,
                              len(out) + index)
            record["project"] = name
            out.append(record)
            print(f"\n--- {step}  ({record['seconds']} s)", flush=True)
            for key in ("route", "recipe", "result", "changed", "frame", "leaks",
                        "code_lines"):
                if record.get(key) not in (None, [], ""):
                    print(f"    {key}: {record[key]}", flush=True)
            for call in record.get("tool_calls", []):
                print(f"    call {call['name']}: {json.dumps(call['arguments'])[:300]}",
                      flush=True)
                print(f"      -> {call['result'][:160]}", flush=True)
            print("    scene: " + " | ".join(record["scene"]), flush=True)
            print("    " + record["chat"][-600:].replace("\n", "\n    "), flush=True)
        print(f"({round(time.monotonic() - started)} s for {name})", flush=True)
        bench.release()
        bench.close()
        shutil.rmtree(root, ignore_errors=True)
    (HERE / "results" / f"{label}.json").write_text(json.dumps(out, indent=1) + "\n")
    print("\nwritten", HERE / "results" / f"{label}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
