# Measurements

Everything here was measured, not estimated. Sections 1-7 are the Phase 1 risk spikes
that the agent and execution layers were built on; sections 8 and 9 record what Phases 2
to 4 observed afterwards, including where a Phase 1 conclusion turned out not to transfer
and where the documented workflow turned out to be wrong.

**Measured on:** Apple silicon (arm64), macOS 15.7.9, 48 GB unified memory, mlx 0.32.2,
mlx-lm 0.31.3, Python 3.12.14.

**Caveat that applies throughout:** the development Mac has 48 GB. The product targets an
8 GB baseline. Absolute memory figures transfer; timings under memory pressure do not.
Re-measure on 8 GB hardware before V1.

---

## Outcome

| Decision | Resolved to |
|---|---|
| **D2** — default local model | `mlx-community/Qwen3-4B-Instruct-2507-4bit`, pinned to `50d4275` |
| **D3** — tool-call format | Native `<tool_call>` chat template, temperature 0, **four** tools, file state injected |

Both risks are retired. The agent design can proceed.

---

## 1. Development sandbox

Added before any third-party artifact was executed. Development is two-phase:

| Phase | Script | Network | Purpose |
|---|---|---|---|
| Fetch | `scripts/fetch.sh` | **on** | Pinned artifacts only, into the sandbox |
| Test | `scripts/offline.sh` | **off** | Everything downloaded runs here |

`scripts/offline.sh` uses macOS Seatbelt (`sandbox-exec`, no root) to deny all network and
confine writes to the project. Verified against a Python process, not just `curl`:

| Check | Unsandboxed | Sandboxed |
|---|---|---|
| Raw socket to 1.1.1.1:443 | connects | **blocked** |
| HTTPS to huggingface.co | connects | **blocked** |
| DNS resolution | resolves | **blocked** |
| Write to `~` | succeeds | **blocked** |
| Write inside sandbox | succeeds | succeeds |
| Read project source | succeeds | succeeds |

Containment is separate from isolation: `OPENNEST_HOME` relocates Open Nest's own state,
and the script additionally redirects `HF_HOME`, `PIP_CACHE_DIR`, `XDG_CACHE_HOME` and
`MPLCONFIGDIR`. Without that second part, "contained" would still have meant gigabytes of
model blobs in the machine-wide Hugging Face cache. Everything lives in
`.opennest-sandbox/` and `rm -rf` removes all of it.

`sandbox-exec` is marked deprecated by Apple but is present and functional. It is a
development control here — work order §19 will need its own boundary for running child
project code, and this is a working prototype of it.

## 2. Artifact pinning

`mlx-community` publishes community MLX *conversions*, not the original models, so there
are two trust hops. Every model in `models.json` now records an explicit commit SHA, the
upstream publisher, and the license; `test_local_models_are_pinned_to_a_commit` fails the
build if any is missing.

| Model | Size | Upstream | License |
|---|---|---|---|
| Qwen3-4B-Instruct-2507-4bit | 2.28 GB | `Qwen/Qwen3-4B-Instruct-2507` | **apache-2.0** |
| Qwen2.5-Coder-3B-Instruct-4bit | 1.75 GB | `Qwen/Qwen2.5-Coder-3B-Instruct` | other |
| Llama-3.2-3B-Instruct-4bit | 1.82 GB | `meta-llama/Llama-3.2-3B-Instruct` | llama3.2 |
| gemma-2-2b-it-4bit | 1.49 GB | `google/gemma-2-2b-it` | gemma |

Only the Qwen3 build was downloaded. The Apache-2.0 license was a deciding factor
alongside the benchmark: it is the cleanest licensing surface of the candidates, which
matters for a product intended for distribution.

## 3. Local model performance

`mlx-community/Qwen3-4B-Instruct-2507-4bit`, measured offline:

| Metric | Value |
|---|---|
| Load time from local snapshot | **0.3 s** |
| Resident memory after load | **2.61 GB** |
| MLX peak memory during generation | 2.44 GB |
| Prompt throughput | 39.6 tok/s |
| Generation throughput | **92.5 tok/s** |

Load time is negligible because weights are memory-mapped, which makes an unload-on-idle
policy cheap — reloading costs a third of a second.

### Offline defect found

`mlx_lm.load("<repo-id>")` contacts the Hub even when the snapshot is fully cached, and
raises under `HF_HUB_OFFLINE`. Left unaddressed this would break work order §34 outright:
Open Nest would need internet to use a local model.

**The provider must resolve the snapshot to a local path first** via
`snapshot_download(..., local_files_only=True)` and pass the directory to `mlx_lm.load()`.
Phase 2 must implement it this way, and a test should run with `HF_HUB_OFFLINE=1`.

### 8 GB baseline

| Component | Resident |
|---|---|
| Model loaded | 2.61 GB |
| PySide6 application | 0.08 GB |
| Pygame child process | 0.05 GB |
| **Total** | **≈ 2.74 GB** |

