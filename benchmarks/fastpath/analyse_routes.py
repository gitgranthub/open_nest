"""Score the routes the shipped router actually chose, from a decide_*.json.

    .venv/bin/python benchmarks/fastpath/analyse_routes.py decide_heldout3.json

For runs made after the closure pass (SPIKES.md section 25M), bench_decide.py stores the
router's own decision -- every rule applied -- so nothing is re-derived here. A RECIPE
decision on a guide-only recipe is guidance, as it is in the product. "Right" means the
intent the router acted on is one the gold label accepts; an intent no label accepts
(``change_thing_motion`` is new, and no labelled request asks for it) counts as wrong.
"""
import json, sys
from collections import Counter
from pathlib import Path
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
rows = json.loads((RESULTS / sys.argv[1]).read_text())
c = Counter(); wrong = []; composed = []
for row in rows:
    route = row["route"]
    if route == "recipe" and not row["deterministic"]:
        route = "guide"
    intent = row.get("router_intent") or row["intent"]
    right = intent in row["accept"]
    change = row["gold"] != "other"
    if row.get("compound"):
        composed.append((row["text"][:70], route, right))
    if route == "recipe":
        outcome = "recipe right" if right else "RECIPE WRONG"
        if not right:
            wrong.append((row["profile"], intent, row["text"][:70]))
    elif route == "guide":
        outcome = "guided right" if right else "guided wrong"
    else:
        outcome = "Gary (missed change)" if change else "Gary (correct)"
    c[("change" if change else "not a change", outcome)] += 1
print("==", sys.argv[1], f"({len(rows)} requests)")
for key, value in sorted(c.items()):
    print("  ", key, value)
print("   wrong recipe routes:", wrong)
print("   composed compounds:", composed)
ms = sorted(r["decide_seconds"] * 1000 for r in rows)
print(f"   intent+gate latency: median {ms[len(ms)//2]:.0f} ms, p90 {ms[int(len(ms)*0.9)]:.0f} ms")
