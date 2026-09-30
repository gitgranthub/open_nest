"""One line per step of a stress walk, from its results file -- for SPIKES.md section 29.

    .venv/bin/python benchmarks/stress/summarise.py stress_4b [stress_luna ...]

Reads ``results/<label>.json`` (``stress_walk.py``) and prints a Markdown table per
label: what was asked, the route, what changed, whether a question changed anything,
tool syntax or code in the chat, and the first words Gary said -- then the totals a
reader checks the matrix against. It flags; it does not grade intent: every flagged line
is read against the files kept in the JSON beside it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from opennest.agent.replies import hardware_claims, instructs_edit, is_question  # noqa: E402


def gary(chat: str) -> str:
    said = chat.split("Gary:", 1)[1] if "Gary:" in chat else chat
    return " ".join(said.split())


def main() -> int:
    for label in sys.argv[1:] or ["stress_4b"]:
        records = json.loads((HERE / "results" / f"{label}.json").read_text())
        totals = {"turns": 0, "questions": 0, "question_changed": 0, "leaks": 0,
                  "code": 0, "hardware": 0, "instructions": 0, "input": 0, "output": 0,
                  "calls": 0}
        print(f"\n### {label}\n")
        print("| project | step | route | changed | flags | Gary |")
        print("|---|---|---|---|---|---|")
        for r in records:
            step = r.get("message") or r["step"]
            said = gary(r.get("chat", ""))
            if r.get("kind") != "turn":
                shown = (r.get("panel") or r.get("chart") or r.get("caption") or
                         r.get("added") or r.get("board") or r.get("hand_edit") or "")
                print(f"| {r['project']} | {step} | -- | -- | -- | "
                      f"{' '.join(str(shown).split())[:90]} |")
                continue
            totals["turns"] += 1
            totals["input"] += r.get("input_tokens") or 0
            totals["output"] += r.get("output_tokens") or 0
            totals["calls"] += r.get("calls") or 0
            flags = []
            if is_question(step):
                totals["questions"] += 1
                if r.get("changed"):
                    totals["question_changed"] += 1
                    flags.append("QUESTION CHANGED FILES")
            if r.get("leaks"):
                totals["leaks"] += 1
                flags.append("leak " + ",".join(r["leaks"]))
            if r.get("code_lines"):
                totals["code"] += 1
                flags.append(f"{r['code_lines']} code lines")
            if r["profile"] in ("arduino", "raspberry_pi") or "Pi" in r["project"] or \
                    "Sketch" in r["project"]:
                if hardware_claims(said):
                    totals["hardware"] += 1
                    flags.append("HARDWARE CLAIM")
            if instructs_edit(said) and not r.get("changed"):
                totals["instructions"] += 1
                flags.append("edit instructions")
            changed = ", ".join(r.get("changed") or []) or "nothing"
            route = r.get("recipe") or r.get("route") or ("answer" if r.get("answered")
                                                          else "gary")
            print(f"| {r['project']} | {step[:50]} | {route} | {changed} | "
                  f"{'; '.join(flags) or '--'} | {said[:140]} |")
        print(f"\n{totals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
