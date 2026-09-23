#!/usr/bin/env python3
"""Deterministic preparation of the Open Nest runtime brand assets.

Brand guide section 50 asks for exactly this: a small reproducible script rather than
hand-edited generated copies, so frame slicing and integer resizing can be re-run.
Preparation here is **technical only** -- nothing draws, redraws, recolours or invents
artwork. Every output is a resize of a supplied master, and the canonical originals in
``assets/*.png`` are never read for writing and never modified.

Run it from the repository root::

    .venv/bin/python tools/prepare_brand_assets.py            # write the assets
    .venv/bin/python tools/prepare_brand_assets.py --check    # report, change nothing
    .venv/bin/python tools/prepare_brand_assets.py --table    # print the eagle offsets

Three things about the method are measured rather than chosen.

**Area-averaging, not nearest-neighbour, and the reason only shows up in motion.** The
supplied delivery's frame sets are exact nearest-neighbour downscales of
``master_frames`` -- verified at 0.00 mean difference, so ``asset_manifest.json``'s
``"pixel_rendering": "nearest-neighbor"`` is accurate and describes what was done. On a
*single frame* nearest is fine and even marginally the most faithful: measured across the
twelve poses at 32 px, ink mass lands at 99.6% of the master against area-averaging's
100.0%, and round-trip error is 12.66 against 12.97. What that average hides is the
**spread between frames**. Nearest-neighbour samples a different subset of the soft
source in each pose, so the bird's apparent weight swings 3.90 percentage points across
the cycle at 32 px and 2.17 pp at 64 px, against 0.42 pp and 0.44 pp for area-averaging.
In a still that is invisible; in a twelve-frame loop it is the bird pulsing as it flaps.
So the ladder is regenerated with ``Image.BOX``, which is a true area average.

**Premultiplied, because straight alpha bleeds the background into the edges.** The
artwork is black-on-transparent and the transparent pixels are ``(0, 0, 0, 0)``, so
straight-alpha resizing pulls black into every partially covered edge pixel and darkens
the silhouette. Resizing premultiplied and dividing alpha back out is the correct
operation for RGBA and is what keeps the edges the weight the artist drew.

**The source is soft, so there is no pixel grid to protect.** Only 0.7% of the eagle
sheet's pixels are fully opaque and 23.6% are partially transparent: this is pixel-art
*styled* raster at ~2000 px, not a sprite on an integer grid. That is why a smooth filter
is not vandalism here and why nearest-neighbour buys nothing -- there are no hard
one-pixel features to preserve.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError:  # pragma: no cover - a developer tool, not an app dependency
    sys.exit(
        "This script needs Pillow and numpy. They are in requirements/projects.txt:\n"
        "    .venv/bin/pip install pillow numpy"
    )

ROOT = Path(__file__).resolve().parent.parent
DELIVERY = ROOT / "assets" / "open_nest_asset_delivery"
LOGOS = DELIVERY / "01_logos"
SYMBOLS = DELIVERY / "02_symbols"
EAGLE = DELIVERY / "03_eagle_animation"

#: The runtime eagle ladder. 32 and 48 are the sizes the interface actually uses (at 1x);
#: 64 and 96 are their 2x partners. 128 and 256 are kept because the delivery shipped
#: them and a larger indicator may yet be wanted.
EAGLE_SIZES = (32, 48, 64, 96, 128, 256)

#: Frames in the supplied cycle. Read from disk rather than trusted -- guide section 34
#: says to determine the count from the artwork.
EAGLE_MASTERS = EAGLE / "master_frames"

#: Mark sizes to add to the delivery's ladder, each with the master it derives from.
#:
#: **Deliberately empty, and that is a finding rather than an omission.** A 40 px compact
#: mark was generated and then withdrawn: rendered, its ON is illegible and its nest is a
#: blob, which is precisely guide section 33's "do not reduce the artwork until it becomes
#: illegible". The delivery's compact ladder starts at 64 and its nest ladder at 96, and
#: those floors turn out to encode legibility rather than convenience -- 64 is exactly
#: where the lockup starts to read. So the supplied mark sizes are taken as given.
#:
#: The eagle is the exception the rebuild below exists for, and the difference is
#: structural: it is one bold silhouette with no fine detail to lose, so it still reads
#: at 32 px where a lockup containing two letters does not.
#:
#: If a size is ever added here, derive the compact mark from the **prepared composite**
#: rather than recomposing ON + nest -- the approved proportions live in that file, and
#: rebuilding the lockup here would be inventing brand geometry.
MARK_OUTPUTS: tuple[tuple[Path, Path, int, str], ...] = ()


# --------------------------------------------------------------------------- resizing

def _to_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"), dtype=np.float64)


def resize_rgba(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Area-average ``image`` down to ``size``, premultiplying so edges keep their weight.

    Straight-alpha resizing of black-on-transparent art averages the invisible black
    backing into every partially covered pixel, which thickens and darkens the
    silhouette. Premultiplying first, resizing, then dividing alpha back out is the
    correct operation and the one that leaves the artwork looking like itself.
    """
    source = _to_array(image)
    alpha = source[..., 3:4] / 255.0
    premultiplied = np.concatenate([source[..., :3] * alpha, source[..., 3:4]], axis=-1)
    small = Image.fromarray(
        premultiplied.round().clip(0, 255).astype(np.uint8), "RGBA"
    ).resize(size, Image.BOX)

    out = _to_array(small)
    out_alpha = out[..., 3:4] / 255.0
    rgb = np.divide(
        out[..., :3], out_alpha, out=np.zeros_like(out[..., :3]), where=out_alpha > 0
    )
    return Image.fromarray(
        np.concatenate([rgb.clip(0, 255), out[..., 3:4]], axis=-1).round().astype(np.uint8),
        "RGBA",
    )


