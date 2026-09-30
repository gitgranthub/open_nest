"""The cross-preset stress pass after Phase 13C (SPIKES.md section 29).

The same three kinds of message -- a change, a question about the project, a question
about Open Nest -- driven through Website, Research, Arduino, Raspberry Pi and Blank with
the local 4B and 8B, OpenAI Luna and Anthropic Sonnet (``benchmarks/stress/``). Each test
here is one thing those walks found the shared layer letting through, whichever model
said it:

- a press of Run / Test on Mac counted as a file change, so "I updated the code in
  main.py" in an answer about a turn that had changed nothing went unchecked;
- a reply to a request that told the child how to edit the code instead of editing it;
- "The code now confirms blinks on a real Pi" -- nothing ran on a Pi;
- "Graph this." drew a chart on the way to a plan, and was told nothing had changed;
- an empty Blank project's help naming a file the child never needs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from opennest.agent import evidence
from opennest.agent.controller import AgentController, Plan, PlannedStep, Turn
from opennest.agent.replies import (
    ANSWER_CORRECTION,
    child_nouns,
    files_said_wrongly,
    hardware_claims,
    hardware_correction,
    instructs_edit,
)
from opennest.agent.tools import Toolbox, ToolResult
from opennest.ai.provider import Reply, ToolCall
from opennest.projects.manager import create_project
from tests.conftest import ScriptedProvider

REPO = Path(__file__).resolve().parents[1]


def make(project, replies):
    provider = ScriptedProvider(replies)
    return AgentController(project, provider, Toolbox(project)), provider


def sent(provider) -> list[str]:
    """What Open Nest said to the model in its own voice, last call."""
    return [m.content for m in provider.calls[-1] if m.role == "user"]


# ------------------------------------------- a press of Run is not a change

def test_a_press_of_test_on_mac_does_not_make_a_claimed_edit_believable(tmp_path) -> None:
    """The 4B, measured: the turn before had only described the edit; the child pressed
    Test on Mac; "How do I test this?" was answered "I updated the code in main.py"."""
    pi = create_project("Pi Light", "raspberry_pi", root=tmp_path)
    controller, provider = make(pi, [
        Reply(text="I updated the code in main.py to set ON_SECONDS = 2.0. Click Test on "
                   "Mac to see the blink duration."),
        Reply(text="Click Test on Mac: it prints what the pins would do. ON_SECONDS is "
                   "still 0.3."),
    ])
    controller.note_event("The child pressed Test on Mac: it ran.")
    assert "The child pressed Test on Mac: it ran." in controller._notes()   # still told
    turn = controller.send("How do I test this?")
    assert turn.answered
    assert sent(provider)[-1] == ANSWER_CORRECTION
    assert turn.text.startswith("Click Test on Mac") and "I updated" not in turn.text


def test_a_run_that_drew_a_chart_still_counts_as_something_made(tmp_path) -> None:
    research = create_project("Garden", "research", root=tmp_path)
    controller, provider = make(research, [
        Reply(text="The chart is in charts/chart.png -- it's there now."),
    ])
    (research.directory / "charts").mkdir()
    shutil.copy(REPO / "assets" / "nest_bw.png", research.directory / "charts" / "chart.png")
    controller.note_event("The child pressed Run Analysis: it ran and drew charts/chart.png.",
                          drew=True)
    turn = controller.send("Where is my chart?")
    assert len(provider.calls) == 1                 # nothing to correct
    assert turn.text == "The chart is in charts/chart.png -- it's there now."


# --------------------------------------------------- telling instead of doing

TOLD_HOW = ("I haven't changed anything yet. The file still has the original code.\n"
            "I need to edit the main.py file to update ON_SECONDS.\n"
            "Here is the exact text to replace:\n```python\nON_SECONDS = 0.3\n```\n"
            "Replace it with:\n```python\nON_SECONDS = 2.0\n```")


def test_a_request_answered_with_edit_instructions_is_not_relayed(tmp_path) -> None:
    pi = create_project("Pi Light", "raspberry_pi", root=tmp_path)
    controller, _provider = make(pi, [
        Reply(text=TOLD_HOW),
        Reply(text="1. Make the light stay on for two seconds\n2. Test it on the Mac"),
        Reply(text="I haven't changed that yet."),
    ])
    turn = controller.send("Make it stay on for two seconds.")
    assert "Replace it with" not in turn.text and "exact text" not in turn.text
    assert "ON_SECONDS = 0.3" not in turn.text
    assert "one step at a time" in turn.text        # a way in, not a job for the child


def test_an_answer_telling_them_to_edit_by_hand_offers_to_do_it(tmp_path) -> None:
    """"What do I do now?" -- "Change ON_SECONDS from 0.3 to 2.0 in src/main.py." Gary can
    make that change; an answer cannot, so it is offered."""
    pi = create_project("Pi Light", "raspberry_pi", root=tmp_path)
    controller, _ = make(pi, [Reply(text="Change ON_SECONDS from 0.3 to 2.0 in src/main.py. "
                                         "Then click Test on Mac.")])
    turn = controller.send("What do I do now?")
    assert turn.answered and turn.text.endswith("Want me to make that change for you?")


def test_instructions_are_read_only_when_they_are_code_shaped() -> None:
    told = [TOLD_HOW, "Change ON_SECONDS from 0.3 to 2.0 in src/main.py.",
            "Replace `LED_PIN = 17` with `LED_PIN = 22`.",
            "Open src/main.py and change BLINKS to 10.",
            "Set BLINK_COUNT to 10 and press Test on Mac."]
    not_told = ["Press Preview Website to see it.",
                "I can change the colour to blue if you like.",
                "Try asking me to change the title to Dino World.",
                "Click src/main.py in the Project panel to see the code.",
                "The sketch uses LED_BUILTIN, which is the board's built-in LED.",
                "It blinks 3 times, with 0.3 seconds on and off."]
    assert all(instructs_edit(text) for text in told)
    assert not any(instructs_edit(text) for text in not_told)


# ------------------------------------------------ hardware nobody has seen

#: Said as fact about a real board or Pi: every one is a claim nobody could check.
SEEN = ["The code now confirms blinks on a real Pi.", "The LED is blinking now.",
        "It works on your board.", "The light was flashing on the Arduino.",
        "I tested it on a real Raspberry Pi and it blinked.",
        # Qwen3 8B, measured, about a sketch nobody had sent to a board:
        "The LED is already blinking as per the starter sketch."]
#: Looking ahead, telling them what to do, saying it has not run there, or about the
#: pretend pins: none of these may be flagged.
NOT_SEEN = ["The Arduino will blink the built-in LED.",
            "No. The Pi is not blinking.",
            "Nothing has run on a real Raspberry Pi, so nobody has seen a light.",
            "Test it on a real Raspberry Pi:",
            "1. Plug a resistor and LED into BCM pin 17 (as per wiring guide).",
            "To see the real blink, you need a Raspberry Pi.",
            "When you send it to your board, the light blinks every half second.",
            "The code runs on this Mac with pretend pins.",
            "\"Send to Board\" sends the code to the Arduino board.",
            "The output shows the LED turning on and off.",
            "The LED is blinking on and off in the output.",
            "Once it's on your Pi, the LED on pin 17 turns on for two seconds.",
            "The LED on pin 17 is on for 2 seconds, then off.",
            # Sonnet, measured: describing the wiring, not what the light did.
            "On the real Raspberry Pi, that's pin 17 driving an actual LED -- wire the "
            "LED's long leg through a resistor to pin 17, and the short leg to ground.",
            "Wire the LED on your breadboard to pin 13.",
            # Qwen3 8B, measured -- a true answer the first version of the check corrected:
            "You're using the board's built-in LED (LED_BUILTIN), which is the default "
            "onboard light on the Arduino Uno."]


def test_what_real_hardware_did_is_read_a_sentence_at_a_time() -> None:
    assert all(hardware_claims(text) for text in SEEN)
    assert not any(hardware_claims(text) for text in NOT_SEEN)


def test_a_pi_reply_saying_what_the_real_pi_did_is_corrected(tmp_path) -> None:
    pi = create_project("Pi Light", "raspberry_pi", root=tmp_path)
    change = ToolCall("edit_file", {"path": "src/main.py", "old_text": 'print("Done.")',
                                    "new_text": 'print("LED blinked successfully.")'})
    controller, provider = make(pi, [
        Reply(tool_calls=(change,)),
        Reply(text="The code now confirms blinks on a real Pi."),
        Reply(text="It now prints a message when it has blinked. Test on Mac shows it."),
    ])
    turn = controller.send("Make it say when it finishes blinking.")
    assert sent(provider)[-1] == hardware_correction("raspberry_pi", "Test on Mac")
    assert "Compile" not in sent(provider)[-1]                  # a Pi has no Compile
    assert turn.text.startswith("It now prints a message")


def test_said_again_the_hardware_claim_goes_and_the_fact_is_said(tmp_path) -> None:
    sketch = create_project("Blinky", "arduino", root=tmp_path)
    controller, _ = make(sketch, [
        Reply(text="It blinks every half second. It works on your board."),
        Reply(text="It blinks every half second. It works on your board."),
    ])
    turn = controller.send("Does it work?")
    assert "It works on your board" not in turn.text
    assert turn.text.startswith("It blinks every half second.")
    assert "Open Nest can't see your board" in turn.text


def test_a_website_is_not_read_for_hardware(tmp_path) -> None:
    site = create_project("Dino Site", "website", root=tmp_path)
    controller, provider = make(site, [Reply(text="The page works on your board game.")])
    controller.send("Does the page work?")
    assert len(provider.calls) == 1


# ------------------------------------------ a chart drawn on the way to a plan

def test_a_plan_that_changed_no_file_but_drew_a_chart_says_so(tmp_path) -> None:
    research = create_project("Garden", "research", root=tmp_path)
    controller = AgentController(research, ScriptedProvider([]), Toolbox(research))
    steps = ["Draw the x- and y-axes", "Plot one point on the graph"]
    controller._plan = Plan(request="Graph this.", steps=[PlannedStep(s) for s in steps])
    turn = Turn(reduced=True, fastpath={"plan": steps})
    turn.tool_results = [
        ("edit_file", ToolResult(False, "That exact text is not in it.", reason="not_found")),
        ("run_project", ToolResult(True, "It ran successfully.",
                                   made_files=("charts/chart.png",)))]
    text = controller._framed(turn).text
    assert "I haven't changed anything yet" not in text
    assert text.startswith("I haven't changed any file yet, but running the project drew "
                           "charts/chart.png -- click it in the Project panel to see it.")
    assert "1. Draw the x- and y-axes" in text


# --------------------------------------------- an empty Blank project's help

def test_an_empty_project_is_described_without_the_file_the_child_never_needs(tmp_path) -> None:
    blank = create_project("Blank Site", "blank", root=tmp_path)
    block = evidence.checked_block(blank, Toolbox(blank))
    assert "say the project is empty, without that file's name" in block


# ------------------------------------------------- a colour the page has not got

def _site(tmp_path, css_extra=""):
    site = create_project("Dino Site", "website", root=tmp_path)
    css = site.directory / "src" / "styles.css"
    css.write_text(css.read_text(encoding="utf-8") + css_extra, encoding="utf-8")
    return site


def test_the_colours_a_page_has_are_read_from_its_files(tmp_path) -> None:
    site = _site(tmp_path, "\nheader { background: linear-gradient(#ffd54f, #ff8a65); "
                           "color: rgb(20, 90, 90); border-color: coral; }\n")
    families, words = evidence.page_colours(site)
    assert {"yellow", "orange", "teal", "green"} <= families     # the starter's accent too
    assert "coral" in words


def test_a_colour_said_about_a_change_that_no_file_has_is_corrected(tmp_path) -> None:
    """The 4B, measured: "It's lighter and uses the warm orange accent color" -- the
    accent it used is the starter's green, and nothing orange is anywhere in the page."""
    site = _site(tmp_path)
    lighter = "h1 {\n  font-weight: 300;\n  color: var(--accent);"
    change = ToolCall("edit_file", {"path": "src/styles.css", "old_text": "h1 {",
                                    "new_text": lighter})
    controller, provider = make(site, [
        Reply(tool_calls=(change,)),
        Reply(text="The header is lighter and uses the warm orange accent color."),
        Reply(text="The header's title now uses the green accent colour, in a lighter weight."),
    ])
    turn = controller.send("Make the header feel brighter and more fun.")
    assert sent(provider)[-1].startswith("The page's files have no orange in them")
    assert turn.text.startswith("The header's title now uses the green accent")


