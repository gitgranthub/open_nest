# Phase 12 — the owner's test drive, and what clicking it found

Read [HANDOFF.md](HANDOFF.md) first. This file is what Phase 12 measured, what it fixed,
and what it deliberately left alone.

**Phase 12 is complete.** The acceptance defect — Gary narrating changes he has not made
— was reproduced through the real interface in Phase 12.1, traced to three separate holes
in one existing guard, fixed in `agent/controller.py`, and re-measured by driving the
same three turns again. **§8 has the investigation and what it found.**

One thing §8 recorded turned out to be false, and it matters for anyone reading the old
version: the tools *were* running. The failure was never "no tool call".

**Phases 13 and 14 are specified at the bottom of this file.** Nothing in either has
started.

---

## 1. The one sentence

Eleven phases built an application that did not work when clicked, and 980 tests passed
the whole time. `ui/worker.run_in_thread` silently dropped every background worker, so
the setup wizard hung on step 3 of 9 with Continue and Back disabled, the local model
never finished loading, and a child's message to Gary never ran.

Nothing about that was visible from the suite, and nothing about it was visible from
rendering a screen and looking at it — the two things every earlier phase did.

---

## 2. What was wrong, in the order it hurt

Full measurements in SPIKES.md §20. Short version:

| | |
|---|---|
| **No background work ran at all** | `moveToThread` + `started.connect(worker.run)` loses the worker under PySide6 6.11.2. Eight call sites. §20A |
| **A lambda handler runs on the worker thread** | So `_model_ready` swapped a Flight Deck status row from off the GUI thread. Exposed by fixing the above. §20B |
| **Closing the window during the model load aborted the process** | exit 134, macOS crash report. `closeEvent` never waited for the loader. §20C |
| **The interface could not be used without a mouse** | The Flight Deck's whole tab chain was `QScrollArea -> Settings`. Every card in the product was `NoFocus`. §20F |
| **Return did nothing in the wizard, and Escape ended setup** | Qt picked "Show other options" — on a different step — as the default button. §20G |
| **Two sentences that contradicted each other** | "nothing will be downloaded … it will be checked after it downloads". §20H |
| **Closing a project left a running game on screen** | Stop lived on the Workbench, so nothing could reach it afterwards. §20I |

Everything above is fixed, with tests. 1011 pass, ruff clean.

---

## 3. Things that will bite you

**A test that reaches behaviour through an inline seam says nothing about the thread.**
This is the lesson of the phase. `tests/test_wizard.py` uses `LocalAIStep.inspect_now`,
the seam that exists so a recommendation can be tested for a Mac nobody owns — a good
seam, and the reason the threaded path had never run once. `tests/test_worker.py` is the
counterweight: it drives `run_in_thread` directly and asserts the three things that
matter (it runs, it runs off the GUI thread, the result arrives on the GUI thread).

**PySide6 holds a receiver QObject weakly in a signal connection, and it does the same
for a bound method built at connect time.** Both bit, in that order, and each fix looked
complete until the next thing was measured. `WorkerThread` overrides `QThread.run` so
there is no connection involved at all. **Do not go back to the idiom** — it is the one
in every Qt tutorial and it does not work here.

**Do not add `thread.finished.connect(worker.deleteLater)` back.** Holding the worker
makes Python its owner, and asking Qt to delete an object Python owns frees it twice.
Measured as a SIGSEGV.

**`QTest.qWait` starves worker threads of the GIL — 140x, measured.** A pure-Python loop
took 0.07 s on the main thread and 10.02 s on a worker while the main thread spun
`qWait`. That turned a 0.02 s machine inspection into a minute and produced a confident,
wrong diagnosis before it was caught. Every driver in `spikes/phase12/` uses a nested
`QEventLoop` instead, which is what `app.exec()` does. If you write a Qt driver, do the
same.

**`requirements/base.txt` is pinned now, and this is why.** `PySide6>=6.7,<7` let the GUI
toolkit change under the product between one `pip install` and the next, which is exactly
the class of failure §20A is. The repo pins model weights to commit SHAs; it should not
have been letting its window toolkit float. Bumping a pin is a deliberate edit, and the
thing to run afterwards is `spikes/phase12/` — the suite cannot see this class of change.

