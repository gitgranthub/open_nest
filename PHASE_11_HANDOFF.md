# Phase 11 — starter kits, the Website profile, and a machine-aware model registry

Read [HANDOFF.md](HANDOFF.md) first. This file is what Phase 11 added, what it measured,
and what it deliberately did not do.

**Phase 12 is the owner's first hands-on use of the application, and nothing in it has
started.** Do not begin it from here. Phase 11 exists so that the starter system and the
model registry — both of which change real interaction paths — are finished *before*
anybody judges the finished experience.

---

## 1. What is here

Two tracks, both complete.

**11A — starter kits and the Website profile.** A project no longer always begins from a
template that was always applied. A profile offers zero or more *starter kits*, names
which one it begins with (or `null` for empty), records what was used in `project.json`,
and tells Gary. A new `website` profile builds a page out of three plain files and
previews it inside Open Nest behind an enforced offline policy.

**11B — the model registry.** Machine capability detection, a layered catalogue, a
deterministic per-Mac recommendation, discovery of models already on the Mac, and
migration. The four inputs of the work order's section 21 are four modules under
`opennest/models/`, and the compatibility decision belongs to Open Nest rather than to a
provider, a search, or a model.

980 tests pass, ruff is clean.

---

## 2. Things that will bite you

These each cost real time. None is obvious from the code.

**A clean suite says nothing about a window, and this phase proved it three more times.**
Every defect below was found by rendering something and looking at it, while the whole
suite passed:

- **`project.json` sat in the child's file panel above the words "Nothing here yet."**
  The manifest had always been in that list and had always read as a file the child made;
  the new empty state turned it into a contradiction on screen. It is now filtered out of
  the panel and still present in `visible_files`, so the model is told what is really
  there.
- **The setup wizard crashed the interpreter on Quit.** See below — it is the worst thing
  this phase found.
- **A 64 GB Mac was suggested the same 2.3 GB model as an 8 GB Air.** Found by a test
  rather than a render, but the same shape of error: `verified` ranked above size in the
  suggestion, and exactly one local entry is verified, so the ladder could never move.
  `verified` is a fact about *Open Nest's testing*, not about the model, and using it as a
  tiebreak silently turned it into one.

**Destroying a widget while one of its worker threads runs aborts the interpreter.** No
traceback, no failed test — the process dies. The test fixtures have quit-and-waited by
hand since Phase 5, so the hazard was understood and guarded everywhere *except* in the
application. Phase 11B made it reachable: `LocalAIStep.enter` now starts a worker the
moment the step opens, so there is a live thread during a step a parent may well press
Quit Setup on, and `set_busy` deliberately does not disable quitting.
`ui.worker.stop_thread` is the fix and `SetupWizard.done` / `Workbench.release` are where
it is called. **If you add a worker, wait for it on the way out.**

**Qt destroys a `QWebEngineProfile` whose page is still alive with "Expect troubles!",
and the trouble is a crash.** The page is parented to the profile, `closeEvent` releases
it explicitly, and `deleteLater` is flushed with `sendPostedEvents` because the wait can
happen during teardown when no event loop will turn again. Closing a parent widget does
**not** call `closeEvent` on its children, which is why `MainWindow._close_project` asks
the Workbench to release rather than trusting Qt.

**`du` still tells you almost nothing about a Hugging Face cache, and Phase 11 found the
second half of why.** SPIKES.md section 15C recorded that a complete model reads as a few
megabytes. The reason is that `<cache>/blobs` is a *shared* content-addressed store —
there is a `.huggingface-shared-blobs` marker in it — and `models--<repo>/` holds
symlinks into it. So **deleting the repository directory frees almost nothing** and leaves
gigabytes nothing will ever read. `downloader.remove` goes through
`scan_cache_dir(...).delete_revisions(...)`, which owns that layout; a dry run against the
real cache reported 2.28 GB and predicted freeing 2.3 GB.

