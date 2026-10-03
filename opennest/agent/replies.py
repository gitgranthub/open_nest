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

from opennest.ai.protocol import strip_tool_calls

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
                  "i watched", "i looked at the game", "i played it", "i can tell it",
                  # ...and pointing at it, as if it were on screen in front of Gary: "Run
                  # the game to see it. There it is." (the 4B and the 8B, stress pass).
                  "there it is.", "there they are.", "there it is!", "there they are!")


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
    # ... and where a scene is: "the deep sea", "in space". Measured on the 13C worlds
    # walk (SPIKES.md section 28M): "the deep sea" made "deep" a thing, and Gary was
    # corrected into telling the child "The deep is not in the game".
    "sea", "ocean", "water", "space", "night", "day", "morning", "evening", "sunset",
    "dusk", "dawn",
    # ... and what kind of game it is. "A first person shooter" (the owner's test04) is a
    # genre, not a thing the code would name.
    "shooter", "person", "platformer", "runner", "adventure", "puzzle", "racer", "racing",
    # ... and how a thing is drawn, said about the code: "replace the `shapes` or `drawing`
    # with the pictures" -- "The game has no drawing" followed (the test04 replay, 8B).
    "shapes", "drawing", "drawings", "picture", "pictures", "image", "images", "photo",
    # ... and the website itself. Measured on the stress pass (SPIKES.md section 29):
    # "Make me a website about dinosaurs" made "website" a thing, and Sonnet's true answer
    # "Did you click Preview Website again?" was corrected, because a page titled
    # "Dinosaur World" never says the word.
    "website", "websites", "site", "page", "pages", "webpage",
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
    "deep", "snowy", "starry", "rainy", "stormy", "spooky", "magical", "sandy", "grassy",
    # "the correct pictures I added" (the owner's test04): which ones, not a thing.
    "correct", "right", "wrong", "proper", "actual", "good", "bad", "best", "same", "exact",
    "first", "last", "next", "main", "own",
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
        # Past the words that describe it: "full of little stars" (the 13C worlds walk --
        # "with stars" was then said of a sky that had none, SPIKES.md section 28M).
        at = index + 1
        while at < len(words) - 1 and words[at] in _DESCRIBING and at - index <= 2:
            at += 1
        following = words[at]
        if (word in _BEFORE_PLURALS or word in _PLACING) and following.endswith("s") \
                and len(following) > 3 and following not in _NOT_THINGS \
                and following not in _DESCRIBING:
            # "flies over cars", "a site about dinosaurs": a plural needs no "the".
            # Measured: "The car appears at the right edge" went unquestioned because
            # "over cars" was never read as a thing the child asked for.
            found.add(following)
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
#: "I need to edit the main.py file" is the same (the stress pass, SPIKES.md section 29).
PROMISES = re.compile(
    r"\b(?:i'll|i will|let me|i'm going to|i am going to|i need to|i have to)\s+"
    r"(?:now\s+|first\s+|just\s+)?"
    r"(?:add|make|create|edit|build|write|change|update|fix|put|set|do|draw|move|"
    r"style|insert)\b", re.IGNORECASE)

#: Telling the child how to change the code instead of changing it: "Here is the exact
#: text to replace: ON_SECONDS = 0.3 ... Replace it with: ON_SECONDS = 2.0" -- the 4B, on
#: a request, with no call made (the stress pass, SPIKES.md section 29). Only code-shaped
#: targets: "change the title to My Dog Club" is a thing a child can ask for, not an edit.
_CODE_THING = r"(?:`[^`\n]+`|[A-Za-z_]*_[A-Za-z_]+|[A-Z]{3,}|src/[\w./-]+)"
INSTRUCTS_EDIT = re.compile(
    r"\bexact (?:text|line|code) to (?:replace|change)\b|"
    r"\breplace (?:it|this|that|the (?:line|text|code|value)|" + _CODE_THING + r")\s+with\b|"
    r"\b(?:change|set|update) " + _CODE_THING + r" (?:from \S+ )?to\b|"
    r"\b(?:open|in|edit) " + _CODE_THING + r",? (?:and )?(?:change|replace|set|add)\b|"
    r"\byou (?:need|have|will need) to (?:edit|change|update|replace|open) (?:the )?"
    r"(?:file|code|line|src/|`)", re.IGNORECASE)


def instructs_edit(text: str) -> bool:
    """Whether a reply tells the child how to edit the code -- a change described rather
    than made, which on a request is the same as a promise with nothing done."""
    return bool(INSTRUCTS_EDIT.search(text or ""))


