"""What Gary's replies may say, read deterministically -- the owner-test pass.

The first real test of Phase 13 (SPIKES.md section 27) found the 4B model writing tool
calls out as text, looping the same lines until its output cap, saying "the eagle is now
flying" about a game with no eagle, "I see the eagle is missing" with nothing shown to
it, and promising "I'll do that now" at the end of a turn that did nothing. These are the
checks the controller applies to a reply before a child reads it, kept apart from the
loop that decides what to do about them: whether a message asks or asks for, what the
chat may carry (``presentable``), whether a reply looped, which phrases claim a result,
a look or a promise, and which things a child has named.
"""

from __future__ import annotations

import re

#: Saying a result is there -- "the eagle is now flying", "the cars now move" -- which is a
#: claim of a change whoever made it. Only a claim when no file changed this turn or the
#: one before: the owner's first Phase 13 test had "The eagle is now flying back and forth
#: across the screen" after three turns in which no file changed at all, and none of the
#: first-person verbs above was in it (SPIKES.md section 27).
CLAIMED_RESULT = ("is now ", "are now ", "now flies", "now fly ", "now moves", "now move ",
                   "now has ", "now have ", "now shows", "now appears", "now drops",
                   "is now visible", "will now see", "you'll now see", "there now",
                   "it's there", "in place now", "all set up", "look for it in")
#: ...and the same said as work under way, starting a sentence: "Creating src/main.py
#: with a placeholder." -- in an answer, where nothing can change (the owner-test walk).
UNDERWAY_START = re.compile(
    r"(?:^|[.!?]\s+|\n\s*)(?:creating|adding|writing|making|setting up|updating|"
    r"changing|drawing|building)\s", re.IGNORECASE)

#: Saying it looked. Nothing Open Nest does shows Gary the game, the screen or the Build /
#: Preview panel -- and no provider sends image bytes at all yet
#: (``provider.IMAGE_INPUT_IMPLEMENTED``) -- so each of these is an observation nobody
#: made. Measured: "I see the eagle is missing." Only these phrasings, so "I see, you want
#: it red" is left alone.
CLAIMED_SIGHT = ("i see the", "i see that", "i see it", "i see your", "i see a ",
                  "i see there", "i see no", "i can see", "i could see",
                  # A chart is a picture too, and nobody has looked at it (parity walk):
                  "the chart shows", "the graph shows", "the plot shows", "chart shows the",
                  "i watched", "i looked at the game", "i played it", "i can tell it")


#: A sentence that suggests, plans or denies rather than says a thing is there: "I can
#: add the eagle", "there's no eagle yet", "want me to make the cars?".
NOT_ASSERTED = re.compile(
    r"\b(?:add|adding|make|making|will|'ll|can|could|would|want|wants|next|if|let's|"
    r"going to|haven't|hasn't|isn't|aren't|not|no|yet|missing|didn't|doesn't|don't|"
    r"without|instead|should|plan|step|idea|try adding|ask)\b", re.IGNORECASE)
#: Words a child uses that are never the name of a thing a game has, or that the Basic
#: Game has without spelling them out ("the orange square" is ``pygame.draw.rect``).
_NOT_THINGS = frozenset((
    "game", "games", "player", "screen", "window", "keys", "key", "code", "file", "files",
    "project", "starter", "square", "shape", "thing", "things", "one", "way", "step",
    "steps", "time", "part", "parts", "bit", "lot", "lots", "colour", "color", "left",
    "right", "top", "bottom", "side", "sides", "middle", "run", "arrow", "arrows",
    "button", "buttons", "idea", "ideas", "start", "end", "goal", "back", "forth",
    "front", "ones", "kind", "sort", "level", "levels", "version", "rest", "same",
    "other", "new", "old", "first", "last", "point", "points", "times", "score",
    # Phase 13C: what a scene is described as, not a thing in it. A row of buildings is
    # the town and the sky is the background -- checking them for a name of their own
    # would correct Gary for a scene he really made.
    "background", "scene", "world", "place", "style", "look", "feel",
))


#: Words a plural thing follows without a determiner: "over cars", "about dinosaurs".
_BEFORE_PLURALS = frozenset(("over", "about", "with", "of", "under", "near", "around",
                             "avoid", "dodge", "catch", "shoot", "collect", "and", "some"))