**Chromium refuses a remote request from a `file:` page before your interceptor sees it.**
Measured both ways (SPIKES.md section 19). With
`LocalContentCanAccessRemoteUrls=False` an `<img src=https>`, a remote `<link>` and a
JavaScript `fetch()` were all refused with the hook seeing *nothing*; flipping it on, the
hook saw and blocked both. The first draft of `execution/web_preview.py` claimed the
interceptor was what kept the page offline. It is not, and the consequence is the real
one: **a blocked request is silent**, so a child would see a missing picture and no
explanation. `remote_references()` reads the project's own source before the render and
says what will not load. The interceptor's actual job is stopping the page reading files
*outside* the project, which it was measured doing — an `<iframe src="file:///…">` was
seen, blocked, and its canary did not reach the page.

**Loading a model from anywhere it happens to be is not a convenience, it is a hole.**
The first version of `resolve_local_model` searched every cache on the Mac so an existing
model would not be downloaded twice. That silently widened what Open Nest reads: weights
it did not fetch, cannot vouch for, and on a work-managed machine are exactly what
containment exists to keep in one place — and it would have failed closed under Seatbelt
anyway. `discovery.load_paths()` (contained) and `discovery.discover_paths()` (wider,
read-only) are now different lists, and the gap between them is where the parent's choice
goes.

---

## 3. How starter kits work

`opennest/projects/starters.py`. A kit is a directory under `opennest/projects/starters/`
with a `starter.json` beside the files it ships.

```
starters/website_basic/
    starter.json      id, profile, name, description, entry_point, version, files
    index.html
    styles.css
    script.js
```

**Config schema 2** replaced `starter_template` with two fields:

| | |
|---|---|
| `starters` | the kit ids this profile offers. May be `[]`. |
| `starter_default` | which one a new project begins with, or `null` for empty. |

`null` rather than `""` deliberately: a falsy-string sentinel is one every future consumer
has to remember. `test_no_profile_uses_an_empty_string_where_it_means_no_default` pins it,
and `test_nothing_still_reads_the_schema_1_starter_field` tokenises every module to prove
no code still looks for the old key.

**The schema allows a starter; it does not require one.** Blank offers none at all — the
Phase 0 `blank_basic` kit was withdrawn rather than left offered, because a profile whose
whole purpose is an empty page should not have a starter to decline. Image Creation keeps
`prompts.md`, and that is not schema filler: `prompts/image_creation.txt` instructs Gary
to keep that file current, so it is the one thing that profile's prompt depends on
existing.

**Applying one never overwrites work.** `starters.apply` refuses if any file it would
write already exists, and it refuses *before* writing anything. That is what makes the
one-click "Add Basic Website" safe: it is only offered into an empty `src/`, and the
refusal is in the function rather than in whichever button calls it.

**What Gary is told, and what he is not.** `project_state()` names the kit, its
description, and — explicitly — that *those files are the child's now, to change, remove
or replace*. Section 14 of the work order asks for that and it needed saying, because a
model told "this came from a starter" will otherwise treat it as boilerplate to preserve.

When `starter_id` is `None` the prompt says **nothing**, and that covers two different
cases on purpose: a project started empty, and a project made before Phase 11. Claiming
"started empty" about the second would assert something nobody measured — its files might
be a Phase 0 template or might by now be entirely the child's.

---

## 4. The Website profile

`run_mode: "preview"` — the only one. A website is not executed: no process, no exit code,
nothing for the process sandbox to confine, because the files *are* the thing.

**No toolchain, and that is a requirement rather than a simplification.** No React, Node,
npm, bundler or build step; `packages` and `frameworks` are both empty and the prompt
forbids introducing any. A child's first website should be understandable as files.

**Gary has not seen the page**, exactly as he has not seen a picture. There is deliberately
no preview tool — giving him one would produce "the page looks fine", which is the
section 13 honesty problem in a new costume. The profile has three tools, not four.

**The preview is rendered inside Open Nest, not handed to a browser.** Safari would work
and would give the page the whole internet, a history, a cookie jar and whatever
extensions are installed. Two guards, and it matters which does what (section 2 above):
Chromium's own `LocalContentCanAccessRemoteUrls=False` is what makes the internet
unreachable; the request interceptor is what stops the page leaving the project on disk.

