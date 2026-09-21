"""Installing a local model, with the six behaviours WORKORDER_01 section 35A asks for.

Display progress, show expected disk usage, support cancellation, support resume, detect
an already downloaded model, and avoid downloading duplicates. None of them were
possible against ``scripts/fetch.sh``, which runs a bare ``snapshot_download`` with
progress bars switched off.

Three measurements shape this (SPIKES.md section 15), none guessable from the
huggingface_hub documentation:

**The default storage backend cannot be cancelled.** huggingface_hub 1.32 defaults to
Xet, and an exception raised from ``tqdm_class`` is swallowed inside its progress
reporting: a cancel firing at 127 MB still let the whole 1,598 MB model download. With
``HF_HUB_DISABLE_XET=1`` the classic HTTP backend stops at 54 MB against a 50 MB
threshold, in 3.1 s. So this module sets that variable and drives one backend. Which
backend a download used, and how it laid bytes out, is not something the rest of Open
Nest is told about.

**Cancellation runs the download in a subprocess anyway.** Killing a process is a
guarantee; an exception raised on a library's worker thread is a hope. The child reports
byte counts on stdout, which is also what makes a progress bar possible without this
module knowing anything about Qt.

**Resume does not work, so it is not offered.** Measured three times over: each
``snapshot_download`` writes a partial file with a *fresh random suffix*, re-transfers
from the beginning, and orphans the previous one. Three cancelled runs left three dead
partials totalling 102 MB. So a cancelled download discards its partial rather than
pretending it is a head start, and the message a parent sees says the next attempt
starts over. What genuinely is reused is a **complete** model: :func:`is_installed`
resolves the pinned revision offline, and a download that finds one does not run at all.

**A returned snapshot path proves nothing about the model.** A model is only *ready*
once :func:`verify` has run a real inference through the provider the application
itself uses -- section 35A's "Do not create a separate installer-only inference
implementation".
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from opennest import paths
from opennest.ai import router
from opennest.ai.provider import Message, ProviderError, Settings

#: What the verification step asks the model to say (section 35A, "Model verification").
#: Nothing checks the answer against this -- see :func:`verify` for why. It is worth
#: asking for something specific anyway: a model that echoes it is easy to eyeball, and
#: Qwen3 4B does reply with exactly these words.
VERIFICATION_PROMPT = "Respond with exactly: OPEN NEST READY"

#: Generous. The point is to prove inference completes, not to measure how fast.
VERIFICATION_MAX_TOKENS = 32

#: How often a download checks whether Cancel was pressed. Short enough that the button
#: feels immediate, long enough that the loop is not a spin.
CANCEL_POLL_SECONDS = 0.2

#: Runs in the managed environment as a child process. Keeps no application imports so
#: it starts fast, and reports on stdout so the parent can drive a progress bar.
_CHILD = r'''
import json, os, sys, time
from huggingface_hub import snapshot_download
from huggingface_hub.utils import tqdm as hf_tqdm

class Reporting(hf_tqdm):
    """Totals bytes across the snapshot's files, without counting any of them twice.

    Measured rather than assumed, because two things about huggingface_hub's bars are
    not what you would guess:

    - **The same bar is updated twice for the same bytes.** A bar with total 2515 gets
      update(1570) twice. Summing the update() arguments therefore overshoots -- a
      2.28 GB model reported 4.2 GB. So this reads each bar's own cumulative ``n``
      after tqdm has applied the update, clamped to that bar's total, and sums across
      bars. A double update cannot inflate a clamped per-bar figure.
    - **``unit`` is not set on these bars**, so "count only the byte bars" cannot be
      written that way. snapshot_download runs a "Fetching N files" counter whose
      total is a file count, and adding 9 to a byte total is nonsense. Bars are
      therefore selected by size: a real weights file is megabytes, a file counter is
      single digits. Tiny config files fall below the line too and are not counted,
      which costs a few kilobytes against several gigabytes -- far below the 0.1 GB
      the display rounds to.

    The bar object is the dict key, not ``id(self)``: an id can be reused after a bar
    is collected, and the total would then go backwards.
    """
    #: bar -> bytes that bar has confirmed. Class state, since there is one per file.
    bars = {}
    last = 0.0

    #: Below this a bar is metadata or a file counter, not a download worth showing.
    FLOOR = 1_000_000

    def update(self, n=1):
        total = self.total or 0
        if total >= Reporting.FLOOR:
            # Accumulated here rather than read from ``self.n``: progress bars are
            # switched off for this child, and a disabled tqdm returns from update()
            # *before* incrementing its own counter, so self.n stays 0 forever.
            # Clamping per bar is what stops a repeated update inflating the total.
            Reporting.bars[self] = min(Reporting.bars.get(self, 0) + (n or 0), total)
            now = time.time()
            if now - Reporting.last > 0.2:
                Reporting.last = now
                sys.stdout.write(
                    json.dumps({"bytes": sum(Reporting.bars.values())}) + "\n")
                sys.stdout.flush()
        return super().update(n)

try:
    path = snapshot_download(sys.argv[1], revision=sys.argv[2] or None,
                             cache_dir=sys.argv[3], tqdm_class=Reporting,
                             max_workers=4)
except BaseException as exc:
    sys.stdout.write(json.dumps(
        {"done": False, "error": "%s: %s" % (type(exc).__name__, exc)}) + "\n")
else:
    # Reporting the success is outside the try on purpose. It used to be inside, and
    # a stale reference in this line raised AttributeError *after* a 2.3 GB download
    # had completed -- which the except caught and dressed up as "could not be
    # downloaded", for a model that was sitting on disk and worked. A fault in saying
    # so must not be reported as a fault in the thing itself.
    sys.stdout.write(json.dumps(
        {"done": True, "path": path, "bytes": sum(Reporting.bars.values())}) + "\n")
sys.stdout.flush()
'''


@dataclass(frozen=True)
class Progress:
    """One progress report, in the terms section 35A's example displays them."""

    downloaded_bytes: int
    total_bytes: int

    @property
    def fraction(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(1.0, self.downloaded_bytes / self.total_bytes)

    @property
    def percent(self) -> int:
        return int(self.fraction * 100)

    def describe(self) -> str:
        """"3.1 GB of 4.0 GB", the line under the bar in section 35A's example."""
        if self.total_bytes <= 0:
            return f"{_gb(self.downloaded_bytes)} so far"
        return f"{_gb(self.downloaded_bytes)} of {_gb(self.total_bytes)}"


@dataclass(frozen=True)
class DownloadResult:
    ok: bool
    #: ``completed`` | ``cancelled`` | ``failed`` | ``already-installed``
    outcome: str
    message: str = ""
    path: Path | None = None


@dataclass(frozen=True)
class VerificationResult:
    """Section 35A's "Model verification" checklist, as separately reportable facts."""

    engine_loaded: bool = False
    model_loaded: bool = False
    inference_completed: bool = False
    reply: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.engine_loaded and self.model_loaded and self.inference_completed

    def lines(self) -> tuple[str, ...]:
        """The three ticks section 35A shows under the model name."""
        return (
            _tick(self.engine_loaded, "Installed"),
            _tick(self.model_loaded, "Loaded successfully"),
            _tick(self.inference_completed, "Test response received"),
        )


# --------------------------------------------------------------------- what is installed

def is_installed(entry: router.ModelEntry) -> bool:
    """Whether this model is available and valid: on disk, pinned revision, no network.

    The one question the installer asks about the cache. How huggingface_hub lays those
    bytes out -- per-repo folders, symlinks, a shared content-addressed blob store -- is
    its business, and deliberately not modelled here. ``resolve_local_model`` is the
    same call the application makes when it loads a model, so a True here means the
    thing the app will actually do would succeed.
    """
    if not entry.model_id:
        return False
    from opennest.ai.mlx_provider import resolve_local_model

    try:
        resolve_local_model(entry.model_id, entry.revision)
    except ProviderError:
        return False
    return True


def expected_bytes(entry: router.ModelEntry) -> int:
    """The download size, from the catalogue.

    Section 35A: "download sizes should come from the model configuration file rather
    than being hard-coded into wizard logic". ``dry_run`` was tried as a live source and
    reports nothing usable (SPIKES.md section 15).
    """
    return int((entry.download_gb or 0) * 1_000_000_000)


# --------------------------------------------------------------------- downloading

def download(
    entry: router.ModelEntry,
    *,
    on_progress: Callable[[Progress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    store: Path | None = None,
    python_executable: str | None = None,
) -> DownloadResult:
    """Install one model, reporting progress and stopping when asked.

    A model that is already complete is not downloaded again -- that is the reuse the
    installer actually gets, and it is checked before anything starts. A *partial*
    download cannot be continued (SPIKES.md section 15B), so cancelling discards it.
    """
    if not entry.model_id:
        return DownloadResult(False, "failed", f"{entry.info.name} has no model configured.")
    if is_installed(entry):
        # Section 35A: "avoid downloading duplicate copies unnecessarily".
        return DownloadResult(True, "already-installed", f"{entry.info.name} is already installed.")

    target = Path(store) if store is not None else paths.models_dir()
    target.mkdir(parents=True, exist_ok=True)

    environment = dict(os.environ)
    # The measured reason this module exists. See the module docstring.
    environment["HF_HUB_DISABLE_XET"] = "1"
    environment["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

    announced = expected_bytes(entry)
    child = subprocess.Popen(
        [
            python_executable or sys.executable, "-c", _CHILD,
            entry.model_id, entry.revision or "", str(target),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        text=True,
    )

    # Read on a thread rather than iterating child.stdout here. A stalled transfer
    # produces no lines, and a blocking readline would sit there ignoring Cancel for as
    # long as the network took to give up -- which fails the one thing Cancel promises.
    # Polling a queue means cancellation is noticed within CANCEL_POLL_SECONDS whether
    # bytes are arriving or not.
    lines: queue.Queue = queue.Queue()
    reader = threading.Thread(target=_pump, args=(child, lines), daemon=True)
    reader.start()

    result = DownloadResult(False, "failed", "The download stopped unexpectedly.")
    try:
        while True:
            if should_cancel is not None and should_cancel():
                return _cancel(child, entry, target)
            try:
                line = lines.get(timeout=CANCEL_POLL_SECONDS)
            except queue.Empty:
                # Deliberately no "the child has exited, so stop" shortcut here.
                # ``_pump`` always puts a sentinel when the stream closes, so waiting
                # for it is both sufficient and correct, and an early break can lose
                # the race against the last line the child wrote.
                continue
            if line is None:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "done" in message:
                result = _finish(message, entry)
                break
            if on_progress is not None:
                # The denominator is the catalogue's, which section 35A makes the
                # source of truth for a download size, and the numerator is clamped to
                # it. The child's byte count is a sum over huggingface_hub's own
                # progress bars and can overshoot -- the acceptance pass watched a
                # 2.28 GB model report "4.2 GB of 4.2 GB", because an earlier version
                # let the stated total chase the count upward. A bar that overstates
                # what it is downloading is exactly the kind of small lie this project
                # does not tell.
                seen = int(message.get("bytes", 0))
                on_progress(Progress(min(seen, announced) if announced else seen, announced))
    finally:
        _stop(child)
    return result


def _pump(child: subprocess.Popen, sink: queue.Queue) -> None:
    """Move the child's lines into a queue so the caller never blocks on a read."""
    try:
        for line in child.stdout:
            sink.put(line)
    except (OSError, ValueError):
        pass
    finally:
        sink.put(None)


def _stop(child: subprocess.Popen) -> None:
    """Make sure nothing keeps downloading after this function returns.

    The requirement is that cancelling stops the UI waiting *and* leaves no transfer
    running unnoticed, so this is unconditional rather than best-effort.
    """
    if child.poll() is None:
        child.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        child.wait(timeout=30)
    if child.stdout is not None:
        with contextlib.suppress(OSError):
            child.stdout.close()


def _cancel(child: subprocess.Popen, entry: router.ModelEntry, store: Path) -> DownloadResult:
    _stop(child)
    discarded = _discard_partial_files(entry, store)
    message = f"The download of {entry.info.name} was cancelled."
    if discarded:
        message += " The part that had downloaded was removed, so starting again begins " \
                   "from the beginning."
    return DownloadResult(False, "cancelled", message)


def _discard_partial_files(entry: router.ModelEntry, store: Path) -> int:
    """Delete this model's abandoned ``.incomplete`` files. Returns bytes removed.

    Measured (SPIKES.md section 15B): huggingface_hub 1.32 does **not** resume across
    processes. Each run writes a partial with a fresh random suffix, re-transfers from
    the start, and leaves the previous one behind -- three cancelled runs left three
    orphans totalling 102 MB, none of which any later download will ever read.

    So a cancelled download's bytes are not a head start being saved, they are litter.
    Nothing else removes them, and a parent who cancels twice should not silently lose
    disk. Only ``.incomplete`` files under *this* repository are touched; a completed
    model is never at risk.
    """
    if not entry.model_id:
        return 0
    folder = Path(store) / ("models--" + entry.model_id.replace("/", "--"))
    if not folder.is_dir():
        return 0
    removed = 0
    for partial in folder.rglob("*.incomplete"):
        try:
            size = partial.stat().st_size
            partial.unlink()
        except OSError:
            continue
        removed += size
    return removed


def _finish(message: dict, entry: router.ModelEntry) -> DownloadResult:
    if message.get("done"):
        return DownloadResult(
            True, "completed", f"{entry.info.name} was installed.",
            path=Path(message["path"]) if message.get("path") else None,
        )
    return DownloadResult(
        False, "failed",
        f"{entry.info.name} could not be downloaded.\n\n{message.get('error', '')}".strip(),
    )


# --------------------------------------------------------------------- verifying

def verify(
    entry: router.ModelEntry,
    *,
    provider=None,
    timeout_seconds: float = 300.0,
) -> VerificationResult:
    """Run one real inference through the application's own provider (section 35A).

    Reports each stage separately because the three ticks in the work order's example
    are three different failures: MLX missing is a broken environment, a model that will
    not load is a bad download, and inference that never completes is neither.
    """
    if provider is None:
        try:
            provider = router.build_provider(entry.info.id)
        except ProviderError as exc:
            return VerificationResult(message=str(exc))

    try:
        provider.load()
    except ProviderError as exc:
        # "The local AI engine is not installed" is MLX itself; anything else is the
        # model. The distinction is what makes the message actionable.
        engine_missing = "engine" in str(exc).lower()
        return VerificationResult(
            engine_loaded=not engine_missing,
            message=str(exc),
        )
    except Exception as exc:
        return VerificationResult(message=f"The model could not be loaded.\n\n{exc}")

    outcome: dict = {}

    def run() -> None:
        try:
            for _ in provider.chat(
                [Message(role="user", content=VERIFICATION_PROMPT)],
                settings=Settings(temperature=0.0, max_tokens=VERIFICATION_MAX_TOKENS),
            ):
                pass
            outcome["reply"] = provider.finish().text
        except Exception as exc:  # noqa: BLE001 - reported, never raised at a parent
            outcome["error"] = f"{type(exc).__name__}: {exc}"

    # A model that hangs must not hang the wizard. The thread is left to finish on its
    # own if it ever does -- it holds no lock the wizard needs.
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout_seconds)

    if worker.is_alive():
        return VerificationResult(
            engine_loaded=True, model_loaded=True,
            message=f"{entry.info.name} did not answer within "
                    f"{int(timeout_seconds)} seconds.",
        )
    if "error" in outcome:
        return VerificationResult(
            engine_loaded=True, model_loaded=True,
            message=f"{entry.info.name} could not answer.\n\n{outcome['error']}",
        )

    # Deliberately not an exact match against what the prompt asked for. Section 35A's
    # checklist is about the machinery -- MLX loads, the model loads, the tokenizer
    # loads, inference completes -- and a 4B model that answers "Sure! OPEN NEST READY"
    # has proved every one of them. Requiring the exact string would fail setup on a
    # model that works, which is the worse error of the two.
    reply = (outcome.get("reply") or "").strip()
    if not reply:
        # Section 35A wants inference to *complete*, and silence is not completion --
        # SPIKES.md section 13 has a real case of a model spending its whole budget
        # before saying anything.
        return VerificationResult(
            engine_loaded=True, model_loaded=True,
            message=f"{entry.info.name} loaded but answered with nothing.",
        )
    return VerificationResult(
        engine_loaded=True, model_loaded=True, inference_completed=True, reply=reply,
    )


# --------------------------------------------------------------------- internals

def _gb(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f} GB"
    return f"{value / 1_000_000:.0f} MB"


def _tick(done: bool, label: str) -> str:
    return f"{'✓' if done else '○'} {label}"
