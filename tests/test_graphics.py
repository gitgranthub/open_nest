"""Phase 13C: the game graphics layer -- the kit a game draws with, and game_object.

Three halves, tested separately and then together:

- ``opennest/graphics/kit/scene.py``, the pygame helper a child's game imports. Tested
  here under SDL's dummy driver, in this process -- the only place in the suite that
  imports pygame directly, because the kit is the one piece of Open Nest that is the
  child's code rather than the application's.
- ``game_object``: what it writes into a game, found and checked with the parser.
- the two together, under the real sandbox and the real headless playtest: a whole scene
  built call by call, run, and the scene's own record of what it drew read back.

The owner's test03 game (SPIKES.md section 28A) is the fixture the refusals are about: an
``eagle.png`` that was a sentence the model had written, loaded inside a ``try`` that drew
a square whenever it failed.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from opennest.agent.tools import Toolbox
from opennest.execution import playtest
from opennest.fastpath.kinds import Context, games
from opennest.graphics import game_object, looks
from opennest.graphics import source as scene_source
from opennest.security.process_sandbox import sandbox_available

REPO = Path(__file__).resolve().parents[1]
EAGLE = REPO / "assets/open_nest_asset_delivery/03_eagle_animation/frames_128/eagle_01.png"
SHEET = REPO / "assets/eagle_cycle_bw.png"
needs_sandbox = pytest.mark.skipif(not sandbox_available(),
                                   reason="the process sandbox cannot be applied here")


@pytest.fixture
def eagle(project):
    """A Games project with a real eagle picture in its assets, as the owner had."""
    (project.directory / "assets").mkdir(exist_ok=True)
    shutil.copy(EAGLE, project.directory / "assets" / "eagle.png")
    return project


def call(project, **arguments):
    """game_object, with its files written the way the Toolbox writes them."""
    outcome = game_object.run(project, arguments)
    for relative, text in outcome.files.items():
        (project.directory / relative).write_text(text, encoding="utf-8")
    return outcome


def game(project) -> str:
    return project.entrypoint_path.read_text(encoding="utf-8")


def near(pixel, rgb, within=6) -> bool:
    """Drawings are smoothed, so a colour comes back within a few steps of itself."""
    return all(abs(a - b) <= within for a, b in zip(tuple(pixel)[:3], rgb))


def keeps_every_line(before: str, after: str) -> bool:
    """``after`` has every line ``before`` had, in the same order."""
    lines = iter(after.split("\n"))
    return all(any(line == other for other in lines) for line in before.split("\n"))


# ============================================================================ the kit


@pytest.fixture(scope="module")
def kit():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    pygame = pytest.importorskip("pygame")
    spec = importlib.util.spec_from_file_location("scene_kit_under_test", looks.KIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pygame.init()
    screen = pygame.display.set_mode((640, 480))
    module.PROJECT = REPO          # pictures are found from the repository in these tests
    return module, pygame, screen


def test_the_kit_imports_nothing_but_pygame_and_the_standard_library() -> None:
    """It goes into the child's project, and has to run wherever the game goes."""
    tree = ast.parse(looks.kit_source())
    imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert imported <= {"pygame", "random", "pathlib"}
    assert looks.kit_version() == 1


def test_colours_by_name_hex_and_numbers(kit) -> None:
    scene, pygame, _ = kit
    assert tuple(scene.colour("red"))[:3] == scene.COLOURS["red"]
    assert tuple(scene.colour("Sky Blue"))[:3] == scene.COLOURS["skyblue"]
    assert tuple(scene.colour("#102030"))[:3] == (16, 32, 48)
    assert tuple(scene.colour((1, 2, 3)))[:3] == (1, 2, 3)
    assert tuple(scene.colour("coral"))[:3] == (255, 127, 80)       # pygame's own names
    with pytest.raises(scene.SceneError):
        scene.colour("darkbrown")


def test_a_picture_keeps_its_shape_and_its_see_through_parts(kit) -> None:
    scene, pygame, _ = kit
    look = scene.Picture(str(EAGLE))
    image = look.image((100, 50))
    assert image.get_size() == (100, 50)
    # Fitted, not stretched: a square picture in a wide box leaves see-through sides.
    assert image.get_at((2, 25)).a == 0
    assert image.get_bounding_rect().width <= 52


def test_a_picture_that_is_not_one_fails_loudly(kit, tmp_path) -> None:
    """test03's eagle.png: a sentence with a picture's name. Never quietly a square."""
    scene, pygame, _ = kit
    fake = tmp_path / "eagle.png"
    fake.write_text("i can't generate images, so i can't add the eagle image.")
    with pytest.raises(scene.SceneError, match="cannot load"):
        scene.Picture(str(fake)).image((40, 40))
    with pytest.raises(scene.SceneError, match="cannot find"):
        scene.Picture(str(tmp_path / "missing.png")).image((40, 40))


