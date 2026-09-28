"""A game shown inside Open Nest: the pictures it draws, and the keys it is given.

Phase 13, and PHASE_12_HANDOFF.md section 6 is the specification. The child's game still
runs out of process, under exactly the same process sandbox as every other run -- that is
the product's outer security boundary and nothing here relaxes it. What changes is where
the picture goes: :mod:`opennest.execution.live_shim` runs the game with no window and
sends each frame it draws over one channel Open Nest hands it at launch, and this module
is the receiving end. The Workbench paints the frames (:mod:`opennest.ui.game_view`).

**Nothing here knows about the Workbench, a conversation or a model**, on purpose. A
stream is a running project and a picture, so the same pieces can later show a game that
was shared with somebody, in a play-only mode, without a Toolbox behind it.

**Everything the game sends is untrusted.** It is generated code, and it can write
whatever it likes to the channel it was given. So a message has a fixed binary header,
sizes are bounded before anything is allocated, a payload must be exactly the length its
header says, only the newest picture is ever kept, and the window title is treated as
plain text of bounded length. Anything else ends the stream -- :attr:`LiveStream.broken`
says why -- and the caller stops the game. No pickle, no JSON, nothing evaluated.

**Input goes the other way, and never blocks Open Nest.** A key press is a short line
sent without waiting; if the game has stopped reading, presses wait in a small bounded
buffer and then are dropped whole, rather than freezing the window the child is typing
into. Measured, and not what the documentation suggests: on macOS ``MSG_DONTWAIT`` on a
Unix socket *send* still blocks, so Open Nest's end is put in non-blocking mode instead
and the reader waits in ``select``.

**The channel is a Unix socket pair, not a pipe**, measured (SPIKES.md section 26): with
the main thread busy in Python a pipe fell to 12.7 frames a second and slowed the game
with it; the socket pair held 55. It is created here, inherited by the one process it was
made for, and connects to nothing else. The sandbox profile is byte-for-byte unchanged;
the game gains no network, no file access and no new permission.
"""

from __future__ import annotations

import contextlib
import json
import select
import socket
import struct
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

SHIM = Path(__file__).with_name("live_shim.py")

#: ``magic, kind, width, height, payload length``. Kept in step with ``live_shim``.
HEADER = struct.Struct("<4scxHHI")
MAGIC = b"ONLV"
FRAME, TITLE = b"F", b"T"

#: Bounds checked before anything is allocated. A 4096-pixel side is past any window a
#: child's game opens; 16 MB is one 2048x2048 frame, and only one is ever held.
MAX_SIDE = 4096
MAX_FRAME_BYTES = 16 << 20
MAX_TITLE_BYTES = 400
#: Room for a few frames in flight, so the game's ``flip`` never waits on Open Nest.
BUFFER_BYTES = 4 << 20

#: Input waiting for a game that is not reading. Far more than a child can type between
#: two frames; past it, a press is dropped whole so the next one still reads correctly.
MAX_PENDING_INPUT = 64 << 10

#: The environment variable that tells the shim which descriptor is its channel.
CHANNEL_VARIABLE = "OPENNEST_LIVE_FD"


#: How a picture's pixels are laid out: four bytes each, blue, green, red and an opaque
#: fourth byte -- exactly ``QImage.Format_RGB32`` on a little-endian Mac, so Qt draws it
#: without converting. Measured (SPIKES.md section 26G): RGB triples made Qt convert every
#: frame, which was 17 of the 39 % of a core that showing a game cost.
FRAME_FORMAT = "BGRA"
BYTES_PER_PIXEL = 4


@dataclass(frozen=True)
class Frame:
    """One picture the game drew: ``width * height`` pixels in :data:`FRAME_FORMAT`."""

    sequence: int
    width: int
    height: int
    data: bytes


def command_for(command: Sequence[str]) -> tuple[str, ...] | None:
    """The run command with the shim in front of the game, or None if it cannot be.

    Only a ``python <file>`` command can be run this way, because the shim is a Python
    file that runs the child's one. The Games profile's command always is.
    """
    if len(command) < 2 or command[0] != "python":
        return None
    return ("python", str(SHIM), *command[1:])


