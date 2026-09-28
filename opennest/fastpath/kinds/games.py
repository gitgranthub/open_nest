"""Games: what Open Nest can read about a pygame file, and the changes the recipes make.

Phase 12.3 found the shape of almost every failed game (SPIKES.md section 23C): a thing
in a pygame game needs three pieces in three places -- created above the loop, moved in
the loop, drawn after ``screen.fill`` -- and the model reliably supplies two. Here the
three places are *found*, with Python's own parser, and each piece is put where it
belongs. That is the whole idea of this module, and it is also its limit: when the file
no longer has a single game loop with a fill and a flip in it, the facts are absent and
every operation that needs them steps aside for Gary.

Everything is read from the file as it is now, never from what a recipe put there
earlier -- except for one naming convention that makes a later recipe able to find an
earlier one's work: a thing called ``ASTEROID`` has ``ASTEROID_SPEED``, ``ASTEROID_SIZE``
and a list called ``asteroids``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from opennest.assets import manager as assets
from opennest.fastpath import slots
from opennest.fastpath.classifier import OTHER, Option
from opennest.fastpath.kinds import (
    AlreadyDone,
    Change,
    Context,
    Facts,
    NeedsAnswer,
    NotApplicable,
    confident,
    game_things,
)

# ----------------------------------------------------------------------------- facts


@dataclass(frozen=True)
class Const:
    name: str
    value: object
    line: int          # 0-based
    start: int         # character column of the value
    end: int


def _chars(line: str, byte_col: int) -> int:
    """ast columns are UTF-8 byte offsets; strings are indexed by character."""
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Expr):
        node = node.value
    return _dotted(node.func) if isinstance(node, ast.Call) else ""


def _contains_call(node: ast.AST, names: tuple[str, ...]) -> bool:
    return any(
        isinstance(sub, ast.Call) and _dotted(sub.func) in names for sub in ast.walk(node)
    )


FLIPS = ("pygame.display.flip", "pygame.display.update")


def entry_path(project) -> str:
    return f"src/{project.manifest.entrypoint}"


def facts(project, attachments=()) -> Facts:
    """Read the game file. Every value is a line number or a name, or absent."""
    path = entry_path(project)
    values: dict = {"entry": path}
    images = [a.path for a in assets.list_assets(project) if a.kind == "image"]
    attached = [a.path for a in attachments if getattr(a, "kind", "") == "image"]
    values["images"] = images or None
    values["attached_images"] = attached or None

    file = project.directory / path
    if not file.is_file():
        return Facts(values)
    source = file.read_text(encoding="utf-8")
    values["source"] = source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return Facts(values)
    lines = source.split("\n")

    constants: dict[str, Const] = {}
    imports: set[str] = set()
    last_import = None
    init_line = None
    set_mode_line = None
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [
                node.module or ""
            ]
            imports.update(names)
            last_import = node.end_lineno - 1
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError, TypeError):
                value = None
            if value is not None and name.isupper() and node.lineno == node.end_lineno:
                line = lines[node.lineno - 1]
                constants[name] = Const(
                    name, value, node.lineno - 1,
                    _chars(line, node.value.col_offset), _chars(line, node.value.end_col_offset),
                )
            if isinstance(node.value, ast.Call) and _dotted(node.value.func) == \
                    "pygame.display.set_mode":
                values["surface"] = name
                set_mode_line = node.lineno - 1
                size = node.value.args[0] if node.value.args else None
                if isinstance(size, ast.Tuple) and len(size.elts) == 2 and all(
                    isinstance(e, ast.Name) for e in size.elts
                ):
                    values["width"], values["height"] = (e.id for e in size.elts)
        elif isinstance(node, ast.Expr) and _call_name(node) == "pygame.init":
            init_line = node.lineno - 1
        elif isinstance(node, ast.Expr) and _call_name(node) == "pygame.display.set_caption":
            call = node.value
            if call.args and isinstance(call.args[0], ast.Constant) and isinstance(
                call.args[0].value, str
            ):
                line = lines[node.lineno - 1]
                values["caption"] = (node.lineno - 1,
                                     _chars(line, call.args[0].col_offset),
                                     _chars(line, call.args[0].end_col_offset),
                                     call.args[0].value)
    values["constants"] = constants
    values["imports"] = imports
    values["last_import"] = last_import
    values["set_mode_line"] = set_mode_line

    # The last constant of the block at the top -- where new tunable numbers belong, so
    # they sit beside the ones the starter taught the child to change.
    before = init_line if init_line is not None else len(lines)
    top = [c.line for c in constants.values() if c.line < before]
    values["constants_end"] = max(top) if top else last_import

    loops = [n for n in tree.body if isinstance(n, ast.While) and _contains_call(n, FLIPS)]
    if len(loops) != 1:
        # None, or several: either way there is no one place a new thing obviously goes.
        return Facts(values)
    loop = loops[0]
    values["loop"] = loop.lineno - 1
    values["indent"] = " " * loop.body[0].col_offset
    index = tree.body.index(loop)
    previous = tree.body[index - 1] if index else None
    values["setup_line"] = loop.lineno - 1
    if (isinstance(previous, ast.Assign) and len(previous.targets) == 1
            and isinstance(previous.targets[0], ast.Name)
            and isinstance(previous.value, ast.Constant) and previous.value.value is True):
        # ``running = True`` belongs to the loop; setup goes above it.
        values["setup_line"] = previous.lineno - 1

    surface = values.get("surface")
    for stmt in loop.body:
        name = _call_name(stmt)
        if name.endswith(".fill") and "fill" not in values and (
            surface is None or name == f"{surface}.fill"
        ):
            values["fill"] = stmt.lineno - 1
            arg = stmt.value.args[0] if stmt.value.args else None
            if isinstance(arg, ast.Name) and isinstance(
                getattr(constants.get(arg.id), "value", None), tuple
            ):
                values["background"] = arg.id
        elif name in FLIPS and "fill" in values:
            values["flip"] = stmt.lineno - 1

    _player_facts(loop, tree, constants, values)
    _thing_facts(tree, constants, values)
    return Facts(values)


def _player_facts(loop: ast.While, tree: ast.Module, constants: dict, values: dict) -> None:
    """The rect the arrow keys move, what moves it, and how it is drawn."""
    player = None
    speed = None
    arrows = []
    for node in ast.walk(loop):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if isinstance(test, ast.Subscript) and _dotted(test.slice).startswith("pygame.K_"):
            key = _dotted(test.slice).split(".")[-1]
            for stmt in node.body:
                if isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Attribute) \
                        and isinstance(stmt.target.value, ast.Name):
                    player = player or stmt.target.value.id
                    if isinstance(stmt.value, ast.Name) and stmt.value.id in constants:
                        speed = speed or stmt.value.id
            arrows.append((node.lineno - 1, key))
    if player is None:
        return
    values["player"] = player
    values["arrow_ifs"] = arrows or None
    if speed and isinstance(constants[speed].value, (int, float)):
        values["player_speed"] = speed

    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == player
                and isinstance(node.value, ast.Call)
                and _dotted(node.value.func) == "pygame.Rect" and len(node.value.args) == 4):
            size = node.value.args[2]
            if isinstance(size, ast.Name) and size.id in constants:
                values["player_size"] = size.id
    for stmt in loop.body:
        call = stmt.value if isinstance(stmt, ast.Expr) else None
        if not isinstance(call, ast.Call):
            continue
        name = _dotted(call.func)
        # The player's drawing is whatever pygame.draw call draws the player's rect --
        # the starter's rectangle, or the ship a recipe drew instead, over several lines.
        # Measured through the real app walk (SPIKES.md section 25): recognising only the
        # rectangle meant one recipe's ship stopped the next recipe using the picture.
        if name.startswith("pygame.draw.") and "player_draw" not in values and len(
            call.args
        ) >= 2 and any(isinstance(n, ast.Name) and n.id == player
                       for arg in call.args[2:] for n in ast.walk(arg)):
            values["player_draw"] = (stmt.lineno - 1, stmt.end_lineno - 1)
            values["player_shape"] = name.rsplit(".", 1)[-1]
            colour = call.args[1]
            if isinstance(colour, ast.Name) and isinstance(
                getattr(constants.get(colour.id), "value", None), tuple
            ):
                values["player_colour"] = colour.id
        elif name == f"{player}.clamp_ip":
            values["clamp"] = stmt.lineno - 1


def _thing_facts(tree: ast.Module, constants: dict, values: dict) -> None:
    """Things added under the naming convention, and whether there is a score."""
    speed_of_player = values.get("player_speed")
    things = {}
    for name, const in constants.items():
        if name.endswith("_SPEED") and name != speed_of_player and not name.startswith(
            "PLAYER"
        ) and isinstance(const.value, (int, float)):
            prefix = name[: -len("_SPEED")]
            things[prefix] = {"speed": name, "list": None}
    lists = set()
    for node in tree.body:
        if isinstance(node, ast.For):
            # ``things.append(pygame.Rect(...))`` in a loop at the top level: the shape
            # add_things writes, and the ordinary way to make several of something.
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "append"
                        and isinstance(sub.func.value, ast.Name)
                        and _contains_call(sub, ("pygame.Rect",))):
                    lists.add(sub.func.value.id)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
            node.targets[0], ast.Name
        ):
            target = node.targets[0].id
            if isinstance(node.value, (ast.ListComp, ast.List)) and _contains_call(
                node.value, ("pygame.Rect",)
            ):
                lists.add(target)
            if target == "score":
                values["score"] = True
            if target == "font":
                values["font"] = True
    for prefix, thing in things.items():
        plural = _plural(prefix.lower().split("_")[0])
        suffix = prefix.split("_")[1] if "_" in prefix else ""
        candidate = f"{plural}_{suffix}" if suffix else plural
        if candidate in lists:
            thing["list"] = candidate
    values["things"] = things or None
    values["thing_lists"] = sorted(lists) or None
    values["names_used"] = _names_used(tree, lists)
    if things:
        values["thing_speed"] = True


def _names_used(tree: ast.Module, lists: set[str]) -> tuple[str, ...]:
    """Every name the module assigns, except inside loops over things a recipe added.

    Those loops are where a recipe's own ``x, y = ... .center`` lines live, so skipping
    them lets a second recipe reuse the short names the first one used, while a child's
    own ``x`` or ``size`` anywhere else makes every recipe use prefixed names instead.
    """
    used: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) \
                and node.iter.id in lists:
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            used.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            used.add(node.name)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return tuple(sorted(used))


def where(facts: Facts) -> str:
    """Where things are in this file, for Gary, when Gary writes the change himself.

    The measured case for this (SPIKES.md section 22F): half the refused edits were the
    model editing code it had imagined. It is given the real lines instead.
    """
    source = facts.get("source")
    if not source:
        return ""
    lines = source.split("\n")
    entry = facts.get("entry")

    def show(index: int) -> str:
        return f"line {index + 1}: {lines[index].strip()}"

    notes = [f"WHERE THINGS ARE IN {entry} RIGHT NOW"]
    if facts.has("constants_end"):
        notes.append(f"- New tunable numbers go with the others near the top, after "
                     f"{show(facts.get('constants_end'))}")
    if facts.has("loop"):
        notes.append(f"- Create a new thing once, above the game loop, which starts at "
                     f"{show(facts.get('loop'))}")
    if facts.has("fill"):
        notes.append(f"- Move things inside the loop, before {show(facts.get('fill'))}")
    if facts.has("flip"):
        notes.append(f"- Draw things inside the loop, after the fill and before "
                     f"{show(facts.get('flip'))}")
    if facts.has("indent"):
        notes.append(f"- Code inside the loop is indented {len(facts.get('indent'))} spaces.")
    if facts.has("player"):
        notes.append(f"- The player is the rect called {facts.get('player')}.")
    return "\n".join(notes) if len(notes) > 1 else ""


# ------------------------------------------------------------------------ editing


class _Edit:
    """Insertions before lines, and replacements within a line, applied together."""

    def __init__(self, source: str) -> None:
        self.lines = source.split("\n")
        self.inserts: dict[int, list[str]] = {}
        self.spans: list[tuple[int, int, int, str]] = []
        self.dropped: set[int] = set()

    def before(self, index: int, block: list[str], indent: str = "") -> None:
        self.inserts.setdefault(index, []).extend(
            (indent + line) if line else "" for line in block
        )

    def after(self, index: int, block: list[str], indent: str = "") -> None:
        self.before(index + 1, block, indent)

    def replace(self, line: int, start: int, end: int, text: str) -> None:
        self.spans.append((line, start, end, text))

    def replace_statement(self, first: int, last: int, text: str) -> None:
        """One statement, however many lines it spans, becomes ``text``."""
        self.replace(first, 0, len(self.lines[first]), text)
        self.dropped.update(range(first + 1, last + 1))

    def text(self) -> str:
        lines = list(self.lines)
        for line, start, end, text in sorted(self.spans, reverse=True):
            lines[line] = lines[line][:start] + text + lines[line][end:]
        out: list[str] = []
        for index, line in enumerate(lines):
            out.extend(self.inserts.get(index, []))
            if index not in self.dropped:
                out.append(line)
        out.extend(self.inserts.get(len(lines), []))
        return "\n".join(out)


def _require(facts: Facts, *names: str) -> None:
    missing = facts.missing(names)
    if missing:
        raise NotApplicable(f"the game does not have: {', '.join(missing)}")


def _format_number(value: float, like: object) -> str:
    if isinstance(like, int) and float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _new_amount(ctx: Context, old: float, integer: bool) -> tuple[float, str]:
    """The new value for a number, and the direction, from what the child said."""
    params = ctx.params
    words = set(re.findall(r"[a-z]+", ctx.request.lower()))
    if (words & _UP_WORDS or re.search(r"\bspeed\w*\s+up\b", ctx.request, re.I)) and (
            words & _DOWN_WORDS or re.search(r"\bslow\w*\s+down\b", ctx.request, re.I)):
        # "speed up and slow down without warning" is not one direction. Measured: a
        # step worded that way had its speed raised, and nothing more.
        raise NotApplicable("the message asks for faster and slower at once")
    amount = slots.explicit_amount(ctx.request)
    if amount is not None and amount.value is not None:
        new = amount.value
    else:
        if amount is not None and amount.factor is not None:
            factor = amount.factor
        else:
            if ctx.choose is None:
                raise NotApplicable("no model to ask which way")
            answer = confident(ctx.choose(params["question"], [
                Option("up", params["up"]),
                Option("down", params["down"]),
                Option(OTHER, "neither, or something else"),
            ]))
            if answer not in ("up", "down"):
                raise NotApplicable("not sure which way")
            factor = params.get("factor", 1.6)
            if answer == "down":
                factor = 1 / factor
        new = old * factor
        if integer:
            new = round(new)
            if new == old:
                new = old + (1 if factor > 1 else -1)
    new = max(params.get("min", 1), min(params.get("max", 60), new))
    if new == old:
        raise NotApplicable("the number would not change")
    return new, ("up" if new > old else "down")


#: Words that name a direction for a number. "more" and "less" are left out on purpose:
#: "slower, more like a real road" is one direction.
_UP_WORDS = frozenset({"faster", "quicker", "bigger", "larger", "higher"})
_DOWN_WORDS = frozenset({"slower", "smaller", "lower"})


def _set_constant(ctx: Context, name: str) -> Change:
    const = ctx.facts.get("constants")[name]
    if not isinstance(const.value, (int, float)) or isinstance(const.value, bool):
        raise NotApplicable(f"{name} is not a number")
    new, direction = _new_amount(ctx, float(const.value), isinstance(const.value, int))
    edit = _Edit(ctx.facts.get("source"))
    text = _format_number(new, const.value)
    edit.replace(const.line, const.start, const.end, text)
    words = ctx.params.get("up_word" if direction == "up" else "down_word", "")
    return Change(
        files={ctx.facts.get("entry"): edit.text()},
        values={"name": name, "old": str(const.value), "new": text, "direction": words},
        expect={"constant": name, "value": new},
    )


def set_number(ctx: Context) -> Change:
    """Change one tunable number: the player's speed or size, or a thing's speed."""
    fact = ctx.params["fact"]
    if fact == "thing_speed":
        return _set_constant(ctx, _which_thing(ctx)["speed"])
    _require(ctx.facts, fact)
    return _set_constant(ctx, ctx.facts.get(fact))


def _which_thing(ctx: Context) -> dict:
    things = ctx.facts.get("things") or {}
    if not things:
        raise NotApplicable("no thing with a speed constant")
    if len(things) == 1:
        prefix = next(iter(things))
    else:
        named = slots.noun_in(ctx.request, NOUN_WORDS)
        matches = [p for p in things if named and p.split("_")[0] == named[0].upper()]
        if len(matches) != 1:
            raise NotApplicable("more than one thing, and the message does not say which")
        prefix = matches[0]
    thing = dict(things[prefix])
    thing["prefix"] = prefix
    thing["noun"] = prefix.split("_")[0].lower()
    return thing


def _colour_answer(ctx: Context) -> tuple[str, tuple[int, int, int]]:
    written = slots.explicit_colour(ctx.request)
    if written is not None:
        return "that colour", written
    if ctx.choose is None:
        raise NotApplicable("no model to ask which colour")
    options = [Option(name, name) for name in slots.PALETTE]
    options.append(Option(OTHER, "a colour not in this list, or no colour named"))
    answer = confident(ctx.choose(ctx.params["question"], options))
    if answer is None or answer == OTHER:
        raise NotApplicable("not sure which colour")
    return answer, slots.PALETTE[answer]


def set_colour(ctx: Context) -> Change:
    """Change the background or the player's colour constant."""
    fact = ctx.params["fact"]
    _require(ctx.facts, fact)
    const = ctx.facts.get("constants")[ctx.facts.get(fact)]
    name, rgb = _colour_answer(ctx)
    edit = _Edit(ctx.facts.get("source"))
    text = f"({rgb[0]}, {rgb[1]}, {rgb[2]})"
    if tuple(const.value) == rgb:
        part = "The background" if fact == "background" else "The player"
        raise AlreadyDone(f"{part} is already {name}, so there was nothing to change.")
    edit.replace(const.line, const.start, const.end, text)
    return Change(
        files={ctx.facts.get("entry"): edit.text()},
        values={"name": const.name, "colour": name, "old": str(const.value), "new": text},
        expect={"constant": const.name, "value": rgb},
    )


