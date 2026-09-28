"""Route outcomes from a decide_*.json, at the shipped thresholds and a sweep of others.

    .venv/bin/python benchmarks/fastpath/analyse_decide.py decide_heldout.json
"""
from __future__ import annotations
import json, sys
from collections import Counter, defaultdict
from pathlib import Path
HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
RESULTS = HERE / "results"
RAW = RESULTS / "raw"   # full runs, file contents included: local only, gitignored
sys.path.insert(0, str(HERE.parents[1]))
from opennest.fastpath.registry import RecipeRegistry  # noqa: E402
rows = json.loads((RESULTS / sys.argv[1]).read_text())
_REG = RecipeRegistry()


def _deterministic(profile, intent):
    recipe = _REG.for_profile(profile).for_intent(intent)
    return recipe is not None and recipe.deterministic

def route(row, recipe_min=0.9, guide_min=0.6, gate=True):
    if row["intent"] == "other" or row["score"] < guide_min:
        return "normal"
    recipe = _REG.for_profile(row["profile"]).for_intent(row["intent"])
    if recipe is not None and recipe.whole:
        return "recipe" if row["agreement"] == 1.0 and row["score"] >= 0.99 else "normal"
    if gate and not (row["shape"] == "one" and row["shape_agreement"] == 1.0 and row["shape_score"] >= 0.8):
        return "normal"
    if row["agreement"] == 1.0 and row["score"] >= recipe_min and _deterministic(
            row["profile"], row["intent"]):
        return "recipe"
    return "guide"

def outcome(row, r):
    right = row["intent"] in row["accept"]
    change = row["gold"] != "other"
    if r == "recipe":
        return "fast_correct" if right and row["intent"] != "other" else "FAST_WRONG"
    if r == "guide":
        return "guided_correct" if right else "guided_wrong"
    return "missed" if change else "correct_fallback"

def table(label, **kw):
    counts = Counter(); by_profile = defaultdict(Counter)
    for row in rows:
        o = outcome(row, route(row, **kw))
        counts[o] += 1; by_profile[row["profile"]][o] += 1
    changes = sum(1 for r in rows if r["gold"] != "other")
    fast = counts["fast_correct"] + counts["FAST_WRONG"]
    print(f"{label:34} n={len(rows)} changes={changes}  fast={fast} "
          f"(correct {counts['fast_correct']}, WRONG {counts['FAST_WRONG']})  "
          f"guided {counts['guided_correct']}+{counts['guided_wrong']}w  missed {counts['missed']}  "
          f"fallback-ok {counts['correct_fallback']}")
    return counts, by_profile

intent_ok = sum(r["intent"] in r["accept"] for r in rows)
lex_ok = sum(r["lexical"] in r["accept"] for r in rows)
print(f"intent correct (lenient): qwen {intent_ok}/{len(rows)} = {intent_ok/len(rows):.0%}   lexical {lex_ok}/{len(rows)} = {lex_ok/len(rows):.0%}")
for source in sorted({r['source'] for r in rows}):
    sub = [r for r in rows if r["source"] == source]
    q = sum(r["intent"] in r["accept"] for r in sub); l = sum(r["lexical"] in r["accept"] for r in sub)
    print(f"  {source:12} qwen {q}/{len(sub)}  lexical {l}/{len(sub)}")
ms = sorted(r["decide_seconds"] * 1000 for r in rows)
print(f"classify+gate latency: median {ms[len(ms)//2]:.0f} ms, p90 {ms[int(len(ms)*0.9)]:.0f} ms, max {ms[-1]:.0f} ms")
print()
counts, by_profile = table("STRICT GATE ONLY (0.90 / 0.60) -- for the final gate see analyse_final_gate.py")
for profile, c in sorted(by_profile.items()):
    print(f"    {profile:13} fast {c['fast_correct']}+{c['FAST_WRONG']}w  guided {c['guided_correct']}+{c['guided_wrong']}w  missed {c['missed']}  fallback-ok {c['correct_fallback']}")
table("no gate (0.90 / 0.60)", gate=False)
for t in (0.8, 0.95, 0.99):
    table(f"gate on, recipe >= {t}", recipe_min=t)
print("\nFAST_WRONG, strict gate:")
for row in rows:
    if outcome(row, route(row)) == "FAST_WRONG":
        print(f"   {row['profile']:12} {row['intent']:20} gold={row['gold']:18} {row['text'][:70]!r}")
print("\nguided_wrong, strict gate:")
for row in rows:
    if outcome(row, route(row)) == "guided_wrong":
        print(f"   {row['profile']:12} {row['intent']:20} gold={row['gold']:18} {row['text'][:70]!r}")
