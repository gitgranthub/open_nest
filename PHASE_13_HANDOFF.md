# Phase 13 — the game drawn inside the Workbench

Read [HANDOFF.md](HANDOFF.md) first. This file is what Phase 13 built, what it measured,
and what is left. The measurements are SPIKES.md section 26; the specification was
PHASE_12_HANDOFF.md section 6.

**13A and 13B are built. Run Game plays the child's game inside the Build / Preview
panel, and "Pop out" gives it a window of its own and "Put back" brings it home -- the
same widget moved, the game never restarted (§8).** Before 13B, the owner-test pass (§7)
and a cross-preset parity pass (§7A) corrected the flow around it.

**13C -- the game graphics and scene layer -- is built (§9).** A child's picture becomes
the player, and a scene is described in plain words -- a sky, a road, buildings, cars to
dodge, coins to collect -- through one tool, `game_object`, that writes one readable line
per thing into the game and draws it with `src/scene.py`, a small pygame kit that lives in
the project. The look of a thing is separate from its movement and collisions. SPIKES §28
has the prototypes, the four-against-five tool benchmark and the acceptance walks.

**Phase 13 is complete and pushed** (`phase-13-live-preview`): 1525 tests with 13C (1430
before it), ruff clean, Phase 12 app walk 41/41. **Next: a person clicking it on a real
screen (§5), then Phase 14 -- Publish (§6).**

**13A: Run Game plays the child's game inside the Build / Preview panel.** The game still
runs in its own sandboxed process — the profile is byte-for-byte unchanged — and opens no
window; Open Nest paints what it draws and sends it the child's keys and clicks. One thing
is owed that no driver can do from here: **a person clicking the real window once** (§5).

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
| after §7, §7A and §8 | **1430 passed**, ruff clean; the Phase 12 app walk 41/41 with the same recipe routes; the Phase 13 walk offscreen 40/45, the same 40 as the pre-13B commit (the five misses are focus checks offscreen cannot activate); the owner-test and parity walks in `benchmarks/owner_pass/` |

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

- ~~**13B — pop out and put back.**~~ **Built** (§8).
- **Nobody has clicked it.** The walk's focus checks are Qt-activated (§3). A person
  should press Run Game in the real window, play with the arrow keys, click the chat and
  back, and press Tab out of the game -- and, since 13B, press Pop out, play in the
  window, Tab to Put back, and close the window (it must put the game back, not stop it).
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

### 7A. The cross-preset parity pass -- then frozen

The same fixes, checked beyond Games (SPIKES §27F): Website, Research (a real CSV),
Arduino (a real `arduino-cli` compile), Raspberry Pi, and Blank begun five ways, through
`benchmarks/owner_pass/parity_walk.py`. Small corrections only, each from a measured
miss: answers checked against the last three turns, with a correction that fits an
answer; the checked facts beside the question; a file changed between messages noticed;
bare JSON calls read and never shown; per-preset facts read from the files (a page's
headings, sections, menu, figures and missing pictures; a CSV's rows, words and ranges;
an Arduino's pins, board and last compile, and that nothing can test the board; a Pi's
pin with pretend pins); a run's charts counted as work done and clickable; numbers in a
data answer that nothing printed caught; compile claims checked; child-facing compile
messages; Blank becoming a game, data or Pi project, and saying plainly it cannot be a
website or an Arduino project.

Final: 49 turns across nine projects, no tool syntax or code in the chat, 36 questions
and none changed a file, every click showed the real file, every change marked.
Remaining loose wording and the two things that would need architecture work are in
SPIKES §27F. **Frozen; 13B followed (§8).**


---

## 8. 13B -- pop out and put back

The owner's original ask from the test drive ("an optional popout window and put back
option"), and small because of 13A: the game is a widget Open Nest owns
(`GameView`), so popping it out moves that widget into a window Open Nest also owns, and
putting it back moves it home. **The game never notices**: its process, its unchanged
sandbox profile and its one socket are exactly as they were, and the stream, its reader
and the view's poll timer carry on -- no restart, no missed picture.

