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

Six things here are measured rather than chosen, and each is load-bearing.

**Prepared sizes are drawn, never rescaled.** The supplied artwork is pixel-art *styled*
raster at ~2000 px wide, not a small sprite on an integer grid -- only 0.7% of the eagle
sheet's pixels are fully opaque and 23.6% are partially transparent. So there is no
"native" pixel grid to snap to and nothing for an integer scale factor to preserve;
sizing is a resampling problem, solved once offline at fixed sizes rather than per frame
at runtime. This module therefore picks the prepared file for the requested *device* size
and blits it 1:1. That is what honours the guide's no-smoothing rule in practice;
``Qt.FastTransformation`` only matters if something scales, and nothing here does.

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
anchor, now taking both the feet spread and the body spread to **0 px** with 0.000% of
the ink clipped. ``tests/test_brand.py`` recomputes the alignment from the images, so if
a corrected frame set is ever delivered the test says so instead of this table going
stale. The table is generated -- ``tools/prepare_brand_assets.py --table`` reproduces it.

**The eagle ladder was rebuilt, because nearest-neighbour downscaling made it shimmer.**
The delivery's frame sets are exact nearest-neighbour downscales of ``master_frames``
(verified at 0.00 mean difference, so ``asset_manifest.json``'s ``"nearest-neighbor"``
is accurate -- an earlier note calling that a documentation inconsistency was wrong). Per
frame that is fine and even marginally the most faithful. Across the *cycle* it is not:
nearest samples a different subset of the soft source in each pose, so ink mass swung
**2.17 percentage points** frame to frame at 64 px and 3.90 pp at 32 px, which reads as
the bird pulsing as it flaps. Regenerated with premultiplied area-averaging, the swing is
**0.36-0.65 pp** at every size. Single-frame metrics could not see this -- ink mass and
round-trip error both rated nearest *better* -- which is the same trap as measuring a
composite's contrast with one whole-image mean.

