"""A model that can see the child's pictures -- and the honesty rules kept until it has.

SPIKES.md section 32. A local vision model (Qwen3-VL, "Gary Fast" and "Gary Smart") is
shown a picture's pixels through the vision engine, and what it says the picture shows
is kept with the picture (``assets.look``). These tests pin the half that does not need
a model: a picture counts as seen only once its pixels really reached one and the answer
is recorded -- never because the model in use *could* see (SPIKES.md section 12) -- and
everything that follows from that, from the prompt to the setup wizard.

The provider here is scripted, like everywhere in the suite: whether Qwen3-VL describes a
monster well is measured in SPIKES.md section 32, not asserted.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

import pytest

from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.ai import provider as provider_module
from opennest.ai import router
from opennest.ai.mlx_provider import MLXProvider
from opennest.ai.provider import Chunk, Message, ModelInfo, Reply
from opennest.assets import look
from opennest.assets import manager as assets
from opennest.models import catalog
from opennest.setup import checks, downloader
from tests.conftest import ScriptedProvider
from tests.test_assets import SIGHTED, png_bytes

MONSTER = png_bytes(32, 32, alpha=True)
SAW = "a cheerful, fluffy blue monster with purple spots and antennae"


class SeeingProvider(ScriptedProvider):
    """A local vision model: shown the pictures on the latest message carrying any."""

    def __init__(self, replies, *, sees: bool = True, shows: bool = True) -> None:
        super().__init__(replies)
        self.info = ModelInfo(id="qwen3-vl-4b-instruct", name="Gary Fast", provider="mlx",
                              supports_images=True)
        self._sees = sees
        self._shows = shows
        self.last_shown: tuple[str, ...] = ()
        self.pictures: list[tuple[str, ...]] = []

    @property
    def sees_images(self) -> bool:
        return self._sees and self._loaded

    def chat(self, messages: Sequence[Message], *, tools=None, settings=None) -> Iterator[Chunk]:
        carrying = [m for m in messages if m.images]
        shown = carrying[-1].images if carrying and self.sees_images and self._shows else ()
        self.pictures.append(shown)
        yield from super().chat(messages, tools=tools, settings=settings)
        self.last_shown = shown


@pytest.fixture
def dropped(tmp_path):
    """A file outside the project, as if just dragged from Finder."""
    def _make(name: str, content: bytes):
        source = tmp_path / "dragged" / name
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(content)
        return source
    return _make


@pytest.fixture
def monster(project, dropped):
    return assets.import_file(project, dropped("blue_monster.png", MONSTER))


# -- what counts as seen -------------------------------------------------------------

def test_a_picture_is_unread_until_a_model_has_looked_even_with_a_vision_model(
        project, monster) -> None:
    """The Phase 6 hole, closed for good: a vision model in use is not a look."""
    vision = SeeingProvider([]).info
    assert provider_module.can_send_images(vision)
    asset = assets.list_assets(project)[0]
    assert not assets.can_interpret(asset, vision)
    assert "NOBODY HAS LOOKED" in assets.context_block(project, vision)


def test_looking_records_what_was_seen_and_the_prompt_says_it(project, monster) -> None:
    provider = SeeingProvider([Reply(text=f"This picture shows {SAW}.")])
    assert look.look(project, provider, monster.path) == SAW
    assert provider.pictures == [(str(project.directory / monster.path),)]
    asset = assets.list_assets(project)[0]
    assert asset.seen == SAW
    assert assets.can_interpret(asset, None)
    block = assets.context_block(project, provider.info)
    assert f"you have looked at it: it shows {SAW}" in block
    assert "NOBODY HAS LOOKED" not in block
    record = json.loads((project.directory / look.RECORD).read_text())
    assert record[monster.path]["by"] == "qwen3-vl-4b-instruct"


def test_what_was_seen_stays_true_for_whichever_model_is_gary_next(project, monster) -> None:
    """A sentence from a model that saw the pixels is evidence; Claude reading it later
    is not claiming to have looked."""
    look.look(project, SeeingProvider([Reply(text=SAW)]), monster.path)
    assert "NOBODY HAS LOOKED" not in assets.context_block(project, SIGHTED)
    assert assets.unread_assets(project, SIGHTED) == []


def test_a_replaced_picture_is_unread_again(project, monster) -> None:
    look.look(project, SeeingProvider([Reply(text=SAW)]), monster.path)
    (project.directory / monster.path).write_bytes(png_bytes(40, 40))
    assert assets.list_assets(project)[0].seen == ""
    assert "NOBODY HAS LOOKED" in assets.context_block(project, None)


@pytest.mark.parametrize("provider", [
    SeeingProvider([Reply(text=SAW)], sees=False),     # the vision engine is missing
    SeeingProvider([Reply(text=SAW)], shows=False),    # asked, but no pixels went
], ids=["cannot-see", "picture-not-shown"])
def test_nothing_is_recorded_unless_the_pixels_really_reached_the_model(
        project, monster, provider) -> None:
    assert look.look(project, provider, monster.path) == ""
    assert assets.list_assets(project)[0].seen == ""


def test_a_cloud_model_is_never_asked_to_look(project, monster) -> None:
    """Claude and OpenAI could see, and their providers send no pixels."""
    cloud = ScriptedProvider([Reply(text=SAW)])
    cloud.info = SIGHTED
    assert not look.can_look(cloud)
    assert look.look(project, cloud, monster.path) == ""
    assert cloud.calls == []


def test_a_secret_read_out_of_a_screenshot_is_not_written_down(project, monster) -> None:
    provider = SeeingProvider([Reply(text="a screen with the key sk-ant-api03-" + "Q" * 40)])
    assert look.look(project, provider, monster.path) == ""
    assert not (project.directory / look.RECORD).exists()


def test_what_was_seen_is_one_short_clause() -> None:
    assert look.tidy("This picture shows a red car.  It is fast.") == "a red car. It is fast"
    assert look.tidy("It shows a tree.") == "a tree"
    assert len(look.tidy("A dragon " + "with wings " * 60)) <= look.MAX_CHARS


# -- what Gary says ------------------------------------------------------------------

def test_the_import_message_says_what_was_seen(project, monster) -> None:
    look.look(project, SeeingProvider([Reply(text=SAW)]), monster.path)
    asset = assets.list_assets(project)[0]
    said = assets.import_messages([asset], SeeingProvider([]).info, game=True)
    assert f"It shows {SAW}." in said
    assert "cannot see" not in said


def test_six_pictures_looked_at_are_listed_once(project, dropped) -> None:
    trees = [assets.import_file(project, dropped(f"tree_0{n}.png", png_bytes(8 + n, 8)))
             for n in range(1, 7)]
    provider = SeeingProvider([Reply(text=f"a cartoon tree number {n}") for n in range(1, 7)])
    for tree in trees:
        look.look(project, provider, tree.path)
    said = assets.import_messages(assets.list_assets(project), provider.info, game=True)
    assert said.count("I looked at them:") == 1
    assert "- tree_06.png: a cartoon tree number 6" in said
    assert "cannot see" not in said


# -- the controller ------------------------------------------------------------------

def test_a_turn_looks_at_new_pictures_first_outside_its_budget(project, monster) -> None:
    provider = SeeingProvider([Reply(text=SAW), Reply(text="That is your blue monster."),
                               Reply(text="It is your picture.")])
    controller = AgentController(project, provider, Toolbox(project))
    turn = controller.send("what is my monster picture?")
    assert assets.list_assets(project)[0].seen == SAW
    assert provider.calls[0][0].content == look.QUESTION
    # The look was one call, and the turn's own budget counted only the turn's.
    assert turn.usage.calls == len(provider.calls) - 1
    assert SAW in provider.calls[1][0].content


def test_an_attached_picture_travels_with_its_message_and_only_that_turn(
        project, monster) -> None:
    provider = SeeingProvider([Reply(text=SAW), Reply(text="I can see a blue monster."),
                               Reply(text="Sure.")])
    controller = AgentController(project, provider, Toolbox(project))
    turn = controller.send("what is this?", attachments=[monster])
    picture = str(project.directory / monster.path)
    assert provider.pictures[1] == (picture,)
    # Shown the pixels, "I can see" is true and is not corrected.
    assert turn.text == "I can see a blue monster."
    assert not any(message.images for message in controller.history)
    controller.send("thanks")
    assert provider.pictures[2] == ()


def test_a_blind_model_is_given_no_pixels_and_still_cannot_claim_to_see(
        project, monster) -> None:
    provider = ScriptedProvider([Reply(text="I can see a blue monster."),
                                 Reply(text="I have not seen it.")])
    provider.info = ModelInfo(id="qwen3-4b-instruct", name="Qwen3 4B", provider="mlx")
    controller = AgentController(project, provider, Toolbox(project))
    controller.send("what is this?", attachments=[monster])
    assert not any(message.images for call in provider.calls for message in call)
    assert len(provider.calls) == 2, "the sight claim was corrected"


# -- the vision engine ---------------------------------------------------------------

class _Tokenizer:
    def __init__(self) -> None:
        self.payloads: list[list[dict]] = []

    def apply_chat_template(self, payload, **kwargs):
        self.payloads.append(payload)
        return "rendered"


def test_the_picture_markers_go_on_the_message_that_carries_the_pictures() -> None:
    """The child's message keeps its pictures for every call of the turn, including
    after a correction Open Nest adds as a later user message."""
    provider = MLXProvider(SeeingProvider([]).info, "mlx-community/x", "0" * 40)
    provider._tokenizer = _Tokenizer()
    messages = [Message(role="system", content="s"),
                Message(role="user", content="what is this?", images=("a.png", "b.png")),
                Message(role="assistant", content="It is a dragon."),
                Message(role="user", content="say again, in your own words")]
    provider._render(messages, None, pictures=2)
    payload = provider._tokenizer.payloads[-1]
    assert payload[1]["content"] == [{"type": "image"}, {"type": "image"},
                                     {"type": "text", "text": "what is this?"}]
    assert payload[3]["content"] == "say again, in your own words"


def test_a_see_through_picture_is_shown_on_white_and_small(tmp_path) -> None:
    """Measured: the eagle, a dark bird on nothing, was "a completely black image"."""
    pil = pytest.importorskip("PIL.Image")
    from opennest.ai.mlx_provider import PICTURE_PIXELS, prepare_picture

    path = tmp_path / "sprite.png"
    pil.new("RGBA", (1200, 1000), (0, 0, 0, 0)).save(path)
    shown = prepare_picture(str(path))
    assert shown.mode == "RGB"
    assert shown.getpixel((0, 0)) == (255, 255, 255)
    assert shown.width * shown.height <= PICTURE_PIXELS
    assert prepare_picture(str(tmp_path / "missing.png")) is None


# -- what is offered, and setup -------------------------------------------------------

def _entry(model_id: str):
    return router.get_entry(model_id)


def test_only_an_installed_local_vision_model_is_offered_for_a_picture(monkeypatch,
                                                                      credentials) -> None:
    monkeypatch.setattr(router, "_installed", lambda entry: entry.info.id ==
                        "qwen3-vl-4b-instruct")
    offered = [entry.info.id for entry in router.models_that_can_read(
        "image", allow_cloud=True, credentials=credentials)]
    assert offered == ["qwen3-vl-4b-instruct"]


def test_the_two_gary_models_are_pinned_vision_models() -> None:
    for model_id, name in (("qwen3-vl-4b-instruct", "Gary Fast"),
                           ("qwen3-vl-8b-instruct", "Gary Smart")):
        entry = _entry(model_id)
        assert entry.info.name == name
        assert entry.info.supports_images and entry.has("vision")
        assert provider_module.can_send_images(entry.info)
        assert len(entry.revision) == 40 and entry.model_id.startswith("mlx-community/")
        assert entry.upstream_model.startswith("Qwen/Qwen3-VL-")
        assert "images" in entry.good_for


def test_a_catalogue_good_for_list_is_short_words_or_the_entry_is_refused() -> None:
    item = dict(json.loads((catalog.paths.config_dir() / "models.json").read_text())
                ["models"][0])
    assert catalog._entry_is_valid(item)
    assert not catalog._entry_is_valid({**item, "good_for": ["x" * 41]})
    assert not catalog._entry_is_valid({**item, "good_for": "images"})
    assert not catalog._entry_is_valid({**item, "good_for": [""] })


class _VerifyingProvider(SeeingProvider):
    def __init__(self, colour_answer: str, **kwargs) -> None:
        super().__init__([Reply(text="OPEN NEST READY"), Reply(text=colour_answer)], **kwargs)


def test_verifying_a_vision_model_shows_it_a_picture(monkeypatch) -> None:
    pytest.importorskip("PIL")
    result = downloader.verify(_entry("qwen3-vl-4b-instruct"),
                               provider=_VerifyingProvider("Red."))
    assert result.ok and result.sees_pictures is True
    assert result.lines()[-1] == "✓ Sees pictures"


def test_a_vision_model_that_cannot_be_shown_a_picture_says_so() -> None:
    pytest.importorskip("PIL")
    result = downloader.verify(_entry("qwen3-vl-4b-instruct"),
                               provider=_VerifyingProvider("Red.", sees=False))
    assert result.ok, "it still works as a text model"
    assert result.sees_pictures is False
    assert "could not be shown a picture" in result.message


def test_a_text_model_is_not_given_a_vision_check() -> None:
    provider = ScriptedProvider([Reply(text="OPEN NEST READY")])
    result = downloader.verify(_entry("qwen3-4b-instruct"), provider=provider)
    assert result.sees_pictures is None and len(result.lines()) == 3


def test_a_missing_vision_engine_fails_the_health_check_only_for_a_vision_model(
        monkeypatch) -> None:
    import builtins

    real = builtins.__import__

    def without_vision(name, *args, **kwargs):
        if name == "mlx_vlm":
            raise ImportError("not installed")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_vision)
    assert checks._vision_engine("qwen3-vl-4b-instruct").state == checks.FAILED
    assert checks._vision_engine("qwen3-4b-instruct").state == checks.NOT_CONFIGURED
    plan = checks.plan_repair([checks._vision_engine("qwen3-vl-4b-instruct")])
    assert plan.reinstall_dependencies


def test_the_vision_engine_is_installed_without_its_declared_extras(monkeypatch) -> None:
    from bootstrap import environment

    ran: list[list[str]] = []
    monkeypatch.setattr(environment, "_run", lambda command, what: ran.append(command))
    environment.install_requirements(["/r/requirements/macos-apple-silicon.txt",
                                      "/r/requirements/vision.txt"])
    installs = [command for command in ran if "-r" in command]
    assert "--no-deps" not in installs[0]
    assert "--no-deps" in installs[1]


def test_an_update_reinstalls_the_ai_engines_on_apple_silicon(monkeypatch, tmp_path) -> None:
    from bootstrap import environment
    from opennest.setup import migration

    for name in ("base.txt", "macos-apple-silicon.txt", "vision.txt", "projects.txt"):
        (tmp_path / "requirements").mkdir(exist_ok=True)
        (tmp_path / "requirements" / name).write_text("")
    monkeypatch.setattr(migration, "_apple_silicon", lambda env: True)
    seen: list[list[str]] = []
    ok, _ = migration._reinstall(tmp_path, lambda manifests: seen.append(manifests) or 0)
    assert ok
    assert [p.rsplit("/", 1)[-1] for p in seen[0]] == [
        "base.txt", "macos-apple-silicon.txt", "vision.txt", "projects.txt"]
    assert environment.NO_DEPS_MANIFESTS == ("vision.txt",)


# -- which model the application starts with ------------------------------------------

@pytest.mark.parametrize("preferred, installed, expected", [
    ("qwen3-vl-8b-instruct", {"qwen3-vl-8b-instruct"}, "qwen3-vl-8b-instruct"),
    ("qwen3-vl-8b-instruct", set(), None),            # chosen, then removed from the Mac
    ("claude-sonnet", {"claude-sonnet"}, None),        # never a cloud model at startup
    ("no-such-model", {"no-such-model"}, None),
    ("", set(), None),
], ids=["chosen-and-installed", "not-on-this-mac", "cloud", "unknown", "none"])
def test_the_app_starts_with_the_model_setup_chose(monkeypatch, preferred, installed,
                                                   expected) -> None:
    """Until now it always started the default, whatever a parent picked in setup."""
    monkeypatch.setattr(router, "_installed", lambda entry: entry.info.id in installed)
    assert router.startup_model_id(preferred) == (expected or router.default_model_id())


def test_saying_it_sees_a_picture_it_looked_at_is_not_corrected(project, monster) -> None:
    """A check that corrects a true sentence is a bug (SPIKES.md section 29)."""
    provider = SeeingProvider([Reply(text=SAW),
                               Reply(text="I can see your monster picture has purple spots."),
                               Reply(text="unused")])
    controller = AgentController(project, provider, Toolbox(project))
    turn = controller.send("does my monster have spots?")
    assert turn.text == "I can see your monster picture has purple spots."
    assert len(provider.calls) == 2


def test_saying_it_sees_the_game_is_still_corrected_once_a_picture_was_seen(
        project, monster) -> None:
    provider = SeeingProvider([Reply(text=SAW), Reply(text="I see the monster is missing."),
                               Reply(text="The game has the orange square.")])
    controller = AgentController(project, provider, Toolbox(project))
    controller.send("is the monster in my game?")
    assert len(provider.calls) == 3, "the claim about the screen was corrected"


# -- the Workbench: looked at on a worker, then said ----------------------------------

def _spin(predicate, timeout_ms: int = 5000) -> bool:
    """The real event loop until ``predicate`` holds (tests/test_worker.py's reason)."""
    from PySide6.QtCore import QEventLoop, QTimer

    waited = 0
    while waited < timeout_ms and not predicate():
        loop = QEventLoop()
        QTimer.singleShot(25, loop.quit)
        loop.exec()
        waited += 25
    return bool(predicate())


def test_adding_a_picture_looks_at_it_off_the_gui_thread_and_says_what_it_shows(
        qt_app, project, dropped) -> None:
    import threading

    from opennest.ui.workbench import Workbench

    provider = SeeingProvider([Reply(text=f"This picture shows {SAW}.")])
    threads: list[str] = []
    real_chat = provider.chat

    def chat(messages, **kwargs):
        threads.append(threading.current_thread().name)
        yield from real_chat(messages, **kwargs)

    provider.chat = chat
    bench = Workbench(project, AgentController(project, provider, Toolbox(project)))
    bench.show()
    try:
        bench._ask_what_it_is = lambda source, count=1: "asset"
        bench._add([dropped("blue_monster.png", MONSTER)], attach=False)
        assert bench._thread is not None, "the look runs on a worker"
        assert not bench._send_button.isEnabled()
        assert _spin(lambda: bench._thread is None)
        said = bench._transcript.toPlainText()
        assert f"blue_monster.png is in your project. It shows {SAW}." in said
        assert threads and threads[0] != threading.main_thread().name
        assert bench._send_button.isEnabled()
    finally:
        bench.release()
        bench.close()


def test_a_blind_model_says_the_limitation_at_once(qt_app, project, dropped) -> None:
    from opennest.ui.workbench import Workbench

    provider = ScriptedProvider([])
    provider.info = ModelInfo(id="qwen3-4b-instruct", name="Qwen3 4B", provider="mlx")
    bench = Workbench(project, AgentController(project, provider, Toolbox(project)))
    try:
        bench._ask_what_it_is = lambda source, count=1: "asset"
        bench._add([dropped("blue_monster.png", MONSTER)], attach=False)
        assert bench._thread is None
        assert "Qwen3 4B cannot see pictures" in bench._transcript.toPlainText()
        assert provider.calls == []
    finally:
        bench.release()
        bench.close()


# -- a replaced model keeps working and is not offered again ---------------------------

_REAL_CATALOGUE = router.load_catalogue


def _catalogue_with_a_replaced_model():
    from dataclasses import replace

    entries = _REAL_CATALOGUE()
    return tuple(replace(entry, status="deprecated") if entry.info.id == "qwen3-4b-instruct"
                 else entry for entry in entries)


def test_a_replaced_model_is_never_the_suggestion_even_when_installed() -> None:
    from opennest.models import compatibility
    from tests.test_models import AIR_8GB

    entries = _catalogue_with_a_replaced_model()
    chosen, _ = compatibility.suggestion(entries, AIR_8GB,
                                         installed_ids=["qwen3-4b-instruct"])
    assert chosen.info.id != "qwen3-4b-instruct"
    assert chosen.offered_for_install


def test_a_replaced_model_stays_in_the_project_picker_only_where_installed(monkeypatch) -> None:
    from opennest.projects.profiles import get_profile

    monkeypatch.setattr(router, "load_catalogue", _catalogue_with_a_replaced_model)
    games = get_profile("games")
    monkeypatch.setattr(router, "_installed", lambda entry: False)
    assert "qwen3-4b-instruct" not in [e.info.id for e in router.models_for_project(games)]
    monkeypatch.setattr(router, "_installed", lambda entry: True)
    assert "qwen3-4b-instruct" in [e.info.id for e in router.models_for_project(games)]


def test_a_line_said_twice_in_one_reply_is_said_once() -> None:
    """Verbatim from the Gary Fast test04 replay (SPIKES.md section 32)."""
    from opennest.agent.replies import presentable

    line = "- The trees are drawn in front of the monster, and clicking the monster gives a point."
    reply = f"The trees are now in the game.\n{line}\n{line}\nNext, I'll add a score system."
    assert presentable(reply).count(line) == 1
    # Code may repeat, and so may short lines.
    code = "```\nscreen.fill(SKY)\nscreen.fill(SKY)\n```"
    assert presentable(code).count("screen.fill(SKY)") == 2
    assert presentable("Yes.\nYes.\nDone.").count("Yes.") == 2


# -- a whole file sent as an edit (the Gary Fast maze replay) ---------------------------

def test_a_whole_imagined_file_as_an_edit_is_told_what_to_use_instead(project) -> None:
    toolbox = Toolbox(project)
    assert "game_object" in toolbox.allowed        # a Games project has the scene
    imagined = "import pygame\npygame.init()\n\n# Tunable numbers\nSCREEN_WIDTH = 640\n"
    result = toolbox.dispatch("edit_file", {"path": "src/game.py", "old_text": imagined})
    assert not result.ok and result.reason == "missing_argument"
    assert "does not replace the whole file" in result.content
    assert "call game_object" in result.content
    written = toolbox.dispatch("write_file", {"path": "src/game.py", "content": imagined})
    assert not written.ok and "call game_object" in written.content


def test_a_real_line_with_no_new_text_still_just_asks_for_it(project) -> None:
    toolbox = Toolbox(project)
    result = toolbox.dispatch("edit_file", {"path": "src/game.py",
                                            "old_text": "PLAYER_SPEED = 5"})
    assert not result.ok
    assert result.content.startswith("edit_file needs a path, the exact old_text")


def test_a_picture_that_cannot_be_looked_at_costs_one_call_a_session(project, monster) -> None:
    provider = SeeingProvider([Reply(text="ok")] * 6, shows=False)
    controller = AgentController(project, provider, Toolbox(project))
    controller.look_at_pictures()
    controller.look_at_pictures()
    assert len(provider.calls) == 1


def test_a_picture_added_during_a_turn_is_promised_a_look_not_called_unseeable(
        project, monster) -> None:
    """The look waits for the turn; the message must not say this model cannot see."""
    said = assets.import_messages([monster], SeeingProvider([]).info, game=True)
    assert "cannot see" not in said
    assert "I'll look at it before your next message." in said
    single = assets.import_message(monster, SeeingProvider([]).info)
    assert "cannot see" not in single


def test_a_promise_with_what_next_tacked_on_is_still_a_promise(project) -> None:
    """Verbatim from the Gary Smart test04 replay (SPIKES.md section 32)."""
    promised = ("You added tree images. I'll replace the current tree drawing with your tree "
                "pictures.\n\nLet me change the trees to use your tree images. What do you "
                "want next?")
    provider = ScriptedProvider([Reply(text=promised), Reply(text="I have not changed it yet.")])
    controller = AgentController(project, provider, Toolbox(project))
    controller.send("replace the drawing with the pictures I added")
    assert len(provider.calls) == 2, "the promise was corrected"


def test_a_real_question_back_still_ends_a_turn(project) -> None:
    asked = "I'll add it. Which picture should be the monster: blue_monster.png or tree.png?"
    provider = ScriptedProvider([Reply(text=asked)])
    controller = AgentController(project, provider, Toolbox(project))
    turn = controller.send("make the monster use my picture")
    assert len(provider.calls) == 1 and "Which picture" in turn.text
