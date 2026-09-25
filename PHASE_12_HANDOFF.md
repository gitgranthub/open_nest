# Phase 12 — the owner's test drive, and what clicking it found

Read [HANDOFF.md](HANDOFF.md) first. This file is what Phase 12 measured, what it fixed,
and what it deliberately left alone.

**Phase 12 is NOT complete, and an earlier version of this file said it was. That was
wrong and the correction matters more than the claim did.**

Four rounds of work are genuinely closed: the test drive itself (§1-§5), **12.1** the
truthfulness defect (§8), **12.2** the edit tool (§9), and **12.4** the playability
feedback loop (§12) — Open Nest now tests a game after every change and sends a crash, a
blank window or a frozen picture back for repair. What none of them delivered is the
thing the phase exists to prove:

> **A child asks for a game and does not get one.** Every edit now lands, every claim
> Gary makes is now true, and the window still shows an orange square on black — or, once
> the model has had a go, a spaceship on an empty background with an asteroid that is
> stationary and invisible. The owner has watched this happen on every walk and has never
> once seen a working game.

Phase 12's own definition of done is WORKORDER_01 §42, which is a child building
something real. Marking it complete because the defects behind it are fixed confuses *the
faults found* with *the outcome required*. **It stays open until a real conversation
through the real interface produces a game that runs and does what Gary says it does.**

What is genuinely settled, and should not be re-investigated:

- the runtime and threading defects (§2), with tests
- Gary never claims a mutation that did not happen (§8) — measured three times through
  the real UI
- `edit_file` lands 3 of 4 real edits instead of 0 of 5, with a bounded deterministic
  recovery that refuses ambiguity (§9)
- one project runs one copy of itself; the window pile-up is gone (§9)
- the approval mark is no longer awarded for the starter template launching (§10)
- a game that crashes, never draws, closes itself or shows a frozen picture is caught
  after every change — whether or not the model ran it — and sent back for repair,
  bounded, with **zero false failures** in the acceptance run (§12)

One thing §8 originally recorded turned out to be false, and it matters for anyone
reading the old version: the tools *were* running. The failure was never "no tool call".

---

## THE CONCLUSION — why Phase 12 is still open

> **Open Nest can now tell a game that is clearly broken from one that is not — after
> every change, whether or not the model ran it. It still cannot tell whether a game
> that is not broken does what the child asked, and a deterministic check was
> deliberately not made to try.**

That was one sentence shorter before Phase 12.4: *"Open Nest can detect that a game
crashed. It cannot yet determine whether an interactive game that successfully launches
actually behaves as requested."* 12.4 closed the half of it that deterministic evidence
can close (§12). Phase 12.3 measured the remaining gap properly and it is **not** what
§9 guessed — a prompt-and-context problem was the hypothesis, and twenty-four
conversations say otherwise.

**The established evidence. None of this needs re-measuring; all of it is in SPIKES §23 and §24.**

| | |
|---|---|
| **1 of 24** measured conversations produced the requested moving game | §23B, §23F, §23G |
| **4B vs 8B did not solve it** — 8B scored 0/6 and landed `edit_file` at 30% against the 4B's 63% | §23G |
| **Prompt tuning did not solve it** — three variants, no distinguishable gain | §23D, §23F |
| **Starter markers made results worse** — 5/6 crashed; a labelled section invites replacing the code it labels | §23D |
| **Tool execution alone is not the dominant remaining problem** — edits land and the game still does not work | §23C |
| **`RunResult.ok == True` means the process launched and stayed alive, not that the game works** | §23H |
| **The repair loop therefore cannot react to the dominant "runs but does not work" case** — a crash gets three attempts, a frozen picture gets none | §23H |
| **`does_it_play.py` shows deterministic behavioural inspection is feasible** — but graded **7 of 10 working games frozen** and could not be wired in as it was | §23A, §24A |
| **Built in 12.4:** a headless playtest after every change, feeding crash / no picture / closed itself / frozen to the repair loop. **0 false failures** in 14 real conversations; of the 2 games it caught, 1 was repaired and the other stopped at three attempts and said so | §24B–§24F |
| **All 10 crashes in the 12.3 sample were first-frame crashes nothing ran** — the model called `run_project` in only 3 of 15 turns in the 12.4 acceptance | §24C, §24F |

**Two things left open on purpose, and neither should be guessed at:**