**The canonical artwork is the top-level ``assets/*.png``, not the delivery's
``00_source/``.** Measured: of the five files in ``00_source/``, only ``ON_b.png`` is
byte-identical to the original. ``OPENNEST_b``, ``eagle_cycle_bw`` and ``glasses`` are
2048x682 there against the originals' 2172x724, and ``nest_bw`` differs in 45% of its
pixels. Nothing is lost, because the originals are still present -- but derive future
sizes from ``assets/*.png``, not from ``00_source/``.

**Sizes are asked for in logical pixels and resolved in device pixels.** Guide section 44
requires each source pixel to stay a crisp square on a Retina Mac, and the 10A
implementation did not consult ``devicePixelRatio`` at all -- a 128 px mark on a 2x
display asked for the 128 px file and Qt then stretched it over 256 device pixels. So
:func:`device_size` multiplies by the ratio before choosing a file, and the pixmap carries
that ratio, which is what makes Qt blit it 1:1 instead of resampling. Every size in
:data:`PLACEMENTS` has an **exact** 2x prepared file for that reason; when an exact double
is missing the nearest is used and Qt softens it slightly, so
``test_every_placement_size_has_an_exact_2x_file`` fails rather than letting a new
placement pick a size that cannot stay crisp.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
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
_EAGLE_SIZES: tuple[int, ...] = (32, 48, 64, 96, 128, 256)

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
    32: ((1, -2), (1, -3), (0, -2), (0, -2), (0, -2), (0, -2),
         (0, 2), (-1, 2), (-2, 2), (-4, 1), (-2, 2), (-1, 1)),
    48: ((2, -3), (1, -3), (0, -3), (0, -3), (0, -3), (-1, -2),
         (0, 4), (-1, 3), (-2, 3), (-6, 2), (-3, 3), (-2, 2)),
    64: ((2, -4), (2, -5), (0, -4), (0, -4), (0, -4), (-1, -3),
         (0, 5), (-1, 4), (-3, 4), (-8, 3), (-4, 4), (-2, 3)),
    96: ((4, -6), (3, -7), (1, -5), (1, -5), (0, -6), (-1, -4),
         (1, 8), (-1, 7), (-4, 7), (-11, 4), (-6, 7), (-2, 4)),
    128: ((6, -8), (4, -9), (0, -8), (1, -8), (0, -8), (-1, -6),
          (1, 10), (-2, 8), (-6, 8), (-14, 5), (-8, 8), (-4, 5)),
    256: ((12, -15), (9, -18), (2, -15), (2, -15), (1, -15), (-1, -11),
          (3, 20), (-2, 17), (-10, 17), (-28, 11), (-15, 17), (-6, 11)),
}


#: Approved placement sizes, in **logical** pixels. Guide section 45 asks a component to
#: define its approved sizes so an individual screen requests one rather than inventing a
#: number; these are those sizes, named for where they appear.
#:
#: Every one has an exact 2x prepared file, which is what keeps a Retina Mac on a 1:1
#: blit. ``tests/test_brand.py`` fails if a new placement picks a size whose double is
#: missing from the delivery.
PLACEMENTS: dict[str, tuple[Mark, int]] = {
    # Guide section 56: the Flight Deck is the strongest everyday expression of the brand.
    "flight_deck_wordmark": (Mark.WORDMARK, 256),
    "flight_deck_nest": (Mark.NEST, 96),
    # Section 57: compact, small, and never a large area of the Workbench. 64 is the
    # floor rather than a preference -- rendered at 40 the lockup's ON is illegible and
    # the nest is a blob, which is section 33's "do not reduce the artwork until it
    # becomes illegible". The delivery's compact ladder starts at 64 for that reason.
    # The nest is the dark-mode stand-in, at the size that gives it comparable presence;
    # heights match closely too, so the header does not change shape between schemes.
    "workbench_compact": (Mark.COMPACT, 64),
    "workbench_nest": (Mark.NEST, 96),
    # Section 58: the wizard may use the full identity more prominently.
    "wizard_wordmark": (Mark.WORDMARK, 256),
    "wizard_nest": (Mark.NEST, 96),
    # Section 30 lists "About Open Nest" as a place the wordmark belongs, and the
    # General page is that surface -- it is where the version lives. The smallest
    # prepared width, because a settings page is a utility surface: the rule for Phase
    # 10D is that the closer something is to actual work, the less branding it carries,
    # and this is the only settings surface that gets any at all.
    "settings_about": (Mark.WORDMARK, 192),
    # Sections 38-39: rare, and therefore worth something when it appears.
    "completion_glasses": (Mark.GLASSES, 128),
}

#: The eagle's logical sizes. An activity indicator should read as an indicator rather
#: than an illustration, so the inline one matches the macOS spinning indicator at 32 pt.
#: The wizard gets 48: guide section 58 makes the eagle part of a sequence that teaches
#: the visual language, and in a 640 px dialog with room around it a 32 pt bird is too
#: timid to register as identity.
#:
#: Both are 1:1 at 1x *and* 2x -- 32 takes ``frames_32`` then ``frames_64``, 48 takes
#: ``frames_48`` then ``frames_96``. The delivery's ladder started at 64, so
#: ``tools/prepare_brand_assets.py`` generated the small sets rather than letting a
#: 32 pt indicator soften on a non-Retina display.
EAGLE_INLINE = 32
EAGLE_SETUP = 48


@dataclass(frozen=True)
class _Key:
    """What uniquely identifies a rendered mark, so the cache can be keyed on it.

    ``ratio`` is part of the identity because the pixmap carries it: two screens at
    different scale factors need different objects, and mutating a shared cached pixmap
    to suit the caller would corrupt the other one.
    """

    mark: Mark
    size: int
    dark: bool
    ratio: float


def prepared_sizes(mark: Mark) -> tuple[int, ...]:
    """The widths this mark exists at. Asking for anything else is a programming error."""
    return _PREPARED[mark]


def nearest_size(mark: Mark, wanted: int) -> int:
    """The prepared width closest to ``wanted``, in **device** pixels.

    Callers state the size they want and take back one that exists, so the pixmap is
    always blitted rather than scaled.
    """
    return min(_PREPARED[mark], key=lambda s: (abs(s - wanted), s))


def device_pixel_ratio(widget: QWidget | None = None) -> float:
    """How many device pixels the display puts in a logical one.

    2.0 on every Retina Mac, 1.0 otherwise. A widget is preferred when there is one,
    because a Mac can have a Retina built-in display and a 1x external monitor at the
    same time and the answer differs per window.
    """
    if widget is not None:
        return float(widget.devicePixelRatioF())
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def device_size(mark: Mark, logical: int, ratio: float) -> int:
    """The prepared file to draw for ``logical`` points at this scale factor.

    The exact double is preferred over the merely nearest: at 2x a 128 pt mark wants the
    256 px file, and taking it means Qt copies pixels rather than resampling them. Only
    when no prepared size matches exactly does this fall back to the nearest, which is a
    soft rescale -- :data:`PLACEMENTS` is chosen so that never happens in shipped code.
    """
    wanted = logical * ratio
    exact = int(round(wanted))
    if abs(wanted - exact) < 1e-9 and exact in _PREPARED[mark]:
        return exact
    return nearest_size(mark, exact)


def path_for(mark: Mark, size: int) -> Path:
    """Where a prepared mark lives on disk."""
    folder, pattern = _FILES[mark]
    return folder / pattern.format(size=size)


def eagle_frame_path(size: int, frame: int) -> Path:
    """One prepared eagle frame. ``frame`` is 1-based, matching the delivery's names."""
    return EAGLE / f"frames_{size}" / f"eagle_{frame:02d}.png"


def _nearest_eagle_size(wanted: float) -> int:
    """The prepared eagle frame size closest to ``wanted`` device pixels."""
    exact = int(round(wanted))
    if exact in _EAGLE_SIZES:
        return exact
    return min(_EAGLE_SIZES, key=lambda s: (abs(s - exact), s))


@lru_cache(maxsize=64)
def _eagle_frame(size: int, frame: int, *, dark: bool) -> QPixmap:
    """One eagle frame at a **device** size, inverted for dark surfaces.

    The eagle is black-on-transparent like the wordmark -- measured at 216 mean contrast
    on bone against 26 on charcoal -- so a dark theme needs it flipped or there is simply
    nothing on screen while the app is working.

    No device pixel ratio is set here: these are composited onto the indicator's own
    canvas, and that canvas is what carries the ratio.
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
    pix = QPixmap.fromImage(image)
    # What tells Qt these are device pixels rather than points. Without it a 512 px
    # wordmark on a 2x display lays out 512 points wide -- twice its intended size --
    # and with the old code the 256 px file was stretched over 512 device pixels instead.
    pix.setDevicePixelRatio(key.ratio)
    return pix


def pixmap(mark: Mark, size: int, *, dark: bool = False, ratio: float | None = None) -> QPixmap:
    """A prepared mark at ``size`` **logical** pixels, ready to blit.

    The file chosen is the prepared one for ``size x ratio`` device pixels, and the
    pixmap carries the ratio, so nothing is ever resampled at a placement size.
    ``ratio`` defaults to the display's, and is injectable so a test can exercise 2x
    without a Retina screen.
    """
    ratio = device_pixel_ratio() if ratio is None else ratio
    return _load(_Key(mark, device_size(mark, size, ratio), dark, ratio))


def mark_label(
    mark: Mark,
    size: int,
    *,
    dark: bool = False,
    decorative: bool = False,
    ratio: float | None = None,
) -> QLabel:
    """A mark as a label, sized in logical pixels and carrying its accessible name.

    ``decorative`` suppresses the accessible name, for guide section 46's "do not
    announce decorative repeated artwork": the nest beside the wordmark on the Flight
    Deck is one identity, and a screen reader saying "Open Nest, Open Nest" is worse than
    saying it once.
    """
    label = QLabel()
    pix = pixmap(mark, size, dark=dark, ratio=ratio)
    label.setPixmap(pix)
    label.setFixedSize(pix.deviceIndependentSize().toSize())
    if not decorative:
        label.setAccessibleName(_ACCESSIBLE[mark])
    label.setScaledContents(False)
    return label


def placed(name: str, *, dark: bool = False, decorative: bool = False) -> QLabel:
    """A mark at its approved size for a named place in the interface.

    Screens go through this rather than choosing a number, which is what keeps spacing
    and proportion consistent between them (guide sections 45 and 48).
    """
    mark, size = PLACEMENTS[name]
    return mark_label(mark, size, dark=dark, decorative=decorative)


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
        self,
        parent: QWidget | None = None,
        *,
        size: int = EAGLE_INLINE,
        dark: bool = False,
        ratio: float | None = None,
    ) -> None:
        super().__init__(parent)
        ratio = device_pixel_ratio() if ratio is None else ratio
        #: The prepared frame size actually drawn, in device pixels.
        self._size = _nearest_eagle_size(size * ratio)
        self._ratio = ratio
        #: What the layout sees. Equals the requested size whenever the exact double is
        #: prepared, which :data:`EAGLE_INLINE` and :data:`EAGLE_SETUP` both guarantee.
        self._logical = max(1, round(self._size / ratio))
        self._frame = 0
        self._frames = [
            _eagle_frame(self._size, n, dark=dark) for n in range(1, EAGLE_FRAMES + 1)
        ]
        # The offsets are in the prepared frames' own pixels, so they are indexed by the
        # device size rather than the logical one.
        self._offsets = _EAGLE_REGISTRATION[self._size]
        self._canvas = QLabel(self)
        self._canvas.setFixedSize(self._logical, self._logical)
        self._canvas.setScaledContents(False)
        self.setFixedSize(self._logical, self._logical)
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
        # interpolation, nothing for Qt to soften. The canvas is in device pixels and
        # carries the ratio, so the offsets stay whole pixels at 2x as well as at 1x --
        # composing in logical units would land the bird on a half pixel.
        canvas = QPixmap(self._size, self._size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.drawPixmap(dx, dy, source)
        painter.end()
        canvas.setDevicePixelRatio(self._ratio)
        self._canvas.setPixmap(canvas)