def _python_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_caption(ctx: Context) -> Change:
    """Change the title on the game window."""
    title = slots.title_in(ctx.request)
    if not title:
        raise NotApplicable("no title written in the message")
    edit = _Edit(ctx.facts.get("source") or "")
    caption = ctx.facts.get("caption")
    if caption is not None:
        line, start, end, old = caption
        if old == title:
            raise AlreadyDone(f"The game is already called \u201c{title}\u201d.")
        edit.replace(line, start, end, _python_string(title))
    elif ctx.facts.has("set_mode_line"):
        old = ""
        edit.after(ctx.facts.get("set_mode_line"),
                   [f"pygame.display.set_caption({_python_string(title)})"])
    else:
        raise NotApplicable("no window to title")
    return Change(
        files={ctx.facts.get("entry"): edit.text()},
        values={"title": title, "old": old},
        expect={"caption": title},
    )


# -- things that move ----------------------------------------------------------------
#
# What each thing looks like and how its variety is decided lives in game_things; this
# is only where the pieces go.

NOUN_WORDS = game_things.NOUN_WORDS
_plural = game_things.plural

#: Words that mean the player is a vehicle, so an avoiding game draws it as one.
_SHIP_WORDS = re.compile(r"\b(space\s*ship|ship|rocket|jet|plane|spacecraft)\b", re.IGNORECASE)


