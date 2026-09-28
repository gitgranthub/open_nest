"""A game drawn inside Open Nest: the channel, what it refuses, and real games through it.

Phase 13. Three layers, the same way ``test_playtest.py`` is built:

- what the stream accepts and refuses, driven by a test standing in for the game on the
  other end of the socket -- including a game that sends something hostile;
- the runner's output reading, which is the fix for a game that prints every frame
  freezing once its pipe filled (SPIKES.md section 26);
- real games, run through the real shim under the real process sandbox. Those skip,
  rather than fail, where the sandbox cannot be applied.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import struct
import time
from pathlib import Path

import pytest

from opennest.agent.tools import Toolbox
from opennest.execution import live_view, python_runner
from opennest.execution.live_view import FRAME, HEADER, MAGIC, TITLE, LiveStream
from opennest.execution.python_runner import finished, run_project, stop_project
from opennest.projects.manager import create_project
from opennest.security import process_sandbox
from opennest.security.process_sandbox import sandbox_available

needs_sandbox = pytest.mark.skipif(
    not sandbox_available(), reason="the process sandbox cannot be applied here"
)

#: The starter's orange, as a frame carries it: blue, green, red, opaque.
STARTER_ORANGE = bytes((62, 142, 214, 255))


# ------------------------------------------------------------ the stream, by hand

@pytest.fixture
def stream_and_game():
    """A stream, and the socket the game would hold, with the test playing the game."""
    stream = LiveStream()
    game = socket.socket(fileno=os.dup(stream.child_fd))
    stream.start()
    yield stream, game
    game.close()
    stream.close()


def _message(kind: bytes, width: int, height: int, payload: bytes,
             magic: bytes = MAGIC) -> bytes:
    return HEADER.pack(magic, kind, width, height, len(payload)) + payload


def _until(predicate, seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_a_picture_arrives_whole_and_only_the_newest_is_kept(stream_and_game) -> None:
    stream, game = stream_and_game
    red, blue = b"\x00\x00\xff\xff" * 4, b"\xff\x00\x00\xff" * 4
    game.sendall(_message(FRAME, 2, 2, red) + _message(FRAME, 2, 2, blue))
    assert _until(lambda: stream.latest() is not None and stream.latest().sequence == 2)
    frame = stream.latest()
    assert (frame.width, frame.height, frame.data) == (2, 2, blue)
    assert not stream.broken


def test_the_window_title_is_plain_text(stream_and_game) -> None:
    """A game's caption is shown on a label, so it must not arrive as anything else."""
    stream, game = stream_and_game
    game.sendall(_message(TITLE, 0, 0, b"Eagle\x07 Patrol\n<b>"))
    assert _until(lambda: stream.title != "")
    assert stream.title == "Eagle Patrol<b>"
    assert "\n" not in stream.title and "\x07" not in stream.title


@pytest.mark.parametrize("message, why", [
    (_message(FRAME, 2, 2, b"\x00" * 16, magic=b"EVIL"), "not a picture"),
    (_message(FRAME, 2, 2, b"\x00" * 12), "did not add up"),
    (HEADER.pack(MAGIC, FRAME, 65535, 65535, 0), "too big to show"),
    (HEADER.pack(MAGIC, FRAME, 2, 2, 999), "did not add up"),
    (HEADER.pack(MAGIC, FRAME, 0, 5, 0), "too big to show"),
    (HEADER.pack(MAGIC, TITLE, 0, 0, 100_000), "too long"),
    (HEADER.pack(MAGIC, b"Z", 0, 0, 0), "not a picture"),
])
def test_anything_that_is_not_a_picture_or_a_title_ends_the_stream(
    stream_and_game, message, why
) -> None:
    """Generated code can write whatever it likes to the channel it is given.

    Checked before anything is allocated: the 65535x65535 header claims 12 GB, and the
    stream refuses it from the header alone.
    """
    stream, game = stream_and_game
    game.sendall(message)
    assert stream.wait_finished(3), "the stream kept reading after a bad message"
    assert why in stream.broken
    assert stream.latest() is None


