# Handoff — start here

Read in this order: [WHATS_NEW.md](WHATS_NEW.md) (the latest pass, one page), then this
file, then [SPIKES.md](SPIKES.md) for the measurement behind any rule you want to change.
[HANDOFF_ARCHIVE.md](HANDOFF_ARCHIVE.md) is the full history and the reasoning behind every
line below. It uses the **same section numbers**, so "HANDOFF §4" in a code comment means
§4 here, and its full text is in the archive. The phase handoffs (PHASE_10 to
PHASE_13_HANDOFF.md) hold each phase's detail.

Keep this file short: what is true now, and the rules. History goes in the archive or a
phase handoff. WHATS_NEW.md is rewritten at the end of every pass.

## Where it stands (2026-10-04)

- **Built through Phase 13, on `phase-13-live-preview`.** It has seven project types and a
  nine-step setup wizard. Local AI is Gary Fast or Gary Smart (Qwen3-VL, both see
  pictures), with optional cloud AI. The game plays inside the Workbench and has a scene
  layer, and a 3D Block World starter for 3D games. The Fast Path handles common
  requests with recipes. There is invisible version history with Undo, project memory,
  and GitHub backup. **1797 tests pass, ruff is clean.**
- **The game builds pass (SPIKES §33, WHATS_NEW.md).** Neither local model builds a whole
  game from one sentence, and before it neither drew anything 3D. A 3D ask now gets the
  3D Block World. Beginning a Game on Gary Fast warns that it struggles with games
  (`struggles_with` in `models.json`). Gary Smart measured about even with Gary Fast at
  2D games, and better at changing the 3D world. Cloud was unmeasured: both saved keys
  were refused.
- Branches are stacked, one per phase, and nothing is merged to `main`. Branch Phase 14
  from `phase-13-live-preview`.
- **Phase 12 is still formally open.** Its definition of done, "a child asks for a game
  and gets one", is the owner's call to close. Never confuse *faults fixed* with
  *outcome met*; an earlier version of this file did.

**What is next**

