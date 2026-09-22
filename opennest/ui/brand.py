"""Open Nest brand assets, as components rather than scattered image loads.

The brand guide's section 45 asks for exactly this: no direct image-loading calls spread
through the application, one component per mark, approved sizes, correct interpolation,
and accessible labelling in one place. Individual screens ask for a component and a size
tier; nothing else opens a PNG.

The semantic system (guide sections 40, 63), which every caller is expected to respect:

============  ==========================================
Wordmark      product identity -- "this is Open Nest"
Compact mark  compact identity -- "Open Nest is here"
Nest          home / project / place
Eagle cycle   activity -- "something is happening"
Glasses       authority / approval / meaningful completion
============  ==========================================

Four things here are measured rather than chosen, and each is load-bearing.

**Prepared sizes are drawn, never rescaled.** The supplied artwork is pixel-art *styled*
raster at ~2000 px wide, not a small sprite on an integer grid: round-tripping it through
nearest-neighbour downscale-and-restore shows error falling monotonically with no minimum
at any low logical size. So there is no "native" pixel grid to snap to, and nearest-
neighbour downscaling to a UI size drops edge steps unevenly -- it reads as a rendering
fault, not as pixel art. The developer's prepared delivery solves this by resampling once,
offline, at fixed sizes. This module therefore picks the prepared file closest to the
requested device size and blits it 1:1. That is what honours the guide's no-smoothing rule
in practice; ``Qt.FastTransformation`` only matters if something scales, and nothing here
does.

**Three marks are invisible in dark mode, and three are not.** Measured as mean
\\|ink - background\\| against the real theme colours -- wordmark 222 on bone against 27 on
charcoal, standalone ON 232 against 28, eagle 216 against 26; meanwhile the compact logo
(165/73), nest (145/86) and glasses (145/99) carry their own dark outlines and read on
both. :data:`_INVERTS_FOR_DARK` names the three, and :func:`_inverted` flips luminance
while preserving alpha. That is not the recolouring guide section 42 forbids -- its
examples are all hue changes (a green eagle, orange glasses, a colorised nest), and an
inversion keeps the artwork's black-and-white identity, which is the property that
section protects.

**The eagle frames are normalised in canvas size but not registered.** Measured on the
prepared 342 px masters: the feet baseline spans 51 px and the body's right edge 53 px
across the twelve frames, with a ~43 px discontinuity between frame 6 and frame 7. Played
in order the bird hops about 13% of the canvas height at the row boundary and drops back
at the loop point -- which is the positional motion guide section 37 explicitly forbids.
The cause is the source sheet rather than the preparation (row 0's feet average y=344.7,
row 1's y=301.3, and the prepared frames reproduce that faithfully), so the fix belongs
here: :data:`_EAGLE_REGISTRATION` translates each frame by whole pixels onto a common body
anchor, taking the feet spread to 1 px and the body spread to 1 px with every opaque pixel
preserved. ``tests/test_brand.py`` recomputes the alignment from the images, so if a
corrected frame set is ever delivered the test says so instead of this table going stale.

**The canonical artwork is the top-level ``assets/*.png``, not the delivery's
``00_source/``.** Measured: of the five files in ``00_source/``, only ``ON_b.png`` is
byte-identical to the original. ``OPENNEST_b``, ``eagle_cycle_bw`` and ``glasses`` are
2048x682 there against the originals' 2172x724, and ``nest_bw`` differs in 45% of its
pixels. Nothing is lost, because the originals are still present -- but derive future
sizes from ``assets/*.png``, not from ``00_source/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

#: The developer's prepared asset delivery. Resolved relative to the package because the
#: product ships as a git clone -- the same assumption ``git_manager.askpass_helper``
#: makes about ``github/askpass.sh``. ``tests/test_brand.py`` fails if it stops resolving.
DELIVERY = Path(__file__).resolve().parent.parent.parent / "assets" / "open_nest_asset_delivery"

LOGOS = DELIVERY / "01_logos"
SYMBOLS = DELIVERY / "02_symbols"
EAGLE = DELIVERY / "03_eagle_animation"

#: Milliseconds per eagle frame. The delivery recommends 125 ms (8 fps) and the guide's
#: section 35 asks for 6-10 fps, "deliberate, slightly mechanical, not frantic".
EAGLE_FRAME_MS = 125

#: Frames in the prepared cycle, in loop order.
EAGLE_FRAMES = 12


class Mark(Enum):
    """The five brand marks, by what they mean rather than by filename."""

    WORDMARK = "wordmark"
    COMPACT = "compact"
    NEST = "nest"
    GLASSES = "glasses"
    ON = "on"


#: Prepared widths per mark, from the delivery's manifest. A caller may only ask for a
#: size that exists on disk, so nothing is ever resampled at runtime.
_PREPARED: dict[Mark, tuple[int, ...]] = {
    Mark.WORDMARK: (192, 256, 384, 512, 768, 1024),
    Mark.COMPACT: (64, 96, 128, 192, 256, 384, 512, 1024),
    Mark.NEST: (96, 128, 192, 256, 384, 512),
    Mark.GLASSES: (64, 96, 128, 192, 256, 384, 512),
    Mark.ON: (64, 96, 128, 192, 256, 384),
}

_FILES: dict[Mark, tuple[Path, str]] = {
    Mark.WORDMARK: (LOGOS, "open_nest_wordmark_w{size}.png"),
    Mark.COMPACT: (LOGOS, "open_nest_compact_{size}.png"),
    Mark.NEST: (SYMBOLS, "nest_w{size}.png"),
    Mark.GLASSES: (SYMBOLS, "approval_glasses_w{size}.png"),
    Mark.ON: (LOGOS, "on_wordmark_w{size}.png"),
}

#: Prepared eagle sizes. ``master_frames`` is 342 px and is not a runtime size.
_EAGLE_SIZES: tuple[int, ...] = (64, 96, 128, 256)

#: The marks that vanish on a charcoal surface and need their luminance flipped. See the
#: module docstring for the contrast measurements; the eagle belongs to this set too and
#: :class:`EagleActivityIndicator` inverts its own frames.
_INVERTS_FOR_DARK: frozenset[Mark] = frozenset({Mark.WORDMARK, Mark.ON})

#: Accessible names, per guide section 46: a brand graphic is never the only signal, and
#: decorative repeats are not announced.
_ACCESSIBLE: dict[Mark, str] = {
    Mark.WORDMARK: "Open Nest",
    Mark.COMPACT: "Open Nest",
    Mark.NEST: "Open Nest",
    Mark.GLASSES: "Task completed",
    Mark.ON: "Open Nest",
}

#: Whole-pixel (dx, dy) per frame, per prepared size, putting every pose on one body
#: anchor. Generated from the prepared frames; ``tests/test_brand.py`` re-derives the
#: alignment from the images rather than trusting these numbers.
_EAGLE_REGISTRATION: dict[int, tuple[tuple[int, int], ...]] = {
    64: ((3, -4), (3, -5), (1, -4), (1, -4), (0, -4), (0, -3),
         (1, 5), (0, 4), (-2, 4), (-7, 3), (-3, 4), (-1, 3)),
    96: ((5, -6), (4, -7), (2, -6), (2, -6), (1, -6), (0, -4),
         (2, 8), (0, 7), (-3, 7), (-9, 4), (-5, 7), (-2, 4)),
    128: ((8, -8), (6, -10), (2, -8), (2, -8), (2, -8), (1, -6),
          (3, 10), (0, 8), (-4, 8), (-12, 5), (-6, 8), (-2, 5)),
    256: ((15, -15), (12, -18), (5, -15), (5, -15), (4, -15), (2, -11),
          (6, 20), (1, 17), (-7, 17), (-25, 11), (-12, 17), (-4, 11)),
}


@dataclass(frozen=True)
class _Key:
    """What uniquely identifies a rendered mark, so the cache can be keyed on it."""

    mark: Mark
    size: int
    dark: bool


def prepared_sizes(mark: Mark) -> tuple[int, ...]:
    """The widths this mark exists at. Asking for anything else is a programming error."""
    return _PREPARED[mark]


def nearest_size(mark: Mark, wanted: int) -> int:
    """The prepared width closest to ``wanted``.

    Callers state the size they want in device pixels and take back one that exists, so
    the pixmap is always blitted rather than scaled.
    """
    return min(_PREPARED[mark], key=lambda s: (abs(s - wanted), s))


def path_for(mark: Mark, size: int) -> Path:
    """Where a prepared mark lives on disk."""
    folder, pattern = _FILES[mark]
    return folder / pattern.format(size=size)


def eagle_frame_path(size: int, frame: int) -> Path:
    """One prepared eagle frame. ``frame`` is 1-based, matching the delivery's names."""
    return EAGLE / f"frames_{size}" / f"eagle_{frame:02d}.png"


