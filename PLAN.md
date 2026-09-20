# Open Nest — Implementation Plan

Working plan derived from `WORKORDER_01.md` (functional scope) and `DESIGN_DOC.md`
(naming and visual direction). This document records phases, exit criteria, decisions,
and open questions. It is expected to be amended as work proceeds.

Status: **Phases 0 and 1 complete. Phase 2 (core vertical slice) is next.**

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
├── conversations/ manager, context_budget, rollover, archive
├── memory/        manager, project_bible, project_state, compactor, history_search
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

**Exit:** DoD 21–25 and 29–30 — an idea becomes a running game, and "make the asteroids
move faster" works.

### Phase 3 — Durability

Atomic writes, dirty-state tracking, autosave; per-project Git init with generated
`.gitignore` and repo-scoped identity; checkpoint commits at meaningful events; Undo and
Checkpoint restore in child-facing language; interrupted-session recovery on startup.

**Exit:** DoD 31; killing the app mid-edit recovers cleanly.

### Phase 4 — Memory and thread rollover

`.opennest/project_bible.md` and `project_state.md`, with deterministic fields written by
the application and semantic content by the model; per-model context budget; handoff
summary generation; `conversations/thread_vNN.jsonl` archive plus summaries; new-thread
bootstrap composition; history search; compaction.

**Exit:** DoD 39–43, demonstrated with a deliberately low test threshold, proving rollover
is silent and retains prior decisions.

### Phase 5 — Assets

Copy-in import; drag-and-drop onto chat, file panel, and asset panel; classification with
user override; image / document / data handlers; capability-aware attachment with honest
messaging when a model cannot read an attachment.

**Exit:** DoD 26–28 and 32–34.

### Phase 6 — Cloud AI, credentials, parent controls

Keychain credential manager; OpenAI and Anthropic providers on the same interface; cloud
master switch defaulting OFF; per-use consent dialog; parent PIN; permission gates for
packages, network, Arduino upload, Pi deployment; Settings including Parent and Advanced.

**Exit:** DoD 35–37. With cloud disabled the app is fully functional, and no key appears in
any file or log.

### Phase 7 — Remaining profiles

Raspberry Pi (explicit "runs on this Mac" vs. "runs on the Pi" distinction), Arduino
(`project.ino`, `README.md`, `wiring.md`; compile via `arduino-cli` when present; never
invent pin assignments), Research (pandas/matplotlib runner and chart display), Blank.
Starter idea cards per profile.

**Exit:** each profile creates and runs or compiles its template.

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
- **Lint:** ruff across `opennest/` and `bootstrap/`; `bootstrap/` additionally checked for
  Python 3.9 compatibility.
- **Manual:** a short checklist per phase for UI behaviour.
- **Hardware-dependent:** Phases 1, 2, and 8 require real-device testing that automated
  tests cannot cover, including a clean-user-account installer run.
