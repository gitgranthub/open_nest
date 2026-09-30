"""The Fast Path: classifier, registry, router, executor, verifier and the controller hook.

No model here. A fake scorer stands in for ``MLXProvider.score_choices``: it reads the
lettered options out of the question it is asked and puts all its weight on the one a
test chose, so every routing rule can be exercised deterministically. What the real
model does with these questions is measured separately (SPIKES.md section 25), the way
tool selection always has been.

Most tests replace the headless playtest with a recorded pass, because a real one takes
about two seconds and the playtest has its own tests. One test runs the real thing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.ai.provider import Reply
from opennest.execution import playtest
from opennest.fastpath import edits, slots
from opennest.fastpath.classifier import (
    LETTERS,
    OTHER,
    Classification,
    IntentClassifier,
    Option,
    Scored,
    orderings,
)
from opennest.fastpath.kinds import (
    KINDS,
    AlreadyDone,
    Context,
    NeedsAnswer,
    NotApplicable,
    arduino,
    game_things,
    games,
    kind_for,
    raspberry_pi,
    research,
    website,
)
from opennest.fastpath.registry import RecipeError, RecipeRegistry, load_profile
from opennest.fastpath.router import (
    COMPOUND,
    GUIDE,
    NORMAL,
    RECIPE,
    FastPathRouter,
    split_parts,
)
from opennest.projects.manager import create_project
from tests.conftest import ScriptedProvider

# ----------------------------------------------------------------------- fakes


class FakeScorer:
    """Answers closed questions the way a test says to, by option description.

    ``answers`` maps a phrase to look for in the question's options to the description
    of the option to pick. The first phrase found in the options wins; when none is
    found the last option (always "other" for an intent question) is picked.
    """

    def __init__(self, *picks: str) -> None:
        self.picks = list(picks)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str, labels) -> list[float]:
        self.calls.append((system, user))
        listed = dict(re.findall(r"^([A-Z])\. (.+)$", system, re.MULTILINE))
        chosen = None
        for pick in self.picks:
            chosen = next((letter for letter, text in listed.items() if text == pick), None)
            if chosen:
                break
        chosen = chosen or labels[-1]
        return [0.0 if label == chosen else -30.0 for label in labels]


class ScoringProvider(ScriptedProvider):
    """A scripted provider that can also answer closed questions, like the MLX one."""

    def __init__(self, replies, scorer: FakeScorer) -> None:
        super().__init__(replies)
        self.scorer = scorer

    def score_choices(self, system, user, labels):
        return self.scorer(system, user, labels)


def passing_playtest(*_args, **_kwargs) -> playtest.Playtest:
    return playtest.Playtest(playtest.PASSED, entry="src/game.py", frames=100,
                             moved_by_itself=True, responded_to=("right", "left"))


def describe(profile: str, intent: str) -> str:
    return RecipeRegistry().for_profile(profile).for_intent(intent).describe


def controller_for(project, scorer, replies=(), *, playtest_result=passing_playtest):
    provider = ScoringProvider(list(replies), scorer)
    toolbox = Toolbox(project)
    if playtest_result is not None:
        toolbox.playtest = playtest_result
    controller = AgentController(project, provider, toolbox, fastpath=FastPathRouter())
    return controller, provider


YES = "yes"


# -------------------------------------------------------------------- registry


def test_every_shipped_recipe_names_an_operation_and_checks_that_exist() -> None:
    registry = RecipeRegistry()
    assert sorted(registry.profiles()) == sorted(KINDS)
    for profile in registry.profiles():
        kind = kind_for(profile)
        for recipe in registry.for_profile(profile).recipes:
            if recipe.deterministic:
                assert recipe.op in kind.OPS, recipe.id
                assert recipe.report, recipe.id
            for check in recipe.verify:
                assert check in kind.CHECKS, (recipe.id, check)
            assert recipe.guide.strip(), recipe.id


def test_a_recipe_with_an_operation_must_say_how_it_is_verified(tmp_path) -> None:
    (tmp_path / "games").mkdir()
    (tmp_path / "games" / "index.json").write_text(json.dumps(
        {"profile": "games", "building": "x", "other": "y", "order": ["g.a"]}))
    (tmp_path / "games" / "a.json").write_text(json.dumps(
        {"id": "g.a", "intent": "a", "describe": "d", "op": "set_number", "guide": "g",
         "report": "r"}))
    with pytest.raises(RecipeError, match="verified"):
        load_profile("games", tmp_path)


def test_an_unknown_recipe_key_is_an_error_not_a_silent_typo(tmp_path) -> None:
    (tmp_path / "games").mkdir()
    (tmp_path / "games" / "index.json").write_text(json.dumps(
        {"profile": "games", "building": "x", "other": "y", "order": ["g.a"]}))
    (tmp_path / "games" / "a.json").write_text(json.dumps(
        {"id": "g.a", "intent": "a", "describe": "d", "guide": "g", "verfy": ["x"]}))
    with pytest.raises(RecipeError, match="unknown keys"):
        load_profile("games", tmp_path)


def test_the_index_must_list_every_recipe_exactly_once(tmp_path) -> None:
    (tmp_path / "games").mkdir()
    (tmp_path / "games" / "index.json").write_text(json.dumps(
        {"profile": "games", "building": "x", "other": "y", "order": []}))
    (tmp_path / "games" / "a.json").write_text(json.dumps(
        {"id": "g.a", "intent": "a", "describe": "d", "guide": "g"}))
    with pytest.raises(RecipeError, match="order"):
        load_profile("games", tmp_path)


def test_options_end_with_other_and_fit_in_the_alphabet() -> None:
    registry = RecipeRegistry()
    for profile in registry.profiles():
        options = registry.for_profile(profile).options()
        assert options[-1].name == OTHER
        assert len(options) <= len(LETTERS)


def test_no_report_opens_with_praise() -> None:
    """Brand guide section 18: no "Great!", and no milder praise word instead."""
    banned = re.compile(r"^(great|awesome|amazing|nice|good|cool|perfect|wow)\b", re.I)
    for profile in RecipeRegistry().profiles():
        for recipe in RecipeRegistry().for_profile(profile).recipes:
            for phrasing in recipe.report:
                assert not banned.search(phrasing.strip()), (recipe.id, phrasing)
                assert "It works" not in phrasing, recipe.id


# ------------------------------------------------------------------ classifier


def test_orderings_are_fixed_and_keep_other_last() -> None:
    runs = orderings(5, 3)
    assert runs == orderings(5, 3)
    assert all(run[-1] == 4 for run in runs)
    assert len({tuple(run) for run in runs}) == 3


def test_a_yes_no_question_can_be_asked_both_ways_round() -> None:
    assert orderings(2, 2, keep_last=False) == [[0, 1], [1, 0]]


def test_agreement_and_share_come_from_every_ordering() -> None:
    options = [Option("a", "first"), Option("b", "second"), Option(OTHER, "anything else")]
    calls = []

    def fickle(system, user, labels):
        # Picks whatever option is listed first -- pure position bias.
        calls.append(system)
        return [0.0] + [-30.0] * (len(labels) - 1)

    result = IntentClassifier(fickle, orderings=2).classify("a game", options, "hi")
    assert len(calls) == 2
    assert result.agreement == 0.5
    assert result.score == pytest.approx(0.5, abs=1e-6)


def test_a_steady_answer_is_full_agreement() -> None:
    options = [Option("a", "first"), Option("b", "second"), Option(OTHER, "anything else")]
    result = IntentClassifier(FakeScorer("second"), orderings=3).classify(
        "a game", options, "hi")
    assert result.name == "b"
    assert result.agreement == 1.0
    assert result.score == pytest.approx(1.0)
    assert result.letter_mass == pytest.approx(1.0)


def test_what_the_project_is_goes_in_the_question_not_the_cached_part() -> None:
    scorer = FakeScorer("second")
    options = [Option("a", "first"), Option("b", "second"), Option(OTHER, "else")]
    IntentClassifier(scorer, orderings=1).classify(
        "a game", options, "go faster", previous="make it red", about="The player is a square.")
    system, user = scorer.calls[0]
    assert "square" not in system
    assert "About the project: The player is a square." in user
    assert "Their message before this one: make it red" in user
    assert user.endswith("Message: go faster")


# ---------------------------------------------------------------------- router


def test_no_model_that_can_score_means_the_normal_path() -> None:
    decision = FastPathRouter().decide("games", "make it faster", None)
    assert decision.route == NORMAL


def test_other_means_the_normal_path() -> None:
    decision = FastPathRouter().decide("games", "make it spooky", FakeScorer())
    assert decision.route == NORMAL


def test_a_confident_single_change_is_a_recipe() -> None:
    scorer = FakeScorer(describe("games", "change_player_speed"), YES)
    decision = FastPathRouter().decide("games", "make the player faster", scorer)
    assert decision.route == RECIPE
    assert decision.recipe.id == "game.change_player_speed"


def test_several_changes_at_once_go_to_gary_however_sure_the_intent_is() -> None:
    scorer = FakeScorer(describe("games", "change_player_speed"), "no")
    decision = FastPathRouter().decide("games", "faster and add a score", scorer)
    assert decision.route == NORMAL
    assert "single change" in decision.reason


def test_a_tweak_gets_a_second_question_about_itself() -> None:
    speed = describe("games", "change_player_speed")
    asked = []

    def scorer(system, user, labels):
        asked.append(system)
        listed = dict(re.findall(r"^([A-Z])\. (.+)$", system, re.MULTILINE))
        gate = "yes" in listed.values()
        # The general gate says no; the question about this change says yes.
        want = ("yes" if speed in system else "no") if gate else speed
        pick = next(k for k, v in listed.items() if v == want)
        return [0.0 if label == pick else -30.0 for label in labels]

    decision = FastPathRouter().decide("games", "my guy is a snail, quicker", scorer)
    assert decision.route == RECIPE
    assert any(speed in system and "nothing more" in system for system in asked)


def test_an_addition_does_not_get_the_second_question() -> None:
    ball = describe("games", "add_moving_thing")
    scorer = FakeScorer(ball, "no")
    assert FastPathRouter().decide("games", "a ball and more", scorer).route == NORMAL
    assert not any("nothing more" in system for system, _ in scorer.calls)


def test_a_likely_but_unsteady_intent_is_guidance_not_a_recipe() -> None:
    wanted = describe("games", "add_score")
    other = describe("games", "add_collectible")
    turn = {"n": 0}

    def wobbly(system, user, labels):
        listed = dict(re.findall(r"^([A-Z])\. (.+)$", system, re.MULTILINE))
        if "yes" in listed.values():
            pick = next(k for k, v in listed.items() if v == "yes")
        else:
            turn["n"] += 1
            target = other if turn["n"] == 2 else wanted
            pick = next(k for k, v in listed.items() if v == target)
        return [0.0 if label == pick else -30.0 for label in labels]

    decision = FastPathRouter().decide("games", "add points", wobbly)
    assert decision.route == GUIDE


def test_a_whole_game_ask_skips_the_one_change_gate_but_must_be_certain() -> None:
    avoid = describe("games", "make_avoid_game")
    # The gate would say "no" -- a whole game is several parts -- and must not be asked.
    scorer = FakeScorer(avoid, "no")
    decision = FastPathRouter().decide("games", "make a dodging game", scorer)
    assert decision.route == RECIPE and decision.recipe.whole
    assert all("exactly one" not in system for system, _ in scorer.calls)

    other = describe("games", "add_score")
    runs = {"n": 0}

    def mostly(system, user, labels):
        # Two orderings of three agree: 0.67, far below the whole-game bar.
        listed = dict(re.findall(r"^([A-Z])\. (.+)$", system, re.MULTILINE))
        runs["n"] += 1
        target = other if runs["n"] == 2 else avoid
        pick = next(k for k, v in listed.items() if v == target)
        return [0.0 if label == pick else -30.0 for label in labels]

    assert FastPathRouter().decide("games", "a whole dungeon game", mostly).route == NORMAL


def test_an_attached_picture_confirms_a_picture_request_the_gate_doubts() -> None:
    sprite = describe("games", "replace_player_sprite")
    scorer = FakeScorer(sprite, "no")
    router = FastPathRouter()
    assert router.decide("games", "use this", scorer).route == NORMAL
    decision = router.decide("games", "use this", scorer, attached_image=True)
    assert decision.route == RECIPE and decision.recipe.attachment_confirms


def test_a_profile_without_recipes_is_left_alone() -> None:
    assert FastPathRouter().decide("blank", "anything", FakeScorer()).route == NORMAL


# ----------------------------------------------------------------------- edits


@pytest.mark.parametrize("before,after", [
    ("a\nb\nc", "a\nx\nb\nc"),                 # insertion in the middle
    ("a\nb\nc", "top\na\nb\nc"),               # insertion at the very top
    ("a\nb\nc", "a\nc"),                       # deletion
    ("a\nb\nc\nd", "a\nB\nc\nD"),              # two separate hunks
    ("x = 1\nfill\nx = 1\nflip", "x = 1\nfill\nx = 1\nnew\nflip"),  # repeated lines
])
def test_hunks_reproduce_the_file_and_each_matches_exactly_once(before, after) -> None:
    assert edits.apply(before, edits.hunks(before, after)) == after


# ----------------------------------------------------------------------- slots


@pytest.mark.parametrize("text,title", [
    ("Call my game Space Rocks.", "Space Rocks"),
    ('change the title to "Maya\'s Dog Club"', "Maya's Dog Club"),
    ("call it 'Blob Quest'", "Blob Quest"),
])
def test_titles_are_read_as_written(text, title) -> None:
    assert slots.title_in(text) == title


def test_what_a_button_says_stops_where_the_description_starts() -> None:
    assert slots.words_in("add a button that says hello when you press it") == "hello"


@pytest.mark.parametrize("text,halves", [
    ("make it stay on for 1 second", ("on",)),
    ("a longer gap between blinks", ("off",)),
    ("blink faster", ("on", "off")),
])
def test_which_half_of_a_blink_is_meant(text, halves) -> None:
    assert slots.on_or_off(text) == halves


def test_a_pin_is_only_ever_what_the_child_wrote() -> None:
    assert slots.pin_in("my led is on pin 18") == 18
    assert slots.pin_in("add another led") is None
    assert slots.arduino_pin_in("a knob on A0") == "A0"


# ----------------------------------------------------------------------- games


def chosen(*answers):
    queue = list(answers)

    def choose(question, options):
        answer = queue.pop(0)
        assert answer in [option.name for option in options]
        return Classification((Scored(answer, 1.0),), 20, 1.0, 2, 1.0, 0.0)

    return choose


def test_games_facts_find_the_three_places_in_the_starter(project) -> None:
    facts = games.facts(project)
    lines = facts.get("source").split("\n")
    assert lines[facts.get("loop")].startswith("while running")
    assert "screen.fill" in lines[facts.get("fill")]
    assert "display.flip" in lines[facts.get("flip")]
    assert facts.get("player") == "player"
    assert facts.get("player_speed") == "PLAYER_SPEED"
    assert facts.get("background") == "BACKGROUND"


def made(project, change) -> str:
    """A recipe's change made the way the product makes it -- its edits, then its tool
    calls, through the Toolbox -- and the game it leaves."""
    from opennest.fastpath.executor import RecipeExecutor

    applied = RecipeExecutor().apply(change, Toolbox(project))
    assert all(result.ok for _, result in applied.calls)
    return project.entrypoint_path.read_text()


def test_a_new_thing_is_made_above_the_loop_moved_in_it_and_drawn_by_the_scene(project):
    facts = games.facts(project)
    ctx = Context(project, facts, "Add a ball that bounces around the screen.",
                  {"motion": "choose"}, choose=chosen("bounce"))
    change = games.add_things(ctx)
    # How it looks is the same game_object call Gary makes, with the kit's shapes.
    assert [tool for tool, _ in change.calls] == ["game_object"]
    assert change.calls[0][1]["name"] == "balls" and change.calls[0][1]["shapes"]
    source = made(project, change)
    compile(source, "game.py", "exec")
    lines = source.split("\n")
    loop = next(i for i, line in enumerate(lines) if line.startswith("while running"))
    fill = next(i for i, line in enumerate(lines) if "screen.fill" in line)
    setup = next(i for i, line in enumerate(lines) if line.startswith("balls = []"))
    look = next(i for i, line in enumerate(lines) if line.startswith('scene.add("balls"'))
    move = next(i for i, line in enumerate(lines) if "ball.x += ball_move[0]" in line)
    draw = next(i for i, line in enumerate(lines) if line.strip() == "scene.draw()")
    assert setup < look < loop < move < fill < draw
    assert "rects=balls" in source and "Circle(" in source and "BALL_COLOUR)" in source


def test_the_same_project_gets_the_same_build_and_another_project_may_not(tmp_path):
    ask = "Make a game where a spaceship moves around and avoids asteroids."
    params = {"motion": ["drift", "fall", "zigzag", "wave"], "noun": "asteroid",
              "many": True, "on_touch": "reset_player", "ship_player": True}

    built = []

    def build(name: str) -> str:
        # Its own directory each time, the same project name: the seed is the name.
        built.append(name)
        project = create_project(name, "games", root=tmp_path / str(len(built)))
        change = games.add_things(Context(project, games.facts(project), ask, params))
        return next(iter(change.files.values()))

    assert build("Kid One") == build("Kid One")
    assert len({build(name) for name in ("Kid One", "Kid Two", "Kid Three", "Kid Four")}) > 1


def test_the_childs_own_words_win_over_the_seed(project) -> None:
    ctx = Context(project, games.facts(project), "add a big red ball that bounces",
                  {"motion": "choose"}, choose=chosen("bounce"))
    change = games.add_things(ctx)
    source = next(iter(change.files.values()))
    assert "BALL_COLOUR = (220, 60, 60)" in source
    assert "big red ball" in change.values["what"]


def test_a_speed_change_edits_only_the_number(project) -> None:
    before = project.entrypoint_path.read_text()
    recipe = RecipeRegistry().for_profile("games").for_intent("change_player_speed")
    ctx = Context(project, games.facts(project), "Make the player move faster.",
                  recipe.params, choose=chosen("up"))
    after = next(iter(games.set_number(ctx).files.values()))
    changed = [(a, b) for a, b in zip(before.split("\n"), after.split("\n")) if a != b]
    assert changed == [("PLAYER_SPEED = 5", "PLAYER_SPEED = 8")]


def test_a_picture_replaces_the_ship_an_earlier_recipe_drew(project) -> None:
    """Recipes compose: the dodging game's ship must not stop the picture recipe.

    Found by driving the real app (SPIKES.md section 25): the player's drawing was only
    recognised as the starter's one-line rectangle, so after the ship replaced it the
    picture recipe could not find the player and stepped aside.
    """
    ship = Context(project, games.facts(project), "a spaceship game dodging asteroids",
                   {"motion": "drift", "noun": "asteroid", "many": True,
                    "on_touch": "reset_player", "ship_player": True})
    made(project, games.add_things(ship))
    # Phase 13C: the ship is a shape in the player's colour, drawn by the scene.
    source = project.entrypoint_path.read_text()
    assert 'scene.add("player", Drawing((40, 40), [' in source and "PLAYER_COLOUR)" in source
    assert "pygame.draw.rect(screen, PLAYER_COLOUR, player)" not in source
    assert "a drawing of 1 shape" in games.brief(games.facts(project))
    # ... and still the player's colour, so "make my ship blue" is still a recipe.
    assert games.facts(project).get("player_colour") == "PLAYER_COLOUR"

    (project.directory / "assets").mkdir(exist_ok=True)
    (project.directory / "assets" / "ship.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    change = games.use_sprite(Context(project, games.facts(project), "use my picture", {}))
    # Phase 13C: through the graphics layer, the same call Gary would make.
    assert change.calls == [("game_object", {"name": "player", "picture": "assets/ship.png"})]
    result = Toolbox(project).dispatch(*change.calls[0])
    assert result.ok, result.content
    source = project.entrypoint_path.read_text()
    compile(source, "game.py", "exec")
    assert "Polygon" not in source and 'Picture("assets/ship.png")' in source
    assert source.count('scene.add("player"') == 1        # the ship's line was replaced


def test_a_game_that_is_no_longer_starter_shaped_is_not_touched(project) -> None:
    project.entrypoint_path.write_text("import pygame\nprint('hello')\n")
    ctx = Context(project, games.facts(project), "add a ball", {"motion": "bounce"})
    with pytest.raises(NotApplicable):
        games.add_things(ctx)


def test_a_picture_the_project_does_not_have_is_asked_about(project) -> None:
    ctx = Context(project, games.facts(project), "use my picture", {})
    with pytest.raises(NeedsAnswer):
        games.use_sprite(ctx)


def test_every_noun_is_drawn_by_the_scene_from_generic_looks(tmp_path) -> None:
    """Every thing a recipe can add is given its look through game_object -- a ready-made
    drawing or the kit's basic shapes -- and nothing is drawn with inline pygame."""
    from opennest.graphics import looks

    for noun in game_things.NOUNS:
        project = create_project(noun, "games", root=tmp_path / noun)
        ctx = Context(project, games.facts(project), f"add a {noun}",
                      {"motion": "drift", "noun": noun})
        change = games.add_things(ctx)
        (tool, arguments), = change.calls
        assert tool == "game_object"
        assert arguments.get("drawing") in (None, *looks.DRAWINGS), noun
        source = made(project, change)
        compile(source, noun, "exec")
        assert source.count("pygame.draw.") == 1, noun         # only the starter's square
        assert f'scene.add("{arguments["name"]}"' in source, noun


