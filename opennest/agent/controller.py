"""The agent loop: prompt, tool calls, and the repair cycle.

WORKORDER_01 sections 17, 18 and 28.

Prompt composition is base + profile + build style + current project context + project
memory. The project context is assembled by the application from what it
deterministically knows -- the file list above all -- rather than being something the
model must go and fetch. Phase 1 measured that choice as worth 19 points of tool-selection
accuracy (SPIKES.md section 4), and section 15A applies the same rule to memory.

Both collaborators here are optional. Without a :class:`VersionHistory` nothing is
checkpointed; without a :class:`MemoryManager` nothing is remembered between threads. The
loop itself behaves identically either way, which is what keeps them separately testable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from opennest import paths
from opennest.agent import evidence
from opennest.agent.budget import (
    CORRECTION,
    PLAN,
    PRIMARY,
    RECOVERY,
    REPAIR,
    ROLLOVER,
    WRITE_GAME,
    BudgetExhausted,
    CallBudget,
    MeteredProvider,
    TurnUsage,
)
from opennest.agent.replies import (
    ANSWER_CORRECTION,
    CLAIMED_RESULT,
    CLAIMED_RUN,
    CLAIMED_SIGHT,
    NOT_ASSERTED,
    RESULT_CORRECTION,
    RUN_CORRECTION,
    SIGHT_CORRECTION,
    UNDERWAY_START,
    as_offer,
    child_nouns,
    colours_said,
    echoes,
    files_said_wrongly,
    handed_back,
    hardware_claims,
    hardware_correction,
    instructs_edit,
    is_greeting,
    is_question,
    looped,
    presentable,
    promises,
    without_coordinates,
)
from opennest.agent.tools import Step, Toolbox, ToolResult, normalise_tool_name, schemas_for
from opennest.ai.provider import (
    Message,
    ModelProvider,
    ProviderError,
    Settings,
    ToolCall,
    TruncatedReply,
)
from opennest.assets import kinds as asset_kinds
from opennest.assets import look
from opennest.assets import manager as assets
from opennest.execution import playtest
from opennest.execution.python_runner import RunResult
from opennest.graphics import block_world
from opennest.memory.manager import MemoryManager
from opennest.projects import starters as starter_kits
from opennest.projects.manager import (
    Project,
    ProjectError,
    add_starter,
    plays_in_panel,
    source_fingerprint,
)
from opennest.security.sandbox import visible_files
from opennest.versioning.checkpoint import (
    LABEL_AFTER_CHANGE,
    LABEL_BEFORE_CHANGE,
    VersionHistory,
)

if TYPE_CHECKING:
    from opennest.fastpath.router import FastPathRouter

#: WORKORDER_01 section 28: "Maximum automatic repair attempts: 3". Per turn, and shared
#: between a run that crashed and a game that failed its headless test -- one repair
#: budget, for the same reason there is one call budget.
MAX_REPAIR_ATTEMPTS = 3

#: What the child is told when the game still fails its test and the repairs are spent.
#: Each is the measured result in plain words, never a guess at the cause.
_PLAYTEST_GAVE_UP = {
    playtest.CRASHED: "it stopped with an error",
    playtest.NO_PICTURE: "the window stayed empty",
    playtest.CLOSED_ITSELF: "the window closed by itself straight away",
    playtest.FROZEN: "nothing on screen moved, even when I pressed keys",
}

#: The tool loop used to have its own iteration cap here. It no longer needs one: the
#: loop runs until the model stops asking for tools or the turn's shared call budget is
#: spent (``agent/budget.py``). One ceiling is the point -- a per-loop cap plus a
#: per-repair cap plus a rollover meant nothing counted the total.

#: Phase 1 measured a "call exactly one tool" instruction as worth 30 points of
#: single-turn selection accuracy. Carried into the multi-turn loop verbatim it actively
#: caused failure: the model read a file, then reported an edit it had never made,
#: because it had been told to stop after one call. The "do not explore" property is
#: what mattered; the "exactly one" part had to go.
#: These sentences must agree with what the tools actually do. They did not: this said
#: "to change a file, call write_file", while ``write_file`` refuses to overwrite and
#: its own schema says to use ``edit_file`` -- the Phase 2 decision SPIKES.md section 8
#: measured. Running the repair loop against the real model showed the cost: Luna
#: followed the prompt, ``write_file`` refused, and a whole repair attempt was spent
#: learning what the prompt should have said (SPIKES.md section 13).
TOOL_USE_RULES = (
    "Use your tools to actually change the project. Do not look around first -- the "
    "files in this project are listed below and you already know what exists.\n"
    "- If they ask a question -- about their project, how to play it, or how to use Open "
    "Nest -- answer it from what is below. Do not change a file to answer a question.\n"
    "- To change a file that already exists, call edit_file with the exact text to "
    "replace. This is how you make almost every change.\n"
    "- write_file only creates a file that does not exist yet. It will refuse to "
    "overwrite one that does.\n"
    "- Never say you changed, added or fixed something unless the tool call succeeded. "
    "Saying it is not doing it.\n"
    "- If they ask to run or play it, call run_project.\n"
    "- Read a file first only when you do not already know what is in it."
)

#: The verbs a model reaches for when it believes it changed the project, as
#: (past, participle, progressive). Generated into phrases below rather than written
#: out, because the hand-written list this replaced had grown asymmetric: it carried
#: ``i increased`` and not ``i've increased``, and no progressive form at all. Phase
#: 12.1 drove three real Games turns through the interface and the model said
#: **"I've increased asteroid speed to 3.0"** and **"I'm adding image loading for the
#: spaceship"** with every ``edit_file`` refused and the file byte-identical -- both
#: forms the list happened not to hold. SPIKES.md section 21 has the transcripts.
_CHANGE_VERBS = (
    ("changed", "changed", "changing"),
    ("increased", "increased", "increasing"),
    ("decreased", "decreased", "decreasing"),
    ("updated", "updated", "updating"),
    ("added", "added", "adding"),
    ("set", "set", "setting"),
    ("fixed", "fixed", "fixing"),
    ("made", "made", "making"),
    ("replaced", "replaced", "replacing"),
    ("removed", "removed", "removing"),
    ("renamed", "renamed", "renaming"),
    ("created", "created", "creating"),
    ("wrote", "written", "writing"),
    # Added after the pre-13 acceptance run, where "I moved the nervous behavior inside
    # the car loop" went to the child about a file nothing had changed.
    ("moved", "moved", "moving"),
    ("put", "put", "putting"),
    ("inserted", "inserted", "inserting"),
    ("adjusted", "adjusted", "adjusting"),
    ("tweaked", "tweaked", "tweaking"),
    ("raised", "raised", "raising"),
    ("lowered", "lowered", "lowering"),
    ("swapped", "swapped", "swapping"),
    ("rewrote", "rewritten", "rewriting"),
    ("drew", "drawn", "drawing"),
)

#: Saying it was run or tested. Only a claim when nothing ran in Gary's share of the
#: turn: the recipes' replies say "I tested it without a window", and the model copied
#: that into a turn where it had changed and run nothing (the pre-13 acceptance run).
_CLAIMED_TEST = ("i tested it", "i've tested", "i have tested", "tested it without a window",
                 "i ran it", "i've run it", "i have run it")

def _claim_phrases() -> tuple[str, ...]:
    """Past simple, present perfect and present progressive, for each verb.

    Deliberately **not** the future or modal forms. "I'll add a score" is a suggestion,
    and the Games prompt actively asks for one; flagging it would make an honest turn
    look like a lie. What is caught is the model asserting the work is done or underway.
    """
    phrases: list[str] = []
    for past, participle, progressive in _CHANGE_VERBS:
        phrases += [f"i {past}", f"i've {participle}", f"i have {participle}"]
        phrases += [f"i'm {progressive}", f"i am {progressive}"]
    return tuple(phrases)


#: Phrases a model uses when it believes it edited something. Used to catch the failure
#: above deterministically rather than trusting the prompt to have fixed it.
_CLAIMED_CHANGE = tuple(dict.fromkeys(_claim_phrases() + (
    # Said without "I": Qwen3 8B, asked "Tell me what changed the most." in a turn that
    # changed nothing, answered "The most significant change was adding the code to plot
    # ..." (the stress pass, SPIKES.md section 29).
    "change was adding", "change was making", "change was creating", "change was writing",
    "change was updating", "change was changing", "the change i made", "the changes i made",
) + tuple(
    # ...and "The only change made was removing the orange clock." (Gary Smart, the game
    # builds, SPIKES.md section 33), in a turn that changed nothing: every verb above.
    f"change{made} was {progressive}" for _past, _participle, progressive in _CHANGE_VERBS
    for made in (" made", ""))))
#: ...of which these say the work is happening now.
_CLAIMED_UNDERWAY = tuple(phrase for phrase in _CLAIMED_CHANGE
                          if phrase.startswith(("i'm ", "i am ")))

#: A first step each project type is measured to handle -- every one of these went
#: through the real model and a recipe (SPIKES.md sections 25G and 25M). Offered when a
#: turn changed nothing and nothing was even attempted, so "one small piece" has an
#: example a child can copy.
_FIRST_STEPS: dict[str, tuple[str, ...]] = {
    "games": ("Make a game where you fly around and avoid cars",
              "Add a ball that bounces around the screen"),
    "website": ("Make the background dark blue", "Change the title to My Dog Club"),
    "research": ("Graph this and tell me what changed the most",),
    "arduino": ("Make it blink faster",),
    "raspberry_pi": ("Make it blink 10 times",),
}

#: What Gary is told when he changed something and ended by saying what he will do next.
#: Telling them to ask for help -- Gary is the help -- dropped even from an answer. Only
#: that: "Ask me to build the simple website" (Luna) is how to ask, which is right.
_ASK_AGAIN = re.compile(r"\bask (?:me |someone |a grown-up )?for help\b", re.IGNORECASE)

#: Instead of "Answer <their message> again" after a request: measured on the test04
#: replays, both models then said the child's message back word for word, as Gary's.
_SAY_IT_AGAIN = ("Say again, in your own words, what you really did for them this turn -- "
                 "from the tool results above -- and what is still to do. Do not repeat "
                 "their message.")

CARRY_ON = ("You said you would do more, and then stopped. Do it now with your tools, then "
            "say only what you made. If there is nothing more to do, say what you made.")

#: How many turns back "nothing has changed lately" looks (``_quiet_lately``).
QUIET_TURNS = 3

#: How many refused edits, with nothing changed, before Open Nest stops Gary retrying the
#: same change and splits it into steps instead. Measured on the pre-13 acceptance run:
#: six refusals in a row, nothing landed, all twelve calls and 162 seconds spent.
REFUSALS_BEFORE_STEPS = 3

#: "next" when nothing is waiting: answered without a model call. Only the word "next" --
#: a bare "yes" may be answering a question Gary asked, so it still goes to him.
_JUST_NEXT = re.compile(r"^(?:next|next one|next step|the next one|do the next one)[.!]*$",
                        re.IGNORECASE)

#: A reply that carries on with a plan whenever one is waiting, however many questions
#: came in between.
_CARRY_ON = re.compile(
    r"^(?:ok\s+|okay\s+)?(?:next|next one|next step|the next one|go on|keep going|carry on|"
    r"continue|do the next one|do the next step|try again|try it again|try that again)"
    r"(?:\s+please)?[.!]*$", re.IGNORECASE)

#: ...and one that only means "yes, do what you just offered": straight after the offer.
#: A turn later a bare "yes" may be answering something else Gary asked.
_YES = re.compile(
    r"^(?:yes|yeah|yep|yup|ok|okay|sure|go ahead|do it|do that|yes please|ok do it|"
    r"sounds good|go for it|start|go)[.!]*$", re.IGNORECASE)

#: A Blank project is given a game only when the child says "game" -- the rule the whole-
#: game recipes already keep (SPIKES.md section 25N).
_NAMES_A_GAME = re.compile(r"\bgames?\b", re.IGNORECASE)

#: How a page says a thing a child names by another word. Measured on the parity walk:
#: "a menu at the top" is a ``<nav>``, the word "menu" appeared nowhere, and a false "no
#: menu" correction led Gary to deny a change that had really been made.
_PAGE_FORMS = {
    "menu": ("<nav",), "navigation": ("<nav",), "picture": ("<img",), "photo": ("<img",),
    "image": ("<img",), "pic": ("<img",), "link": ("href",), "title": ("<h1", "<title"),
    "heading": ("<h1", "<h2", "<h3"), "headline": ("<h1",), "list": ("<ul", "<ol"),
    "table": ("<table",), "form": ("<form",), "box": ("<input", "<div"),
}

#: How a game's code says a thing a child names by what it is made of. Measured on the 13C
#: walk: "the eagle flies over the town" about a scene with a sky, a road and no building.
_SCENE_FORMS = {"town": ("building", "house"), "city": ("building",),
                "village": ("house", "building"), "street": ("road",),
                # Measured on the owner's test04 replay: "the woods" about three trees was
                # corrected as "The game has no woods", and the 8B's true reply was lost.
                "wood": ("tree",), "woods": ("tree",), "forest": ("tree",),
                "jungle": ("tree",), "orchard": ("tree",), "park": ("tree",)}

#: What a Blank project can become by itself, from the child's own words: only what its
#: one Run button (``python src/main.py``) can really run. The kit's entry file becomes
#: ``src/main.py``; its other files go beside it. Measured on the parity walk: without
#: this, "Make a Pi project." became a script printing "Hello from Pi!" and "Analyze
#: this CSV." took Gary three repairs and 170 seconds.
_BLANK_BECOMES = (
    (_NAMES_A_GAME, "pygame_basic", (), "as a game"),
    (re.compile(r"\b(?:csv|data|dataset|spreadsheet|graph|chart|analy[sz]e|analysis)\b",
                re.IGNORECASE), "research_basic", ("matplotlibrc",), "as a data project"),
    (re.compile(r"\b(?:raspberry|pi|gpio)\b", re.IGNORECASE), "raspberry_pi_basic", (),
     "as a Raspberry Pi project"),
)
#: ...and what it cannot: a page to preview, a sketch to compile. Said plainly, with the
#: project type that can. Measured: Blank "Make me a website." wrote a page that its Run
#: button reported as "nothing to run", and "Write an Arduino project." became a Python
#: loop that ran until the 120-second limit.
_BLANK_CANNOT = (
    (re.compile(r"\b(?:website|web ?page|web ?site|html)\b", re.IGNORECASE),
     "show a web page", "Website"),
    (re.compile(r"\b(?:arduino|sketch)\b", re.IGNORECASE),
     "compile a sketch or send it to a board", "Arduino"),
)



@dataclass
class PlannedStep:
    """One step of a plan, and what actually happened to it -- never what was hoped."""

    text: str
    #: ``todo``, ``done`` (a file changed for it), or ``not_done`` (tried; nothing landed).
    status: str = "todo"
    #: The project's content just before the turn that made it, so an Undo that takes
    #: it back out is recognised as exactly that.
    before: tuple = ()


@dataclass
class Plan:
    """A too-big request broken into steps (``prompts/plan.txt``), done one at a time.

    The owner's first Phase 13 test: a plan made in an empty project, step 1 "done" when
    nothing had changed, a starter added underneath it, and "next" carried on to step 2
    regardless. Now a step is done only when a file changed for it, a step that did not
    land is offered again rather than skipped, and before any step runs the project is
    compared with how the last turn left it.
    """

    request: str
    steps: list[PlannedStep]
    #: The project's content when a turn last finished with this plan live.
    files: tuple = ()
    #: Whether the reply just given offered the next step, so a bare "yes" means it.
    offered: bool = False
    #: What changed the project outside a message since then (an Undo, a starter), kept
    #: until a step runs -- a question asked in between must not absorb it.
    changes: list[str] = field(default_factory=list)

    def next_index(self) -> int | None:
        return next((i for i, step in enumerate(self.steps) if step.status != "done"), None)

#: ...and phrases that plainly say it did not. A reply holding one of these is not a
#: completion claim whatever else it says, which matters for two reasons. It is exactly
#: what the correction below asks the model to produce -- "say plainly that you have not
#: changed anything yet" -- so treating a compliant answer as a fresh lie would punish
#: the model for doing the right thing. And it keeps an honest admission that happens to
#: contain a claim verb ("I haven't changed anything -- I made a mistake reading the
#: file") on the right side of the line.
_DENIED_CHANGE = (
    "haven't changed", "have not changed", "didn't change", "did not change",
    "haven't edited", "have not edited", "didn't edit", "did not edit",
    "nothing changed", "nothing has changed", "nothing was changed",
    "nothing was saved", "no changes were made", "couldn't change",
    "could not change", "wasn't able to change", "was not able to change",
)


@dataclass
class Turn:
    """What happened during one exchange, for the UI to render."""

    text: str = ""
    tool_results: list[tuple[str, ToolResult]] = field(default_factory=list)
    repair_attempts: int = 0
    gave_up: bool = False
    #: Every provider call this turn made, and what each cost. Provider-reported.
    usage: TurnUsage = field(default_factory=TurnUsage)
    #: True when the turn stopped because it hit the shared call ceiling.
    hit_call_limit: bool = False
    #: Whether an empty reply was retried once with more room.
    recovered_truncation: bool = False
    #: Ref of the checkpoint saved after this turn, if anything changed.
    checkpoint: str | None = None
    #: Whether the thread rolled over after this turn. For tests and logs only -- the
    #: child must never be told (WORKORDER_01 section 15A).
    rolled_over: bool = False
    #: Whether the model was pulled up for describing a file it has not seen. For tests
    #: and for measuring how often the prompt is not enough (SPIKES.md section 10).
    corrected_invention: bool = False
    #: Every headless test of the game this turn, in order. Empty when nothing changed or
    #: the profile has no test. For tests and for measuring the loop (SPIKES.md
    #: section 24).
    playtests: list[playtest.Playtest] = field(default_factory=list)
    #: What the Fast Path decided and did: intent, score, route, recipe, result, changed
    #: files, verification. None when no Fast Path is attached. For tests, logs and the
    #: benchmark -- never shown to the child, who only ever hears Gary (SPIKES.md
    #: section 25).
    fastpath: dict | None = None
    #: Where Gary's own share of this turn starts in ``tool_results``. Zero unless recipes
    #: already made part of the message: the honesty guard, "nothing changed" and the
    #: fallback description then look only at what *he* did, so a recipe's real change
    #: can never cover a claim of his that did not happen.
    gary_from: int = 0
    #: Said before and after Gary's reply: what the recipes made, and what is still to do.
    prefix: str = ""
    suffix: str = ""
    #: Whether a too-big request has already been broken into steps this turn. Once only.
    reduced: bool = False
    #: Files Open Nest itself created before anyone worked on the message, because the
    #: project had nothing to build on yet (``_set_up_if_empty``). Not Gary's change.
    scaffolded: tuple[str, ...] = ()
    #: Whether Open Nest started the game again as the 3D Block World this turn.
    block_world_started: bool = False
    #: What became of writing the whole game in one reply (``_write_whole_game``):
    #: "" when it was not tried, "written", or "kept the starter: <last verdict>".
    whole_game: str = ""
    #: Whether this turn's change broke a game that worked, and was put back (``_put_back``).
    put_back: bool = False
    #: Said first, before everything else: what Open Nest set up, or which step of a plan
    #: this is and what changed underneath it.
    opening: str = ""
    #: Which step of the plan this turn worked on, if any (0-based).
    plan_step: int | None = None
    #: Said last, about the plan: what is next, or that a step did not land.
    plan_note: str = ""
    #: Where the plan step's share of ``tool_results`` begins: after any recipes that made
    #: other steps first, when the plan was made this turn.
    step_from: int = 0
    #: Whether the message was a question, answered without tools or recipes.
    answered: bool = False
    #: Gary's own calls this turn, (tool, arguments, result), in order -- what a claim
    #: about a change is checked against when some of them were refused (Phase 13C).
    calls: list[tuple[str, dict, ToolResult]] = field(default_factory=list)
    #: A Blank project asked for something it cannot do (a web page, a sketch), and told
    #: which project type can -- nothing built, no model call.
    routed: bool = False
    #: The whole reply is a recipe's own words, which Open Nest wrote (``_tidy`` leaves
    #: those alone: they are not Gary handing anything back).
    by_recipe: bool = False


def scene_prompt() -> str:
    """The Games prompt's PICTURES, DRAWINGS AND THE SCENE section, as it is written there."""
    games = (paths.prompts_dir() / "games.txt").read_text(encoding="utf-8")
    start = games.index("PICTURES, DRAWINGS AND THE SCENE")
    end = games.find("\n\n", start)
    return games[start:end if end != -1 else None].strip()