def _screen_size(facts: Facts) -> tuple[str, str]:
    surface = facts.get("surface", "screen")
    return (facts.get("width", f"{surface}.get_width()"),
            facts.get("height", f"{surface}.get_height()"))


def _unique_prefix(facts: Facts, noun: str) -> str:
    constants = facts.get("constants") or {}
    prefix = noun.upper()
    number = 2
    while any(name.startswith(prefix + "_") for name in constants):
        prefix = f"{noun.upper()}_{number}"
        number += 1
    return prefix


@dataclass
class _Thing:
    noun: str
    prefix: str        # ASTEROID
    items: str         # asteroids
    item: str          # asteroid
    style: game_things.Style

    @property
    def count(self) -> int:
        return self.style.count

    @property
    def motion(self) -> str:
        return self.style.motion

    @property
    def speed(self) -> str:
        return f"{self.prefix}_SPEED"

    @property
    def size(self) -> str:
        return f"{self.prefix}_SIZE"


def _spawn(thing: _Thing, width: str, height: str) -> tuple[str, str]:
    """Where each new thing starts. At least one is on screen from the first frame."""
    p, size = thing.prefix, thing.size
    anywhere_x = f"random.randint(0, {width} - {size})"
    top_third = f"random.randint(0, {height} // 3)"
    from_right = f"{width} - {size} + i * {width} // {p}_COUNT"
    return {
        "drift": (from_right, f"random.randint(0, {height} - {size})"),
        "zigzag": (from_right, f"random.randint(0, {height} - {size})"),
        "wave": (from_right, f"random.randint({p}_WAVE, {height} - {p}_WAVE - {size})"),
        "fall": (anywhere_x, f"-i * {height} // {p}_COUNT"),
        "rise": (anywhere_x, f"{height} - {size} + i * {height} // {p}_COUNT"),
        "bounce": (anywhere_x, top_third),
        "slide": (anywhere_x, top_third),
        "orbit": (f"random.randint({p}_RADIUS, {width} - {p}_RADIUS - {size})",
                  f"random.randint({p}_RADIUS, {height} // 2)"),
        "chase": (f"i * {size} * 2", "0"),
        "still": (anywhere_x, top_third),
    }[thing.motion]


def _respawn(thing: _Thing, name: str, width: str, height: str) -> list[str]:
    size = thing.size
    if thing.motion == "fall":
        return [f"{name}.bottom = 0", f"{name}.x = random.randint(0, {width} - {size})"]
    if thing.motion == "rise":
        return [f"{name}.top = {height}", f"{name}.x = random.randint(0, {width} - {size})"]
    if thing.motion in ("drift", "zigzag", "wave"):
        return [f"{name}.left = {width}", f"{name}.y = random.randint(0, {height} - {size})"]
    return [f"{name}.x = random.randint(0, {width} - {size})",
            f"{name}.y = random.randint(0, {height} - {size})"]


def _rgb(colour) -> str:
    return f"({colour[0]}, {colour[1]}, {colour[2]})"


