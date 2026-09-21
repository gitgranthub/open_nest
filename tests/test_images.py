"""Image Creation: the profile, its gating, and what may be said afterwards.

PLAN.md decision D6. No test here opens a socket -- the transport is injected, the same
way the cloud providers are tested, and the real service was exercised separately by
``spikes/spike_image_generation.py`` (SPIKES.md sections 12 and 14: 798 KB of PNG inline
as base64 in 10.9 s).

The rule worth guarding hardest is the last one. Phase 6 already broke asset honesty
once, by making a vision model selectable and thereby telling the prompt that somebody
had looked at a picture nobody had sent. Image generation is the same trap wearing a
different hat: Open Nest asked for this picture and saved it, and *still* has not seen
it.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from opennest.ai import cloud, images
from opennest.ai.provider import ProviderError
from opennest.ai.router import get_entry
from opennest.assets import manager as assets
from opennest.projects.manager import create_project
from opennest.projects.profiles import get_profile

#: A genuinely valid 1x1 RGB PNG -- correct CRCs, and it really decodes.
#:
#: The first version of this constant had valid magic bytes and a corrupt IDAT checksum.
#: Every test here passed, because ``describe.py`` reads the header and never decodes the
#: image. It was the *workbench* test that caught it, with ``libpng error: IDAT:
#: incorrect data check``, because QPixmap actually has to render the thing. Worth
#: remembering: a fixture that satisfies a header reader is not necessarily an image.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mPQypsDAAH6ATVkpzDmAAAAAElFTkSuQmCC"
)


class ScriptedTransport:
    """Returns a fixed payload and records the request. Opens nothing."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[cloud.Request] = []

    def send(self, request: cloud.Request) -> dict:
        self.requests.append(request)
        return self.payload

    def stream(self, request: cloud.Request):  # pragma: no cover - not used here
        raise AssertionError("image generation does not stream")


def png_payload(raw: bytes = PNG) -> dict:
    return {"data": [{"b64_json": base64.b64encode(raw).decode("ascii")}]}


@pytest.fixture
def picture_project(tmp_path: Path):
    return create_project("My Pictures", "image_creation", root=tmp_path)


# -- the profile -------------------------------------------------------------


def test_the_image_model_is_not_in_the_chat_catalogue() -> None:
    """A models.json entry is something that answers a conversation.

    ``gpt-image-2.5-flare`` takes a sentence and returns a PNG, so it lives on the
    profile. Keeping it out of the catalogue is what stops it appearing in the model
    picker as though a child could talk to it.
    """
    profile = get_profile("image_creation")
    assert profile.image_model == "gpt-image-2.5-flare"
    with pytest.raises(ProviderError):
        get_entry(profile.image_model)


def test_image_creation_runs_nothing(picture_project) -> None:
    """The sandbox denies network, so generation cannot be a project run.

    This is the reason ``run_mode: generate`` exists rather than another run command:
    a child's own code could never reach an image service, and should not be able to.
    """
    profile = picture_project.profile
    assert profile.generates
    assert profile.run_command is None
    assert profile.compile_command is None


def test_image_creation_does_not_get_a_run_tool(picture_project) -> None:
    """Nothing to run means no tool to run it with, and still under the four-tool cap."""
    tools = picture_project.profile.tools
    assert "run_project" not in tools
    assert "compile_project" not in tools
    assert len(tools) <= 4


# -- gating ------------------------------------------------------------------


def test_with_cloud_off_the_reason_points_at_the_master_switch(
    picture_project, configured_credentials
) -> None:
    reason = images.unmet_requirements(
        picture_project.profile, allow_cloud=False, credentials=configured_credentials
    )
    assert reason and "turned off" in reason
    assert "Settings" in reason


def test_with_cloud_on_but_no_key_the_reason_points_at_the_key(
    picture_project, credentials
) -> None:
    """Two permissions, two remedies. Conflating them sends a parent to fix the wrong one."""
    reason = images.unmet_requirements(
        picture_project.profile, allow_cloud=True, credentials=credentials
    )
    assert reason and "key" in reason.lower()
    assert "turned off" not in reason


def test_with_cloud_on_and_a_key_there_is_no_obstacle(
    picture_project, configured_credentials
) -> None:
    assert images.unmet_requirements(
        picture_project.profile, allow_cloud=True, credentials=configured_credentials
    ) is None


def test_no_other_profile_is_gated_on_cloud() -> None:
    """Everything else has to keep working with cloud off -- that is the default."""
    from opennest.projects.profiles import load_profiles

    for profile in load_profiles():
        if profile.id == "image_creation":
            continue
        assert images.unmet_requirements(
            profile, allow_cloud=False, credentials=None
        ) is None, profile.id


# -- generation --------------------------------------------------------------


