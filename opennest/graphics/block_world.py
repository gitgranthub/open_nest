"""The 3D Block World: a game seen through the player's eyes, built of 1 metre blocks.

The owner's test05 (2026-10-04, Gary Fast): "create a simple, block 3D game. Where the
world is made by 1 meter square cubes." Three turns later the game was one rectangle the
size of the window -- and Open Nest had asked for that: the whole-game guidance said "if
it needs 3D or first person, build the closest 2D version". The game builds in
``benchmarks/game_builds`` put the same request to both local models (SPIKES.md section
33): neither can write a first-person renderer through ``edit_file``, and nothing in the
scene layer draws one.

So a 3D game is a starter, like every other foundation (``projects/starters``): the
``pygame_blocks3d`` kit is about two hundred lines of plain pygame -- a ray for every few
pixels across the screen, block stacks drawn far to near -- that Open Nest ships and
tests, and everything a child would change is a named value at the top of the game:
``WORLD`` (the map seen from above, one letter a block), ``BLOCKS``, ``SKY``, ``GROUND``,
``PLANETS``, ``HANDS``, the speeds. What Gary is for is changing those -- and a sky or a
ground is one word ("night", "moon"), because measured on Gary Fast a look that took two
coordinated edits got one of them: stars switched on over a blue day sky.

This module is what the rest of Open Nest knows about such a game: whether a game is one
(read from its code every time, never from a flag), whether a message asks for 3D, what
Gary is told beside a request, and the checked facts about the world. Nothing here
imports pygame.
"""

from __future__ import annotations

import ast
import re

#: The kit's id in ``projects/starters``.
STARTER_ID = "pygame_blocks3d"

#: A message that asks for a game in 3D. "First person" alone is deliberately not one:
#: the owner's test04 ("A first person shooter. We have to shoot monsters hiding behind
#: trees") is answered, measured over five replay rounds (SPIKES.md section 30), by a 2D
#: night forest made of the child's own tree pictures with their monster to shoot -- and
#: the block world draws neither pictures nor monsters.
ASKS_FOR_3D = re.compile(
    r"\b(?:3[- ]?d|three[- ]dimension(?:al|s)?|minecraft|voxels?|block[- ]?world)\b",
    re.IGNORECASE)

_WORLD = re.compile(r"^WORLD\s*=\s*\[", re.MULTILINE)
_BLOCKS = re.compile(r"^BLOCKS\s*=\s*\{", re.MULTILINE)
#: ...and its renderer: a flat tile game of the child's own may well have a WORLD map
#: and a BLOCKS table, and must keep its scene layer.
_VIEW = re.compile(r"^FIELD_OF_VIEW\s*=", re.MULTILINE)

#: Said beside every request in a block-world game. Words only Gary reads, and no
#: sentence for him to copy as a reply (SPIKES.md section 30D).
GUIDE = (
    "(Open Nest: this game is a 3D Block World, seen through the player's eyes. It is not a "
    "scene of shapes, so game_object is not used here. What they see and do is set by the "
    "names at the top of {entry}: WORLD is the map seen from above -- each letter is one "
    "1 metre block, BLOCKS says each letter's name, colour and how many blocks high it is, "
    "a space is open ground and P is where they start; SKY is one word -- day, sunset, "
    "night or space (night and space have stars) -- GROUND is grass, sand, snow or moon, "
    "and PLANETS, HANDS and SHOW_HANDS are the rest of how it looks; WALK_SPEED and "
    "TURN_SPEED are how fast they move (bigger is faster); COLLECT is the name of the "
    "blocks they pick up. Make the change with "
    "edit_file on those lines, copied exactly as they are. A new kind of block is a new "
    "letter in BLOCKS, then that letter in WORLD. Change only what they asked for; if the "
    "world already has what they describe, change nothing and say it is there.)")

#: Said beside the request that started it, the turn Open Nest set it up.
JUST_STARTED = (
    "(Open Nest: it has just been set up as the 3D Block World, so it already has a sky "
    "and ground, blocks to walk among, W A S D to walk and turn, two hands, and gold "
    "blocks to pick up. Change only what they asked for that it does not have yet. If it "
    "already has all of it, change nothing and tell them how to play.)")


#: What the child is told the turn it was set up, when Gary's own extra changes did not
#: land -- instead of "I haven't built any of that yet", which the opening contradicts.
READY = ("It's ready to play: press Run Game and click inside the game. To change it, tell "
         "me what you'd like different -- the sky, the blocks and where they go, or how fast "
         "you walk.")


