"""The setup health check -- WORKORDER_01 section 35A, step 7.

The work order lists twelve things to check and adds one rule that shapes the whole
module: *"Any optional unconfigured service should show ``○ Not configured`` rather than
an error."* So a check has three outcomes, not two. Something a parent chose not to set
up is not a fault, and reporting it as one teaches them to ignore the screen.

Everything here probes by **doing the thing**, never by looking for a file. That is the
stance ``process_sandbox.sandbox_available`` and ``arduino.available`` already take, and
it exists because a keyring with no usable backend imports perfectly and fails on first
read, while a binary present at the expected path may still not run.

Reused by Repair Installation (section 35A, "Repair setup"), which is the same list of
questions asked at a different moment -- so this module answers them and neither the
wizard nor Settings owns the knowledge.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from opennest import paths
from opennest.ai import router
from opennest.security import keychain, permissions, process_sandbox

#: A check passed.
OK = "ok"
#: An optional service the parent has not set up. Section 35A: not an error.
NOT_CONFIGURED = "not-configured"
#: Something that should work does not.
FAILED = "failed"

_SYMBOLS = {OK: "✓", NOT_CONFIGURED: "○", FAILED: "✗"}

#: The minimum the application itself needs. Mirrors bootstrap.environment.MIN_PYTHON,
#: which cannot be imported from here without coupling the app to the installer.
MIN_PYTHON = (3, 12)


@dataclass(frozen=True)
class Check:
    """One row of the health check."""

    name: str
    state: str
    detail: str = ""

    @property
    def symbol(self) -> str:
        return _SYMBOLS.get(self.state, "?")

    @property
    def ok(self) -> bool:
        """Whether this row blocks. An unconfigured optional service does not."""
        return self.state != FAILED

    def line(self) -> str:
        suffix = f" — {self.detail}" if self.detail else ""
        if self.state == NOT_CONFIGURED and not self.detail:
            suffix = " — Not configured"
        return f"{self.symbol} {self.name}{suffix}"


def run(
    controls: permissions.ParentControls | None = None,
    credentials: keychain.Credentials | None = None,
    *,
    preferred_model: str = "",
) -> tuple[Check, ...]:
    """Every check in section 35A step 7, in the order it lists them."""
    settings = controls if controls is not None else permissions.current()
    store = credentials or keychain.default()

    found = [
        _python(),
        _importable("PySide6", "PySide6.QtWidgets"),
        _importable("MLX", "mlx.core"),
        _importable("MLX-LM", "mlx_lm"),
        _local_model(preferred_model),
        _project_directory(),
        _sandbox(),
        _keychain(store),
        _git(),
        _github(settings),
    ]
    found.extend(_cloud(settings, store))
    found.append(_arduino())
    return tuple(found)


def blocking(results: Sequence[Check]) -> tuple[Check, ...]:
    """The checks that actually failed, which is what stops a parent finishing."""
    return tuple(check for check in results if check.state == FAILED)


def summary(results: Sequence[Check]) -> str:
    problems = blocking(results)
    if not problems:
        return "Everything Open Nest needs is working."
    if len(problems) == 1:
        return f"One thing needs attention: {problems[0].name.lower()}."
    return f"{len(problems)} things need attention."


# --------------------------------------------------------------------- the checks

def _python() -> Check:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] < MIN_PYTHON:
        return Check(
            "Python environment", FAILED,
            f"Open Nest needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} "
            f"and this is {version}.",
        )
    return Check("Python environment", OK, f"Python {version}")


def _importable(name: str, module: str) -> Check:
    """Import it. Section 35A: "validate that important components can actually import"."""
    try:
        __import__(module)
    except Exception as exc:
        return Check(name, FAILED, f"could not be loaded ({type(exc).__name__})")
    return Check(name, OK)


def _local_model(preferred: str) -> Check:
    """Whether there is a usable local model, and whether it is the chosen one."""
    from opennest.setup import downloader

    try:
        entries = router.local_models()
    except Exception as exc:
        return Check("Local model", FAILED, f"the model list could not be read ({exc})")

    installed = [entry for entry in entries if downloader.is_installed(entry)]
    if not installed:
        # Section 35A allows skipping model installation, and says the wizard must
        # explain that Open Nest then needs cloud AI. That is a choice, not a fault.
        return Check("Local model", NOT_CONFIGURED, "no local model is installed")

    names = ", ".join(entry.info.name for entry in installed)
    if preferred and not any(entry.info.id == preferred for entry in installed):
        return Check(
            "Local model", FAILED,
            f"the chosen model is not installed. Available: {names}",
        )
    return Check("Local model", OK, names)


def _project_directory() -> Check:
    """Present, and actually writable -- a directory that exists can still be read-only."""
    target = paths.projects_root()
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".opennest-write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check("Project folder", FAILED, f"{target} cannot be written to ({exc.strerror})")
    return Check("Project folder", OK, str(target))


def _sandbox() -> Check:
    """Probed by applying a trivial profile, not by looking for sandbox-exec.

    A failure here is serious: ``run_project`` fails closed, so nothing a child makes
    will run at all.
    """
    if not process_sandbox.sandbox_available():
        return Check(
            "Project sandbox", FAILED,
            "projects cannot be run safely on this Mac, so Open Nest will not run them",
        )
    return Check("Project sandbox", OK)


def _keychain(store: keychain.Credentials) -> Check:
    if not store.available():
        return Check(
            "macOS Keychain", FAILED,
            "Open Nest cannot save API keys or a parent PIN",
        )
    return Check("macOS Keychain", OK)


def _git() -> Check:
    """Section 35A step 5: local version history works with or without GitHub."""
    from opennest.versioning import git_manager

    if not git_manager.git_available():
        return Check(
            "Version history", FAILED,
            "Git is not installed, so Open Nest cannot save versions of a project",
        )
    return Check("Version history", OK, "Git is installed")


def _github(controls: permissions.ParentControls) -> Check:
    """Phase 9 owns the connection itself; this reports honestly until then."""
    return Check("GitHub backup", NOT_CONFIGURED)


def _cloud(
    controls: permissions.ParentControls, store: keychain.Credentials
) -> list[Check]:
    """One row per cloud provider.

    Two separate facts, as section 6B of the handoff insists: the master switch and a
    saved key have different remedies, so they get different sentences.
    """
    rows: list[Check] = []
    for status in store.statuses():
        if not status.configured:
            rows.append(Check(status.label, NOT_CONFIGURED))
        elif not controls.cloud_allowed():
            rows.append(Check(status.label, NOT_CONFIGURED, "key saved, cloud AI is off"))
        else:
            rows.append(Check(status.label, OK, "key saved"))
    return rows


def _arduino() -> Check:
    """D7: the toolchain is an optional choice, so absent is "not configured"."""
    from opennest.execution import arduino

    if not arduino.available():
        return Check("Arduino tools", NOT_CONFIGURED)
    return Check("Arduino tools", OK)


# --------------------------------------------------------------------- repair

@dataclass(frozen=True)
class RepairPlan:
    """What Repair Installation would do, worked out before anything is touched.

    Section 35A's repair list is explicit about what must survive: projects, their Git
    repositories, project memory, and valid credentials. The safest way to honour that
    is for repair to have no destructive step at all -- it reinstalls dependencies and
    re-downloads *missing* model files, and everything else it merely re-checks.
    """

    reinstall_dependencies: bool
    missing_models: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def anything_to_do(self) -> bool:
        return self.reinstall_dependencies or bool(self.missing_models)


def plan_repair(
    results: Sequence[Check], *, preferred_model: str = ""
) -> RepairPlan:
    """Turn a health check into the list of repairs section 35A asks for."""
    by_name = {check.name: check for check in results}
    broken_imports = [
        name for name in ("PySide6", "MLX", "MLX-LM")
        if by_name.get(name) is not None and by_name[name].state == FAILED
    ]

    missing: list[str] = []
    model_check = by_name.get("Local model")
    if model_check is not None and model_check.state != OK and preferred_model:
        missing.append(preferred_model)

    notes: list[str] = []
    for name in ("Project sandbox", "macOS Keychain", "Version history", "Project folder"):
        check = by_name.get(name)
        if check is not None and check.state == FAILED:
            # Not repairable by reinstalling anything, so it is reported rather than
            # attempted. A missing Git is a job for the parent, not for the installer.
            notes.append(check.detail or name)

    return RepairPlan(
        reinstall_dependencies=bool(broken_imports),
        missing_models=tuple(missing),
        notes=tuple(notes),
    )


def git_executable() -> str | None:
    return shutil.which("git")


def report(results: Sequence[Check]) -> str:
    """The whole check as text, for the wizard's panel and for diagnostics."""
    return "\n".join(check.line() for check in results)
