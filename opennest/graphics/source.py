"""Reading and changing the scene in a game's own source -- with the parser, by name.

A game that uses the kit says what it shows in one statement per thing, above the game
loop::

    scene = Scene(screen)
    scene.add("sky", Sky("skyblue"), layer="background")
    cars = scene.add("cars", Vehicle("red"), size=(80, 40), on="road", count=3,
                     moves=(-3, 0))

and two calls inside it, ``scene.update()`` before ``screen.fill(...)`` and
``scene.draw()`` straight after it. Everything here finds those with :mod:`ast` -- the
statement for a name, where the loop, the fill and the flip are, which statements draw
the player -- and changes the source as whole lines, so what comes out is the game as it
was with only those lines different. Nothing is regenerated that was not asked about.

Nothing here imports pygame or runs the game. What the change *does* is checked by the
playtest afterwards, the same as any other change (``execution/playtest.py``).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from opennest.graphics.looks import quoted

#: The comment above the scene, so a child reading the game knows what it is.
SCENE_COMMENT = "# The scene: everything the game shows, drawn back to front by scene.draw()."

#: What Open Nest writes above a rule it added, so the rule can be found again.
RULE_MARK = "# Open Nest: "


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _call_of(stmt: ast.stmt) -> ast.Call | None:
    value = stmt.value if isinstance(stmt, (ast.Expr, ast.Assign)) else None
    return value if isinstance(value, ast.Call) else None


# ----------------------------------------------------------------------------- reading


@dataclass
class Entry:
    """One ``scene.add(...)`` statement."""

    name: str
    first: int                   # 0-based line span of the whole statement
    last: int
    target: str | None           # ``cars`` in ``cars = scene.add(...)``
    look: str                    # the look argument, as written
    look_class: str              # ``Picture``, ``Vehicle``, ...
    keywords: dict[str, str]     # keyword -> source text
    wraps: str | None = None     # the game's own rect or list it draws, if any
    literals: dict = field(default_factory=dict)   # keyword values that are literals

    @property
    def layer(self) -> str:
        return self.literals.get("layer", "things")


@dataclass
class GameScene:
    """What the kit is doing in one game file, found with the parser."""

    source: str
    tree: ast.Module | None
    imported: tuple[str, ...] = ()
    import_line: int | None = None
    variable: str | None = None          # usually ``scene``
    created: int | None = None           # the line ``scene = Scene(...)`` is on
    entries: dict[str, Entry] = field(default_factory=dict)
    update_line: int | None = None
    draw_line: int | None = None
    rules: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def adopted(self) -> bool:
        return self.variable is not None and self.draw_line is not None

    def entry_for(self, name: str) -> Entry | None:
        return self.entries.get(name)


def read(source: str) -> GameScene:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return GameScene(source, None)
    found = GameScene(source, tree)
    lines = source.split("\n")
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "scene":
            found.imported = tuple(a.name for a in node.names)
            found.import_line = node.lineno - 1
        call = _call_of(node)
        if call is not None and isinstance(node, ast.Assign) and _dotted(call.func) == \
                "Scene" and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            found.variable = node.targets[0].id
            found.created = node.lineno - 1
    if found.variable is None:
        return found
    var = found.variable
    for node in tree.body:
        call = _call_of(node)
        if call is None or _dotted(call.func) != f"{var}.add" or not call.args:
            continue
        name = call.args[0]
        if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
            continue
        look = call.args[1] if len(call.args) > 1 else None
        keywords = {k.arg: ast.get_source_segment(source, k.value) or ""
                    for k in call.keywords if k.arg}
        literals = {}
        for k in call.keywords:
            if not k.arg:
                continue
            try:
                literals[k.arg] = ast.literal_eval(k.value)
            except (ValueError, SyntaxError, TypeError):
                continue
        wraps = None
        for k in call.keywords:
            if k.arg in ("rect", "rects") and isinstance(k.value, ast.Name):
                wraps = k.value.id
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
                node.targets[0], ast.Name):
            target = node.targets[0].id
        found.entries[name.value] = Entry(
            name=name.value, first=node.lineno - 1, last=node.end_lineno - 1,
            target=target, look=ast.get_source_segment(source, look) if look else "",
            look_class=_dotted(look.func) if isinstance(look, ast.Call) else "",
            keywords=keywords, wraps=wraps, literals=literals)
    loop = main_loop(tree)
    if loop is not None:
        for stmt in loop.body:
            call = _call_of(stmt)
            name = _dotted(call.func) if call is not None else ""
            if name == f"{var}.update" and isinstance(stmt, ast.Expr):
                found.update_line = stmt.lineno - 1
            elif name == f"{var}.draw" and isinstance(stmt, ast.Expr):
                found.draw_line = stmt.lineno - 1
            touched = _touched_name(stmt, var)
            if touched is not None:
                first = stmt.lineno - 1
                if first > 0 and lines[first - 1].strip().startswith(RULE_MARK):
                    first -= 1
                found.rules[touched] = (first, stmt.end_lineno - 1)
    return found


def _touched_name(stmt: ast.stmt, var: str) -> str | None:
    """The name in ``scene.touched(player, "cars")`` heading an if or a for -- or
    ``scene.touching``, which the rules were written with before the kit's version 2."""
    head = stmt.test if isinstance(stmt, ast.If) else stmt.iter if isinstance(
        stmt, ast.For) else None
    if isinstance(head, ast.Call) and _dotted(head.func) in (f"{var}.touched",
                                                             f"{var}.touching") and \
            len(head.args) == 2 and isinstance(head.args[1], ast.Constant) and \
            isinstance(head.args[1].value, str):
        return head.args[1].value
    return None


