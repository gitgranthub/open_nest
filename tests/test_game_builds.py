"""The game builds pass: a 3D game, the idea cards, and which model builds a game.

The owner's test05 (2026-10-04, Gary Fast): "create a simple, block 3D game. Where the
world is made by 1 meter square cubes." -- and three turns later one rectangle the size
of the window, because a first-person renderer is more than a small model can write and
Open Nest's own guidance asked for "the closest 2D version". ``benchmarks/game_builds``
put eight builds to both local models (SPIKES.md section 33). These tests pin what came
of it: a 3D game begins from the 3D Block World starter (never over the child's work),
the 2D layer and the Fast Path step aside in one, Gary is told the world's facts and how
to change it, and the Platform Game card is no longer built as a dodging game.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent import evidence  # noqa: E402
from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.provider import Reply, ToolCall  # noqa: E402
from opennest.execution import playtest  # noqa: E402
from opennest.fastpath.registry import RecipeRegistry  # noqa: E402
from opennest.graphics import block_world  # noqa: E402
from opennest.projects import starters  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from tests.conftest import ScriptedProvider  # noqa: E402

#: The owner's own first message in test05, typos and all.
TEST05 = "create a simple, block 3D game. Where the world is made by 1 meter square cubes."


def kit_source() -> str:
    kit = starters.get_starter(block_world.STARTER_ID)
    return (kit.directory / kit.entry_point).read_text(encoding="utf-8")


def make(project, replies, fastpath=None):
    provider = ScriptedProvider(replies)
    controller = AgentController(project, provider, Toolbox(project), fastpath=fastpath)
    return controller, provider


def offered_names(provider) -> set[str]:
    return {tool["function"]["name"] if "function" in tool else tool.get("name")
            for tools in provider.tools_offered for tool in tools}


class RecordingFastPath:
    """Stands in for the Fast Path and records whether it was asked anything."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.asked.append(name)
            raise AssertionError(f"the Fast Path was consulted ({name})")
        return record


# ------------------------------------------------------------------ the starter

def test_games_offer_the_block_world_as_a_way_to_start() -> None:
    from opennest.projects.profiles import get_profile

    games = get_profile("games")
    offered = [kit.id for kit in starters.starters_for(games)]
    assert offered == ["pygame_basic", block_world.STARTER_ID]
    # The Basic Game is still what an ordinary new game starts from.
    assert starters.default_starter(games).id == "pygame_basic"
    assert block_world.offered(games)


def test_the_block_world_is_recognised_from_its_code() -> None:
    assert block_world.is_block_world(kit_source())
    basic = starters.get_starter("pygame_basic")
    assert not block_world.is_block_world(
        (basic.directory / basic.entry_point).read_text(encoding="utf-8"))
    compile(kit_source(), "game.py", "exec")


@pytest.mark.parametrize("sky,ground", [("night", "moon"), ("space", "snow"),
                                        ("sunset", "sand"), ("(200, 120, 60)", "(1, 2, 3)")])
def test_every_sky_and_ground_the_game_offers_plays(tmp_path, sky, ground) -> None:
    project = create_project("Blocks", "games", root=tmp_path,
                             starter_id=block_world.STARTER_ID)
    source = project.entrypoint_path.read_text(encoding="utf-8")
    source = source.replace('SKY = "day"', f"SKY = {sky if sky[0] == '(' else repr(sky)}")
    source = source.replace('GROUND = "grass"',
                            f"GROUND = {ground if ground[0] == '(' else repr(ground)}")
    project.entrypoint_path.write_text(source, encoding="utf-8")
    result = playtest.run(project.directory, project.profile.run_command)
    assert result.verdict == playtest.PASSED, result.error


def test_a_flat_tile_game_with_a_world_map_is_not_taken_for_3d() -> None:
    tiles = ('WORLD = [\n    "#####",\n    "#   #",\n]\nBLOCKS = {"#": (90, 90, 90)}\n'
             "import pygame\n")
    assert not block_world.is_block_world(tiles)


