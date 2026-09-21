"""Talking to arduino-cli: is it here, what boards exist, compile, upload.

WORKORDER_01 section 8. Compilation matters more than uploading initially, and that is
how this is built: compile is verified end to end under the process sandbox, upload is
implemented and gated but cannot currently reach a board (see :func:`upload`).

Everything here was measured against arduino-cli 1.5.1 on Apple silicon. SPIKES.md
section 14 has the runs; four findings shaped this module and none of them is guessable
from the documentation:

**A sketch folder must be named after its sketch.** ``arduino-cli compile src/`` fails
with ``main file missing from sketch: src/src.ino``. So the Arduino template is
``src/project/project.ino``, and the profile's entrypoint carries that subdirectory.

**Every invocation needs its data directory named, not just the ones that write.**
arduino-cli creates ``~/Library/Arduino15`` the moment it runs without one -- including
``version`` and ``board listall``. :func:`_environment` is therefore used by every call
in this module, even the read-only probes.

**Compiling works fully confined, but only once three paths are moved.** The toolchain
itself stays read-only, which is a bonus rather than a compromise: a compile cannot
modify its own compiler. What has to be writable is the staging directory, the
sketchbook and the build path, and all three go inside the project.

**Board lists are never hard-coded.** ``board listall --format json`` is the source, so
the picker shows what is actually installed and section 8's "never invent" rule extends
from pin numbers to board names.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from opennest import paths
from opennest.execution.python_runner import RunResult, run_project
from opennest.projects.manager import Project

EXECUTABLE = "arduino-cli"

#: Long enough for a cold compile of a large sketch, short enough to give up on a hang.
COMPILE_TIMEOUT_SECONDS = 300

#: Read-only under the sandbox. Holds the cores, which are 324 MB for AVR alone.
DATA_DIRNAME = "arduino-data"

#: Everything arduino-cli needs to *write*, relative to the project.
_STAGING = ".opennest/tmp/arduino-staging"
_SKETCHBOOK = ".opennest/tmp/arduino-user"
_BUILD = ".opennest/tmp/arduino-build"


class ArduinoUnavailable(Exception):
    """arduino-cli is not installed, in words a child can read."""


@dataclass(frozen=True)
class Board:
    name: str
    fqbn: str


@dataclass(frozen=True)
class Port:
    """A serial port, and the board on it if arduino-cli recognised one."""

    address: str
    board: Board | None = None

    @property
    def label(self) -> str:
        if self.board is None:
            return f"{self.address} (unrecognised)"
        return f"{self.board.name} on {self.address}"


def data_dir() -> Path:
    return paths.tools_dir() / DATA_DIRNAME


def cli_path() -> Path | None:
    """The managed copy first, then whatever is on PATH.

    A parent who already uses arduino-cli should not have to have a second one
    downloaded, but Open Nest's own copy is the one it can make promises about.
    """
    managed = paths.tools_dir()
    if managed.is_dir():
        for candidate in sorted(managed.glob(f"{EXECUTABLE}-*/{EXECUTABLE}")):
            if os.access(candidate, os.X_OK):
                return candidate
    found = shutil.which(EXECUTABLE)
    return Path(found) if found else None


def available() -> bool:
    """Whether arduino-cli can actually be run -- attempted, not assumed.

    The same stance as ``process_sandbox.sandbox_available``: a file existing where a
    binary should be is not the same question as that binary working.
    """
    cli = cli_path()
    if cli is None:
        return False
    try:
        result = subprocess.run(
            [str(cli), "version"],
            capture_output=True,
            timeout=30,
            env=_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def missing_message() -> str:
    """What to tell a child when the tools are not installed."""
    return (
        "The Arduino tools are not installed on this Mac yet, so I cannot check your "
        "sketch. Your code is saved. A parent can add them in Settings."
    )


def _environment(project_dir: Path | None = None) -> dict[str, str]:
    """Environment for one arduino-cli call.

    ``ARDUINO_DIRECTORIES_DATA`` is set even for read-only calls, because without it
    arduino-cli builds itself a home in ``~/Library`` and Open Nest's containment
    promise quietly stops being true.
    """
    env = dict(os.environ)
    env["ARDUINO_DIRECTORIES_DATA"] = str(data_dir())
    if project_dir is not None:
        env["ARDUINO_DIRECTORIES_USER"] = str(Path(project_dir) / _SKETCHBOOK)
        env["ARDUINO_DIRECTORIES_DOWNLOADS"] = str(Path(project_dir) / _STAGING)
    return env


def _query(args: list[str]) -> dict:
    """Run a read-only arduino-cli query and parse its JSON.

    Not run under the process sandbox, and the reason is worth stating: the sandbox
    confines code the *model* wrote. This is the application asking its own installed
    toolchain what it contains, touching no part of the child's project. Compiling and
    uploading, which do read the child's sketch, go through the sandbox.
    """
    cli = cli_path()
    if cli is None:
        raise ArduinoUnavailable(missing_message())
    try:
        result = subprocess.run(
            [str(cli), *args, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
            env=_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArduinoUnavailable(missing_message()) from exc
    if result.returncode != 0:
        raise ArduinoUnavailable(
            "The Arduino tools could not answer. " + (result.stderr or "").strip()[:200]
        )
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ArduinoUnavailable("The Arduino tools gave an answer Open Nest "
                                 "could not read.") from exc


def boards() -> list[Board]:
    """Every board the installed cores know about, alphabetically.

    Read from arduino-cli rather than written down here. Section 8 forbids inventing pin
    assignments; inventing the name of a board a parent does not own is the same
    mistake one level up.
    """
    payload = _query(["board", "listall"])
    found = [
        Board(name=entry["name"], fqbn=entry["fqbn"])
        for entry in payload.get("boards") or []
        if entry.get("fqbn") and entry.get("name")
    ]
    found.sort(key=lambda board: board.name.lower())
    return found


def connected_ports() -> list[Port]:
    """Serial ports with an Arduino on them, best guess first.

    A port with a recognised board is what an upload wants. Ports with nothing
    identifiable are still returned -- a board Open Nest does not recognise is not the
    same as no board, and saying "nothing is plugged in" when something is would be a
    lie a child can disprove by looking.
    """
    payload = _query(["board", "list"])
    found: list[Port] = []
    for entry in payload.get("detected_ports") or []:
        address = (entry.get("port") or {}).get("address")
        if not address:
            continue
        matching = entry.get("matching_boards") or []
        board = None
        if matching and matching[0].get("fqbn"):
            board = Board(
                name=matching[0].get("name") or matching[0]["fqbn"],
                fqbn=matching[0]["fqbn"],
            )
        found.append(Port(address=address, board=board))
    found.sort(key=lambda port: port.board is None)
    return found


def sketch_directory(project: Project) -> str:
    """The sketch folder, relative to the project.

    Derived from the manifest entrypoint (``project/project.ino``) rather than assumed,
    so a renamed sketch keeps working.
    """
    entrypoint = Path("src") / project.manifest.entrypoint
    return str(entrypoint.parent)


def compile_sketch(project: Project, fqbn: str) -> RunResult:
    """Compile the sketch under the process sandbox.

    Verified: exit 0 with clean stderr, 1.3 s cold and 0.4 s warm, with network denied
    and writes confined to the project. A broken sketch returns a real compiler
    diagnostic, which is what the repair loop needs.
    """
    cli = cli_path()
    if cli is None:
        raise ArduinoUnavailable(missing_message())
    return run_project(
        project.directory,
        (
            str(cli),
            "compile",
            "--fqbn", fqbn,
            "--build-path", _BUILD,
            sketch_directory(project),
        ),
        timeout=COMPILE_TIMEOUT_SECONDS,
        extra_env=_environment(project.directory),
    )


def upload(project: Project, fqbn: str, port: str) -> RunResult:
    """Put a compiled sketch onto a connected board -- a privileged application action.

    Uploading is the one thing here that deliberately crosses the project boundary,
    because crossing it is the point. It is treated as a privileged action rather than
    as project execution: still sandboxed, still offline, but granted write access to
    the single serial port a parent approved and to nothing else. No wider ``/dev``, no
    filesystem, no network, no shell. See ``process_sandbox.grant_devices``.

    That grant is necessary, and measured: an Arduino appears as ``/dev/cu.usbmodem*``,
    and the ordinary profile denies ``/dev/cu.*`` writes outright -- ``/dev/null`` is
    permitted, ``/dev/cu.debug-console`` returns ``Operation not permitted``, and only
    ``/dev/tty*`` is whitelisted (SPIKES.md section 14). Without the grant this could
    never succeed, no matter what was plugged in.

    **Hardware verification is pending.** No board has been connected to a machine
    running this code, so the grant is known to be necessary and is not yet known to be
    sufficient. Everything up to opening the port is exercised.

    The caller is responsible for the parent gate: ``permissions.gate("arduino_upload",
    approver)`` must have said yes before this is reached. This function does not check
    it, because the answer can be a dialog and this module has no UI.
    """
    cli = cli_path()
    if cli is None:
        raise ArduinoUnavailable(missing_message())
    return run_project(
        project.directory,
        (
            str(cli),
            "upload",
            "--fqbn", fqbn,
            "--port", port,
            "--input-dir", _BUILD,
            sketch_directory(project),
        ),
        timeout=COMPILE_TIMEOUT_SECONDS,
        extra_env=_environment(project.directory),
        devices=(port,),
    )


def describe() -> str:
    """One line for diagnostics and the health check."""
    cli = cli_path()
    if cli is None:
        return "Arduino tools: not installed"
    return f"Arduino tools: {cli} (data in {data_dir()})"
