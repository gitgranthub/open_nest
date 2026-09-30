"""The things a game recipe can add: what each one looks like, how it moves, and variety.

A recipe that gave every child the same five grey circles would make the Fast Path feel
like a template, and a child asking for asteroids in their game and in their friend's
would get the same game twice. So the look, the motion and the numbers are shaped in
this order:

1. **What the child said.** "A big red ball", "lots of tiny stars", "fast asteroids":
   size, colour, count and speed words are read from the request and win outright.
2. **What the thing is.** Each noun has its own small look -- craters on an asteroid,
   eyes on a monster, a ring round a planet -- built from the scene kit's generic shapes
   or ready-made drawings (``scene_look``), and a sensible size, speed and number.
3. **Which project it is.** Anything still undecided -- which of a few shades, a little
   bigger or smaller, a little faster or slower, which way the asteroids come from -- is
   chosen from a seed made of the project's name and what is being added. The same
   project asking the same thing gets the same result, so a test, an undo and a retry
   are all reproducible; two projects asking the same thing do not.

Every look is drawn on the thing's own rectangle, so a star field can have stars of
different sizes and a child can change ``..._SIZE`` and have everything follow.
"""

from __future__ import annotations

import random
import re
import zlib
from dataclasses import dataclass

from opennest.fastpath import slots

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Look:
    drawing: str
    size: int
    #: A few shades; the project's seed picks one when the child names none.
    colours: tuple[RGB, ...]
    #: How many "some" means for this thing.
    many: int
    #: How the second colour of the drawing is made: darker, lighter, or a fixed colour.
    detail: str | RGB = "darker"


NOUNS: dict[str, Look] = {
    "asteroid": Look("rock", 30, ((150, 150, 160), (135, 125, 120), (165, 150, 140)), 5),
    "rock": Look("rock", 30, ((140, 130, 120), (120, 115, 110)), 5),
    "meteor": Look("rock", 28, ((200, 120, 60), (210, 90, 50)), 5),
    "ball": Look("shiny", 24, ((240, 240, 240), (240, 200, 60), (90, 170, 240),
                              (230, 90, 90)), 3, "lighter"),
    "star": Look("dot", 5, ((240, 240, 255), (255, 240, 200), (200, 220, 255)), 40),
    "snowflake": Look("dot", 6, ((245, 245, 255),), 40),
    "raindrop": Look("drop", 6, ((120, 170, 255), (100, 150, 240)), 40),
    "bubble": Look("bubble", 22, ((150, 210, 255), (190, 230, 255)), 6, "lighter"),
    "planet": Look("planet", 40, ((130, 100, 210), (210, 140, 80), (90, 170, 160)), 3,
                   "lighter"),
    "coin": Look("coin", 20, ((240, 200, 60), (230, 180, 40)), 5, "lighter"),
    "gem": Look("gem", 20, ((80, 220, 200), (200, 90, 230), (90, 200, 90)), 5, "lighter"),
    "apple": Look("apple", 24, ((220, 50, 50), (120, 200, 70)), 5, (70, 130, 50)),
    "fruit": Look("apple", 24, ((230, 120, 50), (240, 200, 60)), 5, (70, 130, 50)),
    "heart": Look("heart", 22, ((230, 70, 110), (240, 90, 140)), 3),
    "dot": Look("dot", 10, ((240, 240, 240), (240, 200, 90)), 10),
    "circle": Look("dot", 30, ((240, 240, 240), (90, 200, 240)), 3),
    "block": Look("block", 30, ((90, 140, 230), (230, 160, 60), (120, 200, 120)), 3),
    "square": Look("block", 40, ((90, 200, 140), (90, 140, 230), (230, 110, 110)), 3),
    "box": Look("block", 30, ((170, 120, 70), (150, 100, 60)), 3),
    "enemy": Look("creature", 36, ((220, 70, 70), (200, 60, 160), (230, 120, 40)), 3),
    "alien": Look("creature", 36, ((120, 220, 90), (100, 200, 200)), 3),
    "monster": Look("creature", 40, ((180, 60, 160), (120, 80, 200)), 3),
    "zombie": Look("creature", 36, ((100, 160, 90), (130, 150, 80)), 3),
    "ghost": Look("ghost", 36, ((230, 230, 240), (200, 220, 255)), 3),
    "ufo": Look("saucer", 40, ((160, 200, 220), (200, 200, 210)), 3, (120, 230, 140)),
    "bat": Look("wings", 26, ((120, 100, 150), (90, 80, 110)), 5, "lighter"),
    "bird": Look("wings", 24, ((200, 90, 60), (80, 150, 220)), 5, "lighter"),
    "car": Look("car", 44, ((220, 60, 60), (60, 120, 230), (240, 200, 60)), 3),
    "cloud": Look("cloud", 60, ((230, 230, 240), (200, 205, 215)), 3),
    "fish": Look("fish", 32, ((240, 150, 60), (90, 180, 230), (240, 200, 60)), 5),
    "obstacle": Look("block", 36, ((150, 150, 160),), 3),
    "thing": Look("rounded", 30, ((200, 200, 210), (120, 200, 220)), 3),
}


