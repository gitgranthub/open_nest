# Open Nest — Implementation Plan

Working plan derived from `WORKORDER_01.md` (functional scope) and `DESIGN_DOC.md`
(naming and visual direction). This document records phases, exit criteria, decisions,
and open questions. It is expected to be amended as work proceeds.

Status: **Phases 0-9 complete. Phase 10 (design and polish) is next.** Phase 9's GitHub
backup is built but has made no real GitHub call — see its section and HANDOFF §6C-bis.

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
- ~~GitHub auth approach remains an open decision (§4, D1).~~ **Resolved in Phase 9**:
  OAuth device flow, `repo` scope, token in the Keychain.

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
├── github/        auth, api, transport, push_queue, backup   (Phase 9)
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

Phase 9: the sketch's `versioning/github_manager.py` became an `opennest/github/`
package. One module would have held the device flow, the REST client, a persisted retry
queue and the PR policy — four jobs with four different reasons to change, and the queue
in particular had to be testable without Qt or a network. `versioning/git_manager.py`
kept the *git* side (remotes, push, branches), because that is the same tool doing more
of the same job; what moved out is everything that talks to GitHub rather than to git.

Phase 6: `security/keychain.py` as sketched, but the parent controls are
`security/permissions.py` rather than the sketch's `agent/permissions.py` — they govern
cloud access, project network access and device actions, none of which the agent loop
ever consults. `ai/cloud.py` (shared transport, injectable), `ui/consent.py` (the cloud
warning, the parent PIN, the permission prompt), `agent/budget.py` (the per-turn call
ceiling and usage accounting) and `diagnostics.py` are additions the sketch did not
anticipate. The sketch's `agent/repair_loop.py` remains part of `controller.py`: it is
thirty lines that need the conversation, and moving it out would mean two owners of the
message list — the mistake Phase 2 already made once.

---

## 4. Open decisions

| # | Decision | Needed by | Current lean |
|---|---|---|---|
| ~~D1~~ | ~~GitHub auth: registered OAuth App (device flow) vs. shelling to `gh` vs. PAT fallback~~ | ~~Phase 9~~ | **Resolved in Phase 9**: classic OAuth App, device flow, `repo` scope, token in the Keychain. `gh` rejected on measurement — it authenticates whichever account it is logged into, so "Connected as X" would be a claim Open Nest does not own and Disconnect could revoke nothing |
| D11 | Whether GitHub authorization should move to a **GitHub App**, scoped to only the repositories Open Nest creates | security hardening, after V1 | A classic OAuth App's `repo` scope reaches every repository the parent can see. Accepted as a V1 trade-off; a GitHub App changes the token lifecycle, not just the registration |
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
the prompt states in as many words that nothing has looked at the file. 317 tests, ruff clean.

**The exit was narrowed from "DoD 26–28 and 32–34" to DoD 26–28.** 32–34 is a Research
requirement that happens to involve an asset, not an asset requirement that happens to
need Research: it needs the `research_basic` starter template (which does not exist — a
Research project today creates an empty `src/`), the pandas/matplotlib runner and chart
display that are Phase 7's line item verbatim, and a packaging change, since the bootstrap
installs only `base.txt`. **32–34 moved onto Phase 7's exit.** The asset half of it is
done and tested here for every profile: a dropped CSV classifies as Data, lands in
`data/`, and reaches the prompt as its column names and row count.

> **Corrected in Phase 7.** This paragraph also listed "a measurement of matplotlib under
> Seatbelt (`MPLCONFIGDIR` has to sit inside the project)" as a blocker. It was measured
> (SPIKES.md §14A) and it is not one: matplotlib works under the sandbox as shipped,
> exit 0 with the chart written, falling back to `TMPDIR`, which the profile already makes
> writable. What it does is rebuild its font cache on **every** run — 6.1 s and three
> lines of stderr each time, against 0.2 s and silence once `MPLCONFIGDIR` persists. A
> worthwhile one-line fix for speed and noise, never a blocker. The claim was carried for
> two phases without being checked.

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

### Phase 6 — Cloud AI, credentials, parent controls — **complete**

Keychain credential manager; OpenAI and Anthropic providers on the same interface; cloud
master switch defaulting OFF; per-use consent dialog; parent PIN; permission gates for
packages, network, Arduino upload, Pi deployment; Settings including Parent and Advanced.

