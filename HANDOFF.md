# Handoff — start here

You are picking up Open Nest after Phase 4. **Phase 5 (assets) is next.** This document
is what you need before touching anything.

Read in this order: this file → [PLAN.md](PLAN.md) (phases and decisions) →
[SPIKES.md](SPIKES.md) (measurements the design rests on). `WORKORDER_01.md` and
`DESIGN_DOC.md` are the source requirements; read the sections you are implementing
rather than all 3,400 lines up front.

`CLAUDE.md` points here, so this file is the entry point for every session. Keep it
current: if you finish a phase or learn something that would have saved you an hour,
it belongs in section 4.

---

## 1. Where the project is

| Phase | State |
|---|---|
| 0 — Skeleton, bootstrap installer | complete, [PR #1](https://github.com/gitgranthub/open_nest/pull/1) |
| 1 — Sandbox and risk spikes | complete, [PR #2](https://github.com/gitgranthub/open_nest/pull/2) |
| 2 — Core vertical slice | complete, [PR #3](https://github.com/gitgranthub/open_nest/pull/3) |
| 3 — Durability | complete, [PR #4](https://github.com/gitgranthub/open_nest/pull/4) |
| 4 — Memory and thread rollover | complete, not yet in a PR |
| **5 — Assets** | **not started — yours** |

Branches are **stacked**: each is based on the previous one, so each PR shows only its
own phase. Nothing is merged to `main` yet. Branch from `phase-4-memory`.

What works today: a child picks a project type, describes an idea, the local model edits
the project, it runs, they can undo, and the project remembers its decisions across
conversations. Everything is local; there is no cloud provider and no asset import.

245 tests pass, ruff is clean.

---

## 2. Get running in five minutes

```bash
.venv/bin/python -m pytest -q      # 245 passing
```

**Run the test suite unwrapped.** It is hermetic — temporary directories, no network, no
model — so it needs nothing from the sandbox. Wrapping it in `scripts/offline.sh` used to
be the documented instruction and it was wrong: see "Seatbelt does not nest" in section 4.
A wrapped run is green now (231 passed, 14 skipped), but the skips are real coverage you
lose, so prefer the unwrapped run.

If `.venv` does not exist yet, run `./Setup\ Open\ Nest.command` first. It installs its
own CPython 3.12.14 — do not expect a system Python to be usable.

**Development is two-phase, and this is not optional.**

| Phase | Command | Network |
|---|---|---|
| Fetch | `scripts/fetch.sh model <id>` / `scripts/fetch.sh deps` | **on**, pinned artifacts only |
| Anything touching the model | `scripts/offline.sh <command>` | **off** |
| The test suite | `.venv/bin/python -m pytest -q` | not used |

`scripts/offline.sh` is for the case it was built for: spikes, end-to-end runs, and
anything that loads the downloaded model or could reach the network. It denies network and
confines writes to the project using macOS Seatbelt, because the developer requires
downloaded models and libraries to stay contained on a work-managed machine.

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
│   └── main_window.py      shell; owns the provider, VersionHistory and memory lifecycle
├── ai/
│   ├── provider.py         ModelProvider interface, Message/ToolCall/Reply
│   ├── mlx_provider.py     local MLX; resolves a local snapshot path before loading
│   └── router.py           curated catalogue, refuses cloud when disabled
├── agent/
│   ├── controller.py       the loop: prompt, tools, repair, checkpoints, rollover
│   └── tools.py            read_file / edit_file / write_file / run_project
├── memory/
│   ├── manager.py          the only memory object the controller holds
│   ├── project_bible.py    durable knowledge; app owns Project and Assets
│   ├── project_state.py    current state, all of it deterministic
│   ├── compactor.py        supersede on conflict, then cap. No model call.
│   ├── history_search.py   lookup, injected into context — deliberately not a tool
│   ├── safety.py           the one place memory files get written. Secret-scanned.
│   └── markdown.py         the little bit of Markdown the memory files use
├── conversations/
│   ├── context_budget.py   per-model policy, usage, when to hand over
│   ├── archive.py          thread_vNN.jsonl, sequential, never overwritten
│   └── rollover.py         the section 15A handover sequence
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

- **Seatbelt does not nest.** Applying a `sandbox-exec` profile inside an existing one
  fails with `sandbox_apply: Operation not permitted`, so the ten tests that start a child
  project cannot pass from inside `scripts/offline.sh` — `run_project` correctly refuses
  to run anything it cannot confine. `process_sandbox.sandbox_available()` now *probes*
  the capability by applying a trivial profile once, rather than checking that the binary
  exists, so those tests skip instead of failing. Do not weaken the sandbox to make them
  pass; failing closed is the point.
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

## 6. How memory works, now that it does

Phase 4 is built. `WORKORDER_01.md` §15A is the specification. Four decisions in it are
not obvious from the code, and one of them looks like a deviation until you read why.

**Memory is injected, never fetched.** There is no `search_memory` tool and there should
not be one. Adding a fifth tool cost 19 points of selection accuracy in Phase 1, and the
dominant failure was the model reaching for a lookup instead of acting. So when a child
says "like we talked about before", `memory/history_search.py` finds the answer
deterministically and the application puts it in the system prompt. The model never
chooses to search and cannot fail to.

**`project_state.md` is written but not injected — deliberately.** §15A lists it in the
new-thread bootstrap. `controller.project_state()` has injected the same facts live since
Phase 2, straight from the application, so reading the file back would put them in the
prompt twice and slightly stale. What the live block cannot know — the carried task and
open problems — *is* injected, via `project_state.carried_notes()`. Same for the handoff
summary: its decisions are merged into the bible and its "where we left off" line becomes
the carried task, so injecting the file as well would repeat both.

**Supersession is mechanical and depends on dropping numbers.** `compactor.subject()`
reduces a decision to its first three meaningful words with digits removed, so "Player
speed is 5" and "Player speed is 8" collapse to the same subject and the old one moves to
`## Superseded Decisions`. Keeping the number would miss the exact case the mechanism
exists for. Comparison is by prefix, not equality, because a restatement is usually
longer than the original.

**A rollover cannot fail because the model had a bad turn.** One call, plain prose under
two headings, leniently parsed, and a deterministic fallback built from facts when it
yields nothing. §15A requires that fallback in its own right.

Everything that writes a memory file goes through `memory/safety.py`, which secret-scans
first and drops the offending line. Chat archives too — a child can paste a key into chat
as easily as into a file.

### What is not done

- **Rollover latency is unmeasured with the real model.** Summarising sends the thread's
  prose back through the model a second time. Phase 1 measured prompt throughput at
  39.6 tok/s on a short prompt; if that figure holds for a few thousand tokens, a
  rollover is a visible pause after a turn. Measure it before Phase 10, and if it is bad
  the fix is to run the handoff on the worker thread rather than inline.
- **The live thread is not persisted as it grows.** It is archived at rollover and at
  close, so a crash loses the current transcript — never the project or the bible.
- **Memory quality has not been checked against the real model.** The loop is proven by
  `tests/test_rollover.py`; whether a 4B model writes a *good* handoff is a separate
  measurement, the way Phase 2 measured tool selection separately from tool wiring.

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