#: Handing the building back: telling the child to make what they asked Gary to make, or
#: to ask again for what Gary is there to do. Measured on the owner's test04 and its
#: replays (4B and 8B): "You can now make the forest we walk through.", "Fix the player's
#: movement to walk forward only.", "Ask for help to add one.", "To use it, you must
#: replace the shapes...". Gary is the help. Run over every reply of the earlier walks
#: (639): in answers, "Ask me to build the simple website" is how to ask, so an answer
#: loses only "ask for help" (``AgentController._tidy``).
_HANDS_BACK = re.compile(
    r"^\s*(?:\d+[.)]\s*|[-*]\s*)?(?:next:\s*)?(?:fix|add|make|change|set|put|replace|draw|"
    r"create|build)\s+(?:the|a|an|it|them|your|some|each|more|one)\b|"
    r"\byou can (?:now |also |then )?(?:make|add|build|create|draw|put|replace)\b|"
    r"\bask (?:me |again )?(?:for|to)\b|\bask for help\b|"
    r"\byou (?:must|need to|have to|should|will need to) (?:replace|add|make|change|fix|draw|"
    r"put|create|build)\b", re.IGNORECASE)
#: ...but not how to play: "Move the player with the arrow keys" is the child's to do.
_PLAYING = re.compile(r"\b(?:arrow|keys?|mouse|click|press|space ?bar|play|playing)\b",
                      re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


#: ...nor a picture to make: only the child can make one (Gary cannot make picture files),
#: so "Make a PNG with a see-through background" is theirs, and true.
_THEIRS = re.compile(r"\b(?:png|pictures?|images?|photos?|see-through|transparent|drawing "
                     r"app|grown-up|add to project)\b", re.IGNORECASE)


def handed_back(text: str) -> list[str]:
    """The sentences of a reply that hand the building back to the child."""
    return [sentence.strip() for sentence in _SENTENCES.split(text or "")
            if sentence.strip() and _HANDS_BACK.search(sentence)
            and not _PLAYING.search(sentence) and not _THEIRS.search(sentence)
            and "?" not in sentence]


def as_offer(sentence: str) -> str:
    """"Fix the player's movement." -> "Want me to fix the player's movement?" -- or ""
    when the sentence is not a thing to build ("Ask for help to add one")."""
    asked = re.search(r"\bask me to (.+?)[.!]*$", sentence, re.IGNORECASE)
    if asked and len(asked.group(1)) <= 100:
        # "-- ask me to change the writing colour too" is an offer already.
        return f"Want me to {asked.group(1).strip()}?"
    words = re.sub(r"^\s*(?:\d+[.)]\s*|[-*]\s*)?(?:next:\s*)?", "", sentence).strip()
    words = re.sub(r"^(?:to use it, )?you (?:can (?:now |also |then )?|must |need to |have to |"
                   r"should |will need to )", "", words, flags=re.IGNORECASE)
    if not re.match(r"(?:fix|add|make|change|set|put|replace|draw|create|build)\b", words,
                    re.IGNORECASE) or len(words) > 110:
        return ""
    words = words.rstrip(" .!")
    return f"Want me to {words[0].lower()}{words[1:]}?"


#: A place on the screen in numbers -- "at (100, 300)", "[0, 400]". Nothing a child needs:
#: the 4B told the child where things were in pixels in every reply of the test04 replay.
_COORDINATES = re.compile(r"[(\[]\s*-?\d+\s*,\s*-?\d+\s*[)\]]")


_PAIR = r"[(\[]\s*-?\d+\s*,\s*-?\d+\s*[)\]]"
#: "at (100, 300)" -- and any more places listed after it -- inside a sentence about
#: something else.
_PLACED_AT = re.compile(r"\s*\b(?:at|to|from|near|by|around)\s+" + _PAIR +
                        r"(?:\s*,\s*(?:and\s+)?" + _PAIR + r")*(?:\s*,?\s*and\s+" + _PAIR + r")?")
#: Speeds in pixels: "at 2 pixels per frame". (A size -- "64 pixels wide" -- is what a
#: child asked for when they asked for bigger, so it stays.)
_PIXEL_PHRASE = re.compile(r"\s*,?\s*\b(?:at\s+)?\d+\s*(?:pixels?|px)\s+(?:per|a|each)\s+"
                           r"frame\b", re.IGNORECASE)
#: What is left hanging once its numbers have gone: "placed", "starting".
_DANGLING = re.compile(r"\s*\b(?:placed|positioned|located|drawn|sized|starting)"
                       r"(?:\s+respectively)?\s*(?=[,.;!?]|$)", re.IGNORECASE)
#: ...and a sentence that no longer reads: "Three red cars are now."
_UNFINISHED = re.compile(r"^(?:it|it's|they|they're|this|that)\s*,|"
                         r"\b(?:is|are|at|and|the|a|now|to|from|by|of|starts?)\s*[.!?]?$|"
                         r"\b(?:is|are)\s+(?:and|with|,)|"
                         r"\b(?:to|at|by|of|from)\s+(?:in|on|and|the end)\b",
                         re.IGNORECASE)


def without_coordinates(text: str) -> str:
    """The reply without places in pixels: "The monster at (100, 300) stays still" is
    "The monster stays still"; a sentence that was only numbers goes -- unless that is all
    the reply says.

    Run over every reply of the earlier walks (639) before it stayed: what it takes out is
    the numbers, and the sentence they were in is kept wherever it still reads --
    "Two red cars are now in the game, moving left at 2 pixels per frame" keeps its cars.
    """
    sentences = [s for s in _SENTENCES.split(text or "") if s.strip()]
    kept, changed = [], False
    for sentence in sentences:
        if not (_COORDINATES.search(sentence) or _PIXEL_PHRASE.search(sentence)):
            kept.append(sentence.strip())
            continue
        changed = True
        cleaned = _DANGLING.sub("", _PIXEL_PHRASE.sub("", _PLACED_AT.sub("", sentence)))
        cleaned = re.sub(r"\s*[,:;]\s*(?=[,:;.!?]|$)", "", cleaned)
        cleaned = re.sub(r"\s+(?=[.!?,])", "", re.sub(r"\s{2,}", " ", cleaned)).strip()
        if _COORDINATES.search(cleaned) or len(cleaned.split()) < 3 or \
                _UNFINISHED.search(cleaned):
            continue
        kept.append(cleaned)
    if not changed or not kept:
        return text
    return "\n".join(kept)


def echoes(reply: str, said: str) -> bool:
    """Whether a reply is the child's own message said back -- Gary speaking their words.

    Measured on the test04 replays, both models: told by a correction to "Answer <their
    message> again", the reply began with their message word for word ("I added tree
    images now... this should allow you to make the forest we walk through.")."""
    def words(text: str) -> list[str]:
        return re.findall(r"[a-z']+", (text or "").lower())
    theirs = words(said)
    if len(theirs) < 5:
        return False
    mine = words(reply)[:len(theirs) + 3]
    same = sum(1 for a, b in zip(theirs, mine) if a == b)
    return same >= 0.8 * len(theirs)


#: Saying what real hardware did. Nothing in Open Nest can see a board or a Pi: Compile
#: checks the code, Test on Mac runs it with pretend pins, and after Send to Board only
#: the child can say what the light does. Measured on the stress pass (SPIKES.md section
#: 29): "The code now confirms blinks on a real Pi." Read a sentence at a time; one that
#: looks ahead ("will", "when you", "once"), tells them what to do, or says it has not
#: run there is not a claim, and neither is one about Test on Mac's printed pretend pins.
_HARDWARE = r"(?:raspberry pi|pi|board|arduino|breadboard|circuit)"
_RESULT = (r"(?:confirm\w*|works?|worked|working|blink\w*|flash\w*|lit|light(?:s|ed)? up|"
           r"glow\w*|tested|verified|proved?|ran|runs|running|turn(?:s|ed) on|spin\w*)")
_HARDWARE_SEEN = re.compile(
    r"\b" + _RESULT + r"\b[^.!?\n]*\bon (?:a|the|your) (?:real |actual |physical )?"
    + _HARDWARE + r"\b|"
    r"\bon (?:a|the|your) (?:real |actual |physical )?" + _HARDWARE + r"\b[^.!?\n]*\b"
    + _RESULT + r"\b|"
    r"\b(?:the |your )?(?:led|light|lamp|bulb|motor|buzzer)s? (?:is|are|was|were|has been|"
    r"have been|kept) (?:now |already |still |currently )?(?:blinking|flashing|lit|glowing|"
    r"shining|spinning|turning|"
    r"buzzing|working)\b", re.IGNORECASE)
_LOOKS_AHEAD = re.compile(
    r"\b(?:will|would|'ll|when|whenever|once|if|after|should|can|could|might|may|need|"
    r"needs|want|expect|until|pretend|not|no|nothing|never|hasn't|haven't|isn't|aren't|"
    r"wasn't|didn't|doesn't|cannot|can't|only you|you'll|to see|output|printed|prints|"
    r"simulat\w*|this mac|the mac)\b", re.IGNORECASE)
_TELLING_TO = re.compile(
    r"^\s*(?:\d+[.)]\s*)?(?:test|try|run|send|plug|connect|upload|copy|put|use|press|"
    r"click|wire|hook|check|watch|look)\b", re.IGNORECASE)


def hardware_claims(text: str) -> list[str]:
    """The sentences in ``text`` that say what a real board or Pi did or is doing."""
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if _HARDWARE_SEEN.search(sentence) and not _LOOKS_AHEAD.search(sentence) and \
                not _TELLING_TO.match(sentence):
            found.append(sentence.strip())
    return found


#: A sentence that offers or wonders about a colour rather than saying the page has it.
_WONDERING = re.compile(r"\b(?:can|could|would|want|wants|if|next|'ll|will|try|maybe|might|"
                      r"like|prefer|or|should|let's|ask)\b|\?", re.IGNORECASE)


def colours_said(text: str, known) -> dict[str, str]:
    """Colour words said as fact, each with its sentence: "a sunny orange header" -- not
    "I can make it orange" or "want it orange?"."""
    found = {}
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if _WONDERING.search(sentence):
            continue
        for word in re.findall(r"[a-z]+", sentence.lower()):
            if word in known and word not in found:
                found[word] = sentence.strip()
    return found


#: A file named in a reply: a path with an extension a project's files have.
_PATH = re.compile(r"(?<![\w/.:-])((?:[\w.-]+/)*[\w-]+\.(?:png|jpe?g|gif|svg|csv|py|html?|css|js|"
                   r"ino|md|txt|json))(?![\w/])", re.IGNORECASE)
#: Files a reply can name only as used -- Gary cannot write a picture or a sound.
_MEDIA = re.compile(r"\.(?:png|jpe?g|gif|webp|bmp|wav|mp3|ogg)$", re.IGNORECASE)
#: ...said to have been changed: "I added code in ...", "This change was made in ...".
_CHANGED_IT = re.compile(
    r"\b(?:i|i've|i have)\s+(?:just\s+)?(?:added|changed|edited|updated|wrote|made|modified|"
    r"created|fixed|put)\b|\b(?:was|were|has been|have been)\s+(?:added|changed|edited|"
    r"updated|written|made|modified|created)\b|\bchange was made\b", re.IGNORECASE)
#: ...or a sentence that denies, doubts or tells them what to do, which is neither.
_DENYING = re.compile(r"\b(?:no|not|nothing|never|isn't|aren't|doesn't|don't|didn't|hasn't|"
                      r"haven't|wasn't|missing|yet|without)\b", re.IGNORECASE)
_TELLING = re.compile(r"^\s*(?:\d+[.)]\s*|[-*]\s*)?(?:press|click|open|run|try|look|go|drop|drag|"
                      r"add|put|save|check|pick|choose|select|use|write|type)\b", re.IGNORECASE)


def files_said_wrongly(text: str, files, recent, *, unchanged: bool = True) -> list[str]:
    """What a reply says about the project's files that is not so: a file named as there
    that the project has not got, or -- with ``unchanged`` -- one said to have been changed
    when nothing has changed it lately (``recent``: the paths the last few turns changed or
    drew). Matched by path, or by name alone, so "index.html" is src/index.html.

    Measured on the stress pass (SPIKES.md section 29), Qwen3 8B in a Research project
    that no edit had ever landed in: "saves it as outputs/growth.png", then, asked "What
    did you actually change?", "This change was made in src/analysis.py." Run over every
    reply of seven walks before it stayed: those two, the 4B's "I updated the code in
    main.py", and nothing true."""
    have = set(files)
    names = {name.rsplit("/", 1)[-1] for name in have}
    touched = {name.rsplit("/", 1)[-1] for name in recent}
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if _WONDERING.search(sentence) or _DENYING.search(sentence) or \
                _TELLING.match(sentence):
            continue
        for path in _PATH.findall(sentence.replace("`", "")):
            name = path.rsplit("/", 1)[-1]
            if re.fullmatch(r"[A-Z][a-z]+\.js", path):
                continue                        # a library's name -- Chart.js -- not a file
            if path not in have and f"src/{path}" not in have and name not in names:
                found.append(f"there is no {path} in this project")
            elif _MEDIA.search(path):
                # A picture or sound is used, never edited: "I added the monster (the
                # picture assets/blue_monster.png)" is about the monster. Measured on the
                # test04 replay -- the 8B's true reply was corrected for it, and it then
                # said the child's own message back.
                continue
            elif unchanged and _CHANGED_IT.search(sentence) and name not in touched:
                found.append(f"{path} has not changed -- no edit to it went in")
    return list(dict.fromkeys(found))


def hardware_correction(family: str, run_label: str) -> str:
    """What Gary is told when he says what real hardware did -- in this project's words:
    Luna copied a generic "Compile and Test on Mac" into a Pi answer, which has no
    Compile."""
    if family == "arduino":
        checks, where = f"{run_label} checks the code only", "board"
    else:
        checks, where = f"{run_label} runs it here with pretend pins", "Raspberry Pi"
    return (f"Nothing in Open Nest has run this on a real {where}, and nothing can see one: "
            f"{checks}. So do not say what the {where} or the light did or is doing. Say it "
            f"again: what the code does, and that they will see it on their own {where}.")


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
#: Just a hello. Answered like a question -- with words, no tools -- since nothing is
#: being asked for. Measured on the owner's test04: "Hi Gary" went to the building
#: prompt, and got "Hi. Ready."
_GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|hiya|howdy|yo|good (?:morning|afternoon|evening))\b"
    r"(?:[\s,!.]+(?:gary|there|again|friend|buddy))*[\s,!.]*$", re.IGNORECASE)


