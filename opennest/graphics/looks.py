"""What a thing looks like, from what Gary said -- checked, repaired, and written as code.

Gary describes a look in ``game_object``'s arguments: a picture in the project, one of
the kit's ready-made drawings, shapes, or just a colour. This module turns that into a
:class:`Look` -- a description Open Nest has checked -- and into the Python a child's
game will hold (``Picture("assets/eagle.png")``, ``Vehicle("red")``, ``Drawing(...)``).

Everything here is deterministic, and nothing here imports pygame: the application
never runs a game's graphics, it only writes code that does.

Two repairs are made rather than refused, because the Phase 13C prototype measured the
4B model making them on most calls (SPIKES.md section 28):

- **Shapes placed on the screen instead of in their own box.** A road "at [0, 380]"
  whose rectangle is also "[0, 380, 640, 100]" means the road, not a road 380 pixels
  below itself. When every shape fits the box only once ``at`` is taken off, it is.
- **No size.** The box is where the shapes are.

Both are reported in the tool's result, so what Gary says afterwards can match.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

KIT = Path(__file__).with_name("kit") / "scene.py"

#: The kit's ready-made drawings, as Gary names them, and the class that draws each.
DRAWINGS = {
    "vehicle": "Vehicle", "building": "Building", "house": "House", "tree": "Tree",
    "cloud": "Cloud", "road": "Road", "ground": "Ground", "sky": "Sky", "coin": "Coin",
    "star": "Star", "platform": "Platform", "sign": "Sign",
}

#: Names a thing might be given that mean one of those drawings, when Gary gave no look
#: at all -- a thing he called "road" is drawn as a road. Only the drawings' own names
#: and their plurals, and the vehicles a child names most. Never used to override a
#: look Gary did give.
NAMED_DRAWINGS = {
    **{name: name for name in DRAWINGS},
    **{f"{name}s": name for name in DRAWINGS if name not in ("sky", "ground", "road")},
    "clouds": "cloud", "buildings": "building", "houses": "house", "trees": "tree",
    "car": "vehicle", "cars": "vehicle", "truck": "vehicle", "trucks": "vehicle",
    "bus": "vehicle", "buses": "vehicle", "van": "vehicle", "vans": "vehicle",
    "taxi": "vehicle", "taxis": "vehicle", "vehicles": "vehicle", "roads": "road",
    "street": "road", "streets": "road", "grass": "ground", "floor": "ground",
    "skies": "sky", "background": "sky", "skyline": "building", "town": "building",
    "city": "building", "shop": "building", "shops": "building", "coins": "coin",
    "stars": "star", "platforms": "platform", "signs": "sign",
}

#: Shapes, as Gary writes them, with how many numbers each takes.
SHAPES = {"rect": 4, "circle": 3, "ellipse": 4, "triangle": 4, "line": 4}

#: Named CSS colours the kit's palette does not have, as (red, green, blue). The kit
#: hands any other name to pygame, which knows these too; converting them here means a
#: game never depends on pygame's list agreeing with this one.
_CSS = {
    "aqua": (0, 255, 255), "coral": (255, 127, 80), "crimson": (220, 20, 60),
    "indigo": (75, 0, 130), "ivory": (255, 255, 240), "khaki": (240, 230, 140),
    "lavender": (230, 230, 250), "lime": (0, 255, 0), "maroon": (128, 0, 0),
    "mint": (170, 240, 200), "olive": (128, 128, 0), "peach": (255, 218, 185),
    "plum": (221, 160, 221), "salmon": (250, 128, 114), "sand": (225, 200, 150),
    "sienna": (160, 82, 45), "slateblue": (106, 90, 205), "slategray": (112, 128, 144),
    "tomato": (255, 99, 71), "turquoise": (64, 224, 208), "violet": (238, 130, 238),
    "wheat": (245, 222, 179), "chocolate": (210, 105, 30), "orchid": (218, 112, 214),
    "skyblue": (135, 206, 235), "steelblue": (70, 130, 180), "forestgreen": (34, 139, 34),
    "limegreen": (50, 205, 50), "seagreen": (46, 139, 87), "royalblue": (65, 105, 225),
    "hotpink": (255, 105, 180), "deeppink": (255, 20, 147), "firebrick": (178, 34, 34),
    "goldenrod": (218, 165, 32), "darkorange": (255, 140, 0), "lightpink": (255, 182, 193),
    "lightyellow": (255, 250, 205), "lightcoral": (240, 128, 128),
}

#: Words a model reaches for that are not colours but mean one.
_ALIASES = {"sky": "skyblue", "road": "asphalt", "tarmac": "asphalt", "grass": "grass",
            "sun": "yellow", "leaf": "green", "leaves": "green", "wood": "brown",
            "dirt": "brown", "sea": "blue", "water": "blue", "snow": "white",
            "night": "navy", "stone": "gray", "metal": "silver", "brick": "darkred"}


def quoted(text: str) -> str:
    """A string the way the starter writes one: in double quotes."""
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def kit_source() -> str:
    return KIT.read_text(encoding="utf-8")


def kit_version(source: str | None = None) -> int | None:
    """The ``VERSION`` a scene.py declares, or None when it is not one of ours."""
    tree = _parse(source if source is not None else kit_source())
    for node in tree.body if tree else ():
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            return value if isinstance(value, int) else None
    return None


def kit_classes(source: str | None = None) -> set[str]:
    """The classes a scene.py defines -- what code written against it may use."""
    tree = _parse(source if source is not None else kit_source())
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)} if tree \
        else set()


def palette() -> dict[str, tuple[int, int, int]]:
    """The kit's own colour names, read from the kit file -- one source of truth."""
    tree = _parse(kit_source())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "COLOURS" for t in node.targets):
            return ast.literal_eval(node.value)
    return {}