@lru_cache(maxsize=64)
def _eagle_frame(size: int, frame: int, *, dark: bool) -> QPixmap:
    """One eagle frame, inverted for dark surfaces.

    The eagle is black-on-transparent like the wordmark -- measured at 216 mean contrast
    on bone against 26 on charcoal -- so a dark theme needs it flipped or there is simply
    nothing on screen while the app is working.
    """
    path = eagle_frame_path(size, frame)
    image = QImage(str(path))
    if image.isNull():
        raise FileNotFoundError(f"eagle frame missing: {path}")
    if dark:
        image = _inverted(image)
    return QPixmap.fromImage(image)


def _inverted(image: QImage) -> QImage:
    """Flip luminance, keep alpha.

    ``QImage.invertPixels`` with ``InvertRgb`` leaves the alpha channel alone, which is
    exactly what a transparent mark needs -- inverting alpha as well would fill the
    background in and knock the artwork out.
    """
    out = image.convertToFormat(QImage.Format.Format_ARGB32)
    out.invertPixels(QImage.InvertMode.InvertRgb)
    return out


@lru_cache(maxsize=128)
def _load(key: _Key) -> QPixmap:
    path = path_for(key.mark, key.size)
    image = QImage(str(path))
    if image.isNull():
        # A missing brand asset is a packaging fault, not something to paper over with a
        # blank label -- the same reasoning behind the requirements-manifest test.
        raise FileNotFoundError(f"brand asset missing: {path}")
    if key.dark and key.mark in _INVERTS_FOR_DARK:
        image = _inverted(image)
    return QPixmap.fromImage(image)