**Verified against the real services.** All three cloud models pass every provider check
(SPIKES.md §11), image generation is reachable and imports cleanly (§12), and Luna's
repair loop, rollover, truncation handling and per-turn budget are measured, with
Sonnet 5 parity on repair and rollover (§13). 456 tests, ruff clean.

**Exit criterion met.** DoD 35–37 is proved end to end in
`tests/test_cloud_consent.py::test_switching_to_claude_shows_the_warning_and_then_switches`,
driven through the real `MainWindow._switch_model`: a key is configured, the child picks
Claude, §24's warning appears, and only then does the provider change. The refusal path
is a separate test and matters more — declining leaves both the provider *and* the picker
where they were. With cloud off the other 400 tests pass untouched, which is the "fully
functional without cloud" half. 456 tests, ruff clean.

Six decisions worth knowing.

**No SDK.** `requests` was already in `base.txt`, and both APIs used here are a POST and
an SSE stream. Adding `openai` and `anthropic` would pull two dependency trees onto a
work-managed machine to save a few hundred lines that are mostly translation anyway —
translation that has to exist regardless, because Open Nest's internal message shape is
neither vendor's. `ai/cloud.py` holds the transport; it is injectable, which is what
keeps the provider tests hermetic. **No test in the suite opens a socket, and Phase 6
did not change that.**

**Per-model request shapes are data, and capabilities are declared rather than
inferred.** The warning above — Sonnet 5 takes `thinking: {"type": "adaptive"}` and
returns a 400 for `budget_tokens`, Haiku 4.5 is the other way round — is exactly the
thing §3 forbids hard-coding, so `provider_options` is merged into the request body
untouched. Alongside it, `supports_temperature` and `supports_thinking_budget` are
per-model fields the providers read.

That second half was a correction. The first implementation omitted `temperature`
whenever a thinking block was present. It produced the right request for both catalogue
entries and was still wrong: whether a model accepts a sampling temperature is a fact
about that model, not something derivable from the rest of the request — a model could
reason and still take one, or refuse one with no thinking at all. Both flags were then
**probed against the live API by contradicting them** (SPIKES.md §11), so they are
measurements rather than claims.

**Neither Claude model can be pinned to temperature 0, and that is a real departure.**
Phase 1 measured temperature 0 as load-bearing for tool selection — but on a 4B local
model, and that is not the same risk here. What carries over unchanged is the
application's distrust: `_claimed_a_change_it_did_not_make` and `invented_description`
run against whatever produced the sentence.

**The real spikes found six defects the hermetic suite could not**, in code with 45
passing tests. Recorded in full in SPIKES.md §11, because the *kind* matters more than
the fixes: in every one the request was well-formed and the semantics were wrong, which
is precisely what a scripted transport cannot catch — the script agrees with whatever
the code sends. Two were the same bug in different costumes, and are the ones to
remember: **an output cap covers hidden work as well as the visible answer**, on both
services. Anthropic's `max_tokens` must exceed `thinking.budget_tokens`, or every call
fails; OpenAI's `max_output_tokens` must leave room past reasoning, or the model returns
a mechanically successful response containing nothing at all. Neither side could see it
— the budget comes from the catalogue and the cap from the caller — so the provider,
which sees both, reconciles them.

**All three cloud models are now verified against the real services**, including
`gpt-5.6-luna`. Getting there needed two keys: the first could not reach luna (403
`model_not_found`), so the provider was verified against `gpt-5-mini` through a
spike-only `--as` override, and a correctly-scoped key then verified luna itself. Both
columns are kept in §11 because they are not the same measurement — luna used 24 output
tokens where mini used 183 on the same prompt. There is deliberately **no runtime
fallback**: §38 forbids substituting a model behind the user's back, so an unreachable
model is reported and the request stops.

**Phase 6 briefly disarmed Phase 5's asset honesty, and that is the most important
thing this phase learned.** Making a vision model selectable made `assets.can_interpret`
answer True for images — which removed the "nobody has looked" block from the prompt and
took the file out of the set `invented_description` examines — while neither provider
sent a single pixel. Both defences off in the exact configuration SPIKES.md §10 measured
producing *"I see them clearly."* `provider.IMAGE_INPUT_IMPLEMENTED` fixes it, and the
generalisation is worth keeping: **a capability flag on a model is not a capability of
the system.** `supports_images` was always correct; the transport was missing and nothing
checked for it. Found by SPIKES.md §12, a spike about image *generation* that happened to
check whether generating counted as seeing.