def _thing_pieces(thing: _Thing, facts: Facts) -> dict[str, list[str]]:
    """The four pieces of one new thing: constants, setup, move, draw."""
    width, height = _screen_size(facts)
    surface = facts.get("surface", "screen")
    player = facts.get("player", "player")
    p, one, many = thing.prefix, thing.item, thing.items
    style = thing.style
    look = style.look

    constants = [f"{p}_COUNT = {style.count}", f"{p}_SIZE = {style.size}"]
    if thing.motion in game_things.SPEEDS:
        constants.append(f"{p}_SPEED = {style.speed}")
    constants.append(f"{p}_COLOUR = {_rgb(style.colour)}")
    if game_things.uses_detail(look.drawing):
        constants.append(f"{p}_DETAIL = {_rgb(style.detail)}")
    if thing.motion == "wave":
        constants.append(f"{p}_WAVE = 40")
    if thing.motion == "orbit":
        constants.append(f"{p}_RADIUS = 50")

    x, y = _spawn(thing, width, height)
    # A star field looks flat if every star is the same size.
    varied = look.drawing in ("dot", "drop") and style.count >= 10
    each = f"{one}_size" if varied else f"{p}_SIZE"
    moves, waves, orbits = f"{one}_moves", f"{one}_waves", f"{one}_orbits"
    # A plain loop rather than a comprehension: a child reads this, and "make a list,
    # then add each one to it" is the version they can change. Anything each one needs
    # to remember -- its own direction, its place in a wave -- is made in the same loop.
    setup = [f"{many} = []"]
    if thing.motion in ("bounce", "slide", "zigzag"):
        setup.append(f"{moves} = []")
    elif thing.motion == "wave":
        setup.append(f"{waves} = []")
    elif thing.motion == "orbit":
        setup.append(f"{orbits} = []")
    setup.append(f"for i in range({p}_COUNT):")
    if varied:
        setup.append(f"    {one}_size = random.randint(max(2, {p}_SIZE // 2), {p}_SIZE)")
    setup += [
        f"    {one}_x = {x}",
        f"    {one}_y = {y}",
        f"    {many}.append(pygame.Rect({one}_x, {one}_y, {each}, {each}))",
    ]
    either_way = f"random.choice((-1, 1)) * {p}_SPEED"
    if thing.motion == "bounce":
        setup.append(f"    {moves}.append([{either_way}, {either_way}])")
    elif thing.motion == "slide":
        setup.append(f"    {moves}.append([{either_way}, 0])")
    elif thing.motion == "zigzag":
        setup.append(f"    {moves}.append([0, {either_way}])")
    elif thing.motion == "wave":
        setup.append(f"    {waves}.append([{one}_y, i * 0.8])")
    elif thing.motion == "orbit":
        setup.append(f"    {orbits}.append([{one}_x, {one}_y, i * 1.3])")

    wrap = [f"    if {one}.right < 0:", f"        {one}.left = {width}"]
    if thing.motion == "drift":
        move = [f"for {one} in {many}:", f"    {one}.x -= {p}_SPEED",
                f"    if {one}.right < 0:"] + [
            f"        {line}" for line in _respawn(thing, one, width, height)]
    elif thing.motion == "fall":
        move = [f"for {one} in {many}:", f"    {one}.y += {p}_SPEED",
                f"    if {one}.top > {height}:"] + [
            f"        {line}" for line in _respawn(thing, one, width, height)]
    elif thing.motion == "rise":
        move = [f"for {one} in {many}:", f"    {one}.y -= {p}_SPEED",
                f"    if {one}.bottom < 0:"] + [
            f"        {line}" for line in _respawn(thing, one, width, height)]
    elif thing.motion in ("bounce", "slide"):
        move = [
            f"for {one}, {one}_move in zip({many}, {moves}):",
            f"    {one}.x += {one}_move[0]",
            f"    {one}.y += {one}_move[1]",
            f"    if {one}.left < 0 or {one}.right > {width}:",
            f"        {one}_move[0] = -{one}_move[0]",
            f"        {one}.clamp_ip({surface}.get_rect())",
            f"    if {one}.top < 0 or {one}.bottom > {height}:",
            f"        {one}_move[1] = -{one}_move[1]",
            f"        {one}.clamp_ip({surface}.get_rect())",
        ]
    elif thing.motion == "zigzag":
        move = [
            f"for {one}, {one}_move in zip({many}, {moves}):",
            f"    {one}.x -= {p}_SPEED",
            f"    {one}.y += {one}_move[1]",
            f"    if {one}.top < 0 or {one}.bottom > {height}:",
            f"        {one}_move[1] = -{one}_move[1]",
            f"        {one}.clamp_ip({surface}.get_rect())",
        ] + wrap
    elif thing.motion == "wave":
        move = [
            f"for {one}, {one}_wave in zip({many}, {waves}):",
            f"    {one}.x -= {p}_SPEED",
            f"    {one}_wave[1] += 0.08",
            f"    {one}.y = {one}_wave[0] + round({p}_WAVE * math.sin({one}_wave[1]))",
        ] + wrap
    elif thing.motion == "orbit":
        turn = f"{one}_orbit"
        move = [
            f"for {one}, {turn} in zip({many}, {orbits}):",
            f"    {turn}[2] += {p}_SPEED / 50",
            f"    {one}.x = {turn}[0] + round({p}_RADIUS * math.cos({turn}[2]))",
            f"    {one}.y = {turn}[1] + round({p}_RADIUS * math.sin({turn}[2]))",
        ]
    elif thing.motion == "chase":
        move = [
            f"for {one} in {many}:",
            f"    if {one}.centerx < {player}.centerx - {p}_SPEED:",
            f"        {one}.x += {p}_SPEED",
            f"    elif {one}.centerx > {player}.centerx + {p}_SPEED:",
            f"        {one}.x -= {p}_SPEED",
            f"    if {one}.centery < {player}.centery - {p}_SPEED:",
            f"        {one}.y += {p}_SPEED",
            f"    elif {one}.centery > {player}.centery + {p}_SPEED:",
            f"        {one}.y -= {p}_SPEED",
        ]
    else:
        move = []

    # Short local names for the drawing when the child's code leaves them free.
    taken = set(facts.get("names_used") or ()) & set(game_things.DRAWING_NAMES)
    names = ({"x": f"{one}_x", "y": f"{one}_y", "size": f"{one}_size"} if taken
             else {"x": "x", "y": "y", "size": "size"})
    draw = [f"for {one} in {many}:"] + [
        f"    {line}" for line in game_things.drawing(look.drawing, one, p, surface, **names)]
    return {"constants": constants, "setup": setup, "move": move, "draw": draw}


def _motion(ctx: Context, rng) -> str:
    """How the new thing moves: fixed by the recipe, picked from the child's words or
    the project's seed, or -- for "add something that moves" -- asked of the model."""
    wanted = ctx.params.get("motion", "choose")
    if isinstance(wanted, list):
        said = game_things.motion_in(ctx.request)
        return said if said in wanted else rng.choice(wanted)
    if wanted != "choose":
        return wanted
    if ctx.choose is None:
        raise NotApplicable("no model to ask how it moves")
    options = [Option(name, text) for name, text in game_things.MOTIONS.items()]
    options.append(Option(OTHER, "some other way, or it does not say"))
    answer = confident(ctx.choose("How should the new thing move?", options))
    if answer is None or answer == OTHER:
        raise NotApplicable("not sure how it should move")
    return answer


def _new_thing(ctx: Context) -> _Thing:
    facts = ctx.facts
    named = slots.noun_in(ctx.request, NOUN_WORDS)
    noun, plural_asked = named if named else (ctx.params.get("noun", "thing"), False)
    if noun not in game_things.NOUNS:
        noun = "thing"
    prefix = _unique_prefix(facts, noun)
    rng = game_things.variety(ctx.project, noun, prefix, ctx.params.get("motion"))
    motion = _motion(ctx, rng)
    style = game_things.style(noun, plural_asked, ctx.request, motion, rng,
                              many=bool(ctx.params.get("many")))
    items = _plural(noun)
    suffix = prefix[len(noun):].lower()
    return _Thing(noun=noun, prefix=prefix, items=items + suffix, item=noun + suffix,
                  style=style)


def _score_pieces(facts: Facts, rule: str) -> dict[str, list[str]]:
    surface = facts.get("surface", "screen")
    setup = [] if facts.has("score") else ["score = 0"]
    if not facts.has("font"):
        setup.append("font = pygame.font.Font(None, 36)")
    constants = [] if "SCORE_COLOUR" in (facts.get("constants") or {}) else [
        "SCORE_COLOUR = (240, 240, 240)"]
    move = []
    if rule == "per_second":
        setup.append("score_start = pygame.time.get_ticks()")
        move = ["score = (pygame.time.get_ticks() - score_start) // 1000"]
    draw = [f'{surface}.blit(font.render(f"Score: {{score}}", True, SCORE_COLOUR), (10, 10))']
    return {"constants": constants, "setup": setup, "move": move, "draw": draw}


