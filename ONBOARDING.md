# Onboarding — Open Nest

You are joining a macOS desktop app that lets a child describe an idea and get a real,
running project out of it, with a **4-billion-parameter model running locally on their
Mac**. That last detail shapes almost every decision in this codebase. If something
looks over-cautious or oddly shaped, it is usually because it was measured against that
model and the obvious version did not work.

This page is your first thirty minutes. [HANDOFF.md](HANDOFF.md) is the real entry point
after that.

---

## Get it running

```bash
.venv/bin/python -m pytest -q
```

317 tests, about six seconds. **Run the suite unwrapped** — it is hermetic (temp
directories, no network, no model). Wrapping it in `scripts/offline.sh` is wrong and
silently skips sixteen tests; see "Seatbelt does not nest" below.

No `.venv` yet? Run `./Setup\ Open\ Nest.command` first. It downloads and installs its
own CPython 3.12.14 — do not expect a system Python to work. The development Mac this
was built on has only Python 3.9.

Launch the app:

```bash
./Launch\ Open\ Nest.command
```

---

## The one workflow rule

Development is two-phase, and it is not optional:

| Phase | Command | Network |
|---|---|---|
| Fetch | `scripts/fetch.sh model <id>` / `scripts/fetch.sh deps` | **on**, pinned artifacts only |
| Anything touching the model | `scripts/offline.sh <command>` | **off** |
| The test suite | `.venv/bin/python -m pytest -q` | not used |

Third-party artifacts are fetched pinned to a commit SHA with the network on, then
executed with the network denied and writes confined to the project, enforced by macOS
Seatbelt without root. This exists because the machine is work-managed and downloaded
models must stay contained. Everything lives under `.opennest-sandbox/`; `rm -rf`
removes all of it.

---

## Where things are

```
opennest/
├── ui/            PySide6. theme.py owns every colour; no widget hard-codes one.
├── ai/            provider interface, local MLX provider, model catalogue + routing
├── agent/         the loop (controller.py) and the four tools (tools.py)
├── assets/        importing a child's own files, and what may honestly be said about them
├── memory/        project_bible.md, project_state.md, compaction, history search
├── conversations/ context budget, thread archive, the rollover handover
├── projects/      manifest, profiles, starter templates
├── execution/     running child code out of process
├── versioning/    invisible Git: autosave, checkpoints, undo, secret scanning
├── security/      sandbox.py (path confinement) + process_sandbox.py (Seatbelt)
├── config/        models.json, profiles.json      <- data, not code
└── prompts/       base + per-profile + build-style <- data, not code

bootstrap/         runs before a modern Python exists. MUST stay 3.9-compatible.
```

Two structural rules a test will enforce for you: `bootstrap/` never imports `opennest`,
and it never uses 3.10+ syntax.

---

## Five things that will cost you a day if you don't know them

**1. The tool set is four tools wide, and that is a measured ceiling.** Selection
accuracy fell from 94% to 75% when a fifth tool was added. There is no
`list_project_files`, no `inspect_error`, no `search_memory`, no `list_assets` — even
though the work order lists all four. Anything the application already knows is
**injected into the system prompt** instead. When you are tempted to add a tool, the
answer is almost always an injected block.

**2. `edit_file` is the primary way to change a file.** Asked to reproduce a whole file
inside a JSON string, the model emits Python triple-quotes and the call never parses.
`write_file` refuses to overwrite for exactly this reason.

**3. Seatbelt does not nest.** A `sandbox-exec` profile cannot be applied inside another
one, so tests that start a child project fail from inside `scripts/offline.sh`.
`run_project` fails closed when it cannot confine code — that is correct and should not
be weakened to make a test pass.

**4. macOS filesystems are case-insensitive.** `.GIT/HEAD` opens `.git/HEAD`. This was a
live sandbox bypass once. Path comparisons are casefolded.

**5. Prompt instructions are not trusted on their own.** The base prompt tells the model
not to claim edits it did not make, and it does it anyway — so the application checks.
Same for describing an image it cannot see. Where you find a deterministic check
shadowing a prompt rule, it is there because the prompt was measured and found wanting.

---

## How decisions get made here

**Measure, then decide.** [SPIKES.md](SPIKES.md) is the record, and it is the most
useful document in the repository. Several design choices look wrong until you read why
they were measured that way — check it before "fixing" one. Every number in it came from
a real run, and where something was *not* measured, it says so.

If you find yourself about to write "this is unverified" in a summary, check first
whether you can just run it. The model is downloaded and `scripts/offline.sh` works, so
behavioural questions about the model are usually answerable in a few minutes. In Phase
5 that habit reversed a decision: an honesty check had been argued impossible, and the
measurement produced the exact sentence that made it possible.

**Honesty is a product requirement, not a nicety.** A child is the user. The app never
claims a model saw something it did not, never claims an edit it did not make, and never
hides that it is stuck. Several mechanisms exist only to enforce that.

**The child never sees the machinery.** No Git vocabulary, no "context window", no
"rollover". Version history is "Undo". Thread handover is invisible by design.

---

## What is built, and what is next

Phases 0–5 are complete: setup and vendored Python, the risk spikes, the core
idea→project→run slice, invisible Git with undo and crash recovery, project memory with
automatic thread rollover, and asset import.

**Phase 6 is next — cloud AI, credentials, and parent controls.** Keychain credential
storage, OpenAI and Anthropic providers behind the existing `ModelProvider` interface, a
cloud master switch defaulting off, per-use consent, and parent PIN. [PLAN.md](PLAN.md)
has the model choices and three API details that will otherwise bite.

Nothing is merged to `main`. Branches are stacked, each based on the previous one, so
each PR shows only its own phase.

---

## Working agreements

- Smallest change that correctly solves the request. Stay in scope.
- Read the relevant code, and `HANDOFF.md`, before changing anything.
- **Do not commit, push, branch, or open PRs unless asked.** Asked once is not standing
  permission.
- Pin third-party artifacts to a commit SHA, never a moving branch.
- Download one or two artifacts for an experiment, not a whole candidate set — each is
  gigabytes and adds licensing surface.
- Run the tests and `ruff check .` before saying something is done, and say plainly what
  is not done.

---

Read [HANDOFF.md](HANDOFF.md) next. It supersedes any stale assumption this page or the
code would otherwise give you.