# ------------------------------------------------------ other project types


def test_a_website_section_is_linked_from_the_menu_and_the_page_stays_balanced(tmp_path):
    project = create_project("Site", "website", root=tmp_path)
    ctx = Context(project, website.facts(project), "add a section about my favourite films", {})
    change = website.add_section(ctx)
    page = change.files["src/index.html"]
    assert 'id="my-favourite-films"' in page and 'href="#my-favourite-films"' in page
    assert "<ul>" in page.split('id="my-favourite-films"')[1]
    (project.directory / "src/index.html").write_text(page)
    assert website.facts(project).get("balanced")


def test_a_contact_section_warns_about_personal_details(tmp_path) -> None:
    project = create_project("Site", "website", root=tmp_path)
    change = website.add_section(Context(project, website.facts(project),
                                         "add a contact me section", {}))
    assert "Ask a grown-up" in change.files["src/index.html"]


def test_a_picture_on_a_page_is_never_described_by_open_nest(tmp_path) -> None:
    project = create_project("Site", "website", root=tmp_path)
    (project.directory / "assets").mkdir(exist_ok=True)
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (32).to_bytes(4, "big")
           + (32).to_bytes(4, "big") + b"\x08\x06\x00\x00\x00" + b"\x00" * 4)
    (project.directory / "assets" / "red-dragon.png").write_bytes(png)
    change = website.add_image(Context(project, website.facts(project),
                                       "put my picture on the page", {}))
    page = change.files["src/index.html"]
    assert 'alt="Say what this picture shows"' in page
    assert "dragon" not in page.split("<img")[1].split("alt=")[1]