def main_loop(tree: ast.Module) -> ast.While | None:
    loops = [node for node in tree.body if isinstance(node, ast.While) and any(
        isinstance(sub, ast.Call) and _dotted(sub.func) in (
            "pygame.display.flip", "pygame.display.update") for sub in ast.walk(node))]
    return loops[0] if len(loops) == 1 else None


# ----------------------------------------------------------------- drawing statements


_DRAWS = ("pygame.draw.",)


def _is_draw_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    name = _dotted(node.func)
    return name.startswith(_DRAWS) or name.endswith(".blit") or (
        isinstance(node.func, ast.Attribute) and node.func.attr == "blit")


def _mentions(node: ast.AST, names: set[str]) -> bool:
    return any(isinstance(sub, ast.Name) and sub.id in names for sub in ast.walk(node))


def _draws_only(body: list[ast.stmt]) -> bool:
    """Every statement only draws, or sets a local name used for drawing."""
    for stmt in body:
        if isinstance(stmt, ast.Expr) and _is_draw_call(stmt.value):
            continue
        if isinstance(stmt, ast.Assign) and all(
                isinstance(t, (ast.Name, ast.Tuple)) and all(
                    isinstance(e, ast.Name) for e in (t.elts if isinstance(t, ast.Tuple)
                                                      else [t]))
                for t in stmt.targets):
            continue
        if isinstance(stmt, ast.For) and _draws_only(stmt.body) and not stmt.orelse:
            continue
        return False
    return True


def player_drawing(tree: ast.Module, player: str) -> list[tuple[int, int]]:
    """The loop's statements that draw the player, as 0-based line spans.

    A ``pygame.draw`` call or a ``blit`` naming the player's rect -- the Basic Game's
    ``pygame.draw.rect(screen, PLAYER_COLOUR, player)``, the old sprite recipe's
    ``screen.blit(player_image, ...)`` -- or a ``try`` made only of loading and drawing
    it, the shape the owner's test03 game had (a picture that fails to load, and a
    square drawn instead where nobody can tell).
    """
    loop = main_loop(tree)
    if loop is None:
        return []
    spans = []
    for stmt in loop.body:
        if isinstance(stmt, ast.Expr) and _is_draw_call(stmt.value) and _mentions(
                stmt.value, {player}):
            spans.append((stmt.lineno - 1, stmt.end_lineno - 1))
        elif isinstance(stmt, ast.Try) and _mentions(stmt, {player}):
            parts = stmt.body + [s for handler in stmt.handlers for s in handler.body]
            if parts and all(_loads_or_draws(s) for s in parts):
                spans.append((stmt.lineno - 1, stmt.end_lineno - 1))
    return spans


def _loads_or_draws(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Expr) and _is_draw_call(stmt.value):
        return True
    if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
        if _dotted(stmt.value.func).startswith(("pygame.image.", "pygame.transform.")):
            return True
        return isinstance(stmt.value.func, ast.Attribute) and \
            stmt.value.func.attr in ("convert_alpha", "convert")
    return isinstance(stmt, ast.Pass)


