# Open Nest — Implementation Plan

Working plan derived from `WORKORDER_01.md` (functional scope) and `DESIGN_DOC.md`
(naming and visual direction). This document records phases, exit criteria, decisions,
and open questions. It is expected to be amended as work proceeds.

Status: **Phases 0-5 complete. Phase 6 (cloud AI, credentials, parent controls) is next.**

New developers should start with [HANDOFF.md](HANDOFF.md).

Phase 1 measurements are in [SPIKES.md](SPIKES.md).

---

## 1. Naming decision

`WORKORDER_01.md` uses the placeholder name "Build Lab". `DESIGN_DOC.md` §21 supersedes
it wherever naming is not already locked. Nothing is locked — the repository contains no
code — so Open Nest naming is used from the first commit:

```text
Build Lab   → Open Nest
BuildLab    → OpenNest
buildlab    → opennest
.buildlab   → .opennest
```

Launchers: `Setup Open Nest.command`, `Launch Open Nest.command`.
Future bundle: `Open Nest.app`.

Read every "Build Lab" in the work order as "Open Nest".

---

## 2. Constraints and risks identified during document review

### 2.1 No modern Python exists on a target Mac

The development Mac (macOS 15.7.9, arm64) has **only the system Python 3.9.6**. No
Homebrew Python, no pyenv, no uv, no python.org framework build. A parent's Mac should be
assumed to be the same or worse.

Consequences:

- Everything under `bootstrap/` must **run correctly on Python 3.9**. It is the code that
  runs *before* a modern interpreter exists. No `match`, no PEP 604 (`X | Y`) annotations
  evaluated at runtime, no `tomllib`, no 3.10+ stdlib.
- The bootstrap must be able to **acquire** Python 3.12+ without `sudo` (work order §35A:
  "The launcher should not require `sudo` for normal installation"). Running the
  python.org `.pkg` prompts for an admin password, so it cannot be the primary path.

**Resolved in Phase 0** (decision D5). `bootstrap/python_setup.py`:

1. Use a suitable existing interpreter (3.12+) if one is found, preferring Open Nest's own.
2. Otherwise download a pinned [python-build-standalone] arm64 build into
   `~/Library/Application Support/Open Nest/python/<version>/`, verify it against the
   project's published SHA256, and unpack it there. No admin rights, self-contained,
   uninstalled by deleting one folder.

This turned out to block Phase 0 rather than Phase 1: the development Mac could not run
the app at all until it was implemented, and a parent's Mac is the same case by default.

Pinned build: CPython **3.12.14**, release `20260901`. 3.12 rather than 3.13/3.14 for the
widest wheel availability across PySide6, mlx, pygame, pandas and matplotlib. Bumping it
is a deliberate edit to the constants in `bootstrap/python_setup.py`, including a fresh
checksum from the release's `SHA256SUMS`.

[python-build-standalone]: https://github.com/astral-sh/python-build-standalone

### 2.2 Tool-calling reliability on a 3–4B local model — highest technical risk

The entire agent design assumes a local model in the 3–4B range can emit well-formed tool
calls consistently. If it cannot, the agent layer needs a different shape (constrained
decoding, a stricter single-tool-per-turn protocol, or a larger default model).

**Measured in Phase 1 — see [SPIKES.md](SPIKES.md) §4.** Viable, but only in a specific
configuration: naive use gives 50% correct tool selection. The agent layer must not expose
an "explore" tool, must keep ≤4 tools live, and must inject deterministic file state.

### 2.3 8 GB unified memory is genuinely tight

Baseline target must simultaneously hold: 4-bit ~4B model weights, the PySide6 app, and a
child project process (Pygame window or a pandas/matplotlib run). Required from the start:

- Project execution always happens **out of process**.
- An explicit model load/unload policy (unload on idle, unload before a heavy run).
- Measured, not assumed, memory figures — see Phase 1.

### 2.4 Model identifiers in the work order are illustrative

"Qwen 3.5 4B", "Gemma 3 4B", "Llama 3.2 3B" and their download sizes must be resolved
against real `mlx-community` repositories and quantizations at implementation time. They
live in `config/models.json` so that correcting them is a data edit, never a code change
(work order §3: "Do not hard-code individual model logic throughout the application").

