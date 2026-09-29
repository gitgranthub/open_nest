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
    missing = []
    for noun in sorted(nouns):
        stem = _stem(noun)
        if stem in lowered and not any(stem in name for name in drawn):
            missing.append(noun)
    return missing


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
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and ast.unparse(node.value.func) in ("pygame.Rect", "Rect")):
                continue
            for target in node.targets:
                name = target.id.lower() if isinstance(target, ast.Name) else ""
                found += [noun for noun in sorted(nouns)
                          if name and _stem(noun) in name and noun not in found]
    return found


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
    controls = games.controls_read(source)
    if controls is None:
        lines.append("- Its controls cannot be read: the code does not parse. Do not guess "
                     "them.")
    elif controls:
        lines.append("- The controls the code actually reads: " + "; ".join(controls) + ".")
    else:
        lines.append("- The code reads no keys and no mouse, so there is nothing to press.")
    for noun in undrawn(source, asked):
        lines.append(f"- The code has {noun} in it, but nothing draws it, so it is not on "
                     f"screen.")
    for noun in made_every_frame(source, asked):
        lines.append(f"- The {noun} is made again inside the game loop every frame, so it "
                     f"is put back where it started each time and cannot move anywhere.")
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
    return lines


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
    if not path.is_file():
        thing = "game" if project.profile.playtest == "pygame" else "project"
        lines.append(f"- There is no {entry} yet, so there is no {thing} to run or play. If "
                     f"they want to build something, Open Nest sets up the starting files "
                     f"when they ask for it.")
        return "\n".join(lines)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "\n".join(lines)
    starter = unchanged_starter(project, source)
    if starter is not None:
        lines.append(f"- {entry} is exactly the {starter.name} starter, unchanged: "
                     f"{starter.description} Nothing anyone has described since is in it.")
    if _is_game(project, source):
        lines += _game_lines(project, source, asked)
    if toolbox is not None:
        if project.profile.can_run and getattr(toolbox, "last_run", None) is None:
            # Measured: "where did my chart go?" was answered "the chart didn't generate"
            # before anything had run. Nothing had, and that is a fact to hand over.
            lines.append(f"- Nothing has been run yet in this session: no output and no "
                         f"chart exist until they press {project.profile.run_label}.")
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
                f"ends it.")
    return (f"\u201c\u25b6 {label}\u201d runs it and shows what it printed or drew in "
            f"Build / Preview; \u201cStop\u201d ends one that keeps running.")


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
        "the AI.",
        "- It saves by itself. There is no Publish or Share yet.",
    ])
