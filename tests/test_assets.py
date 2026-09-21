"""Importing files into a project, and telling the model the truth about them.

WORKORDER_01 sections 10-13 and DoD 26-28.

The end-to-end case at the bottom is the one the phase exists for: a child drags in a
PNG, says "use this picture for my spaceship", and the project ends up using it -- with
a model that never saw a single pixel. It runs on the scripted provider from conftest.py
for the reason tests/test_rollover.py does: whether a 4B model *chooses* the right edit
is a separate, measured question, and whether the application hands it honest material
to work from is this one.

Image fixtures are assembled byte by byte rather than with Pillow. Pillow lives in
requirements/projects.txt -- a package child projects may import -- so a developer who
installed only the application and its dev tooling does not have it, and the suite has
to stay hermetic.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.ai.provider import ModelInfo, Reply, ToolCall
from opennest.ai.router import models_that_can_read
from opennest.assets import describe, kinds
from opennest.assets import manager as assets
from opennest.memory import project_bible
from tests.conftest import ScriptedProvider

# --------------------------------------------------------------- image fixtures


def png_bytes(width: int, height: int, *, alpha: bool = True) -> bytes:
    """A real, decodable PNG of the given size."""
    colour_type = 6 if alpha else 2
    channels = 4 if alpha else 3
    pixel = bytes([0, 0, 0, 255][:channels])
    raw = b"".join(b"\x00" + pixel * width for _ in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def jpeg_bytes(width: int, height: int) -> bytes:
    """Enough of a JPEG to carry a start-of-frame marker."""
    frame = (
        b"\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + frame + b"\xff\xd9"


def gif_bytes(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00\x3b"


def jpeg_with_exif_thumbnails(width: int, height: int, segments: int = 3) -> bytes:
    """A JPEG shaped like a camera's: the frame header sits behind EXIF blocks.

    A JPEG segment cannot exceed 65533 bytes, so a real photo carrying a thumbnail and
    maker notes uses several -- which is how the dimensions end up further into the file
    than a small header read would reach.
    """
    filler = 60_000
    app = b"".join(
        b"\xff\xe1" + struct.pack(">H", filler + 2) + b"\x00" * filler
        for _ in range(segments)
    )
    frame = (
        b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app + frame + b"\xff\xd9"


SPACESHIP = png_bytes(64, 64, alpha=True)

BLIND = ModelInfo(id="local", name="Qwen3 4B", provider="mlx", supports_images=False)
SIGHTED = ModelInfo(id="cloud", name="Claude", provider="anthropic", supports_images=True)


@pytest.fixture
def dropped(tmp_path):
    """A file sitting outside the project, as if just dragged from Finder."""
    def _make(name: str, content: bytes | str) -> object:
        source = tmp_path / "dragged" / name
        source.parent.mkdir(exist_ok=True)
        if isinstance(content, str):
            source.write_text(content, encoding="utf-8")
        else:
            source.write_bytes(content)
        return source
    return _make


# --------------------------------------------------------------- classification

def test_a_picture_becomes_a_project_asset(project, dropped) -> None:
    asset = assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    assert asset.path == "assets/spaceship.png"
    assert asset.kind == kinds.IMAGE
    assert asset.role == kinds.ASSET


def test_a_table_becomes_data(project, dropped) -> None:
    asset = assets.import_file(project, dropped("birds.csv", "day,count\n1,3\n"))
    assert asset.path == "data/birds.csv"
    assert asset.role == kinds.DATASET


def test_a_pdf_becomes_reference_material(project, dropped) -> None:
    asset = assets.import_file(project, dropped("wiring.pdf", b"%PDF-1.4\n%%EOF\n"))
    assert asset.path == "docs/wiring.pdf"
    assert asset.role == kinds.REFERENCE


def test_source_code_lands_with_the_source(project, dropped) -> None:
    asset = assets.import_file(project, dropped("helper.py", "x = 1\n"))
    assert asset.path == "src/helper.py"
    assert asset.role == kinds.SOURCE


def test_the_child_can_say_it_is_something_else(project, dropped) -> None:
    """Section 12: the user should be able to change the classification."""
    asset = assets.import_file(
        project, dropped("diagram.png", SPACESHIP), role=kinds.REFERENCE
    )
    assert asset.path == "docs/diagram.png"
    assert asset.kind == kinds.IMAGE  # what it is does not change; what it is for does


def test_the_bytes_beat_the_file_name(project, dropped) -> None:
    """A JPEG called .png is a JPEG. Describing it as a PNG would be an invention."""
    asset = assets.import_file(project, dropped("ship.png", jpeg_bytes(20, 10)))
    assert "JPEG" in asset.summary
    assert "20x10" in asset.summary


def test_a_text_file_named_like_an_image_is_not_treated_as_one(project, dropped) -> None:
    asset = assets.import_file(project, dropped("notes.png", "this is not a picture"))
    assert asset.kind == kinds.OTHER
    assert "image" not in asset.summary.lower()


# --------------------------------------------------------------- derived facts

def test_a_png_gives_up_its_size_and_transparency(tmp_path) -> None:
    path = tmp_path / "ship.png"
    path.write_bytes(SPACESHIP)
    described = describe.describe(path)
    assert described.summary == "PNG image, 64x64 pixels, has transparency"
    assert not described.readable


def test_a_png_without_an_alpha_channel_says_so(tmp_path) -> None:
    path = tmp_path / "flat.png"
    path.write_bytes(png_bytes(8, 4, alpha=False))
    assert describe.describe(path).summary == "PNG image, 8x4 pixels, no transparency"


def test_a_gif_gives_up_its_size(tmp_path) -> None:
    path = tmp_path / "loop.gif"
    path.write_bytes(gif_bytes(120, 90))
    assert "120x90 pixels" in describe.describe(path).summary


def test_a_camera_jpeg_with_exif_thumbnails_still_gives_its_size(tmp_path) -> None:
    """The frame header sits ~180 KB in, past the prefix a normal describe() reads.

    Reporting "size could not be read" for an ordinary holiday photo would be honest
    but useless, so one deeper read is tried before giving up.
    """
    path = tmp_path / "IMG_4821.jpg"
    path.write_bytes(jpeg_with_exif_thumbnails(4032, 3024))
    assert path.stat().st_size > describe.HEAD_BYTES
    assert "4032x3024 pixels" in describe.describe(path).summary


def test_a_frame_header_beyond_even_the_deep_read_says_unknown(tmp_path, monkeypatch) -> None:
    """The honest failure is still there underneath, for a file too odd to parse."""
    monkeypatch.setattr(describe, "HEAD_BYTES", 1024)
    monkeypatch.setattr(describe, "DEEP_SCAN_BYTES", 2048)
    path = tmp_path / "huge_exif.jpg"
    path.write_bytes(jpeg_with_exif_thumbnails(800, 600))
    assert "could not be read" in describe.describe(path).summary


def test_an_unreadable_header_reports_unknown_rather_than_guessing(tmp_path) -> None:
    """Section 13 is about not inventing. A missing fact is said, not filled in."""
    path = tmp_path / "truncated.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    summary = describe.describe(path).summary
    assert "could not be read" in summary
    assert not any(character.isdigit() for character in summary)  # nothing invented


def test_nothing_derived_describes_what_the_picture_shows(tmp_path) -> None:
    """The one invariant this whole module exists for.

    The filename is the child's word for the file, not evidence about the pixels. A
    description that echoed it back would read as though something had looked.
    """
    path = tmp_path / "red-spaceship-with-wings.png"
    path.write_bytes(SPACESHIP)
    summary = describe.describe(path).summary.lower()
    for word in ("red", "spaceship", "wings"):
        assert word not in summary


def test_a_table_is_described_by_its_columns_and_row_count(tmp_path) -> None:
    path = tmp_path / "birds.csv"
    path.write_text("day,species,count\n1,robin,3\n2,crow,5\n3,robin,1\n")
    described = describe.describe(path)
    assert "columns: day, species, count" in described.summary
    assert "3 rows" in described.summary
    assert described.readable  # the model can just read it


def test_a_json_object_is_described_by_its_keys(tmp_path) -> None:
    path = tmp_path / "sensor.json"
    path.write_text('{"pin": 4, "mode": "input"}')
    assert "keys: pin, mode" in describe.describe(path).summary


# --------------------------------------------------------------- copy-in

def test_the_original_can_be_thrown_away_afterwards(project, dropped) -> None:
    """Section 11: do not depend on the original location of a user's file."""
    source = dropped("spaceship.png", SPACESHIP)
    asset = assets.import_file(project, source)
    source.unlink()
    assert (project.directory / asset.path).read_bytes() == SPACESHIP


