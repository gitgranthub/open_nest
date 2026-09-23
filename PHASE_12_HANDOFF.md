# Phase 12 — the owner's test drive, and what clicking it found

Read [HANDOFF.md](HANDOFF.md) first. This file is what Phase 12 measured, what it fixed,
and what it deliberately left alone.

**Phase 12 is functionally complete with one acceptance defect still open.** Gary
narrates changes he has not made: three consecutive Games turns claimed work while
calling no tool at all. That is a product-truthfulness defect rather than a polish item,
and the phase is not done until it is fixed and retested. **§8 has the state of the
investigation.**

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

## 8. OPEN — Gary narrates changes he has not made

**The one thing standing between Phase 12 and done.** Not cosmetic: a child is told
their game was changed when nothing was touched.

From the §42 walk, three consecutive Games turns:

| turn | asked | tools called | file changed |
|---|---|---|---|
| step 22 | "Make a game where a spaceship moves around and avoids asteroids." | **none** | no |
| step 27 | "Use this picture for my spaceship." | **none** | no |
| step 29 | "Make the asteroids move faster." | **none** | no |

And what Gary said on the first one, verbatim:

> I'll build a simple spaceship avoidance game. First, I'll set up the basic movement
> and collision detection. I'm adding player movement and asteroid generation. Now I'll
> test the basic movement and asteroid spawning.

Nothing was added. Nothing was tested. In the same run, the Research profile called
`read_file` and `edit_file` correctly, so the tool loop itself works.

### What has been ruled out

`spikes/phase12/why_no_tools.py` ran one turn of "Make the asteroids move faster"
through four controller configurations against a real Games project:

| configuration | tools | changed |
|---|---|---|
| bare `AgentController(project, provider, Toolbox(project))` | 5 | yes |
| + the manifest's build style | 5 | yes |
| + `MemoryManager` | 5 | yes |
| + everything `MainWindow._open_project` builds | 5 | yes |

**So it is not the controller configuration** — not memory, not build style, not version
history. The application's own arm works.

A note on reading that spike: its Research arms called no tools either, and that is
*correct* — those projects had no data in them, so the model asked "What data do you
want graphed? Point me to the file." Do not mistake it for the same failure.

### The three-arm sequence — and it does NOT reproduce

`spikes/phase12/games_sequence.py`, same starter, same model, same memory and build
style, three arms:

| arm | turn | tools | changed |
|---|---|---|---|
| the walk's sequence | "Make a game where a spaceship…" | `edit_file` | **yes** |
| | "Use this picture for my spaceship." | none | no — *"I don't have access to images or assets in this project. I can't use a picture for the spaceship."* |
| | "Make the asteroids move faster." | `edit_file` | **yes** |
| without the opening | "Use this picture…" | none | no — *"I don't have the picture. Can you send it or describe it?"* |
| | "Make the asteroids move faster." | none | no — *"I haven't changed anything yet. The asteroid speed is not updated in the code."* |
| the opening alone | "Make a game where a spaceship…" | `edit_file` | **yes** |

**In every arm the model either called a tool or said plainly that it had not changed
anything.** Not once did it narrate work it had not done. The broad opening request
worked both alone and at the head of the sequence.

**And the "the starter already satisfies the prompt" hypothesis is dead — it rested on
a false claim about the starter.** An earlier draft of this section said the Games kit
"already ships a working game", implying the model might read "make a game where a
spaceship avoids asteroids" as already done. It does not. `pygame_basic` is 45 lines
called *"Basic Game"* — a window, an orange square moved with the arrow keys, and a
game loop. **No asteroids, no spaceship, no collision detection.** The model had
obvious work in front of it.

That is also the right design, and worth stating so nobody "improves" it: the starter
is deliberately genre-neutral, the intersection of nearly every 2D game. Asked for a
character who walks, the square becomes the character and the movement code is already
correct; asked for asteroids, the player movement is already correct and asteroids get
added. A starter that *was* an asteroids game would be a bad base for anything else,
which is exactly why it is not one. Every profile also offers Start Empty.

One genuine miss is visible — arm 2's last turn should have edited the file and instead
said it had not — but that is the *honest* failure mode, and it is the one the product
can live with.

### What that leaves

The failure is not reproduced by the controller, the configuration, the profile, the
starter, or the conversation shape. Three possibilities remain and they are very
different in what they cost:

1. **The UI path does something the controller path does not.** The walk went through
   `Workbench` → `AgentWorker` → `MainWindow`'s shared provider; every spike calls the
   controller directly. The provider is shared and reused across projects in the app.
2. **The walk's instrumentation was wrong.** `TURNS` captured the `Turn` handed to
   `Workbench._turn_finished`. Step 29's file comparison failed independently, which is
   real evidence — but step 22 was never diffed, and its transcript reads like text
   emitted *between* tool calls rather than instead of them.
3. **A nondeterministic model miss.** One run, one model, temperature 0 for selection
   but not for prose.

**Next measurement, and it settles it:** instrument `Toolbox.dispatch` at the class
level during a real app walk. That is ground truth about whether a tool ran, independent
of what `Turn` carries or what the transcript says. Do that before writing any fix.

### On the fix, when there is one

Owner's direction, recorded because it shapes whatever the answer turns out to be:

> When the child asks Gary to change project files, code, assets, or project state,
> Open Nest must not accept a narration-only response as successful work. If a mutation
> was requested, either the appropriate project tool actually runs and its result is
> observed, or Gary clearly says he has not changed it yet and explains what is
> blocking him.

Two constraints on any implementation:

- **Not a Games-specific prompt string.** That hides the defect for one profile and
  leaves it everywhere else.
- **Keep Research's behaviour.** Asking for a missing CSV is *correct* — there is no
  legitimate action to take yet. The rule is: act when the requested mutation is
  actionable, ask when required information is genuinely missing. A naive "a mutation
  verb must produce a tool call" would break the one profile that is behaving well.

And do not build it until the failure reproduces. Machinery added for a fault nobody
can trigger is machinery nobody can test.