def test_colours_the_page_really_has_are_left_alone(tmp_path) -> None:
    """Luna, measured: "a sunny yellow-to-orange header background, coral decorative
    circles, dark teal text" -- every one of them in its CSS."""
    site = _site(tmp_path)
    css = ("\nheader { background: linear-gradient(135deg, #ffe66d, #ff9f43); "
           "color: #134e4a; }\n.header::after { background: #ff7f6e; }\n")
    change = ToolCall("edit_file", {"path": "src/styles.css", "old_text": "h1 {",
                                    "new_text": css + "h1 {"})
    controller, provider = make(site, [
        Reply(tool_calls=(change,)),
        Reply(text="Look for a sunny yellow-to-orange header, coral circles and dark teal "
                   "text. I can make it pink instead if you like."),
    ])
    turn = controller.send("Make the header feel brighter and more fun.")
    assert len(provider.calls) == 2 and turn.text.startswith("Look for a sunny")


def test_an_arduino_sketch_is_described_by_what_its_loop_does(tmp_path) -> None:
    """Luna, after an Undo back to the starter: "so it does not blink yet". It does."""
    sketch = create_project("Blinky", "arduino", root=tmp_path)
    block = evidence.checked_block(sketch, Toolbox(sketch))
    assert ("What it does, read from the code: loop() turns the board's own light "
            "(LED_BUILTIN) on for 500 ms and off for 500 ms, over and over -- it blinks."
            in block)
    assert "exactly the Basic Arduino Sketch starter, unchanged: A sketch that blinks" in block


