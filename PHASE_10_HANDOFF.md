# Phase 10 handoff — design and polish

**Stage 10A is complete. 10B, 10C and 10D are not started.**

Read `HANDOFF.md` first for the project as a whole; this file covers Phase 10 only and
assumes you have read `brand_design_guide.md` (2,166 lines, 63 sections) and
`DESIGN_DOC.md` §§2–23.

```
773 tests pass (724 at Phase 9 — 49 added).  ruff clean.
18/18 checks pass under the real cocoa platform.
Nothing is committed. See "Git state" at the bottom before you do anything else.
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

## 5. What 10B should do

Adopt Gary and do the copy pass. The tone rules are brand guide §§1–24; the personality
hierarchy in §21 is the tie-breaker (clear → useful → calm → warm → human → dryly funny →
eccentric, and never sacrifice clarity for personality).

Where the strings are:

- `opennest/ui/` — `workbench.py` (the largest share, including `_say`), `flight_deck.py`,
  `settings.py`, `consent.py`, `new_project.py`, `github_connect.py`, `common.py`
- `opennest/setup/` — `wizard.py` (nine steps; a parent's first impression), `update_dialog.py`
- `opennest/prompts/` — `base.txt` and the per-profile prompts. Gary's voice in
  conversation comes from here, not from the UI.

Three things to know before you start:

- **`self._say("Assistant", ...)` and `self._say("Open Nest", ...)` are the current speaker
  labels** in `workbench.py`. That is the seam where Gary arrives, and it is also where
  the system-versus-Gary split gets decided per message.
- **`prompts/base.txt` is where brevity is asked for**, not the token cap — HANDOFF §6B
  is explicit that shrinking `output_headroom_tokens` to control verbosity just truncates
  mid-sentence.
- **Do not put personality into the honesty machinery.** `assets.invented_description`
  and `_claimed_a_change_it_did_not_make` fire on deterministic checks and their wording
  is load-bearing; HANDOFF §6A explains why the narrowness matters. Gary can be warm about
  a correction, but the trigger stays mechanical.

Copy that already exists and is already right per the guide: the Cloud AI warning's
Cancel / Ask Parent buttons (§10), and `_model_row`'s refusal to say "premium" or
"powerful" (`DESIGN_DOC` §13).

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

- **10B, 10C, 10D.** Nothing wired into any screen. `brand.py` is built and tested but
  has no consumer.
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

## 10. Git state — read this before anything else

**Nothing is committed.** All of 10A is uncommitted in the working tree, and the current
branch is still `phase-9-github`.

`CLAUDE.md` says not to commit, push, branch or open PRs without being asked, and that was
not asked. So the next person needs a decision from the developer:

- `assets/` and `brand_design_guide.md` were already untracked before Phase 10 began. A
  fresh clone has neither the guide nor any artwork, so **nothing in `brand.py` can
  resolve on a clean checkout until they are committed.**
- Per `HANDOFF.md` §1, Phase 10 should be branched from `phase-9-github` and its PR opened
  against `phase-9-github`. Nothing is merged to `main`.

Suggested first action: confirm the branch name, create it from `phase-9-github`, and
commit the prepared assets and the guide as their own commit before the code — the code is
meaningless without them.