def test_importing_the_same_name_twice_keeps_both(project, dropped) -> None:
    first = assets.import_file(project, dropped("ship.png", SPACESHIP))
    second = assets.import_file(project, dropped("ship.png", png_bytes(8, 8)))
    assert first.path == "assets/ship.png"
    assert second.path == "assets/ship-2.png"
    assert (project.directory / first.path).read_bytes() == SPACESHIP


def test_importing_never_overwrites_the_projects_own_code(project, dropped) -> None:
    before = project.entrypoint_path.read_text()
    asset = assets.import_file(project, dropped("game.py", "print('hi')\n"))
    assert asset.path == "src/game-2.py"
    assert project.entrypoint_path.read_text() == before


def test_a_credential_file_is_refused(project, dropped) -> None:
    with pytest.raises(assets.AssetError):
        assets.import_file(project, dropped(".env", "OPENAI_API_KEY=sk-abc\n"))


def test_dragging_a_folder_says_what_to_do_instead(project, tmp_path) -> None:
    folder = tmp_path / "my pictures"
    folder.mkdir()
    with pytest.raises(assets.AssetError, match="folder"):
        assets.import_file(project, folder)


def test_something_far_too_big_is_refused(project, dropped, monkeypatch) -> None:
    monkeypatch.setattr(assets, "MAX_IMPORT_BYTES", 10)
    with pytest.raises(assets.AssetError, match="too big"):
        assets.import_file(project, dropped("huge.csv", "x" * 100))