def test_the_page_summary_lists_the_headings_its_count_is_about(tmp_path) -> None:
    site = create_project("Dino Site", "website", root=tmp_path)
    said = evidence.summary_for_child(site)
    assert said.startswith("Right now the page has 2 sections, with the headings")
    assert "“One”" not in said                        # a card's title, not a section's


def test_the_website_itself_is_not_a_thing_its_page_must_name(tmp_path) -> None:
    """Sonnet, measured: "Did you click Preview Website again?" was corrected into a
    denial, because "a website about dinosaurs" made "website" a thing to look for in a
    page titled "Dinosaur World"."""
    site = create_project("Dino Site", "website", root=tmp_path)
    index = site.directory / "src" / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace("My Website", "Dinosaur World")
                     .replace("<title>", "<title>Dinos ").replace("Made with Open Nest.", ""),
                     encoding="utf-8")
    controller = AgentController(site, ScriptedProvider([]), Toolbox(site))
    controller._asked_for = child_nouns("Make me a website about dinosaurs.")
    assert controller._asked_for == {"dinosaurs"}
    controller._last_outcome = "Last time, no file changed."
    said = ("The file has a Fossils section. Did you click Preview Website again after the "
            "change?")
    assert controller._names_what_is_not_there(Turn(answered=True), said) is None