def test_the_block_world_really_plays(tmp_path) -> None:
    """Run headless under the real harness and sandbox, as after every change."""
    project = create_project("Blocks", "games", root=tmp_path,
                             starter_id=block_world.STARTER_ID)
    result = playtest.run(project.directory, project.profile.run_command)
    assert result.verdict == playtest.PASSED, result.error
    # W A S D and the arrows turn and walk: the picture changes for each.
    assert {"wasd", "left", "right", "up"} <= set(result.responded_to)
    assert not result.moved_by_itself


@pytest.mark.parametrize("text,asks", [
    (TEST05, True),
    ("make a 3D game where I walk around in space in first person", True),
    ("can it be 3-d", True),
    ("a minecraft kind of game", True),
    ("I want a three dimensional world", True),
    ("make a block world I can walk in", True),
    # The owner's test04: a first-person shooter of their own pictures, built in 2D.
    ("Let's make this a game in the woods at night. A first person shooter.", False),
    ("give me 3 lives", False),
    ("add 3 dogs", False),
])
def test_what_counts_as_asking_for_3d(text, asks) -> None:
    assert bool(block_world.ASKS_FOR_3D.search(text)) is asks


# ------------------------------------------------------- starting a 3D game

def test_the_owners_test05_gets_a_3d_world(project) -> None:
    """The Basic Game, untouched, and a 3D game asked for: the block world instead."""
    fastpath = RecordingFastPath()
    controller, provider = make(project, [Reply(text="Walk with W A S D.")],
                                fastpath=fastpath)
    turn = controller.send(TEST05)

    assert project.entrypoint_path.read_text(encoding="utf-8") == kit_source()
    assert project.manifest.starter_id == block_world.STARTER_ID
    assert turn.block_world_started and turn.scaffolded == ("src/game.py",)
    assert turn.text.startswith("You asked for a 3D game, so I started it as the 3D Block "
                                "World")
    # Not built by a recipe, and not a scene of shapes.
    assert fastpath.asked == []
    assert "game_object" not in offered_names(provider)
    assert "edit_file" in offered_names(provider)
    # Gary is told what the world is, beside the message, and what is in it.
    sent = provider.calls[0][-1].content
    assert "this game is a 3D Block World" in sent and "WORLD is the map" in sent
    assert "it has just been set up as the 3D Block World" in sent
    assert "closest 2D version" not in sent
    assert "Blocks in the world:" in provider.system_prompt
    assert "there are 3 to find" in provider.system_prompt


def test_the_turn_it_is_set_up_is_never_planned_as_unbuilt(project) -> None:
    """Measured: Gary Fast's own extra edits were refused, and Open Nest's fallback said
    "I haven't built any of that yet" and offered a plan, under "I started it as the 3D
    Block World"."""
    wrong = ToolCall(name="edit_file", arguments={
        "path": "src/game.py", "old_text": "WORLD = [\n    \"# # # #\",", "new_text": "x"})
    controller, _ = make(project, [Reply(tool_calls=[wrong]) for _ in range(6)]
                         + [Reply(text="1. Add blocks\n2. Add lighting\n3. Add a camera")])
    turn = controller.send("make a 3D block world game")
    assert turn.block_world_started and not turn.reduced
    assert "I haven't built any of that yet" not in turn.text
    assert "one step at a time" not in turn.text
    assert turn.text.startswith("You asked for a 3D game")
    assert block_world.READY in turn.text


def test_asked_for_what_the_world_already_has_it_is_said_never_planned(tmp_path) -> None:
    """Measured: told of "a sky and ground ... W, S, A and D ... a simple pair of hands",
    all already there, Gary Fast's refused edits became a plan to add them."""
    project = create_project("Blocks", "games", root=tmp_path,
                             starter_id=block_world.STARTER_ID)
    wrong = ToolCall(name="edit_file", arguments={
        "path": "src/game.py", "old_text": "SKY = (1, 2, 3)", "new_text": "x"})
    controller, _ = make(project, [Reply(tool_calls=[wrong]) for _ in range(6)]
                         + [Reply(text="1. Add a sky\n2. Add W A S D\n3. Add hands")])
    turn = controller.send("we should see a sky and ground and a simple pair of hands")
    assert not turn.reduced and "one step at a time" not in turn.text
    assert ("Right now the 3D world has a day sky, grass ground, blocks of stone, wood and "
            "grass to walk among, 3 gold blocks to find, two hands and W A S D to walk and "
            "turn.") in turn.text


