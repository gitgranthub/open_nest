"""Installing the Arduino toolchain from the wizard — decision D7.

Phase 7 built the compile path and pinned the toolchain, but only
``scripts/fetch.sh arduino`` could install it, which is a developer command. A parent
had no way to get it, so the Arduino profile shipped able to create a project and
unable to build one. This is the same install, driven from the wizard.

**D7 is resolved as AVR only.** arduino-cli v1.5.1 plus the `arduino:avr` core, about
341 MB together, behind an explicit choice rather than in the default install. A child
with an ESP32 or a Pico still gets a board list that does not contain their board --
honest but unhelpful, and the reason the decision stays open for a later phase. It is
AVR alone because 324 MB is the one core size that has actually been measured
(SPIKES.md section 14B); offering a menu of cores would mean printing sizes nobody has
checked, which is not how anything else in this repository is sized.

Everything the shell script got right is kept, and the two that matter are not
obvious:

- **Pinned to a release tag and verified against Arduino's published SHA256**, never
  "latest" -- the same rule ``models.json`` follows for model weights. A checksum
  mismatch refuses to install rather than warning.
- **Every ``arduino-cli`` invocation names its data directory**, including ones that
  only read. Without it the tool creates ``~/Library/Arduino15`` and containment stops
  being true (SPIKES.md section 14B, tripped twice while measuring). That is
  ``arduino._environment``'s job and this module reuses it rather than building a
  second copy.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from opennest import paths
from opennest.execution import arduino

#: Pinned, like every other third-party artifact here.
VERSION = "1.5.1"

#: Measured in SPIKES.md section 14B: ~17 MB for the binary, 324 MB for the AVR core.
APPROXIMATE_MB = 341

#: The only core installed. See the module docstring for why there is not a menu.
CORE = "arduino:avr"

_BASE = f"https://github.com/arduino/arduino-cli/releases/download/v{VERSION}"

#: Long enough for 17 MB on a slow connection.
TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ToolchainResult:
    ok: bool
    message: str


def is_installed() -> bool:
    """Whether arduino-cli can actually be run -- attempted, not assumed."""
    return arduino.available()


def describe() -> str:
    return arduino.describe()


def archive_name(machine: str | None = None) -> str | None:
    """The release asset for this Mac, or None if Arduino does not publish one."""
    architecture = machine or os.uname().machine
    suffix = {"arm64": "macOS_ARM64", "x86_64": "macOS_64bit"}.get(architecture)
    return f"arduino-cli_{VERSION}_{suffix}.tar.gz" if suffix else None


def install(
    *,
    on_progress: Callable[[str], None] | None = None,
    tools_dir: Path | None = None,
) -> ToolchainResult:
    """Download, verify and install arduino-cli and the AVR core.

    Reports progress as sentences rather than a percentage: this is two downloads and
    an extraction, and the core install reports nothing useful to attach a bar to.
    """
    say = on_progress or (lambda message: None)
    tools = Path(tools_dir) if tools_dir is not None else paths.tools_dir()
    target = tools / f"arduino-cli-{VERSION}"

    if (target / "arduino-cli").exists():
        say("The Arduino tools are already installed.")
        return _install_core(target, tools, say)

    asset = archive_name()
    if asset is None:
        return ToolchainResult(
            False, "Arduino does not publish its tools for this kind of Mac."
        )

    tools.mkdir(parents=True, exist_ok=True)
    say("Downloading the Arduino tools (about 17 MB)...")
    try:
        expected = _published_checksum(asset)
        payload = _fetch(f"{_BASE}/{asset}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return ToolchainResult(
            False,
            "The Arduino tools could not be downloaded. This step needs the internet."
            f"\n\n{type(exc).__name__}",
        )

    actual = hashlib.sha256(payload).hexdigest()
    if not expected or actual != expected:
        # Refuse, never warn. The same stance grant_devices takes about a port name:
        # this came from outside, so it is checked rather than trusted.
        return ToolchainResult(
            False,
            "The Arduino tools did not match the checksum Arduino publishes for them, "
            "so nothing was installed.",
        )

    say("Checking and unpacking...")
    try:
        _extract(payload, target)
    except (OSError, tarfile.TarError) as exc:
        shutil.rmtree(target, ignore_errors=True)
        return ToolchainResult(False, f"The Arduino tools could not be unpacked.\n\n{exc}")

    return _install_core(target, tools, say)


def _install_core(target: Path, tools: Path, say: Callable[[str], None]) -> ToolchainResult:
    """Install the board core. The only part that needs network at compile time."""
    binary = target / "arduino-cli"
    if not binary.exists():
        return ToolchainResult(False, "The Arduino tools are not where they should be.")

    say(f"Installing the {CORE} board support (about 324 MB). This takes a few minutes...")
    try:
        result = subprocess.run(
            [str(binary), "core", "install", CORE],
            capture_output=True,
            timeout=1800,
            env=_environment(tools),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ToolchainResult(False, f"The board support could not be installed.\n\n{exc}")

    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()[-400:]
        return ToolchainResult(False, f"The board support could not be installed.\n\n{detail}")

    if not arduino.available():
        return ToolchainResult(
            False, "The Arduino tools installed but could not be run."
        )
    return ToolchainResult(True, "The Arduino tools are installed.")


def _environment(tools: Path) -> dict:
    """arduino-cli's data directories, kept inside the containment root.

    Reuses ``arduino._environment`` so there is one definition of where this tool is
    allowed to write. Left to itself arduino-cli creates ``~/Library/Arduino15`` on its
    very first run, including for commands that read nothing.
    """
    environment = arduino._environment()
    # During installation ``paths.tools_dir()`` may be overridden for a test, so the
    # caller's directory wins over the module's default.
    for key, sub in (
        ("ARDUINO_DIRECTORIES_DATA", "arduino-data"),
        ("ARDUINO_DIRECTORIES_USER", "arduino-user"),
        ("ARDUINO_DIRECTORIES_DOWNLOADS", "arduino-downloads"),
    ):
        if key in environment:
            environment[key] = str(tools / sub)
    return environment


def _published_checksum(asset: str) -> str | None:
    """Arduino's own checksum file for this release."""
    text = _fetch(f"{_BASE}/{VERSION}-checksums.txt").decode("utf-8", "replace")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].endswith(asset):
            return parts[0]
    return None


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        return response.read()


def _extract(payload: bytes, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=True) as scratch:
        scratch.write(payload)
        scratch.flush()
        with tarfile.open(scratch.name, "r:gz") as archive:
            _safe_extract(archive, target)
    (target / "arduino-cli").chmod(0o755)


def _safe_extract(archive: tarfile.TarFile, target: Path) -> None:
    """Extract, refusing any member that would land outside ``target``.

    The archive is checksum-verified before this runs, so this is belt and braces --
    but an extractor that can be talked into writing outside its directory is exactly
    the kind of thing ``security/sandbox.py`` exists to prevent elsewhere, and it costs
    four lines to not have one.
    """
    root = target.resolve()
    for member in archive.getmembers():
        destination = (root / member.name).resolve()
        if not destination.is_relative_to(root):
            raise tarfile.TarError(f"refusing to extract {member.name} outside {root}")
        if member.issym() or member.islnk():
            raise tarfile.TarError(f"refusing to extract the link {member.name}")
    archive.extractall(root)  # noqa: S202 - every member checked above