def test_a_refused_edit_in_a_pi_project_is_corrected_without_the_scene(tmp_path) -> None:
    """Luna in a Blank project that became a Pi project: told how to change a thing "in
    the scene" with game_object, it said "No scene object was changed" to the child."""
    pi = create_project("Pi Light", "raspberry_pi", root=tmp_path)
    controller = AgentController(pi, ScriptedProvider([]), Toolbox(pi))
    controller._asked_for = {"light"}
    turn = Turn(text="The light is now brighter.")
    turn.calls = [("edit_file", {"path": "src/main.py", "old_text": "light = dim",
                                 "new_text": "light = bright"},
                   ToolResult(False, "That exact text is not in it.", reason="not_found"))]
    correction, _fact = controller._claims_what_was_refused(turn)
    assert correction.startswith("The changes to the light did not go in")
    assert "game_object" not in correction and "scene" not in correction


# -------------------------------------------------- what an Undo took back

ROAR = ('I added a "Roar" button and three fun facts about fossils in the "Fossils" '
        'section. Press Preview Website to see the changes.')


def test_a_reply_repeating_what_an_undo_took_back_is_corrected(tmp_path) -> None:
    """Qwen3 8B, measured: after an Undo, "What do I do now?" was answered with the undone
    reply word for word."""
    site = create_project("Dino Site", "website", root=tmp_path)
    change = ToolCall("edit_file", {"path": "src/index.html", "old_text": "<h2>About</h2>",
                                    "new_text": "<h2>About</h2>\n<button>Roar</button>"})
    controller, provider = make(site, [
        Reply(tool_calls=(change,)), Reply(text=ROAR),
        Reply(text=ROAR),
        Reply(text="You pressed Undo, so the Roar button is gone. Ask me to add it again."),
    ])
    controller.send("add a button that says Roar")
    controller.note_outside_change("The child pressed Undo.", undone=True)
    turn = controller.send("What do I do now?")
    assert "not in the files any more" in sent(provider)[-1]
    assert turn.text.startswith("You pressed Undo, so the Roar button is gone.")