Comfortable on 8 GB. The PySide6 figure is the empty Phase 0 window; a populated Workbench
will be higher, but the model dominates and there is real headroom. Two practices should
still be kept: run projects out of process, and unload the model on idle.

## 4. Tool-calling reliability — the main risk

20 realistic child requests, temperature 0, scored on whether the model selected the
correct single tool.

| Condition | Parseable | Correct |
|---|---|---|
| A — 5 tools, no system prompt | 18/20 | 10/20 (50%) |
| B — 5 tools, + one-tool nudge | 19/20 | 16/20 (80%) |
| C — 3 tools, no nudge | 10/12 | 10/12 (83%) |

Two independent effects: **tool-set size degrades selection**, and a four-line system
prompt recovers 30 points.

The dominant failure was not malformed output — syntax was near-perfect throughout — but
an "explore first" bias, where the model reached for `list_project_files` instead of
acting. That suggested removing the tool entirely and injecting the file list, which work
order §15A already argues for: deterministic facts should be populated programmatically
rather than asked of the model.

Re-run on the 16 cases that never require listing:

| Condition | Parseable | Correct |
|---|---|---|
| B — 5 tools incl. `list`, + nudge | 15/16 | 12/16 (75%) |
| D — 4 tools, `list` removed, + nudge | 15/16 | 15/16 (94%) |
| **E — 4 tools, `list` removed, nudge + file state** | **16/16** | **16/16 (100%)** |

### What Phase 2 should do

1. **Do not expose `list_project_files` as a tool.** Inject the current file list into
   context. This removed the single largest failure mode and saves a round-trip.
2. **Keep the active tool set small** — four or fewer per turn. Gate rarely-used tools
   behind context rather than offering everything always.
3. **Use the native `<tool_call>` chat template**, not prompt-instructed bare JSON.
4. **Temperature 0 for tool-selection turns.**
5. **Include the one-tool nudge** in the base system prompt.
6. **Normalise tool names before dispatch** — `run_project()` and `functions.run_project`
   both occur and are the right answer, awkwardly spelled. Rejecting them would have
   looked like a 55% hallucination rate that did not exist.

**Do not read 100% as "solved".** It is 16 single-turn cases on one model at temperature 0.
It shows the configuration is sound, not that the agent is reliable. Multi-turn behaviour,
argument correctness, and recovery from a bad call are all still unmeasured — Phase 2 needs
its own harness, and this one should be promoted out of `spikes/` when it does.

## 5. Project execution

Out-of-process execution against a fixture that prints, crashes, and hangs on demand:

| Check | Result |
|---|---|
| Clean run exits 0 | pass |
| stdout captured | pass |
| stderr captured separately from stdout | pass |
| Crash gives non-zero exit | pass |
| Traceback available for the repair loop | pass |
| Partial stdout kept on crash | pass |
| Hung process terminated | pass |
| Timeout respected | pass |
| Output kept from hung process | pass |
| No orphan processes left behind | pass |

Escalating `SIGTERM` to `SIGKILL` across a new session group is what makes termination
reliable; without `start_new_session=True` a hung child can survive its parent.

## 6. macOS Keychain

Native `keyring.backends.macOS.Keyring`. Round-trip, overwrite, 259-character value,
delete, absent-key returning `None`, and `PasswordDeleteError` on deleting an absent key
all behave correctly, with no interactive prompt for the app's own items.

---

## 7. The sandbox earned its keep immediately

Running the existing test suite *inside* the sandbox failed five tests that passed
outside it. Both causes were real bugs in the tests, not sandbox artifacts:

- `test_compiles_under_oldest_supported_python` shelled out to `py_compile`, and Apple's
  system Python 3.9 writes bytecode to `~/Library/Caches/com.apple.python/` — outside the
  project. Now compiles in memory instead, which is all the test ever needed.
- `test_internal_state_stays_out_of_the_repository` asserted an invariant that contained
  mode deliberately inverts. Replaced by two mode-aware tests: installed mode writes
  nothing into the repository, and contained mode keeps everything under one root.

The suite now passes 35/35 in both modes, which is the property worth having: the same
tests hold whether Open Nest is contained or installed normally.

### Known gap — residual runtime outside containment

`.opennest-sandbox/` holds 2.2 GB and the machine-wide Hugging Face cache was not touched.
But 73 MB of vendored CPython 3.12.14 still sits at
`~/Library/Application Support/Open Nest/python/`, installed during Phase 0 before
containment existed. It cannot simply be deleted: `.venv/bin/python3` symlinks into it.

Moving it inside the sandbox means re-running setup with `OPENNEST_HOME` set and
rebuilding the virtual environment — the code already supports this, since
`bootstrap.environment.runtime_dir()` honours the containment root. Left as a deliberate
choice rather than an unprompted rebuild.

---

## 8. Later measurements (Phases 2 and 3)

Recorded here so the measurement record stays in one place.