def plural(noun: str) -> str:
    if noun == "fish":
        return "fish_list"
    if noun.endswith("y") and noun[-2:] not in ("ay", "ey", "oy"):
        return noun[:-1] + "ies"
    if noun.endswith(("s", "x")):
        return noun + "es"
    return noun + "s"


#: How a noun is said, where that is not how it is spelled in code.
_SPOKEN = {"ufo": "UFO"}


def spoken(noun: str) -> str:
    return _SPOKEN.get(noun, noun)


def spoken_plural(noun: str) -> str:
    if noun == "fish":
        return "fish"
    return spoken(noun) + "s" if noun in _SPOKEN else plural(noun)


#: Every spelling a child might use for each noun, singular or plural.
NOUN_WORDS: dict[str, str] = {}
for _noun in NOUNS:
    NOUN_WORDS[_noun] = _noun
    NOUN_WORDS[spoken_plural(_noun)] = _noun
NOUN_WORDS.update({"ufos": "ufo", "saucer": "ufo", "saucers": "ufo", "meteorite": "meteor",
                   "meteorites": "meteor", "baddie": "enemy", "baddies": "enemy",
                   "snow": "snowflake", "rain": "raindrop", "boulder": "rock",
                   "boulders": "rock", "gems": "gem", "jewel": "gem", "jewels": "gem"})

#: How a thing can move by itself -- the closed question the model is asked.
MOTIONS = {
    "drift": "moves across the screen by itself and comes back on the other side",
    "fall": "falls or drifts down the screen and starts again at the top",
    "rise": "floats up the screen and starts again at the bottom",
    "bounce": "bounces around the screen off the edges",
    "slide": "slides left and right on its own",
    "zigzag": "zigzags across the screen",
    "wave": "floats across in a wavy line, up and down",
    "orbit": "goes round and round in circles",
}

#: What the child is told each motion does: (one of them, several of them).
MOTION_WORDS = {
    "drift": ("drifts across from the right and comes back round",
              "drift across from the right and come back round"),
    "fall": ("falls down the screen and starts again at the top",
             "fall down the screen and start again at the top"),
    "rise": ("floats up the screen and starts again at the bottom",
             "float up the screen and start again at the bottom"),
    "bounce": ("bounces off the edges", "bounce off the edges"),
    "slide": ("slides left and right", "slide left and right"),
    "zigzag": ("zigzags across the screen and comes back round",
               "zigzag across the screen and come back round"),
    "wave": ("floats across in a wave and comes back round",
             "float across in a wave and come back round"),
    "orbit": ("goes round in circles", "go round in circles"),
    "chase": ("follows the player", "follow the player"),
    "still": ("sits still until you touch it", "sit still until you touch them"),
}

