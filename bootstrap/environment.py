"""Machine inspection and Python environment management.

Must stay importable and runnable on Python 3.9 (PLAN.md section 2.1). ``from __future__
import annotations`` makes annotations strings, so modern syntax like ``str | None`` is
safe here even though 3.9 cannot evaluate it.
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import subprocess
import sys

MIN_PYTHON = (3, 12)

#: Mirrors opennest.APP_NAME. Duplicated deliberately: the bootstrap layer runs before
#: the application package exists and must not import it.
APP_NAME = "Open Nest"

#: Baseline hardware Open Nest is designed for (WORKORDER_01 "Initial target hardware").
MIN_MEMORY_GB = 8
#: Enough room for the environment plus one local model, with headroom.
MIN_FREE_DISK_GB = 12

_PROBE = 'import platform,sys;print("%d.%d.%d" % sys.version_info[:3]);print(platform.machine())'


class SetupError(Exception):
    """A setup step failed in a way the parent needs to be told about."""


class MachineInfo:
    """What the setup launcher needs to know about this Mac."""

    def __init__(
        self,
        macos_version: str,
        arch: str,
        memory_gb: float,
        free_disk_gb: float,
    ) -> None:
        self.macos_version = macos_version
        self.arch = arch
        self.memory_gb = memory_gb
        self.free_disk_gb = free_disk_gb

    @property
    def is_apple_silicon(self) -> bool:
        return self.arch == "arm64"

    @property
    def is_macos(self) -> bool:
        return sys.platform == "darwin"

    def problems(self) -> list[str]:
        """Reasons this Mac cannot run Open Nest, in parent-readable language."""
        found: list[str] = []
        if not self.is_macos:
            found.append("Open Nest runs on macOS.")
        if not self.is_apple_silicon:
            found.append(
                f"Open Nest needs an Apple silicon Mac (M1 or newer). "
                f"This Mac reports '{self.arch}'."
            )
        if self.memory_gb and self.memory_gb < MIN_MEMORY_GB:
            found.append(
                f"Open Nest needs at least {MIN_MEMORY_GB} GB of memory. "
                f"This Mac has about {self.memory_gb:.0f} GB."
            )
        if self.free_disk_gb and self.free_disk_gb < MIN_FREE_DISK_GB:
            found.append(
                f"Open Nest needs about {MIN_FREE_DISK_GB} GB of free storage for the "
                f"environment and a local AI model. "
                f"This Mac has about {self.free_disk_gb:.0f} GB free."
            )
        return found


def detect_machine(disk_path: str | None = None) -> MachineInfo:
    return MachineInfo(
        macos_version=platform.mac_ver()[0],
        arch=platform.machine(),
        memory_gb=_memory_gb(),
        free_disk_gb=_free_disk_gb(disk_path or os.path.expanduser("~")),
    )


def _memory_gb() -> float:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        return (page_size * pages) / (1024.0**3)
    except (ValueError, OSError, AttributeError):
        return 0.0


def _free_disk_gb(path: str) -> float:
    try:
        return shutil.disk_usage(path).free / (1024.0**3)
    except OSError:
        return 0.0


def probe_python(executable: str) -> tuple[tuple[int, int, int], str] | None:
    """Return ``((major, minor, micro), arch)`` for an interpreter, or None if unusable."""
    try:
        out = subprocess.run(
            [executable, "-c", _PROBE],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    fields = out.stdout.decode("utf-8", "replace").split()
    if len(fields) < 2:
        return None
    try:
        parts = tuple(int(n) for n in fields[0].split("."))
    except ValueError:
        return None
    if len(parts) != 3:
        return None
    return parts, fields[1]


def app_support_dir() -> str:
    """Mirrors opennest.paths.app_support_dir(), for the same reason as APP_NAME."""
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME)


def managed_pythons() -> list[str]:
    """Interpreters Open Nest installed for itself (see bootstrap.python_setup)."""
    pattern = os.path.join(app_support_dir(), "python", "*", "bin", "python3")
    return sorted(glob.glob(pattern), reverse=True)


def candidate_pythons() -> list[str]:
    """Interpreters worth probing, best-guess first. May contain paths that do not exist."""
    # Open Nest's own interpreter wins: it is the one setup verified.
    found: list[str] = managed_pythons()
    found.append(sys.executable)

    for name in ("python3.14", "python3.13", "python3.12"):
        found.append("/opt/homebrew/bin/" + name)
        found.append("/usr/local/bin/" + name)
        which = shutil.which(name)
        if which:
            found.append(which)

    for minor in (14, 13, 12):
        found.append(f"/Library/Frameworks/Python.framework/Versions/3.{minor}/bin/python3")

    which_any = shutil.which("python3")
    if which_any:
        found.append(which_any)

    ordered: list[str] = []
    for path in found:
        if path and path not in ordered:
            ordered.append(path)
    return ordered


def find_python(minimum: tuple[int, int] = MIN_PYTHON) -> str | None:
    """Find an installed interpreter new enough to run Open Nest.

    Returns None when the Mac has nothing suitable, in which case the caller installs
    Open Nest's own copy (bootstrap.python_setup).
    """
    for path in candidate_pythons():
        result = probe_python(path)
        if result is None:
            continue
        version, arch = result
        if version[:2] >= minimum and arch == platform.machine():
            return path
    return None


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def venv_dir(root: str | None = None) -> str:
    return os.path.join(root or repo_root(), ".venv")


def venv_python(root: str | None = None) -> str:
    return os.path.join(venv_dir(root), "bin", "python")


def venv_is_usable(root: str | None = None, minimum: tuple[int, int] = MIN_PYTHON) -> bool:
    executable = venv_python(root)
    if not os.path.exists(executable):
        return False
    result = probe_python(executable)
    return result is not None and result[0][:2] >= minimum


def create_venv(python_exe: str, root: str | None = None) -> None:
    _run([python_exe, "-m", "venv", venv_dir(root)], "create the Python environment")


def install_requirements(requirement_files: list[str], root: str | None = None) -> None:
    executable = venv_python(root)
    _run(
        [executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        "update the packaging tools",
    )
    for path in requirement_files:
        _run(
            [executable, "-m", "pip", "install", "-r", path],
            f"install {os.path.basename(path)}",
        )


def verify_imports(modules: tuple[str, ...], root: str | None = None) -> list[str]:
    """Return the subset of ``modules`` that the environment cannot import."""
    executable = venv_python(root)
    missing: list[str] = []
    for module in modules:
        try:
            result = subprocess.run(
                [executable, "-c", f"import {module}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            missing.append(module)
            continue
        if result.returncode != 0:
            missing.append(module)
    return missing


def _run(command: list[str], description: str) -> None:
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        raise SetupError(f"Could not {description}.\n\n{exc}") from exc
    if result.returncode != 0:
        output = result.stdout.decode("utf-8", "replace").strip()
        raise SetupError(f"Could not {description}.\n\n{_last_lines(output, 20)}")


def _last_lines(text: str, count: int) -> str:
    return "\n".join(text.splitlines()[-count:])
