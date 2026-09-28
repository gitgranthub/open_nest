"""Anonymised, shuffled cases from e2e.json for blind grading, in batches.

    .venv/bin/python benchmarks/fastpath/blind_cases.py e2e.json <scratchpad-dir>

Which arm produced a case is replaced by a random id; the key is written separately and
never shown to a grader. Every case the automatic grader could not decide goes in, plus
a sample of the ones it did decide, so the automatic grader is itself checked.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
RESULTS = HERE / "results"
RAW = RESULTS / "raw"   # full runs, file contents included: local only, gitignored
results = json.loads((RAW / sys.argv[1]).read_text())
out = Path(sys.argv[2])
rng = random.Random(25)

MAIN = {"games": ["src/game.py"], "website": ["src/index.html", "src/styles.css", "src/script.js"],
        "research": ["src/analysis.py"], "arduino": ["src/project/project.ino",
                                                     "src/project/wiring.md"],
        "raspberry_pi": ["src/main.py"]}

undecided = [r for r in results if r["grade"].get("judged") != "auto"]
decided = [r for r in results if r["grade"].get("judged") == "auto"]
sample = rng.sample(decided, min(12, len(decided)))
chosen = undecided + sample
rng.shuffle(chosen)

cases, key = [], {}
for index, result in enumerate(chosen):
    case_id = f"case-{index + 1:03d}-{rng.randrange(16**4):04x}"
    key[case_id] = {"id": result["id"], "arm": result["arm"],
                    "auto": result["grade"].get("working"),
                    "judged": result["grade"].get("judged")}
    facts = {k: v for k, v in result["grade"].items()
             if k in ("playtest", "moved_by_itself", "compiled", "exit", "charts", "balanced")}
    cases.append({
        "case": case_id,
        "project_type": result["profile"],
        "child_messages": result["messages"],
        "gary_replies": [t["text"] for t in result["turns"]],
        "final_files": {name: result["files"].get(name, "(missing)") for name in
                        MAIN[result["profile"]]},
        "measured": facts,
    })

size = 12
for number, start in enumerate(range(0, len(cases), size), 1):
    (out / f"blind_batch_{number}.json").write_text(json.dumps(cases[start:start + size],
                                                               indent=1))
(out / "blind_key.json").write_text(json.dumps(key, indent=1))
print(len(cases), "cases in", (len(cases) + size - 1) // size, "batches;",
      len(undecided), "undecided +", len(sample), "sampled")
