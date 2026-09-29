"""The owner's first real test, replayed: the real Workbench, the real model, real games.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/owner_pass/owner_walk.py [label]

The owner's own sequence (the Phase 13 owner-test pass): create a Game project, ask for a
game with no hidden prerequisites, see what changed, run it in the panel, check that what
Gary says matches the files, ask how to play and what to do now, make a request big
enough to be planned, say "next", change the project between steps, and see the next
step start from the project as it is. Three projects: the owner's actual state (a Game
project begun with Start Empty, the first message the owner's own words), a Game project
with its default starter, and a Blank project asked for a game.

Wired as MainWindow wires it -- VersionHistory, memory, the Fast Path, the Toolbox -- and
driven through the Workbench's own handlers (``_send``, ``_run``, ``_undo``,
``_add_starter``) off the GUI thread. Not wrapped in scripts/offline.sh: Seatbelt does
not nest, and the games run under the product's own sandbox.

Writes ``results/<label>.json``. What it records is evidence for a reader: the chat each
step added, the files that changed, what the game file actually contains, whether the
chat carries tool syntax, and what the panel shows. It grades nothing about intent.
"""

from __future__ import annotations

import hashlib
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
REPO = Path(os.environ.get("OPENNEST_SOURCE", HERE.parents[1]))
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication  # noqa: E402

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.router import build_provider  # noqa: E402
from opennest.fastpath.kinds import games  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.memory.manager import MemoryManager  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from opennest.ui.workbench import Workbench  # noqa: E402
from opennest.versioning.checkpoint import VersionHistory  # noqa: E402

RUN = "<run game>"
UNDO = "<undo>"
STARTER = "<add basic game>"
NEXT_IF_PLANNED = "<next, if a plan is waiting>"
CHANGE_THEN_NEXT = "<undo, then next>"
HAND_EDIT_THEN_NEXT = "<change a file by hand, then next>"

OWNER_FIRST = ("Hi Gary. build a game that s an eagle flying over cars parked in a "
               "dealership. the dealership is called Trent Motors. The goal is to fly the "
               "eagle back and forth and try to poop on the cars below.")

SCRIPTS = [
    # The owner's actual state: a Game project begun with Start Empty.
    ("Trent Motors", "games", None, [
        OWNER_FIRST,
        RUN,
        "everything ok? what do i do now",
        "how do I play this?",
        NEXT_IF_PLANNED,
        "there is no eagle. just an Orange square on black. try to add the esgle again",
        RUN,
        "make the eagle drop poop when I press space, put five cars parked along the "
        "bottom, and give me a point every time the poop lands on a car",
        NEXT_IF_PLANNED,
        CHANGE_THEN_NEXT,
    ]),
    # A Game project as the dialog begins one by default.
    ("Eagle Dealership", "games", "default", [
        "make me a game where an eagle flies over cars",
        RUN,
        "how do I play this?",
        "what are the controls?",
        "what do I do now?",
        NEXT_IF_PLANNED,                  # step 1, if a plan was offered
        CHANGE_THEN_NEXT,                 # Undo that step, then "next": re-checked?
        HAND_EDIT_THEN_NEXT,              # the files change by hand, then "next"
        "where is the code?",
        "how do I undo that?",
        RUN,
    ]),
    # Blank stays blank until the child says what it is.
    ("Blank Eagle", "blank", None, [
        "what do I do now?",
        "make me a game where an eagle flies over cars",
        RUN,
        "how do I play it?",
    ]),
    # The same experience in a Website project, begun with Start Empty.
    ("Dog Club", "website", None, [
        "what do I do now?",
        "make me a page about my dog Biscuit",
        RUN,
        "how do I see my page?",
        "where is the code?",
        "make the background dark blue, add a section with photos of Biscuit, and put a "
        "footer that says made by maya",
        NEXT_IF_PLANNED,
        CHANGE_THEN_NEXT,
        "how do I undo that?",
        "how do I publish this?",
    ]),
    # Research and a Raspberry Pi project as the dialog begins them: questions only.
    ("Plant Study", "research", "default", [
        "what do I do now?",
        "how do I run it?",
        "where did my chart go?",
    ]),
    ("Robot Car", "raspberry_pi", "default", [
        "what do I do now?",
        "how do I test it without a raspberry pi?",
    ]),
]

#: Tool protocol or generated code on its way to the child.
LEAK = re.compile(r"edit_file|write_file|read_file|run_project|old_text|new_text|"
                  r"<tool_call>|\"name\"\s*:|```|\\n")
#: A line of code in the chat: an assignment, a pygame call, a Python statement.
CODE = re.compile(r"^\s*(?:[A-Za-z_][\w.]*\s*[-+]?=\s*\S|pygame\.\w|def |for .* in |"
                  r"while .*:|if .*:\s*$|import \w)", re.MULTILINE)


def facts_of(project) -> dict:
    entry = project.entrypoint_path
    source = entry.read_text(encoding="utf-8") if entry.is_file() else ""
    record = {"entry_exists": entry.is_file(),
              "sha": hashlib.sha256(source.encode()).hexdigest()[:10] if source else "",
              "lines": source.count("\n"),
              "src": sorted(str(p.relative_to(project.directory))
                            for p in (project.directory / "src").rglob("*") if p.is_file())}
    record["source"] = source
    if project.profile.id == "games" or "pygame" in source:
        facts = games.facts(project)
        record["brief"] = games.brief(facts)
        record["things"] = sorted(facts.get("things") or {})
        record["eagle_in_code"] = "eagle" in source.lower()
        record["keys_in_code"] = sorted(set(re.findall(r"K_[A-Za-z0-9_]+", source)))
    return record


