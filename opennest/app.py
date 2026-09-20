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

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