def _touch_pieces(thing: _Thing, facts: Facts, rule: str) -> list[str]:
    player = facts.get("player")
    width, height = _screen_size(facts)
    if rule == "reset_player":
        return [f"if {player}.collidelist({thing.items}) != -1:",
                f"    {player}.center = ({width} // 2, {height} // 2)"]
    if rule == "collect":
        return [f"for {thing.item} in {thing.items}:",
                f"    if {player}.colliderect({thing.item}):",
                "        score += 1"] + [
            f"        {line}" for line in _respawn(thing, thing.item, width, height)]
    return []


def _ship_player(ctx: Context, edit: _Edit) -> bool:
    """Draw the player as a small ship, when the child called it one. Same rectangle, so
    movement and collisions are unchanged -- only its picture."""
    facts = ctx.facts
    if not (_SHIP_WORDS.search(ctx.request) and facts.has("player_draw")
            and facts.has("player_colour") and facts.get("player_shape") == "rect"):
        return False
    player = facts.get("player")
    surface = facts.get("surface", "screen")
    indent = facts.get("indent")
    line, last = facts.get("player_draw")
    edit.replace_statement(line, last,
                           f"{indent}pygame.draw.polygon({surface}, "
                           f"{facts.get('player_colour')}, [")
    edit.after(line, [
        f"    ({player}.centerx, {player}.top),",
        f"    ({player}.right, {player}.bottom),",
        f"    ({player}.centerx, {player}.bottom - {player}.height // 4),",
        f"    ({player}.left, {player}.bottom),",
        "])",
    ], indent)
    return True


def _assemble(ctx: Context, pieces: list[dict[str, list[str]]], *, needs_random: bool,
              needs_math: bool = False, edit: _Edit | None = None) -> str:
    """Put each piece in its place. The whole point of the module is this function."""
    facts = ctx.facts
    edit = edit or _Edit(facts.get("source"))
    indent = facts.get("indent")
    constants = [line for piece in pieces for line in piece.get("constants", [])]
    setup = [line for piece in pieces for line in piece.get("setup", [])]
    move = [line for piece in pieces for line in piece.get("move", [])]
    draw = [line for piece in pieces for line in piece.get("draw", [])]

    imports = facts.get("imports") or set()
    wanted = [name for name, needed in (("math", needs_math), ("random", needs_random))
              if needed and name not in imports]
    if wanted:
        if not facts.has("last_import"):
            raise NotApplicable("no imports to add beside")
        edit.after(facts.get("last_import"), [f"import {name}" for name in wanted])
    if constants:
        if not facts.has("constants_end"):
            raise NotApplicable("nowhere obvious for new constants")
        edit.after(facts.get("constants_end"), constants)
    if setup:
        edit.before(facts.get("setup_line"), setup + [""])
    if move:
        edit.before(facts.get("fill"), move + [""], indent)
    if draw:
        edit.before(facts.get("flip"), draw, indent)
    return edit.text()


def add_things(ctx: Context) -> Change:
    """A new thing -- or several -- set up above the loop, moved in it, drawn after fill.

    ``params`` decides what else comes with it, which is how one operation serves
    "add a moving asteroid", "add an enemy that chases me", "add a coin to collect" and
    "make a game where you catch falling blocks": ``motion`` (a name, a list the child's
    words or the project's seed choose from, or ``choose`` to ask the model),
    ``on_touch`` (``reset_player`` or ``collect``), ``score`` (``per_touch`` or
    ``per_second``) and ``ship_player``.
    """
    _require(ctx.facts, "loop", "fill", "flip")
    on_touch = ctx.params.get("on_touch")
    if on_touch or ctx.params.get("motion") == "chase":
        _require(ctx.facts, "player")
    thing = _new_thing(ctx)
    pieces = [_thing_pieces(thing, ctx.facts)]
    score = ctx.params.get("score")
    if score:
        pieces.append(_score_pieces(ctx.facts, score))
    if on_touch:
        # Collisions come after every move, so they test where things are this frame.
        pieces[0]["move"] = pieces[0]["move"] + _touch_pieces(thing, ctx.facts, on_touch)
    edit = _Edit(ctx.facts.get("source"))
    ship = bool(ctx.params.get("ship_player")) and _ship_player(ctx, edit)
    source = _assemble(ctx, pieces, needs_random=True,
                       needs_math=thing.motion in ("wave", "orbit"), edit=edit)

    touch = ""
    if on_touch == "reset_player":
        touch = "If one touches the player, the player goes back to the middle."
    elif on_touch == "collect":
        touch = f"Touch {'it' if thing.count == 1 else 'one'} to score a point."
    p = thing.prefix
    knobs = [f"{p}_COUNT", f"{p}_SIZE"] + (
        [f"{p}_SPEED"] if thing.motion in game_things.SPEEDS else [])
    tune = (f"{', '.join(knobs[:-1])} and {knobs[-1]} at the top set how many, how big"
            + (" and how fast." if len(knobs) == 3 else "."))
    return Change(
        files={ctx.facts.get("entry"): source},
        values={"what": game_things.describe(thing.style), "touch": touch,
                "noun": thing.noun, "tune": tune,
                "ship": "The player is drawn as a little ship now." if ship else
                        "The square is your ship for now -- add a picture and I can use it.",
                "speed": thing.speed if thing.motion in game_things.SPEEDS else ""},
        expect={"moves_by_itself": thing.motion != "still", "list": thing.items},
    )


def add_score(ctx: Context) -> Change:
    """A score on screen: one that counts seconds, or one that waits to be given points."""
    _require(ctx.facts, "loop", "fill", "flip")
    if ctx.facts.has("score"):
        raise NotApplicable("there is a score already")
    rule = ctx.params.get("rule", "choose")
    if rule == "choose" and re.search(r"\b(every|each|per|a) second\b|\bby itself\b|\btimer\b",
                                      ctx.request, re.IGNORECASE):
        # What the child literally wrote decides it, before any question is asked.
        rule = "per_second"
    if rule == "choose":
        if ctx.choose is None:
            raise NotApplicable("no model to ask how the score works")
        answer = confident(ctx.choose("How should the score go up?", [
            Option("per_second", "it goes up by itself as time passes, every second"),
            Option("shown", "it is just a score shown on screen; they did not say how it "
                            "goes up"),
            Option(OTHER, "some other way"),
        ]))
        if answer not in ("per_second", "shown"):
            raise NotApplicable("not sure how the score should go up")
        rule = answer
    source = _assemble(ctx, [_score_pieces(ctx.facts, rule)], needs_random=False)
    how = ("It goes up by one every second." if rule == "per_second"
           else "It starts at 0. Nothing adds points yet -- tell me what should.")
    return Change(files={ctx.facts.get("entry"): source}, values={"how": how},
                  expect={"score": True})


