"""One line per step of an owner walk, from its results file -- for SPIKES.md section 27.

    .venv/bin/python benchmarks/owner_pass/summarise.py final

Reads ``results/<label>.json`` (``owner_walk.py``) and prints a Markdown table: what was
asked, what changed, whether the chat carried tool syntax or code, what the plan holds,
and the first words Gary said -- the evidence a reader checks the claims against, with
the game's source kept in the JSON beside it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def gary(chat: str) -> str:
    said = chat.split("Gary:", 1)[1] if "Gary:" in chat else ""
    return " ".join(said.split())[:150]


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "final"
    records = json.loads((HERE / "results" / f"{label}.json").read_text())
    print("| project | step | changed | leaks / code | plan | Gary |")
    print("|---|---|---|---|---|---|")
    for r in records:
        if r.get("skipped"):
            continue
        step = r.get("message") or r["step"]
        if r.get("kind") == "run":
            shown = ("game playing" if r.get("game_running") else
                     "page shown" if r.get("page_visible") else r.get("panel", "")[:60])
            print(f"| {r['project']} | {r['step']} | -- | -- | -- | {shown} |")
            continue
        leaks = ", ".join(r.get("leaks") or []) or "none"
        code = r.get("code_lines", 0)
        plan = "; ".join(r.get("plan_waiting") or []) or "--"
        changed = ", ".join(r.get("changed") or []) or "nothing"
        print(f"| {r['project']} | {step[:60]} | {changed} | {leaks}, {code} code lines | "
              f"{plan[:80]} | {gary(r.get('chat', ''))} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
