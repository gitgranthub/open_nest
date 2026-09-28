"""The child's game, drawn inside the Workbench -- Phase 13.

The Qt half of :mod:`opennest.execution.live_view`. The game itself runs in its own
sandboxed process and opens no window; this widget paints the pictures it sends and
passes the child's keys and clicks back. Five decisions are worth knowing.

**It asks for pictures on a timer rather than being sent them.** The stream's reader is
an ordinary thread and touches no Qt object; this widget checks for a newer picture
sixty times a second on the GUI thread and repaints only when there is one. Nothing is
emitted across threads, so none of Phase 12's three threading traps (HANDOFF section 4)
can apply here.

**The game only hears the keyboard once the child has clicked it**, the way a window has
to be clicked before it hears anything. Tab still moves on to the next control and is
never sent: the Workbench had a keyboard trap once (SPIKES.md section 20F), and a game
that swallowed Tab would be a new one.

**Held keys are let go of when it loses focus.** Otherwise a key held down while the
child clicked the chat stays held in the game for ever.

**Qt's auto-repeat is ignored.** Holding a key sends Qt a stream of press/release pairs;
passed on, the game's ``key.get_pressed`` would flicker between down and up. The game
gets one press and one release, as SDL would give it.

**It shows only what the game drew.** The picture is scaled to fit, never cropped, and
nothing is painted over it while it runs. When it stops, the last picture is dimmed and
says so, so a stopped game is never mistaken for a frozen one.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from opennest.execution.live_view import Frame, LiveStream
from opennest.ui import theme

#: How often to look for a new picture. The game draws at most about sixty a second.
POLL_MS = 16

_K = Qt.Key
#: Qt's key to pygame's name for it. A shifted symbol maps to the key it is on, because
#: that is what pygame reports -- ``K_1`` with a ``!`` -- and because Qt may report the
#: release of the same key unshifted.
KEYS: dict[int, str] = {
    _K.Key_Left: "K_LEFT", _K.Key_Right: "K_RIGHT", _K.Key_Up: "K_UP", _K.Key_Down: "K_DOWN",
    _K.Key_Space: "K_SPACE", _K.Key_Return: "K_RETURN", _K.Key_Enter: "K_RETURN",
    _K.Key_Escape: "K_ESCAPE", _K.Key_Backspace: "K_BACKSPACE", _K.Key_Delete: "K_DELETE",
    _K.Key_Home: "K_HOME", _K.Key_End: "K_END", _K.Key_PageUp: "K_PAGEUP",
    _K.Key_PageDown: "K_PAGEDOWN",
    # On a Mac, Qt calls Command "Control" and the Control key "Meta".
    _K.Key_Shift: "K_LSHIFT", _K.Key_Control: "K_LMETA", _K.Key_Meta: "K_LCTRL",
    _K.Key_Alt: "K_LALT",
    _K.Key_Minus: "K_MINUS", _K.Key_Underscore: "K_MINUS",
    _K.Key_Equal: "K_EQUALS", _K.Key_Plus: "K_EQUALS",
    _K.Key_Comma: "K_COMMA", _K.Key_Less: "K_COMMA",
    _K.Key_Period: "K_PERIOD", _K.Key_Greater: "K_PERIOD",
    _K.Key_Slash: "K_SLASH", _K.Key_Question: "K_SLASH",
    _K.Key_Semicolon: "K_SEMICOLON", _K.Key_Colon: "K_SEMICOLON",
    _K.Key_Apostrophe: "K_QUOTE", _K.Key_QuoteDbl: "K_QUOTE",
    _K.Key_BracketLeft: "K_LEFTBRACKET", _K.Key_BraceLeft: "K_LEFTBRACKET",
    _K.Key_BracketRight: "K_RIGHTBRACKET", _K.Key_BraceRight: "K_RIGHTBRACKET",
    _K.Key_Backslash: "K_BACKSLASH", _K.Key_Bar: "K_BACKSLASH",
    _K.Key_QuoteLeft: "K_BACKQUOTE", _K.Key_AsciiTilde: "K_BACKQUOTE",
    _K.Key_Exclam: "K_1", _K.Key_At: "K_2", _K.Key_NumberSign: "K_3", _K.Key_Dollar: "K_4",
    _K.Key_Percent: "K_5", _K.Key_AsciiCircum: "K_6", _K.Key_Ampersand: "K_7",
    _K.Key_Asterisk: "K_8", _K.Key_ParenLeft: "K_9", _K.Key_ParenRight: "K_0",
}
for _letter in range(26):
    KEYS[int(_K.Key_A) + _letter] = "K_" + chr(ord("a") + _letter)
for _digit in range(10):
    KEYS[int(_K.Key_0) + _digit] = f"K_{_digit}"
for _number in range(1, 13):
    KEYS[int(_K.Key_F1) + _number - 1] = f"K_F{_number}"

#: Qt's mouse button to pygame's number for it.
BUTTONS = {Qt.MouseButton.LeftButton: 1, Qt.MouseButton.MiddleButton: 2,
           Qt.MouseButton.RightButton: 3}


def pygame_key(key: int) -> str | None:
    """pygame's name for a Qt key, or None for a key the game is not given."""
    return KEYS.get(int(key))


def fit(frame_width: int, frame_height: int, area: QRectF) -> QRectF:
    """Where a picture goes in ``area``: as large as fits, whole, centred."""
    if frame_width <= 0 or frame_height <= 0 or area.width() <= 0 or area.height() <= 0:
        return QRectF()
    scale = min(area.width() / frame_width, area.height() / frame_height)
    width, height = frame_width * scale, frame_height * scale
    return QRectF(area.x() + (area.width() - width) / 2,
                  area.y() + (area.height() - height) / 2, width, height)


