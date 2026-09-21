# Handoff — start here

You are picking up Open Nest after Phase 6. **Phase 7 (remaining profiles) is next.**
This document is what you need before touching anything.

Three things before the rest.

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
| **7 — Remaining profiles** | **not started — yours** |

Branches are **stacked**: each is based on the previous one, so each PR shows only its
own phase. Nothing is merged to `main` yet. Branch from `phase-6-cloud`.

What works today: a child picks a project type, describes an idea, the local model edits
the project, it runs, they can undo, the project remembers its decisions across
conversations, and they can drag their own pictures, data and documents in and have the
project use them. A parent can add an API key, turn cloud on, and the child can switch to
Claude or OpenAI after a warning. Everything still works with cloud off, which is the
default.

456 tests pass, ruff is clean.

**Phase 7 is mostly not about cloud.** It is Raspberry Pi, Arduino, Research and Blank
profiles, plus DoD 32–34 (a Research project takes a dropped CSV and produces analysis
and a chart), which Phase 5 moved onto it. Two things Phase 6 left you: the
`arduino_upload` and `raspberry_pi_deployment` permission gates are built and enforceable
but have no consumer yet — call `controls.gate(name, approver)` when you add one — and
DoD 32–34 needs matplotlib working under Seatbelt, which means `MPLCONFIGDIR` inside the
project.

---

## 2. Get running in five minutes

```bash
.venv/bin/python -m pytest -q      # 456 passing
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
│   ├── cloud.py            HTTP + SSE for both cloud providers. Transport is injectable.
│   ├── anthropic_provider.py  Messages API. Most of it is message translation.
│   ├── openai_provider.py  Responses API. Same.
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
├── projects/               manifest, profiles, starter templates
├── execution/              out-of-process running, batch vs interactive
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
Nest stops and asks (cloud warning, parent PIN, permission prompt).

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

Phase 6 added a third concern that is not a boundary in the same sense.
`security/keychain.py` is the only place a credential lives, and
`security/permissions.py` is what a parent sets. Neither confines anything; they decide
what is permitted and where a secret may be. §6B has the detail.

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
| D6 | Image generation as an optional tab. OpenAI-only via `gpt-image-2` — Anthropic has no image model, so the picker must show the asymmetry honestly. **Now unblocked**: cloud access is built. It inherits two rules from Phase 5, recorded in PLAN.md — a generated image is an ordinary asset and goes through `assets.import_file`, and a model that generated a picture still has not *seen* it, so `can_interpret` governs what may be said about it | any time |
| — | Git author identity is currently `Open Nest <opennest@localhost>` until the setup wizard collects a real one | Phase 8 |
| — | Only one model is verified and downloaded. The other three local ones are pinned and described but untested, and **all three cloud entries are unverified against the real service** (SPIKES.md §11) | cloud: as soon as a key exists |
| — | All measurements are from a 48 GB Mac. The target is 8 GB | before V1 |

Resolved in Phase 6: the `claude-sonnet` context budget, which PLAN.md flagged for
revisiting. It came *down*, to 48000/36000, on cost rather than context — the reasoning
and the arithmetic are in `models.json`, so the next person raising it does so knowing
the per-turn price.
