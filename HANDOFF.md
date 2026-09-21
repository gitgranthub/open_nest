# Handoff — start here

You are picking up Open Nest after Phase 7. **Phase 8 (setup wizard and installation
lifecycle) is next.** This document is what you need before touching anything.

Three things before the rest.

**Four of the five profiles had never worked, and nothing said so.** `profiles.json`
named five starter templates and only `pygame_basic` existed; `create_project` skipped a
missing one silently, so Raspberry Pi, Arduino, Research and Blank each produced a
directory containing `project.json` and nothing else. No error. It dated from Phase 0 and
survived six phases. All six templates now exist, `create_project` raises before creating
anything, and a test checks each profile's entrypoint rather than just its template
directory. If you add a profile, that test is the one that will catch you.

**No profile's dependencies were installed on a fresh Mac — Games included.** The
bootstrap installed `base.txt` only, and `requirements/projects.txt` (pygame, pandas,
matplotlib, numpy, pillow) was installed by nothing. Games looked fine because developer
machines already had pygame. Both the bootstrap and `scripts/fetch.sh deps` now install
it: ~188 MB, against 1,179 MB of PySide6 the bootstrap already fetches.

**Actions that leave the project boundary are privileged, and that is a rule now, not a
one-off.** Ordinary project code stays confined exactly as it was. Upload, deploy, export
and publish are application actions with an explicit minimal grant each. §5 has the rule;
`process_sandbox.grant_devices` is the first instance. Read it before adding anything that
writes outside a project.

**All three cloud models are verified against the real services** — Sonnet 5, Haiku 4.5
and `gpt-5.6-luna` each pass every check in SPIKES.md §11, and Luna's repair loop,
rollover and truncation handling are verified in §13. Between them the real runs found
**nine defects the full hermetic suite could not see**. One made every Haiku call fail;
one made a reasoning model answer with total silence; one told a parent their perfectly
good key had been rejected; one was a sentence in the system prompt telling the model to
use a tool that refuses the job, billed once per turn for as long as it stood; and one
let a turn fix a child's game and then say nothing at all.

**A turn has one call budget and everything shares it** — twelve provider calls covering
the tool loop, repair, the honesty corrections, truncation recovery and rollover
(`agent/budget.py`, §6B). Before this each subsystem had a private allowance and nothing
counted the total.

**A vision model still cannot see a picture, and that is now enforced.** Neither cloud
provider transmits image bytes — `provider.IMAGE_INPUT_IMPLEMENTED` is False and says
so. Phase 6 briefly broke this: making Claude selectable made `can_interpret` answer
True, which removed the honesty block from the prompt *and* took the image out of the
set `invented_description` checks, while no pixels were sent. Both of Phase 5's defences
off at once. SPIKES.md §12 has it; read it before touching `can_interpret`.

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
| 6 — Cloud AI, credentials, parent controls | complete, committed on `phase-6-cloud`. All three cloud models verified against the real services |
| 7 — Remaining profiles | complete, committed on `phase-7-profiles`. Arduino compile verified against the real toolchain; upload hardware-unverified |
| **8 — Setup wizard and installation lifecycle** | **not started — yours** |

Branches are **stacked**: each is based on the previous one, so each PR shows only its
own phase. Nothing is merged to `main` yet. Branch from `phase-7-profiles`.

The review chain is 1 → 2 → 3 → 4 → 6 → 7 → 5. The PR numbers do not match the review
order, because #5 was opened before #6 and #7.

What works today: a child picks one of six project types, describes an idea, the local
model edits the project, it runs, they can undo, the project remembers its decisions
across conversations, and they can drag their own pictures, data and documents in and have
the project use them. A Research project turns a dropped CSV into analysis and a chart they
can see. An Arduino project compiles for a board they choose. A parent can add an API key,
turn cloud on, and the child can switch to Claude or OpenAI after a warning, or make
pictures with an image model. Everything except Image Creation still works with cloud off,
which is the default.

538 tests pass, ruff is clean.

**Phase 8 is the setup wizard**, and Phase 7 handed it two concrete items:

- **The Arduino toolchain needs a wizard step.** `scripts/fetch.sh arduino` installs it
  for development — pinned v1.5.1, SHA256-verified, into `$OPENNEST_HOME/tools` — but a
  parent has no way to get it. It is a ~17 MB binary plus **324 MB** of board cores, so it
  belongs behind a choice rather than in the default install. `arduino.available()` and
  `arduino.describe()` are what a health check should call.
- **`projects.txt` is now in the bootstrap**, which makes the install bigger. Worth
  showing in the wizard rather than letting it be a silent five-minute wait.

And one item raised after Phase 7 closed: **the app has no concept of its own version.**
`opennest.__version__` is `"0.1.0"` and only ever gets printed; `installation.json` is
declared in `paths.py` and never written. The work order does ask for safe updates after a
`git pull` (§"Repository update behavior", DoD 51–53), but only as migrations on the next
launch — not noticing that a new version exists, not pulling from inside the app, and not
restarting a running one. That is **D9**, and PLAN.md's Phase 8 section has the gap and the
traps written out.

Still with no consumer: `raspberry_pi_deployment`. §7 calls SSH deployment future, so
Phase 7 had nothing to gate without inventing a feature. When you build it, it takes the
privileged-action pattern in §5, not a new mechanism.

---

## 2. Get running in five minutes

```bash
.venv/bin/python -m pytest -q      # 538 passing, about 40 seconds
```

It is slower than it was (7 s at Phase 6). Phase 7 added tests that actually run each
profile's starter template under the real sandbox, which is the only way to tell "the file
was copied in" from "the file works" — and the distinction was the whole bug. The Arduino
and image tests are hermetic and fast; the profile runs are not.

**Run the test suite unwrapped.** It is hermetic — temporary directories, no network, no
model — so it needs nothing from the sandbox. Wrapping it in `scripts/offline.sh` used to
be the documented instruction and it was wrong: see "Seatbelt does not nest" in section 4.

**A wrapped run is not green, and this file used to claim it was.** Measured at Phase 7:
`scripts/offline.sh .venv/bin/python -m pytest -q` gives **4 failed, 501 passed, 33
skipped**. The four are in `tests/test_budget.py` and they fail the same way at the
Phase 6 commit, so this is not a Phase 7 regression — it is the nested-Seatbelt problem
again. Twelve tests were taught to *skip* when the sandbox cannot be applied; these four
exercise the repair loop, which runs the project, and they assert on a successful run
instead, so they fail rather than skip. Either teach them the same skip or give them a
stubbed runner. Until then: **run unwrapped.** The suite needs nothing the wrapper
provides.

If `.venv` does not exist yet, run `./Setup\ Open\ Nest.command` first. It installs its
own CPython 3.12.14 — do not expect a system Python to be usable.

**Development is two-phase, and this is not optional.**

