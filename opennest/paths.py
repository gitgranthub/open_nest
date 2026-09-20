"""Where Open Nest keeps things on disk.

Every location the application writes to is defined here, so nothing else has to guess.
Projects live somewhere a child can find them; everything internal lives in the standard
macOS locations.
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
    return Path.home() / "Library" / "Application Support" / APP_NAME


def logs_dir() -> Path:
    return Path.home() / "Library" / "Logs" / APP_NAME


def models_dir() -> Path:
    """Managed local model store. Kept out of the repository and out of projects."""
    return app_support_dir() / "models"


def projects_root() -> Path:
    """Where a child's projects live. Deliberately somewhere visible in Finder."""
    override = os.environ.get("OPENNEST_PROJECTS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / APP_NAME / "Projects"


def installation_state_file() -> Path:
    return app_support_dir() / INSTALLATION_STATE_FILENAME


def project_internal_dir(project_dir: Path) -> Path:
    return Path(project_dir) / PROJECT_INTERNAL_DIRNAME


def ensure_app_dirs() -> None:
    """Create the directories Open Nest needs. Safe to call on every launch."""
    for path in (app_support_dir(), logs_dir(), models_dir(), projects_root()):
        path.mkdir(parents=True, exist_ok=True)