### 2.5 Other notes

- Non-vision models must never be fed an image and allowed to pretend they saw it. They
  receive derived text/metadata, and the UI says so plainly and offers a capable model
  (work order §13).
- Keychain is the only permitted location for API keys. Not config, not `.env`, not logs,
  not prompts, not project memory, not Git.
- GitHub auth approach remains an open decision (§4, D1).

---

## 3. Architecture summary

Per work order §39/§40, renamed:

```text
opennest/
├── app.py
├── ui/            main_window, flight_deck, workbench, chat_panel,
│                  file_panel, asset_panel, settings, theme
├── ai/            router, provider, mlx_provider, openai_provider, anthropic_provider
├── agent/         controller, tools, permissions, repair_loop
├── conversations/ context_budget, rollover, archive
├── memory/        manager, project_bible, project_state, compactor, history_search,
│                  safety, markdown
├── projects/      manager, profiles, templates/
├── assets/        manager, image_handler, document_handler, data_handler
├── execution/     python_runner, pygame_runner, arduino_runner
├── versioning/    autosave, git_manager, github_manager, checkpoint, secret_scanner
├── prompts/       base.txt, games.txt, raspberry_pi.txt, arduino.txt, research.txt
├── security/      keychain, sandbox
└── config/        models.json, profiles.json

bootstrap/         bootstrap, environment, python_setup, dependency_check,
                   model_setup, github_setup, installer_ui   (Python 3.9-compatible)
requirements/      base.txt, macos-apple-silicon.txt, projects.txt, dev.txt
scripts/           sandbox.sh, fetch.sh, offline.sh     (contained development)
```

Guiding rules:

- Profiles, models, and prompts are **data**, not code.
- The bootstrap layer must not import the application runtime.
- Model verification during setup runs a real inference through the **app's own provider
  code**, never an installer-only implementation (work order §35A).

Three departures from the sketch above.

Phase 4: `conversations/manager.py` was not built — `AgentController` already owns the
message list, and a second owner of it is how Phase 2 broke checkpointing.
`memory/safety.py` and `memory/markdown.py` were added instead — one choke point for
writing memory files, secret-scanned, and the small amount of Markdown those files rely
on being able to parse back.

Phase 5: `assets/` is `kinds.py`, `describe.py` and `manager.py` rather than
`image_handler` / `document_handler` / `data_handler`. Those three would have been three
small functions; splitting by job instead of by file type keeps the rule that matters —
what may honestly be said about a file — in one place rather than repeated three times.

---

## 4. Open decisions