def test_research_writes_code_that_computes_the_finding(tmp_path) -> None:
    project = create_project("Plants", "research", root=tmp_path)
    (project.directory / "data").mkdir(exist_ok=True)
    (project.directory / "data/plants.csv").write_text(
        "day,plant,height_cm\n1,Basil,2.0\n1,Mint,2.5\n2,Basil,3.0\n2,Mint,2.9\n")
    ctx = Context(project, research.facts(project),
                  "make a bar chart of height for each plant", {"chart": "bar"})
    change = research.chart(ctx)
    source = change.files["src/analysis.py"]
    compile(source, "analysis.py", "exec")
    assert 'groupby("plant")["height_cm"].mean()' in source
    assert "has the highest" in source          # the title is computed, not asserted
    assert change.expect["chart"] == "charts/height_cm_by_plant.png"


def test_research_with_no_data_asks_for_some(tmp_path) -> None:
    project = create_project("Empty", "research", root=tmp_path)
    with pytest.raises(NeedsAnswer):
        research.chart(Context(project, research.facts(project), "bar chart", {"chart": "bar"}))


@pytest.mark.parametrize("request_text", ["add another LED", "add an LED on pin 1",
                                          "add an LED on pin 0"])
def test_an_arduino_pin_is_never_invented_or_the_usb_pins(tmp_path, request_text) -> None:
    project = create_project("Blink", "arduino", root=tmp_path)
    with pytest.raises(NeedsAnswer):
        arduino.add_led(Context(project, arduino.facts(project), request_text, {}))