def test_the_end_of_the_game_is_the_end_of_the_stream(stream_and_game) -> None:
    stream, game = stream_and_game
    game.sendall(_message(FRAME, 1, 1, b"\x01\x02\x03\xff"))
    game.close()
    assert stream.wait_finished(3)
    assert not stream.broken
    assert stream.latest().data == b"\x01\x02\x03\xff", "the last picture was thrown away"


def test_the_childs_input_arrives_as_lines_the_shim_can_read(stream_and_game) -> None:
    stream, game = stream_and_game
    stream.send_key("K_LEFT", True, "")
    stream.send_mouse("down", 10, 20, 1)
    stream.release_all()
    game.settimeout(2)
    received = b""
    while received.count(b"\n") < 3:
        received += game.recv(4096)
    lines = [json.loads(line) for line in received.splitlines()]
    assert lines == [
        {"t": "key", "k": "K_LEFT", "d": 1, "u": ""},
        {"t": "mouse", "m": "down", "x": 10, "y": 20, "b": 1},
        {"t": "release"},
    ]


def test_input_never_blocks_open_nest_on_a_game_that_stopped_reading(stream_and_game) -> None:
    """The keys are typed on the GUI thread. A frozen game must not freeze the window."""
    stream, _game = stream_and_game
    started = time.monotonic()
    for _ in range(200_000):
        stream.send_key("K_SPACE", True, " ")
    assert time.monotonic() - started < 10, "sending input waited on the game"


def test_a_stream_that_never_started_closes_cleanly() -> None:
    """The sandbox refused, or the game could not be started: nothing is left open."""
    stream = LiveStream()
    stream.close()
    assert stream.finished


def test_only_a_python_command_can_be_run_this_way() -> None:
    assert live_view.command_for(("python", "src/game.py")) == (
        "python", str(live_view.SHIM), "src/game.py")
    assert live_view.command_for(("arduino-cli", "compile")) is None
    assert live_view.command_for(("python",)) is None


def test_the_shims_own_frames_are_taken_out_of_a_traceback() -> None:
    stderr = (
        "hello from the game\n"
        "Traceback (most recent call last):\n"
        f'  File "{live_view.SHIM}", line 300, in <module>\n'
        "    runpy.run_path(ENTRY, run_name=\"__main__\")\n"
        '  File "<frozen runpy>", line 287, in run_path\n'
        '  File "src/game.py", line 12, in <module>\n'
        "    speed = 5 / 0\n"
        "ZeroDivisionError: division by zero\n"
    )
    cleaned = live_view.without_shim_frames(stderr)
    assert "live_shim" not in cleaned and "runpy" not in cleaned
    assert 'File "src/game.py", line 12' in cleaned
    assert "hello from the game" in cleaned
    assert cleaned.rstrip().endswith("ZeroDivisionError: division by zero")


def test_the_shim_and_open_nest_agree_on_the_message_format() -> None:
    """The shim cannot import this module, so the two copies are compared here."""
    import ast

    source = live_view.SHIM.read_text(encoding="utf-8")
    shim = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        target, value = node.targets[0], node.value
        if isinstance(value, ast.Call) and getattr(value.func, "attr", "") == "Struct":
            value = value.args[0]
        pairs = (zip(target.elts, value.elts) if isinstance(target, ast.Tuple)
                 and isinstance(value, ast.Tuple) else [(target, value)])
        for name, literal in pairs:
            if isinstance(name, ast.Name):
                with contextlib.suppress(ValueError):
                    shim[name.id] = ast.literal_eval(literal)
    assert shim["HEADER"] == HEADER.format
    assert shim["MAGIC"] == MAGIC
    assert (shim["FRAME"], shim["TITLE"]) == (FRAME, TITLE)
    assert shim["MAX_TITLE_BYTES"] == live_view.MAX_TITLE_BYTES
    assert struct.calcsize(HEADER.format) == HEADER.size
    imported = [
        alias.name if isinstance(node, ast.Import) else node.module or ""
        for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [node])
    ]
    assert not [name for name in imported if name.split(".")[0] == "opennest"], (
        "the shim runs in the child's interpreter and must import nothing from Open Nest"
    )


# ------------------------------------------------------------ the runner's output

