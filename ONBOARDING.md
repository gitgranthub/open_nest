# Onboarding

Open Nest is a PySide6 Mac app. A child describes an idea, and Gary, an assistant
running on a **small local model** (Gary Fast is Qwen3-VL 4B), builds and runs it. Most
design choices that look odd were measured against that model. Check
[SPIKES.md](SPIKES.md) before "fixing" one.

Read next: [WHATS_NEW.md](WHATS_NEW.md) (the latest work), then [HANDOFF.md](HANDOFF.md),
the full reference and the entry point for every session.

## Run it

```bash
./Setup\ Open\ Nest.command          # first time: installs Python, .venv, a model
./Launch\ Open\ Nest\ Demo.command    # the app, using the dev sandbox .opennest-sandbox
.venv/bin/python -m pytest -q         # 1750 tests, about 4 minutes
```

| What | Command | Network |
|---|---|---|
| Fetch pinned artifacts | `scripts/fetch.sh model <id>` / `deps` / `arduino` | on |
| Anything that loads the model | `scripts/offline.sh <command>` | off |
| The test suite | `.venv/bin/python -m pytest -q`, unwrapped | not used |

## Where things are

`opennest/agent` is the turn loop and its honesty checks. `ai` holds the model
providers. `assets` covers a child's files and what Gary has seen in a picture.
`graphics` is the game scene layer. `fastpath` has the recipes for common requests.
`setup` is the install wizard, and `config/models.json` and `profiles.json` are data,
not code. `bootstrap/` runs before a modern Python exists, so it must stay
3.9-compatible and never import `opennest`.

## Six things that will cost you a day

1. **Inject, don't add tools.** Gary has four tools (five in games). Each extra tool was
   measured to cost accuracy, so anything the app already knows goes into the prompt.
2. **The app checks, it never trusts the prompt.** A claimed edit, run, or sighting that
   did not happen is caught and corrected. A picture counts as seen only once its pixels
   reached a model (`assets.look`).
3. **`edit_file` is how files change.** `write_file` refuses to overwrite. A small model
   cannot reproduce a whole file inside JSON.
4. **Seatbelt does not nest.** Code that runs child projects cannot run inside
   `scripts/offline.sh`. Never weaken the sandbox to make a test pass.
5. **Qt threads are fragile here.** Use `ui/worker.py`, never the `moveToThread` idiom,
   and never connect a lambda to a worker signal (HANDOFF §4).
6. **Measure on the real model.** Run the replays and benchmarks in `benchmarks/`.
   Temperature 0 on MLX is not exactly repeatable, so report each run.

## Working agreements

Smallest correct change, in scope. Pin third-party artifacts to a commit SHA. Download one
or two artifacts for an experiment, not a candidate set. Run the tests and `ruff check .`
before calling anything done, and say plainly what is not done. Branches are stacked per
phase, and nothing is merged to `main`. Commit finished, verified work on the phase
branch.