def test_a_name_that_tries_to_escape_cannot(project, dropped) -> None:
    source = dropped("ship.png", SPACESHIP)
    asset = assets.import_file(project, source)
    # Directory components are dropped before anything touches the filesystem.
    assert assets.safe_name("../../../etc/passwd") == "passwd"
    assert asset.path.startswith("assets/")


# --------------------------------------------------------------- what the model is told

def block(project, model=BLIND, attached=()):
    return assets.context_block(project, model, attached=attached)


def test_a_project_with_no_assets_says_nothing(project) -> None:
    assert block(project) == ""


def test_the_block_carries_the_path_and_the_real_size(project, dropped) -> None:
    assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    text = block(project)
    assert "assets/spaceship.png" in text
    assert "64x64 pixels" in text
    assert "has transparency" in text


def test_a_model_that_cannot_see_is_told_so_plainly(project, dropped) -> None:
    assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    text = block(project)
    assert "NOBODY HAS LOOKED INSIDE THESE FILES" in text
    assert "never guess" in text


def test_what_the_child_says_about_a_file_is_still_allowed(project, dropped) -> None:
    """Not seeing the picture is not the same as ignoring "this is my spaceship".

    The child naming the thing is information; the model inventing a description is not.
    The block has to permit the first while forbidding the second, or DoD 27 cannot work.
    """
    assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    assert "If they tell you what one is, believe them" in block(project)


def test_a_model_that_can_see_is_not_told_it_cannot(project, dropped) -> None:
    """Capability-driven, not a hard-coded apology. Adding a vision model is a data edit."""
    assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    text = block(project, model=SIGHTED)
    assert "assets/spaceship.png" in text
    assert "NOBODY HAS LOOKED" not in text


def test_a_readable_file_is_never_called_unread(project, dropped) -> None:
    assets.import_file(project, dropped("birds.csv", "day,count\n1,3\n"))
    text = block(project)
    assert "columns: day, count" in text
    assert "NOBODY HAS LOOKED" not in text


