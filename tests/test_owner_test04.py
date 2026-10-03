"""The owner's test04 (2026-10-02), and what its replays showed was Open Nest's own doing.

The owner asked the local 4B for "a game in the woods at night. A first person shooter.
We have to shoot monsters hiding behind trees", then added their own monster picture and
six tree pictures. Replayed message for message with the 4B and Qwen3 8B
(``benchmarks/owner_test04/``), half of what went wrong was not the model:

- **The scene layer**: a picture kept a box that was not its shape, so the monster hung
  in the sky; three calls for one tree left one tree; "square" and "circle" were refused
  as drawings; five trees each the size of the window; the monster's picture put on the
  trees; six tree pictures with no way to use them together; and nothing to shoot with.
- **Open Nest's checks**: "the woods" said of trees, a picture named in a sentence, and
  "the monster" -- the child's own word from two messages before -- each drew a false
  correction, and the corrections then had Gary say the child's message back as his own,
  or deny work he had done.
- **The replies Open Nest writes**: "Here is where I got to" with nothing after it, "a
  real square", "changed how the tree looks and changed how the tree looks".
- **Gary's words reaching the child**: the job handed back ("You can now make the
  forest"), and pixels ("The monster at (100, 300) stays still").
- **Adding pictures**: six questions and six messages for six trees, and a dropdown too
  narrow to read on macOS.
- **Getting started**: "Hi. Ready." and "Run the game. Watch the orange square move."
"""

from __future__ import annotations

import json
import os
import struct
import zlib
from pathlib import Path

import pytest

from opennest.agent import replies
from opennest.agent.controller import AgentController, _scene_changes
from opennest.agent.tools import Toolbox
from opennest.ai.provider import Reply, ToolCall
from opennest.assets import manager as assets
from opennest.graphics import looks
from opennest.graphics import source as scene_source
from tests.conftest import ScriptedProvider


def png(path: Path, width: int, height: int) -> Path:
    """A real PNG of ``width`` x ``height``, see-through round a solid middle."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            inside = width // 5 <= x < width - width // 5 and height // 8 <= y
            row += bytes((40, 120, 220, 255) if inside else (0, 0, 0, 0))
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"".join(rows)))
                     + chunk(b"IEND", b""))
    return path


@pytest.fixture
def woods(project):
    """The owner's assets: a nearly square monster and six tall trees."""
    png(project.directory / "assets" / "blue_monster.png", 64, 62)
    for n in range(1, 7):
        png(project.directory / "assets" / f"tree_0{n}.png", 54, 72)
    return project


def dispatch(box: Toolbox, message: str, **arguments) -> dict:
    if box.message[0] != message:
        box.message = (message, ())
    result = box.dispatch("game_object", arguments)
    body = json.loads(result.content)
    assert result.ok, body
    return body


def scene(project) -> scene_source.GameScene:
    return scene_source.read(project.entrypoint_path.read_text(encoding="utf-8"))


# ============================================================================ the layer


def test_a_picture_box_is_the_picture_s_shape(woods) -> None:
    """The monster kept its shapes' 140x470 box: a nearly square picture in the middle of
    a tall box standing on the road hung in the sky."""
    box = Toolbox(woods)
    dispatch(box, "a road", name="road", drawing="road")
    body = dispatch(box, "the monster", name="monster", picture="assets/blue_monster.png",
                    size=[140, 470], on="road")
    assert body["drawn_size"] == [140, 136]
    assert any("own shape" in note for note in body["notes"])


def test_a_drawing_swapped_for_a_picture_is_drawn_at_the_picture_s_size(woods) -> None:
    box = Toolbox(woods)
    dispatch(box, "a monster", name="monster", shapes=[{"rect": [0, 0, 140, 470]}],
             size=[140, 470])
    body = dispatch(box, "use my monster picture", name="monster",
                    picture="assets/blue_monster.png")
    width, height = body["drawn_size"]
    assert max(width, height) <= 120 and abs(width - height) <= 4
    assert any("it was a drawing before" in note for note in body["notes"])


