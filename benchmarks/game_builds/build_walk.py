"""Can Gary build the game a child asks for? Eight game builds, one model per run.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/game_builds/build_walk.py <label> [model-id] [thread ...]

The owner's question after test05 (2026-10-04, a Game project on Gary Fast: "create a
simple, block 3D game. Where the world is made by 1 meter square cubes." -- and three
turns later one block the size of the window): can Gary Fast build a usable game at all,
or must a game need Gary Smart or a cloud model? So the same eight builds go through each
model -- a Blank start, an empty Games project, the idea cards, changing the characters,
changing the background, a side-scroller, the owner's own block-3D thread verbatim, and a
first-person walk in space -- each step with what following it would mean written down
before anything ran (``expect``), so a reader grades against that and not against what
came out.

Driven exactly as ``owner_test04/replay.py`` drives the Workbench (it reuses its
``run_step``): VersionHistory, memory, the Fast Path and the Toolbox wired as MainWindow
wires them; a cloud id uses the Keychain's key and gets no Fast Path, as in the app. Not
wrapped in scripts/offline.sh: Seatbelt does not nest.

Keeps the chat, every draft, call, result and correction, the playtests and what the
scene drew, the game's source after each step, and the frames (``results/<label>/``,
ignored: one thread draws the owner's monster picture). Grades nothing.
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
sys.path.insert(0, str(REPO / "benchmarks" / "owner_test04"))

import replay  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from replay import MONSTER, RUN, run_step  # noqa: E402

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.router import build_provider, default_model_id, get_entry  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.memory.manager import MemoryManager  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from opennest.ui.workbench import Workbench  # noqa: E402
from opennest.versioning.checkpoint import VersionHistory  # noqa: E402

#: ``run_step`` names its frames relative to the folder it writes under.
replay.HERE = HERE

STARTER, EMPTY = "default", None

#: name -> (profile, starter, [(step, expect)]). ``expect`` is what following the step
#: means, written before any run; RUN and picture steps expect nothing of Gary.
THREADS = {
    # WORKORDER_01 section 26's own example, in a Blank project.
    "blank_cat": ("blank", EMPTY, [
        ("Make a game where a cat catches falling pizzas.",
         "a game window: a cat (any look) the player moves, pizzas falling, catching one "
         "counts"),
        ("Make the cat move faster and show a score.",
         "the cat's speed raised; a score on screen that goes up on a catch"),
        (RUN, ""),
    ]),
    # The Games card "Space Game" on a project started empty.
    "empty_space": ("games", EMPTY, [
        ("Make a space game",
         "a ship the player flies in a space scene (dark, stars), something to dodge or "
         "shoot"),
        ("add asteroids that I have to dodge",
         "asteroids that move on their own; touching one costs a life or ends the game"),
        (RUN, ""),
    ]),
    # The Games card "Platform Game" on the starter.
    "card_platform": ("games", STARTER, [
        ("Make a platform game",
         "a player that runs and jumps (gravity), ground or platforms to stand on"),
        ("add a gap in the ground that I have to jump over",
         "a gap the player falls into unless they jump it"),
        (RUN, ""),
    ]),
    "characters": ("games", STARTER, [
        ("make my player a blue circle", "the player drawn as a blue circle"),
        (MONSTER, ""),
        ("use my monster picture for the player", "the player is blue_monster.png"),
        ("make the player bigger", "the player's size raised, still the monster picture"),
        ("add a red enemy that chases me",
         "a red enemy that moves toward the player by itself"),
        (RUN, ""),
    ]),
    "backgrounds": ("games", STARTER, [
        ("make the background a night sky with stars", "a dark sky with stars behind"),
        ("add mountains far away behind everything",
         "mountains in the background, behind the player"),
        ("add trees along the ground", "trees standing along the bottom"),
        ("now make it a sunny day instead", "a light day sky replaces the night one"),
        (RUN, ""),
    ]),
    "sidescroll": ("games", STARTER, [
        ("make it a side scrolling game where I run to the right and jump over rocks",
         "the player jumps (Space or Up); rocks come toward the player; the world scrolls"),
        ("the trees and ground should scroll past as I run",
         "scenery moves left past the player"),
        ("add coins to collect and a score", "coins to collect; a score that goes up"),
        (RUN, ""),
    ]),
    # The owner's test05 (2026-10-04, Gary Fast), message for message, typos kept.
    "block3d": ("games", STARTER, [
        ("create a simple, block 3D game. Where the world is made by 1 meter square cubes.",
         "a first-person 3D view of a world built of cubes"),
        ("we should see a sky and ground and landscaper made by these 1 meter blocks.... so "
         "I can use W, S, A and D to navigate forward and around this 3D world. The orange "
         "clock should not be there and we should see a simple pait of hands as the first "
         "person view",
         "sky and ground, a landscape of blocks in perspective; W/S move forward and back, "
         "A/D turn or strafe; no orange square; two hands drawn at the bottom"),
        ("the world should be made of blocks",
         "the landscape is cubes (not one flat rectangle)"),
        (RUN, ""),
    ]),
    # After the block world existed: can each model change one? Not in the first round.
    "block3d_more": ("games", STARTER, [
        ("make a 3D block world game", "the 3D Block World"),
        ("make it night time with stars in the sky",
         "a dark SKY and STARS = True"),
        ("add a tall red tower made of blocks",
         "a new red block kind, several high, placed in WORLD"),
        ("make me walk faster", "WALK_SPEED raised"),
        (RUN, ""),
    ]),
    # The owner's "basic 3D game walking in space".
    "space3d": ("games", STARTER, [
        ("make a 3D game where I walk around in space in first person, with planets and "
         "stars around me",
         "a first-person 3D view: stars and planets drawn in perspective"),
        ("use W A S D to walk and the arrow keys to turn and look around",
         "W/S move, A/D strafe, arrows turn the view; the scene changes with each"),
        (RUN, ""),
    ]),
}


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "builds"
    model = sys.argv[2] if len(sys.argv) > 2 else default_model_id()
    names = sys.argv[3:] or list(THREADS)
    app = QApplication([])
    provider = build_provider(model, allow_cloud=not get_entry(model).info.is_local)
    provider.load()
    out_dir = HERE / "results" / label
    out_dir.mkdir(parents=True, exist_ok=True)
    out: dict = {"model": model, "threads": {}}
    target = HERE / "results" / f"{label}.json"
    for name in names:
        profile, starter, script = THREADS[name]
        root = Path(tempfile.mkdtemp(prefix=f"build-{name}-"))
        project = create_project(name, profile, root=root, model=model,
                                 **({} if starter == STARTER else {"starter_id": None}))
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
        print(f"\n===== {name} ({model}, {profile}, "
              f"{'starter' if starter else 'empty'})", flush=True)
        thread_dir = out_dir / name
        thread_dir.mkdir(exist_ok=True)
        records = []
        started = time.monotonic()
        for index, (step, expect) in enumerate(script):
            record = run_step(project, controller, bench, app, step, thread_dir, index)
            record["expect"] = expect
            records.append(record)
            print(f"\n--- {record['step']}  ({record['seconds']} s)", flush=True)
            if expect:
                print(f"    expect: {expect}", flush=True)
            for key in ("route", "recipe", "provider_calls", "hit_call_limit", "changed",
                        "gave_up", "game_running", "frame", "still", "leaks"):
                if record.get(key) not in (None, [], "", False):
                    print(f"    {key}: {record[key]}", flush=True)
            for entry in record.get("history", []):
                for call in entry.get("calls", []):
                    print(f"    call {call['name']}: "
                          f"{json.dumps(call['arguments'])[:300]}", flush=True)
                if entry["role"] == "tool":
                    print(f"      -> {entry['content'][:200]}", flush=True)
            for test in record.get("playtests", []):
                drew = ", ".join(f"{s['name']}({s['look']})" for s in test["scene"])
                print(f"    playtest {test['verdict']}: {drew}", flush=True)
            print("    " + record["chat"].replace("\n", "\n    ")[:1500], flush=True)
        out["threads"][name] = {"profile": profile, "starter": bool(starter),
                                "seconds": round(time.monotonic() - started, 1),
                                "steps": records}
        target.write_text(json.dumps(out, indent=1) + "\n")
        bench.release()
        bench.close()
        app.processEvents()
        shutil.rmtree(root, ignore_errors=True)
    print("\nwritten", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