def _parse(source: str):
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


# ----------------------------------------------------------------------------- colours

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def colour(value, notes: list[str] | None = None, *, default: str = "white"):
    """A colour the kit will draw, as the code should say it: a name the kit's palette
    has, ``"#rrggbb"``, or an (r, g, b) tuple. Unknown names become the nearest thing
    with a note, never an error the child sees."""
    notes = notes if notes is not None else []
    if isinstance(value, (list, tuple)) and len(value) in (3, 4) and all(
            isinstance(v, (int, float)) for v in value):
        return tuple(max(0, min(255, round(v))) for v in value[:3])
    if not isinstance(value, str) or not value.strip():
        return default
    text = value.strip()
    match = _HEX.match(text)
    if match:
        return "#" + match.group(1).lower()
    key = re.sub(r"[\s_-]+", "", text.lower())
    names = palette()
    if key in names:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    if key in _CSS:
        return _CSS[key]
    for prefix, amount in (("dark", -0.3), ("light", 0.4), ("pale", 0.5), ("bright", 0.15)):
        base = key[len(prefix):]
        if key.startswith(prefix) and (base in names or base in _CSS):
            rgb = names.get(base) or _CSS[base]
            target = 255 if amount > 0 else 0
            return tuple(round(c + (target - c) * abs(amount)) for c in rgb)
    notes.append(f"Open Nest doesn't know the colour {text!r}, so it used {default}")
    return default


def rgb(value) -> tuple[int, int, int] | None:
    """A colour ``colour()`` returned, as (red, green, blue) -- for a constant."""
    if isinstance(value, tuple):
        return value
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    if isinstance(value, str):
        return palette().get(value) or _CSS.get(value)
    return None


def colour_code(value) -> str:
    return quoted(value) if isinstance(value, str) else \
        f"({value[0]}, {value[1]}, {value[2]})"


# ----------------------------------------------------------------------------- the look


@dataclass
class Look:
    """A look Open Nest has checked. ``kind`` is picture, animation, drawing, shapes or
    colour; the rest depends on it."""

    kind: str
    picture: str = ""
    frames: int = 0
    series: tuple[str, ...] = ()
    drawing: str = ""
    fill: object = None
    text: str = ""
    shapes: list = field(default_factory=list)
    #: The box the shapes are drawn in (shapes only), or the shape a ready-made drawing
    #: keeps when drawn on a game's own rectangle.
    box: tuple[int, int] | None = None

    def code(self, *, keep_shape: tuple[int, int] | None = None) -> str:
        """The look as the game's code says it."""
        if self.kind == "picture":
            return f"Picture({quoted(self.picture)})"
        if self.kind == "animation":
            if self.series:
                listed = ", ".join(quoted(path) for path in self.series)
                return f"Animation([{listed}], fps=8)"
            return f"Animation({quoted(self.picture)}, frames={self.frames}, fps=8)"
        if self.kind == "drawing":
            args = [colour_code(self.fill)] if self.fill is not None else []
            if keep_shape:
                args.append(f"size=({keep_shape[0]}, {keep_shape[1]})")
            if self.drawing == "sign" and self.text:
                args.append(f"words={quoted(self.text)}")
            return f"{DRAWINGS[self.drawing]}({', '.join(args)})"
        if self.kind == "colour":
            return f"Colour({colour_code(self.fill)}, round=6)"
        lines = ",\n".join(f"    {shape}" for shape in self.shapes)
        return f"Drawing(({self.box[0]}, {self.box[1]}), [\n{lines},\n])"

    def classes(self) -> set[str]:
        """The kit classes the code for this look uses."""
        if self.kind == "picture":
            return {"Picture"}
        if self.kind == "animation":
            return {"Animation"}
        if self.kind == "drawing":
            return {DRAWINGS[self.drawing]}
        if self.kind == "colour":
            return {"Colour"}
        used = {"Drawing"}
        for shape in self.shapes:
            used.add(shape.split("(", 1)[0])
        return used

    def describe(self) -> str:
        if self.kind == "picture":
            return f"the picture {self.picture}"
        if self.kind == "animation":
            count = len(self.series) or self.frames
            return f"the animation {self.picture} ({count} frames)"
        if self.kind == "drawing":
            return f"a ready-made {self.drawing} drawing"
        if self.kind == "colour":
            return "a plain rounded box"
        return f"a drawing of {len(self.shapes)} shape{'' if len(self.shapes) == 1 else 's'}"