- **The `edit_file` exact-match dedent hazard** (§23E). A replacement sent at column zero
  for an indented region is applied verbatim, compiles, and silently lifts code out of the
  loop. It never reaches the §22 recovery ladder, because the match is exact. **Do not
  "fix" it by re-indenting exact matches** — moving code out of an `if` is an ordinary
  legitimate edit and the tool cannot tell the two apart from the text.
- **Claim-to-artifact attribution** (§9, SPIKES §21C-bis), deferred by the owner. Do not
  let it grow into a semantic claim-analysis subsystem.

### 12.4 is closed. What it established, and what comes next

> **Playtest now detects crashes, no-draw, premature exit, and genuinely static output
> under controlled input. It does not determine whether the generated game semantically
> matches the child's request.**

**The measured result that motivates the next work: the 12.4 acceptance set still failed
to produce the requested behaviour reliably.** None of the six controlled game requests
produced the game that was asked for. The loop stopped broken games reaching the child as
"done"; it did not make the model build the right one. The falling square that jitters,
the title that is a comment, the ball that does not bounce — each passes, because none
of them is broken, and none of them is what was asked. That is why Phase 12 stays open.

**Next: the Fast Path — a classifier plus known recipes.** Route common requests
("make it fall", "add an enemy", "add a score") through implementations known to work,
rather than asking a 4B model to invent the whole thing each time. It is the next
architecture experiment, owner-directed, and **not started** in the session that built
12.4. The playtest stays as it is under it: a recipe's output still gets tested.

**Recorded as future hardening, deliberately not built:**

- **Claims of motion the test measured as absent.** In three of fourteen acceptance
  conversations Gary described a bouncing ball, a chasing enemy or a moving coin while
  the playtest had measured `moved_by_itself = False`. That comparison is deterministic,
  and it is claim-to-artifact attribution, which the owner deferred. It must not be
  grown out of 12.4 into semantic claim verification; the Fast Path is expected to make
  these cases rarer at the source.
- **Turns where no edit landed.** Two of the six controlled conversations ended as the
  untouched starter: one with every edit refused, one with the model looping inside its
  own tool call until the output cap. The raw JSON that second case put on screen is
  **fixed** (§12, "Two fallbacks corrected"); the loop itself is not.

**Phase 13 stays reserved for the frame-streamed / embedded game preview** (§6, feasibility
measured). It shares the frame-capture technique with `does_it_play.py` and is otherwise a
different piece of work — do not merge the two. **Phase 14** is export (§7). Neither has
started.

---

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

---

## 9. CLOSED — an edit tool a small model can actually hit

**Phase 12.2.** 12.1 made a failing edit honest; it did not make it rare. **18 of 18
`edit_file` calls were refused** across the 12.1 walks. Full measurements in SPIKES.md
§22.

### Measured before anything was built

15 refusals, from one real UI walk plus a wider headless sample:

| category | n | share | verdict |
|---|---|---|---|
| `absent` — the model editing code it imagined writing | 7 | 47% | correctly refused |
| `indent_shift` — right line, wrong column | 5 | 33% | **recoverable** |
| `literal_backslash_n` — a newline written as two characters | 3 | 20% | **recoverable** |
| `ambiguous`, `trailing_ws`, `crlf`, `broken_python` | 0 | — | — |

**It was never a byte-perfection problem.** In every recoverable case the model
reproduced the right lines and got the *encoding* wrong. Two beliefs going in were wrong:
"18 of 18" is that one conversation, not the tool — ordinary Games requests succeed **8 of
18** — and `"Make the player move faster."` failed **0 of 6**, every attempt sending
`    PLAYER_SPEED = 5` against a starter that has it at column zero.

### What was built, and the rules that keep it safe

`tools.repair_edit` runs only when the exact text is absent, and **every rung must find
the text exactly once or it does not fire**: `escaping` (repairing `old_text` and
`new_text` as a pair), `whitespace` (trailing space and CRLF), `indentation` (moving the
replacement by the measured delta rather than writing it as sent).

No edit distance, no similarity score, nothing picks the "closest" text. Matching is
line-aligned because a character span found in normalised space has to be mapped back
onto the original bytes, and getting that wrong edits the wrong region silently.
Ambiguity stays a refusal at every rung; a dedent deeper than the line allows aborts the
repair; `_reject_broken_python` still gates the result. **No fifth tool** — SPIKES §4 and
§8 priced that at 19 points of selection accuracy.

`ToolResult.reason` carries the refusal as one machine-readable word; `ToolResult.recovered`
carries how an edit landed, and is the only reason recovery usage can be reported at all.