def test_a_sprite_sheet_is_cut_into_its_frames(kit) -> None:
    """The brand's twelve-frame wing cycle is six by two: cells nearest to square."""
    scene, pygame, _ = kit
    frames = scene.Animation(str(SHEET), frames=12).pictures()
    assert len(frames) == 12
    assert frames[0].get_size() == (2172 // 6, 724 // 2)


def test_every_ready_made_drawing_draws_something(kit) -> None:
    scene, pygame, _ = kit
    for kind, name in looks.DRAWINGS.items():
        look = getattr(scene, name)()
        size = look.natural_size()
        image = look.image(size)
        assert image.get_size() == tuple(size), kind
        assert image.get_bounding_rect(min_alpha=1).width > size[0] // 3, kind


def test_a_drawing_is_its_shapes_in_its_own_box(kit) -> None:
    scene, pygame, _ = kit
    look = scene.Drawing((40, 20), [scene.Rect(0, 0, 20, 20, "red"),
                                    scene.Circle(30, 10, 5, "blue")])
    image = look.image((80, 40))                 # drawn twice the size
    assert near(image.get_at((10, 20)), scene.COLOURS["red"])
    assert near(image.get_at((60, 20)), scene.COLOURS["blue"])
    assert image.get_at((50, 3)).a == 0


def test_a_row_spreads_across_the_screen_and_things_stand_on_things(kit) -> None:
    scene, pygame, screen = kit
    world = scene.Scene(screen)
    world.add("road", scene.Road(), size=(640, 80), at=(0, 400), layer="scenery")
    trees = world.add("trees", scene.Tree(), size=(50, 80), count=4, on="road")
    world.draw()                                    # standing on something settles here
    assert [t.drawn_rect().bottom for t in trees] == [400] * 4
    lefts = [t.drawn_rect().left for t in trees]
    assert lefts == sorted(lefts) and lefts[0] < 100 and lefts[-1] > 400


def test_a_thing_is_a_rect_so_the_games_own_collisions_still_work(kit) -> None:
    scene, pygame, screen = kit
    world = scene.Scene(screen)
    cars = world.add("cars", scene.Vehicle(), size=(80, 40), at=(0, 200), count=3)
    player = pygame.Rect(0, 0, 20, 20)
    player.center = cars[1].center
    assert player.collidelist(cars) == 1
    assert world.touching(player, "cars") == [cars[1]]


def test_moving_things_come_back_round_only_off_the_side_they_head_for(kit) -> None:
    scene, pygame, screen = kit
    world = scene.Scene(screen)
    car = world.add("car", scene.Vehicle(), size=(80, 40), at=(700, 200), moves=(-5, 0))
    world.update()
    assert car.drawn_rect().left == 695            # still on its way in, not wrapped
    car.x = -200
    world.update()
    assert car.drawn_rect().left >= 600            # gone off the left, back on the right


def test_the_games_own_rect_is_drawn_with_a_look_and_keeps_its_box(kit) -> None:
    """The player: its look is the scene's, its rectangle -- movement, collisions -- the
    game's. The picture follows the rect when the rect changes size."""
    scene, pygame, screen = kit
    world = scene.Scene(screen)
    player = pygame.Rect(100, 100, 40, 40)
    world.add("player", scene.Picture(str(EAGLE)), rect=player, scale=1.5, layer="player")
    assert world._drawn_area(world.entries["player"], player).size == (60, 60)
    player.inflate_ip(20, 20)
    assert world._drawn_area(world.entries["player"], player).size == (90, 90)
    player.x += 30
    world.reset("player")
    assert player.topleft == (100, 100)            # where it was when given to the scene


def test_layers_draw_back_to_front_whatever_order_things_were_added(kit) -> None:
    scene, pygame, screen = kit
    world = scene.Scene(screen)
    world.add("box", scene.Colour("red"), size=(100, 100), at=(0, 0), layer="player")
    world.add("sky", scene.Sky("blue"), size=(640, 480), at=(0, 0), layer="background")
    screen.fill((0, 0, 0))
    world.draw()
    assert near(screen.get_at((50, 50)), scene.COLOURS["red"])


def test_the_scene_reports_what_it_drew_and_what_was_on_screen(kit) -> None:
    scene, pygame, screen = kit
    world = scene.Scene(screen)
    world.add("sun", scene.Star(), size=(30, 30), at=(10, 10))
    world.add("lost", scene.Coin(), size=(30, 30), at=(2000, 10))
    world.draw()
    world.draw()
    report = {item["name"]: item for item in world.report()}
    assert report["sun"]["frames"] == 2 and report["sun"]["on_screen"] == 1
    assert report["lost"]["on_screen"] == 0
    assert report["sun"]["look"] == "star drawing"
    assert world in scene.Scene.all


# ======================================================================= game_object


def test_the_first_call_gives_the_game_its_scene_and_changes_nothing_else(eagle) -> None:
    before = game(eagle)
    outcome = call(eagle, name="road", drawing="road")
    assert outcome.ok, outcome.result
    after = game(eagle)
    compile(after, "game.py", "exec")
    assert "from scene import Road, Scene" in after
    lines = after.split("\n")
    fill = next(i for i, line in enumerate(lines) if "screen.fill(" in line)
    assert lines[fill - 1].strip() == "scene.update()"
    assert lines[fill + 1].strip() == "scene.draw()"
    assert keeps_every_line(before, after)
    assert (eagle.directory / "src/scene.py").read_text() == looks.kit_source()
    assert outcome.result["files_changed"] == ["src/game.py", "src/scene.py"]


def test_my_eagle_picture_becomes_the_player_and_the_square_goes(eagle) -> None:
    """The work order's acceptance example, at the level of the code."""
    outcome = call(eagle, name="player", picture="my eagle picture", size=[72, 72])
    assert outcome.ok, outcome.result
    source = game(eagle)
    assert "pygame.draw.rect(screen, PLAYER_COLOUR, player)" not in source
    assert 'scene.add("player", Picture("assets/eagle.png"), rect=player, scale=1.5' in source
    assert "player.x -= PLAYER_SPEED" in source         # movement untouched
    assert "PLAYER_SIZE = 48" in source                 # 72 drawn over a 48 box
    result = outcome.result
    assert result["picture"] == "assets/eagle.png"
    assert result["drawn_size"] == [72, 72] and result["collision_box"] == [48, 48]
    assert "unchanged" in result["kept"]


def test_a_fake_picture_is_refused_and_nothing_is_written(eagle) -> None:
    fake = eagle.directory / "assets" / "dragon.png"
    fake.write_text("i can't generate images, so i can't add the eagle image.")
    before = game(eagle)
    outcome = game_object.run(eagle, {"name": "player", "picture": "assets/dragon.png"})
    assert not outcome.ok and outcome.reason == "not_a_picture"
    assert outcome.files == {} and game(eagle) == before
    assert "not a picture" in outcome.result["message"]


def test_a_picture_the_project_does_not_have_is_refused_with_what_it_has(eagle) -> None:
    outcome = game_object.run(eagle, {"name": "player", "picture": "assets/dog.png"})
    assert outcome.reason == "no_picture"
    assert "assets/eagle.png" in outcome.result["message"]


def test_the_player_keeps_its_look_when_only_its_size_changes(eagle) -> None:
    call(eagle, name="player", picture="assets/eagle.png")
    outcome = call(eagle, name="eagle", size=[96, 96])       # its picture's name
    assert outcome.ok and outcome.result["object"] == "player"
    source = game(eagle)
    assert source.count('scene.add("player"') == 1
    assert 'Picture("assets/eagle.png")' in source and "PLAYER_SIZE = 64" in source


def test_a_sky_fills_the_screen_and_is_drawn_first(eagle) -> None:
    call(eagle, name="road", drawing="road")
    outcome = call(eagle, name="sky", drawing="sky", size=[640, 100], at=[0, 0])
    source = game(eagle)
    scene = scene_source.read(source)
    first = min(scene.entries.values(), key=lambda e: e.first)
    assert first.name == "sky"
    assert scene.entries["sky"].keywords["size"] == "(640, 480)"
    assert any("fills the whole screen" in note for note in outcome.result["notes"])
    road = scene.entries["road"]
    assert road.keywords == {"size": "(640, 80)", "at": "(0, 400)", "layer": '"scenery"'}


def test_buildings_stand_on_the_road_and_cars_drive_on_it(eagle) -> None:
    call(eagle, name="road", drawing="road")
    call(eagle, name="buildings", drawing="building", count=5)
    outcome = call(eagle, name="cars", drawing="vehicle", color="red", count=3,
                   moves="left", speed=3, touch="avoid")
    scene = scene_source.read(game(eagle))
    assert scene.entries["buildings"].literals["on"] == "road"
    assert scene.entries["buildings"].literals["vary"] == 0.25
    cars = scene.entries["cars"]
    assert cars.literals["on"] == "road" and cars.keywords["moves"] == "(-3, 0)"
    assert "cars" in scene.rules
    assert "player.topleft = (WIDTH // 2, HEIGHT // 2)" in game(eagle)
    assert outcome.result["touch"] == "touching it sends the player back to the start"


def test_coins_to_collect_bring_a_score_with_them(eagle) -> None:
    call(eagle, name="sky", drawing="sky")
    call(eagle, name="coins", drawing="coin", count=5, at=[40, 340], touch="collect")
    source = game(eagle)
    assert "score = 0" in source and "score += 1" in source
    assert "coin.respawn()" in source
    assert "SCORE_COLOUR = (35, 38, 45)" in source      # dark on a light sky
    compile(source, "game.py", "exec")


def test_the_same_name_again_changes_only_what_was_given(eagle) -> None:
    call(eagle, name="clouds", drawing="cloud", count=3, moves="left")
    call(eagle, name="clouds", color="lightgray")
    entry = scene_source.read(game(eagle)).entries["clouds"]
    assert entry.look == 'Cloud("lightgray")'
    assert entry.keywords["count"] == "3" and entry.keywords["moves"] == "(-1, 0)"


def test_something_can_be_taken_out_of_the_scene(eagle) -> None:
    call(eagle, name="coins", drawing="coin", count=3, touch="collect")
    outcome = call(eagle, name="coins", remove=True)
    assert outcome.result["action"] == "removed"
    source = game(eagle)
    assert '"coins"' not in source
    compile(source, "game.py", "exec")
    assert not game_object.run(eagle, {"name": "player", "remove": True}).ok


def test_shapes_given_as_places_on_the_screen_are_moved_into_their_own_box(eagle) -> None:
    """Measured on the 4B's prototype calls: a road "at [0, 380]" whose rect was also
    "[0, 380, 640, 100]"."""
    outcome = call(eagle, name="stripe", size=[640, 20], at=[0, 380],
                   shapes=[{"rect": [0, 380, 640, 20], "color": "yellow"}])
    assert outcome.ok
    entry = scene_source.read(game(eagle)).entries["stripe"]
    assert 'Rect(0, 0, 640, 20, "yellow")' in entry.look
    assert any("own box" in note for note in outcome.result["notes"])


def test_an_unknown_colour_is_said_and_something_near_it_is_used(eagle) -> None:
    outcome = call(eagle, name="fence", drawing="platform", color="darkbrown")
    entry = scene_source.read(game(eagle)).entries["fence"]
    assert entry.look.startswith("Platform((")          # brown, darkened
    assert outcome.ok


@pytest.mark.parametrize("name", ["timer", "lives", "jump", "game_over", "score"])
def test_how_the_game_plays_is_refused_with_where_to_go(eagle, name) -> None:
    """Measured: offered game_object, the 4B reached for it for timers, lives, jumping
    and game over. A drawing called "timer" that counts nothing is not a timer."""
    outcome = game_object.run(eagle, {"name": name, "shapes": [{"rect": [0, 0, 9, 9]}]})
    assert outcome.reason == "not_a_look" and "edit_file" in outcome.result["message"]
    assert outcome.files == {}


def test_make_the_player_bigger_grows_the_square_without_a_scene(eagle) -> None:
    outcome = call(eagle, name="player", size=[60, 60])
    assert outcome.ok and "PLAYER_SIZE = 60" in game(eagle)
    assert "scene" not in game(eagle) and not (eagle.directory / "src/scene.py").exists()
    assert game_object.run(eagle, {"name": "player", "size": [60, 60]}).reason == "no_change"


def test_what_a_new_thing_does_and_does_not_do_is_in_the_result(eagle) -> None:
    result = call(eagle, name="rock", drawing="platform").result
    assert result["touch"] == "nothing happens when it is touched"
    assert result["moves"] == "it stays where it is" and "edit_file" in result["does_not"]


def test_a_game_with_no_loop_to_draw_in_is_refused(eagle) -> None:
    eagle.entrypoint_path.write_text("import pygame\nprint('hello')\n")
    outcome = game_object.run(eagle, {"name": "sky", "drawing": "sky"})
    assert outcome.reason == "no_game_loop" and outcome.files == {}


def test_a_scene_py_that_is_not_the_kit_is_left_alone(eagle) -> None:
    (eagle.directory / "src" / "scene.py").write_text("def scene():\n    return 1\n")
    outcome = game_object.run(eagle, {"name": "sky", "drawing": "sky"})
    assert outcome.reason == "kit_taken"


def test_test03s_try_that_draws_a_square_when_the_picture_fails_is_taken_out(eagle) -> None:
    """The owner's game drew the eagle inside a try whose except drew a rectangle."""
    source = game(eagle).replace(
        "    pygame.draw.rect(screen, PLAYER_COLOUR, player)\n",
        "    try:\n"
        "        image = pygame.image.load('assets/eagle.png').convert_alpha()\n"
        "        image = pygame.transform.scale(image, (40, 40))\n"
        "        screen.blit(image, (player.x, player.y))\n"
        "    except pygame.error:\n"
        "        pygame.draw.rect(screen, PLAYER_COLOUR, player)\n")
    eagle.entrypoint_path.write_text(source)
    assert call(eagle, name="player", picture="assets/eagle.png").ok
    after = game(eagle)
    assert "try:" not in after and "except pygame.error" not in after
    compile(after, "game.py", "exec")


# ------------------------------------------------------------- a recipe's things


@pytest.fixture
def dodging(eagle):
    """The Fast Path's dodging game, with cars: what "make a game where I avoid cars" makes."""
    ctx = Context(eagle, games.facts(eagle), "make a game where I avoid cars",
                  {"motion": "drift", "noun": "car", "many": True, "on_touch": "reset_player"})
    eagle.entrypoint_path.write_text(next(iter(games.add_things(ctx).files.values())))
    return eagle


def test_a_recipes_cars_get_a_new_look_and_keep_moving_and_colliding(dodging) -> None:
    before = game(dodging)
    outcome = call(dodging, name="cars", drawing="vehicle", color="blue", size=[80, 40])
    assert outcome.ok, outcome.result
    after = game(dodging)
    assert 'scene.add("cars", Vehicle("blue", size=(80, 40)), rects=cars' in after
    assert "player.collidelist(cars)" in after            # the rule is kept
    assert "car.x -= CAR_SPEED" in after                  # so is the movement
    assert "for wheel_x in" in before and "for wheel_x in" not in after   # old drawing gone
    assert games.motion_of(games.facts(dodging), "CAR") is not None


def test_a_recipes_cars_asked_onto_the_road_are_handed_to_the_scene(dodging) -> None:
    call(dodging, name="road", drawing="road")
    outcome = call(dodging, name="cars", drawing="vehicle", on="road")
    assert outcome.ok, outcome.result
    source = game(dodging)
    assert ('cars = scene.add("cars", Vehicle(), size=(80, 40), on="road", count=CAR_COUNT, '
            'moves=(-CAR_SPEED, 0)') in source.replace("\n", " ").replace("  ", " ") or \
        "moves=(-CAR_SPEED, 0)" in source
    assert "car.x -= CAR_SPEED" not in source            # the scene moves them now
    assert "player.collidelist(cars)" in source          # the rule still works on Things
    compile(source, "game.py", "exec")


def test_the_recipe_colour_change_steps_aside_once_the_scene_draws_them(dodging) -> None:
    """CAR_COLOUR no longer draws anything; changing it would be a change nobody sees."""
    from opennest.fastpath.kinds import NotApplicable

    call(dodging, name="cars", drawing="vehicle", color="blue")
    ctx = Context(dodging, games.facts(dodging), "make the cars red", {})
    with pytest.raises(NotApplicable):
        games.thing_look(ctx)


def test_the_player_is_described_by_its_picture(eagle) -> None:
    call(eagle, name="player", picture="assets/eagle.png")
    call(eagle, name="clouds", drawing="cloud", count=2)
    brief = games.brief(games.facts(eagle))
    assert brief.startswith("The player is the picture assets/eagle.png")
    assert "clouds" in brief and "Nothing else" not in brief


# ======================================================================= the Toolbox


def test_game_object_goes_through_the_toolbox_and_shows_what_changed(eagle) -> None:
    box = Toolbox(eagle)
    steps = []
    box.observer = steps.append
    result = box.dispatch("game_object", {"name": "player", "picture": "assets/eagle.png"})
    assert result.ok and set(result.changed_files) == {"src/game.py", "src/scene.py"}
    assert json.loads(result.content)["picture"] == "assets/eagle.png"
    changed = {s.path: s for s in steps if s.kind == "changed"}
    assert changed["src/scene.py"].created and not changed["src/game.py"].created
    assert changed["src/game.py"].changed_lines
    assert steps[0].text == "drawing the player"


def test_a_refusal_is_json_with_a_reason_and_writes_nothing(eagle) -> None:
    box = Toolbox(eagle)
    result = box.dispatch("game_object", {"name": "player", "picture": "assets/cat.png"})
    assert not result.ok and result.reason == "no_picture" and not result.changed_files
    assert json.loads(result.content)["ok"] is False
    assert not (eagle.directory / "src" / "scene.py").exists()


@pytest.mark.parametrize("path", ["assets/eagle2.png", "assets/boom.wav", "notes.pdf"])
def test_write_file_will_not_write_text_into_a_picture_or_sound(eagle, path) -> None:
    """test03: write_file("assets/eagle.png", "i can't generate images...")."""
    result = Toolbox(eagle).dispatch("write_file", {"path": path, "content": "i can't"})
    assert not result.ok and result.reason == "not_text"
    assert "game_object" in result.content
    assert not (eagle.directory / path).exists()


def test_edit_file_will_not_edit_a_picture_either(eagle) -> None:
    fake = eagle.directory / "assets" / "old.png"
    fake.write_text("hello")
    result = Toolbox(eagle).dispatch("edit_file", {"path": "assets/old.png",
                                                   "old_text": "hello", "new_text": "hi"})
    assert not result.ok and fake.read_text() == "hello"


def test_games_offer_game_object_and_nothing_else_does() -> None:
    from opennest.projects.profiles import load_profiles

    for profile in load_profiles():
        assert ("game_object" in profile.tools) == (profile.id == "games"), profile.id


# ================================================================= Gary's facts


def test_gary_is_told_the_scene_and_the_window_from_the_code(eagle) -> None:
    from opennest.agent import evidence

    call(eagle, name="player", picture="assets/eagle.png")
    call(eagle, name="road", drawing="road")
    call(eagle, name="cars", drawing="vehicle", count=3, moves="left", touch="avoid")
    block = evidence.checked_block(eagle, Toolbox(eagle), (), ("cars", "eagle"))
    assert "The game window is 640 wide and 480 tall" in block
    assert "cars: 3 x vehicle drawing, standing on road, moving (-3, 0) a frame" in block
    assert "player: the picture assets/eagle.png, the player's rectangle" in block
    assert "nothing draws it" not in block                 # the scene draws the cars


def test_a_scene_add_inside_the_loop_is_made_every_frame() -> None:
    from opennest.agent import evidence

    source = ("import pygame\nscene = Scene(None)\nwhile True:\n"
              "    scene.add('car', Vehicle(), at=(0, 0))\n    pygame.display.flip()\n")
    assert evidence.made_every_frame(source, {"car"}) == ["car"]


def test_what_the_test_saw_the_scene_draw_is_said_and_off_screen_is_flagged() -> None:
    from opennest.agent import evidence

    test = playtest.Playtest(playtest.PASSED, scene=(
        {"name": "sky", "layer": "background", "look": "sky drawing", "count": 1,
         "frames": 90, "on_screen": 1},
        {"name": "cars", "layer": "things", "look": "vehicle drawing", "count": 3,
         "frames": 90, "on_screen": 0}))
    lines = evidence._drew_lines(test)
    assert "sky (sky drawing); cars (vehicle drawing, 3)" in lines[0]
    assert "cars was drawn but never on screen" in lines[1]


def test_a_scene_record_from_the_game_is_bounded_and_checked() -> None:
    """The record comes from the child's process: read like everything else from there."""
    junk = [{"name": "x" * 500, "layer": "things", "look": "a\nb", "count": 1,
             "frames": 1, "on_screen": 1},
            {"name": "bad", "layer": "things", "look": "l", "count": "many", "frames": 1,
             "on_screen": 1}, "not a dict"] + [{"name": str(i), "layer": "ui", "look": "l",
                                                 "count": 1, "frames": 1, "on_screen": 1}
                                                for i in range(100)]
    kept = playtest._scene(junk)
    assert len(kept) <= 40 and len(kept[0]["name"]) == 40 and kept[0]["look"] == "a b"
    assert all(item["name"] != "bad" for item in kept)
    assert playtest._scene("nonsense") == ()


# ======================================================== together, for real


@needs_sandbox
def test_a_whole_scene_runs_under_the_sandbox_and_the_test_sees_the_eagle(eagle) -> None:
    """The acceptance scene, built call by call, run by the real headless playtest."""
    for arguments in (
        {"name": "player", "picture": "my eagle picture", "size": [72, 72]},
        {"name": "sky", "drawing": "sky"},
        {"name": "road", "drawing": "road"},
        {"name": "buildings", "drawing": "building", "color": "tan", "count": 5},
        {"name": "clouds", "drawing": "cloud", "count": 3, "moves": "left"},
        {"name": "cars", "drawing": "vehicle", "color": "red", "count": 3, "moves": "left",
         "touch": "avoid"},
        {"name": "coins", "drawing": "coin", "count": 5, "at": [40, 340],
         "touch": "collect"},
    ):
        assert call(eagle, **arguments).ok, arguments
    result = Toolbox(eagle).playtest()
    assert result.verdict == playtest.PASSED, result
    assert result.moved_by_itself and "right" in result.responded_to
    drawn = {item["name"]: item for item in result.scene}
    assert drawn["player"]["look"] == "picture assets/eagle.png"
    assert drawn["player"]["on_screen"] == 1 and drawn["player"]["frames"] > 10
    assert drawn["cars"]["count"] == 3 and drawn["buildings"]["on_screen"] == 5
    assert [item["name"] for item in result.scene][:2] == ["sky", "clouds"]


@needs_sandbox
def test_a_picture_that_breaks_later_crashes_the_test_rather_than_hiding(eagle) -> None:
    """Nothing quietly draws a square: the repair loop is told the real error."""
    call(eagle, name="player", picture="assets/eagle.png")
    (eagle.directory / "assets" / "eagle.png").write_text("not a picture any more")
    result = Toolbox(eagle).playtest()
    assert result.verdict == playtest.CRASHED
    assert "cannot load 'assets/eagle.png'" in result.error


@needs_sandbox
def test_the_sprite_recipe_now_draws_through_the_scene_and_checks_it_was_seen(eagle) -> None:
    from opennest.fastpath.executor import RecipeExecutor

    change = games.use_sprite(Context(eagle, games.facts(eagle), "use my eagle", {}))
    assert change.calls == [("game_object", {"name": "player",
                                             "picture": "assets/eagle.png"})]
    box = Toolbox(eagle)
    applied = RecipeExecutor().apply(change, box)
    assert [call.name for call, _ in applied.calls] == ["game_object"]
    assert applied.originals["src/scene.py"] is None
    ctx = type("Ctx", (), {"once": lambda self, key, fn: fn(), "toolbox": box,
                           "expect": change.expect})()
    assert games.CHECKS["picture_drawn"](ctx).status == "pass"
    RecipeExecutor.rollback(applied, box)
    assert not (eagle.directory / "src" / "scene.py").exists()
    assert "pygame.draw.rect(screen, PLAYER_COLOUR, player)" in game(eagle)


def test_a_file_named_like_a_picture_is_described_as_not_one(eagle) -> None:
    """What Gary was told about test03's eagle.png: "a file (102 bytes)"."""
    from opennest.assets import manager as assets

    (eagle.directory / "assets" / "fake.png").write_text("i can't generate images")
    listed = {a.path: a for a in assets.list_assets(eagle)}
    assert listed["assets/fake.png"].summary.startswith("NOT a picture")
    assert "its bytes are text" in listed["assets/fake.png"].summary
    assert listed["assets/eagle.png"].summary.startswith("PNG image, 128x128")


# ================================================================ through Gary's loop


def _controller(project, replies):
    from opennest.agent.controller import AgentController
    from tests.conftest import ScriptedProvider

    provider = ScriptedProvider(replies)
    return AgentController(project, provider, Toolbox(project)), provider


@needs_sandbox
def test_a_game_object_turn_is_tested_like_any_change(eagle) -> None:
    from opennest.ai.provider import Reply, ToolCall

    controller, provider = _controller(eagle, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "player",
                                                   "picture": "assets/eagle.png"}),)),
        Reply(text="The eagle picture is your player now."),
    ])
    turn = controller.send("Use my eagle picture as the player.")
    assert [(name, result.ok) for name, result in turn.tool_results] == [("game_object", True)]
    assert turn.playtests and turn.playtests[-1].verdict == playtest.PASSED
    assert any(item["look"] == "picture assets/eagle.png"
               for item in turn.playtests[-1].scene)
    assert turn.text == "The eagle picture is your player now."
    # What Gary reads next turn is the call and its JSON result -- not a page of code.
    tool_message = next(m for m in controller.history if m.role == "tool")
    assert json.loads(tool_message.content)["picture"] == "assets/eagle.png"
    assert "In that test the scene drew" in controller.history[0].content


