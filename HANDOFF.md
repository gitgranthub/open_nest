# Handoff — start here

You are picking up Open Nest after Phase 5. **Phase 6 (cloud AI, credentials, parent
controls) is next.** This document is what you need before touching anything.

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
| 5 — Assets | complete, not yet in a PR |
| **6 — Cloud AI, credentials, parent controls** | **not started — yours** |

Branches are **stacked**: each is based on the previous one, so each PR shows only its
own phase. Nothing is merged to `main` yet. Branch from `phase-5-assets`.

What works today: a child picks a project type, describes an idea, the local model edits
the project, it runs, they can undo, the project remembers its decisions across
conversations, and they can drag their own pictures, data and documents in and have the
project use them. Everything is local; there is no cloud provider.

317 tests pass, ruff is clean.

---

## 2. Get running in five minutes

```bash
.venv/bin/python -m pytest -q      # 317 passing
```

**Run the test suite unwrapped.** It is hermetic — temporary directories, no network, no
model — so it needs nothing from the sandbox. Wrapping it in `scripts/offline.sh` used to
be the documented instruction and it was wrong: see "Seatbelt does not nest" in section 4.
A wrapped run is green now (233 passed, 16 skipped), but the skips are real coverage you
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
├── assets/
│   ├── kinds.py            what a file is, and which directory it belongs in
│   ├── describe.py         derived facts. The honesty rule lives here.
│   └── manager.py          copy-in import; the injected block — deliberately not a tool
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
  fails with `sandbox_apply: Operation not permitted`, so the twelve tests that start a child
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

Auditing that claim found two facts the live block genuinely did not carry, both now
fixed: the package list (the base prompt tells the model to stop rather than install,
while never saying what exists) and `manifest.last_successful_run`, which nothing wrote,
so the section that renders it was dead. If you add a section to `project_state.md`,
check which side of this line it falls on.

**`## Superseded Decisions` never reaches the prompt.** A model handed a list of things
that are no longer true will act on some of them. `Bible.render_for_prompt()` leaves it
out; the file keeps it for a person to read. §15A shows that section for the reader's
benefit, not the model's.

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
  prose back through the model a second time, and closing a project does the same. Phase
  1 measured prompt throughput at 39.6 tok/s on a short prompt; if that figure holds for
  a few thousand tokens, a rollover is a visible pause after a turn and quitting pauses
  too. Measure it before Phase 10. If it is bad, the lever is already there —
  `close(summarise=False)` — and the real fix is running the handoff on the worker
  thread rather than inline.
- **The recall cue list is an unmeasured heuristic.** `history_search.CUES` decides when
  the application searches memory. A phrasing nobody thought of is simply missed; the
  failure is soft, because the bible is in the prompt either way. It was deliberately not
  tuned by intuition — measure it, the way everything else here was.
- **The live thread is not persisted as it grows.** It is archived at rollover and at
  close, so a crash loses the current transcript — never the project or the bible.
- **Memory quality has not been checked against the real model.** The loop is proven by
  `tests/test_rollover.py`; whether a 4B model writes a *good* handoff is a separate
  measurement, the way Phase 2 measured tool selection separately from tool wiring.

---

## 6A. How assets work, now that they do

Phase 5 is built. `WORKORDER_01.md` §§10-13 is the specification. Four things are not
obvious from the code.

**The application may state facts about the file. It may never state facts about the
picture.** That is the whole of §13's "derived text or metadata", given a line you can
enforce. A PNG header gives the real format, the dimensions and whether there is an alpha
channel — checkable, and exactly what is needed to size a sprite and choose
`convert_alpha()`. What the image *depicts* is not in the header, so nothing says it. The
filename is the child's word for the file, not evidence about its contents; a description
that echoed it back would read as though something had looked, and
`test_nothing_derived_describes_what_the_picture_shows` fails if one ever does.

`describe.py` reports unknowns as unknown. A WebP variant it cannot parse yields a
description with no dimensions, never a plausible pair of numbers. Dimensions come from
`struct` and file headers, **not Pillow** — Pillow is in `requirements/projects.txt`, a
package child *projects* may import, not an application dependency, and the test suite
would stop being hermetic if it leaned on one.

