# Phase 10 handoff — design and polish

**Stages 10A and 10B are complete. 10C and 10D are not started.**

Read `HANDOFF.md` first for the project as a whole; this file covers Phase 10 only and
assumes you have read `brand_design_guide.md` (2,166 lines, 63 sections) and
`DESIGN_DOC.md` §§2–23.

```
786 tests pass (724 at Phase 9 — 62 added).  ruff clean.
18/18 checks pass under the real cocoa platform.
Tool selection unchanged by Gary's prompt: 15/16 before, 15/16 after (SPIKES.md §18A).
On branch phase-10-design, two commits, local only. See "Git state" at the bottom.
```

---

## 1. The four decisions, as settled

Settled with the developer at the start of Phase 10. Do not reopen these without asking.

**Precedence.** Where `brand_design_guide.md` and `DESIGN_DOC.md` differ, the brand guide
governs — it is newer and more specific. `DESIGN_DOC.md` §23 now records this and the one
substantive conflict, and `PLAN.md`'s Phase 10 section carries the restated scope.

**The eagle ships.** A stationary twelve-frame wing cycle, only for real waiting states,
always paired with status text, never moved around the screen. It is not Gary and not a
mascot. `DESIGN_DOC.md` §12's and §16's substance survives — nothing swoops or bounces.
The **app icon** still follows `DESIGN_DOC.md` §18 rather than brand guide §31, because
the legibility argument against a detailed nest at 16 px is the stronger one.

**Gary is adopted** as the visible conversational helper, for 10B. He is a voice, not a
character: no illustrated face, and no visual connection to the eagle, nest or sunglasses.
System-level messages — installation, security, account, recovery, status — stay
attributed to Open Nest rather than pretending Gary said them.

**No menu bar.** There is no `QMenuBar` anywhere in `opennest/` and Phase 10 is not the
place to invent one. "App, setup and menus" means any menus that already exist should use
the same design system. If native File/Edit/Window menus are ever wanted for a concrete
macOS interaction, scope that deliberately as its own piece of work.

---

## 2. What 10A changed

### New files

| File | What it is |
|---|---|
| `opennest/ui/brand.py` | The five brand marks as components. Approved sizes, light/dark, accessible names. **Nothing else in the app loads a brand PNG.** |
| `tests/test_brand.py` | 17 tests. Asset presence, size snapping, light/dark contrast, eagle registration, playback restraint. |
| `tests/test_settings_layout.py` | 15 tests. The five §17F defects, pinned. |
| `tests/test_technical_details.py` | 15 tests. §30's headline/detail split. |

Also in `tests/test_wizard.py`: a `fixed_pin_salt` fixture and two tests, fixing a flaky
assertion inherited from Phase 8 — see §9.

### Changed

- `opennest/ui/theme.py` — added `role="deviceCode"`.
- `opennest/ui/github_connect.py` — defects 1–3.
- `opennest/ui/settings.py` — defects 4–5; GitHub Backup moved to the top of Parent
  Settings; `_key_row` split onto two lines; three path labels wrap.
- `opennest/ui/common.py` — `mono_label(..., wrap=True)`, opt-in.
- `opennest/ui/workbench.py` — §30's technical-details layer; all panel writes routed
  through `_panel_text`.
- `PLAN.md`, `DESIGN_DOC.md` — scope and precedence, as above.

### The five defects from SPIKES.md §17F

All fixed, each with a regression test, all re-verified under cocoa.

| # | Was | Now |
|---|---|---|
| 1 | `"Open GitHub agai"` — four buttons in a 460 px dialog | The spent `Connect` button hides once the flow starts. No visible button is narrower than its size hint. |
| 2 | The device code rendered twice | The dialog owns its step wording. `auth.DeviceCode.instructions` is **unchanged** — it is protocol-layer code with no other consumer, and a test pins it. |
| 3 | Code at `mono`'s 11 px muted grey | `role="deviceCode"`: 28 px against 13 px body text, full text colour, bordered. |
| 4 | GitHub Backup 726 px down a 443 px viewport | 74 px down a 441 px viewport. Cloud AI stays above the fold at 376 px. |
| 5 | 13 px horizontal overflow on Parent Settings | Page minimum 375 px against a 510 px viewport. **All six pages** are now checked. |