def to_game(point: QPointF, target: QRectF, frame_width: int,
            frame_height: int) -> tuple[int, int] | None:
    """A point on the widget, in the game's own pixels; None outside the picture."""
    if target.isEmpty() or not target.contains(point):
        return None
    x = int((point.x() - target.x()) * frame_width / target.width())
    y = int((point.y() - target.y()) * frame_height / target.height())
    return min(max(x, 0), frame_width - 1), min(max(y, 0), frame_height - 1)


class GameView(QWidget):
    """Paints one :class:`LiveStream` and gives it the child's input."""

    #: The stream has finished -- the game ended, was stopped, or sent something it
    #: should not have. Emitted once, on the GUI thread, from the poll timer.
    ended = Signal()
    #: Whether the game is hearing the keyboard now, for the Workbench's caption.
    focus_changed = Signal(bool)
    #: The game's window title changed. The title is plain text, bounded by the stream.
    title_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        # Every pixel is painted below, so Qt need not paint the panel behind it first,
        # sixty times a second. Measured: 22 -> 18 % of a core with a game playing.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 120)
        self.setAccessibleName("Your game")
        self.setAccessibleDescription("Click to play. Tab moves on to the next control.")
        self._stream: LiveStream | None = None
        self._frame: Frame | None = None
        self._image: QImage | None = None
        self._title = ""
        self._stopped_text = ""
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

    # -- the stream --------------------------------------------------------------------

    @property
    def stream(self) -> LiveStream | None:
        return self._stream

    @property
    def running(self) -> bool:
        return self._stream is not None and not self._stopped_text

    def attach(self, stream: LiveStream) -> None:
        """Show this stream from now on, replacing whatever was shown before."""
        self._stream = stream
        self._frame = self._image = None
        self._title = ""
        self._stopped_text = ""
        self._timer.start()
        self._poll()
        self.update()

    def detach(self) -> None:
        """Stop looking at the stream. The game itself is stopped by whoever owns it."""
        self._timer.stop()
        if self._stream is not None:
            self._stream.release_all()
        self._stream = None

    def show_stopped(self, text: str) -> None:
        """Dim the last picture and say, in a few words, that the game is not running."""
        self._timer.stop()
        self._stopped_text = text
        self.update()

    def current_frame(self) -> Frame | None:
        return self._frame

    def _poll(self) -> None:
        stream = self._stream
        if stream is None:
            return
        frame = stream.latest()
        if frame is not None and (self._frame is None or frame.sequence != self._frame.sequence):
            self._frame = frame
            # The stream's own layout is Qt's native one: drawn without a conversion.
            self._image = QImage(frame.data, frame.width, frame.height, frame.width * 4,
                                 QImage.Format.Format_RGB32)
            self.update()
        title = stream.title
        if title != self._title:
            self._title = title
            self.title_changed.emit(title)
        if stream.finished:
            self._timer.stop()
            self.ended.emit()

    # -- painting ----------------------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return QSize(480, 360)

    def _target(self) -> QRectF:
        if self._frame is None:
            return QRectF()
        area = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        return fit(self._frame.width, self._frame.height, area)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        palette = theme.resolve_palette()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(palette.surface_alt))
        target = self._target()
        if self._image is not None and not target.isEmpty():
            # Smooth only when the picture is really shrunk, in *device* pixels, so a busy
            # picture stays readable; exact pixels otherwise, so a game's own pixel art
            # stays sharp. On a Retina panel a 640-pixel game is usually being enlarged,
            # and smoothing it anyway was measured as the costliest part of showing it.
            smooth = target.width() * self.devicePixelRatioF() < self._frame.width
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
            painter.drawImage(target, self._image)
        elif self._stream is not None and not self._stopped_text:
            painter.setPen(QColor(palette.text_muted))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Starting the game…")
        if self._stopped_text:
            veil = QColor(palette.window)
            veil.setAlpha(190)
            painter.fillRect(self.rect(), veil)
            painter.setPen(QColor(palette.text))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._stopped_text)
        edge = QColor(palette.accent if self.hasFocus() else palette.border)
        painter.setPen(QPen(edge, 2 if self.hasFocus() else 1))
        painter.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        painter.end()

    # -- input -------------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        name = pygame_key(event.key())
        if name is None or not self.running:
            super().keyPressEvent(event)
            return
        if not event.isAutoRepeat():
            self._stream.send_key(name, True, event.text())
        event.accept()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 - Qt's name
        name = pygame_key(event.key())
        if name is None or not self.running:
            super().keyReleaseEvent(event)
            return
        if not event.isAutoRepeat():
            self._stream.send_key(name, False)
        event.accept()

    def _mouse(self, kind: str, event) -> None:
        if not self.running or self._frame is None:
            return
        point = to_game(event.position(), self._target(), self._frame.width,
                        self._frame.height)
        if point is None:
            return
        self._stream.send_mouse(kind, point[0], point[1], BUTTONS.get(event.button(), 0))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._mouse("down", event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self._mouse("up", event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self._mouse("move", event)

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().focusInEvent(event)
        self.update()
        self.focus_changed.emit(True)

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().focusOutEvent(event)
        if self._stream is not None:
            self._stream.release_all()
        self.update()
        self.focus_changed.emit(False)
