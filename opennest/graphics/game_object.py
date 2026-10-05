"""``game_object``: Gary says what a thing is and how it looks; Open Nest writes the code.

The tool Gary calls for anything the child *sees* -- the player's picture, a sky, a road,
buildings, cars, coins. His arguments are the creative decisions: what the thing is
called, a picture or a drawing or shapes, its colour, where it goes, how many, which way
it moves, what touching it does. What this module decides is only the mechanics: which
statement in the game that means, where it goes so the game still works, and what the
kit (``src/scene.py``) needs to draw it.

The thing it changes is found by name:

- **"player"** -- or the picture the player already wears -- is the rectangle the arrow
  keys move. Its look is swapped; its rectangle, its movement and everything that bumps
  into it are left exactly as they were. That is the work order's separation of visual
  from logic, applied to the one object every game has.
- **a thing already in the scene** is changed where it stands; anything not mentioned
  keeps its value.
- **a list the game already draws** -- the Fast Path's cars, or Gary's own -- is drawn by
  the scene instead, with the loop that used to draw it taken out. Asked to move it
  somewhere, a list a recipe made is handed over to the scene altogether, when its code
  is still exactly what the recipe wrote.
- **anything else** is new.

It never writes a file itself. It returns the text each file should have, and the
Toolbox writes them through the same path checks and the same "never leave broken
Python" rule as every other tool (``agent/tools.py``). The result it returns is the
machine-readable account of what was actually done -- the only thing Gary's reply about
it may rest on.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from opennest.graphics import looks, maze, source
from opennest.graphics.looks import Look, LookError, quoted

#: The kit, as it goes into a project.
KIT_PATH = "src/scene.py"

#: Where a child's word for a thing's layer comes from, and the order they are drawn in.
LAYERS = ("background", "scenery", "things", "player", "effects", "ui")

#: How a thing moves by itself, as (x, y) per frame for a speed of one.
DIRECTIONS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1),
              "bounce": (1, 1)}

#: Drawings that stand on the ground, and land on a road or ground by themselves when
#: Gary said nothing about where.
STANDING = ("vehicle", "building", "house", "tree", "sign")
#: Drawings that are a band across the whole screen.
BANDS = ("road", "ground")

#: How much bigger than its box a picture is drawn when it becomes the player: a
#: picture has see-through edges, and the box is what bumps into things.
PICTURE_SCALE = 1.5

PLAYER_WORDS = ("player", "me", "hero", "character", "main character", "you")

#: Names that are how a game PLAYS, not something to see. Measured (SPIKES.md section
#: 28C): offered game_object, the 4B model reached for it for "add a timer", "3 lives",
#: "jump", "a game over screen" -- and a drawing called "timer" that counts nothing would
#: have been a success nobody could see through. So it is refused, with where to go.
MECHANICS = frozenset({
    "timer", "countdown", "clock", "lives", "life", "health", "score", "points",
    "level", "levels", "jump", "jumping", "gravity", "game_over", "gameover",
    "start_screen", "title_screen", "menu", "controls", "keys", "speed", "rules",
    "physics", "shooting", "attack", "collision", "collisions", "title", "caption",
    "sound", "sounds", "music",
})

CHECK = ("Open Nest tests the game after this turn, and the test says what the scene "
         "really drew.")
#: The same result in a project with no headless test -- a Blank project that became a
#: game (``agent.tools.offers_graphics``): nothing is promised that will not happen.
UNTESTED = ("Open Nest does not test games in this kind of project, so nothing has seen "
            "it drawn yet: pressing Run Game shows it.")


def _check_of(project) -> str:
    return CHECK if project.profile.playtest == "pygame" else UNTESTED


class Refused(Exception):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class Outcome:
    ok: bool
    result: dict
    #: Project-relative path -> the full text it should have. Empty on a refusal.
    files: dict[str, str] = field(default_factory=dict)
    reason: str = ""


def run(project, arguments: dict, *, pictures: list[str] | None = None,
        kit: str | None = None, message: tuple[str, tuple[str, ...]] = ("", ()),
        added: frozenset[str] = frozenset(),
        pictured: frozenset[str] = frozenset()) -> Outcome:
    """Work out the change ``arguments`` ask for. Never raises for Gary's mistakes.

    ``message`` is the child's words this turn and the pictures attached to them -- what a
    picture may be used for is decided from those, never from what it might show.
    ``added`` is what earlier calls for this same message put in the scene, by name: a
    second call for one of those, somewhere else, is another of it (``_another``);
    ``pictured``, what this message gave a picture to, the same for a new picture."""
    try:
        return _run(project, arguments or {}, pictures, kit, message, added, pictured)
    except (Refused, LookError) as exc:
        return Outcome(False, {"ok": False, "object": str((arguments or {}).get("name", "")),
                               "reason": exc.reason, "message": str(exc),
                               "changed": "nothing -- no file was changed"},
                       reason=exc.reason)


# ----------------------------------------------------------------------------- the work


def _run(project, args: dict, pictures, kit_text, message=("", ()),
         added: frozenset[str] = frozenset(), pictured: frozenset[str] = frozenset()) -> Outcome:
    from opennest.fastpath.kinds import games  # the parser that finds the game's loop

    name = _clean_name(args.get("name"))
    if not name:
        raise Refused("game_object needs a name for the thing, like player, sky or cars.",
                      "missing_argument")
    if name in MECHANICS or name.rstrip("s") in MECHANICS:
        what = ("the window's title is set with pygame.display.set_caption" if name in (
            "title", "caption") else f"a {name.replace('_', ' ')} is how the game plays "
            f"-- counting, keys, rules, sound")
        if name in ("shooting", "attack"):
            what += ("; to make things that can be shot, give those things touch: shoot "
                     "(game_object with their name)")
        raise Refused(f"game_object only puts things to see in the scene and changes how "
                      f"they look, and {what}, so make it with edit_file. (A sign with words "
                      f"on it is a drawing: name it sign.) Nothing was changed.", "not_a_look")
    entry = f"src/{project.manifest.entrypoint}"
    path = project.directory / entry
    if not path.is_file():
        raise Refused(f"There is no {entry} yet, so there is no game to add to.",
                      "missing_file")
    text = path.read_text(encoding="utf-8")
    if pictures is None:
        pictures = _project_pictures(project)
    notes: list[str] = []

    files: dict[str, str] = {}
    facts = games.facts_of(text, entry)
    if not all(facts.has(key) for key in ("loop", "fill", "flip", "surface")):
        raise Refused(
            f"Open Nest can't find one game loop with a screen.fill(...) and a "
            f"pygame.display.flip() in {entry}, so it can't put anything in the scene. "
            f"Nothing was changed; edit_file can still change the code.", "no_game_loop")
    scene = source.read(text)
    resized = _resize_square(project, text, facts, scene, args, name, notes)
    if resized is not None:
        return resized
    # A recipe's things made faster or more numerous change only their own constants:
    # nothing about that needs a scene, so none is added for it.
    needs_scene = not _only_constants(facts, scene, args, name)
    kit_now = _kit_status(project, kit_text) if needs_scene else "not needed"
    if kit_now == "missing":
        files[KIT_PATH] = looks.kit_source()
    if needs_scene and scene.variable is None and "scene" in source.names_bound(scene.tree):
        raise Refused(f"{entry} already uses the name 'scene' for something else, so Open "
                      f"Nest can't add its scene.", "name_taken")
    if needs_scene and not scene.adopted:
        text = _adopt(text, facts, scene)
        facts = games.facts_of(text, entry)
        scene = source.read(text)
    work = _Work(project, text, facts, scene, args, name, pictures, notes, message, added)
    work.pictured = pictured
    if kit_now == "ours":
        # A kit changed by hand is never replaced, so it is drawn with what it can do: one
        # look per copy arrived in version 3, a grid -- a maze -- in version 4.
        present = (project.directory / KIT_PATH).read_text(encoding="utf-8")
        work.lists = (looks.kit_version(present) or 0) >= 3
        work.grids = (looks.kit_version(present) or 0) >= 4
    text, result = work.apply()
    if needs_scene:
        text = _imports(text, source.read(text))
        text = _drop_unread_colours(text, work.redundant, notes)
    if kit_now == "ours":
        present = (project.directory / KIT_PATH).read_text(encoding="utf-8")
        needed = set(source.read(text).imported) - looks.kit_classes(present)
        if needed:
            raise Refused(f"src/scene.py was changed and no longer has "
                          f"{', '.join(sorted(needed))}, which this needs. Nothing was "
                          f"changed.", "kit_changed")
    unchanged = text == path.read_text(encoding="utf-8")
    if kit_now == "earlier" and not unchanged:
        # A kit an earlier Open Nest put here, exactly as it was: the current one keeps
        # everything it had and adds what this change may use (``touched``, version 2).
        files[KIT_PATH] = looks.kit_source()
        notes.append("src/scene.py was brought up to date with Open Nest's newest scene kit")
    if unchanged and KIT_PATH not in files:
        # The same rule edit_file keeps: a change that leaves the game exactly as it was is
        # not a change, and must not be reported or counted as one.
        raise Refused(f"The {result.get('object', name)} already looks like that, so nothing "
                      f"was changed.", "no_change")
    try:
        compile(text, entry, "exec")
    except SyntaxError as exc:   # a bug here, never Gary's: say so rather than write it
        raise Refused(f"Open Nest could not make that change cleanly ({exc.msg}), so "
                      f"nothing was changed.", "internal") from None
    files[entry] = text
    result["files_changed"] = sorted(files)
    if notes:
        result["notes"] = notes
    result["check"] = _check_of(project)
    return Outcome(True, result, files)


def _resize_square(project, text, facts, scene, args, name, notes) -> Outcome | None:
    """"Make the player bigger", for a player the scene does not draw: its size constant,
    and nothing else -- no scene needed for a square to grow."""
    looks_given = any(args.get(key) for key in ("picture", "drawing", "shapes", "color",
                                                "colour", "frames"))
    player = facts.get("player")
    if looks_given or not _pair(args.get("size")) or not player or "player" in scene.entries:
        return None
    if name.replace("_", " ") not in PLAYER_WORDS and name != player:
        return None
    size_name = facts.get("player_size")
    constants = facts.get("constants") or {}
    const = constants.get(size_name) if size_name else None
    if const is None or not isinstance(const.value, int):
        return None
    new = max(8, min(min(_screen_size(facts)) // 3, max(_pair(args["size"]))))
    if new == const.value:
        raise Refused(f"The player is already {new} across, so nothing was changed.",
                      "no_change")
    lines = text.split("\n")
    line = lines[const.line]
    lines[const.line] = line[:const.start] + str(new) + line[const.end:]
    entry = f"src/{project.manifest.entrypoint}"
    return Outcome(True, {"ok": True, "object": "player", "action": "changed",
                          "size": f"{size_name} went from {const.value} to {new}",
                          "kept": "how it looks, the keys that move it and everything that "
                                  "bumps into it", "files_changed": [entry],
                          "check": _check_of(project)}, {entry: "\n".join(lines)})


def _drop_unread_colours(text: str, names: tuple[str, ...], notes: list[str]) -> str:
    """Colour constants the scene made redundant, once nothing reads them.

    Measured on the Qwen3 8B walk (SPIKES.md section 28E): after the player became a
    picture, "make everything more colourful" changed PLAYER_COLOUR, and Gary told the
    child the player was bright yellow now. Nothing drew with it. A constant listed under
    "Things you can change" that changes nothing is a trap for both of them.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    read = {node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    edit = source.Edit(text)
    dropped = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
                node.targets[0], ast.Name) and node.targets[0].id in names and \
                node.targets[0].id not in read:
            edit.replace(node.lineno - 1, node.end_lineno - 1, [])
            dropped.append(node.targets[0].id)
    if not dropped:
        return text
    notes.append(f"{', '.join(dropped)} went: nothing drew with "
                 f"{'it' if len(dropped) == 1 else 'them'} any more")
    return edit.text()


def _only_constants(facts, scene, args, name) -> bool:
    """A recipe's things, asked only to be faster or more of them."""
    if any(args.get(key) for key in ("picture", "drawing", "shapes", "color", "colour",
                                     "frames", "at", "on", "touch", "remove", "size")):
        return False
    if args.get("moves") not in (None, "", "still"):
        return False
    if not any(isinstance(args.get(key), (int, float)) for key in ("count", "speed")):
        return False
    if name in scene.entries or any(form in scene.entries for form in _forms(name)):
        return False
    for prefix, thing in (facts.get("things") or {}).items():
        noun = prefix.split("_")[0].lower()
        if thing.get("list") and (name in _forms(noun) or name in _forms(thing["list"])):
            return True
    return False


def _clean_name(value) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"[^a-z0-9_ ]", "", value.strip().lower()).strip().replace(" ", "_")
    return cleaned[:40]


def _project_pictures(project) -> list[str]:
    from opennest.assets import manager as assets

    return [a.path for a in assets.list_assets(project) if a.kind == "image"]


def _kit_status(project, kit_text: str | None) -> str:
    """"missing", "earlier" (a kit an earlier Open Nest shipped, unchanged), "ours" (the
    current kit or one changed by hand), or refuse."""
    place = project.directory / KIT_PATH
    if not place.is_file():
        return "missing"
    try:
        present = place.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        present = ""
    if looks.kit_version(present) is None or "Scene" not in looks.kit_classes(present):
        raise Refused("There is already a src/scene.py in this project that isn't Open "
                      "Nest's scene kit, so Open Nest won't touch it. Nothing was changed.",
                      "kit_taken")
    return "earlier" if looks.is_earlier_kit(present) else "ours"


def counts_touches(project) -> bool:
    """Whether the kit this project will have after a change has ``Scene.touched``: it
    has none yet (it gets the current one), an earlier one of ours unchanged (brought up
    to date), or a changed one that has it anyway. A child's changed kit without it keeps
    the rules it can run -- ``touching``, every frame."""
    place = project.directory / KIT_PATH
    if not place.is_file():
        return True
    try:
        present = place.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return looks.is_earlier_kit(present) or "touched" in looks.kit_methods(present)