def summary_for_child(source: str) -> str:
    """What the world has, in a few words a child reads: "a day sky, grass ground, ..."."""
    values = _values(source)
    parts = []
    sky, ground = values.get("SKY"), values.get("GROUND")
    if isinstance(sky, str):
        parts.append(f"a {sky} sky" + (" with stars" if sky in ("night", "space") else ""))
    if isinstance(ground, str):
        parts.append(f"{ground} ground")
    world, blocks = values.get("WORLD"), values.get("BLOCKS")
    collect = values.get("COLLECT")
    if isinstance(world, list) and isinstance(blocks, dict):
        names: dict[str, int] = {}
        for row in world:
            for letter in str(row):
                kind = blocks.get(letter)
                if isinstance(kind, (list, tuple)) and kind:
                    names[str(kind[0])] = names.get(str(kind[0]), 0) + 1
        found = names.pop(collect, 0) if isinstance(collect, str) else 0
        if names:
            kinds = list(names)
            listed = kinds[0] if len(kinds) == 1 else \
                f"{', '.join(kinds[:-1])} and {kinds[-1]}"
            parts.append(f"blocks of {listed} to walk among")
        if found:
            parts.append(f"{found} {collect} block{'s' if found != 1 else ''} to find")
    if values.get("SHOW_HANDS") is not False:
        parts.append("two hands")
    parts.append("W A S D to walk and turn")
    return ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]


def is_block_world(source: str) -> bool:
    """Whether this game is a 3D Block World: its ``WORLD`` map, ``BLOCKS`` key and the
    first-person view they are drawn in."""
    return bool(_WORLD.search(source) and _BLOCKS.search(source) and _VIEW.search(source))


def of_project(project) -> bool:
    """Whether the project's game is a block world, read from its entry file now."""
    try:
        return is_block_world(project.entrypoint_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False


def offered(profile) -> bool:
    """Whether this kind of project can start from the block world kit."""
    return STARTER_ID in tuple(getattr(profile, "starters", ()) or ())


def _values(source: str) -> dict:
    """The literal values the game assigns at the top level, by name."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
                node.targets[0], ast.Name):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                continue
    return found


def facts(source: str, entry: str, colour_family) -> list[str]:
    """What is in the world, read from the code: checked facts for Gary's prompt.

    ``colour_family`` names a colour the way the other checked facts do
    (``agent.evidence.colour_family``), passed in so this package needs nothing above it.
    """
    values = _values(source)
    world, blocks = values.get("WORLD"), values.get("BLOCKS")
    if not isinstance(world, list) or not isinstance(blocks, dict):
        return [f"- The game is a 3D Block World, seen through the player's eyes, but its "
                f"WORLD or BLOCKS in {entry} cannot be read. Do not guess what is in it."]
    counts: dict[str, int] = {}
    starts = 0
    for row in world:
        for letter in str(row):
            if letter == "P":
                starts += 1
            kind = blocks.get(letter)
            if isinstance(kind, (list, tuple)) and kind:
                counts[str(kind[0])] = counts.get(str(kind[0]), 0) + 1
    width = max((len(str(row)) for row in world), default=0)
    lines = [f"- The game is a 3D Block World, seen through the player's eyes: the world "
             f"is WORLD at the top of {entry}, {width} blocks across and {len(world)} deep "
             f"seen from above, each block 1 metre."]
    if counts:
        lines.append("- Blocks in the world: " + ", ".join(
            f"{number} {name}" for name, number in counts.items()) + ".")
    kinds = []
    for letter, kind in blocks.items():
        if isinstance(kind, (list, tuple)) and len(kind) >= 3:
            name, colour, high = kind[0], kind[1], kind[2]
            try:
                shade = colour_family(colour)
            except (TypeError, ValueError, IndexError):
                shade = "an unreadable colour"
            kinds.append(f'"{letter}" {name}, {shade}, {high} high')
    if kinds:
        lines.append("- What each letter is (BLOCKS): " + "; ".join(kinds) + ".")
    collect = values.get("COLLECT")
    if isinstance(collect, str) and collect:
        number = counts.get(collect, 0)
        lines.append(f"- Walking into a {collect} block picks it up for a point; there are "
                     f"{number} to find." if number else
                     f"- COLLECT is {collect}, but no {collect} block is in WORLD, so there "
                     f"is nothing to pick up.")
    look = []
    for name in ("SKY", "GROUND"):
        value = values.get(name)
        if isinstance(value, str):
            look.append(f'{name} is "{value}"')
        elif isinstance(value, (list, tuple)) and len(value) >= 3:
            look.append(f"{name} is {colour_family(value)}")
    if values.get("SKY") in ("night", "space"):
        look.append("stars are in the sky")
    planets = values.get("PLANETS")
    if isinstance(planets, list) and planets:
        look.append(f"{len(planets)} planet{'s' if len(planets) != 1 else ''} in the sky")
    if values.get("SHOW_HANDS") is False:
        look.append("the hands are hidden (SHOW_HANDS is False)")
    elif values.get("SHOW_HANDS") is True:
        look.append("two hands show at the bottom")
    if look:
        lines.append("- How it looks: " + "; ".join(look) + ".")
    if not starts:
        lines.append("- WORLD has no P, so the player starts in the top-left corner.")
    return lines