SPEEDS = {"drift": 3, "fall": 3, "rise": 2, "bounce": 3, "slide": 3, "zigzag": 3,
          "wave": 2, "orbit": 3, "chase": 2}

#: Motion words a child writes plainly, for recipes that do not ask the model.
MOTION_CUES = (
    ("orbit", r"\b(orbit|circles?|round and round|spin)"),
    ("zigzag", r"\bzig\s*-?\s*zag"),
    ("wave", r"\bwav(e|y|es)\b"),
    ("rise", r"\b(rise|rising|float(s|ing)? up|bubbl)"),
    ("fall", r"\b(fall|falling|falls|drop|dropping|rain(ing)?|from the sky|from above)"),
    ("bounce", r"\bbounc"),
    ("slide", r"\b(slide|slides|side to side|left and right)"),
    ("chase", r"\b(chase|chases|chasing|follow|follows)"),
)

_BIGGER = {"big", "bigger", "large", "huge", "giant", "massive", "enormous"}
_SMALLER = {"small", "tiny", "little", "mini", "smaller"}
_FASTER = {"fast", "faster", "quick", "speedy", "zooming", "rapid", "zoomy"}
_SLOWER = {"slow", "slowly", "gentle", "lazy", "slower"}
_LOTS = {"lots", "loads", "many", "tons", "hundreds", "bunch", "heaps"}

_EXTRA_COLOURS: dict[str, RGB] = {"silver": (192, 192, 200)}

_NUMBER_WORDS = {1: "a", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                 7: "seven", 8: "eight", 9: "nine", 10: "ten", 12: "twelve",
                 20: "twenty"}


def variety(project, *parts: object) -> random.Random:
    """A generator seeded by the project and what is being made. Stable across runs.

    ``zlib.crc32`` rather than ``hash``: Python salts ``hash`` per process, which would
    make the "same" project come out differently every launch.
    """
    key = "|".join([getattr(project, "name", ""), *(str(part) for part in parts)])
    return random.Random(zlib.crc32(key.encode("utf-8")))


def motion_in(text: str) -> str | None:
    lowered = text.lower()
    for motion, pattern in MOTION_CUES:
        if re.search(pattern, lowered):
            return motion
    return None


def colour_in(text: str) -> tuple[str, RGB] | None:
    """A colour the child named in the request, longest name first ("dark blue")."""
    lowered = text.lower()
    names = {**slots.PALETTE, **_EXTRA_COLOURS}
    for name in sorted(names, key=len, reverse=True):
        if re.search(rf"\b{name}\b", lowered):
            return name, names[name]
    written = slots.explicit_colour(text)
    return ("that colour", written) if written else None


@dataclass
class Style:
    """How one new group of things looks and behaves, decided once."""

    noun: str
    look: Look
    count: int
    motion: str
    size: int
    speed: int
    colour: RGB
    detail: RGB
    #: The child's own describing words, repeated back: ("big", "red").
    said: tuple[str, ...] = ()


def _mix(colour: RGB, towards: RGB, amount: float) -> RGB:
    return tuple(round(c + (t - c) * amount) for c, t in zip(colour, towards))  # type: ignore[return-value]


def detail_of(look: Look, colour: RGB) -> RGB:
    if isinstance(look.detail, tuple):
        return look.detail
    if look.detail == "lighter":
        return _mix(colour, (255, 255, 255), 0.55)
    return _mix(colour, (0, 0, 0), 0.35)