**The cloud context budget was revisited, and came down rather than up.** The note said
120000 "was a deliberate budget rather than a limit — revisit it now that the real number
is known". The real number is 1M, and it is the wrong thing to size against. At $2 per 1M
input tokens, a turn near a 120000-token budget costs about **$0.24 of input alone, every
turn**, for a child changing one line of a game. The binding constraint on a cloud model
in a consumer app is cost, not context. Now 48000/36000: about $0.10 a turn on Sonnet,
half that on Haiku, and still three times the room the largest local model has. The
arithmetic is in `models.json` so the next person raising it does so knowing the price.

**Cloud models need two things, not one.** Phase 5 predicted `models_that_can_read` would
start offering Claude "with no code change" once cloud arrived. It does — but the
condition gained a second half: the master switch **and** a key in the Keychain. Phase 5's
own rule is why. Offering a model the child cannot reach is what §13 says not to do, and a
cloud model with no key saved is precisely that model. The Phase 5 test was updated and a
companion added for the keyless case. The *picker* still shows it, disabled with the
reason, because hiding it leaves a parent hunting for where Claude went.

**One call budget per turn, shared by every subsystem.** Added at closeout, and the
reason is arithmetic: the tool loop allowed eight iterations, repair three, each honesty
correction one, and a rollover happened whenever the threshold said so — so a bad turn
could stack fourteen billable requests and nothing was counting. Now twelve, shared, and
`MeteredProvider` collects them by wrapping the provider rather than threading a budget
through memory and rollover. Counted on dispatch, because a call that dies mid-stream is
still a call and counting only successes made failures free. Twelve is measured: the
worst real turn used five (SPIKES.md §13), and the ceiling is deliberately loose because
the real spend limit belongs on the API key where a parent sets it.

**Running the repair loop against the real model found two defects, one of them
embarrassing.** `TOOL_USE_RULES` told the model to change files with `write_file` —
which refuses to overwrite, by the Phase 2 decision SPIKES.md §8 measured, and whose own
schema says to use `edit_file`. Every model that believed the prompt paid for a refused
call. And repair declared failure without re-testing, so a game Luna had actually fixed
on its last attempt was reported to the child as broken. Both fixed; the second costs no
provider call, because verifying is a local run.

**Unanswered means no.** A permission set to "Ask Parent" with nothing available to ask
resolves to refused, not granted — the same fail-closed stance `process_sandbox` takes,
and the reason `Toolbox.network_policy` is a callable rather than a flag: the answer can
be a dialog, so it cannot be known when the project opened. `build_profile(allow_network=)`
has existed unused since Phase 2; §25 is what finally supplies it.

Departures from the module sketch in section 3. `security/permissions.py` rather than
`agent/permissions.py`: these are not agent permissions but parent controls, consulted by
the UI and the runner and never by the agent loop. `ai/cloud.py` and `diagnostics.py` are
new. `ui/consent.py` holds the three places Open Nest stops and asks, kept together
because they share one rule — say what will actually happen, in the fewest words that are
still true.

Carried forward: **no provider sends an image to a model**, so a vision model buys the
asset layer nothing (SPIKES.md §12). Also `arduino_upload` and
`raspberry_pi_deployment` are declared and enforceable but have no consumer until Phase 7,
only one exchange per cloud model has been run so the repair loop and rollover are
untested against one, and there is still no logging subsystem (see "Later: logging" below).

#### Later: logging

§33 asks for internal logs and an Export Diagnostic Log button. The button exists and
`diagnostics.py` builds its report from live state at the moment it is asked for. What is
*not* built is a logging subsystem — nothing writes a log file. That is a smaller gap than
it looks: the exit criterion's "no key appears in any file or log" is currently true by
construction rather than by discipline, because there is no log to leak from. If one is
added, it inherits an obligation: §33's list of things a log must never contain, and the
same scan `diagnostics.report()` runs over itself.

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

#### Later: image generation — now measured, still unbuilt