def test_a_row_given_the_whole_screen_is_drawn_at_each_one_s_size(woods) -> None:
    """The 4B: "trees", count 5, size [640, 480] -- five trees each as big as the window."""
    body = dispatch(Toolbox(woods), "woods", name="trees", drawing="tree", count=5,
                    at=[0, 0], size=[640, 480])
    assert body["drawn_size"][0] < 640 // 5
    assert any("whole screen" in note for note in body["notes"])


def test_a_row_too_wide_for_the_screen_is_made_to_fit(woods) -> None:
    body = dispatch(Toolbox(woods), "woods", name="trees", drawing="tree", count=8,
                    size=[200, 300])
    assert body["drawn_size"][0] * 8 <= 640 * 1.05


def test_three_calls_for_one_tree_in_one_message_are_three_trees(woods) -> None:
    """The 8B planted a forest as three calls named tree, each replacing the last."""
    box = Toolbox(woods)
    dispatch(box, "woods", name="ground", drawing="ground")
    for x in (100, 200, 300):
        body = dispatch(box, "woods", name="tree", drawing="tree", size=[40, 100],
                        at=[x, 340])
    assert body["action"] == "added" and body["count"] == 3
    entry = scene(woods).entries["tree"]
    assert [spot[0] for spot in entry.literals["at"]] == [100, 200, 300]
    assert entry.literals["on"] == "ground"


def test_the_same_name_in_a_later_message_still_moves_it(woods) -> None:
    box = Toolbox(woods)
    dispatch(box, "a tree", name="tree", drawing="tree", at=[100, 300])
    body = dispatch(box, "move the tree", name="tree", at=[400, 300])
    assert body["action"] == "changed"
    assert scene(woods).entries["tree"].literals["at"] == (400, 300)


@pytest.mark.parametrize("word, shape", [("square", "Rect("), ("circle", "Circle("),
                                         ("red triangle", "Triangle(")])
def test_a_shape_named_as_a_drawing_is_drawn_as_that_shape(woods, word, shape) -> None:
    """The 4B asked for drawing "square" and "circle", was refused twice, and the child
    was offered a picture of "a real square"."""
    body = dispatch(Toolbox(woods), "a monster", name="monster", drawing=word,
                    color="red", size=[30, 30])
    assert body["action"] == "added"
    assert shape in scene(woods).entries["monster"].look


def test_a_picture_named_for_another_thing_is_not_used_for_this_one(woods) -> None:
    """"I added the monster image now ... hide behind the trees", and the 4B gave the
    trees blue_monster.png."""
    box = Toolbox(woods)
    message = ("I added the monster image now. the player must be walking forward through "
               "the trees and the monster will hide behind the trees.")
    dispatch(box, message, name="monster", shapes=[{"circle": [15, 15, 15]}])
    body = dispatch(box, message, name="trees", picture="assets/blue_monster.png", count=5)
    assert "Tree(" in scene(woods).entries["trees"].look
    assert any("it is the monster" in note for note in body["notes"])


def test_a_new_thing_given_the_picture_the_child_just_named_is_that_thing(woods) -> None:
    """"I added the monster image now", and the 4B called a new "tree" with
    blue_monster.png -- its own reply said "The blue monster is now visible"."""
    body = dispatch(Toolbox(woods), "I added the monster image now.", name="tree",
                    picture="assets/blue_monster.png", touch="shoot")
    assert body["object"] == "monster"
    assert "blue_monster.png" in scene(woods).entries["monster"].look
    assert "tree" not in scene(woods).entries


def test_the_child_can_still_give_one_thing_s_picture_to_another(woods) -> None:
    box = Toolbox(woods)
    dispatch(box, "a monster", name="monster", shapes=[{"circle": [15, 15, 15]}])
    dispatch(box, "use the monster picture for the enemies", name="enemies",
             picture="assets/blue_monster.png")
    assert "blue_monster.png" in scene(woods).entries["enemies"].look


def test_numbered_pictures_in_a_row_are_used_one_per_copy(woods) -> None:
    """Six tree pictures, "make the forest", and the 8B used tree_01.png for one tree."""
    body = dispatch(Toolbox(woods), "I added tree images now, make the forest",
                    name="trees", picture="assets/tree_01.png", count=6)
    entry = scene(woods).entries["trees"]
    assert entry.look_class == "Picture" and entry.look.lstrip().startswith("[")
    assert all(f"tree_0{n}.png" in entry.look for n in range(1, 7))
    assert "one per copy" in body["look"]
    assert entry.layer == "scenery" and entry.literals.get("vary")
    assert "the pictures" in scene_source.look_words(entry)