---

## 3. Three defects in the prepared asset delivery

These are worth your attention because two of them contradict what
`assets/open_nest_asset_delivery/ASSET_GUIDE.md` claims.

**`00_source/` is not the untouched original artwork.** The guide says "The original
uploaded files are preserved unchanged in `00_source/`" and "Do not edit files in
`00_source/`". Measured: only `ON_b.png` is byte-identical. `OPENNEST_b`,
`eagle_cycle_bw` and `glasses` are **2048×682** there against the originals' **2172×724**
— downscaled about 5.7% — and `nest_bw` is the same dimensions but differs in **45.25%**
of its pixels (max channel delta 101).

Nothing is lost: the true originals are still the top-level `assets/*.png`. But the
guide's closing instruction to "derive future sizes from the prepared master or the
original source" would regenerate from degraded art if followed against `00_source/`.
**Treat `assets/*.png` as the art source of truth.**

**The eagle frames are normalised in canvas size but not registered.** The guide says the
frames are "normalized to a common transparent canvas so the eagle stays registered
during animation." They are not. Measured on the 342 px masters: the feet baseline spans
**51 px** and the body's right edge **53 px** across the twelve frames, with a ~43 px
discontinuity between frame 6 and frame 7. Played in order the bird hops about 13% of the
canvas height at the row boundary and drops back at the loop — the positional motion
brand guide §37 forbids.

The cause is the supplied sheet, not the preparation: row 0's feet average y=344.7 and row
1's y=301.3, and the prepared frames reproduce that faithfully. It is a contact sheet of
poses, never registered as an animation strip.

Fixed in `brand.py` by `_EAGLE_REGISTRATION`, a whole-pixel translation per frame onto a
common body anchor. Feet spread 51 px → 1 px, body spread 53 px → 1 px, every opaque pixel
preserved, nothing touching the canvas edge. `tests/test_brand.py` re-derives the
alignment from the rendered images rather than trusting the table, and a negative control
asserts the raw frames really do drift — so if a corrected frame set is ever delivered,
the test tells you and the table can be retired.

**The compact mark has no dark-mode variant, and cannot be given one here.** It is a
pre-composited black `ON` over a white-ish nest. A single mean-contrast figure scores it
73 on charcoal and looks acceptable, because the white nest pixels dominate the average —
that was my own measurement error, caught by looking at the render. Band by band it is
not acceptable: the top third (the `ON`) scores **28.1** with a mean ink luminance of
**0.3** — pure black on charcoal — while the nest bands score 85.6 and 88.0.

It cannot be fixed the way the wordmark was. Inverting the whole composite would blacken
the nest, and the two elements are already flattened into one PNG. The proper fix is a
dark composite in the delivery, next to `open_nest_compact_*`, because that is where the
approved ON-to-nest proportions live — reconstructing them in code would be guessing at
brand geometry.

**This blocks the Workbench header in 10C** (brand guide §57 asks for the compact mark
there). Nothing consumes the component yet, so nothing is broken today.
`test_the_compact_mark_has_no_dark_variant_yet` is the test to delete when a dark variant
arrives.

### A note on `ON_W`, in case it comes back

Two files, `assets/ON_W.png` and `assets/ON_W.jpg`, were present before the prepared
delivery arrived and were **removed when it landed**. Recording what they were, so nobody
re-measures it: the white-on-dark ON mark, 950×880, RGB, **no alpha**, on an opaque
near-black background, and on a different pixel grid from `ON_b.png` (1774×887) — so
separately drawn art rather than an inversion of it.

`ON_W.png` **was not a PNG**: its magic bytes were `8BPS`, a Photoshop document with a
`.png` extension, which `QImage` refuses to load. The `.jpg` was the same art lossily
compressed, which is the wrong format for hard pixel edges.