Wanted as an *option*, not a default: a way for a child to generate or edit a picture for
their project, surfaced as its own tab and linked optionally from Settings or the setup
wizard. It lands after cloud access is proved (Phase 6), because it cannot work without
it. Two things it inherits from Phase 5: a generated image is an ordinary imported asset
and should go through `assets.import_file` rather than a second path into the project;
and a model that generated a picture still has not *seen* it, so `can_interpret` governs
what may be said about it afterwards exactly as it does for a dragged-in PNG.

**Both rules were checked against the real service** — SPIKES.md §12, via
`spikes/spike_image_generation.py`. `gpt-image-2.5-flare` returns a PNG **inline as
base64**, not a URL, so there is no second fetch and nothing to expire; it imports
through `assets.import_file` and `describe.py` reads its header correctly without
Pillow. Checking the second rule is what exposed the `can_interpret` hole above.

Three things the tab will have to deal with, all measured: **10–15 seconds** per image,
so it belongs on the worker thread with visible progress; ~800 KB per 1024×1024 PNG; and
`quality` defaulting to `low` unless asked otherwise, which is a cost knob a parent may
want to see. The image model is deliberately **not** a `models.json` entry — a catalogue
entry is something that answers a conversation — so D6 has to decide where it lives.

### Phase 7 — Remaining profiles — **complete**

Raspberry Pi (explicit "runs on this Mac" vs. "runs on the Pi" distinction), Arduino
(`project.ino`, `README.md`, `wiring.md`; compile via `arduino-cli`; never invent pin
assignments), Research (pandas/matplotlib runner and chart display), Blank. Starter idea
cards per profile. Plus **Image Creation**, added during the phase — see below.

**Exit criterion met.** All six profiles create and run or compile their template, proved
per profile in `tests/test_profiles.py` against the real sandbox. DoD 32–34 is proved end
to end in
`test_a_research_project_turns_a_dropped_csv_into_analysis_and_a_chart`: a CSV is dropped
into `data/`, the analysis reports the file, its row count and its columns, and a PNG
chart is written and found by the application. 538 tests, ruff clean.

**Four of the five profiles had never worked, and nothing said so.** `profiles.json` named
five starter templates; only `pygame_basic` had ever existed. `create_project` skipped a
missing template silently (`if source.is_dir():`), so a Raspberry Pi, Arduino, Research or
Blank project was a directory containing `project.json` and nothing else, with a manifest
pointing at an entrypoint that was not there. No error, no empty-state message, just no
project. This dated from Phase 0 and survived six phases of review.

Two changes so it cannot recur: `create_project` now raises, **before** creating anything,
so a packaging fault does not leave a half-made directory blocking the name; and
`test_every_profile_starter_template_exists_and_holds_its_entrypoint` checks the
entrypoint and not just the directory. Checking the entrypoint is what makes it bite —
the Arduino sketch has to be at `project/project.ino`, and the obvious flat path is the
one that silently cannot compile.

**No profile's dependencies were installed on a fresh Mac, Games included.** The bootstrap
installed `base.txt` only, and `requirements/projects.txt` — pygame, pandas, matplotlib,
numpy, pillow — was installed by *nothing*, not the bootstrap and not
`scripts/fetch.sh deps`. Games appeared to work because developer machines already had
pygame. Both now install it. Measured cost: **~188 MB**, against the 1,179 MB PySide6 the
bootstrap already fetches, on a 1.76 GB environment. The alternative — installing
per-profile on first use behind the `package_installation` gate — was rejected because it
needs network at project-creation time in an offline-first app, and that gate exists for a
parent approving a *new* package, not for bootstrapping the curated allowlist.

**Arduino compiles for real, and getting there needed a pinned toolchain.** arduino-cli
v1.5.1, SHA256-verified, installed by `scripts/fetch.sh arduino` into
`$OPENNEST_HOME/tools`. A confined compile takes 1.3 s cold and 0.4 s warm and reports
*"Sketch uses 924 bytes (2%) of program storage space"*; a broken sketch yields a real
compiler diagnostic. SPIKES.md §14B has the four findings that shaped it, of which two
matter most: a sketch folder must be named after its sketch, and **every** arduino-cli
invocation must name its data directory or the tool builds itself a home in
`~/Library/Arduino15`.

The board list and port list come from `arduino-cli`, never from a list written here, and
nothing is preselected. §8 forbids inventing pin assignments; choosing a board for a child
chooses every pin on it, so an unset board is a question.