def test_a_refused_game_object_is_not_announced_as_done(eagle) -> None:
    """The owner's failure, by the new route: the call is refused and the claim is not
    relayed -- the honesty guard sees no file changed, as for any other tool."""
    from opennest.ai.provider import Reply, ToolCall

    controller, provider = _controller(eagle, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "player",
                                                   "picture": "assets/dragon.png"}),)),
        Reply(text="I added the dragon as the player."),
        Reply(text="I added the dragon as the player."),
        Reply(text="I added the dragon as the player."),
    ])
    turn = controller.send("make the dragon the player")
    assert not turn.tool_results[0][1].ok
    assert "I added the dragon" not in turn.text
    assert "haven't" in turn.text.lower() or "have not" in turn.text.lower()
    correction = [m.content for call in provider.calls for m in call if m.role == "user"]
    assert any("game_object, for how something looks" in text for text in correction)


def test_restyled_recipe_cars_asked_onto_the_road_later_are_handed_over(dodging) -> None:
    call(dodging, name="cars", drawing="vehicle", color="blue")
    call(dodging, name="road", drawing="road")
    outcome = call(dodging, name="cars", on="road")
    assert outcome.ok and outcome.result.get("now") == "the scene moves cars instead of the loop"
    source = game(dodging)
    assert source.count('"cars"') == 1 and "rects=cars" not in source
    assert 'Vehicle("blue")' in source and "car.x -= CAR_SPEED" not in source
    compile(source, "game.py", "exec")