def test_an_empty_game_project_starts_from_the_block_world(tmp_path) -> None:
    empty = create_project("Space Walk", "games", starter_id=None, root=tmp_path)
    controller, _ = make(empty, [Reply(text="Walk with W A S D.")])
    turn = controller.send("make a 3D game where I walk around in space")
    assert empty.entrypoint_path.read_text(encoding="utf-8") == kit_source()
    assert turn.block_world_started
    assert turn.text.startswith("There was nothing in the project yet, so I started it "
                                "from the 3D Block World")


def test_a_blank_project_asked_for_a_3d_game_gets_the_block_world(tmp_path) -> None:
    blank = create_project("Blank Blocks", "blank", root=tmp_path)
    controller, provider = make(blank, [Reply(text="Walk with W A S D.")])
    turn = controller.send("make me a 3D game with blocks")
    assert blank.entrypoint_path.name == "main.py"
    assert blank.entrypoint_path.read_text(encoding="utf-8") == kit_source()
    assert turn.text.startswith("There was nothing in the project yet, so I started it as "
                                "a 3D game")
    assert "game_object" not in offered_names(provider)


def test_a_game_the_child_has_changed_is_never_replaced(project) -> None:
    source = project.entrypoint_path.read_text(encoding="utf-8").replace(
        "PLAYER_SPEED = 5", "PLAYER_SPEED = 8")
    project.entrypoint_path.write_text(source, encoding="utf-8")
    controller, _ = make(project, [Reply(text="I kept it flat."),
                                   Reply(text="Done."), Reply(text="Done.")])
    turn = controller.send("make it a 3D game")
    assert project.entrypoint_path.read_text(encoding="utf-8") == source
    assert not turn.block_world_started
    # Told once where a 3D game is -- not on every message after.
    assert "choose 3D Block World under How it starts" in turn.text
    again = controller.send("make it a 3D game please")
    assert "How it starts" not in again.text


def test_a_question_about_3d_changes_nothing(project) -> None:
    # ("can you make ..." is a polite request by is_question's rule, so it is built for.)
    before = project.entrypoint_path.read_text(encoding="utf-8")
    controller, _ = make(project, [Reply(text="A 3D game is seen through your eyes.")])
    controller.send("how do 3D games work?")
    assert project.entrypoint_path.read_text(encoding="utf-8") == before


def test_a_change_to_the_block_world_is_an_edit_to_its_names(tmp_path) -> None:
    project = create_project("Blocks", "games", root=tmp_path,
                             starter_id=block_world.STARTER_ID)
    edit = ToolCall(name="edit_file", arguments={
        "path": "src/game.py", "old_text": 'SKY = "day"', "new_text": 'SKY = "night"'})
    controller, provider = make(project, [Reply(tool_calls=[edit]),
                                          Reply(text="There are stars in the sky now.")])
    turn = controller.send("make it night with stars in the sky")
    assert 'SKY = "night"' in project.entrypoint_path.read_text(encoding="utf-8")
    assert "game_object" not in offered_names(provider)
    assert "this game is a 3D Block World" in provider.calls[0][-1].content
    assert "it has just been set up" not in provider.calls[0][-1].content
    assert "stars are in the sky" in provider.system_prompt
    assert "There are stars in the sky now." in turn.text


def test_the_block_worlds_facts_are_its_own_not_a_2d_games(tmp_path) -> None:
    project = create_project("Blocks", "games", root=tmp_path,
                             starter_id=block_world.STARTER_ID)
    lines = "\n".join(evidence._game_lines(project, kit_source(),
                                           asked={"gold", "block", "sky", "world"}))
    assert "3D Block World" in lines and "Blocks in the world:" in lines
    assert '"*" gold, yellow, 1 high' in lines
    assert "W (hold down)" in lines                       # the controls, read from the code
    # The 2D readings would say its speeds are things and its blocks are not drawn.
    assert "nothing draws it" not in lines
    assert "Other things in the game" not in lines


def test_toolbox_offers_game_object_only_to_a_2d_game(project, tmp_path) -> None:
    assert "game_object" in Toolbox(project).allowed
    world = create_project("Blocks", "games", root=tmp_path / "w",
                           starter_id=block_world.STARTER_ID)
    assert "game_object" not in Toolbox(world).allowed