| Phase | Command | Network |
|---|---|---|
| Fetch | `scripts/fetch.sh model <id>` / `deps` / `arduino` | **on**, pinned artifacts only |
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
│   ├── cloud.py            HTTP + SSE for both cloud providers. Transport is injectable.
│   ├── anthropic_provider.py  Messages API. Most of it is message translation.
│   ├── openai_provider.py  Responses API. Same.
│   ├── images.py           image generation. NOT a ModelProvider -- it answers no
│   │                       conversation, so it is not in the catalogue either.
│   └── router.py           curated catalogue; cloud needs the switch AND a key
├── agent/
│   ├── controller.py       the loop: prompt, tools, repair, checkpoints, rollover
│   ├── budget.py           ONE call budget per turn; every subsystem spends from it
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
├── projects/               manifest, profiles, starter templates (one per profile)
├── execution/
│   ├── python_runner.py    out-of-process running, batch vs interactive
│   ├── arduino.py          arduino-cli: is it here, boards, ports, compile, upload
│   └── outputs.py          which pictures a run produced. Deterministic, not a tool.
├── versioning/             git_manager, checkpoint, autosave, secret_scanner
├── security/
│   ├── sandbox.py          path confinement for Open Nest's own tools
│   ├── process_sandbox.py  Seatbelt confinement for code Open Nest runs
│   ├── keychain.py         the ONLY place a credential lives. No file I/O at all.
│   └── permissions.py      parent controls. Unanswered means no.
├── diagnostics.py          the Export Diagnostic Log report, scanned before it is returned
├── config/                 models.json, profiles.json   (data, not code)
└── prompts/                base + per-profile + build-style   (data, not code)
```

`ui/settings.py` is the six sections of §32; `ui/consent.py` is the three places Open
Nest stops and asks (cloud warning, parent PIN, permission prompt); `ui/new_project.py`
is the name-it-and-pick-an-idea dialog (§27's idea cards).

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

**Phase 7 traps, all measured (SPIKES.md §14):**

- **An Arduino sketch folder must be named after its sketch.** `arduino-cli compile src/`
  fails with `main file missing from sketch: src/src.ino`. The template is
  `src/project/project.ino` and the profile entrypoint carries the subdirectory. The
  obvious flat layout is the one that cannot compile, so this looks wrong until you try it.
- **Every `arduino-cli` call must name its data directory — including `version` and
  `board listall`.** Without it the tool creates `~/Library/Arduino15`, and containment is
  a promise this project makes. `arduino._environment()` exists for that; use it even for
  a read-only probe. I tripped this twice while measuring.
- **A confined Arduino compile needs three paths moved inside the project** (staging,
  sketchbook, build path), and it fails on them one at a time as you find them. The 324 MB
  toolchain stays *outside* and therefore read-only, which is the right way round: a
  compile cannot modify its own compiler.
- **`MPLCONFIGDIR` is a speed fix, not a correctness one.** matplotlib always worked under
  Seatbelt. Without a persistent cache it rebuilds its fonts every run: 6.1 s and three
  lines of stderr, against 0.2 s and silence. PLAN.md called it a blocker for two phases;
  corrected in place.
- **Opening a `/dev/cu.*` device blocks waiting for carrier.** An upload to an absent
  board hangs rather than erroring — that is what the timeout is for, and why a probe that
  writes to a real serial device appears to freeze.
- **`isVisible()` is False on a widget you never showed**, so a Qt test asserting
  `not thing.isVisible()` passes whatever the code does. Use `isVisibleTo(parent)`. One of
  my own tests was vacuous until I checked it.

---

## 5. Security model — do not weaken this

Two boundaries, doing different jobs:

| Layer | Protects | Does not protect |
|---|---|---|
| `security/sandbox.py` | Paths passing through Open Nest's own file tools | Anything a running process does |
| `security/process_sandbox.py` | Code Open Nest **runs** — no network, writes confined, kernel-enforced | — |

Phase 6 added a third concern that is not a boundary in the same sense.
`security/keychain.py` is the only place a credential lives, and
`security/permissions.py` is what a parent sets. Neither confines anything; they decide
what is permitted and where a secret may be. §6B has the detail.

The process sandbox is the real outer boundary. A single `open("/etc/passwd")` inside
generated code bypasses every path check. `run_project` **fails closed**: if the sandbox
cannot be applied, the project does not run.

### Privileged actions — the Phase 7 rule

Some things a child wants have to leave the project, because leaving it is the point:
putting a sketch on an Arduino, deploying to a Pi, exporting a game for a friend. Phase 7
found that the ordinary profile denies `/dev/cu.*` — which is what an Arduino *is* — so
upload could never have worked, whatever was plugged in.

The rule the developer set, which **generalises and should be reused**:

| | |
|---|---|
| Normal child code | sandboxed, unchanged |
| Compile | sandboxed, offline |
| Export / publish / deploy / upload | **privileged application actions** |

A privileged action is still sandboxed. It is granted **one more thing**, explicitly,
per action, and never let out. Specifically:

- Arduino upload may write to **only the selected `/dev/cu.*` device**, and stays behind
  the existing `arduino_upload` gate.
- No arbitrary `/dev`, filesystem, network or shell access is granted to support it. An
  upload is still offline.
- The grant is **enforced, not intended**: `process_sandbox.grant_devices` refuses
  anything that is not a serial port, because the port string comes from outside the
  application. `/dev/disk0`, `/etc/passwd`, `/dev/ttys000` and
  `/dev/cu.ok/../../etc/passwd` are all rejected, with tests.
- An ordinary profile is **byte-identical** to before this existed —
  `build_profile(p) == build_profile(p, devices=())` is a test, so the capability cannot
  quietly leak into normal runs.
- A privileged action that cannot be verified because hardware is absent is
  **implemented, gated, and marked verification-pending** rather than blocking a phase.
  That is the current state of upload.

Do not reopen this architecture unless implementation reveals a concrete security
limitation. When you build Pi deployment or file export, they take this pattern.

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
`supports_images` / `supports_documents`. `assets.can_interpret` is the one function
that decides whether something is readable here.

Phase 6 added a hard-won qualification to both: **a capability flag on a model is not a
capability of the system.** `supports_images: true` on the Claude entry is correct —
Claude really can see pictures — but Open Nest sends it none, so the honest answer for
an image is still no. `provider.IMAGE_INPUT_IMPLEMENTED` is what carries that, and both
functions consult it. See §6B and SPIKES.md §12 for what happened when only the model
flag was checked.

### What is not done

- **Honesty is measured on one model, one filename, eight cases.** Read 62% as "the
  configuration is sound and the worst failure is gone", not "the agent is honest" —
  the same caution SPIKES.md §4 carries about 16/16 tool selection. Widen it before
  Phase 10.
- **An image cannot yet be *sent* to a model that could see it.** Phase 6 built the
  providers but not image transmission, so this is still true — and §6B explains why
  that briefly became dangerous rather than merely incomplete once a vision model became
  selectable. `provider.IMAGE_INPUT_IMPLEMENTED` now holds the line.
- **The classification dialog asks once per dropped file.** One extra click on the
  commonest path. Correct, but worth watching a real child use before keeping it.

---

## 6B. How cloud, credentials and parent controls work

Phase 6 is built. `WORKORDER_01.md` §§21-25 and §32 are the specification. Six things are
not obvious from the code.

**A cloud model needs two separate permissions, and conflating them is the bug to avoid.**
The master switch (`controls.cloud_allowed()`) and a key in the Keychain are different
facts with different remedies, and the child sees a different sentence for each.
`router.is_available()` is where they meet; `router.why_unavailable()` is the sentence.
This tightened a Phase 5 prediction: §6A said turning cloud on would make
`models_that_can_read` start offering Claude with no code change, and it does — but only
with a key, because Phase 5's own rule is that the child is never sent after a model they
cannot reach.

**The picker still shows a model it will not let you pick.** Disabled, with the reason.
Hiding an unusable cloud model leaves a parent hunting for where Claude went, and
DESIGN_DOC §13 lists INTERNET as a visible section of the picker.

**Model-specific request shapes are in `models.json`, not in Python.** `provider_options`
is merged into the request body untouched. That is how Sonnet 5 declares
`thinking: {"type": "adaptive"}` while Haiku 4.5 declares the `budget_tokens` form that
Sonnet **rejects with a 400** — both confirmed against the real service. If you add a
cloud model, its request quirks go in the catalogue.

**Request parameters follow declared capabilities, never an inference.**
`supports_temperature` and `supports_thinking_budget` are per-model fields the providers
read. An earlier version omitted `temperature` whenever a thinking block was present; it
produced the right request for both catalogue entries and was still wrong, because a
model that thinks and *also* takes a temperature would have been silently denied one.
`test_thinking_does_not_by_itself_suppress_temperature` is the test that pins the
difference. Both flags were verified by contradicting them against the live API, so they
are measurements rather than claims.

Note what that costs: **neither Claude model can be pinned to temperature 0.** Phase 1
measured temperature 0 as load-bearing for tool selection on a 4B local model; it is not
the same risk here, and the deterministic checks
(`_claimed_a_change_it_did_not_make`, `assets.invented_description`) run against whatever
produced the sentence, which is the reason they were built that way.

**One call budget per user turn, shared by everything.** `agent/budget.py`. The tool
loop, the repair cycle, both honesty corrections, a truncation retry and the rollover
all spend from the same twelve calls — no subsystem has a private allowance, because
nothing was counting the total and on a cloud model every one of those is billable.
`MeteredProvider` wraps the provider and is handed to the controller, the memory manager
and rollover alike, so a rollover is counted without `conversations/rollover.py` knowing
budgets exist. That only works because of §21's single interface.

Three things about it that are easy to get wrong again:

- **Calls are counted on dispatch, not on completion.** A call that dies mid-stream is
  still a call. Counting only successes made failures free, and a free failure is one a
  retry loop repeats forever.
- **Twelve is measured, not chosen.** The worst real turn used five calls; the longest
  constructible legitimate path is ten. SPIKES.md §13 has the arithmetic. It is
  deliberately loose — the real spend limit belongs on the API key.
- **`Turn.usage` is provider-reported throughout.** Never inferred from reply length: a
  reasoning model's bill has no relationship to what appeared on screen.

**An output cap covers hidden work as well as the answer, on both services, and the
provider has to reserve room for it.** This bit twice, in different costumes:

- Anthropic's `max_tokens` covers thinking *and* the reply. With a 4000-token budget and
  the `Settings` default of 1200, **every Haiku call failed**. `_make_room_for_thinking`
  reconciles them.
- OpenAI's `max_output_tokens` covers reasoning *and* the reply. gpt-5-mini given 120
  spent all of it reasoning and streamed **nothing** — a success by every mechanical
  measure, silence to a child. `output_headroom_tokens` gives it room, and
  `raise_if_silently_truncated` makes an empty reply say why it is empty.

That field was called `reasoning_reserve_tokens` until Luna was measured properly
(SPIKES.md §13): reasoning turned out to be 14–334 tokens, while a long answer wanted
2,179 against a default cap of 1,200. It is headroom for the whole output, and is now
named for that. **Do not shrink it to control verbosity** — a cap does not make a model
concise, it makes it stop mid-sentence. `prompts/base.txt` is where brevity is asked
for.

In both cases the budget comes from the catalogue and the cap from the caller, and
neither knows about the other — the provider is the only place that sees both. Hidden
tokens are billed and never appear on screen, which is why Haiku's budget is 1024 rather
than something generous.

**A model the key cannot reach is said out loud, never worked around.** §38 forbids
substituting a model behind the user's back, so there is no fallback: `cloud.http_error`
detects the model-access case and stops. Getting there took a fix — OpenAI returns
**403** for it, so it was hitting the auth branch and telling parents their good key had
been rejected. The model check now runs ahead of the auth check, on the body rather than
the status.

**"Ask Parent" with nobody to ask is a refusal.** `permissions.gate()` returns False when
a permission is set to `ask` and no approver was supplied. This is why
`Toolbox.network_policy` is a *callable*: the answer can be a dialog, so it cannot be
known when the project opened. `build_profile(allow_network=)` has been sitting unused
since Phase 2 — §25 is what finally supplies it, and the default is still no.

**`security/keychain.py` has no file I/O, and that is the design rather than an
accident.** §22 lists everywhere a key must not appear; the cheapest way to satisfy most
of that list is for the module that holds keys to be unable to write anything. Related
guards, all tested: `permissions.save()` refuses anything credential-shaped (nothing puts
a key there — the guard exists for the change that one day would), `cloud.redact()`
scrubs a key out of any server error before it reaches a dialog, and
`diagnostics.report()` scans its own output before returning it. The parent PIN is stored
as a salted PBKDF2 hash, so reading the Keychain item does not yield the PIN.

One thing to know about testing near this: **nothing in the suite may touch the real
Keychain.** A test whose result depends on whether you happen to have saved a key is not
a test. `tests/conftest.py` has `FakeKeyring` and the `credentials` /
`configured_credentials` fixtures; anything that reads a credential takes an injected
store. `Workbench`, `MainWindow`, `SettingsWindow` and `router.build_provider` all accept
one for this reason.

### What is not done

- **No provider sends an image to a model.** `IMAGE_INPUT_IMPLEMENTED` is the flag; it
  is False, and both `can_interpret` and `models_that_can_read` respect it, so the
  behaviour is honest. But it means a vision model buys the asset layer nothing today.
  Implementing transmission means image content blocks in both message translators,
  a size limit, and deciding whether only *attached* images travel. Flip the flag and
  delete the `can_send_images` test fixture in the same change.
- **No long real session has been run.** Repair, rollover and truncation have Sonnet
  and Luna parity (SPIKES.md §13), but every measurement is one or two turns — rollover
  was forced with a 900-token threshold rather than reached at 36,000.
- **No long session has been run.** Rollover was forced with a 900-token threshold, not
  reached naturally at 36,000, so per-session cost is still arithmetic.
- **Image generation is proved reachable but unbuilt.** SPIKES.md §12: 
  `gpt-image-2.5-flare` returns a PNG inline as base64 in 10–15 s, and it imports and
  describes correctly through the Phase 5 asset path. The D6 tab itself — prompt UI,
  size and quality, cost display, where the button lives — is not started, and the image
  model is deliberately not a `models.json` entry.
- **There is no logging subsystem.** §33 asks for one. Export Diagnostic Log exists and
  builds its report from live state, so "no key in any log" is currently true because
  there is no log. If you add one, it inherits §33's list and the same self-scan.
- **`arduino_upload` and `raspberry_pi_deployment` have no consumer.** Declared,
  configurable, enforceable, unused until Phase 7.
- **Cloud rollover is a billable extra call.** SPIKES.md §9's unmeasured latency question
  now has a cost dimension: summarising a 36000-token transcript through Sonnet costs
  real money at every rollover and at every close. Same lever (`close(summarise=False)`),
  higher stakes.
- **No parent PIN exists until Phase 8's wizard collects one.** Parent Settings opens
  without one and says so plainly rather than implying a lock it does not have.

---

## 6C. How the six profiles work, now that they all do

Phase 7 is built. `WORKORDER_01.md` §§5, 7, 8, 9, 27 and 30 are the specification. Five
things are not obvious from the code.

**A profile is data, and now that includes how it *finishes*.** `run_mode` had two values
and has three: `interactive` stays on screen until the child closes it (games, a Pi test
loop), `batch` runs to completion and is captured (an analysis, a compile), and
`generate` runs **nothing at all**. Image Creation is the only `generate` profile, and
the reason is the security model rather than convenience: the process sandbox denies
network, so a child's own code could never reach an image service. Generation has to be
an application action. `test_every_profile_gives_the_child_a_button_that_does_something`
pins that a profile has a run command, a compile command, or `generate` — and never both
a command and `generate`.

**The main button dispatches by profile, and used to not.** `Workbench._run` always sent
`run_project`. An Arduino project has no run command and no such tool, so a child pressing
**Compile** got the Toolbox's refusal written for a model: *"'run_project' is not
available here. You can use: read_file, edit_file, write_file, compile_project."* If you
add a profile, check what its button actually does — this was invisible to every test and
to six phases of reading, and took one button press to find.

**Nothing about the Arduino profile invents hardware.** §8 forbids inventing pin
assignments, and Phase 7 extended that in two directions. The board list and port list
come from `arduino-cli board listall` / `board list`, so a picker shows what is installed
rather than what someone typed into a constant. And **no board is preselected** — picking
a board for a child picks every pin on it, so an unset board makes both the tool and the
UI ask. The starter sketch uses `LED_BUILTIN` rather than pin 13 for the same reason: it
asserts nothing about how anything is wired. There is a test for each of those three.

**Chart display is injected knowledge, not a tool — the same rule as everything else
here.** `execution/outputs.py` compares the project's pictures before and after a run and
shows the newest thing that changed. The alternative is asking the model where it saved
the chart, and a model reporting a path can report the wrong one, forget to, or invent it
— which is §6A's whole problem in a new costume. Comparing the directory cannot be wrong
about what is on disk. It is deliberately not Research-specific: "a picture appeared" is
a fact about a run.

**Image Creation is a profile, and the honesty rule survives it.** This is the important
one. Open Nest asks for the picture and saves it, and **still has not seen it**:
`can_interpret` answers False, the file is listed as unread, and the prompt still carries
`NOBODY HAS LOOKED`. That is exactly the configuration §6B describes Phase 6 breaking, so
it has its own test (`test_generating_a_picture_is_not_seeing_it`) and the reply the child
sees says so in as many words. The image model lives on the profile rather than in
`models.json`, because a catalogue entry is something that answers a conversation.

### What is not done

- **Upload has never reached a board.** No Arduino has been attached to a machine running
  this code, so the serial-port grant is known to be *necessary* (the ordinary profile
  denies `/dev/cu.*`, measured) and not known to be *sufficient*. Everything up to opening
  the port is exercised. Plug one in and run `spikes/spike_arduino.py`.
- **Only the AVR core is installed**, so `board listall` returns 27 boards and no ESP32 or
  SAMD. A child with a Nano 33 or a Pico gets a board list that does not contain their
  board, which is honest but unhelpful. Installing another core is
  `arduino-cli core install`, and it needs network — a Phase 8 wizard question.
- **§30's "Show technical details" toggle is not built.** Raw stderr still goes to the
  Build/Preview panel. Deliberately out of scope, left for the Phase 10 polish pass, and a
  compiler diagnostic is the case that most needs it.
- **`raspberry_pi_deployment` still has no consumer.** §7 calls SSH deployment future. It
  takes the §5 privileged-action pattern when it arrives, not a new mechanism.
- **The Pi profile is only tested on a Mac**, which is the point of its design but does
  mean the real `RPi.GPIO` branch of the starter template has never run. The shim is
  structured so that branch is the only untested part.
- **Image generation cost is not shown anywhere.** ~800 KB and 10-15 s per image at
  `quality=low`, billed per image. A parent can see neither a count nor a total. D6's
  note about cost display is still open.
- **One image was generated to verify the profile path**, and that is all the real
  measurement there is. Nobody has used this for an hour.

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
| D9 | **How the app updates itself, and whether checking is a parent-controlled action.** The work order already asks for migration *after* someone runs `git pull` (§"Repository update behavior", DoD 51–53). Noticing that upstream moved, pulling from inside the app, and restarting safely are all past that — PLAN.md's Phase 8 section has the gap analysis and the five traps. An update check is the *application* reaching the network, which `external_requests` does not govern | Phase 8 |
| D7 | **Which Arduino board cores to install.** Only `arduino:avr` is installed (324 MB, 27 boards). ESP32, SAMD and RP2040 are each another download, and a child whose board is missing sees an honest but useless list. Installing everything is gigabytes; installing on demand needs network mid-project | Phase 8 wizard |
| D8 | **Whether image generation shows its cost.** ~800 KB and 10–15 s per image, billed per image, with no count or total anywhere. A parent who turned cloud on for chat has also turned this on | before real use |
| — | Git author identity is currently `Open Nest <opennest@localhost>` until the setup wizard collects a real one | Phase 8 |
| — | Only one model is verified and downloaded. The other three local ones are pinned and described but untested | — |
| — | All measurements are from a 48 GB Mac. The target is 8 GB | before V1 |

Resolved in Phase 6: the `claude-sonnet` context budget, which PLAN.md flagged for
revisiting. It came *down*, to 48000/36000, on cost rather than context — the reasoning
and the arithmetic are in `models.json`, so the next person raising it does so knowing
the per-turn price. Also resolved in Phase 6: all three cloud entries are now verified
against the real services (SPIKES.md §11).

**Resolved in Phase 7 — D6.** Image generation is a **profile card, not an optional tab**:
a child looks for "a thing I can make" on the Flight Deck, not in a tab. The image model
stays out of `models.json` because a catalogue entry is something that answers a
conversation. Both Phase 5 rules it inherits are implemented and tested — a generated PNG
goes through `assets.import_file`, and generating is not seeing. What D6 also asked for and
did **not** get is cost display, which is now D8.

**Also resolved in Phase 7:** the sandbox-versus-privileged-action question, recorded as a
design rule in §5 and in PLAN.md rather than as a decision, because it applies to Pi
deployment and file export as much as to Arduino upload.