def drawing_loop(tree: ast.Module, items: str) -> tuple[int, int] | None:
    """The loop statement ``for x in <items>:`` that only draws them, as a line span."""
    loop = main_loop(tree)
    if loop is None:
        return None
    found = [stmt for stmt in loop.body if isinstance(stmt, ast.For) and isinstance(
        stmt.iter, ast.Name) and stmt.iter.id == items and _draws_only(stmt.body)]
    if len(found) != 1:
        return None
    return found[0].lineno - 1, found[0].end_lineno - 1


def other_drawing_of(tree: ast.Module, items: str, keep: tuple[int, int] | None) -> bool:
    """Whether anything else in the loop draws ``items`` -- a loop that also moves them,
    say -- so taking the pure drawing loop away would not stop them being drawn twice."""
    loop = main_loop(tree)
    if loop is None:
        return False
    for stmt in loop.body:
        if keep and stmt.lineno - 1 == keep[0]:
            continue
        if isinstance(stmt, ast.For) and isinstance(stmt.iter, ast.Name) and \
                stmt.iter.id == items and any(_is_draw_call(n) for n in ast.walk(stmt)):
            return True
    return False


def draws(tree: ast.Module, items: str) -> bool:
    """Whether the game loop draws ``items`` by hand at all: a drawing call naming them,
    or one inside a loop that walks them. A list of rects nothing draws yet -- the Fast
    Path's things before their look is given, or Gary's own ``enemies`` -- is the scene's
    to draw."""
    loop = main_loop(tree)
    if loop is None:
        return False
    for stmt in loop.body:
        for node in ast.walk(stmt):
            if _is_draw_call(node) and _mentions(node, {items}):
                return True
            if isinstance(node, ast.For) and _mentions(node.iter, {items}) and any(
                    _is_draw_call(sub) for sub in ast.walk(node)):
                return True
    return False


def top_level_lists(tree: ast.Module) -> dict[str, int]:
    """Lists of rects made above the loop: ``cars = []`` filled with ``pygame.Rect``s, or a
    list written out. Name -> the line it is made on."""
    found: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
                node.targets[0], ast.Name) and isinstance(node.value, (ast.List, ast.ListComp)):
            found[node.targets[0].id] = node.lineno - 1
    lists = {}
    for node in tree.body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and \
                    sub.func.attr == "append" and isinstance(sub.func.value, ast.Name) and \
                    sub.func.value.id in found and any(
                        isinstance(n, ast.Call) and _dotted(n.func) in ("pygame.Rect", "Rect")
                        for n in ast.walk(sub)):
                lists[sub.func.value.id] = found[sub.func.value.id]
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
                node.targets[0], ast.Name) and node.targets[0].id in found and any(
                isinstance(n, ast.Call) and _dotted(n.func) in ("pygame.Rect", "Rect")
                for n in ast.walk(node.value)):
            lists[node.targets[0].id] = found[node.targets[0].id]
    return lists


def references(tree: ast.Module, name: str, *, besides: tuple[int, int] | None = None) -> int:
    """How many times the code reads ``name``, outside the line span ``besides``."""
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
            line = node.lineno - 1
            if besides and besides[0] <= line <= besides[1]:
                continue
            count += 1
    return count


def assignments_of(tree: ast.Module, name: str) -> list[tuple[int, int]]:
    """Top-level statements assigning ``name``, as line spans."""
    return [(node.lineno - 1, node.end_lineno - 1) for node in tree.body
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets)]


def names_used(tree: ast.Module) -> set[str]:
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            used.add(node.name)
    return used


def names_bound(tree: ast.Module) -> set[str]:
    """The names a game gives a value to: assigned, imported, defined, or an argument.
    A name that is only read -- ``scene.touched(...)`` a recipe wrote just before its
    look call gives the game its scene -- is not one the game has taken."""
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.alias):
            bound.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    return bound


