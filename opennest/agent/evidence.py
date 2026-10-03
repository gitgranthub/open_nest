"""What Open Nest has checked about the project, and the screen the child is using.

The owner's first test of Phase 13 (SPIKES.md section 27): every ``edit_file`` was written
out as text and never ran, the game on screen stayed the Basic Game starter's orange
square, and Gary told the child "The eagle is now flying back and forth", then "I see
the eagle is missing" -- with nothing in front of him but his own earlier sentences. The
honesty guard catches "I added"; it cannot catch a model that believes its own history.

So every turn Gary is handed what is true *now*, each line something the application
measured: whether there is a game file at all, whether it is still exactly a starter,
what is in it (read with the parser), which keys it reads, what the last message really
changed, whether the game on screen is the version the files hold, and what the last
test saw. Deterministic, like the file list -- never something the model fetches or
guesses (SPIKES.md section 4).

The second half is the guide: what the child is looking at, so "what do I do now?",
"how do I undo that?" and "where did my picture go?" are answered by Gary from the real
interface rather than from what apps usually have.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from pathlib import Path

from opennest.projects import starters as starter_kits
from opennest.projects.manager import Project, plays_in_panel, source_fingerprint


def _entry(project: Project) -> str:
    return f"src/{project.manifest.entrypoint}"


def _is_game(project: Project, source: str) -> bool:
    return project.profile.playtest == "pygame" or plays_in_panel(project)


def unchanged_starter(project: Project, source: str) -> starter_kits.Starter | None:
    """The starter the entry file is still byte-for-byte, if it is one."""
    candidates = list(starter_kits.starters_for(project.profile))
    if project.manifest.starter_id:
        with contextlib.suppress(starter_kits.StarterError):
            candidates.insert(0, starter_kits.get_starter(project.manifest.starter_id))
    for starter in candidates:
        try:
            shipped = starter.directory / starter.entry_point
            if shipped.read_text(encoding="utf-8") == source:
                return starter
        except (OSError, UnicodeDecodeError):
            continue
    return None


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def code_words(source: str) -> str | None:
    """Every name and string in the code, lower case, one per line -- never its comments.

    What a game *has* is its code: a comment reading "# the eagle flies over the cars"
    is not a car. ``None`` when the code does not parse.
    """
    import ast

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    words = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            words.append(node.id)
        elif isinstance(node, ast.Attribute):
            words.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            words.append(node.name)
        elif isinstance(node, ast.arg):
            words.append(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            words.append(node.value)
    return "\n".join(words).lower()


def undrawn(source: str, nouns) -> list[str]:
    """Things the child named that the code has, but that nothing ever draws.

    Phase 12.3's commonest broken game, measured again on the owner-test walk: "add an
    eagle" landed as ``eagle = pygame.Rect(...)`` and nothing more, the step was counted
    done, and Gary told the child "Look for the eagle. It's there." A thing is drawn when
    a name containing it is an argument to a ``pygame.draw`` call or a ``blit`` -- read
    with the parser, never guessed. ``[]`` when the code does not parse.
    """
    import ast

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    lowered = code_words(source) or ""
    drawn: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        owner = ast.unparse(func).lower()
        if not (owner.startswith("pygame.draw.") or name == "blit"):
            continue
        for arg in [*node.args, *(k.value for k in node.keywords)]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Name):
                    drawn.add(sub.id.lower())
                elif isinstance(sub, ast.Attribute):
                    drawn.add(sub.attr.lower())
    # A loop variable drawn stands for the list it walks: ``for car in cars: draw(car)``.
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and \
                node.target.id.lower() in drawn:
            drawn.add(ast.unparse(node.iter).lower())
    # Whatever the scene kit draws (Phase 13C): scene.add("cars", ..., rects=cars) draws
    # the cars, though no pygame.draw call in the game names them.
    drawn |= _scene_drawn(source)
    missing = []
    for noun in sorted(nouns):
        stem = _stem(noun)
        if stem in lowered and not any(stem in name for name in drawn):
            missing.append(noun)
    return missing


def _scene_drawn(source: str) -> set[str]:
    """The names the game's scene draws, when ``scene.draw()`` is in its loop."""
    from opennest.graphics import source as scene_source

    scene = scene_source.read(source)
    if not scene.adopted:
        return set()
    names = set()
    for entry in scene.entries.values():
        names |= {entry.name.lower(), *(n.lower() for n in (entry.target, entry.wraps) if n)}
        # What it is drawn as counts too: the player wearing assets/eagle.png draws the
        # eagle, though nothing in the game is called that.
        names.add(entry.look.lower())
    return names