def test_a_long_run_keeps_what_it_printed_bounded_like_a_short_one() -> None:
    captured = python_runner._Captured()
    text = "".join(f"line {i}\n" for i in range(50_000))
    for start in range(0, len(text), 777):
        captured.add(text[start:start + 777])
    assert captured.text() == python_runner._clip(text)


@needs_sandbox
def test_a_project_that_prints_all_the_time_keeps_running(tmp_path) -> None:
    """The freeze Phase 13 found (SPIKES.md section 26).

    An interactive run was read for its four-second startup and never again, so its
    output piled up in the pipe; when the pipe was full, the next ``print`` blocked and
    the project stood still. This prints 4 KB a step, so the pipe would be full within
    a fraction of a second of the startup check ending.
    """
    project = tmp_path / "noisy"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text(
        "import os, time\n"
        "step = 0\n"
        "while True:\n"
        "    step += 1\n"
        "    print('x' * 4000, flush=True)\n"
        "    # Replaced whole, so the test never reads it half-written.\n"
        "    open('step.tmp', 'w').write(str(step))\n"
        "    os.replace('step.tmp', 'step.txt')\n"
        "    time.sleep(0.01)\n"
    )
    result = run_project(project, ("python", "src/main.py"), interactive=True)
    try:
        assert result.still_running, result.failure_text
        time.sleep(1.5)
        first = int((project / "step.txt").read_text())
        time.sleep(1.0)
        second = int((project / "step.txt").read_text())
        assert second > first, f"the project stopped at step {first}"
    finally:
        stop_project(result)
    ended = finished(result)
    assert ended is not None and result.output.stopped
    assert "characters omitted" in ended.stdout, "the output was not bounded"


# ------------------------------------------------------------ real games

def _game(tmp_path: Path, source: str | None = None):
    project = create_project("Live Test", "games", root=tmp_path)
    if source is not None:
        (project.directory / "src" / "game.py").write_text(source)
    return project


def _player_x(frame) -> int | None:
    for x in range(frame.width):
        for y in range(0, frame.height, 4):
            i = (y * frame.width + x) * 4
            if frame.data[i:i + 4] == STARTER_ORANGE:
                return x
    return None


@needs_sandbox
def test_the_starter_plays_inside_open_nest_and_answers_the_keyboard(tmp_path) -> None:
    """The whole route: the Toolbox's run, the shim, the sandbox, the stream, a key."""
    project = _game(tmp_path)
    started = []
    box = Toolbox(project)
    box.observer = started.append
    result = box.dispatch("run_project", {})
    run = result.run
    try:
        assert result.ok and run.still_running, result.content
        assert run.live is not None, "a Games run was not drawn inside Open Nest"
        playing = [step for step in started if step.kind == "playing"]
        assert playing and playing[0].live is run.live, "the stream was not handed over"
        assert _until(lambda: run.live.latest() is not None)
        assert run.live.title == "My Game"
        frame = run.live.latest()
        assert (frame.width, frame.height) == (640, 480)
        before = _player_x(frame)
        run.live.send_key("K_RIGHT", True)
        assert _until(lambda: (_player_x(run.live.latest()) or 0) > before + 50)
        run.live.send_key("K_RIGHT", False)
    finally:
        stop_project(run)
    assert run.live.wait_finished(5)
    assert run.output.stopped, "an ending Open Nest caused must be known as one"


@needs_sandbox
def test_a_live_run_is_confined_by_exactly_the_ordinary_sandbox(tmp_path, monkeypatch) -> None:
    """The profile does not change: same wrap, no device, no network, the shim in front."""
    seen = []
    real_wrap = python_runner.wrap

    def spy(argv, project_dir, **kwargs):
        seen.append((list(argv), kwargs))
        return real_wrap(argv, project_dir, **kwargs)

    monkeypatch.setattr(python_runner, "wrap", spy)
    project = _game(tmp_path)
    result = run_project(project.directory, ("python", "src/game.py"),
                         interactive=True, live=True)
    try:
        argv, kwargs = seen[-1]
        assert kwargs == {"allow_network": False, "devices": ()}
        assert argv[1:] == [str(live_view.SHIM), "src/game.py"]
        assert process_sandbox.build_profile(project.directory) == \
            process_sandbox.build_profile(project.directory, devices=())
        assert result.live is not None
    finally:
        stop_project(result)


