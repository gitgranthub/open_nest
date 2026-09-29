# Phase 13 — the game drawn inside the Workbench

Read [HANDOFF.md](HANDOFF.md) first. This file is what Phase 13 built, what it measured,
and what is left. The measurements are SPIKES.md section 26; the specification was
PHASE_12_HANDOFF.md section 6.

**13A is built and verified: Run Game plays the child's game inside the Build / Preview
panel.** The game still runs in its own sandboxed process — the profile is byte-for-byte
unchanged — and opens no window; Open Nest paints what it draws and sends it the child's
keys and clicks. **13B, pop out and put back, is next** and has not started. One thing is
owed that no driver can do from here: **a person clicking the real window once** (§5).

The owner's direction for the phase, kept as its rules: the live view is the child's
*experience*, never proof that a feature is right — the invisible playtest stays the
verification layer, unchanged; the sandbox stays unchanged; no Fast Path or classifier
work; and the white sunglasses are reserved for publishing a version (§4).

---

## 1. What it is

```
child's process (confined, unchanged profile)          Open Nest
  live_shim.py runs src/game.py, unmodified              LiveStream (reader thread)
  SDL_VIDEODRIVER=dummy -- no window                       keeps the newest picture only
  flip()/update() --- changed frames, over ------------>  GameView polls it at 60 Hz,
  set_caption()   --- the window title  one socket         paints it scaled and whole
  key.get_pressed & co. <--- keys and clicks ----------   keys, clicks, release-all
```