def made_every_frame(source: str, nouns) -> list[str]:
    """Things the child named that the game loop makes again on every frame.

    Phase 12.3's other broken shape (SPIKES.md section 23C), seen again on the owner-test
    walk: ``eagle = pygame.Rect(300, 200, 30, 30)`` inside ``while running:``, so the
    eagle is put back where it started sixty times a second and cannot go anywhere --
    while the reply said it was "flying left and right". Read with the parser: a name
    holding a child's word, assigned a ``pygame.Rect(...)`` inside the loop that flips.
    """
    import ast

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    found = []
    for loop in (node for node in tree.body if isinstance(node, ast.While)):
        calls = {ast.unparse(n.func) for n in ast.walk(loop) if isinstance(n, ast.Call)}
        if not calls & {"pygame.display.flip", "pygame.display.update"}:
            continue
        for node in ast.walk(loop):
            call = node.value if isinstance(node, (ast.Assign, ast.Expr)) else None
            if isinstance(call, ast.Call) and ast.unparse(call.func).endswith(".add") and \
                    call.args and isinstance(call.args[0], ast.Constant) and \
                    isinstance(call.args[0].value, str):
                # scene.add(...) inside the loop puts the thing back where it started on
                # every frame, the same as a Rect made there.
                name = call.args[0].value.lower()
                found += [noun for noun in sorted(nouns)
                          if _stem(noun) in name and noun not in found]
                continue
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and ast.unparse(node.value.func) in ("pygame.Rect", "Rect")):
                continue
            for target in node.targets:
                name = target.id.lower() if isinstance(target, ast.Name) else ""
                found += [noun for noun in sorted(nouns)
                          if name and _stem(noun) in name and noun not in found]
    return found


#: Collision checks that are true on every frame two things overlap.
_OVERLAPS = ("colliderect", "collidelist", "collidelistall", "collideobjects", "touching")
#: What moves one of the two apart, so the next frame no longer overlaps.
_SEPARATES = ("respawn", "remove", "pop", "kill", "reset", "clear")


def counted_every_frame(source: str) -> list[str]:
    """Counters the game changes on every frame a touch lasts, as sentences for Gary.

    Measured in Luna's space run (SPIKES.md section 28M): ``if scene.touching(player,
    "asteroids"): hits += 1`` showed "HITS 18" for one bump in two and a half seconds, and
    ``lives -= 1`` the same way takes every life in one touch. Read with the parser: an
    ``if`` (or ``for``) in the game loop headed only by an overlap check, whose body adds
    to or takes from a number and moves nothing apart -- a collected coin that respawns
    is counted once, and a check with its own guard (``and not hit_before``) is left
    alone. ``scene.touched`` counts once per touch, and is what each sentence points to.
    """
    import ast

    from opennest.graphics import looks
    from opennest.graphics import source as scene_source

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    loop = scene_source.main_loop(tree)
    if loop is None:
        return []
    scene = scene_source.read(source)
    counts = scene.adopted and "touched" in looks.kit_methods()

    def overlap(head) -> ast.Call | None:
        if isinstance(head, ast.Compare) and len(head.ops) == 1:
            head = head.left                   # player.collidelist(cars) != -1
        if isinstance(head, ast.Call) and isinstance(head.func, ast.Attribute) and \
                head.func.attr in _OVERLAPS:
            return head
        return None

    found = []
    for node in (n for stmt in loop.body for n in ast.walk(stmt)):
        head = node.test if isinstance(node, ast.If) else node.iter if isinstance(
            node, ast.For) else None
        call = overlap(head)
        if call is None:
            continue
        body = [n for stmt in node.body for n in ast.walk(stmt)]
        counters = [n for n in body if isinstance(n, ast.AugAssign)
                    and isinstance(n.target, ast.Name) and isinstance(n.op, (ast.Add, ast.Sub))]
        apart = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in _SEPARATES for n in body) or any(
            isinstance(n, ast.Assign) and any(isinstance(t, (ast.Attribute, ast.Subscript))
                                               for t in n.targets) for n in body)
        if not counters or apart:
            continue
        def code(part) -> str:                 # as the game writes it, quotes and all
            return ast.get_source_segment(source, part) or ast.unparse(part)

        counter, check = code(counters[0]), code(call)
        if counts and call.func.attr == "touching":
            instead = f"{scene.variable}.touched({', '.join(code(a) for a in call.args)})"
        elif counts and len(call.args) == 1:
            instead = f"{scene.variable}.touched({code(call.func.value)}, " \
                      f"{code(call.args[0])})"
        else:
            instead = ""
        way = (f"{instead} is true only in the frame a touch begins" if instead else
               "count it only in the frame a touch begins, by remembering whether they "
               "were touching the frame before")
        sentence = (f"`{counter}` runs on every frame of a touch ({check}), so a touch "
                    f"lasting one second changes it about 60 times. If it should happen "
                    f"once per touch -- a hit, a point, a catch, a lost life -- {way}.")
        if sentence not in found:
            found.append(sentence)
    return found[:3]


def _drawn_under_the_scene(scene) -> list[str]:
    """What the loop draws by hand between the fill and ``scene.draw()`` -- painted over.

    Measured on the second 4B walk (SPIKES.md section 28E): asked for something more
    colourful, the model drew a "glow" round the eagle straight after screen.fill, where
    the prompt had always said to draw, and the sky covered it on every frame. Gary told
    the child the eagle had a glow.
    """
    import ast

    from opennest.graphics import source as scene_source

    loop = scene_source.main_loop(scene.tree) if scene.tree is not None else None
    if loop is None or scene.draw_line is None:
        return []
    fill = next((stmt.lineno - 1 for stmt in loop.body if isinstance(stmt, ast.Expr)
                 and isinstance(stmt.value, ast.Call)
                 and ast.unparse(stmt.value.func).endswith(".fill")), None)
    if fill is None or fill > scene.draw_line:
        return []
    found = []
    for stmt in loop.body:
        line = stmt.lineno - 1
        if not fill < line < scene.draw_line:
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and (ast.unparse(node.func).startswith(
                    "pygame.draw.") or ast.unparse(node.func).endswith(".blit")):
                args = node.args[2:] if ast.unparse(node.func).startswith("pygame.draw.") \
                    else node.args[:1]
                names = [ast.unparse(arg) for arg in args][:1] or ["something"]
                found += [name for name in names if name not in found]
    return found[:4]