def _adopt(text: str, facts, scene: source.GameScene) -> str:
    """Give a game its scene: the import, ``scene = Scene(screen)``, and the two calls in
    the loop. Nothing already in the game is moved or changed."""
    edit = source.Edit(text)
    lines = text.split("\n")
    last_import = facts.get("last_import")
    if not scene.imported:
        edit.insert(last_import + 1 if last_import is not None else 0,
                    ["", "from scene import Scene"])
    setup = facts.get("setup_line")
    edit.insert(setup, [source.SCENE_COMMENT, f"scene = Scene({facts.get('surface')})", ""])
    fill = facts.get("fill")
    indent = source.indent_of(lines[fill])
    edit.insert(fill, [f"{indent}scene.update()"])
    edit.insert(fill + 1, [f"{indent}scene.draw()"])
    return edit.text()


def _imports(text: str, scene: source.GameScene) -> str:
    """``from scene import ...`` naming exactly the kit's classes the game uses."""
    if scene.tree is None or scene.import_line is None:
        return text
    # Only the names inside the scene's own statements: a game with a bare pygame ``Rect``
    # must never have it replaced by the kit's.
    kit = looks.kit_classes()
    wanted = {"Scene"}
    for node in scene.tree.body:
        call = source._call_of(node)
        if call is not None and scene.variable and source._dotted(call.func) == \
                f"{scene.variable}.add":
            wanted |= {n.id for arg in call.args[1:2] for n in ast.walk(arg)
                       if isinstance(n, ast.Name) and n.id in kit}
    # Anything else the game imported from the kit stays imported while the game still
    # uses it -- a child's own Circle(...) keeps working; the ship's Polygon, once the
    # player is a picture, does not linger.
    read = {n.id for n in ast.walk(scene.tree) if isinstance(n, ast.Name)}
    used = sorted(wanted | (set(scene.imported) & read))
    line = f"from scene import {', '.join(used)}"
    if len(line) > 92:
        wrapped = ["from scene import ("]
        current = "    "
        for name in used:
            if len(current) + len(name) + 2 > 92:
                wrapped.append(current.rstrip())
                current = "    "
            current += f"{name}, "
        wrapped += [current.rstrip(), ")"]
        block = wrapped
    else:
        block = [line]
    node = next(n for n in scene.tree.body if isinstance(n, ast.ImportFrom)
                and n.module == "scene")
    edit = source.Edit(text)
    edit.replace(node.lineno - 1, node.end_lineno - 1, block)
    return edit.text()


# ----------------------------------------------------------------------------- targets