def test_an_arduino_led_gets_a_wiring_row_with_its_resistor(tmp_path) -> None:
    project = create_project("Blink", "arduino", root=tmp_path)
    change = arduino.add_led(Context(project, arduino.facts(project),
                                     "add a red LED on pin 9", {}))
    wiring = change.files["src/project/wiring.md"]
    assert "| Red LED | 9 |" in wiring and "resistor" in wiring
    assert "const int RED_LED_PIN = 9;" in change.files["src/project/project.ino"]


def test_stay_on_longer_changes_only_the_on_time(tmp_path) -> None:
    project = create_project("Blink", "arduino", root=tmp_path)
    change = arduino.blink_timing(Context(project, arduino.facts(project),
                                          "make it stay on for 1 second", {}))
    assert change.values["on"] == "1000" and change.values["off"] == "500"


def test_a_pi_pin_must_be_named(tmp_path) -> None:
    project = create_project("Blink", "raspberry_pi", root=tmp_path)
    with pytest.raises(NeedsAnswer):
        raspberry_pi.led_pin(Context(project, raspberry_pi.facts(project),
                                     "move the led to another pin", {}))


# ------------------------------------------------------------------ controller


def test_a_recipe_turn_edits_through_the_toolbox_and_never_asks_the_model(project) -> None:
    scorer = FakeScorer(describe("games", "change_player_speed"), YES, "faster")
    controller, provider = controller_for(project, scorer)
    turn = controller.send("Make the player move faster.")

    assert turn.fastpath["route"] == RECIPE and turn.fastpath["result"] == "success"
    assert "PLAYER_SPEED = 8" in project.entrypoint_path.read_text()
    assert provider.calls == []                       # no generation at all
    assert [name for name, _ in turn.tool_results] == ["edit_file"]
    assert "PLAYER_SPEED" in turn.text and "8" in turn.text

    # Gary's history holds what really happened: the edit, its result, and his words.
    roles = [m.role for m in controller.history[-4:]]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert controller.history[-3].tool_calls[0].name == "edit_file"
    assert controller.history[-1].content == turn.text


def test_the_next_turn_tells_gary_what_open_nest_did(project) -> None:
    scorer = FakeScorer(describe("games", "change_player_speed"), YES, "faster")
    controller, provider = controller_for(project, scorer, [Reply(text="Sure.")])
    controller.send("Make the player move faster.")
    scorer.picks = []                                  # "other": Gary takes the next one
    controller.send("why is it faster?")
    assert "WHAT OPEN NEST JUST DID" in provider.system_prompt
    assert "game.change_player_speed" in provider.system_prompt
    provider.replies.append(Reply(text="Again."))
    controller.send("hello")
    assert "WHAT OPEN NEST JUST DID" not in provider.system_prompt


def test_guidance_reaches_gary_for_one_turn_only(project) -> None:
    project.entrypoint_path.write_text(
        "import pygame\nwhile True:\n    pygame.display.flip()\n")
    scorer = FakeScorer(describe("games", "add_moving_thing"), YES, "bounces around the "
                        "screen off the edges")
    controller, provider = controller_for(project, scorer,
                                          [Reply(text="Here."), Reply(text="Hi.")])
    turn = controller.send("add a ball that bounces")
    assert turn.fastpath["route"] == GUIDE
    assert "A KNOWN WAY TO DO THIS" in provider.system_prompt
    scorer.picks = []
    controller.send("thanks")
    assert "A KNOWN WAY TO DO THIS" not in provider.system_prompt


def test_a_change_that_fails_its_check_is_undone_exactly(project) -> None:
    before = project.entrypoint_path.read_bytes()

    def broken(*_args, **_kwargs):
        return playtest.Playtest(playtest.CRASHED, entry="src/game.py", error="boom")

    scorer = FakeScorer(describe("games", "change_player_speed"), YES, "faster")
    controller, provider = controller_for(project, scorer, [Reply(text="Let me look.")],
                                          playtest_result=broken)
    turn = controller.send("Make the player move faster.")
    assert turn.fastpath["result"] == "verification_failed"
    assert turn.fastpath["rolled_back"] is True
    assert project.entrypoint_path.read_bytes() == before
    assert len(provider.calls) == 1                   # Gary took the turn
    assert all(name != "edit_file" for name, _ in turn.tool_results)


def test_a_fast_path_that_raises_is_recorded_and_gary_takes_the_turn(project) -> None:
    class Exploding(FastPathRouter):
        def handle(self, *args, **kwargs):
            raise RuntimeError("bug")

    provider = ScriptedProvider([Reply(text="Hello.")])
    controller = AgentController(project, provider, Toolbox(project), fastpath=Exploding())
    turn = controller.send("hi")
    assert turn.text == "Hello."
    assert "bug" in turn.fastpath["reason"]


def test_a_cloud_model_with_no_scorer_gets_the_normal_path(project) -> None:
    provider = ScriptedProvider([Reply(text="Done.")])       # no score_choices
    controller = AgentController(project, provider, Toolbox(project),
                                 fastpath=FastPathRouter())
    turn = controller.send("Make the player move faster.")
    assert turn.fastpath["route"] == NORMAL
    assert "no model" in turn.fastpath["reason"]
    assert len(provider.calls) == 1


def test_a_separate_classifier_can_serve_a_model_that_cannot_score(project) -> None:
    """D13: a cloud Gary with the local model classifying. The wiring, not the policy."""
    local = ScoringProvider([], FakeScorer(describe("games", "change_player_speed"), YES,
                                           "faster"))
    provider = ScriptedProvider([])
    toolbox = Toolbox(project)
    toolbox.playtest = passing_playtest
    controller = AgentController(project, provider, toolbox,
                                 fastpath=FastPathRouter(classifier_provider=local))
    turn = controller.send("Make the player move faster.")
    assert turn.fastpath["route"] == RECIPE
    assert provider.calls == []


def test_recipes_build_on_each_other_and_on_what_is_in_the_file(project) -> None:
    avoid = describe("games", "make_avoid_game")
    faster = describe("games", "change_thing_speed")
    controller, _ = controller_for(project, FakeScorer(avoid, YES))
    first = controller.send("Make a game where a spaceship moves around and avoids asteroids.")
    assert first.fastpath["result"] == "success"
    source = project.entrypoint_path.read_text()
    speed = re.search(r"ASTEROID_SPEED = (\d+)", source).group(1)

    controller.fastpath = FastPathRouter()
    controller.provider = ScoringProvider([], FakeScorer(faster, YES, "faster"))
    second = controller.send("Make the asteroids move faster.")
    assert second.fastpath["result"] == "success"
    after = project.entrypoint_path.read_text()
    assert int(re.search(r"ASTEROID_SPEED = (\d+)", after).group(1)) > int(speed)
    # Only the one number changed; the first recipe's work is all still there.
    new_speed = re.search(r"ASTEROID_SPEED = (\d+)", after).group(1)
    assert [line for line in after.split("\n") if line not in source.split("\n")] == [
        f"ASTEROID_SPEED = {new_speed}"]