def _flips_per_frame(source: str) -> int:
    """How many times the game loop shows a picture each time round: its own flips."""
    import ast

    from opennest.graphics import source as scene_source

    try:
        loop = scene_source.main_loop(ast.parse(source))
    except (SyntaxError, ValueError):
        return 0
    if loop is None:
        return 0
    return sum(1 for stmt in loop.body if isinstance(stmt, ast.Expr) and isinstance(
        stmt.value, ast.Call) and ast.unparse(stmt.value.func) in (
            "pygame.display.flip", "pygame.display.update"))


def _draw_calls(source: str) -> int:
    import ast

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return 0
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.Call) and (
        ast.unparse(node.func).startswith("pygame.draw.")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "blit")))


def describe_game(project: Project, *, for_child: bool = False) -> str:
    """What is in the game, read from the code -- or "" when it cannot be said.

    The Fast Path's ``brief`` knows the player and the things recipes add under their
    naming convention, and says "Nothing else is in the game yet" otherwise. Code Gary
    wrote under his own names -- five cars drawn in a ``for`` loop -- is invisible to it,
    so when anything besides the player is drawn, that sentence is not said.
    """
    from opennest.fastpath.kinds import games  # lazily: an optional collaborator

    facts = games.facts(project)
    brief = games.brief(facts) if facts.has("loop") else ""
    if not brief or "changed a lot" in brief:
        return ""
    source = facts.get("source") or ""
    recipe_things = len(facts.get("things") or {})
    if "Nothing else is in the game yet." in brief and _draw_calls(source) > 1 + recipe_things:
        look = (f"click {_entry(project)} in the Project panel to see its code"
                if for_child else "read the code to know what")
        brief = brief.replace("Nothing else is in the game yet.",
                              f"It draws other things too -- {look}.")
    return brief


def _game_lines(project: Project, source: str, asked=()) -> list[str]:
    """What is in the game and how it is played, read from the code itself."""
    # Lazily: the Fast Path is an optional collaborator, and these are two of its parsers.
    from opennest.fastpath.kinds import games

    lines = []
    brief = describe_game(project)
    if brief:
        lines.append(f"- In the game right now, read from the code: {brief}")
    lines += _scene_lines(project, source)
    controls = games.controls_read(source)
    if controls is None:
        lines.append("- Its controls cannot be read: the code does not parse. Do not guess "
                     "them.")
    elif controls:
        lines.append("- The controls the code actually reads: " + "; ".join(controls) + ".")
    else:
        lines.append("- The code reads no keys and no mouse, so there is nothing to press.")
    flips = _flips_per_frame(source)
    if flips > 1:
        # Measured on the 13C walk (SPIKES.md section 28E): an edit copied the loop's body
        # into itself, so every time round the screen was drawn twice -- the scene, then a
        # dark fill with only the coins -- and the game flickered between the two. The
        # playtest passes a game like that; the child sees it at once.
        lines.append(f"- The game loop shows {flips} different pictures each time round "
                     f"(pygame.display.flip is called {flips} times), so what is on screen "
                     f"flickers between them. One flip at the end of the loop is right.")
    for noun in undrawn(source, asked):
        lines.append(f"- The code has {noun} in it, but nothing draws it, so it is not on "
                     f"screen.")
    for noun in made_every_frame(source, asked):
        lines.append(f"- The {noun} is made again inside the game loop every frame, so it "
                     f"is put back where it started each time and cannot move anywhere.")
    lines += [f"- {sentence}" for sentence in counted_every_frame(source)]
    return lines


