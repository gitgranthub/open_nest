"""Gary's voice, and the line between him and Open Nest (Phase 10B).

``brand_design_guide.md`` sections 1-24 are the tone rules; section 3 names Gary and
section 47 keeps him separate from the pixel-art symbols. ``PHASE_10_HANDOFF.md``
section 1 settles the split: Gary is the visible conversational helper, and system-level
messages -- installation, security, account, recovery, status -- stay attributed to Open
Nest rather than pretending Gary said them.

Two kinds of test here, doing different jobs.

**The split** is pinned per call site, because deciding it is the actual work of 10B and
a later edit could quietly move a message to the wrong speaker. ``_turn_failed`` is the
one that matters most: what arrives there is a ``ProviderError``, and Gary announcing a
transport fault would be exactly the pretending the split exists to prevent.

**The register sweep** is a standing guard over every user-visible string in the
application, not just the ones 10B touched. That is what makes a surgical copy pass
defensible: the guide's banned vocabulary was measured absent from the copy before this
phase, and this test is what keeps it absent afterwards. It reads the source rather than
a curated list, so a new screen inherits the rule without anybody remembering to.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from opennest import APP_NAME, ASSISTANT_NAME, SYSTEM_NAME

PACKAGE = Path(__file__).resolve().parent.parent / "opennest"


# --------------------------------------------------------------- who says what

def test_gary_is_the_assistants_name() -> None:
    """Section 3. One constant, so 10C and 10D have a single place to read it."""
    assert ASSISTANT_NAME == "Gary"


def test_system_messages_are_still_attributed_to_open_nest() -> None:
    """The settled split. Gary is a voice; the product still speaks as itself."""
    assert SYSTEM_NAME == APP_NAME == "Open Nest"
    assert SYSTEM_NAME != ASSISTANT_NAME


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def bench(qt_app, tmp_path):
    from opennest.agent.controller import AgentController
    from opennest.agent.tools import Toolbox
    from opennest.ai.provider import Reply
    from opennest.projects.manager import create_project
    from opennest.ui.workbench import Workbench
    from tests.conftest import ScriptedProvider

    project = create_project("Asteroid Game", "games", root=tmp_path / "projects")
    provider = ScriptedProvider([Reply(text="ok")] * 2)
    widget = Workbench(project, AgentController(project, provider, Toolbox(project)))
    yield widget
    if widget._thread is not None:
        widget._thread.quit()
        widget._thread.wait(5000)
    widget.close()


def transcript(bench) -> str:
    return bench._transcript.toPlainText()


def test_a_reply_from_the_model_is_gary_speaking(bench) -> None:
    """The ordinary case: a turn produced text, so Gary said it."""
    class _Turn:
        text = "I made the asteroids start slower and speed up."
        tool_results = ()
        checkpoint = None

    bench._turn_finished(_Turn())
    assert f"{ASSISTANT_NAME}: I made the asteroids" in transcript(bench)


def test_a_failed_turn_is_open_nest_not_gary(bench) -> None:
    """The substantive half of the split, and the easiest one to regress.

    ``AgentWorker`` emits ``failed`` for a ``ProviderError`` -- the model would not
    load, the service refused the key, the call budget ran out. Nobody said anything,
    so nobody is quoted. Putting Gary's name here would have him announce a fault in
    the machinery he speaks through.
    """
    bench._turn_failed("That didn't work. The model could not be loaded.")
    text = transcript(bench)
    assert f"{SYSTEM_NAME}: That didn't work." in text
    assert f"{ASSISTANT_NAME}:" not in text


class _Versions:
    """Just enough of ``VersionHistory`` for ``_undo`` to reach its two messages.

    A real one would bring git with it, and git is tested in ``test_checkpoint.py``.
    What is under test here is which name goes on the sentence, so the stub stops at
    the boundary where that is decided.
    """

    can_undo = True

    def __init__(self, restored=None):
        self._restored = restored

    def undo(self):
        return self._restored


class _Restored:
    label = "Before Gary made changes"


def test_an_undo_with_nothing_to_go_back_to_is_gary_speaking(bench) -> None:
    """Section 22's "Undo" is one of the guide's worked Gary examples."""
    bench.versions = _Versions(restored=None)
    bench._undo()
    assert transcript(bench).startswith(f"{ASSISTANT_NAME}: There is no earlier version")


def test_a_successful_undo_is_gary_speaking(bench) -> None:
    bench.versions = _Versions(restored=_Restored())
    bench._undo()
    assert f"{ASSISTANT_NAME}: Went back to: Before Gary made changes" in transcript(bench)


def test_the_conversation_panel_is_titled_for_gary(bench) -> None:
    """Section 57's panel. The label a child actually reads.

    ``section_label`` renders an equipment-style uppercase header, so the panel reads
    GARY next to PROJECT and BUILD / PREVIEW. Compared case-insensitively for that
    reason -- asserting the exact casing here would be pinning the theme, not the name.
    """
    from PySide6.QtWidgets import QLabel

    titles = [
        widget.text().casefold()
        for widget in bench._chat_panel.findChildren(QLabel)
        if widget.text()
    ]
    assert ASSISTANT_NAME.casefold() in titles
    assert "assistant" not in titles


# ------------------------------------------------- section 47: Gary and the artwork

def test_gary_never_names_the_brand_artwork() -> None:
    """Section 47: the symbols belong to Open Nest, and Gary does not claim them.

    "My eagle is flying!" is the guide's own example of what must not happen. The
    symbols stay implicit -- Gary may speak to their *semantics* ("One second. I'm
    checking something.") while the eagle flaps above him, and never about the graphic.
    """
    forbidden = re.compile(
        r"\b(my|our)\s+(eagle|sunglasses|nest)\b|\bputting on\s+(my|the)\s+sunglasses\b",
        re.IGNORECASE,
    )
    for path, text, _line in user_visible_strings():
        assert not forbidden.search(text), f"{path}: Gary names the artwork -- {text!r}"


# ------------------------------------------------------- the standing register sweep

#: The vocabulary the guide rules out, with the section that rules it out. Matched
#: whole-word and case-insensitively against user-visible copy only.
BANNED = {
    # Section 2 -- the alarm-system register.
    r"uh-oh": "section 2",
    r"something went terribly wrong": "section 2",
    r"don't worry": "section 2",
    r"great news": "section 2",
    # Section 9 -- error tone. Permitted inside the technical-detail view, which shows
    # the tool's own output rather than copy written here.
    r"invalid input": "section 9",
    r"operation failed": "section 9",
    # Section 10 -- the button a warning must not offer.
    r"proceed anyway": "section 10",
    # Section 17 -- pitch-deck vocabulary.
    r"ai-powered": "section 17",
    r"seamless": "section 17",
    r"intelligent automation": "section 17",
    r"copilot": "section 17",
    r"next-generation": "section 17",
    r"revolutionary": "section 17",
    r"smart workflow": "section 17",
    r"supercharge": "section 17",
    # Section 18 -- fake excitement.
    r"awesome": "section 18",
    r"fantastic": "section 18",
    r"sure thing": "section 18",
    # Section 19 -- infantilisation.
    r"little coder": "section 19",
    r"young genius": "section 19",
    r"kiddo": "section 19",
    r"superstar": "section 19",
    r"future engineer": "section 19",
}


def user_visible_strings():
    """Every string literal in the package that a person could plausibly read.

    Deliberately over-inclusive rather than curated: it walks the AST of every module,
    skips docstrings and anything that is obviously an identifier, and keeps the rest.
    A curated list would have to be maintained, and the failure mode of forgetting to
    add a new screen is silence.

    ``projects/templates/`` is included -- a child reads that code. ``prompts/`` is
    checked separately by :func:`test_the_prompt_files_keep_the_register` because those
    are text files, not Python.
    """
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            value = node.value
            # An identifier, a path fragment or a format key is not copy.
            if " " not in value.strip():
                continue
            yield path.relative_to(PACKAGE.parent), value, node.lineno


def test_no_user_visible_string_uses_the_banned_register() -> None:
    """The guard that makes a surgical copy pass defensible rather than lucky.

    This passed before 10B changed anything -- the copy was written against
    ``DESIGN_DOC.md`` section 20, which is the same position in fewer words. The point
    of pinning it is that the next screen inherits the rule for free.
    """
    offences = []
    for path, text, line in user_visible_strings():
        for pattern, section in BANNED.items():
            if re.search(rf"\b{pattern}\b", text, re.IGNORECASE):
                offences.append(f"{path}:{line} ({section}): {text!r}")
    assert not offences, "banned register in user-visible copy:\n" + "\n".join(offences)


def test_the_prompt_files_keep_the_register() -> None:
    """The prompts are copy too -- they are how Gary is told to sound."""
    offences = []
    for path in sorted((PACKAGE / "prompts").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        for pattern, section in BANNED.items():
            for match in re.finditer(rf"\b{pattern}\b", text, re.IGNORECASE):
                # base.txt names the openers in order to forbid them, which is the
                # opposite of using them.
                line = text[: match.start()].count("\n") + 1
                context = text.splitlines()[line - 1]
                if "Never open with" in context or "Never call them" in context:
                    continue
                offences.append(f"{path.name}:{line} ({section}): {context.strip()!r}")
    assert not offences, "banned register in the prompts:\n" + "\n".join(offences)


# ------------------------------------------------------------------ the base prompt

def base_prompt() -> str:
    """The prompt as one line, so an assertion cannot be defeated by a line wrap.

    ``base.txt`` is hard-wrapped prose. Asserting a phrase that happens to straddle a
    wrap fails for a reason that has nothing to do with the rule being present, and
    "fix it by rewrapping the prompt" is the wrong lesson to teach the next person.
    """
    text = (PACKAGE / "prompts" / "base.txt").read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", text)


def test_gary_may_not_claim_a_state_he_did_not_observe() -> None:
    """The state-claim rule, by developer direction in Phase 10B.

    Gary must not say a project works, runs, compiles, is playable, is finished or is
    fixed unless a tool reported it this turn or the child just said so. Otherwise he
    finds out rather than sounding confident.

    This is the generalisation of the rule ``assets.invented_description`` enforces for
    pictures (HANDOFF section 6A) and ``_claimed_a_change_it_did_not_make`` enforces for
    edits: **do not assert a fact about the project that nothing established.** Those
    two are deterministic checks on the reply; this one cannot be, because "is it
    playable?" has no mechanical answer. So it is carried in the prompt, and what is
    pinned here is that the rule is still *in* the prompt and still names the two
    permitted sources of evidence.

    SPIKES.md section 18B is why it exists: asked "I made a game where a cat flies
    through space... is that good?", the model answered that the game "is playable"
    without reading a line of it.
    """
    text = base_prompt()
    claim = text[text.index("HONESTY"):]

    # The states a reply must not assert unevidenced.
    for state in ("works", "runs", "compiles", "playable", "finished", "fixed"):
        assert state in claim, f"the state-claim rule no longer covers {state!r}"

    # Both permitted sources of evidence, and only those two.
    assert "a tool actually reported it" in claim
    assert "they just told you it does" in claim

    # And the instruction to go and find out rather than guess. It names a tool call
    # deliberately: the first draft of this rule said only "find out", and the model
    # answered by narrating an edit it had not made. See SPIKES.md section 18C.
    assert "call a tool and find out" in claim


def test_praise_is_replaced_by_acknowledgment_not_by_a_milder_word() -> None:
    """Ruling in Phase 10B: the tone rule is broader than a banned-word list.

    Swapping "Great!" for "Good." satisfies section 18's literal list and misses the
    point -- generic approval carries no information either way. The prompt has to ask
    for the thing that does: name the specific part, or mark that it happened.

    Pinned because a future edit trimming the prompt for length would most likely cut
    the worked example, which is the part that makes the rule land.
    """
    text = base_prompt()
    assert "do not reach for a milder praise word" in text
    assert '"Good" is' in text and 'no better than "Great"' in text
    # Section 20's model answer, which is what the rule is pointing at.
    assert "There it is." in text
    # Specific acknowledgment, the other permitted move.
    assert "say which part and why" in text
    assert "name the specific part you mean" in text


def test_the_base_prompt_is_gary_and_still_asks_for_what_it_asked_for() -> None:
    """Voice was added; nothing load-bearing was removed.

    ``HANDOFF.md`` section 6B is explicit that brevity is asked for here rather than
    enforced with a token cap, and section 4 records the honesty and tool rules as
    measured rather than chosen. A future edit reaching for more personality should not
    be able to drop any of them by accident.
    """
    text = (PACKAGE / "prompts" / "base.txt").read_text(encoding="utf-8")
    assert text.startswith(f"You are {ASSISTANT_NAME},")
    assert "Be brief by default" in text                    # brevity lives here
    assert "Never claim to have done something" in text     # the honesty rule
    assert "no network" in text                             # the tool boundary
    assert "Never put an API key" in text                   # section 22's rule