def build_system_prompt(
    project: Project,
    *,
    build_style: str = "build",
    last_run: RunResult | None = None,
    memory: str = "",
    asset_context: str = "",
    guidance: str = "",
    toolbox: Toolbox | None = None,
    notes: Sequence[str] = (),
    asked: Sequence[str] = (),
    wishes: Sequence[str] = (),
) -> str:
    """The new-thread bootstrap of section 15A: base + profile + style + state + memory.

    ``asset_context`` is the imported files and what is honestly known about them
    (WORKORDER_01 section 13). It comes near the end, nearest the conversation, because
    when it is non-empty the child has usually just attached something and is talking
    about it.

    ``guidance`` is the Fast Path's known way of doing what this one message asks, with
    where the pieces go in this project's files -- present for one turn only, when the
    request was recognised but Open Nest did not make the change itself.
    """
    base = (paths.prompts_dir() / "base.txt").read_text(encoding="utf-8").strip()
    profile_prompt = project.profile.system_prompt()
    if toolbox is not None and "game_object" in toolbox.allowed and \
            "game_object" not in project.profile.tools:
        # A Blank project that has become a game has the graphics layer too (tools.
        # offers_graphics), and the words that go with it -- the ones measured with it.
        profile_prompt += "\n\n" + scene_prompt()
    style_file = "style_teach.txt" if build_style == "teach" else "style_build.txt"
    style = (paths.prompts_dir() / style_file).read_text(encoding="utf-8").strip()
    screen = evidence.guide(project.profile, live=plays_in_panel(project))
    parts = [base, profile_prompt, style, TOOL_USE_RULES, screen,
             project_state(project, last_run, toolbox=toolbox, notes=notes, asked=asked)]
    if memory:
        parts.append(memory)
    if wishes:
        parts.append(_wishes_block(wishes))
    if asset_context:
        parts.append(asset_context)
    if guidance:
        parts.append(guidance)
    return "\n\n".join(parts)


#: Writing a whole game (``_write_whole_game``): room for a program of 100-200 lines, and
#: how many times a failed test goes back. Measured (SPIKES.md section 33G): 108-180
#: lines; one repair turned Gary Smart's side-scroller from a crash into the game.
WHOLE_GAME_TOKENS = 4000
WHOLE_GAME_REPAIRS = 2
_PROGRAM = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.DOTALL)


def _whole_program(reply: str, relative: str) -> tuple[str, str]:
    """The program in a reply, and "" -- or "" and what to say about why it is not one.

    It must be complete and parse, and have the one top-level game loop -- a
    ``screen.fill`` and a ``pygame.display.flip`` in it -- that the scene layer, the
    recipes and the checked facts read; a game inside a class could not be given the
    child's pictures afterwards.
    """
    from opennest.fastpath.kinds import games  # lazily: the parser that finds the loop

    found = _PROGRAM.search(reply)
    if not found:
        return "", ("Your reply had no complete ```python code block -- it may have been "
                    "cut off. Write a shorter version of the whole game.")
    code = found.group(1)
    try:
        compile(code, relative, "exec")
    except SyntaxError as exc:
        return "", (f"That program does not parse: {exc.msg} on line {exc.lineno}. Fix it.")
    facts = games.facts_of(code, relative)
    if not all(facts.has(key) for key in ("loop", "fill", "flip", "surface")):
        return "", ("Open Nest needs the game loop at the top level of the file -- `while "
                    "running:`, not inside a function or a class -- with screen.fill(...) "
                    "and pygame.display.flip() in it, so the child's pictures and changes "
                    "can be added later. Write it that way.")
    return code, ""


#: The sentences Open Nest writes around a plan (``_reduce``, ``_framed``). In a model's
#: reply they can only have been copied from the conversation.
_OPEN_NEST_PLAN = re.compile(
    r"Here['\u2019]s a way to build it, one step at a time:|To build more on it, one step at a "
    r"time:|That was a lot to build in one go, so I split it into steps:|Want me to start "
    r"with the first one\?")


def _wishes_block(wishes: Sequence[str]) -> str:
    return WISHES_HEADING + "\n" + "\n".join(f"- \u201c{wish}\u201d" for wish in wishes)


#: What Gary is told when the message is a question (``AgentController._answering``).
ANSWER_RULES = (
    "THEY ASKED A QUESTION\n"
    "Answer that question first, in a few short sentences, from what Open Nest has "
    "checked below and from the screen described below -- those are true now, and they "
    "beat anything said earlier. Asked how to play, give the controls Open Nest read from "
    "the code and how to start the game. Asked where something is or what a button does, "
    "say where it is on the screen below. Describe only what the files really have; if "
    "something they asked about is not there, say so plainly. Nothing changes on a "
    "question: if they might want a change, ask whether they want it -- never say you "
    "are doing it now.\n"
    "Asked what to do, or for ideas -- or just greeted -- be the partner who gets them "
    "going. If a plan's next step is waiting, offer that. Otherwise, and above all while "
    "the project is still its starter, give two or three ideas they could build here, "
    "each in a few words, and show them how to ask: one sentence about what they want -- "
    "who they are, what they try to do, what gets in their way. Say they can add their own "
    "pictures with \u201c+ Add to Project\u201d. A hello gets a plain hello back first, no "
    "praise.\n"
    "If they say the game is not good, do not apologise or describe the code: say in one "
    "or two sentences what would make it play better, and ask if you should make that."
)

#: Said beside a hello or "what should I do?" while nothing has been built yet.
GETTING_STARTED = (
    "(Open Nest: they are just getting started.{hello} Then give three short ideas of your "
    "own for a game they could make here, a few words each, and show them how to ask for "
    "one -- one sentence saying who they play, what they try to do and what gets in the "
    "way. Say they can add their own pictures with \u201c+ Add to Project\u201d. Do not "
    "describe the code or the square.)")
#: ...and once the ideas have been given: help them choose, do not say them again.
STARTED_AGAIN = (
    "(Open Nest: you have already given them ideas. Do not repeat them or say hello again: "
    "help them choose -- ask which one they like, or what game they have in mind -- and "
    "show the sentence to ask with, like \u201ca game where I ride a horse and jump the "
    "fences\u201d.)")

#: Said beside a request for a whole game -- only then. Measured (tool_choice probe, the
#: real 4B): in the Games prompt on every turn, the same words took plain requests
#: ("make the player blue") from 5 of 8 acted on to 2 of 8, the rest narrated; on the
#: test04 replay they were what made it say "I'll build a 2D side-view version" and build
#: the night woods, the monster to shoot and the trees.
WHOLE_GAME = (
    "(Open Nest: this asks for a whole game. Work out what the player does, what they try "
    "to do and what gets in the way -- then build it now with your tools: the scene with "
    "game_object, one call per thing, with touch shoot, avoid or collect for what touching "
    "does, and edit_file for other rules. If it needs 3D or first person, build the "
    "closest 2D version and say so in one sentence.)")

#: Said beside a message about a game seen from above -- a maze, "top down". Measured on
#: the owner's Maze_test01: asked for "a top down view of a maze you create, no road", the
#: 4B kept the sky and the road and made its walls buildings standing on the road -- the
#: only scene it had been shown was one seen from the side.
TOP_DOWN = (
    "(Open Nest: this game is seen from above. A sky and a road are for a game seen from "
    "the side, and a maze has neither. For the maze, call game_object once with name walls "
    "and layout maze: Open Nest lays the maze out, makes its walls solid and puts the "
    "player at its start. Then put what they are looking for at the end with at "
    "\"maze end\". (touch block makes any other wall solid too.))")
_FROM_ABOVE = re.compile(r"\b(?:maze|labyrinth|top[- ]?down|from above|bird'?s[- ]eye|"
                         r"overhead view|dungeon|pac-?man)\b", re.IGNORECASE)

#: A message that asks for a whole game: "make a game where...", a kind of game.
_GENRES = re.compile(r"\b(?:shooter|platformer|racer|racing game|runner|maze|dodger|"
                     r"adventure|rpg|tower defen[cs]e|space invaders|pac-?man|mario)\b",
                     re.IGNORECASE)

#: A message that asks for a game to be made: "make a space game", "a game where ...".
#: Not "add asteroids to the game" -- a change to the game there is.
_MAKES_A_GAME = re.compile(
    r"\b(?:make|build|create|write|code|design|turn (?:it|this) into|let'?s (?:make|build|"
    r"do|have))\b[^.!?]*\bgames?\b|\bgames? (?:where|about|with|in which|that|like)\b",
    re.IGNORECASE)

#: Said beside the message, when Open Nest had the whole game written and it passed its
#: test (``_write_whole_game``). Gary's reply is what remains.
WHOLE_WRITTEN = (
    "(Open Nest: you have just written this whole game into {entry}, and Open Nest "
    "tested it without a window: it runs. Tell them in two or three sentences what the "
    "game is and how to play it, from the code. Do not change it in this turn.)")

#: Said beside a message asking to use the child's pictures, in a game with no scene yet --
#: one written whole, or built by hand. Measured on the test04 replay after the game was
#: written whole (SPIKES.md section 33H): asked to use the tree and monster pictures,
#: Gary Smart loaded them with edit_file, twelve calls a turn, and crashed the game; the
#: tool that puts a picture on the game's own things, keeping how they move, went unused.
PICTURES_BY_TOOL = (
    "(Open Nest: to put their pictures in the game, call game_object -- one call for each "
    "thing, with its name and the picture, or a list of pictures for several copies. Open "
    "Nest draws them on the game's own things of that name and keeps how they move. Do not "
    "load pictures with edit_file.)")
_PICTURE_WORDS = re.compile(r"\b(?:pictures?|images?|photos?|png)\b", re.IGNORECASE)

#: Said beside a message that says the game is not good. The rule is in ANSWER_RULES;
#: the final test04 replay's 4B answered "You are not making a good game" with the trees'
#: positions and nothing else.
NOT_GOOD = (
    "(Open Nest: they are not happy with the game. Do not apologise or describe the code. "
    "Say in one or two sentences what would make it play better -- the part of what they "
    "asked for that is still missing -- and ask if you should make it.)")
_UNHAPPY = re.compile(r"\bnot (?:making |a |very )*(?:good|fun)\b|\bbad game\b|\bboring\b|"
                      r"\bsucks\b|\bterrible\b|\bnot what i (?:want|asked)", re.IGNORECASE)

#: "What should I do first?", "any ideas?", "where do I start?" -- asking for a way in.
_WAY_IN = re.compile(
    r"\b(?:what (?:should|can|do|could) (?:i|we) (?:do|make|build|try)|any ideas|ideas? for|"
    r"some ideas|where (?:do|should) (?:i|we) (?:start|begin)|how do (?:i|we) (?:start|begin)|"
    r"what (?:can|could) (?:you|we) (?:make|build|do)|what now|help me start|"
    r"what(?:'s| is) first|get(?:ting)? started)\b", re.IGNORECASE)

#: The child's own requests this conversation, for Gary every turn: what the game is
#: meant to be. Measured on the owner's test04: by the third message the 4B had lost
#: "a game in the woods at night ... shoot monsters hiding behind trees" under its own
#: tool results, and made one tree drift left -- its own earlier suggestion.
WISHES_HEADING = (
    "WHAT THEY HAVE ASKED FOR, IN THEIR OWN WORDS (oldest first)\n"
    "Together this is the game they want. Every change should move it closer to that, "
    "and use what they told you -- the pictures they added, what each is for.")


def build_answer_prompt(project: Project, *, build_style: str = "build",
                        last_run: RunResult | None = None, memory: str = "",
                        asset_context: str = "", guidance: str = "",
                        toolbox: Toolbox | None = None, notes: Sequence[str] = (),
                        asked: Sequence[str] = (), wishes: Sequence[str] = ()) -> str:
    """The system prompt for answering a question: no tools, no building instructions.

    Measured on the owner-test walk with the ordinary prompt: "how do I undo that?" was
    answered "Undo in the top-right" (it is at the bottom), "where is the code?" with a
    red square the game does not have, and "what are the controls?" was taken by a recipe
    as a request and *changed the controls*. The building half of a profile's prompt --
    three pieces in three places -- is what a 4B model repeats when it has nothing to
    build, so a question gets the project type's first lines, the voice, the screen and
    the checked facts, and nothing it could mistake for an instruction to edit.
    """
    base = (paths.prompts_dir() / "base.txt").read_text(encoding="utf-8").strip()
    kind = "\n\n".join(project.profile.system_prompt().split("\n\n")[:2])
    style_file = "style_teach.txt" if build_style == "teach" else "style_build.txt"
    style = (paths.prompts_dir() / style_file).read_text(encoding="utf-8").strip()
    screen = evidence.guide(project.profile, live=plays_in_panel(project))
    parts = [base, kind, style, ANSWER_RULES, screen,
             project_state(project, last_run, toolbox=toolbox, notes=notes, asked=asked)]
    parts += [part for part in (memory, _wishes_block(wishes) if wishes else "",
                                asset_context, guidance) if part]
    return "\n\n".join(parts)


def _starter_facts(project: Project) -> list[str]:
    """What foundation this project was built on, when there is one recorded.

    Section 13 of the Phase 11 work order: Gary should not ask "are you using HTML?"
    about a project Open Nest knows began from the Basic Website kit. Deterministic
    application knowledge, injected like the file list rather than guessed from
    filenames -- which is the same argument SPIKES.md section 4 makes about tools.

    Silence when nothing is recorded, and that covers two different cases on purpose: a
    project started empty, and a project made before Phase 11 whose files might be a
    shipped template or might by now be entirely the child's. Saying "started empty"
    about the second would be asserting something nobody measured.
    """
    starter_id = project.manifest.starter_id
    if not starter_id:
        return []
    try:
        starter = starter_kits.get_starter(starter_id)
    except starter_kits.StarterError:
        # The kit was withdrawn from a later release. The project still has the files,
        # so name what was recorded rather than dropping the fact.
        return [f"Started from the {starter_id} starter."]
    line = f"Started from the {starter.name} starter: {starter.description}"
    if project.manifest.starter_version != starter.version:
        return [line]
    return [
        line,
        "Those files are the child's now. Change them, remove them or replace them as "
        "the project needs -- they are a beginning, not something to preserve.",
    ]


def project_state(project: Project, last_run: RunResult | None = None, *,
                  toolbox: Toolbox | None = None, notes: Sequence[str] = (),
                  asked: Sequence[str] = ()) -> str:
    """Facts the application knows for certain. Never asked of the model.

    The file list and the last run result both live here rather than behind tools. They
    are application knowledge, and Phase 1 measured that offering them as tools costs
    real accuracy because the model reaches for them instead of acting. What Open Nest
    has checked about the files, the game on screen and the last message
    (:mod:`opennest.agent.evidence`) comes last, nearest the conversation.
    """
    files = visible_files(project.directory)
    listing = "\n".join(f"  {name}" for name in files) or "  (no files yet)"
    parts = [
        "CURRENT PROJECT",
        f"Name: {project.name}",
        f"Type: {project.profile.name}",
        f"Entry point: src/{project.manifest.entrypoint}",
        f"Run action: {project.profile.run_label}",
    ]
    parts.extend(_starter_facts(project))
    parts.append(f"Files in this project (you already know these):\n{listing}")
    # The base prompt tells the model to stop rather than install a missing package, so
    # it has to be told what it already has. Deterministic, from the profile.
    if project.profile.packages:
        parts.append(
            "Packages you can import (these are installed; there are no others):\n"
            + "\n".join(f"  {name}" for name in project.profile.packages)
        )
    if last_run is not None:
        if last_run.still_running and not _still_going(last_run):
            parts.append("Last run: it started, and it has stopped since.")
        elif last_run.still_running:
            parts.append("Last run: the project started and is running now.")
        elif last_run.ok:
            parts.append("Last run: it worked.")
        else:
            parts.append(
                "The last run FAILED. This is the error, you do not need to ask for it:\n"
                + last_run.failure_text[:3000]
            )
    checked = evidence.checked_block(project, toolbox, notes, asked)
    if checked:
        parts.append(checked)
    return "\n".join(parts)


def _still_going(run: RunResult) -> bool:
    """Whether a run that survived its startup is still running now -- Stop, a newer run
    or the game ending itself all leave ``still_running`` True on the result."""
    process = run.process
    if process is None:
        return True
    stopped = run.output is not None and run.output.stopped
    return process.poll() is None and not stopped