def test_said_again_after_an_undo_open_nest_says_what_is_there(tmp_path) -> None:
    site = create_project("Dino Site", "website", root=tmp_path)
    change = ToolCall("edit_file", {"path": "src/index.html", "old_text": "<h2>About</h2>",
                                    "new_text": "<h2>About</h2>\n<button>Roar</button>"})
    controller, _ = make(site, [Reply(tool_calls=(change,)), Reply(text=ROAR),
                                Reply(text=ROAR), Reply(text=ROAR)])
    controller.send("add a button that says Roar")
    controller.note_outside_change("The child pressed Undo.", undone=True)
    turn = controller.send("What do I do now?")
    assert turn.text.startswith("You pressed Undo, so that last change is gone. Right now")
    assert "I added" not in turn.text


# --------------------------------------- the Research starter's chart, in words

def test_the_research_starter_charts_an_all_number_table_by_its_first_column(tmp_path):
    """The stress pass's garden table (week, sunflower_cm, tomato_cm): the starter drew
    ``week`` against the row number -- a straight line -- and the 4B then told the child
    it "shows both sunflower and tomato growth over weeks". Now it draws that, and says
    what it drew, so what anyone says about the chart can be checked against the run."""
    pytest.importorskip("pandas")
    pytest.importorskip("matplotlib")
    starter = REPO / "opennest/projects/starters/research_basic"
    (tmp_path / "data").mkdir()
    shutil.copy(REPO / "benchmarks/stress/inputs/garden.csv", tmp_path / "data")
    shutil.copy(starter / "analysis.py", tmp_path)
    shutil.copy(starter / "matplotlibrc", tmp_path)
    ran = subprocess.run([sys.executable, "analysis.py"], cwd=tmp_path, capture_output=True,
                         text=True, timeout=120)
    assert ran.returncode == 0, ran.stderr
    assert "Chart saved to charts/chart.png: sunflower_cm and tomato_cm by week." in ran.stdout
    assert (tmp_path / "charts" / "chart.png").is_file()


def test_there_it_is_is_a_look_nobody_took(tmp_path) -> None:
    """The 4B's Blank game and the 8B's Arduino, measured: "... There it is." -- nothing
    shows Gary the game or the board."""
    sketch = create_project("Blinky", "arduino", root=tmp_path)
    controller, provider = make(sketch, [
        Reply(text="The sketch already blinks the board's own light. There it is."),
        Reply(text="The sketch already blinks the board's own light, every half second."),
    ])
    turn = controller.send("Make the LED blink.")
    assert sent(provider)[-1].startswith("You cannot see the game")
    assert "There it is" not in turn.text



# ------------------------------------------------ files that are not so

def test_a_file_the_project_has_not_got_is_not_said_to_be_there(tmp_path) -> None:
    """Qwen3 8B, measured: "This creates a line chart ... and saves it as
    outputs/growth.png" -- no edit had landed, and there is no such file."""
    research = create_project("Garden", "research", root=tmp_path)
    controller, provider = make(research, [
        Reply(text="Sunflower grew the most. The chart of it is saved as "
                   "`outputs/growth.png`."),
        Reply(text="Nothing has been drawn yet: press Run Analysis to make the chart."),
    ])
    turn = controller.send("Tell me what changed the most.")
    assert "there is no outputs/growth.png in this project" in sent(provider)[-1]
    assert turn.text.startswith("Nothing has been drawn yet")