**Imported pictures live one level up.** The preview root is the *project* directory, not
`src/`, so `<img src="../assets/dragon.png">` resolves — a website that could not show a
child's own pictures would send them to the internet for pictures instead.

---

## 5. How the model registry works

Five modules under `opennest/models/`, one question each.

| module | question |
|---|---|
| `machine.py` | what is this Mac? |
| `catalog.py` | which models does Open Nest know about? |
| `remote.py` | has that list changed since this release? |
| `discovery.py` | which are already here, and what does a provider have today? |
| `compatibility.py` | given all of that, what should this Mac run? |

**Detection happens in one function and nothing else calls it.** `machine.detect()`
returns a `MachineProfile`; every decision downstream is a pure function of that value and
is *handed* one. That is what lets an 8 GB Air, a 16 GB Pro and a 64 GB Studio all be
tested on a machine that is none of them — and it is not academic. The target hardware is
8 GB and every measurement in this repository was taken on 48 GB.

**The memory numbers are guidance derived by a stated rule, not measurements.** One thing
was measured: Qwen3 4B, a 2.28 GB download, is 2.61 GB resident — a ratio of about 1.15.
So `estimated_memory_gb = download_gb × 1.15 + 0.5`, and the minimum and recommended
figures add room for macOS and round **to memory sizes Apple actually ships**. A threshold
of 12 GB is a threshold no Mac can sit on. The rule is written into `models.json` so it can
be argued with.

**The catalogue got larger models, because a tiering engine with nothing to tier is
machinery.** Before this every local entry claimed `recommended_ram_gb: 8`. Qwen3 8B, 14B
and Coder 30B-A3B were added with real pinned commit SHAs and real sizes read from the
Hugging Face metadata API on 2026-09-22 — metadata only, no weights fetched. **Only Qwen3
4B is `verified`**; `compatibility.untested_note()` is how the others say so on screen.

The ladder, as it now behaves:

| Mac | suggested |
|---|---|
| 8 GB M1 Air | Qwen3 4B — 2.28 GB |
| 16 GB M2 Pro | Qwen3 8B — 4.62 GB |
| 64 GB M4 Max | Qwen3 Coder 30B — 17.20 GB |

**A remote catalogue is data and cannot become anything else.** There is no field for a
URL, a path or a command — a local model is a repository id plus a commit SHA, both
validated, and *where* those are fetched from is a constant in Open Nest. So a hostile
catalogue's worst case is naming a repository that does not exist. One malformed entry is
dropped rather than taking the rest with it, and `default_local_model` is deliberately not
something a remote catalogue may change.

**No catalogue is published yet.** `remote.CATALOG_URL` points at where one would live in
the project's own public repository. Every installation currently takes the
"no catalogue, use the bundled list" path, which is the designed fallback and is exercised
by tests rather than by a server.

---

## 6. Containment, and the choice it makes visible

The one place Phase 11 nearly traded a safety property for a convenience.

| | |
|---|---|
| `discovery.load_paths()` | where Open Nest will **load** a model from. Its own contained store, plus anything explicitly adopted. Empty of anything else by default. |
| `discovery.discover_paths()` | where the **search** looks. Wider, read-only, and finding something here does not make it usable. |

Adopting an external model writes its cache into `installation.json`'s
`extra_model_paths`, after a dialog that shows the parent where the model is and says
Open Nest will start reading from that folder. Nothing is copied or moved. The default
installation has an empty list, which is the containment promise intact.

**Ollama is found, listed, and declined.** Open Nest runs MLX; Ollama keeps GGUF and
serves it through its own runtime, so bridging them means a second inference engine. They
are reported with the reason rather than hidden, because a family who knows they have
three Ollama models and is told "none found" will reasonably conclude the search is
broken. The same applies to a `faster-whisper` model in the standard Hugging Face cache —
a real model, in the right folder, in CTranslate2's format — which is the negative control
this was tested against on a real machine.

---

## 7. The setup wizard

Section 41 wants the step to begin by detecting the computer. Section 56 wants the page not
to become more technical as a result. So it answers the question a parent already has, in
one sentence, and folds the ladder away:

```
Open Nest suggests Qwen3 4B for this Mac.
Good for building, coding and everyday project help. About 2.3 GB to download.
[ Show other options ]  [ Already have a model? ]
```