def _scene_lines(project: Project, source: str) -> list[str]:
    """The game's scene, from its code, and the window it is drawn in (Phase 13C)."""
    from opennest.fastpath.kinds import games
    from opennest.graphics import source as scene_source

    lines = []
    facts = games.facts_of(source, _entry(project))
    constants = facts.get("constants") or {}
    width = constants.get(facts.get("width", "WIDTH"))
    height = constants.get(facts.get("height", "HEIGHT"))
    if width is not None and height is not None:
        lines.append(f"- The game window is {width.value} wide and {height.value} tall; "
                     f"x grows to the right and y downwards.")
    scene = scene_source.read(source)
    if not scene.adopted:
        return lines
    things = scene_source.describe(scene, facts.get("player"))
    if things:
        # Said as a list, not indented like code: measured on the test04 replays, both
        # models copied one of these lines into edit_file as the text to replace.
        lines.append("- The game's scene, read from its code and drawn back to front -- "
                     "described in words, not the code itself; game_object changes any of "
                     "these by name:\n" + "\n".join(f"  * {thing}" for thing in things))
    skies = [entry for entry in scene.entries.values() if entry.look_class == "Sky"]
    background = facts.get("background")
    if skies and background and skies[0].look == f"Sky({background})":
        lines.append(f"- The sky covers the whole screen and is drawn in {background}'s "
                     f"colour, so changing {background} changes the sky.")
    elif skies:
        lines.append(f"- A sky covers the whole screen, so the screen.fill colour"
                     f"{' ' + background if background else ''} is never seen: the sky's "
                     f"colour is the background now.")
    hidden = _drawn_under_the_scene(scene)
    if hidden:
        sky = any(entry.look_class == "Sky" for entry in scene.entries.values())
        covered = " -- and the sky covers the whole screen, so the child never sees it" \
            if sky else ""
        lines.append(f"- The code draws {', '.join(hidden)} after screen.fill but before "
                     f"scene.draw(), so the scene is drawn over "
                     f"{'it' if len(hidden) == 1 else 'them'}{covered}. Drawing done by "
                     f"hand goes after scene.draw().")
    kit = project.directory / "src" / "scene.py"
    if kit.is_file():
        # Measured (SPIKES.md section 28E): a crash whose traceback ended in the kit sent
        # the 4B to edit and re-read all of src/scene.py, twelve calls and nine minutes.
        lines.append("- src/scene.py is Open Nest's scene kit: game_object uses it for you. "
                     "Do not read or change it -- change the game in "
                     f"{_entry(project)}.")
    if not kit.is_file():
        lines.append("- The game imports scene, but src/scene.py is missing: it cannot run "
                     "until game_object puts the kit back.")
    return lines


def _screen_lines(project: Project, toolbox) -> list[str]:
    """Whether the game on screen and the last test are about the files as they are."""
    lines = []
    now = None
    run = getattr(toolbox, "last_run", None)
    if run is not None and run.still_running and plays_in_panel(project):
        process = run.process
        alive = process is not None and process.poll() is None and not (
            run.output is not None and run.output.stopped)
        if alive:
            now = source_fingerprint(project.directory)
            if toolbox.last_run_files == now:
                lines.append("- The game in the Build / Preview panel is running, and it is "
                             "the current code.")
            else:
                lines.append("- The game in the Build / Preview panel is an OLDER version: "
                             "the files changed after it started. Run Game again shows the "
                             "new one.")
        else:
            lines.append("- The game is not running now.")
    test = getattr(toolbox, "last_playtest", None)
    if test is not None:
        now = now if now is not None else source_fingerprint(project.directory)
        if toolbox.last_playtest_files != now:
            lines.append("- The files have changed since Open Nest last tested the game.")
        elif test.failed:
            lines.append(f"- Open Nest's last test of this exact code, with no window: it "
                         f"FAILED ({test.verdict.replace('_', ' ')}).")
        else:
            moved = "things moved on their own" if test.moved_by_itself else \
                "nothing moved on its own"
            lines.append(f"- Open Nest's last test of this exact code, with no window: it "
                         f"ran and drew pictures; {moved}. That shows it runs, not that it "
                         f"does what they asked.")
            lines += _drew_lines(test)
    return lines


def _drew_lines(test) -> list[str]:
    """What the scene drew in the last test, and anything it never showed on screen."""
    scene = getattr(test, "scene", ())
    if not scene:
        return []
    drew = "; ".join(f"{item['name']} ({item['look']}"
                     f"{', ' + str(item['count']) if item['count'] > 1 else ''})"
                     for item in scene if item["frames"])
    lines = [f"- In that test the scene drew, back to front: {drew}."] if drew else []
    hidden = [item["name"] for item in scene if item["frames"] and not item["on_screen"]]
    never = [item["name"] for item in scene if not item["frames"]]
    if hidden:
        lines.append(f"- {', '.join(hidden)} {'was' if len(hidden) == 1 else 'were'} drawn "
                     f"but never on screen, so the child cannot see "
                     f"{'it' if len(hidden) == 1 else 'them'}.")
    if never:
        lines.append(f"- {', '.join(never)} {'is' if len(never) == 1 else 'are'} in the "
                     f"scene but {'was' if len(never) == 1 else 'were'} never drawn.")
    return lines


# ------------------------------------------------------------- the other project types

def family(project: Project) -> str | None:
    """Which kind of project this is: its type, or what a Blank one's files have become."""
    try:
        from opennest.fastpath.kinds import family_for  # lazily: an optional collaborator
    except ImportError:
        return project.profile.id
    found, _why = family_for(project)
    return found


class _Page:
    """Headings, sections and pictures in an HTML file, read with the standard parser."""

    def __init__(self, text: str) -> None:
        from html.parser import HTMLParser

        self.headings: list[tuple[str, str]] = []
        self.sections = 0
        self.pictures: list[str] = []
        self.menu: list[str] = []
        self.ids: list[str] = []
        self.figures = 0
        page = self

        class Reader(HTMLParser):
            heading: str | None = None
            words: list[str] = []
            in_nav = 0
            link: list[str] | None = None

            def handle_starttag(self, tag, attrs):
                named = dict(attrs).get("id")
                if named and named not in page.ids:
                    page.ids.append(named)
                if tag == "figure":
                    page.figures += 1
                if tag == "nav":
                    self.in_nav += 1
                elif tag == "a" and self.in_nav:
                    self.link = []
                if tag in ("h1", "h2", "h3"):
                    self.heading, self.words = tag, []
                elif tag == "section":
                    page.sections += 1
                elif tag == "img":
                    source = dict(attrs).get("src") or ""
                    if source:
                        page.pictures.append(source)

            def handle_data(self, data):
                if self.heading:
                    self.words.append(data)
                if self.link is not None:
                    self.link.append(data)

            def handle_endtag(self, tag):
                if tag == "nav":
                    self.in_nav = max(0, self.in_nav - 1)
                elif tag == "a" and self.link is not None:
                    words = " ".join("".join(self.link).split())
                    if words:
                        page.menu.append(words)
                    self.link = None
                if tag == self.heading:
                    words = " ".join("".join(self.words).split())
                    if words:
                        page.headings.append((tag, words))
                    self.heading = None

        Reader().feed(text)


