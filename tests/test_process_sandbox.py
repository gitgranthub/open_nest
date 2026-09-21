"""The outer boundary: what a child's project process can and cannot do.

These tests run real code in a real sandbox. They are the evidence for the claim that
generated code cannot reach the network or write outside its project -- a claim the path
checks in opennest.security.sandbox cannot make, because they never see a process.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opennest.execution.python_runner import run_project
from opennest.security.process_sandbox import (
    SandboxUnavailable,
    build_profile,
    sandbox_available,
    wrap,
)

pytestmark = pytest.mark.skipif(
    not sandbox_available(), reason="macOS Seatbelt not available"
)


def _run(project: Path, code: str):
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "src" / "main.py").write_text(code)
    return run_project(project, ("python", "src/main.py"), timeout=40)


def test_project_code_cannot_open_a_socket(tmp_path: Path) -> None:
    result = _run(tmp_path, (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 443), timeout=5)\n"
        "    print('REACHED')\n"
        "except OSError:\n"
        "    print('BLOCKED')\n"
    ))
    assert "BLOCKED" in result.stdout, result.stdout + result.stderr


def test_project_code_cannot_resolve_dns(tmp_path: Path) -> None:
    result = _run(tmp_path, (
        "import socket\n"
        "try:\n"
        "    socket.gethostbyname('example.com')\n"
        "    print('REACHED')\n"
        "except OSError:\n"
        "    print('BLOCKED')\n"
    ))
    assert "BLOCKED" in result.stdout, result.stdout + result.stderr


def test_project_code_cannot_write_outside_the_project(tmp_path: Path) -> None:
    result = _run(tmp_path, (
        "import pathlib\n"
        "try:\n"
        "    p = pathlib.Path.home() / 'opennest-escape.txt'\n"
        "    p.write_text('escaped'); p.unlink()\n"
        "    print('WROTE')\n"
        "except OSError:\n"
        "    print('BLOCKED')\n"
    ))
    assert "BLOCKED" in result.stdout, result.stdout + result.stderr


def test_project_code_cannot_read_and_exfiltrate_via_write(tmp_path: Path) -> None:
    """Reads are permitted, so the denial that matters is getting data back out."""
    result = _run(tmp_path, (
        "import pathlib\n"
        "try:\n"
        "    data = pathlib.Path('/etc/hosts').read_text()[:20]\n"
        "except OSError:\n"
        "    data = '(unreadable)'\n"
        "try:\n"
        "    (pathlib.Path.home() / 'stolen.txt').write_text(data)\n"
        "    print('EXFILTRATED')\n"
        "except OSError:\n"
        "    print('BLOCKED')\n"
    ))
    assert "BLOCKED" in result.stdout, result.stdout + result.stderr


def test_project_code_can_write_inside_its_own_project(tmp_path: Path) -> None:
    """Confinement must not stop a project doing its actual job."""
    result = _run(tmp_path, (
        "import pathlib\n"
        "pathlib.Path('output.txt').write_text('a result')\n"
        "print('WROTE OK')\n"
    ))
    assert result.ok and "WROTE OK" in result.stdout, result.stderr
    assert (tmp_path / "output.txt").read_text() == "a result"


def test_ordinary_project_output_is_unaffected(tmp_path: Path) -> None:
    result = _run(tmp_path, "print('hello from the project')\n")
    assert result.ok and "hello from the project" in result.stdout


def test_a_crash_still_reports_its_traceback(tmp_path: Path) -> None:
    """The repair loop depends on seeing the real error through the sandbox."""
    result = _run(tmp_path, "raise ValueError('asteroid_speed must be a number')\n")
    assert not result.ok
    assert "asteroid_speed" in result.stderr


def test_profile_confines_writes_to_the_project(tmp_path: Path) -> None:
    profile = build_profile(tmp_path)
    assert "(deny network*)" in profile
    assert "(deny file-write*)" in profile
    assert str(tmp_path.resolve()) in profile


def test_an_ordinary_run_is_granted_no_serial_device(tmp_path: Path) -> None:
    """The privileged-action machinery must be invisible to normal project execution.

    An Arduino upload may write to one approved serial port. Nothing else may, and the
    profile a child's code runs under has to be exactly what it was before that
    capability existed -- not "the same in spirit".
    """
    plain = build_profile(tmp_path)
    assert "/dev/cu" not in plain
    assert plain == build_profile(tmp_path, devices=())


def test_a_privileged_action_is_granted_exactly_the_port_it_was_given(
    tmp_path: Path,
) -> None:
    granted = build_profile(tmp_path, devices=("/dev/cu.usbmodem1101",))
    assert '(literal "/dev/cu.usbmodem1101")' in granted
    # Still confined in every other respect: a privileged action is granted one more
    # thing, not let out.
    assert "(deny network*)" in granted
    assert "(deny file-write*)" in granted
    # And only the one port, not the family.
    assert "/dev/cu.usbmodem1102" not in granted


@pytest.mark.parametrize(
    "candidate",
    [
        "/dev/disk0",
        "/etc/passwd",
        "/dev/cu.ok/../../etc/passwd",
        "~/secrets",
        "/dev/ttys000",
        "/dev/",
        "",
    ],
)
def test_only_a_serial_port_can_ever_be_granted(tmp_path: Path, candidate: str) -> None:
    """The port string comes from outside the application, so it is validated.

    WORKORDER_01 section 19 and the Phase 7 design rule: a privileged action gets the
    minimum access it needs. "The minimum" has to be enforced, not intended -- otherwise
    a bad port string is a way to ask for arbitrary write access.
    """
    with pytest.raises(ValueError):
        build_profile(tmp_path, devices=(candidate,))


def test_run_project_refuses_rather_than_running_with_a_bad_device(
    tmp_path: Path,
) -> None:
    """A rejected grant must stop the run, not fall back to running it unconfined."""
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text("print('should not run')")
    result = run_project(
        tmp_path, ("python", "src/main.py"), timeout=20, devices=("/etc/passwd",)
    )
    assert not result.ok
    assert "should not run" not in result.stdout


def test_network_can_be_allowed_for_a_future_parent_permission(tmp_path: Path) -> None:
    """WORKORDER_01 section 25 makes this a parent control. Off everywhere in V1."""
    assert "(deny network*)" not in build_profile(tmp_path, allow_network=True)


def test_wrap_raises_rather_than_returning_an_unconfined_command(
    tmp_path: Path, monkeypatch
) -> None:
    """Fail closed: a caller must not be able to run a project by ignoring a flag."""
    monkeypatch.setattr(
        "opennest.security.process_sandbox.sandbox_available", lambda: False
    )
    with pytest.raises(SandboxUnavailable):
        wrap(["echo", "hi"], tmp_path)


def test_run_refuses_when_the_sandbox_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('should not run')")
    monkeypatch.setattr(
        "opennest.security.process_sandbox.sandbox_available", lambda: False
    )
    result = run_project(tmp_path, ("python", "src/main.py"))
    assert not result.ok
    assert "did not run the project" in result.stderr
    assert "should not run" not in result.stdout