def test_a_kit_changed_by_hand_that_lacks_a_drawing_is_not_relied_on(eagle) -> None:
    call(eagle, name="sky", drawing="sky")
    kit = eagle.directory / "src" / "scene.py"
    kit.write_text(kit.read_text().replace("class Vehicle(Ready):", "class Car(Ready):"))
    outcome = game_object.run(eagle, {"name": "cars", "drawing": "vehicle"})
    assert outcome.reason == "kit_changed" and "Vehicle" in outcome.result["message"]


def test_a_silent_game_object_turn_is_described_from_the_results(eagle) -> None:
    from opennest.agent.controller import _scene_changes

    box = Toolbox(eagle)
    results = [("game_object", box.dispatch("game_object", {"name": "sky", "drawing": "sky"})),
               ("game_object", box.dispatch("game_object", {"name": "player",
                                                           "picture": "assets/eagle.png"}))]
    assert _scene_changes(results) == ("I added the sky (a ready-made sky drawing) and made "
                                       "the player the picture assets/eagle.png.")
    assert _scene_changes(results + [("edit_file", box.dispatch("edit_file", {
        "path": "src/game.py", "old_text": "PLAYER_SPEED = 5",
        "new_text": "PLAYER_SPEED = 6"}))]) == ""


def test_a_call_that_changes_nothing_is_refused_not_reported(eagle) -> None:
    call(eagle, name="player", picture="assets/eagle.png")
    outcome = game_object.run(eagle, {"name": "player", "picture": "assets/eagle.png"})
    assert outcome.reason == "no_change" and outcome.files == {}