def rect_start(tree: ast.Module, player: str) -> str | None:
    """Where the player's rect starts, as code: the first two arguments of its
    ``pygame.Rect(...)``, so "back to the start" means where this game starts it."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == player for t in node.targets) and \
                isinstance(node.value, ast.Call) and _dotted(node.value.func) in (
                    "pygame.Rect", "Rect") and len(node.value.args) == 4:
            x, y = (ast.unparse(a) for a in node.value.args[:2])
            return f"({x}, {y})"
    return None


# ----------------------------------------------------------------------------- editing


class Edit:
    """Whole-line changes against one version of the source, applied together.

    Insertions go before a line; a span of lines can be replaced or dropped. Positions
    all refer to the source the Edit was made from, so a caller works out every place
    first and never has to track how earlier changes moved the lines.
    """

    def __init__(self, source: str) -> None:
        self.lines = source.split("\n")
        self.before: dict[int, list[str]] = {}
        self.replaced: dict[int, list[str]] = {}
        self.dropped: set[int] = set()

    def insert(self, index: int, block: list[str]) -> None:
        self.before.setdefault(index, []).extend(block)

    def replace(self, first: int, last: int, block: list[str]) -> None:
        self.replaced[first] = block
        self.dropped.update(range(first, last + 1))

    def drop(self, first: int, last: int) -> None:
        self.dropped.update(range(first, last + 1))
        # A "# Draw the player" left above nothing is noise.
        above = first - 1
        if above >= 0 and above not in self.dropped and re.match(
                r"^\s*#\s*draw\b", self.lines[above], re.IGNORECASE):
            self.dropped.add(above)

    def text(self) -> str:
        out: list[str] = []
        for index, line in enumerate(self.lines):
            out.extend(self.before.get(index, []))
            if index in self.replaced:
                out.extend(self.replaced[index])
            if index not in self.dropped:
                out.append(line)
        out.extend(self.before.get(len(self.lines), []))
        return _tidy("\n".join(out))


def _tidy(source: str) -> str:
    """No run of more than two blank lines, the way the starter is written."""
    return re.sub(r"\n{4,}", "\n\n\n", source)


def indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


# ----------------------------------------------------------------------------- writing




def call_text(var: str, name: str, look: str, keywords: list[tuple[str, str]],
              target: str | None, width: int = 92) -> list[str]:
    """``[target = ]scene.add("name", look, key=value, ...)``, wrapped to ``width``."""
    head = f"{target} = " if target else ""
    opening = f"{head}{var}.add({quoted(name)}, "
    parts = [f"{key}={value}" for key, value in keywords]
    look_lines = look.split("\n")
    if len(look_lines) == 1:
        line = opening + ", ".join([look_lines[0], *parts]) + ")"
        if len(line) <= width:
            return [line]
        pad = " " * len(f"{head}{var}.add(")
        lines = [opening + look_lines[0] + ","]
        current = pad
        for index, part in enumerate(parts):
            piece = part + ("," if index < len(parts) - 1 else ")")
            if len(current) + len(piece) + 1 > width and current.strip():
                lines.append(current.rstrip())
                current = pad
            current += piece + " "
        lines.append(current.rstrip())
        return lines
    # A drawing written out shape by shape.
    lines = [opening + look_lines[0]] + look_lines[1:-1]
    closing = look_lines[-1]
    tail = ", ".join(parts)
    lines.append(closing + (", " + tail if tail else "") + ")")
    return lines


# ----------------------------------------------------------------------------- saying it

#: How each look reads in a sentence, from the code that makes it.
_LOOK_WORDS = {"Picture": "picture", "Animation": "animation", "Drawing": "drawing",
               "Colour": "plain box"}


def look_words(entry: Entry) -> str:
    """"the picture assets/eagle.png", "a vehicle drawing", "a drawing of 4 shapes"."""
    cls = entry.look_class
    quoted_text = re.findall(r"""["']([^"']+)["']""", entry.look)
    if cls in ("Picture", "Animation"):
        path = quoted_text[0] if quoted_text else "a file"
        return f"the {_LOOK_WORDS[cls]} {path}"
    if cls == "Drawing":
        shapes = len(re.findall(r"\b(?:Rect|Circle|Ellipse|Triangle|Polygon|Line|Text)\(",
                                entry.look))
        return f"a drawing of {shapes} shape{'' if shapes == 1 else 's'}"
    if cls == "Colour":
        return "a plain box"
    if cls:
        return f"a {cls.lower()} drawing"
    return "a look Open Nest can't read"


#: Bands a thing can be on or above, by what draws them.
_BANDS = ("Road", "Ground")


def _relation(entry: Entry, scene: GameScene) -> str:
    """Where a thing placed by corners is against a road or ground, in words -- the
    geometry neither model does from numbers (SPIKES.md section 28E)."""
    at, size = entry.literals.get("at"), entry.literals.get("size")
    # A sky is the whole screen, behind everything: "below the road" about it (the
    # re-run 4B walk's evidence) is geometry, not something anyone would mean.
    if entry.look_class in _BANDS + ("Sky",) or not (isinstance(at, tuple) and
                                                    isinstance(size, tuple)):
        return ""
    for band in scene.entries.values():
        spot, span = band.literals.get("at"), band.literals.get("size")
        if band.look_class not in _BANDS or not (isinstance(spot, tuple) and
                                                  isinstance(span, tuple)):
            continue
        bottom, top = at[1] + size[1], spot[1]
        if bottom < top - 4:
            return f"above the {band.name}, not on it"
        if bottom <= top + span[1]:
            return f"on the {band.name}"
        return f"below the {band.name}"
    return ""


def relation(scene: GameScene, name: str) -> str:
    """Where a thing in the scene is against the road or ground, in words, or ""."""
    entry = scene.entries.get(name)
    if entry is None:
        return ""
    if "on" in entry.literals:
        return f"on the {entry.literals['on']}"
    return _relation(entry, scene)


def touch_rule(scene: GameScene, name: str) -> str:
    """"avoid", "collect", or "" -- what touching a thing in the scene does, from the
    rule Open Nest wrote for it or the game's own collision code for its list."""
    rule = scene.rules.get(name)
    if rule is not None:
        text = "\n".join(scene.source.split("\n")[rule[0]:rule[1] + 1])
        return "collect" if "score" in text else "avoid"
    entry = scene.entries.get(name)
    items = entry.wraps if entry is not None else None
    target = entry.target if entry is not None else None
    loop = main_loop(scene.tree) if scene.tree is not None else None
    for stmt in loop.body if loop is not None else ():
        mentioned = {n.id for n in ast.walk(stmt) if isinstance(n, ast.Name)}
        if not mentioned & {items, target} - {None}:
            continue
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and
               n.func.attr in ("collidelist", "colliderect", "touching", "touched")
               for n in ast.walk(stmt)):
            return "collect" if "score" in ast.unparse(stmt) else "avoid"
    return ""


