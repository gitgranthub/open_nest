"""The brand asset layer -- ``opennest/ui/brand.py`` and the prepared asset delivery.

Runs under Qt's ``offscreen`` platform like the other UI tests. Nothing here asserts on
appearance; everything here asserts on something that would regress silently and that a
person looking at the window would not reliably catch.

Three of these tests exist because measuring the delivery found defects in it:

* the eagle frames are normalised in canvas size but **not registered**, so playing them
  in order makes the bird hop -- :func:`test_the_eagle_frames_are_registered_on_one_body`
  re-derives the alignment from the images rather than trusting the offset table;
* three marks are invisible on a charcoal surface, so dark mode needs them inverted;
* a brand asset that does not resolve on disk is a packaging fault, and this project has
  been bitten three times by a data file nothing installed (``projects.txt``,
  ``macos-apple-silicon.txt``, ``requirements/macos-apple-silicon.txt``).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.ui import brand  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# ------------------------------------------------------- the delivery is present

def test_every_declared_brand_asset_is_on_disk():
    """A declared size that does not exist is a packaging fault, not a fallback.

    ``opennest/ui/brand.py`` resolves the delivery relative to the package, the way
    ``git_manager.askpass_helper`` resolves ``github/askpass.sh``. If the delivery is
    ever moved, renamed, or left out of a distribution, this is the test that says so.
    """
    missing = []
    for mark in brand.Mark:
        for size in brand.prepared_sizes(mark):
            path = brand.path_for(mark, size)
            if not path.is_file():
                missing.append(str(path))
    for size in (64, 96, 128, 256):
        for frame in range(1, brand.EAGLE_FRAMES + 1):
            path = brand.eagle_frame_path(size, frame)
            if not path.is_file():
                missing.append(str(path))
    assert not missing, f"brand assets missing from the delivery: {missing}"


def test_the_eagle_cycle_is_twelve_frames_at_every_runtime_size():
    """The count is measured from the artwork, never assumed (guide section 34).

    The supplied sheet is a uniform 6x2 grid of 362 px cells, which is 12 poses, and the
    delivery's manifest agrees. A size folder that disagreed would desynchronise the
    registration table.
    """
    for size in (64, 96, 128, 256):
        frames = sorted((brand.EAGLE / f"frames_{size}").glob("eagle_*.png"))
        assert len(frames) == brand.EAGLE_FRAMES, f"frames_{size} has {len(frames)}"


# ------------------------------------------------------- sizes are never resampled

def test_a_requested_size_always_snaps_to_one_that_exists():
    """Nothing is scaled at runtime, so a caller can only get a prepared size.

    The supplied artwork is pixel-art *styled* raster at ~2000 px, not a sprite on an
    integer grid, so an arbitrary runtime downscale produces uneven edge steps. Every
    size a caller asks for resolves to a file.
    """
    for mark in brand.Mark:
        prepared = brand.prepared_sizes(mark)
        for wanted in (1, 50, 77, 100, 200, 500, 4000):
            got = brand.nearest_size(mark, wanted)
            assert got in prepared
            assert brand.path_for(mark, got).is_file()


def test_the_nearest_size_is_actually_the_nearest():
    assert brand.nearest_size(brand.Mark.NEST, 129) == 128
    assert brand.nearest_size(brand.Mark.NEST, 200) == 192
    assert brand.nearest_size(brand.Mark.GLASSES, 64) == 64
    # Ties resolve downward, so a tie never silently costs memory.
    assert brand.nearest_size(brand.Mark.GLASSES, 80) == 64


# ------------------------------------------------------- light and dark

def _mean_contrast(image, background) -> float:
    """Mean |ink - background| over the non-transparent pixels, composited."""
    from PySide6.QtGui import qAlpha, qBlue, qGreen, qRed

    br, bg, bb = background
    bg_lum = 0.299 * br + 0.587 * bg + 0.114 * bb
    total = 0.0
    count = 0
    for y in range(0, image.height(), 3):
        for x in range(0, image.width(), 3):
            px = image.pixel(x, y)
            alpha = qAlpha(px) / 255.0
            if alpha <= 0.15:
                continue
            r = qRed(px) * alpha + br * (1 - alpha)
            g = qGreen(px) * alpha + bg * (1 - alpha)
            b = qBlue(px) * alpha + bb * (1 - alpha)
            total += abs((0.299 * r + 0.587 * g + 0.114 * b) - bg_lum)
            count += 1
    return total / count if count else 0.0


BONE = (231, 226, 216)      # theme.LIGHT.window
CHARCOAL = (30, 28, 26)     # theme.DARK.window


@pytest.mark.parametrize("mark", [brand.Mark.WORDMARK, brand.Mark.ON])
def test_the_black_marks_are_legible_in_dark_mode_only_once_inverted(qt_app, mark):
    """Measured: the wordmark scores 222 on bone and 27 on charcoal as supplied.

    Guide section 42 forbids *recolouring* the artwork, and its examples are all hue
    changes -- a green eagle, orange glasses, a colorised nest. A luminance inversion
    keeps the black-and-white identity that section protects, and without it there is
    nothing on screen at all in dark mode.
    """
    plain = brand.pixmap(mark, 256, dark=False).toImage()
    inverted = brand.pixmap(mark, 256, dark=True).toImage()

    assert _mean_contrast(plain, BONE) > 120, "should be legible on bone as supplied"
    assert _mean_contrast(plain, CHARCOAL) < 60, "the defect this guards against"
    assert _mean_contrast(inverted, CHARCOAL) > 120, "inverting must fix dark mode"


@pytest.mark.parametrize("mark", [brand.Mark.NEST, brand.Mark.GLASSES])
def test_the_marks_that_carry_their_own_outlines_are_left_alone(qt_app, mark):
    """These read on both surfaces already, so inverting them would be the bug.

    Measured: nest 145/86, glasses 145/99 (bone/charcoal). The glasses in particular are
    *white* art -- inverting them for dark mode would turn the approval mark black
    exactly when it is meant to feel crisp.
    """
    assert _mean_contrast(brand.pixmap(mark, 256, dark=False).toImage(), BONE) > 60
    assert _mean_contrast(brand.pixmap(mark, 256, dark=True).toImage(), CHARCOAL) > 60
    # Unchanged between schemes: the same prepared file, untouched.
    light = brand.pixmap(mark, 256, dark=False).toImage()
    dark = brand.pixmap(mark, 256, dark=True).toImage()
    assert light == dark, f"{mark} must not be altered for dark mode"


def _band_contrast(image, background, y0_frac, y1_frac) -> float:
    """Contrast over a horizontal band, for marks that are composites."""
    from PySide6.QtGui import qAlpha, qBlue, qGreen, qRed

    br, bg, bb = background
    bg_lum = 0.299 * br + 0.587 * bg + 0.114 * bb
    total = 0.0
    count = 0
    y_start = int(image.height() * y0_frac)
    y_end = int(image.height() * y1_frac)
    for y in range(y_start, y_end, 2):
        for x in range(0, image.width(), 2):
            px = image.pixel(x, y)
            alpha = qAlpha(px) / 255.0
            if alpha <= 0.15:
                continue
            r = qRed(px) * alpha + br * (1 - alpha)
            g = qGreen(px) * alpha + bg * (1 - alpha)
            b = qBlue(px) * alpha + bb * (1 - alpha)
            total += abs((0.299 * r + 0.587 * g + 0.114 * b) - bg_lum)
            count += 1
    return total / count if count else 0.0


def test_the_compact_mark_has_no_dark_variant_yet(qt_app):
    """A known gap in the prepared delivery, pinned so it cannot be forgotten.

    The compact mark is a pre-composited **black ON over a white-ish nest**. A single
    mean-contrast figure over the whole image scores it 73 on charcoal and looks fine,
    because the white nest pixels dominate the average. Measured band by band it is not
    fine at all: the top third, which is the ON, scores **28.1** with a mean ink
    luminance of 0.3 -- pure black on charcoal -- while the nest bands score 85.6 and
    88.0. The ON is invisible in dark mode.

    It cannot be fixed the way the wordmark was. Inverting the whole composite would
    blacken the nest, and the two elements are already flattened into one PNG, so there
    is nothing here to inverted selectively. The proper fix is a dark composite in the
    delivery, next to ``open_nest_compact_*``, since that is where the approved ON-to-nest
    proportions live -- reconstructing them here would be guessing at brand geometry.

    Nothing consumes this component yet, so nothing is broken today. It blocks the
    Workbench header in 10C (guide section 57 asks for the compact mark there). When a
    dark variant arrives, this test is the one to delete.
    """
    image = brand.pixmap(brand.Mark.COMPACT, 256, dark=True).toImage()
    on_band = _band_contrast(image, CHARCOAL, 0.0, 1 / 3)
    nest_band = _band_contrast(image, CHARCOAL, 2 / 3, 1.0)

    assert nest_band > 60, "the nest half reads on charcoal"
    assert on_band < 45, (
        f"the ON band now scores {on_band:.1f} on charcoal -- if a dark compact variant "
        "has been supplied, wire it up in brand.py and delete this test"
    )


def test_the_compact_mark_is_fine_on_a_light_surface(qt_app):
    """Both halves read on bone, which is why the gap is dark-mode-only."""
    image = brand.pixmap(brand.Mark.COMPACT, 256, dark=False).toImage()
    assert _band_contrast(image, BONE, 0.0, 1 / 3) > 60
    assert _band_contrast(image, BONE, 2 / 3, 1.0) > 60


# ------------------------------------------------------- the eagle stays put

def _body_anchor(image):
    """Feet baseline and body right edge, ignoring the wing tips.

    The wings are what animate; the body is what must not. Sampling the lower 55% and
    right 75% of the canvas excludes the wing tips, so this tracks the bird rather than
    the pose.
    """
    from PySide6.QtGui import qAlpha

    h, w = image.height(), image.width()
    lowest = -1
    rightmost = -1
    for y in range(int(h * 0.45), h):
        for x in range(int(w * 0.25), w):
            if qAlpha(image.pixel(x, y)) > 128:
                lowest = max(lowest, y)
                rightmost = max(rightmost, x)
    return lowest, rightmost


def test_the_eagle_frames_are_registered_on_one_body(qt_app):
    """Only the wings may move. Guide section 37 forbids animating its position.

    The prepared frames are faithful to the supplied sheet, and the sheet is a contact
    sheet of poses rather than a registered strip: row 0's feet average y=344.7 and row
    1's y=301.3, a ~43 px offset that shows up as a 51 px feet spread and a 53 px body
    spread across the twelve prepared 342 px frames. Played in order the bird hops about
    13% of the canvas height between frames 6 and 7 and drops back at the loop.

    This test re-derives the alignment from the rendered frames, so it is checking the
    result rather than the offset table. If a corrected frame set is ever delivered, the
    offsets fall to roughly zero and this still passes.
    """
    from PySide6.QtWidgets import QWidget

    size = 128
    parent = QWidget()
    indicator = brand.EagleActivityIndicator(parent, size=size)
    try:
        feet = []
        body = []
        for index in range(brand.EAGLE_FRAMES):
            indicator._show_frame(index)
            image = indicator._canvas.pixmap().toImage()
            low, right = _body_anchor(image)
            assert low > 0, f"frame {index + 1} rendered nothing in the body region"
            feet.append(low)
            body.append(right)
        feet_spread = max(feet) - min(feet)
        body_spread = max(body) - min(body)
        # As delivered these were 19 px and 20 px at this size. A couple of pixels is
        # genuine leg movement; anything more is the bird hopping.
        assert feet_spread <= 3, f"feet move {feet_spread}px across the cycle: {feet}"
        assert body_spread <= 3, f"body moves {body_spread}px across the cycle: {body}"
    finally:
        parent.deleteLater()


def test_the_unregistered_frames_really_do_drift(qt_app):
    """The negative control for the test above.

    If the prepared frames were already registered, the previous test would pass without
    the offset table doing anything, and would be pinning nothing. This measures the raw
    frames to show the defect is real.
    """
    from PySide6.QtGui import QImage

    feet = []
    for frame in range(1, brand.EAGLE_FRAMES + 1):
        image = QImage(str(brand.eagle_frame_path(128, frame)))
        assert not image.isNull()
        low, _ = _body_anchor(image)
        feet.append(low)
    assert max(feet) - min(feet) > 10, (
        "the prepared frames appear to be registered now -- if so, the offset table in "
        "brand.py can be retired and this test removed"
    )


# ------------------------------------------------------- playback restraint

def test_the_indicator_does_not_animate_until_asked(qt_app):
    """Section 36: the eagle must not become decoration that runs constantly."""
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    indicator = brand.EagleActivityIndicator(parent, size=96)
    try:
        assert not indicator.running
        indicator.start()
        assert indicator.running
        indicator.start()  # idempotent
        assert indicator.running
        indicator.stop()
        assert not indicator.running
    finally:
        parent.deleteLater()


def test_hiding_the_indicator_stops_its_timer(qt_app):
    """A hidden indicator that keeps ticking burns CPU behind a switched-away page."""
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    indicator = brand.EagleActivityIndicator(parent, size=64)
    try:
        indicator.start()
        assert indicator.running
        indicator.hide()
        assert not indicator.running
    finally:
        parent.deleteLater()


def test_the_frame_rate_matches_the_prepared_recommendation():
    """The delivery recommends 125 ms; guide section 35 asks for 6-10 fps."""
    assert brand.EAGLE_FRAME_MS == 125
    assert 6 <= 1000 / brand.EAGLE_FRAME_MS <= 10


# ------------------------------------------------------- accessibility

def test_every_mark_carries_an_accessible_name(qt_app):
    """Section 46: a brand graphic is never the only signal."""
    for mark in brand.Mark:
        label = brand.mark_label(mark, 128)
        assert label.accessibleName(), f"{mark} has no accessible name"


def test_the_indicator_says_what_it_means(qt_app):
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    try:
        indicator = brand.EagleActivityIndicator(parent, size=64)
        assert indicator.accessibleName() == "Open Nest is working"
    finally:
        parent.deleteLater()