def test_a_list_of_pictures_is_used_as_given(woods) -> None:
    dispatch(Toolbox(woods), "a forest from my trees", name="forest",
             picture=["assets/tree_02.png", "assets/tree_05.png"], count=4)
    look = scene(woods).entries["forest"].look
    assert "tree_02.png" in look and "tree_05.png" in look and "tree_01.png" not in look


def test_the_player_wears_one_picture_of_a_list(woods) -> None:
    body = dispatch(Toolbox(woods), "the player is my tree", name="player",
                    picture=["assets/tree_01.png", "assets/tree_02.png"])
    assert body["picture"] == "assets/tree_01.png"
    assert "[" not in scene(woods).entries["player"].look


def test_shooting_is_a_rule_the_scene_writes(woods) -> None:
    """Asked for a shooter, no model shot anything; the 4B's own try was a yellow dot
    added every frame Space was held, forever, hitting nothing."""
    box = Toolbox(woods)
    dispatch(box, "a sky", name="sky", color="navy")
    body = dispatch(box, "monsters to shoot", name="monsters",
                    picture="assets/blue_monster.png", count=3, touch="shoot",
                    layer="scenery", moves="right")
    code = woods.entrypoint_path.read_text(encoding="utf-8")
    assert "event.type == pygame.MOUSEBUTTONDOWN" in code and "pygame.K_SPACE" in code
    assert "score += 1" in code and ".respawn()" in code and "Score: {score}" in code
    found = scene(woods)
    assert scene_source.touch_rule(found, "monsters") == "shoot"
    assert found.entries["monsters"].layer == "scenery"      # it may hide behind trees
    assert "clicking" in body["touch"]
    compile(code, "game.py", "exec")
    # A dark sky gets light score words.
    assert "SCORE_COLOUR = (240, 240, 240)" in code


def test_a_shooting_rule_can_be_changed_back(woods) -> None:
    box = Toolbox(woods)
    dispatch(box, "monsters to shoot", name="monsters", picture="assets/blue_monster.png",
             touch="shoot")
    dispatch(box, "dodge them instead", name="monsters", touch="avoid")
    code = woods.entrypoint_path.read_text(encoding="utf-8")
    assert "MOUSEBUTTONDOWN" not in code and "scene.touched(player" in code


@pytest.fixture(scope="module")
def kit():
    import importlib.util

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    pygame = pytest.importorskip("pygame")
    spec = importlib.util.spec_from_file_location("scene_kit_v3", looks.KIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pygame.init()
    screen = pygame.display.set_mode((640, 480))
    return module, pygame, screen


def test_the_kit_draws_a_list_of_looks_one_per_copy(kit) -> None:
    scene, pygame, screen = kit
    world = scene.Scene(screen)
    trees = world.add("trees", [scene.Colour("red"), scene.Colour("blue")], size=(40, 40),
                      at=(0, 100), count=4)
    screen.fill((0, 0, 0))
    world.draw()
    colours = [tuple(screen.get_at(thing.center))[:3] for thing in trees]
    assert colours[0] == colours[2] and colours[1] == colours[3]
    assert colours[0] != colours[1]
    assert world.report()[0]["look"] == "a plain colour, a plain colour"


# ============================================================================ the checks


def _controller(project, replies_):
    provider = ScriptedProvider(replies_)
    controller = AgentController(project, provider, Toolbox(project))
    controller.toolbox.playtest = lambda: None
    return controller, provider


def corrections(provider) -> list[str]:
    return [m.content for m in provider.calls[-1] if m.role == "user"][1:]


def test_trees_are_the_woods(woods) -> None:
    """The 8B's "Now the player is in the woods" about three trees was corrected as "The
    game has no woods", and its true reply was lost."""
    controller, provider = _controller(woods, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "tree", "drawing": "tree"}),)),
        Reply(text="I added the trees. Now the player is in the woods.")])
    turn = controller.send("Let's make this a game in the woods at night.")
    assert not corrections(provider)
    assert "woods" in turn.text


