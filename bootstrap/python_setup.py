"""Obtain a Python interpreter for Open Nest without an administrator password.

macOS ships Python 3.9, and Open Nest needs 3.12+. Asking a parent to install Python
themselves means either a Terminal session or an installer that prompts for an admin
password -- both of which WORKORDER_01 section 35A rules out.

So Open Nest brings its own. A standalone CPython build is downloaded into Open Nest's
application-support directory, verified against a published checksum, and used only by
Open Nest. It touches nothing else on the Mac, and uninstalling is deleting one folder.

Python 3.9-compatible, standard library only. See PLAN.md decision D5.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from typing import Callable

from bootstrap.environment import SetupError, app_support_dir, probe_python

#: A pinned build, never "whatever is newest". Checksum published by the project at
#: https://github.com/astral-sh/python-build-standalone/releases/download/20260901/SHA256SUMS
#:
#: 3.12 rather than a newer release because it has the widest wheel availability for
#: PySide6, mlx, pygame, pandas and matplotlib. Revisit deliberately, not automatically.
PINNED_VERSION = "3.12.14"
PINNED_RELEASE = "20260901"
PINNED_ASSET = "cpython-3.12.14+20260901-aarch64-apple-darwin-install_only.tar.gz"
PINNED_SHA256 = "3ee3ee547cedfeb7c2b16b2b7156039f7b470bb8f857e226fd3d2eb11db83c76"
PINNED_SIZE_BYTES = 25135464

_RELEASE_URL = (
    f"https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PINNED_RELEASE}/{PINNED_ASSET}"
)

#: Called with (bytes_downloaded, total_bytes). total_bytes is 0 when unknown.
ProgressCallback = Callable[[int, int], None]


def managed_root() -> str:
    return os.path.join(app_support_dir(), "python")


def managed_install_dir(version: str = PINNED_VERSION) -> str:
    return os.path.join(managed_root(), version)


def managed_python(version: str = PINNED_VERSION) -> str:
    return os.path.join(managed_install_dir(version), "bin", "python3")


def is_installed(version: str = PINNED_VERSION) -> bool:
    """True when a managed interpreter exists and actually runs."""
    executable = managed_python(version)
    if not os.path.exists(executable):
        return False
    return probe_python(executable) is not None


def install(
    progress: ProgressCallback | None = None,
    version: str = PINNED_VERSION,
) -> str:
    """Download, verify and unpack the pinned interpreter. Returns its path.

    Safe to call when it is already installed -- that case returns immediately without
    downloading anything.
    """
    if is_installed(version):
        return managed_python(version)

    destination = managed_install_dir(version)
    os.makedirs(managed_root(), exist_ok=True)

    staging = tempfile.mkdtemp(prefix="opennest-python-", dir=managed_root())
    try:
        archive = os.path.join(staging, PINNED_ASSET)
        _download(_RELEASE_URL, archive, progress)
        _verify_checksum(archive, PINNED_SHA256)
        _extract(archive, staging)

        unpacked = os.path.join(staging, "python")
        if not os.path.isdir(unpacked):
            raise SetupError(
                "The downloaded Python did not look the way Open Nest expected. "
                "Try running Setup again."
            )

        # Replace any half-finished previous attempt, then move into place.
        if os.path.exists(destination):
            shutil.rmtree(destination, ignore_errors=True)
        shutil.move(unpacked, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    executable = managed_python(version)
    if probe_python(executable) is None:
        raise SetupError(
            "Open Nest installed Python but could not run it. Try running Setup again."
        )
    return executable


def uninstall(version: str = PINNED_VERSION) -> None:
    shutil.rmtree(managed_install_dir(version), ignore_errors=True)


def _download(url: str, target: str, progress: ProgressCallback | None) -> None:
    try:
        response = urllib.request.urlopen(url, timeout=60)  # noqa: S310 - pinned https URL
    except (urllib.error.URLError, OSError) as exc:
        raise SetupError(
            "Open Nest could not download Python.\n\n"
            "Check that this Mac is connected to the internet, then try again.\n\n"
            f"{exc}"
        ) from exc

    try:
        total = int(response.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        total = 0

    downloaded = 0
    try:
        with open(target, "wb") as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total)
    except OSError as exc:
        raise SetupError(f"Open Nest could not save the Python download.\n\n{exc}") from exc
    finally:
        response.close()

    if total and downloaded != total:
        raise SetupError("The Python download did not finish. Check the connection and try again.")


def _verify_checksum(path: str, expected: str) -> None:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise SetupError(
            "The Python download did not match its published checksum, so Open Nest "
            "stopped. Nothing was installed.\n\nTry running Setup again."
        )


def _extract(archive: str, destination: str) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            _reject_unsafe_member(member.name, destination)
        # Python 3.12+ has extraction filters; 3.9 does not, hence the check above.
        if hasattr(tarfile, "data_filter"):
            tar.extractall(destination, members=members, filter="data")
        else:
            tar.extractall(destination, members=members)  # noqa: S202 - members validated


def _reject_unsafe_member(name: str, destination: str) -> None:
    resolved = os.path.realpath(os.path.join(destination, name))
    root = os.path.realpath(destination)
    if not (resolved == root or resolved.startswith(root + os.sep)):
        raise SetupError("The Python download contained an unexpected file path.")