def test_a_real_playtest_verifies_a_recipe(project) -> None:
    """One end-to-end run with the real headless playtest -- the rest stub it for speed."""
    scorer = FakeScorer(describe("games", "add_moving_thing"), YES,
                        "bounces around the screen off the edges")
    controller, _ = controller_for(project, scorer, playtest_result=None)
    turn = controller.send("Add a ball that bounces around the screen.")
    checks = {c["check"]: c["status"] for c in turn.fastpath.get("verification", [])}
    if checks.get("playtest_passes") == "unavailable":
        pytest.skip("the process sandbox cannot be applied here")
    assert turn.fastpath["result"] == "success"
    assert checks == {"playtest_passes": "pass", "moves_by_itself": "pass",
                      "thing_drawn": "pass"}
    assert "something moves on its own" in turn.text


def test_an_edit_outside_the_project_is_refused_and_nothing_changes(project, monkeypatch):
    before = project.entrypoint_path.read_bytes()

    def escape(ctx):
        from opennest.fastpath.kinds import Change
        return Change(files={"../outside.py": "print('no')\n"})

    monkeypatch.setitem(games.OPS, "set_number", escape)
    scorer = FakeScorer(describe("games", "change_player_speed"), YES)
    controller, provider = controller_for(project, scorer, [Reply(text="Okay.")])
    turn = controller.send("Make the player move faster.")
    assert turn.fastpath["route"] == NORMAL
    assert project.entrypoint_path.read_bytes() == before
    assert not (Path(project.directory).parent / "outside.py").exists()


# --------------------------------------------------------------- closure pass
#
# SPIKES.md section 25M: Blank projects gain a family from their files, the three
# known missing cases, and the one website gap. No model: the fakes above.

STARTERS = Path(__file__).resolve().parents[1] / "opennest" / "projects" / "starters"


def by_message(intent: str, gate):
    """A scorer that picks ``intent`` for "which kind", and ``gate(message)`` for yes/no."""

    def scorer(system, user, labels):
        listed = dict(re.findall(r"^([A-Z])\. (.+)$", system, re.MULTILINE))
        message = user.rsplit("Message: ", 1)[1]
        want = gate(message) if "yes" in listed.values() else intent
        pick = next((k for k, v in listed.items() if v == want), labels[-1])
        return [0.0 if label == pick else -30.0 for label in labels]

    return scorer


def blank_with(tmp_path, files: dict[str, str]):
    project = create_project("Something", "blank", root=tmp_path)
    for relative, text in files.items():
        path = project.directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return project


def _starter(name: str) -> str:
    return (STARTERS / name).read_text()


@pytest.mark.parametrize("files,family", [
    ({"src/index.html": "<html></html>"}, "website"),
    ({"src/main.py": "import pygame\n"}, "games"),
    ({"src/main.py": "import pandas as pd\n", "data/plants.csv": "a,b\n1,2\n"}, "research"),
    ({"src/main.py": "def on():\n    import RPi.GPIO as GPIO\n"}, "raspberry_pi"),
    ({"src/blink/blink.ino": "void setup() {}\nvoid loop() {}\n"}, "arduino"),
    ({}, None),
    ({"src/main.py": "import pandas as pd\n"}, None),            # no data to analyse yet
    ({"data/plants.csv": "a,b\n1,2\n"}, None),                    # data, and no analysis
    ({"src/index.html": "<html></html>", "src/main.py": "import pygame\n"}, None),
])
def test_a_blank_project_gains_a_family_from_its_files(tmp_path, files, family) -> None:
    from opennest.fastpath.kinds import family_for

    found, why = family_for(blank_with(tmp_path, files))
    assert found == family, why


def test_a_blank_website_is_offered_only_website_recipes_and_they_run(tmp_path) -> None:
    project = blank_with(tmp_path, {
        f"src/{name}": _starter(f"website_basic/{name}")
        for name in ("index.html", "styles.css", "script.js")})
    scorer = FakeScorer(describe("website", "change_colours"), YES)
    controller, provider = controller_for(project, scorer)
    turn = controller.send("make the background dark blue")

    assert turn.fastpath["family"] == "website"
    assert turn.fastpath["result"] == "success"
    assert "--bg: #0f1950;" in (project.directory / "src/styles.css").read_text()
    intent_questions = [system for system, _ in scorer.calls if "The kinds:" in system]
    assert intent_questions and all(describe("website", "add_card") in s
                                    for s in intent_questions)
    assert not any(describe("games", "add_score") in s for s in intent_questions)
    # There is no Preview Website button in a Blank project, so it is not mentioned.
    assert "Preview Website" not in turn.text
    assert provider.calls == []


def test_a_game_in_a_blank_project_is_guidance_not_an_unchecked_edit(tmp_path) -> None:
    project = blank_with(tmp_path, {"src/main.py": _starter("pygame_basic/game.py")})
    before = project.entrypoint_path.read_text()
    scorer = FakeScorer(describe("games", "change_player_speed"), YES, "faster")
    controller, provider = controller_for(project, scorer, [Reply(text="Here you go.")])
    turn = controller.send("Make the player move faster.")

    assert turn.fastpath["family"] == "games"
    assert turn.fastpath["route"] == GUIDE
    assert "cannot run the check" in turn.fastpath["stepped_aside"]
    assert project.entrypoint_path.read_text() == before
    assert "A KNOWN WAY TO DO THIS" in provider.system_prompt
    assert len(provider.calls) == 1


def test_a_blank_project_with_nothing_recognisable_is_left_to_gary(tmp_path) -> None:
    project = blank_with(tmp_path, {"src/main.py": "print('hello')\n"})
    scorer = FakeScorer(describe("games", "change_player_speed"), YES)
    controller, provider = controller_for(project, scorer, [Reply(text="Hi.")])
    turn = controller.send("make it faster")
    assert turn.fastpath["route"] == NORMAL
    assert scorer.calls == []              # nothing was put to the classifier at all


# -- how an existing thing moves ------------------------------------------------------

def _dodging_game(project, motion: str = "drift") -> str:
    ctx = Context(project, games.facts(project), "a spaceship game dodging asteroids",
                  {"motion": motion, "noun": "asteroid", "many": True,
                   "on_touch": "reset_player", "ship_player": True})
    return made(project, games.add_things(ctx))


def test_an_existing_thing_can_be_made_to_zigzag(project) -> None:
    before = _dodging_game(project)
    assert games.motion_of(games.facts(project), "ASTEROID")[0] == "drift"
    ctx = Context(project, games.facts(project),
                  "Make the asteroids zigzag instead of going straight.", {})
    change = games.thing_motion(ctx)
    after = change.files["src/game.py"]
    compile(after, "game.py", "exec")
    project.entrypoint_path.write_text(after)
    assert games.motion_of(games.facts(project), "ASTEROID")[0] == "zigzag"
    assert change.values["how"] == "zigzag across the screen and come back round"
    # Only the setup and the movement changed: drawing, touching and constants did not.
    kept = [line for line in before.split("\n") if "collidelist" in line
            or "ASTEROID_COLOUR" in line or line.startswith("ASTEROID_")]
    assert kept and all(line in after.split("\n") for line in kept)


def test_the_motion_named_after_instead_of_is_the_old_one(project) -> None:
    _dodging_game(project, "zigzag")
    ctx = Context(project, games.facts(project),
                  "make the asteroids fall instead of zigzagging", {})
    assert games.thing_motion(ctx).expect["motion"] == "fall"


def test_movement_code_someone_changed_is_left_to_gary(project) -> None:
    source = _dodging_game(project)
    project.entrypoint_path.write_text(
        source.replace("asteroid.x -= ASTEROID_SPEED", "asteroid.x -= ASTEROID_SPEED * 2"))
    with pytest.raises(NotApplicable, match="changed"):
        games.thing_motion(Context(project, games.facts(project),
                                   "make the asteroids bounce", {}))


def test_a_motion_change_is_made_and_checked_through_the_controller(project) -> None:
    _dodging_game(project)
    scorer = FakeScorer(describe("games", "change_thing_motion"), YES)
    controller, provider = controller_for(project, scorer)
    turn = controller.send("Make the asteroids zigzag instead of going straight.")
    checks = {c["check"]: c["status"] for c in turn.fastpath["verification"]}
    assert turn.fastpath["result"] == "success"
    assert checks["motion_set"] == "pass" and checks["thing_drawn"] == "pass"
    assert "zigzag" in turn.text and provider.calls == []


