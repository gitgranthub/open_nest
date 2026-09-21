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


def test_every_requirements_manifest_is_installed_by_something() -> None:
    """A manifest nothing installs is invisible, and has now bitten twice.

    Phase 7 found ``projects.txt`` installed by nothing, so no profile's starter
    template ran on a fresh Mac. The Phase 8 acceptance pass found the same thing for
    ``macos-apple-silicon.txt`` -- mlx and mlx-lm -- which made the wizard's own model
    download and inference test impossible on a clean install.

    ``dev.txt`` is exempt and says so in its own first line: it is developer tooling
    and the setup launcher must not install pytest onto a family Mac.
    """
    root = BOOTSTRAP_DIR.parent
    manifests = {p.name for p in (root / "requirements").glob("*.txt")}
    manifests.discard("dev.txt")

    installed_by_bootstrap = (BOOTSTRAP_DIR / "bootstrap.py").read_text(encoding="utf-8")
    missing = sorted(name for name in manifests if name not in installed_by_bootstrap)
    assert not missing, (
        f"requirements/{', '.join(missing)} is installed by nothing. "
        f"Either the bootstrap installs it or it should not exist."
    )


def test_the_local_ai_manifest_is_not_required_to_import() -> None:
    """MLX's absence must not stop setup reporting success.

    ``macos-apple-silicon.txt`` is separate from ``base.txt`` precisely so the app and
    the wizard can start and say something useful when MLX is unavailable. Adding it to
    REQUIRED_IMPORTS would turn a recoverable state into a failed installation.
    """
    import sys

    sys.path.insert(0, str(BOOTSTRAP_DIR.parent))
    from bootstrap.bootstrap import REQUIRED_IMPORTS

    assert not any("mlx" in module for module in REQUIRED_IMPORTS)
