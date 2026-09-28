"""The half of a live game that runs inside the child's process.

    python live_shim.py src/game.py          (OPENNEST_LIVE_FD names the channel)

Phase 13. :mod:`opennest.execution.live_view` starts this exactly the way it would start
the game -- same interpreter, same process sandbox, same working directory -- with SDL's
dummy video driver, so the game opens no window of its own. It runs the child's
``src/game.py`` unmodified and sends each picture the game draws to Open Nest, which
paints it inside the Workbench. The keys and clicks the child gives that picture come
back the same way.

**Why not the game's own window.** macOS has no way to put another process's window
inside a Qt view, and running the game inside Open Nest would hand generated code the
application's memory. Placing the window over the panel was built and withdrawn in
Phase 12 because Open Nest could place it and never clip it (SPIKES.md section 20I).
Drawing the frames ourselves is the only honest "inside the workbench".

It imports nothing from Open Nest, for the same reason the playtest harness does: it
runs in the child's interpreter alongside the child's code.

Four things here follow from measurements (SPIKES.md section 26):

- **The channel is a socket, not a pipe.** A pipe moves a 640x480 frame in fifteen or
  so 64 KB reads; with Open Nest's main thread busy in Python each read waited for the
  interpreter lock and the stream fell to 12.7 frames a second -- and dragged the game
  down with it, because a full pipe blocks the game's ``flip``. A socket with large
  buffers moved the same frames at 55 a second under the same load.
- **A frame is sent only when the picture changed.** A game that is standing still
  costs nothing. It is sent in the byte order Qt draws natively (B, G, R, opaque), so
  Open Nest never converts one: that conversion was measured at 17 % of a core.
- **Input is posted into the game's own event queue**, never substituted for it, and the
  functions a game reads the keyboard and mouse through directly --
  ``key.get_pressed`` above all, which the starter uses -- are answered from what the
  child is holding. Posting an event does not change SDL's own idea of which keys are
  down, so without that the starter's player would not move at all. The playtest harness
  learnt the same thing (SPIKES.md section 24).
- **``runpy`` runs the child's file in place**, so a traceback names ``src/game.py`` and
  the real line. Open Nest removes this file's own frames before anyone reads it.
"""

import contextlib
import json
import os
import runpy
import select
import socket
import struct
import sys
import time

CHANNEL_FD = int(os.environ["OPENNEST_LIVE_FD"])
ENTRY = sys.argv[1]

#: Kept in step with :mod:`opennest.execution.live_view`, which cannot be imported here.
HEADER = struct.Struct("<4scxHHI")
MAGIC = b"ONLV"
FRAME, TITLE = b"F", b"T"
MAX_TITLE_BYTES = 400
BUFFER_BYTES = 4 << 20

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

_channel = socket.socket(fileno=CHANNEL_FD)
# Not handed on to anything the game itself starts.
os.set_inheritable(CHANNEL_FD, False)
_channel.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_BYTES)


def _schedule_like_a_game_on_screen():
    """Tell macOS this process is the one being looked at, as a window in front would.

    Measured (SPIKES.md section 26): macOS gives a process with no window loose timer
    deadlines, so every sleep overshoots -- ``time.sleep(0.016)`` took 22 ms, and a game
    asking ``clock.tick(60)`` drew 46 frames a second instead of the 56 it drew in a
    window of its own. Nothing about the game or the stream was slow; drawing a frame
    took 0.05 ms. AppKit marks a frontmost application with this task role, and setting
    it here restores the windowed timing exactly (17.9 ms, 56 fps). Thread QoS alone
    changed nothing. It is a scheduling class and grants nothing -- no file, no network,
    no device -- and if it is refused the game simply runs as before.
    """
    with contextlib.suppress(Exception):
        import ctypes

        system = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        task = ctypes.c_uint.in_dll(system, "mach_task_self_").value
        foreground = ctypes.c_int(1)          # TASK_FOREGROUND_APPLICATION
        system.task_policy_set(task, 1, ctypes.byref(foreground), 1)   # TASK_CATEGORY_POLICY