### Two things to know before touching it

- **`repair_written_text` exists because of the nastiest version of the fault, and the
  match-side repair does not reach it.** `old_text` can match *perfectly* while
  `new_text` carries literal escapes — and then a whole block is written as **one
  comment**, deleting real code, compiling cleanly, and reported as success. A refusal
  would have been better. The discriminator is Python's own parser: an intended newline
  unescapes into valid code, a `\n` inside a string literal does not.
- **One project runs one copy of itself.** `Toolbox.last_run` holds one result and an
  interactive run never ends by itself, so every extra `run_project` used to orphan the
  previous process — unreachable by Stop, by closing the project, or by quitting. Five
  were live on the owner's screen at once, all reparented to init. `stop_running()` is
  called before starting another. §20I fixed the *last* window outliving the Workbench;
  this is the same family, one copy deeper.

### Verified through the real UI

Same driver, same three turns, same model: **3 of 4 edits succeed, all three via the
recovery path**, the one refusal correct (`absent`), **zero stray processes**, and the
finished `src/game.py` parses, draws, and still moves the player.

### And it still does not build a working game

Worth stating plainly, because "3 of 4 edits succeeded" invites the wrong conclusion. The
final walk's game contains two ordinary beginner faults:

```python
while running:
    asteroid_x = 500          # re-initialised every frame
    asteroid_x -= 5           # ...so it never actually moves
    pygame.draw.circle(...)   # drawn BEFORE the background fill
    ...
    screen.fill(BACKGROUND)   # ...which paints over it
```

The asteroid is stationary and invisible. Gary says it moves left; the window shows a
spaceship on an empty background. **Neither fault is something the edit tool can catch** —
each individual edit did exactly what it said. This is the capability miss, and it is now
the largest thing in the way.

### The drivers

| | |
|---|---|
| `spikes/phase12/edit_refusals.py` | the real UI walk: full tool arguments, the file at the moment of each call, per-turn diffs, recovery usage, and the finished game read back |
| `spikes/phase12/edit_sample.py` | the wider headless sample; dumps every refusal verbatim to `refusals.json` |
| `spikes/phase12/refusal_kinds.py` | the classifier, shared so both report the same categories |
| `spikes/phase12/raw_toolcall.py` | whether the stray backslash is the model's or ours — it is the model's |

**A measurement harness must persist what it measured, not just its conclusion.** The
first classifier mislabelled all ten headless refusals (it asked `"appears" in reason`,
which the *not-found* message also contains) and re-classifying cost a second ten-minute
model run purely because the raw material had been thrown away. Hence `refusals.json`.

---

## 10. The approval mark was awarded for the starter template

Found by the owner watching a 12.2 walk: *"the sunglasses show after the first model run
and stay… they saw, you built this… seems premature to me."* They were right, and it is
the **same over-claim Phase 12.1 removed from Gary's mouth, in the application's own
voice.**

The chain, confirmed in the code:

1. The model calls `run_project` itself during its first turn. The child never pressed Run.
2. The untouched starter launches — an orange square on black.
3. `RunResult.ok` returns True whenever `still_running` is, and for an interactive project
   that means only *"did not crash within four seconds"*.
4. `_mark_first_success` fires → the sunglasses and **"You built that."**
5. It is once-per-project-lifetime by design, so it never clears.

The copy had already been chosen carefully to avoid claiming machine state — `FIRST_SUCCESS`
is "You built that." precisely because "It works." would assert something one run does not
establish. That reasoning is sound and it is why this looked defensible. It is not: for a
starter nobody has edited, the part that is false is **authorship**. The child built
nothing; Open Nest shipped it.

`_mark_first_success` now also requires `_child_has_changed_anything()`, and `can_undo` is
an exact test rather than a proxy — `VersionHistory.start` commits `LABEL_CREATED` at
creation and `save` only commits when something really changed, so a second checkpoint
existing *is* "this project has diverged from the kit it began as". Two tests, and they
needed a Workbench with real versioning: the existing brand-placement fixture has
`versions=None`, so it exercises the fallback and would have passed either way.

**The general rule, which is the reusable part:** a brand state that asserts something
about the child's work has to be gated on evidence of the child's work, not on a process
exiting non-negative. Section 39 lists what the sunglasses are not for; "a template we
shipped started up" belongs on that list.

---

## 11. Runs must leave the machine as they found it

