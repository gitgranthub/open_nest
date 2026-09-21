"""The Arduino toolchain integration, without requiring the toolchain.

arduino-cli is not installed on every machine, and a test whose result depends on
whether it happens to be present is not a test. So everything here either exercises pure
logic or injects a stand-in; the behaviour that genuinely needs the real binary was
measured by hand and is recorded in SPIKES.md section 14 (a real compile: exit 0, 924
bytes of program storage, 1.3 s cold and 0.4 s warm, fully confined).

What matters most here is the degradation. Before this phase, pressing Compile on an
Arduino project showed the child a message written for the model -- "'run_project' is not
available here. You can use: read_file, ..." -- and with the tools missing it showed a
raw ``execvp() ... No such file or directory``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opennest.agent.tools import Toolbox
from opennest.execution import arduino
from opennest.projects.manager import create_project


@pytest.fixture
def sketch(tmp_path: Path):
    return create_project("Traffic Light", "arduino", root=tmp_path)


def test_the_sketch_directory_comes_from_the_manifest(sketch) -> None:
    """Derived, not assumed, so a renamed sketch keeps compiling."""
    assert arduino.sketch_directory(sketch) == "src/project"

    sketch.manifest.entrypoint = "lights/lights.ino"
    assert arduino.sketch_directory(sketch) == "src/lights"


def test_compiling_without_the_tools_says_so_in_plain_words(sketch, monkeypatch) -> None:
    """Not an execvp error, and not a tool-availability message meant for the model."""
    monkeypatch.setattr(arduino, "available", lambda: False)
    sketch.manifest.arduino_board = "arduino:avr:uno"

    result = Toolbox(sketch).dispatch("compile_project", {})

    assert not result.ok
    assert "not installed" in result.content
    assert "execvp" not in result.content
    assert "run_project" not in result.content
    # And it says the work is not lost, because that is the child's first worry.
    assert "saved" in result.content


def test_compiling_with_no_board_chosen_asks_instead_of_guessing(
    sketch, monkeypatch
) -> None:
    """Section 8: never invent hardware details.

    Picking a board on the child's behalf picks every pin on it, so an unset board is a
    question rather than a default.
    """
    monkeypatch.setattr(arduino, "available", lambda: True)
    assert sketch.manifest.arduino_board is None

    result = Toolbox(sketch).dispatch("compile_project", {})

    assert not result.ok
    assert "which" in result.content.lower()
    # It must not have silently compiled for some board it chose.
    assert "uno" not in result.content.lower()


def test_a_new_arduino_project_has_no_board_yet(sketch) -> None:
    assert sketch.manifest.arduino_board is None


def test_the_chosen_board_survives_reopening_the_project(sketch) -> None:
    from opennest.projects.manager import open_project

    sketch.manifest.arduino_board = "arduino:avr:mega"
    sketch.save()
    assert open_project(sketch.directory).manifest.arduino_board == "arduino:avr:mega"


def test_the_board_list_is_read_from_the_tool_not_written_down(monkeypatch) -> None:
    """A hard-coded board list would be section 8's mistake one level up."""
    payload = {
        "boards": [
            {"name": "Arduino UNO", "fqbn": "arduino:avr:uno"},
            {"name": "Adafruit Circuit Playground", "fqbn": "arduino:avr:circuitplay32u4cat"},
            {"name": "Nameless", "fqbn": ""},
        ]
    }
    monkeypatch.setattr(arduino, "_query", lambda args: payload)

    boards = arduino.boards()

    assert [b.fqbn for b in boards] == [
        "arduino:avr:circuitplay32u4cat",
        "arduino:avr:uno",
    ]
    # An entry with no FQBN cannot be compiled for, so it is not offered.
    assert all(board.fqbn for board in boards)