# ------------------------------------------------------------- the idea cards

@pytest.mark.parametrize("card", ["Make a platform game", "Make a racing game",
                                  "Make a maze", "Make a quiz game"])
def test_an_idea_card_for_another_game_is_not_a_dodging_or_catching_game(card) -> None:
    """Measured: on Gary Fast, "Make a platform game" was built as five falling asteroids."""
    games = RecipeRegistry().for_profile("games")
    for intent in ("make_avoid_game", "make_catch_game"):
        assert not games.for_intent(intent).mentioned(card)


@pytest.mark.parametrize("ask", [
    "Make a game where a spaceship moves around and avoids asteroids.",
    "Make a game where you catch falling blocks.",
    "create a simple spaceship game",
])
def test_the_labelled_whole_game_requests_still_reach_their_recipes(ask) -> None:
    games = RecipeRegistry().for_profile("games")
    assert any(games.for_intent(intent).mentioned(ask)
               for intent in ("make_avoid_game", "make_catch_game"))


# ------------------------------------------------------- the 2D scene layer

@pytest.mark.parametrize("shape,at,box", [
    # Gary Smart's own calls: drawn at y 600 and 800 before, off the screen.
    ({"rect": [0, 300, 640, 100], "color": "dark gray", "round": 10}, (0, 300), (640, 100)),
    ({"rect": [0, 400, 20, 100], "color": "green", "round": 5}, (0, 400), (20, 100)),
])
def test_shapes_given_as_screen_places_without_a_size_are_moved_into_their_box(
        shape, at, box) -> None:
    from opennest.graphics.looks import shapes_look

    notes: list[str] = []
    look = shapes_look([shape], None, at, notes)
    assert look.box == box and look.shapes[0].startswith("Rect(0, 0, ")
    assert any("places on the screen" in note for note in notes)


def test_shapes_inside_their_own_box_are_left_where_they_are() -> None:
    from opennest.graphics.looks import shapes_look

    look = shapes_look([{"rect": [0, 300, 640, 100], "color": "red"}], None, (0, 0), [])
    assert look.box == (640, 400) and look.shapes[0].startswith("Rect(0, 300, ")
    look = shapes_look([{"rect": [0, 0, 40, 40], "color": "red"}], None, (100, 200), [])
    assert look.box == (40, 40)


# ------------------------------------------------- Open Nest's words, said by Gary

#: Gary Fast's whole reply to "add coins to collect and a score" on the game builds: the
#: plan Open Nest had written the turn before, word for word.
PARROTED = ("I haven't changed anything yet. Here's a way to build it, one step at a time:"
            "\n\n1. Add scrolling trees and ground as you run\n2. Make the trees and ground "
            "move smoothly with your speed\n3. Adjust the scroll speed so it feels natural "
            "when you run fast\n\nWant me to start with the first one?")


def test_open_nests_own_plan_said_by_gary_is_not_shown_as_his(project) -> None:
    controller, _ = make(project, [Reply(text=PARROTED) for _ in range(4)])
    turn = controller.send("add coins to collect and a score")
    assert "scrolling trees" not in turn.text
    assert "one step at a time" not in turn.text
    assert "2.\n3." not in turn.text


def test_a_change_said_as_the_change_made_is_checked(project) -> None:
    """Gary Smart, in a turn that changed nothing: "The only change made was removing the
    orange clock." Caught like "I removed the orange clock" always was."""
    controller, provider = make(project, [
        Reply(text="The only change made was removing the orange clock."),
        Reply(text="I haven't changed anything."),
    ])
    turn = controller.send("the orange clock should not be there")
    assert "change made was removing" not in turn.text
    assert len(provider.calls) == 2                       # it was asked again


def test_a_plan_never_offers_the_same_step_twice(project) -> None:
    """Measured: "add mountains far away behind everything", planned as itself x3."""
    controller, _ = make(project, [])
    controller.provider.replies = [Reply(text=(
        "1. Add mountains far away behind everything\n2. Add mountains far away behind "
        "everything.\n3. add mountains far away behind everything"))]
    assert controller._plan_steps("add mountains far away behind everything") == [
        "Add mountains far away behind everything"]


# ------------------------------------------- which model a game is begun with

