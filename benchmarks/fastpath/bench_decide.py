"""The whole decision on labelled requests: facts, intent, message shape, route.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/fastpath/bench_decide.py labels.json 4b [model-id, default: the catalogue default] [--only=games]

Unwrapped (HF_HUB_OFFLINE) because a follow-up's previous message is run through the
real Fast Path first -- which may run a playtest or a compile, and Seatbelt cannot nest.
Stores every number so thresholds can be chosen afterwards (analyse_decide.py).
"""
from __future__ import annotations
import json, shutil, sys, tempfile, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
RESULTS = HERE / "results"
RAW = RESULTS / "raw"   # full runs, file contents included: local only, gitignored
REPO = HERE.parents[1]; sys.path.insert(0, str(REPO)); sys.path.insert(0, str(HERE))
import lexical
from opennest.agent.tools import Toolbox
from opennest.ai.router import build_provider, default_model_id
from opennest.fastpath.classifier import IntentClassifier, OTHER
from opennest.fastpath.kinds import kind_for
from opennest.fastpath.router import FastPathRouter, SHAPE_OPTIONS, SHAPE_QUESTION, SLOT_ORDERINGS
from opennest.projects.manager import create_project

args = [a for a in sys.argv[1:] if not a.startswith("--only=")]
only = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--only=")), None)
labels_file, label = args[0], args[1]
model = args[2] if len(args) > 2 else default_model_id()
items = json.loads((INPUTS / labels_file).read_text())
if only:
    # One profile's requests only: an option added to one profile's list moves no other
    # profile's letters, so only that profile needs re-asking.
    items = [item for item in items if item["profile"] == only]
provider = build_provider(model); provider.load()
router = FastPathRouter()
DATA = {"plants": INPUTS / "plants.csv", "weather": INPUTS / "weather.csv"}

def fresh(profile, data):
    root = Path(tempfile.mkdtemp(prefix="fp-decide-"))
    project = create_project("Decide", profile, root=root)
    if profile == "research":
        (project.directory / "data").mkdir(exist_ok=True)
        shutil.copy(DATA[data], project.directory / "data" / DATA[data].name)
    if profile == "arduino":
        project.manifest.arduino_board = "arduino:avr:uno"; project.save()
    return root, project

out = []
for item in items:
    root, project = fresh(item["profile"], item.get("data", "plants"))
    try:
        toolbox = Toolbox(project)
        prior = None
        if item["previous"]:
            prior = router.handle(project, toolbox, item["previous"], provider=provider).record
            toolbox.stop_running()
        kind = kind_for(item["profile"])
        facts = kind.facts(project)
        about = kind.brief(facts)
        recipes = router.registry.for_profile(item["profile"])
        started = time.monotonic()
        c = IntentClassifier(provider.score_choices, orderings=3).classify(
            recipes.building, recipes.options(), item["text"], previous=item["previous"], about=about)
        shape = IntentClassifier(provider.score_choices, orderings=SLOT_ORDERINGS).choose(
            SHAPE_QUESTION, list(SHAPE_OPTIONS), item["text"], previous=item["previous"], about=about,
            keep_last=False)
        seconds = time.monotonic() - started
        decision = router.decide(item["profile"], item["text"], provider.score_choices,
                                 previous=item["previous"], about=about)
        out.append({**item, "about": about, "prior": prior, **c.as_record(),
                    "shape": shape.name, "shape_score": round(shape.score, 4),
                    "shape_agreement": shape.agreement, "route": decision.route,
                    "reason": decision.reason, "decide_seconds": round(seconds, 3),
                    # What the shipped router chose, all of its rules included (the tweak
                    # question, a recipe's needs_words, a composed compound) -- scored by
                    # analyse_routes.py without re-deriving any rule.
                    "router_intent": (decision.classification.name
                                      if decision.classification else None),
                    "recipe": decision.recipe.id if decision.recipe else None,
                    "deterministic": bool(decision.recipe and decision.recipe.deterministic),
                    "compound": decision.compound,
                    "lexical": lexical.classify(item["profile"], item["text"])})
        ok = c.name in item["accept"]
        print(f"{decision.route:6} {'ok ' if ok else 'BAD'} {c.name:21} s={c.score:.2f} a={c.agreement:.2f} "
              f"shape={shape.name}:{shape.score:.2f}/{shape.agreement:.1f} gold={item['gold']:20} {item['text'][:52]!r}", flush=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)
(RESULTS / f"decide_{label}.json").write_text(json.dumps(out, indent=1))
print("written", RESULTS / f"decide_{label}.json")
