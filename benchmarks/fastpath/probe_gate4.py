"""Gate phrasings, chosen on the first set only. A conditional gate names the intent.

    OPENNEST_HOME=... scripts/offline.sh .venv/bin/python benchmarks/fastpath/probe_gate4.py decide_dev3.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
RESULTS = HERE / "results"
RAW = RESULTS / "raw"   # full runs, file contents included: local only, gitignored
sys.path.insert(0, str(HERE.parents[1]))
from opennest.ai.router import build_provider, default_model_id
from opennest.fastpath.classifier import IntentClassifier, Option
from opennest.fastpath.registry import RecipeRegistry

VARIANTS = {
 "current": lambda d: "Does this message ask for exactly one specific change to the project, and nothing else?",
 "everything": lambda d: f"One kind of change is: {d}. Is that everything this message asks for?",
 "only": lambda d: f"Does this message ask only for this: {d}? Answer no if it also asks for something else, or if it is only a question.",
 "just_that": lambda d: f"Is this message asking for exactly this, and nothing more: {d}?",
}
rows = json.loads((RESULTS / sys.argv[1]).read_text())
reg = RecipeRegistry()
provider = build_provider(default_model_id()); provider.load()
out = []
for row in rows:
    recipe = reg.for_profile(row["profile"]).for_intent(row["intent"])
    if recipe is None:
        out.append({}); continue
    answers = {}
    for key, question in VARIANTS.items():
        c = IntentClassifier(provider.score_choices, orderings=2).choose(
            question(recipe.describe), [Option("one", "yes"), Option("no", "no")], row["text"],
            previous=row["previous"], about=row["about"], keep_last=False)
        answers[key] = (c.name, round(c.score, 3), c.agreement)
    # The same question with the description in the variable part, so the fixed part
    # -- the cached prefix -- is one string for every intent.
    c = IntentClassifier(provider.score_choices, orderings=2).choose(
        "Is the kind of change named below everything this message asks for?",
        [Option("one", "yes"), Option("no", "no")], row["text"], previous=row["previous"],
        about=f"{row['about']}\nThe kind of change: {recipe.describe}.", keep_last=False)
    answers["everything_user"] = (c.name, round(c.score, 3), c.agreement)
    out.append(answers)
(RESULTS / f"gate4_{Path(sys.argv[1]).stem}.json").write_text(json.dumps(out))
print("done")
