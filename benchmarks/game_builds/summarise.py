"""Lay out a game builds run beside what each step was expected to do.

    .venv/bin/python benchmarks/game_builds/summarise.py results/<label>.json [...]

For a reader grading by hand: per step, what following it meant (written before the
run), how Open Nest routed it, what changed, the headless test, what the scene drew,
and what the child read. Grades nothing itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def gary(chat: str) -> str:
    return chat.split("Gary:", 1)[-1].strip() if "Gary:" in chat else ""


def main() -> int:
    for name in sys.argv[1:]:
        run = json.loads(Path(name).read_text())
        print(f"\n######## {name} -- {run['model']}")
        for thread, record in run["threads"].items():
            print(f"\n=== {thread} ({record['profile']}, "
                  f"{'starter' if record['starter'] else 'empty'}, {record['seconds']} s)")
            for step in record["steps"]:
                print(f"\n  > {step['step']}  ({step['seconds']} s)")
                if step.get("expect"):
                    print(f"    expect: {step['expect']}")
                if step.get("kind") == "turn":
                    calls = [call["name"] for entry in step.get("history", [])
                             for call in entry.get("calls", [])]
                    refused = sum(1 for result in step.get("results", []) if not result["ok"])
                    print(f"    route: {step.get('route')} {step.get('recipe') or ''}  "
                          f"calls: {len(calls)} ({refused} refused)  "
                          f"changed: {', '.join(step.get('changed') or []) or 'nothing'}")
                    for test in step.get("playtests", []):
                        print(f"    playtest: {test['verdict']}")
                    if step.get("scene"):
                        print("    scene: " + " | ".join(step["scene"])[:400])
                    print("    gary: " + gary(step.get("chat", "")).replace("\n", " ")[:600])
                    if step.get("leaks"):
                        print(f"    LEAKS: {step['leaks']}")
                elif step.get("kind") == "run":
                    print(f"    running: {step.get('game_running')}  frame: {step.get('frame')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