**Qwen3 8B and 14B are *thinking* models; the 4B is not.** `Qwen3-4B-Instruct-2507`
answers; `Qwen3-8B` and `Qwen3-14B` emit `<think>` blocks. `mlx_provider._render` now
passes `enable_thinking=False` (measured: the 8B's template gains a pre-closed
`<think></think>`, the 4B's ignores it byte-for-byte) and `strip_tool_calls` removes any
block that survives, including an unclosed one. If you add a local model, check which
kind it is.

---

## 4. The drivers

`spikes/` is gitignored, so these are not committed. They are worth keeping.

| | |
|---|---|
| `spikes/phase12/drive.py` | the harness: checks, screenshots, modal answering, tab-chain walking, a `pump` that does not starve threads |
| `spikes/phase12/keyboard.py` | tab order, focus and keyboard reachability across four surfaces — **17/17** |
| `spikes/phase12/wizard_walk.py` | all nine wizard steps, real clicks, real modals — **51/51** |
| `spikes/phase12/app_walk.py` | WORKORDER_01 §42 steps 21 onward, against the real local model |
| `spikes/phase12/probe_*.py` | one measurement each: the quit crash, the inspection thread, `run_in_thread` four ways, the wizard's keys, `enable_thinking`, the game window |
| `spikes/phase12/verify_8b.py` | Qwen3 8B through `downloader.verify`, with resident memory |
| `spikes/phase12/thinking_model.py` | a real turn through both local models, side by side |

Three rules they follow, each learned the hard way and each worth keeping:

1. **A check that could not run is a FAILURE**, never an omission. SPIKES §17F's lesson.
2. **`detail` is printed on failure only.** The first app-walk transcript read
   `[PASS] the run finished — the run never came back`, because the detail string was a
   failure explanation shown on both.
3. **Disarm a modal answerer when its stage ends.** One left running caught the New
   Project dialog two stages later and closed it, reporting two failures for one bug.

---

## 4A. What the owner asked for while watching, and what happened to each

Four asks came in during the drive. Three were defects in disguise.

**"Results from Research saved as a document or PDF … and sharing or exporting any of
the projects."** *Not built — it is Phase 14 (spec in §7).* Confirmed first: the only
export in the entire product is the diagnostic log in Settings → Advanced. A child
cannot get a chart, a report or a project out of Open Nest onto the Mac at all.

**"Is where we create new projects or load previous projects easy to find?"** New, yes
— seven profile cards under the question. Previous, **no, and it was broken**:
`flight_deck.py` was `list_projects()[:6]` with nothing offering the rest, so a seventh
project was on disk and unreachable from the interface. Fixed: six, then "Show all N
projects", which is a row like the others so it is reachable by Tab and Return.

**"Is there a manual save button?"** There was not. Autosave and per-turn checkpoints
only, with `VersionHistory.save` sitting there and Undo as the one thing exposing any
of it. Added "Save a Version" beside Undo. It says "nothing new to save" when autosave
already took it, rather than writing an identical second version or doing nothing
visible.

**"Include safe modern Python libraries to prettify the reports … seaborn?"** Added,
with a validated palette. See §4B — it is the one that needed real design work.

## 4B. The chart style

seaborn is in `requirements/projects.txt` and the Research profile's package list. It
was chosen over plotly and altair for a reason that is about this product rather than
about charts: both of those render through a browser, and this one runs offline in a
sandbox and shows a PNG. seaborn is a thin layer over matplotlib, so **Gary can still
be told to change a colour, a label or a font** and the instruction works.

**The palette is computed, not chosen.** Full measurements in SPIKES §20J. The short
version: the brand has one accent and three status colours, two of which a series may
never borrow, so the rest had to be derived and then validated for colour-blind
separation. Three candidate sets failed before one passed.

Two things to know before touching it:

- **The slot order is the accessibility mechanism.** Adjacent pairs were checked for
  deuteranopia, protanopia and tritanopia. Re-order them and that stops being true,
  and nothing about the render looks wrong. `test_the_chart_palette_is_the_one_that_was_validated`
  is what will catch you.
- **`sns.set_theme()` destroys the style.** Measured: it replaces the whole rc, cycle
  back to seaborn blue-and-orange, background back to white. The first draft of the
  research prompt asked for exactly that line. It now names the trap, with a test.

**It is delivered as data, not as instructions.** matplotlib reads a `matplotlibrc`
from the working directory and `run_project` runs from the project directory, so the
style is a file in the research starter kit and every chart picks it up with no import
and no setup call. That also makes it the child's — "change the colours" is one
editable file, which is the same thing the starter-kit rule already says about every
other file in there.

## 5. What is not done

- **Still a 48 GB M4 Pro.** Every measurement in this repository. The target is 8 GB.
- **Qwen3 14B and Coder 30B have never been run.** 8B is verified now; those two are
  pinned, sized and described. 14B is called a thinking model on the strength of its
  name and the 8B's behaviour, not a measurement.
- **Ollama and LM Studio were still not seen.** The search on this Mac found the two Qwen
  models and correctly declined a `faster-whisper` model with a reason. Neither Ollama
  nor LM Studio is installed here, so the copy that declines *them* is exercised only
  against mocked payloads. Unchanged from Phase 11, and stated again because the owner
  asked about it.
- **No pristine macOS user account.** Unchanged from Phase 8; a release item.
- **Five of seven rows in the model picker say "Recommended for this Mac"** on a 48 GB
  machine, because everything fits. Accurate, and does no ranking work at that size.
  Noticed and deliberately not changed — the headline above it answers the question, and
  on an 8 GB Mac the labels differ.
- **The child never sees text stream in.** `AgentWorker.chunk` is emitted and nothing is
  connected to it, so the transcript updates once, when the turn ends. Noticed while
  tracing the worker signals. Not a Phase 12 defect — it has always been so — but it is
  the difference between a 16-second silence and a reply arriving as it is written.

---

## 6. Phase 13 — the game preview in the workbench

The owner asked for this while watching the test drive: *"the preview window for game
building must open in the workbench too, locked into the window system of Open Nest …
and optional popout window and put back option."*

**Phase 12 built the cheap version, measured it, and removed it.** Read SPIKES §20I
before starting — the removal is the useful part.

The constraint: a game runs out of process because `process_sandbox` is the product's
outer security boundary, and **macOS has no API for adopting another process's window
into a Qt view**. X11 has `QWindow::fromWinId`, Windows has `SetParent`, Cocoa has
neither. Running Pygame in-process would make it embeddable and would hand generated
code the application's own memory.

Positioning the child's window over the Build / Preview panel works — measured exactly —
and was withdrawn because Open Nest can *place* another process's window but cannot
**clip** it. A game larger than the panel overflows the application, it can be dragged
away, and Mission Control treats it separately. Half-docked sets an expectation the
implementation cannot keep. SDL also already centres the window by default on macOS, so
the positioning was solving a problem that did not exist.

**The route that works, with the feasibility already measured:**

```
child process (confined)              Open Nest
  SDL_VIDEODRIVER=dummy                 GamePanel widget
  hook pygame.display.flip  --frames-->   paints a QImage
         ^                                     |
         +-------------- input events ---------+
```

- **Capture is cheap.** `SDL_VIDEODRIVER=dummy` with a hook on `pygame.display.flip`
  captured 180 frames at **0.06 ms/frame**; 192 KB per 320x200 RGB frame, headroom far
  past 60 fps. The child keeps its own loop timing.
- **The shim has to be injected**, not asked for. A child's `game.py` calls
  `pygame.display.set_mode` and `flip` directly and must not have to know about any of
  this. `python_runner` already builds the child's argv and environment, which is where
  a `-c` preamble or a `PYTHONSTARTUP`-style wrapper goes.
- **Input has to go back.** Keyboard and mouse from the Qt panel, translated to
  `pygame.event` posts. This is the half with the real design in it.
- **Pop out and put back become trivial**, because by then the game is being drawn into
  a widget Open Nest owns — reparenting your own widget is allowed.
- **The sandbox does not change.** The child stays confined; frames and events go over a
  pipe the runner already owns.

What to keep from Phase 12: `Workbench.release` stops a running game, with a test. That
defect was real and is independent of how the preview is drawn.

---

## 7. Phase 14 — getting work out of Open Nest

Asked for during the test drive: *"make sure results from Research can be saved as a
document or pdf to the computer and that goes for sharing or exporting any of the
projects."*

**Nothing exists today.** The only export in the product is the diagnostic log. A
finished chart, a findings write-up, a working game — none of them can leave.

This is not a small feature, and the reason is the security model rather than the UI.
Everything Open Nest writes lives under `OPENNEST_HOME`; saving to a parent's Desktop
crosses that boundary deliberately. HANDOFF §5 already has the rule and the pattern:

> Export / publish / deploy / upload are **privileged application actions**. A
> privileged action is still sandboxed. It is granted **one more thing**, explicitly,
> per action, and never let out.

`process_sandbox.grant_devices` is the worked instance — it refuses anything that is
not a serial port, because the value comes from outside the application. A file export
takes the same shape: one destination, chosen by a person through a real save dialog,
validated, and granted for that write alone. **Do not add a general "write anywhere"
capability**, and do not let the model reach it — export is an application action a
person takes, not a tool in the four-tool set.

Three things worth deciding before building:

1. **What a "report" is.** A Research project already produces a chart PNG and
   `findings.md`. The cheapest honest export is those two composed into a PDF, and it
   needs no new generation — `matplotlib.backends.backend_pdf` and a Markdown render
   would do it with no new dependency beyond what is installed.
2. **Whether export is gated.** Section 25's permissions have no entry for it. It
   writes outside the project, so it probably wants one — but a child unable to save
   their own work without a PIN is its own failure. A likely answer is "no gate, but
   only through a save dialog a person drives", which is the same logic that made
   "Check for Updates" not need a new permission (§6D, decision D9).
3. **Secret scanning.** §29A scans before a push. An export is the same class of
   egress and should use `secret_scanner` the same way.

There is also a smaller, unrelated question sitting next to this one: **the child never
sees text stream in.** `AgentWorker.chunk` is emitted and nothing consumes it, so a
16-second turn is 16 seconds of nothing followed by a finished reply. Noticed while
tracing the worker signals in §20B. It is a one-connection change and it is the
difference between a product that feels alive and one that feels stuck.

---

## 8. CLOSED — Gary narrated changes he had not made

**Resolved in Phase 12.1.** Reproduced through the real interface, traced, fixed in
`agent/controller.py`, and re-measured by driving the same three turns again. Full
measurements in SPIKES.md §21; this is what a reader needs to know.

### What it actually was — and the original diagnosis was wrong

This section used to say the three Games turns "claimed work while calling no tool at
all". The next measurement it asked for was to instrument `Toolbox.dispatch` at the class
level during a real app walk. That was the right instrument, and it contradicted the
premise:

| turn | dispatch entered | tools | files changed |
|---|---|---|---|
| step 22 | **5 times** | `edit_file` ✗ `read_file` ✓ `edit_file` ✗ `edit_file` ✗ `read_file` ✓ | none |
| step 27 | **2 times** | `edit_file` ✗ `read_file` ✓ | none |
| step 29 | **2 times** | `edit_file` ✗ `read_file` ✓ | none |

The tools ran, on the worker thread, every turn. `Turn.tool_results` agreed with the
dispatch log exactly, so the original walk's instrumentation was sound too. What failed
was **every `edit_file`** — the model's `old_text` never matched `src/game.py` — followed
by Gary announcing a white spaceship, a red asteroid and collision detection that had
never been written.

So of the three hypotheses this section listed, both of the cheap ones were wrong. It was
not orchestration and it was not instrumentation. It was the honesty guard.

### Three holes in one guard, and the third only appeared after the first two were fixed

`_claimed_a_change_it_did_not_make` has existed since Phase 2 for exactly this failure. It
missed all three turns, for three different reasons:

1. **The phrase list had grown asymmetric.** It held `i increased` and not
   `i've increased`, and no progressive form at all — so *"I've increased asteroid speed
   to 3.0"* and *"I'm adding image loading"* were never challenged even once. Only four of
   thirteen verbs carried their present-perfect form. The set is now **generated** from
   `(past, participle, progressive)` triples. Future and modal forms are deliberately
   excluded: "I'll add a score" is a suggestion and `prompts/games.txt` asks for one.
2. **The correction was one shot with no fallback.** Step 22 *did* match, the pushback
   fired, the model said the same thing again, and `if not challenged` relayed the repeat
   verbatim. The round trip is kept — a model that takes it and makes the real edit must
   be reported as having made it — but when the claim comes back, the application now
   replaces the text with what it can prove.
3. **The check read `reply.text`, not `turn.text`.** Found only by rerunning the walk
   after fixing 1 and 2, which **still leaked the identical claim**: the model answered the
   pushback with *nothing*, `reply.text` was `""`, and the previous reply's sentence went
   to the child unexamined. Gary is answerable for the sentence on screen.

**Hole 3 is the lesson worth keeping.** It existed only because the first two were fixed,
and it would have shipped if the fix had been trusted instead of re-driven. A defect found
by clicking has to be re-checked by clicking.

### What was built — and what was not

Three changes inside `agent/controller.py`. No enforcement layer, no orchestration, no new
subsystem — this section's own instruction was not to build machinery for a fault nobody
can trigger, and that still holds now that it can be.

Both constraints this section set were checked rather than assumed. **Nothing is
Games-specific**: the change is in the shared controller and the phrase set names no
profile. **Research is untouched** — *"What data do you want graphed? Point me to the
file."* holds no claim and no denial, so no branch fires, pinned by
`test_research_asking_for_missing_data_is_left_alone`.

A fourth thing was added because the fix needed it: **a plain denial is exempt.** The
correction asks the model to "say plainly that you have not changed anything yet", so a
compliant answer must not be scored as a fresh lie — and it keeps an honest admission
carrying a claim verb ("I haven't changed anything — I made a mistake reading the file")
on the right side of the line.

Seven regression tests in `tests/test_agent.py`, including the verbatim reply the real
model produced. Three of them fail against the pre-fix controller; the other four are
guards that must pass both ways.

### The verification walk, and the one turn it did not clear

Same driver, same model, same three turns, **12/12**:

| turn | dispatch | files changed | Gary |
|---|---|---|---|
| step 22 | 5, all edits refused | none | *"I haven't changed anything yet. The change I tried did not go through…"* |
| step 27 | 9, four refused, **one `write_file` succeeded** | `src/spaceship_image.py` | *"The spaceship now moves with arrow keys…"* |
| step 29 | 4, all edits refused | none | *"I haven't changed anything yet…"* |

**Step 27 is a different fault and is left open on purpose.** The model wrote a real new
file and then described work it had not done — `src/game.py` was refused four times and is
untouched. Because a mutation genuinely occurred, `changed_files` is non-empty and the
guard correctly stands down. That is **claim-to-artifact attribution**, not claim
detection: knowing a sentence is about `game.py` while the change landed elsewhere.

It is tractable and deterministic, and SPIKES §21C-bis has the shape: `Turn.tool_results`
carries `(name, ToolResult)` and drops the call arguments, so the application cannot say
which *paths* were attempted. Carry the path through and the rule becomes "a claim is
false when a path the model tried and failed to mutate is still unchanged". That is a
data-shape change to `Turn` and wants its own measurement.

### The bigger problem underneath, which is not honesty

Across all three walks **18 of 18 `edit_file` calls were refused**, every one because
`old_text` did not match `src/game.py` — repeatedly right after the model had read the
file, and twice re-sending a byte-identical failing call. Open Nest is now honest about
that. It is not yet good at it, and a child asking for a spaceship game still does not get
one.

That is the **capability / action-selection miss** this section asks to be kept separate
from the truthfulness defect, and keeping them separate is what stops "Gary told the
truth" being read as "Gary did the job". It is the thing to work on next, and it is about
`edit_file` ergonomics against a 4B model — the tool wants a shape a small model can hit,
or the model needs the file's exact lines in front of it when it composes the call.

### The drivers

| | |
|---|---|
| `spikes/phase12/dispatch_walk.py` | the class-level `Toolbox.dispatch` probe, per-turn sha256 of the whole project, and the `Turn` the Workbench was handed — three independent sources printed side by side |
| `spikes/phase12/replay_step22.py` | the real replies through a scripted provider: no inference, control flow the only variable |