Also from watching: pygame windows appearing unbidden and never closing, and the sandbox
quietly filling with artefacts.

Two separate causes, both now closed:

- **The orphaned processes** were a product defect — `Toolbox.last_run` holds one result
  and every extra `run_project` abandoned the previous live process. §9 has it.
- **The residue** was the drivers. Each cleaned up its own project on the happy path and
  nothing cleaned up anything after a failure or a Ctrl-C, so a day's measuring left 6 MB
  of stale screenshots, fixtures and dumps — and a run that died left its project on disk
  where the next run would find it.

`spikes/phase12/scratch.py` is the shared teardown: a run registers what it will create
*before* creating it, and `atexit` plus SIGINT/SIGTERM handlers clear it on success,
failure and interrupt alike.

**Its safety property matters more than its cleaning, and this is the part to keep.** The
sandbox holds **6.4 GB of model weights, a 430 MB toolchain and a 42 MB pip cache** — and
a teardown that can delete those by accident is far worse than the residue it exists to
remove. So removal is allowed only inside an explicit allowlist (`phase12`, `ui-smoke`,
`cache/phase12`, `demo`), every path is resolved before it is checked so `..` and symlinks
cannot escape, and anything else **raises** rather than being skipped quietly. Verified
against 12 paths that must be refused — including `models/`, the containment root itself,
a traversal through `phase12/../../`, and `/etc/passwd` — and 5 that must be allowed.

`paths.opennest_home()` returns None when Open Nest runs against standard macOS locations
rather than a sandbox, and `home()` **raises** in that case. A teardown that cannot say
where its root is has no business deleting anything.

**Two decisions the owner settled, so they are not reopened:**

- **The demo launcher lives on its own branch** and never merges. Main carries the real
  app launcher only.
- **Its teardown clears everything except the models and the toolchain.** Demo projects,
  conversations, memory, checkpoints, screenshots and logs go; the 6.4 GB of weights, the
  430 MB Arduino toolchain and the pip cache stay. That is exactly the `EPHEMERAL` /
  `PROTECTED` split `scratch.py` already enforces.

**This is the prototype for the demo launcher's teardown**, which has the same job at
higher stakes: real model calls, something really built, and the machine left exactly as
it was found.

**The pytest suite was measured and is already hermetic** — 94 files in the sandbox
before a full run and the same 94 after, nothing added, nothing removed. The leak was
never the tests.

---

## 12. CLOSED — Phase 12.4, the playability feedback loop

**Open Nest now tests a game after every change and reacts when it is clearly broken.**
Before this, `RunResult.ok` was True for any interactive game that survived four seconds,
so a frozen picture got no repair at all, and a crash got one only if the model happened
to run the game. Full measurements in SPIKES.md §24; this is what a reader needs.

> **Playtest now detects crashes, no-draw, premature exit, and genuinely static output
> under controlled input. It does not determine whether the generated game semantically
> matches the child's request.** And the 12.4 acceptance set still failed to produce the
> requested behaviour reliably — the result the Fast Path work starts from.

### The spike could not be wired in, and why that mattered most

`does_it_play.py` proved the technique and was not a grader anyone could act on. Measured
against ten small **working** games, it called **seven frozen** — it replaces
`pygame.event.get` with a function returning nothing, which swallows every KEYDOWN and
the game's own `set_timer` events, and it only ever fakes arrow keys. It also discarded
any traceback after the first frame. As a repair trigger it would have had Gary
"fixing" seven working games. The 12.3 corpus never showed this because all 24 of its
games came from the arrow-key starter.

### What was built

| | |
|---|---|
| `execution/playtest_harness.py` | runs inside the child's process under the same Seatbelt profile, no network, no window. **Records only**: window, per-frame hash, the input being given, how it ended. Posts input into the game's own queue; `runpy` keeps real line numbers; a watchdog ends it by 10 s |
| `execution/playtest.py` | runs it through `python_runner.run_project` and classifies. Pure, tested without a game |
| `Toolbox.playtest()` | an application method, **not a tool** — in no schema, refused by `dispatch`. Never touches `last_run` |
| `AgentController._playtest_wants_repair` | whenever the model stops and the turn changed a file since the last test |
| `profiles.json` | `"playtest": "pygame"` on Games, and nowhere else |