# --------------------------------------------------------------------------- registration

def body_anchor(alpha: np.ndarray) -> tuple[int, int]:
    """Feet baseline and body right edge, with the wing tips excluded.

    The wings are what animate and the body is what must not, so a plain bounding box
    would read a legitimate flap as mis-registration (or hide a real drift behind one).
    Sampling the lower 55% and right 75% of the canvas tracks the bird rather than the
    pose -- the same rule ``tests/test_brand.py`` uses to check the result.
    """
    height, width = alpha.shape
    region = alpha[int(height * 0.45):, int(width * 0.25):]
    rows, cols = np.nonzero(region > 128)
    if len(rows) == 0:
        return -1, -1
    return int(rows.max() + int(height * 0.45)), int(cols.max() + int(width * 0.25))


#: Alpha at or above which a pixel counts as ink for the clamp below -- about 3%
#: opacity. Clamping on ``alpha > 0`` instead sounds safer and is much worse: the
#: artwork is soft enough that a single one-part-in-255 pixel reaches the canvas edge in
#: most poses, which blocks the translation entirely and leaves the body hopping 16 px
#: at 256. Measured both ways; ``--check`` reports the ink this threshold clips so the
#: trade stays visible rather than assumed.
CLAMP_ALPHA = 8


def registration_offsets(frames: list[Image.Image]) -> tuple[tuple[int, int], ...]:
    """Whole-pixel translations putting every pose on one body anchor.

    The supplied sheet is a contact sheet of poses, not a registered animation strip:
    its two rows sit about 43 px apart at master scale, so played in order the bird hops
    at the row boundary and drops back at the loop. Guide section 37 forbids animating
    its position, so each frame is translated -- never scaled, never resampled -- onto
    the median anchor, and clamped so no *visible* ink is pushed off the canvas.
    """
    alphas = [_to_array(frame)[..., 3] for frame in frames]
    anchors = [body_anchor(a) for a in alphas]
    target_y = int(np.median([y for y, _ in anchors]))
    target_x = int(np.median([x for _, x in anchors]))

    offsets = []
    for alpha, (y, x) in zip(alphas, anchors):
        dy, dx = target_y - y, target_x - x
        rows, cols = np.nonzero(alpha >= CLAMP_ALPHA)
        if len(rows):
            size = alpha.shape[0]
            dy = max(-int(rows.min()), min(dy, size - 1 - int(rows.max())))
            dx = max(-int(cols.min()), min(dx, size - 1 - int(cols.max())))
        offsets.append((int(dx), int(dy)))
    return tuple(offsets)


def clipped_ink(frames: list[Image.Image], offsets) -> float:
    """Percentage of total ink the registration shifts off the canvas.

    The honest cost of :data:`CLAMP_ALPHA`. If this is not ~0 the threshold is wrong and
    the bird is losing a wing tip to keep its feet still, which is the worse trade.
    """
    kept = lost = 0.0
    for frame, (dx, dy) in zip(frames, offsets):
        alpha = _to_array(frame)[..., 3]
        total = alpha.sum()
        h, w = alpha.shape
        window = alpha[
            slice(max(0, -dy), min(h, h - dy)), slice(max(0, -dx), min(w, w - dx))
        ]
        kept += window.sum()
        lost += total - window.sum()
    return float(lost / (kept + lost) * 100) if kept + lost else 0.0