def test_a_file_said_to_be_changed_that_nothing_changed_is_corrected(tmp_path) -> None:
    """...then "What did you actually change?" -- "This change was made in
    src/analysis.py." Nothing had changed it; said again, Open Nest says so."""
    research = create_project("Garden", "research", root=tmp_path)
    claim = "I added code to draw the chart. This change was made in src/analysis.py."
    controller, _ = make(research, [Reply(text=claim), Reply(text=claim)])
    # The turn before ran the analysis, and the run drew a chart: something was made
    # lately, so "I added" alone is not a claim of nothing -- the file named is checked.
    (research.directory / "charts").mkdir()
    shutil.copy(REPO / "assets" / "nest_bw.png", research.directory / "charts" / "chart.png")
    controller._recent_changes, controller._recent_paths = [True], [{"charts/chart.png"}]
    turn = controller.send("What did you actually change?")
    assert turn.text.endswith("(Open Nest: src/analysis.py has not changed -- no edit to it "
                              "went in.)")


def test_files_named_rightly_are_left_alone() -> None:
    files = ["src/index.html", "src/styles.css", "charts/chart.png", "data/garden.csv"]
    fine = ["The chart is in charts/chart.png.", "Open index.html to see the page.",
            "I changed src/styles.css so the header is brighter.",
            "No src/main.py file exists yet.", "Press Run Analysis to make charts/new.png.",
            "I can save it as outputs/growth.png if you like.",
            "The page does not use Chart.js or anything from the internet."]
    for sentence in fine:
        assert files_said_wrongly(sentence, files, {"src/styles.css"}) == [], sentence
    assert files_said_wrongly("It is saved as outputs/growth.png.", files, set()) == [
        "there is no outputs/growth.png in this project"]
    assert files_said_wrongly("I changed styles.css.", files, set()) == [
        "styles.css has not changed -- no edit to it went in"]


def test_the_research_prompt_names_the_folder_the_analysis_draws_into() -> None:
    """Both local models told the child the chart "will appear in outputs/growth.png":
    the prompt said outputs/, and the starter and every recipe save into charts/."""
    from opennest import paths

    prompt = (paths.prompts_dir() / "research.txt").read_text(encoding="utf-8")
    assert 'plt.savefig("charts/name.png")' in prompt and "outputs/" not in prompt
    analysis = (REPO / "opennest/projects/starters/research_basic/analysis.py").read_text()
    assert 'CHART_DIR = Path("charts")' in analysis


def test_back_at_the_starter_after_an_undo_is_said_plainly(tmp_path) -> None:
    sketch = create_project("Blinky", "arduino", root=tmp_path)
    change = ToolCall("edit_file", {"path": "src/project/project.ino",
                                    "old_text": "ON_MILLISECONDS = 500",
                                    "new_text": "ON_MILLISECONDS = 250"})
    said = "It blinks 250 ms on and 500 ms off now, a bit faster than before."
    controller, _ = make(sketch, [Reply(tool_calls=(change,)), Reply(text=said),
                                  Reply(text=said), Reply(text=said)])
    controller.send("make it blink faster")
    controller.versions = None
    sketch.entrypoint_path.write_text(sketch.entrypoint_path.read_text().replace(
        "ON_MILLISECONDS = 250", "ON_MILLISECONDS = 500"))       # what the Undo put back
    controller.note_outside_change("The child pressed Undo.", undone=True)
    turn = controller.send("What do I do next?")
    assert turn.text.startswith("You pressed Undo, so that last change is gone. It's back "
                                "to how it started. Right now:")


def test_a_change_claimed_without_i_is_still_a_claim(tmp_path) -> None:
    from opennest.assets import manager as assets

    research = create_project("Garden", "research", root=tmp_path)
    assets.import_file(research, REPO / "benchmarks/stress/inputs/garden.csv")
    controller, provider = make(research, [
        Reply(text="The most significant change was adding the code to plot the growth."),
        Reply(text="Sunflower grew the most: from 5 cm to 38 cm. Tomato went from 3 to 33."),
    ])
    turn = controller.send("Tell me what changed the most.")
    assert sent(provider)[-1].startswith("You did not actually change any file")
    assert turn.text.startswith("Sunflower grew the most")