def test_the_sprite_recipe_says_it_already_is(eagle) -> None:
    from opennest.fastpath.kinds import AlreadyDone

    call(eagle, name="player", picture="assets/eagle.png")
    with pytest.raises(AlreadyDone):
        games.use_sprite(Context(eagle, games.facts(eagle), "use my eagle", {}))


def test_faster_asteroids_is_their_own_constant(dodging) -> None:
    before = game(dodging)
    outcome = call(dodging, name="cars", speed=6)
    assert outcome.ok and "CAR_SPEED went from 2 to 6" in outcome.result["notes"][0]
    assert "CAR_SPEED = 6" in game(dodging) and "scene" not in game(dodging)
    assert before.replace("CAR_SPEED = 2", "CAR_SPEED = 6") == game(dodging)


def test_a_new_road_says_which_standing_things_are_not_on_it(eagle) -> None:
    call(eagle, name="cars", drawing="vehicle", at=[500, 300], count=2, moves="left")
    result = call(eagle, name="road", drawing="road").result
    assert result["not_on_it"] == ('standing on nothing yet: cars. game_object with on: '
                                   '"road" puts a thing on the road')


def test_a_colour_nothing_draws_with_any_more_is_taken_away(eagle) -> None:
    """The 8B walk: PLAYER_COLOUR changed after the player was a picture, and Gary said
    the player was bright yellow now."""
    outcome = call(eagle, name="player", picture="assets/eagle.png")
    assert "PLAYER_COLOUR" not in game(eagle)
    assert any("PLAYER_COLOUR went" in note for note in outcome.result["notes"])
    compile(game(eagle), "game.py", "exec")


