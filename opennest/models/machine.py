"""What this Mac is, as one value everything else takes as an argument.

WORKORDER_01's target hardware is an 8 GB Apple silicon Mac; the machine this was
written on has 48 GB. Those two facts are the whole reason this module exists in the
shape it does.

**Detection happens in exactly one function, and nothing else calls it.**
:func:`detect` produces a :class:`MachineProfile`; every decision downstream --
which models to recommend, what to warn about, what the wizard shows -- is a pure
function of that value and is handed one. So the recommendation engine can be tested
against an 8 GB Air, a 16 GB Pro and a 64 GB Studio without any of them being present,
and a developer's own machine cannot quietly become the reference.

Section 23 of the Phase 11 work order asks for this directly: one service owns machine
capability detection, rather than hardware queries scattered across the screens that
happen to need them.

**This is capability detection, not a fingerprint.** Nothing here is sent anywhere,
stored for comparison, or used to identify a machine. It exists to answer "will this
model run here?" and it is re-read rather than remembered -- section 50: the first
machine Open Nest saw is not eternal. Free disk in particular changes hourly.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

#: Baseline Open Nest is designed for. Mirrors ``bootstrap.environment``, which cannot
#: import this module -- the bootstrap runs before the application package exists.
MIN_MEMORY_GB = 8

#: Memory macOS, Open Nest itself and whatever else the family has open are assumed to
#: want. Subtracted before asking whether a model fits, because "will it fit" is a
#: question about what is *free*, not about what is installed. Deliberately generous:
#: the cost of being wrong low is a Mac that swaps for twenty minutes.
SYSTEM_RESERVE_GB = 4.0

#: Timeout for a single ``sysctl``/``ioreg`` call. Measured at 2 ms and 17 ms
#: respectively on one Mac; this is only here so a wedged call cannot hang setup.
_PROBE_TIMEOUT = 5


@dataclass(frozen=True)
class MachineProfile:
    """The normalised capability object of section 23.

    Every field is something a model requirement can be compared against. Nothing is
    here for description alone, except ``chip`` and ``model_identifier``, which a parent
    reads to recognise their own Mac.
    """

    platform: str = "macOS"
    architecture: str = ""
    #: "Apple M4 Pro", "Apple M1". Empty when it could not be read.
    chip: str = ""
    #: "Mac16,7". Apple's own identifier for the model.
    model_identifier: str = ""
    macos_version: str = ""
    memory_gb: float = 0.0
    free_disk_gb: float = 0.0
    cpu_cores: int = 0
    #: 0 means unknown, never "no GPU". On Apple silicon the GPU shares the unified
    #: memory this whole module is really about, so it informs speed rather than fit.
    gpu_cores: int = 0
    #: Whether the local AI engine is importable. Probed, not inferred from the chip:
    #: an Apple silicon Mac whose environment is half-installed has no MLX.
    mlx_available: bool = False

    @property
    def is_apple_silicon(self) -> bool:
        return self.architecture == "arm64"

    @property
    def is_supported(self) -> bool:
        """Whether Open Nest can run local AI here at all."""
        return self.platform == "macOS" and self.is_apple_silicon

    @property
    def usable_memory_gb(self) -> float:
        """Memory a model may plausibly have, after leaving the Mac room to work."""
        return max(0.0, self.memory_gb - SYSTEM_RESERVE_GB)

    def summary(self) -> str:
        """The block the wizard shows a parent. Facts, in their own words."""
        hardware = self.chip or ("Apple silicon" if self.is_apple_silicon else
                                 self.architecture or "unknown")
        return (
            f"Mac              {hardware}\n"
            f"macOS            {self.macos_version or 'unknown'}\n"
            f"Memory           {self.memory_gb:.0f} GB\n"
            f"Free storage     {self.free_disk_gb:.0f} GB"
        )

    def with_free_disk(self, free_disk_gb: float) -> MachineProfile:
        """A copy with storage re-read. The one field that moves on its own."""
        return replace(self, free_disk_gb=free_disk_gb)


def detect(disk_path: Path | str | None = None) -> MachineProfile:
    """Read this Mac. The only function in Open Nest that inspects the hardware."""
    base = _from_bootstrap(disk_path)
    return MachineProfile(
        platform="macOS" if _is_macos() else platform.system(),
        architecture=base.get("arch", platform.machine()),
        chip=_sysctl("machdep.cpu.brand_string"),
        model_identifier=_sysctl("hw.model"),
        macos_version=base.get("macos_version", ""),
        memory_gb=base.get("memory_gb", 0.0),
        free_disk_gb=base.get("free_disk_gb", 0.0),
        cpu_cores=_sysctl_int("hw.ncpu"),
        gpu_cores=_gpu_cores(),
        mlx_available=mlx_available(),
    )


def mlx_available() -> bool:
    """Whether the local AI engine is installed.

    A spec lookup rather than an import: importing MLX initialises the framework and
    costs real time, and what this answers is "is it installed", not "does it work".
    Whether it *works* is the download verification's job, and that one runs a real
    inference through the provider the application itself uses.
    """
    import importlib.util

    try:
        return importlib.util.find_spec("mlx_lm") is not None
    except (ImportError, ValueError):
        return False


def problems(machine: MachineProfile, *, need_disk_gb: float = 0.0) -> list[str]:
    """Why this Mac may struggle, in parent-readable language. Empty when it is fine.

    A warning, never a refusal -- WORKORDER_01 section 35A: an unsupported Mac is not
    always a broken one, and the parent is the one who decides.
    """
    found: list[str] = []
    if machine.platform != "macOS":
        found.append("Open Nest runs on macOS.")
    if not machine.is_apple_silicon:
        found.append(
            f"Open Nest needs an Apple silicon Mac (M1 or newer). "
            f"This Mac reports '{machine.architecture or 'an unknown processor'}'."
        )
    if machine.memory_gb and machine.memory_gb < MIN_MEMORY_GB:
        found.append(
            f"Open Nest needs at least {MIN_MEMORY_GB} GB of memory. "
            f"This Mac has about {machine.memory_gb:.0f} GB."
        )
    if need_disk_gb and machine.free_disk_gb and machine.free_disk_gb < need_disk_gb:
        found.append(
            f"This needs about {need_disk_gb:.0f} GB of free storage. "
            f"This Mac has about {machine.free_disk_gb:.0f} GB free."
        )
    if machine.is_supported and not machine.mlx_available:
        found.append(
            "The local AI engine is not installed, so Open Nest cannot run a model on "
            "this Mac yet. Running Setup again installs it."
        )
    return found


# --------------------------------------------------------------------------- probing

def _is_macos() -> bool:
    import sys

    return sys.platform == "darwin"


def _from_bootstrap(disk_path) -> dict:
    """Memory, storage, architecture and macOS version, from the bootstrap's detection.

    Imported lazily and tolerantly for the reason the wizard already did it this way:
    the bootstrap is the authority on what this Mac is and must stay importable on
    Python 3.9, so the arrow points one way only -- ``opennest`` may import
    ``bootstrap``, never the reverse.
    """
    try:
        from bootstrap import environment

        info = environment.detect_machine(str(disk_path) if disk_path else None)
    except Exception:
        return {}
    return {
        "arch": info.arch,
        "macos_version": info.macos_version,
        "memory_gb": info.memory_gb,
        "free_disk_gb": info.free_disk_gb,
    }


def _sysctl(name: str) -> str:
    if not _is_macos() or not shutil.which("sysctl"):
        return ""
    try:
        out = subprocess.run(
            ["sysctl", "-n", name],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.decode("utf-8", "replace").strip()


def _sysctl_int(name: str) -> int:
    try:
        return int(_sysctl(name))
    except ValueError:
        return 0


def _gpu_cores() -> int:
    """GPU core count, when the system will say. 0 when it will not.

    ``ioreg -rc AGXAccelerator -d 1`` rather than ``ioreg -l``: the full dump is
    megabytes and the scoped query is milliseconds.
    """
    if not _is_macos() or not shutil.which("ioreg"):
        return 0
    try:
        out = subprocess.run(
            ["ioreg", "-rc", "AGXAccelerator", "-d", "1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        if "gpu-core-count" in line:
            digits = "".join(c for c in line.split("=")[-1] if c.isdigit())
            if digits:
                return int(digits)
    return 0
