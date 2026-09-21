"""Finishing an update on the launch after someone ran ``git pull``.

WORKORDER_01's "Repository update behavior" and DoD 51-53: the next launch detects
dependency, configuration-schema and model-definition changes and performs the required
migrations before the app starts, preserving projects, Git history, project memory,
assets, settings and Keychain credentials.

Most of that list is preserved **by layout rather than by care**, which is worth knowing
before reading this file looking for the code that protects it. Projects live in
``~/Open Nest/Projects``, outside the repository; each has its own Git repository and
its own ``.opennest`` memory directory inside it; settings are in Application Support;
credentials are in the Keychain and not in the filesystem at all. A ``git pull`` cannot
reach any of them. So the job here is narrow: reinstall what the manifests now ask for,
adopt the new fingerprint, and **report** the one change that is genuinely expensive.

Two rules, both from PLAN.md's Phase 8 section:

**A moved model pin is shown, never acted on.** Re-pinning a model implies a
multi-gigabyte download. It is reported as something the parent may choose to do in
Settings, and nothing starts on its own.

**Nothing here deletes anything.** There is no destructive step to get wrong. The most
this does is run pip and rewrite ``installation.json``. If metadata is damaged rather
than merely old, :meth:`InstallationState.needs_setup` sends the parent to setup or
repair instead, and the damaged file is left where it is.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from opennest.setup.state import InstallationState


@dataclass
class MigrationPlan:
    """What the next launch is going to do, worked out before it does any of it."""

    changes: tuple = ()
    #: Manifests to reinstall, because a pull moved them.
    reinstall_dependencies: bool = False
    #: Model ids whose pinned revision moved. Reported, never downloaded automatically.
    models_to_refresh: tuple = ()

    @property
    def needed(self) -> bool:
        return bool(self.changes)

    @property
    def automatic(self) -> bool:
        """Whether applying this needs nothing from the parent beyond pressing once."""
        return self.needed and not self.models_to_refresh

    def headline(self) -> str:
        """The work order's prompt, near enough its words."""
        return "Open Nest was updated. A few components need to be refreshed."

    def lines(self) -> tuple:
        return tuple(change.summary for change in self.changes)


@dataclass
class MigrationResult:
    ok: bool
    message: str
    notes: tuple = field(default_factory=tuple)


def plan(state: InstallationState) -> MigrationPlan:
    """Work out what a pull moved. Reads only; writes nothing."""
    changes: tuple = state.pending_changes()
    if not changes:
        return MigrationPlan()
    return MigrationPlan(
        changes=changes,
        reinstall_dependencies=any(c.kind == "dependencies" for c in changes),
        models_to_refresh=tuple(
            c.summary for c in changes if c.kind == "models" and c.costly
        ),
    )


def apply(
    state: InstallationState,
    migration: MigrationPlan,
    *,
    on_progress: Callable[[str], None] | None = None,
    repo_root: Path | None = None,
    runner: Callable[[list], int] | None = None,
) -> MigrationResult:
    """Carry out the migration, then adopt the new checkout as the known-good one.

    The fingerprint is recorded **last and only on success**. It means "this is what we
    are known to work against", so writing it after a failed reinstall would tell the
    next launch there was nothing to do.
    """
    say = on_progress or (lambda message: None)
    notes: list = []

    if migration.reinstall_dependencies:
        say("Updating what Open Nest needs...")
        ok, detail = _reinstall(repo_root, runner)
        if not ok:
            # Deliberately not recording the fingerprint: the next launch should try
            # again rather than assume this succeeded.
            return MigrationResult(
                False,
                "Open Nest could not finish updating.\n\n" + detail
                + "\n\nYour projects are untouched. Try running Setup again.",
            )
        notes.append("Dependencies reinstalled.")

    for summary in migration.models_to_refresh:
        # PLAN.md: shown, never silently started.
        notes.append(summary)

    say("Finishing up...")
    state.record_launch()
    try:
        state.save()
    except (OSError, ValueError) as exc:
        return MigrationResult(
            False, f"Open Nest updated, but could not record it.\n\n{exc}"
        )

    return MigrationResult(True, "Open Nest is up to date.", tuple(notes))


def _reinstall(repo_root: Path | None, runner: Callable[[list], int] | None) -> tuple:
    """Reinstall the requirement manifests through the bootstrap's own installer.

    Imported lazily, and by name rather than by copying the logic: ``bootstrap`` is the
    authority on how this environment is built, and two implementations of "install the
    requirements" would drift. The dependency only goes this way -- the bootstrap must
    never import the application.
    """
    try:
        from bootstrap import environment
        from bootstrap.environment import SetupError
    except ImportError:
        return False, "The Open Nest installer could not be found."

    root = str(repo_root) if repo_root is not None else environment.repo_root()
    manifests = [
        str(Path(root) / "requirements" / name)
        for name in ("base.txt", "projects.txt")
        if (Path(root) / "requirements" / name).is_file()
    ]
    if not manifests:
        return False, "The list of things Open Nest needs could not be found."

    if runner is not None:
        # Injected by the tests, which must not run pip.
        return (runner(manifests) == 0), "The installer reported a problem."

    try:
        environment.install_requirements(manifests, root)
    except SetupError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - reported to a parent, never raised
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""