def wait_idle(app, bench, timeout=600) -> None:
    deadline = time.monotonic() + timeout
    while bench._thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)


def pending_plan(controller) -> list:
    plan = getattr(controller, "_plan", None)
    if plan is not None:
        return [f"{s.status}: {s.text}" for s in plan.steps]
    return list(getattr(controller, "_pending", []) or [])


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "owner_walk"
    only = set(sys.argv[2:])
    app = QApplication([])
    provider = build_provider("qwen3-4b-instruct")
    provider.load()
    out = []
    for name, profile, starter, script in SCRIPTS:
        if only and name not in only:
            continue
        root = Path(tempfile.mkdtemp(prefix="owner-"))
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
        print(f"    files at start: {facts_of(project)['src']}", flush=True)
        for step in script:
            message = step
            before = len(bench._transcript.toPlainText())
            started = time.monotonic()
            record: dict = {"project": name, "step": step}
            if step == NEXT_IF_PLANNED:
                if not pending_plan(controller):
                    record["skipped"] = "no plan waiting"
                    out.append(record)
                    print(f"\n--- {step}: skipped, no plan waiting", flush=True)
                    continue
                message = "next"
            if step == CHANGE_THEN_NEXT:
                if not pending_plan(controller):
                    record["skipped"] = "no plan waiting"
                    out.append(record)
                    print(f"\n--- {step}: skipped, no plan waiting", flush=True)
                    continue
                bench._undo()
                app.processEvents()
                record["changed_by"] = "undo"
                message = "next"
            if step == HAND_EDIT_THEN_NEXT:
                if not pending_plan(controller):
                    record["skipped"] = "no plan waiting"
                    out.append(record)
                    print(f"\n--- {step}: skipped, no plan waiting", flush=True)
                    continue
                game = project.entrypoint_path
                game.write_text(game.read_text(encoding="utf-8").replace(
                    "BACKGROUND = (18, 22, 34)", "BACKGROUND = (40, 90, 60)"),
                    encoding="utf-8")
                record["changed_by"] = "hand edit of BACKGROUND"
                message = "next"
            if step == RUN:
                bench._run()
                wait_idle(app, bench, 60)
                shown = time.monotonic()
                while time.monotonic() - shown < 2.0:
                    app.processEvents()
                    time.sleep(0.02)
                game = bench._game
                record.update({
                    "kind": "run",
                    "page_visible": bool(bench._web is not None and not bench._web.isHidden()),
                    "game_running": bool(game is not None and game.running),
                    "game_visible": bool(game is not None and not game.isHidden()),
                    "frame": (lambda f: [f.width, f.height] if f else None)(
                        game.current_frame() if game is not None else None),
                    "panel": bench._output.toPlainText()[:300],
                    "caption": bench._game_title.text() if game is not None else "",
                })
                bench._stop()
                app.processEvents()
            elif step == UNDO:
                bench._undo()
                app.processEvents()
                record["kind"] = "undo"
            elif step == STARTER:
                bench._add_starter("pygame_basic")
                app.processEvents()
                record["kind"] = "starter"
            else:
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
                    "route": fp.get("route"), "recipe": fp.get("recipe"),
                    "result": fp.get("result"), "plan": fp.get("plan"),
                    "calls": turn.usage.calls if turn else None,
                    "tools": [(n, r.ok, r.reason) for n, r in turn.tool_results] if turn
                    else [],
                    "changed": sorted({p for _, r in turn.tool_results
                                       for p in r.changed_files}) if turn else [],
                    "playtests": [t.verdict for t in turn.playtests] if turn else [],
                    "code_caption": (bench._code_caption.text()
                                     if not bench._code_caption.isHidden() else ""),
                    "files_panel": [bench._files.item(i).text()
                                    for i in range(bench._files.count())],
                })
            record["seconds"] = round(time.monotonic() - started, 1)
            record["chat"] = bench._transcript.toPlainText()[before:].strip()
            record["leaks"] = sorted(set(LEAK.findall(record["chat"])))
            gary = record["chat"].split("Gary:", 1)[-1] if "Gary:" in record["chat"] else ""
            record["code_lines"] = len(CODE.findall(gary))
            record["repeated"] = len(gary) - len(set(p.strip() for p in gary.split("\n\n")))
            record["facts"] = facts_of(project)
            record["plan_waiting"] = pending_plan(controller)
            out.append(record)
            print(f"\n--- {step if step != message else message}  ({record['seconds']} s)",
                  flush=True)
            for key in ("route", "recipe", "result", "plan", "calls", "tools", "changed",
                        "playtests", "code_caption", "files_panel", "game_running",
                        "game_visible", "page_visible", "frame", "panel", "caption", "leaks",
                        "code_lines",
                        "plan_waiting", "changed_by"):
                if record.get(key) not in (None, [], ""):
                    print(f"    {key}: {record[key]}", flush=True)
            print(f"    facts: { {k: v for k, v in record['facts'].items() if k != 'source'} }",
                  flush=True)
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