def test_a_generated_picture_becomes_an_ordinary_asset(
    picture_project, configured_credentials
) -> None:
    """Rule one from Phase 5: one way into a project, not a special path for this.

    Going through ``import_file`` is what makes the file classified, copied to
    ``assets/`` and described from its real header -- and therefore what keeps every
    Phase 5 guarantee working on a picture that came from a model.
    """
    transport = ScriptedTransport(png_payload())

    asset = images.generate_into(
        picture_project, "a green rocket",
        credentials=configured_credentials, transport=transport,
    )

    assert asset.kind == "image"
    assert asset.path.startswith("assets/")
    assert (picture_project.directory / asset.path).read_bytes() == PNG
    # Named from the child's own words, so they can find it again.
    assert "rocket" in asset.path


def test_the_request_carries_the_profiles_model_and_a_cost_conscious_default(
    picture_project, configured_credentials
) -> None:
    transport = ScriptedTransport(png_payload())
    images.generate_into(
        picture_project, "an icon",
        credentials=configured_credentials, transport=transport,
    )
    body = transport.requests[0].body
    assert body["model"] == "gpt-image-2.5-flare"
    assert body["quality"] == "low"
    assert body["prompt"] == "an icon"


def test_the_key_never_appears_anywhere_but_the_authorization_header(
    picture_project, configured_credentials
) -> None:
    transport = ScriptedTransport(png_payload())
    images.generate_into(
        picture_project, "a castle",
        credentials=configured_credentials, transport=transport,
    )
    request = transport.requests[0]
    key = configured_credentials.get_key("openai")
    assert request.headers["Authorization"] == f"Bearer {key}"
    assert key not in str(request.body)
    assert key not in request.url


def test_a_reply_that_is_not_a_png_is_refused(
    picture_project, configured_credentials
) -> None:
    """describe.py reads real headers, so a non-PNG would be described confidently wrong."""
    transport = ScriptedTransport(png_payload(b"this is not a png"))
    with pytest.raises(ProviderError) as caught:
        images.generate_into(
            picture_project, "a dog",
            credentials=configured_credentials, transport=transport,
        )
    assert "not a PNG" in str(caught.value)


def test_an_empty_reply_is_refused(picture_project, configured_credentials) -> None:
    transport = ScriptedTransport({"data": []})
    with pytest.raises(ProviderError):
        images.generate_into(
            picture_project, "a dog",
            credentials=configured_credentials, transport=transport,
        )


def test_nothing_is_left_behind_in_the_staging_directory(
    picture_project, configured_credentials
) -> None:
    transport = ScriptedTransport(png_payload())
    images.generate_into(
        picture_project, "a tree",
        credentials=configured_credentials, transport=transport,
    )
    staging = picture_project.internal_dir / "tmp"
    assert not list(staging.glob("*.png"))


def test_two_pictures_do_not_overwrite_each_other(
    picture_project, configured_credentials
) -> None:
    transport = ScriptedTransport(png_payload())
    first = images.generate_into(
        picture_project, "a rocket",
        credentials=configured_credentials, transport=transport,
    )
    second = images.generate_into(
        picture_project, "a rocket",
        credentials=configured_credentials, transport=transport,
    )
    assert first.path != second.path
    assert (picture_project.directory / first.path).is_file()
    assert (picture_project.directory / second.path).is_file()


def test_a_prompt_with_no_usable_words_still_gets_a_filename() -> None:
    assert images.filename_for("???").endswith(".png")
    assert images.filename_for("???") == "picture.png"


# -- honesty -----------------------------------------------------------------


def test_generating_a_picture_is_not_seeing_it(
    picture_project, configured_credentials
) -> None:
    """Rule two from Phase 5, and the one Phase 6 broke once already.

    Open Nest asked for this image and saved it. Nothing has looked at the pixels, so
    ``can_interpret`` must still say no and the prompt must still carry the block that
    stops the model describing it. Verified against the real service too (SPIKES.md
    section 12) -- checking this is what exposed the ``can_interpret`` hole.
    """
    transport = ScriptedTransport(png_payload())
    asset = images.generate_into(
        picture_project, "a red dragon with wings",
        credentials=configured_credentials, transport=transport,
    )

    info = get_entry("openai-gpt").info
    assert not assets.can_interpret(asset, info)

    unread = [item.path for item in assets.unread_assets(picture_project, info)]
    assert asset.path in unread

    block = assets.context_block(picture_project, info, attached=(asset,))
    assert "NOBODY HAS LOOKED" in block


def test_the_description_of_a_generated_picture_states_only_file_facts(
    picture_project, configured_credentials
) -> None:
    """A 1x1 PNG described as 1x1, with nothing said about what it depicts.

    The prompt asked for a dragon. The description must not mention one, because the
    only evidence available is a PNG header.
    """
    transport = ScriptedTransport(png_payload())
    asset = images.generate_into(
        picture_project, "a red dragon with wings",
        credentials=configured_credentials, transport=transport,
    )
    summary = asset.summary.lower()
    assert "png" in summary
    assert "1x1" in summary.replace("×", "x")
    for invented in ("dragon", "red", "wings"):
        assert invented not in summary, f"the description claims to know about {invented!r}"