| # | Decision | Needed by | Current lean |
|---|---|---|---|
| D1 | GitHub auth: registered OAuth App (device flow) vs. shelling to `gh` vs. PAT fallback | Phase 9 | `gh` is now authenticated on the dev machine, which is a viable path; it authenticates the parent's account, so revisit in Phase 9 |
| ~~D2~~ | ~~Default local model + quantization~~ | ~~Phase 1~~ | **Resolved**: `mlx-community/Qwen3-4B-Instruct-2507-4bit` @ `50d4275`. Apache-2.0, 2.61 GB resident, 92.5 tok/s |
| ~~D3~~ | ~~Tool-call format~~ | ~~Phase 1~~ | **Resolved**: native `<tool_call>` template, temp 0, ≤4 tools, file state injected rather than listed via a tool |
| D4 | Projects directory location | Phase 0 | `~/Open Nest/Projects` (mirrors work order's `~/BuildLab/Projects`) |
| ~~D5~~ | ~~Vendor a standalone Python vs. require Homebrew/python.org~~ | ~~Phase 1~~ | **Resolved in Phase 0**: vendor a pinned, checksum-verified standalone build (section 2.1) |

---

## 5. Phases

Each phase ends in something demonstrable. Phases 2–9 map onto the Definition of Done
scenario in work order §42 (referenced as "DoD n").

### Phase 0 — Skeleton and conventions — **complete**

- Repository layout above, with Open Nest naming throughout.
- `config/models.json`, `config/profiles.json`, `prompts/*.txt` present as data. Every
  model entry carries `verified: false` until Phase 1 checks it against a real repository.
- `opennest/paths.py`: projects root, application support, logs, model store.
- `Setup Open Nest.command` + `Launch Open Nest.command`, Python 3.9-safe, no `sudo`,
  including the vendored-interpreter path described in section 2.1.
- `opennest/ui/theme.py` — design tokens and stylesheet, light and dark, built now so
  styling is not retrofitted in Phase 10.
- Tooling: `pyproject.toml`, ruff, pytest, `requirements/dev.txt`.

**Exit criterion met.** On a Mac with only Python 3.9.6, the setup launcher installed
CPython 3.12.14, created `.venv`, installed PySide6 6.11.2 and keyring, and opened the
themed window. 32 tests pass; ruff is clean.

Known gap carried forward: the launcher currently starts the app detached with no error
surface if the app itself fails at startup. Phase 8 replaces this with the real wizard and
proper reporting.

### Phase 1 — Risk spikes — **complete**

Deliverable: [SPIKES.md](SPIKES.md). D2 and D3 resolved.

Added beyond the original scope, at the request of the developer: a contained,
network-isolated development sandbox (`scripts/sandbox.sh`, `scripts/fetch.sh`,
`scripts/offline.sh`). Third-party artifacts are fetched pinned with network on, then
executed with network denied and writes confined to the project, enforced by macOS
Seatbelt without root. One model was downloaded rather than the full candidate set.

Headline results:

- Tool calling is **viable but configuration-sensitive**: 50% correct tool selection
  naively, 100% on 16 single-turn cases once `list_project_files` is replaced by injected
  file state and a one-tool nudge is added. Treat this as "the configuration is sound",
  not "the agent is reliable" — multi-turn behaviour is still unmeasured.
- Memory is not the constraint it was feared to be: 2.74 GB for model, app and a running
  project combined.
- **Defect found:** `mlx_lm.load()` reaches the network even for a cached model, which
  would have broken offline operation (work order §34). Phase 2 must resolve the local
  snapshot path first.

### Phase 2 — Core vertical slice (Games, local model only)

Project manager, manifest, profile loader, Pygame starter template; provider interface +
MLX provider with streaming + model router; agent with `read_file`, `write_file`,
`run_project`, `inspect_error` (**not** `list_project_files` — see SPIKES.md §4); sandbox
path confinement and timeouts; Flight Deck and Workbench; repair loop capped at 3 attempts.

Carries these obligations from Phase 1: resolve models to a local path before loading and
test it with `HF_HUB_OFFLINE=1`; normalise tool names before dispatch; port
`scripts/offline.sh` into `opennest/security/sandbox.py` as the child-code boundary.

**Exit criterion met.** An idea becomes a project, the model edits it correctly, and it
runs. Measured 5/6 on varied change requests end to end with the real local model,
offline. 114 tests, ruff clean.

Three design changes were forced by measurement rather than chosen up front:

- **`edit_file` replaced whole-file writes as the primary edit tool.** Asked to reproduce
  a whole file inside a JSON string, the model emitted Python triple-quotes and produced
  unparseable output. Targeted edits scored 5/5 against write_file's 4/5, and offering
  both together scored worse than either alone.
- **`write_file` now refuses to overwrite** and both write paths reject syntactically
  invalid Python. A run that left a child's working game broken is a far worse outcome
  than a refused edit the model can retry.
- **The Phase 1 "call exactly one tool" nudge had to be rewritten.** It was measured on
  single-turn selection; carried into a multi-turn loop verbatim it caused the model to
  read a file and then *claim* an edit it never made. The application now also checks
  for that claim deterministically rather than trusting the prompt.

Known gaps carried to Phase 3: nothing is saved to Git yet, there is no undo, and the
Workbench transcript is not persisted.

### Security review follow-ups

Raised in review of the Phase 2 sandbox. The first three are done in that branch; the
fourth is deliberately deferred.

- **Done** — `.env` and the rest of the secret family are now unreadable as well as
  unwritable. Reading a credential is how it ends up quoted into a reply, a prompt or a
  commit, and relying on `visible_files()` hiding it was never protection: the model can
  name a path it was never shown.
- **Done** — case-variant protected paths. This was a *live bypass*, not a missing test:
  macOS is case-insensitive by default, so `.GIT/HEAD` opened `.git/HEAD` while the
  Python comparison saw two different strings. Every protected directory was reachable by
  changing the case. Comparison is now casefolded.
- **Done** — the boundary is documented, and made real. `run_project` now runs every
  project under macOS Seatbelt with no network and writes confined to the project,
  failing closed if the sandbox cannot be applied. Previously the process sandbox existed
  only as a development script, so the "outer boundary" was aspirational.
- **Deferred — TOCTOU.** `resolve_in_project()` validates a path and returns it; the
  caller opens it afterwards, so in principle a symlink could be swapped in between.
  Under the stated threat model — a confused 4B model, not hostile local code able to
  race the process — this is accepted. Hardening means holding an open descriptor inside
  the module (`os.open` with `O_NOFOLLOW`, then `openat` relative to a directory
  descriptor) and handing callers descriptors rather than paths, which changes every
  tool signature. Revisit if the threat model ever includes untrusted local code.

### Phase 3 — Durability

Atomic writes, dirty-state tracking, autosave; per-project Git init with generated
`.gitignore` and repo-scoped identity; checkpoint commits at meaningful events; Undo and
Checkpoint restore in child-facing language; interrupted-session recovery on startup.

**Exit:** DoD 31; killing the app mid-edit recovers cleanly.

### Phase 4 — Memory and thread rollover — **complete**

`.opennest/project_bible.md` and `project_state.md`, with deterministic fields written by
the application and semantic content by the model; per-model context budget; handoff
summary generation; `conversations/thread_vNN.jsonl` archive plus summaries; new-thread
bootstrap composition; history search; compaction.

**Exit criterion met.** DoD 39–43 is proved end to end in
`tests/test_rollover.py::test_the_thread_rolls_over_and_the_new_one_remembers`, with a
scripted provider and a threshold of 300 tokens: two turns cross it, `thread_v01` is
archived, the manifest advances to thread 2, the new thread starts with the bootstrap
alone, and the child's next message — "like we talked about before" — is answered from
the bible rather than the conversation, which is gone. A companion test asserts that no
text the child sees contains "context", "thread", "rollover", "new chat" or "summar".
249 tests, ruff clean.

Four decisions were re-examined after the first implementation. Two stood, one exposed a
real gap, and one was wrong.

**No `search_memory` tool — stands.** §15A asks the agent to search memory before saying
it does not remember; a fifth tool would have cost the accuracy Phase 1 measured. The
application searches deterministically when the child's phrasing refers to the past and
injects the result, exactly as it injects the file list. The trigger is a cue-phrase list
(`history_search.CUES`) and is an unmeasured heuristic: it can miss a phrasing nobody
thought of. The failure is soft — the bible is in the prompt regardless — so the list was
deliberately *not* tuned by intuition. It is on the SPIKES follow-up list instead.

Rejected alternative: search on every turn and inject above a relevance threshold. It
removes the brittle trigger but the block's framing ("they are referring to something
from before, treat it as true") is wrong for an ordinary request, and over-anchoring a 4B
model on a past decision it was about to change is a worse failure than missing a cue.

**`project_state.md` written but not injected — stands, and exposed two real gaps.** The
live block in `controller.project_state()` already carries the same facts, more
accurately. But auditing the claim found two things it did *not* carry, both fixed:

- **Dependencies were never in any prompt.** The base prompt tells the model to stop
  rather than install a missing package, while never telling it which packages exist.
  `project_state()` now lists `profile.packages`. This was a gap from Phase 2.
- **`manifest.last_successful_run` was never written**, so the "Last Successful Run"
  section could never render — a dead path. `run_project` now records it, which is what
  §15A means by populating run status programmatically.

After those, everything in `project_state.md` is either in the live block or carried by
`project_state.carried_notes()`, and the decision is sound rather than merely convenient.

**Supersession drops numbers from a decision's subject — stands, with the prompt
tightened.** "Player speed is 5" and "Player speed is 8" must collapse to one subject or
the §15A example never triggers. Subjects compare by prefix rather than equality, because
a restatement is longer than the original — caught by a test before it shipped. It is a
heuristic and can mis-fire on a two-word subject that prefixes a three-word one; the harm
is bounded because nothing is deleted until `MAX_SUPERSEDED` entries accumulate.

What did change: `## Superseded Decisions` is no longer rendered into the prompt. A model
handed a list of things that are no longer true will act on some of them. The file keeps
the record for a person to read; the prompt gets current truths.

**Quitting used to skip the handoff generation — reversed.** The original reasoning was
that an application must not pause on Command-Q. That traded away the wrong thing. A
session long enough for summarising to be slow has *already* rolled over, so the
transcript left at close is bounded by the rollover threshold and is usually far shorter;
quit latency and rollover latency are the same unmeasured number. Special-casing quit
bought a bounded saving at the cost of losing the decisions of every session that never
crossed the threshold — which is most short sessions, and exactly the ones that updating
memory at close exists for. `close(summarise=False)` remains as the lever if the latency
measurement comes back badly.

Carried forward: rollover latency with the real model is unmeasured, the recall cue list
is unmeasured, and the in-progress thread is not persisted until it is archived.

### Phase 5 — Assets — **complete**

Copy-in import; drag-and-drop onto chat, file panel, and asset panel; classification with
user override; derived description per kind; capability-aware attachment with honest
messaging when a model cannot read an attachment.

**Exit criterion met.** DoD 26–28 is proved end to end in
`tests/test_assets.py::test_a_picture_the_model_never_saw_becomes_the_players_sprite`,
with a scripted provider whose model has `supports_images: False`, exactly like all four
local entries in `models.json`: a 64×64 RGBA PNG is imported, the child says "Use this
picture for my spaceship", and `game.py` ends up loading `assets/spaceship.png` — while
the prompt states in as many words that nothing has looked at the file. 317 tests, ruff
clean.

**The exit was narrowed from "DoD 26–28 and 32–34" to DoD 26–28.** 32–34 is a Research
requirement that happens to involve an asset, not an asset requirement that happens to
need Research: it needs the `research_basic` starter template (which does not exist — a
Research project today creates an empty `src/`), the pandas/matplotlib runner and chart
display that are Phase 7's line item verbatim, a measurement of matplotlib under Seatbelt
(`MPLCONFIGDIR` has to sit inside the project), and a packaging change, since the
bootstrap installs only `base.txt`. **32–34 moved onto Phase 7's exit.** The asset half of
it is done and tested here for every profile: a dropped CSV classifies as Data, lands in
`data/`, and reaches the prompt as its column names and row count.

Four decisions worth knowing.

**"Derived text or metadata" for an image means facts about the file, never facts about
the picture.** §13 forbids letting a non-vision model pretend it saw an image, and the
line that makes that enforceable is the one between the header and the pixels. A PNG
header yields the real format, the dimensions and whether there is an alpha channel —
all checkable, and all exactly what is needed to *use* a sprite. What the image depicts
is not derivable and is never stated, including by the application: the filename is the
child's word for the file, not evidence about its contents, and
`test_nothing_derived_describes_what_the_picture_shows` holds that line.

Unknowns are reported as unknown rather than estimated. A WebP variant the header reader
cannot parse produces a description with no dimensions, not a plausible pair of numbers.

This generalises past images without special-casing: every asset carries whether anything
has actually read it. A CSV has (the model can `read_file` it), a PDF and a sound file
have not, and the prompt says so under one heading rather than letting a summary stand in
for the thing. **Open Nest has no PDF text extractor and none was added** — that is a
dependency this phase does not need, and "nobody has read this" is the honest description.

**No fifth tool.** §18 lists `list_assets()` and `read_text_asset()` among the candidate
tools. Neither is built, for the reason `list_project_files` is not built (SPIKES.md §4):
the application knows what has been imported, so it injects it, the same treatment the
file list gets and the same treatment Phase 4 gave memory retrieval. `read_text_asset`
needs no replacement at all — an imported CSV is a file in the project and `read_file`
already reads it. `test_attaching_a_picture_does_not_add_a_fifth_tool` pins the set at
four.

**The capability message is a lookup, not a written-in sentence.** `models_that_can_read`
filters `models.json` by `supports_images` / `supports_documents` and by the cloud gate,
so a vision model added to the catalogue starts being offered without a line of Python
changing, and so does Claude or OpenAI once a key is configured. Today it returns nothing
for an image with cloud off, so the child is told the limitation and not sent after a
model they cannot reach. `can_interpret` is the single function that decides, and it is
the one that changes when a provider able to carry whole files arrives in Phase 6.

**Not seeing a picture is not the same as ignoring what the child says about it.** The
first draft of the injected block forbade the model to describe an unread file "from its
name, and not from what they called it" — which would also have forbidden it to act on
"use this picture for my spaceship", and DoD 27 is precisely that sentence. The block now
forbids invention while explicitly permitting the child's own account: *if they tell you
what one is, believe them; if it matters and they have not said, ask.*

**The prompt was measured, found insufficient, and backed with a check — reversing the
first decision here.** The original judgement was that a deterministic check could not
be written: the Phase 2 pattern verifies rather than trusts, but "I increased" is
unambiguous where "the red spaceship" might be the child's own word, so a regex would
accuse innocent sentences.

`spikes/spike_asset_honesty.py` settled it (SPIKES.md §10). Against the real model the
block fixed the useful half outright — the control cases, where the model must *use* the
facts it was given, went from 1/2 to 2/2 — and left invention untouched: asked "does the
dragon in my picture have wings?" it replied *"Yes, the dragon in the picture has wings.
I see them clearly."*

That reply is what made the check possible. **"I see them clearly" is never the child's
word and is never true of a model that was handed no pixels** — precisely the
`_claimed_a_change_it_did_not_make` shape, and it was in the data all along. So
`assets.invented_description` uses two narrow signals, a claim to have looked and a
filename word the child never used, and the controller pulls the model up once. 38% →
50% → 62%, with every outright fabrication gone; what remains is name-derived shorthand
("the dragon"), which is milder and deliberately not chased.

The narrowness is load-bearing. The first version fired on the word *"with"*, harvested
from `red-dragon-with-wings`, and an accusation triggered by an English function word is
worse than the failure it guards against. The tests use the model's verbatim replies as
fixtures, so the regression test is the measurement.

**The application also refuses a model that cannot do the job at all.**
`router.unmet_requirements` compares what a profile needs against what a model does.
`gemma2-2b` is in the catalogue with `supports_tools: false` and every profile works by
calling tools, so it can discuss a game and cannot build one — and nothing said so
before. Not being able to see a picture is deliberately not a blocker; that is a
limitation the asset layer states honestly and works around. `models_for_project()` is
the filtered list a model picker should offer.

Departure from the module sketch in section 3: `assets/` has three modules, not the four
listed there. `image_handler` / `document_handler` / `data_handler` are three small
functions; splitting by job — `kinds` (what it is and where it goes), `describe` (what can
honestly be said), `manager` (copy-in and the context block) — is the smaller thing and
keeps the honesty rule in one file.

Carried forward: the classification dialog asks once per file, which is one extra click on
the commonest path (drag one sprite in) and should be watched with a real child; and
`ASSET_DIRS` in `project_bible` now comes from `assets.kinds.LIBRARY_DIRECTORIES`, so
reference material imported into `docs/` appears in the bible's Asset Library the way
§11's own example shows it.

### Phase 6 — Cloud AI, credentials, parent controls

Keychain credential manager; OpenAI and Anthropic providers on the same interface; cloud
master switch defaulting OFF; per-use consent dialog; parent PIN; permission gates for
packages, network, Arduino upload, Pi deployment; Settings including Parent and Advanced.

**Exit:** DoD 35–37. With cloud disabled the app is fully functional, and no key appears in
any file or log.

#### Model choices for the cloud providers

Direction from the developer, to be implemented here rather than in Phase 5. Every model
identifier below belongs in `config/models.json` and nowhere else (§3: "Do not hard-code
individual model logic throughout the application").

**OpenAI.** Build against the **Responses API**. Use `gpt-5.6-luna` for chat, reasoning,
tool calls and image understanding. Use `gpt-image-2` *only* when the child explicitly
asks for image generation or editing. Do not reach for a flagship model to do integration
testing.

**Anthropic — the equivalent of that tier is Claude Sonnet 5**, `claude-sonnet-5`, which
is already what `models.json` records. It is the mid-tier workhorse: vision and tool use,
1M context, **$2 / $10 per 1M tokens** against Opus 5's $5 / $25, so it is the right
default for a consumer app and is explicitly not the flagship. For integration testing
where cost matters more than judgement, **Claude Haiku 4.5** (`claude-haiku-4-5`,
$1 / $5, 200K context) is the cheaper rung. Three integration details that will otherwise
bite:

- Sonnet 5 uses **adaptive thinking** (`thinking: {"type": "adaptive"}`) and **rejects
  `budget_tokens` with a 400**. Haiku 4.5 is the other way round — it still takes
  `budget_tokens`. A shared provider must not assume one shape.
- **Assistant prefill is removed on Sonnet 5** (400). Anything that shapes a reply has to
  go through the system prompt or structured outputs.
- Sonnet 5 does **not** support mid-conversation `role: "system"` messages, unlike Opus 5.

The `context_policy` for `claude-sonnet` in `models.json` says 120000 max tokens against
a real 1M window. That was a deliberate budget rather than a limit, but revisit it here
now that the real number is known.

**Anthropic has no image generation model.** If an image-generation feature ships, it is
OpenAI-only via `gpt-image-2` unless another provider is added — an asymmetry the model
picker has to show honestly rather than hide.

#### Later: image generation

Wanted as an *option*, not a default: a way for a child to generate or edit a picture for
their project, surfaced as its own tab and linked optionally from Settings or the setup
wizard. It lands after cloud access is proved (Phase 6), because it cannot work without
it. Two things it inherits from Phase 5: a generated image is an ordinary imported asset
and should go through `assets.import_file` rather than a second path into the project;
and a model that generated a picture still has not *seen* it, so `can_interpret` governs
what may be said about it afterwards exactly as it does for a dragged-in PNG.

### Phase 7 — Remaining profiles

Raspberry Pi (explicit "runs on this Mac" vs. "runs on the Pi" distinction), Arduino
(`project.ino`, `README.md`, `wiring.md`; compile via `arduino-cli` when present; never
invent pin assignments), Research (pandas/matplotlib runner and chart display), Blank.
Starter idea cards per profile.

**Exit:** each profile creates and runs or compiles its template, **and DoD 32–34** — a
Research project takes a dropped CSV and produces Python analysis and a chart. Moved here
from Phase 5, which owns the asset half of it and has it working; what is missing is the
`research_basic` template, the runner, chart display, and matplotlib under Seatbelt.

### Phase 8 — Full setup wizard and installation lifecycle

Complete PySide6 wizard: welcome, identity, local AI with download progress / resume /
cancel and real-inference verification, optional cloud, optional GitHub, parent controls,
health check, finish. Installation state file; relaunch detection; Repair Installation; Run
Setup Again; migration after `git pull`.

**Exit:** Launcher Definition of Done (§35A steps 1–22) on a clean user account.

### Phase 9 — GitHub backup

Authentication per D1; private repository creation; background push queue with offline
retry; secret scanning before commit and push; PR policy modes; conversation-history
backup setting.

**Exit:** DoD 46–50.

### Phase 10 — Design and polish pass

Full light and dark treatment against `DESIGN_DOC.md`, status indicators, motion restraint,
copy and tone pass, application icon, wordmark.

**Exit:** design checklist review against `DESIGN_DOC.md` §§2–22.

---

## 6. Verification approach

- **Automated (pytest):** sandbox escape attempts and path resolution, memory and rollover
  logic, secret scanning, Git operations, config and profile loading. These are the
  correctness-critical, UI-free parts.
- **Automated, headless Qt:** UI behaviour that is *logic* rather than appearance —
  which panel a file was dropped on, where it lands, what goes with the next message.
  Added in Phase 5, because that widget stopped being a view and started making
  decisions that regress silently. `tests/test_workbench.py` runs under Qt's `offscreen`
  platform, so it needs no display and skips if that platform is unavailable. Nothing
  there asserts on pixels, fonts, or layout — that stays manual.
- **Lint:** ruff across `opennest/` and `bootstrap/`; `bootstrap/` additionally checked for
  Python 3.9 compatibility.
- **Manual:** a short checklist per phase for UI behaviour.
- **Hardware-dependent:** Phases 1, 2, and 8 require real-device testing that automated
  tests cannot cover, including a clean-user-account installer run.