class _Work:
    """One call's change, against a game that already has its scene."""

    def __init__(self, project, text, facts, scene, args, name, pictures, notes,
                 message=("", ()), added=frozenset()):
        self.project, self.text, self.facts, self.scene = project, text, facts, scene
        self.args, self.name, self.pictures, self.notes = args, name, pictures, notes
        self.said, self.attached = message
        self.added = added
        #: How many there are now, when this call was another of one this message added.
        self.another = 0
        #: Whether the project's kit can draw a list of looks, one per copy (version 3).
        self.lists = True
        #: What earlier calls for this message gave a picture to.
        self.pictured: frozenset[str] = frozenset()
        #: Whether the project's kit can lay copies out from a grid (version 4).
        self.grids = True
        #: Whether this call's collect rule is a maze's goal.
        self.maze_goal = False
        self.lines = text.split("\n")
        self.width, self.height = _screen_size(facts)
        self.var = scene.variable
        #: Colour constants this change may have left drawing nothing.
        self.redundant: tuple[str, ...] = ()
        #: The game's own colour constants -- ``ASTEROID_COLOUR = (150, 150, 160)`` -- which
        #: a look may be drawn in by name, so the number at the top keeps deciding it.
        self.colour_constants = frozenset(
            name for name, const in (facts.get("constants") or {}).items()
            if isinstance(const.value, tuple) and len(const.value) == 3
            and all(isinstance(v, int) for v in const.value))

    # -- which thing ---------------------------------------------------------------

    def apply(self) -> tuple[str, dict]:
        player = self.facts.get("player")
        if self._means_maze():
            if player and self._means_player(player):
                raise Refused("A maze is its walls, not the player: call game_object with "
                              "name walls and layout maze. Nothing was changed.", "not_a_look")
            return self._maze(player)
        if player and self._means_player(player):
            return self._player(player)
        entry = self._existing_entry()
        if entry is not None:
            self._another(entry)
            return self._change_entry(entry)
        listed = self._game_list()
        if listed is not None:
            return self._take_over_list(*listed)
        if self.args.get("remove"):
            raise Refused(f"There is nothing called {self.name!r} in the scene to take "
                          f"away. Nothing was changed.", "not_found")
        return self._new()

    def _means_player(self, player: str) -> bool:
        name = self.name.replace("_", " ")
        if name in PLAYER_WORDS or self.name == player:
            return True
        current = self.scene.entries.get("player")
        worn = re.findall(r"['\"]([^'\"]+)['\"]", current.look) if current else []
        return any(self.name in {w for w in re.split(r"[^a-z0-9]+", Path(p).stem.lower())}
                   for p in worn)

    def _existing_entry(self) -> source.Entry | None:
        for candidate in _forms(self.name):
            if candidate in self.scene.entries and candidate != "player":
                entry = self.scene.entries[candidate]
                self.name = candidate
                return entry
        return None

    def _another(self, entry: source.Entry) -> None:
        """A second call for something this message already added, at another place, is
        another of it -- not the first one moved there.

        Measured on the owner's test04 replay: Qwen3 8B planted a forest as three calls,
        ``tree`` at x 100, 200 and 300; each replaced the last, and the game had one tree
        while the reply said "I added the trees". Its corners become a list -- one each.
        Only for this message's own additions, given only a new place and nothing that
        changes the look, so asking to move a thing that was already there still moves it.
        """
        args = self.args
        spot = _pair(args.get("at"))
        if (entry.name not in self.added and entry.name not in self.pictured) or \
                spot is None or args.get("remove") or \
                isinstance(entry.literals.get("count"), int) and entry.literals["count"] > 1:
            return
        current = entry.literals.get("at")
        spots = [tuple(s) for s in current] if isinstance(current, list) else \
            [tuple(current)] if isinstance(current, tuple) and len(current) == 2 else []
        if not spots or tuple(spot) in spots:
            return
        if entry.name in self.pictured and isinstance(args.get("picture"), str) and \
                entry.look_class == "Picture" and self.lists:
            # One picture per call, each at its own place: measured on the final test04
            # replay, the 8B planted the forest as six calls named "tree", tree_01.png at
            # x 100 to tree_06.png at x 600, and each replaced the last -- one tree. It is
            # one tree per picture, each at its place.
            paths = re.findall(r"""Picture\(\s*["']([^"']+)["']""", entry.look)
            if len(paths) != len(spots):
                return
            new = self._one_picture(args["picture"])
            if new.kind != "picture":
                return
            spots.append(tuple(spot))
            self.args = {**args, "picture": [*paths, new.picture],
                         "at": [list(s) for s in spots]}
            if "on" in entry.literals and not args.get("on"):
                self.args["on"] = entry.literals["on"]
            self.another = len(spots)
            self.notes.append(f"this message had already given {entry.name} a picture, so "
                              f"this is another one with {new.picture} at the new place: "
                              f"{len(spots)} now, each its own picture")
            return
        if entry.name not in self.added:
            return
        look = self.look(required=False)
        if look is not None and look.code() != entry.look:
            return
        size = _pair(args.get("size"))
        if size and entry.literals.get("size") not in (None, size):
            return
        spots.append(tuple(spot))
        self.args = {**args, "at": [list(s) for s in spots]}
        if "on" in entry.literals and not args.get("on"):
            self.args["on"] = entry.literals["on"]
        self.another = len(spots)
        self.notes.append(f"this message had already added {entry.name}, so this is another "
                          f"one at the new place: {len(spots)} now, one at each place")

    def _game_list(self):
        """A list of rects the game already has under this name: (list, prefix or None)."""
        things = self.facts.get("things") or {}
        for prefix, thing in things.items():
            noun = prefix.split("_")[0].lower()
            if thing.get("list") and (self.name in _forms(noun) or self.name in _forms(
                    thing["list"])):
                return thing["list"], prefix
        lists = source.top_level_lists(self.scene.tree)
        for candidate in _forms(self.name):
            if candidate in lists:
                return candidate, None
        return None

    # -- the look ------------------------------------------------------------------

    def look(self, *, required: bool) -> Look | None:
        args = self.args
        if args.get("picture"):
            return self._picture_look(args["picture"])
        drawing = args.get("drawing")
        #: A drawing asked for by a name the kit has no drawing for -- "planet", "rocket".
        unknown = None
        if isinstance(drawing, str) and drawing.strip().lower() in looks.DRAWINGS:
            drawing = drawing.strip().lower()
        elif drawing and looks.shape_word(drawing) and not args.get("shapes"):
            # "square", "a red circle": the plain shape is what was meant (test04 replay).
            kind = looks.shape_word(drawing)
            self.notes.append(f"there is no ready-made {drawing!r} drawing, so it is drawn as "
                              f"one plain {kind if kind != 'rect' else 'rectangle'}")
            colour_arg = args.get("color", args.get("colour"))
            return looks.shapes_look(looks.one_shape(kind, _pair(args.get("size")), colour_arg),
                                     _pair(args.get("size")), None, self.notes,
                                     self.colour_constants)
        elif drawing:
            meant = looks.infer_drawing(str(drawing))
            if meant:
                # "cars", "town": a word for one of the twelve.
                self.notes.append(f"{drawing!r} is drawn as the ready-made {meant} drawing")
                drawing = meant
            else:
                self.notes.append(f"there is no ready-made {drawing!r} drawing")
                unknown = str(drawing).strip()[:30]
                drawing = None
        fill = args.get("color", args.get("colour"))
        fill = looks.colour(fill, self.notes, constants=self.colour_constants) if fill \
            else None
        shapes = args.get("shapes")
        size = _pair(args.get("size"))
        at = _pair(args.get("at"))
        if shapes:
            drawn = looks.shapes_look(shapes, size, at, self.notes, self.colour_constants)
            if drawn is not None and not drawing:
                return drawn
            if drawn is not None and drawing:
                self.notes.append(f"it has a ready-made {drawing} drawing, so its extra "
                                  f"shapes were left out")
        if drawing:
            return Look("drawing", drawing=drawing, fill=fill,
                        text=str(args.get("text", "") or "")[:30])
        inferred = looks.infer_drawing(self.name)
        if unknown and not inferred:
            # Measured on the 13C worlds walk (SPIKES.md section 28M): Qwen3 8B asked for a
            # "planet", a "rocket", a "fish", was quietly given a plain box each time, and
            # told the child it had added a purple planet. The kit's drawings are generic
            # on purpose (section 28B) -- a new thing is composed, never added -- so the
            # answer says how to compose it, and changes nothing until it is.
            raise Refused(
                f"There is no ready-made {unknown!r} drawing. The ready-made ones are "
                f"{', '.join(looks.DRAWINGS)}. To draw a {unknown}, give "
                f"{self.name.replace('_', ' ')} shapes in its own box -- circles, ellipses, "
                f"rects, triangles, polygons -- like [{{\"circle\": [20, 20, 18], \"color\": "
                f"\"purple\"}}, {{\"ellipse\": [0, 16, 40, 8], \"color\": \"gold\"}}], or a "
                f"picture from the project. Nothing was changed.", "no_such_drawing")
        if not required:
            return None
        if inferred:
            return Look("drawing", drawing=inferred, fill=fill,
                        text=str(args.get("text", "") or "")[:30])
        if fill is not None:
            return Look("colour", fill=fill)
        raise Refused(f"Say what {self.name!r} looks like: a picture from the project, a "
                      f"ready-made drawing, shapes, or at least a color. Nothing was changed.",
                      "no_look")

    def _picture_look(self, asked) -> Look:
        """A picture's look -- or, for a list of pictures, or a numbered one given a count
        (tree_01.png, count 6), one picture per copy (kit version 3)."""
        if isinstance(asked, (list, tuple)):
            given = [str(item) for item in asked if isinstance(item, str) and item.strip()]
            if not given:
                raise LookError("picture needs the name of a picture in the project. Nothing "
                                "was changed.", "no_picture")
            checked = [self._one_picture(item) for item in given[:12]]
            if len(checked) == 1 or any(look.kind != "picture" for look in checked):
                return checked[0]
            series = tuple(dict.fromkeys(look.picture for look in checked))
            if len(series) == 1 or not self.lists:
                if len(series) > 1:
                    self.notes.append(f"this project's src/scene.py was changed by hand and "
                                      f"draws one picture for all of them, so it is "
                                      f"{series[0]}")
                return checked[0]
            return Look("pictures", picture=series[0], series=series, box=checked[0].box)
        look = self._one_picture(asked)
        count = self.args.get("count")
        if look.kind == "picture" and not self._targets_player and isinstance(
                count, (int, float)) and count > 1:
            series = looks.numbered_series(look.picture, self.pictures) if self.lists else ()
            if series and all(_header(self.project.directory / path) for path in series):
                # Measured on the owner's test04 replay: six tree pictures in Assets, "make
                # the forest", and the 8B used tree_01.png for one tree. A row of them is
                # all of them, in turn -- and said, so the reply can say so.
                self.notes.append(f"the numbered pictures {', '.join(series)} are used one "
                                  f"per copy, in turn")
                return Look("pictures", picture=series[0], series=series, box=look.box)
        return look

    def _one_picture(self, asked) -> Look:
        found = looks.find_picture(str(asked), self.pictures)
        if found is None:
            named = str(asked).strip().lstrip("./")
            place = self.project.directory / named
            if named and ".." not in Path(named).parts and place.is_file():
                # A file with a picture's name that is not one -- test03's eagle.png.
                raise LookError(f"{named} is not a picture -- its bytes are not an image, "
                                f"so the game could not show it. Nothing was changed.",
                                "not_a_picture")
            listed = ", ".join(self.pictures) if self.pictures else "none"
            drawing = looks.infer_drawing(self.name)
            if drawing and not self._targets_player:
                # Measured on the test04 replay: "trees" with assets/tree.png, a picture the
                # child had not added yet, was refused -- and the game had no trees at all.
                self.notes.append(f"there is no picture {asked!r} in the project (its "
                                  f"pictures: {listed}), so it is drawn as the ready-made "
                                  f"{drawing} drawing until there is one")
                fill = self.args.get("color", self.args.get("colour"))
                return Look("drawing", drawing=drawing,
                            fill=looks.colour(fill, self.notes) if fill else None)
            raise LookError(f"There is no picture {asked!r} in the project. Its pictures: "
                            f"{listed}. Nothing was changed.", "no_picture")
        header = _header(self.project.directory / found)
        if header is None:
            raise LookError(f"{found} is not a picture -- its bytes are not an image, so the "
                            f"game could not show it. Nothing was changed.", "not_a_picture")
        if not self._picture_asked_for(found):
            # Measured (SPIKES.md section 28E): with one picture in the project, the 4B used
            # eagle.png for an apple, the asteroids and the cars. Its name is the child's
            # word for it; nothing says it is a car, and nobody has looked. When the thing's
            # name has a ready-made drawing, that is used instead, and said -- measured, a
            # refusal left the 4B promising a car it then never drew.
            stem = Path(found).stem
            if self.owner and self.owner not in self.scene.entries and \
                    self.name not in self.scene.entries and not self._targets_player and \
                    re.search(rf"\b{re.escape(self.owner)}s?\s+(?:image|picture|pic|photo|"
                              rf"sprite)s?\b", (self.said or "").lower()):
                # A new thing, given the picture of something the game has not got yet,
                # that the child has just talked about as a picture: measured on the test04
                # replay, "I added the monster image now" and the 4B
                # called a new "tree" with blue_monster.png -- its own reply said "The blue
                # monster is now visible". The picture says what it was meant to be.
                self.notes.append(f"{found} is the {self.owner}'s picture, so this is the "
                                  f"{self.owner}, not a {self.name.replace('_', ' ')}")
                self.name = self.owner
                return self._one_picture(asked)
            drawing = looks.infer_drawing(self.name)
            whose = (f" -- its name says it is the {self.owner}: game_object with name "
                     f"{self.owner!r} and this picture puts it on the {self.owner}"
                     if self.owner else "")
            if drawing:
                self.notes.append(f"{found} is the child's picture they call {stem!r}, not "
                                  f"a {self.name.replace('_', ' ')}, so it is drawn as a "
                                  f"ready-made {drawing} drawing instead{whose}")
                fill = self.args.get("color", self.args.get("colour"))
                return Look("drawing", drawing=drawing,
                            fill=looks.colour(fill, self.notes) if fill else None,
                            text=str(self.args.get("text", "") or "")[:30])
            if self.owner:
                thing = self.name.replace("_", " ")
                raise LookError(f"{found} is the child's picture of the {self.owner} -- its "
                                f"name says so -- not of the {thing}. Use it for the "
                                f"{self.owner} (game_object with name {self.owner!r}), and "
                                f"draw the {thing} another way. Nothing was changed.",
                                "picture_not_asked")
            raise LookError(f"{found} is the child's picture they call {stem!r}, and nothing "
                            f"they said makes it the {self.name.replace('_', ' ')}. Draw the "
                            f"{self.name.replace('_', ' ')} with a ready-made drawing or shapes "
                            f"-- or ask them if it should be that picture. Nothing was changed.",
                            "picture_not_asked")
        frames = self.args.get("frames")
        frames = int(frames) if isinstance(frames, (int, float)) and frames > 1 else 0
        if frames:
            series = looks.numbered_series(found, self.pictures)
            if series:
                return Look("animation", picture=found, series=series)
            return Look("animation", picture=found, frames=min(frames, 64))
        look = Look("picture", picture=found)
        if header.width and header.height:
            look.box = (header.width, header.height)
        if header.has_alpha is False:
            # Nothing in it is see-through, so it is drawn as a rectangle, background and
            # all. Said, so the reply can say it and Open Nest can say how to fix it.
            self.solid = found
            self.notes.append(f"{found} has no see-through parts, so it is drawn as a "
                              f"rectangle, background and all")
        return look

    #: A picture used this call that has no see-through parts, or "".
    solid = ""

    def _picture_asked_for(self, picture: str) -> bool:
        """Whether a picture may be this thing's look: the player's, one attached to this
        message, one whose name is the thing's, or one the child's words name."""
        if picture in self.attached:
            return True
        words = {w for w in re.split(r"[^a-z0-9]+", Path(picture).stem.lower()) if len(w) > 2}
        if self._targets_player:
            owner = self._picture_owner(words)
            if owner and re.search(
                    rf"\b(?:find|reach|catch|collect|get to|chase|rescue|save|look for)\b"
                    rf"(?:\s+\w+){{0,3}}?\s+{re.escape(owner)}s?\b", (self.said or "").lower()):
                # "a maze game to find the monster I added" -- the monster is what the
                # player looks for, not the player (the 8B, Maze_test01 replay).
                self.owner = owner
                return False
            # Any picture may be the player ("use my eagle picture as the player") -- but
            # not one named for another thing the game already has, unless they say so.
            # Measured on the test04 replay: "I added the monster image now ... the player
            # must be walking forward ... the monster will hide", and the 4B made the
            # player blue_monster.png while the scene had its monster.
            owner = self._picture_owner(words)
            if owner and set(_forms(owner)) & set(self.scene.entries) and \
                    not self._said_for(words):
                self.owner = owner
                return False
            return True
        name = {w for form in _forms(self.name) for w in form.split("_")}
        # "forest" is made of trees, "town" of buildings: a tree picture is a forest's.
        name |= {w for w in list(name) for w in _forms(looks.GROUPS.get(w, ""))}
        if words & name:
            return True
        owner = self._picture_owner(words)
        if owner and not self._said_for(words):
            # Measured on the owner's test04 replay: "I added the monster image now ... the
            # monster will hide behind the trees" -- and the 4B gave the trees
            # blue_monster.png. Its name says whose it is; only the child's own "use the
            # monster picture for the trees" makes it another thing's.
            self.owner = owner
            return False
        # The child's words tie a picture to something only when they talk about a
        # picture: "use my eagle picture for the enemies", or "this picture" with one to
        # mean. "fly an eagle ... avoid cars" names the eagle, not the cars' picture.
        said = set(re.findall(r"[a-z0-9]+", (self.said or "").lower()))
        if not said & {"picture", "pictures", "image", "images", "photo", "pic", "sprite"}:
            return False
        return bool(words & said) or len(self.pictures) == 1

    _targets_player = False
    #: The thing a refused picture's own name says it is for -- "monster" -- or "".
    owner = ""
    #: Asked to stand on a ground the scene has not got: it stands on the screen's bottom
    #: (the final test04 replay: trees "on": "ground" in a game with no ground floated).
    no_ground = False

    def _picture_owner(self, words: set[str]) -> str:
        """Another thing a picture's name names -- one in the scene, or one the child
        talked about this message -- or ""."""
        said = set(re.findall(r"[a-z0-9]+", (self.said or "").lower()))
        mine = set(_forms(self.name)) | set(_forms(looks.GROUPS.get(self.name, "")))
        for word in sorted(words):
            if word in looks.palette() or word in mine:
                continue
            forms = set(_forms(word))
            if forms & mine:
                continue
            if forms & set(self.scene.entries) or forms & said:
                return word
        return ""

    def _said_for(self, words: set[str]) -> bool:
        """Whether the child's words give this picture to this thing: "use my eagle picture
        for the enemies", "make the monster picture the trees"."""
        said = (self.said or "").lower()
        names = "|".join(re.escape(form.replace("_", " ")) for form in _forms(self.name))
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b[^.!?]{{0,40}}\b(?:for|as|on|into|be|be the)"
                         rf"\b[^.!?]{{0,20}}\b(?:{names})\b", said):
                return True
        return False

    # -- the player ----------------------------------------------------------------

    def _player(self, player: str) -> tuple[str, dict]:
        self._targets_player = True
        args = self.args
        if args.get("remove"):
            raise Refused("The player can't be taken out of the scene -- the game needs it. "
                          "Give it another look instead. Nothing was changed.", "cannot_remove")
        ignored = [key for key in ("at", "on", "moves", "count", "touch", "speed")
                   if args.get(key) not in (None, "", [], 0, "still", "nothing")]
        if ignored:
            self.notes.append(f"{', '.join(ignored)} {'was' if len(ignored) == 1 else 'were'}"
                              f" left alone: the player starts where the game starts it and "
                              f"moves with the keys the game reads -- edit_file changes those")
        current = self.scene.entries.get("player")
        look = self.look(required=current is None)
        if look is not None and look.kind == "pictures":
            # One player, one picture: the first of the list.
            self.notes.append(f"the player is one thing, so it wears {look.picture}")
            look = Look("picture", picture=look.picture, box=look.box)
        tree = self.scene.tree
        edit = source.Edit(self.text)
        recoloured = None
        if look is None and current is not None and self._colour_given():
            recoloured = self._recolour(current.look, edit)
        constants = self.facts.get("constants") or {}
        size_name = self.facts.get("player_size")
        box = getattr(constants.get(size_name), "value", None) if size_name else None
        wanted = _pair(args.get("size"))
        limit = min(self.width, self.height) // 3
        if wanted and max(wanted) > limit:
            self.notes.append(f"{wanted[0]}x{wanted[1]} is most of the screen, so it is "
                              f"drawn {limit} across at most")
            wanted = (min(wanted[0], limit), min(wanted[1], limit))
        kind = look.kind if look else self._current_kind(current)
        scale = PICTURE_SCALE if kind in ("picture", "animation") else 1.0
        if current is not None and look is None:
            scale = float(current.literals.get("scale", scale))
        resized = None
        if wanted and isinstance(box, int) and box > 0:
            target = max(wanted)
            if size_name and self._only_the_rect_uses(size_name, player):
                new_box = max(8, round(target / scale))
                if new_box != box:
                    const = constants[size_name]
                    line = self.lines[const.line]
                    edit.replace(const.line, const.line,
                                 [line[:const.start] + str(new_box) + line[const.end:]])
                    resized = (box, new_box)
                    box = new_box
            else:
                scale = round(target / box, 2)
        # The statements that drew the player before are taken out: the scene draws it.
        drawn = source.player_drawing(tree, player) if current is None else []
        colour = self.facts.get("player_colour")
        if colour and (look is None or colour not in look.code()):
            self.redundant = (colour,)
        for first, last in drawn:
            edit.drop(first, last)
        if current is None:
            self._drop_unused_images(edit, player, drawn)
        look_code = look.code(keep_shape=_shape_of(look, wanted)) if look else \
            recoloured or current.look
        keywords = [("rect", player)]
        if scale != 1.0:
            keywords.append(("scale", _num(scale)))
        keywords.append(("layer", quoted(self._layer(current, "player"))))
        statement = source.call_text(self.var, "player", look_code, keywords, None)
        if current is not None:
            edit.replace(current.first, current.last, statement)
        else:
            edit.insert(self._position(after_names=(player,), layer="player"), statement)
        text = edit.text()
        visual = round(box * scale) if isinstance(box, int) else None
        result = {"ok": True, "object": "player",
                  "action": "changed",
                  "look": look.describe() if look else self._describe_code(current.look),
                  "layer": self._layer(current, "player")}
        if look and look.picture:
            result["picture"] = look.picture
            if self.solid:
                result["see_through"] = False
        if look and look.kind == "animation":
            result["frames"] = len(look.series) or look.frames
        if visual:
            result["drawn_size"] = [visual, visual]
        if isinstance(box, int):
            result["collision_box"] = [box, box]
        if resized:
            self.notes.append(f"{size_name} went from {resized[0]} to {resized[1]}, so the "
                              f"box it bumps into things with fits the new size")
        result["kept"] = ("the player's rectangle, the keys that move it and everything that "
                          "bumps into it are unchanged")
        if drawn:
            result["replaced"] = "the code that drew the player before"
        return text, result

    def _current_kind(self, current) -> str:
        if current is None:
            return ""
        return {"Picture": "picture", "Animation": "animation"}.get(current.look_class,
                                                                    "drawing")

    def _only_the_rect_uses(self, constant: str, player: str) -> bool:
        """Whether ``constant`` sizes only the player's rect, so changing it changes
        nothing else in the game."""
        tree = self.scene.tree
        uses = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
                and node.id == constant and isinstance(node.ctx, ast.Load)]
        rect = next((node for node in tree.body if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == player for t in node.targets)), None)
        if rect is None:
            return False
        inside = [n for n in ast.walk(rect) if isinstance(n, ast.Name) and n.id == constant]
        return len(uses) == len(inside) and len(uses) > 0

    def _drop_unused_images(self, edit, player, drawn) -> None:
        """The old sprite recipe's ``player_image = ...`` lines, once nothing draws them."""
        name = f"{player}_image"
        spans = source.assignments_of(self.scene.tree, name)
        if not spans:
            return
        loads = sum(1 for node in ast.walk(self.scene.tree) if isinstance(node, ast.Name)
                    and node.id == name and isinstance(node.ctx, ast.Load)
                    and not any(first <= node.lineno - 1 <= last for first, last in drawn)
                    and not any(first <= node.lineno - 1 <= last for first, last in spans))
        if loads == 0:
            for first, last in spans:
                edit.drop(first, last)

    # -- something already in the scene ----------------------------------------------

    def _change_entry(self, entry: source.Entry) -> tuple[str, dict]:
        edit = source.Edit(self.text)
        if self.args.get("remove"):
            return self._remove(entry, edit)
        if entry.wraps:
            return self._restyle_wrapped(entry, edit)
        look = self.look(required=False)
        recoloured = None
        if look is None and self._colour_given() and entry.look_class == "Sky":
            # A sky's colour is BACKGROUND's (``_sky_from_background``), whoever else reads it.
            look = Look("drawing", drawing="sky", fill=self._fill())
        elif look is None and self._colour_given():
            recoloured = self._recolour(entry.look, edit)
        keywords = self._keywords(entry, look)
        look_code = look.code() if look else recoloured or entry.look
        if look is not None and (entry.look_class == "Sky" or look.drawing == "sky"):
            look_code = self._sky_from_background(look, edit) or look_code
        statement = source.call_text(self.var, entry.name, look_code, keywords, entry.target)
        target = self.scene.entries.get(_on_of(keywords) or "")
        if target is not None and target.first > entry.first:
            # It now stands on something added after it: it goes after that, so a reader
            # sees them in the order they depend on each other.
            edit.drop(entry.first, entry.last)
            edit.insert(target.last + 1, statement)
        else:
            edit.replace(entry.first, entry.last, statement)
        self._rule(edit, entry.name)
        text = edit.text()
        result = self._report("added" if self.another else "changed", look, entry, keywords)
        if self.another:
            result["count"] = self.another
        return text, result

    def _remove(self, entry: source.Entry, edit) -> tuple[str, dict]:
        if entry.wraps:
            raise Refused(f"{entry.name!r} is the game's own code, which the scene only "
                          f"draws. Taking it away means changing that code with edit_file. "
                          f"Nothing was changed.", "cannot_remove")
        if entry.target and source.references(
                self.scene.tree, entry.target, besides=(entry.first, entry.last)):
            raise Refused(f"The game's code uses {entry.target} elsewhere, so taking it out "
                          f"of the scene would break it. Nothing was changed.", "in_use")
        edit.drop(entry.first, entry.last)
        if entry.name in self.scene.rules:
            first, last = self.scene.rules[entry.name]
            edit.drop(first, last)
        return edit.text(), {"ok": True, "object": entry.name, "action": "removed"}

    def _restyle_wrapped(self, entry, edit) -> tuple[str, dict]:
        """The game's own rects the scene draws: their look, colour, size, layer and what
        touching them does. Where they are and how they move stay the game's code."""
        items = entry.wraps
        prefix = self._prefix_of(items)
        look = self.look(required=False)
        if self._wants_place():
            motion, prefix = self._recipe_motion(items)
            if motion is not None:
                return self._hand_over(items, prefix, motion, look or _look_of(entry),
                                       None, edit, entry=entry,
                                       look_code=None if look else entry.look)
            self.notes.append(f"where {items} are and how they move is the game's own "
                              f"code, so only their look changed -- edit_file changes the rest")
        if look is None and prefix is not None and self._numbers_only():
            # "Make the asteroids faster": their own constants, nothing else.
            return self._constants_only(items, prefix, edit)
        size = _pair(self.args.get("size"))
        code = None
        if look is not None:
            code = look.code(keep_shape=_shape_of(look, size))
        elif self._colour_given():
            code = self._recolour(entry.look, edit)
        touch = self.args.get("touch") in ("avoid", "collect", "nothing")
        if code is None and not (size or touch or self._layer_given()):
            raise Refused(f"Say how {entry.name!r} should look: a picture, a drawing, shapes "
                          f"or a color. Nothing was changed.", "no_look")
        keywords = [(k, quoted(self._layer(entry, entry.layer)) if k == "layer" else v)
                    for k, v in entry.keywords.items()]
        if "layer" not in entry.keywords and self._layer_given():
            keywords.append(("layer", quoted(self._layer(entry, entry.layer))))
        if look is not None or size:
            keywords = [(k, v) for k, v in keywords if k != "scale"]
            scale = self._list_scale(entry.name, look or _look_of(entry), prefix=prefix)
            if scale != 1.0:
                keywords.insert(1, ("scale", _num(scale)))
        statement = source.call_text(self.var, entry.name, code or entry.look, keywords,
                                     entry.target)
        edit.replace(entry.first, entry.last, statement)
        self._rule(edit, entry.name, items=items)
        result = self._report("changed", look, entry, keywords)
        self._said_of_game_code(items, result)
        return edit.text(), result

    # -- a maze --------------------------------------------------------------------------

    _MAZE_WORDS = ("maze", "labyrinth")

    def _means_maze(self) -> bool:
        """``layout: maze`` -- or a maze asked for the way a model reaches for it: measured
        on the Maze_test01 confirmations, with layout described only beside the message,
        both models sent ``drawing: "maze"``; and a thing named "maze" with no look."""
        args = self.args
        if str(args.get("layout") or "").strip().lower() in self._MAZE_WORDS:
            return True
        if str(args.get("drawing") or "").strip().lower() in self._MAZE_WORDS:
            return True
        return self.name in self._MAZE_WORDS and not any(
            args.get(key) for key in ("picture", "shapes", "drawing"))

    #: How big a maze's squares are, and how much room the player has in a path.
    MAZE_CELL = 40
    MAZE_ROOM = 12

    def _maze(self, player: str | None) -> tuple[str, dict]:
        """``layout: maze`` -- walls laid out as a maze seen from above, solid, with the
        player at its start and its end said in the result (the owner's Maze_test01).

        What is written is the child's to read and change: ``MAZE`` at the top of the game,
        one string a row, "#" a wall; one ``scene.add(..., grid=MAZE, ...)``; and the rule
        that puts the player back when it walks into a wall. A road or ground goes -- a maze
        is seen from above -- and the player's start moves to the maze's start."""
        if player is None:
            raise Refused("A maze needs a player the arrow keys move, and this game has none "
                          "-- edit_file first. Nothing was changed.", "no_player")
        if not self.grids:
            raise Refused("This project's src/scene.py was changed by hand and cannot lay out "
                          "a grid, so Open Nest can't make a maze in it. Nothing was changed.",
                          "kit_changed")
        edit = source.Edit(self.text)
        tree = self.scene.tree
        cell = self.MAZE_CELL
        constants = self.facts.get("constants") or {}
        size_name = self.facts.get("player_size")
        box = getattr(constants.get(size_name), "value", None) if size_name else None
        room = cell - self.MAZE_ROOM
        if isinstance(box, int) and box > room:
            if size_name and self._only_the_rect_uses(size_name, player):
                const = constants[size_name]
                line = self.lines[const.line]
                edit.replace(const.line, const.line,
                             [line[:const.start] + str(room) + line[const.end:]])
                self.notes.append(f"{size_name} went from {box} to {room}, so the player fits "
                                  f"the maze's paths")
                box = room
            else:
                cell = box + self.MAZE_ROOM
        columns, rows = self.width // cell, self.height // cell
        columns, rows = columns - (columns % 2 == 0), rows - (rows % 2 == 0)
        left, top = (self.width - columns * cell) // 2, (self.height - rows * cell) // 2
        before = source.maze_layout(self.scene)
        seed = sum(map(ord, f"{self.project.name}{before[1] if before else ''}"))
        grid = maze.carve(columns, rows, seed)
        begin, finish = maze.start(grid), maze.end(grid)
        # The layout itself, at the top with the other things to change.
        name = "MAZE"
        constant = ["MAZE = [  # the maze: \"#\" is a wall, a space is a path",
                    *(f'    "{row}",' for row in grid), "]"]
        spans = source.assignments_of(tree, name)
        if spans:
            edit.replace(spans[0][0], spans[0][1], constant)
        else:
            end = self.facts.get("constants_end")
            edit.insert(end + 1 if end is not None else self.facts.get("setup_line"),
                        constant)
        # The walls: a plain block unless they were given a picture or shapes. ("drawing":
        # "maze" asked for the maze, not a look.)
        if str(self.args.get("drawing") or "").strip().lower() in self._MAZE_WORDS:
            self.args = {k: v for k, v in self.args.items() if k != "drawing"}
        look = self.look(required=False)
        if look is None or look.kind == "drawing":
            fill = self.args.get("color", self.args.get("colour")) or "slategray"
            if look is not None:
                self.notes.append(f"a maze's walls are blocks, so it is not a {look.drawing} "
                                  f"drawing -- a picture makes them look like something")
            look = Look("colour", fill=looks.colour(fill, self.notes))
        floor = getattr((self.facts.get("constants") or {}).get(
            self.facts.get("background") or ""), "value", None)
        shade = looks.rgb(look.fill) if look.kind == "colour" else None
        if isinstance(floor, tuple) and len(floor) == 3 and shade and \
                abs(_luminance(shade) - _luminance(floor)) < 60:
            # Black walls on the starter's near-black floor (the 4B, Maze_test01 replay):
            # a maze nobody can see. The walls are made to show.
            light = _luminance(floor) < 128
            look = Look("colour", fill=looks.colour("lightgray" if light else "darkgray",
                                                     self.notes))
            self.notes.append(f"{fill} walls would not show on this background, so they are "
                              f"{'light' if light else 'dark'} gray")
        keywords = [("grid", name), ("cell", str(cell)), ("at", f"({left}, {top})"),
                    ("hitbox", f"({cell}, {cell})"), ("layer", quoted("scenery"))]
        entry = next((self.scene.entries[form] for form in _forms(self.name)
                      if form in self.scene.entries), None)
        if entry is None and before is not None:
            # One maze: asked for again under another name ("maze" after "walls", the 8B
            # on the Maze_test01 replay), it is the same maze made again.
            entry = before[0]
        if entry is not None:
            self.name = entry.name
        # What was tried as walls before -- the 4B's "maze_wall", a building on the road --
        # is the maze now.
        tried = [e for e in self.scene.entries.values() if e is not entry and
                 "grid" not in e.keywords and not e.wraps and
                 any(word in e.name for word in ("wall", "maze"))]
        for old in tried:
            edit.drop(old.first, old.last)
            if old.name in self.scene.rules:
                edit.drop(*self.scene.rules[old.name])
        if tried:
            self.notes.append(f"{', '.join(e.name for e in tried)} went: the maze is the "
                              f"walls now")
        target = (entry.target if entry else self.name) if self.name.isidentifier() and (
            entry is not None or self.name not in source.names_used(tree)) else None
        statement = source.call_text(self.var, self.name, look.code(), keywords, target)
        if entry is not None:
            edit.replace(entry.first, entry.last, statement)
        else:
            edit.insert(self._position(after_names=(), layer="scenery"), statement)
        # Seen from above: no road or ground along the bottom, nothing standing on one.
        bands = [e for e in self.scene.entries.values()
                 if e.look_class in ("Road", "Ground") and e.name != self.name]
        for band in bands:
            edit.drop(band.first, band.last)
            if band.name in self.scene.rules:
                edit.drop(*self.scene.rules[band.name])
        gone = {band.name for band in bands}
        dropped = gone | {old.name for old in tried}
        for other in self.scene.entries.values():
            if other.name not in dropped and other is not entry and \
                    other.literals.get("on") in dropped:
                kept = [(k, v) for k, v in other.keywords.items() if k != "on"]
                edit.replace(other.first, other.last, source.call_text(
                    self.var, other.name, other.look, kept, other.target))
        if gone:
            self.notes.append(f"{', '.join(sorted(gone))} went: a maze is seen from above, "
                              f"and has no road or ground along its bottom")
        if before is not None:
            # A new maze has its end somewhere else: what was at the old end -- the goal --
            # goes to the new one, never left inside what is a wall now (the Maze_test01
            # replay: "create a maze" again, and the monster stayed where the end had been).
            _old, old_grid, old_cell, (old_left, old_top) = before
            old_end = maze.end(old_grid)
            ox, oy = old_left + old_end[0] * old_cell, old_top + old_end[1] * old_cell
            for other in self.scene.entries.values():
                spot, span = other.literals.get("at"), other.literals.get("size")
                if other is entry or other.name in dropped or not (
                        isinstance(spot, tuple) and isinstance(span, tuple)):
                    continue
                if ox <= spot[0] and spot[0] + span[0] <= ox + old_cell + 1 and \
                        oy <= spot[1] and spot[1] + span[1] <= oy + old_cell + 1:
                    nx = left + finish[0] * cell + spot[0] - ox
                    ny = top + finish[1] * cell + spot[1] - oy
                    kept = [(k, f"({nx}, {ny})" if k == "at" else v)
                            for k, v in other.keywords.items()]
                    edit.replace(other.first, other.last, source.call_text(
                        self.var, other.name, other.look, kept, other.target))
                    self.notes.append(f"{other.name} went to the new maze's end")
        # The player starts at the maze's start, and so does "back to the start".
        sx = left + begin[0] * cell + (cell - (box if isinstance(box, int) else room)) // 2
        sy = top + begin[1] * cell + (cell - (box if isinstance(box, int) else room)) // 2
        old_start = source.rect_start(tree, player)
        self._move_start(edit, player, (sx, sy), old_start)
        for first, last in self.scene.rules.values():
            for index in range(first, last + 1):
                line = self.lines[index]
                if re.search(r"\b\w+\.respawn\(\)", line) and "score" in "\n".join(
                        self.lines[first:last + 1]):
                    # Collected in a maze: the player starts again; the goal stays put.
                    edit.replace(index, index, [re.sub(
                        r"\b\w+\.respawn\(\)", f"{player}.topleft = ({sx}, {sy})", line)])
        self._block(edit, self.name, player, start_moved=True)
        result = self._report("changed" if entry is not None else "added", look, None,
                              keywords)
        result["layout"] = (f"a maze {columns} x {rows} squares of {cell} pixels, seen from "
                            f"above, written as MAZE at the top of the game -- # is a wall")
        result["touch"] = "solid: the player cannot walk through the walls"
        result["player"] = f"starts at the maze's start, top left, at ({sx}, {sy})"
        result["end"] = [left + finish[0] * cell, top + finish[1] * cell]
        result["next"] = ("put what they are looking for at the maze's end: game_object with "
                          "its name and at \"maze end\"")
        result.pop("placed", None)
        return edit.text(), result

    def _move_start(self, edit, player: str, spot: tuple[int, int], old: str | None) -> None:
        """The player's ``pygame.Rect(...)`` starts at ``spot`` -- and the rules that send it
        back to where it started send it there."""
        for node in self.scene.tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == player for t in node.targets) and \
                    isinstance(node.value, ast.Call) and len(node.value.args) == 4:
                rest = ", ".join(ast.unparse(a) for a in node.value.args[2:])
                func = ast.unparse(node.value.func)
                edit.replace(node.lineno - 1, node.end_lineno - 1,
                             [f"{player} = {func}({spot[0]}, {spot[1]}, {rest})"])
                break
        if not old:
            return
        for first, last in self.scene.rules.values():
            for index in range(first, last + 1):
                if old in self.lines[index] and f"{player}.topleft" in self.lines[index]:
                    edit.replace(index, index, [self.lines[index].replace(
                        old, f"({spot[0]}, {spot[1]})")])
        self.notes.append(f"the player starts at the maze's start now, at ({spot[0]}, "
                          f"{spot[1]})")

    def _block(self, edit, name: str, player: str | None, *, start_moved=False) -> None:
        """``touch: block`` -- the thing is solid: walking into it puts the player back
        where it was before it moved. Written round the game's own movement code."""
        if player is None:
            self.notes.append("there is no player the arrow keys move, so nothing walks into "
                              "it")
            return
        arrows = self.facts.get("arrow_ifs")
        if not arrows:
            self.notes.append("the game moves the player some other way, so walking into it "
                              "was left to the game -- edit_file changes that")
            return
        existing = self.scene.rules.get(name)
        if existing:
            edit.drop(*existing)
        indent = self.facts.get("indent")
        was = f"{player}_was"
        loop = source.main_loop(self.scene.tree)
        holds = [stmt for stmt in loop.body if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == was for t in stmt.targets)]
        if not holds:
            edit.insert(min(line for line, _ in arrows),
                        [f"{indent}{was} = {player}.topleft  # where it was before it moves"])
        lines = [line for line, _ in arrows]
        after = self.facts.get("clamp")
        if after is None:
            last = max(lines)
            node = next((n for n in loop.body if n.lineno - 1 == last), None)
            after = (node.end_lineno - 1) if node is not None else last
        edit.insert(after + 1, [
            f"{indent}{source.RULE_MARK}{name.replace('_', ' ')} are solid: walking into "
            f"them puts the player back.",
            f"{indent}if {self.var}.touching({player}, {quoted(name)}):",
            f"{indent}    {player}.topleft = {was}"])

    def _on_the_paths(self, spots, size):
        """In a maze, a thing given a place goes on the open square nearest it, at a
        square's size -- never inside a wall. Measured on the Maze_test01 replay: the 8B
        put ten coins on a diagonal through the walls, and the monster at a picture's
        full size, over them."""
        _entry, grid, cell, (left, top) = source.maze_layout(self.scene)
        squares = sorted(maze.open_squares(grid))
        room = cell - 6
        if max(size) > room:
            scale = room / max(size)
            size = (max(4, round(size[0] * scale)), max(4, round(size[1] * scale)))
        many = isinstance(spots, (list, tuple)) and spots and isinstance(spots[0], (list, tuple))
        wanted = [_pair(s) for s in spots] if many else [_pair(spots)]
        placed, used = [], set()
        for spot in wanted:
            if spot is None:
                continue
            free = [sq for sq in squares if sq not in used] or squares
            square = min(free, key=lambda sq: (left + sq[0] * cell + cell / 2 - spot[0]) ** 2
                         + (top + sq[1] * cell + cell / 2 - spot[1]) ** 2)
            used.add(square)
            placed.append([left + square[0] * cell + (cell - size[0]) // 2,
                           top + square[1] * cell + (cell - size[1]) // 2])
        if not placed:
            return spots, size
        self.notes.append("it is on the maze's paths, a square's size")
        return (placed if many else placed[0]), size

    def _drop_hold(self, edit, name: str) -> None:
        """A solid thing's rule gone: its "where the player was" line goes too, once no
        other solid thing needs it."""
        player = self.facts.get("player")
        loop = source.main_loop(self.scene.tree) if player else None
        if loop is None:
            return
        others = [rule for key, rule in self.scene.rules.items() if key != name and
                  "_was" in "\n".join(self.lines[rule[0]:rule[1] + 1])]
        if others:
            return
        for stmt in loop.body:
            if isinstance(stmt, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == f"{player}_was" for t in stmt.targets):
                edit.drop(stmt.lineno - 1, stmt.end_lineno - 1)

    def _maze_spot(self, which: str, size: tuple[int, int]):
        """("maze end" or "maze start") -> ((x, y), size) inside that square of the scene's
        maze, the size made to fit it -- or None."""
        layout = source.maze_layout(self.scene)
        if layout is None:
            self.notes.append(f"there is no maze in the scene for {which!r}, so it was placed "
                              f"without it")
            return None
        _entry, grid, cell, (left, top) = layout
        square = maze.start(grid) if "start" in which.lower() else maze.end(grid)
        if square is None:
            return None
        room = cell - 6
        if max(size) > room:
            scale = room / max(size)
            size = (max(4, round(size[0] * scale)), max(4, round(size[1] * scale)))
        x = left + square[0] * cell + (cell - size[0]) // 2
        y = top + square[1] * cell + (cell - size[1]) // 2
        self.notes.append(f"it is at the maze's {'start' if 'start' in which else 'end'}")
        return (x, y), size

    # -- a list the game already draws ---------------------------------------------

    def _wants_place(self) -> bool:
        return any(self.args.get(k) not in (None, "", []) for k in ("at", "on")) or \
            self.args.get("moves") not in (None, "", "still")

    def _recipe_motion(self, items: str):
        """(how a recipe's list moves and where its code is, its prefix) -- or (None, None)
        when the list is not a recipe's, its code changed, or the scene cannot move it
        that way."""
        from opennest.fastpath.kinds import games

        for prefix, thing in (self.facts.get("things") or {}).items():
            if thing.get("list") != items:
                continue
            try:
                found = games.motion_of(self.facts, prefix)
            except Exception:   # noqa: BLE001 - a recipe's shape changed: just not movable
                found = None
            if found is not None and found[0] in ("drift", "fall", "rise"):
                return found, prefix
        return None, None

    def _take_over_list(self, items: str, prefix: str | None) -> tuple[str, dict]:
        tree = self.scene.tree
        edit = source.Edit(self.text)
        look = self.look(required=False)
        if look is None and prefix is not None and not self._wants_place() and \
                self._numbers_only():
            # "Make the asteroids faster": a recipe's things have their own constants, and
            # changing them needs no scene at all.
            return self._constants_only(items, prefix, edit)
        if look is None:
            look = self.look(required=True)
        drawing = source.drawing_loop(tree, items)
        # A list nothing draws yet -- the Fast Path's things before their look is given,
        # or rects Gary made with edit_file -- is simply drawn by the scene from now on.
        undrawn = drawing is None and not source.draws(tree, items)
        if not undrawn and (drawing is None or source.other_drawing_of(tree, items, drawing)):
            raise Refused(f"{items} are drawn by code that does other things as well, so "
                          f"Open Nest can't safely hand their drawing to the scene. Nothing "
                          f"was changed; edit_file can change that code.", "drawn_elsewhere")
        wants_place = self._wants_place()
        motion = self._recipe_motion(items)[0] if prefix is not None else None
        name = self.name
        if wants_place and motion is not None:
            return self._hand_over(items, prefix, motion, look, drawing, edit)
        if wants_place:
            self.notes.append(f"where {items} are and how they move is the game's own code, "
                              f"so only their look changed -- edit_file changes the rest")
        self._set_constants(edit, prefix)
        if drawing is not None:
            edit.drop(*drawing)
        if prefix:
            self.redundant = (f"{prefix}_COLOUR", f"{prefix}_DETAIL")
        scale = self._list_scale(items, look, prefix=prefix)
        keywords = [("rects", items)]
        if scale != 1.0:
            keywords.append(("scale", _num(scale)))
        keywords.append(("layer", quoted(self._layer(None, "things"))))
        statement = source.call_text(self.var, name, look.code(keep_shape=_shape_of(
            look, _pair(self.args.get("size")))), keywords, None)
        edit.insert(self._position(after_names=(items,), layer="things"), statement)
        self._rule(edit, name, items=items)
        result = self._report("added" if undrawn else "changed", look, None, keywords)
        result["kept"] = f"how {items} move and what happens when they are touched are unchanged"
        if drawing is not None:
            result["replaced"] = f"the loop that drew {items} before"
        self._said_of_game_code(items, result)
        return edit.text(), result

    def _constants_only(self, items: str, prefix: str, edit) -> tuple[str, dict]:
        self._set_constants(edit, prefix)
        if not self.notes:
            raise Refused(f"{items} are already like that, so nothing was changed.",
                          "no_change")
        return edit.text(), {"ok": True, "object": self.name, "action": "changed",
                             "kept": f"how {items} look and what touching them does"}

    def _numbers_only(self) -> bool:
        """Only ``count`` or ``speed`` given -- nothing about how it looks or where."""
        return not any(self.args.get(key) for key in (
            "picture", "drawing", "shapes", "color", "colour", "frames", "size", "layer",
            "touch")) and any(isinstance(self.args.get(key), (int, float))
                              for key in ("count", "speed"))

    def _prefix_of(self, items: str | None) -> str | None:
        """The recipe prefix (``ASTEROID``) whose list is ``items``, if a recipe made it."""
        for prefix, thing in (self.facts.get("things") or {}).items():
            if items and thing.get("list") == items:
                return prefix
        return None

    def _said_of_game_code(self, items: str, result: dict) -> None:
        """What the result says about the game's own rects is what the game's code does.

        The scene only draws them, so "it stays where it is" and "nothing happens when it
        is touched" -- the defaults for a thing the scene makes -- would be false about a
        recipe's asteroids that drift and send the player back.
        """
        loop = source.main_loop(self.scene.tree)
        moved = False
        for stmt in loop.body if loop else ():
            for node in ast.walk(stmt):
                if not (isinstance(node, ast.For) and source._mentions(node.iter, {items})):
                    continue
                each = {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
                moved = moved or any(
                    isinstance(sub, (ast.Assign, ast.AugAssign)) and any(
                        isinstance(t, ast.Attribute) and _dotted_name(t.value) in each
                        for t in (sub.targets if isinstance(sub, ast.Assign) else [sub.target]))
                    for sub in ast.walk(node))
        if "moves" not in result or result["moves"] == "it stays where it is":
            result["moves"] = "the game's own code moves them" if moved else \
                "they stay where they are"
        if self.args.get("touch") not in ("avoid", "collect", "nothing"):
            touched = self._touched_by_code(items)
            if touched == "collect":
                result["touch"] = "touching one scores a point -- the game's own code"
            elif touched == "avoid":
                result["touch"] = "touching one sends the player back -- the game's own code"

    def _touched_by_code(self, items: str) -> str:
        """"avoid", "collect", or "" -- what the game's own code does when the player
        touches one of ``items``."""
        loop = source.main_loop(self.scene.tree)
        player = self.facts.get("player")
        for stmt in loop.body if loop else ():
            if not source._mentions(stmt, {items}):
                continue
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr in ("collidelist", "colliderect", "touching", "touched")
                   and (_dotted_name(n.func.value) == player
                        or n.func.attr in ("touching", "touched"))
                   for n in ast.walk(stmt)):
                return "collect" if "score" in ast.unparse(stmt) else "avoid"
        return ""

    # -- colour -----------------------------------------------------------------------

    def _colour_given(self) -> bool:
        return self.args.get("color", self.args.get("colour")) not in (None, "")

    def _layer_given(self) -> bool:
        return isinstance(self.args.get("layer"), str) and bool(self.args["layer"].strip())

    def _fill(self):
        return looks.colour(self.args.get("color", self.args.get("colour")), self.notes,
                            constants=self.colour_constants)

    def _recolour(self, code: str, edit) -> str | None:
        """``code`` -- a look as the game writes it -- in the colour Gary gave; None when
        it has no colour of its own to change (a picture keeps its own).

        Everything else about the look is kept as written: a sign's words, a drawing's
        size, the other colours of a drawing made of shapes. A ready-made drawing or a
        plain box changes its colour; shapes change their main colour -- the first
        shape's -- wherever it is used. A colour that is one of the game's constants and
        colours nothing else is changed at the top, so that number keeps deciding it.
        """
        fill = self._fill()
        try:
            call = ast.parse(code, mode="eval").body
        except SyntaxError:
            return None
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            return None
        if call.func.id in ("Picture", "Animation"):
            if any(self.args.get(key) not in (None, "", [], 0) for key in (
                    "size", "at", "on", "count", "moves", "touch", "layer", "speed")):
                self.notes.append("it is a picture, which keeps its own colours")
                return None
            raise Refused(f"{self.name.replace('_', ' ')} is a picture, which keeps its own "
                          f"colours -- a drawing or shapes can be any colour. Nothing was "
                          f"changed.", "keeps_its_colours")
        others = False
        if call.func.id == "Drawing":
            found = [_shape_colour(s) for s in (call.args[1].elts if len(call.args) > 1 and
                                                isinstance(call.args[1], ast.List) else [])]
            found = [n for n in found if n is not None]
            if not found:
                return None
            main = ast.unparse(found[0])
            targets = [n for n in found if ast.unparse(n) == main]
            others = len(targets) < len(found)
        else:
            node = call.args[0] if call.args else next(
                (k.value for k in call.keywords if k.arg == "fill"), None)
            if node is None:       # Vehicle() -- its own default colour until now
                at = _offset(code, call.func.end_lineno, call.func.end_col_offset) + 1
                rest = ", " if call.args or call.keywords else ""
                return code[:at] + looks.colour_code(fill) + rest + code[at:]
            targets = [node]
        if others:
            self.notes.append("its main colour -- the first shape's -- changed; its other "
                              "colours were kept")
        names = [n.id for n in targets if isinstance(n, ast.Name)]
        const = (self.facts.get("constants") or {}).get(names[0]) \
            if len(names) == len(targets) and len(set(names)) == 1 else None
        wanted = looks.rgb(fill)
        if const is not None and wanted is not None and const.name in self.colour_constants \
                and source.references(self.scene.tree, const.name) == sum(
                    1 for n in ast.walk(call) if isinstance(n, ast.Name) and n.id == const.name):
            if tuple(const.value) != tuple(wanted):
                line = self.lines[const.line]
                edit.replace(const.line, const.line, [
                    line[:const.start] + f"({wanted[0]}, {wanted[1]}, {wanted[2]})"
                    + line[const.end:]])
                self.notes.append(f"{const.name} is its colour, so {const.name} changed")
            return code
        spans = sorted(((_offset(code, n.lineno, n.col_offset),
                         _offset(code, n.end_lineno, n.end_col_offset)) for n in targets),
                       reverse=True)
        for start, end in spans:
            code = code[:start] + looks.colour_code(fill) + code[end:]
        return code

    def _hand_over(self, items, prefix, motion, look, drawing, edit, *,
                   entry: source.Entry | None = None,
                   look_code: str | None = None) -> tuple[str, dict]:
        """A recipe's things, moved by the scene from now on, with their rules kept.
        ``drawing`` is the loop that drew them, or ``entry`` the scene line that did."""
        from opennest.fastpath.kinds import games

        kind, places = motion
        self.redundant = (f"{prefix}_COLOUR", f"{prefix}_DETAIL")
        for (first, text) in places:
            edit.drop(first, first + text.count("\n"))
        if drawing is not None:
            edit.drop(*drawing)
        if entry is not None:
            edit.drop(entry.first, entry.last)
        constants = self.facts.get("constants") or {}
        speed = f"{prefix}_SPEED" if f"{prefix}_SPEED" in constants else None
        count = f"{prefix}_COUNT" if f"{prefix}_COUNT" in constants else None
        self._set_constants(edit, prefix)
        direction = self.args.get("moves")
        default = {"drift": "left", "fall": "down", "rise": "up"}[kind]
        direction = direction if direction in DIRECTIONS and direction != "bounce" else default
        dx, dy = DIRECTIONS[direction]
        if speed:
            moves = f"({_signed(dx, speed)}, {_signed(dy, speed)})"
        else:
            moves = f"({dx * 3}, {dy * 3})"
        keywords = self._placement(look, count_code=count)
        keywords.append(("moves", moves))
        keywords.append(("layer", quoted(self._layer(None, "things"))))
        statement = source.call_text(self.var, self.name, look_code or look.code(), keywords,
                                     items)
        edit.insert(self._position(after_names=(), layer="things",
                                   on=_on_of(keywords)), statement)
        # The recipe's "collect it" rule sent a collected coin anywhere on the screen;
        # the scene's respawn keeps it on its road.
        thing = games._existing(self.facts, prefix, kind)
        collect = games._touch_pieces(thing, self.facts, "collect")
        indent = self.facts.get("indent")
        block = "\n".join(indent + line for line in collect)
        framed = "\n" + self.text + "\n"
        if collect and framed.count("\n" + block + "\n") == 1:
            start = framed[:framed.index("\n" + block + "\n")].count("\n")
            one = thing.item
            touch_call = "touched" if counts_touches(self.project) else "touching"
            edit.replace(start, start + len(collect) - 1, [
                f"{indent}for {one} in {self.var}.{touch_call}({self.facts.get('player')}, "
                f"{quoted(self.name)}):", f"{indent}    score += 1",
                f"{indent}    {one}.respawn()"])
        self._rule(edit, self.name)
        result = self._report("changed", look, None, keywords)
        result["kept"] = f"what happens when {items} are touched is unchanged"
        result["now"] = f"the scene moves {items} instead of the loop"
        return edit.text(), result

    def _set_constants(self, edit, prefix) -> None:
        """``count`` and ``speed`` for a recipe's things are its own constants."""
        if prefix is None:
            return
        constants = self.facts.get("constants") or {}
        for key, suffix in (("count", "COUNT"), ("speed", "SPEED")):
            value = self.args.get(key)
            const = constants.get(f"{prefix}_{suffix}")
            if not isinstance(value, (int, float)) or const is None or value <= 0:
                continue
            new = max(1, min(60 if key == "count" else 20, round(value)))
            if new != const.value:
                line = self.lines[const.line]
                edit.replace(const.line, const.line,
                             [line[:const.start] + str(new) + line[const.end:]])
                self.notes.append(f"{const.name} went from {const.value} to {new}")

    def _list_scale(self, items, look, prefix=None) -> float:
        """How much bigger than each rect the look is drawn, to be ``size``."""
        # A picture's box is its file's own pixels (the owner's monster: 1278 across), not a
        # size anyone asked for: given none, it fits the game's own rect (scale 1). Measured
        # on the game builds (SPIKES.md section 33H): put on a written game's 30-pixel
        # enemies, it was drawn at 42.6 times their size.
        wanted = _pair(self.args.get("size")) or (
            look.box if look and look.kind not in ("shapes", "picture") else None)
        if look and look.kind == "drawing" and not wanted:
            wanted = _READY_SIZES.get(look.drawing)
        constants = self.facts.get("constants") or {}
        const = constants.get(f"{prefix}_SIZE") if prefix else None
        box = const.value if const is not None and isinstance(const.value, int) else None
        if not wanted or not box:
            return 1.0
        return round(max(wanted) / box, 2)

    # -- something new ----------------------------------------------------------------

    def _sky_from_background(self, look: Look, edit) -> str | None:
        """A sky drawn in the game's BACKGROUND colour, with the colour Gary gave written
        into that constant -- or None when the game has no such constant.

        Measured with both models (SPIKES.md section 28E): asked for more colour, each
        changed BACKGROUND and said the sky had changed, while the sky covered the fill it
        coloured. With the sky drawn in BACKGROUND, changing it -- by Gary, the Fast Path's
        background recipe, or by hand -- changes what is on screen.
        """
        name = self.facts.get("background")
        const = (self.facts.get("constants") or {}).get(name) if name else None
        if const is None or look.kind != "drawing" or look.drawing != "sky":
            return None
        wanted = looks.rgb(look.fill) if look.fill is not None else None
        if wanted is None and self.name not in self.scene.entries:
            wanted = looks.palette().get("skyblue")      # a day sky, not the starter's night
        if wanted is not None and tuple(wanted) != tuple(const.value):
            line = self.lines[const.line]
            edit.replace(const.line, const.line, [
                line[:const.start] + f"({wanted[0]}, {wanted[1]}, {wanted[2]})"
                + line[const.end:]])
            self.notes.append(f"{name} is the sky's colour now: changing it changes the sky")
        return f"Sky({name})"

    def _new(self) -> tuple[str, dict]:
        look = self.look(required=True)
        edit = source.Edit(self.text)
        sky = self._sky_from_background(look, edit)
        keywords = self._placement(look)
        layer = self._layer(None, self._default_layer(look))
        motion = self._motion(look)
        if motion:
            keywords += motion
        keywords.append(("layer", quoted(layer)))
        target = self.name if self.name.isidentifier() and self.name not in \
            source.names_used(self.scene.tree) and not keyword_like(self.name) else None
        statement = source.call_text(self.var, self.name, sky or look.code(), keywords,
                                     target)
        backdrop = look.kind == "drawing" and look.drawing == "sky"
        edit.insert(self._position(after_names=(), layer=layer, on=_on_of(keywords),
                                   first=backdrop), statement)
        self._rule(edit, self.name)
        result = self._report("added", look, None, keywords)
        # Measured on the Luna walk (SPIKES.md section 28K): "background buildings" added to
        # the scenery after the town and the trees were drawn over both -- the trees
        # vanished -- and the reply said they were "behind the town". Within a layer,
        # later is in front; the result says so, and which layer is behind.
        over = [entry.name for entry in sorted(self.scene.entries.values(),
                                               key=lambda e: e.first)
                if entry.layer == layer and entry.look_class != "Sky" and not backdrop]
        if over:
            behind = LAYERS[LAYERS.index(layer) - 1] if LAYERS.index(layer) > 0 else ""
            result["drawn_over"] = (
                f"{', '.join(over[:6])}: things in the {layer} layer are drawn in the order "
                f"they were added, so this one is in front of them wherever they overlap"
                + (f" -- layer {behind} puts it behind them" if behind else ""))
        if look.kind in ("picture", "pictures", "animation") and \
                "player" not in self.scene.entries \
                and self.facts.get("player"):
            result["player"] = ("the player -- the one the arrow keys move -- still looks the "
                                "way it did; this is a new thing that does not move with the "
                                "keys. If it should be the player, use the name player")
        if look.kind == "drawing" and look.drawing in BANDS:
            # Things placed before there was anything to stand on are not moved -- where
            # they go is Gary's to decide -- but he is told they are not on it.
            loose = [entry.name for entry in self.scene.entries.values()
                     if entry.look_class in ("Vehicle", "Building", "House", "Tree", "Sign")
                     and "on" not in entry.keywords]
            if loose:
                result["not_on_it"] = (f"standing on nothing yet: {', '.join(loose)}. "
                                       f"game_object with on: \"{self.name}\" puts a thing on "
                                       f"the {self.name}")
        return edit.text(), result

    def _default_layer(self, look: Look) -> str:
        drawing = look.drawing if look.kind == "drawing" else \
            looks.infer_drawing(self.name) if look.kind in ("picture", "pictures") else ""
        if drawing and look.kind != "drawing" and not self._in_front():
            # The child's tree pictures are scenery, as the tree drawing is.
            look = Look("drawing", drawing=drawing)
        if look.kind == "drawing":
            if look.drawing in ("sky", "cloud"):
                return "background"
            if look.drawing in ("road", "ground", "building", "house", "tree", "sign",
                                "platform"):
                return "scenery"
        return "things"

    def _layer(self, entry, default: str) -> str:
        asked = self.args.get("layer")
        if isinstance(asked, str) and asked.strip().lower() in LAYERS:
            asked = asked.strip().lower()
            look = self.args.get("drawing")
            if look == "sky" and asked != "background":
                self.notes.append("a sky is always the very back, so it is in background")
                return "background"
            if asked in ("background", "scenery") and self._in_front():
                # Measured on the final 8B walk (SPIKES.md section 28E): cars to dodge put
                # in scenery, and buildings added after them in the same layer covered
                # them. Something the player can touch, or a vehicle on the move, is in
                # front of the scenery.
                self.notes.append(f"it is something the player meets, so it is drawn in "
                                  f"front of the {asked}, in things")
                return "things"
            return asked
        if asked:
            self.notes.append(f"there is no layer {asked!r}; the layers are "
                              f"{', '.join(LAYERS)}")
        if entry is not None:
            return entry.layer
        return default

    def _in_front(self) -> bool:
        """A thing the player can touch, or a vehicle that moves by itself."""
        # (A thing to shoot may hide behind the scenery -- the owner's test04: "monsters
        # hiding behind trees" -- so only a thing the player bumps into is pulled forward.)
        touch = self.args.get("touch") in ("avoid", "collect")
        entry = self.scene.entries.get(self.name)
        vehicle = self.args.get("drawing") == "vehicle" or (
            entry is not None and entry.look_class == "Vehicle")
        moving = self.args.get("moves") not in (None, "", "still") or (
            entry is not None and entry.keywords.get("moves") not in (None, "(0, 0)"))
        ruled = entry is not None and self.name in self.scene.rules
        return touch or ruled or (vehicle and moving)

    def _placement(self, look: Look, *, count_code: str | None = None) -> list:
        """size, at, on and count for a thing the scene makes, with sensible defaults."""
        args = self.args
        keywords: list[tuple[str, str]] = []
        drawing = look.drawing if look.kind == "drawing" else ""
        size = _pair(args.get("size"))
        if drawing == "sky":
            if args.get("size") or args.get("at"):
                self.notes.append("a sky fills the whole screen, behind everything")
            keywords.append(("size", f"({self.width}, {self.height})"))
            keywords.append(("at", "(0, 0)"))
            return keywords
        if drawing in BANDS:
            height = size[1] if size else _READY_SIZES[drawing][1]
            height = max(8, min(self.height // 2, height))
            if size and size[0] != self.width:
                self.notes.append(f"a {drawing} goes all the way across the screen")
            keywords.append(("size", f"({self.width}, {height})"))
            spot = _pair(args.get("at"))
            if spot and spot[1] < self.height // 3:
                # A road along the top of the window: measured on the test04 replay, the 4B
                # gave every thing at [0, 0], meaning nowhere in particular, and then said
                # "the road is a green strip at the bottom".
                self.notes.append(f"a {drawing} goes along the bottom, where things stand on "
                                  f"it")
                spot = None
            y = spot[1] if spot else self.height - height
            keywords.append(("at", f"(0, {max(0, min(self.height - 8, y))})"))
            return keywords
        if not size:
            size = _READY_SIZES.get(drawing) or _natural(look, self.width, self.height)
        else:
            size = self._sensible(size, look, drawing)
        size = (max(4, min(self.width, size[0])), max(4, min(self.height, size[1])))
        size = self._picture_shaped(size, look)
        spots = args.get("at")
        if isinstance(spots, str):
            # "maze end": where the goal of a maze goes (``_maze``'s result says so).
            placed = self._maze_spot(spots, size)
            spots, size = (list(placed[0]), placed[1]) if placed else (None, size)
        elif spots and drawing not in ("sky", "cloud") and \
                source.maze_layout(self.scene) is not None:
            spots, size = self._on_the_paths(spots, size)
        keywords.append(("size", f"({size[0]}, {size[1]})"))
        on = self._on_target()
        standing = drawing in STANDING or (look.kind in ("picture", "pictures") and
                                           looks.infer_drawing(self.name) in STANDING)
        if isinstance(spots, (list, tuple)) and spots and all(
                _pair(s) for s in spots) and isinstance(spots[0], (list, tuple)):
            places = [_clamp_spot(_pair(s), size, self.width, self.height) for s in spots][:60]
            keywords.append(("at", "[" + ", ".join(f"({x}, {y})" for x, y in places) + "]"))
        else:
            spot = _pair(spots)
            if spot and standing and on is None and (spot[1] <= 0 or self.no_ground) and \
                    drawing != "sign":
                # Measured on the test04 replays: both models gave trees "at": [0, 0],
                # meaning nowhere in particular -- and the trees stood along the top of
                # the window. A thing that stands stands on the ground, or the screen's
                # bottom when there is no ground.
                on = self._ground()
                y = spot[1] if on else self.height - size[1]
                self.notes.append(f"it stands, so it is on the {on}" if on else
                                  "it stands, so it is along the bottom of the screen")
                spot = (spot[0], y)
                x, y = _clamp_spot(spot, size, self.width, self.height)
                keywords.append(("at", f"({x}, {y})"))
            elif spot:
                x, y = _clamp_spot(spot, size, self.width, self.height)
                keywords.append(("at", f"({x}, {y})"))
                if on is None and standing:
                    on = self._snap(y + size[1])
            elif drawing == "cloud":
                keywords.append(("at", f"(0, {self.height // 12})"))
            elif not on:
                count = args.get("count")
                if standing:
                    # Trees or buildings with no ground to stand on stand on the bottom of
                    # the screen, not across its middle (the 8B's forest, test04 replay).
                    keywords.append(("at", f"(0, {self.height - size[1]})"))
                elif isinstance(count, (int, float)) and count > 1:
                    keywords.append(("at", f"(0, {(self.height - size[1]) // 2})"))
        if on:
            keywords.append(("on", quoted(on)))
        count = args.get("count")
        if count_code:
            keywords.append(("count", count_code))
        elif isinstance(count, (int, float)) and count > 1 and not (
                isinstance(spots, (list, tuple)) and spots and isinstance(spots[0],
                                                                          (list, tuple))):
            keywords.append(("count", str(max(2, min(60, round(count))))))
            if (drawing or (looks.infer_drawing(self.name) if look.kind in (
                    "picture", "pictures") else "")) in ("building", "house", "tree", "cloud"):
                keywords.append(("vary", "0.25"))
        return keywords

    def _sensible(self, size: tuple[int, int], look: Look, drawing: str) -> tuple[int, int]:
        """A size Gary gave, unless it is the whole screen for one thing or a row too wide
        for the screen -- then the size each one should be, said in the notes.

        Measured on the owner's test04 replay: "trees", count 5, size [640, 480] -- the
        4B gave the screen's size as the area to fill -- drew five trees each as big as
        the window, and nothing else in the game could be seen. A sky or a band is the
        whole width by rule and never comes here."""
        name = self.name.replace("_", " ")
        if size[0] >= self.width * 0.9 and size[1] >= self.height * 0.6:
            own = _READY_SIZES.get(drawing) or _natural(look, self.width, self.height)
            self.notes.append(f"{size[0]}x{size[1]} is the whole screen -- {name} that big "
                              f"would cover everything -- so each is {own[0]}x{own[1]}")
            return own
        count = self.args.get("count")
        if isinstance(count, (int, float)) and count > 1 and size[0] * count > self.width * 1.3:
            scale = self.width / (size[0] * count)
            own = (max(8, round(size[0] * scale)), max(8, round(size[1] * scale)))
            self.notes.append(f"{round(count)} of them {size[0]} wide would not fit across "
                              f"the screen, so each is {own[0]}x{own[1]}")
            return own
        return size

    def _picture_shaped(self, size: tuple[int, int], look: Look | None) -> tuple[int, int]:
        """A picture's box, the shape of the picture: the biggest that fits in ``size``.

        Measured on the owner's test04: the monster kept a 140x470 box from the shapes
        it had been, its nearly square picture was drawn in the middle of that box, and
        the box stood on the road -- so the monster hung in the sky, and what bumped into
        things was a tall invisible column. What is seen is what stands and what touches."""
        if look is None or look.kind not in ("picture", "pictures") or not look.box:
            return size
        width, height = look.box
        scale = min(size[0] / max(1, width), size[1] / max(1, height))
        shaped = (max(4, round(width * scale)), max(4, round(height * scale)))
        if abs(shaped[0] - size[0]) > 2 or abs(shaped[1] - size[1]) > 2:
            self.notes.append(f"the picture is {width}x{height}, so its box is "
                              f"{shaped[0]}x{shaped[1]}, the picture's own shape -- what "
                              f"stands and what is touched is what is seen")
            return shaped
        return size

    #: How far above a road a standing thing's bottom can be and still be meant to be
    #: on it. Both models put cars 40-80 pixels above the road they asked for (SPIKES.md
    #: section 28E); a sign meant to float higher than that stays where it was put.
    SNAP = 90

    def _snap(self, bottom: int) -> str | None:
        """The road or ground a standing thing placed just above -- or on, or sunk into --
        belongs on."""
        for entry in self.scene.entries.values():
            spot, span = entry.literals.get("at"), entry.literals.get("size")
            if entry.look_class not in ("Road", "Ground") or not (
                    isinstance(spot, tuple) and isinstance(span, tuple)):
                continue
            # Just above it, on it, or past its lower edge -- the final 4B walk's tree stood
            # 10 pixels below a 20-pixel road, and the test04 replay's 8B planted a tree's
            # top on the road, its trunk below the bottom of the screen.
            if spot[1] - self.SNAP <= bottom:
                self.notes.append(f"it was put just above the {entry.name}, so it stands on "
                                  f"the {entry.name}")
                return entry.name
        return None

    def _ground(self) -> str | None:
        """The road or ground in the scene, if there is one."""
        for ground in ("road", "ground", "street", "grass"):
            if ground in self.scene.entries and ground != self.name:
                return ground
        for entry in self.scene.entries.values():
            if entry.look_class in ("Road", "Ground") and entry.name != self.name:
                return entry.name
        return None

    def _on_target(self) -> str | None:
        """The thing this one stands on: the one Gary named, or -- for a drawing that
        stands on the ground, placed nowhere in particular -- the road or ground."""
        asked = self.args.get("on")
        if isinstance(asked, str) and asked.strip():
            for candidate in _forms(_clean_name(asked)):
                if candidate in self.scene.entries and candidate != self.name:
                    return candidate
            ground = self._ground()
            if ground and _clean_name(asked) in ("ground", "road", "grass", "floor", "street"):
                self.notes.append(f"there is no {asked}, so it stands on the {ground}")
                return ground
            self.notes.append(f"there is nothing called {asked!r} in the scene to stand on, "
                              f"so it was placed without it")
            self.no_ground = _clean_name(asked) in ("ground", "road", "grass", "floor",
                                                    "street")
            return None
        drawing = self.args.get("drawing") or looks.infer_drawing(self.name)
        if drawing in STANDING and not self.args.get("at"):
            for ground in ("road", "ground", "street", "grass"):
                if ground in self.scene.entries and ground != self.name:
                    return ground
        return None

    def _motion(self, look: Look) -> list:
        moves = self.args.get("moves")
        if moves not in DIRECTIONS:
            if moves not in (None, "", "still"):
                self.notes.append(f"it can move left, right, up, down or bounce, not "
                                  f"{moves!r}, so it stays still")
            return []
        speed = self.args.get("speed")
        default = 1 if (look.kind == "drawing" and look.drawing == "cloud") else 3
        speed = max(1, min(20, round(speed))) if isinstance(speed, (int, float)) and speed \
            else default
        dx, dy = DIRECTIONS[moves]
        found = [("moves", f"({dx * speed}, {dy * speed})")]
        if moves == "bounce":
            found.append(("edges", quoted("bounce")))
        return found

    def _keywords(self, entry: source.Entry, look: Look | None) -> list:
        """An existing thing's keywords, with only what Gary gave now changed."""
        args = self.args
        current = dict(entry.keywords)
        if "grid" in current:
            # A maze's walls: their layout is the maze. Measured on the Maze_test01 replay,
            # the 4B sent the walls a size and "at": "maze end" copied from a result, and
            # the maze became one block at its own end. A look, a layer or what touching
            # them does can change; where they are is layout maze's.
            if any(args.get(key) not in (None, "", [], 0) for key in ("size", "at", "count")):
                self.notes.append("the walls are laid out as the maze, so their places and "
                                  "size stayed -- layout maze makes a new one")
            kept = [(key, current[key]) for key in ("grid", "cell", "at", "hitbox")
                    if key in current]
            return kept + [("layer", quoted(self._layer(entry, entry.layer)))]
        probe = look or _look_of(entry)
        fresh = dict(self._placement(probe))
        given = {key for key in ("size", "at", "on", "count") if args.get(key) not in
                 (None, "", [], 0)}
        if isinstance(args.get("at"), str) or ("at" in given and "grid" not in current and
                                               source.maze_layout(self.scene) is not None):
            given.add("size")              # a maze's square decides how big it can be
        # A sky and a band are placed by rule, whatever they were given before.
        forced = probe.kind == "drawing" and probe.drawing in ("sky",) + BANDS
        merged: list[tuple[str, str]] = []
        for key in ("size", "at", "on", "count", "vary"):
            asked = key in given or (key == "vary" and "count" in given) or (
                forced and key in ("size", "at"))
            if asked:
                if key in fresh:
                    merged.append((key, fresh[key]))
            elif key == "on" and "at" in given:
                # A new place replaces what it stood on -- unless the new place is itself
                # just above a road, where it stands on the road again (``_snap``).
                if "on" in fresh:
                    merged.append((key, fresh[key]))
            elif key == "at" and "count" in given and isinstance(entry.literals.get("at"), list):
                # One corner each made as many as there were corners; a count asked for now
                # is a row of that many instead.
                continue
            elif key in current:
                merged.append((key, current[key]))
        if look is not None and look.kind in ("picture", "pictures") and "size" not in given:
            # A new picture keeps a picture's box only as the room it has, shaped to the
            # new picture. A box a drawing had says nothing about a picture -- the owner's
            # test04 monster kept its shapes' 140x470 and hung in the sky; a thin drawn
            # tree's 20x100 made a tree picture 20x27 -- so a picture replacing a drawing
            # is drawn at a picture's own size.
            for index, (key, code) in enumerate(merged):
                if key != "size":
                    continue
                kept = _pair(_value(code)) if not isinstance(_value(code), str) else None
                if not kept:
                    continue
                if entry.look_class == "Picture":
                    shaped = self._picture_shaped(self._sensible(kept, look, ""), look)
                else:
                    shaped = _natural(look, self.width, self.height)
                    self.notes.append(f"it was a drawing before, so the picture is drawn at "
                                      f"its own size, {shaped[0]}x{shaped[1]}")
                merged[index] = ("size", f"({shaped[0]}, {shaped[1]})")
        if args.get("moves") == "still":
            motion = []
        elif args.get("moves") not in (None, ""):
            motion = self._motion(probe)
        else:
            motion = [(k, current[k]) for k in ("moves", "edges") if k in current]
        merged += motion
        merged.append(("layer", quoted(self._layer(entry, entry.layer))))
        return merged

    # -- rules: what touching it does ---------------------------------------------

    def _rule(self, edit, name: str, *, items: str | None = None) -> None:
        touch = self.args.get("touch")
        if touch not in ("avoid", "collect", "nothing", "shoot", "block"):
            return
        entry = self.scene.entries.get(name)
        if touch == "avoid" and entry is not None and "grid" in entry.keywords:
            # A maze's walls are solid; "avoid" on them is the 4B's habit (the Maze_test01
            # replay), and back-to-the-start on every brush with a wall is no maze.
            self.notes.append("the maze's walls stay solid -- touch nothing makes them "
                              "passable")
            touch = "block"
        if touch == "block" and entry is not None and name in self.scene.rules and \
                "_was" in "\n".join(self.lines[self.scene.rules[name][0]:
                                                self.scene.rules[name][1] + 1]):
            return                     # solid already
        player = self.facts.get("player")
        if touch == "shoot":
            self._shot(edit, name, player, items)
            return
        if touch == "block":
            if items:
                self.notes.append(f"{items} are the game's own code, so walking into them was "
                                  f"left to it -- edit_file changes that")
                return
            self._block(edit, name, player)
            return
        if player is None:
            self.notes.append("there is no player the arrow keys move, so nothing happens "
                              "when it is touched")
            return
        existing = self.scene.rules.get(name)
        if existing:
            edit.drop(*existing)
            self._drop_hold(edit, name)
        if touch == "nothing":
            return
        if items and self._already_touched(items):
            self.notes.append(f"the game already does something when {items} are touched, "
                              f"so that was left as it is")
            return
        indent = self.facts.get("indent")
        var = self.var
        at = (self.scene.update_line + 1) if self.scene.update_line is not None else \
            self.facts.get("fill")
        # Once per touch, in the frame it begins: a bump that lasts twenty frames is one
        # bump, and a car crossing the start cannot pin the player there (SPIKES §29).
        touch_call = "touched" if counts_touches(self.project) else "touching"
        if touch == "avoid":
            start = source.rect_start(self.scene.tree, player) or \
                f"({self.width // 2}, {self.height // 2})"
            block = [f"{indent}{source.RULE_MARK}touching {name} sends the player back to "
                     f"the start.",
                     f"{indent}if {var}.{touch_call}({player}, {quoted(name)}):",
                     f"{indent}    {player}.topleft = {start}"]
        elif source.maze_layout(self.scene) is not None:
            # In a maze, reaching it is the end of a run: a point, and the player starts
            # the maze again -- the thing stays at the end (the owner's Maze_test01).
            start = source.rect_start(self.scene.tree, player) or \
                f"({self.width // 2}, {self.height // 2})"
            block = [f"{indent}{source.RULE_MARK}reaching {name} scores a point, and the "
                     f"player starts the maze again.",
                     f"{indent}if {var}.{touch_call}({player}, {quoted(name)}):",
                     f"{indent}    score += 1",
                     f"{indent}    {player}.topleft = {start}"]
            self._score(edit)
            self.maze_goal = True
        else:
            one = _singular(name)
            if one in source.names_used(self.scene.tree) or not one.isidentifier():
                one = "touched"
            block = [f"{indent}{source.RULE_MARK}touching {name} scores a point.",
                     f"{indent}for {one} in {var}.{touch_call}({player}, {quoted(name)}):",
                     f"{indent}    score += 1",
                     f"{indent}    {one}.respawn()"]
            self._score(edit)
        edit.insert(at, block)

    def _shot(self, edit, name: str, player: str | None, items: str | None) -> None:
        """``touch: shoot`` -- clicking it, or Space with the player over it, hits it: a
        point, and it goes round again.

        Measured on the owner's test04 and both replays: asked for "a first person
        shooter -- we have to shoot monsters hiding behind trees", no model shot anything.
        The 4B's own try in the owner's game was Space adding a yellow dot every frame,
        forever, hitting nothing. Shooting is a rule, like avoid and collect, so the scene
        gives it: a click is an event, so it goes in the event loop, once per click."""
        if items:
            self.notes.append(f"{items} are the game's own code, so clicking them was left to "
                              f"it -- edit_file changes that")
            return
        existing = self.scene.rules.get(name)
        if existing:
            edit.drop(*existing)
        events = source.event_loop(self.scene.tree)
        if events is None:
            self.notes.append("the game has no event loop to hear a click in, so nothing "
                              "happens when it is clicked")
            return
        event = events.target.id
        indent = " " * events.body[0].col_offset
        one = _singular(name)
        if one in source.names_used(self.scene.tree) or not one.isidentifier():
            one = "hit"
        clicked = f"{event}.type == pygame.MOUSEBUTTONDOWN"
        if player:
            how = f"clicking {name.replace('_', ' ')} -- or Space with the player over it --"
            test = (f"{clicked} or ({event}.type == pygame.KEYDOWN and {event}.key == "
                    f"pygame.K_SPACE)")
            aim = f"{event}.pos if {clicked} else {player}.center"
        else:
            how, test, aim = f"clicking {name.replace('_', ' ')}", clicked, f"{event}.pos"
        block = [f"{indent}{source.RULE_MARK}{how} hits it: a point, and it goes round again.",
                 f"{indent}if {test}:",
                 f"{indent}    aim = {aim}",
                 f"{indent}    for {one} in {self.var}.get({quoted(name)}):",
                 f"{indent}        if {one}.drawn_rect().collidepoint(aim):",
                 f"{indent}            score += 1",
                 f"{indent}            {one}.respawn()",
                 f"{indent}            break"]
        edit.insert(events.end_lineno, block)
        self._score(edit)

    def _already_touched(self, items: str) -> bool:
        loop = source.main_loop(self.scene.tree)
        player = self.facts.get("player")
        for stmt in loop.body if loop else ():
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and (
                        (node.func.attr in ("collidelist", "colliderect")
                         and _dotted_name(node.func.value) == player)
                        or node.func.attr in ("touched", "touching")) and \
                        source._mentions(stmt, {items}):
                    return True
        return False

    def _score(self, edit) -> None:
        """A score to count points in, drawn in the corner, when the game has none."""
        facts = self.facts
        if facts.has("score"):
            return
        # Dark words on a light sky, light ones on a dark one -- a night sky is a sky too
        # (the test04 shooting gallery's score was dark grey on navy).
        light = any(e.look_class in ("Sky",) for e in self.scene.entries.values())
        background = (facts.get("constants") or {}).get(facts.get("background") or "")
        shade = getattr(background, "value", None)
        if isinstance(shade, tuple) and len(shade) == 3 and all(isinstance(v, int)
                                                                for v in shade):
            light = 0.299 * shade[0] + 0.587 * shade[1] + 0.114 * shade[2] > 128
        colour = "(35, 38, 45)" if light else "(240, 240, 240)"
        if facts.has("constants_end"):
            edit.insert(facts.get("constants_end") + 1, [f"SCORE_COLOUR = {colour}"])
        else:
            edit.insert(facts.get("setup_line"), [f"SCORE_COLOUR = {colour}"])
        setup = ["score = 0"]
        if not facts.has("font"):
            setup.append("font = pygame.font.Font(None, 36)")
        edit.insert(facts.get("setup_line"), setup + [""])
        indent = facts.get("indent")
        edit.insert(facts.get("flip"), [
            f'{indent}{facts.get("surface")}.blit(font.render(f"Score: {{score}}", True, '
            f'SCORE_COLOUR), (10, 10))'])

    # -- placing the statement --------------------------------------------------------

    def _position(self, *, after_names, layer: str, on: str | None = None,
                  first: bool = False) -> int:
        """Where a new ``scene.add`` goes: after ``scene = Scene(...)``, after anything it
        draws or stands on, and among the others in the order they are drawn."""
        tree = self.scene.tree
        loop = source.main_loop(tree)
        limit = self.facts.get("setup_line")
        position = self.scene.created + 1
        if first:
            return position
        rank = LAYERS.index(layer) if layer in LAYERS else 2
        for entry in sorted(self.scene.entries.values(), key=lambda e: e.first):
            if LAYERS.index(entry.layer) <= rank if entry.layer in LAYERS else True:
                position = max(position, entry.last + 1)
        if on and on in self.scene.entries:
            position = max(position, self.scene.entries[on].last + 1)
        for name in after_names:
            for node in tree.body:
                if node is loop:
                    break
                if node.lineno - 1 >= limit:
                    break
                if source._mentions(node, {name}):
                    position = max(position, node.end_lineno)
        return min(position, limit)

    # -- what to say -------------------------------------------------------------------

    def _report(self, action, look, entry, keywords) -> dict:
        result = {"ok": True, "object": self.name, "action": action}
        described = look.describe() if look else self._describe_code(entry.look if entry
                                                                     else "")
        result["look"] = described
        if look and look.picture:
            result["picture"] = look.picture
            if self.solid:
                result["see_through"] = False
        values = {key: _value(code) for key, code in keywords}
        if "layer" in values:
            result["layer"] = values["layer"]
        if "count" in values:
            result["count"] = values["count"]
        if "size" in values:
            result["drawn_size"] = values["size"]
        if "on" in values:
            result["placed"] = f"standing on {values['on']}"
        elif "at" in values:
            result["placed"] = f"top-left at {values['at']}"
        if "moves" in values:
            result["moves"] = (f"{values['moves']} pixels each frame (x, y), coming back "
                               f"round the other side")
        touch = self.args.get("touch")
        if touch == "avoid":
            result["touch"] = "touching it sends the player back to the start"
        elif touch == "collect" and self.maze_goal:
            result["touch"] = ("reaching it scores a point, and the player starts the maze "
                               "again")
        elif touch == "collect":
            result["touch"] = "touching one scores a point, and it goes round again"
        elif touch == "shoot":
            result["touch"] = ("clicking one -- or Space with the player over it -- hits it: "
                               "a point, and it goes round again")
        elif entry is None or self.name not in self.scene.rules:
            result["touch"] = "nothing happens when it is touched"
        if "moves" not in values:
            result["moves"] = "it stays where it is"
        result["does_not"] = ("it does not react to any key -- anything the game should do "
                              "when a key is pressed is edit_file")
        return result

    @staticmethod
    def _describe_code(code: str) -> str:
        match = re.match(r"(\w+)\(", code or "")
        if not match:
            return "its look as before"
        name = match.group(1)
        if name == "Picture":
            path = re.findall(r"['\"]([^'\"]+)['\"]", code)
            return f"the picture {path[0]}" if path else "a picture"
        for kind, cls in looks.DRAWINGS.items():
            if cls == name:
                return f"a ready-made {kind} drawing"
        return "its look as before"


# ----------------------------------------------------------------------------- helpers

#: The size a ready-made drawing is when Gary gives none: the kit's own defaults.
_READY_SIZES = {"vehicle": (80, 40), "building": (80, 140), "house": (90, 80),
                "tree": (50, 80), "cloud": (110, 50), "road": (640, 80),
                "ground": (640, 60), "sky": (640, 480), "coin": (28, 28), "star": (30, 30),
                "platform": (120, 20), "sign": (120, 70)}


def _on_of(keywords) -> str | None:
    """The name a statement's ``on=`` names, as written -- a snapped one included."""
    code = dict(keywords).get("on")
    value = _value(code) if code else None
    return value if isinstance(value, str) else None


def _value(code: str):
    """A keyword's value for the result: the value itself when it is one, else its code
    (``CAR_COUNT``), and tuples as lists, the way JSON has them."""
    try:
        value = ast.literal_eval(code)
    except (ValueError, SyntaxError):
        return code
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return [list(v) if isinstance(v, tuple) else v for v in value]
    return value


def keyword_like(name: str) -> bool:
    import keyword

    return keyword.iskeyword(name) or name in ("scene", "screen", "pygame", "running",
                                               "clock", "font", "score")


def _look_of(entry: source.Entry) -> Look:
    for kind, cls in looks.DRAWINGS.items():
        if cls == entry.look_class:
            return Look("drawing", drawing=kind)
    if entry.look_class == "Drawing":
        # Its own box, so a drawing handed to the scene keeps the size it was drawn at.
        try:
            box = ast.literal_eval(ast.parse(entry.look, mode="eval").body.args[0])
        except (SyntaxError, ValueError, AttributeError, IndexError):
            box = None
        box = tuple(box) if isinstance(box, tuple) and len(box) == 2 else None
        return Look("shapes", box=box)
    return Look("picture")


#: Where each shape's colour is among its arguments, in the kit's own signatures.
_COLOUR_ARG = {"Rect": 4, "Circle": 3, "Ellipse": 4, "Triangle": 4, "Polygon": 1,
               "Line": 2, "Text": 3}


def _shape_colour(shape: ast.AST) -> ast.AST | None:
    """The node that is a shape's colour in ``Circle(15, 15, 15, ROCK_COLOUR)``."""
    if not isinstance(shape, ast.Call) or not isinstance(shape.func, ast.Name):
        return None
    for keyword in shape.keywords:
        if keyword.arg == "colour":
            return keyword.value
    index = _COLOUR_ARG.get(shape.func.id)
    return shape.args[index] if index is not None and len(shape.args) > index else None


def _offset(code: str, lineno: int, col: int) -> int:
    """The character index in ``code`` of an ast (line, UTF-8 column) position."""
    lines = code.split("\n")
    before = sum(len(line) + 1 for line in lines[:lineno - 1])
    return before + len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8", "ignore"))


def _forms(name: str) -> list[str]:
    """``car`` and ``cars``, ``bus`` and ``buses``, ``party`` and ``parties``."""
    name = name or ""
    found = [name]
    if name.endswith("ies"):
        found.append(name[:-3] + "y")
    elif name.endswith("es") and name[:-2].endswith(("s", "x", "ch", "sh")):
        found.append(name[:-2])
    elif name.endswith("s"):
        found.append(name[:-1])
    else:
        found.append(name[:-1] + "ies" if name.endswith("y") else
                     name + ("es" if name.endswith(("s", "x", "ch", "sh")) else "s"))
    return found


def _singular(name: str) -> str:
    forms = _forms(name)
    return min(forms, key=len)


def _pair(value) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        return (round(value[0]), round(value[1]))
    return None


def _luminance(rgb) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _clamp_spot(spot, size, width, height) -> tuple[int, int]:
    x = max(-size[0] + 8, min(width - 8, spot[0]))
    y = max(-size[1] + 8, min(height - 8, spot[1]))
    return (x, y)


def _natural(look: Look, width: int, height: int) -> tuple[int, int]:
    """A picture's own size, no bigger than a quarter of the screen; a drawing's box."""
    if look.box:
        w, h = look.box
        pictured = look.kind in ("picture", "pictures", "animation")
        limit = min(width, height) // 4 if pictured else max(width, height)
        scale = min(1.0, limit / max(w, h))
        return (max(4, round(w * scale)), max(4, round(h * scale)))
    return (64, 64)


def _shape_of(look: Look | None, wanted) -> tuple[int, int] | None:
    """For a ready-made drawing on a game's own rect: the shape it keeps -- the size Gary
    asked for, or the drawing's own. None when the default is right anyway."""
    if look is None or look.kind != "drawing":
        return None
    if wanted:
        return wanted
    return None


def _screen_size(facts) -> tuple[int, int]:
    constants = facts.get("constants") or {}
    width = constants.get(facts.get("width", "WIDTH"))
    height = constants.get(facts.get("height", "HEIGHT"))
    w = width.value if width is not None and isinstance(width.value, int) else 640
    h = height.value if height is not None and isinstance(height.value, int) else 480
    return w, h


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _signed(direction: int, name: str) -> str:
    if direction == 0:
        return "0"
    return name if direction > 0 else f"-{name}"


def _dotted_name(node) -> str:
    return node.id if isinstance(node, ast.Name) else ""


def _header(path: Path):
    from opennest.assets import describe

    try:
        with path.open("rb") as stream:
            head = stream.read(describe.HEAD_BYTES)
    except OSError:
        return None
    return describe.read_image_header(head)