def style(noun: str, plural_asked: bool, request: str, motion: str, rng: random.Random,
          *, many: bool = False) -> Style:
    """Decide size, count, speed and colour: the child's words first, then the seed."""
    look = NOUNS.get(noun, NOUNS["thing"])
    words = set(re.findall(r"[a-z]+", request.lower()))
    said: list[str] = []

    written = slots.count_in(request)
    count = written or (look.many if plural_asked or many else 1)
    if not written and words & _LOTS:
        count = max(count, look.many) * 2
    count = max(1, min(count, 60))

    size = round(look.size * rng.choice((0.85, 1.0, 1.15)))
    if words & _BIGGER:
        size = round(look.size * 1.6)
        said.append(sorted(words & _BIGGER)[0])
    elif words & _SMALLER:
        size = max(2, round(look.size * 0.6))
        said.append(sorted(words & _SMALLER)[0])

    speed = max(1, SPEEDS.get(motion, 0) + rng.choice((-1, 0, 0, 1))) if motion in SPEEDS else 0
    if motion in SPEEDS and words & _FASTER:
        speed = SPEEDS[motion] + 3
        said.append(sorted(words & _FASTER)[0])
    elif motion in SPEEDS and words & _SLOWER:
        speed = 1
        said.append(sorted(words & _SLOWER)[0])
    if look.size < 8 and speed > 1 and not words & _FASTER:
        speed -= 1   # a star field drifts; it does not race

    named = colour_in(request)
    if named is not None:
        colour = named[1]
        if named[0] != "that colour":
            said.append(named[0])
    else:
        colour = rng.choice(look.colours)
    return Style(noun=noun, look=look, count=count, motion=motion, size=size, speed=speed,
                 colour=colour, detail=detail_of(look, colour), said=tuple(said))


def describe(s: Style) -> str:
    """"a big red ball that bounces off the edges", "five asteroids that drift..."."""
    one, several = MOTION_WORDS[s.motion]
    adjectives = " ".join(s.said)
    name = f"{adjectives} {spoken(s.noun)}".strip() if s.count == 1 else \
        f"{adjectives} {spoken_plural(s.noun)}".strip()
    if s.count == 1:
        # "an asteroid", "a UFO": the sound, not the letter, and a capital is a letter.
        article = "an" if name[0] in "aeio" or name[:2] == "un" else "a"
        return f"{article} {name} that {one}"
    number = _NUMBER_WORDS.get(s.count, str(s.count))
    return f"{number} {name} that {several}"


# -- looks ---------------------------------------------------------------------------
#
# What each thing looks like is said the way Gary says it: ``game_object``'s arguments,
# drawn by the game's scene (Phase 13C, ``opennest/graphics``). A car is the kit's
# ready-made vehicle, a coin its coin, a cloud its cloud; everything else is the kit's
# basic shapes in the thing's own box -- the same ``shapes`` any model can send, and the
# same call Gary can later change by name. Nothing here is a drawing only a recipe has.
# The shapes are placed for the thing's size and drawn on each of its rects, so a star
# field of different sizes stays different sizes and a child's change to ``..._SIZE``
# is followed. Its colours are the thing's own constants, so ``ASTEROID_COLOUR`` at the
# top keeps deciding them, for the child and for the recipe that changes colours.

#: The kit's ready-made drawings a recipe's thing is drawn as, and the shape it keeps.
READY = {"car": ("vehicle", (1.6, 0.8)), "cloud": ("cloud", (1.6, 0.75)),
         "coin": ("coin", (1.0, 1.0))}

_WHITE, _INK = [255, 255, 255], [30, 30, 36]


