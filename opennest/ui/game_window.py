"""The child's game in a window of its own, and back -- Phase 13B.

13A drew the game inside the Build / Preview panel, which is also what makes this part
small: the picture is a widget Open Nest owns (:class:`~opennest.ui.game_view.GameView`),
and moving a widget of your own into another window is allowed where adopting another
process's window is not (PHASE_12_HANDOFF.md section 6). So "pop out" moves that same
widget -- its stream, its timer, the game's keys -- into this window, and "put back"
moves it home. The game never notices: its process, its sandbox and its one socket are
exactly as they were, and not one picture is missed.

Three decisions:

- **Closing the window puts the game back; it never stops the game.** A window's close
  button reads as "go away", and the game is the child's -- it goes back where it came
  from, still playing. Stop is in the Workbench, where it always was.
- **There is a way out that is not the game.** The window has a caption and a "Put back
  in Open Nest" button beside the picture, so Tab moves on from the game to the button
  rather than being trapped (the Workbench had a keyboard trap once, SPIKES.md 20F).
- **It opens at the game's own size**, whole, and never larger than the screen: a
  640-by-480 game gets a window that shows it pixel for pixel when there is room.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

#: The height of the bar under the picture, for sizing the window around the game.
BAR_HEIGHT = 44
#: How much of the screen the window may take at most.
SCREEN_SHARE = 0.9
#: Never narrower than this, so the caption and Put back fit beside each other; a small
#: game is shown whole in the middle.
MIN_WIDTH = 600


def window_size(frame_width: int, frame_height: int, available: QSize) -> QSize:
    """The window's size for a game this big: its own size, shrunk whole to fit."""
    width, height = max(frame_width, 160), max(frame_height, 120)
    room_w = int(available.width() * SCREEN_SHARE)
    room_h = int(available.height() * SCREEN_SHARE) - BAR_HEIGHT
    scale = min(1.0, room_w / width, room_h / height) if room_w > 0 and room_h > 0 else 1.0
    return QSize(max(int(width * scale), min(MIN_WIDTH, room_w)),
                 int(height * scale) + BAR_HEIGHT)


class GameWindow(QWidget):
    """A window that holds the game while it is popped out."""

    #: The child asked for the game back -- the button, or the window's close button.
    put_back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        # Owned by the Workbench, so it cannot outlive the project it shows.
        super().__init__(parent, Qt.WindowType.Window)
        self.setAccessibleName("Your game, in its own window")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._slot = QVBoxLayout()
        self._slot.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._slot, 1)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 6, 12, 8)
        self.caption = QLabel()
        self.caption.setProperty("role", "mono")
        self.back = QPushButton("Put back in Open Nest")
        self.back.setToolTip("Put the game back in the Build / Preview panel -- it keeps playing")
        self.back.clicked.connect(self.put_back_requested.emit)
        bar.addWidget(self.caption, 1)
        bar.addWidget(self.back)
        outer.addLayout(bar)
        self.game: QWidget | None = None

    def hold(self, game: QWidget, title: str) -> None:
        """Take the game, size the window around it, and give it the keys."""
        self.game = game
        self._slot.addWidget(game)
        game.show()
        self.set_title(title)
        frame = game.current_frame() if hasattr(game, "current_frame") else None
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry().size() if screen is not None else QSize(1280, 800)
        self.resize(window_size(frame.width if frame else 640, frame.height if frame else 480,
                                available))
        self.show()
        self.raise_()
        self.activateWindow()
        game.setFocus(Qt.FocusReason.OtherFocusReason)

    def give_back(self) -> QWidget | None:
        """Let go of the game so the Workbench can have it back; the window hides."""
        game, self.game = self.game, None
        if game is not None:
            self._slot.removeWidget(game)
        self.hide()
        return game

    def set_title(self, title: str) -> None:
        self.setWindowTitle(title)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.game is not None:
            # Closing the window means "put it back", never "stop the game".
            event.ignore()
            self.put_back_requested.emit()
            return
        super().closeEvent(event)