The inspection is real work off the GUI thread — subprocesses for the hardware, every
approved cache searched — which is what entitles the page to the eagle. The progress bar
is indeterminate there on purpose: there is nothing to count, and a bar that invents a
percentage is the kind of small lie this project does not tell.

**The copy is Open Nest's voice, not Gary's, and the reason is better than the
convention.** At that moment in setup there is no model installed — Gary does not exist
yet. Having him warmly narrate the search for the model that will *become* him would be a
small lie about what is running. The Phase 10 split (installation, security, recovery and
failure are Open Nest) therefore holds unchanged.

**Setup never hard-stops.** No local model, no cloud: the Local AI step warns on the way
out, and the health check step names everything broken and asks "Finish anyway?". The
wizard's stance throughout is warn-never-refuse, and the parent decides.

---

## 8. What is not done

- **Only Qwen3 4B has ever been run.** The three larger entries are pinned, sized and
  described, and no inference has been run through any of them. Their memory figures are
  the derived rule, not measurements. Verifying one — Qwen3 8B is 4.62 GB — is the cheapest
  way to move the verified default up a rung, and it is a download decision rather than a
  code one.
- **No remote catalogue exists**, so the success path is tested and never exercised.
- **Provider discovery has never run against a real service.** The parsing, filtering and
  classification are tested against mocked payloads for both providers, per section 51.
  Nothing has called the real `/v1/models`.
- **Ollama and LM Studio paths were never seen.** Neither is installed on the machine this
  was written on, so those layouts come from documented conventions. The failure is
  bounded: a path that does not exist yields nothing, and an unrecognised directory is
  reported as unsupported rather than guessed at.
- **Section 37's "Custom Model ID" is not built.** The work order marks it optional ("may
  optionally permit") and it is not in the definition of done. Provider discovery already
  classifies an unknown-but-usable cloud model as `available`; what is missing is the
  parent-settings field to type one into.
- **Adopting an unrecognised MLX model is not possible**, only a catalogued one found in
  an unexpected place. Open Nest has no context budget, tool capability or memory figure
  for an arbitrary directory and would be guessing at all three. Section 32 asks for that
  caution. Making it selectable is a catalogue question, not a detection one.
- **Nobody has clicked any of this.** Five surfaces were rendered under real cocoa and
  looked at, which found the three defects in section 2. Tab order, focus, and whether the
  copy makes sense to an actual parent are unverified — as is the whole application, which
  is what Phase 12 is for.
- **The website preview has not been used for an hour.** One page was rendered at two
  widths and a blocked request was measured. Whether a child can actually get somewhere
  with it is a Phase 12 question.

---

## 9. Definition of done

| | |
|---|---|
| Build a Website is a first-class profile | done |
| A Website starter works | done, rendered at desktop and phone widths |
| The starter-kit abstraction is reusable | done — six kits, one manifest format |
| Existing project types have starter options | done |
| Starting empty remains possible | done, for every profile |
| Starter selection is deterministic | done — real files, never generated |
| Starter metadata reaches project context | done |
| Gary knows when a starter was used | done, and that the files are the child's |
| Gary behaves consistently regardless of provider | unchanged from Phase 10 |
| Machine capability detection is centralised | done — one function, one value |
| Local model compatibility is metadata-driven | done |
| A bundled catalogue exists | done |
| An updateable catalogue mechanism exists | done, unpublished |
| Cached/offline fallback works | done |
| Provider discovery can be incorporated | done, mocked only |
| A future model needs no UI source change | done, proven by test |
| Newly discovered models are not auto-trusted | done |
| Setup recommends based on the actual Mac | done |
| An installed Qwen is reused without downloading | done — and the bug that would have prevented it is fixed |
| No downloads without explicit action | done |
| Existing configurations migrate safely | done |
| Tests and ruff clean | 980 passing, ruff clean |
| Cocoa UI review of the new surfaces | done — five surfaces, three defects found and fixed |
| Documentation updated | this file, HANDOFF §4, SPIKES §19 |
| Nothing committed | nothing committed |