class AgentController:
    """Drives one project's conversation with one model."""

    def __init__(
        self,
        project: Project,
        provider: ModelProvider,
        toolbox: Toolbox,
        *,
        build_style: str = "build",
        versions: VersionHistory | None = None,
        memory: MemoryManager | None = None,
        fastpath: FastPathRouter | None = None,
    ) -> None:
        self.project = project
        self.provider = provider
        self.toolbox = toolbox
        self.build_style = build_style
        #: Recognises common requests and handles them with a known recipe before the
        #: model is asked to write anything (``opennest.fastpath``). Optional, and the
        #: loop is unchanged without it; with it, every request it does not handle
        #: arrives at the loop exactly as it would have.
        self.fastpath = fastpath
        #: The Fast Path's guidance for the message being answered. One turn only, for
        #: the same reason an attachment is: it describes *this* request.
        self._guidance = ""
        #: The child's previous message, so "now make it blue" can be classified.
        self._last_request: str | None = None
        #: What the Fast Path did on the last turn, for Gary on this one. Only ever one
        #: turn old: after that the conversation history carries it.
        self._recent_note = ""
        #: A too-big request broken into steps, and what has really happened to each.
        #: "next" (or "keep going", or "yes" straight after the offer) does the first one
        #: not done; a message that changes the project some other way sets it aside.
        self._plan: Plan | None = None
        #: What the last message actually changed, in one line, for Gary on this one --
        #: and what changed outside any message since (an Undo, a starter added by hand).
        #: Both are cleared once a turn has been told them (``evidence``).
        self._last_outcome = ""
        self._outside: list[str] = []
        #: What the child did that changed no file -- pressed Run, Compile, Test on Mac --
        #: told to Gary the same way, and kept apart from changes: a press of Run is not
        #: a change, so it must not make "I updated main.py" believable (SPIKES §29).
        self._events: list[str] = []
        #: The reply an Undo just took back, until a turn has been told (``_repeats_undone``).
        self._undone = ""
        #: The project's files as the last turn left them, so a change made between
        #: messages -- a file edited outside Open Nest -- is noticed, not assumed away.
        self._files_after = source_fingerprint(project.directory)
        #: The things the child has asked for in this conversation ("eagle", "cars"), so
        #: a reply that says the game has one its code does not can be caught.
        self._asked_for: set[str] = set()
        #: The words (and pictures) Open Nest has already told the child how to make a
        #: picture for in this conversation -- said once, not every turn.
        self._offered_pictures: set[str] = set()
        #: A 3D game asked for in a game that was already built flat (so it was kept),
        #: and whether the child has been told how to start a 3D one. Once a conversation.
        self._wants_3d = False
        self._told_3d = False
        #: Saved versions. Named `versions`, not `history`, because `self.history` is
        #: already the message list -- conflating the two silently broke checkpointing.
        #: Optional so tests and headless use do not require Git.
        self.versions = versions
        #: Project memory and thread rollover. Optional for the same reason.
        self.memory = memory
        #: Files attached to the message being answered. Rebuilt each turn and never
        #: kept, the same way memory's recall hits are -- the asset itself is permanent
        #: and stays in the listing, but "this picture" only means something for the
        #: message it arrived with.
        self._attached: tuple[assets.Asset, ...] = ()
        #: The pictures attached to this message that were sent to the model as pixels.
        self._shown: tuple[str, ...] = ()
        #: Pictures already tried this session, so one that cannot be looked at (it will
        #: not open) costs one call, not one before every turn.
        self._tried_looking: set[str] = set()
        #: Set by :meth:`stop`: the project is closing, so a turn ends at its next call.
        self._stopping = False
        self.history: list[Message] = []
        self._reset_history()

    def stop(self) -> None:
        """End the turn in progress at its next safe point, because the project is closing.

        Called from the GUI thread while the turn runs on its worker; the Workbench then
        waits for that worker to finish, so nothing is torn down under it. The turn ends
        through the call budget (``CallBudget.stop``) -- exactly as a turn that ran out
        of calls ends, which every subsystem already handles -- keeping and checkpointing
        whatever it had already changed. A recipe, an edit, a run or a test already under
        way finishes first. Only for closing: this controller is not used again.
        """
        self._stopping = True
        budget = getattr(self, "_budget", None)
        if budget is not None:
            budget.stop()

    def _reset_history(self) -> None:
        """Begin a thread: one system message carrying the whole bootstrap."""
        self.history = [
            Message(role="system", content=build_system_prompt(
                self.project,
                build_style=self.build_style,
                memory=self._memory_block(),
                asset_context=self._asset_block(),
                guidance=self._guidance,
                toolbox=self.toolbox,
                notes=self._notes(),
                asked=sorted(getattr(self, "_asked_for", ())),
                wishes=getattr(self, "_wishes", ()),
            ))
        ]

    def _notes(self) -> list[str]:
        return [note for note in (getattr(self, "_last_outcome", ""),
                                  *getattr(self, "_outside", ()),
                                  *getattr(self, "_events", ())) if note]

    def note_outside_change(self, what: str, *, undone: bool = False) -> None:
        """Something changed the project outside a message: an Undo, a starter added.

        Gary is told on his next turn, among the things Open Nest has checked, and a plan
        waiting for "next" is compared with the files before its next step runs.

        ``undone``: an Undo took the last change back out, so the reply that announced it
        is marked as undone where it sits in the history. Measured on the parity walk:
        after an Undo removed a gallery, the next turn read its own "The gallery section
        is now added with five dinosaur cards" and told the child it was already there.
        """
        if undone:
            for index in range(len(self.history) - 1, 0, -1):
                message = self.history[index]
                if message.role == "assistant" and not message.tool_calls:
                    self._undone = message.content
                    self.history[index] = Message(role="assistant", content=(
                        f"{message.content}\n\n[Open Nest: the child pressed Undo after "
                        f"this, so the change described here is no longer in the files.]"))
                    break
        self._outside.append(what)
        if self._plan is not None:
            self._plan.changes.append(what)
        self.refresh_state()

    def use_provider(self, provider: ModelProvider) -> None:
        """Change which model this conversation is talking to, keeping the conversation.

        WORKORDER_01 section 4 lets a child switch models; section 38 forbids doing it
        silently, which is the caller's job -- by the time this is called the switch has
        been chosen and, for a cloud model, consented to.

        Three things move with the provider. The context budget, because the new model
        has its own (``MemoryManager.adopt``). The asset block, because what may honestly
        be said about an imported picture depends on whether *this* model can see it --
        which is the Phase 5 capability plumbing doing what it was built for. And the
        project state, which carries both.
        """
        self.provider = provider
        if self.memory is not None:
            self.memory.adopt(provider)
        self.refresh_state()

    def refresh_state(self) -> None:
        """Re-inject the file list and last run result after anything changes."""
        build = build_answer_prompt if getattr(self, "_answering", False) \
            else build_system_prompt
        self.history[0] = Message(
            role="system",
            content=build(
                self.project,
                build_style=self.build_style,
                last_run=self.toolbox.last_run,
                memory=self._memory_block(),
                asset_context=self._asset_block(),
                guidance=self._guidance,
                toolbox=self.toolbox,
                notes=self._notes(),
                asked=sorted(getattr(self, "_asked_for", ())),
                wishes=getattr(self, "_wishes", ()),
            ),
        )

    def _memory_block(self) -> str:
        return self.memory.context_block() if self.memory is not None else ""

    def _asset_block(self) -> str:
        """What the child has imported, and what is honestly known about it.

        Injected, not fetched. Section 18 lists a ``list_assets`` tool; building it would
        repeat the mistake SPIKES.md section 4 measured, so the application states what
        it already knows instead and the tool set stays at four.
        """
        return assets.context_block(
            self.project,
            getattr(self.provider, "info", None),
            attached=self._attached,
        )

    def send(
        self,
        text: str,
        *,
        attachments: Sequence[assets.Asset] = (),
        on_text: Callable[[str], None] | None = None,
        on_progress: Callable[[Step], None] | None = None,
    ) -> Turn:
        """One exchange: the child says something, the agent acts, and reports back.

        ``attachments`` are files the child dropped onto this message (WORKORDER_01
        sections 12 and 13). They are already imported into the project by the time they
        arrive here -- what this adds is that *these* are the ones being talked about.

        ``on_progress`` is told each :class:`~opennest.agent.tools.Step` as it happens --
        thinking, each file read or changed and what it now says, each run and test --
        for this turn only. The Workbench shows them; nothing here depends on them.
        """
        self.toolbox.observer = on_progress
        self.toolbox.message = (text, tuple(a.path for a in attachments))
        try:
            # Before the turn, and outside its call budget: a picture is looked at once,
            # for the picture, not for this message (``assets.look``).
            seen = self.look_at_pictures()
            if seen:
                attachments = tuple(next((a for a in seen if a.path == attached.path),
                                         attached) for attached in attachments)
            return self._send(text, attachments, on_text)
        finally:
            self.toolbox.observer = None
            self.toolbox.message = ("", ())

    def look_at_pictures(self, limit: int = 8) -> list[assets.Asset]:
        """Look at each picture in the project nothing has looked at yet, when Gary can
        see -- once per picture, ever; what was seen goes into every later prompt.

        Called by the Workbench straight after an import, so the child hears what Gary
        saw, and before every turn, for a picture that came in any other way. Each is one
        short local call, never from a turn's budget (``assets.look``), at most ``limit``
        at a time; the rest wait for the next message. Returns the pictures now seen.
        """
        if not look.can_look(self.provider):
            return []
        def tried(asset) -> str:
            # By content: a picture replaced under the same name is a new one to look at.
            try:
                return f"{asset.path}:{look.digest(self.project.directory / asset.path)}"
            except OSError:
                return asset.path

        waiting = [asset for asset in look.unlooked(self.project,
                                                    assets.list_assets(self.project))
                   if tried(asset) not in self._tried_looking][:limit]
        done: list[str] = []
        for asset in waiting:
            if self._stopping:
                break
            self._tried_looking.add(tried(asset))
            if self.toolbox.observer is not None:
                self.toolbox.observer(Step("thinking", f"looking at {asset.name}",
                                           path=asset.path))
            try:
                saw = look.look(self.project, self.provider, asset.path)
            except ProviderError:
                break
            if saw:
                done.append(asset.path)
        if not done:
            return []
        self.refresh_state()
        return [asset for asset in assets.list_assets(self.project) if asset.path in done]

    def _send(self, text: str, attachments: Sequence[assets.Asset],
              on_text: Callable[[str], None] | None) -> Turn:
        start = len(self.history)
        turn = self._answer(text, attachments, on_text)
        self._close_turn(turn, start)
        return turn

    def _answer(self, text: str, attachments: Sequence[assets.Asset],
                on_text: Callable[[str], None] | None) -> Turn:
        self._notice_changes_since_last_turn()
        self._missing_before = (evidence.missing_pictures(self.project)
                                if evidence.family(self.project) == "website" else [])
        step, opening = self._resume_plan(text)
        if step is not None:
            # "next": the child is not made to retype the step Open Nest offered.
            text = self._plan.steps[step].text
        elif _JUST_NEXT.match(text.strip()):
            # Measured on the acceptance run: "next" with nothing offered went to the model
            # as a request, and twelve calls later nothing had changed.
            turn = Turn(text="I don't have a next step lined up. Tell me what you'd like to "
                             "add or change next.")
            self.history.append(Message(role="user", content=text))
            self.history.append(Message(role="assistant", content=turn.text))
            return turn
        # Checkpoint whatever state exists before touching anything, so "undo" goes
        # back to what the child had rather than to some earlier assistant turn.
        self._checkpoint(LABEL_BEFORE_CHANGE)
        if step is not None:
            self._plan.steps[step].before = source_fingerprint(self.project.directory)
            self._guidance = self._plan_guidance(step)
        elif self._plan is not None and self._plan.next_index() is not None:
            self._guidance = self._plan_guidance(None)

        # "Like we talked about before" is answered from memory, deterministically,
        # before the model sees the message (WORKORDER_01 section 15A, memory retrieval).
        self._attached = tuple(attachments)
        if self.memory is not None:
            self.memory.recall_for(text)
        # Unconditional: a lookup that finds nothing must also clear the previous turn's,
        # or the model keeps being handed an answer to an old question -- and the same is
        # true of an attachment, which must not linger onto the next message.
        self.refresh_state()

        # A picture attached to this message travels with it as pixels, to a model that
        # really receives them: "what is this?" is answered by looking. Only this turn --
        # the history keeps the words (``_settle_history``), and what was seen is in the
        # prompt as a sentence from then on.
        self._shown = tuple(
            str(self.project.directory / asset.path) for asset in attachments
            if asset.kind == asset_kinds.IMAGE) if getattr(
                self.provider, "sees_images", False) else ()
        self.history.append(Message(role="user", content=text, images=self._shown))
        self._asked_for |= child_nouns(text)
        self._child_said = [*getattr(self, "_child_said", []), text][-40:]
        turn = Turn(opening=opening, plan_step=step)
        challenged = False
        corrected = False

        # One budget for this whole turn: the tool loop, both honesty corrections, the
        # repair cycle, a truncation retry and the rollover all spend from it. See
        # agent/budget.py for why the subsystems no longer get separate allowances.
        self._budget = CallBudget()
        if self._stopping:
            # Asked to stop before this turn had a budget to stop.
            self._budget.stop()
        turn.usage = self._budget.usage
        self._metered = MeteredProvider(self.provider, self._budget)
        #: How many of this turn's tool results the last headless test already covers.
        self._tested_through = 0
        #: The game as it was, when Open Nest's own test last passed on exactly these files
        #: -- what a turn that breaks it puts back (``_put_back``).
        self._working = self._verified_working()

        previous, self._last_request = self._last_request, text
        recent, self._recent_note = self._recent_note, ""
        if recent:
            self._guidance = "\n\n".join(part for part in (self._guidance, recent) if part)
            self.refresh_state()
        # Before anyone works on it: a project with nothing to build on gets its
        # starting files, so neither a recipe nor Gary edits a file that does not exist.
        self._set_up_if_empty(turn, text)
        self._set_up_block_world(turn, text)
        if turn.routed:
            # Blank asked for something it cannot do: said, and nothing built.
            self.history.append(Message(role="assistant", content=turn.text))
            return self._finish_turn(turn)
        # A question is answered, never built for: no recipe, no tools (``ANSWER_RULES``).
        # In both labelled sets every question-shaped message is gold "other", so no
        # recipe route is lost; "what are the controls?" no longer rewrites the controls.
        answering = step is None and is_question(text)
        if not answering and step is None and len(text.split()) >= 3 and not (
                _CARRY_ON.match(text.strip()) or _YES.match(text.strip())):
            # What the game is meant to be, in their words, kept in front of Gary.
            self._wishes = [*getattr(self, "_wishes", []), text.strip()[:300]][-6:]
        # ...except a question about a data project's data: "What changed the most?" is
        # answered by an analysis recipe that computes it, and measured on the parity
        # walk, answered without one it became "Nothing changed". Every question-shaped
        # Research message in both label sets is gold "other", so the recipe steps aside
        # for the rest and they are answered below as before.
        analysis = answering and evidence.family(self.project) == "research"
        outcome = "gary"
        # A block world has none of the shapes a game recipe is written for: its player is
        # the camera, its things are letters in WORLD (``graphics.block_world``).
        in_3d = block_world.of_project(self.project)
        if self.fastpath is not None and (not answering or analysis) and not in_3d:
            outcome = self._fast_path(turn, text, previous, attachments, on_text)
        if outcome == "handled":
            turn.by_recipe = True
            return self._finish_turn(turn)
        if outcome == "rest":
            answering = False
            text = " and ".join(turn.fastpath.get("remaining") or ()) or text

        self._answering = answering
        if answering:
            turn.answered = True
            self.refresh_state()
            # The checked facts again, beside the question itself. Measured on the parity
            # walk: with them only in the system prompt, a 4B answer followed its own
            # earlier replies instead ("The LED is on BCM pin 17" after it became 22).
            # Only in what is sent; the settled history keeps the child's own words.
            checked = evidence.checked_block(self.project, self.toolbox, self._notes(),
                                             sorted(self._asked_for))
            if checked:
                self.history[-1] = replace(self.history[-1], content=(
                    f"{text}\n\n({checked.splitlines()[0].split(' -- ')[0]}:\n"
                    + "\n".join(checked.splitlines()[1:]) + ")"))
                self._asked_text = text
            if self._getting_started(text):
                again = getattr(self, "_ideas_given", False)
                self._ideas_given = True
                # Plain words: "friendly" drew "Great to see you starting." (the final
                # 4B replay), and the brand guide rules out opening with praise.
                hello = " Say hello back in a few plain words, no praise." \
                    if is_greeting(text) else ""
                # Measured on the owner's test04 and its replays: "Hi Gary" got "Hi.
                # Ready." and "What should I do first? any ideas?" got "Run the game.
                # Watch the orange square move" -- true, and no way in. The rule is in the
                # answer prompt; beside the message is where a small model follows it.
                steer = STARTED_AGAIN if again else GETTING_STARTED.format(hello=hello)
                self.history[-1] = replace(self.history[-1], content=(
                    f"{self.history[-1].content}\n\n{steer}"))
                self._asked_text = text
            elif _UNHAPPY.search(text):
                self.history[-1] = replace(self.history[-1], content=(
                    f"{self.history[-1].content}\n\n{NOT_GOOD}"))
                self._asked_text = text
        written = None
        if not answering and step is None and outcome == "gary" and not in_3d:
            written = self._write_whole_game(turn, text)
        if not answering and step is None and plays_in_panel(self.project):
            # Beside the message, for this turn only; the settled history keeps their words.
            notes = [WHOLE_GAME] if _GENRES.search(text) or (
                _NAMES_A_GAME.search(text) and len(text.split()) >= 8) else []
            if _FROM_ABOVE.search(text) and "game_object" in self.toolbox.allowed and \
                    not self._has_maze():
                notes.append(TOP_DOWN)
            if in_3d:
                # Instead of the 2D game's guidance, never beside it: "the closest 2D
                # version" and "call game_object" are both wrong here.
                notes = [block_world.GUIDE.format(entry=f"src/{self.project.manifest.entrypoint}")]
                if turn.block_world_started:
                    notes.append(block_world.JUST_STARTED)
            elif written is not None:
                # Instead of "build it now with game_object": it is built, and tested.
                notes = [WHOLE_WRITTEN.format(entry=f"src/{self.project.manifest.entrypoint}")]
            elif self._asks_for_pictures_without_a_scene(text):
                notes.append(PICTURES_BY_TOOL)
            elif block_world.ASKS_FOR_3D.search(text) and block_world.offered(
                    self.project.profile):
                self._wants_3d = True
            if notes:
                self.history[-1] = replace(self.history[-1], content="\n\n".join(
                    [self.history[-1].content, *notes]))
                self._asked_text = text
        if written is not None:
            # What the model wrote goes into the history as the call it was, after the
            # message, so the next thing Gary says is about the game it just made.
            call, result = written
            self.history.append(Message(role="assistant", content="", tool_calls=(call,)))
            self.history.append(Message(role="tool", name=call.name, tool_call_id=call.id,
                                        content=result.content))
        try:
            turn = self._exchange(turn, text, on_text, challenged, corrected)
        except BudgetExhausted:
            turn = self._out_of_calls(turn)
        finally:
            self._answering = False
        return self._framed(turn)

    # -- the end of every turn ----------------------------------------------

    def _close_turn(self, turn: Turn, start: int) -> None:
        """Say what happened, and leave the conversation as the child saw it.

        Three things, in this order, for every turn however it ended:

        - **The words.** What Open Nest set up or which plan step this was, Gary's
          reply, and what is next in the plan -- each from what happened, never hoped.
        - **The history.** What the model reads next turn is what was done and what the
          child was told -- not every sentence Gary produced on the way. The owner's
          first Phase 13 test measured why: a reply the honesty guard caught was replaced
          on screen and kept in the history, so the next turn's model read "I added the
          eagle (a white circle)... Now the eagle flies back and forth" as its own last
          word and repeated it to the child, and closing the project summarised it into
          the project's memory as a decision. The calls and their results stay, exactly
          as they were: they are what happened.
        - **Rollover**, last, so a handover summarises that and nothing else.
        """
        self._settle_plan(turn)
        broken = self._pictures_this_turn_broke(turn)
        how = self._picture_how_to(turn) or self._three_d_how_to()
        turn.text = "\n\n".join(part for part in (turn.opening, turn.text, broken, how,
                                                   turn.plan_note) if part)
        self._settle_history(start, turn.text)
        self._record_outcome(turn)
        if not turn.hit_call_limit:
            self._roll_over_if_needed(turn)

    def _three_d_how_to(self) -> str:
        """How to get a 3D game, when one was asked for in a game already built flat.

        A 3D game is a starter (``graphics.block_world``), and Open Nest only starts a
        game again while it is still the untouched Basic Game -- never over the child's
        work. So past that point Gary builds the closest flat version (``WHOLE_GAME``) and
        the child is told, once, where the 3D one is.
        """
        if not self._wants_3d or self._told_3d:
            return ""
        self._wants_3d, self._told_3d = False, True
        return ("A game you walk through in 3D starts from Open Nest's 3D Block World. "
                "This game was already made flat, so I kept it. For a 3D one, go back to "
                "the Flight Deck, start a new Game project and choose 3D Block World "
                "under How it starts.")

    def _picture_how_to(self, turn: Turn) -> str:
        """How to make a picture for a thing only a picture would draw well -- or "".

        Gary cannot make picture files, and neither can any chat model here. When this
        turn met a thing the scene kit has no drawing for ("a rocket"), a picture the
        model reached for that the project has not got ("assets/car.png"), or the
        child's picture of something else, the child is told how to make one: a PNG with
        a see-through background, at a size worked out from the thing in the game, and
        how to hand it over. And a picture used with a solid background is said to show
        as a rectangle. Built from the tool's own results, never left to the model, once
        per word a conversation. Tools are named by kind only: a drawing app, or an AI
        picture maker with a grown-up -- the owner's ruling (2026-09-30), never a site.
        """
        if not plays_in_panel(self.project) or "game_object" not in self.toolbox.allowed:
            return ""
        if re.search(r"\b(?:png|see-through|transparent)\b", turn.text or "", re.I):
            return ""                     # the reply says how already
        pictured = {str(arguments.get("name") or "") for tool, arguments, result in
                    turn.calls if tool == "game_object" and result.ok and
                    arguments.get("picture")}
        for tool, arguments, result in turn.calls:
            if tool != "game_object":
                continue
            try:
                said = json.loads(result.content or "{}")
            except ValueError:
                said = {}
            name = str(arguments.get("name") or "").strip()
            if result.ok and said.get("see_through") is False:
                picture = str(said.get("picture") or "")
                if picture and picture not in self._offered_pictures:
                    self._offered_pictures.add(picture)
                    return (f"{picture} has a solid background, so it shows as a "
                            f"rectangle, background and all. A PNG with a see-through "
                            f"background looks better: most drawing apps can save one, and "
                            f"an AI picture maker can take a background away -- ask a "
                            f"grown-up first. Then add it with + Add to Project.")
                continue
            if result.ok or name in pictured:
                continue
            word = _picture_word(result.reason, arguments, name)
            if not word or word in self._offered_pictures or self._has_picture_of(word):
                continue
            self._offered_pictures.add(word)
            width, height = self._picture_size(name, arguments)
            thing = "the player" if name == "player" else f"the {name.replace('_', ' ')}"
            real = "look real" if _singular(word) == _singular(name.replace("_", " ")) \
                else f"look like a real {word}"
            return (f"Want {thing} to {real}? You can make a picture of "
                    f"one: draw it in a drawing app, or make it with an AI picture maker "
                    f"-- ask a grown-up first. Save it as a PNG with a see-through "
                    f"background, about {width} x {height} pixels, then press + Add to "
                    f"Project and say \u201cuse my {word} picture for {thing}\u201d.")
        return ""

    def _has_picture_of(self, word: str) -> bool:
        stem = _singular(word)
        return any(stem in _singular(Path(a.path).stem.lower().replace("_", " "))
                   for a in assets.list_assets(self.project) if a.kind == "image")

    def _picture_size(self, name: str, arguments: dict) -> tuple[int, int]:
        """A picture's size for a thing: about twice what it is drawn at, so it stays
        sharp, on a picture-friendly side -- 64, 128, 256 or 512 -- keeping its shape."""
        from opennest.fastpath.kinds import games
        from opennest.graphics import source as scene_source

        size = arguments.get("size")
        drawn = tuple(size) if isinstance(size, (list, tuple)) and len(size) == 2 and all(
            isinstance(v, (int, float)) and v > 0 for v in size) else None
        try:
            code = self.project.entrypoint_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            code = ""
        if drawn is None:
            entry = scene_source.read(code).entries.get(name)
            literal = entry.literals.get("size") if entry is not None else None
            if isinstance(literal, tuple) and len(literal) == 2:
                drawn = literal
        if drawn is None and name == "player":
            facts = games.facts_of(code)
            const = (facts.get("constants") or {}).get(facts.get("player_size", ""))
            if const is not None and isinstance(const.value, int):
                drawn = (const.value * 1.5, const.value * 1.5)
        width, height = drawn or (64, 64)
        longest = max(width, height)
        side = next((s for s in (64, 128, 256, 512) if s >= 2 * longest), 512)
        return (max(16, round(width * side / longest / 8) * 8),
                max(16, round(height * side / longest / 8) * 8))

    def _pictures_this_turn_broke(self, turn: Turn) -> str:
        """A page this turn changed now points at a picture the project has not got.

        Measured on the parity walk: a step added ``<img src="../assets/dinosaurs.jpg">``
        with no such file, and Gary described the picture ("It shows T-Rex, Stegosaurus
        and Triceratops"). Open Nest cannot say what a picture shows; it can say one is
        missing, which is what the child will see."""
        changed = [path for _, result in turn.tool_results for path in result.changed_files
                   if path.endswith(".html")]
        if not changed or evidence.family(self.project) != "website":
            return ""
        before = set(getattr(self, "_missing_before", ()))
        missing = [src for src in evidence.missing_pictures(self.project, changed)
                   if src not in before]
        if not missing:
            return ""
        many = len(missing) > 1
        return (f"The page now points at {', '.join(missing[:3])}"
                f"{' and more' if len(missing) > 3 else ''}, which "
                f"{'are' if many else 'is'} not in the project yet, so "
                f"{'they' if many else 'it'} will show as broken "
                f"{'pictures' if many else 'a broken picture'}. Add "
                f"{'pictures' if many else 'one'} with + Add to Project and I can use "
                f"{'them' if many else 'it'}.")

    def _settle_history(self, start: int, shown: str) -> None:
        """This turn's history, reduced to the child's message, the calls and their
        results, and the reply the child actually read."""
        turn = self.history[start:]
        asked = getattr(self, "_asked_text", None)
        if asked is not None and turn and turn[0].role == "user":
            turn[0] = Message(role="user", content=asked)   # the child's words, as said
            self._asked_text = None
        kept = turn[:1]
        if kept and kept[0].images:
            kept[0] = Message(role=kept[0].role, content=kept[0].content)
        for message in turn[1:]:
            if message.role == "tool":
                kept.append(message)
            elif message.role == "assistant" and message.tool_calls:
                kept.append(Message(role="assistant", content="",
                                    tool_calls=message.tool_calls))
        if shown:
            kept.append(Message(role="assistant", content=shown))
        self.history[start:] = kept

    def _record_outcome(self, turn: Turn) -> None:
        """What this turn really changed, for Gary next time (``evidence``)."""
        changed = sorted({path for _, result in turn.tool_results
                          for path in result.changed_files} | set(turn.scaffolded))
        made = sorted({path for _, result in turn.tool_results for path in result.made_files})
        if changed:
            line = f"Last time, these files changed: {', '.join(changed)}."
            if turn.gave_up:
                line += " The game then failed its test and was not fixed."
        elif made:
            line = f"Last time, no file changed; a run drew {', '.join(made)}."
        else:
            line = "Last time, no file changed -- so nothing described in that reply was made."
        self._last_outcome = line
        self._recent_changes = [*getattr(self, "_recent_changes", []),
                                bool(changed or made)][-QUIET_TURNS:]
        self._recent_paths = [*getattr(self, "_recent_paths", []),
                              set(changed) | set(made)][-QUIET_TURNS:]
        self._outside = []
        self._events = []
        self._undone = ""
        self._files_after = source_fingerprint(self.project.directory)
        self.refresh_state()

    def note_event(self, what: str, *, drew: bool = False) -> None:
        """Something the child did that changed no file -- pressed Run, say. Gary is told
        next turn; a plan is not affected.

        ``drew``: the run drew a chart, which is something made, as a run of Gary's is
        (``_changed_anything``). Anything else is only an event: measured on the stress
        pass, a press of Test on Mac counted as a change, so "I updated the code in
        main.py to set ON_SECONDS = 2.0" -- in an answer, about a turn that had only
        described the edit -- went unchecked to the child (SPIKES.md section 29)."""
        (self._outside if drew else self._events).append(what)
        self.refresh_state()

    def _notice_changes_since_last_turn(self) -> None:
        """Files that changed since the last turn when nothing Open Nest knows of did it.

        Measured on the parity walk: LED_PIN changed from 17 to 22 between messages and
        Gary, reading his own earlier answers, still said 17. An Undo or a starter says
        so itself (``note_outside_change``); anything else is found here, by content.
        """
        now = source_fingerprint(self.project.directory)
        before = getattr(self, "_files_after", now)
        if now == before or self._outside:
            self._files_after = now
            return
        old, new = dict(before), dict(now)
        # The code, not a picture the child imported: that is described in the asset block.
        changed = sorted(path for path in set(old) | set(new)
                         if old.get(path) != new.get(path) and path.startswith("src/"))
        self._files_after = now
        if changed:
            what = (f"{', '.join(changed[:4])} changed since your last reply, and not by you "
                    f"-- read it again before saying what it has")
            self._outside.append(what)
            if self._plan is not None:
                self._plan.changes.append(f"{', '.join(changed[:4])} changed")

    # -- a project with nothing in it yet -------------------------------------

    def _set_up_if_empty(self, turn: Turn, text: str) -> None:
        """Give an empty project its starting files, when the message asks for something.

        The owner's first Phase 13 test: a Game project begun with Start Empty, "build a
        game that's an eagle flying over cars", and every recipe stepped aside (each one
        needs a game loop to put things in) while Gary edited a ``src/game.py`` that did
        not exist. The child had to find "Add Basic Game" in the Project panel -- hidden
        product knowledge. So Open Nest does what that button does, first:

        - **A typed project** (Game, Website, ...) gets its profile's own default kit, the
          one the New Project dialog offers first. Every recipe is measured against it.
        - **Blank stays blank** until the child names a game, and then gets the Basic Game
          as its ``src/main.py``. Nothing else is guessed for Blank.
        - **A question is answered, not built for**: "what do I do now?" in an empty
          project gets an answer, and the starting files wait for a request.

        Reported as it happens (the file appears in Build / Preview as a new file) and
        said at the start of the reply. Not Gary's change: it is kept out of the tool
        results the honesty guard judges him by.
        """
        project = self.project
        src = project.directory / "src"
        if starter_kits.has_own_files(src) or is_question(text) or project.profile.generates:
            return
        blank = project.profile.id == "blank"
        began = ""
        try:
            if blank:
                becomes = [entry for entry in _BLANK_BECOMES if entry[0].search(text)]
                cannot = [entry for entry in _BLANK_CANNOT if entry[0].search(text)]
                if cannot and not becomes:
                    _pattern, verb, kind = cannot[0]
                    turn.routed = True
                    article = "an" if kind[0] in "AEIOU" else "a"
                    turn.text = (f"A Blank project can't {verb}, so I'd be making something "
                                 f"you couldn't see or use. Go back to the Flight Deck and "
                                 f"start {article} {kind} project instead -- it sets itself "
                                 f"up with everything it needs.")
                    return
                if len(becomes) != 1:
                    return            # nothing named, or several at once: Gary asks
                _pattern, starter_id, extras, began = becomes[0]
                if starter_id == "pygame_basic" and block_world.ASKS_FOR_3D.search(text):
                    starter_id, began = block_world.STARTER_ID, "as a 3D game"
                starter = starter_kits.get_starter(starter_id)
                target = project.entrypoint_path
                source = starter.directory / starter.entry_point
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                written = [project.manifest.entrypoint]
                for extra in extras:
                    if (starter.directory / extra).is_file():
                        (src / extra).write_bytes((starter.directory / extra).read_bytes())
                        written.append(extra)
                project.manifest.starter_id = starter.id
                project.manifest.starter_version = starter.version
                project.save()
            else:
                # A 3D game begins from the block world (``_set_up_block_world``).
                starter = starter_kits.get_starter(block_world.STARTER_ID) if (
                    block_world.offered(project.profile)
                    and block_world.ASKS_FOR_3D.search(text)) \
                    else starter_kits.default_starter(project.profile)
                if starter is None:
                    return
                written = add_starter(project, starter.id)
        except (ProjectError, starter_kits.StarterError, OSError):
            return
        what = "game" if "game" in began or project.profile.playtest == "pygame" \
            else "project"
        self.toolbox.report(Step("recipe", f"setting up the starting {what}"))
        paths_written = []
        for name in written:
            relative = f"src/{name}"
            paths_written.append(relative)
            content = self.toolbox._file_text(relative)
            if content is not None:
                self.toolbox.report(Step("changed", f"created {relative}", path=relative,
                                         content=content, created=True))
        turn.scaffolded = tuple(paths_written)
        turn.block_world_started = starter.id == block_world.STARTER_ID
        description = starter.description[:1].lower() + starter.description[1:]
        began = began or f"from the {starter.name}"
        turn.opening = " ".join(part for part in (
            turn.opening,
            f"There was nothing in the project yet, so I started it {began}: {description}",
        ) if part)
        self.refresh_state()

    def _write_whole_game(self, turn: Turn, text: str):
        """Have a new game written whole, tested and repaired -- while nothing is lost.

        Measured on the game builds (SPIKES.md section 33G): asked for a whole game in one
        reply, the way any coding assistant is asked, Gary Smart wrote the cat game, the
        space game and the side-scroller, each tested by Open Nest's own playtest and
        repaired from its feedback; through the edit tool, building on the starter by
        exact text, it made none of them from the first message, with 47 of its 72 edits
        refused. What the edit tool is for -- changing a game a child has, without
        losing any of it -- is not at stake while the game is still the untouched Basic
        Game. So then, and only then:

        - one reply with the whole program (``prompts/whole_game.txt``: one file, the
          numbers at the top, one game loop at the top level -- the shape the scene
          layer, the recipes and the checked facts read), then Open Nest's playtest;
        - a failure goes back with the test's own words, twice at most, all from the
          turn's one call budget;
        - kept only if it passes. Otherwise the starter is put back exactly as it was
          and the turn goes on the ordinary way.

        Only for a model not measured to struggle with games (``struggles_with``): one
        reply gave Gary Fast one working game in five, its long output breaking (a
        runaway repetition, a stray word in another language). A model the catalogue
        does not know -- a test's scripted one -- is never asked.

        Returns the write as a (call, result) pair for the history, or None.
        """
        project = self.project
        if not plays_in_panel(project) or _FROM_ABOVE.search(text) or \
                not (_MAKES_A_GAME.search(text) or _GENRES.search(text)) or \
                block_world.ASKS_FOR_3D.search(text):
            return None
        info = getattr(self.provider, "info", None)
        try:
            from opennest.ai.router import get_entry  # lazily, like the other model lookups

            if "games" in get_entry(getattr(info, "id", "")).struggles_with:
                return None
        except ProviderError:
            return None
        budget = getattr(self, "_budget", None)
        if budget is not None and budget.remaining < 4:
            return None
        path = project.entrypoint_path
        try:
            basic = starter_kits.get_starter("pygame_basic")
            starter = (basic.directory / basic.entry_point).read_text(encoding="utf-8")
            if path.read_text(encoding="utf-8") != starter:
                return None
        except (OSError, UnicodeDecodeError, starter_kits.StarterError):
            return None

        relative = f"src/{project.manifest.entrypoint}"
        pictures = [asset for asset in assets.list_assets(project)
                    if asset.kind == asset_kinds.IMAGE]
        listed = "; ".join(f"{asset.path}" + (f" ({asset.seen})" if asset.seen else "")
                           for asset in pictures[:6])
        template = (paths.prompts_dir() / "whole_game.txt").read_text(encoding="utf-8")
        system = template.strip().replace("{pictures}", (
            f" -- or these pictures from the project, loaded with pygame.image.load and the "
            f"path exactly as written: {listed}") if listed else "")
        wishes = getattr(self, "_wishes", None) or [text]
        messages = [Message(role="system", content=system), Message(
            role="user", content="Their idea, in their own words:\n" + "\n".join(
                f"- \u201c{wish}\u201d" for wish in wishes))]
        provider = getattr(self, "_metered", None) or self.provider
        self.toolbox.report(Step("recipe", "writing the whole game"))
        verdict, written = "", None
        try:
            for attempt in range(1 + WHOLE_GAME_REPAIRS):
                if isinstance(provider, MeteredProvider):
                    provider.kind = WRITE_GAME
                try:
                    for _chunk in provider.chat(messages, tools=None, settings=Settings(
                            temperature=0.0, max_tokens=WHOLE_GAME_TOKENS)):
                        pass
                    reply = provider.finish()
                except ProviderError as exc:
                    if isinstance(exc, BudgetExhausted):
                        raise
                    break
                code, problem = _whole_program(reply.text or "", relative)
                if problem:
                    verdict, feedback = "not a whole game", problem
                else:
                    tried = self._keep_if_it_plays(turn, code, relative, attempt)
                    if tried is None:
                        verdict = "untested"
                        break
                    written, failure = tried
                    if written is not None:
                        return written
                    verdict, feedback = failure
                if attempt < WHOLE_GAME_REPAIRS:
                    messages += [Message(role="assistant", content=reply.text or ""),
                                 Message(role="user", content=(
                                     f"{feedback}\n\nReply with the whole corrected "
                                     f"program in one ```python code block."))]
        finally:
            if written is None:
                # Nothing kept: the project is exactly as it was before the step.
                path.write_text(starter, encoding="utf-8")
        turn.whole_game = f"kept the starter: {verdict or 'no reply'}"
        return None

    def _keep_if_it_plays(self, turn: Turn, code: str, relative: str, attempt: int):
        """Write ``code`` and test it: ((call, result), None) when it passed and is kept,
        (None, (verdict, feedback)) when it did not, or None when it could not be tested."""
        self.project.entrypoint_path.write_text(code, encoding="utf-8")
        test = self._test_written_game()
        if test is None:
            return None
        if not test.failed:
            return self._keep_written_game(turn, code, test, relative, attempt), None
        return None, (test.verdict, test.feedback())

    def _asks_for_pictures_without_a_scene(self, text: str) -> bool:
        """The child asks to use their pictures, they have some, and the game has no scene."""
        if "game_object" not in self.toolbox.allowed or not _PICTURE_WORDS.search(text):
            return False
        if not any(asset.kind == asset_kinds.IMAGE for asset in assets.list_assets(
                self.project)):
            return False
        from opennest.graphics import source as scene_source  # lazily, like evidence

        try:
            code = self.project.entrypoint_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        return not scene_source.read(code).adopted

    def _verified_working(self) -> dict[str, str] | None:
        """The project's src/ files, when Open Nest's last test passed on exactly them."""
        last = getattr(self.toolbox, "last_playtest", None)
        if last is None or last.verdict != playtest.PASSED:
            return None
        def code(entries) -> tuple:
            # The code only: a picture added since (assets/) changes nothing that ran.
            return tuple(entry for entry in entries if entry[0].startswith("src/"))

        if code(getattr(self.toolbox, "last_playtest_files", ())) != code(
                source_fingerprint(self.project.directory)):
            return None
        src = self.project.directory / "src"
        try:
            return {str(path.relative_to(self.project.directory)): path.read_text(
                encoding="utf-8") for path in sorted(src.rglob("*.py"))
                if "__pycache__" not in path.parts}
        except (OSError, UnicodeDecodeError):
            return None

    def _put_back(self, turn: Turn) -> None:
        """A change that broke a game which worked goes, and the working game comes back.

        Measured on the game builds (SPIKES.md section 33H): after Gary Smart wrote the
        owner's test04 game whole, "use the tree pictures" became twelve hand edits, a
        crash the repairs could not mend, and a game that no longer ran at all -- three
        turns running. The give-up already offered "we can go back to the last version
        that worked"; when Open Nest's own test passed on the game before this message,
        that is done, and said. Never to a version nobody tested.
        """
        working = getattr(self, "_working", None)
        if not working or not turn.playtests or not turn.playtests[-1].failed or not any(
                result.changed_files for _, result in turn.tool_results):
            return
        directory = self.project.directory
        try:
            for path in (directory / "src").rglob("*.py"):
                relative = str(path.relative_to(directory))
                if "__pycache__" not in path.parts and relative not in working:
                    path.unlink()             # made by this turn's broken change
            for relative, text in working.items():
                (directory / relative).write_text(text, encoding="utf-8")
        except OSError:
            return
        turn.put_back = True
        failed = turn.playtests[-1]
        saw = _PLAYTEST_GAVE_UP.get(failed.verdict, "it did not work")
        turn.text = (f"That change broke the game: when I tested it, {saw}. So I put the "
                     f"game back the way it was before your message -- that version works. "
                     f"Want me to try it another way?")
        turn.plan_note = ""
        self._recent_note = ("(Open Nest: your last change broke the game, so Open Nest put "
                             "back the version from before it. The files are as they were "
                             "before that message.)")
        self._files_after = source_fingerprint(directory)
        relative = f"src/{self.project.manifest.entrypoint}"
        content = self.toolbox._file_text(relative)
        if content is not None:
            self.toolbox.report(Step("changed", f"put back {relative}", path=relative,
                                     content=content))
        self.refresh_state()

    def _test_written_game(self) -> playtest.Playtest | None:
        """Open Nest's playtest of what was just written -- also in a Blank game, which has
        no test after an ordinary change, because nothing here is kept untested."""
        result = self.toolbox.playtest()
        if result is not None or not plays_in_panel(self.project):
            return result
        self.toolbox.report(Step("testing", "testing the game without a window"))
        files = source_fingerprint(self.project.directory)
        result = playtest.run(self.project.directory, self.project.profile.run_command,
                              python_executable=self.toolbox.python_executable)
        self.toolbox.last_playtest, self.toolbox.last_playtest_files = result, files
        return result

    def _keep_written_game(self, turn: Turn, code: str, test: playtest.Playtest,
                           relative: str, attempt: int):
        """The written game, passed: a change of Gary's, tested, reported as it is."""
        moving = "something moves on its own" if test.moved_by_itself else ""
        keys = "it responds to the keys" if test.responded_to else ""
        seen = " and ".join(part for part in (moving, keys) if part)
        result = ToolResult(True, (
            f"Wrote {relative}: the whole game, {code.count(chr(10)) + 1} lines"
            f"{f', after {attempt} repair' + ('s' if attempt != 1 else '') if attempt else ''}. "
            f"Open Nest tested it without a window: it runs{', and ' + seen if seen else ''}."),
            changed_files=(relative,))
        call = ToolCall(name="write_file", arguments={"path": relative, "content": code},
                        id="whole_game")
        turn.tool_results.append((call.name, result))
        turn.calls.append(("write_file", call.arguments, result))
        turn.playtests.append(test)
        # Tested just now: the turn's own test after a change need not run it again.
        self._tested_through = len(turn.tool_results)
        turn.whole_game = "written"
        content = self.toolbox._file_text(relative)
        if content is not None:
            self.toolbox.report(Step("changed", f"changed {relative}", path=relative,
                                     content=content))
        self.refresh_state()
        return call, result

    def _set_up_block_world(self, turn: Turn, text: str) -> None:
        """Start the game again as the 3D Block World, when 3D is asked for first thing.

        The owner's test05 (2026-10-04, Gary Fast): "create a simple, block 3D game.
        Where the world is made by 1 meter square cubes." in a game that was still the
        Basic Game -- and three turns later one rectangle the size of the window. A
        first-person world is a starter (``graphics.block_world``), so while the game is
        the Basic Game byte for byte, nothing the child made is in the way and Open Nest
        swaps it, the way ``_set_up_if_empty`` fills an empty project. Saved as a version
        like any change, so Undo brings the square back. A game changed in any way is
        never replaced; ``_three_d_how_to`` says where the 3D one is instead.
        """
        project = self.project
        if turn.scaffolded or is_question(text) or not block_world.ASKS_FOR_3D.search(text):
            return
        if not (block_world.offered(project.profile) or project.profile.id == "blank"):
            return
        path = project.entrypoint_path
        try:
            basic = starter_kits.get_starter("pygame_basic")
            if path.read_text(encoding="utf-8") != (
                    basic.directory / basic.entry_point).read_text(encoding="utf-8"):
                return
            kit = starter_kits.get_starter(block_world.STARTER_ID)
            path.write_text((kit.directory / kit.entry_point).read_text(encoding="utf-8"),
                            encoding="utf-8")
        except (OSError, UnicodeDecodeError, starter_kits.StarterError):
            return
        project.manifest.starter_id = kit.id
        project.manifest.starter_version = kit.version
        project.save()
        relative = f"src/{project.manifest.entrypoint}"
        self.toolbox.report(Step("recipe", "setting up a 3D game"))
        content = self.toolbox._file_text(relative)
        if content is not None:
            self.toolbox.report(Step("changed", f"changed {relative}", path=relative,
                                     content=content))
        turn.scaffolded = (relative,)
        turn.block_world_started = True
        description = kit.description[:1].lower() + kit.description[1:]
        turn.opening = " ".join(part for part in (
            turn.opening,
            f"You asked for a 3D game, so I started it as the {kit.name}: {description} "
            f"W and S walk, A and D turn, and walking into a gold block picks it up.",
        ) if part)
        self.refresh_state()

    # -- plans ------------------------------------------------------------------

    def _resume_plan(self, text: str) -> tuple[int | None, str]:
        """The step "next" means, and what to say first -- or (None, "") if it is not one.

        Before a step runs, the project is compared with how the last turn left it. An
        Undo, a starter added by hand, or a file changed some other way means the plan's
        assumptions may be stale, so the step is worked out again from the files as they
        are, and the child is told. A step whose change an Undo took back out is not done
        any more. A step that did not land last time is offered again, never skipped.
        """
        plan = self._plan
        if plan is None:
            return None, ""
        words = text.strip()
        if not (_CARRY_ON.match(words) or (plan.offered and _YES.match(words))):
            return None, ""
        if plan.next_index() is None:
            self._plan = None
            return None, ""
        changed = self._revalidate(plan)
        index = plan.next_index()
        step, count = plan.steps[index], len(plan.steps)
        if step.status == "not_done":
            head = (f"Step {index + 1} of {count} didn't get made last time, so I'm trying "
                    f"it again: {step.text}.")
        else:
            head = f"Step {index + 1} of {count}: {step.text}."
        return index, " ".join(part for part in (changed, head) if part)

    def _revalidate(self, plan: Plan) -> str:
        """Compare the project with how the plan last saw it. A sentence if it changed."""
        now = source_fingerprint(self.project.directory)
        changes, plan.changes = plan.changes, []
        if now == plan.files:
            return ""
        plan.files = now
        undone = [index for index, step in enumerate(plan.steps)
                  if step.status == "done" and step.before == now]
        if undone:
            first = min(undone)
            for step in plan.steps[first:]:
                if step.status == "done":
                    step.status = "todo"
            return (f"Your project is back to how it was before step {first + 1}, so that "
                    f"step isn't done any more.")
        what = "; ".join(changes)
        return ("Your project changed since the last step"
                + (f" ({what})" if what else "")
                + ", so I looked at it again and I'm working from what's there now.")

    def _plan_guidance(self, index: int | None) -> str:
        """The plan as it really stands, for Gary: the one step he is doing, or -- when
        this message is something else -- the step that is waiting."""
        plan = self._plan
        status = {"done": "done -- a file changed for it", "not_done":
                  "tried before; nothing changed", "todo": "not started"}
        listed = "\n".join(
            f"{number}. {step.text} -- "
            f"{'THIS ONE' if number - 1 == index else status[step.status]}"
            for number, step in enumerate(plan.steps, 1))
        heading = f"A PLAN OPEN NEST IS WORKING THROUGH, for \u201c{plan.request}\u201d:"
        if index is None:
            waiting = plan.next_index() + 1
            return (f"{heading}\n{listed}\nThis message is not a step. If they ask what to "
                    f"do next, offer step {waiting}; do not start it unless they ask.")
        return (f"{heading}\n{listed}\nDo only step {index + 1}, against the files as they "
                f"are now (see what Open Nest has checked). If it is already in the game, "
                f"say so and change nothing.")

    def _settle_plan(self, turn: Turn) -> None:
        """Mark the step this turn worked on by what happened to the files, and say so."""
        plan = self._plan
        if plan is None:
            return
        if turn.plan_step is None:
            if turn.plan_note:
                plan.offered = True           # the plan was just offered, nothing made
            elif any(result.changed_files for _, result in turn.tool_results) or \
                    turn.scaffolded:
                self._plan = None             # the child moved on to something else
                return
            else:
                # A question in between: the plan waits, still compared with how the last
                # step left the files, so an Undo before the question is not absorbed.
                plan.offered = False
                return
            plan.files = source_fingerprint(self.project.directory)
            return
        step = plan.steps[turn.plan_step]
        mine = turn.tool_results[turn.step_from:]
        landed = any(result.changed_files for _, result in mine) and not turn.gave_up
        hidden = self._not_drawn(step.text) if landed else []
        step.status = "done" if landed and not hidden else "not_done"
        number, count = turn.plan_step + 1, len(plan.steps)
        following = plan.next_index()
        moved = f", so I haven't moved on to step {number + 1}" if number < count else ""
        if hidden:
            held = f" I haven't moved on to step {number + 1}." if number < count else ""
            source = self.project.entrypoint_path.read_text(encoding="utf-8")
            why = ("nothing draws it yet, so it isn't on screen"
                   if hidden[0] in evidence.undrawn(source, hidden) else
                   "the game makes it again every frame, so it can't move yet")
            turn.plan_note = (f"The {hidden[0]} is in the code now, but {why}.{held} Want "
                              f"me to try it again?")
        elif not landed:
            turn.plan_note = (f"That step didn't get made{moved}. Want me to try it "
                              f"again, or would you rather change something else?")
        elif following is None:
            turn.plan_note = "That was the last step."
            self._plan = None
            return
        else:
            turn.plan_note = (f"Next is step {following + 1} of {count}: \u201c"
                              f"{plan.steps[following].text}\u201d. Want me to keep going?")
        plan.offered = True
        plan.files = source_fingerprint(self.project.directory)

    def _framed(self, turn: Turn) -> Turn:
        """Put what the recipes made before Gary's reply, and what is left after it."""
        steps = (turn.fastpath or {}).get("plan") or []
        if turn.reduced and steps and self._plan is not None and not any(
                result.changed_files for _, result in turn.tool_results):
            # Even the steps came to nothing. The plan is still worth having: it is the
            # way in, and "yes" or "next" starts it -- the child is not left to rewrite it.
            for step in self._plan.steps:
                step.status = "todo"
            turn.plan_step = None
            listed = "\n".join(f"{n}. {step}" for n, step in enumerate(steps, 1))
            turn.prefix = ""
            # After Open Nest set up the starting files, "changed anything" is not true.
            first = ("I haven't built any of that yet." if turn.scaffolded
                     else "I haven't changed anything yet.")
            way = "Here's a way to build it, one step at a time:"
            made = sorted({path for _, result in turn.tool_results
                           for path in result.made_files})
            if made:
                # A run on the way drew a chart: that is something done, and the child is
                # told where it is. Measured on the stress pass: "Graph this." drew
                # charts/chart.png and was answered "I haven't changed anything yet" and
                # a plan to draw the axes (SPIKES.md section 29).
                first = (f"I haven't changed any file yet, but running the project drew "
                         f"{', '.join(made)} -- click it in the Project panel to see it.")
                way = "To build more on it, one step at a time:"
            turn.text = f"{first} {way}\n\n{listed}"
            turn.plan_note = "Want me to start with the first one?"
            return turn
        turn.text = "\n\n".join(part for part in (turn.prefix, turn.text, turn.suffix)
                                if part)
        return turn

    @staticmethod
    def _stuck_on_edits(turn: Turn) -> bool:
        """Several edits refused in Gary's share of the turn, and nothing changed."""
        mine = turn.tool_results[turn.gary_from:]
        if any(result.changed_files for _, result in mine):
            return False
        refused = sum(1 for name, result in mine if not result.ok
                      and normalise_tool_name(name) in ("edit_file", "write_file"))
        return refused >= REFUSALS_BEFORE_STEPS

    def _stalled(self, turn: Turn, text: str, on_text, corrected: bool, *,
                 too_big: bool = False) -> Turn:
        """Gary's attempt came to nothing. A request is split into steps; a question is
        answered with what the project has.

        Measured on the owner-test walk: "everything ok? what do i do now" drew two
        refused edits, and the planner then split the *question* into three steps
        ("Check your game project for what needs to be built next"). A question is never
        a plan. What Open Nest knows -- what is in the game, how it is played, and the
        step that is waiting -- answers it truthfully instead.
        """
        if is_question(text):
            turn.text = self._as_it_is_text()
            plan = self._plan
            index = plan.next_index() if plan is not None else None
            if index is not None and turn.plan_step is None:
                turn.plan_note = (f"Want me to start on step {index + 1}, \u201c"
                                  f"{plan.steps[index].text}\u201d?")
            return self._finish_turn(turn)
        if self._can_reduce(turn):
            return self._reduce(turn, text, on_text, corrected, too_big=too_big)
        turn.text = self._nothing_changed_text(turn, too_big=too_big)
        return self._finish_turn(turn)

    def _can_reduce(self, turn: Turn) -> bool:
        """Once per turn, for the whole request, and only with calls left to spend -- and
        never a plan's own step. Measured on the owner-test walk: "next" re-planned step 1
        into three new steps and the plan's other two were silently dropped."""
        budget = getattr(self, "_budget", None)
        left = budget.remaining if budget is not None else 0
        # Nor in a 3D Block World. Measured on the game builds (SPIKES.md section 33): the
        # turn Open Nest set one up, a plan read "I haven't built any of that yet" beneath
        # "I started it as the 3D Block World"; later, asked for the sky, the W A S D and
        # the hands it already had, Gary Fast's plan was to add them. Its plans are for a
        # game it is not.
        return (not turn.reduced and not turn.gary_from and turn.plan_step is None
                and left >= 2 and not block_world.of_project(self.project))

    def _reduce(self, turn: Turn, text: str, on_text, corrected: bool, *,
                too_big: bool = False) -> Turn:
        """Break a request Gary could not do in one go into steps, and start on them.

        The fallback before this told the child to ask for something smaller, which
        makes them the orchestration layer. Instead: one planning call to the model
        Gary is (at most three steps, ``prompts/plan.txt``); the steps a recipe can make
        are made and checked (``FastPathRouter.run_parts``); Gary then does the first of
        the rest -- only that one, honesty-guarded from where his share begins -- and
        the others are offered, with "next" to do them. Bounded twice over: this runs
        once per turn, and every call it makes spends from the turn's one budget.
        """
        turn.reduced = True
        steps = self._plan_steps(text)
        record = turn.fastpath if turn.fastpath is not None else {}
        turn.fastpath = record
        if len(steps) < 2:
            # "Too much in one go" only where that is the checked cause (a cut-off call).
            turn.text = self._nothing_changed_text(turn, too_big=too_big)
            return self._finish_turn(turn)
        record["plan"] = steps
        self._plan = Plan(request=text, steps=[PlannedStep(step) for step in steps])
        rest, done_text, guidance = list(steps), "", ""
        if self.fastpath is not None:
            try:
                result = self.fastpath.run_parts(
                    self.project, self.toolbox, text, steps, provider=self.provider,
                    attachments=tuple(self._attached), build_style=self.build_style)
            except Exception as exc:  # noqa: BLE001 - the Fast Path must not break a turn
                record["plan_error"] = repr(exc)
            else:
                record["plan_parts"] = result.record.get("parts")
                guidance = result.guidance
                if result.handled:
                    self._take_in(turn, result)
                    done_text, rest = result.text, list(result.remaining)
        for step in self._plan.steps:
            if step.text not in rest:
                step.status = "done"          # a recipe made it, and checked it
        listed = "\n".join(f"{n}. {step}" for n, step in enumerate(steps, 1))
        intro = f"That was a lot to build in one go, so I split it into steps:\n\n{listed}"
        if not rest:
            turn.prefix = "\n\n".join(part for part in (intro, done_text) if part)
            turn.text = ""
            return self._finish_turn(turn)
        first = rest[0]
        index = steps.index(first)
        heading = f"Step {index + 1} of {len(steps)}: {first}."
        turn.prefix = "\n\n".join(part for part in (intro, done_text, heading) if part)
        record["remaining"] = [first]
        turn.plan_step = index
        turn.gary_from = turn.step_from = len(turn.tool_results)
        self._tested_through = len(turn.tool_results)
        if guidance:
            self._guidance = "\n\n".join(part for part in (self._guidance, guidance) if part)
        made = "; the first part is made above and checked" if done_text else ""
        self.history.append(Message(role="user", content=(
            f"That was too much for one go, so Open Nest split it into steps{made}. Now do "
            f"only this step: \u201c{first}\u201d. Nothing else.")))
        self.refresh_state()
        return self._exchange(turn, first, on_text, False, corrected)

    def _plan_steps(self, text: str) -> list[str]:
        """At most three small steps for a request, from one call. [] if none came back."""
        self.toolbox.report(Step("thinking", "breaking it into smaller steps"))
        provider = getattr(self, "_metered", None) or self.provider
        if isinstance(provider, MeteredProvider):
            provider.kind = PLAN
        template = (paths.prompts_dir() / "plan.txt").read_text(encoding="utf-8").strip()
        messages = [Message(role="system", content=template.replace(
                        "{project}", self.project.profile.name.lower())),
                    Message(role="user", content=text)]
        try:
            for _chunk in provider.chat(messages, tools=None,
                                        settings=Settings(temperature=0.0, max_tokens=200)):
                pass
            reply = provider.finish()
        except BudgetExhausted:
            raise
        except ProviderError:
            return []
        steps = []
        for line in (reply.text or "").split("\n"):
            step = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", line).strip().strip('"')
            # Each step once. Measured on the game builds (SPIKES.md section 33): Gary Fast
            # planned "add mountains far away behind everything" as that sentence three
            # times, and the child was offered it as steps 1, 2 and 3.
            if 2 <= len(step.split()) <= 20 and len(step) <= 140 and \
                    step.rstrip(".").casefold() not in (done.casefold() for done in steps):
                steps.append(step.rstrip("."))
        return steps[:3]

    def _fast_path(self, turn: Turn, text: str, previous: str | None,
                   attachments: Sequence[assets.Asset],
                   on_text: Callable[[str], None] | None) -> str:
        """Let the Fast Path take the turn if it can: "handled", "gary", or "rest".

        "rest" is a message that was several requests, of which recipes made some: their
        edits go into the history as below, and Gary does the rest in this same turn,
        from the files as the recipes left them (``_hand_over_the_rest``).

        When a recipe handled the request, the history gets what actually happened --
        the edits as ``edit_file`` calls, their results, and Gary's reply -- so on the
        next turn the model reads a change it can see was made, rather than a claim.
        That is how Gary knows which recipe ran without being told a word about recipes.

        When it did not, the only trace is the guidance in the system prompt for this
        one turn, and the loop runs exactly as it would have. The Fast Path must never be
        the thing that breaks a child's turn, so a failure inside it is recorded and the
        turn goes to the model.
        """
        try:
            result = self.fastpath.handle(
                self.project, self.toolbox, text,
                provider=self.provider, previous=previous,
                attachments=tuple(attachments), build_style=self.build_style,
            )
        except Exception as exc:  # noqa: BLE001 - see the docstring
            turn.fastpath = {"route": "normal", "reason": f"the Fast Path failed: {exc!r}"}
            return "gary"
        turn.fastpath = result.record
        if not result.handled:
            # A recipe that was rolled back tested code that no longer exists. Leaving
            # that test in the turn would have the repair loop chase a crash Gary's code
            # never had -- measured, it spent all three attempts doing so.
            if result.guidance:
                self._guidance = "\n\n".join(
                    part for part in (self._guidance, result.guidance) if part)
                self.refresh_state()
            return "gary"
        self._take_in(turn, result)
        if result.remaining:
            self._hand_over_the_rest(turn, result.remaining, result.text, result.guidance)
            return "rest"
        turn.text = result.text
        if on_text is not None:
            on_text(result.text)
        self.refresh_state()
        return "handled"

    def _take_in(self, turn: Turn, result) -> None:
        """What a recipe made goes into the history and the turn as what it was."""
        self._recent_note = result.note
        turn.playtests.extend(result.playtests)

        if result.calls:
            # An "it already is" answer made no calls, and an assistant message with no
            # words and no calls is noise in the history the model reads next turn.
            self.history.append(Message(
                role="assistant", content="",
                tool_calls=tuple(call for call, _ in result.calls),
            ))
        for call, tool_result in result.calls:
            turn.tool_results.append((call.name, tool_result))
            self.history.append(Message(role="tool", name=call.name, tool_call_id=call.id,
                                        content=tool_result.content))
        self.history.append(Message(role="assistant", content=result.text))

    def _hand_over_the_rest(self, turn: Turn, rest, done_text: str, guidance: str) -> None:
        """Gary does what the recipes did not, in this turn, knowing what they made."""
        turn.prefix = done_text
        turn.gary_from = len(turn.tool_results)
        # The recipes' own checks already tested what they made.
        self._tested_through = len(turn.tool_results)
        if guidance:
            self._guidance = "\n\n".join(part for part in (self._guidance, guidance) if part)
        wanted = " and ".join(f"\u201c{part}\u201d" for part in rest)
        self.history.append(Message(role="user", content=(
            "Open Nest has already made the part above itself and checked it. Now do only "
            f"the rest of what they asked: {wanted}. Do not redo or undo what was made.")))
        self.refresh_state()

    def _out_of_calls(self, turn: Turn) -> Turn:
        """Stop cleanly at the ceiling, with something a child can act on.

        Deliberately not another call: the point of a ceiling is that reaching it costs
        nothing more. The partial work already done is kept and checkpointed by
        ``_finish_turn`` exactly as a successful turn's would be.
        """
        turn.hit_call_limit = True
        # Measured on the owner's test04: "Here is where I got to", and then nothing --
        # what had been made was never said. It is said now, from the tool results.
        done = self._describe_what_happened(turn)
        turn.text = (
            "That turned into more steps than I can do at once. "
            + (f"So far: {done} " if done else "Nothing has changed yet. ")
            + "Say \u201ckeep going\u201d and I'll carry on from here."
        )
        if self._budget.stopped:
            # Not out of calls: the project was closed while he worked, and the turn must
            # not report a reason that is not true. (Like any turn's closing line, it is
            # not added to the history; the archive keeps the child's message and any
            # changes, which are checkpointed.)
            turn.text = "I stopped there because the project was closed."
        return self._finish_turn(turn)

    def _exchange(
        self,
        turn: Turn,
        text: str,
        on_text: Callable[[str], None] | None,
        challenged: bool,
        corrected: bool,
    ) -> Turn:
        looked = named = counted = carried = tallied = scened = disowned = False
        wired = hued = unsaid = filed = False
        while True:
            reply = self._generate(on_text, turn=turn)
            self.history.append(
                Message(role="assistant", content=reply.text, tool_calls=reply.tool_calls)
            )
            # What the child would read: no tool syntax, no page of code (``presentable``).
            shown = presentable(reply.text)
            if shown:
                turn.text = shown
            if looped(reply.text) and self._changed_anything(turn):
                # The change is real and the words about it are a loop: Open Nest says
                # what it did instead. (A loop that changed nothing is handled below.)
                turn.text = self._describe_what_happened(turn)

            if not reply.wants_tool:
                if (reply.dropped_tool_call or looped(reply.text)) and \
                        not self._changed_anything(turn):
                    # A call the model could not finish -- it ran out of output while
                    # writing it -- so nothing ran and nothing changed. The provider has
                    # already kept the raw protocol off the screen; without this the
                    # child would be told nothing at all, or a half-sentence that came
                    # before the call. Not retried: measured, it was a repetition loop,
                    # and at temperature 0 the same prompt loops the same way.
                    return self._stalled(turn, text, on_text, corrected, too_big=True)
                # Checked against ``turn.text`` -- what the child will actually be told
                # -- and not against ``reply.text``. The two differ whenever a reply
                # comes back empty, because the assignment above only overwrites on
                # non-empty text, and that is not a corner case: it is how the Phase
                # 12.1 verification walk still leaked step 22's claim after the
                # correction was already in place. The model answered the pushback with
                # nothing at all, ``reply.text`` was "", the check saw no claim, and the
                # *previous* reply's "I replaced the old player movement" went to the
                # child unexamined. Gary is answerable for the sentence on screen.
                claim = self._claim_in(turn, turn.text) or (
                    "run" if self._claimed_a_run_it_did_not_do(turn, turn.text) else "")
                if claim == "run" and challenged:
                    # Said again after its correction: Open Nest says what really happened.
                    turn.text = self._describe_what_happened(turn) or self._as_it_is_text()
                    return self._finish_turn(turn)
                if claim:
                    if not challenged:
                        challenged = True
                        self._metered.kind = CORRECTION
                        there = self._already_there() if claim not in ("run", "result") \
                            and not turn.answered else ""
                        self.history.append(Message(role="user", content=(
                            RUN_CORRECTION if claim == "run" else
                            ANSWER_CORRECTION if turn.answered else
                            RESULT_CORRECTION if claim == "result" else
                            # A game that already has what was claimed: the facts first.
                            # Led by "You did not change any file", the 4B said the tree
                            # pictures it had added the turn before "were not added".
                            f"Nothing changed in this turn's calls.{there} If not, make "
                            f"the change now with game_object or edit_file." if there else
                            "You did not actually change any file. Call edit_file now "
                            "with the exact text to replace"
                            + (" -- or game_object, for how something looks --"
                               if "game_object" in self.toolbox.allowed else "")
                            + ", or say plainly that you have not changed anything yet."
                        )))
                        continue
                    # The correction has been spent and the claim came back anyway.
                    # Phase 12.1 measured that reaching a child verbatim: three real
                    # Games turns, every edit_file refused, the file byte-identical, and
                    # Gary announcing a white spaceship and a red asteroid that were
                    # never written. The application knows exactly what happened, so it
                    # says that instead of relaying the claim -- the same move
                    # _describe_what_happened makes when the model says nothing at all,
                    # and it costs no further provider call.
                    return self._stalled(turn, text, on_text, corrected)
                if not corrected:
                    invented = self._described_a_file_it_cannot_see(reply.text, text)
                    if invented is not None:
                        corrected = True
                        turn.corrected_invention = True
                        self._metered.kind = CORRECTION
                        self.history.append(Message(role="user", content=(
                            f"You have not seen {invented} and neither has anyone else. "
                            f"Do not say what is in it or what it looks like. Say what you "
                            f"actually did with the file, and tell them plainly that you "
                            f"do not know what the picture shows."
                        )))
                        continue
                if self._only_promised(turn, text):
                    # "I'll add the eagle, poop, and cars now. ... I'll do that now." --
                    # and the turn ended with nothing changed (the owner-test walk). A
                    # promise is not a change; the request is split into steps instead.
                    return self._stalled(turn, text, on_text, corrected)
                if self._playtest_wants_repair(turn):
                    continue
                # What the reply says is checked against the game once the game itself is
                # settled: a broken game is repaired first, then described truthfully.
                missing = self._names_what_is_not_there(turn, turn.text)
                if missing is not None and named:
                    # Corrected once and said again (measured: "Eagle is now flying" about
                    # a Blank game whose code has no eagle). Open Nest says what it knows.
                    turn.text = self._what_it_has_now(turn)
                    return self._finish_turn(turn)
                if missing is not None:
                    # "Look for the white rectangle -- that's the eagle", about a game
                    # whose code has no eagle (the owner-test walk). Once per turn.
                    named = True
                    self._metered.kind = CORRECTION
                    about = evidence.describe_game(self.project)
                    about = (f"Right now, from the code: {about}" if about
                             else evidence.summary_for_child(self.project))
                    # Their question stays the point: measured, "say plainly that the
                    # eagle isn't there" turned "how do I undo that?" into an eagle report.
                    what = "game" if plays_in_panel(self.project) else "project"
                    if turn.answered:
                        self.history.append(Message(role="user", content=(
                            f"Answer this again: \u201c{text}\u201d. Do not say the {what} "
                            f"has a {missing} -- its files have none. {about}")))
                    else:
                        # A request: the thing may simply not have been made yet. Measured
                        # on the 13C walk: "It's behind the road" after a turn that made
                        # only the sky (SPIKES.md section 28E).
                        how = (" -- game_object with name walls and layout maze makes one"
                               if missing.rstrip("s") in ("maze", "labyrinth") else "")
                        self.history.append(Message(role="user", content=(
                            f"The {what} has no {missing} -- its files have none. If they "
                            f"asked for one, make it now with your tools{how}; otherwise "
                            f"say plainly it is not there. {about}")))
                    continue
                refused_claim = self._claims_what_was_refused(turn)
                if refused_claim is not None and disowned:
                    # Said again after its correction: Open Nest says what happened.
                    correction, fact = refused_claim
                    turn.text = f"{turn.text}\n\n({fact})"
                    return self._finish_turn(turn)
                if refused_claim is not None:
                    disowned = True
                    self._metered.kind = CORRECTION
                    self.history.append(Message(role="user", content=refused_claim[0]))
                    continue
                misdescribed = None if scened else self._scene_claims(turn.text)
                if misdescribed is not None:
                    scened = True
                    self._metered.kind = CORRECTION
                    self.history.append(Message(role="user", content=misdescribed))
                    continue
                wrong_count = None if tallied else self._counts_nobody_made(turn.text)
                if wrong_count is not None:
                    tallied = True
                    noun, actual, said_number = wrong_count
                    self._metered.kind = CORRECTION
                    self.history.append(Message(role="user", content=(
                        f"The game has {actual} {noun if actual != 1 else _singular(noun)}, "
                        f"not {said_number}. Say how many there really are -- or, if they "
                        f"asked for {said_number}, game_object with count: {said_number} "
                        f"makes that many.")))
                    continue
                invented = None if counted else self._numbers_nobody_printed(turn.text, text)
                if invented:
                    # "Leeds: 14.5°C, Seville: 18.2°C, Oslo: 19.0°C" -- about a chart
                    # nobody looked at, and numbers the analysis never printed (parity walk).
                    counted = True
                    self._metered.kind = CORRECTION
                    # Their question stays the point, and the numbers are not repeated
                    # back: measured, naming them made the answer about them.
                    self.history.append(Message(role="user", content=(
                        f"Answer this again: \u201c{text}\u201d. Some numbers in your answer "
                        f"are not in anything the analysis printed or Open Nest checked, so "
                        f"leave them out -- use only numbers the output shows, or say what "
                        f"would have to be run to find out.")))
                    continue
                if looked and self._claimed_to_see(turn.text):
                    # Said again after its correction ("The chart shows temperature by
                    # city", parity walk): Open Nest says what it knows instead.
                    turn.text = self._describe_what_happened(turn) or self._as_it_is_text()
                    return self._finish_turn(turn)
                if not looked and self._claimed_to_see(turn.text):
                    # Nothing shows Gary the game or the screen, so "I see the eagle is
                    # missing" is an observation nobody made. After the picture check,
                    # which says the same about an attachment more exactly. Once.
                    looked = True
                    self._metered.kind = CORRECTION
                    self.history.append(Message(role="user", content=SIGHT_CORRECTION))
                    continue
                if not self._changed_anything(turn) and self._repeats_undone(turn.text):
                    if unsaid:
                        # Said again after its correction: what is true now is said instead.
                        now = re.sub(r"^I haven't changed anything in the (?:project|game) "
                                     r"yet\.\s*", "It's back to how it started. ",
                                     self._as_it_is_text())
                        turn.text = f"You pressed Undo, so that last change is gone. {now}"
                        return self._finish_turn(turn)
                    # Measured on the stress pass (SPIKES.md section 29): after an Undo took
                    # a Roar button back out, Qwen3 8B answered "What do I do now?" with its
                    # own undone reply, word for word -- "I added a Roar button...".
                    unsaid = True
                    self._metered.kind = CORRECTION
                    self.history.append(Message(role="user", content=(
                        "The child pressed Undo after your last change, so what that reply "
                        "described is not in the files any more. Do not say it again. "
                        + (f"Answer \u201c{text}\u201d from what Open Nest has checked about "
                           "the files as they are now." if turn.answered else _SAY_IT_AGAIN))))
                    continue
                unseen = self._hardware_claims(turn.text)
                if unseen and wired:
                    # Said again after its correction: those sentences go, and what Open
                    # Nest knows about the hardware is said instead.
                    turn.text = self._without_hardware_claims(turn.text, unseen)
                    return self._finish_turn(turn)
                if unseen:
                    # "The code now confirms blinks on a real Pi" (the stress pass, SPIKES
                    # section 29): nothing ran on a Pi, and nothing here can see one. Once.
                    wired = True
                    self._metered.kind = CORRECTION
                    self.history.append(Message(role="user", content=hardware_correction(
                        evidence.family(self.project), self.project.profile.run_label)))
                    continue
                off = self._colours_nobody_used(turn)
                if off and hued:
                    # Said again after its correction: the fact is added to it.
                    turn.text = (f"{turn.text}\n\n(The page's files have no "
                                 f"{' or '.join(off)} in them.)")
                    return self._finish_turn(turn)
                if off:
                    # "It uses the warm orange accent colour", about a green one (the 4B,
                    # stress pass, SPIKES.md section 29). Once.
                    hued = True
                    self._metered.kind = CORRECTION
                    families, _words = evidence.page_colours(self.project)
                    self.history.append(Message(role="user", content=(
                        f"The page's files have no {' or '.join(off)} in them -- the colours "
                        f"their CSS really has are {', '.join(sorted(families)) or 'none'}. "
                        f"Say only colours the files have; if they asked for "
                        f"{' or '.join(off)}, change the CSS now.")))
                    continue
                wrong = self._files_said_wrongly(turn)
                if wrong and filed:
                    # Said again after its correction: Open Nest adds what is so.
                    turn.text = f"{turn.text}\n\n(Open Nest: {'; '.join(wrong)}.)"
                    return self._finish_turn(turn)
                if wrong:
                    filed = True
                    self._metered.kind = CORRECTION
                    self.history.append(Message(role="user", content=(
                        f"That is not what the files say: {'; '.join(wrong)}. "
                        + (f"Answer \u201c{text}\u201d again, and say only what really happened "
                           f"-- the project's files are listed in what Open Nest has checked."
                           if turn.answered else _SAY_IT_AGAIN))))
                    continue
                if not carried and self._promised_more(turn):
                    # "The sky is now blue. I'll add the road now." -- and the turn ended,
                    # three times on the second 4B walk (SPIKES.md section 28E): the small
                    # model makes one call a reply and then says what it will do next.
                    # Something did change, so this is not a false claim to correct; it is
                    # a job half done. Once per turn, from the one budget.
                    carried = True
                    self._metered.kind = PRIMARY
                    self.history.append(Message(role="user", content=CARRY_ON))
                    continue
                return self._finish_turn(turn)

            self._metered.kind = PRIMARY
            should_continue = self._run_tools(reply.tool_calls, turn)
            if should_continue and self._stuck_on_edits(turn):
                # The same change will not land. Retrying it is what spent a whole turn's
                # calls on the acceptance run; splitting it into steps is the next move.
                return self._stalled(turn, text, on_text, corrected)
            if not should_continue:
                # The crash repair has had its go. A game it got running still has to
                # pass the same test as any other.
                if self._playtest_wants_repair(turn):
                    continue
                return self._finish_turn(turn)

    def _finish_turn(self, turn: Turn) -> Turn:
        """Save a checkpoint if the assistant changed anything, then update memory.

        The rollover that used to end this is in :meth:`_close_turn`, after the history
        has been settled to what the child was told."""
        # The attachment belonged to the message just answered. The file stays in the
        # project and keeps appearing in the listing; only "they just added this" goes.
        # The Fast Path's guidance was about this message too, and a rollover below must
        # not carry it into the next thread's prompt.
        self._attached = ()
        self._guidance = ""
        self._put_back(turn)
        changed = not turn.put_back and (any(
            result.changed_files for _, result in turn.tool_results) or bool(turn.scaffolded))
        # State is refreshed before the checkpoint so the saved version contains both the
        # change and the note describing it.
        if self.memory is not None:
            self.memory.note_turn(
                changed_files=changed,
                ran_project=any(result.run is not None for _, result in turn.tool_results),
                last_run=self.toolbox.last_run,
            )
        if changed:
            turn.checkpoint = self._checkpoint(LABEL_AFTER_CHANGE)
        if not turn.text:
            turn.text = self._describe_what_happened(turn)
        if not turn.text and turn.answered:
            # An answer that was only a call, which a question does not run: what the
            # project has is still an answer, and silence is not.
            turn.text = self._as_it_is_text()
        offer = self._tidy(turn)
        if not turn.plan_note and "?" not in turn.text and promises(turn.text):
            # "I'll add the eagle now." in an answer, which changes nothing, or "I'll fix
            # that now." as the last word of a turn that has ended (the owner-test walk).
            # Either way it is an offer, so it is said as one; "yes" then asks -- for the
            # plan's next step when one is waiting, since that is what it means.
            plan = self._plan
            index = plan.next_index() if plan is not None else None
            turn.plan_note = (f"Want me to start on step {index + 1}, \u201c"
                              f"{plan.steps[index].text}\u201d?" if index is not None
                              else "Want me to go ahead?")
        elif not turn.plan_note and offer:
            turn.plan_note = offer
        elif not turn.plan_note and "?" not in turn.text and turn.answered and \
                instructs_edit(turn.text):
            # An answer telling them to change the code by hand: Gary can make that change,
            # so it is offered (the stress pass, SPIKES.md section 29).
            turn.plan_note = "Want me to make that change for you?"
        return turn

    def _already_there(self) -> str:
        """What the game already has, said with a "you changed nothing" correction.

        Measured on the test04 replay: the trees had worn the child's six pictures since
        the turn before, the 4B said "I replaced the tree drawing with the 6 tree pictures"
        again, and corrected, told the child "The tree pictures were not added to the
        game". Nothing changing now does not undo what is there."""
        if not plays_in_panel(self.project):
            return ""
        try:
            about = evidence.describe_game(self.project)
            # What each thing looks like, too: told only "Other things in the game: sky,
            # tree, monster", the 4B decided the game had "a single tree" and that the six
            # tree pictures "were not added" (the final test04 replay).
            from opennest.fastpath.kinds import games
            from opennest.graphics import source as scene_source

            code = self.project.entrypoint_path.read_text(encoding="utf-8")
            things = scene_source.describe(scene_source.read(code),
                                           games.facts_of(code).get("player"))
        except Exception:  # noqa: BLE001 - a description must never break a turn
            about, things = "", []
        if not things:
            # Nothing has been put in the scene: there is nothing a claim could already be
            # true of, and the measured correction stands (Phase 12.1).
            return ""
        listed = "; ".join(things)
        return (" What the game already has is still there, made before -- do not say it "
                f"is missing: {about}" + (f" Its scene: {listed}." if listed else "")
                + " If what they asked for is already so, tell them it already is, and how "
                  "it looks now.")

    def _has_maze(self) -> bool:
        """Whether the game's scene has a maze laid out (``layout: maze``)."""
        if not self.project.entrypoint_path.is_file():
            return False
        from opennest.graphics import source as scene_source

        try:
            code = self.project.entrypoint_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        return scene_source.maze_layout(scene_source.read(code)) is not None

    def _getting_started(self, text: str) -> bool:
        """A hello or "what should I do?" -- while the game is still its starter."""
        if not (is_greeting(text) or _WAY_IN.search(text or "")):
            return False
        path = self.project.entrypoint_path
        if not path.is_file():
            return True
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        return evidence.unchanged_starter(self.project, source) is not None

    def _tidy(self, turn: Turn) -> str:
        """The reply as a child should read it -- and an offer, or "".

        Three things the owner's test04 and its replays (4B and 8B) put on screen, none of
        them a model's own fault alone and none of them for a child:

        - **Their own message said back.** Told to answer it again, both models began the
          reply with the child's words, as Gary's. What happened is said instead.
        - **The job handed back.** "You can now make the forest", "Fix the player's
          movement", "Ask for help to add one" -- on what the child asked Gary to make.
          Those sentences go, and the first thing to build among them is offered: "Want me
          to fix the player's movement?"
        - **Pixels.** "The monster at (100, 300) stays still" in every 4B reply. In a game,
          a sentence placing things in numbers goes, unless it is all there is.
        """
        text = turn.text or ""
        if turn.by_recipe or turn.routed:
            return ""
        asked = getattr(self, "_last_request", None) or ""
        if text and echoes(text, asked):
            text = self._what_it_has_now(turn) if not turn.answered else self._as_it_is_text()
        elif text and _OPEN_NEST_PLAN.search(text) and not turn.reduced:
            # **Open Nest's own plan, said as Gary's.** Measured on the game builds
            # (SPIKES.md section 33): asked "add coins to collect and a score", Gary Fast
            # changed nothing and answered with the plan Open Nest wrote the turn before,
            # word for word -- about scrolling trees -- which the reply filters then cut
            # into "1. ... 2. 3. ...". Those sentences are only ever Open Nest's.
            text = self._what_it_has_now(turn) if self._changed_anything(turn) \
                else self._nothing_changed_text(turn)
        if re.fullmatch(r"\s*I found a problem\.\s*I'm fixing it\.\s*", text or "") and \
                not turn.repair_attempts and all(
                    test.verdict == playtest.PASSED for test in turn.playtests):
            # The base prompt's own example, said as the whole reply after a change that
            # worked, and to a question (the test04 replay, 8B, three times): nothing was
            # found and nothing is being fixed. Say what was done, or what is there.
            text = self._describe_what_happened(turn) or self._as_it_is_text()
        if plays_in_panel(self.project):
            text = without_coordinates(text)
        offer = ""
        # Build it and teach me: telling them how to change it themselves is the point.
        # And an answer's ideas are ideas: "Add a red circle..." to "any ideas?" is right.
        handed = handed_back(text) if self.build_style != "teach" else []
        if turn.answered:
            handed = [sentence for sentence in handed if _ASK_AGAIN.search(sentence)]
        if handed:
            offer = next((found for found in map(as_offer, handed) if found), "")
            kept = [sentence for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
                    if sentence.strip() and sentence.strip() not in handed]
            text = "\n".join(sentence.strip() for sentence in kept)
            if not text.strip():
                text = self._describe_what_happened(turn) or self._as_it_is_text()
        turn.text = text
        return offer

    @staticmethod
    def _changed_anything(turn: Turn) -> bool:
        """A file changed, or a run drew a chart, in Gary's share of the turn.

        The chart counts: on the parity walk "Graph this." ran the Research starter, which
        drew charts/chart.png, and the turn was treated as having done nothing -- planned
        into steps and reported "I haven't changed anything yet"."""
        return any(result.changed_files or result.made_files
                   for _, result in turn.tool_results[turn.gary_from:])

    @staticmethod
    def _describe_what_happened(turn: Turn) -> str:
        """Say what was done when the model did it without saying anything.

        Found by the Anthropic parity run (SPIKES.md section 13). Sonnet 5 repaired a
        broken game correctly -- read, edit, clean run -- and produced no prose at all,
        so ``turn.text`` was empty and the Workbench showed the child **no reply**.
        Their game was fixed and nothing said so.

        Luna narrates and hid this; it is not provider-specific, and the local model can
        do it too. The application knows exactly what happened from the tool results, so
        it says so itself rather than spending a provider call asking the model to
        repeat itself in words.

        **"It works." is only said for a run that finished.** An interactive run is
        ``ok`` the moment it survives four seconds, and Phase 12.4 measured how little
        that says: a game can launch and do nothing at all (SPIKES.md section 24). So a
        game that launched is described as having started -- which is all a launch
        shows -- and nothing here claims the child's feature was checked.
        """
        mine = turn.tool_results[turn.gary_from:]
        changed = sorted({path for _, result in mine for path in result.changed_files})
        ran = [result for _, result in mine if result.run is not None]
        last_run_ok = ran and ran[-1].ok
        only_launched = last_run_ok and ran[-1].run.still_running
        made = ran[-1].made_files if ran else ()
        drew = f" It drew {', '.join(made)}." if made else ""

        drawn = _scene_changes(mine)
        if drawn:
            # game_object's own results say exactly what was made (Phase 13C).
            return drawn
        if changed and only_launched:
            return f"I changed {', '.join(changed)} and started it."
        if changed and last_run_ok:
            return f"I changed {', '.join(changed)} and ran it. It works.{drew}"
        if changed:
            return f"I changed {', '.join(changed)}."
        if last_run_ok:
            return f"I ran it.{drew}"
        if ran:
            return "I ran it, and it did not work."
        return ""

    def _roll_over_if_needed(self, turn: Turn) -> None:
        """Hand this thread over to the next one, silently (WORKORDER_01 section 15A).

        This runs only after the turn is complete, so the child has already read the
        reply; nothing here changes what they see. Section 15A step 1 requires exactly
        that ordering, and steps 7 and 8 are the ``_reset_history`` below -- the new
        thread's system prompt is rebuilt with the memory the old one just wrote.

        **A rollover is one more billable call and spends from the same turn budget.**
        If nothing is left it is skipped, not forced: the threshold will still be over
        on the next turn, and closing the project rolls over regardless. Deferring
        costs a slightly longer thread; forcing it would let a turn that already ran
        away spend one more time. That is also what stops repair and rollover
        compounding -- a turn that burned its budget repairing cannot then roll over.
        """
        if self.memory is None or not self.memory.should_roll_over(self.history):
            return
        budget = getattr(self, "_budget", None)
        if budget is not None and budget.exhausted:
            return
        metered = getattr(self, "_metered", None) or self.provider
        if isinstance(metered, MeteredProvider):
            metered.kind = ROLLOVER
        try:
            result = self.memory.roll_over(metered, self.history)
        except BudgetExhausted:
            return
        if result.happened:
            self._reset_history()
            turn.rolled_over = True

    def close(self, *, summarise: bool = True) -> None:
        """End this project's thread. Called when the project closes, not per turn.

        Closing summarises, including on quit. An earlier version skipped the model call
        when quitting, on the reasoning that an application must not pause on Command-Q.
        That traded the wrong thing away: a session long enough for summarising to be
        slow has *already* rolled over, so the transcript left at close is bounded by the
        rollover threshold and is usually far shorter. Quit latency and rollover latency
        are therefore the same unmeasured number, and special-casing quit bought a
        bounded saving at the cost of losing the decisions of every session that never
        crossed the threshold -- which is most short sessions, and exactly the ones
        updating memory at close exists for.

        ``summarise=False`` remains as the lever if that measurement (SPIKES.md section 9)
        comes back badly, and as the way to end a thread without touching the model.
        """
        if self.memory is not None:
            self.memory.close(self.provider if summarise else None, self.history)
            self._reset_history()

    def _checkpoint(self, label: str) -> str | None:
        if self.versions is None:
            return None
        # Versioning must never break the thing the child is doing -- except for a
        # credential, which save_quietly still raises for.
        return self.versions.save_quietly(label)

    def _described_a_file_it_cannot_see(self, text: str, said: str) -> str | None:
        """Catch the model describing an imported file nobody has looked inside.

        The prompt already forbids this, and SPIKES.md section 10 measured that the
        prompt is not enough: the honesty block took the model from 25% to 50% honest
        and left it answering "does the dragon in my picture have wings?" with "Yes...
        I see them clearly." So the application checks, exactly as it checks for a
        claimed edit that never happened.

        The decision of what counts lives in :func:`assets.invented_description`, and is
        deliberately narrow -- naming the file, and repeating a word the child used, are
        both fine.
        """
        unread = assets.unread_assets(self.project, getattr(self.provider, "info", None))
        if not unread:
            return None
        # The child's words are theirs whenever they said them, and a thing the game
        # already has is the game's: measured on the owner's test04 and its 4B replay,
        # "the monster" -- what the child had called blue_monster.png two messages before,
        # and a thing in the scene -- was taken for a description of the picture on every
        # turn after, and Gary was made to say "I did not see its content. I did not use
        # it" instead of what he had done.
        known = " ".join((said, *getattr(self, "_child_said", ()), *self._scene_names()))
        return assets.invented_description(text, known, unread)

    def _scene_names(self) -> list[str]:
        """The names of the things in the game's scene, as words."""
        if not plays_in_panel(self.project) or not self.project.entrypoint_path.is_file():
            return []
        from opennest.graphics import source as scene_source

        try:
            code = self.project.entrypoint_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        return [name.replace("_", " ") for name in scene_source.read(code).entries]

    def _claim_in(self, turn: Turn, text: str) -> str:
        """"change", "result", or "" -- what kind of claim of a change nobody made.

        "result" is the Phase 13 owner-test case: nothing changed this turn or the one
        before, and the reply says something "is now" so. Checked before the plain
        denial on purpose, because the measured reply began with one: "I haven't changed
        any file yet. ... The eagle is now flying from left to right."
        """
        mine = turn.tool_results[turn.gary_from:]
        if any(result.changed_files or result.made_files for _, result in mine):
            return ""
        lowered = (text or "").lower()
        quiet = self._quiet_lately(turn)
        if turn.answered:
            # An answer changes nothing by design, so "I added the Fossils section" is
            # about an earlier turn -- true if one changed a file. Measured on the parity
            # walk: judged against this turn alone, a true answer was "corrected" with
            # "Call edit_file now" in a turn that has no tools.
            if not quiet:
                return ""
            claimed = (any(phrase in lowered for phrase in CLAIMED_RESULT)
                       or UNDERWAY_START.search(text or "")
                       or self._claimed_a_change_it_did_not_make(turn, text))
            return "result" if claimed else ""
        if quiet and (any(phrase in lowered for phrase in CLAIMED_RESULT)
                      or UNDERWAY_START.search(text or "")):
            return "result"
        return "change" if self._claimed_a_change_it_did_not_make(turn, text) else ""

    @staticmethod
    def _claimed_a_run_it_did_not_do(turn: Turn, text: str) -> bool:
        """"I compiled the project", "I tested it" -- with nothing run, compiled or tested.

        Measured on the parity walk: an Arduino turn edited the sketch and said "I
        compiled the project" with no compile. Checked whatever else the turn changed,
        because a real edit does not make a claimed compile true. A game's headless test
        counts as testing it, and a run or a compile of any kind counts as running it.
        """
        lowered = (text or "").lower()
        if not any(phrase in lowered for phrase in CLAIMED_RUN):
            return False
        mine = turn.tool_results[turn.gary_from:]
        return not (turn.playtests or any(result.run is not None for _, result in mine))

    def _quiet_lately(self, turn: Turn) -> bool:
        """No file changed in this turn, in the last few, or outside a turn since.

        "The last few", not "the last one": measured on the parity walk, a question in
        between ("how do I undo that?") made a gallery added two turns earlier count as
        never made, and "What did you change?" was corrected into denying it."""
        if turn.scaffolded or any(result.changed_files or result.made_files
                                  for _, result in turn.tool_results):
            return False
        if self._outside:
            return False
        return not any(getattr(self, "_recent_changes", [])[-QUIET_TURNS:])

    def _not_drawn(self, text: str) -> list[str]:
        """Things named in ``text`` that the game's code has and never draws."""
        if not plays_in_panel(self.project):
            return []
        entry = self.project.entrypoint_path
        try:
            source = entry.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        nouns = child_nouns(text)
        return evidence.undrawn(source, nouns) or evidence.made_every_frame(source, nouns)

    def _promised_more(self, turn: Turn) -> bool:
        """Gary's share changed something, and his last word says he will do more now."""
        if turn.answered or not self._changed_anything(turn):
            return False
        budget = getattr(self, "_budget", None)
        if budget is None or budget.remaining < 2:
            return False
        text = turn.text or ""
        last = re.split(r"(?<=[.!?])\s+", text.strip())[-1] if text.strip() else ""
        return "?" not in last and promises(last)

    def _only_promised(self, turn: Turn, text: str) -> bool:
        """A request, Gary's share changed nothing, and his last word is that he will --
        not a question back to the child, which is a fair way to end a turn.

        Telling the child how to edit the code is the same thing: measured on the stress
        pass, "Make it stay on for two seconds" was answered "Here is the exact text to
        replace: ... Replace it with: ..." with no call made (SPIKES.md section 29)."""
        if is_question(text) or self._changed_anything(turn):
            return False
        lowered = (turn.text or "").lower()
        # A question back is a fair end -- but not "What do you want next?" after "I'll
        # replace the trees with your pictures" and no call (the Gary Smart test04
        # replay, twice; on the 782 replies of the kept walks it is only those two).
        questions = re.findall(r"[^.?!\n]*\?", lowered)
        if questions and not all(_NEXT_QUESTION.search(q) for q in questions):
            return False
        return promises(lowered) or instructs_edit(turn.text)

    def _repeats_undone(self, text: str) -> bool:
        """Whether a reply says again what the reply an Undo took back said -- a sentence
        of five words or more, word for word."""
        undone = getattr(self, "_undone", "")
        if not undone or not text:
            return False

        def sentences(words: str) -> set[str]:
            return {" ".join(part.lower().split()) for part in
                    re.split(r"(?<=[.!?])\s+|\n+", words) if len(part.split()) >= 5}

        return bool(sentences(text) & sentences(undone))

    def _files_said_wrongly(self, turn: Turn) -> list[str]:
        """Files the reply names that the project has not got, or says were changed when
        nothing changed them lately (``replies.files_said_wrongly``). After a change
        outside a message -- an Undo, a hand edit -- only a missing file is said."""
        try:
            files = visible_files(self.project.directory)
        except OSError:
            return []
        recent = set().union(*getattr(self, "_recent_paths", [])[-QUIET_TURNS:])
        recent |= {path for _, result in turn.tool_results
                   for path in (*result.changed_files, *result.made_files)}
        recent |= set(turn.scaffolded)
        return files_said_wrongly(turn.text, files, recent,
                                  unchanged=not (self._outside or turn.scaffolded))

    def _colours_nobody_used(self, turn: Turn) -> dict[str, str]:
        """Colours Gary says his change to a website has, that none of its files do.

        Only in a website, and only about a change of his to its CSS or HTML this turn:
        what he just did is what he describes. Read generously -- a colour named anywhere
        in the files, or any value near it ("coral" on an orange), is enough."""
        if evidence.family(self.project) != "website":
            return {}
        mine = turn.tool_results[turn.gary_from:]
        if not any(path.endswith((".css", ".html"))
                   for _, result in mine for path in result.changed_files):
            return {}
        families, words = evidence.page_colours(self.project)
        said = colours_said(turn.text, evidence.COLOUR_WORDS)
        return {word: sentence for word, sentence in said.items()
                if word not in words and not evidence.COLOUR_WORDS[word] & families}

    def _hardware_claims(self, text: str) -> list[str]:
        """Sentences saying what a real board or Pi did -- only in a project for one."""
        if evidence.family(self.project) not in ("arduino", "raspberry_pi"):
            return []
        return hardware_claims(text)

    def _without_hardware_claims(self, text: str, claims: list[str]) -> str:
        kept = text
        for sentence in claims:
            kept = kept.replace(sentence, "")
        kept = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", kept)).strip()
        if evidence.family(self.project) == "raspberry_pi":
            fact = (f"Nothing has run on a real Raspberry Pi, so nobody has seen the light: "
                    f"{self.project.profile.run_label} shows what the pins would do.")
        else:
            fact = ("Open Nest can't see your board: once it is on the board with Send to "
                    "Board, only you can see what it does.")
        return f"{kept}\n\n{fact}".strip()

    def _names_what_is_not_there(self, turn: Turn, text: str) -> str | None:
        """A thing the child asked for, said to be in the game, when its code has none.

        Read against the code as it is when the reply is given, whatever changed this
        turn: a word that appears nowhere in the game's files is not in the game. Measured
        both ways on the owner-test walk -- "Look for the eagle moving back and forth"
        straight after the Basic Game was set up, and "The cars are parked below" after an
        edit that added an eagle and no car. Only in a game, where the measurement was;
        only a sentence that says so rather than suggests, plans or denies it; and only a
        word the child used for a thing ("an eagle", "the cars"), looked for in every file
        under src/. A thing Gary made under another name is the case this cannot tell,
        and it costs one correction, never a wrong word on screen.
        """
        project = self.project
        wanted = self._asked_for
        if not wanted or not text:
            return None
        source = ""
        if plays_in_panel(project):
            # A game: its code's names and strings, never its comments -- and never Open
            # Nest's scene kit, which names every drawing it can make (Road, Building,
            # Vehicle...). Read, it made "the road" true of a game with no road (the final
            # 13C walk, SPIKES.md section 28E).
            from opennest.graphics import looks

            for path in sorted((project.directory / "src").rglob("*.py")):
                try:
                    code = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if path.name == "scene.py" and looks.kit_version(code) is not None:
                    continue
                words = evidence.code_words(code)
                if words is None:
                    return None       # code that does not parse: nothing can be said
                source += words + "\n"
        elif evidence.family(project) == "website":
            # A website: everything its page files say. Measured on the parity walk: after
            # an Undo took the gallery out, "The gallery is now in the page" was relayed.
            # Only when the page is not Gary's fresh work -- nothing changed by him this
            # turn or the last, or something (an Undo) changed it since: word by word
            # against HTML, a false "no menu" made him deny a change he had just made.
            fresh = any(result.changed_files for _, result in turn.tool_results) or (
                not self._outside and self._last_outcome.startswith("Last time, these"))
            if fresh:
                return None
            for path in sorted((project.directory / "src").rglob("*")):
                if path.suffix.lower() in (".html", ".css", ".js"):
                    try:
                        source += path.read_text(encoding="utf-8").lower() + "\n"
                    except (OSError, UnicodeDecodeError):
                        continue
        else:
            return None
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            lowered = sentence.lower()
            if NOT_ASSERTED.search(lowered):
                continue
            for word in sorted(wanted):
                stem = word[:-1] if word.endswith("s") and len(word) > 3 else word
                forms = (stem, *_PAGE_FORMS.get(stem, ())) if not plays_in_panel(project) \
                    else (stem, *_SCENE_FORMS.get(stem, ()))
                if stem in ("maze", "labyrinth") and plays_in_panel(project):
                    # A maze is a layout, not a word: a "maze_wall" building made "the maze
                    # has walls and a path" true of a game with no maze (Maze_test01).
                    if re.search(rf"\b{stem}s?\b", lowered) and not self._has_maze():
                        return word
                    continue
                if re.search(rf"\b{stem}s?\b", lowered) and not any(
                        form in source for form in forms):
                    return word
        return None

    def _claims_what_was_refused(self, turn: Turn) -> tuple[str, str] | None:
        """A correction when the reply says it changed something whose every edit this
        turn was refused -- or None.

        The turn-level guard (``_claimed_a_change_it_did_not_make``) only looks when
        nothing changed at all. Measured on the final 4B walk (SPIKES.md section 28E):
        "more colourful" changed the coins and the sky, and three edits to lines the
        model imagined -- ``road.color = 'gray'`` -- were refused; the reply said the
        roads were dark grey, the buildings tan and the clouds light grey. Only things
        named in a refused call and in no call that landed are considered, and only in a
        sentence that says so.
        """
        refused: set[str] = set()
        landed: set[str] = set()
        #: What each refused edit would have made a thing: "dark" in 'dark gray'.
        values: set[str] = set()
        for tool, arguments, result in turn.calls:
            words = _call_words(tool, arguments)
            if (result.ok and (result.changed_files or result.made_files)) or \
                    result.reason == "no_change":
                # "It already looks like that" is the thing as asked, not a failure --
                # measured, counting it refused made "the road remains gray" a false alarm.
                landed |= words
            elif not result.ok and tool in ("edit_file", "game_object", "write_file"):
                refused |= words
                old = set(re.findall(r"[a-z]{3,}", str(arguments.get("old_text", "")).lower()))
                new = set(re.findall(r"[a-z]{3,}", str(arguments.get("new_text", "")).lower()))
                values |= new - old
                if tool == "game_object":
                    values |= set(re.findall(r"[a-z]{3,}", str(
                        arguments.get("color", "")).lower()))
        things = {_singular(word) for word in getattr(self, "_asked_for", set())}
        if plays_in_panel(self.project):
            from opennest.graphics import source as scene_source

            try:
                scene = scene_source.read(self.project.entrypoint_path.read_text(
                    encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                scene = None
            if scene is not None:
                things |= {_singular(name) for name in scene.entries}
        suspects = {word for word in refused - landed if len(word) > 2
                    and _singular(word) in things}
        if not suspects or not turn.text:
            return None
        said = []
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", turn.text):
            lowered = sentence.lower()
            if "?" in lowered or _OFFERED.search(lowered):
                continue
            words = set(re.findall(r"[a-z]+", lowered))
            if not words & (_CHANGE_WORDS | values):
                continue
            said += sorted({word for word in words if word in suspects or
                            _singular(word) in suspects} - set(said))
        if not said:
            return None
        listed = ", ".join(said[:4])
        one = len(said) == 1 and not said[0].endswith("s")
        looks = "looks as it did -- that change" if one else "look as they did -- those changes"
        # The scene's tool only where there is one: said in a Pi project, Luna told the
        # child "No scene object was changed" (the stress pass, SPIKES.md section 29).
        scene = (" To change how a thing in the scene looks, use game_object with its name "
                 "and the new colour." if "game_object" in self.toolbox.allowed else "")
        return (f"The changes to the {listed} did not go in -- those edits were refused, so "
                f"{'it looks' if one else 'they look'} as before. Say only what really "
                f"changed.{scene}",
                f"Open Nest: the {listed} {looks} did not go in.")

    def _scene_claims(self, text: str) -> str | None:
        """A correction for what a reply says a scene's thing does or where it is, when
        the scene says otherwise -- or None.

        Measured on the final Qwen3 8B walk (SPIKES.md section 28E): "avoid the cars" and
        "collect coins" about things whose touch did nothing (the tool's own result said
        so), and "10 cars moving left across the road" about cars driving along the top
        of the screen. The scene knows both; only its own things are checked, and only in
        a sentence that says so.
        """
        if not text or not plays_in_panel(self.project):
            return None
        from opennest.graphics import source as scene_source

        try:
            scene = scene_source.read(self.project.entrypoint_path.read_text(
                encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return None
        if not scene.adopted:
            return None
        names = {form: name for name in scene.entries for form in (
            name, _singular(name), name + "s")}
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            lowered = sentence.lower()
            # Not NOT_ASSERTED: "now you can avoid the cars" says what the game does. Only
            # an offer, a question or a denial is left alone here.
            if "?" in lowered or _OFFERED.search(lowered):
                continue
            for verb, wanted, fix in (("avoid|dodge", "avoid", "avoid"),
                                      ("collect|grab|catch|pick up", "collect", "collect")):
                for match in re.finditer(rf"\b(?:{verb})\w*\s+(?:the\s+|all\s+the\s+)?"
                                         rf"(?:\w+\s+){{0,2}}?(\w+)\b", lowered):
                    name = names.get(match.group(1))
                    if name and scene_source.touch_rule(scene, name) != wanted:
                        does = "send the player back" if wanted == "avoid" else \
                            "score a point"
                        return (f"Touching the {name} does not {does} in the game -- "
                                f"nothing in its code does that. Say what touching them "
                                f"really does, or give them touch: {fix} with game_object.")
            for match in re.finditer(r"\b(?:on|along|across|down)\s+the\s+(road|ground|"
                                     r"street|grass)\b", lowered):
                band = match.group(1)
                for word in re.findall(r"[a-z]+", lowered):
                    name = names.get(word)
                    if not name or name == band or name not in scene.entries:
                        continue
                    where = scene_source.relation(scene, name)
                    if where.startswith(("above", "below")):
                        return (f"The {name} are {where} -- not on it. Say where they "
                                f"really are, or put them on it with game_object and "
                                f"on: \"{band}\".")
        return None

    def _counts_nobody_made(self, text: str) -> tuple[str, int, int] | None:
        """"Three red cars are now at..." about a game whose scene has one car.

        Measured on the third 4B walk (SPIKES.md section 28E): three game_object calls all
        named "car", each replacing the last, and a reply counting three. The scene knows
        how many of each thing it makes, so a number said about one is checked -- only in
        a game with a scene, only for a thing in it, and only in a sentence that says so.
        """
        if not text or not plays_in_panel(self.project):
            return None
        from opennest.fastpath.kinds import games
        from opennest.graphics import source as scene_source

        try:
            source = self.project.entrypoint_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        scene = scene_source.read(source)
        if not scene.adopted:
            return None
        constants = games.facts_of(source).get("constants") or {}
        counts = {}
        for entry in scene.entries.values():
            if entry.wraps:
                continue
            count = entry.literals.get("count", 1)
            if isinstance(entry.literals.get("at"), list):
                count = len(entry.literals["at"])
            elif isinstance(entry.keywords.get("count"), str) and \
                    entry.keywords["count"] in constants:
                count = constants[entry.keywords["count"]].value
            if isinstance(count, int):
                counts[entry.name] = count
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            if NOT_ASSERTED.search(sentence.lower()):
                continue
            for match in _COUNTED.finditer(sentence.lower()):
                said = _NUMBERS.get(match.group(1)) or (int(match.group(1))
                                                        if match.group(1).isdigit() else 0)
                noun = match.group(2)
                for form in (noun, _singular(noun), noun + "s"):
                    actual = counts.get(form)
                    if actual is not None and said and actual != said:
                        return noun, actual, said
        return None

    def _numbers_nobody_printed(self, reply: str, asked: str) -> list[str]:
        """In a data project, numbers in the reply that no output or check contains.

        Only numbers with a decimal point or of two digits and more -- "3 cities" is a
        count anyone can make -- and only against what exists: the last run's output, the
        data summary Open Nest read (``evidence``), and the child's own words."""
        if evidence.family(self.project) != "research" or not reply:
            return []
        known = " ".join((
            getattr(getattr(self.toolbox, "last_run", None), "stdout", "") or "",
            evidence.checked_block(self.project, self.toolbox, (), ()),
            asked,
        ))
        found = re.findall(r"(?<![\w.])(\d+\.\d+|\d{2,})(?![\w.])", reply)
        # A range worked out from what is known is not a guess: measured, "27.6" was
        # 31.5 - 3.9, from "temp_c from 3.9 to 31.5". Only those spans -- allowing any
        # sum or difference of every known number would let almost anything through.
        spans = [float(high) - float(low) for low, high in re.findall(
            r"from (-?\d+(?:\.\d+)?) to (-?\d+(?:\.\d+)?)", known)]

        def derived(number: str) -> bool:
            return any(abs(span - float(number)) < 0.051 for span in spans)

        return [number for number in dict.fromkeys(found)
                if number not in known and number.rstrip("0").rstrip(".") not in known
                and not derived(number)]

    def _claimed_to_see(self, text: str) -> bool:
        """"I see", "I can see" -- when nothing has shown Gary anything to see.

        A picture attached to this message and really shown to the model as pixels is
        the one exception (``_shown``): there, "I can see a blue monster" is true.
        """
        if getattr(self, "_shown", ()):
            return False
        lowered = (text or "").lower()
        if not any(phrase in lowered for phrase in CLAIMED_SIGHT):
            return False
        # ...and a sentence about a picture a model really looked at ("I can see your
        # monster picture has purple spots") is not about the screen: it was seen, at
        # import (``assets.look``). Narrow on purpose -- the sentence has to be about a
        # picture, so "I see the monster is missing" is still a claim about the game.
        seen = [asset for asset in assets.list_assets(self.project) if asset.seen]
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", lowered):
            if not any(phrase in sentence for phrase in CLAIMED_SIGHT):
                continue
            about_a_picture = seen and (_PICTURE_WORD.search(sentence) or any(
                asset.name.lower() in sentence for asset in seen))
            if not about_a_picture:
                return True
        return False

    def _what_it_has_now(self, turn: Turn) -> str:
        """What this turn did and what the game has, in Open Nest's words."""
        done = self._describe_what_happened(turn)
        if not done:
            return self._as_it_is_text()
        about = self._as_it_is_text().replace("I haven't changed anything in the game yet. ",
                                               "")
        return f"{done} {about}" if about.startswith("Right now") else done

    def _as_it_is_text(self) -> str:
        """What the project has now, from Open Nest's own reading of it."""
        project = self.project
        if not project.entrypoint_path.is_file():
            if project.profile.playtest == "pygame":
                return ("There isn't a game here yet. I can make the starting game for you "
                        "-- tell me what you'd like to build -- or you can add the Basic "
                        "Game from the Project panel.")
            return "There's nothing in this project yet. Tell me what you'd like to make."
        try:
            about = evidence.describe_game(project, for_child=True)
        except Exception:  # noqa: BLE001 - a description must never break a turn
            about = ""
        try:
            source = project.entrypoint_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            source = ""
        # Only claim nothing has changed when the files say so -- measured, the generic
        # sentence was said about a page two recipes had just changed.
        untouched = evidence.unchanged_starter(project, source) is not None
        if about:
            play = ""
            if plays_in_panel(project):
                play = (f" To play it, press {project.profile.run_label} and click inside "
                        f"the game so it gets the keys.")
            lead = "I haven't changed anything in the game yet. " if untouched else ""
            return f"{lead}Right now: {about}{play}"
        summary = evidence.summary_for_child(project)
        lead = "I haven't changed anything in the project yet." if untouched else ""
        return " ".join(part for part in (lead, summary) if part) or \
            "Here's where things are: the files are in the Project panel on the left."

    @staticmethod
    def _claimed_a_change_it_did_not_make(turn: Turn, text: str) -> bool:
        """Catch the model reporting an edit it never performed.

        Phase 2 saw exactly this: read_file, then "I increased the player speed from 5
        to 8" with no write. The base prompt forbids it, but a 4B model does it anyway,
        so the application checks rather than trusts.

        A reply that plainly denies changing anything is never a claim, however it is
        phrased afterwards. That branch is the *permitted* outcome -- the acceptance
        rule asks for a real tool call or a plain "I have not changed it yet", and this
        is what keeps the second one from being mistaken for the first.
        """
        mine = turn.tool_results[turn.gary_from:]
        if any(result.changed_files or result.made_files for _, result in mine):
            return False
        lowered = (text or "").lower()
        if any(phrase in lowered for phrase in _DENIED_CHANGE):
            # A denial covers "I made a mistake reading the file" -- but not work said to
            # be under way now with no call made: "I haven't changed any file yet. ... I'm
            # adding the eagle and cars" (the owner-test walk) is still a claim.
            return not mine and any(phrase in lowered for phrase in _CLAIMED_UNDERWAY)
        if any(phrase in lowered for phrase in _CLAIMED_CHANGE):
            return True
        ran = any(result.run is not None for _, result in mine)
        return not ran and any(phrase in lowered for phrase in _CLAIMED_TEST)

    def _nothing_changed_text(self, turn: Turn, *, too_big: bool = False) -> str:
        """What the child is told when the model insists on a change that did not happen.

        Composed by the application from the tool results, never by the model, for the
        reason ``_describe_what_happened`` exists: the application knows the answer
        deterministically and asking again costs a provider call and can come back
        wrong a third time.

        It says the one thing that is certainly true -- nothing changed -- and then what
        is blocking, which WORKORDER_01's acceptance direction asks for. Two things it
        deliberately does not do:

        - **It does not quote the refused tool's own message.** That text is written for
          the model ("Read the file again and copy the line you want to change exactly
          as it appears") and putting it in front of a child is instructions meant for
          somebody else.
        - **It does not name a cause it has not checked.** ``edit_file`` refuses for
          four different reasons and ``write_file`` for four more; an earlier draft of
          this said "the text I tried to replace was not in the file", which was the
          measured case and would have been a fresh invention in the other seven. The
          application knows a change was attempted and refused, so that is what it says.

        Brand guide section 9: an error is something unexpected, not a failure, and the
        reply ends with the way forward rather than the fault. When nothing was even
        attempted, the way forward is a first step this project type is known to handle
        (``_FIRST_STEPS``): the owner's first test drive asked for a whole isometric game
        in one sentence and was told, twice, to "tell me again what you want different".
        ``too_big`` is only ever passed when the model is known to have run out of room
        writing a call -- the one case where "too much in one go" is a checked cause.
        """
        refused = {
            normalise_tool_name(name)
            for name, result in turn.tool_results[turn.gary_from:]
            if not result.ok
        }
        if turn.block_world_started:
            # Open Nest made the 3D game this turn; Gary's own extra changes did not land.
            return block_world.READY
        if block_world.of_project(self.project) and turn.plan_step is None:
            try:
                has = block_world.summary_for_child(
                    self.project.entrypoint_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                has = ""
            first = ("I haven't changed that yet. My edit didn't match the file cleanly, so "
                     "I left it alone." if refused & {"edit_file", "write_file"}
                     else "I haven't changed anything yet.")
            now = f" Right now the 3D world has {has}." if has else ""
            return (f"{first}{now} Tell me what you'd like different -- the sky, the blocks "
                    f"and where they go, or how fast you walk.")
        if turn.plan_step is not None:
            # A plan's step: what is next is the plan's to say ("Want me to try it
            # again?"), so no second way forward -- and no "try one small piece first",
            # which this already is.
            if refused & {"edit_file", "write_file"}:
                return ("I haven't changed that yet. My edit didn't match the file cleanly, "
                        "so I left it alone.")
            return "I haven't changed that yet."
        if turn.gary_from and turn.prefix:
            # Recipes made part of the message; this is about Gary's part only.
            rest = " and ".join(f"\u201c{part}\u201d"
                                for part in (turn.fastpath or {}).get("remaining", ()))
            return f"I haven't done the rest yet{f' ({rest})' if rest else ''}."
        # Offered, not handed back: "Say it again" made the child the retry loop (the
        # owner's test04 replays, both models).
        if refused & {"edit_file", "write_file"}:
            return (
                "I haven't changed that yet. My edit didn't match the file cleanly, so "
                "I left it alone. Want me to try it another way?"
            )
        if refused:
            return (
                "I haven't changed that yet. What I tried didn't work. "
                "Want me to try it another way?"
            )
        first = "I haven't changed anything yet."
        if too_big:
            first += " That was too much for me to write in one go."
        steps = _FIRST_STEPS.get(self.project.profile.id)
        if not steps:
            return f"{first} Try asking for one small piece of it first."
        examples = " or ".join(f"\u201c{step}\u201d" for step in steps)
        return f"{first} Try one small piece of it first -- for example {examples}."

    def _generate(self, on_text: Callable[[str], None] | None, *, turn: Turn | None = None):
        """One provider call, metered, with one retry if the answer came back empty.

        The retry exists because a reasoning model can spend its entire output
        allowance thinking and return a mechanically successful response with nothing
        in it (SPIKES.md section 11). That reaches a child as silence, so it is worth
        one more attempt with more room -- and exactly one, from the shared budget,
        because a model that cannot fit an answer in four times the space will not fit
        it in eight either.
        """
        reply = self._call(on_text, Settings(temperature=0.0), turn=turn)
        return reply

    def _call(self, on_text, settings: Settings, *, turn: Turn | None,
              retried: bool = False):
        provider = getattr(self, "_metered", None) or self.provider
        self.toolbox.report(Step("thinking", "thinking"))
        answering = getattr(self, "_answering", False)
        tools = None if answering else schemas_for(self.toolbox.allowed)
        try:
            for chunk in provider.chat(self.history, tools=tools, settings=settings):
                if chunk.text and on_text:
                    on_text(chunk.text)
            reply = provider.finish()
        except TruncatedReply:
            if retried:
                # Already given more room once. Stop rather than keep paying.
                raise
            if isinstance(provider, MeteredProvider):
                provider.kind = RECOVERY
            if turn is not None:
                turn.recovered_truncation = True
            roomier = Settings(
                temperature=settings.temperature,
                max_tokens=settings.max_tokens * 4,
                seed=settings.seed,
            )
            return self._call(on_text, roomier, turn=turn, retried=True)

        # The provider already counted the prompt, so the context budget never needs to
        # re-tokenise anything (conversations.context_budget).
        if self.memory is not None:
            self.memory.observe(reply)
        if answering and reply.tool_calls:
            # A call written out in an answer is not run: a question changes nothing.
            reply = replace(reply, tool_calls=())
        return reply

    def _run_tools(self, calls: tuple[ToolCall, ...], turn: Turn) -> bool:
        """Execute calls and append results. Returns whether to keep going."""
        for call in calls:
            result = self.toolbox.dispatch(call.name, call.arguments)
            turn.tool_results.append((call.name, result))
            turn.calls.append((normalise_tool_name(call.name) or "",
                               call.arguments if isinstance(call.arguments, dict) else {},
                               result))
            self.history.append(
                Message(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=result.content,
                )
            )
            if result.changed_files or result.run is not None:
                self.refresh_state()

            # A failed run is the repair loop's trigger, not an ordinary tool reply.
            if normalise_tool_name(call.name) in ("run_project", "compile_project") \
                    and not result.ok:
                self._repair(turn)
                return False
        return True

    def _repair(self, turn: Turn) -> None:
        """Try to fix a failing project, at most MAX_REPAIR_ATTEMPTS times.

        After that, stop and explain. WORKORDER_01 section 28 is explicit that this must
        not loop indefinitely -- a child watching an AI fail the same way five times is a
        worse experience than being told plainly that it is stuck.

        Two ceilings apply, and the tighter one wins. This one is section 28's three
        attempts. The other is the turn's shared call budget, which repair spends from
        like everything else -- so a turn that already used its calls getting here has
        fewer repairs available, or none. That is deliberate: the alternative is each
        subsystem holding its own reserve and the total being nobody's problem.

        The attempt count is the turn's, not this method's: a game that failed its
        headless test and was sent back for repair has already spent some of the three,
        and a crash that repair then causes gets what is left rather than three more.
        """
        while turn.repair_attempts < MAX_REPAIR_ATTEMPTS:
            turn.repair_attempts += 1
            if isinstance(getattr(self, "_metered", None), MeteredProvider):
                self._metered.kind = REPAIR
            self.history.append(
                Message(
                    role="user",
                    content=(
                        "That failed. Look at the error above, fix the cause by writing "
                        "the corrected file, then run it again."
                    ),
                )
            )
            reply = self._generate(None, turn=turn)
            self.history.append(
                Message(role="assistant", content=reply.text, tool_calls=reply.tool_calls)
            )
            shown = presentable(reply.text)
            if shown:
                turn.text = shown

            if not reply.wants_tool:
                return

            succeeded = False
            for call in reply.tool_calls:
                result = self.toolbox.dispatch(call.name, call.arguments)
                turn.tool_results.append((call.name, result))
                self.history.append(
                    Message(role="tool", name=call.name, tool_call_id=call.id,
                            content=result.content)
                )
                if result.changed_files or result.run is not None:
                    self.refresh_state()
                if result.run is not None and result.ok:
                    succeeded = True
            if succeeded:
                return

        if self._repair_actually_worked(turn):
            return

        turn.gave_up = True
        turn.text = (
            "I tried three times and could not get this working. "
            "Tell me what you want to try next, or we can go back to the last version "
            "that worked."
        )

    def _playtest_wants_repair(self, turn: Turn) -> bool:
        """Test the game after a change; hand a failure back for repair. True to go on.

        Phase 12.4. ``RunResult.ok`` means only that an interactive game outlived its
        four-second startup, so the crash repair above could never react to a game that
        runs and does nothing -- and that was most of what Phase 12.3 measured. Worse,
        all ten of the games in that sample that *did* crash crashed on their first
        frame, where the existing repair would have caught them, had anything run them:
        the model often ends a turn without calling ``run_project``. So the application
        runs the test itself, whenever the turn has changed something since the last one
        (SPIKES.md section 24).

        What counts as failing, and why the list is short, is in
        :mod:`opennest.execution.playtest`. A failure goes back to the model once per
        attempt as the measured result, and the ordinary tool loop carries the fix; the
        next time the model stops, this tests again. Three things bound it:

        - **The turn's repair attempts**, shared with the crash repair: three in all.
        - **The turn's call budget**, which every attempt spends from like everything
          else, so this can never be the thing that runs a turn away.
        - **Unchanged code is never tested twice.** An answer that changes no file has
          fixed nothing, and a second run would only say so again. It still spends an
          attempt, and the model is pulled up rather than let off: measured, handed the
          exact traceback, it replied *"I added the import for random at the top of the
          file"* and called no tool -- the Phase 12.1 fault, which the claim guard cannot
          see here because the turn changed a file earlier on.

        Whichever ends it, the child is told what the test saw, in the application's
        words -- the model's own reply will usually be describing a working game.
        """
        if turn.gave_up:
            return False
        fresh = turn.tool_results[self._tested_through:]
        if not any(result.changed_files for _, result in fresh):
            last = turn.playtests[-1] if turn.playtests else None
            if last is None or not last.failed:
                return False
            return self._send_back(turn, last, last.reminder())

        self._tested_through = len(turn.tool_results)
        result = self.toolbox.playtest()
        if result is None:
            return False
        turn.playtests.append(result)
        if not result.failed:
            return False
        return self._send_back(turn, result, result.feedback())

    def _send_back(self, turn: Turn, result: playtest.Playtest, message: str) -> bool:
        """Spend one repair attempt on ``message``, or give up if none are left."""
        if turn.repair_attempts >= MAX_REPAIR_ATTEMPTS:
            self._gave_up_on_playtest(turn, result)
            return False
        turn.repair_attempts += 1
        self._metered.kind = REPAIR
        self.history.append(Message(role="user", content=message))
        return True

    @staticmethod
    def _gave_up_on_playtest(turn: Turn, result: playtest.Playtest) -> None:
        """Stop, and say what the test saw rather than what the model hoped.

        Same shape as the crash repair's giving up, and it replaces the model's text for
        the same reason ``_nothing_changed_text`` does: the application knows the game
        failed its test, and the reply it would otherwise relay is usually announcing a
        game that works. Only the measured result is named, never a cause.
        """
        turn.gave_up = True
        turn.text = (
            f"I made the change, but when I tested the game "
            f"{_PLAYTEST_GAVE_UP[result.verdict]}, and I couldn't fix that yet. "
            f"Tell me what you want to try next, or we can go back to the last version "
            f"that worked."
        )

    def _repair_actually_worked(self, turn: Turn) -> bool:
        """Check the project before declaring failure, if repair changed anything.

        Measured against the real model (SPIKES.md section 13): Luna spent its three
        attempts reading, then being refused an overwrite, then finally making the
        correct ``edit_file`` -- and because nothing ran afterwards, the loop reported
        "I tried three times and could not get this working" about a game that was, by
        then, fixed. Telling a child their working project is broken is worse than the
        original bug.

        This costs **no provider call**: running the project is a local tool. It only
        happens when repair changed something and never got a clean run, so an
        untouched project is not run again for nothing.
        """
        changed = any(result.changed_files for _, result in turn.tool_results)
        if not changed:
            return False
        result = self.toolbox.dispatch("run_project", {})
        turn.tool_results.append(("run_project", result))
        if not result.ok:
            return False
        self.refresh_state()
        if result.run is not None and result.run.still_running:
            # A game that got past its startup: all that proves is that it starts, and
            # the headless playtest that follows is what says any more (Phase 12.4).
            turn.text = (
                "That took a few tries, but it starts now. "
                "I changed it and started it again to check."
            )
        else:
            turn.text = (
                "That took a few tries, but it works now. "
                "I fixed the problem and ran it to make sure."
            )
        return True


#: Words a sentence uses when it says something was changed.
_CHANGE_WORDS = frozenset(("changed", "change", "now", "made", "turned", "updated", "set",
                           "gave", "painted", "coloured", "colored", "switched"))


#: "What do you want next?" -- a question that asks nothing about the request.
_NEXT_QUESTION = re.compile(r"\b(?:what (?:do you want|would you like)(?: (?:me )?to do)? "
                            r"next|anything else|what(?:'s| is)? next)\s*\?")

#: A sentence about a picture, for ``_claimed_to_see``.
_PICTURE_WORD = re.compile(r"\b(?:picture|image|photo|drawing|png)s?\b")


def _call_words(tool: str, arguments: dict) -> set[str]:
    """The names a tool call was about: game_object's thing, or the identifiers in an
    edit's old and new text ("road" from ``road.color = 'gray'``)."""
    if tool == "game_object":
        name = str(arguments.get("name") or "").lower()
        return {part for part in re.split(r"[^a-z]+", name) if part} | (
            {name.rstrip("s")} if name else set())
    text = " ".join(str(arguments.get(key) or "") for key in ("old_text", "new_text", "path"))
    return {word.lower() for word in re.findall(r"[A-Za-z]{3,}", text)}


#: A sentence that offers, plans or denies rather than says what the game does.
_OFFERED = re.compile(r"\b(?:if you want|want me to|would you like|shall i|i can add|i could|"
                      r"could add|let me know|next|haven't|hasn't|isn't|aren't|not|no|yet|"
                      r"don't|doesn't|didn't|without|instead|nothing)\b", re.IGNORECASE)

#: Numbers a child's game is described with, in words.
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "twenty": 20}
#: "three red cars", "5 coins", "two big fluffy clouds": a number, a few describing
#: words, and the thing.
_COUNTED = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|twelve|"
                      r"twenty)\s+(?:[a-z]+\s+){0,2}?([a-z]{3,}s)\b")


def _picture_word(reason: str, arguments: dict, name: str) -> str:
    """What a picture would be of, from a game_object refusal -- or "" when it is not one a
    picture would answer."""
    from opennest.graphics import looks  # lazily: the graphics layer is optional here

    if reason == "no_such_drawing":
        word = str(arguments.get("drawing") or "")
        if looks.shape_word(word):
            # "square" is a shape, not a thing a picture is of: the owner's test04 was
            # offered "a real square" for its monster. The thing is what it is of.
            word = _singular(name)
    elif reason == "no_picture":
        word = Path(str(arguments.get("picture") or "")).stem
    elif reason == "picture_not_asked":
        word = _singular(name)
    else:
        return ""
    word = re.sub(r"[^a-z ]+", " ", word.lower().replace("_", " ")).strip()
    return word if 2 < len(word) <= 24 and word not in ("player", "image", "picture",
                                                        "sprite") else ""


def _singular(noun: str) -> str:
    if noun.endswith("ies"):
        return noun[:-3] + "y"
    if noun.endswith("es") and noun[:-2].endswith(("s", "x", "ch", "sh")):
        return noun[:-2]
    return noun[:-1] if noun.endswith("s") else noun


def _scene_changes(results) -> str:
    """What game_object calls made this turn, from their results, in plain words -- or "".

    Only when every change in Gary's share came from game_object: its result is the
    machine-readable account of what was done (``opennest.graphics.game_object``), so it
    can be said as it is. Anything else changed as well is said the general way.

    Each thing once, as it ended up. Measured on the owner's test04 replay: three calls
    for one tree were said as "added the tree (a ready-made tree drawing), changed how the
    tree looks and changed how the tree looks".
    """
    import json

    things: dict[str, dict] = {}
    other = False
    for name, result in results:
        if not result.changed_files:
            continue
        if normalise_tool_name(name) != "game_object":
            other = True
            continue
        try:
            record = json.loads(result.content)
        except (TypeError, ValueError):
            return ""
        thing = record.get("object")
        if not thing:
            return ""
        seen = things.setdefault(thing, {"added": False, "removed": False})
        action = record.get("action")
        seen["removed"] = action == "removed"
        seen["added"] = seen["added"] or action == "added"
        for key in ("look", "picture", "count"):
            if record.get(key):
                seen[key] = record[key]
    if not things or other:
        return ""
    added, changed, removed = [], [], []
    for thing, seen in things.items():
        words = thing.replace("_", " ")
        count = seen.get("count")
        picture = seen.get("picture")
        if seen["removed"]:
            removed.append(f"the {words}")
        elif thing == "player":
            changed.append(f"the player is {_look_phrase(seen.get('look'), picture)} now")
        elif seen["added"]:
            plural = words if words.endswith("s") else f"{words}s"
            what = f"{count} {plural}" if isinstance(count, int) and count > 1 else \
                f"the {words}"
            if picture:
                what += f" ({_look_phrase(seen.get('look'), picture)})"
            added.append(what)
        else:
            changed.append(f"the {words} {'are' if words.endswith('s') else 'is'} "
                           f"{_look_phrase(seen.get('look'), picture)} now" if picture
                           else f"I changed the {words}")
    parts = []
    if added:
        parts.append("I added " + _listed(added))
    parts += changed
    if removed:
        parts.append("I took " + _listed(removed) + " out")
    sentence = "; ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def _look_phrase(look, picture) -> str:
    """"your blue_monster.png", "a vehicle drawing", "drawn with shapes"."""
    look = str(look or "")
    if look.startswith("the pictures "):
        return "your pictures, a different one each"
    if picture:
        return f"your {Path(str(picture)).name}"
    match = re.match(r"a ready-made (\w+) drawing", look)
    if match:
        return f"a {match.group(1)} drawing"
    if look.startswith("a drawing of"):
        return "drawn with shapes"
    return look or "drawn differently"


def _listed(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def stream_reply(controller: AgentController, text: str) -> Iterator[str]:
    """Convenience wrapper for callers that want the text as it arrives."""
    pieces: list[str] = []
    controller.send(text, on_text=pieces.append)
    yield from pieces