def test_where_things_stand_against_the_road_is_said_in_words(eagle) -> None:
    from opennest.agent import evidence

    call(eagle, name="road", drawing="road", at=[0, 440], size=[640, 40])
    call(eagle, name="cars", drawing="vehicle", at=[500, 300], size=[40, 20])
    call(eagle, name="sky", drawing="sky")
    block = evidence.checked_block(eagle, None, (), ())
    assert "cars: a vehicle drawing, at (500, 300), above the road, not on it" in block
    assert "drawn in BACKGROUND's colour, so changing BACKGROUND changes the sky" in block


def test_a_picture_nobody_asked_for_is_not_used_for_something_else(eagle) -> None:
    """Measured: with one picture in the project, the 4B used eagle.png for an apple."""
    outcome = game_object.run(eagle, {"name": "apple", "picture": "assets/eagle.png"},
                              message=("make a game where you catch falling apples", ()))
    assert outcome.reason == "picture_not_asked" and outcome.files == {}
    assert "ready-made drawing or shapes" in outcome.result["message"]


@pytest.mark.parametrize("said, attached", [
    ("use my eagle picture for the enemies", ()),
    ("use this picture for the enemies", ()),
    ("these are the enemies", ("assets/eagle.png",)),
])
def test_the_childs_words_or_an_attachment_let_a_picture_be_anything(eagle, said,
                                                                       attached) -> None:
    outcome = game_object.run(eagle, {"name": "enemies", "picture": "assets/eagle.png"},
                              message=(said, attached))
    assert outcome.ok, outcome.result


def test_a_new_picture_thing_says_the_player_is_still_as_it_was(eagle) -> None:
    outcome = game_object.run(eagle, {"name": "eagle", "picture": "assets/eagle.png"},
                              message=("make a game where I fly an eagle", ()))
    assert outcome.ok and "use the name player" in outcome.result["player"]


def test_gary_is_told_things_to_see_need_no_drawing_code(eagle) -> None:
    assert "game_object puts each one in the scene" in games.where(games.facts(eagle))
    call(eagle, name="sky", drawing="sky")
    assert "drawn by line" in games.where(games.facts(eagle))


def test_a_loop_that_shows_two_pictures_a_frame_is_said(eagle) -> None:
    """The first 4B walk: the loop's body copied into itself, two flips, a flicker."""
    from opennest.agent import evidence

    source = game(eagle)
    body = source.split("while running:\n", 1)[1].split("\npygame.quit()")[0]
    eagle.entrypoint_path.write_text(source.replace("    clock.tick(60)\n",
                                                    "    clock.tick(60)\n" + body + "\n", 1))
    block = evidence.checked_block(eagle, None, (), ())
    assert "shows 2 different pictures each time round" in block


def test_drawing_the_scene_paints_over_is_said(eagle) -> None:
    """The second 4B walk's "glow effect": drawn after the fill, under the sky."""
    from opennest.agent import evidence

    call(eagle, name="sky", drawing="sky")
    call(eagle, name="player", picture="assets/eagle.png")
    source = game(eagle).replace(
        "    scene.draw()\n",
        "    pygame.draw.rect(screen, (214, 142, 62), glow, 3)\n    scene.draw()\n")
    source = source.replace("running = True\n",
                            "glow = pygame.Rect(0, 0, 9, 9)\n\nrunning = True\n")
    eagle.entrypoint_path.write_text(source)
    block = evidence.checked_block(eagle, None, (), ())
    assert "The code draws glow after screen.fill but before scene.draw()" in block
    assert "the sky covers the whole screen, so the child never sees it" in block
    assert "after line" in games.where(games.facts(eagle))
    assert "painted over by the scene" in games.where(games.facts(eagle))


def test_a_half_done_turn_that_promises_the_rest_is_carried_on_once(eagle) -> None:
    from opennest.ai.provider import Reply, ToolCall

    controller, provider = _controller(eagle, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "sky", "drawing": "sky"}),)),
        Reply(text="The sky is now blue. I'll add the road now."),
        Reply(tool_calls=(ToolCall("game_object", {"name": "road", "drawing": "road"}),)),
        Reply(text="I added the sky and the road. I'll add buildings next."),
    ])
    turn = controller.send("give it a sky and a road")
    assert [name for name, _ in turn.tool_results] == ["game_object", "game_object"]
    pushes = [m.content for m in provider.calls[-1]
              if m.role == "user" and m.content.startswith("You said you would do more")]
    assert len(pushes) == 1                 # once per turn, never a loop
    assert len(provider.calls) == 4


def test_three_cars_said_about_a_scene_with_one_is_corrected(eagle) -> None:
    """The third 4B walk: three calls named "car", each replacing the last."""
    from opennest.ai.provider import Reply, ToolCall

    car = {"name": "car", "drawing": "vehicle", "moves": "left"}
    controller, provider = _controller(eagle, [
        Reply(tool_calls=(ToolCall("game_object", {**car, "at": [100, 300]}),)),
        Reply(tool_calls=(ToolCall("game_object", {**car, "at": [300, 300]}),)),
        Reply(text="Three red cars are now at (100, 300) and (300, 300)."),
        Reply(tool_calls=(ToolCall("game_object", {**car, "count": 3}),)),
        Reply(text="There are three cars now."),
    ])
    turn = controller.send("Add three cars to the road.")
    sent = [m.content for m in provider.calls[-1] if m.role == "user"]
    assert any(text.startswith("The game has 1 car, not 3") for text in sent)
    assert "count: 3 makes that many" in sent[-1]
    assert turn.text == "There are three cars now."
    entry = scene_source.read(game(eagle)).entries["car"]
    assert entry.literals["count"] == 3