def test_a_pdf_is_unread_whichever_model_is_in_use(project, dropped) -> None:
    """Open Nest has no PDF extractor, so this is an application limit, not a model one."""
    assets.import_file(project, dropped("wiring.pdf", b"%PDF-1.4\n%%EOF\n"))
    assert "NOBODY HAS LOOKED" in block(project, model=SIGHTED)


def test_an_attachment_is_named_as_belonging_to_this_message(project, dropped) -> None:
    asset = assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    text = block(project, attached=[asset])
    assert "They attached this to the message you are answering: assets/spaceship.png" in text


# --------------------------------------------------------------- offering a model

def test_no_local_model_can_read_a_picture_today(project) -> None:
    assert models_that_can_read("image") == ()


def test_turning_cloud_on_surfaces_the_models_that_can(project) -> None:
    """Section 13's "offer a compatible model", driven by models.json rather than code."""
    names = {entry.info.name for entry in models_that_can_read("image", allow_cloud=True)}
    assert {"Claude", "OpenAI"} <= names


def test_the_import_message_says_what_the_model_cannot_do(project, dropped) -> None:
    asset = assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    message = assets.import_message(asset, BLIND)
    assert "spaceship.png is in your project." in message
    assert "Qwen3 4B cannot see pictures" in message
    assert "64x64 pixels" in message


def test_the_import_message_offers_a_model_that_can(project, dropped) -> None:
    asset = assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    message = assets.import_message(asset, BLIND, alternatives=[SIGHTED])
    assert "Claude can read it." in message


def test_the_import_message_stays_quiet_when_there_is_nothing_to_explain(
    project, dropped
) -> None:
    asset = assets.import_file(project, dropped("birds.csv", "day,count\n1,3\n"))
    assert assets.import_message(asset, BLIND) == "birds.csv is in your project."


# --------------------------------------------------------------- in the agent loop

def build(project, replies, *, model=None):
    provider = ScriptedProvider(replies)
    if model is not None:
        provider.info = model
    return AgentController(project, provider, Toolbox(project)), provider


def test_attaching_a_picture_does_not_add_a_fifth_tool(project, dropped) -> None:
    """SPIKES.md section 4: the set is four wide, and the asset layer must not widen it."""
    asset = assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    controller, provider = build(project, [Reply(text="ok")])
    controller.send("use this", attachments=[asset])
    offered = {t["function"]["name"] for t in provider.tools_offered[0]}
    assert offered == {"read_file", "edit_file", "write_file", "run_project"}
    assert "list_assets" not in offered


def test_an_attachment_does_not_linger_onto_the_next_message(project, dropped) -> None:
    asset = assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    controller, provider = build(project, [Reply(text="ok"), Reply(text="ok")])
    controller.send("use this", attachments=[asset])
    controller.send("now make it faster")
    prompt = provider.system_prompt
    assert "assets/spaceship.png" in prompt          # the file is still in the project
    assert "attached this to the message" not in prompt  # but it is not "this" any more


def test_a_project_with_no_assets_has_an_unchanged_prompt(project) -> None:
    controller, provider = build(project, [Reply(text="ok")])
    controller.send("hello")
    assert "FILES THEY HAVE ADDED" not in provider.system_prompt


def test_importing_a_file_keeps_project_memory_readable(project, dropped) -> None:
    """The bible's Asset Library is rewritten from disk, so an import lands in memory."""
    assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    assets.import_file(project, dropped("wiring.pdf", b"%PDF-1.4\n%%EOF\n"))
    project_bible.save(project, project_bible.load(project))

    text = project_bible.path_for(project).read_text()
    assert "## Assets\n- assets/spaceship.png\n- docs/wiring.pdf" in text
    # The derived detail stays in the live block, not here: the same reasoning Phase 4
    # used for project_state.md, so the facts are not in the prompt twice.
    assert "64x64" not in text


# ------------------------------------------- catching it describing what it cannot see
#
# Every REPLY_* below is a verbatim reply the real Qwen3 4B produced in
# spikes/spike_asset_honesty.py with the shipped prompt (SPIKES.md section 10). The
# honest ones must not be flagged and the invented ones must be, so these are the
# measurement turned into a regression test rather than failures someone imagined.

DRAGON = "assets/red-dragon-with-wings.png"