Nothing is lost by their removal — the delivery's `on_wordmark_*` files are real PNGs with
alpha and are what `brand.py` loads. The top-level `assets/` is now exactly brand guide
§29's five canonical files, which is tidier than it was. If a white ON variant is supplied
again, it needs to be a real PNG with an alpha channel.

### One documentation inconsistency, not a defect

`asset_manifest.json` says `"pixel_rendering": "nearest-neighbor"` and the guide says to
prefer `Qt.FastTransformation`. The prepared sizes are in fact **smooth-resampled** — only
57–73% of alpha values are fully 0 or 255, the rest intermediate.

That is the *right* choice and should not be "corrected". The supplied artwork is
pixel-art *styled* raster at ~2000 px, not a small sprite on an integer grid: round-tripping
it through nearest-neighbour downscale-and-restore shows error falling monotonically with
no minimum at any low logical size, so there is no native pixel grid to snap to.
Nearest-neighbour downscaling to a UI size drops edge steps unevenly and reads as a
rendering fault. Resampling once, offline, at fixed sizes is exactly correct.

What it changes is the runtime rule: **draw prepared sizes 1:1 and never rescale.**
`FastTransformation` only matters if something scales, and `brand.py` does not — callers
ask for a size and get the nearest prepared one. Applying `FastTransformation` *while*
scaling would be the worst combination available.

---

## 4. Two more instances of defect 5, on pages §17F never visited

The smoke test only ever opened Parent Settings, because that is where GitHub backup
lives. Parametrising the overflow test across all six settings pages found the same fault
twice more, and worse:

- **Local AI** needed **1,021 px** in a 520 px viewport — a 501 px overflow, against
  Parent Settings' 13 px.
- **General** also overflowed.

Both from `mono_label` carrying an absolute path with no wrapping. `mono_label` now takes
`wrap=True`, opt-in so single-line status rows keep their behaviour.

**Local AI is still the tightest page: 512 px minimum against a 520 px viewport — 8 px of
margin.** Any new content on that page, or a longer model name, will put the scrollbar
back. Worth widening deliberately in 10C rather than discovering it again.

---

## 5. What 10B did

Gary is adopted, and the copy pass is done. `ASSISTANT_NAME` and `SYSTEM_NAME` live in
`opennest/__init__.py` next to `APP_NAME`, so 10C and 10D have one place to read the
names. The tone rules are brand guide §§1–24; §21's hierarchy was the tie-breaker.

### The copy pass was smaller than it reads, and that was measured first

The guide's banned vocabulary — §2's alarm register, §17's pitch-deck words, §18's
openers, §19's infantilisation — was swept across every string literal in the package
before anything was edited. **Zero hits in copy.** Every match was an identifier or a
comment. Button labels already satisfied §12; the wizard already read in §11's parent
register. Phases 2–9 were written against `DESIGN_DOC` §20, which is the same position in
fewer words.

So 10B is surgical by decision, not by omission: Gary at the seams, plus the specific
gaps that could be pointed at. A line-by-line rewrite of ~800 literals would have been
churn dressed as a design pass. **`tests/test_voice.py` now keeps that honest** — it
walks the AST of all 60 modules, pulls 826 user-visible strings, and fails on the banned
register. A new screen inherits the rule without anybody remembering to add it. Verified
with a negative control: an injected `"Awesome! Nothing here yet, kiddo."` is caught and
attributed to §18 and §19.

### The split, decided per message

`_say` takes a speaker, and who it is was decided per call site rather than by renaming:

| Site | Was | Is | Why |
|---|---|---|---|
| A turn's reply, the panel title | Assistant | **Gary** | — |
| Asset import | Open Nest | **Gary** | §22's "Asset Import" is a worked Gary example |
| Undo, both branches | Open Nest | **Gary** | §22's "Undo" likewise |
| A generated picture | Open Nest | **Gary** | §22's shape; the honesty sentence is byte-identical |
| **A failed turn** | Assistant | **Open Nest** | — |

That last row is the substantive one and the easiest to regress. What reaches
`_turn_failed` is a `ProviderError` from `AgentWorker`: the model would not load, the
service refused the key, the budget ran out. Nobody said anything, so nobody is quoted —
putting Gary's name on it would have him announce a fault in the machinery he speaks
through. Pinned by `test_a_failed_turn_is_open_nest_not_gary`.