def add_collision(ctx: Context) -> Change:
    """Something happens when the player touches a thing that is already in the game."""
    _require(ctx.facts, "loop", "fill", "flip", "player")
    things = {p: t for p, t in (ctx.facts.get("things") or {}).items() if t["list"]}
    if not things:
        raise NotApplicable("nothing in the game for the player to touch")
    if len(things) == 1:
        prefix = next(iter(things))
    else:
        named = slots.noun_in(ctx.request, NOUN_WORDS)
        matches = [p for p in things if named and p.split("_")[0] == named[0].upper()]
        if len(matches) != 1:
            raise NotApplicable("more than one kind of thing, and the message does not say")
        prefix = matches[0]
    noun = prefix.split("_")[0].lower()
    # Respawning somewhere random is right for whatever motion the thing has: it is only
    # used when a collected thing needs a new place.
    look = game_things.NOUNS.get(noun, game_things.NOUNS["thing"])
    thing = _Thing(noun=noun, prefix=prefix, items=things[prefix]["list"],
                   item=noun + prefix[len(noun):].lower(),
                   style=game_things.Style(noun, look, 2, "bounce", look.size, 0,
                                           look.colours[0], look.colours[0]))
    if ctx.choose is None:
        raise NotApplicable("no model to ask what should happen")
    answer = confident(ctx.choose("What should happen when they touch?", [
        Option("reset_player", "the player gets hit, loses, or has to start again"),
        Option("collect", "the player collects it or gets a point"),
        Option(OTHER, "something else"),
    ]))
    if answer not in ("reset_player", "collect"):
        raise NotApplicable("not sure what should happen on touching")
    pieces = [{"move": _touch_pieces(thing, ctx.facts, answer)}]
    if answer == "collect":
        pieces.append(_score_pieces(ctx.facts, "shown") if not ctx.facts.has("score")
                      else {})
    source = _assemble(ctx, pieces, needs_random=True)
    what = ("the player goes back to the middle" if answer == "reset_player"
            else f"the {noun} jumps somewhere new and the score goes up")
    return Change(files={ctx.facts.get("entry"): source},
                  values={"noun": noun, "what": what}, expect={})


def thing_look(ctx: Context) -> Change:
    """Recolour or resize something a recipe added earlier, by its own constants.

    Mid-build changes are most of a real session: "make the asteroids red", "bigger
    stars". The thing is found by the naming convention in the file as it is now, and
    only its ``..._COLOUR`` / ``..._SIZE`` lines change -- nothing is re-added.
    """
    thing = _which_thing(ctx)
    constants = ctx.facts.get("constants") or {}
    prefix = thing["prefix"]
    edit = _Edit(ctx.facts.get("source"))
    said = []
    named = game_things.colour_in(ctx.request)
    colour = constants.get(f"{prefix}_COLOUR")
    if named is not None and colour is not None:
        edit.replace(colour.line, colour.start, colour.end, _rgb(named[1]))
        detail = constants.get(f"{prefix}_DETAIL")
        if detail is not None:
            look = game_things.NOUNS.get(thing["noun"], game_things.NOUNS["thing"])
            edit.replace(detail.line, detail.start, detail.end,
                         _rgb(game_things.detail_of(look, named[1])))
        said.append(named[0])
    words = set(re.findall(r"[a-z]+", ctx.request.lower()))
    size = constants.get(f"{prefix}_SIZE")
    factor = 1.5 if words & {"big", "bigger", "large", "larger", "huge", "giant"} else \
        (1 / 1.5 if words & {"small", "smaller", "tiny", "little"} else None)
    changed = [f"{prefix}_COLOUR"] if said else []
    if factor and size is not None and isinstance(size.value, int):
        new = max(2, round(size.value * factor))
        edit.replace(size.line, size.start, size.end, str(new))
        said.append("bigger" if factor > 1 else "smaller")
        changed.append(f"{prefix}_SIZE")
    if not said:
        raise NotApplicable("the message names no colour or size to change")
    noun = game_things.spoken_plural(thing["noun"])
    # Named only for what changed: the report used to say "CAR_COLOUR and CAR_SIZE are
    # what changed" when only the size had (the pre-13 acceptance run).
    return Change(files={ctx.facts.get("entry"): edit.text()},
                  values={"things": noun, "how": " and ".join(said), "prefix": prefix,
                          "changed": " and ".join(changed),
                          "were": "is" if len(changed) == 1 else "are"},
                  expect={})


#: Every way a recipe can have made a thing move -- what an existing thing's code is
#: compared against. "still" has no movement code to compare.
_MOVING = tuple(game_things.MOTIONS) + ("chase",)


def _existing(facts: Facts, prefix: str, motion: str) -> _Thing:
    """The thing a recipe added under ``prefix``, as it would be with ``motion``."""
    things = facts.get("things") or {}
    constants = facts.get("constants") or {}
    count = getattr(constants.get(f"{prefix}_COUNT"), "value", None)
    if prefix not in things or not things[prefix]["list"] or not isinstance(count, int):
        raise NotApplicable(f"{prefix} is not laid out the way a recipe adds things")
    noun = prefix.split("_")[0].lower()
    look = game_things.NOUNS.get(noun, game_things.NOUNS["thing"])
    # Only the parts that decide the setup and movement code matter here: the count
    # (a big field of dots gets different sizes) and the motion. Colour, size and
    # speed are constants the code refers to by name.
    style = game_things.Style(noun, look, count, motion, look.size, 0, look.colours[0],
                              look.colours[0])
    return _Thing(noun=noun, prefix=prefix, items=things[prefix]["list"],
                  item=noun + prefix[len(noun):].lower(), style=style)


def _written(facts: Facts, thing: _Thing) -> tuple[str, str]:
    """The setup and movement code a recipe writes for this thing, exactly as written."""
    pieces = _thing_pieces(thing, facts)
    indent = facts.get("indent")
    return ("\n".join(pieces["setup"]),
            "\n".join(indent + line if line else "" for line in pieces["move"]))


def _whole_lines(source: str, text: str) -> int | None:
    """The line ``text`` starts on, when it is whole lines of ``source`` exactly once."""
    framed = f"\n{source}\n"
    if not text or framed.count(f"\n{text}\n") != 1:
        return None
    return framed[:framed.index(f"\n{text}\n")].count("\n")


def motion_of(facts: Facts, prefix: str) -> tuple[str, list[tuple[int, str]]] | None:
    """How a recipe-made thing moves now, and where its setup and movement code are.

    Found by writing each motion's code for this thing and looking for it, as whole
    lines and exactly once, in the file. None when the child or Gary has changed either
    piece -- and then nothing here touches it.
    """
    source = facts.get("source") or ""
    for motion in _MOVING:
        if motion == "chase" and not facts.has("player"):
            continue
        pieces = _written(facts, _existing(facts, prefix, motion))
        found = [(_whole_lines(source, text), text) for text in pieces]
        if all(line is not None for line, _ in found):
            return motion, found
    return None


