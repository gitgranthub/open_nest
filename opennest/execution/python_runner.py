"""Running a child's project, out of process.

WORKORDER_01 sections 19, 28 and 30. Out of process for three reasons: a crashing game
must not take Open Nest down, the model's weights and the game must not contend in one
address space on an 8 GB Mac, and a separate process can actually be killed.

Phase 1 validated the mechanics -- see SPIKES.md section 5. Escalating SIGTERM to SIGKILL
across a new session group is what makes termination reliable; without a new session a
hung child can outlive its parent.

Every run is confined by :mod:`opennest.security.process_sandbox`: no network, writes
limited to the project. That is the boundary that actually holds against generated code,
as opposed to the path checks in :mod:`opennest.security.sandbox`, which only cover paths
travelling through Open Nest's own tools. If the sandbox cannot be applied, the project
is not run.
"""

from __future__ import annotations

import codecs
import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from opennest.execution import live_view
from opennest.security.process_sandbox import SandboxUnavailable, wrap

#: A child's game runs until they close it; an analysis should not run forever.
DEFAULT_TIMEOUT_SECONDS = 120

#: Enough to diagnose a failure without flooding the model's context.
MAX_CAPTURED_CHARS = 20_000


#: How long an interactive project gets to crash before we call it "running".
#: Long enough to catch an import error or a bad constant, short enough not to feel slow.
STARTUP_GRACE_SECONDS = 4.0


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool
    #: True when an interactive project survived startup and is still on screen.
    still_running: bool = False
    #: Live handle for a still-running project, so the UI can offer a Stop control.
    process: subprocess.Popen | None = None
    #: What a still-running project prints, read as it arrives -- see :class:`Output`.
    output: Output | None = None
    #: The pictures of a game shown inside Open Nest, and its input. Phase 13.
    live: live_view.LiveStream | None = None

    @property
    def ok(self) -> bool:
        if self.still_running:
            return True
        return self.exit_code == 0 and not self.timed_out

    @property
    def failure_text(self) -> str:
        """What the repair loop needs to see: stderr first, then trailing stdout."""
        parts = []
        if self.timed_out:
            parts.append(f"The project was still running after {self.seconds:.0f} seconds "
                         f"and was stopped.")
        if self.stderr.strip():
            parts.append(self.stderr.strip())
        if self.stdout.strip():
            parts.append("Output before it stopped:\n" + self.stdout.strip()[-2000:])
        return "\n\n".join(parts)


def _clip(text: str) -> str:
    if len(text) <= MAX_CAPTURED_CHARS:
        return text
    half = MAX_CAPTURED_CHARS // 2
    omitted = len(text) - MAX_CAPTURED_CHARS
    return f"{text[:half]}\n...[{omitted} characters omitted]...\n{text[-half:]}"


class _Captured:
    """One stream's text, bounded the way :func:`_clip` bounds it, however long it runs.

    The first half is kept as it arrived and the rest is a rolling tail, so a game that
    prints every frame for an hour holds 20,000 characters, not 36 MB.
    """

    def __init__(self) -> None:
        self._head = ""
        self._tail = ""
        self._omitted = 0

    def add(self, text: str) -> None:
        half = MAX_CAPTURED_CHARS // 2
        room = half - len(self._head)
        if room > 0:
            self._head += text[:room]
            text = text[room:]
        self._tail += text
        if len(self._tail) > half:
            self._omitted += len(self._tail) - half
            self._tail = self._tail[-half:]

    def text(self) -> str:
        if not self._omitted:
            return self._head + self._tail
        return f"{self._head}\n...[{self._omitted} characters omitted]...\n{self._tail}"