**The Compile button was broken in a way only pressing it would show.** `Workbench._run`
always dispatched `run_project`. Arduino has no run command and no such tool, so the
Toolbox refused it with text written for a model — *"'run_project' is not available here.
You can use: read_file, edit_file, write_file, compile_project."* — straight into the
child's Build/Preview panel. It now dispatches by profile, and §30's `✓` replaces `▶`
for a profile that compiles.

**Chart display is deterministic, and deliberately not a tool.** The application compares
the project's pictures before and after a run and shows the newest thing that changed
(`execution/outputs.py`). Asking the model to report where it saved a chart would be the
Phase 5 problem again: a model reporting a path can report the wrong one, forget, or
invent it. Comparing the directory cannot be wrong about what is on disk. It is not
Research-specific — "an image appeared" is a fact about a run, not about a profile.

#### The privileged-action rule

Direction from the developer, arising from SPIKES.md §14C: the ordinary sandbox profile
denies writes to `/dev/cu.*`, which is exactly how an Arduino appears, so upload could
never have worked no matter what was attached.

The rule, which generalises past Arduino and should be reused:

- **Normal child code stays sandboxed.** Unchanged, and an ordinary profile is
  byte-identical to before this existed.
- **Compile stays sandboxed and offline.**
- **Export, publish, deploy and upload are privileged application actions** — they cross
  the project boundary because crossing it is the point, and they are the application's
  own actions on an explicit instruction, not something a model decided to do.
- **Each action gets the minimum access it needs**, named explicitly, per action.
- **Arduino upload may access only the selected `/dev/cu.*` device**, and stays behind the
  existing `arduino_upload` gate. Enforced, not intended:
  `process_sandbox.grant_devices` refuses anything that is not a serial port, because the
  port string originates outside the application.
- **No arbitrary `/dev`, filesystem, network or shell access** is granted to support it.
  An upload is still offline.
- **The same pattern is the one to reuse** for Raspberry Pi deployment and for file and
  export workflows.
- **A privileged action that cannot be verified because hardware is absent is
  implemented, gated, and marked hardware-verification-pending** rather than blocking the
  phase.

`arduino_upload` is that gate's first consumer since Phase 6 declared it.
`raspberry_pi_deployment` is still unconsumed: §7 calls SSH deployment future, so there is
nothing in Phase 7 for it to gate without inventing a feature.

#### Decision D6 resolved — Image Creation is a profile, not a tab

D6 asked where image generation lives. It is a **profile card on the Flight Deck**, not
the optional tab the decision originally sketched, because that is where a child looks
for "a thing I can make".

Both Phase 5 rules it inherits are honoured and tested. A generated PNG goes through
`assets.import_file` like a dragged-in file, and **generating is not seeing**:
`can_interpret` still answers False afterwards, the picture is listed as unread, and the
prompt still carries `NOBODY HAS LOOKED`. That last one is the trap Phase 6 fell into in a
new costume, so it has its own test.

Three things about its shape:

- **The image model is not a `models.json` entry.** A catalogue entry is something that
  answers a conversation, and `gpt-image-2.5-flare` takes a sentence and returns a PNG.
  It lives on the profile. Keeping it out of the catalogue is what stops it appearing in
  the model picker as something a child could talk to.
- **`run_mode: generate` is the first profile that executes nothing.** The process
  sandbox denies network, so a child's own code could never call an image service — which
  means generation has to be an application action rather than another run command. The
  config test that required every profile to run or compile was taught this, and forbids
  a profile claiming both.
- **Shown disabled with the reason when it cannot be used**, following Phase 6's choice
  for cloud models in the picker: hiding it leaves a parent hunting for a feature they
  were told exists. Cloud off and no key saved are two different sentences, because they
  have two different remedies.

Carried forward: **upload is hardware-unverified**; `raspberry_pi_deployment` still has no
consumer; and §30's "Show technical details" toggle is **not built** — raw stderr still
goes to the panel, deliberately left for the Phase 10 polish pass.

### Phase 8 — Full setup wizard and installation lifecycle — **complete**

Nine steps: §35A's eight plus the Arduino toolchain (D7). Installation state file;
relaunch detection; Repair Installation; Run Setup Again; migration after `git pull`; the
parent PIN; the update check.

