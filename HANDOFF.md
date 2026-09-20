# Handoff — start here

You are picking up Open Nest after Phase 3. **Phase 4 (memory and thread rollover) is
next.** This document is what you need before touching anything.

Read in this order: this file → [PLAN.md](PLAN.md) (phases and decisions) →
[SPIKES.md](SPIKES.md) (measurements the design rests on). `WORKORDER_01.md` and
`DESIGN_DOC.md` are the source requirements; read the sections you are implementing
rather than all 3,400 lines up front.

---

## 1. Where the project is

| Phase | State |
|---|---|
| 0 — Skeleton, bootstrap installer | complete, [PR #1](https://github.com/gitgranthub/open_nest/pull/1) |
| 1 — Sandbox and risk spikes | complete, [PR #2](https://github.com/gitgranthub/open_nest/pull/2) |
| 2 — Core vertical slice | complete, [PR #3](https://github.com/gitgranthub/open_nest/pull/3) |
| 3 — Durability | complete, [PR #4](https://github.com/gitgranthub/open_nest/pull/4) |
| **4 — Memory and thread rollover** | **not started — yours** |

Branches are **stacked**: each is based on the previous one, so each PR shows only its
own phase. Nothing is merged to `main` yet. Branch from `phase-3-durability`.

What works today: a child picks a project type, describes an idea, the local model edits
the project, it runs, and they can undo. Everything is local; there is no cloud provider,
no asset import, and no persistent memory.

185 tests pass, ruff is clean.

---

## 2. Get running in five minutes

```bash
source scripts/sandbox.sh          # contain everything under .opennest-sandbox/
scripts/offline.sh .venv/bin/python -m pytest -q
```

If `.venv` does not exist yet, run `./Setup\ Open\ Nest.command` first. It installs its
own CPython 3.12.14 — do not expect a system Python to be usable.

**Development is two-phase, and this is not optional.**

| Phase | Command | Network |
|---|---|---|
| Fetch | `scripts/fetch.sh model <id>` / `scripts/fetch.sh deps` | **on**, pinned artifacts only |
| Everything else | `scripts/offline.sh <command>` | **off** |

Run tests and any model work through `scripts/offline.sh`. It denies network and confines
writes to the project using macOS Seatbelt. This exists because the developer requires
downloaded models and libraries to be contained on a work-managed machine, and because
running the suite inside it has already caught two test bugs that passed outside it.

Launch the app: `./Launch\ Open\ Nest.command`, or
`OPENNEST_HOME=$PWD/.opennest-sandbox .venv/bin/python -m opennest.app`.

---

## 3. Map of the code

```
opennest/
├── app.py                  entry point
├── paths.py                every location the app writes to; OPENNEST_HOME containment
├── ui/
│   ├── theme.py            design tokens + QSS, light and dark. No widget hard-codes colour.
│   ├── common.py           section labels, status rows, ClickableFrame
│   ├── flight_deck.py      home screen
│   ├── workbench.py        project workspace
│   ├── worker.py           QThread plumbing; generation never blocks the UI
│   └── main_window.py      shell, owns the provider and VersionHistory lifecycle
├── ai/
│   ├── provider.py         ModelProvider interface, Message/ToolCall/Reply
│   ├── mlx_provider.py     local MLX; resolves a local snapshot path before loading
│   └── router.py           curated catalogue, refuses cloud when disabled
├── agent/
│   ├── controller.py       the loop: prompt, tools, repair, checkpoints
│   └── tools.py            read_file / edit_file / write_file / run_project
├── projects/               manifest, profiles, starter templates
├── execution/              out-of-process running, batch vs interactive
├── versioning/             git_manager, checkpoint, autosave, secret_scanner
├── security/
│   ├── sandbox.py          path confinement for Open Nest's own tools
│   └── process_sandbox.py  Seatbelt confinement for code Open Nest runs
├── config/                 models.json, profiles.json   (data, not code)
└── prompts/                base + per-profile + build-style   (data, not code)
```

`bootstrap/` is separate and **must stay Python 3.9-compatible** — it runs before a modern
interpreter exists. A test enforces this, and another enforces that it never imports
`opennest`.

---

## 4. Things that will bite you

These each cost real time to discover. None is obvious from the code alone.

**The model is a 4B local model, and the design is shaped around what it measurably
does.** Do not "clean up" these without re-measuring:

- **There is no `list_project_files` tool and no `inspect_error` tool.** The file list and
  the last run result are injected into the system prompt instead. Adding them back costs
  ~19 points of tool-selection accuracy, because the model reaches for them instead of
  acting. Same reasoning §15A applies to memory: the application knows these things
  deterministically, so it should not ask the model to fetch them.
- **Tool sets are four tools wide.** Selection accuracy falls as the set grows — measured
  50% at five tools with no system prompt, 94% at four with one.
- **`edit_file` is the primary way to change a file, not `write_file`.** Asked to
  reproduce a whole file inside a JSON string, the model emits Python triple-quotes and
  the call will not parse. `write_file` refuses to overwrite for this reason.
- **Temperature 0 for anything involving tool selection.**
- **Normalise tool names before dispatch.** Models emit `run_project()` and
  `functions.run_project`. Both are correct, awkwardly spelled.

**Other traps:**

- `mlx_lm.load("<repo-id>")` contacts the Hub even for a fully cached model and fails
  offline. Always resolve a local snapshot path first — see `ai/mlx_provider.py`.
- Every model in `models.json` is pinned to a commit SHA. `mlx-community` publishes
  community *conversions*, so bumping a pin is a deliberate edit, never a side effect.
- A `QPushButton` with a child layout renders empty — its size hint ignores the layout.
  Use `ClickableFrame`.
- macOS filesystems are case-insensitive. `.GIT/HEAD` opens `.git/HEAD`. Path comparisons
  in `security/sandbox.py` are casefolded for this reason; it was a live bypass once.
- `AgentController.history` is the *message list*. Saved versions are `.versions`.
- Starter templates under `projects/templates/` are excluded from ruff: a child reads
  that code, and the linter wanted to collapse a readable `if/elif` into one long line.

---

## 5. Security model — do not weaken this

Two boundaries, doing different jobs:

| Layer | Protects | Does not protect |
|---|---|---|
| `security/sandbox.py` | Paths passing through Open Nest's own file tools | Anything a running process does |
| `security/process_sandbox.py` | Code Open Nest **runs** — no network, writes confined, kernel-enforced | — |

The process sandbox is the real outer boundary. A single `open("/etc/passwd")` inside
generated code bypasses every path check. `run_project` **fails closed**: if the sandbox
cannot be applied, the project does not run.

A known, accepted limitation: TOCTOU between validating a path and opening it. Recorded
in `security/sandbox.py` with what the fix would be. Do not "solve" it casually — it
changes every tool signature.

Commits are refused if the project contains anything credential-shaped. API keys belong
in the macOS Keychain and nowhere else.

---

## 6. Phase 4 — what you are building

Persistent project memory and invisible conversation rollover. `WORKORDER_01.md` §15A is
the specification; read it in full. `PLAN.md` has the phase entry and exit criteria.

Target: **DoD steps 39–43** — the child keeps working, the thread silently rolls over, and
the new thread still knows the project's decisions without replaying the conversation.

### Already in place for you

- `paths.project_internal_dir(project)` → `.opennest/`, already created per project,
  already protected from the model by `security/sandbox.py`, already gitignored for
  `conversations/` while `project_bible.md` and `project_state.md` are versioned.
- `versioning/autosave.atomic_write_text` — use it for memory files. A half-written bible
  is worse than none.
- `agent/controller.py::project_state()` — the existing deterministic context block. Memory
  should extend this, not replace it.
- `models.json` already carries a `context_policy` per model
  (`max_context_tokens`, `rollover_threshold`, `memory_reserved_tokens`), and a test
  enforces that rollover happens before the hard limit.
- `Reply` carries `prompt_tokens` and `generated_tokens` from the provider, so you can
  measure budget without re-tokenising.

### What §15A insists on, and is easy to get wrong

- **Deterministic facts are written by the application, not the model.** File names,
  dependencies, model selection, run status, Git state. Only the semantic summary comes
  from the model. This is the same principle that made tool selection work in Phase 2.
- **The child never sees it happen.** No "context window full", no New Chat button.
- **Roll over early**, while there is still enough context to write a good handoff.
- **Never store credentials in memory files.** `versioning/secret_scanner.py` already
  exists — reuse it before writing memory, not only before committing.

### Suggested order

1. `memory/project_bible.py` and `memory/project_state.py` — read/write with atomic writes,
   deterministic sections owned by the app.
2. `conversations/context_budget.py` — token accounting against the model's policy.
3. `conversations/archive.py` — `thread_vNN.jsonl`, sequential, never overwritten.
4. `conversations/rollover.py` — handoff summary, archive, new thread bootstrap.
5. `memory/compactor.py` and `memory/history_search.py`.
6. Wire into `AgentController`, which already owns the message list.

Build a **scripted-provider test** for rollover the way `tests/test_agent.py` does — force
a low threshold in test config and prove the new thread retains decisions. Do not rely on
the real model for the loop's correctness; use it to check quality separately.

---

## 7. Working agreements

From `CLAUDE.md` and from the developer directly:

- Smallest change that correctly solves the request; stay in scope.
- **Do not commit, push, branch, or open PRs unless asked.** Asked once ≠ standing
  permission.
- **Download one or two artifacts for an experiment, not a whole candidate set.** Each is
  GBs and adds licensing surface on a work-managed machine.
- **Pin third-party artifacts to a commit SHA**, never a moving branch.
- Run tests and lint before saying something is done, and say plainly what is not done.

---

## 8. Open decisions

| # | Decision | Needed by |
|---|---|---|
| D1 | GitHub auth — OAuth device flow, `gh` CLI, or PAT. `gh` is authenticated on the dev machine but authenticates the *parent's* account | Phase 9 |
| — | Git author identity is currently `Open Nest <opennest@localhost>` until the setup wizard collects a real one | Phase 8 |
| — | Only one model is verified and downloaded. The other three are pinned and described but untested | when something needs them |
| — | All measurements are from a 48 GB Mac. The target is 8 GB | before V1 |
