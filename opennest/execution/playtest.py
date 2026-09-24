"""Does the game do anything? A headless test of an interactive project, after a change.

Phase 12.3 measured the gap this closes (SPIKES.md section 23H). ``RunResult.ok`` is True
whenever an interactive game survives its four-second startup, so a game that crashes
gets three repair attempts and a game that opens onto a frozen picture gets none -- and
Gary is left describing an asteroid that is not there. Of twenty-four real conversations
only one produced the game that was asked for.

So after a turn changes a game, the application runs it once more, **without a window**,
and watches. :mod:`opennest.execution.playtest_harness` runs inside the child's process
and records; this module runs it and decides. Deterministic throughout: no model is
asked anything, nothing about what the game *should* be is guessed, and a result is
either something that was measured or no result at all.

WHAT COUNTS AS FAILING
----------------------
Only what is broken whatever the child asked for. Each of these was checked against ten
working games written in the idioms a first game uses, and none of the ten trips any of
them (SPIKES.md section 24):

- ``crashed``: it raised, at any point -- on the first frame, or when a key was pressed.
- ``no_picture``: it opened a window and never drew into it.
- ``closed_itself``: it ended on its own before it had drawn more than a frame or two.
- ``frozen``: every frame was the same picture, left alone *and* through every key and
  click the test gives it.

And deliberately **not** failing, because telling them apart needs to know what the
child meant, which this does not pretend to:

- A game that only moves when a key is pressed. The shipped starter is exactly that.
- A change that made no visible difference. Measured on the corpus, it would catch real
  faults -- and it would also fire on every window title, quit key, sound, and anything
  set to happen after a few seconds.

The run goes through :func:`opennest.execution.python_runner.run_project`, so it is
confined by the same process sandbox as every other run, and it never has the network:
a test must not be something that can ask a parent a question.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from opennest.execution.python_runner import RunResult, run_project

HARNESS = Path(__file__).with_name("playtest_harness.py")

#: Where the harness writes what it saw. Inside the project, because that is where the
#: sandbox lets a run write, and under ``.opennest/tmp`` because that is git-ignored and
#: hidden from the file list the model is shown.
RECORD = ".opennest/tmp/playtest.jsonl"

#: The harness ends every run itself within ten seconds. This is only the backstop.
TIMEOUT_SECONDS = 20

#: The first frames often come from before the game loop -- a flip straight after
#: ``set_mode`` -- so they are not evidence that anything moves.
WARMUP_FRAMES = 2

#: Traceback shown to the model is capped the way the last run's error already is.
MAX_ERROR_CHARS = 3000

PASSED = "passed"
CRASHED = "crashed"
NO_PICTURE = "no_picture"
CLOSED_ITSELF = "closed_itself"
FROZEN = "frozen"
#: Not failures, and not passes either: nothing the test can stand behind.
NO_WINDOW = "no_window"
INCONCLUSIVE = "inconclusive"
UNAVAILABLE = "unavailable"

FAILURES = frozenset({CRASHED, NO_PICTURE, CLOSED_ITSELF, FROZEN})

#: What the test pressed, in the words the model is told.
INPUTS_TRIED = (
    "the arrow keys, W A S D, space, enter, a number, some letters, "
    "and clicked and moved the mouse"
)


@dataclass(frozen=True)
class Playtest:
    """What one headless run of the game showed."""

    verdict: str
    #: The file that was run, relative to the project, as the model knows it.
    entry: str = ""
    frames: int = 0
    seconds: float = 0.0
    #: Which input was being given when the run ended, or "idle" before any.
    during: str = ""
    #: The traceback, trimmed to the child's own code. Only for ``crashed``.
    error: str = ""
    #: Diagnostics, never a verdict: whether anything moved with nobody touching it,
    #: and which inputs changed the picture.
    moved_by_itself: bool = False
    responded_to: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return self.verdict in FAILURES

    def feedback(self) -> str:
        """What the model is told when the game failed, so it can repair it.

        Every sentence is something the run measured. It says what was tried and what
        was seen, and it does not name a cause the run did not observe -- the Phase 12.1
        rule for the copy that exists to stop invention.
        """
        tried = (
            f"Open Nest tested {self.entry} without opening a window. It left the game "
            f"alone for a moment, then pressed {INPUTS_TRIED}."
        )
        if self.verdict == CRASHED:
            when = (
                "before it drew anything" if self.frames == 0
                else f"after {self.frames} frames, while it was pressing {self.during}"
                if self.during not in ("", "idle")
                else f"after {self.frames} frames, before anything was pressed"
            )
            what = f"It stopped with an error {when}:\n\n{self.error}"
        elif self.verdict == NO_PICTURE:
            what = (
                "It opened a window and never showed a picture: nothing called "
                "pygame.display.flip() or pygame.display.update() within 4 seconds."
            )
        elif self.verdict == CLOSED_ITSELF:
            what = (
                f"It ended by itself after drawing {self.frames} frame"
                f"{'' if self.frames == 1 else 's'}, before anyone pressed anything, so "
                f"the window would close as soon as it opened."
            )
        elif self.verdict == FROZEN:
            what = (
                f"It drew {self.frames} frames and every one was exactly the same picture. "
                f"Nothing moved by itself, and nothing on screen changed when any key was "
                f"pressed or the mouse was clicked."
            )
        else:
            return ""
        return (
            f"{tried}\n\n{what}\n\n"
            f"Change the code to fix that. You do not need to run it: Open Nest will "
            f"test it again after your change."
        )

    def reminder(self) -> str:
        """What the model is told when it answered the feedback without changing a file.

        Measured, and it is the Phase 12.1 fault in a new place: handed the exact
        traceback, the model replied *"I added the import for random at the top of the
        file."* and called no tool at all. Nothing is fixed and the code is identical, so
        there is nothing to test again -- but pulled up, this model does act.
        """
        still = {
            CRASHED: "stops with the error above",
            NO_PICTURE: "never shows a picture",
            CLOSED_ITSELF: "closes by itself straight away",
            FROZEN: "shows exactly the same picture on every frame",
        }.get(self.verdict)
        if still is None:
            return ""
        return (
            f"You did not change any file, so nothing is fixed yet: the game still "
            f"{still}. Call edit_file now to make the fix. Open Nest will test it again "
            f"after your change."
        )


def run(
    project_dir: Path,
    command: Sequence[str],
    *,
    python_executable: str | None = None,
) -> Playtest:
    """Run the game headless under the harness and say what it did.

    ``command`` is the profile's own run command -- ``("python", "src/game.py")`` -- so
    the test runs exactly the file the Run button would.
    """
    entry = command[-1]
    try:
        project_dir = Path(project_dir).resolve(strict=True)
        record = project_dir / RECORD
        record.parent.mkdir(parents=True, exist_ok=True)
        record.unlink(missing_ok=True)
        try:
            result = run_project(
                project_dir,
                ("python", str(HARNESS), *command[1:]),
                timeout=TIMEOUT_SECONDS,
                python_executable=python_executable,
                extra_env={
                    "SDL_VIDEODRIVER": "dummy",
                    "SDL_AUDIODRIVER": "dummy",
                    "OPENNEST_PLAYTEST_RECORD": str(record),
                },
            )
            records = _read(record)
        finally:
            record.unlink(missing_ok=True)
    except OSError:
        # A test that could not be set up says nothing about the game, and must never
        # be the thing that breaks the child's turn.
        return Playtest(UNAVAILABLE, entry=entry)
    return classify(records, result, entry=entry)


def _read(record: Path) -> list[dict]:
    if not record.is_file():
        return []
    records = []
    for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue   # a line cut short by a kill; everything before it still counts
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def classify(records: list[dict], result: RunResult, *, entry: str = "") -> Playtest:
    """Decide what a run showed, from the harness's record and how the process ended.

    Pure, so every rule here is tested without starting a game.
    """
    frames = [r for r in records if "frame" in r]
    hashes = [str(r.get("hash", "")) for r in frames]
    end = next((r for r in reversed(records) if "end" in r), {})
    reason = end.get("end", "")
    during = str(end.get("during", ""))
    base = {"entry": entry, "frames": len(frames), "seconds": round(result.seconds, 2),
            "during": during}

    # Never reached the game: the sandbox could not be applied, pygame is not installed,
    # or the harness itself failed. The harness writes an end record however the game
    # finishes -- a crash on the first line included -- so no record at all means the
    # game never ran, and a traceback here would be the harness's, not the child's.
    if reason == "no_pygame" or not records:
        return Playtest(UNAVAILABLE, **base)

    error = game_traceback(result.stderr)
    signalled = result.exit_code is not None and result.exit_code < 0 and not result.timed_out
    if (error and result.exit_code not in (0, None)) or signalled:
        return Playtest(CRASHED, error=error or "The game stopped suddenly.", **base)

    if not any("window" in r for r in records):
        # Not a pygame window at all. Whatever it is, this test cannot see it.
        return Playtest(NO_WINDOW, **base)

    ended_itself = reason in ("exit", "returned")
    if ended_itself and len(frames) <= WARMUP_FRAMES:
        return Playtest(CLOSED_ITSELF, **base)
    if not frames:
        return Playtest(NO_PICTURE, **base)

    # The warm-up frames are discounted as evidence of *movement*, never of response: a
    # game that redraws only when a key arrives draws three frames in the whole test,
    # every one different, and discarding the first two of those graded it frozen.
    steady = hashes[WARMUP_FRAMES:] or hashes
    idle = [h for r, h in zip(frames, hashes) if r.get("input") == "idle"][WARMUP_FRAMES:]
    responded_to = _responses(frames)
    diagnostics = {"moved_by_itself": len(set(idle)) > 1, "responded_to": responded_to}
    if len(set(steady)) > 1 or responded_to:
        return Playtest(PASSED, **base, **diagnostics)
    if ended_itself:
        # Still until it ended, and it ended itself after input began -- a game that
        # quits on one of the keys, perhaps. Not something to repair on.
        return Playtest(INCONCLUSIVE, **base, **diagnostics)
    return Playtest(FROZEN, **base, **diagnostics)


def _responses(frames: list[dict]) -> tuple[str, ...]:
    """Inputs during which the picture changed from the frame before."""
    seen: list[str] = []
    for previous, current in zip(frames, frames[1:]):
        label = str(current.get("input", ""))
        if label in ("idle", "done", "") or label in seen:
            continue
        if current.get("hash") != previous.get("hash"):
            seen.append(label)
    return tuple(seen)


def game_traceback(stderr: str) -> str:
    """The traceback from ``stderr``, without the harness's own frames.

    The harness and ``runpy`` sit above the child's code on every stack. Their frames
    are true and useless to the model, which should see exactly what ``python
    src/game.py`` would have printed.
    """
    start = stderr.find("Traceback (most recent call last):")
    if start < 0:
        return ""
    kept: list[str] = []
    skipping = False
    for line in stderr[start:].strip().splitlines():
        if line.startswith('  File "'):
            skipping = HARNESS.name in line or "<frozen runpy>" in line
        elif not line.startswith("    "):
            skipping = False
        if not skipping:
            kept.append(line)
    text = "\n".join(kept)
    if len(text) > MAX_ERROR_CHARS:
        text = "...\n" + text[-MAX_ERROR_CHARS:]
    return text
