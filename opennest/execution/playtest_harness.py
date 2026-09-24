"""The half of a playtest that runs inside the child's process.

    python playtest_harness.py src/game.py        (OPENNEST_PLAYTEST_RECORD names the file)

:mod:`opennest.execution.playtest` starts this exactly the way it would start the game --
same interpreter, same process sandbox, same working directory -- with SDL's dummy video
driver, so no window opens and the game draws into an offscreen surface instead. Then it
runs the child's game, unmodified, with a few pygame functions wrapped.

**It records and never judges.** One JSON line per thing that happened, written to the
record file: the window opening, each frame's hash with the input being given at the
time, and how the run ended. What any of it means is decided by the parent, where it can
be tested without a game.

It imports nothing from Open Nest, because it runs in the child's interpreter alongside
the child's code, and Open Nest's own modules have no business in there.

Three things here were each measured as the difference between a working game and a
false failure (SPIKES.md section 24). Phase 12.3's grader replaced ``pygame.event.get``
with a function returning nothing, which swallowed every KEYDOWN *and* every timer event
the game set up for itself, and graded seven of ten working games as frozen:

- **Input is posted into the game's own event queue**, never substituted for it, so
  ``event.get``, ``poll``, filtered gets and ``set_timer`` all behave as they would.
- **The input is broad**: arrows, W A S D, space, enter, a number, letters, mouse clicks
  and mouse movement, and one long hold for anything that has to build up speed. A game
  frozen under all of it is frozen; a game that answers only to the letter P is not.
- **``runpy`` runs the child's file in place**, so a traceback names ``src/game.py`` and
  the real line, which is what the repair loop has to act on. Copying the game somewhere
  else to add a preamble -- the spike's method -- shifted every line number and broke
  any path built from ``__file__``.
"""

import hashlib
import json
import os
import random
import runpy
import sys
import threading
import time

#: How long the game is left alone before any input. Frames or seconds, whichever comes
#: first, so a game running at 10 frames a second is not left for three seconds.
IDLE_FRAMES, IDLE_SECONDS = 15, 0.25
#: How long each input is held, and then how long the game gets to show the release.
PRESS_FRAMES, PRESS_SECONDS = 3, 0.1
RELEASE_FRAMES, RELEASE_SECONDS = 3, 0.1
#: The last input is held much longer, for a ship that accelerates rather than moves.
LONG_FRAMES, LONG_SECONDS = 20, 0.4
#: A game that has not drawn anything by now is not going to.
NO_FRAME_SECONDS = 4.0
#: Nothing runs longer than this, whatever the game does.
WALL_SECONDS = 10.0

#: (label, keys held, mouse gesture, held long). Never Escape or Q: a game that quits on
#: those would end the test early for no reason worth reporting.
ACTIONS = (
    ("right", ("K_RIGHT",), None, False),
    ("left", ("K_LEFT",), None, False),
    ("up", ("K_UP",), None, False),
    ("down", ("K_DOWN",), None, False),
    ("space", ("K_SPACE",), None, False),
    ("enter", ("K_RETURN",), None, False),
    ("wasd", ("K_d", "K_s"), None, False),
    ("number", ("K_1",), None, False),
    ("letters", ("K_p", "K_x", "K_z", "K_e", "K_f", "K_r"), None, False),
    ("click", (), "click", False),
    ("mouse", (), "move", False),
    ("hold", ("K_UP", "K_RIGHT", "K_w", "K_d", "K_SPACE"), None, True),
)

_TEXT = {"K_SPACE": " ", "K_RETURN": "\r", "K_1": "1"}

RECORD = os.environ["OPENNEST_PLAYTEST_RECORD"]
ENTRY = sys.argv[1]

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

_started = time.monotonic()
_lock = threading.Lock()
_out = open(RECORD, "w", encoding="utf-8")  # noqa: SIM115 -- open for the whole run
_state = {"frames": 0, "ended": False}


def _write(record):
    with _lock:
        _out.write(json.dumps(record) + "\n")
        _out.flush()


def _end(reason, during=""):
    with _lock:
        if _state["ended"]:
            return
        _state["ended"] = True
    _write({"end": reason, "during": during, "frames": _state["frames"],
            "seconds": round(time.monotonic() - _started, 3)})


