"""Open Nest application entry point.

    python -m opennest.app

Normally started by the repository launchers rather than run directly.
"""

from __future__ import annotations

import sys
from typing import Sequence

from PySide6.QtWidgets import QApplication

from opennest import APP_NAME, paths
from opennest.ui import theme
from opennest.ui.main_window import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    paths.ensure_app_dirs()

    app = QApplication(list(argv if argv is not None else sys.argv))
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    theme.apply(app)

    # WORKORDER_01 "Repository update behavior": the launch after a `git pull` finishes
    # the update before the app opens. Does nothing on an ordinary launch.
    finish_any_pending_update()

    window = MainWindow()
    window.show()
    return app.exec()


def finish_any_pending_update() -> None:
    """Detect and apply what a ``git pull`` moved (DoD 51-53).

    Deliberately forgiving: this runs before every launch, and a fault in *noticing* an
    update must never be a reason a child cannot open their projects. Anything
    unexpected here is swallowed and the app starts regardless.
    """
    from opennest.setup.state import InstallationState

    try:
        state = InstallationState.load()
        if state.needs_setup():
            # Never set up, or metadata that will not parse. Either way this is a setup
            # or repair question, not a migration one -- and nothing is reset.
            return
        from opennest.setup import migration
        from opennest.setup.update_dialog import run_migration

        plan = migration.plan(state)
        if plan.needed:
            run_migration(state, plan)
    except Exception:  # noqa: BLE001 - a broken update check must not block launch
        return


if __name__ == "__main__":
    sys.exit(main())
