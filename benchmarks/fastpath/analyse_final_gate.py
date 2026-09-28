"""Routing under the FINAL gate, from stored answers -- the 19-right / 1-partial figure.

    .venv/bin/python benchmarks/fastpath/analyse_final_gate.py

analyse_decide.py reproduces the strict gate only (15 right, 0 wrong on held-out). The
shipped gate adds two rules decided after it: whole-game recipes skip the gate at share
>= 0.99, and a tweak (router.TWEAK_OPS) gets the second question, whose answers are in
gate4_decide_*.json. This is the computation that SPIKES.md section 25E quotes, saved as
it was run.
"""
import json, sys
from collections import Counter
from pathlib import Path
HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
RESULTS = HERE / "results"
RAW = RESULTS / "raw"   # full runs, file contents included: local only, gitignored
sys.path.insert(0, str(HERE.parents[1]))
from opennest.fastpath.registry import RecipeRegistry  # noqa: E402
from opennest.fastpath.router import TWEAK_OPS  # noqa: E402
reg = RecipeRegistry()
def ok(v): return v[0] == "one" and v[2] == 1.0 and v[1] >= 0.8
for name in ("decide_dev3", "decide_heldout2"):
    rows = json.loads((RESULTS / f"{name}.json").read_text()); gates = json.loads((RESULTS / f"gate4_{name}.json").read_text())
    c = Counter(); wrong = []
    for row, g in zip(rows, gates):
        recipe = reg.for_profile(row["profile"]).for_intent(row["intent"])
        route = "normal"
        if row["intent"] != "other" and row["score"] >= 0.6 and recipe is not None:
            if recipe.whole:
                route = "recipe" if row["agreement"] == 1 and row["score"] >= 0.99 else "normal"
            else:
                first = (row["shape"], row["shape_score"], row["shape_agreement"])
                passed = ok(first) or (recipe.op in TWEAK_OPS and g and ok(g["just_that"]))
                if passed:
                    route = "recipe" if (row["agreement"] == 1 and row["score"] >= 0.9 and recipe.deterministic) else "guide"
        right = row["intent"] in row["accept"]
        change = row["gold"] != "other"
        if route == "recipe":
            o = "recipe right" if right else "RECIPE WRONG"
            if not right: wrong.append(row["text"][:70])
        elif route == "guide":
            o = "guided right" if right else "guided wrong"
        else:
            o = "Gary (missed change)" if change else "Gary (correct)"
        c[(("change" if change else "not a change"), o)] += 1
    print("==", name)
    for k, v in sorted(c.items()): print("  ", k, v)
    print("   wrong recipe routes:", wrong)