def test_a_count_that_is_right_is_left_alone(eagle) -> None:
    from opennest.ai.provider import Reply, ToolCall

    controller, provider = _controller(eagle, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "clouds", "drawing": "cloud",
                                                   "count": 2}),)),
        Reply(text="Two clouds float in the sky."),
    ])
    turn = controller.send("add two clouds")
    assert turn.text == "Two clouds float in the sky." and len(provider.calls) == 2


def test_a_car_put_just_above_the_road_stands_on_it(eagle) -> None:
    """Both models put cars 40-80 pixels above the road they asked for."""
    call(eagle, name="road", drawing="road", at=[0, 400], size=[640, 20])
    outcome = call(eagle, name="cars", drawing="vehicle", at=[200, 300], size=[60, 20])
    entry = scene_source.read(game(eagle)).entries["cars"]
    assert entry.literals["on"] == "road" and entry.literals["at"] == (200, 300)
    assert any("stands on the road" in note for note in outcome.result["notes"])
    call(eagle, name="sign", drawing="sign", at=[200, 40], size=[120, 60])
    assert "on" not in scene_source.read(game(eagle)).entries["sign"].literals


def test_a_town_is_its_buildings() -> None:
    from opennest.agent.controller import _SCENE_FORMS

    assert "building" in _SCENE_FORMS["town"]


def test_moving_a_car_along_the_road_keeps_it_on_the_road(eagle) -> None:
    """The final 4B walk: the same car sent again with its old corner fell off the road."""
    call(eagle, name="road", drawing="road", at=[0, 400], size=[640, 20])
    call(eagle, name="car", drawing="vehicle", at=[200, 300], size=[60, 20])
    call(eagle, name="car", drawing="vehicle", color="blue", at=[250, 300], size=[60, 20])
    entry = scene_source.read(game(eagle)).entries["car"]
    assert entry.literals["on"] == "road" and entry.literals["at"] == (250, 300)
    call(eagle, name="car", at=[250, 40])
    assert "on" not in scene_source.read(game(eagle)).entries["car"].literals


@needs_sandbox
def test_an_animated_player_from_a_sprite_sheet_runs_and_is_seen(eagle) -> None:
    """Work order section 8: frames and timing, without Gary writing frame code."""
    shutil.copy(SHEET, eagle.directory / "assets" / "eagle_cycle.png")
    outcome = call(eagle, name="player", picture="assets/eagle_cycle.png", frames=12)
    assert outcome.ok and outcome.result["frames"] == 12
    assert 'Animation("assets/eagle_cycle.png", frames=12, fps=8)' in game(eagle)
    result = Toolbox(eagle).playtest()
    assert result.verdict == playtest.PASSED and result.moved_by_itself
    drawn = {item["name"]: item for item in result.scene}
    assert drawn["player"]["look"] == "animation assets/eagle_cycle.png, 12 frames"


def test_the_kit_finds_its_pictures_from_anywhere_the_game_is_started(kit, eagle,
                                                                       tmp_path,
                                                                       monkeypatch) -> None:
    """Work order section 16: the game runs outside Open Nest, from any folder."""
    _scene, pygame, _screen = kit
    call(eagle, name="player", picture="assets/eagle.png")
    spec = importlib.util.spec_from_file_location("copied_kit",
                                                  eagle.directory / "src" / "scene.py")
    copied = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copied)
    monkeypatch.chdir(tmp_path)                    # nowhere near the project
    assert eagle.directory.resolve() == copied.PROJECT
    assert copied.Picture("assets/eagle.png").image((40, 40)).get_size() == (40, 40)


def test_a_thing_can_stand_on_something_added_after_it(kit) -> None:
    """The final 4B walk crashed: buildings on the road, written before the road."""
    scene, pygame, screen = kit
    world = scene.Scene(screen)
    houses = world.add("houses", scene.House(), size=(90, 80), count=2, on="road",
                       layer="background")
    world.add("road", scene.Road(), size=(640, 60), at=(0, 420), layer="scenery")
    world.draw()
    assert [h.drawn_rect().bottom for h in houses] == [420, 420]
    lost = scene.Scene(screen)
    lost.add("sign", scene.Sign(), on="nothing")
    with pytest.raises(scene.SceneError, match="nothing called 'nothing'"):
        lost.draw()


@needs_sandbox
def test_buildings_snapped_onto_a_road_written_later_still_run(eagle) -> None:
    call(eagle, name="road", drawing="road", at=[0, 400], size=[640, 20])
    call(eagle, name="building", drawing="building", at=[300, 300], size=[80, 100],
         layer="background", count=2)
    scene = scene_source.read(game(eagle))
    assert scene.entries["building"].first > scene.entries["road"].first
    assert Toolbox(eagle).playtest().verdict == playtest.PASSED


def test_the_only_picture_is_not_the_cars_just_because_the_eagle_was_mentioned(eagle) -> None:
    """The final 4B walk: "fly an eagle ... avoid cars", and the car given eagle.png."""
    outcome = call(eagle, name="car", picture="assets/eagle.png", color="red",
                   moves="left")
    entry = scene_source.read(game(eagle)).entries["car"]
    assert outcome.ok and entry.look == 'Vehicle("red")'
    assert any("not a car, so it is drawn as a ready-made vehicle" in note
               for note in outcome.result["notes"])
    refused = game_object.run(eagle, {"name": "apple", "picture": "assets/eagle.png"},
                              message=("Make a game where I fly an eagle and catch apples", ()))
    assert refused.reason == "picture_not_asked"


def test_avoid_and_collect_are_checked_against_what_touching_does(eagle) -> None:
    """The final 8B walk: "avoid the cars, and collect coins" -- neither had a rule."""
    from opennest.ai.provider import Reply, ToolCall

    controller, provider = _controller(eagle, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "cars", "drawing": "vehicle",
                                                   "count": 3, "moves": "left"}),)),
        Reply(text="Now you can fly the eagle and avoid the cars."),
        Reply(text="The cars drive left. Touching them does nothing yet."),
    ])
    turn = controller.send("add some cars")
    sent = [m.content for m in provider.calls[-1] if m.role == "user"]
    assert sent[-1].startswith("Touching the cars does not send the player back")
    assert turn.text == "The cars drive left. Touching them does nothing yet."
    call(eagle, name="coins", drawing="coin", count=2, touch="collect")
    assert controller._scene_claims("Collect the coins for points.") is None