_DETERMINERS = frozenset((
    "a", "an", "the", "some", "my", "more", "two", "three", "four", "five", "six", "ten",
    "many", "lots",
))
#: Words that describe the thing after them: "a white eagle", "five parked cars".
_DESCRIBING = frozenset((
    "big", "bigger", "small", "smaller", "tiny", "little", "huge", "giant", "large",
    "fast", "faster", "slow", "slower", "red", "orange", "yellow", "green", "blue",
    "purple", "pink", "white", "black", "grey", "gray", "brown", "gold", "silver", "dark",
    "light", "bright", "flying", "parked", "moving", "falling", "shiny", "cute", "scary",
    "funny", "angry", "happy", "new", "old", "other", "fun", "cool", "simple", "short",
    "long", "little", "few", "nice", "real",
    # Phase 13C: how a child describes a look -- "a clean modern mobile game".
    "clean", "modern", "mobile", "colorful", "colourful", "friendly", "pretty",
    "beautiful", "sunny", "cloudy", "busy", "quiet", "tall", "wide", "round", "soft",
    "flat", "cartoon", "realistic", "whole",
))
#: "add buildings", "put coins along the road": a plural straight after one of these is a
#: thing asked for, with no "the" (Phase 13C's walk: "buildings" was never read).
_PLACING = frozenset(("add", "put", "draw", "place", "show"))
#: Verbs a joined word can be instead of a thing: "a town and avoid cars".
_DOING = frozenset(("make", "fly", "move", "jump", "run", "go", "get", "see", "use", "play",
                    "turn", "change", "drive", "fall", "shoot", "win", "lose", "try"))
#: Words that follow a determiner and are not things: "a lot", "the same", "that".
_NOT_NOUNS = frozenset((
    "that", "this", "these", "those", "same", "lot", "bit", "way", "of", "to", "and", "or",
))


def child_nouns(text: str) -> set[str]:
    """Thing words from a child's request: the word after "a", "the", "five"...,
    past one describing word -- "an eagle", "the cars", "five parked cars"."""
    words = re.findall(r"[a-z']+", text.lower())
    found = set()

    def thing(noun: str) -> bool:
        return len(noun) >= 3 and noun.isalpha() and noun not in _NOT_THINGS \
            and noun not in _NOT_NOUNS and noun not in _DESCRIBING \
            and noun not in _DETERMINERS

    for index, word in enumerate(words[:-1]):
        following = words[index + 1]
        if (word in _BEFORE_PLURALS or word in _PLACING) and following.endswith("s") \
                and len(following) > 3 and following not in _NOT_THINGS \
                and following not in _DESCRIBING:
            # "flies over cars", "a site about dinosaurs": a plural needs no "the".
            # Measured: "The car appears at the right edge" went unquestioned because
            # "over cars" was never read as a thing the child asked for.
            found.add(following)
            at = index + 1
        elif word in _DETERMINERS:
            at = index + 1
            # Past the words that describe it: "a clean modern mobile game".
            while at < len(words) - 1 and words[at] in _DESCRIBING and at - index <= 3:
                at += 1
            if not thing(words[at]):
                continue
            found.add(words[at])
        else:
            continue
        # "a sky and road": what is joined to a thing is a thing too -- but not "a town
        # and avoid cars", where it is what happens next.
        joined = words[at + 2] if at + 2 < len(words) else ""
        if words[at + 1:at + 2] in (["and"], ["or"]) and thing(joined) and \
                joined not in _BEFORE_PLURALS and joined not in _PLACING and \
                joined not in _DOING:
            found.add(joined)
    return found


#: Saying it will do it now -- which, at the end of a turn that changed nothing, it did not.
PROMISES = re.compile(
    r"\b(?:i'll|i will|let me|i'm going to|i am going to)\s+(?:now\s+|first\s+|just\s+)?"
    r"(?:add|make|create|edit|build|write|change|update|fix|put|set|do|draw|move|"
    r"style|insert)\b", re.IGNORECASE)


def promises(text: str) -> bool:
    """Whether a reply says Gary will do something -- which is only true if he then does.

    A pattern, not a list: the list missed "Let me create the basic structure" and
    "I'll edit index.html" on the parity walk, and the turn that said them changed
    nothing."""
    return bool(PROMISES.search(text or ""))


#: What the model is told when it describes a result no file change made.
#: Saying it was run, compiled or tested -- a claim when nothing was.
CLAIMED_RUN = ("i compiled", "i've compiled", "i have compiled", "compiled it and",
               "i tested it", "i've tested", "i have tested", "i ran it", "i've run it",
               "i have run it", "i uploaded", "i've uploaded", "i sent it to", "i've sent it")

RUN_CORRECTION = (
    "Nothing was run, compiled or tested this turn, so do not say it was. Say only what "
    "you changed, and tell them how to run or compile it themselves."
)

ANSWER_CORRECTION = (
    "Nothing in this project has changed lately, so do not describe anything as new, "
    "added or under way. Answer their question again from what Open Nest has checked "
    "below, and say plainly what is and is not there yet."
)

RESULT_CORRECTION = (
    "No file has changed, so nothing you just described as new is in the project. If they "
    "asked for a change, make it now with a tool call. If they asked a question, answer "
    "it from what Open Nest has checked about the project, and say plainly what is and "
    "is not there yet."
)

#: ...and when it says it looked.
SIGHT_CORRECTION = (
    "You cannot see the game, the screen or the Build / Preview panel -- nothing has "
    "shown them to you. Say it again without \"I see\" or \"I can see\": say what the "
    "project's files and what Open Nest has checked show instead."
)