1. **The owner tries the game builds pass**: a 3D game ("create a simple, block 3D
   game", test05), the warning when a Game is begun on Gary Fast, the Platform Game card.
   Two calls for the owner: whether Gary Smart should get the warning too (it was about
   even at 2D games, SPIKES §33B/§33D), and new cloud keys (`.env`, as before) so
   `benchmarks/game_builds/build_walk.py <label> claude-sonnet` can measure a cloud Gary.
2. **The owner re-runs test04 and the maze on Gary Fast.** On a Mac set up before the
   vision pass, the first launch after `git pull` reinstalls the requirements (network
   needed), and Gary Fast is downloaded from Settings. **An 8 GB Mac is still
   unmeasured.**
3. **The background cut-out.** `Picture(path, see_through=True)` in the kit: the corner
   colour's connected area made transparent with `pygame.mask`. Raise `VERSION` to 5,
   add v4's SHA-256 to `looks.EARLIER_KITS` with a v4 fixture, and add `see_through` to
   `game_object`. Because that changes the tool's description, re-run
   `benchmarks/graphics/tool_choice.py` first.
4. **Phase 14, Publish Version**, as the owner reshaped it (PHASE_13_HANDOFF §6,
   PHASE_12_HANDOFF §7). Not started; the sunglasses wait for it.
5. **Hardening** (SPIKES §28N). The playtest sees under 2 s of a game, so a crash behind
   a timer is missed. Gary can repeat one refused call until the budget runs out.
6. **Known limits, recorded:**
   - Gary Fast's whole-game turn tries to rewrite the file first.
   - Gary Smart ignores the child's monster picture.
   - Cloud providers send no pixels.
   - The models' layouts are uneven.
   - A Blank project cannot become a Website or Arduino project in place.
   - Whole games in one sentence (a platformer, a side-scroller, the cat game) fail on
     both local models; Open Nest offers a plan.
   - In the 3D world, neither model adds a new kind of block to `WORLD`, and Gary Fast
     lowered `WALK_SPEED` when asked to walk faster.

## 1. Where the project is

| Phase | State |
|---|---|
| 0–3 Skeleton, sandbox spikes, core slice, durability | done (PRs #1–#4) |
| 4 Memory and thread rollover | done (§6) |
| 5 Assets | done (§6A) |
| 6 Cloud AI, credentials, parent controls | done; Sonnet, Haiku and Luna verified against the real services (§6B) |
| 7 The remaining profiles | done; Arduino compile verified, upload never tried on a board (§6C) |
| 8 Setup wizard and installation lifecycle | done (§6D); a pristine-account run is still open |
| 9 GitHub backup | done, verified against the real GitHub (§6C-bis) |
| 10 Design and polish | done (PHASE_10_HANDOFF) |
| 11 Starter kits, Website, model registry | done (PHASE_11_HANDOFF) |
| 12 Owner test drive | **open** (PHASE_12_HANDOFF); 12.1–12.5 closed: truthfulness, editing, playtest loop, Fast Path |
| 13 Game in the Workbench, scene layer, owner passes, vision models | done (PHASE_13_HANDOFF, SPIKES §26–32) |
| 14 Publish Version | not started |

PR numbers do not match review order: review 1 → 2 → 3 → 4 → 6 → 7 → 5 → 8 → 9.

## 2. Get running

```bash
./Setup\ Open\ Nest.command          # no .venv yet: installs its own CPython 3.12.14
./Launch\ Open\ Nest\ Demo.command    # the app on the dev sandbox, .opennest-sandbox
.venv/bin/python -m pytest -q         # 1750 tests, ~4 min -- run it UNWRAPPED
```

| Phase | Command | Network |
|---|---|---|
| Fetch | `scripts/fetch.sh model <id>` / `deps` / `arduino` | on; pinned artifacts only |
| Anything that loads the model | `scripts/offline.sh <command>` | off; writes confined |
| The test suite | `.venv/bin/python -m pytest -q` | not used |

Some things cannot go through `offline.sh`, because Seatbelt does not nest: the suite,
the replays and the app walks. Run them unwrapped with `HF_HUB_OFFLINE=1`. Everything
the dev setup writes is under `.opennest-sandbox/`.

## 3. Map of the code

```
opennest/
├── agent/       controller.py (the turn loop, repair, honesty checks, plans), tools.py,
│                replies.py (what a reply may say), evidence.py (what Open Nest has
│                checked), budget.py (one call budget per turn)
├── ai/          provider.py (the interface), mlx_provider.py (local, incl. vision),
│                anthropic/openai providers, protocol.py (shared reply filters), router.py
├── assets/      importing the child's files; look.py (what a model saw in a picture)
├── graphics/    game_object and the scene kit copied into a game as src/scene.py
├── fastpath/    classifier on Gary's own model, router, recipes executor, verifier
├── recipes/     the recipes, JSON per profile (data)
├── memory/      project bible, state, compaction, history search, safety (secret scan)
├── conversations/  context budget, archive, rollover
├── execution/   running child code, playtest, live view, Arduino
├── models/      catalogue, machine, discovery, compatibility (the model registry)
├── setup/       the wizard, downloader, health check, updates, migration
├── github/      device flow, private repos, push queue
├── security/    sandbox.py (paths), process_sandbox.py (Seatbelt), keychain, permissions
├── ui/          PySide6; theme.py owns every colour; worker.py owns every thread
├── config/      models.json, profiles.json (data, not code)
└── prompts/     the prompts (data)
bootstrap/       runs before a modern Python exists: 3.9-compatible, never imports opennest
benchmarks/      measurement drivers and kept results (replays, tool choice, Fast Path)
```

## 4. Things that will bite you

*Each line is a measured trap; the archive §4 and SPIKES have the evidence.*

**The model shapes the design**
- Profiles get **four tools**; Games has a fifth, `game_object`. Both counts were measured
  (SPIKES §4, §28C). There is no list or lookup tool: inject what the app knows into the
  prompt.
- `edit_file` is how files change; `write_file` refuses to overwrite.
- Use temperature 0 for tool selection. MLX at temperature 0 is not exactly repeatable,
  so report each run.
- Guidance for one kind of request goes beside that message, not in an always-on prompt.
  Measure any always-on prompt change with `tool_choice.py`. Example sentences in a
  prompt get copied as replies.

**Honesty: the app checks, it never trusts the prompt**
- Check `turn.text` (what is on screen), not `reply.text`. Exempt a plain denial. Never
  name a cause you have not checked.
- Validate a check or reply filter on the kept replies before it ships. A check that
  corrects a true sentence is a bug.
- Gary's history is settled every turn (`_close_turn`). Anything the next turn needs goes
  in the prompt (`agent/evidence.py`), never in the history.
- A question never reaches the Fast Path or a tool (`replies.is_question`).
- Reply filters are shared by every provider (`ai/protocol.py`,
  `replies.presentable`). `AgentWorker.chunk` is the raw stream: never show it.
- **Pictures:**
  - A picture is seen only when `asset.seen` says so (`assets.look`), never because a
    vision model is selected.
  - Pixels travel only with the message they came with. Rebuild that message with
    `dataclasses.replace`, or they are dropped.
  - See-through pixels must be laid on white (`prepare_picture`).
  - Looks happen outside the turn's call budget.

**The Fast Path (frozen before Phase 13)**
- The gate uses `agreement` across orderings, not `score`.
- The "exactly one change?" gate is load-bearing.
- New options go at the end of `index.json`.
- Project facts go in the question, never the fixed prompt, which is the cached prefix.
- A recipe edits only where its check can run.

**The game layer**
- A change to `game_object`'s description means re-running `tool_choice.py`.
- A recipe's look is a `game_object` call. There are twelve ready-made drawings, by the
  owner's ruling, and no more.
- A Thing is a `pygame.Rect`. `touched` fires once per touch; `touching` fires every
  frame.
- A kit change is three things: `VERSION` raised, the old SHA-256 in
  `looks.EARLIER_KITS`, and a fixture.
- Draw after `scene.draw()`, never between the fill and it.
- **A 3D game is the 3D Block World starter** (`graphics/block_world.py`). It is
  recognised from its code (`WORLD`, `BLOCKS`, `FIELD_OF_VIEW`). `game_object`, the Fast
  Path and plans step aside in it. A game the child changed is never swapped for it. Its
  knobs are one edit each (`SKY = "night"`); a look that took two edits got one from a 4B.

**Sandbox, macOS, toolchains**
- Seatbelt does not nest. `run_project` fails closed; never weaken it to pass a test.
- `mlx_lm.load("<repo>")` contacts the Hub, so resolve a local snapshot path first.
- macOS paths are case-insensitive: `.GIT/HEAD` opens `.git/HEAD`. Compare casefolded.
- **Arduino:** the sketch folder must be named after its sketch, and every `arduino-cli`
  call names its data directory.
- **Downloads:**
  - `du` says nothing about a Hugging Face cache, because blobs are shared. Remove with
    `scan_cache_dir`.
  - `snapshot_download` does not resume.
  - Xet ignores a cancel, so set `HF_HUB_DISABLE_XET=1`.
- **GitHub:**
  - `git push` can hang forever: the `http.lowSpeedLimit` settings are load-bearing.
  - Clear `credential.helper` on every authenticated call.
  - A private repo says "not found" to an anonymous `ls-remote`.
- `mlx-vlm` is installed `--no-deps` (`requirements/vision.txt`). `pip check` complains,
  by design.

**Qt (read before writing any)**
- Use `ui.worker.run_in_thread`, never the `moveToThread` + `started.connect` idiom,
  which silently never runs.
- Never `deleteLater` a worker, and never connect a lambda to a worker signal.
- `QTest.qWait` starves workers; use a nested `QEventLoop`. A modal dialog blocks
  forever offscreen, so stub it.
- `isVisible()` and `isVisibleTo()` are vacuous on unshown widgets and in a stack. Use
  `isHidden()`.
- Never let MLX compile on the main thread, never abandon a running turn's thread, and
  never destroy a widget while its worker runs.

**Models and setup**
- The app starts `router.startup_model_id(preferred)`, not the default. A `deprecated`
  model runs where it is installed and is never offered.
- A capability flag on a model is not a capability of the system: `verified`,
  `supports_images`.
- `struggles_with` (`models.json`) is measured data: it decides the warning when a kind
  of project is begun on that model (`router.model_advice`). Never name a model in code.
- Every machine-dependent decision is handed the `MachineProfile`. Only
  `models.machine.detect()` looks at hardware.
- Requirements are pinned; bumping one is a deliberate edit. `opennest` may import
  `bootstrap`, never the reverse.

## 5. Security model — do not weaken this

| Layer | Protects |
|---|---|
| `security/sandbox.py` | paths through Open Nest's own file tools |
| `security/process_sandbox.py` | code Open Nest **runs**: no network, writes confined, kernel-enforced, fails closed |

- **Privileged actions** (upload, deploy, export, publish) stay sandboxed and are granted
  one more thing, explicitly and enforced. For example, Arduino upload may write only to
  the selected `/dev/cu.*`. An ordinary profile is byte-identical without the grant.
- **Credentials:** keys and the parent PIN are only in the Keychain (`keychain.py` has no
  file I/O). Commits are refused if anything is credential-shaped. No test touches the
  real Keychain (`FakeKeyring`).
- The live game view adds no grant: one socket pair, with everything from it treated as
  hostile. The TOCTOU between validating a path and opening it is accepted and
  documented in `sandbox.py`.

## 6. The subsystems, briefly

- **6 Memory.** Memory is injected into the prompt, never fetched by a tool.
  `project_state.md` is written but not injected. Superseded decisions never reach the
  prompt. A rollover cannot fail, because it has a deterministic fallback. Every memory
  write goes through `memory/safety.py`.
- **6A Assets.** Open Nest states facts about a *file*, and about a *picture* only what a
  model was really shown (`asset.seen`). It believes the child's account of a file. The
  invention check is narrow on purpose. A model without tools is refused for a project
  (`router.unmet_requirements`).
- **6B Cloud.** Cloud needs the parent's switch **and** a saved key. Request quirks live
  in `models.json`, and capabilities are declared, not inferred. One budget of twelve
  calls per turn covers everything, counted on dispatch. An output cap covers hidden
  reasoning too. A model the key cannot reach is said out loud, never substituted.
- **6C Profiles.** A profile is data, including how it finishes (`run_mode`), and the
  main button dispatches by profile. Hardware is never invented: no preselected board,
  and `LED_BUILTIN` rather than a pin number. Generating a picture is not seeing it.
- **6C-bis GitHub.** Sign-in uses OAuth device flow (`CLIENT_ID`) on the parent's
  account; the child's name goes on the commits. The token never touches disk
  (`GIT_ASKPASS`). The push scan reads blobs. Only offline is worth retrying. A review
  branch is made before the change.
- **6D Setup.** The wizard lives in `opennest/setup/`, started as a subprocess by the
  bootstrap. The parent PIN makes every gate real; `consent.approve` marshals to the GUI
  thread. A model is ready only after a real inference, and a vision model must also
  name a red picture. Damaged metadata means repair, never reset. **Check for Updates**
  only reads; the launch after `git pull` reinstalls, and adopts the new fingerprint
  last.

## 7. Working agreements

- Make the smallest correct change and stay in scope. Read the code and this file first.
- Pin third-party artifacts to a commit SHA. For an experiment, download one or two
  artifacts, not a candidate set.
- Run the tests and `ruff check .` before saying something is done. Say plainly what is
  not done, and measure rather than list caveats.
- Commit finished, verified work on the phase branch and push it. Never commit to
  `main`, and never commit an untested tree.
- At the end of a pass, rewrite WHATS_NEW.md and update "Where it stands" here. Move
  anything historical to the phase handoff.

## 8. Open decisions

| # | Decision |
|---|---|
| D8 | whether image generation shows its cost (none is shown today) |
| D10 | whether a one-click in-app updater is wanted at all |
| D11 | moving GitHub sign-in to a GitHub App, scoped to Open Nest's repositories only |
| D12 | what "Ask before using cloud AI" should require (today a child-answerable dialog, once per switch) |
| D13 | which model classifies for the Fast Path when Gary is a cloud model (wired, off) |
| — | measuring on an 8 GB Mac, the target; everything so far is from a 48 GB Mac |
