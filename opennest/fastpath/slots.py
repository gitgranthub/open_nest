"""The details of a request a recipe needs: how much, what colour, what name, which pin.

Two kinds, and the split is the same one the rest of the Fast Path makes:

- **What the child literally wrote** is read with ordinary code: a number, a quoted
  title, a pin, a noun from a closed list. No model, and no guessing -- a pin that is not
  in the message is *absent*, never inferred, because inventing a pin is the one thing
  every hardware prompt forbids.
- **What the child meant** by a word the code cannot map -- "make it the colour of
  grass", "slower" versus "faster" -- is a closed question to the same model, through
  :meth:`IntentClassifier.choose`. It answers from a fixed list or not at all.

A slot that cannot be filled is not an error. The recipe steps aside and Gary, who can
ask, takes the turn with the recipe's guidance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Named colours a child might ask for, as RGB. One list for every project type: a game
#: uses the tuple, a website the hex. Kept short on purpose -- it is a closed question to
#: the model and every extra option is another letter to confuse.
PALETTE: dict[str, tuple[int, int, int]] = {
    "red": (220, 60, 60),
    "dark red": (130, 25, 30),
    "orange": (240, 140, 40),
    "yellow": (240, 210, 60),
    "gold": (225, 180, 45),
    "green": (70, 180, 90),
    "dark green": (20, 70, 35),
    "light green": (150, 225, 140),
    "blue": (60, 120, 230),
    "dark blue": (15, 25, 80),
    "light blue": (140, 190, 245),
    "purple": (140, 80, 200),
    "pink": (240, 120, 180),
    "white": (245, 245, 245),
    "black": (0, 0, 0),
    "grey": (128, 128, 128),
    "brown": (130, 85, 45),
    "teal": (30, 150, 150),
}

_HEX = re.compile(r"#([0-9a-fA-F]{6})\b")
_RGB = re.compile(r"\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)")


def hex_of(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def explicit_colour(text: str) -> tuple[int, int, int] | None:
    """A colour written out as a six-digit hex code or ``(10, 20, 30)``, or None."""
    match = _HEX.search(text)
    if match:
        value = match.group(1)
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    match = _RGB.search(text)
    if match:
        parts = tuple(int(part) for part in match.groups())
        if all(0 <= part <= 255 for part in parts):
            return parts  # type: ignore[return-value]
    return None


# -- how much -----------------------------------------------------------------------

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "twenty": 20,
}
_TIMES = re.compile(r"\b(\d+(?:\.\d+)?|" + "|".join(_WORD_NUMBERS) + r")\s*(?:x|times)\b",
                    re.IGNORECASE)
_TO_VALUE = re.compile(
    r"\b(?:to|=|at|be|is|of)\s+(\d+(?:\.\d+)?)\b(?!\s*(?:x|times|%|percent))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Amount:
    """How much a number should change. Exactly one of the fields is set."""

    value: float | None = None
    factor: float | None = None


def explicit_amount(text: str) -> Amount | None:
    """"to 10", "twice as fast", "3 times bigger", "half as fast" -- or None."""
    lowered = text.lower()
    if re.search(r"\b(twice|double)\b", lowered):
        return Amount(factor=2.0)
    if re.search(r"\bhalf\b", lowered):
        return Amount(factor=0.5)
    match = _TIMES.search(lowered)
    if match:
        word = match.group(1)
        factor = float(_WORD_NUMBERS.get(word, word))
        if factor > 0:
            return Amount(factor=factor)
    match = _TO_VALUE.search(lowered)
    if match:
        return Amount(value=float(match.group(1)))
    return None


def count_in(text: str) -> int | None:
    """"add 3 asteroids", "add five coins" -- a count the child wrote, or None."""
    lowered = text.lower()
    match = re.search(r"\b(\d{1,3})\s+(?:more\s+)?[a-z]", lowered)
    if match:
        return int(match.group(1))
    for word, number in _WORD_NUMBERS.items():
        if re.search(rf"\b{word}\s+(?:more\s+)?[a-z]", lowered) and word != "one":
            return number
    return None


# -- which thing --------------------------------------------------------------------

def noun_in(text: str, nouns: dict[str, str]) -> tuple[str, bool] | None:
    """The first noun from a closed list the child used, and whether it was plural.

    ``nouns`` maps each plural spelling to its singular (``{"asteroids": "asteroid",
    "asteroid": "asteroid"}``). Naming, not routing: this only chooses what the new
    variables are called and what the reply says.
    """
    words = re.findall(r"[a-z]+", text.lower())
    for word in words:
        if word in nouns:
            return nouns[word], nouns[word] != word
    return None


# -- what it says -------------------------------------------------------------------

#: Double or curly quotes first, since an apostrophe inside them ("Maya's Club") is part
#: of the name. Single quotes only count when they open and close around whole words.
_QUOTED = re.compile(
    r'"([^"]{1,60})"|“([^”]{1,60})”|(?:^|\s)\'([^\']{1,60})\'(?=[\s.!?,]|$)'
)
#: Where what a thing *says* ends and what the child says *about* it begins:
#: "says hello when you press it".
_TRAILING_CLAUSE = re.compile(r"\s+(?:when|whenever|if|after|every|each|so that|and then)\b.*$",
                              re.IGNORECASE)


def _quoted(text: str) -> str | None:
    match = _QUOTED.search(text)
    if not match:
        return None
    found = next(group for group in match.groups() if group is not None).strip()
    return found or None
_NAMED = re.compile(
    r"\b(?:call(?:ed)?|name(?:d)?|title(?:d)?|rename)\s+"
    r"(?:it|my\s+\w+|the\s+\w+|this)?\s*(?:to\s+|as\s+)?(.+?)\s*[.!?]?\s*$",
    re.IGNORECASE,
)
_SAYS = re.compile(
    r"\b(?:say|says|read|reads|to)\s+(.+?)\s*[.!?]?\s*$",
    re.IGNORECASE,
)


def title_in(text: str) -> str | None:
    """A title or name the child spelled out: quoted, or after "call it"/"name it"."""
    quoted = _quoted(text)
    if quoted:
        return quoted
    match = _NAMED.search(text.strip())
    if match:
        found = match.group(1).strip().strip("\"'“”")
        if 0 < len(found) <= 60 and not found.lower().startswith(("something", "a ", "an ")):
            return found
    return None


def words_in(text: str) -> str | None:
    """What a heading should say: quoted, or after "say"/"to". Else None."""
    quoted = _quoted(text)
    if quoted:
        return quoted
    match = _SAYS.search(text.strip())
    if match:
        found = _TRAILING_CLAUSE.sub("", match.group(1).strip()).strip("\"'“”")
        # "change it to say Hello": the first "to" matched, and "say" is not the words.
        found = re.sub(r"^(?:say|says|read|reads)\s+", "", found, flags=re.IGNORECASE)
        if 0 < len(found) <= 80 and not found.lower().startswith(
            ("something", "a ", "an ", "be ", "make ", "look ")
        ):
            return found
    return None


# -- which pin ----------------------------------------------------------------------

_PIN = re.compile(r"\b(?:pin|gpio|bcm)\s*(?:number\s*)?#?\s*(\d{1,2})\b", re.IGNORECASE)
_ARDUINO_PIN = re.compile(r"\b(?:pin\s*)?([aA][0-5])\b|\bpin\s*(\d{1,2})\b", re.IGNORECASE)


def pin_in(text: str) -> int | None:
    """A pin number the child wrote next to the word pin. Never inferred."""
    match = _PIN.search(text)
    return int(match.group(1)) if match else None


def arduino_pin_in(text: str) -> str | None:
    """An Arduino pin as written: ``9`` or ``A0``. Never inferred."""
    match = _ARDUINO_PIN.search(text)
    if not match:
        return None
    return (match.group(1) or match.group(2)).upper()


# -- which of a pair ----------------------------------------------------------------

_ON_ONLY = re.compile(r"\b(stay(s)? on|on for|on longer|on shorter|on_\w+|light on|lit)\b",
                      re.IGNORECASE)
_OFF_ONLY = re.compile(r"\b(off for|stay(s)? off|off longer|off shorter|off_\w+|gap|pause|"
                       r"between|dark for)\b", re.IGNORECASE)


def on_or_off(text: str) -> tuple[str, ...]:
    """Which half of a blink the child means: ("on",), ("off",), or both.

    "stay on for 1 second" is the on time only; "a longer gap" is the off time only; a
    message that pulls them different ways -- "on longer and off shorter" -- is both
    named, and the caller must not treat that as one direction.
    """
    on, off = bool(_ON_ONLY.search(text)), bool(_OFF_ONLY.search(text))
    if on and not off:
        return ("on",)
    if off and not on:
        return ("off",)
    return ("on", "off")


_DURATION = re.compile(
    r"(?:(every|once every)\s+)?(\d+(?:\.\d+)?|half a|a)\s*"
    r"(ms|milliseconds?|millis|s|secs?|seconds?)\b", re.IGNORECASE)


def duration_in(text: str) -> tuple[float, bool] | None:
    """A time the child wrote, in seconds, and whether it was "every" -- a whole cycle.

    "on for 1 second" -> (1.0, False); "once every 2 seconds" -> (2.0, True);
    "200 ms" -> (0.2, False). None when no time is written.
    """
    match = _DURATION.search(text)
    if not match:
        return None
    amount = {"half a": 0.5, "a": 1.0}.get(match.group(2).lower())
    value = amount if amount is not None else float(match.group(2))
    unit = match.group(3).lower()
    seconds = value / 1000 if unit.startswith("m") else value
    return seconds, bool(match.group(1))