def test_a_picture_named_in_a_reply_is_used_not_edited(woods) -> None:
    """The 8B's true "I added the monster (the picture assets/blue_monster.png)" was
    corrected as a claim that the picture file had changed."""
    said = "I added the monster (the picture assets/blue_monster.png)."
    assert replies.files_said_wrongly(said, ["assets/blue_monster.png", "src/game.py"],
                                      set()) == []


def test_the_child_s_word_from_an_earlier_message_is_not_invention(woods) -> None:
    """"the monster" -- what the child had called blue_monster.png two messages before --
    drew "You have not seen assets/blue_monster.png" on every turn after."""
    controller, provider = _controller(woods, [
        Reply(text="Got it."),
        Reply(tool_calls=(ToolCall("game_object", {"name": "tree", "drawing": "tree"}),)),
        Reply(text="I added a tree. The monster can hide behind it.")])
    controller.send("I added the monster image now.")
    turn = controller.send("now add a tree")
    assert not any("You have not seen" in text for text in corrections(provider))
    assert "monster" in turn.text


def test_a_correction_after_a_request_does_not_quote_the_request(woods) -> None:
    from opennest.agent.controller import _SAY_IT_AGAIN

    controller, provider = _controller(woods, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "tree", "drawing": "tree"}),)),
        Reply(text="I added the tree and changed src/forest.py."),
        Reply(text="I added a tree.")])
    controller.send("add a tree to the woods please")
    sent = corrections(provider)
    assert sent and sent[-1].endswith(_SAY_IT_AGAIN)
    assert "add a tree to the woods please" not in sent[-1]


def test_a_reply_that_says_the_child_s_message_back_is_not_shown(woods) -> None:
    message = "I added tree images now... this should allow you to make the forest we walk"
    controller, _ = _controller(woods, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "trees", "drawing": "tree",
                                                   "count": 3}),)),
        Reply(text=message + ". The trees use a picture.")])
    turn = controller.send(message)
    assert not turn.text.startswith("I added tree images now")
    assert "3 trees" in turn.text


def test_the_job_is_offered_not_handed_back(woods) -> None:
    controller, _ = _controller(woods, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "tree", "drawing": "tree"}),)),
        Reply(text="I added the first tree. You can now make the forest we walk through.")])
    turn = controller.send("make the forest we walk through")
    assert "You can now make" not in turn.text
    assert turn.text.endswith("Want me to make the forest we walk through?")


def test_ideas_in_an_answer_stay_ideas(woods) -> None:
    controller, _ = _controller(woods, [
        Reply(text="Hi! Some ideas: Add a dragon that chases you. Ask for help to add one.")])
    turn = controller.send("any ideas for me?")
    assert "Add a dragon that chases you." in turn.text
    assert "Ask for help" not in turn.text


def test_pixels_are_not_said_to_a_child(project) -> None:
    controller, _ = _controller(project, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "tree", "drawing": "tree"}),)),
        Reply(text="I added a tree.\nThe monster at (100, 300) stays still.")])
    turn = controller.send("add a tree")
    assert "(100, 300)" not in turn.text and "I added a tree." in turn.text


def test_running_out_of_calls_says_what_was_made(woods) -> None:
    calls = [Reply(tool_calls=(ToolCall("game_object", {"name": f"tree{n}",
                                                        "drawing": "tree"}),))
             for n in range(14)]
    controller, _ = _controller(woods, calls)
    turn = controller.send("make a forest")
    assert turn.hit_call_limit
    assert "So far: I added" in turn.text and "tree" in turn.text
    assert "Here is where I got to" not in turn.text


def test_a_scene_turn_is_said_once_per_thing() -> None:
    from opennest.agent.tools import ToolResult

    def made(**record):
        return ("game_object", ToolResult(True, json.dumps(record),
                                          changed_files=("src/game.py",)))

    said = _scene_changes([
        made(object="sky", action="added", look="a ready-made sky drawing"),
        made(object="tree", action="added", look="a ready-made tree drawing"),
        made(object="tree", action="added", look="a ready-made tree drawing", count=2),
        made(object="tree", action="added", look="a ready-made tree drawing", count=3),
        made(object="monster", action="changed", look="the picture assets/blue_monster.png",
             picture="assets/blue_monster.png")])
    assert said == ("I added the sky and 3 trees; the monster is your blue_monster.png "
                    "now.")