def missing_pictures(project: Project, pages=None) -> list[str]:
    """Pictures a page shows that are not files in the project (remote ones aside)."""
    found = []
    paths = ([project.directory / page for page in pages] if pages is not None
             else sorted((project.directory / "src").rglob("*.html")))
    for path in paths:
        try:
            page = _Page(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        found += [src for src in page.pictures if "://" not in src and not src.startswith(
            "data:") and not (path.parent / src).exists() and not (project.directory / src)
            .exists() and src not in found]
    return found


def _website_lines(project: Project) -> list[str]:
    lines = []
    for path in sorted((project.directory / "src").rglob("*.html")):
        try:
            page = _Page(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        name = str(path.relative_to(project.directory))
        titles = "; ".join(f"\u201c{words}\u201d" for _tag, words in page.headings[:12])
        menu = ", ".join(page.menu[:10])
        ids = ", ".join(page.ids[:14])
        # Things that are not sections with headings count too: measured, a gallery of
        # five figures with no heading was answered "No gallery of dinosaur cards exists".
        extras = [f"{page.figures} figure{'' if page.figures == 1 else 's'}"] \
            if page.figures else []
        extras += [f"{len(page.pictures)} picture{'' if len(page.pictures) == 1 else 's'}"] \
            if page.pictures else []
        lines.append(f"- {name}, read from the file: {page.sections} section"
                     f"{'' if page.sections == 1 else 's'}; headings {titles or '(none)'}; "
                     f"{'menu links ' + menu if menu else 'no menu'}"
                     f"{'; ' + ', '.join(extras) if extras else ''}"
                     f"{'; element ids ' + ids if ids else ''}.")
        missing = [src for src in page.pictures if "://" not in src
                   and not (path.parent / src).exists() and not (project.directory / src).exists()]
        if missing:
            lines.append(f"- It shows pictures that are not in the project, so they appear "
                         f"broken: {', '.join(missing[:6])}.")
    lines.append("- Nobody in Open Nest can see the page -- only the child, with Preview. What "
                 "is known is what the files say.")
    return lines


def _arduino_lines(project: Project, toolbox) -> list[str]:
    import re as _re

    lines = []
    sketch = project.entrypoint_path
    try:
        source = sketch.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        source = ""
    pins = _re.findall(r"^\s*(?:const\s+)?(?:int|byte|uint8_t)\s+(\w*PIN\w*)\s*=\s*([^;]+);",
                       source, _re.MULTILINE)
    if pins:
        said = "; ".join(f"{name} = {value.strip()}"
                         + (" (the board's own light, no wire)"
                            if value.strip() == "LED_BUILTIN" else "")
                         for name, value in pins)
        lines.append(f"- Pins the sketch uses, read from the code: {said}.")
    else:
        lines.append("- The sketch names no pins.")
    doing = _sketch_does(project)
    if doing:
        lines.append(f"- What it does, read from the code: {doing}")
    board = project.manifest.arduino_board
    lines.append(f"- Board chosen beside Compile: {board}." if board else
                 "- No board is chosen yet. They pick theirs beside the Compile button; "
                 "until then it cannot compile, and no pin on a real board is known.")
    run = getattr(toolbox, "last_run", None)
    if run is not None and not run.still_running:
        lines.append("- The last compile worked. That checks the code only, not a board."
                     if run.ok else "- The last compile FAILED (the error is above).")
    lines.append("- Nothing in Open Nest can see or test the board. After Send to Board, only "
                 "the child can say what it does.")
    return lines


def _sketch_does(project: Project) -> str:
    """The blink the sketch's loop() really does, from its constants -- or "".

    Measured on the stress pass (SPIKES.md section 29): after an Undo back to the
    starter, Luna told the child "the sketch is back to the starter, so it does not blink
    yet" -- the starter blinks, and nothing Gary was handed said so."""
    try:
        from opennest.fastpath.kinds import arduino

        facts = arduino.facts(project)
    except Exception:  # noqa: BLE001 - a fact that cannot be read is simply not said
        return ""
    constants = facts.get("constants") or {}
    if not (facts.has("blink_times") and facts.has("led_writes")):
        return ""
    pin = constants.get("LED_PIN")
    light = ("the board's own light (LED_BUILTIN)" if pin is not None and
             pin.value == "LED_BUILTIN" else f"the light on {pin.value}" if pin else
             "the light")
    return (f"loop() turns {light} on for {constants['ON_MILLISECONDS'].value} ms and off "
            f"for {constants['OFF_MILLISECONDS'].value} ms, over and over -- it blinks.")


def _pi_lines(project: Project) -> list[str]:
    lines = []
    try:
        from opennest.fastpath.kinds import raspberry_pi

        facts = raspberry_pi.facts(project)
        about = raspberry_pi.brief(facts)
    except Exception:  # noqa: BLE001 - a fact that cannot be read is simply not said
        about = ""
    if about:
        lines.append(f"- What it does, read from the code: {about}")
    lines.append("- Test on Mac runs it here with pretend pins and prints what the pins would "
                 "do. Nothing has run on a real Raspberry Pi, so nobody has seen a light or a "
                 "motor.")
    return lines


def _table_lines(path: Path, name: str) -> list[str]:
    """What is really in a CSV: rows, columns, the words in each text column, number
    ranges. Measured: asked "what's in my data?" the model named four cities the file
    does not have."""
    import csv

    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        return []
    if not rows:
        return [f"- {name} is empty."]
    header, body = rows[0], rows[1:5001]
    parts = []
    for index, column in enumerate(header[:12]):
        cells = [row[index].strip() for row in body if index < len(row) and row[index].strip()]
        try:
            numbers = [float(cell) for cell in cells]
        except ValueError:
            numbers = []
        if numbers:
            parts.append(f"{column} from {min(numbers):g} to {max(numbers):g}")
        else:
            values = list(dict.fromkeys(cells))
            shown = ", ".join(values[:6]) + (f" and {len(values) - 6} more"
                                             if len(values) > 6 else "")
            parts.append(f"{column} ({shown})" if values else column)
    return [f"- {name}, read from the file: {len(rows) - 1} rows. " + "; ".join(parts) + "."]


def _data_and_picture_lines(project: Project, toolbox) -> list[str]:
    from opennest.execution import outputs
    from opennest.security.sandbox import visible_files

    lines = []
    tables = [p for p in sorted((project.directory / "data").rglob("*.csv"))]
    tables += [p for p in sorted((project.directory / "src").rglob("*.csv"))]
    for table in tables[:3]:
        lines += _table_lines(table, str(table.relative_to(project.directory)))
    pictures = [relative for relative in visible_files(project.directory)
                if Path(relative).suffix.lower() in outputs.IMAGE_SUFFIXES
                and not relative.startswith(("assets/", "data/"))]
    made = set(getattr(toolbox, "last_made", ()) or ())
    if pictures:
        said = ", ".join(f"{picture}{' (drawn by the last run)' if picture in made else ''}"
                         for picture in pictures[:6])
        lines.append(f"- Pictures the project's own code has drawn: {said}. The newest shows "
                     f"in Build / Preview after a run; clicking one in the Project panel shows "
                     f"it too.")
    elif tables:
        lines.append(f"- No chart exists yet: the code has not drawn one. Running it "
                     f"({project.profile.run_label}, or run_project) is what draws one.")
    return lines


#: A colour word, and the colour families a page's values may have for it to be true --
#: generous at the edges: "coral" is fine on an orange, a pink or a red.
COLOUR_WORDS = {
    "red": {"red", "pink"}, "crimson": {"red"}, "scarlet": {"red"}, "cherry": {"red"},
    "orange": {"orange", "red"}, "coral": {"orange", "pink", "red"},
    "peach": {"orange", "pink"}, "tangerine": {"orange"}, "amber": {"orange", "yellow"},
    "yellow": {"yellow", "orange"}, "gold": {"yellow", "orange"},
    "golden": {"yellow", "orange"}, "lemon": {"yellow"}, "green": {"green", "teal"},
    "lime": {"green", "yellow"}, "mint": {"green", "teal"}, "teal": {"teal", "green", "blue"},
    "turquoise": {"teal", "blue"}, "cyan": {"teal", "blue"}, "aqua": {"teal", "blue"},
    "blue": {"blue", "teal", "purple"}, "navy": {"blue"}, "purple": {"purple", "pink"},
    "violet": {"purple"}, "lavender": {"purple"}, "lilac": {"purple", "pink"},
    "pink": {"pink", "red", "purple"}, "magenta": {"pink", "purple"},
    "brown": {"brown", "orange"}, "black": {"black"}, "white": {"white"},
    "gray": {"gray"}, "grey": {"gray"}, "silver": {"gray", "white"},
}
#: CSS's own colour names that pages use most, by value.
_CSS_NAMED = {
    "red": (255, 0, 0), "orange": (255, 165, 0), "yellow": (255, 255, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "purple": (128, 0, 128),
    "pink": (255, 192, 203), "brown": (165, 42, 42), "black": (0, 0, 0),
    "white": (255, 255, 255), "gray": (128, 128, 128), "grey": (128, 128, 128),
    "gold": (255, 215, 0), "coral": (255, 127, 80), "tomato": (255, 99, 71),
    "salmon": (250, 128, 114), "crimson": (220, 20, 60), "orangered": (255, 69, 0),
    "darkorange": (255, 140, 0), "khaki": (240, 230, 140), "lime": (0, 255, 0),
    "limegreen": (50, 205, 50), "forestgreen": (34, 139, 34), "seagreen": (46, 139, 87),
    "teal": (0, 128, 128), "turquoise": (64, 224, 208), "cyan": (0, 255, 255),
    "aqua": (0, 255, 255), "skyblue": (135, 206, 235), "navy": (0, 0, 128),
    "royalblue": (65, 105, 225), "dodgerblue": (30, 144, 255), "violet": (238, 130, 238),
    "indigo": (75, 0, 130), "magenta": (255, 0, 255), "hotpink": (255, 105, 180),
    "lavender": (230, 230, 250), "beige": (245, 245, 220), "tan": (210, 180, 140),
    "chocolate": (210, 105, 30), "sienna": (160, 82, 45), "silver": (192, 192, 192),
    "lightgray": (211, 211, 211), "darkgray": (169, 169, 169),
}


def colour_family(rgb) -> str:
    """The plain name a child would give a colour: its hue, or black / white / gray."""
    import colorsys

    red, green, blue = (max(0, min(255, int(v))) / 255 for v in rgb[:3])
    hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
    hue *= 360
    if light > 0.93:
        return "white"
    if light < 0.12:
        return "black"
    if sat < 0.15:
        return "white" if light > 0.85 else "black" if light < 0.2 else "gray"
    if hue < 12 or hue >= 345:
        return "brown" if light < 0.3 else "pink" if light > 0.75 else "red"
    if hue < 45:
        return "brown" if light < 0.35 else "orange"
    if hue < 70:
        return "yellow"
    if hue < 165:
        return "green"
    if hue < 200:
        return "teal"
    if hue < 255:
        return "blue"
    if hue < 290:
        return "purple"
    return "pink"


def page_colours(project: Project) -> tuple[set[str], set[str]]:
    """The colour families a website's own files use, and the colour words in them.

    Read from every .css and .html file under src/: hex, rgb() and hsl() values and CSS's
    colour names, each given its plain name (``colour_family``). The words -- "orange"
    in a class name, a comment or the page's own text -- are kept too, so a colour named
    anywhere in the files is never said to be missing."""
    import colorsys
    import re as _re

    families, words = set(), set()
    for path in sorted((project.directory / "src").rglob("*")):
        if path.suffix.lower() not in (".css", ".html"):
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except (OSError, UnicodeDecodeError):
            continue
        words |= set(_re.findall(r"[a-z]+", text)) & set(COLOUR_WORDS)
        for value in _re.findall(r"#([0-9a-f]{6}|[0-9a-f]{3})\b", text):
            if len(value) == 3:
                value = "".join(c * 2 for c in value)
            families.add(colour_family(tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))))
        for numbers in _re.findall(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)", text):
            families.add(colour_family(tuple(int(n) for n in numbers)))
        for h, sat, light in _re.findall(r"hsla?\(\s*(\d+)[a-z]*[,\s]+(\d+)%[,\s]+(\d+)%",
                                          text):
            rgb = colorsys.hls_to_rgb(int(h) / 360, int(light) / 100, int(sat) / 100)
            families.add(colour_family(tuple(v * 255 for v in rgb)))
        for name in _re.findall(r"[:\s,(]([a-z]+)\b", text):
            if name in _CSS_NAMED:
                families.add(colour_family(_CSS_NAMED[name]))
    return families, words


def summary_for_child(project: Project) -> str:
    """One or two plain sentences on what the project has, from its files -- for the
    replies Open Nest writes itself when Gary's answer could not be used."""
    kind = family(project)
    if kind == "website":
        entry = project.entrypoint_path
        try:
            page = _Page(entry.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return ""
        # The title and the section headings, not every card's: measured on the stress
        # pass, "the page has 4 sections: " followed by eight headings read as a count
        # that did not add up (SPIKES.md section 29).
        main = [words for tag, words in page.headings if tag in ("h1", "h2")] or \
            [words for _tag, words in page.headings]
        titles = ", ".join(f"\u201c{words}\u201d" for words in main[:8])
        return (f"Right now the page has {page.sections} section"
                f"{'' if page.sections == 1 else 's'}"
                f"{', with the headings ' + titles if titles else ''}. "
                f"Press {project.profile.run_label} to see it.")
    lines = (_arduino_lines(project, None) if kind == "arduino" else
             _pi_lines(project) if kind == "raspberry_pi" else [])
    lines += _data_and_picture_lines(project, None)
    # Written for Gary, said to the child: not "What it does, read from the code: ..."
    # (measured on the stress pass, when Sonnet's answer came back empty).
    said = " ".join(line[2:].replace("What it does, read from the code: ", "")
                    .replace(", read from the code:", ":") for line in lines[:2])
    where = f" Its code is {_entry(project)}, in the Project panel on the left." \
        if project.entrypoint_path.is_file() else ""
    return f"Right now: {said}{where}" if said else ""


def _blank_limits(project: Project, kind: str | None) -> list[str]:
    """What a Blank project cannot do, when its files have become something that needs to.

    Blank's one button runs ``src/main.py``. A web page or an Arduino sketch in it is
    written and kept, but not shown or compiled -- a real limit, said rather than hidden."""
    if project.profile.id != "blank":
        return []
    if kind == "website":
        return ["- This is a Blank project: its Run button runs src/main.py, so it cannot "
                "show a web page. A Website project can preview one."]
    if kind == "arduino":
        return ["- This is a Blank project: it cannot compile or send a sketch to a board. "
                "An Arduino project can."]
    return []


def checked_block(project: Project, toolbox=None, notes: Sequence[str] = (),
                  asked=()) -> str:
    """The lines Gary is given about what is true now. Empty only if nothing is known."""
    entry = _entry(project)
    path = project.entrypoint_path
    lines = ["WHAT OPEN NEST HAS CHECKED -- true right now. Trust this over anything said "
             "earlier in the conversation, including by you."]
    lines += [f"- {note}" for note in notes if note]
    if project.profile.generates:
        return "\n".join(lines) if len(lines) > 1 else ""
    kind = family(project)
    kind_lines = []
    if kind == "website":
        kind_lines = _website_lines(project)
    elif kind == "arduino" or project.profile.can_compile:
        kind_lines = _arduino_lines(project, toolbox)
    elif kind == "raspberry_pi":
        kind_lines = _pi_lines(project)
    kind_lines += _blank_limits(project, kind)
    if project.profile.can_run:
        kind_lines += _data_and_picture_lines(project, toolbox)
    if not path.is_file():
        lines += kind_lines
        thing = "game" if project.profile.playtest == "pygame" else "project"
        # Measured on the stress pass: an empty Blank project's "what do I do now?" was
        # answered "No src/main.py file exists" -- a name the child never needs.
        lines.append(f"- There is no {entry} yet, so there is no {thing} to run or play: "
                     f"say the project is empty, without that file's name. If they want to "
                     f"build something, Open Nest sets up the starting files when they ask "
                     f"for it.")
        return "\n".join(lines)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "\n".join(lines)
    starter = unchanged_starter(project, source)
    if starter is not None:
        kit = starter.name if starter.name.lower().endswith("starter") else \
            f"{starter.name} starter"
        lines.append(f"- {entry} is exactly the {kit}, unchanged: "
                     f"{starter.description} Nothing anyone has described since is in it.")
    if _is_game(project, source):
        lines += _game_lines(project, source, asked)
    lines += kind_lines
    if toolbox is not None:
        if project.profile.can_run and getattr(toolbox, "last_run", None) is None:
            # Measured: "where did my chart go?" was answered "the chart didn't generate"
            # before anything had run. Nothing had, and that is a fact to hand over.
            chart = " and no chart" if kind == "research" else ""
            lines.append(f"- Nothing has been run yet in this session: no output{chart} "
                         f"exists until they press {project.profile.run_label}.")
        lines += _screen_lines(project, toolbox)
    return "\n".join(lines)


# ----------------------------------------------------------------------------- guide

def _run_line(profile, live: bool = False) -> str:
    label = profile.run_label
    if profile.generates:
        return f"\u201c{label}\u201d makes a picture from what they typed."
    if profile.previews:
        return f"\u201c{label}\u201d shows the page in Build / Preview."
    if profile.can_compile:
        return (f"\u201c\u2713 {label}\u201d checks the sketch; they pick their board beside "
                f"it, and \u201cSend to Board\u201d puts it on the Arduino.")
    if profile.live_view or live:
        return (f"\u201c\u25b6 {label}\u201d plays it in Build / Preview -- they click "
                f"inside the game first so it gets the keys, and Tab leaves it; \u201cStop\u201d "
                f"ends it. \u201cPop out\u201d beside the game gives it a window of its own; "
                f"\u201cPut back\u201d (or closing that window) brings it home, still playing.")
    return (f"\u201c\u25b6 {label}\u201d runs it and shows what it printed or drew in "
            f"Build / Preview; \u201cStop\u201d ends one that keeps running.")


def _new_project_line() -> str:
    """How a new project is started, from the Flight Deck's own cards. Measured on the
    stress pass: sent there from a Blank project, the child was told to click a "New
    Project" button that does not exist (SPIKES.md section 29)."""
    try:
        from opennest.projects.profiles import load_profiles

        names = [profile.name for profile in load_profiles()]
    except Exception:  # noqa: BLE001 - a guide line that cannot be read is not said
        return ""
    if not names:
        return ""
    cards = ", ".join(f"\u201c{name}\u201d" for name in names)
    return (f" On the Flight Deck, \u201cWhat do you want to make?\u201d has a card for each "
            f"kind of project -- {cards} -- and clicking one starts a new project of that "
            f"kind.")


def guide(profile, *, live: bool = False) -> str:
    """The Workbench as the child sees it, for questions about Open Nest itself.
    ``live``: Run plays a game in the panel (``plays_in_panel``), Blank included."""
    return "\n".join([
        "OPEN NEST -- THE SCREEN THEY SEE",
        "Questions about Open Nest itself -- what to do now, how to play, where something "
        "is, what a button does -- are answered from this, briefly, changing nothing. "
        "Never invent a button.",
        "- PROJECT (left): their files. Clicking one shows its code in Build / Preview "
        "with the last changes marked; a dot means changed or new since their last "
        "message. ASSETS below: things they added; \u201c+ Add to Project\u201d adds more.",
        "- BUILD / PREVIEW (middle): the code, and the result.",
        "- Buttons along the bottom: " + _run_line(profile, live) + " \u201cSave a "
        "Version\u201d keeps how it is now; \u201cUndo\u201d goes back one change; "
        "\u201cBuild Style\u201d is just build it, or build it and teach me.",
        "- Top: \u201c\u2190 Flight Deck\u201d is all their projects; \u201cModel\u201d picks "
        "the AI." + _new_project_line(),
        "- It saves by itself. There is no Publish or Share yet.",
    ])