try:
    import pygame
except ImportError:
    # Not the game's fault, and nothing a repair could change.
    _end("no_pygame")
    sys.exit(0)


class _Finished(SystemExit):
    """Every input has been given. Raised through the game's own call stack to stop it."""


class _Script:
    """What the game is being given, advanced once per drawn frame."""

    def __init__(self):
        self.step = -1              # -1 is the idle opening; then an index into ACTIONS
        self.pressed = False
        self.frames = 0             # frames drawn since the current phase began
        self.since = time.monotonic()
        self.held = set()
        self.mouse_pos = None
        self.mouse_down = False
        self.size = (640, 480)

    @property
    def label(self):
        if self.step < 0:
            return "idle"
        if self.step >= len(ACTIONS):
            return "done"
        return ACTIONS[self.step][0]

    def after_frame(self):
        """Decide what the game gets before its next frame."""
        if self.step >= len(ACTIONS):
            self._finish()
        self.frames += 1
        self.mouse_down = False
        elapsed = time.monotonic() - self.since
        if self.step < 0:
            if self.frames >= IDLE_FRAMES or elapsed >= IDLE_SECONDS:
                self._press(0)
        elif self.pressed:
            _, _, mouse, long = ACTIONS[self.step]
            frames, seconds = (LONG_FRAMES, LONG_SECONDS) if long else (
                PRESS_FRAMES, PRESS_SECONDS)
            if self.frames >= frames or elapsed >= seconds:
                self._release()
            elif mouse == "move":
                self._move_mouse()
        elif self.frames >= RELEASE_FRAMES or elapsed >= RELEASE_SECONDS:
            self._press(self.step + 1)

    def skip_ahead(self):
        """The game is waiting for input and nothing is queued: give it the next one now.

        A game that redraws only when something happens -- ``event.wait()`` rather than a
        frame loop -- would otherwise wait forever, because the script advances on
        frames. Time spent in ``pygame.time.wait`` is deliberately *not* skipped: a
        title card held for a second and a half is the game's own pacing.
        """
        if self.step >= len(ACTIONS):
            self._finish()
        if self.pressed:
            self._release()
        else:
            self._press(self.step + 1)

    def _finish(self):
        """Every input has been given: stop the game.

        Raised through the game's own call stack the first time, so the game ends the
        ordinary way. A game with a bare ``except:`` round its loop swallows that, and
        comes straight back here on its next frame -- by which time the record is
        complete and flushed, so the process just ends. Anything else would either
        index past the script, raising from harness code that reads as the game
        crashing, or loop until the wall clock.
        """
        if _state["ended"]:
            os._exit(0)
        self.step, self.pressed = len(ACTIONS), False
        _end("done", "done")
        raise _Finished(0)

    def _press(self, step):
        self.step, self.pressed, self.frames = step, True, 0
        self.since = time.monotonic()
        if step >= len(ACTIONS):
            self._finish()
        _, keys, mouse, _ = ACTIONS[step]
        for name in keys:
            code = getattr(pygame, name)
            self.held.add(code)
            text = _TEXT.get(name, name[2:] if len(name) == 3 else "")
            pygame.event.post(pygame.event.Event(
                pygame.KEYDOWN, key=code, mod=0, unicode=text, scancode=0))
            if text.strip():
                pygame.event.post(pygame.event.Event(pygame.TEXTINPUT, text=text))
        if mouse == "click":
            self._click()
        elif mouse == "move":
            self._move_mouse()

    def _release(self):
        for code in sorted(self.held):
            pygame.event.post(pygame.event.Event(
                pygame.KEYUP, key=code, mod=0, unicode="", scancode=0))
        self.held.clear()
        self.pressed, self.frames = False, 0
        self.since = time.monotonic()

    def _click(self):
        # Five places, the centre last so it is also where the pointer is left. A
        # clickable Start button is usually centred left-to-right; how far down it sits
        # varies, which is what the other four cover.
        w, h = self.size
        spots = [(w // 2, h * 7 // 10), (w // 2, h * 3 // 10), (w * 3 // 10, h // 2),
                 (w * 7 // 10, h // 2), (w // 2, h // 2)]
        for pos in spots:
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))
        self.mouse_pos, self.mouse_down = spots[-1], True

    def _move_mouse(self):
        w, h = self.size
        x = int(w * (0.2 + 0.2 * min(self.frames, 3)))
        pos = (x, h * 4 // 5)
        previous = self.mouse_pos or pos
        self.mouse_pos = pos
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEMOTION, pos=pos, rel=(pos[0] - previous[0], pos[1] - previous[1]),
            buttons=(0, 0, 0)))