**Exit criterion substantially met, with one gap stated rather than glossed.** Phase 8
closed with a real installer acceptance pass — a fresh copy of the tree with no `.venv`,
a fresh `OPENNEST_HOME`, and the actual `Setup Open Nest.command`. **71 checks, 0
failures.** The launcher found no suitable Python and installed CPython 3.12.14 itself;
Qwen3 4B downloaded in 204 s; Cancel stopped at 63 MB in 4.5 s leaving no orphans;
verification answered `OPEN NEST READY` in 1.5 s; the Arduino toolchain installed in 20 s
and listed 27 boards, fully contained; and every network path failed in under a second
when run offline. SPIKES.md §16 has the table.

What is **not** met: a pristine macOS user account. The pip wheel cache was warm, so
dependency installation took seconds rather than minutes, and nobody has clicked the
wizard — the pass drives the step objects under offscreen Qt, so layout, focus and
whether the copy reads well to a real parent are unverified. That is a
release/integration acceptance item. 660 tests, ruff clean.

**The pass found four defects, three of which no hermetic test could have found.** Full
detail in SPIKES.md §16; the one that matters most for this plan:

**Nothing installed `requirements/macos-apple-silicon.txt`**, so a fresh Mac had no mlx
and no mlx-lm — no local AI engine at all, making Launcher DoD steps 9 and 10 impossible.
This is the **third** occurrence of the same shape: a manifest that exists and nothing
installs. Phase 7 found it for `projects.txt`. There is now a test that every
`requirements/*.txt` except `dev.txt` is referenced by the bootstrap, which would have
caught both.

The other three: the progress bar overstated a 2.28 GB download as *"4.2 GB of 4.2 GB"*;
the update check blamed the network for a branch the remote simply did not have; and a
completed download reported "failed" because a stale reference raised while *composing
the success message*, inside a blanket `except` that then called the download itself a
failure.

**The wizard could not live in `bootstrap/`, which decided the architecture.** Two
existing tests pin `bootstrap/*.py` to Python 3.9 and forbid it importing `opennest`;
§35A requires the installer's inference test to go *through the application's own
provider*; PySide6 does not exist until the bootstrap installs it. So the wizard is
`opennest/setup/` and the bootstrap starts it as a subprocess — decoupled by process
boundary rather than by a second implementation of anything. The arrow points one way:
the wizard imports `bootstrap.environment`, never the reverse.

**The parent PIN landed, and one latent Qt bug came with it.** `Toolbox.network_policy`
is consulted mid-turn, on a `QThread`. Qt widgets may only be used on the GUI thread.
This was unreachable while `external_requests` sat at its `deny` default and nothing ever
called the approver; the wizard's parent page now offers "Ask Parent" as a supported
choice, which makes it live. `consent.approve` marshals onto the GUI thread and blocks
for the answer.

**Three download findings, one of which was recorded wrongly first** (SPIKES.md §15):

- huggingface_hub 1.32 defaults to the Xet backend, where an exception from `tqdm_class`
  is swallowed — a cancel at 127 MB still fetched all 1,598 MB. One backend is driven,
  deliberately.
- **Resume does not work.** The first pass saw disk usage grow across two runs and
  concluded it did. Three runs from a clean cache show each one re-transferring from the
  start into a fresh randomly-suffixed partial and orphaning the last; the total grew
  because litter accumulated. A cancelled download now discards its partial and the
  message says the next attempt starts over. What *is* reused is a complete model.
- A snapshot path means nothing: large files are symlinks into a shared blob store, so a
  complete model reads as 116 KB and a "deleted" one re-downloads in 0.4 s. Nothing in
  `opennest/` reasons about cache layout; `is_installed` asks the same function
  `MLXProvider.load` asks.

#### Decision D9 resolved — notice and report, do not pull

Settled with the developer. The app may **check** and may **finish** an update someone
else started; it may not perform one.

- **Checking is a parent action, not a new permission.** It happens only on a button in
  Settings behind the parent PIN, so pressing it is the permission. `external_requests`
  governs a *child's project* reaching the network and is the wrong gate — this is the
  application contacting its own source.
- **The check is read-only by construction.** `git ls-remote`, which writes nothing into
  `.git`, unlike `git fetch`. A test enumerates the git commands issued and fails on
  `pull`, `merge`, `reset`, `checkout`, `stash`, `clean` or `push`.
- **No credentials needed**, because the repository is public — so this did not wait on
  D1.