def machine_with(memory_gb: float):
    from opennest.models.machine import MachineProfile

    return MachineProfile(platform="macOS", architecture="arm64", memory_gb=memory_gb,
                          free_disk_gb=200.0, mlx_available=True)


@pytest.fixture
def installed(monkeypatch):
    """Which local models count as downloaded, without looking at a cache."""
    from opennest.ai import router

    present = {"qwen3-vl-4b-instruct"}
    monkeypatch.setattr(router, "_installed", lambda entry: entry.info.id in present)
    return present


def test_gary_fast_is_marked_as_struggling_with_games_and_nothing_else() -> None:
    from opennest.ai.router import get_entry, load_catalogue

    assert get_entry("qwen3-vl-4b-instruct").struggles_with == ("games",)
    assert [entry.info.id for entry in load_catalogue() if entry.struggles_with] == [
        "qwen3-vl-4b-instruct"]


def test_a_game_on_gary_fast_is_warned_and_offered_gary_smart(installed) -> None:
    from opennest.ai.router import model_advice
    from opennest.projects.profiles import get_profile

    installed.add("qwen3-vl-8b-instruct")
    advice = model_advice("qwen3-vl-4b-instruct", get_profile("games"), machine_with(16))
    assert advice.headline == "Gary Fast struggles to build a game that works."
    assert "use at least Gary Smart or a cloud model" in advice.explanation
    assert advice.choices == (("qwen3-vl-8b-instruct", "Gary Smart"),)
    assert advice.parent_steps == (
        "A parent can turn on Cloud AI and add a key in Settings.",)


def test_only_what_this_mac_can_use_is_offered(installed, configured_credentials) -> None:
    from opennest.ai.router import model_advice
    from opennest.projects.profiles import get_profile

    games = get_profile("games")
    # 16 GB, Gary Smart not downloaded: a step for a parent, not a button.
    advice = model_advice("qwen3-vl-4b-instruct", games, machine_with(16))
    assert advice.choices == ()
    assert "A parent can download Gary Smart in Settings." in advice.parent_steps
    # 8 GB: Gary Smart cannot run here at all, and that is said as the reason.
    advice = model_advice("qwen3-vl-4b-instruct", games, machine_with(8))
    assert advice.choices == ()
    assert any(step.startswith("Gary Smart cannot run on this Mac: it needs about 16 GB")
               for step in advice.parent_steps)
    # Cloud on, with a key: the cloud models a key reaches are the way forward.
    advice = model_advice("qwen3-vl-4b-instruct", games, machine_with(8), allow_cloud=True,
                          credentials=configured_credentials)
    assert advice.choices and all(model_id in ("claude-sonnet", "claude-haiku", "openai-gpt")
                                  for model_id, _ in advice.choices)


def test_nothing_is_said_where_nothing_was_measured(installed) -> None:
    from opennest.ai.router import model_advice
    from opennest.projects.profiles import get_profile

    mac = machine_with(16)
    assert model_advice("qwen3-vl-8b-instruct", get_profile("games"), mac) is None
    assert model_advice("qwen3-vl-4b-instruct", get_profile("website"), mac) is None
    assert model_advice("no-such-model", get_profile("games"), mac) is None


@pytest.fixture
def window(qt_app, monkeypatch, configured_credentials, tmp_path):
    """A MainWindow that loads no model, with the dialogs answered by the test."""
    from opennest.projects.manager import create_project as real_create
    from opennest.ui import main_window as module
    from opennest.ui.new_project import NewProject

    local = ScriptedProvider([Reply(text="Done.")])
    local.info = local.info.__class__(id="qwen3-vl-4b-instruct", name="Gary Fast",
                                      provider="mlx")
    monkeypatch.setattr(module, "run_in_thread", lambda *a, **k: None)
    monkeypatch.setattr(module, "build_provider", lambda model_id, **kw: local)
    monkeypatch.setattr(module.new_project, "ask", lambda parent, profile: NewProject(
        name="My Project", starter_idea=None, starter_id=None))
    monkeypatch.setattr(module, "create_project", lambda name, profile_id, **kw: real_create(
        name, profile_id, root=tmp_path, **kw))
    win = module.MainWindow(credentials=configured_credentials)
    win._provider = local
    win._machine = machine_with(16)
    opened, switched = [], []
    monkeypatch.setattr(win, "_open_project", lambda project, **kw: (
        opened.append(project), setattr(win, "_workbench", object())))
    monkeypatch.setattr(win, "_switch_model", switched.append)
    return win, opened, switched