**Whole-file writes fail on this model.** Asked to reproduce a whole file inside a JSON
string, it emits Python triple-quotes (`"content": """...`) and the call never parses.
Against five change requests:

| Tool set | Parseable | Correct target |
|---|---|---|
| `write_file` (whole file) | 5/5 | 4/5 |
| `edit_file` (targeted) | 5/5 | **5/5** |
| both offered | 4/5 | 4/5 |

Offering both is worse than either alone — the same tool-count effect as section 4.
`write_file` now refuses to overwrite, and both write paths reject invalid Python before
saving.

**The single-turn nudge was wrong for multi-turn.** The "call exactly one tool"
instruction from section 4 caused the model to read a file and then *claim* an edit it
never made. Rewritten to keep the "do not explore" property without the stop-after-one
instruction, plus a deterministic check for a claimed change with no write.

**Full slice, real model, offline:** 5/6 varied change requests applied correctly, output
still valid Python, ~7 s per turn.

**Phase 3, with real processes rather than simulations:**

- DoD 31 — model changed `PLAYER_SPEED` 5 → 8, undo restored the file byte-for-byte, undo
  again brought the change back.
- Crash recovery — a project opened in a separate process, edited, then SIGKILLed. On
  reopen the interrupted session was detected and both the unsaved edit and a newly
  created file were preserved as their own checkpoint.

## 9. Phase 4 — Seatbelt does not nest

Not a spike; a defect in the documented workflow, found by following it.

`HANDOFF.md` §2 said to run the test suite through `scripts/offline.sh`. Ten tests failed
that way when this was found — all of them tests that start a child project, twelve of
them now:

```text
sandbox-exec: sandbox_apply: Operation not permitted
```

`scripts/offline.sh` is itself a Seatbelt sandbox, and a Seatbelt profile cannot be
applied inside another one. Verified directly, independent of this project:

| Command | Result |
|---|---|
| `sandbox-exec -p '(version 1)(allow default)' true` | succeeds |
| the same, nested one level deeper | **`sandbox_apply: Operation not permitted`** |

Nothing was wrong with the sandbox. `run_project` fails closed when it cannot confine a
project, which is correct, and the instruction was asking it to do so ten times.

Two consequences, both now in place:

- The suite runs **unwrapped**. It is hermetic — temporary directories, no network, no
  model — so it never needed the sandbox. `scripts/offline.sh` keeps the job it exists
  for: anything that loads the downloaded model or could reach the network.
- `process_sandbox.sandbox_available()` now **probes** the capability by applying a
  trivial profile once and caching the answer, instead of checking that
  `/usr/bin/sandbox-exec` exists. A file-existence test reports a capability the process
  may not have. Deliberately an attempt rather than an environment variable: this decides
  whether a model's generated code runs at all, and anything the process can assert about
  itself is the wrong input to that decision. A wrapped run is now 233 passed, 16 skipped
  rather than 10 failed.

### Still unmeasured after Phase 4

Thread rollover sends the conversation's prose back through the model a second time to
write the handoff, and closing a project does the same. Section 3 measured prompt
throughput at **39.6 tok/s**, but on a short prompt — if that figure holds at a few
thousand tokens, a rollover is a visible pause after a turn rather than the invisible
event §15A requires. The transcript excludes the system prompt and all tool traffic, and
generation is capped at 400 tokens, so the real cost is probably much lower. It has not
been measured. Do that before Phase 10; if it is bad, move the handoff onto the worker
thread instead of running it inline.

Note that this is a single number governing both paths. Quitting was briefly special-cased
to skip the model call, on the assumption the pause would be intolerable — but the
transcript left at close is bounded by the same rollover threshold, so both stand or fall
together. Measure once.

**The recall cue list is unmeasured.** `history_search.CUES` decides when the application
searches memory on the child's behalf. It was written by inspection and deliberately not
tuned further, because tuning a heuristic by intuition is what this document exists to
discourage. The failure mode is soft: a missed cue means the model answers from the bible,
which is in the prompt regardless. Worth a pass of real child phrasings.

Memory *quality* is also unmeasured. `tests/test_rollover.py` proves the application
rolls over correctly with a scripted provider; whether a 4B model writes a handoff worth
keeping is the separate question, and the Phase 2 pattern applies — measure it against
the real model, on its own.

---

## Follow-ups for later phases

- **Phase 2:** resolve models to a local path before loading; add an `HF_HUB_OFFLINE=1`
  test; build the multi-turn tool harness; normalise tool names.
- **Phase 2:** port `scripts/offline.sh` into `opennest/security/sandbox.py` as the
  boundary for running child project code (work order §19).
- **Phase 8:** installer must verify a model by real inference through the provider, which
  means it needs the local-path resolution too.
- **Before Phase 10:** measure rollover latency with the real model (section 9), and check
  handoff quality separately from handoff wiring.
- **Re-measure on 8 GB hardware** before V1.
- Remaining models stay unverified until something actually needs them.