- **Offline is an answer**, phrased as one.
- **The launch after a real `git pull`** runs the work order's migration: detect, prompt,
  reinstall through the bootstrap's own installer, adopt the new fingerprint **last and
  only on success**.
- **A moved model pin is reported, never started.** Gigabytes.
- **A one-click in-app updater is out of scope** and is now D10. The five traps this
  section used to list are exactly the reasons.

#### Decision D7 resolved — AVR only, narrowed rather than closed

`setup/toolchain.py` installs arduino-cli v1.5.1 and `arduino:avr`, ~341 MB, behind its
own wizard step — the same pinned, SHA256-verified artifact `scripts/fetch.sh arduino`
fetches, now reachable by a parent. AVR alone because 324 MB is the one core size anybody
has measured, and printing unmeasured sizes for ESP32, SAMD and RP2040 is not how
anything else here is sized. A child with a board outside that family still sees a list
without it.

Carried forward: the **pristine-account run**, and the fact that nobody has clicked the
wizard. Accepted as non-blocking by developer direction at closeout: Xet-versus-classic
download speed, cross-process resume the library does not support, network-drop resume,
cache-management tooling, and self-update machinery. Cancellation stays truthful about
all of them — it does not claim a resume that cannot happen.

#### The update protocol — partly specified, and the gap is the interesting part

Raised by the developer at the end of Phase 7. It **is** in the work order, which is worth
knowing before designing it: §"Repository update behavior" (around line 2714) and DoD
51–53. What those ask for:

- after a `git pull`, the **next launch** detects dependency, configuration-schema and
  model-definition changes and runs migrations before starting the app
- a prompt: *"Build Lab was updated. A few components need to be refreshed.
  [ Update Build Lab ]"*
- the updater **must preserve** projects, Git history, project memories, assets, settings
  and Keychain credentials

What the developer described goes past that in three specific ways, none of them in the
work order:

1. **The app notices a new version exists.** The work order assumes `git pull` has already
   happened — a parent ran it in Terminal — and the app merely reacts afterwards. Noticing
   that upstream has moved means the app *fetches and compares* against the remote. That
   is a new capability, not a migration.
2. **The button performs the pull.** In the work order the button refreshes components
   *after* someone else pulled. Here it does the pull itself, which makes the app a
   consumer of its own repository rather than a passenger in it.
3. **A safe restart of a running app.** The work order's migrations happen before launch.
   Restarting an app whose own code has just changed underneath it is a different problem:
   Python has already imported the old modules, so the restart is mandatory rather than a
   nicety, and it has to happen with no project work in flight.

What already exists to build on, and what does not:

- `opennest.__version__` is `"0.1.0"` and is **display-only** — Settings and
  `diagnostics.report()` print it; nothing compares it to anything.
- `schema_version` exists in `profiles.json` (1) and `models.json` (3), so the data
  carries versions but **nothing migrates on them**.
- `paths.installation_state_file()` → `installation.json` is **declared and never
  written**; only `tests/test_paths.py` mentions it. It is the obvious home for "which
  commit and which schema versions did we last run successfully".
- **Projects are already safe by layout**, which is most of "does not overwrite projects":
  `paths.projects_root()` is `~/Open Nest/Projects`, outside the repository, and the
  Keychain is not in the filesystem at all. The developer sandbox
  (`OPENNEST_HOME=.opennest-sandbox`) is the exception — it lives *inside* the repo, so
  test any destructive step against a real install layout, not that one.

Five things that will bite, worth designing for rather than discovering:

- **A pull can fail on local modifications.** A parent's clone may have local edits; the
  dev clone certainly does. Deciding between refusing, stashing and a detached update is a
  real choice, and refusing loudly is the safe default.
- **`requirements/*.txt` can change in the pull**, so dependencies must be reinstalled
  before relaunch — this is the work order's "dependency manifest changes", and it is now
  bigger, because Phase 7 put `projects.txt` into the bootstrap.
- **`models.json` pins commit SHAs.** A pull that moves a pin implies a model
  re-download — gigabytes, and the work order's "model-definition changes". It must be
  shown, never silently started.
- **Checking upstream needs network, and this app is offline-first.** An update check is
  the *application* reaching GitHub, which is a different thing from a project reaching
  the network, but a parent may reasonably expect to control it. `external_requests`
  governs project runs and is the wrong gate; whether a new one is needed is D9.
