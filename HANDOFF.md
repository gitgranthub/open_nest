# Handoff — start here

You are picking up Open Nest during **Phase 12 (the owner's test drive)**, which is
**still open**. This document is what you need before touching anything.

**Read the top of [PHASE_12_HANDOFF.md](PHASE_12_HANDOFF.md) before you trust any claim
that something is done.** Four rounds are closed — the runtime and threading faults,
12.1's truthfulness defect, 12.2's edit tool, 12.4's playability feedback loop — and the
phase still has not met its own definition of done: **a child asks for a game and does not
get one.** An earlier
version of both files said Phase 12 was complete. That was wrong, and confusing *the
faults found* with *the outcome required* is the mistake to avoid repeating here.

**Phase 12.1 closed the last acceptance defect: Gary narrating changes he had not
made.** Driving the real interface with `Toolbox.dispatch` instrumented at the class
level killed the diagnosis it was filed under — the tools *were* running, every turn, on
the worker thread. What was failing was every `edit_file`, followed by Gary announcing a
white spaceship that had never been written. Three separate holes in one Phase 2 honesty
guard, all in `agent/controller.py`, and **the third one only appeared after the first
two were fixed and the walk was rerun**. See [PHASE_12_HANDOFF.md](PHASE_12_HANDOFF.md)
§8 and SPIKES.md §21.

**Read [PHASE_12_HANDOFF.md](PHASE_12_HANDOFF.md) next, and read it before you trust
anything else here.** Phase 12 was the first time anything clicked the application, and
it did not work: `ui/worker.run_in_thread` was silently dropping every background
worker, so the setup wizard hung on step 3 of 9 with Continue and Back disabled, the
local model never finished loading, and a child's message to Gary never ran. **980 tests
passed the whole time**, because every test reaches behaviour through an inline seam and
the threading was the one part nothing exercised. Seven defects, three of them crashes
or hangs, all fixed. If you add a worker, or a Qt driver, that file tells you what not
to do.

**Phase 12.4 — the playability feedback loop — is closed, and Phase 12 is still open.**
Open Nest now runs a game headless after every change the model makes, whether or not
the model ran it, and sends a crash, a blank window, a window that shuts itself or a
frozen picture back to the repair loop — bounded by the same three attempts and twelve
calls as everything else. Fourteen real conversations: **zero false failures**, no crash
reached the child as "done", and one crash the model never ran was caught and repaired.
The spike it grew from could not be used as it was: it graded **7 of 10 working games
frozen**. What remains is the half no deterministic check should try: a game that is
not broken is not therefore the game that was asked for, and **the 12.4 acceptance set
still failed to produce the requested behaviour reliably.** That result is why the next
work is the **Fast Path** — a classifier plus known recipes for common requests — which
the owner has chosen and nobody has started. Two user-facing fallbacks 12.4 exposed are
fixed: raw tool-call JSON never reaches the child, and "It works." is no longer said
because a game merely launched. PHASE_12_HANDOFF §12 and SPIKES §24 have all of it.

**`edit_file` was the previous suspect and is now measured NOT to be the dominant problem.** Across
the three Phase 12.1 walks **18 of 18 `edit_file` calls the 4B model produced were
refused** — every one because its `old_text` did not match `src/game.py` byte-for-byte,
including repeatedly right after it had read the file, and twice re-sending an identical
failing call. The model picks the right tool and then cannot hit it. Open Nest is now
honest about that, which is what Phase 12.1 was for; it is not yet *good* at it, and a
child asking for a spaceship game still does not get one. PHASE_12_HANDOFF §8 keeps this
**capability / action-selection miss** separate from the truthfulness defect on purpose —
"Gary told the truth" must not be read as "Gary did the job". The lever is tool
ergonomics (an anchor or line-numbered edit a small model can actually hit), not tone,
and it wants a measurement before a redesign.

**Phases 13 and 14 are specified and not started**: the game preview drawn inside the
workbench (PHASE_12_HANDOFF §6, feasibility measured), and getting work out of Open Nest
at all — export, PDF, sharing (§7, nothing exists today).

**The assistant is called Gary**, as of 10B. He is a voice, not a character: no
illustrated face, and brand guide §47 keeps him separate from the eagle, the nest and the
sunglasses, which belong to Open Nest. 10C added a small optional aside — a quiet `ⓘ`
beside his name opens a popover explaining who he is, and it is never shown unless
somebody clicks it (`opennest/ui/about_gary.py`). Its last line, *"Gary wrote this bio."*,
is the joke and has a test; the bio is third person throughout and then signs itself. `ASSISTANT_NAME` and `SYSTEM_NAME` are in
`opennest/__init__.py`. Installation, security, account, recovery and **transport
failure** stay attributed to Open Nest — a `ProviderError` is not Gary speaking, and
`test_a_failed_turn_is_open_nest_not_gary` pins it.

**If you are doing Phase 10 work, read [PHASE_10_HANDOFF.md](PHASE_10_HANDOFF.md) after
this file.** It carries the four design decisions as settled, what 10A built, three
defects found in the prepared brand-asset delivery, and what each remaining stage should
do. `brand_design_guide.md` (63 sections) governs where it and `DESIGN_DOC.md` differ —
`DESIGN_DOC.md` §23 records that ruling and the one substantive conflict.

Three things before the rest.

**GitHub backup works against the real GitHub, and the proof is in SPIKES.md §17C-E.**
D1 is resolved as OAuth device flow. A real device flow authorised `gitgranthub` in 53 s;
a real private repository was created in 3.4 s, pushed to over HTTPS in 1.6 s, and a real
pull request opened — all through the shipped code, with the token in the Keychain and in
**no file on disk**, verified by sweeping all eight of §22's locations for its actual
bytes. Disconnect is a real revocation: git cached nothing, so a later push with the
system credential helper active cannot authenticate at all. **It has also now been
clicked** — 21 checks under the real cocoa platform, including an authorization a person
completed through the actual dialog (§17F). That found five cosmetic defects and no
behavioural ones; they are Phase 10's.

**A parent can now install Open Nest without a Terminal, and the wizard is where every
"you will need to do this by hand" ended up.** Nine steps (§6D). It collects the parent
PIN, which changes the meaning of every gate that was previously approvable by whoever
was at the keyboard — read §6D's note on that before you touch a permission. It also
installs the Arduino toolchain, which until now only `scripts/fetch.sh arduino` could do.

**`snapshot_download` does not resume, and the first measurement said it did.** Each run
writes a partial with a fresh random suffix, re-transfers from the start, and orphans the
previous one; three cancelled runs left 102 MB nothing would ever read. The disk total
grows, which is what fooled the first pass. SPIKES.md §15B has the three-run table. The
downloader therefore discards a cancelled partial and says so, and the one reuse that is
real — a **complete** model is never fetched twice — is the one it offers.

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
| 8 — Setup wizard and installation lifecycle | complete, committed on `phase-8-setup`. Installer acceptance pass: 71 checks, 0 failures, four defects found and fixed. A pristine-account run is still open — see §6D |
| 9 — GitHub backup | complete, committed on `phase-9-github`. D1 resolved as OAuth device flow, **verified against the real GitHub**: real device flow, real private repo, real push, real PR, and a real Disconnect (SPIKES.md §17C-E). UI smoke-tested under cocoa: 21 checks, 21 passed (§17F). Five cosmetic defects recorded for Phase 10 |
| **10 — Design and polish pass** | **complete**, on `phase-10-design` (10A committed; 10B–10D in the working tree). The brand system is wired into every screen and verified under real cocoa at 2x in both colour schemes. Two final-QA items remain, both "somebody has to look": watching the eagle loop, and a second display. See [PHASE_10_HANDOFF.md](PHASE_10_HANDOFF.md) |
| **11 — Starter kits, Website, model registry** | **complete**, in the working tree on `phase-10-design`. Config schema 2 (`starters` + `starter_default`) and models schema 4 (per-machine memory metadata). A Website profile that previews offline; a catalogue that tiers from an 8 GB Air to a 64 GB Studio. 980 tests, ruff clean. Five surfaces rendered under real cocoa, three defects found and fixed — one of them an interpreter abort. See [PHASE_11_HANDOFF.md](PHASE_11_HANDOFF.md) |
| **12 — Owner test drive and final acceptance** | **OPEN.** Defects fixed, outcome not met — no walk has yet produced a working game. The first time anything clicked the application — and it did not work: `run_in_thread` was silently dropping every background worker, so the setup wizard hung on step 3 of 9, the model never loaded, and a child's message to Gary never ran, with 980 tests passing throughout. Seven defects fixed, three of them crashes or hangs. See [PHASE_12_HANDOFF.md](PHASE_12_HANDOFF.md) |
| 12.1 — the truthfulness defect | **closed.** Gary narrating changes he had not made, reproduced through the real interface and closed. The filed diagnosis ("no tool call") was wrong — `Toolbox.dispatch` was entered every turn; every `edit_file` was refused and the claim was relayed anyway. Three holes in one guard, the third found only by rerunning the walk after fixing the first two. 1025 tests, ruff clean. §8 of PHASE_12_HANDOFF and SPIKES §21 |
| 12.2 — editing reliability | **closed.** 18 of 18 `edit_file` calls were refused; measured the distribution (47% the model editing code it imagined, 33% wrong indent, 20% a newline written as two characters) and added a bounded deterministic recovery that refuses ambiguity. 3 of 4 real edits now land. Also: one project runs one copy of itself, and the approval mark is no longer awarded for the starter launching. 1044 tests, ruff clean. SPIKES §22 |
| 12.3 — does the child get a game? | **measured, and the answer is no.** 1 of 24 conversations produced the game that was asked for. 4B vs 8B did not solve it, prompt tuning did not solve it, starter markers made it worse, and tool execution is no longer the dominant problem. `RunResult.ok` is True for any game that merely launched, so the repair loop cannot react to "runs but does not work". SPIKES §23 |
| 12.4 — Playability Feedback Loop | **closed.** A headless playtest after every change feeds crashed / no picture / closed itself / frozen to the repair loop, sharing its three attempts and the call budget. The 12.3 spike graded 7 of 10 working games frozen and was rebuilt, not wired in. 14 real conversations: 0 false failures, 0 crashes reaching the child as "done". 1104 tests, ruff clean. PHASE_12_HANDOFF §12, SPIKES §24 |
| 13 — The game preview in the workbench | **not started.** Specified in PHASE_12_HANDOFF §6; feasibility measured |
| 14 — Getting work out of Open Nest (export / PDF / share) | **not started.** Specified in PHASE_12_HANDOFF §7. Nothing can currently leave the app |

Branches are **stacked**: each is based on the previous one, so each PR shows only its
own phase. Nothing is merged to `main` yet. Branch Phase 10 from `phase-9-github`.

The review chain is 1 → 2 → 3 → 4 → 6 → 7 → 5 → 8 → 9. The PR numbers do not match the
review order, because #5 was opened before #6, #7 and #8.

What works today: a parent clones the repository, double-clicks one file, and answers a
wizard that installs the environment, downloads and *verifies* a local model, optionally
adds the Arduino toolchain and cloud keys, sets a PIN and the permissions, and runs a
health check. Then a child picks one of six project types, describes an idea, the local
model edits the project, it runs, they can undo, the project remembers its decisions
across conversations, and they can drag their own pictures, data and documents in and have
the project use them. A Research project turns a dropped CSV into analysis and a chart they
can see. An Arduino project compiles for a board they choose. A parent can add an API key,
turn cloud on, and the child can switch to Claude or OpenAI after a warning, or make
pictures with an image model. Everything except Image Creation still works with cloud off,
which is the default.

1104 tests pass, ruff is clean.

**The application icon is deliberately unresolved, and that is a ruling rather than a
gap.** Phase 10D was told not to design or simplify one: it needs a separately approved
simplified Open Nest mark suitable for macOS icon sizes, and deriving one from the
canonical nest artwork without design approval is not an engineering decision. The full
ruling is in `DESIGN_DOC.md` §23, where it closes the apparent §18 conflict. If you pick
it up, it is a design task first and a packaging task second — the `MANIFEST.in` gap in
`PHASE_10_HANDOFF.md` §8 means an app bundle does not currently ship the brand assets
at all.

**Phase 10 was the design and polish pass**, and Phase 9 handed it three things:

- **GitHub backup is on, and `CLIENT_ID` is what holds it on.** `github/auth.py` carries
  the registered OAuth App's client ID — public by design, it ships in every copy. Empty
  it and the whole feature correctly reports itself absent, which is the switch to reach
  for if it ever needs turning off.
- **The update check still needs no credentials and must not start using the token.**
  `git ls-remote` against a public repository is unauthenticated, and
  `test_the_check_only_ever_runs_read_only_git_commands` guards the read-only half.
- ~~**Nothing surfaces a pending backup.**~~ **Answered in Phase 10C**, in two levels: a
  child sees plain backup *state* on the Flight Deck, a parent sees the count and the
  reason in Settings. §6C-bis has the detail.

Still with no consumer: `raspberry_pi_deployment`. §7 calls SSH deployment future, so
Phase 7 had nothing to gate without inventing a feature. When you build it, it takes the
privileged-action pattern in §5, not a new mechanism.

---

## 2. Get running in five minutes

```bash
.venv/bin/python -m pytest -q      # 1104 passing, about 110 seconds
```

It is slower than it was (7 s at Phase 6, 55 s at Phase 12.2). Phase 12.4 made every Games
turn that changes a file run a real ~2 s headless playtest, and about thirteen existing
tests do exactly that — deliberately, since a test-only switch would have them describe a
configuration the product never runs. Phase 7 added tests that actually run each
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
├── projects/               manifest, profiles, and starter kits
│   ├── starters.py         a kit, its manifest, and applying one without overwriting
│   └── starters/           the shipped kits, one directory + starter.json each
├── models/                 what this Mac can run -- Phase 11B
│   ├── machine.py          the ONLY thing that inspects hardware. Everything else is
│   │                       handed the MachineProfile it produced.
│   ├── catalog.py          bundled + cached remote, merged and strictly validated
│   ├── remote.py           the updateable catalogue. Offline is a normal answer.
│   ├── discovery.py        what is installed, what a provider has, what else is on disk.
│   │                       load_paths() is contained; discover_paths() is wider.
│   ├── compatibility.py    Recommended / Can Run / Not Recommended / Incompatible
│   └── migration.py        carrying an existing installation into the registry
├── execution/
│   ├── python_runner.py    out-of-process running, batch vs interactive
│   ├── playtest.py         after a change: does the game do anything? Decides, pure
│   ├── playtest_harness.py ...the half that runs inside the child's process. Records only
│   ├── arduino.py          arduino-cli: is it here, boards, ports, compile, upload
│   └── outputs.py          which pictures a run produced. Deterministic, not a tool.
├── setup/                  installation lifecycle -- WORKORDER_01 section 35A
│   ├── state.py            installation.json, and the fingerprint an update compares
│   ├── wizard.py           the nine steps. The only file here that knows about Qt...
│   ├── update_dialog.py    ...and this one, which is the two update windows
│   ├── downloader.py       download with progress/cancel, and real-inference verify
│   ├── toolchain.py        arduino-cli + AVR core, pinned and SHA256-verified
│   ├── checks.py           the health check, reused by Repair Installation
│   ├── updates.py          "is there a new version?" -- reads, never pulls
│   └── migration.py        what the launch after a `git pull` does
├── github/                 GitHub backup -- WORKORDER_01 section 29A
│   ├── auth.py             device flow (D1); the token, and the Keychain it lives in
│   ├── api.py              create a PRIVATE repo, open a PR. `private` is a constant.
│   ├── transport.py        injectable HTTP, so no test opens a socket
│   ├── push_queue.py       pushes waiting for the internet. No Qt in it.
│   ├── backup.py           orchestration and the PR policy
│   └── askpass.sh          what git execs to get the token. Holds no secret.
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

`ui/github_sync.py` drives the push queue on a timer and a worker thread;
`ui/github_connect.py` is the device-flow window. `ui/settings.py` is the six sections of §32; `ui/consent.py` is the three places Open
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

**Phase 8 traps:**

- **A modal dialog blocks forever under the `offscreen` platform too.** There is no one
  to press the button, so a test that reaches a `QMessageBox.exec()` hangs rather than
  failing. `tests/test_wizard.py` stubs the wizard's own `complain` and `confirm` for
  this reason; they exist as named methods partly to give tests somewhere honest to cut.
- **Qt widgets belong to the GUI thread, and one permission prompt is now reached from a
  worker.** See §6D. `consent.approve` marshals; anything new that asks a parent from
  inside a turn must go through it.
- **`du` tells you almost nothing about a Hugging Face cache.** Large files are symlinks
  into a shared content-addressed blob store, so a complete 1.5 GB model reads as 116 KB
  and deleting `models--<repo>/` frees nothing. This produced two wrong conclusions in a
  row before it produced a right one (SPIKES.md §15C). `is_installed` asks
  `resolve_local_model` — the call the app itself makes — and nothing reasons about
  layout.
- **`opennest/` may import `bootstrap/`; the reverse is a test failure.** The wizard uses
  `bootstrap.environment` for machine detection and `migration` uses it to reinstall,
  both lazily and tolerantly. Keep the arrow pointing that way.

**Phase 9 traps:**

- **A private repo answers "Repository not found" to an anonymous `ls-remote`, and
  `_run(..., check=False)` swallows it into an empty string.** So a good push reads as a
  failed one. Authenticate before believing anything about remote state. Second instance
  of a swallowed git failure being read as a fact (Phase 8's defect 3 was the first).
- **A numeric PIN is valid hex, which made a credential test flaky — and the fix was
  recorded here before it existed.** `test_the_pin_is_stored_as_a_fingerprint_not_as_the_pin`
  (renamed from `..._stored_as_a_hash_...`, which is probably how the fix got lost)
  asserted `"2468" not in stored` against ~96 random hex characters of salt and digest.
  A four-digit decimal PIN is valid hex, so the digits turned up in the salt by chance:
  measured failing **1 run in 800**, and it failed again during Phase 10. This entry used
  to claim it was "fixed by fixing the salt"; it was not, and the test still used a real
  random salt until Phase 10. **Genuinely fixed now**, in two parts:
  - The salt is pinned via a `fixed_pin_salt` fixture. `keychain._hash_pin` already took
    an optional salt, so the real PBKDF2, the real record format and `_verify_pin` are
    untouched — only the randomness is gone. `test_the_same_pin_does_not_produce_the_same_record_twice`
    deliberately does *not* use the fixture, so pinning the salt in an assertion cannot
    hide the absence of salting in the implementation.
  - The haystack is now the salt and digest, not the whole record. Searching the whole
    record was unsound for a second, worse reason: the format is
    `pbkdf2_sha256$<rounds>$<salt>$<digest>` and `$200000$` **contains `0000`**, so a
    parent PIN of `0000` "appears" in every record ever written, under every salt — a
    deterministic failure, not a 1-in-800 one. `test_a_pin_of_all_zeroes_is_stored_just_as_safely`
    pins that case.

  Two lessons, and the second is the bigger one: if you assert a secret's absence from
  random hex, check the alphabet first — and if you assert a secret's absence from a
  *structured* record, check what the constant parts of the structure contain.
- **`isVisibleTo(parent)` is *also* vacuous inside a `QStackedWidget`.** §4 already
  records that `isVisible()` is False on a widget nobody showed, and says to use
  `isVisibleTo(parent)`. That fix does not hold here: a stack **explicitly hides** every
  page but the current one, so `isVisibleTo(window)` is False for every control on the
  Parent Settings page whatever the code does. Two assertions in `test_github_ui.py`
  were vacuous until this was measured both ways. **`isHidden()` is the predicate that
  discriminates** — it reflects the `setVisible()` the code actually called.
- **`git push` can hang forever, and it is not the case you would guess.** A black-hole
  address fails in 75 s (the macOS SYN timeout), but a connection that *establishes and
  then goes silent* has no timeout at all — it ran past 180 s in SPIKES.md §17B. So
  `http.lowSpeedLimit`/`lowSpeedTime` are load-bearing, not tidiness. Removing them
  reintroduces an unbounded hang.
- **macOS configures `credential.helper=osxkeychain` globally, and it will cache your
  token.** Every authenticated git call passes `-c credential.helper=` for that reason. A
  copy in git's own credential store is one Open Nest does not own and cannot remove when
  a parent presses Disconnect.
- **GitHub's device-flow token endpoint answers HTTP 200 with the error in the body.** So
  a status-based error check sees success and falls straight through. Without an explicit
  branch a real failure reports as "GitHub approved the sign-in but sent no token", which
  is both wrong and unactionable. `test_an_unknown_device_flow_error_is_not_reported_as_a_missing_token`
  pins it.
- **A commit-time secret scan cannot see a committed-then-deleted credential.**
  `commit()` scans the working tree; the file is gone and the blob is not. That is why
  §29A asks for a scan before pushes *as well*, and why `scan_commits` reads blobs out of
  the commits rather than looking at the checkout.
- **`permissions.ParentControls.load` only accepted strings that were gate states.** Every
  string field was a three-state permission until `github_pr_policy`, so a saved PR policy
  was silently discarded in favour of the default. `_STRING_VALUES` is the fix; if you add
  another string setting with its own value set, it goes there.
- **`permissions.reload()` returns a new object**, so anything holding the old one reads
  stale switches. `MainWindow._settings_changed` now hands the new one to `GitHubSync`;
  without that, a parent turning backup off kept pushing until the next launch.

**Phase 10 traps:**

- **A tone rule can be broken by the model, so grepping the copy cannot verify tone.**
  Phase 10B swept every user-visible string for the brand guide's banned vocabulary and
  found nothing — and the shipped product was still opening routine replies with
  **"Great!"**, which §18 names explicitly. The word is not in the codebase; the model
  supplies it. Static checks cover the copy the application *writes*; only running the
  real model covers the copy it *says*. SPIKES.md §18B has both halves. If you change a
  prompt for tone, read replies — a clean grep proves nothing about the half of the
  interface a model generates.
- **A harness that names a file the project does not have measures the harness.** The
  Phase 10B tool-selection spike scored 12/16 and three of the four "misses" were the
  model correctly answering *"I don't have a main.py file"* — the Games template's file
  is `game.py`. Corrected, the baseline is 15/16. Third instance of the §17F lesson:
  dump what the harness is actually seeing before you believe its number.
- **`section_label` uppercases**, so a widget titled `Gary` renders `GARY`. A test
  asserting the exact string pins the theme rather than the name; compare casefolded.
- **An average over an animation's frames cannot see an animation defect.** Three
  single-frame measures — ink mass, round-trip error, per-frame fidelity — all rated
  nearest-neighbour the *best* way to downscale the eagle. The defect was a 3.90
  percentage-point swing in apparent weight **between** frames, which is the bird pulsing
  as it flaps, and every one of those metrics averages it away. Measure the spread across
  a cycle. This is the third instance in Phase 10 of an aggregate hiding a per-element
  failure (the compact mark's contrast was the first, the tool-selection harness the
  second).
- **`QLabel.pixmap()` does not return the pixmap you set.** Give it a 128 px pixmap at
  device ratio 2.0 and it hands back a 64 px one at ratio 1.0. The *rendering* is fine —
  a 1 px stripe pattern survives a 2x `grab()` intact, so Qt keeps the high-resolution
  data — but a HiDPI assertion that trusts the getter reports a defect that does not
  exist. Assert on what `brand.pixmap` returns.
- **A nested layout silently breaks `widget.parentWidget().layout()`.** A layout adds no
  widget, so a row moved into a nested layout still reports the page as its parent while
  the page's layout no longer contains it. `QLayout.replaceWidget` then does nothing,
  returns quietly, and the replacement is left unparented — painting on top of whatever
  is behind it. This shipped two overlapping labels on the Flight Deck and **the entire
  suite passed**; only looking at the render found it. Keep a reference to the layout
  that owns a widget, and `setParent(None)` the one you replaced.
- **The prepared delivery's smallest size for a mark is a legibility threshold.** A 40 px
  compact mark was generated and withdrawn: below 64 px the `ON` is illegible and the
  nest is a blob, and 64 is exactly where the supplied ladder starts. The eagle is the
  exception — one bold silhouette with no fine detail — which is why 32 px works for it
  and not for a lockup containing two letters. Render a candidate size before adding one.
- **`QT_SCALE_FACTOR=2` gives a genuine 2x display under the `offscreen` platform**, so
  HiDPI behaviour is testable without a Retina screen. It has to be a subprocess: the
  scale factor is read once when `QGuiApplication` is constructed.
- **A plain `QWidget` used as a layout holder paints the window colour over its panel.**
  The stylesheet gives every `QWidget` `background-color: window`, so a bare container
  inside a `role="panel"` frame draws a band across it. `role="bare"` makes it
  transparent, the same treatment `QLabel` already had.

**Phase 12 traps — read these before writing any Qt:**

- **`moveToThread` + `started.connect(worker.run)` does not work under PySide6 6.11.**
  It is the idiom in every Qt tutorial and it loses the worker silently: `run()` is
  never entered, nothing raises, nothing is logged, and the thread runs forever. Two
  separate weak references bite, in order — the worker itself, then the bound method
  built at connect time — and a third attempt ran the work on the *main* thread, curing
  every symptom and losing the point. `ui.worker.WorkerThread` overrides `QThread.run`
  so there is no connection involved at all. **Do not go back to the idiom.**
- **Do not re-add `thread.finished.connect(worker.deleteLater)`.** Holding the worker
  makes Python its owner and Qt then frees it twice. Measured as a SIGSEGV.
- **A lambda connected to a worker signal runs on the worker thread.** PySide6 picks the
  connection type from the *receiver's* thread affinity and a lambda has no receiver, so
  a cross-thread emit is delivered directly. That put Flight Deck widget updates on a
  worker thread. Connect a bound method of a QObject; carry extra data on the object.
  `test_nothing_connects_a_lambda_to_a_worker_signal` enforces it.
- **`QTest.qWait` starves worker threads of the GIL — 140x, measured.** 0.07 s on the
  main thread against 10.02 s for the identical loop on a worker. It turned a 0.02 s
  inspection into a minute and produced a confident wrong diagnosis. Use a nested
  `QEventLoop`, which is what `app.exec()` does.
- **A test that reaches behaviour through an inline seam says nothing about the thread.**
  The seams are good and should stay; `tests/test_worker.py` is the counterweight.
- **`requirements/` is pinned now.** `PySide6>=6.7,<7` let the GUI toolkit change under
  the product between installs, which is exactly the failure above. Bumping a pin is a
  deliberate edit and the thing to run afterwards is `spikes/phase12/`.
- **`sns.set_theme()` throws away the project's chart style.** The research starter
  ships a `matplotlibrc`, which matplotlib picks up from the working directory; that one
  seaborn call replaces all of it. The prompt names the trap and a test pins the
  sentence.
- **The chart palette's slot ORDER is its accessibility mechanism**, not a preference.
  Re-ordering silently breaks colour-blind separation and the render looks fine.
  SPIKES §20J.

**Phase 12.1 traps — all four are about honesty checks, and all four cost a measurement:**

- **`turn.text` and `reply.text` are not the same string, and the honesty checks must
  read the first.** `turn.text` only takes a reply's text when that text is non-empty, so
  a model answering a correction with **nothing** leaves the *previous* reply standing as
  Gary's words. A check on `reply.text` sees `""`, finds no claim, and relays the earlier
  sentence unexamined. This is how the verification walk leaked the identical false claim
  with the fix already in place. Gary is answerable for the sentence on screen.
- **A hand-written list of phrases rots asymmetrically, and nothing notices.**
  `_CLAIMED_CHANGE` held `i increased` and not `i've increased`; four of thirteen verbs
  had their present-perfect form and none had a progressive. The real model then said
  exactly the missing forms. It is generated from verb triples now — if you add a verb,
  add the triple, not one string.
- **Exempt the plain denial, or the fix punishes the model for complying.** The
  correction asks it to "say plainly that you have not changed anything yet", and an
  honest admission often carries a claim verb: *"I haven't changed anything — I made a
  mistake reading the file."* `_DENIED_CHANGE` is checked first for that reason.
- **Do not name a cause you have not checked, in the copy that exists to stop invention.**
  A draft of `_nothing_changed_text` said "the text I tried to replace was not in the
  file". That was the measured case and would have been a fresh fabrication in the other
  seven ways `edit_file` and `write_file` refuse.
- **A defect found by clicking has to be re-checked by clicking.** Two of the three holes
  were found by measuring; the third existed *only because the first two were fixed*, and
  would have shipped if the fix had been trusted instead of re-driven. SPIKES §21.

**Phase 12.4 traps — the playtest, and the harness it replaced:**

- **`spikes/phase12/does_it_play.py` is not a grader you can act on.** It replaces
  `pygame.event.get` with a function returning nothing, which swallows every KEYDOWN and
  every `set_timer` event, and it only ever fakes arrow keys: **7 of 10 working games
  graded frozen** (SPIKES §24A). The 12.3 corpus never showed it because all 24 games
  came from the arrow-key starter. The product harness *posts into* the game's queue;
  never substitute for it.
- **The application runs the test, not the model.** All ten crashes in the 12.3 corpus
  were first-frame crashes the existing repair loop would have caught — nothing ran
  them. Hooking the check onto `run_project` would have missed every one.
- **Warm-up frames discount *movement*, never *response*.** A game that redraws only on
  input draws three frames in the whole test; discarding two graded it frozen.
- **No record at all is the harness failing, never the child's game.** The harness writes
  an end record however the game finishes, a first-line crash included, so a traceback
  with no record is the harness's own and must not trigger a repair.
- **The playtest cannot fire inside `scripts/offline.sh`.** It runs under the product's
  Seatbelt profile, and Seatbelt does not nest, so there every test is UNAVAILABLE.
  `spikes/phase12/playability_loop.py` therefore runs unwrapped with `HF_HUB_OFFLINE=1`,
  which is how the product runs: model in-process, every game confined.
- **"Passed" means "not clearly broken", not "does what was asked".** A square whose
  position is reset every frame jitters, passes, and does not fall. The deterministic
  check stops there on purpose (SPIKES §24D) — do not grow it into judging intent.
- **Temperature 0 on MLX is not bit-for-bit repeatable across runs.** The same
  conversation crash-repaired and gave up in one run and passed cleanly in the next.
  Report per-run results; do not average a single rerun into a claim.

**Phase 11 traps:**

- **A widget destroyed while one of its worker threads runs aborts the interpreter.** No
  traceback, no failed test, a dead process. The test fixtures have quit-and-waited by
  hand since Phase 5, so this was understood and guarded everywhere except in the
  application. Phase 11 made it reachable — the setup wizard now starts a worker the
  moment the Local AI step opens, and Quit Setup is deliberately never disabled. Use
  `ui.worker.stop_thread`, and wait for anything you start.
- **`<cache>/blobs` is a *shared* content-addressed store**, marked with
  `.huggingface-shared-blobs`, and `models--<repo>/` holds links into it. So deleting a
  repository directory frees almost nothing. This is the second half of §4's existing
  `du` warning. Removal goes through `scan_cache_dir(...).delete_revisions(...)`; SPIKES
  §19C has the figures.
- **Chromium refuses a remote request from a `file:` page before a
  `QWebEngineUrlRequestInterceptor` is consulted.** Measured both ways in SPIKES §19A. The
  page really is offline — and a blocked request is therefore *silent*, which is why
  `web_preview.remote_references()` reads the source before the render instead. If you
  rely on a hook to tell a child something, check the hook actually fires.
- **Qt destroys a `QWebEngineProfile` whose page is still alive with "Expect troubles!",
  and the trouble is a crash.** Closing a parent widget does not call `closeEvent` on its
  children, so `MainWindow._close_project` asks the Workbench to release explicitly.
- **A capability flag about *Open Nest's testing* is not a fact about the model.**
  `verified` ranked above size in the model suggestion, and exactly one entry is verified
  — so every Mac was permanently suggested the 2.3 GB model however much memory it had.
  Rank on fit; say "untested" out loud instead.
- **Every decision that depends on the machine takes the machine as an argument.**
  `models.machine.detect()` is the only thing that inspects hardware, and nothing else
  calls it. The target is an 8 GB Mac and every measurement here was taken on 48 GB, so a
  test that inherits the machine it runs on is a test that passes for the wrong reason.

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
- **DEFECT — "Ask before using cloud AI" is weaker than its name, in two ways.** Found
  in Phase 10B while checking a copy claim, recorded by developer direction, and **not
  fixed there** because it is functional work rather than a copy pass. D12 is the
  decision it needs.

  What *is* solid, so nobody re-audits it: the master switch `allow_cloud_ai` defaults
  OFF, is genuinely parent-controlled (Parent Settings is behind the PIN), and is
  enforced both before a provider is built and again at every model switch. A project
  whose manifest names a cloud model is **not** silently restored to it either —
  `MainWindow` always builds `default_model_id()`, which is local, and
  `Workbench.select_model` follows the live provider, so the only route to a cloud model
  is `_switch_model`, which confirms. A child cannot reach the cloud unless a parent
  turned it on and saved a key.

  The two gaps are in the *per-use* control §24 offers on top of that:

  - **The warning is answered by the child, not the parent.**
    `consent.confirm_cloud_use` is a plain `QMessageBox` and never calls
    `ask_parent_pin` — unlike `consent.approve`, which does take the PIN for
    `arduino_upload` and the rest. The setting is labelled "Ask before using cloud AI"
    and sits in Parent Settings, so it reads as a parent gate; in practice the child
    presses **Use Claude**. It is an awareness prompt, not an approval.
  - **It fires once per model switch, not per cloud request.**
    `cloud_needs_confirmation`'s own docstring says "before each cloud use" and the code
    does not do that. Once confirmed, every remaining turn of the session reaches the
    cloud unprompted. §24's "Before using a cloud model" is ambiguous between the two
    readings; the docstring is not, and it overpromises.

  Both are one-line-ish to change and neither should be changed without deciding D12
  first — asking for a PIN on every turn would make cloud unusable, and asking on none
  is what we have.
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

## 6C-bis. How GitHub backup works

Phase 9 is built and **verified against the real GitHub** — SPIKES.md §17C-E has the
numbers. A real device flow, a real private repository, a real authenticated push, a real
pull request, and a real Disconnect, all driven through the shipped code rather than a
reimplementation. What remains unverified is anything involving a person clicking.

**D1 is resolved as OAuth device flow, and the other two candidates were rejected for
measured reasons.** Not preference:

- **`gh` was the trap the work order warned about, and it is worse than it reads.**
  Measured on this machine: `gh auth status` reports whichever account happens to be
  logged in — here `gitgranthub`, with `repo` scope, in a keyring `gh` owns. Open Nest
  would be displaying "Connected as X" for a fact it does not control, could not revoke
  a token it never held, and on a parent's Mac `gh` is a Homebrew developer tool that is
  probably absent. **Open Nest never shells to `gh`.**
- **A PAT works** and §29A says to avoid it unless nothing better is supported.

**The account is the parent's; the commit identity is separate and may be the child's.**
This distinction is the whole shape of the feature and it is easy to collapse. §35A says
"Sign in to the parent's GitHub account" in as many words, the connection lives behind
the parent PIN, and GitHub's own terms put an age floor under a child having an account.
Meanwhile §29A explicitly permits the child's GitHub noreply address as the commit
author — and Phase 8 already plumbed that half. One account owns the private repository;
the child's name is on the commits.

**The token never touches disk, and that is measured rather than intended.** The obvious
remote URL (`https://x-access-token:TOKEN@github.com/...`) writes the token straight into
`.git/config`; SPIKES.md §17A shows it doing so, as a negative control, before showing
the design that does not. The token goes to git through `GIT_ASKPASS` and an environment
set for one subprocess. Two things fall out of that which are easy to undo by accident:

- **`credential.helper` must be cleared on every authenticated git call.** macOS ships
  `osxkeychain` configured globally, so without `-c credential.helper=` git caches the
  parent's token in a store Open Nest does not own and cannot clear on Disconnect.
- **`opennest/github/askpass.sh` is executed by git**, so it ships in the package with
  its executable bit rather than being written to a cache directory at run time. A file
  anything on the Mac could overwrite is a worse thing to hand to `exec`. It holds no
  secret; it reads from its environment.

**A push scan and a commit scan are different questions, and both are required.** §29A
asks for scanning before commits *and* before pushes, which reads like belt and braces
until you notice that `commit()` scans the **working tree** — so a credential that was
committed and then deleted is invisible to it. The file is gone; the blob is not, and a
push sends the blob. `git_manager.scan_commits` therefore reads blobs out of the commits
being pushed. `test_a_secret_committed_and_then_deleted_still_blocks_the_push` is the
case that justifies the extra work.

**Offline is the only failure worth retrying, and `git push` can hang forever.** The
second half is the surprising one: git has no timeout for a connection that establishes
and then goes silent, so a captive portal hangs a push **indefinitely** (SPIKES.md §17B).
`http.lowSpeedLimit`/`lowSpeedTime` are load-bearing because of that, not decorative. A
rejected or secret-blocked push leaves the queue instead of retrying — a timer cannot fix
either, and for a credential it would repeat the same warning forever.

**One queue entry per project and branch, not per commit.** A push sends whatever the
branch points at, so two queued pushes for one branch are the same push. Re-queueing
resets the backoff rather than adding an entry, because new work is evidence the child is
working now and should not wait out an hour earned while the Wi-Fi was off.

**A review branch is created before the change, never after.** §29A's diagram branches
first, and the alternative is worse than it looks: committing to `main` and then moving
the branch means rewinding `main`, and nothing in this codebase resets anything
(`git_manager.restore` is append-only for the same reason). Branching first also makes
§29A's "small successful modifications can remain ordinary local commits" fall out for
free — a small change is fast-forwarded back into `main` and the branch disappears. The
hook is in `Workbench`, so `AgentController` needed no change at all.

**What counts as a "large" change is an unmeasured heuristic and is labelled as one.**
`backup.LARGE_FILES` (3) and `LARGE_LINES` (120) are deterministic — computed from the
diff, never asked of the model — but the thresholds are a guess, exactly like
`history_search.CUES`. Nobody has watched a child's session and counted.

**Conversation archives are excluded by the `.gitignore`, not by a push-time filter.**
§38 requires no chat archives unless a parent opts in, and `git_manager.GITIGNORE`
already excluded `.opennest/conversations/` from Phase 3 onward. An archive that is never
committed cannot be pushed, so the setting rewrites that one line. Turning it on applies
to every project, not just the open one.

### What the real run added to the above

**A private repository answers "Repository not found" to an anonymous `ls-remote`.**
GitHub does not disclose that private repositories exist, and `_run(..., check=False)`
turns that failure into an empty string — indistinguishable from a successful empty
result. This made a perfectly good push look like it had never arrived, and it is the
second time a swallowed git failure has been read as a fact about the world (Phase 8's
defect 3 was the same shape). If you check remote state, authenticate.

**The update check's freedom from credentials rests on one repository being public**, and
that is now verified rather than assumed: `gitgranthub/open_nest` answers HTTP 200
unauthenticated. If it ever goes private, `setup/updates.py` breaks — and the token is
still the wrong fix, because the check must not require a connected account.

### What is not done

- **Five cosmetic defects are known and unfixed**, all found by looking at the rendered
  window (SPIKES.md §17F) and all left for Phase 10 by developer direction: a clipped
  "Open GitHub agai" button label; the device code shown twice; the standalone code not
  visually prominent; **GitHub Backup sitting 726 px down a 443 px viewport** in Parent
  Settings, when §29A treats it as a headline control; and a horizontal scrollbar on that
  page. The first is a plain bug and a one-line fix.
- **One account, one Mac, one run.** Nothing has been tried against an organisation
  repository, an account with SSO, or 2FA prompts landing mid-flow.
- **What a parent sees on GitHub's own authorization screen is still unreviewed.** The
  developer approved it, so it works; whether its wording about `repo` access reads
  acceptably to a parent is the live evidence for D11 and nobody has assessed it.
- **The classic OAuth `repo` scope is broader than this needs.** It reaches every
  repository the parent can see, including organisation repositories, because classic
  OAuth Apps have no per-repository scoping. Accepted as a documented V1 trade-off by
  developer direction. The tightening option — a **GitHub App** with an installation
  scoped to only the repositories Open Nest creates — is recorded as future
  security-hardening work and is explicitly not Phase 9.
- **Nobody has clicked any of this either.** Same caveat as §6D: the tests drive the
  objects under offscreen Qt, so the device-flow dialog's copy, focus and layout are
  unverified, and the browser hand-off has never been watched by a person.
- **A large first push is untimed.** `PUSH_TIMEOUT_SECONDS` is 300 s on the reasoning in
  SPIKES.md §17B, but no project with real assets in it has been pushed over a real
  connection.
- ~~**Nothing shows a child or a parent that a backup is pending.**~~ **Resolved in
  Phase 10C**, with the split the developer set. A child sees `BACKUP ● COMPLETE` /
  `○ WAITING FOR INTERNET` / `○ NOT SET UP` on the Flight Deck and never a queue depth,
  a repository, a commit count, a push failure or any git vocabulary — §29A's "no
  visible complexity" is about mechanism, not about hiding whether their work is safe.
  Parent Settings gets the count and the reason. `GitHubSync.status()` is the one place
  that decides, and both strings come from it.

  One detail worth keeping: **"Waiting for internet" is verified, not assumed.**
  `PushQueue.drain` keeps an entry only when the push raised `Offline`; a rejected or
  secret-blocked push is dropped and reported to a parent instead. So anything still
  queued really is waiting on the network — except an entry queued and not yet swept,
  which has failed at nothing and says plain "Waiting".

---

## 6D. How setup and the installation lifecycle work

Phase 8 is built. `WORKORDER_01.md` §35A is the specification, and DoD 51–53 is the
update half. Six things are not obvious from the code.

**The wizard cannot live in `bootstrap/`, and that shaped the whole phase.** Three
existing constraints collide: `tests/test_bootstrap_compatibility.py` enforces that
`bootstrap/*.py` stays Python 3.9 and never imports `opennest`; §35A requires the
installer's inference test to run *through the same provider code the app uses*; and
PySide6 does not exist until the bootstrap has installed it. So the wizard is
`opennest/setup/`, and `bootstrap.py` **starts it as a subprocess** once dependencies
verify. §35A's "do not tightly couple the installer to the primary application runtime"
is satisfied by process boundary rather than by duplicating anything. The dependency
only goes one way — the wizard imports `bootstrap.environment` for machine detection,
and the bootstrap still imports nothing from the app.

**The parent PIN is collected now, so every gate actually gates.** This was the
prediction in §6B and it has landed. `consent.ask_parent_pin` still returns True when no
PIN is set, and a parent may still leave it blank — forcing one is a way to lock someone
out of their own Mac. But once set, `arduino_upload`, `external_requests`,
`package_installation` and Parent Settings all genuinely stop.

One consequence needed fixing rather than noting. `Toolbox.network_policy` is consulted
**in the middle of a turn**, and a turn runs on a `QThread` so the window does not
freeze. Qt widgets may only be created and used on the GUI thread. Before Phase 8 this
was unreachable — `external_requests` sat at its `deny` default and the approver was
never called — and the wizard's parent page now offers "Ask Parent" as a supported
choice. `consent.approve` therefore marshals onto the GUI thread and blocks the caller
for the answer (`consent._on_gui_thread`). If you add another gate consulted from a
worker, it gets the same treatment for free by going through `approve`.

**A download reports success long before a model works.** Three separate measurements
say so (SPIKES.md §15), and the code is shaped around them:

- huggingface_hub 1.32 defaults to the **Xet** backend, where an exception raised from
  `tqdm_class` is swallowed — a cancel at 127 MB still fetched all 1,598 MB.
  `downloader` sets `HF_HUB_DISABLE_XET=1` and drives one backend. Do not "support both".
- The download runs in a **subprocess**, so Cancel is a kill rather than a request, and
  the read loop polls a queue so a stalled transfer cannot ignore the button.
- **Resume does not work** and is not offered. See the top of this file.
- A model is marked ready only after `downloader.verify` gets a real answer through
  `MLXProvider` — measured at 2.1 s, replying exactly `OPEN NEST READY`. Verification
  deliberately does *not* require those exact words: §35A's checklist is about the
  machinery, and failing a working model over its phrasing is the worse error.

**`installation.json` is written at last, and damaged metadata means repair.** It holds
§35A's fields plus a `Fingerprint` — the requirement digests, both config schema
versions, and every pinned model revision. Comparing two fingerprints *is* "detect
dependency, configuration-schema and model-definition changes". A file that will not
parse sets `unreadable`, answers `needs_setup()` True, and is **left exactly where it
is**; nothing here has a destructive step.

**The update protocol stops deliberately short of updating.** Decision D9, settled with
the developer:

- "Check for Updates" lives in Settings → Advanced, behind the parent PIN. Pressing it
  *is* the permission, so there is no fifth switch — and `external_requests` would have
  been the wrong one anyway, since that governs a *child's project* reaching the
  network, not the application contacting its own source.
- It runs `git ls-remote` and nothing else. No pull, merge, fetch-into-the-repo, reset
  or checkout, and `test_the_check_only_ever_runs_read_only_git_commands` fails if a
  future change reaches for one. Being offline is an answer, not an error.
- The launch *after* someone runs `git pull` finishes the job: `migration.plan` works
  out what moved, the work order's prompt is shown, dependencies are reinstalled through
  the bootstrap's own installer, and the new fingerprint is adopted **last and only on
  success** — recording it after a failed reinstall would tell the next launch there was
  nothing to do.
- A moved model pin is **reported, never started**. It implies gigabytes.
- A one-click in-app updater is a separate product feature. Do not grow this into
  self-update and restart machinery.

**D7 is resolved as AVR only.** `setup/toolchain.py` installs arduino-cli v1.5.1 and the
`arduino:avr` core, ~341 MB, behind its own wizard step. It is AVR alone because 324 MB
is the one core size anybody has measured; offering a menu would mean printing sizes
nobody checked, which is not how anything else here is sized. A child with an ESP32 or a
Pico still gets a board list without their board, so the decision is narrowed rather
than closed.

### The acceptance pass, and the four defects it found

**71 checks, 0 failures**, run against a *fresh copy of the tree with no `.venv` and a
fresh `OPENNEST_HOME`* (`spikes/` is gitignored; the driver lived in the scratchpad).
Measured, not asserted:

| | |
|---|---|
| `Setup Open Nest.command` | found no suitable Python and **installed CPython 3.12.14 itself** |
| Environment | 1.7 GB, all imports present |
| Model download | Qwen3 4B, 2.28 GB, **204 s**, progress `100% 2.3 GB of 2.3 GB` |
| Cancel | stopped at 63 MB in **4.5 s**, no orphaned partials, model correctly not "installed" |
| Verification | **1.5 s**, replied exactly `OPEN NEST READY` |
| Arduino toolchain | installed in **20 s**, 27 boards, entirely inside the containment root |
| Offline (Seatbelt) | every network path failed in **under 1 s** with readable text; nothing hung |

**Four defects, all now fixed.** Three of them only a real run could have found:

1. **Nothing installed `requirements/macos-apple-silicon.txt`**, so a fresh Mac had no
   mlx and no mlx-lm — no local AI engine at all, making Launcher DoD steps 9 and 10
   impossible. Exactly the shape of the `projects.txt` gap Phase 7 found. The bootstrap
   now installs it, Apple-silicon-gated and deliberately non-fatal, and
   `test_every_requirements_manifest_is_installed_by_something` would have caught both.
2. **The progress bar overstated the download.** `Reporting` summed `update()` across
   huggingface_hub's bars, which update the same bar twice for the same bytes, and the
   denominator was allowed to chase the count upward — a 2.28 GB model displayed
   *"4.2 GB of 4.2 GB"*. The denominator is now the catalogue's, and each bar is
   accumulated and clamped separately.
3. **The update check blamed the network for a missing branch.** `git ls-remote` exits 0
   with empty output for a branch the remote does not have, which was collapsed into
   "could not reach GitHub" on a perfectly connected machine.
4. **A completed download reported "failed".** A stale `Reporting.seen` reference
   survived the rewrite and raised *after* 2.3 GB had downloaded; the child's blanket
   `except` dressed it up as a download failure, for a model that was on disk and passed
   its inference test seconds later. The success line is now outside the `try`, with a
   test that fails if it moves back in.

### What is still not done

- **No pristine macOS user account.** This is the one part of §35A's exit criterion that
  remains open, and it is a release/integration item. What *was* reproduced is more than
  expected — fresh tree, no `.venv`, fresh `OPENNEST_HOME`, and the real
  install-our-own-CPython path. What was not: the **pip wheel cache was warm**, so the
  dependency install took seconds rather than the several minutes a truly cold machine
  would see, and nothing proves the behaviour with no Xcode Command Line Tools at all.
- **Nobody has clicked the wizard.** The pass drives the step objects directly under
  offscreen Qt, so it exercises the behaviour behind each control and not the control.
  The two dialogs where the wizard stops and asks a parent are stubbed, because a modal
  `QMessageBox` blocks forever with nobody to click it. Layout, tab order, focus,
  readability and whether the copy makes sense to an actual parent are all unverified.
- **Xet-versus-classic download speed** is unquantified, **cross-process resume** is a
  library limitation rather than a gap, and **network-drop resume** is untested. All
  three are accepted as non-blocking.
- **`_reinstall` runs pip synchronously behind an indeterminate progress bar.** Minutes
  with no percentage. Acceptable after a `git pull`; first thing to improve if it annoys.

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
| ~~D1~~ | ~~GitHub auth~~ | ~~Phase 9~~ |
| D8 | **Whether image generation shows its cost.** ~800 KB and 10–15 s per image, billed per image, with no count or total anywhere. A parent who turned cloud on for chat has also turned this on | before real use |
| D10 | **Whether a one-click in-app updater is wanted at all**, and if so what it does about local modifications, a moved model pin, and restarting a running app. Phase 8 deliberately stopped at "notice and report" — see §6D | after V1 |
| **D12** | **What "Ask before using cloud AI" should actually require, and how often.** Today it is a child-answerable dialog shown once per model switch. Two independent questions: (a) should it take the parent PIN, making it a real approval rather than an awareness prompt? (b) should it fire per cloud *request* rather than per selection, as `cloud_needs_confirmation`'s docstring already claims? A PIN on every turn makes cloud unusable; a PIN on none is the current state. A likely answer is PIN once per session or per project, but that is a product call. See the defect in §6B | before V1 |
| — | Only one model is verified and downloaded. The other three local ones are pinned and described but untested | — |
| — | All measurements are from a 48 GB Mac. The target is 8 GB | before V1 |

**Resolved in Phase 9 — D1: OAuth device flow.** A classic OAuth App with device flow
and the `repo` scope, the token in the Keychain and nowhere else. `gh` was rejected on a
measurement rather than a preference — it authenticates whichever account it happens to
be logged into, which makes "Connected as X" a claim Open Nest does not own and makes
Disconnect unable to revoke anything. A PAT works and §29A says to avoid one when
something better is supported. **Two things this leaves open**: the OAuth App is not
registered, so `CLIENT_ID` is empty and the feature reports itself absent; and the
classic `repo` scope is broader than needed, accepted as a documented V1 trade-off with a
GitHub App recorded as the tightening option. §6C-bis has both.

**New in Phase 9 — D11.** *Whether GitHub authorization should move to a GitHub App.* A
classic OAuth App's `repo` scope reaches every repository the parent can see, including
organisation ones; a GitHub App installation can be scoped to only the repositories Open
Nest creates. Security hardening, explicitly not Phase 9 work, and it changes the token
lifecycle (installation tokens expire) rather than just the registration.

**Resolved in Phase 8 — D9.** Checking for updates is a **parent action, not a new
permission**: it happens only when a parent presses a button in Settings behind the PIN,
so pressing it is the permission. `external_requests` governs a child's project reaching
the network and was the wrong gate. The check **reads and never writes** — `git
ls-remote`, no pull, merge or reset — and the launch after a real `git pull` runs the
migrations. Everything past that is D10. §6D has the detail.

**Also resolved in Phase 8 — D7**, narrowed rather than closed: AVR only, behind its own
wizard step, because 324 MB is the one core size that has been measured. A child with an
ESP32 or a Pico still gets a board list without their board.

**Closed in Phase 8:** the Git author identity. §35A step 2 collects it, it is stored in
`installation.json`, and `MainWindow` passes it to `VersionHistory.start()`. A parent who
skips the field still gets working version history — the fields fall back to
`git_manager`'s defaults.

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