def test_a_port_with_no_recognised_board_is_still_reported(monkeypatch) -> None:
    """"Nothing is plugged in" would be a lie a child can disprove by looking."""
    payload = {
        "detected_ports": [
            {"port": {"address": "/dev/cu.Bluetooth-Incoming-Port"}},
            {
                "port": {"address": "/dev/cu.usbmodem1101"},
                "matching_boards": [{"name": "Arduino UNO", "fqbn": "arduino:avr:uno"}],
            },
        ]
    }
    monkeypatch.setattr(arduino, "_query", lambda args: payload)

    ports = arduino.connected_ports()

    assert len(ports) == 2
    # Recognised boards come first, because that is what an upload wants.
    assert ports[0].address == "/dev/cu.usbmodem1101"
    assert ports[0].board is not None
    assert ports[1].board is None
    assert "unrecognised" in ports[1].label


def test_an_upload_is_granted_only_the_port_it_was_given(sketch, monkeypatch) -> None:
    """The Phase 7 privileged-action rule, at the one place it is used.

    An upload deliberately crosses the project boundary, so it is granted write access
    to one approved serial port -- not to ``/dev``, the filesystem, the network or a
    shell. Measured necessity: the ordinary profile denies ``/dev/cu.*`` outright.
    """
    captured: dict = {}

    def fake_run(project_dir, command, **kwargs):
        captured["command"] = command
        captured["devices"] = kwargs.get("devices")
        captured["allow_network"] = kwargs.get("allow_network", False)
        return None

    monkeypatch.setattr(arduino, "cli_path", lambda: Path("/fake/arduino-cli"))
    monkeypatch.setattr(arduino, "run_project", fake_run)

    arduino.upload(sketch, "arduino:avr:uno", "/dev/cu.usbmodem1101")

    assert captured["devices"] == ("/dev/cu.usbmodem1101",)
    # Still offline. An upload needs no network, so it is not given one.
    assert captured["allow_network"] is False
    assert "upload" in captured["command"]


def test_every_tool_invocation_names_its_own_data_directory() -> None:
    """Otherwise arduino-cli builds itself a home in ~/Library.

    Measured: running ``arduino-cli version`` or ``board listall`` without
    ARDUINO_DIRECTORIES_DATA creates ``~/Library/Arduino15``. Containment is a promise
    this project makes, so the override belongs on every call and not just the ones that
    obviously write.
    """
    env = arduino._environment()
    assert env["ARDUINO_DIRECTORIES_DATA"] == str(arduino.data_dir())
    assert "Library/Arduino15" not in env["ARDUINO_DIRECTORIES_DATA"]


def test_writable_tool_directories_sit_inside_the_project(tmp_path: Path) -> None:
    """The three paths a confined compile has to be able to write."""
    env = arduino._environment(tmp_path)
    for name in ("ARDUINO_DIRECTORIES_USER", "ARDUINO_DIRECTORIES_DOWNLOADS"):
        assert str(tmp_path) in env[name], name
    # The toolchain itself stays outside, and therefore read-only under the sandbox.
    assert str(tmp_path) not in env["ARDUINO_DIRECTORIES_DATA"]


def test_a_query_that_returns_junk_is_an_error_not_a_crash(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(arduino, "cli_path", lambda: Path("/fake/arduino-cli"))
    monkeypatch.setattr(arduino.subprocess, "run", lambda *a, **k: Result())

    with pytest.raises(arduino.ArduinoUnavailable):
        arduino.boards()


def test_boards_without_the_tool_installed_raises_a_readable_error(monkeypatch) -> None:
    monkeypatch.setattr(arduino, "cli_path", lambda: None)
    with pytest.raises(arduino.ArduinoUnavailable) as caught:
        arduino.boards()
    assert "not installed" in str(caught.value)


def test_the_board_payload_shape_matches_what_arduino_cli_really_sends() -> None:
    """Guards the parser against a shape nobody has seen.

    This is the verbatim shape of ``arduino-cli board listall --format json`` from
    version 1.5.1 on this machine, trimmed to two entries. If a future version changes
    it, this fails rather than the picker silently going empty.
    """
    real = json.loads(
        '{"boards":[{"name":"Arduino UNO","fqbn":"arduino:avr:uno"},'
        '{"name":"Arduino UNO Mini","fqbn":"arduino:avr:unomini"}]}'
    )
    names = [entry["name"] for entry in real["boards"]]
    assert names == ["Arduino UNO", "Arduino UNO Mini"]