class LookError(Exception):
    """A look that cannot be used: the picture is missing, or is not a picture."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


# ----------------------------------------------------------------------------- pictures


def find_picture(asked: str, pictures: list[str]) -> str | None:
    """The project picture ``asked`` means -- a path, a filename, or the child's words
    ("my eagle picture") -- or None. Only ever one: two that fit is no answer."""
    asked = (asked or "").strip()
    if not asked:
        return None
    by_path = {p.lower(): p for p in pictures}
    for candidate in (asked, f"assets/{asked}", asked.lstrip("./")):
        if candidate.lower() in by_path:
            return by_path[candidate.lower()]
    names = {Path(p).name.lower(): p for p in pictures}
    if Path(asked).name.lower() in names:
        return names[Path(asked).name.lower()]
    words = {w for w in re.split(r"[^a-z0-9]+", asked.lower()) if len(w) > 2}
    words -= {"picture", "image", "png", "jpg", "jpeg", "the", "my", "assets", "photo",
              "drawing", "gif", "webp", "use", "this", "that"}
    matches = [p for p in pictures
               if words & {w for w in re.split(r"[^a-z0-9]+", Path(p).stem.lower()) if w}]
    return matches[0] if len(matches) == 1 else None


def numbered_series(path: str, pictures: list[str]) -> tuple[str, ...]:
    """``assets/eagle_01.png`` and its numbered siblings, in order, when there are some."""
    match = re.match(r"^(.*?)(\d+)(\.\w+)$", path)
    if not match:
        return ()
    stem, _number, suffix = match.groups()
    found = []
    for picture in pictures:
        other = re.match(rf"^{re.escape(stem)}(\d+){re.escape(suffix)}$", picture)
        if other:
            found.append((int(other.group(1)), picture))
    return tuple(p for _, p in sorted(found)) if len(found) > 1 else ()


# ----------------------------------------------------------------------------- shapes


def _numbers(value, count: int) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != count:
        return None
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        return None


def _num(value: float) -> str:
    value = round(value, 1)
    return str(int(value)) if value == int(value) else str(value)


def _extent(shape: dict) -> tuple[float, float, float, float] | None:
    """The box a shape Gary wrote covers, (x1, y1, x2, y2), or None if it is not one."""
    for kind, count in SHAPES.items():
        if kind in shape:
            nums = _numbers(shape[kind], count)
            if nums is None:
                return None
            if kind == "circle":
                x, y, r = nums
                return (x - r, y - r, x + r, y + r)
            if kind == "line":
                x1, y1, x2, y2 = nums
                return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            x, y, w, h = nums
            return (x, y, x + w, y + h)
    if "polygon" in shape and isinstance(shape["polygon"], (list, tuple)):
        points = [_numbers(p, 2) for p in shape["polygon"]]
        if len(points) >= 3 and all(points):
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            return (min(xs), min(ys), max(xs), max(ys))
    if "text" in shape:
        at = _numbers(shape.get("at", [0, 0]), 2) or [0, 0]
        size = float(shape.get("size", 20) or 20)
        return (at[0], at[1], at[0] + size * 0.5 * len(str(shape["text"])), at[1] + size)
    for drawing in DRAWINGS:
        if drawing in shape:
            nums = _numbers(shape[drawing], 4)
            if nums:
                return (nums[0], nums[1], nums[0] + nums[2], nums[1] + nums[3])
    return None


def _shape_code(shape: dict, dx: float, dy: float, notes: list[str]) -> str | None:
    """One shape as the kit's code, moved by (-dx, -dy). None for a shape it cannot use."""
    fill = colour(shape.get("color", shape.get("colour")), notes)
    if isinstance(shape.get("color"), (list, tuple)) and len(shape["color"]) == 2 and all(
            isinstance(c, str) for c in shape["color"]):
        top, bottom = (colour(c, notes) for c in shape["color"])
        fill_code = f"({colour_code(top)}, {colour_code(bottom)})"
    else:
        fill_code = colour_code(fill)
    for kind, count in SHAPES.items():
        if kind not in shape:
            continue
        nums = _numbers(shape[kind], count)
        if nums is None:
            return None
        if kind == "circle":
            x, y, r = nums
            return f"Circle({_num(x - dx)}, {_num(y - dy)}, {_num(abs(r))}, {fill_code})"
        if kind == "line":
            x1, y1, x2, y2 = nums
            width = shape.get("width", 3)
            dash = shape.get("dash", 0)
            extra = f", width={_num(float(width))}" if isinstance(width, (int, float)) else ""
            extra += f", dash={_num(float(dash))}" if isinstance(dash, (int, float)) and dash \
                else ""
            return (f"Line(({_num(x1 - dx)}, {_num(y1 - dy)}), ({_num(x2 - dx)}, "
                    f"{_num(y2 - dy)}), {fill_code}{extra})")
        x, y, w, h = nums
        name = {"rect": "Rect", "ellipse": "Ellipse", "triangle": "Triangle"}[kind]
        extra = ""
        if kind == "rect" and isinstance(shape.get("round"), (int, float)) and shape["round"]:
            extra = f", round={_num(float(shape['round']))}"
        return f"{name}({_num(x - dx)}, {_num(y - dy)}, {_num(abs(w))}, {_num(abs(h))}, " \
               f"{fill_code}{extra})"
    if "polygon" in shape:
        points = [_numbers(p, 2) for p in shape["polygon"]] if isinstance(
            shape["polygon"], (list, tuple)) else []
        if len(points) < 3 or not all(points):
            return None
        listed = ", ".join(f"({_num(x - dx)}, {_num(y - dy)})" for x, y in points)
        return f"Polygon([{listed}], {fill_code})"
    if "text" in shape:
        at = _numbers(shape.get("at", [0, 0]), 2) or [0, 0]
        size = shape.get("size", 20)
        size = size if isinstance(size, (int, float)) else 20
        return (f"Text({quoted(str(shape['text'])[:40])}, {_num(at[0] - dx)}, {_num(at[1] - dy)}, "
                f"{fill_code}, size={_num(float(size))})")
    return None