| file | |
|---|---|
| `execution/live_shim.py` | runs inside the child's process, imports nothing from Open Nest, like the playtest harness. Frames out only when the picture changed; input posted into the game's own queue and answered through `key.get_pressed`, `get_mods`, `mouse.get_pos/get_pressed`; `event.wait` waits on the channel |
| `execution/live_view.py` | the receiving end, no Qt. `LiveStream`, the message format, the checks, `without_shim_frames` |
| `execution/python_runner.py` | `run_project(..., live=True, on_live=...)`; `Output` reads an interactive run's output for as long as it runs; `finished(result)` says how a still-running project ended; `stop_project` marks `output.stopped` |
| `ui/game_view.py` | `GameView`: the picture, the keyboard (after a click), the mouse (in the game's pixels), focus |
| `ui/worker.py` | `RunWorker`: Run Game starts the game off the GUI thread |
| `ui/workbench.py` | the panel: shows the game from its first frame, reports how it ended, retires a game made stale by a change or an Undo |
| `agent/tools.py` | `Step("playing", live=stream)`; `_run_project` passes `live` for Games |
| `config/profiles.json` | `"live_view": "pygame"` on Games, and nowhere else |

### The rules it keeps

- **The sandbox does not change.** `wrap()` is called exactly as before, no device, no
  network; the only new thing the game gets is one inherited Unix socket back to Open
  Nest, which connects to nothing else. `test_a_live_run_is_confined_by_exactly_the_ordinary_sandbox`.
- **Everything the game sends is untrusted.** Fixed binary header, sizes bounded before
  anything is allocated, exact lengths, only the newest picture held, the title decoded
  as plain one-line text of bounded length. Anything else ends the stream and the
  Workbench stops the game. A real hostile game is in the tests.
- **Input never blocks Open Nest** (§3, second trap).
- **The playtest is untouched and still decides repair.** Nothing the live view shows is
  evidence of anything; `playtest.py` and `playtest_harness.py` are as they were.
- **One route, whoever runs it.** The child's Run Game and Gary's `run_project` both draw
  in the panel. A run Gary starts never takes the keyboard from the chat; Run Game does.
- **The panel only shows the version the files hold.** Code and pictures are
  fingerprinted when a game starts; after a turn that changed files, or an Undo, a game
  whose fingerprint no longer matches is stopped and taken away, and the test's still is
  shown. That includes a game Gary started this turn and then changed again.
- **How it ended is said, and only what happened**: "Stopped." when Open Nest stopped it,
  "The game ended." when it ended itself, the error line with Show technical details when
  it crashed. **A crash during play is now recorded as the last run**, so Gary's facts say
  it failed, with the child's own `src/game.py` line; before this, nobody saw a crash
  after the startup check, and his facts said "it is running now".
- **The game's window title is shown** beside it, because the game has no window to show
  it in: "Call my game Eagle Patrol" is otherwise invisible.
- **Run Game starts the game on a worker** (`RunWorker`), so the panel keeps painting
  through the four-second startup check and the first picture appears in ~0.3 s. Send
  waits until the start finishes — one project runs one thing through its Toolbox.

### Found and fixed on the way

- **Any interactive project that printed a lot froze** once its unread output pipe was
  full — a game printing a line a frame stopped dead ~12 s in (SPIKES 26B). Fixed for
  every interactive run, Pi test loops included, because it is the same code path.
- **A test that could never fail.** `test_every_placement_name_is_used_or_removed`
  scanned `brand.py`, where every placement is defined, so it counted all of them as
  used. It skips `brand.py` now.

---

## 2. Verification

| | |
|---|---|
| suite | **1303 passed** (1256 before), ruff clean |
| new tests | `test_live_view.py` (25: the channel and what it refuses, the output reader, real games under the real sandbox — the starter steered, a crash mid-play, an `event.wait` game, Escape, a game writing junk to its channel, a printing project), `test_game_view.py` (22: the widget, the Workbench, and Run Game through the real worker thread and sandbox) |
| the Phase 13 walk | `spikes/phase13/live_walk.py`, MainWindow under cocoa, real model: **45/45**. First picture 0.26 s after Run Game; an animated game draws 56.6 fps and 56.3 pictures a second reach the panel; generation 43.1 tok/s without a game and 44.4 with one streaming |
| the Phase 12 app walk, unchanged | `spikes/fastpath/app_walk_fastpath.py`: **41/41** on this branch |

---

## 3. Things that will bite you

- **A pipe is the wrong channel.** Each 640x480 frame is about fifteen 64 KB reads, each
  re-taking the interpreter lock; with Open Nest's main thread busy in Python the stream
  fell to 12.7 frames a second *and dragged the game down with it*, because a full pipe
  blocks the game's `flip`. A socket pair with 4 MB buffers held 55. SPIKES 26A.
- **`MSG_DONTWAIT` on a macOS Unix socket send still blocks.** Honoured for a receive,
  not for this send. Open Nest's end is non-blocking instead, the reader waits in
  `select`, and input goes through a bounded buffer that holds only whole messages.
  Found by the test written to prove it could not happen. SPIKES 26C.
- **A process with no window sleeps late.** macOS gives it loose timer deadlines: every
  `sleep` overshoots by ~5 ms and `clock.tick(60)` gave 46 fps against 56 in a window.
  Thread QoS did nothing, App Nap was not it; the task role AppKit gives a frontmost app
  (`TASK_FOREGROUND_APPLICATION`, set by the shim for its own process) restores the
  windowed timing exactly. It is a scheduling class and grants nothing. SPIKES 26D.
- **Focus needs an active window, and macOS will not activate a background process.**
  Driven from anything other than a person, `isActiveWindow()` stays False and
  `hasFocus()` is False everywhere — so "focus left the game" passes whatever the code
  does. The walk reports the real state and then sets Qt's active window, labelling
  those checks. §4 of HANDOFF has the same family of vacuous-assertion traps.
- **Attaching a stream delivers its title at once.** Reset the caption *before*
  `attach()`, or it is wiped as soon as it arrives (measured: the caption fell back to
  the project name).
- **`run_in_thread` deletes its thread when it finishes.** `wait()` on it afterwards
  raises `Internal C++ object (WorkerThread) already deleted`.
- **An interactive run's pipes belong to `Output`'s threads.** Never `communicate()` on
  one — `_terminate` waits for the process instead when an `Output` is given.
- **Showing a game was the cost, not reading it** (SPIKES 26G): reading the stream is
  ~5 % of a core, and the first version spent ~40 % more converting every RGB frame and
  smoothing a picture that, on a Retina panel, was really being enlarged. Frames travel
  in Qt's native layout (`BGRA` = `Format_RGB32` here) and smoothing is decided in device
  pixels. A native child window (`createWindowContainer`) did not help at all.
- **A game stopped by Open Nest is not a failed run.** `stop_project` sets
  `output.stopped` before it terminates, and nothing reads an exit status without
  checking it. (Pygame answers SIGTERM by quitting cleanly, so the status is often 0
  anyway; do not rely on a signal number to tell the two apart.)

---

## 4. The white sunglasses — the owner's ruling, applied

**Reserved for one moment: a child publishing a version.** The creative director's quiet
nod — no confetti, no animation, no celebration, and Gary never announces it. Not a run,
a recipe, a playtest, Run Game, a completed turn, a checkpoint or Save a Version, a
compile, a preview, a finished setup, or any accomplished stage: those are ordinary state
and text. If a publish's final check fails, there are none, and the project stays a
draft. `brand_design_guide.md` §38 carries the ruling; §54 and §58 point to it.

What changed, because Publish does not exist yet and so **nothing shows them today**:

- the Workbench's first-success mark is gone — `_mark_first_success`, `FIRST_SUCCESS`
  ("You built that."), `completed()` and the milestone bookkeeping;
- the setup wizard's finish page says "Open Nest is ready." with no graphic;
- the `completion_glasses` placement is removed; the artwork stays in `brand.py`'s mark
  table, and its accessible name is now "Version published";
- `test_the_sunglasses_are_reserved_for_publishing_a_version` fails if any screen reaches
  for them. It is the test Publish changes, deliberately, to allow that one screen.

`manifest.last_successful_run` is still stamped by the Toolbox: memory uses it.

---

## 5. What is not done

- **13B — pop out and put back.** The owner's original ask. Now small: the game is a
  widget Open Nest owns, so it moves into a window of its own at the game's full size
  and back, the stream never interrupted. Do it next, once 13A has been used.
- **Nobody has clicked it.** The walk's focus checks are Qt-activated (§3). A person
  should press Run Game in the real window, play with the arrow keys, click the chat and
  back, and press Tab out of the game.
- **Gary running the game mid-turn has not been seen from the model.** Asked twice, he
  edited instead. The `playing` step is tested; a real turn that runs the game is not.
- **Showing a game costs Open Nest 11-22 % of one core** at 54-60 pictures a second
  (SPIKES 26G), down from 44-46 % in the first version. Measured on the 48 GB M4 Pro
  only; the lever left, if an 8 GB Air needs it, is repainting at 30 a second (25 %
  against 39 % in the synthetic test, before the two fixes).
- **A windowless game gets foreground scheduling even while Open Nest is in the
  background.** A windowed game would have been demoted by AppKit. Harmless on a desk,
  worth knowing on battery.
- **The Pi's test loop still shows only "The project is running."** Its output is now
  read (the freeze fix) and bounded, so showing it live is a small addition — not done.
- ~~**Games in a Blank project still open a window of their own.**~~ **Played in the
  panel since the owner-test pass** (§7, `plays_in_panel`): once a Blank project's entry
  file imports pygame, Run plays it here. Blank still has no headless test, so a game
  there is still not checked after a change, and its recipes stay guidance.
- **OpenGL games** (`pygame.OPENGL`) cannot draw under the dummy driver. The playtest has
  always had the same limit.
- **The segfault at interpreter exit is fixed** (SPIKES 26H): a model call on the main
  thread -- only the close-time summary -- runs with MLX compilation off, so no
  main-thread compile cache is left for `exit()` to destroy after Python has finalised.
  Both walks now exit 0. **Quitting while Gary is mid-turn is fixed too** (SPIKES 26I):
  the turn is stopped at its next safe point through its call budget and the Workbench
  waits for its thread, so no running thread is destroyed at exit; what the turn had
  changed is kept and checkpointed.

---

## 6. Publish — the owner's concept, recorded for a later phase

Not Phase 13 work. It reshapes Phase 14 (PHASE_12_HANDOFF.md §7, "getting work out of
Open Nest"), and Phase 13 was built so as not to paint it into a corner.

**Draft / working project** — continually editable; Run / Preview; Save a Version and
Undo; no sunglasses. **Published version** — the child deliberately decides *this
version is ready to show*; Open Nest verifies it one final time where appropriate; a
named, versioned snapshot is kept ("Eagle Patrol — Published v1 — Sep 28, 2026"); the
child keeps editing afterwards, and a later publish makes v2. Publish means "ready to
show", never "finished".

```
Working Project -> Publish Version -> final checks -> frozen release snapshot
    -> project-type outputs -> share / open / export
```

- **Publish and Share are separate.** Publish makes a stable release; Share sends or
  exposes one. A child can publish without sharing, and Share works on a published
  release, not on half-edited files.
- **Outputs by project type, from the same release.** Games: a cover image (a clean
  captured frame, the title, perhaps a small published mark), a playable Open Nest
  package, a GitHub release/tag. Research: a PDF report, the charts, a results snapshot,
  the package. Websites: a local snapshot, a zip of the static files, GitHub, later Pages.
  Arduino / Pi: code, wiring notes, instructions, a printable PDF, the package — and
  never any implication that touching hardware is safe.
- **An Open Nest package** (`Eagle Patrol.opennest`): project type, release metadata,
  files, assets, launch and runtime/profile information, a cover, title and author
  display name, compatibility version, a manifest of included files, and checksum or
  signature metadata later. Opened by someone else it is **viewer/player first**: "This
  project was shared with you" -> Play / Preview Site / View Report / View Project ->
  optionally **Make My Own Copy**, and only then editing or hardware. Never automatic
  execution of arbitrary downloaded code: games stay sandboxed, hardware is never touched
  automatically, network references stay under Open Nest's policy. Designed as a
  capability, not as an exception to the sandbox.
- **Sharing** through the macOS share sheet (Messages, AirDrop, Mail) rather than custom
  integrations; GitHub remains the storage layer and Open Nest the child-friendly way in.
  Peer-to-peer: no marketplace, no hosted community.
- **The sunglasses** belong to a successful Publish, after its final checks — not to
  Share, and never when the checks fail.

**What Phase 13 leaves ready for it:**

- `live_view` and `live_shim` know nothing about the Workbench, a conversation, a model
  or a Toolbox: `run_project(directory, command, interactive=True, live=True)` plays any
  project directory under the ordinary sandbox, and `GameView` shows any `LiveStream`. A
  package's play-only mode is those two pieces pointed at an unpacked release.
- `GameView.current_frame()` is a clean frame the game actually drew, which is what a
  cover image wants — though the playtest's still (`.opennest/tmp/playtest.png`) is the
  one taken under controlled input.
- Export is still a privileged application action under HANDOFF §5's rule, not a tool.

---

## 7. The owner-test pass — before 13B

The owner used 13A for real and the flow around the game was not sound. This pass fixed
that flow and nothing else: no 13B, no classifier or gate change, no new recipe, no
Publish. SPIKES §27 has the trace, the reproduction and every walk.

**What was wrong**, from the owner's own project archive (`test02`): the Game project had
been begun with **Start Empty**, so no recipe could act and Run said there was no
`src/game.py`; every `edit_file` the 4B model produced was **written out as Python text**,
so no tool ran and the chat showed the call; "the eagle is now flying" was not a phrase
the honesty guard knew, and a reply opening "I haven't changed any file yet" exempted
everything after it; the **caught claims stayed in Gary's history**, so the next turn
repeated them, and closing the project wrote them into the bible as decisions; "next" took
a step off the list before trying it. The game on screen was never stale -- it was exactly
the starter, which is what the owner saw.

**What changed** (all project types unless it says games):

| | |
|---|---|
| empty project | Set up on its first *request* with the profile's default kit (`_set_up_if_empty`); Blank only when the child names a game, as the Basic Game in `src/main.py`; a question is answered instead. Start Empty stays. No message names `src/game.py` |
| tool syntax | A call written as Python is run through the Toolbox (`mlx_provider._text_call_spans`, parser-checked, tool names only) or dropped; `replies.presentable` keeps long code, argument lines and repeated paragraphs out of the chat for every model |
| questions | Answered in one turn with **no tools and no recipe** (`build_answer_prompt`): the voice, the project type's first lines, the guide to the screen and the checked facts. "what are the controls?" no longer rewrites the controls |
| what Gary knows | `agent/evidence.py`, every turn: the entry file exists or not; still exactly a starter; what is in the game and the keys it reads (games); a named thing in the code but never drawn, or made again every frame (games); what the last message really changed; an Undo or a starter added by hand; whether the game on screen is the current code; the last test, only while it is about this code; "nothing has been run yet" |
| the history | Settled at the end of every turn to the child's message, the calls and results, and the reply the child read (`_settle_history`); rollover after it |
| claims | "is now" / "Creating ..." / "it's there now" with nothing changed; "I see"; "I'm adding" after a denial; a thing the child named that no code has (games, identifiers only); a looping reply; a promise ending a turn that did nothing -- corrected once, planned, or made an offer; never relayed |
| edits | One that leaves the file as it was is refused (`no_change`), not counted as a change |
| plans | A step is done only when a file changed for it (and, in a game, its thing is drawn and not made every frame); one that did not land is retried, never skipped; "next" compares the files with how the last turn left them first and says so; an Undo back before a step reopens it; a question in between keeps the plan; the planner never re-plans a step; plain offers, no "say next" |
| Project panel | "● new" / "● changed" in muted green beside what the last message touched (`MarkDelegate`); one click shows the code with those lines marked; "Show the game" / "Show the page" goes back, and Preview always brings the page back |
| Blank games | Played in the panel (`plays_in_panel`) instead of a window of its own that timed out after 120 s; still no headless test there |

**Verified**: the suite (1398, ruff clean), the Phase 12 app walk (41/41, same recipe routes), and `benchmarks/owner_pass/owner_walk.py` --
the owner's sequence through the real Workbench and model on a Game project begun empty,
one begun with its starter, a Blank project, a Website begun empty, a Research and a
Raspberry Pi project. Results and each step's source are in `benchmarks/owner_pass/results/`.

**Still true after it** -- recorded, not hidden:

- **The 4B model still mostly cannot write the eagle game.** Its edits are refused (its
  new code does not parse, or matches nothing), and when one lands it is often the
  12.3 shape -- the thing made inside the loop. What changed is that Open Nest now says
  so: "That step didn't get made, so I haven't moved on to step 2."
- **Descriptions of *motion* are not checked.** Open Nest can say a thing is not in the
  code, not drawn, or made every frame; "it flies left and right" about code that moves
  it only on a key is not something the parser decides.
- **Answers are only as good as a 4B model reading a guide.** Most are right now ("Arrow
  keys: move the player (orange square). Escape: quit the game."); some still wander to
  the eagle. The answer turn is where a stronger selected model helps first.
- **The build prompt is ~30 % longer** (1557 -> 2029 tokens on a Games turn). Tool
  selection was not re-benchmarked; the Phase 12 app walk is the regression check that was
  run.
- **The owner's `test02` still holds the memory written before this pass** (its bible
  describes an eagle that was never made). Nothing rewrites a child's memory files
  automatically.
- **Website claims are checked only by the general guards**; the named-thing and "drawn"
  checks are games-only, where they were measured.