def unread(path=DRAGON):
    return [assets.Asset(path=path, kind=kinds.IMAGE, role=kinds.ASSET,
                         summary="PNG image, 96x64 pixels, has transparency",
                         readable=False)]


REPLY_CLAIMED_SIGHT = (
    "Yes, the dragon in the picture has wings. I see them clearly. I'll use that image "
    "for the player character."
)
REPLY_INVENTED = (
    "I don't have access to the image file to describe it. But I know it's a 96x64 "
    "pixel PNG with transparency. It's a red dragon with wings."
)
REPLY_NAME_AS_DESCRIPTION = (
    "I'll use the red dragon image as the spaceship. I changed src/game.py to load the "
    "dragon image and display it as the player ship."
)
REPLY_HONEST = (
    "I don't know what's in the image. I only know its name, size, and location: "
    "assets/red-dragon-with-wings.png. It's a PNG file with transparency."
)
REPLY_HONEST_NAMING_THE_FILE = (
    "I don't have access to the image content. I know it's a PNG file named "
    "`red-dragon-with-wings.png`, 96x64 pixels, with transparency. That's all I can say."
)
REPLY_USING_THE_FACTS = "The picture is 96 pixels wide and 64 pixels tall."
REPLY_CONFABULATED_REASON = (
    "The picture has transparency. I can see that from its file name and the fact it's "
    "used in a game with alpha blending."
)


def test_claiming_to_have_seen_it_is_caught(project) -> None:
    """The worst measured failure, and the one the prompt never fixed."""
    assert assets.invented_description(
        REPLY_CLAIMED_SIGHT, "Does the dragon in my picture have wings?", unread()
    ) == DRAGON


def test_describing_it_from_the_filename_is_caught(project) -> None:
    assert assets.invented_description(
        REPLY_INVENTED, "What does my picture look like?", unread()
    ) == DRAGON


def test_using_the_name_as_a_description_is_caught(project) -> None:
    assert assets.invented_description(
        REPLY_NAME_AS_DESCRIPTION, "Use this picture for my spaceship.", unread()
    ) == DRAGON


def test_an_honest_refusal_is_not_flagged(project) -> None:
    for reply in (REPLY_HONEST, REPLY_HONEST_NAMING_THE_FILE, REPLY_USING_THE_FACTS):
        assert assets.invented_description(reply, "What is in my picture?", unread()) is None


def test_naming_the_file_is_not_describing_it(project) -> None:
    """"I can't describe what's in red-dragon.png" is the right answer, not a failure."""
    reply = "I can't describe what's in `red-dragon-with-wings.png` without seeing it."
    assert assets.invented_description(reply, "What is in it?", unread()) is None


def test_repeating_the_childs_own_word_is_not_invention(project) -> None:
    """The block tells it to believe them when they say what a file is."""
    reply = "I'll put your dragon at the middle of the screen."
    assert assets.invented_description(
        reply, "use my dragon picture for the player", unread()
    ) is None


def test_an_ordinary_word_in_a_filename_cannot_trigger_an_accusation(project) -> None:
    """The first version of this check fired on "with", from red-dragon-WITH-wings.

    An accusation triggered by an English function word is worse than the failure it
    guards against, so every common word a filename can contribute is excluded.
    """
    reply = "I put it on screen with the other sprites. That should work for now."
    assert assets.invented_description(reply, "add my picture", unread()) is None
    noisy = unread("assets/new-photo-copy-2-final-version.png")
    assert assets.invented_description(
        "I made a new copy of the final version for the test.", "add it", noisy
    ) is None


def test_i_see_what_you_mean_is_not_a_claim_to_have_looked(project) -> None:
    reply = "I see what you mean. Let's make it bigger."
    assert assets.invented_description(reply, "it's too small", unread()) is None


def test_a_confabulated_reason_is_tolerated(project) -> None:
    """A known limit, recorded rather than papered over.

    "I can see that from its file name" invents a *reason* for a fact that was in the
    prompt and is correct. Widening the check to catch it would also catch ordinary
    replies, and the child is not misled about the picture -- so it is left alone.
    """
    assert assets.invented_description(
        REPLY_CONFABULATED_REASON, "is my picture see-through?", unread()
    ) is None


