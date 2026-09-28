"""The Fast Path: Open Nest handles the predictable parts, Gary handles the interesting ones.

Phase 12.3 measured one working game in twenty-four conversations, and Phase 12.4 made
the broken ones visible without making the model build the right one. Most of what a
child asks for is not new, though -- "make the player faster", "add a score", "graph
this" -- and asking a 4B model to reinvent a known pattern from scratch every time is
where those turns went wrong. This package routes a request it recognises through a
recipe that is known to work, and leaves everything else exactly as it was.

    request ─ facts ─ FastPathRouter ─ IntentClassifier (same model, one forward pass)
                          │
                          ├─ high score, recipe applies ─ RecipeExecutor ─ RecipeVerifier
                          │                                   │ passes        │ fails
                          │                                   ▼               ▼
                          │                               Gary reports    rolled back
                          │                                               and guided
                          ├─ medium score, or code no longer starter-shaped ─ guidance
                          │     (the recipe's strategy and snippet, placed in *this*
                          │      file, given to Gary for the one turn)
                          └─ low score, "other", creative ─ Gary exactly as before

Pieces, kept separable on purpose:

- :mod:`.classifier` -- the only part that asks the model anything, and it asks a closed
  question: no free-form generation to classify.
- :mod:`.registry` -- the shipped recipes, data under ``opennest/recipes/<profile>/``.
- :mod:`.router` -- scores to a route. The only place thresholds live.
- :mod:`.executor` -- turns a recipe into edits, and applies them **through the Toolbox**,
  so path confinement, the syntax gate and every refusal still apply.
- :mod:`.verifier` -- what each recipe must be seen to do before anyone says it did.
- :mod:`.kinds` -- per project type: the deterministic facts about a file, and the
  small operations that change it. Nothing about any one intent lives in the UI.

What this package deliberately is not: a snippet inserter, a template engine, a vector
store, a second model, or a workflow engine. A recipe encodes a known pattern and where
its pieces go; when the child's code has moved away from that shape the recipe says so
and Gary adapts instead.
"""