@pytest.fixture(scope="session")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_a_new_game_on_gary_fast_shows_the_warning_and_switches(window, monkeypatch,
                                                                installed) -> None:
    from opennest.projects.profiles import get_profile
    from opennest.ui import consent

    win, opened, switched = window
    installed.add("qwen3-vl-8b-instruct")
    shown = []
    monkeypatch.setattr(consent, "advise_model", lambda parent, advice: (
        shown.append(advice), "qwen3-vl-8b-instruct")[1])
    win._new_project(get_profile("games"))
    assert [advice.headline for advice in shown] == [
        "Gary Fast struggles to build a game that works."]
    assert len(opened) == 1 and switched == ["qwen3-vl-8b-instruct"]


def test_keeping_gary_fast_still_makes_the_game(window, monkeypatch, installed) -> None:
    from opennest.projects.profiles import get_profile
    from opennest.ui import consent

    win, opened, switched = window
    monkeypatch.setattr(consent, "advise_model", lambda parent, advice: None)
    win._new_project(get_profile("games"))
    assert len(opened) == 1 and switched == []


def test_other_kinds_of_project_are_not_warned(window, monkeypatch, installed) -> None:
    from opennest.projects.profiles import get_profile
    from opennest.ui import consent

    win, opened, _ = window
    monkeypatch.setattr(consent, "advise_model", lambda parent, advice: (
        _ for _ in ()).throw(AssertionError("warned about a website")))
    win._new_project(get_profile("website"))
    assert len(opened) == 1


# ------------------------------------------------- a new game, written whole

#: A small catch game in the shape the whole-game prompt asks for: the numbers at the top,
#: its things as rects, one game loop at the top level with a fill and a flip. It passes
#: the real playtest.
CATCH_GAME = '''"""A cat catches falling pizzas."""

import random

import pygame

WIDTH, HEIGHT = 640, 480
CAT_SPEED = 6
PIZZA_SPEED = 4

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
clock = pygame.time.Clock()
font = pygame.font.Font(None, 36)
cat = pygame.Rect(300, 420, 60, 40)
pizza = pygame.Rect(random.randint(0, WIDTH - 30), 0, 30, 30)
score = 0

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False
    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT]:
        cat.x -= CAT_SPEED
    if keys[pygame.K_RIGHT]:
        cat.x += CAT_SPEED
    cat.clamp_ip(screen.get_rect())
    pizza.y += PIZZA_SPEED
    if pizza.colliderect(cat):
        score += 1
        pizza.topleft = (random.randint(0, WIDTH - 30), 0)
    elif pizza.top > HEIGHT:
        pizza.topleft = (random.randint(0, WIDTH - 30), 0)
    screen.fill((20, 20, 40))
    pygame.draw.rect(screen, (240, 160, 60), cat)
    pygame.draw.circle(screen, (230, 80, 50), pizza.center, 15)
    screen.blit(font.render(f"Score: {score}", True, (255, 255, 255)), (10, 10))
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
'''

#: The same game, crashing on its first frame.
BROKEN_GAME = CATCH_GAME.replace("pizza.y += PIZZA_SPEED", "pizza.y += PIZZA_SPED")
#: The same game, in a function: it runs, but nothing could add a picture to it later.
IN_A_FUNCTION = "def main():\n" + "\n".join(
    "    " + line if line else line for line in CATCH_GAME.split("\n")) + "\nmain()\n"


def as_model(provider, model_id: str):
    from opennest.ai.provider import ModelInfo

    provider.info = ModelInfo(id=model_id, name=model_id, provider="mlx")
    return provider


def block(code: str) -> Reply:
    return Reply(text=f"```python\n{code}```")