def test_a_file_that_was_actually_read_is_never_flagged(project, dropped) -> None:
    csv = assets.import_file(project, dropped("dragon-counts.csv", "day,count\n1,3\n"))
    assert assets.can_interpret(csv, BLIND)
    assert assets.invented_description("The dragon counts rise on day 3.", "graph it", []) is None


def test_the_agent_pulls_the_model_up_and_it_corrects_itself(project, dropped) -> None:
    """End to end: the measured lie, caught by the application, retried honestly."""
    source = dropped("red-dragon-with-wings.png", SPACESHIP)
    asset = assets.import_file(project, source)
    controller, provider = build(project, [
        Reply(text=REPLY_CLAIMED_SIGHT),
        Reply(text="I have not seen the picture, so I do not know what it shows. "
                   "I put it on screen as the player."),
    ], model=BLIND)

    turn = controller.send("Does the dragon in my picture have wings?", attachments=[asset])

    assert turn.corrected_invention
    assert "I have not seen the picture" in turn.text
    assert any("You have not seen assets/red-dragon-with-wings.png" in m.content
               for m in provider.calls[-1])


def test_an_honest_reply_costs_no_extra_round_trip(project, dropped) -> None:
    asset = assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    controller, provider = build(project, [Reply(text=REPLY_HONEST)], model=BLIND)
    turn = controller.send("What is in my picture?", attachments=[asset])
    assert not turn.corrected_invention
    assert len(provider.calls) == 1


def test_a_model_that_can_see_is_never_pulled_up(project, dropped) -> None:
    """Capability-driven: with a vision model there is nothing dishonest about it."""
    asset = assets.import_file(project, dropped("red-dragon-with-wings.png", SPACESHIP))
    controller, provider = build(project, [Reply(text=REPLY_CLAIMED_SIGHT)], model=SIGHTED)
    turn = controller.send("Does it have wings?", attachments=[asset])
    assert not turn.corrected_invention
    assert len(provider.calls) == 1


# --------------------------------------------------------------- DoD 26-28

def test_a_picture_the_model_never_saw_becomes_the_players_sprite(project, dropped) -> None:
    """DoD 26-28, end to end.

    26 -- the child drags a spaceship PNG into the project.
    27 -- they say "Use this picture for my spaceship."
    28 -- the project is updated to use it.

    The model in this test has ``supports_images=False``, exactly like all four entries
    in models.json. It is handed the path, the real dimensions and the transparency
    flag, and told in as many words that it has not seen the picture. That is enough to
    do the job, and section 13 requires that it is all it gets.
    """
    # 26.
    asset = assets.import_file(project, dropped("spaceship.png", SPACESHIP))
    assert asset.path == "assets/spaceship.png"
    assert (project.directory / "assets" / "spaceship.png").is_file()

    # 27.
    controller, provider = build(project, [
        Reply(tool_calls=(ToolCall("edit_file", {
            "path": "src/game.py",
            "old_text": "player = pygame.Rect(WIDTH // 2, HEIGHT // 2, "
                        "PLAYER_SIZE, PLAYER_SIZE)",
            "new_text": 'sprite = pygame.image.load("assets/spaceship.png").convert_alpha()'
                        "\nplayer = sprite.get_rect(center=(WIDTH // 2, HEIGHT // 2))",
        }),)),
        Reply(text="Your picture is the player now. I have not seen it, so tell me if it "
                   "looks wrong."),
    ], model=BLIND)
    turn = controller.send("Use this picture for my spaceship.", attachments=[asset])

    # What the model was given: the facts, and the limits of them.
    prompt = provider.calls[0][0].content
    assert "assets/spaceship.png -- PNG image, 64x64 pixels, has transparency" in prompt
    assert "They attached this to the message you are answering" in prompt
    assert "NOBODY HAS LOOKED INSIDE THESE FILES" in prompt

    # 28 -- the project uses it.
    game = project.entrypoint_path.read_text()
    assert 'pygame.image.load("assets/spaceship.png")' in game
    assert any(result.changed_files for _, result in turn.tool_results)
    assert not turn.gave_up