@needs_sandbox
def test_a_crash_during_play_is_reported_with_the_childs_own_traceback(tmp_path) -> None:
    """After the startup check, a crash used to be seen by nobody at all."""
    project = _game(tmp_path, (
        "import pygame\n"
        "pygame.init()\n"
        "screen = pygame.display.set_mode((200, 100))\n"
        "clock = pygame.time.Clock()\n"
        "while True:\n"
        "    pygame.event.get()\n"
        "    screen.fill((0, 0, 0))\n"
        "    pygame.display.flip()\n"
        "    clock.tick(60)\n"
        "    if pygame.time.get_ticks() > 4800:\n"
        "        lives = 3 / 0\n"
    ))
    result = Toolbox(project).dispatch("run_project", {})
    run = result.run
    assert run.still_running, "it should have survived the startup check"
    assert run.live.wait_finished(10)
    run.process.wait(5)
    ended = finished(run)
    assert ended is not None and not ended.ok
    assert not run.output.stopped
    assert 'File "src/game.py", line 11' in ended.failure_text
    assert "ZeroDivisionError" in ended.failure_text
    assert "live_shim" not in ended.failure_text


@needs_sandbox
def test_a_game_that_draws_only_when_a_key_arrives_still_hears_it(tmp_path) -> None:
    """``event.wait`` games sleep inside SDL; the shim waits on the channel instead."""
    project = _game(tmp_path, (
        "import pygame\n"
        "pygame.init()\n"
        "screen = pygame.display.set_mode((100, 50))\n"
        "x = 0\n"
        "def draw():\n"
        "    screen.fill((0, 0, 0))\n"
        "    pygame.draw.rect(screen, (255, 255, 255), (x, 10, 10, 10))\n"
        "    pygame.display.flip()\n"
        "draw()\n"
        "while True:\n"
        "    event = pygame.event.wait()\n"
        "    if event.type == pygame.KEYDOWN and event.key == pygame.K_RIGHT:\n"
        "        x += 20\n"
        "        draw()\n"
    ))
    run = run_project(project.directory, ("python", "src/game.py"),
                      interactive=True, live=True)
    try:
        assert run.still_running, run.failure_text
        assert _until(lambda: run.live.latest() is not None)
        first = run.live.latest().sequence
        run.live.send_key("K_RIGHT", True)
        run.live.send_key("K_RIGHT", False)
        assert _until(lambda: run.live.latest().sequence > first), "the key never arrived"
    finally:
        stop_project(run)


@needs_sandbox
def test_a_game_that_quits_on_escape_ends_by_itself(tmp_path) -> None:
    project = _game(tmp_path)
    run = run_project(project.directory, ("python", "src/game.py"),
                      interactive=True, live=True)
    try:
        assert _until(lambda: run.live.latest() is not None)
        run.live.send_key("K_ESCAPE", True)
        assert run.live.wait_finished(5)
        run.process.wait(5)
        ended = finished(run)
        assert ended.ok and not run.output.stopped
    finally:
        stop_project(run)


@needs_sandbox
def test_a_game_that_writes_junk_to_its_channel_is_caught(tmp_path) -> None:
    """The hostile case, for real: generated code writing to the descriptor it was given."""
    project = _game(tmp_path, (
        "import os, time\n"
        "fd = int(os.environ['OPENNEST_LIVE_FD'])\n"
        "os.write(fd, b'\\xff' * 64)\n"
        "while True:\n"
        "    time.sleep(0.1)\n"
    ))
    run = run_project(project.directory, ("python", "src/game.py"),
                      interactive=True, live=True)
    try:
        assert run.live.wait_finished(5)
        assert "not a picture" in run.live.broken
        assert run.process.poll() is None, "the game is still running; its caller stops it"
    finally:
        stop_project(run)
    assert run.process.poll() is not None


@needs_sandbox
def test_something_that_is_not_a_pygame_game_still_runs(tmp_path) -> None:
    project = _game(tmp_path, "print('no window here')\n")
    run = run_project(project.directory, ("python", "src/game.py"),
                      interactive=True, live=True)
    assert not run.still_running and run.ok, run.failure_text
    assert "no window here" in run.stdout