**Every asset records whether anything has actually read it.** That is what generalises
the rule past images. A CSV has been read (the model can `read_file` it). A PNG, a sound
file and a PDF have not, and they are listed under one heading that says so. There is no
PDF text extractor and adding one is a dependency decision, not a gap to fill quietly.

**There is no `list_assets` tool, and there should not be one.** §18 lists it, and it is
the same mistake `list_project_files` was — SPIKES.md §4, 19 points of selection accuracy.
The application knows what has been imported, so `manager.context_block()` injects it, the
same treatment the file list gets and the same treatment §6 describes for memory.
`read_text_asset` needs no replacement either: an imported CSV is a file in the project.
A test pins the set at four tools with an attachment present.

**Not seeing a picture is not the same as ignoring what the child says about it.** The
block forbids invention and explicitly permits the child's own account — *if they tell
you what one is, believe them; if it matters and they have not said, ask.* An earlier
draft forbade both, which would also have forbidden acting on "use this picture for my
spaceship", and that sentence **is** DoD 27. If you tighten that wording, re-read it
against the DoD before deciding it is safer.

**The prompt is not enough, and this was measured.** SPIKES.md §10 ran the shipped
prompt against the real model: the honesty block took it from 38% to 50% honest, fixed
the useful half outright — it now answers "how big is my picture?" from the injected
facts instead of trying to read a PNG as text — and still produced *"Yes, the dragon in
the picture has wings. I see them clearly."*

So `assets.invented_description` checks, and `AgentController` pulls the model up once,
the same way it does for a claimed edit that never happened. That takes it to 62% and
removes every outright fabrication. Two things to know before you touch it:

- **It is narrow on purpose, and the narrowness is load-bearing.** Naming the file is
  fine. Repeating a word the child used is fine. A file that was actually read is never
  considered. The first version fired on the word *"with"* — extracted as a content word
  from `red-dragon-with-wings` — and an accusation triggered by an English function word
  is worse than the failure it guards against. `_EMPTY_NAME_WORDS` exists for that.
- **The fixtures in `tests/test_assets.py` are verbatim replies the real model gave.**
  If you change the check, those are the cases that matter; do not replace them with
  failures you imagined.

It costs a round-trip when it fires, which was on half the turns involving an unread
image. That is the price of not lying to a child, and it is recorded rather than hidden.

**The app refuses a model that cannot do the job.** `router.unmet_requirements(info,
profile)` compares what a profile needs against what a model does, and
`MainWindow._open_project` stops rather than opening. Today it has one rule because
there is one hard blocker: `gemma2-2b` is in the catalogue with `supports_tools: false`
and every profile works by calling tools, so it can discuss a game and cannot build one.
Not being able to see a picture is deliberately *not* a blocker — that is a limitation
the asset layer states honestly and works around. `models_for_project()` is the filtered
list a model picker should show.

**Capability messaging is a catalogue lookup, not a written-in sentence.**
`router.models_that_can_read(kind, allow_cloud=...)` filters `models.json` by
`supports_images` / `supports_documents`. Add a vision model to the catalogue and the
offer appears with no code change; turn cloud on in Phase 6 and Claude and OpenAI appear
the same way. `assets.can_interpret` is the one function that decides whether something
is readable here, and it is the one that changes when a provider can carry whole files.

### What is not done

- **Honesty is measured on one model, one filename, eight cases.** Read 62% as "the
  configuration is sound and the worst failure is gone", not "the agent is honest" —
  the same caution SPIKES.md §4 carries about 16/16 tool selection. Widen it before
  Phase 10.
- **An image cannot yet be *sent* to a model that could see it.** The capability
  plumbing is there and answers correctly; carrying bytes to a vision provider is Phase
  6's provider work, because there is no provider able to receive them.
- **The classification dialog asks once per dropped file.** One extra click on the
  commonest path. Correct, but worth watching a real child use before keeping it.

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
| D6 | Image generation as an optional tab, linked from Settings or the wizard. OpenAI-only via `gpt-image-2` — Anthropic has no image model, so the picker must show the asymmetry honestly. PLAN.md Phase 6 has the direction | after Phase 6 |
| — | Git author identity is currently `Open Nest <opennest@localhost>` until the setup wizard collects a real one | Phase 8 |
| — | Only one model is verified and downloaded. The other three are pinned and described but untested | when something needs them |
| — | All measurements are from a 48 GB Mac. The target is 8 GB | before V1 |