Also renamed, outside the UI: `checkpoint.LABEL_BEFORE_CHANGE` / `LABEL_AFTER_CHANGE`
(read in Project History and after an Undo; they describe rather than identify, so older
commits need no migration), `assets.import_message`, and the Blank starter template's
docstring, which a child reads.

### Gary's conversational voice, and what it cost

`prompts/base.txt` is where it actually lives. The identity line names Gary, and
`HOW YOU TALK` gained what §§5/16/18/19 ask for and it lacked: specific acknowledgment
instead of praise, no enthusiasm openers, understated success, the banned diminutives,
and a dry aside **permitted and never required** — instructing a 4B model to be funny is
how you get performed humour, which §1 and §21 both rule out.

Two further rules were added by developer direction after the first measurement:

- **The praise fix is a principle, not a word swap.** Replacing `Great!` with `Good.`
  satisfies §18's literal list and misses the point. The rule asks for the two things
  that carry information — name the specific part, or mark that it happened (§20's
  *"There it is."*).
- **A state-claim rule.** Gary may not say the project works, runs, compiles, is
  playable, is finished or is fixed unless a tool reported it this turn or the child
  just said so; otherwise he calls a tool and finds out. This generalises
  `assets.invented_description` (pictures) and `_claimed_a_change_it_did_not_make`
  (edits) to **any** unevidenced fact about the project. It cannot be deterministic —
  "is it playable?" has no mechanical answer — so it is prompt-carried, and
  `test_gary_may_not_claim_a_state_he_did_not_observe` pins that it stays in the prompt.

**Measured, not asserted (SPIKES.md §18), and the measurement paid for itself twice.**

Tool selection: **15/16 before, 15/16 after**. But the *first* draft of the two rules
scored **14/16** — eleven lines of new prose about not claiming things crowded out the
instruction to act, and the model answered by narrating an edit it never made. An honesty
rule made honesty worse. Tightening the blocks ~40% and changing "find out" to **"call a
tool and find out"** recovered the point. That phrase is asserted in the test for exactly
this reason.

And the voice arrived, verified against the real model:

| Child says | Before 10B | Now |
|---|---|---|
| "It works! The frog jumps over the cars now." | "**Great!** The frog jumps over cars." | "**There it is.** The frog clears the cars now." |
| "What do you think of my game now?" | invents the game — *"A green frog that moves left/right…"* | "**I haven't run it yet. Let me try it.**" |
| the cat-and-fish praise bait | "Let me check what's in the project." | "**That could work. I like the flying cat.**" |

Row 1 was a live §18 defect that reading the codebase could not find — `Great!` is not in
the codebase; the model supplies it. **Row 2 is the more serious one**: asked an open
question with no evidence attached, the Phase 9 prompt invented a description of a game
it had never read, down to a green frog and a red car. Present before 10B, not introduced
by it, and now answered honestly.

### The §10 claim this file used to make was wrong, and pulling it found a defect

This section previously listed "the Cloud AI warning's Cancel / Ask Parent buttons (§10)"
as copy that already existed and was already right. **It did not exist.**
`consent.confirm_cloud_use` had `Use {model}` / `Cancel`; "Ask Parent" is only a
permission *state* label in `permissions.py`.

**The buttons are correct as they stand and were deliberately left alone.** The brand
guide's §10 example is generic; `WORKORDER_01` §24 specifies this exact dialog and its
buttons are `[ Cancel ]` and `[ Use Claude ]`, which is what ships. The work order is the
requirement here, and the guide's precedence (§1) is over *design* language, not over a
functional specification.

What did change is the warning *text*, which now leads with §10's consequence sentence
while keeping §24's "may be sent to {company}" intact. That sentence is load-bearing: an
earlier draft replaced it with "not on this Mac" and tripped
`test_the_warning_does_not_pretend_it_stays_on_the_mac`, which is the guard §24 asked for.

