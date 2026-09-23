# Phase 10 handoff — design and polish

**Phase 10 is complete — stages 10A, 10B, 10C and 10D.**

Read `HANDOFF.md` first for the project as a whole; this file covers Phase 10 only and
assumes you have read `brand_design_guide.md` (2,166 lines, 63 sections) and
`DESIGN_DOC.md` §§2–23.

```
841 tests pass (724 at Phase 9 — 117 added).  ruff clean.
29 surfaces render under the real cocoa platform at devicePixelRatio 2.0;
the 18 from 10D cover both colour schemes.
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
common body anchor. Feet spread 51 px → **0 px**, body spread 53 px → **0 px**, with
**0.000%** of the ink clipped. `tests/test_brand.py` re-derives the alignment from the
rendered images rather than trusting the table, and a negative control asserts the raw
frames really do drift — so if a corrected frame set is ever delivered, the test tells
you and the table can be retired.

The table is **generated** as of 10C: `tools/prepare_brand_assets.py --table`. One thing
in it is worth knowing before regenerating — the clamp that stops a translation pushing
the bird off-canvas keys on alpha ≥ 8, not alpha > 0. The artwork is soft enough that a
single one-part-in-255 pixel reaches the edge in most poses, and clamping on that blocks
the translation entirely, leaving the body hopping 16 px at 256. Measured both ways; the
script reports the ink each run clips so the trade stays visible.

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

**This blocked the Workbench header, and 10C worked around it rather than solving it.**
Brand guide §57 asks for the compact mark there; in dark mode the header uses the
**nest-only** mark instead, which §48 sanctions "where the product identity is already
clear from surrounding text" — the header carries the project name and "Workbench". The
two marks are within a pixel of the same height, so the header does not change shape
between schemes. The gap itself is unchanged and
`test_the_compact_mark_has_no_dark_variant_yet` is still the test to delete when a dark
variant arrives; `test_the_dark_workbench_falls_back_to_the_nest` is the one that then
needs revisiting.

**Do not try to generate the dark variant.** 10C generated a 40 px compact mark for an
unrelated reason and withdrew it after looking at the render (§5A) — the lockup is
already at its legibility floor, and reconstructing it in code would be guessing at
approved brand geometry.

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

### ~~One documentation inconsistency, not a defect~~ — this was wrong, corrected in 10C

This section used to claim that `asset_manifest.json`'s `"pixel_rendering":
"nearest-neighbor"` was inaccurate, on the evidence that only 57–73% of the prepared
sizes' alpha values are fully 0 or 255. **That inference does not hold, and the manifest
is correct.** Measured in 10C by reproducing the pipeline: `nest_w96` and every eagle
frame set are *exact* nearest-neighbour downscales of their masters — 0.00 mean
difference, not "close". The intermediate alpha comes from the **source artwork**, which
is already soft: only **0.7%** of the eagle sheet's pixels are fully opaque and 23.6% are
partially transparent. A nearest-neighbour downscale of soft art preserves soft alpha; it
does not create it. The original measurement mistook a property of the source for a
property of the resampling.

The conclusion that survives is the one that mattered: the artwork is pixel-art *styled*
raster with no native grid to snap to, so **draw prepared sizes 1:1 and never rescale**.
`FastTransformation` only matters if something scales, and `brand.py` does not.

What changed as a result is the *eagle*, and only the eagle — see "What 10C did" below.
Nearest-neighbour is fine for a still mark and measurably wrong for a twelve-frame loop.

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

## 5A. What 10C did

The visual system reached the screens. Every item in §6 below is done; what follows is
what is not obvious from the diff.

### The eagle ladder was rebuilt, and a single-frame metric could not see why

The developer asked for an indicator at the size of the macOS spinning indicator (32 pt).
The delivery's frame sets started at **64 px**, so a 32 pt eagle would have been 1:1 on a
Retina Mac and a 2:1 downscale on a 1x display. Rather than accept a soft path,
`tools/prepare_brand_assets.py` now regenerates the whole ladder — guide §50's
preparation script, which did not exist.

**The measurement that decided the method is the interesting part.** Three single-frame
metrics all rated nearest-neighbour *best* at 32 px: ink mass 99.6% of the master against
area-averaging's 100.0%, round-trip error 12.66 against 12.97. Every one of them is an
average over the twelve poses, and the defect is in the **spread between** them. Nearest
samples a different subset of the soft source in each pose, so the bird's apparent weight
swings **3.90 percentage points** across the cycle at 32 px and **2.17 pp** at 64 px —
which is the bird pulsing as it flaps. Area-averaging holds it to **0.36–0.65 pp** at
every size. Invisible in a still, obvious in a loop, and the third instance in this phase
of an aggregate hiding a per-element failure.

Registration improved with it: feet spread and body spread both **0 px** now (1 px
before), with **0.000%** of the ink clipped. The offsets table in `brand.py` is generated
— `tools/prepare_brand_assets.py --table` reproduces it.

### One generated size was withdrawn, and that is the more useful finding

A 40 px compact mark was generated for the Workbench header, then **deleted after looking
at it**: at 40 px the `ON` is illegible and the nest is a blob, which is exactly §33's
"do not reduce the artwork until it becomes illegible". Rendering the ladder shows the
lockup starts to read at **64**, which is precisely where the delivery's compact ladder
starts.

**The delivery's minimum sizes encode legibility thresholds, not convenience.** Treat
them as findings. `MARK_OUTPUTS` in the preparation script is deliberately empty and says
so. The eagle is the exception because it is one bold silhouette with no fine detail to
lose — which is why it survives at 32 px where two letters do not.

### HiDPI, and what `QLabel` does to your pixmap

`brand.pixmap` takes a **logical** size, multiplies by the display ratio, picks the
prepared file for that *device* size and sets the ratio on the pixmap. Every entry in
`brand.PLACEMENTS` has an exact 2x file, and `test_every_placement_size_has_an_exact_2x_file`
fails if a new placement picks a size whose double is missing.

Verified at 2x for real: `QT_SCALE_FACTOR=2` makes Qt report `devicePixelRatio() == 2.0`
even under `offscreen`, so the default path — the part that cannot be injected — is
covered by a subprocess test rather than only by arithmetic.

### The child sees backup state; the parent sees the detail

Settled with the developer, closing `HANDOFF.md` §6C-bis. The Flight Deck gains a third
status line — `BACKUP ● COMPLETE` / `○ WAITING FOR INTERNET` / `○ NOT SET UP` — and never
shows queue depth, repository names, commit counts, push failures or any git vocabulary.
Parent Settings → GitHub Backup gets the count and the reason.

"Waiting for internet" is a **verified** claim, not a guess: `PushQueue.drain` keeps an
entry only when the push raised `Offline`, while a rejected or secret-blocked push is
dropped and reported to a parent. An entry queued but never yet attempted says plain
"Waiting", because it has not failed at anything.

### The approval mark fires once per project, on the first run that worked

`manifest.last_successful_run` is written only by `Toolbox._run_project` and
`_compile_project`; the toolbox is four tools wide, so there is no helper command that
could trip it. The Workbench captures the flag *before* dispatch, the way it already
snapshots pictures.

The wording is load-bearing. `RunResult.ok` means different things per profile — ran to
completion (batch), the compiler accepted it (Arduino), or **survived a four-second
startup grace and is on screen** (interactive). That last one is not evidence a game
works, so §38's "It works." would claim a state nothing verified. §38's other line,
**"You built that."**, is about authorship and is true in all three.
`test_the_approval_line_claims_nothing_the_run_did_not_show` pins it against the words
that would over-claim.

### Also in 10C

- **`theme.is_dark()`** — the one place a screen learns which brand variant to ask for.
- **The Workbench header is the compact mark in light, the nest in dark.** §48 permits
  nest-only where surrounding text makes the product clear. §3's blocker stands and
  `test_the_compact_mark_has_no_dark_variant_yet` still records it.
- **The Flight Deck identity is horizontal.** Stacked it ran ~200 px and pushed "What do
  you want to make?" **38% down the window** at the 900×600 minimum with the status
  footer off screen. §48 allows the nest "beneath or adjacent"; adjacent is ~80 px and
  29%.
- **`QProgressBar` had no theme rule**, so the model download — the one place a parent
  watches for 200 seconds — rendered macOS system blue in a bone-and-charcoal page. Now
  amber, per §25's "loading progress".
- **The window had no minimum size at all** (reported 88×88, so it could be dragged to
  where the Workbench header clips). Now 900×600, measured against the Workbench's own
  811×444. Nothing caps the maximum, which is what keeps the macOS full-screen button.
- **The Local AI settings page** went from 496 px in a 520 px viewport to **255 px** —
  `_model_row`'s detail line was an unwrapped `mono_label`, the same fault §4 found three
  times.

### About Gary — the one personality addition

Added at the end of 10C by developer direction. The interface calls the assistant Gary
by name, so someone will eventually wonder who that is; this answers it and stops.

A quiet `ⓘ` beside the conversation panel's heading opens a **popover** — `Qt.Popup`,
dismissed by the next click anywhere, deliberately not a dialog, because a modal window
makes reading a joke feel like a task. The copy is approved verbatim, long form,
`opennest/ui/about_gary.py`.

Four constraints, all of which have a test because each is the kind of thing a later
tidy-up would quietly undo:

- **Never surfaced automatically.** Not onboarding, not a first-run card, not a hover.
  `test_nothing_opens_the_bio_on_its_own`.
- **"Gary wrote this bio." is the joke and is load-bearing.** The bio is third person
  throughout and then signs itself. It reads like a stray sentence to anyone who has not
  been told, which is precisely why `test_gary_wrote_his_own_bio` exists — and why the
  same test asserts the piece stays in the third person.
- **No face, no borrowed artwork, no emoji.** §47 keeps Gary and the pixel symbols
  apart, so the bio never mentions the eagle, nest or sunglasses and the popover
  contains no pixmap at all.
- **Dry.** No exclamation marks; the humour is in the deadpan.

The bio is written as a plain literal rather than interpolating `ASSISTANT_NAME`, which
is a deliberate trade: `test_voice.user_visible_strings` walks `ast.Constant` nodes and
an f-string is **split into fragments at every substitution**, so a banned phrase could
straddle a join unseen. A literal is swept whole, and
`test_the_bio_uses_the_assistant_name_the_rest_of_the_app_uses` is what catches a rename
instead.

`SHORT_BIO` is the approved shorter form. Nothing uses it; it exists so a future cramped
placement shortens the bio by choosing it rather than by inventing a third version and
losing the last line.

### New files

| File | What it is |
|---|---|
| `tools/prepare_brand_assets.py` | Guide §50's preparation script. Regenerates the eagle ladder and the registration table, deterministically, from the delivery's masters. |
| `opennest/ui/about_gary.py` | The optional aside and its popover. |
| `tests/test_brand_placement.py` | 20 tests. Mostly about *restraint* — that the eagle stops, that the mark fires once, that nothing bypasses `brand.py`. |
| `tests/test_window_sizing.py` | 5 tests. Normal-application window behaviour. |

---

## 6. What 10C should do — **done**

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
- ~~**The pending-backup question**~~ **Resolved.** Two levels of visibility, set by the
  developer: the child sees plain backup *state* on the Flight Deck and never the
  mechanism; the parent sees the count and the reason in Parent Settings. See §5A.

## 6A. Final QA — carried into 10D, not blocking 10C

Two checks the developer accepted as final-QA items rather than as work. Both are
"somebody has to look", and neither can be settled by a test.

**Watch the eagle loop.** Guide §35 asks for playback to be tuned *visually*, and 8 fps
is still the delivery's recommendation rather than an observation. What *is* measured is
that it no longer hops (0 px body drift) and no longer pulses (0.36–0.65 pp ink swing).
What nobody has done is watch it flap for a minute and say whether it feels
"deliberate, charming, slightly mechanical, alive, not frantic". The developer is doing
this before signoff.

If it reads wrong, §35 permits exactly two levers and **more frames is not one of them**
— "do not artificially tween", "do not generate intermediate frames". The levers are the
6–10 fps range (`brand.EAGLE_FRAME_MS`, currently 125) and holding individual poses
longer than others, which would mean giving the indicator a per-frame duration table.

**A second display.** §44 asks for a 13-inch display, an external Retina display, and
multiple application scaling settings. 10C measured **one machine at ratio 2.0** under
real cocoa. The arithmetic is covered at both ratios and the default path is covered by
a subprocess test, so what is missing is a second physical display rather than a code
path.

---

## 7. What 10D did

**The scope shrank, and that was the point.** The developer set the principle: *the
closer a surface is to actual work, the less branding it needs* — Flight Deck strongest,
Workbench compact, settings and dialogs restrained, functional modals prioritising the
task over the logo — and *do not add branding simply because a surface exists*.

Applied honestly, **one** new placement survived.

| Surface | Decision |
|---|---|
| Settings → General | **Wordmark, 192.** This is the product's About surface — it is where the version lives — and guide §30 names "About Open Nest" as a place the mark belongs. Smallest prepared width, because a settings page is a utility surface. |
| Settings, other five pages | Nothing. The nav already says where you are. |
| GitHub device-flow dialog | **Nothing.** A task surface whose focal element is a code a parent has to read; §17F defect 3 was about making that code prominent, and a mark beside it would compete. The copy says "Open Nest" in ordinary text, which is what §30 asks for. |
| Migration / update dialog | **Nothing.** A lifecycle task. It already uses the design system throughout. |
| Consent dialogs (cloud, PIN, permission) | **Nothing.** Safety-critical modals; the decision is the content. |
| New project dialog | **Nothing.** A task, two fields deep. |

### The consistency pass is mechanical now, not a read-through

`tests/test_design_consistency.py`. `theme.py` has always opened with *"Widgets should
never hard-code a colour"*; that is a test as of 10D, because both halves fail silently:

- **Every `role`/`state` a widget sets must be styled.** An unstyled one is not an error
  — Qt draws it in the default system appearance, legible and plausible and wrong only
  beside a correctly styled sibling.
- **No colour outside the palette, and no `setStyleSheet` outside `theme.py`.** Both were
  already clean; they are now guaranteed.
- **Light and dark share no values**, so dark stays a scheme rather than light with
  overrides.
- **Every dialog offering a choice marks its primary action.** This found a real defect:
  the device-flow dialog's `Connect GitHub` and `Cancel` rendered identically, so a
  parent had to read both to find the way through. Every other action surface already
  marked its primary.

The audit also found `role="wordmark"` dead — 10C replaced the Flight Deck's text
masthead with the pixel one and nothing else used it. Removed.

**A trap from writing that test, worth keeping.** The first version searched
``ast.unparse(node)`` for ``'"role", "primary"'`` and reported four offenders including
dialogs that plainly do set it. ``ast.unparse`` renders string literals in **single**
quotes, so the substring never matched. A consistency test that flags everything is
indistinguishable from one that flags nothing; walk the tree instead, and negative-control
it by removing a real usage and checking it complains.

### Deliberately not done

- **The application icon.** Ruled out of Phase 10 by the developer, and recorded in
  `DESIGN_DOC.md` §23 so it closes the apparent §18 conflict rather than looking
  forgotten: it needs a separately approved simplified mark, and deriving one from the
  canonical nest without design approval is exactly what 10C's withdrawn 40 px compact
  mark demonstrates the risk of.
- **Any responsive logo geometry.** Prepared assets and documented fallbacks only.

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

These are the ones 10C hit, and the first two cost the most.

- **A single-frame quality metric cannot see an animation defect.** Ink mass and
  round-trip error both rated nearest-neighbour the *most faithful* downscale at 32 px.
  Both are averages over the twelve frames, and the defect — a 3.90 pp swing in apparent
  weight *between* frames — lives in the variance they average away. Measure the spread
  across a cycle, not the mean of it.
- **`QLabel.pixmap()` does not return the pixmap you set.** Hand it a 128 px pixmap at
  ratio 2.0 and it gives back a 64 px one at ratio 1.0. Painting is unaffected — a 1 px
  stripe pattern survives a 2x `grab()` intact, so Qt really does keep the
  high-resolution data — but a HiDPI test that believes the getter reports a defect that
  is not there. Assert on what `brand.py` returns, not on what the label hands back.
- **A nested layout breaks `widget.parentWidget().layout()`.** Moving the Flight Deck's
  status rows into a layout beside the eagle left their `parentWidget()` as the page body
  while the body's layout no longer contained them. `replaceWidget` then silently does
  nothing, the replacement is never laid out, and it paints on top of whatever is behind
  it — "Start with an idea" and "LOCAL AI CHECKING" rendered over each other. **Nothing
  threw and the whole suite passed.** Hold a reference to the layout that actually owns a
  widget, and `setParent(None)` the widget you replaced.
- **The delivery's smallest prepared size is a legibility threshold.** Generating a
  smaller one is easy and was wrong: the compact mark's `ON` disappears below 64 px,
  which is exactly where its ladder starts. Render a candidate size before adding it.
- **`QT_SCALE_FACTOR=2` gives a real 2x display under `offscreen`**, which makes the
  HiDPI path genuinely testable — but only in a subprocess, since the scale factor is
  read once when `QGuiApplication` starts.
- **A plain `QWidget` used as a layout holder paints the window colour**, so a container
  dropped inside a panel draws a band across it. `role="bare"` is the fix; `QLabel`
  already had the same treatment.

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

- **10D.** Not started. 10C wired every component into the screens; what remains is
  icon work per `DESIGN_DOC` §18, the consistency pass, and final screenshots.
- **Gary's voice is measured on one model and five prompts** (SPIKES §18B). Read it as
  "the voice arrived and cost nothing measurable", not "Gary is tuned". The warmth
  instruction has one adverse data point and no follow-up.
- ~~**No HiDPI verification.**~~ **Done in 10C.** `brand.py` resolves logical sizes
  against `devicePixelRatio`, every placement has an exact 2x file, and the cocoa render
  ran at ratio 2.0. **Still not done:** §44 also asks for a 13-inch display and an
  external Retina display specifically, and for multiple application scaling settings.
  One machine, one ratio, is what has been measured.
- **Nobody has watched the eagle animate for more than a few seconds.** Still true, and
  now the *shimmer* is measured away as well as the hop — ink mass holds to 0.36–0.65 pp
  across the cycle. Brand guide §35 asks for playback to be tuned *visually* and 8 fps is
  still the delivery's recommendation rather than an observation. §35 permits two levers
  if it reads wrong: the 6–10 fps range, and holding individual poses longer. It does
  **not** permit more frames — "do not generate intermediate frames".
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