def is_greeting(text: str) -> bool:
    return bool(_GREETING.match(text or ""))


def is_question(text: str) -> bool:
    """Whether a message is asking something rather than asking for something -- or is
    only a hello."""
    if _ASKING_FOR.match(text):
        return False
    return "?" in text or bool(_ASKING.match(text)) or is_greeting(text)


def presentable(text: str) -> str:
    """Gary's words as the child should read them: no tool protocol, no page of code.

    The local provider already drops the calls it runs; this is the boundary for every
    reply, whichever model wrote it -- a cloud model's text meets the same filters
    (``ai.protocol.strip_tool_calls``: a ``<tool_call>`` block, a JSON call, a call
    written as Python, a ``<think>`` block) as the local one's. The code a turn changed
    is shown in Build / Preview with its new lines marked (``tools.Step``), so a long code
    block in the chat only repeats it in a form a child cannot use. A short one stays --
    "Build it and teach me" points at a real line. Lines that are a tool call's arguments
    go whatever they are in.
    """
    if not text:
        return text
    text = strip_tool_calls(text)
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
    kept = [_without_tool_talk(line) for line in kept]
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


#: A sentence that names one of Gary's tools, or repeats what a tool's result told *him*
#: -- never words for the child. Measured on the 13C worlds walk (SPIKES.md section 28M):
#: Qwen3 8B copied game_object's result into its reply -- "It does not react to keys --
#: anything the game should do when a key is pressed is edit_file. Open Nest tests the
#: game after this turn, and the test says what the scene really drew."
_TOOL_TALK = re.compile(
    r"\b(?:read_file|edit_file|write_file|run_project|compile_project|inspect_error|"
    r"game_object)\b|\bOpen Nest tests the game after this turn\b|"
    r"\banything the game should do when a key is pressed\b", re.IGNORECASE)


def _without_tool_talk(line: str) -> str:
    if not _TOOL_TALK.search(line):
        return line
    sentences = re.split(r"(?<=[.!?])\s+", line)
    return " ".join(s for s in sentences if not _TOOL_TALK.search(s))


_ACKNOWLEDGED = re.compile(r"^\s*(?:ok(?:ay)?[,.]?\s+)?i see[.,!]\s*", re.IGNORECASE)

#: The longest code block left in the chat. Anything longer is in Build / Preview.
_SHORT_CODE = 6
#: ``old_text="..."`` / ``"new_text": "..."``: a tool call's argument, never prose -- and
#: Open Nest's own "[Open Nest: ...]" note, which a model reading its history may copy.
_ARGUMENT_LINE = re.compile(
    r'^\s*(?:"?(?:old_text|new_text|content|arguments)"?\s*[:=]|\[Open Nest:|'
    r'\{"name"\s*:\s*"(?:read_file|edit_file|write_file|run_project|compile_project|'
    r'game_object)")')
