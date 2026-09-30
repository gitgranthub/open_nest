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

from opennest.graphics import looks, source
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
        kit: str | None = None, message: tuple[str, tuple[str, ...]] = ("", ())) -> Outcome:
    """Work out the change ``arguments`` ask for. Never raises for Gary's mistakes.

    ``message`` is the child's words this turn and the pictures attached to them -- what a
    picture may be used for is decided from those, never from what it might show."""
    try:
        return _run(project, arguments or {}, pictures, kit, message)
    except (Refused, LookError) as exc:
        return Outcome(False, {"ok": False, "object": str((arguments or {}).get("name", "")),
                               "reason": exc.reason, "message": str(exc),
                               "changed": "nothing -- no file was changed"},
                       reason=exc.reason)


# ----------------------------------------------------------------------------- the work


def _run(project, args: dict, pictures, kit_text, message=("", ())) -> Outcome:
    from opennest.fastpath.kinds import games  # the parser that finds the game's loop

    name = _clean_name(args.get("name"))
    if not name:
        raise Refused("game_object needs a name for the thing, like player, sky or cars.",
                      "missing_argument")
    if name in MECHANICS or name.rstrip("s") in MECHANICS:
        what = ("the window's title is set with pygame.display.set_caption" if name in (
            "title", "caption") else f"a {name.replace('_', ' ')} is how the game plays "
            f"-- counting, keys, rules, sound")
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
    if needs_scene and scene.variable is None and "scene" in source.names_used(scene.tree):
        raise Refused(f"{entry} already uses the name 'scene' for something else, so Open "
                      f"Nest can't add its scene.", "name_taken")
    if needs_scene and not scene.adopted:
        text = _adopt(text, facts, scene)
        facts = games.facts_of(text, entry)
        scene = source.read(text)
    work = _Work(project, text, facts, scene, args, name, pictures, notes, message)
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
    if text == path.read_text(encoding="utf-8") and KIT_PATH not in files:
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
    """"missing", "ours" (the shipped kit or one changed by hand), or refuse."""
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
    return "ours"


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
                 message=("", ())):
        self.project, self.text, self.facts, self.scene = project, text, facts, scene
        self.args, self.name, self.pictures, self.notes = args, name, pictures, notes
        self.said, self.attached = message
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
        if player and self._means_player(player):
            return self._player(player)
        entry = self._existing_entry()
        if entry is not None:
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
            drawing = looks.infer_drawing(self.name)
            if drawing:
                self.notes.append(f"{found} is the child's picture they call {stem!r}, not "
                                  f"a {self.name.replace('_', ' ')}, so it is drawn as a "
                                  f"ready-made {drawing} drawing instead")
                fill = self.args.get("color", self.args.get("colour"))
                return Look("drawing", drawing=drawing,
                            fill=looks.colour(fill, self.notes) if fill else None,
                            text=str(self.args.get("text", "") or "")[:30])
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
        if self._targets_player or picture in self.attached:
            return True
        words = {w for w in re.split(r"[^a-z0-9]+", Path(picture).stem.lower()) if len(w) > 2}
        name = {w for form in _forms(self.name) for w in form.split("_")}
        if words & name:
            return True
        # The child's words tie a picture to something only when they talk about a
        # picture: "use my eagle picture for the enemies", or "this picture" with one to
        # mean. "fly an eagle ... avoid cars" names the eagle, not the cars' picture.
        said = set(re.findall(r"[a-z0-9]+", (self.said or "").lower()))
        if not said & {"picture", "pictures", "image", "images", "photo", "pic", "sprite"}:
            return False
        return bool(words & said) or len(self.pictures) == 1

    _targets_player = False

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
        return text, self._report("changed", look, entry, keywords)

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
                   and n.func.attr in ("collidelist", "colliderect", "touching")
                   and (_dotted_name(n.func.value) == player or n.func.attr == "touching")
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
            edit.replace(start, start + len(collect) - 1, [
                f"{indent}for {one} in {self.var}.touching({self.facts.get('player')}, "
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
        wanted = _pair(self.args.get("size")) or (look.box if look and look.kind != "shapes"
                                                   else None)
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
        if look.kind in ("picture", "animation") and "player" not in self.scene.entries \
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
            y = spot[1] if spot else self.height - height
            keywords.append(("at", f"(0, {max(0, min(self.height - 8, y))})"))
            return keywords
        if not size:
            size = _READY_SIZES.get(drawing) or _natural(look, self.width, self.height)
        size = (max(4, min(self.width, size[0])), max(4, min(self.height, size[1])))
        keywords.append(("size", f"({size[0]}, {size[1]})"))
        spots = args.get("at")
        on = self._on_target()
        if isinstance(spots, (list, tuple)) and spots and all(
                _pair(s) for s in spots) and isinstance(spots[0], (list, tuple)):
            places = [_clamp_spot(_pair(s), size, self.width, self.height) for s in spots][:60]
            keywords.append(("at", "[" + ", ".join(f"({x}, {y})" for x, y in places) + "]"))
        else:
            spot = _pair(spots)
            if spot:
                x, y = _clamp_spot(spot, size, self.width, self.height)
                keywords.append(("at", f"({x}, {y})"))
                if on is None and drawing in STANDING:
                    on = self._snap(y + size[1])
            elif drawing == "cloud":
                keywords.append(("at", f"(0, {self.height // 12})"))
            elif not on:
                count = args.get("count")
                if isinstance(count, (int, float)) and count > 1:
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
            if drawing in ("building", "house", "tree", "cloud"):
                keywords.append(("vary", "0.25"))
        return keywords

    #: How far above a road a standing thing's bottom can be and still be meant to be
    #: on it. Both models put cars 40-80 pixels above the road they asked for (SPIKES.md
    #: section 28E); a sign meant to float higher than that stays where it was put.
    SNAP = 90

    def _snap(self, bottom: int) -> str | None:
        """The road or ground a standing thing placed just above -- or on -- belongs on."""
        for entry in self.scene.entries.values():
            spot, span = entry.literals.get("at"), entry.literals.get("size")
            if entry.look_class not in ("Road", "Ground") or not (
                    isinstance(spot, tuple) and isinstance(span, tuple)):
                continue
            # Just above it, on it, or a little past its lower edge (the final 4B walk's
            # tree stood 10 pixels below a 20-pixel road).
            if spot[1] - self.SNAP <= bottom <= spot[1] + span[1] + 30:
                self.notes.append(f"it was put just above the {entry.name}, so it stands on "
                                  f"the {entry.name}")
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
            self.notes.append(f"there is nothing called {asked!r} in the scene to stand on, "
                              f"so it was placed without it")
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
        probe = look or _look_of(entry)
        fresh = dict(self._placement(probe))
        given = {key for key in ("size", "at", "on", "count") if args.get(key) not in
                 (None, "", [], 0)}
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
            elif key in current:
                merged.append((key, current[key]))
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
        if touch not in ("avoid", "collect", "nothing"):
            return
        player = self.facts.get("player")
        if player is None:
            self.notes.append("there is no player the arrow keys move, so nothing happens "
                              "when it is touched")
            return
        existing = self.scene.rules.get(name)
        if existing:
            edit.drop(*existing)
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
        if touch == "avoid":
            start = source.rect_start(self.scene.tree, player) or \
                f"({self.width // 2}, {self.height // 2})"
            block = [f"{indent}{source.RULE_MARK}touching {name} sends the player back to "
                     f"the start.",
                     f"{indent}if {var}.touching({player}, {quoted(name)}):",
                     f"{indent}    {player}.topleft = {start}"]
        else:
            one = _singular(name)
            if one in source.names_used(self.scene.tree) or not one.isidentifier():
                one = "touched"
            block = [f"{indent}{source.RULE_MARK}touching {name} scores a point.",
                     f"{indent}for {one} in {var}.touching({player}, {quoted(name)}):",
                     f"{indent}    score += 1",
                     f"{indent}    {one}.respawn()"]
            self._score(edit)
        edit.insert(at, block)

    def _already_touched(self, items: str) -> bool:
        loop = source.main_loop(self.scene.tree)
        player = self.facts.get("player")
        for stmt in loop.body if loop else ():
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                        node.func.attr in ("collidelist", "colliderect") and _dotted_name(
                            node.func.value) == player and source._mentions(stmt, {items}):
                    return True
        return False

    def _score(self, edit) -> None:
        """A score to count points in, drawn in the corner, when the game has none."""
        facts = self.facts
        if facts.has("score"):
            return
        light = any(e.look_class in ("Sky",) for e in self.scene.entries.values())
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
        elif touch == "collect":
            result["touch"] = "touching one scores a point, and it goes round again"
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


def _clamp_spot(spot, size, width, height) -> tuple[int, int]:
    x = max(-size[0] + 8, min(width - 8, spot[0]))
    y = max(-size[1] + 8, min(height - 8, spot[1]))
    return (x, y)


def _natural(look: Look, width: int, height: int) -> tuple[int, int]:
    """A picture's own size, no bigger than a quarter of the screen; a drawing's box."""
    if look.box:
        w, h = look.box
        limit = min(width, height) // 4 if look.kind in ("picture", "animation") else \
            max(width, height)
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