def test_a_shape_is_never_offered_as_a_picture(woods) -> None:
    from opennest.agent.controller import _picture_word

    assert _picture_word("no_such_drawing", {"drawing": "square"}, "monster") == "monster"


# ============================================================================ getting started


def test_a_hello_is_answered_with_words_and_no_tools(woods) -> None:
    controller, provider = _controller(woods, [Reply(text="Hi! What shall we make?")])
    turn = controller.send("Hi Gary")
    assert turn.answered and provider.tools_offered[0] == []
    assert "just getting started" in provider.calls[0][-1].content


def test_asking_for_ideas_on_a_new_game_gets_the_way_in(woods) -> None:
    controller, provider = _controller(woods, [Reply(text="Here are three ideas.")])
    controller.send("What should I do first? any ideas for me?")
    asked = provider.calls[0][-1].content
    assert "three short ideas" in asked and "+ Add to Project" in asked


def test_what_they_asked_for_stays_in_front_of_gary(woods) -> None:
    controller, provider = _controller(woods, [Reply(text="ok"), Reply(text="ok")])
    controller.send("Let's make this a game in the woods at night with monsters")
    controller.send("add a tree")
    system = provider.calls[-1][0].content
    assert "WHAT THEY HAVE ASKED FOR, IN THEIR OWN WORDS" in system
    assert "“Let's make this a game in the woods at night with monsters”" in system


# ============================================================================ adding pictures


def _asset(name: str) -> assets.Asset:
    return assets.Asset(f"assets/{name}", "image", "asset", "PNG image, 54x72 pixels")


def test_six_pictures_are_one_message_with_how_to_use_them(monkeypatch) -> None:
    monkeypatch.setattr(assets, "can_interpret", lambda asset, model: False)
    trees = [_asset(f"tree_0{n}.png") for n in range(1, 7)]
    said = assets.import_messages(trees, None, things=["sky", "monster"], game=True)
    assert said.count("is in your project") + said.count("are in your project") == 1
    assert said.count("cannot see pictures") == 1
    assert "“use the tree pictures for the trees”" in said


def test_a_picture_named_for_a_thing_in_the_game_says_so(monkeypatch) -> None:
    monkeypatch.setattr(assets, "can_interpret", lambda asset, model: False)
    said = assets.import_messages([_asset("blue_monster.png")], None,
                                  things=["monster"], game=True)
    assert "“use the monster picture for the monster”" in said


def test_gary_is_told_a_numbered_set_is_one_set(woods) -> None:
    for n in range(1, 4):
        assets.import_file(woods, woods.directory / "assets" / f"tree_0{n}.png")
    block = assets.context_block(woods)
    assert "assets/tree_01.png to assets/tree_06.png" in block
    assert "a file's name is not a description" not in block


def test_replies_helpers() -> None:
    assert replies.handed_back("Run the game. Fix the player's movement to walk forward.") \
        == ["Fix the player's movement to walk forward."]
    assert replies.handed_back("Move the player with the arrow keys.") == []
    assert replies.handed_back("Make a PNG with a see-through background.") == []
    assert replies.as_offer("You can now make the forest we walk through.") == \
        "Want me to make the forest we walk through?"
    assert replies.as_offer("Ask for help to add one.") == ""
    assert replies.echoes("I added tree images now, so make the forest. The trees...",
                          "I added tree images now, so make the forest")
    assert not replies.echoes("I added six trees.", "I added tree images now, make it")
    assert replies.is_greeting("Hi Gary") and replies.is_greeting("hello there!")
    assert not replies.is_greeting("Hi Gary, make a space game")


# ============================================================================ round two