def pixmap(mark: Mark, size: int, *, dark: bool = False) -> QPixmap:
    """A prepared mark at a prepared size, ready to blit.

    ``size`` is snapped to the nearest prepared width, so this never resamples.
    """
    return _load(_Key(mark, nearest_size(mark, size), dark))


def mark_label(mark: Mark, size: int, *, dark: bool = False) -> QLabel:
    """A mark as a label, sized to its pixmap and carrying its accessible name."""
    label = QLabel()
    pix = pixmap(mark, size, dark=dark)
    label.setPixmap(pix)
    label.setFixedSize(pix.size())
    label.setAccessibleName(_ACCESSIBLE[mark])
    label.setScaledContents(False)
    return label


class EagleActivityIndicator(QWidget):
    """The twelve-frame wing cycle -- "Open Nest is working".

    Three restraints from the guide are structural here rather than advisory:

    * **Only the wings move.** Frames are drawn onto one body anchor
      (:data:`_EAGLE_REGISTRATION`), because the prepared frames are not registered and
      playing them raw makes the bird hop. Section 37 forbids animating its position.
    * **It runs only while something is really happening.** The timer is driven by
      :meth:`start` and :meth:`stop`, and stops on hide, so a hidden indicator costs
      nothing. Section 36: it must not become decoration that runs constantly.
    * **It is never the only signal.** Pair it with status text; the widget carries an
      accessible description for the case where it is all there is (section 46).
    """

    def __init__(
        self, parent: QWidget | None = None, *, size: int = 128, dark: bool = False
    ) -> None:
        super().__init__(parent)
        if size not in _EAGLE_SIZES:
            size = min(_EAGLE_SIZES, key=lambda s: (abs(s - size), s))
        self._size = size
        self._frame = 0
        self._frames = [
            _eagle_frame(size, n, dark=dark) for n in range(1, EAGLE_FRAMES + 1)
        ]
        self._offsets = _EAGLE_REGISTRATION[size]
        self._canvas = QLabel(self)
        self._canvas.setFixedSize(size, size)
        self._canvas.setScaledContents(False)
        self.setFixedSize(size, size)
        self.setAccessibleName("Open Nest is working")
        self._timer = QTimer(self)
        self._timer.setInterval(EAGLE_FRAME_MS)
        self._timer.timeout.connect(self._advance)
        self._show_frame(0)

    # -- playback -----------------------------------------------------------

    def start(self) -> None:
        """Begin the cycle. Idempotent, so a second call does not reset the pose."""
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """Stop the cycle and settle on the first pose."""
        self._timer.stop()
        self._show_frame(0)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def hideEvent(self, event) -> None:
        """A hidden indicator must not keep a timer alive."""
        self._timer.stop()
        super().hideEvent(event)

    # -- drawing ------------------------------------------------------------

    def _advance(self) -> None:
        self._show_frame((self._frame + 1) % EAGLE_FRAMES)

    def _show_frame(self, index: int) -> None:
        self._frame = index
        source = self._frames[index]
        dx, dy = self._offsets[index]
        # Registration is a whole-pixel blit onto a transparent canvas: no scaling, no
        # interpolation, nothing for Qt to soften.
        canvas = QPixmap(self._size, self._size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.drawPixmap(dx, dy, source)
        painter.end()
        self._canvas.setPixmap(canvas)