def test_a_new_game_is_written_whole_tested_and_kept(project) -> None:
    """Gary Smart, on the untouched Basic Game: the measured way it builds a game."""
    controller, provider = make(project, [block(CATCH_GAME),
                                          Reply(text="A cat catches pizzas. Use the arrows.")])
    as_model(provider, "qwen3-vl-8b-instruct")
    turn = controller.send("Make a game where a cat catches falling pizzas.")

    assert project.entrypoint_path.read_text(encoding="utf-8") == CATCH_GAME
    assert turn.whole_game == "written"
    assert turn.tool_results[0][0] == "write_file"
    assert turn.tool_results[0][1].changed_files == ("src/game.py",)
    assert turn.playtests and turn.playtests[0].verdict == playtest.PASSED
    # Asked with the whole-game prompt, no tools; then Gary, told it is written, replies.
    assert provider.tools_offered[0] == []
    assert "Their idea, in their own words" in provider.calls[0][-1].content
    told = provider.calls[1]
    assert any("you have just written this whole game" in (m.content or "") for m in told)
    assert any(m.tool_calls and m.tool_calls[0].name == "write_file" for m in told)
    assert "A cat catches pizzas." in turn.text


def test_a_game_that_keeps_failing_its_test_leaves_the_starter(project) -> None:
    before = project.entrypoint_path.read_text(encoding="utf-8")
    controller, provider = make(project, [block(BROKEN_GAME) for _ in range(3)]
                                + [Reply(text="Let me try a smaller change.")])
    as_model(provider, "qwen3-vl-8b-instruct")
    turn = controller.send("Make a game where a cat catches falling pizzas.")
    assert project.entrypoint_path.read_text(encoding="utf-8") == before
    assert turn.whole_game == "kept the starter: crashed"
    assert not (project.directory / "src" / "scene.py").exists()      # nothing left over
    # Each failure went back with the test's own words.
    assert "It stopped with an error" in provider.calls[1][-1].content
    assert not any(name == "write_file" for name, _ in turn.tool_results)


def test_a_repair_that_fixes_it_is_kept(project) -> None:
    controller, provider = make(project, [block(BROKEN_GAME), block(CATCH_GAME),
                                          Reply(text="Catch the pizzas.")])
    as_model(provider, "qwen3-vl-8b-instruct")
    turn = controller.send("Make a game where a cat catches falling pizzas.")
    assert turn.whole_game == "written"
    assert "after 1 repair" in turn.tool_results[0][1].content


def test_a_game_hidden_in_a_function_is_asked_for_again(project) -> None:
    controller, provider = make(project, [block(IN_A_FUNCTION), block(CATCH_GAME),
                                          Reply(text="Catch the pizzas.")])
    as_model(provider, "qwen3-vl-8b-instruct")
    turn = controller.send("Make a game where a cat catches falling pizzas.")
    assert turn.whole_game == "written"
    assert "game loop at the top level" in provider.calls[1][-1].content


@pytest.mark.parametrize("model,text,changed", [
    # Gary Fast: measured one working game in five written this way.
    ("qwen3-vl-4b-instruct", "Make a game where a cat catches falling pizzas.", False),
    # A change to the game is not a new game.
    ("qwen3-vl-8b-instruct", "add asteroids to the game", False),
    # A maze is the scene layer's layout, and 3D is the block world.
    ("qwen3-vl-8b-instruct", "Make a maze game to find the monster", False),
    # The game has been changed: never written over.
    ("qwen3-vl-8b-instruct", "Make a game where a cat catches falling pizzas.", True),
])
def test_a_new_game_is_written_whole_only_when_nothing_is_lost(project, model, text,
                                                                changed) -> None:
    if changed:
        source = project.entrypoint_path.read_text(encoding="utf-8").replace(
            "PLAYER_SPEED = 5", "PLAYER_SPEED = 7")
        project.entrypoint_path.write_text(source, encoding="utf-8")
    before = project.entrypoint_path.read_text(encoding="utf-8")
    controller, provider = make(project, [Reply(text="Here is an idea.")] * 4)
    as_model(provider, model)
    turn = controller.send(text)
    assert turn.whole_game == ""
    assert all("Their idea, in their own words" not in (call[-1].content or "")
               for call in provider.calls)
    assert project.entrypoint_path.read_text(encoding="utf-8") == before