def test_on_the_road_is_checked_against_where_the_scene_has_it(eagle) -> None:
    from opennest.agent.controller import AgentController
    from tests.conftest import ScriptedProvider

    call(eagle, name="road", drawing="road", at=[0, 430], size=[640, 50])
    call(eagle, name="cars", drawing="vehicle", at=[600, 0], size=[40, 20], count=3,
         moves="left")
    controller = AgentController(eagle, ScriptedProvider([]), Toolbox(eagle))
    said = controller._scene_claims("10 cars moving left across the road.")
    assert said.startswith("The cars are above the road, not on it")
    call(eagle, name="cars", on="road")
    assert controller._scene_claims("The cars drive along the road.") is None


def test_the_kit_does_not_make_a_missing_road_true(eagle) -> None:
    """The kit names every drawing it can make; read as the game's words, "the road" was
    true of a game with only a sky (the definitive 4B walk)."""
    from opennest.agent.controller import AgentController, Turn
    from tests.conftest import ScriptedProvider

    call(eagle, name="sky", drawing="sky")
    controller = AgentController(eagle, ScriptedProvider([]), Toolbox(eagle))
    controller._asked_for = {"road", "town"}
    assert controller._names_what_is_not_there(Turn(), "The eagle flies over the road.") \
        == "road"
    assert controller._names_what_is_not_there(Turn(), "It flies over the town.") == "town"
    call(eagle, name="buildings", drawing="building", count=3)
    assert controller._names_what_is_not_there(Turn(), "It flies over the town.") is None


def test_cars_to_dodge_are_never_behind_the_buildings(eagle) -> None:
    """The final 8B walk: cars in scenery, and buildings added after them covered them."""
    outcome = call(eagle, name="cars", drawing="vehicle", count=3, moves="left",
                   touch="avoid", layer="scenery")
    assert scene_source.read(game(eagle)).entries["cars"].layer == "things"
    assert any("in front of the scenery" in note for note in outcome.result["notes"])
    call(eagle, name="clouds", drawing="cloud", count=2, moves="left", layer="background")
    assert scene_source.read(game(eagle)).entries["clouds"].layer == "background"


def test_the_sky_is_drawn_in_background_so_changing_it_is_seen(eagle) -> None:
    """Both models changed BACKGROUND and said the sky had changed, while the sky hid it."""
    outcome = call(eagle, name="sky", drawing="sky", color="skyblue")
    source = game(eagle)
    assert 'Sky(BACKGROUND)' in source and "BACKGROUND = (125, 195, 245)" in source
    assert any("BACKGROUND is the sky's colour" in note for note in outcome.result["notes"])
    call(eagle, name="sky", color="orange")
    assert "BACKGROUND = (242, 153, 74)" in game(eagle) and 'Sky(BACKGROUND)' in game(eagle)
    # ...and the Fast Path's own background recipe now changes the sky too.
    ctx = Context(eagle, games.facts(eagle), "make the background #203060",
                  {"fact": "background", "question": "which colour?"})
    change = games.set_colour(ctx)
    assert next(iter(change.files.values())).count("Sky(BACKGROUND)") == 1


def test_a_claim_about_edits_that_were_refused_is_corrected(eagle) -> None:
    """The final 4B walk: the coins changed, three edits to imagined lines were refused,
    and the reply said the roads, buildings and clouds had new colours."""
    from opennest.ai.provider import Reply, ToolCall

    call(eagle, name="road", drawing="road")
    call(eagle, name="clouds", drawing="cloud", count=2)
    controller, provider = _controller(eagle, [
        Reply(tool_calls=(
            ToolCall("edit_file", {"path": "src/game.py", "old_text": "PLAYER_SPEED = 5",
                                   "new_text": "PLAYER_SPEED = 6"}),
            ToolCall("edit_file", {"path": "src/game.py",
                                   "old_text": "road.color = 'gray'",
                                   "new_text": "road.color = 'dark gray'"}),
            ToolCall("edit_file", {"path": "src/game.py",
                                   "old_text": "cloud.color = 'white'",
                                   "new_text": "cloud.color = 'light gray'"}),
        )),
        Reply(text="I made the player faster, changed the roads to dark gray and the "
                   "clouds to light gray."),
        Reply(text="I made the player faster. The road and clouds look as they did."),
    ])
    turn = controller.send("make everything more colorful and the player faster")
    sent = [m.content for m in provider.calls[-1] if m.role == "user"]
    assert sent[-1].startswith("The changes to the clouds, roads did not go in")
    assert "they look as before" in sent[-1]
    assert turn.text == "I made the player faster. The road and clouds look as they did."


def test_the_refused_value_said_again_is_followed_by_what_happened(eagle) -> None:
    """The last 4B walk: corrected, the reply kept "The road is dark gray"."""
    from opennest.ai.provider import Reply, ToolCall

    call(eagle, name="road", drawing="road")
    controller, provider = _controller(eagle, [
        Reply(tool_calls=(
            ToolCall("edit_file", {"path": "src/game.py", "old_text": "PLAYER_SPEED = 5",
                                   "new_text": "PLAYER_SPEED = 6"}),
            ToolCall("edit_file", {"path": "src/game.py", "old_text": "road.color = 'gray'",
                                   "new_text": "road.color = 'dark gray'"}),
        )),
        Reply(text="I changed the road to dark gray and made the player faster."),
        Reply(text="The player is faster. The road is dark gray."),
    ])
    turn = controller.send("make the road darker and the player faster")
    assert turn.text == ("The player is faster. The road is dark gray.\n\n(Open Nest: the "
                         "road looks as it did -- that change did not go in.)")


def test_nothing_in_the_application_imports_pygame_but_the_kit() -> None:
    """pygame is a package children's projects use, not the application's; the kit is the
    child's code, copied into the project, and is the one exception."""
    package = REPO / "opennest"
    found = []
    for path in package.rglob("*.py"):
        if path == looks.KIT or "starters" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            if any(name.split(".")[0] == "pygame" for name in names):
                found.append(str(path.relative_to(REPO)))
    assert found == [] or all("live_shim" in f or "playtest_harness" in f for f in found), found


def test_a_thing_that_already_looked_so_is_not_a_refused_change(eagle) -> None:
    """The final 4B walk: the road's call was "already looks like that", and "the road
    remains gray" was flagged as a change that did not go in."""
    from opennest.ai.provider import Reply, ToolCall

    call(eagle, name="road", drawing="road", color="gray")
    controller, provider = _controller(eagle, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "sky", "drawing": "sky"}),
                          ToolCall("game_object", {"name": "road", "drawing": "road",
                                                   "color": "gray"}))),
        Reply(text="The sky is now blue. The road remains gray."),
    ])
    turn = controller.send("give it a sky and a road")
    assert turn.text == "The sky is now blue. The road remains gray."


def test_a_tree_a_little_below_a_thin_road_stands_on_it(eagle) -> None:
    call(eagle, name="road", drawing="road", at=[0, 400], size=[640, 20])
    call(eagle, name="tree", drawing="tree", at=[200, 350], size=[40, 80])
    assert scene_source.read(game(eagle)).entries["tree"].literals["on"] == "road"