class Output:
    """Everything a still-running project prints, read as it arrives.

    An interactive run used to be read for its four-second startup and then never
    again, so its output piled up in the pipe until the pipe was full -- and then the
    child's next ``print`` blocked, and their game froze where it stood. Measured
    (SPIKES.md section 26): a game printing one line a frame stopped dead twelve seconds
    after it started, and the same game with its output read kept going. So from the
    moment an interactive project starts, two threads read what it writes, keep a
    bounded copy, and hand it over when the run ends.
    """

    def __init__(self, process: subprocess.Popen) -> None:
        self.started = time.monotonic()
        self.ended = 0.0
        #: Set by :func:`stop_project` before it stops the run, so an ending Open Nest
        #: caused is never mistaken for the project failing.
        self.stopped = False
        self._lock = threading.Lock()
        self._streams = {"stdout": _Captured(), "stderr": _Captured()}
        self._threads = [
            threading.Thread(target=self._read, args=(pipe, name), daemon=True,
                             name=f"project-{name}")
            for pipe, name in ((process.stdout, "stdout"), (process.stderr, "stderr"))
            if pipe is not None
        ]
        for thread in self._threads:
            thread.start()

    def _read(self, pipe, name: str) -> None:
        # The raw descriptor, not the text wrapper: ``read(n)`` on the wrapper waits for
        # n characters, and this has to take what is there as soon as it is there.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        fd = pipe.fileno()
        try:
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                with self._lock:
                    self._streams[name].add(decoder.decode(chunk))
        except OSError:
            pass
        finally:
            with self._lock:
                self._streams[name].add(decoder.decode(b"", final=True))
                self.ended = time.monotonic()

    def join(self, timeout: float = 2.0) -> None:
        for thread in self._threads:
            thread.join(timeout)

    def text(self, name: str) -> str:
        with self._lock:
            return self._streams[name].text()