| file | |
|---|---|
| `ui/game_window.py` | `GameWindow`: the game, a caption, and "Put back in Open Nest"; `window_size` -- the game's own size, fitted whole to 90 % of the screen, never narrower than the bar |
| `ui/workbench.py` | "Pop out" / "Put back" beside the game's caption; `_pop_out`, `_put_back`, `_popped`; every place that showed or hid the game in the panel now asks where it is |
| `agent/evidence.py` | the guide tells Gary the button exists, so "can I make the game bigger?" has a real answer |

**The rules it keeps:**

- **Closing the window puts the game back; it never stops it.** Stop is in the Workbench.
- **No keyboard trap.** In the window, Tab moves from the game to Put back.
- **The game goes home before anything takes it away**: a change that makes it stale, a
  run that replaces it, closing the project. Each puts it back first and then does what it
  always did, so there is one path for stopping a game, not two.
- **Code on screen does not hide a popped game.** While Gary builds, the code has the
  panel to itself and the game keeps playing in its window.
- **The panel says where the game is** ("Your game is playing in its own window. Put back
  brings it here.") and so does Gary, from the guide.

**Verified**: 10 new tests (`tests/test_game_view.py`), including **the real Basic Game
under the real sandbox drawing new pictures while popped out and again once put back,
through one stream the whole time**; the suite (1430), ruff clean; the Phase 13 walk and
the Phase 12 app walk re-run (SPIKES §26J). Rendered offscreen: the panel with the game,
the panel while it is out, and the window.

**Not done**: nobody has clicked it on a real screen -- the same caveat as 13A (§5): macOS
will not activate a background process, so focus in the popped window is Qt-activated in
the tests. A person should pop it out, play, press Tab to Put back, and close the window.


---

## 9. 13C -- the game graphics and scene layer

The owner's work order after 13B, from the owner test: `eagle.png` in Assets, Gary saying
the eagle was the player, and the orange starter square on screen. **Gary makes the
creative decisions; Open Nest executes the boring implementation.** Not a template system:
no `add_eagle`, `add_car`, `add_town`. SPIKES §28 has every measurement; this is the
architecture.

### 9.1 What it is

```
Gary (any model)                       Open Nest (opennest/graphics)            the child's game
  game_object(name="cars",      ->  looks.py   checks the look          ->  src/game.py:
    drawing="vehicle",                         (a real picture? a colour     cars = scene.add("cars",
    color="red", count=3,                      the kit knows? shapes in          Vehicle("red"), size=(80, 40),
    moves="left", on="road",                   their own box?)                   on="road", count=3,
    touch="avoid")                source.py   finds the game's loop, fill,       moves=(-3, 0), layer="things")
                                              flip, player, scene -- with ast   ...
  <- {"ok": true, "object":       game_object.py  decides WHERE and WHAT    scene.update()
      "cars", "placed":                          statement; returns the       screen.fill(BACKGROUND)
      "standing on road", ...}                   files and a JSON result      scene.draw()
                                  Toolbox._game_object writes them through
                                  the same path + parse checks as edit_file  src/scene.py: the kit
```

| file | |
|---|---|
| `graphics/kit/scene.py` | **the kit**: the pygame helper copied into a project as `src/scene.py`. pygame and the standard library only; ~920 commented lines a child can read. Looks, shapes, ready-made drawings, `Thing`, `Scene` |
| `graphics/looks.py` | what Gary asked a thing to look like, checked and written as code: pictures found from the child's words, colours the kit knows, shapes moved into their own box, the kit's palette read from the kit file itself |
| `graphics/source.py` | reads and edits the scene in a game's own source with the parser: the `scene.add(...)` statement for a name, the loop's `scene.update()`/`scene.draw()`, the statements that draw the player, the loop that draws a list, the rules it added. Whole-line edits only; `describe()` says the scene in words for Gary |
| `graphics/game_object.py` | the tool's work: which thing a name means, what changes, where the statement goes, what is refused, and the JSON result |
| `agent/tools.py` | `game_object` schema and `_game_object` (every file checked before any is written); `write_file`/`edit_file` refuse a picture's or sound's filename |
| `execution/playtest_harness.py`, `playtest.py` | the test records what the kit's `Scene.report()` says it drew; `Playtest.scene`, bounded and checked like everything from the child's process |
| `agent/evidence.py` | Gary is told the scene from the code, the window size, what the test drew and what was never on screen, a sky hiding the fill, drawing the scene paints over, a loop that flips twice |
| `fastpath/kinds/games.py` | `facts_of` (the parser on a source string), `brief`/`where` know the scene, `use_sprite` calls `game_object`, a `picture_drawn` check, `thing_look` skips a constant nothing reads; **since §9.11 `add_things` gives every thing's look through `game_object`** (`_look_call`, the ship through `_ship_call`) and `thing_drawn` checks the scene drew it on screen |
| `fastpath/kinds/game_things.py` | each noun's look as `game_object` arguments -- a ready-made drawing or the kit's basic shapes, in the thing's own colour constants (`scene_look`); the old inline `pygame.draw` code is gone |
| `fastpath/executor.py` | a recipe's edits first, then its tool calls, so each call reads what the edits left |
| `recipes/games/*.json` | `guide_scene`: the pattern Gary is given, when his project has `game_object`, points at it instead of hand-written drawing code |
| `config/profiles.json` | `game_object` is the Games profile's fifth tool (§9.6) |

### 9.2 The primitives

**Looks** -- what something is drawn as. Every look makes a picture of itself at a size,
once, and blits it centred on a rectangle.

| | |
|---|---|
| `Picture(path)` | a picture file: loaded once, see-through parts kept, fitted without stretching. A missing file or one that is not a picture raises `SceneError` -- it is never quietly a rectangle |
| `Animation(sheet, frames=N, fps=8)` / `Animation([paths])` | frames from a sprite sheet (the grid nearest to square cells: the brand's 12-frame 2172x724 wing cycle is 6x2) or a list of files |
| `Drawing((w, h), [shapes])` | shapes in the drawing's own box: `Rect` (rounded, outlined, or a two-colour fade), `Circle`, `Ellipse`, `Triangle`, `Polygon`, `Line` (dashed), `Text`. Drawn at 3x and smoothed |
| ready-made drawings | `Vehicle`, `Building`, `House`, `Tree`, `Cloud`, `Road`, `Ground`, `Sky`, `Coin`, `Star`, `Platform`, `Sign` -- each is only the shapes above, worked out for the size it is drawn at (a `Vehicle` 120 wide is a long car, not a stretched one). Twelve generic forms, not objects: a vehicle is a car, a bus, a taxi |
| `Colour(fill)` | a plain box -- the square a new game starts with |

**Things and the scene.**

- `scene.add(name, look, ...)` puts something in the scene or replaces what is there under
  that name. `size`, `at` (a corner, or a list of corners), `on` (the name of what it
  stands on), `count` (a row spread across the screen; moving rows spread over the loop
  they travel), `vary` (copies of different sizes on one ground line), `moves` = (x, y) a
  frame, `edges` = "wrap" (comes back round -- only off the side it is heading for) or
  "bounce", `hitbox`.
- A scene-made **`Thing` is a `pygame.Rect`** -- its collision box -- so `x`, `center`,
  `colliderect` and `collidelist` all work on it: a recipe's `player.collidelist(cars)`
  keeps working when the scene makes the cars.
- `scene.add(name, look, rect=player, scale=1.5)` / `rects=cars` draws **the game's own
  rectangle** with a look, `scale` times its size keeping the look's shape. The game
  keeps moving and colliding it; the scene only draws it. This is how the player's look is
  separate from its logic: the picture follows the rect when `PLAYER_SIZE` changes.
- `scene.touching(rect, name)` (every frame of a touch), `scene.touched(rect, what)` (once,
  in the frame a touch begins -- kit version 2, §10), `scene.reset(name)`, `scene.get(name)`,
  `thing.respawn()`.
- `scene.update()` moves what moves by itself; `scene.draw()` draws everything **back to
  front by layer**: `background`, `scenery`, `things`, `player`, `effects`, `ui`; within
  a layer in the order added. `scene.report()` says what each thing is and how many
  frames it was drawn in and on screen.

**The palette.** "red", "skyblue", "gray" and ~30 other names draw softer shades that sit
together (flat, "clean modern mobile game"); anything pygame knows works too.

### 9.3 How Gary uses it

One tool, `game_object`, with the creative decisions as its arguments: `name`, `picture`
(and `frames`), `drawing`, `color`, `text`, `shapes`, `size`, `at`, `on`, `layer`, `count`,
`moves` (left, right, up, down, bounce) and `speed`, `touch` (avoid, collect), `remove`.
The child never sees any of it; Gary's reply is ordinary words.

What a name means, in order: **the player** ("player", the player's variable, or the name
of the picture it wears) -- its look is swapped and its rectangle, keys and collisions are
untouched; **a thing already in the scene** -- only what is given changes; **a list the
game already draws** (a recipe's cars, or Gary's own) -- drawn by the scene instead, the
loop that drew it taken out; asked to move somewhere, a recipe's list whose code is still
exactly what the recipe wrote is handed to the scene with its speed and count constants,
its rules kept; **anything else** is new.

What Open Nest decides, so the model does not have to:

- **Placement**: a sky fills the screen and is drawn first; a road or ground is a band
  across the bottom; buildings, trees and vehicles given nowhere stand on the road or
  ground; one placed just above a road (both models put cars 40-80 px above it) stands on
  it; statements go where what they depend on already exists.
- **Adoption**: the first call adds `from scene import ...`, `scene = Scene(screen)` and
  the two calls in the loop, and changes nothing else in the game.
- **Rules**: `touch: avoid` writes "touching it sends the player back to where this game
  starts it"; `touch: collect` scores a point and adds a score if there is none. Both are
  once per touch (`scene.touched`, §10).
- **What goes**: the player's old drawing (the starter's rect, the old sprite recipe's
  blit, test03's `try` that drew a square), unused `player_image` lines, and colour
  constants nothing draws with any more -- so an edit to `PLAYER_COLOUR` cannot "succeed"
  invisibly.
- **What it refuses**, each with the reason and where to go: a picture that is not one; a
  picture the child never tied to this thing (with one picture in a project, the 4B used
  `eagle.png` for an apple); a name that is how the game plays (timer, lives, score, jump,
  game over, title -- "that is edit_file"); a change that changes nothing; a game with no
  one loop to draw in; a `src/scene.py` that is not the kit, or a changed kit missing what
  the change needs.

Gary is also told, every turn, from the code: the scene back to front, where things stand
against the road, the window size, what the last test saw drawn and what was never on
screen, a sky hiding the `BACKGROUND` fill, anything drawn between the fill and
`scene.draw()` that the scene paints over, and a loop that flips twice.

### 9.4 Grounded results, and the checks on what Gary says

Every call returns JSON: `ok`, `object`, `action` (added / changed / removed), `look`,
`picture`, `drawn_size`, `collision_box`, `layer`, `count`, `placed`, `moves`, `touch`,
`kept` (what was left alone), `does_not` (it reacts to no key), `notes` (every adjustment
made), `files_changed`, and `check`; or `ok: false` with a `reason` and a message. When
Gary says nothing, Open Nest describes the turn from these results.

The honesty guards already there apply unchanged -- a refused call leaves no change for a
claim to rest on. Added for scenes: a number said about a thing in the scene is checked
against its count ("three cars" about one car -- measured); "the town" is checked as its
buildings; a request turn's "the road" with no road is told to make it or say it is not
there; a reply that changed something and ends promising more is pushed once to do it.

### 9.5 Verification, the preview, Undo

Unchanged: the headless playtest after every change still decides repair, and passes or
fails on the same four verdicts. What it adds is evidence -- the scene's own record of
what it drew and how much was on screen -- and the re-pointed sprite recipe now also
checks `picture_drawn`: the test saw the player drawn with that picture, on screen. A
picture that stops loading later crashes the test (with "cannot load 'assets/eagle.png'")
instead of hiding. The embedded preview plays scene games like any other (they are
ordinary pygame); `src/scene.py` is under `src/`, so it is fingerprinted and a changed
scene retires a running game as stale. Undo restores `src/game.py` and removes a
`src/scene.py` the turn created (`read-tree`).

### 9.6 The fifth tool

`game_object` is the only tool a profile has added since Phase 1's four-tool rule, and
it was measured before it stayed (SPIKES §28C): 94 Games requests, the real 4B, first move
acceptable **43 with four tools, 62 with five**; 6 how-it-plays requests sent to it, 3 of
them names it refuses. `test_no_profile_offers_an_explore_tool` allows five for Games
only; any other fifth tool needs its own measurement. Blank does not have it -- its games
keep the drawing patterns (`guide_scene` is used only where `game_object` is offered).

### 9.7 Portable

The game stays ordinary Python and pygame. `src/scene.py` is plain, commented source in
the project -- no Open Nest import, no network, no build step -- and pictures are found
from the project folder (`src/..`), so `python src/game.py` works from anywhere, with or
without Open Nest. `VERSION` lets Open Nest tell its own copy from one the child changed;
a changed kit is used as it is and never overwritten, and since version 2 an earlier kit
Open Nest shipped, byte for byte, is brought up to date by the next change (§10).

### 9.8 Limits, recorded rather than hidden

- **The 4B still decides the layout, and its layouts are uneven** -- a 20 px road, cars
  at 60x80, a 128 px eagle. Defaults, the snap and the facts help; what it asks for is
  drawn. A stronger model composes better with the same calls (SPIKES §28E).
- **It makes one call a reply in a long conversation**, and a big request can be half
  done: the carry-on push catches the promise, the named-thing check the claim; neither
  makes the model do more than it will.
- **Motion is left, right, up, down or bounce.** Chasing, zig-zagging and orbiting stay
  code (edit_file or the Fast Path's recipes); a recipe's things that move those ways keep
  their own code when restyled and are not handed to the scene.
- ~~**The Fast Path's add-a-thing recipes still write inline pygame.**~~ Done in §9.11:
  every one gives its look through `game_object`. Their *motion* stays their own code --
  chase, zigzag, wave and orbit are not motions the scene has, and their drift and fall
  keep per-thing lanes the scene's rows do not.
- **Nothing sees the picture.** The tool knows a picture's format, size and transparency
  and the child's words for it; it never says what it shows, and it cannot know which way
  an eagle faces.
- ~~**No stronger API model was run.**~~ Luna was, on 2026-09-30, with a key the owner
  handed over (SPIKES §28K); Claude still has no working key.
  ~~Blank projects do not have `game_object` yet.~~ A Blank project that has become a
  game does, since §9.11 -- measured first.

### 9.9 Where image generation plugs in later

Not built. The seam is the look: a generated picture is a file in `assets/`, and
`game_object(name="car", picture="assets/red_sports_car.png")` then works exactly as for
the eagle -- checked as a real picture, drawn by the scene, reported. A future
`image_request` path (the Image Creation profile already talks to an image service under
parent control) would write that file and hand its path to the same call; nothing in the
scene or the kit changes.

### 9.10 Where 13C was paused (historical -- §9.11 finished it)

Paused at the owner's request with the tree green (1525 tests, ruff clean) and committed.
State of the evidence then:

- **Final walks** (`benchmarks/graphics/results/`): `walk_4b_final` (local 4B, the
  documented run: 9 turns, 0 code or tool syntax in the chat, 9/9 playtests passed, 4/4
  Run Game frames, every reply matching the game) and `walk_8b_final` (Qwen3 8B, the
  stronger model). Earlier runs are kept under their numbers; SPIKES §28E says what each
  found. Phase 12 app walk 41/41 (`results/app_walk_13c.txt`).
- **Not re-walked after the last change**: the snap range was widened to catch a thing
  standing up to 30 px below a thin road's lower edge (unit-tested only). Re-run
  `benchmarks/graphics/eagle_walk.py <label>` once to confirm.
- **Open, in priority order**: (1) a person clicks it on a real screen; (2) a working
  cloud key, then the same walk with `claude-sonnet` (SPIKES §28F); (3) the Fast Path's
  add-a-thing recipes still write inline pygame -- making them call `game_object` is the
  natural next step (§9.8); (4) Blank projects have no `game_object`; (5) the playtest's
  two seconds miss a crash that comes later (`pygame.random`, SPIKES §28G).
- **Traps** are in HANDOFF §4 ("Phase 13C traps"): measure any change to `game_object`'s
  description with `benchmarks/graphics/tool_choice.py`; a new recipe that adds a thing to
  see needs a `guide_scene`; drawing by hand goes after `scene.draw()`.

### 9.11 Finishing 13C -- the same building blocks for the Fast Path, Blank, and Gary

The owner's closing order kept the architecture and named the boundary: **Gary makes the
creative decisions; the scene layer gives reliable building blocks; Open Nest must not
become a template game maker.** The twelve ready-made drawings are defaults, not
canonical objects, and a new request is never answered by adding another named one.
What was done, in the order it was asked (SPIKES §28H-N has every measurement):

1. **The re-walk after the road snap** (`walk_4b_snap`): the final scene still coherent
   -- a tree placed 10 px under a thin road stands on it; 9 turns, every playtest passed.
2. **The real app, clicked** (`spikes/phase13/graphics_click_walk.py`, **45/45** under
   cocoa, `results/click_walk.txt`): the town built from the child's words, Run Game, the
   eagle picture on screen, the arrow keys moving it, Pop out with the same process still
   drawing and the keys working there, Put back, a visual change seen on screen, Undo back
   to the exact earlier code and the old sky on screen. It found no defect in the app; it
   found a game-feel one (a dodging game can pin the player at its start while a car
   crosses it -- §28I) and two things a driver must do (wait for Run Game's startup
   check before typing; measure a key during the hold). Still Qt-activated, not a person.
3. **The Fast Path's things through the scene** (§28J). All five add-a-thing recipes --
   enemy, collectible, moving thing, dodging game, catching game -- write the thing's
   logic and give its look with **one `game_object` call**, the ship included; ~110 lines
   of per-noun inline `pygame.draw` code are gone. No `add_car`, no new drawings: a car is
   the kit's vehicle, a coin its coin, everything else the basic shapes, in the thing's
   own `..._COLOUR` constants. The things are now in the scene's layers, the playtest's
   record and Gary's facts, and `thing_drawn` checks the test saw them on screen. The
   Phase 12 app walk: 41/41.
4. **The same primitives for both**, verified and held by tests: every look a recipe
   gives is `game_object`'s own vocabulary; the kit's ready-made drawings are exactly the
   twelve generic forms. Converting the recipes also found places where **Gary could not
   change something the layer claims he can**, each fixed generally: a colour alone on
   the player or the game's own rects (refused), a sign's words (dropped on recolour), a
   drawing of shapes (could not be recoloured), a list of rects nothing drew yet
   (refused), `layer` and `touch` on the game's own rects (ignored). What Gary can change
   on anything in the scene, recipe-made or not, is now: look (a picture, a drawing,
   shapes), colour, size, place, what it stands on, how many, how it moves, layer, what
   touching it does, and whether it is there -- each tested.
5. **Blank** (§28L): measured first -- a Blank project that is the Basic Game, 50 -> 68 of
   94 first moves acceptable with `game_object`, the same gain Games had -- so a Blank
   project whose files are clearly one pygame game is offered it (`tools.offers_graphics`,
   `toolbox.allowed`), with the measured prompt; any other Blank project keeps four tools.
   Its result says it is not tested there, because it is not.
6. **The stronger API model**: Luna, with the owner's new OpenAI key (§28K). The eagle
   sequence composed richly from the same primitives -- the whole town from the first
   sentence, coins along the road, every playtest passing, no tool words in the chat --
   and found one real defect: later in a layer is drawn in front, and nothing told the
   model (now `drawn_over` in the result). Claude's key is still rejected.
7. **Truthfulness kept, and tightened where the new path touched it**: a text file under
   a picture's name is still refused by `write_file`/`edit_file`; a picture that does not
   load still crashes the test; a picture asked to change colour is now refused
   (`keeps_its_colours`) rather than counted as landed; a recipe's thing drawn off screen
   fails its check and is rolled back; `game_object`'s result about the game's own rects
   says what the game's code does, not "stays where it is"; count, avoid/collect,
   on-the-road, town and refused-edit checks unchanged and green.
8. **The playtest's two seconds** are a separate hardening item (§28N), with the options
   and what each costs. It caused no acceptance failure here.

**The finish line** -- several visibly different worlds from the same primitives, no
object type added (SPIKES §28M, `benchmarks/graphics/scenes_walk.py`, any model): five
worlds -- a sea, a space run, a farm, a snowy night town, a Blank project's garden -- each
the model's own composition of the same twelve generic forms, shapes and colours. The
local models' are crude; Luna's are rich, and it drew a fish, jellyfish, coral and a
rocket from shapes that nothing in Open Nest names. Along the way the walks found and
fixed: a background recipe that swallowed "a black sky full of stars with a planet"
into one colour (a `not_words` veto), a made-up drawing name answered with a silent box
(now: how to compose it), two claim-check misreadings ("the deep sea", "full of little
stars"), a model copying a tool's result into the chat (`presentable` now drops tool
talk -- and applies the same protocol filters to every provider's replies, local or
cloud: `ai/protocol.py`), and later-in-a-layer drawn in front with nothing saying so
(`drawn_over`). **The graphics layer gives Gary better building blocks; it does not decide
the game for him.**

### 9.12 The picture how-to (after 13C)

Gary cannot make picture files, and neither can a bigger model. When a turn meets a thing
only a picture would draw well -- a drawing the kit has not got, a picture the project has
not got, the child's picture of something else -- Open Nest ends the reply with how to
make one: a PNG with a see-through background at a size worked out from the thing in the
game, + Add to Project, and what to say. Tools are named by kind only, a drawing app or an
AI picture maker with a grown-up (the owner's ruling, 2026-09-30). A picture used with a
solid background is said to show as a rectangle. `AgentController._picture_how_to`;
SPIKES §28O. The automatic cut-out is designed, not built (HANDOFF "What is next").


---

## 10. The cross-preset stress pass -- before the owner's in-person test

The owner's order after 13C: no new architecture; a conservative stress test of Website,
Research, Arduino, Raspberry Pi and Blank across four models -- the local Qwen3 4B
(baseline) and 8B (spot check), OpenAI Luna (cloud baseline) and Anthropic Sonnet (cloud
spot check, run for the first time) -- and the known touch bug fixed. SPIKES §29 has every
finding, the fix each got, and the matrix; `benchmarks/stress/` has the driver, the table,
the results and a summariser.

**The touch bug** (§29B): `scene.touched(rect, what)` in the kit (`VERSION = 2`) -- true in
the frame a touch begins, not while it lasts, again after they part; `touching` unchanged
for what lasts. The avoid and collect rules `game_object` writes use it, the dodging
recipe's hit uses it, an unchanged v1 `src/scene.py` is brought up to date by the next
change (a changed one never), and Gary is told -- in the edit's result and in his facts --
when his own counter counts every frame. In the Blank-game walks Luna then wrote its own
`lives -= 1` under `scene.touched`.

**What the pass fixed**, all in the shared layer, none for one provider (§29C): a Run
press no longer counts as a change (so a false "I updated main.py" in an answer is
checked); a reply that tells the child how to edit instead of editing is not relayed, and
an answer that does is offered "Want me to make that change for you?"; what a real board or
Pi did is not said; a chart drawn on the way to a plan is said; a colour a website's files
do not have is not claimed; the Arduino facts say what `loop()` does; a reply repeating
what an Undo took back is corrected; "There it is." is a look nobody took; the Research
starter charts a table of numbers against its first column and prints what it drew; the
Flight Deck's cards are in the guide; Open Nest's own fallback text reads cleanly; and
three false positives in Open Nest's own checks, found by Sonnet and the 8B, are gone.

**Verified**: 1622 tests (1572 before; `tests/test_stress_pass.py` and the kit and rule
tests in `tests/test_graphics.py` are this pass's), ruff clean, the Phase 12 app walk 41/41
under cocoa with the same recipe routes, and ten stress runs -- 269 turns, 158 questions,
none changed a file -- the last five on the final code with nothing flagged (SPIKES §29D).

**Rules this pass adds:**

- **A kit change is a version bump and a hash.** A new `scene.py` behaviour needs
  `VERSION` raised and the old file's SHA-256 in `looks.EARLIER_KITS`, or projects holding
  the old kit will run new code against it. `tests/fixtures/scene_kit_v1.txt` is v1.
- **Say what the starter does.** Two findings (Arduino, Research) were models reasoning
  correctly from facts that did not say what the starter code does. A starter's
  description and the per-preset facts are grounding, not labels.
- **A check that corrects a true sentence is a bug.** Every new reply check was run over
  every reply of every walk before it stayed (§29C); keep its fixtures in
  `tests/test_stress_pass.py` when you touch it.