_script = _Script()

_real_flip = pygame.display.flip
_real_update = pygame.display.update
_real_set_mode = pygame.display.set_mode
_real_wait = pygame.event.wait
_real_poll = pygame.event.poll
_real_get_pressed = pygame.key.get_pressed
_real_mouse_pos = pygame.mouse.get_pos
_real_mouse_pressed = pygame.mouse.get_pressed
_to_bytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring


def _capture():
    surface = pygame.display.get_surface()
    digest = ""
    if surface is not None:
        digest = hashlib.sha1(_to_bytes(surface, "RGB")).hexdigest()[:16]
    _write({"frame": _state["frames"], "hash": digest, "input": _script.label})
    _state["frames"] += 1
    _script.after_frame()


def _flip(*args, **kwargs):
    result = _real_flip(*args, **kwargs)
    _capture()
    return result


def _update(*args, **kwargs):
    result = _real_update(*args, **kwargs)
    _capture()
    return result


def _set_mode(*args, **kwargs):
    surface = _real_set_mode(*args, **kwargs)
    _script.size = surface.get_size()
    _write({"window": list(_script.size)})
    return surface


def _wait(*args, **kwargs):
    event = _real_poll()
    while event.type == pygame.NOEVENT:
        _script.skip_ahead()
        event = _real_poll()
    return event


class _Keys:
    """``key.get_pressed()`` with the script's held keys added to the real state."""

    def __init__(self, real):
        self._real = real

    def __getitem__(self, key):
        if key in _script.held:
            return True
        try:
            return self._real[key]
        except (IndexError, KeyError):
            return False

    def __len__(self):
        return len(self._real)


def _get_pressed(*args, **kwargs):
    return _Keys(_real_get_pressed(*args, **kwargs))


def _mouse_get_pos(*args, **kwargs):
    if _script.mouse_pos is None:
        return _real_mouse_pos(*args, **kwargs)
    return _script.mouse_pos


def _mouse_get_pressed(*args, **kwargs):
    real = _real_mouse_pressed(*args, **kwargs)
    if _script.mouse_down:
        return (True,) + tuple(real[1:])
    return real


pygame.display.flip = _flip
pygame.display.update = _update
pygame.display.set_mode = _set_mode
pygame.event.wait = _wait
pygame.key.get_pressed = _get_pressed
pygame.mouse.get_pos = _mouse_get_pos
pygame.mouse.get_pressed = _mouse_get_pressed


def _watchdog():
    """End a run that has drawn nothing, or has gone on too long, from outside the game.

    Needed because a game stuck in a loop that never draws never comes back to anything
    the harness wraps. ``os._exit`` rather than an exception, for the same reason.
    """
    while not _state["ended"]:
        time.sleep(0.05)
        elapsed = time.monotonic() - _started
        if _state["frames"] == 0 and elapsed > NO_FRAME_SECONDS:
            _end("no_frames", _script.label)
        elif elapsed > WALL_SECONDS:
            _end("wall", _script.label)
        else:
            continue
        # Every record line was flushed as it was written, so there is nothing to close.
        os._exit(0)


threading.Thread(target=_watchdog, daemon=True).start()

# Run exactly as ``python src/game.py`` would, except that nothing is reading stdin --
# a real child's window has no console either -- and the dice are loaded the same way
# every time, so the same game gives the same frames.
random.seed(0)
sys.stdin = open(os.devnull, encoding="utf-8")  # noqa: SIM115
sys.argv = [ENTRY]
sys.path[0] = os.path.dirname(os.path.abspath(ENTRY))
try:
    runpy.run_path(ENTRY, run_name="__main__")
except _Finished:
    pass
except SystemExit:
    _end("exit", _script.label)
    raise
except BaseException:
    _end("error", _script.label)
    raise
else:
    _end("returned", _script.label)