def _without_old_motion(text: str) -> str:
    """The request with "instead of going straight" and "not falling" taken out, so the
    motion it names is the new one."""
    text = re.sub(r"\binstead\s+of\s+\w+(?:\s+(?:straight|across|down|up|around|round|"
                  r"sideways|left and right))?", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\b(?:not|stop|no more|no longer)\s+\w+", " ", text, flags=re.IGNORECASE)


def thing_motion(ctx: Context) -> Change:
    """Change how something a recipe added moves: zigzag instead of drifting, and so on.

    Known failure 1 of SPIKES.md section 25J: with no option for this, "make the
    asteroids zigzag instead of going straight" became a speed change. Only code that is
    exactly what a recipe wrote is rewritten -- its setup and its movement, nothing
    else; its drawing, its constants and what happens when it is touched stay as they
    are. The new motion is the one the child named, or a closed question when they
    named none or several.
    """
    _require(ctx.facts, "loop", "fill", "flip")
    prefix = _which_thing(ctx)["prefix"]
    found = motion_of(ctx.facts, prefix)
    if found is None:
        raise NotApplicable(f"how the {prefix.lower()} things move has been changed "
                            "since a recipe wrote it")
    old, places = found
    wanted = {motion for motion, pattern in game_things.MOTION_CUES
              if re.search(pattern, _without_old_motion(ctx.request).lower())}
    wanted &= set(_MOVING)
    if len(wanted) == 1:
        new = wanted.pop()
    else:
        if ctx.choose is None:
            raise NotApplicable("no model to ask how it should move")
        options = [Option(name, text) for name, text in game_things.MOTIONS.items()]
        if ctx.facts.has("player"):
            options.append(Option("chase", "follows the player"))
        options.append(Option(OTHER, "some other way, or it does not say"))
        new = confident(ctx.choose("How should it move now?", options))
        if new is None or new == OTHER:
            raise NotApplicable("not sure how it should move")
    if new == "chase" and not ctx.facts.has("player"):
        raise NotApplicable("there is no player to follow")
    if new == old:
        thing = _existing(ctx.facts, prefix, old)
        one, several = game_things.MOTION_WORDS[old]
        things = (game_things.spoken(thing.noun) if thing.count == 1
                  else game_things.spoken_plural(thing.noun))
        raise AlreadyDone(f"The {things} already {one if thing.count == 1 else several}, "
                          "so I left them as they are.")

    thing = _existing(ctx.facts, prefix, new)
    edit = _Edit(ctx.facts.get("source"))
    for (first, old_text), new_text in zip(places, _written(ctx.facts, thing)):
        edit.replace_statement(first, first + old_text.count("\n"), new_text)
    constants = ctx.facts.get("constants") or {}
    extra = {"wave": [f"{prefix}_WAVE = 40"], "orbit": [f"{prefix}_RADIUS = 50"]}.get(new, [])
    extra = [line for line in extra if line.split(" = ")[0] not in constants]
    if extra:
        edit.after(ctx.facts.get("constants_end"), extra)
    if new in ("wave", "orbit") and "math" not in (ctx.facts.get("imports") or set()):
        if not ctx.facts.has("last_import"):
            raise NotApplicable("no imports to add beside")
        edit.after(ctx.facts.get("last_import"), ["import math"])
    one, several = game_things.MOTION_WORDS[new]
    single = thing.count == 1
    return Change(
        files={ctx.facts.get("entry"): edit.text()},
        values={"things": (game_things.spoken(thing.noun) if single
                           else game_things.spoken_plural(thing.noun)),
                "how": one if single else several, "prefix": prefix,
                "was": game_things.MOTION_WORDS[old][0 if single else 1]},
        expect={"motion": new, "prefix": prefix, "list": thing.items,
                "moves_by_itself": True},
    )


def use_sprite(ctx: Context) -> Change:
    """Draw a picture the child imported where the player's rectangle was drawn."""
    _require(ctx.facts, "player", "player_draw", "set_mode_line")
    choices = ctx.facts.get("attached_images") or ctx.facts.get("images") or []
    if not choices:
        raise NeedsAnswer("there is no picture in the project yet")
    if len(choices) > 1:
        raise NeedsAnswer("there is more than one picture, and it does not say which")
    picture = choices[0]
    player = ctx.facts.get("player")
    size = ctx.facts.get("player_size")
    surface = ctx.facts.get("surface", "screen")
    edit = _Edit(ctx.facts.get("source"))
    scale = size or f"{player}.width"
    edit.after(ctx.facts.get("set_mode_line"), [
        f"{player}_image = pygame.image.load({_python_string(picture)}).convert_alpha()",
        f"{player}_image = pygame.transform.smoothscale(",
        f"    {player}_image,",
        f"    ({scale}, round({scale} * {player}_image.get_height() / "
        f"{player}_image.get_width())),",
        ")",
    ])
    first, last = ctx.facts.get("player_draw")
    indent = ctx.facts.get("indent")
    edit.replace_statement(first, last,
                           f"{indent}{surface}.blit({player}_image, "
                           f"{player}_image.get_rect(center={player}.center))")
    return Change(files={ctx.facts.get("entry"): edit.text()},
                  values={"picture": picture}, expect={"picture": picture})


def controls(ctx: Context) -> Change:
    """Also move with W A S D, or follow the mouse."""
    _require(ctx.facts, "player", "arrow_ifs", "fill")
    if ctx.choose is None:
        raise NotApplicable("no model to ask which controls")
    answer = confident(ctx.choose("How should the player be controlled?", [
        Option("wasd", "with the W A S D keys"),
        Option("mouse", "by following the mouse"),
        Option(OTHER, "some other way"),
    ]))
    source = ctx.facts.get("source")
    edit = _Edit(source)
    if answer == "wasd":
        letters = {"K_LEFT": "K_a", "K_RIGHT": "K_d", "K_UP": "K_w", "K_DOWN": "K_s"}
        changed = 0
        for line, key in ctx.facts.get("arrow_ifs"):
            text = edit.lines[line]
            letter = letters.get(key)
            if letter is None or f"pygame.{letter}" in source:
                continue
            match = re.search(rf"(keys\[pygame\.{key}\])", text)
            if match:
                edit.replace(line, match.start(), match.end(),
                             f"{match.group(1)} or keys[pygame.{letter}]")
                changed += 1
        if not changed:
            raise NotApplicable("W A S D already work, or the arrow keys are not found")
        how = "W A S D move the player as well as the arrow keys now."
    elif answer == "mouse":
        player = ctx.facts.get("player")
        at = ctx.facts.get("clamp", ctx.facts.get("fill"))
        edit.before(at, [f"{player}.center = pygame.mouse.get_pos()"],
                    ctx.facts.get("indent"))
        how = "The player follows the mouse now."
    else:
        raise NotApplicable("not sure which controls")
    return Change(files={ctx.facts.get("entry"): edit.text()}, values={"how": how},
                  expect={})


def player_motion(ctx: Context) -> Change:
    """The player moves on its own: falls, bounces, or slides."""
    _require(ctx.facts, "player", "fill")
    if ctx.choose is None:
        raise NotApplicable("no model to ask how the player moves")
    answer = confident(ctx.choose("How should the player move by itself?", [
        Option("fall", "it falls down the screen and starts again at the top"),
        Option("bounce", "it bounces around off the edges"),
        Option("slide", "it slides left and right"),
        Option(OTHER, "some other way"),
    ]))
    if answer not in ("fall", "bounce", "slide"):
        raise NotApplicable("not sure how the player should move")
    player = ctx.facts.get("player")
    width, height = _screen_size(ctx.facts)
    at = ctx.facts.get("clamp", ctx.facts.get("fill"))
    indent = ctx.facts.get("indent")
    edit = _Edit(ctx.facts.get("source"))
    constants = ctx.facts.get("constants") or {}
    speed = "PLAYER_DRIFT_SPEED"
    if speed in constants:
        raise NotApplicable("the player already moves by itself")
    edit.after(ctx.facts.get("constants_end"), [f"{speed} = 3"])
    if answer == "fall":
        move = [f"{player}.y += {speed}", f"if {player}.bottom >= {height}:",
                f"    {player}.top = 0"]
        words = "falls down the screen and starts again at the top"
    else:
        dy = speed if answer == "bounce" else "0"
        edit.before(ctx.facts.get("setup_line"), [f"{player}_move = [{speed}, {dy}]", ""])
        move = [f"{player}.x += {player}_move[0]", f"{player}.y += {player}_move[1]",
                f"if {player}.left <= 0 or {player}.right >= {width}:",
                f"    {player}_move[0] = -{player}_move[0]",
                f"if {player}.top <= 0 or {player}.bottom >= {height}:",
                f"    {player}_move[1] = -{player}_move[1]"]
        words = "bounces off the edges" if answer == "bounce" else "slides left and right"
    edit.before(at, move, indent)
    return Change(files={ctx.facts.get("entry"): edit.text()},
                  values={"how": words, "name": speed},
                  expect={"moves_by_itself": True})


OPS = {
    "set_number": set_number,
    "set_colour": set_colour,
    "set_caption": set_caption,
    "add_things": add_things,
    "add_score": add_score,
    "add_collision": add_collision,
    "use_sprite": use_sprite,
    "thing_look": thing_look,
    "thing_motion": thing_motion,
    "controls": controls,
    "player_motion": player_motion,
}


# ------------------------------------------------------------------------ checks

def _playtest(ctx):
    return ctx.once("playtest", ctx.toolbox.playtest)


def _check_playtest(ctx):
    from opennest.execution import playtest as playtests
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    result = _playtest(ctx)
    if result is None:
        return Check("playtest_passes", UNAVAILABLE, "this project has no headless test")
    if result.verdict == playtests.PASSED:
        return Check("playtest_passes", PASS, f"{result.frames} frames")
    if result.failed:
        return Check("playtest_passes", FAIL, f"{result.verdict}: {result.error}")
    return Check("playtest_passes", UNAVAILABLE, result.verdict)


def _check_moves(ctx):
    """Something moves with nobody touching anything -- which the starter never does.

    Only meaningful because the recipe *added* a moving thing: the playtest alone
    deliberately never fails a game for being still (SPIKES.md section 24D), because it
    does not know what was asked. The recipe does.
    """
    from opennest.execution import playtest as playtests
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    result = _playtest(ctx)
    if result is None or result.verdict != playtests.PASSED:
        return Check("moves_by_itself", UNAVAILABLE, "the game was not tested")
    if result.moved_by_itself:
        return Check("moves_by_itself", PASS)
    return Check("moves_by_itself", FAIL, "nothing on screen moved without input")


def _check_responds(ctx):
    """The picture changes while a key is held or the mouse moves.

    Weak on its own when something else already moves by itself -- every input then
    "responds" -- which is why speed changes are also checked in the source.
    """
    from opennest.execution import playtest as playtests
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    result = _playtest(ctx)
    if result is None or result.verdict != playtests.PASSED:
        return Check("player_responds", UNAVAILABLE, "the game was not tested")
    if result.responded_to:
        return Check("player_responds", PASS, ", ".join(result.responded_to))
    return Check("player_responds", FAIL, "nothing changed when keys were pressed")


def _check_value(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    name, wanted = ctx.expect.get("constant"), ctx.expect.get("value")
    const = (ctx.facts_after.get("constants") or {}).get(name)
    if const is None:
        return Check("value_set", FAIL, f"{name} is not in the file")
    if const.value == wanted or (
        isinstance(wanted, (int, float)) and isinstance(const.value, (int, float))
        and abs(const.value - wanted) < 1e-9
    ) or (isinstance(wanted, tuple) and tuple(const.value) == tuple(wanted)):
        return Check("value_set", PASS, f"{name} = {const.value}")
    return Check("value_set", FAIL, f"{name} is {const.value}, not {wanted}")


def _check_speed_used(ctx):
    """The constant that changed is still the one the arrow keys move the player by."""
    from opennest.fastpath.verifier import FAIL, PASS, Check

    name = ctx.expect.get("constant")
    if ctx.facts_after.get("player_speed") == name:
        return Check("speed_used", PASS, f"the arrow keys move the player by {name}")
    return Check("speed_used", FAIL, f"the movement no longer uses {name}")


def _check_caption(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    caption = ctx.facts_after.get("caption")
    wanted = ctx.expect.get("caption")
    if caption is not None and caption[3] == wanted:
        return Check("caption_set", PASS, wanted)
    return Check("caption_set", FAIL, "the window title is not what was asked")


def _check_drawn(ctx):
    """A new thing is drawn after the fill -- the fault SPIKES.md section 23C found most.

    Read with the parser: a ``for`` over the thing's list, directly in the game loop,
    after the fill and before the flip, with a ``pygame.draw`` call somewhere inside.
    """
    from opennest.fastpath.verifier import FAIL, PASS, Check

    facts_after = ctx.facts_after
    wanted = ctx.expect.get("list")
    if not (facts_after.has("fill") and facts_after.has("flip") and wanted):
        return Check("drawn_after_fill", FAIL, "the loop, fill or flip is gone")
    tree = ast.parse(facts_after.get("source"))
    loop = next(node for node in tree.body if isinstance(node, ast.While)
                and node.lineno - 1 == facts_after.get("loop"))
    fill, flip = facts_after.get("fill"), facts_after.get("flip")
    for stmt in loop.body:
        if (isinstance(stmt, ast.For) and fill < stmt.lineno - 1 < flip
                and isinstance(stmt.iter, ast.Name) and stmt.iter.id == wanted
                and any(isinstance(n, ast.Call) and _dotted(n.func).startswith("pygame.draw.")
                        for n in ast.walk(stmt))):
            return Check("drawn_after_fill", PASS)
    return Check("drawn_after_fill", FAIL, f"{wanted} is not drawn after the fill")


def _check_motion(ctx):
    """The thing's code, read back from the file, is the new motion's code."""
    from opennest.fastpath.verifier import FAIL, PASS, Check

    prefix, wanted = ctx.expect.get("prefix"), ctx.expect.get("motion")
    try:
        found = motion_of(ctx.facts_after, prefix)
    except NotApplicable as exc:
        return Check("motion_set", FAIL, str(exc))
    if found is not None and found[0] == wanted:
        return Check("motion_set", PASS, f"{prefix}: {wanted}")
    return Check("motion_set", FAIL, f"{prefix} does not {wanted} in the file")


CHECKS = {
    "motion_set": _check_motion,
    "playtest_passes": _check_playtest,
    "moves_by_itself": _check_moves,
    "player_responds": _check_responds,
    "value_set": _check_value,
    "speed_used": _check_speed_used,
    "caption_set": _check_caption,
    "drawn_after_fill": _check_drawn,
}


#: How a change Gary makes here is checked, for his context (router._context).
CHECKED = ("After you change the game, Open Nest runs it once without a window and sends "
           "back a crash, a blank screen, a window that closes itself, or a picture that "
           "never changes.")


def verifiable(project) -> bool:
    """Whether this project gets the headless playtest these recipes are checked by.

    The same condition ``Toolbox.playtest`` applies: a Game project does, and a game
    written into a Blank project does not -- so there its recipes are guidance only.
    """
    return project.profile.playtest == "pygame" and project.profile.can_run


def confirmation(verification, project=None) -> str:
    """One sentence for the child about what was actually checked, and nothing more.

    Built only from checks that passed. "I tested it" is never said about a test that
    could not run, and the sentence names what the test saw rather than what the recipe
    hoped for (the 12.4 rule for "It works.").
    """
    from opennest.fastpath.verifier import PASS

    if verification.status_of("playtest_passes") != PASS:
        button = getattr(getattr(project, "profile", None), "run_label", "Run Game")
        return f"I haven't been able to test it here, so press {button} and see."
    seen = []
    if verification.status_of("moves_by_itself") == PASS:
        seen.append("something moves on its own now")
    if verification.status_of("player_responds") == PASS and not seen:
        seen.append("the player still moves when you press the keys")
    if seen:
        return f"I tested it without a window: it runs, and {seen[0]}."
    return "I tested it without a window, and it runs."


def _nearest_colour(rgb) -> str:
    """The palette name closest to a colour, for describing it in words."""
    try:
        r, g, b = rgb
    except (TypeError, ValueError):
        return ""
    return min(slots.PALETTE, key=lambda name: sum(
        (a - c) ** 2 for a, c in zip(slots.PALETTE[name], (r, g, b))))


def brief(facts: Facts) -> str:
    """What the classifier is told about the game, from the facts alone."""
    if not facts.has("loop"):
        return "The game has been changed a lot from the starter." if facts.has("source") \
            else ""
    parts = []
    if facts.has("player"):
        constants = facts.get("constants") or {}
        colour = constants.get(facts.get("player_colour", ""))
        source = facts.get("source") or ""
        shape = {"rect": "square", "polygon": "ship shape", "circle": "circle"}.get(
            facts.get("player_shape"), "shape")
        if f"{facts.get('player')}_image" in source:
            look = "a picture"
        elif colour is not None:
            look = f"the {_nearest_colour(colour.value)} {shape}"
        else:
            look = f"a {shape}"
        parts.append(f"The player is {look}, moved with the arrow keys.")
    things = facts.get("things") or {}
    if things:
        names = [game_things.spoken_plural(prefix.split("_")[0].lower()) for prefix in things]
        parts.append(f"Other things in the game: {', '.join(names)}.")
    else:
        parts.append("Nothing else is in the game yet.")
    if facts.has("score"):
        parts.append("It has a score.")
    return " ".join(parts)