class LiveStream:
    """The receiving end of one game's pictures, and the sending end of its input.

    Made before the game starts (the game inherits :attr:`child_fd`), then
    :meth:`start` is called once it has. A reader thread takes each message as it
    arrives and keeps only the newest picture, so memory is bounded however fast the
    game draws. The thread touches no Qt object; whoever shows the picture asks for
    :meth:`latest` on their own thread.
    """

    def __init__(self) -> None:
        self._mine, self._theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        with contextlib.suppress(OSError):
            self._mine.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_BYTES)
        # Deliberately left non-inheritable: ``subprocess`` hands it to the one process
        # it is passed to (``pass_fds``), and to nothing else Open Nest starts.
        # Open Nest's end never blocks -- see the module docstring for why a flag on
        # each send is not enough on macOS.
        self._mine.setblocking(False)
        self._outgoing = bytearray()
        self._send_lock = threading.Lock()
        self._lock = threading.Lock()
        self._frame: Frame | None = None
        self._title = ""
        self._sequence = 0
        #: Why the stream was ended by Open Nest, when the game sent something that is
        #: not a picture or a title. Empty otherwise.
        self.broken = ""
        self._done = threading.Event()
        self._reader: threading.Thread | None = None

    # -- starting --------------------------------------------------------------------

    @property
    def child_fd(self) -> int:
        """The descriptor the game's process inherits. Only valid until :meth:`start`."""
        return self._theirs.fileno()

    def environment(self) -> dict[str, str]:
        """What the game's environment needs for the shim to find its channel."""
        return {CHANNEL_VARIABLE: str(self.child_fd), "SDL_VIDEODRIVER": "dummy"}

    def start(self) -> None:
        """The game has its copy of the channel now; begin reading from it."""
        with contextlib.suppress(OSError):
            self._theirs.close()
        self._reader = threading.Thread(target=self._read, name="live-view", daemon=True)
        self._reader.start()

    # -- what the game has shown -----------------------------------------------------

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frame

    @property
    def title(self) -> str:
        with self._lock:
            return self._title

    @property
    def finished(self) -> bool:
        """Whether nothing more will arrive: the game ended, or the stream was ended."""
        return self._done.is_set()

    def wait_finished(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    # -- the child's input -------------------------------------------------------------

    def send_key(self, name: str, down: bool, text: str = "") -> None:
        """A key pressed or released, by its pygame name: ``"K_LEFT"``, ``"K_a"``."""
        self._send({"t": "key", "k": name, "d": int(bool(down)), "u": text[:1]})

    def send_mouse(self, kind: str, x: int, y: int, button: int = 0) -> None:
        """``kind`` is ``"move"``, ``"down"`` or ``"up"``, in the game's own pixels."""
        self._send({"t": "mouse", "m": kind, "x": int(x), "y": int(y), "b": int(button)})

    def release_all(self) -> None:
        """Let go of every key and button -- the game view lost the child's focus."""
        self._send({"t": "release"})

    def _send(self, message: dict) -> None:
        line = (json.dumps(message, separators=(",", ":")) + "\n").encode("ascii")
        with self._send_lock:
            if len(self._outgoing) + len(line) > MAX_PENDING_INPUT:
                return   # the game is not reading; this press is dropped whole
            self._outgoing += line
            try:
                sent = self._mine.send(self._outgoing)
            except (BlockingIOError, InterruptedError):
                return   # kept, and sent ahead of the next press
            except OSError:
                self._outgoing.clear()   # the game is gone
                return
            del self._outgoing[:sent]

    # -- ending ------------------------------------------------------------------------

    def close(self) -> None:
        """Stop receiving. Safe to call more than once, and from any thread."""
        with contextlib.suppress(OSError):
            self._mine.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            self._theirs.close()
        if self._reader is None:
            # The game never started, so there is no reader to close our end and say so.
            with contextlib.suppress(OSError):
                self._mine.close()
            self._done.set()

    # -- the reader thread -------------------------------------------------------------

    def _read(self) -> None:
        try:
            while True:
                head = self._receive(HEADER.size)
                if head is None:
                    return
                magic, kind, width, height, length = HEADER.unpack(head)
                problem = _check(magic, kind, width, height, length)
                if problem:
                    self.broken = problem
                    return
                payload = self._receive(length) if length else b""
                if payload is None:
                    return
                with self._lock:
                    if kind == FRAME:
                        self._sequence += 1
                        self._frame = Frame(self._sequence, width, height, payload)
                    else:
                        self._title = _plain(payload)
        except (OSError, ValueError):
            # ValueError: the socket was closed under ``select`` by :meth:`close`.
            return
        finally:
            with contextlib.suppress(OSError):
                self._mine.close()
            self._done.set()

    def _receive(self, count: int) -> bytes | None:
        """Exactly ``count`` bytes, or None at the end of the stream."""
        buffer = bytearray(count)
        view = memoryview(buffer)
        got = 0
        while got < count:
            try:
                n = self._mine.recv_into(view[got:], count - got)
            except (BlockingIOError, InterruptedError):
                select.select([self._mine], [], [])
                continue
            if n == 0:
                return None
            got += n
        return bytes(buffer)


def _check(magic: bytes, kind: bytes, width: int, height: int, length: int) -> str:
    """Why a header is not one Open Nest will accept, or "" when it is."""
    if magic != MAGIC:
        return "it sent something that was not a picture"
    if kind == FRAME:
        if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
            return f"it sent a picture {width}x{height} pixels, which is too big to show"
        if length != width * height * BYTES_PER_PIXEL or length > MAX_FRAME_BYTES:
            return "it sent a picture whose size did not add up"
        return ""
    if kind == TITLE:
        if width or height or length > MAX_TITLE_BYTES:
            return "it sent a window title that was too long"
        return ""
    return "it sent something that was not a picture"


def _plain(payload: bytes) -> str:
    """A window title as plain text: decoded, one line, no control characters."""
    text = payload.decode("utf-8", "replace")
    return "".join(ch for ch in text if ch.isprintable()).strip()


def without_shim_frames(stderr: str) -> str:
    """``stderr`` with the shim's own traceback frames taken out.

    The shim and ``runpy`` sit above the child's code on every stack. Their frames are
    true and useless: the repair loop and the child should see exactly what ``python
    src/game.py`` would have printed. Everything that is not one of those frames --
    the child's own lines, anything the game printed -- is left as it was.
    """
    kept: list[str] = []
    skipping = False
    for line in stderr.splitlines():
        if line.startswith('  File "'):
            skipping = SHIM.name in line or "<frozen runpy>" in line
        elif not line.startswith("    "):
            skipping = False
        if not skipping:
            kept.append(line)
    text = "\n".join(kept)
    return text + "\n" if stderr.endswith("\n") and text else text