def test_a_road_given_the_top_left_corner_goes_along_the_bottom(woods) -> None:
    """The 4B gave every thing at [0, 0] -- nowhere in particular -- and the road ran
    along the top of the window, the trees standing on it off the screen."""
    body = dispatch(Toolbox(woods), "night woods", name="road", drawing="road",
                    at=[0, 0], size=[640, 100])
    assert scene(woods).entries["road"].literals["at"] == (0, 380)
    assert any("along the bottom" in note for note in body["notes"])


def test_a_thing_placed_on_the_top_edge_that_stands_stands_on_the_ground(woods) -> None:
    box = Toolbox(woods)
    dispatch(box, "a forest", name="ground", drawing="ground")
    dispatch(box, "a forest", name="trees", drawing="tree", at=[0, 0], count=4)
    assert scene(woods).entries["trees"].literals["on"] == "ground"


def test_a_tree_picture_not_added_yet_is_drawn_as_a_tree(woods) -> None:
    """The 4B asked for assets/tree.png before the child had added any trees; refused,
    the game had no trees at all."""
    body = dispatch(Toolbox(woods), "woods", name="trees", picture="assets/tree.png",
                    count=5)
    assert "Tree(" in scene(woods).entries["trees"].look
    assert any("until there is one" in note for note in body["notes"])


def test_saying_i_see_about_the_code_is_not_describing_a_picture() -> None:
    picture = [assets.Asset("assets/blue_monster.png", "image", "asset", "PNG", False)]
    assert assets.invented_description(
        "The trees are not moving. I see the code draws them once.", "why?", picture) is None
    assert assets.invented_description(
        "I can see the picture clearly: it has wings.", "why?", picture) is not None


def test_the_picture_called_by_its_name_is_a_name_once_the_child_has_used_it() -> None:
    picture = [assets.Asset("assets/blue_monster.png", "image", "asset", "PNG", False)]
    said = "I added the monster image now."
    assert assets.invented_description(
        "I added the monster using the blue monster image.", said, picture) is None
    assert assets.invented_description(
        "I made the spaceship the blue monster image.", "use it for my spaceship",
        picture) is not None


def test_which_pictures_and_how_they_are_drawn_are_not_things() -> None:
    found = replies.child_nouns(
        "your job is to replace the `shapes` or `drawing` with the correct pictures I added")
    assert not found & {"correct", "drawing", "shapes", "pictures"}


def test_the_scene_is_listed_as_words_not_as_code(woods) -> None:
    from opennest.agent import evidence

    dispatch(Toolbox(woods), "a sky", name="sky", drawing="sky")
    block = evidence.checked_block(woods)
    assert "\n  * sky: a sky drawing" in block and "\n    sky:" not in block


def test_getting_started_is_only_for_a_game_not_yet_begun(woods) -> None:
    controller, provider = _controller(woods, [Reply(text="Ideas!"), Reply(text="Ideas!")])
    dispatch(controller.toolbox, "a sky", name="sky", drawing="sky")
    controller.send("any ideas for me?")
    assert "just getting started" not in provider.calls[-1][-1].content


KIT_V2 = (Path(__file__).resolve().parent / "fixtures" / "scene_kit_v2.txt").read_text(
    encoding="utf-8")


def test_the_v2_kit_is_known_exactly_and_brought_up_to_date(woods) -> None:
    from opennest.graphics.game_object import KIT_PATH

    assert looks.is_earlier_kit(KIT_V2) and looks.kit_version(KIT_V2) == 2
    dispatch(Toolbox(woods), "a sky", name="sky", drawing="sky")
    kit = woods.directory / KIT_PATH
    kit.write_text(KIT_V2, encoding="utf-8")
    body = dispatch(Toolbox(woods), "a forest", name="trees",
                    picture="assets/tree_01.png", count=6)
    assert kit.read_text(encoding="utf-8") == looks.kit_source()
    assert "one per copy" in body["look"]


def test_a_hand_changed_old_kit_is_given_one_picture_not_a_list(woods) -> None:
    from opennest.graphics.game_object import KIT_PATH

    dispatch(Toolbox(woods), "a sky", name="sky", drawing="sky")
    kit = woods.directory / KIT_PATH
    kit.write_text(KIT_V2.replace("SMOOTH = 3", "SMOOTH = 2"), encoding="utf-8")
    dispatch(Toolbox(woods), "a forest", name="trees",
             picture=["assets/tree_01.png", "assets/tree_02.png"], count=4)
    look = scene(woods).entries["trees"].look
    assert look == 'Picture("assets/tree_01.png")' and "SMOOTH = 2" in kit.read_text()