_schedule_like_a_game_on_screen()


def _send(kind, width, height, payload):
    try:
        _channel.sendall(HEADER.pack(MAGIC, kind, width, height, len(payload)) + payload)
    except OSError:
        # Open Nest is not listening any more -- it stopped the game, or it is gone.
        # Nobody can see the game either way, so it ends here rather than playing on
        # to nobody.
        os._exit(0)


try:
    import pygame
except ImportError:
    pygame = None

if pygame is not None:
    _to_bytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring
    _state = {"last": None, "pending": b"", "pos": (0, 0), "buttons": [False, False, False]}
    _held = set()
    _MODS = {
        pygame.K_LSHIFT: pygame.KMOD_LSHIFT, pygame.K_RSHIFT: pygame.KMOD_RSHIFT,
        pygame.K_LCTRL: pygame.KMOD_LCTRL, pygame.K_RCTRL: pygame.KMOD_RCTRL,
        pygame.K_LALT: pygame.KMOD_LALT, pygame.K_RALT: pygame.KMOD_RALT,
        pygame.K_LMETA: pygame.KMOD_LMETA, pygame.K_RMETA: pygame.KMOD_RMETA,
    }

    def _mods():
        value = 0
        for key in _held:
            value |= _MODS.get(key, 0)
        return value

    def _post(event_type, **fields):
        # A game can call pygame.quit() and carry on; posting then raises. Nothing the
        # child pressed is worth ending their game over.
        with contextlib.suppress(pygame.error):
            pygame.event.post(pygame.event.Event(event_type, **fields))

    def _key(name, down, text):
        code = getattr(pygame, name, None) if name.startswith("K_") else None
        if not isinstance(code, int):
            return
        if down:
            if code in _held:
                return
            _held.add(code)
            _post(pygame.KEYDOWN, key=code, mod=_mods(), unicode=text, scancode=0)
            if text and text.isprintable():
                _post(pygame.TEXTINPUT, text=text)
        elif code in _held:
            _held.discard(code)
            _post(pygame.KEYUP, key=code, mod=_mods(), unicode="", scancode=0)

    def _release_all():
        for code in sorted(_held):
            _post(pygame.KEYUP, key=code, mod=0, unicode="", scancode=0)
        _held.clear()
        for index, down in enumerate(_state["buttons"]):
            if down:
                _state["buttons"][index] = False
                _post(pygame.MOUSEBUTTONUP, pos=_state["pos"], button=index + 1)

    def _mouse(kind, x, y, button):
        previous = _state["pos"]
        _state["pos"] = (x, y)
        if kind == "move":
            _post(pygame.MOUSEMOTION, pos=(x, y), rel=(x - previous[0], y - previous[1]),
                  buttons=tuple(int(b) for b in _state["buttons"]))
        elif kind in ("down", "up") and 1 <= button <= 3:
            _state["buttons"][button - 1] = kind == "down"
            event_type = pygame.MOUSEBUTTONDOWN if kind == "down" else pygame.MOUSEBUTTONUP
            _post(event_type, pos=(x, y), button=button)

    def _apply(line):
        try:
            message = json.loads(line)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        what = message.get("t")
        try:
            if what == "key":
                _key(str(message.get("k", "")), bool(message.get("d")),
                     str(message.get("u", ""))[:1])
            elif what == "mouse":
                _mouse(str(message.get("m", "")), int(message.get("x", 0)),
                       int(message.get("y", 0)), int(message.get("b", 0)))
            elif what == "release":
                _release_all()
        except (TypeError, ValueError):
            return

    def _pump():
        """Take whatever the child has pressed since last time. Never waits."""
        while True:
            try:
                chunk = _channel.recv(65536, socket.MSG_DONTWAIT)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                os._exit(0)
            if not chunk:
                # Open Nest closed its end. The same as a failed send.
                os._exit(0)
            _state["pending"] += chunk
            *lines, _state["pending"] = _state["pending"].split(b"\n")
            for line in lines:
                _apply(line)

    def _show():
        surface = pygame.display.get_surface()
        if surface is None:
            return
        try:
            # Qt's own RGB32 layout on a little-endian Mac. See live_view.FRAME_FORMAT.
            data = _to_bytes(surface, "BGRA")
        except (pygame.error, ValueError):
            return
        if data == _state["last"]:
            return
        _state["last"] = data
        width, height = surface.get_size()
        _send(FRAME, width, height, data)

    _real = {
        "flip": pygame.display.flip,
        "update": pygame.display.update,
        "set_caption": pygame.display.set_caption,
        "get": pygame.event.get,
        "poll": pygame.event.poll,
        "wait": pygame.event.wait,
        "peek": pygame.event.peek,
        "event_pump": pygame.event.pump,
        "get_pressed": pygame.key.get_pressed,
        "get_mods": pygame.key.get_mods,
        "mouse_pos": pygame.mouse.get_pos,
        "mouse_pressed": pygame.mouse.get_pressed,
    }

    def _flip(*args, **kwargs):
        result = _real["flip"](*args, **kwargs)
        _show()
        _pump()
        return result

    def _update(*args, **kwargs):
        result = _real["update"](*args, **kwargs)
        _show()
        _pump()
        return result

    def _set_caption(title, *args, **kwargs):
        text = str(title).encode("utf-8", "replace")[:MAX_TITLE_BYTES]
        _send(TITLE, 0, 0, text)
        return _real["set_caption"](title, *args, **kwargs)

    def _after_pump(name):
        def wrapped(*args, **kwargs):
            _pump()
            return _real[name](*args, **kwargs)
        return wrapped

    def _wait(*args, **kwargs):
        """``event.wait``, for a game that redraws only when something happens.

        The real one would sleep inside SDL while the child's key sat unread on the
        channel, so it waits on the channel instead and hands over whatever arrives.
        A timeout, when the game gives one, is kept.
        """
        timeout = args[0] if args else kwargs.get("timeout", 0)
        deadline = time.monotonic() + timeout / 1000 if timeout else None
        while True:
            _pump()
            event = _real["poll"]()
            if event.type != pygame.NOEVENT:
                return event
            if deadline is not None and time.monotonic() >= deadline:
                return event
            select.select([_channel], [], [], 0.05)

    class _Keys:
        """``key.get_pressed()`` with the keys the child is holding in Open Nest."""

        def __init__(self, real):
            self._real = real

        def __getitem__(self, key):
            if key in _held:
                return True
            try:
                return self._real[key]
            except (IndexError, KeyError):
                return False

        def __len__(self):
            return len(self._real)

    def _get_pressed(*args, **kwargs):
        _pump()
        return _Keys(_real["get_pressed"](*args, **kwargs))

    def _get_mods(*args, **kwargs):
        return _real["get_mods"](*args, **kwargs) | _mods()

    def _mouse_pos(*args, **kwargs):
        return _state["pos"]

    def _mouse_pressed(*args, **kwargs):
        real = _real["mouse_pressed"](*args, **kwargs)
        held = tuple(_state["buttons"])
        return tuple(bool(r) or held[i] if i < 3 else r for i, r in enumerate(real))

    pygame.display.flip = _flip
    pygame.display.update = _update
    pygame.display.set_caption = _set_caption
    pygame.event.get = _after_pump("get")
    pygame.event.poll = _after_pump("poll")
    pygame.event.peek = _after_pump("peek")
    pygame.event.pump = _after_pump("event_pump")
    pygame.event.wait = _wait
    pygame.key.get_pressed = _get_pressed
    pygame.key.get_mods = _get_mods
    pygame.mouse.get_pos = _mouse_pos
    pygame.mouse.get_pressed = _mouse_pressed

# Run exactly as ``python src/game.py`` would. A game that is not a pygame game, or a
# Mac without pygame, still runs: it simply never sends a picture, and its own import
# error is the one the child's code would have raised anyway.
sys.argv = [ENTRY]
sys.path[0] = os.path.dirname(os.path.abspath(ENTRY))
runpy.run_path(ENTRY, run_name="__main__")
