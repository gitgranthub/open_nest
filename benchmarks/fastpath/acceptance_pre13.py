"""The pre-13 owner acceptance run: natural wording, the real Workbench, the real model.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/fastpath/acceptance_pre13.py

The question is not "did the classifier pick the right label" but whether a child can
talk to Gary naturally and get a working result: a game built over several turns, a
picture described in their own words, a two-change request, a creative request that
reaches Gary, a request too big for one go, a website change, and Undo after both a
recipe's change and Gary's. Wired as MainWindow wires it -- VersionHistory, the Fast Path,
the Toolbox -- and driven through ``Workbench._send`` and the Undo button's handler, off
the GUI thread, so the chat steps, the code panel and the still frame are all exercised.

The wording is the developer's, not a benchmark's, and was written before the run.
Writes ``results/pre13_acceptance.json``.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication  # noqa: E402

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.router import build_provider, default_model_id  # noqa: E402
from opennest.assets import manager as assets  # noqa: E402
from opennest.fastpath.kinds import games, website  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.memory.manager import MemoryManager  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from opennest.ui.workbench import Workbench  # noqa: E402
from opennest.versioning.checkpoint import VersionHistory  # noqa: E402

UNDO = "<undo>"

#: (project, profile, [(message, attach a picture?)]) -- natural wording, several turns.
SCRIPTS = [
    ("Eagle Flight", "games", [
        ("i want a game where i'm flying around and have to dodge cars", False),
        ("use this as my eagle", True),
        ("the cars are too slow, speed them up and give me a score", False),
        ("make the cars act nervous, like they're scared of me", False),
        (UNDO, False),                       # after Gary's change
        ("make the cars bigger", False),
        (UNDO, False),                       # after a recipe's change
    ]),
    ("Parking Lot", "games", [
        ("make an isometric game where an eagle flies over a parking lot and poops on the "
         "cars", False),
        ("next", False),
    ]),
    ("Maya Site", "website", [
        ("can the bottom of the page say made by maya", False),
        ("and make the background a sunset orange", False),
    ]),
]


def png(width: int = 40, height: int = 32) -> bytes:
    raw = b"".join(b"\x00" + bytes([120, 90, 40, 255]) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6,
                                                               0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def facts_of(project) -> dict:
    """A few objective facts about the files, for reading the run afterwards."""
    if project.profile.id == "games":
        facts = games.facts(project)
        source = facts.get("source") or ""
        constants = facts.get("constants") or {}
        return {"things": sorted(facts.get("things") or {}),
                "speeds": {n: c.value for n, c in constants.items() if n.endswith("_SPEED")},
                "sizes": {n: c.value for n, c in constants.items() if n.endswith("_SIZE")},
                "sha": __import__("hashlib").sha256(source.encode()).hexdigest()[:10],
                "score": bool(facts.get("score")),
                "score_drawn": "score" in source.lower() and ".render(" in source,
                "picture": "_image" in source, "loop": facts.has("loop")}
    facts = website.facts(project)
    footer = (facts.get("page") or "").split("<footer", 1)[-1]
    bg = [v.value for v in (facts.get("css_vars") or {}).get("--bg", [])]
    return {"footer": footer.split("</footer>")[0].strip()[:120], "bg": bg,
            "balanced": bool(facts.get("balanced"))}


def main() -> int:
    app = QApplication([])
    provider = build_provider(default_model_id())
    provider.load()
    out = []
    for name, profile, script in SCRIPTS:
        root = Path(tempfile.mkdtemp(prefix="pre13-"))
        project = create_project(name, profile, root=root)
        versions = VersionHistory(project)
        versions.start()
        controller = AgentController(
            project, provider, Toolbox(project), build_style=project.manifest.build_style,
            versions=versions, memory=MemoryManager.for_provider(project, provider,
                                                                 versions=versions),
            fastpath=FastPathRouter())
        bench = Workbench(project, controller, versions)
        bench.resize(1200, 800)
        bench.show()
        print(f"\n===== {name} ({profile})", flush=True)
        for message, attach in script:
            before = len(bench._transcript.toPlainText())
            started = time.monotonic()
            record: dict = {"project": name, "message": message}
            if message == UNDO:
                bench._undo()
                app.processEvents()
                record["kind"] = "undo"
            else:
                if attach:
                    picture = root / "eagle.png"
                    picture.write_bytes(png())
                    bench._pending.append(assets.import_file(project, picture))
                finished = []
                real = bench._turn_finished
                bench._turn_finished = lambda turn, real=real: (finished.append(turn),
                                                                real(turn))[1]
                bench._input.setText(message)
                bench._send()
                while bench._thread is not None:
                    app.processEvents()
                    time.sleep(0.02)
                app.processEvents()
                bench._turn_finished = real
                turn = finished[0] if finished else None
                fp = (turn.fastpath or {}) if turn else {}
                record.update({
                    "kind": "turn",
                    "route": fp.get("route"), "reason": fp.get("reason"),
                    "recipe": fp.get("recipe"), "result": fp.get("result"),
                    "parts": [{k: p.get(k) for k in ("part", "route", "recipe", "result")}
                              for p in fp.get("parts", [])],
                    "remaining": fp.get("remaining"), "plan": fp.get("plan"),
                    "context": fp.get("context"),
                    "calls": turn.usage.calls if turn else None,
                    "changed": sorted({p for _, r in turn.tool_results
                                       for p in r.changed_files}) if turn else [],
                    "playtests": [t.verdict for t in turn.playtests] if turn else [],
                    "still_shown": not bench._chart.isHidden(),
                    "code_caption": (bench._code_caption.text()
                                     if not bench._code_caption.isHidden() else ""),
                })
            record["seconds"] = round(time.monotonic() - started, 1)
            record["chat"] = bench._transcript.toPlainText()[before:].strip()
            record["facts"] = facts_of(project)
            out.append(record)
            print(f"\n--- {message}  ({record['seconds']} s)", flush=True)
            for key in ("route", "reason", "recipe", "result", "parts", "remaining", "plan",
                        "context", "calls", "changed", "playtests", "still_shown",
                        "code_caption"):
                if record.get(key) not in (None, [], ""):
                    print(f"    {key}: {record[key]}", flush=True)
            print(f"    facts: {record['facts']}", flush=True)
            print("    " + record["chat"].replace("\n", "\n    "), flush=True)
        bench.close()
        shutil.rmtree(root, ignore_errors=True)
    (HERE / "results" / "pre13_acceptance.json").write_text(json.dumps(out, indent=1) + "\n")
    print("\nwritten", HERE / "results" / "pre13_acceptance.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