# -- what an Arduino button does ------------------------------------------------------

@pytest.mark.parametrize("text,behaviour,shows", [
    ("add a button on pin 2 that turns the light on when i press it", "steady",
     "digitalWrite(LED_PIN, HIGH);"),
    ("add a button on pin 2 and the light only comes on when i press it", "steady",
     "digitalWrite(LED_PIN, HIGH);"),
    ("add a button on pin 3 that turns the light on and off", "toggle", "lightOn = !lightOn;"),
    ("add a button on pin 2 that makes it blink", "blink", "delay(ON_MILLISECONDS);"),
    ("add a button on pin 2", "blink", "delay(ON_MILLISECONDS);"),
])
def test_an_arduino_button_does_what_the_child_said(tmp_path, text, behaviour, shows) -> None:
    project = create_project("Blink", "arduino", root=tmp_path)
    change = arduino.add_button(Context(project, arduino.facts(project), text, {}))
    sketch = change.files["src/project/project.ino"]
    assert change.values["behaviour"] == behaviour
    assert shows in sketch and "INPUT_PULLUP" in sketch
    assert sketch.count("{") == sketch.count("}")
    if behaviour != "blink":
        assert "delay(ON_MILLISECONDS)" not in sketch


def test_a_button_asked_to_do_two_things_is_left_to_gary(tmp_path) -> None:
    project = create_project("Blink", "arduino", root=tmp_path)
    with pytest.raises(NotApplicable):
        arduino.add_button(Context(project, arduino.facts(project),
                                   "a button on pin 2 that turns the light on and makes it "
                                   "blink", {}))


def test_blink_timing_is_not_a_fact_once_the_light_no_longer_blinks(tmp_path) -> None:
    project = create_project("Blink", "arduino", root=tmp_path)
    change = arduino.add_button(Context(project, arduino.facts(project),
                                        "add a button on pin 2 that turns the light on", {}))
    (project.directory / "src/project/project.ino").write_text(
        change.files["src/project/project.ino"])
    assert not arduino.facts(project).has("blink_times")


# -- the words on a page ---------------------------------------------------------------

@pytest.mark.parametrize("text,part,words", [
    ("make the tagline say i like cats and minecraft", "the line under the headline",
     "i like cats and minecraft"),
    ("change the button to say Surprise me!", "the button", "Surprise me"),
    ("change the footer to made by jayden 2026", "the footer", "made by jayden 2026"),
    ("put 'everything about axolotls' under the title instead of what it says now",
     "the line under the headline", "everything about axolotls"),
])
def test_the_words_of_a_named_part_change(tmp_path, text, part, words) -> None:
    project = create_project("Site", "website", root=tmp_path)
    change = website.set_text(Context(project, website.facts(project), text, {}))
    page = change.files["src/index.html"]
    assert change.values["part"] == part and words in page
    (project.directory / "src/index.html").write_text(page)
    assert website.facts(project).get("balanced")


def test_words_for_a_part_that_is_not_named_are_left_to_gary(tmp_path) -> None:
    project = create_project("Site", "website", root=tmp_path)
    with pytest.raises(NotApplicable):
        website.set_text(Context(project, website.facts(project),
                                 "rename the cards to Dogs, Cats and Fish", {}))


def test_to_say_is_not_part_of_the_words() -> None:
    assert slots.words_in("change the title to say Hello There") == "Hello There"


# -- research: the known confusion, the compound request, and time order -------------

def test_a_superlative_is_not_a_change_so_the_recipe_is_not_taken() -> None:
    biggest = describe("research", "biggest_change")
    router = FastPathRouter()
    windiest = router.decide("research", "find the windiest day",
                             FakeScorer(biggest, YES))
    assert windiest.route == NORMAL and "does not say" in windiest.reason
    # Said as two requests, it is decided in two parts -- and the veto holds in each.
    assert router.decide("research", "find the windiest day and print it",
                         FakeScorer(biggest, YES)).route == COMPOUND
    assert router.decide("research", "which plant grew the most?",
                         FakeScorer(biggest, YES)).route == RECIPE


@pytest.mark.parametrize("message", [
    "Make the background a black sky full of little stars, with a big purple planet.",
    "Make it look like the deep sea: dark blue water, sand on the bottom, green seaweed "
    "and bubbles floating up.",
])
def test_a_background_that_is_also_things_to_see_is_garys(message) -> None:
    """The 13C worlds walk (SPIKES.md section 28M): each became one colour, the stars,
    planet, sand and seaweed dropped. With things to see in it, the message is Gary's,
    who has game_object -- and he is not handed the one-colour recipe as his pattern."""
    background = describe("games", "change_background")
    decision = FastPathRouter().decide("games", message, FakeScorer(background, YES))
    assert decision.route == NORMAL and "does not say" in decision.reason


@pytest.mark.parametrize("message", [
    "change the backround to black", "Change the background colour to dark blue.",
    "backround should be dark purple", "make the background grass green",
])
def test_a_plain_background_colour_is_still_the_recipes(message) -> None:
    background = describe("games", "change_background")
    decision = FastPathRouter().decide("games", message, FakeScorer(background, YES))
    assert decision.route == RECIPE


def test_graph_this_and_one_charting_change_is_taken_by_that_recipe() -> None:
    biggest = describe("research", "biggest_change")
    two_things = by_message(biggest, lambda m: "no" if " and " in m else "yes")
    decision = FastPathRouter().decide(
        "research", "Graph this and tell me what changed the most.", two_things)
    assert decision.route == RECIPE and decision.recipe.id == "analysis.biggest_change"
    assert decision.compound["covered"] == "Graph this"
    assert decision.compound["decided"] == "tell me what changed the most"


@pytest.mark.parametrize("text,intent", [
    ("graph this and make the chart red", "restyle_chart"),      # guide-only recipe
    ("make a bar chart and tell me what changed the most", "biggest_change"),  # no bare part
    ("graph this and tell me what changed the most and why", "biggest_change"),  # three
    ("graph this and find the windiest day", "biggest_change"),  # the veto still holds
    ("graph this and what does std mean", "describe_data"),      # no chart in the recipe
])
def test_every_other_compound_still_goes_to_gary(text, intent) -> None:
    """Never one recipe for the whole message. Several requests are decided one by one
    (``run_parts``); none of these is one a charting recipe covers."""
    scorer = by_message(describe("research", intent), lambda m: "no" if " and " in m else "yes")
    assert FastPathRouter().decide("research", text, scorer).route in (NORMAL, COMPOUND)


def test_month_names_are_kept_in_the_order_they_were_written(tmp_path) -> None:
    """The Phase 12 walk's own CSV: sorted alphabetically, Jan-Dec became Apr-Sep."""
    project = create_project("Weather", "research", root=tmp_path)
    (project.directory / "data").mkdir(exist_ok=True)
    (project.directory / "data/weather.csv").write_text(
        "month,rainfall_mm,sunshine_hours\nJan,88,44\nFeb,71,68\nMar,60,110\n"
        "Apr,52,150\nMay,49,190\nJun,44,205\nJul,42,215\nAug,55,196\nSep,64,150\n"
        "Oct,86,105\nNov,92,60\nDec,95,40\n")
    change = research.biggest_change(Context(
        project, research.facts(project), "tell me what changed the most", {}))
    source = change.files["src/analysis.py"]
    compile(source, "analysis.py", "exec")
    # month is the one time axis -- "sunshine_hours" is a measurement, not a second one --
    # and it is not sorted, because sorting month names puts April first.
    assert "from the first month to the last" in source
    assert "sunshine_hours" in source
    assert 'sort_values("month")' not in source
    pytest.importorskip("pandas")
    pytest.importorskip("matplotlib")
    import subprocess
    import sys

    (project.directory / "src/analysis.py").write_text(source)
    ran = subprocess.run([sys.executable, "src/analysis.py"], cwd=project.directory,
                         capture_output=True, text=True, timeout=120,
                         env={"MPLBACKEND": "Agg", "PATH": "/usr/bin:/bin",
                              "MPLCONFIGDIR": str(tmp_path / "mpl")})
    assert ran.returncode == 0, ran.stderr
    assert "The biggest change was rainfall_mm: +7.00" in ran.stdout   # Dec 95 - Jan 88
    assert "sunshine_hours" in ran.stdout                              # 40 - 44, also shown