def describe(scene: GameScene, player: str | None = None) -> list[str]:
    """One line per thing in the scene, back to front, from the code alone."""
    order = ("background", "scenery", "things", "player", "effects", "ui")
    rank = {layer: index for index, layer in enumerate(order)}
    lines = []
    for entry in sorted(scene.entries.values(),
                        key=lambda e: (rank.get(e.layer, 2), e.first)):
        count = entry.literals.get("count")
        spots = entry.literals.get("at")
        if isinstance(spots, list):
            count = len(spots)
        words = look_words(entry)
        if isinstance(count, int) and count > 1:
            words = f"{count} of {words}" if words.startswith("the ") else \
                f"{count} x {words.removeprefix('a ')}"
        elif entry.keywords.get("count"):
            words = f"{entry.keywords['count']} x {words.removeprefix('a ')}"
        parts = [f"{entry.name}: {words}"]
        if entry.wraps:
            parts.append("the player's rectangle" if entry.wraps == player else
                         f"drawn on the game's own {entry.wraps}")
        if "on" in entry.literals:
            parts.append(f"standing on {entry.literals['on']}")
        elif "at" in entry.keywords and not isinstance(spots, list):
            parts.append(f"at {entry.keywords['at']}")
            where = _relation(entry, scene)
            if where:
                parts.append(where)
        if "moves" in entry.keywords and entry.keywords["moves"] not in ("(0, 0)",):
            parts.append(f"moving {entry.keywords['moves']} a frame")
        rule = scene.rules.get(entry.name)
        if rule is not None:
            text = "\n".join(scene.source.split("\n")[rule[0]:rule[1] + 1])
            parts.append("touching one scores a point" if "score" in text else
                         "touching one sends the player back to the start")
        parts.append(f"layer {entry.layer}")
        lines.append(", ".join(parts))
    return lines