def test_a_word_of_a_picture_s_name_about_something_else_is_not_about_the_picture() -> None:
    """"The sky is dark blue" was taken for a description of blue_monster.png."""
    picture = [assets.Asset("assets/blue_monster.png", "image", "asset", "PNG", False)]
    said = "I added the monster image now."
    assert assets.invented_description("The sky is dark blue.", "make it night", picture) \
        is None
    assert assets.invented_description("The blue monster hides.", "make it night",
                                       picture) == "assets/blue_monster.png"
    # Once the child calls it by its name, the name is theirs.
    assert assets.invented_description("The blue monster hides.", said, picture) is None


def test_a_tool_written_into_the_game_as_code_is_refused(woods) -> None:
    """The 8B wrote ``game_object(name='sky', color='black')`` into src/game.py; the game
    stopped with a NameError and three repairs could not save it."""
    box = Toolbox(woods)
    result = box.dispatch("edit_file", {
        "path": "src/game.py",
        "old_text": "player = pygame.Rect(WIDTH // 2, HEIGHT // 2, PLAYER_SIZE, PLAYER_SIZE)",
        "new_text": "player = pygame.Rect(WIDTH // 2, HEIGHT // 2, PLAYER_SIZE, PLAYER_SIZE)"
                    "\ngame_object(name='sky', color='black')"})
    assert not result.ok and result.reason == "tool_as_code"
    assert "game_object(" not in woods.entrypoint_path.read_text(encoding="utf-8")


def test_a_whole_game_request_is_told_how_to_build_one(woods) -> None:
    controller, provider = _controller(woods, [Reply(text="ok")])
    controller.send("Let's make this a game in the woods at night. A first person shooter.")
    sent = provider.calls[0][-1].content
    assert "this asks for a whole game" in sent and "closest 2D version" in sent
    assert controller.history[1].content.startswith("Let's make this a game")
    assert "whole game" not in controller.history[1].content


def test_a_small_request_is_not(woods) -> None:
    controller, provider = _controller(woods, [Reply(text="ok")])
    controller.send("make the player blue")
    assert "whole game" not in provider.calls[0][-1].content


def test_the_player_does_not_take_a_picture_named_for_another_thing_in_the_game(woods) -> None:
    """The 4B made the player blue_monster.png while the scene had its monster."""
    box = Toolbox(woods)
    dispatch(box, "a monster", name="monster", shapes=[{"circle": [15, 15, 15]}])
    message = ("I added the monster image now. the player must be walking forward through "
               "the trees and the monster will hide behind the trees.")
    box.message = (message, ())
    result = box.dispatch("game_object", {"name": "player",
                                          "picture": "assets/blue_monster.png"})
    assert not result.ok and result.reason == "picture_not_asked"
    assert "the monster" in json.loads(result.content)["message"]
    assert "player" not in scene(woods).entries


def test_the_player_still_takes_the_picture_the_child_gives_it(woods) -> None:
    body = dispatch(Toolbox(woods), "use my monster picture as the player", name="player",
                    picture="assets/blue_monster.png")
    assert body["picture"] == "assets/blue_monster.png"


def test_the_prompt_s_own_example_is_not_a_reply(woods) -> None:
    controller, _ = _controller(woods, [
        Reply(tool_calls=(ToolCall("game_object", {"name": "tree", "drawing": "tree"}),)),
        Reply(text="I found a problem. I'm fixing it.")])
    turn = controller.send("add a tree")
    assert "found a problem" not in turn.text and "tree" in turn.text


def test_trees_with_no_ground_stand_on_the_bottom_of_the_screen(woods) -> None:
    """The 8B gave its forest no usable place and the game no ground: the row of trees
    hung across the middle of the window."""
    dispatch(Toolbox(woods), "a forest", name="trees", picture="assets/tree_01.png", count=6,
             at="tree_01.png to tree_06.png")
    entry = scene(woods).entries["trees"]
    assert entry.literals["at"][1] + entry.literals["size"][1] == 480