**Do not read the above as "the gap was only a documentation error."** By developer
direction: checking the claim surfaced a real functional shortfall, and it is now
recorded as a **defect in `HANDOFF.md` §6B with decision D12**, not left to evaporate
with the sentence that mis-described it.

In short — the master switch is genuinely parent-controlled and genuinely enforced, and
a saved cloud model is never silently restored (all three verified, details in §6B). But
the *per-use* control §24 offers on top of that is weaker than its label: the warning is
answered by the **child**, never asking the parent PIN the way `consent.approve` does,
and it fires **once per model switch** rather than per cloud request — which
`cloud_needs_confirmation`'s own docstring already claims it does. Neither is 10B work.
Both need D12 answered first, because a PIN on every turn makes cloud unusable.

### Still true, and still worth knowing

- **`prompts/base.txt` is where brevity is asked for**, not the token cap — HANDOFF §6B
  is explicit that shrinking `output_headroom_tokens` to control verbosity just truncates
  mid-sentence. `test_the_base_prompt_is_gary_and_still_asks_for_what_it_asked_for` pins
  brevity, the honesty rule, the tool boundary and §22's key rule against a future edit
  reaching for more personality and dropping one.
- **Do not put personality into the honesty machinery.** `assets.invented_description`
  and `_claimed_a_change_it_did_not_make` fire on deterministic checks and their wording
  is load-bearing; HANDOFF §6A explains why the narrowness matters. Gary says the
  image-saved sentence now, and the sentence itself is unchanged.
- **§47 is pinned.** Gary has no illustrated face and never names the eagle, nest or
  sunglasses. `test_gary_never_names_the_brand_artwork` guards it before 10C puts the
  artwork on screen.
- `_model_row` still refuses to say "premium" or "powerful" (`DESIGN_DOC` §13).

### Not done in 10B

- **The per-profile prompts were not re-voiced.** `games.txt`, `research.txt`,
  `arduino.txt`, `raspberry_pi.txt`, `image_creation.txt` and `blank.txt` carry project
  instructions rather than voice, and they read in register already. `base.txt` is where
  the voice is set and it is the file every profile shares.
- **No cloud model was sampled.** Sonnet and Luna get the same `base.txt`, and neither
  can be pinned to temperature 0 (SPIKES §11), so their voice is unmeasured.
- **The wizard copy was read and left.** It is a parent's first impression and it already
  reads in §11's register; nothing in it tripped the sweep. 10D's consistency pass is the
  natural place to look again with fresh eyes.
- **`rollover.render_transcript` still labels turns `Assistant:`, deliberately.** It is
  model-facing only — the transcript handed to the model to write a handoff note, with
  `Child:` as its counterpart — so it is outside 10B's "every user-visible string".
  Renaming it to `Gary:` is defensible on consistency grounds and was not done: it would
  change the input to the memory path, and HANDOFF §6 records that memory *quality* has
  never been checked against the real model. Changing an unmeasured path for tidiness is
  how you acquire a regression nobody can see. `assistant` is the literal role name in
  every chat template, so the model is not confused by it.

## 6. What 10C should do

Wire the components that 10A built. They exist and are tested; no screen uses them yet.

- **Flight Deck** (§56) — the strongest everyday expression of the brand. Wordmark plus
  nest, `FLIGHT DECK`, greeting, "What do you want to make?".
- **Workbench** (§57) — compact mark in the header, small. **Blocked on the dark compact
  variant.** Use the nest-only or wordmark mark in dark mode until it arrives, or resolve
  the variant first.
- **Setup wizard** (§58) — full identity at the opening, eagle during model install,
  sunglasses at completion. This is the sequence that teaches the visual language.
- **Eagle processing states** (§36) — model loading, AI generation, error inspection,
  project preparation, build, install, dependency checks, restore, asset processing.
  `ui/worker.py` is the seam: generation already runs off the GUI thread.
- **Sunglasses completion states** (§§38–39) — setup finished, a major repair worked, a
  project milestone works, verified configuration. Sparing. Not every save.