def shapes_look(shapes, size, at, notes: list[str]) -> Look | None:
    """Gary's shapes as a Drawing, placed in their own box -- or None if none are usable."""
    if not isinstance(shapes, (list, tuple)):
        return None
    usable = [s for s in shapes if isinstance(s, dict) and _extent(s) is not None]
    dropped = sum(1 for s in shapes if isinstance(s, dict)) - len(usable)
    if dropped:
        notes.append(f"left out {dropped} shape{'' if dropped == 1 else 's'} it could not "
                     f"read")
    usable = [s for s in usable if not any(d in s for d in DRAWINGS)]
    if not usable:
        return None
    extents = [_extent(s) for s in usable]
    x1 = min(e[0] for e in extents)
    y1 = min(e[1] for e in extents)
    x2 = max(e[2] for e in extents)
    y2 = max(e[3] for e in extents)
    box = size
    dx = dy = 0.0
    if at is not None and box is not None:
        ax, ay = at
        inside_as_given = x1 >= -1 and y1 >= -1 and x2 <= box[0] + 1 and y2 <= box[1] + 1
        inside_moved = x1 >= ax - 1 and y1 >= ay - 1 and x2 <= ax + box[0] + 1 and \
            y2 <= ay + box[1] + 1
        if not inside_as_given and inside_moved and (ax or ay):
            dx, dy = ax, ay
            notes.append("its shapes were given as places on the screen, so Open Nest "
                         "moved them into its own box")
    if box is None:
        box = (max(1, math.ceil(x2 - min(0.0, x1))), max(1, math.ceil(y2 - min(0.0, y1))))
    elif x2 - dx > box[0] + 1 or y2 - dy > box[1] + 1:
        grown = (max(box[0], math.ceil(x2 - dx)), max(box[1], math.ceil(y2 - dy)))
        notes.append(f"its shapes reach past its size, so its box is {grown[0]}x{grown[1]}")
        box = grown
    codes = [code for code in (_shape_code(s, dx, dy, notes) for s in usable) if code]
    if not codes:
        return None
    return Look("shapes", shapes=codes, box=(int(box[0]), int(box[1])))


def infer_drawing(name: str) -> str | None:
    """The ready-made drawing a thing's name means, when Gary gave no look at all."""
    key = re.sub(r"[^a-z]", "", (name or "").lower())
    return NAMED_DRAWINGS.get(key)