def test_the_prompt_s_own_example_is_not_an_answer(woods) -> None:
    controller, _ = _controller(woods, [Reply(text="I found a problem. I'm fixing it.")] * 3)
    turn = controller.send("Gary, whay is a tree moving? You are not making a good game.")
    assert "found a problem" not in turn.text and "Right now" in turn.text


def test_trees_asked_to_stand_on_a_ground_there_is_not_stand_on_the_bottom(woods) -> None:
    dispatch(Toolbox(woods), "woods", name="tree", drawing="tree", size=[80, 120],
             at=[100, 100], count=5, on="ground")
    entry = scene(woods).entries["tree"]
    assert entry.literals["at"][1] + entry.literals["size"][1] == 480


def test_shapes_placed_on_the_screen_are_moved_into_their_own_box(woods) -> None:
    """A 30x30 monster given a circle at (150, 150) grew a 168x170 box with a dot in it."""
    body = dispatch(Toolbox(woods), "a monster", name="monster", size=[30, 30],
                    at=[150, 150], shapes=[{"circle": [150, 150, 15], "color": "darkred"}])
    assert body["drawn_size"] == [30, 30]
    assert "Circle(15, 15, 15" in scene(woods).entries["monster"].look


def test_a_you_changed_nothing_correction_says_what_each_thing_looks_like(woods) -> None:
    """Told only "Other things in the game: sky, tree, monster", the 4B said the six tree
    pictures it had added the turn before "were not added to the game"."""
    controller, provider = _controller(woods, [
        Reply(text="I replaced the tree drawing with the 6 tree pictures."),
        Reply(text="The trees already wear your six pictures.")])
    dispatch(controller.toolbox, "a forest", name="trees", picture="assets/tree_01.png",
             count=6)
    controller.send("your job is to replace the drawing with the correct pictures I added")
    said = corrections(provider)[-1]
    assert "already is" in said and "tree_06.png" in said


def test_an_unhappy_child_is_answered_with_what_would_make_it_better(woods) -> None:
    controller, provider = _controller(woods, [Reply(text="ok")])
    controller.send("Gary, whay is a tree moving? You are not making a good game.")
    assert "they are not happy with the game" in provider.calls[0][-1].content


def test_one_picture_per_call_in_one_message_is_one_tree_per_picture(woods) -> None:
    """The 8B planted the forest as six calls named "tree", tree_01.png at x 100 to
    tree_06.png at x 600, and each replaced the last -- one tree."""
    box = Toolbox(woods)
    dispatch(box, "a tree", name="tree", drawing="tree", at=[100, 300])
    message = "I added tree images now... this should allow you to make the forest"
    for n in range(1, 7):
        body = dispatch(box, message, name="tree", picture=f"assets/tree_0{n}.png",
                        at=[100 * n, 360], size=[1086, 1448])
    entry = scene(woods).entries["tree"]
    assert body["count"] == 6 and len(entry.literals["at"]) == 6
    assert all(f"tree_0{n}.png" in entry.look for n in range(1, 7))


def test_a_thing_given_a_picture_and_then_moved_in_one_message_moves(woods) -> None:
    box = Toolbox(woods)
    dispatch(box, "a tree", name="tree", drawing="tree", at=[100, 300])
    dispatch(box, "my tree, on the right", name="tree", picture="assets/tree_01.png")
    dispatch(box, "my tree, on the right", name="tree", at=[500, 300])
    assert scene(woods).entries["tree"].literals["at"] == (500, 300)


def test_an_edit_of_a_tool_call_the_game_has_not_got_is_explained(woods) -> None:
    result = Toolbox(woods).dispatch("edit_file", {
        "path": "src/game.py", "old_text": "game_object('sky', drawing='sky')",
        "new_text": "game_object('sky', picture='assets/tree_06.png')"})
    assert not result.ok and "one of your tools, not code in the game" in result.content


def test_a_sentence_that_would_not_read_without_its_place_goes() -> None:
    said = ("The blue monster is at (150, 350) with touch scoring a point. Trees are already "
            "in place at (100, 300) with six copies.")
    assert replies.without_coordinates(said) == "Trees are already in place with six copies."