- **The waiting hierarchy** (§53) — under ~1 s gets no graphic at all; short waits get
  inline text; meaningful waits get the eagle; a major download gets the eagle *plus* real
  numbers. Never replace numeric progress with animation: `setup/downloader.py` already
  reports real bytes and that stays.
- **The completion hierarchy** (§54) — routine `Saved` / `Ready`, a useful milestone gets a
  line from Gary, a significant one gets the graphic.
- **Widen the Local AI settings page** — see §4 above, 8 px of margin.
- **The pending-backup question** is still open — HANDOFF §6C-bis. Nothing surfaces "3
  projects waiting to back up" today, deliberately (§29A: no visible complexity). Whether
  a parent wants to see it is a Phase 10 product question nobody has answered.

## 7. What 10D should do

Wordmark and compact-logo placement across app and setup, icon work per `DESIGN_DOC` §18,
a consistency pass, and final cocoa screenshots at realistic window sizes. Then the
restated exit criterion in `PLAN.md`.

---

## 8. Traps specific to this phase

Everything in `HANDOFF.md` §4 still applies. These are the ones 10A hit.

- **`offscreen` is not `cocoa`, and the numbers differ.** The GitHub block measured 676 px
  down a 431 px viewport offscreen against 726/443 under cocoa. Same defect, different
  arithmetic. Layout thresholds need margin, and a final look needs the real platform.
- **`QWidget.grab()` under cocoa works and needs no screen-recording permission.** The
  driver is in the scratchpad, not the repo. Set
  `app.setQuitOnLastWindowClosed(False)` — SPIKES §17F's own lesson is that a harness
  reported 11/11 passed while silently skipping every stage after a dialog accepted.
- **An aggregate contrast metric hides a per-element failure.** My whole-image mean scored
  the compact mark 73 on charcoal and passed it. The black `ON` was invisible. Looking at
  the render caught what the number missed — measure per band on a composite.
- **`Image.paste(im, box, im)` erodes edge alpha.** Using the image as its own mask
  multiplies alpha and drops semi-transparent edge pixels below threshold. For an exact
  integer translation of pixel art, shift the array; do not composite.
- **A varying bounding box is not mis-registration on a flap cycle.** The wings *should*
  move. Measure the body — feet baseline and body edge, wings excluded — or you will
  either miss the defect or invent one.
- **`_panel_text` must not call itself.** A mechanical rewrite of
  `self._output.setPlainText(` → `self._panel_text(` caught the line *inside*
  `_panel_text`, producing a `RecursionError` in seven tests. Obvious in hindsight.
- **A missing brand asset raises rather than rendering blank.** `brand.py` raises
  `FileNotFoundError`. This project has been bitten three times by a data file nothing
  installed; a silently empty logo is the same failure wearing a nicer coat.

These are the ones 10B hit.

- **A clean grep of the copy proves nothing about tone.** The banned-register sweep came
  back empty across all 826 strings, and the product was still saying "Great!" on routine
  successes. The model supplies the word. Static checks cover what the application
  writes; only the real model covers what it says. SPIKES §18B.
- **A fixture that names a file the project does not have measures the fixture.** The
  tool-selection spike scored 12/16 until three "misses" turned out to be the model
  correctly reporting that `main.py` does not exist. The Games template's file is
  `game.py`. Read the raw replies before believing the score — third instance of §17F's
  lesson in this phase alone.
- **`section_label` uppercases its argument**, so the conversation panel reads `GARY`.
  A test asserting `"Gary" in titles` fails against `['GARY']` and would be pinning the
  theme rather than the name. Compare casefolded.
- **An honesty rule can make honesty worse.** Eleven lines telling the model not to
  claim unverified things cost a tool-selection point, and the failure it caused was the
  model *claiming an edit it never made*. Prose about not asserting things competes with
  the instruction to act. Tie the rule to the action — "call a tool and find out", not
  "find out" — and keep it short. SPIKES §18C.
- **`base.txt` is hard-wrapped, so a prompt assertion can straddle a line break.**
  `test_voice.base_prompt()` collapses whitespace before matching. Without that, a test
  fails for a reason unrelated to the rule being present, and the tempting fix is to
  rewrap the prompt, which teaches the wrong lesson.