**Failures, the only things that trigger repair**: `crashed` (a traceback, any frame),
`no_picture` (a window, nothing drawn in 4 s), `closed_itself` (ended within two frames),
`frozen` (every frame identical, left alone and through every scripted input). Anything
else is a pass or no verdict. **Rejected on measurement**, because telling them apart
needs to know what the child meant: "only moves when a key is held" (the starter is
exactly that) and "the change made no visible difference" (it would fire on every window
title, quit key and sound).

**The bounds**: one repair budget per turn — `MAX_REPAIR_ATTEMPTS = 3`, now shared with
the crash repair — and the turn's twelve-call budget. Unchanged code is never tested
twice, but an answer that changes nothing is pulled up and spends an attempt, because
that was measured: handed the exact `NameError`, the model said *"I added the import for
random at the top of the file"* and called no tool. Whichever bound ends it, the child is
told what the test saw, in the application's words.

### Acceptance — 14 real conversations, Qwen3 4B

| | |
|---|---|
| launched (old `RunResult.ok`) | 13 / 14 |
| model ran the game itself | 3 of 15 turns |
| behavioural check failed | 4 tests, 2 conversations, all real first-frame crashes |
| repair triggered · attempts | 2 conversations · 5 |
| repaired to passing | 1 (the falling square) — the other gave up at three and said so |
| crashes that reached the child as "done" | **0** |
| **false behavioural failures** | **0** — 4 / 4 probes passed, and passed correctly |
| cost | ~2 s per test on a changed game; nothing on a turn that changed nothing |

### Three things to know before touching it

- **"Passed" is "not clearly broken".** The falling square passes because its position is
  reset to a random `x` every frame — it jitters. That is the honest limit, and the reason
  Phase 12 stays open.
- **It cannot fire under `scripts/offline.sh`.** Seatbelt does not nest; every test there
  is UNAVAILABLE. The acceptance driver runs unwrapped with `HF_HUB_OFFLINE=1`, as the
  product does.
- **The suite is slower: 55 s → ~110 s.** About thirteen existing tests change a Games
  project and now pay a real ~2 s playtest of the starter, plus ~15 s of new playtest
  tests. Kept on purpose: the profile says Games are tested, and a test-only switch would
  make every one of those tests describe a configuration the product never runs.

### Two fallbacks corrected, both exposed by 12.4

Owner-directed cleanup, kept narrow on purpose: neither reopens the 12.1 truthfulness
system nor redesigns the tool-call parser.

- **Raw tool-call JSON never reaches the child.** The acceptance run had the model loop
  inside an `edit_file` argument until the output cap; the block never closed, the
  parser only removed *closed* blocks, and the whole raw `<tool_call>{...` became Gary's
  reply. `strip_tool_calls` now drops an unclosed block from its tag to the end — the
  same treatment an unclosed `<think>` already had — and `Reply.dropped_tool_call` says a
  call was begun and could not be read. When that is the last word and nothing changed,
  the child gets the application's existing honest "I haven't changed anything yet"
  instead of silence or the half-sentence before the call. Not retried: it was a
  repetition loop, and at temperature 0 the same prompt loops the same way. The parser
  itself is unchanged.
- **"It works." is no longer inferred from a launch.** Two fallbacks said it from
  `RunResult.ok`, which for a game means only that it survived four seconds:
  `_describe_what_happened` now says *"I changed src/game.py and started it."*, and
  `_repair_actually_worked` says *"That took a few tries, but it starts now."* A run that
  **finished** — a Research analysis that exited cleanly — keeps "It works.", because it
  is not a launch. Neither sentence mentions the playtest's pass: "the picture changes"
  would read to a child as "my asteroid moves", which nothing verified.

**A trap left in place, noted rather than changed:** `AgentWorker.chunk` streams the
model's *raw* output, every tool call included. Nothing renders it today — the transcript
updates once, at the end of the turn (§5). Connecting it to the transcript without the
same stripping would put tool protocol on screen for every call, not just a broken one.

### What was deliberately left

- **Claims of motion the test measured as absent** — future hardening, see the conclusion
  section. Not built, and not to be grown out of the playtest.
- **The model looping inside its own tool call.** Its output is now kept off the screen;
  the loop itself is a capability miss, the kind the Fast Path is meant to route around.

### The drivers

| | |
|---|---|
| `spikes/phase12/playability_loop.py` | the acceptance run: controlled / extended / probe conversations, `--only kind:index` to re-drive one, everything persisted including the full message history |
| `spikes/phase12/does_it_play.py` | kept as the 12.3 record. **Do not use it to grade anything new** |
