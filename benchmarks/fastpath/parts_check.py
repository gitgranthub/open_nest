"""Every labelled request that splits into parts, made for real: what did each part do?

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/fastpath/parts_check.py

The label sets score a message by one intent, and a message of several requests has no
single right one -- so ``analyse_routes.py`` cannot say whether a part was made right.
This runs each such request through ``FastPathRouter.handle`` in a fresh project (the
recipes edit, the checks run, a failure rolls back) and records, part by part, which
recipe made what, so each can be judged against what the child asked. Writes
``results/parts_check.json``; the judgements are in SPIKES.md section 25N.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.router import build_provider  # noqa: E402
from opennest.fastpath.router import FastPathRouter, split_parts  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402

DATA = {"labels.json": "plants.csv", "labels_heldout.json": "weather.csv"}


def main() -> int:
    provider = build_provider("qwen3-4b-instruct")
    provider.load()
    router = FastPathRouter()
    out = []
    for labels, data in DATA.items():
        for row in json.loads((HERE / "inputs" / labels).read_text()):
            if not split_parts(row["text"]) or row["previous"]:
                continue
            root = Path(tempfile.mkdtemp(prefix="parts-"))
            try:
                project = create_project("Parts", row["profile"], root=root)
                if row["profile"] == "research":
                    (project.directory / "data").mkdir(exist_ok=True)
                    shutil.copy(HERE / "inputs" / data, project.directory / "data" / data)
                if row["profile"] == "arduino":
                    project.manifest.arduino_board = "arduino:avr:uno"
                    project.save()
                toolbox = Toolbox(project)
                result = router.handle(project, toolbox, row["text"], provider=provider)
                toolbox.stop_running()
                record = result.record
                parts = [{k: p.get(k) for k in ("part", "route", "intent", "score", "recipe",
                                                "result", "stepped_aside")}
                         for p in record.get("parts", [])]
                out.append({"set": labels, "profile": row["profile"], "text": row["text"],
                            "route": record.get("route"), "reason": record.get("reason"),
                            "recipe": record.get("recipe"), "parts": parts,
                            "remaining": record.get("remaining"), "reply": result.text})
                print(f"\n[{row['profile'][:6]}] {row['text'][:88]!r} -> {record.get('route')}"
                      f" {record.get('recipe') or ''}", flush=True)
                for part in parts:
                    print(f"    {part['part'][:44]!r:47} {part['route']:8} "
                          f"{(part.get('recipe') or '-'):26} {part.get('result') or ''}",
                          flush=True)
                if record.get("remaining"):
                    print(f"    left for Gary: {record['remaining']}", flush=True)
                if result.text:
                    print("    said: " + result.text.replace("\n", " / ")[:240], flush=True)
            finally:
                shutil.rmtree(root, ignore_errors=True)
    (HERE / "results" / "parts_check.json").write_text(json.dumps(out, indent=1) + "\n")
    print("\nwritten", HERE / "results" / "parts_check.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