- **`test_the_warning_does_not_pretend_it_stays_on_the_mac` is a blunt substring guard,
  and it earns it.** A first draft of the §10 rewording said the model runs "not on this
  Mac" — factually true, phrased in the exact words §24 forbids, and caught immediately.
  Do not reach for "on this Mac" in cloud copy even to negate it.

### Packaging — a real gap, not yet closed

`pyproject.toml`'s `[tool.setuptools.package-data]` can only ship files **under
`opennest/`**, and the prepared delivery is at top-level `assets/`. There is no
`MANIFEST.in`. The product ships as a git clone today — the comment in `pyproject.toml`
says so explicitly — so the assets are simply present and `brand.py` resolves them
relative to the package, the way `git_manager.askpass_helper()` resolves `askpass.sh`.

`test_every_declared_brand_asset_is_on_disk` fails loudly if that stops being true. But
**if Open Nest is ever built as a wheel or an app bundle, the brand assets will not be
included.** That needs either a `MANIFEST.in` with `include_package_data`, or the runtime
derivatives moved under `opennest/`. Deliberately not done in 10A because it is a
packaging decision, not a design one.

---

## 9. Not done, and not attempted

- **10C and 10D.** Nothing wired into any screen. `brand.py` is built and tested but
  still has no consumer — 10B was voice and copy, and touched no artwork.
- **Gary's voice is measured on one model and five prompts** (SPIKES §18B). Read it as
  "the voice arrived and cost nothing measurable", not "Gary is tuned". The warmth
  instruction has one adverse data point and no follow-up.
- **No HiDPI verification.** Brand guide §44 asks for testing at 2x, on a 13-inch display
  and an external Retina display. `brand.py` snaps to prepared sizes and never rescales,
  which is the right foundation, but `devicePixelRatio` is not consulted — a 128 px mark on
  a 2x display currently asks for the 128 px file rather than the 256 px one. That is the
  next thing to do in 10C and it is a small change.
- **Nobody has watched the eagle animate for more than a few seconds.** The registration
  is verified by measurement and by a twelve-frame contact sheet, and all twelve frames
  draw under cocoa. Brand guide §35 asks for playback to be tuned *visually*; 8 fps is the
  delivery's recommendation, not an observation.
- ~~**The flaky parent-PIN test.**~~ **Fixed.** It failed once during a Phase 10 run — the
  ~1-in-800 flake `HANDOFF.md` §4 documents, where a four-digit decimal PIN turns up in
  the random hex salt by chance. HANDOFF claimed it had been "fixed by fixing the salt"
  and it had not; the test had been renamed, which is the likeliest way the fix got lost.
  Now genuinely fixed: the salt is pinned through a `fixed_pin_salt` fixture, and the
  haystack narrowed from the whole record to the salt and digest. That second part matters
  more than the flake — `$200000$` contains `0000`, so a whole-record check fails a parent
  PIN of `0000` **every** time, not one run in 800. Two tests added, and
  `HANDOFF.md` §4 corrected.
- **New scope raised by the developer, not part of Phase 10:** a project coding interface
  that launches a local server and a Chrome browser view for building HTML web apps in
  Open Nest. That is a new profile and a new execution path — it touches
  `process_sandbox` (the sandbox denies network, and a local server is a network listener),
  `profiles.json`, and `execution/`. It should take the privileged-action pattern in
  `HANDOFF.md` §5 rather than a new mechanism, and it deserves its own phase and its own
  spike rather than being folded into a design pass.

---

## 10. Git state

**Resolved for 10A; 10B is uncommitted.** The branch is `phase-10-design`, cut from
`phase-9-github`, with two commits, local only — nothing pushed, nothing merged to
`main`. The guide and the prepared artwork went in as their own commit before the code,
so `brand.py` resolves on a clean checkout.

10B's changes are in the working tree and **not committed**. `CLAUDE.md` says not to
commit, push, branch or open PRs without being asked, and that was not asked.

Per `HANDOFF.md` §1, Phase 10's PR opens against `phase-9-github`, not `main`.