def run_project(
    project_dir: Path,
    command: tuple[str, ...],
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    python_executable: str | None = None,
    interactive: bool = False,
    allow_network: bool = False,
    extra_env: dict[str, str] | None = None,
    devices: Sequence[str] = (),
    live: bool = False,
    on_live: Callable[[live_view.LiveStream], None] | None = None,
) -> RunResult:
    """Run a project's command from its directory and capture everything.

    ``command`` comes from the project profile. A leading "python" is replaced with the
    interpreter Open Nest manages, so a project never depends on what is on PATH.

    Two modes, because two kinds of project behave completely differently:

    **batch** (analyses, compiles) runs to completion under ``timeout`` and captures all
    output.

    **interactive** (games, hardware test loops) is meant to keep running until the child
    closes the window. Killing a game after two minutes of play would be absurd. So the
    process is launched, given :data:`STARTUP_GRACE_SECONDS` to fall over, and then
    reported as running with a live handle the UI can stop. A crash inside the grace
    window is captured exactly as in batch mode, which is what the repair loop needs.
    Its output is read for as long as it runs (:class:`Output`), because an unread pipe
    fills and then freezes the project.

    ``live`` is Phase 13: an interactive game that opens no window and sends its
    pictures to Open Nest instead (:mod:`opennest.execution.live_view`). Same sandbox,
    same profile, same command -- the shim goes in front of the child's file, and the
    game is handed one channel back to Open Nest. Ignored for anything that is not
    ``python <file>``. ``on_live`` is told the stream the moment the game has started,
    so its first pictures can be shown during the startup grace rather than after it.
    """
    project_dir = Path(project_dir).resolve(strict=True)
    stream = None
    if live and interactive and live_view.command_for(command) is not None:
        command = live_view.command_for(command)
        stream = live_view.LiveStream()
        extra_env = {**(extra_env or {}), **stream.environment()}
    argv = list(command)
    if argv and argv[0] == "python":
        argv[0] = python_executable or sys.executable

    started = time.monotonic()

    # The real security boundary. opennest.security.sandbox guards paths going through
    # Open Nest's tools; it cannot constrain a process, and generated code is a process.
    # ``devices`` is empty for every ordinary run. It is non-empty only for a privileged
    # application action -- an Arduino upload -- which is still confined, just granted
    # the one serial port a parent approved. See process_sandbox.grant_devices.
    try:
        argv = wrap(argv, project_dir, allow_network=allow_network, devices=devices)
    except SandboxUnavailable as exc:
        if stream is not None:
            stream.close()
        return RunResult(None, "", str(exc), time.monotonic() - started, False)
    except ValueError as exc:
        # A device that is not a grantable serial port. Refused, not run.
        if stream is not None:
            stream.close()
        return RunResult(None, "", str(exc), time.monotonic() - started, False)

    try:
        process = subprocess.Popen(
            argv,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=_child_environment(project_dir, extra_env),
            start_new_session=True,
            # The live channel, and nothing else, goes to the game.
            pass_fds=(stream.child_fd,) if stream is not None else (),
        )
    except OSError as exc:
        if stream is not None:
            stream.close()
        return RunResult(None, "", f"Open Nest could not start the project: {exc}",
                         time.monotonic() - started, False)

    if interactive:
        output = Output(process)
        if stream is not None:
            stream.start()
            if on_live is not None:
                with contextlib.suppress(Exception):   # showing it never stops a run
                    on_live(stream)
        try:
            process.wait(timeout=STARTUP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            # Survived startup: leave it on screen for the child.
            return RunResult(
                exit_code=None, stdout="", stderr="",
                seconds=time.monotonic() - started,
                timed_out=False, still_running=True, process=process,
                output=output, live=stream,
            )
        # Exited within the grace window -- succeeded quickly, or crashed.
        output.join()
        if stream is not None:
            stream.close()
        return RunResult(
            exit_code=process.returncode,
            stdout=output.text("stdout"),
            stderr=_stderr_for(output, stream),
            seconds=time.monotonic() - started,
            timed_out=False,
        )

    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stdout, stderr = _terminate(process)

    return RunResult(
        exit_code=process.returncode,
        stdout=_clip(stdout or ""),
        stderr=_clip(stderr or ""),
        seconds=time.monotonic() - started,
        timed_out=timed_out,
    )


def stop_project(result: RunResult) -> None:
    """Stop a still-running interactive project. Safe to call more than once."""
    if result.output is not None and result.process is not None \
            and result.process.poll() is None:
        result.output.stopped = True
    if result.process is not None and result.process.poll() is None:
        _terminate(result.process, result.output)
    if result.live is not None:
        result.live.close()


def finished(result: RunResult) -> RunResult | None:
    """How a still-running project ended, once it has; None while it is still going.

    For the game on the child's screen: the run reported ``still_running`` when it
    survived startup, and that stays true of the result however it ends. This is what
    it actually did -- its exit status and everything it printed, the shim's own
    traceback frames removed exactly as they are for a crash during startup.
    ``result.output.stopped`` says whether Open Nest was the one that ended it.
    """
    process, output = result.process, result.output
    if process is None or output is None or process.poll() is None:
        return None
    output.join()
    return RunResult(
        exit_code=process.returncode,
        stdout=output.text("stdout"),
        stderr=_stderr_for(output, result.live),
        seconds=(output.ended or time.monotonic()) - output.started,
        timed_out=False,
    )


def _stderr_for(output: Output, stream: live_view.LiveStream | None) -> str:
    text = output.text("stderr")
    return live_view.without_shim_frames(text) if stream is not None else text


def _terminate(process: subprocess.Popen, output: Output | None = None) -> tuple[str, str]:
    """Stop a process group, escalating if it ignores the polite request.

    With ``output``, the pipes already belong to its reader threads, so this waits for
    the process rather than reading from them a second time.
    """
    def collect(grace: float) -> tuple[str, str]:
        if output is None:
            return process.communicate(timeout=grace)
        process.wait(timeout=grace)
        output.join(1.0)
        return output.text("stdout"), output.text("stderr")

    for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except (ProcessLookupError, PermissionError):
            break
        try:
            return collect(grace)
        except subprocess.TimeoutExpired:
            continue
    try:
        return collect(1)
    except subprocess.TimeoutExpired:
        return "", ""


#: Where matplotlib may keep its font cache. Inside the project, so the sandbox permits
#: the write, and under ``.opennest/tmp`` so it is already git-ignored and already hidden
#: from the file list the model sees.
MATPLOTLIB_CACHE = ".opennest/tmp/matplotlib"


def _child_environment(project_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """A deliberately small environment for the child process.

    Passing the parent's environment wholesale would hand a generated script every token
    and path Open Nest happens to be holding.
    """
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SDL_VIDEODRIVER", "DISPLAY")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env["PYTHONUNBUFFERED"] = "1"          # so partial output survives a crash
    env["PYTHONDONTWRITEBYTECODE"] = "1"   # no __pycache__ litter in the child's project
    env["OPENNEST_PROJECT"] = str(project_dir)

    # Without this, matplotlib finds ~/.matplotlib unwritable under Seatbelt, falls back
    # to a fresh temporary directory, and rebuilds its font cache on EVERY run: measured
    # at 6.6 s per run plus three lines of stderr warning, against 0.3 s and silence once
    # the cache persists. See SPIKES.md section 14. It is a speed and noise fix, not a
    # correctness one -- the chart was always written.
    env["MPLCONFIGDIR"] = str(Path(project_dir) / MATPLOTLIB_CACHE)

    if extra:
        env.update(extra)
    return env