def test_days_that_are_numbers_are_still_sorted(tmp_path) -> None:
    project = create_project("Plants", "research", root=tmp_path)
    (project.directory / "data").mkdir(exist_ok=True)
    (project.directory / "data/plants.csv").write_text(
        "day,plant,height_cm\n2,Basil,3.0\n1,Basil,2.0\n2,Mint,2.9\n1,Mint,2.5\n")
    change = research.biggest_change(Context(
        project, research.facts(project), "which plant grew the most", {}))
    assert 'sort_values("day")' in change.files["src/analysis.py"]


def test_a_part_gets_the_recipe_question_and_a_whole_message_does_not() -> None:
    """The general gate calls "tell me what changed the most" a question, not a change --
    measured, on the real model, even on its own. Within "graph this and ...", the part is
    asked the recipe's own question instead; a single message is not."""
    biggest = describe("research", "biggest_change")

    def scorer(system, user, labels):
        listed = dict(re.findall(r"^([A-Z])\. (.+)$", system, re.MULTILINE))
        if "yes" in listed.values():
            want = "yes" if "nothing more" in system else "no"
        else:
            want = biggest
        pick = next((k for k, v in listed.items() if v == want), labels[-1])
        return [0.0 if label == pick else -30.0 for label in labels]

    router = FastPathRouter()
    assert router.decide("research", "tell me what changed the most", scorer).route == NORMAL
    decision = router.decide("research", "Graph this and tell me what changed the most.", scorer)
    assert decision.route == RECIPE and decision.compound["shape"]["intent"] == "one"


# -- "it already is" ----------------------------------------------------------------

def test_already_zigzagging_is_answered_not_handed_to_gary(project) -> None:
    """The owner's first test drive: the cars already zigzagged, the recipe stepped aside,
    and Gary rewrote code that was fine. Now Open Nest says so and changes nothing."""
    _dodging_game(project, "zigzag")
    before = project.entrypoint_path.read_text()
    scorer = FakeScorer(describe("games", "change_thing_motion"), YES)
    controller, provider = controller_for(project, scorer)
    turn = controller.send("Make the asteroids zigzag.")
    assert turn.fastpath["result"] == "already"
    assert turn.text == ("The asteroids already zigzag across the screen and come back "
                         "round, so I left them as they are.")
    assert project.entrypoint_path.read_text() == before
    assert provider.calls == [] and turn.tool_results == []
    assert controller.history[-1].content == turn.text
    assert controller.history[-2].role == "user"      # no empty assistant message


@pytest.mark.parametrize("make_change,text,said", [
    (lambda p: games.set_colour(Context(p, games.facts(p), "make the background dark blue",
                                        {"fact": "background", "question": "?"},
                                        choose=chosen("dark blue"))),
     None, "The background is already dark blue"),
    (lambda p: games.set_caption(Context(p, games.facts(p), "call my game My Game", {})),
     None, "already called \u201cMy Game\u201d"),
])
def test_a_game_already_that_way_says_so(project, make_change, text, said) -> None:
    source = project.entrypoint_path.read_text()
    project.entrypoint_path.write_text(source.replace("BACKGROUND = (18, 22, 34)",
                                                      "BACKGROUND = (15, 25, 80)"))
    with pytest.raises(AlreadyDone, match=said):
        make_change(project)


def test_pi_and_website_already_that_way_say_so(tmp_path) -> None:
    pi = create_project("Blink", "raspberry_pi", root=tmp_path / "pi")
    with pytest.raises(AlreadyDone, match="already on BCM pin 17"):
        raspberry_pi.led_pin(Context(pi, raspberry_pi.facts(pi), "move the led to pin 17", {}))
    site = create_project("Site", "website", root=tmp_path / "site")
    with pytest.raises(AlreadyDone, match="The footer already says"):
        website.set_text(Context(site, website.facts(site),
                                 "change the footer to say Made with Open Nest.", {}))



# -- several requests in one message (pre-13) ------------------------------------------

def by_part(picks: dict[str, str], *, slots: dict[str, str] | None = None):
    """A scorer that picks an intent by which words the message has, says yes to every
    gate, and answers detail questions from ``slots`` (question word -> option text)."""
    slots = slots or {}

    def scorer(system, user, labels):
        listed = dict(re.findall(r"^([A-Z])\. (.+)$", system, re.MULTILINE))
        message = user.rsplit("Message: ", 1)[1].lower()
        if "yes" in listed.values():
            want = "yes"
        elif "The kinds:" in system:
            want = next((d for words, d in picks.items() if words in message), None)
        else:
            want = next((d for words, d in slots.items() if words in system), None)
        pick = next((k for k, v in listed.items() if v == want), labels[-1])
        return [0.0 if label == pick else -30.0 for label in labels]

    return scorer


_FASTER = {"faster": "faster"}


def test_the_split_is_only_of_requests_that_stand_on_their_own() -> None:
    assert split_parts("Make the cars faster and add a score") == [
        "Make the cars faster", "add a score"]
    assert split_parts("make it blink 20 times, use pin 23, and add a buzzer") == [
        "make it blink 20 times", "use pin 23", "add a buzzer"]
    for whole in ("make the tagline say i like cats and minecraft",
                  "make the asteroids red and bigger", "can you make it sweep back and forth",
                  "traffic light!! red yellow green on 11 12 and 13",
                  "add a button on pin 2 and the light only comes on when i press it"):
        assert split_parts(whole) is None, whole


def test_two_requests_are_each_made_and_checked(project) -> None:
    _dodging_game(project)
    scorer = by_part({"faster": describe("games", "change_thing_speed"),
                      "score": describe("games", "add_score")},
                     slots={"faster or slower": "faster",
                            "score go up": "it is just a score shown on screen; they did "
                                           "not say how it goes up"})
    controller, provider = controller_for(project, scorer)
    turn = controller.send("Make the asteroids faster and add a score")

    parts = turn.fastpath["parts"]
    assert [p.get("recipe") for p in parts] == ["game.change_thing_speed", "game.add_score"]
    assert turn.fastpath["result"] == "success" and provider.calls == []
    assert "ASTEROID_SPEED" in turn.text and "Score" in turn.text or "score" in turn.text
    source = project.entrypoint_path.read_text()
    assert "score = 0" in source


def test_the_part_no_recipe_makes_goes_to_gary_in_the_same_turn(project) -> None:
    _dodging_game(project)
    scorer = by_part({"faster": describe("games", "change_thing_speed")},
                     slots={"faster or slower": "faster"})
    controller, provider = controller_for(project, scorer, [Reply(text="Here is the mood.")])
    turn = controller.send("Make the asteroids faster and make it feel spooky")

    assert turn.fastpath["remaining"] == ["make it feel spooky"]
    assert "Now do only the rest of what they asked: \u201cmake it feel spooky\u201d" in \
        provider.calls[0][-1].content
    # Gary claimed nothing and changed nothing: his words stand, after the recipe's.
    assert "ASTEROID_SPEED" in turn.text and turn.text.endswith("\n\nHere is the mood.")


def test_a_recipe_change_never_covers_a_claim_gary_did_not_make(project) -> None:
    _dodging_game(project)
    scorer = by_part({"faster": describe("games", "change_thing_speed")},
                     slots={"faster or slower": "faster"})
    claim = Reply(text="I added spooky fog.")
    controller, _ = controller_for(project, scorer, [claim, claim, Reply(text="")])
    turn = controller.send("Make the asteroids faster and make it feel spooky")
    assert "spooky fog" not in turn.text
    assert "I haven't done the rest yet (\u201cmake it feel spooky\u201d)" in turn.text
    assert "ASTEROID_SPEED" in project.entrypoint_path.read_text()   # the part made stays