def scene_look(name: str, s: int, prefix: str) -> dict:
    """``game_object``'s arguments for a thing drawn as ``name``, ``s`` pixels across."""
    c, d = f"{prefix}_COLOUR", f"{prefix}_DETAIL"
    if name in READY:
        drawing, (wide, tall) = READY[name]
        return {"drawing": drawing, "color": c, "size": [round(s * wide), round(s * tall)]}
    h = s / 2

    def n(value: float) -> float:
        return round(value, 1)

    def circle(x, y, r, colour):
        return {"circle": [n(x), n(y), n(r)], "color": colour}

    def ellipse(x, y, w, t, colour):
        return {"ellipse": [n(x), n(y), n(w), n(t)], "color": colour}

    def rect(x, y, w, t, colour, rounded=0):
        shape = {"rect": [n(x), n(y), n(w), n(t)], "color": colour}
        return {**shape, "round": n(rounded)} if rounded else shape

    def polygon(points, colour):
        return {"polygon": [[n(x), n(y)] for x, y in points], "color": colour}

    def eyes(y, white, pupil=None):
        found = []
        for x in (h - s / 6, h + s / 6):
            found.append(circle(x, y, s / 8 + 1, white))
            if pupil:
                found.append(circle(x, y, s / 16 + 1, pupil))
        return found

    shapes = {
        "rock": lambda: [circle(h, h, h, c), circle(h - s / 6, h - s / 8, s / 7 + 1, d),
                         circle(h + s / 5, h + s / 6, s / 9 + 1, d)],
        "shiny": lambda: [circle(h, h, h, c), circle(h - s / 6, h - s / 6, s / 6 + 1, d)],
        "dot": lambda: [circle(h, h, h, c)],
        "drop": lambda: [ellipse(s / 6, 0, s * 2 / 3, s, c)],
        "bubble": lambda: [circle(h, h, h, c), circle(h, h, h - max(2, s / 10), d),
                           circle(h - s / 5, h - s / 5, s / 8 + 1, _WHITE)],
        "planet": lambda: [ellipse(0, s * 0.4, s, s * 0.22, d), circle(h, h, s * 0.34, c),
                           ellipse(s * 0.1, s * 0.53, s * 0.8, s * 0.09, d)],
        "gem": lambda: [polygon([(h, 0), (s, h), (h, s), (0, h)], c),
                        {"line": [n(s / 4), n(h), n(s * 3 / 4), n(h)], "color": d, "width": 2}],
        "apple": lambda: [circle(h, s * 0.58, s * 0.42, c),
                          rect(s * 0.46, 0, s * 0.08, s * 0.24, d),
                          ellipse(s * 0.54, s * 0.06, s * 0.26, s * 0.13, d)],
        "heart": lambda: [circle(s / 4, s * 0.36, s / 4, c), circle(s * 3 / 4, s * 0.36, s / 4, c),
                          polygon([(0, s * 0.42), (s, s * 0.42), (h, s)], c)],
        "block": lambda: [rect(0, 0, s, s, d), rect(s * 0.1, s * 0.1, s * 0.8, s * 0.8, c)],
        "rounded": lambda: [rect(0, 0, s, s, c, s / 4)],
        "creature": lambda: [rect(0, 0, s, s, c, s / 5)] + eyes(h - s / 6, _WHITE, _INK),
        "ghost": lambda: [circle(h, h, h, c), rect(0, h, s, h, c)]
        + eyes(h - s / 8, [30, 30, 50]),
        "saucer": lambda: [circle(h, s * 0.4, s * 0.24, d), ellipse(0, s * 0.4, s, s * 0.3, c)],
        "wings": lambda: [polygon([(0, 0), (h, h), (s, 0), (h, s)], c),
                          circle(h, h, s / 6 + 1, d)],
        "fish": lambda: [ellipse(0, s / 6, s * 0.75, s * 2 / 3, c),
                         polygon([(s * 0.68, h), (s, s / 6), (s, s * 5 / 6)], c),
                         circle(s * 0.2, s * 0.44, max(1.5, s / 16), _INK)],
    }.get(name, lambda: [rect(0, 0, s, s, c)])()
    return {"shapes": shapes, "size": [s, s]}


def uses_detail(name: str) -> bool:
    """Whether the look for ``name`` is drawn in a second colour, ``..._DETAIL``."""
    return any(shape.get("color") == "X_DETAIL"
               for shape in scene_look(name, 30, "X").get("shapes", []))