- **Do not build a second git layer.** `versioning/git_manager.py` exists and already
  refuses commits containing anything credential-shaped. An update touches the *app's*
  repository rather than a project's, so the two must not be confused — but the secret
  scanning and the failure vocabulary are worth reusing.

Sequencing note: this overlaps Phase 9's D1 (GitHub authentication). An update check
against a **public** repository needs no credentials at all, so the update protocol can
land before D1 is settled and should not wait for it.

### Phase 9 — GitHub backup — **built, integration unverified**

Authentication per D1; private repository creation; background push queue with offline
retry; secret scanning before commit and push; PR policy modes; conversation-history
backup setting.

**Exit:** DoD 46–50. **Met in mechanism, not in integration**, and the distinction is
the whole status of this phase: every part is implemented and tested, and **nothing has
made a real GitHub call**. The OAuth App is unregistered, so `auth.CLIENT_ID` is empty,
`configured()` answers False, and the wizard and Settings both report the feature as
absent rather than offering a button that cannot work — Phase 8's precedent, kept. 719
tests, ruff clean.

#### Decision D1 resolved — OAuth device flow

A classic OAuth App with device flow and the `repo` scope; the token in the Keychain and
nowhere else. Both alternatives were rejected on measurements rather than taste:

- **`gh` was the trap the work order named, and measuring it made it worse.** `gh auth
  status` on this machine reports `gitgranthub` — whichever account it happens to be
  logged into, in a keyring `gh` owns. Open Nest would display "Connected as X" for a
  fact it does not control, could not revoke a token it never held, and on a parent's Mac
  `gh` is a Homebrew developer tool that is probably absent. Open Nest never shells to it.
- **A PAT works**, and §29A says to avoid one "unless no better supported approach
  exists". One does.

**Accepted as a documented V1 trade-off:** a classic OAuth App's `repo` scope reaches
every repository the parent can see, including organisation repositories, because classic
OAuth Apps have no per-repository scoping. The tightening option — a GitHub App scoped to
only the repositories Open Nest creates — is recorded as **D11** and is explicitly not
Phase 9 work.

**Whose account, settled with the developer:** the parent's owns the repository and holds
the token; the *commit identity* stays separate and may be the child's, which §29A
permits and Phase 8 already plumbed.

#### The two measurements this phase rests on (SPIKES.md §17)

**The token reaches no file, and the rejected design was shown to leak first.** The
obvious remote URL — `https://x-access-token:TOKEN@host/repo.git` — writes the token
straight into `.git/config`, measured. The shipped design (clean URL, `GIT_ASKPASS`, a
per-subprocess environment) pushed successfully over real HTTP Basic auth with the token
in no file, no `.git/config` and no argv. It also turned up something not in the plan:
`credential.helper` has to be *cleared* on every call, because macOS configures
`osxkeychain` globally and would otherwise cache the parent's token where Open Nest
cannot clear it.

**`git push` can hang indefinitely, and not in the obvious case.** A black-hole address
fails in 75 s. A connection that establishes and then goes silent — captive portal, loaded
server — has no timeout at all and ran past 180 s. `http.lowSpeedLimit`/`lowSpeedTime` are
therefore load-bearing rather than decorative; the shipping values abort in 30.1 s. What
actually keeps the child working is that the queue is off the GUI thread; these bound a
wedged git process, which is a different and real problem.

#### Two design points that were not obvious

**A review branch is created before the change, never after.** §29A's diagram branches
first, and the alternative means rewinding `main` — and nothing in this codebase resets
anything. Branching first also makes §29A's "small successful modifications can remain
ordinary local commits" fall out for free: a small change fast-forwards back into `main`
and the branch disappears. The hook went in `Workbench`, so `AgentController` needed no
change.

**A push scan is not the same as a commit scan.** `commit()` scans the working tree, so
a credential that was committed and then deleted is invisible to it — the file is gone,
the blob is not, and a push sends the blob. That is why §29A asks for both, and
`scan_commits` reads blobs out of the commits being pushed.

**Carried forward:** S1 and S3 in SPIKES.md §17 — the real device flow and a real private
repository, push and PR. Both wait on the client ID. Also unverified: anything involving a
person clicking, a large first push over a real connection, and whether a parent wants to
see that a backup is pending (nothing surfaces it today, deliberately).

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
