"""The bootstrap layer must run on the Python a Mac already has.

macOS still ships Python 3.9, and bootstrap/ is what runs before Open Nest's own
interpreter exists. If these files use syntax newer than 3.9, setup fails on exactly the
machines it is supposed to rescue. See PLAN.md section 2.1.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BOOTSTRAP_DIR = Path(__file__).resolve().parent.parent / "bootstrap"
OLDEST_SUPPORTED = (3, 9)
OLDEST_LABEL = f"{OLDEST_SUPPORTED[0]}.{OLDEST_SUPPORTED[1]}"


def _bootstrap_sources() -> list[Path]:
    return sorted(BOOTSTRAP_DIR.glob("*.py"))


def _oldest_available_python() -> str | None:
    """Find an interpreter at the oldest version bootstrap must support."""
    candidates = [
        shutil.which(f"python{OLDEST_LABEL}"),
        f"/usr/bin/python{OLDEST_LABEL}",
        "/usr/bin/python3",
    ]
    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        try:
            out = subprocess.run(
                [candidate, "-c", 'import sys;print("%d.%d" % sys.version_info[:2])'],
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0 and out.stdout.decode().strip() == OLDEST_LABEL:
            return candidate
    return None


def test_bootstrap_has_sources() -> None:
    assert _bootstrap_sources(), "bootstrap/ should contain Python sources"


@pytest.mark.parametrize("source", _bootstrap_sources(), ids=lambda p: p.name)
def test_compiles_under_oldest_supported_python(source: Path) -> None:
    interpreter = _oldest_available_python()
    if interpreter is None:
        pytest.skip(f"no Python {OLDEST_LABEL} available to check against")

    # compile() rather than py_compile: Apple's system Python writes bytecode to
    # ~/Library/Caches/com.apple.python, which the offline sandbox blocks. Syntax is all
    # this test cares about, and compiling in memory touches no disk at all.
    probe = (
        "import sys;src=open(sys.argv[1]).read();"
        "compile(src, sys.argv[1], 'exec')"
    )
    result = subprocess.run(
        [interpreter, "-B", "-c", probe, str(source)],
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"{source.name} does not compile under Python {OLDEST_LABEL}:\n"
        f"{result.stderr.decode()}"
    )


@pytest.mark.parametrize("source", _bootstrap_sources(), ids=lambda p: p.name)
def test_does_not_import_the_application(source: Path) -> None:
    """bootstrap/ runs before opennest/ is installed, so it cannot depend on it."""
    text = source.read_text(encoding="utf-8")
    offenders = re.findall(r"^\s*(?:from|import)\s+opennest\b", text, flags=re.MULTILINE)
    assert not offenders, f"{source.name} imports the application runtime"


def test_running_interpreter_is_new_enough_for_the_app() -> None:
    """A sanity check on the test environment itself."""
    assert sys.version_info[:2] >= (3, 12)
