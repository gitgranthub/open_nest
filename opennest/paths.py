"""Where Open Nest keeps things on disk.

Every location the application writes to is defined here, so nothing else has to guess.

Two modes:

**Contained.** With ``OPENNEST_HOME`` set, everything Open Nest owns -- runtime, models,
caches, logs, projects, state -- lives under that one directory. Nothing is written
anywhere else. This is what development and work-managed machines should use: one
directory to inspect, audit, back up, or delete.

**Installed.** With it unset, the standard macOS locations are used, which is correct for
the shipped product on a family Mac.

``paths_report()`` prints the resolved locations so containment can be verified rather
than assumed.
"""

from __future__ import annotations

import os
from pathlib import Path

from opennest import APP_NAME

#: Internal per-project directory (DESIGN_DOC.md section 21, WORKORDER_01 section 15A).
#: Holds project memory and conversation archives. Not shown in the child's file browser.
PROJECT_INTERNAL_DIRNAME = ".opennest"

#: Machine-level installation state (WORKORDER_01 section 35A). Never holds secrets --
#: those belong in the macOS Keychain.
INSTALLATION_STATE_FILENAME = "installation.json"

#: Parent controls and switch positions (WORKORDER_01 section 25). Plain JSON, readable
#: by anyone on the Mac, and for that reason never a place for a credential -- section 22
#: names plaintext preferences explicitly. ``security.permissions`` enforces it.
SETTINGS_FILENAME = "settings.json"

#: Set this to contain every Open Nest file under one directory.
HOME_ENV_VAR = "OPENNEST_HOME"

#: Finer-grained override, wins over OPENNEST_HOME. Mainly for tests.
PROJECTS_ENV_VAR = "OPENNEST_PROJECTS_DIR"


def opennest_home() -> Path | None:
    """The containment root, or None when running against standard macOS locations."""
    value = os.environ.get(HOME_ENV_VAR)
    if not value:
        return None
    return Path(value).expanduser()


def is_contained() -> bool:
    return opennest_home() is not None


def repo_root() -> Path:
    """The cloned repository. The source of truth for bundled config and prompts."""
    return Path(__file__).resolve().parent.parent


def package_root() -> Path:
    return Path(__file__).resolve().parent


def config_dir() -> Path:
    """Bundled configuration: curated models, project profiles."""
    return package_root() / "config"


def prompts_dir() -> Path:
    """Bundled system-prompt templates (WORKORDER_01 section 17)."""
    return package_root() / "prompts"


def app_support_dir() -> Path:
    home = opennest_home()
    if home:
        return home / "state"
    return Path.home() / "Library" / "Application Support" / APP_NAME


def logs_dir() -> Path:
    home = opennest_home()
    if home:
        return home / "logs"
    return Path.home() / "Library" / "Logs" / APP_NAME


def models_dir() -> Path:
    """Managed local model store. Never the machine-wide Hugging Face cache."""
    home = opennest_home()
    if home:
        return home / "models"
    return app_support_dir() / "models"


def runtime_dir() -> Path:
    """Where the vendored Python interpreter lives (see bootstrap.python_setup)."""
    home = opennest_home()
    if home:
        return home / "runtime"
    return app_support_dir() / "python"


def tools_dir() -> Path:
    """Managed third-party toolchains -- today just arduino-cli and its board cores.

    The same reasoning as :func:`models_dir`: a toolchain Open Nest downloads is Open
    Nest's to keep inside its own containment root, not something to scatter through
    ``~/Library``. arduino-cli in particular will create ``~/Library/Arduino15`` the
    first time it runs without being told otherwise, so every invocation has to point
    it here (SPIKES.md section 14).
    """
    home = opennest_home()
    if home:
        return home / "tools"
    return app_support_dir() / "tools"


def cache_dir() -> Path:
    """Scratch for third-party tooling caches (Hugging Face, pip) when contained.

    Keeping these inside the containment root is the difference between "one directory
    holds everything" and "mostly, except several gigabytes in ~/.cache".
    """
    home = opennest_home()
    if home:
        return home / "cache"
    return Path.home() / "Library" / "Caches" / APP_NAME


def projects_root() -> Path:
    """Where a child's projects live."""
    override = os.environ.get(PROJECTS_ENV_VAR)
    if override:
        return Path(override).expanduser()
    home = opennest_home()
    if home:
        return home / "projects"
    # Deliberately somewhere visible in Finder for the shipped product.
    return Path.home() / APP_NAME / "Projects"


def installation_state_file() -> Path:
    return app_support_dir() / INSTALLATION_STATE_FILENAME


def settings_file() -> Path:
    return app_support_dir() / SETTINGS_FILENAME


def project_internal_dir(project_dir: Path) -> Path:
    return Path(project_dir) / PROJECT_INTERNAL_DIRNAME


def managed_locations() -> dict[str, Path]:
    """Every directory Open Nest writes to, for verification and reporting."""
    return {
        "state": app_support_dir(),
        "logs": logs_dir(),
        "models": models_dir(),
        "runtime": runtime_dir(),
        "tools": tools_dir(),
        "cache": cache_dir(),
        "projects": projects_root(),
    }


def ensure_app_dirs() -> None:
    """Create the directories Open Nest needs. Safe to call on every launch."""
    for path in managed_locations().values():
        path.mkdir(parents=True, exist_ok=True)


def paths_report() -> str:
    mode = f"contained under {opennest_home()}" if is_contained() else "standard macOS locations"
    lines = [f"Open Nest paths ({mode}):"]
    for name, path in sorted(managed_locations().items()):
        lines.append(f"  {name:9} {path}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(paths_report())