def registered_spread(frames: list[Image.Image], offsets) -> tuple[int, int]:
    """Feet and body spread once the offsets are applied. Zero would be perfect."""
    feet, body = [], []
    for frame, (dx, dy) in zip(frames, offsets):
        alpha = _to_array(frame)[..., 3]
        shifted = np.zeros_like(alpha)
        h, w = alpha.shape
        ys, xs = slice(max(0, dy), min(h, h + dy)), slice(max(0, dx), min(w, w + dx))
        sy, sx = slice(max(0, -dy), min(h, h - dy)), slice(max(0, -dx), min(w, w - dx))
        shifted[ys, xs] = alpha[sy, sx]
        y, x = body_anchor(shifted)
        feet.append(y)
        body.append(x)
    return max(feet) - min(feet), max(body) - min(body)


# --------------------------------------------------------------------------- the run

def eagle_master_frames() -> list[Image.Image]:
    paths = sorted(EAGLE_MASTERS.glob("eagle_*.png"))
    if not paths:
        sys.exit(f"no master frames under {EAGLE_MASTERS}")
    return [Image.open(path).convert("RGBA") for path in paths]


def ink_spread(frames: list[Image.Image], masters: list[Image.Image]) -> float:
    """Percentage-point swing in ink mass across the cycle -- the shimmer measurement."""
    base = np.array([_to_array(m)[..., 3].mean() for m in masters])
    got = np.array([_to_array(f)[..., 3].mean() for f in frames])
    ratio = got / base
    return float((ratio.max() - ratio.min()) * 100)


def prepare(write: bool) -> int:
    masters = eagle_master_frames()
    print(f"{len(masters)} master frames at {masters[0].size[0]}px")

    table: dict[int, tuple[tuple[int, int], ...]] = {}
    for size in EAGLE_SIZES:
        frames = [resize_rgba(master, (size, size)) for master in masters]
        offsets = registration_offsets(frames)
        feet, body = registered_spread(frames, offsets)
        table[size] = offsets
        print(
            f"  frames_{size:<4} ink spread {ink_spread(frames, masters):4.2f}pp   "
            f"registered feet {feet}px body {body}px   "
            f"clipped {clipped_ink(frames, offsets):.3f}%"
        )
        if write:
            folder = EAGLE / f"frames_{size}"
            folder.mkdir(parents=True, exist_ok=True)
            for index, frame in enumerate(frames, start=1):
                frame.save(folder / f"eagle_{index:02d}.png")

    for source, folder, size, pattern in MARK_OUTPUTS:
        master = Image.open(source).convert("RGBA")
        width = size
        height = max(1, round(master.height * size / master.width))
        mark = resize_rgba(master, (width, height))
        print(f"  {pattern.format(size=size):<30} {width}x{height} from {source.name}")
        if write:
            mark.save(folder / pattern.format(size=size))

    if write:
        print("\nwritten. Paste the table below into opennest/ui/brand.py.")
    print_table(table)
    return 0


def print_table(table: dict[int, tuple[tuple[int, int], ...]]) -> None:
    """Emit the table already wrapped, so pasting it into brand.py passes ruff."""
    print("\n_EAGLE_REGISTRATION: dict[int, tuple[tuple[int, int], ...]] = {")
    for size, offsets in table.items():
        pairs = [f"({dx}, {dy})" for dx, dy in offsets]
        indent = " " * (len(f"    {size}: ("))
        half = ", ".join(pairs[:6])
        rest = ", ".join(pairs[6:])
        print(f"    {size}: ({half},")
        print(f"{indent}{rest}),")
    print("}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report only, write nothing")
    parser.add_argument("--table", action="store_true", help="print the offsets and stop")
    args = parser.parse_args(argv)
    if args.table:
        masters = eagle_master_frames()
        table = {
            size: registration_offsets([resize_rgba(m, (size, size)) for m in masters])
            for size in EAGLE_SIZES
        }
        print_table(table)
        return 0
    return prepare(write=not args.check)


if __name__ == "__main__":
    raise SystemExit(main())