def test_a_whole_game_recipe_is_never_one_part_of_a_message(project) -> None:
    """Measured on the label sets: "add some walls i have to get around" was read as
    "make a dodging game" at 1.00."""
    scorer = by_part({"walls": describe("games", "make_avoid_game"),
                      "name": describe("games", "set_title")})
    controller, _ = controller_for(project, scorer, [Reply(text="Walls next.")])
    turn = controller.send("add some walls i have to get around and change the name to "
                           "Maze Runner")
    parts = turn.fastpath["parts"]
    assert parts[0].get("recipe") is None and parts[1]["recipe"] == "game.set_title"
    assert turn.fastpath["remaining"] == ["add some walls i have to get around"]
    assert "Maze Runner" in project.entrypoint_path.read_text()
    assert "ASTEROID" not in project.entrypoint_path.read_text()


def test_several_requests_none_of_them_a_recipe_go_to_gary_whole(project) -> None:
    controller, provider = controller_for(project, by_part({}), [Reply(text="Sure.")])
    turn = controller.send("make it feel spooky and add some mysterious music")
    assert turn.fastpath["route"] == NORMAL and turn.text == "Sure."
    assert provider.calls[0][-1].content == "make it feel spooky and add some mysterious music"


# -- a picture, described in the child's own words -------------------------------------

def test_a_picture_is_the_players_look_whichever_way_the_child_says_it() -> None:
    """With a picture attached, "use a picture for the player" and "make the player a
    different shape or character" are the same capability (measured: "use this as my
    eagle" went to the second at 1.00, and then to Gary)."""
    look = describe("games", "change_player_look")
    decision = FastPathRouter().decide("games", "use this as my eagle", FakeScorer(look, "no"),
                                       attached_image=True)
    assert decision.route == RECIPE and decision.recipe.id == "game.replace_player_sprite"
    # Without the picture, the player's look is still Gary's.
    assert FastPathRouter().decide("games", "use this as my eagle",
                                   FakeScorer(look, "no")).route != RECIPE


def test_a_whole_game_can_start_a_message_that_goes_on(project) -> None:
    scorer = by_part({"game": describe("games", "make_avoid_game"),
                      "score": describe("games", "add_score")},
                     slots={"score go up": "it is just a score shown on screen; they did "
                                           "not say how it goes up"})
    controller, provider = controller_for(project, scorer)
    turn = controller.send("make a game where you dodge asteroids and add a score")
    assert [p.get("recipe") for p in turn.fastpath["parts"]] == [
        "game.make_avoid_game", "game.add_score"]
    assert provider.calls == []



# -- what Gary is given when he writes it himself (pre-13) ------------------------------

def test_gary_gets_the_project_and_how_it_is_checked_for_a_creative_request(project) -> None:
    controller, provider = controller_for(project, FakeScorer(), [Reply(text="Spooky.")])
    turn = controller.send("make it feel spooky")
    assert turn.fastpath["route"] == NORMAL and turn.fastpath["context"] == "facts"
    assert "WHERE THINGS ARE IN src/game.py RIGHT NOW" in provider.system_prompt
    assert "HOW IT WILL BE CHECKED" in provider.system_prompt
    assert "A PATTERN" not in provider.system_prompt      # nothing forced onto a mood


def test_a_likely_recipe_the_gate_stopped_is_given_as_a_pattern(project) -> None:
    ball = describe("games", "add_moving_thing")
    controller, provider = controller_for(project, FakeScorer(ball, "no"),
                                          [Reply(text="Swooping.")])
    turn = controller.send("make the eagle swoop down and grab things")
    assert turn.fastpath["context"] == "facts+game.add_moving_thing"
    assert "only if it fits what they asked" in provider.system_prompt
    # Phase 13C: in a project that has game_object, a thing to see is made with it.
    assert "Call game_object for it" in provider.system_prompt
    assert "three pieces in three places" not in provider.system_prompt.split(
        "A PATTERN THIS PROJECT CAN USE")[1]


def test_a_project_without_game_object_keeps_the_drawing_pattern() -> None:
    """Blank has no game_object: its games are still guided to write the code."""
    from opennest.fastpath.registry import RecipeRegistry, guide_for
    from opennest.projects.profiles import load_profiles

    recipe = RecipeRegistry().for_profile("games").for_intent("add_moving_thing")
    blank = next(p for p in load_profiles() if p.id == "blank")
    assert "three pieces in three places" in guide_for(recipe, blank.tools)
    assert "Call game_object" in guide_for(recipe, ("game_object",))


def test_a_veto_gives_no_pattern(tmp_path) -> None:
    project = create_project("Weather", "research", root=tmp_path)
    (project.directory / "data").mkdir(exist_ok=True)
    (project.directory / "data/w.csv").write_text("day,wind\n1,5\n2,9\n")
    scorer = FakeScorer(describe("research", "biggest_change"), YES)
    controller, provider = controller_for(project, scorer, [Reply(text="Day 2.")],
                                          playtest_result=None)
    turn = controller.send("find the windiest day")
    assert turn.fastpath["context"] == "facts"
    assert "last value minus the first" not in provider.system_prompt


def test_a_message_that_only_continues_the_last_is_read_as_its_own_request() -> None:
    """Measured: "and make the background a sunset orange", with the message before it
    shown, was "several changes"; without the leading "and", the colour recipe at 1.00."""
    scorer = FakeScorer(describe("website", "change_colours"), YES)
    FastPathRouter().decide("website", "and make the background orange", scorer,
                            previous="can the bottom say made by maya")
    assert scorer.calls[0][1].endswith("Message: make the background orange")
    scorer = FakeScorer(describe("website", "change_colours"), YES)
    FastPathRouter().decide("website", "and then make it orange", scorer)
    assert scorer.calls[0][1].endswith("Message: and then make it orange")


def test_a_picture_message_is_not_read_through_the_one_before_it() -> None:
    scorer = FakeScorer(describe("games", "change_player_look"), "no")
    FastPathRouter().decide("games", "use this as my eagle", scorer, attached_image=True,
                            previous="i want a game where i'm flying around")
    assert all("Their message before this one" not in user for _, user in scorer.calls)


def test_a_whole_game_must_be_asked_for_in_this_message() -> None:
    """Measured: "make this the player" after "i want a game where..." was read as a
    whole new game at 1.00, and the word "game" was only in the message before."""
    avoid = RecipeRegistry().for_profile("games").for_intent("make_avoid_game")
    assert not avoid.mentioned("make this the player", "i want a game where i fly")
    assert avoid.mentioned("make a game where you dodge cars")
    biggest = RecipeRegistry().for_profile("research").for_intent("biggest_change")
    assert biggest.mentioned("show me that on a chart", "which plant grew the most?")


def test_a_reply_starts_with_a_capital_whatever_its_first_value_is(tmp_path) -> None:
    project = create_project("Site", "website", root=tmp_path)
    recipe = RecipeRegistry().for_profile("website").for_intent("change_colours")
    change = website.set_colour(Context(project, website.facts(project),
                                        "make the background orange", recipe.params))
    from opennest.fastpath.verifier import Verification

    for n in range(len(recipe.report)):
        said = FastPathRouter._report(
            RecipeRegistry().for_profile("website").for_intent("change_colours"), website,
            change, Verification(checks=[]), "build", project=project,
            before={"x": str(n)})
        assert said[0].isupper(), said


def test_a_look_change_names_only_what_changed(project) -> None:
    _dodging_game(project)
    change = games.thing_look(Context(project, games.facts(project),
                                      "make the asteroids bigger", {}))
    assert change.values["changed"] == "ASTEROID_SIZE" and change.values["were"] == "is"
    both = games.thing_look(Context(project, games.facts(project),
                                    "make the asteroids red and bigger", {}))
    assert both.values["changed"] == "ASTEROID_COLOUR and ASTEROID_SIZE"


def test_faster_and_slower_at_once_is_not_one_direction(project) -> None:
    _dodging_game(project)
    recipe = RecipeRegistry().for_profile("games").for_intent("change_thing_speed")
    with pytest.raises(NotApplicable, match="faster and slower"):
        games.set_number(Context(project, games.facts(project),
                                 "Make the asteroids speed up and slow down without warning",
                                 recipe.params, choose=chosen("up")))