def test_a_blank_project_asked_for_a_game_gets_one_written_and_tested(tmp_path) -> None:
    """Blank has no test after an ordinary change; a game written whole is still tested."""
    blank = create_project("Blank Cat", "blank", root=tmp_path)
    controller, provider = make(blank, [block(CATCH_GAME), Reply(text="Catch the pizzas.")])
    as_model(provider, "qwen3-vl-8b-instruct")
    turn = controller.send("Make a game where a cat catches falling pizzas.")
    assert blank.entrypoint_path.read_text(encoding="utf-8") == CATCH_GAME
    assert turn.whole_game == "written" and turn.playtests[0].verdict == playtest.PASSED


# ------------------------------------------- a game that worked is never left broken

def test_a_change_that_breaks_a_working_game_is_put_back(project) -> None:
    """Measured on the test04 replay after a game was written whole: three turns of
    hand edits left a game that no longer ran at all."""
    breaks = ToolCall(name="edit_file", arguments={
        "path": "src/game.py", "old_text": "pizza.y += PIZZA_SPEED",
        "new_text": "pizza.y += PIZZA_SPED"})
    still = ToolCall(name="edit_file", arguments={
        "path": "src/game.py", "old_text": "PIZZA_SPEED = 4", "new_text": "PIZZA_SPEED = 5"})
    controller, provider = make(project, [
        block(CATCH_GAME), Reply(text="A cat catches pizzas."),
        Reply(tool_calls=[breaks]), Reply(text="Done."),
        *[Reply(tool_calls=[still]), Reply(text="Fixed.")] * 3,
        Reply(text="Done."), Reply(text="Done."),
    ])
    as_model(provider, "qwen3-vl-8b-instruct")
    controller.send("Make a game where a cat catches falling pizzas.")
    assert project.entrypoint_path.read_text(encoding="utf-8") == CATCH_GAME

    turn = controller.send("make the pizzas fall faster")
    assert turn.playtests and turn.playtests[-1].failed
    assert turn.put_back
    assert project.entrypoint_path.read_text(encoding="utf-8") == CATCH_GAME
    assert turn.text.startswith("That change broke the game: when I tested it, it stopped "
                                "with an error. So I put the game back")
    # Gary is told on the next message, so he does not describe the broken change.
    assert "put back the version from before it" in controller._recent_note


def test_nothing_is_put_back_that_nobody_tested(project) -> None:
    """The Basic Game was never tested this session: a broken change stays, as before,
    with the give-up that offers going back."""
    breaks = ToolCall(name="edit_file", arguments={
        "path": "src/game.py", "old_text": "player.x -= PLAYER_SPEED",
        "new_text": "player.x -= PLAYER_SPED"})
    controller, _ = make(project, [Reply(tool_calls=[breaks]), Reply(text="Done.")]
                         + [Reply(text="I could not fix it.")] * 6)
    turn = controller.send("make the player slower")
    assert not turn.put_back
    assert "PLAYER_SPED" in project.entrypoint_path.read_text(encoding="utf-8")


def test_asked_for_pictures_in_a_game_with_no_scene_gary_is_told_the_tool(project) -> None:
    from PIL import Image

    Image.new("RGBA", (16, 16), (40, 90, 220, 255)).save(
        project.directory / "assets" / "monster.png")
    project.entrypoint_path.write_text(CATCH_GAME, encoding="utf-8")   # no scene in it
    controller, provider = make(project, [Reply(text="Which one?")] * 3)
    controller.send("use my monster picture for the pizza")
    assert "call game_object -- one call for each thing" in provider.calls[0][-1].content


def test_a_game_with_a_scene_is_not_told_again(project) -> None:
    from PIL import Image

    Image.new("RGBA", (16, 16), (40, 90, 220, 255)).save(
        project.directory / "assets" / "monster.png")
    with_scene = CATCH_GAME.replace("import pygame\n", "import pygame\nfrom scene import Scene\n")
    with_scene = with_scene.replace("score = 0\n", "score = 0\nscene = Scene(screen)\n")
    with_scene = with_scene.replace("    screen.fill((20, 20, 40))\n",
                                    "    screen.fill((20, 20, 40))\n    scene.draw()\n")
    project.entrypoint_path.write_text(with_scene, encoding="utf-8")
    controller, provider = make(project, [Reply(text="Which one?")] * 3)
    controller.send("use my monster picture for the pizza")
    assert "call game_object -- one call for each thing" not in provider.calls[0][-1].content