#: A message that asks rather than tells. Only used where both answers are safe: an empty
#: project is given its starting files for a request and not for a question ("what do I
#: do now?" is answered, the owner's example). "Can you make me a game?" is a request, and
#: so is "when I press space it should jump" -- "when" is not a question word here.
_ASKING = re.compile(
    r"^\s*(?:what|what's|whats|how|why|where|which|who|is|are|am|does|did|do i|do you|"
    r"should|will it|was|were|can i|could i|wat|hw)\b", re.IGNORECASE)
_ASKING_FOR = re.compile(r"^\s*(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:make|add|"
                         r"build|create|put|give|change|turn|do|write|set)\b", re.IGNORECASE)
def is_question(text: str) -> bool:
    """Whether a message is asking something rather than asking for something."""
    if _ASKING_FOR.match(text):
        return False
    return "?" in text or bool(_ASKING.match(text))


def presentable(text: str) -> str:
    """Gary's words as the child should read them: no tool protocol, no page of code.

    The provider already drops calls it recognises; this is the boundary for everything
    else, whichever model wrote it. The code a turn changed is shown in Build / Preview
    with its new lines marked (``tools.Step``), so a long code block in the chat only
    repeats it in a form a child cannot use. A short one stays -- "Build it and teach me"
    points at a real line. Lines that are a tool call's arguments go whatever they are in.
    """
    if not text:
        return text
    # "I see." / "I see," as an opening acknowledgement: nothing was seen, and the owner's
    # rule is that Gary never says it without evidence. Dropping two words costs nothing.
    text = _ACKNOWLEDGED.sub("", text)
    kept, block, fenced, opened = [], [], False, "```"
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if fenced:
                if len(block) <= _SHORT_CODE:
                    kept += [opened, *block, "```"]
                block, fenced = [], False
            else:
                fenced, opened = True, line.strip()
            continue
        if fenced:
            block.append(line)
        elif not _ARGUMENT_LINE.match(line):
            kept.append(line)
    if fenced and len(block) <= _SHORT_CODE:
        kept += block
    kept = _without_code_runs(kept)
    paragraphs, seen = [], set()
    for paragraph in re.split(r"\n\s*\n", "\n".join(kept)):
        key = " ".join(paragraph.split()).lower()
        if key and key in seen:
            continue                  # a model repeating itself says it once here
        seen.add(key)
        paragraphs.append(paragraph.strip())
    return "\n\n".join(part for part in paragraphs if part).strip()


def looped(text: str) -> bool:
    """Whether a reply repeats a whole paragraph: the 4B model stuck in a loop.

    Measured on the owner-test walk: asked for the whole eagle game, it wrote the same
    four paragraphs over and over until the output cap, with no call in it. That is the
    same failure as a call cut off at the cap -- nothing done, the room run out -- and it
    is handled the same way: split into steps, never relayed.
    """
    seen = set()
    for paragraph in re.split(r"\n\s*\n", text or ""):
        key = " ".join(paragraph.split()).lower()
        if len(key.split()) < 8:
            continue
        if key in seen:
            return True
        seen.add(key)
    # ...or the same short lines, round and round: "Look for the eagle. / It's there. /
    # But it doesn't move." eleven times over, one line each (the owner-test walk).
    counts: dict[str, int] = {}
    for line in re.split(r"\n+|(?<=[.!?])\s+", text or ""):
        key = " ".join(line.split()).lower()
        if len(key.split()) >= 3:
            counts[key] = counts.get(key, 0) + 1
            if counts[key] >= 3:
                return True
    return False


#: A line of code outside a fence: an assignment, a call, a statement Python starts with.
_CODE_LINE = re.compile(
    r"^\s*(?:#|(?:def|class|for|while|if|elif|else|import|from|return|try|except)\b|"
    r"[A-Za-z_][\w.\[\]]*\s*(?:[-+*/]?=|\()|[)\]}]\s*$)")


def _without_code_runs(lines: list[str]) -> list[str]:
    """Three or more code lines in a row, unfenced, are code -- and not for the chat."""
    kept, run = [], []
    for line in lines + [""]:
        if line.strip() and _CODE_LINE.match(line) and not line.rstrip().endswith((".", "?")):
            run.append(line)
            continue
        if len(run) < 3:
            kept += run
        run = []
        kept.append(line)
    return kept[:-1]


_ACKNOWLEDGED = re.compile(r"^\s*(?:ok(?:ay)?[,.]?\s+)?i see[.,!]\s*", re.IGNORECASE)

#: The longest code block left in the chat. Anything longer is in Build / Preview.
_SHORT_CODE = 6
#: ``old_text="..."`` / ``"new_text": "..."``: a tool call's argument, never prose -- and
#: Open Nest's own "[Open Nest: ...]" note, which a model reading its history may copy.
_ARGUMENT_LINE = re.compile(
    r'^\s*(?:"?(?:old_text|new_text|content|arguments)"?\s*[:=]|\[Open Nest:|'
    r'\{"name"\s*:\s*"(?:read_file|edit_file|write_file|run_project|compile_project|'
    r'game_object)")')
