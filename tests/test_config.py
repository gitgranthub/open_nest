"""Models, profiles and prompts are data. These tests keep that data honest."""

from __future__ import annotations

import json
import re
import tokenize
from pathlib import Path

import pytest

from opennest import paths
from opennest.projects import starters

REPO = paths.repo_root()

#: The tool vocabulary from WORKORDER_01 section 18. A profile may not invent tools.
KNOWN_TOOLS = {
    "list_project_files",
    "read_file",
    "write_file",
    "edit_file",
    "create_directory",
    "delete_project_file",
    "run_project",
    "compile_project",
    "inspect_error",
    "list_assets",
    "read_text_asset",
    "get_project_info",
}


def _load(name: str) -> dict:
    return json.loads((paths.config_dir() / name).read_text(encoding="utf-8"))


def _allowlisted_packages() -> set[str]:
    text = (REPO / "requirements" / "projects.txt").read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(re.split(r"[<>=!~\[; ]", line)[0].strip().lower())
    return names


@pytest.fixture(scope="module")
def models() -> list[dict]:
    return _load("models.json")["models"]


@pytest.fixture(scope="module")
def profiles() -> list[dict]:
    return _load("profiles.json")["profiles"]


def test_model_ids_are_unique(models: list[dict]) -> None:
    ids = [m["id"] for m in models]
    assert len(ids) == len(set(ids))


def test_every_model_declares_its_capabilities(models: list[dict]) -> None:
    """The app must be able to ask a model what it can do (WORKORDER_01 section 13)."""
    required = {"id", "name", "provider", "description", "supports_images", "supports_tools"}
    for model in models:
        missing = required - model.keys()
        assert not missing, "model {} is missing {}".format(model.get("id"), sorted(missing))


def test_every_model_has_a_context_policy(models: list[dict]) -> None:
    """Thread rollover needs a budget per model (WORKORDER_01 section 15A)."""
    for model in models:
        policy = model.get("context_policy")
        assert policy, "model {} has no context_policy".format(model["id"])
        assert policy["rollover_threshold"] < policy["max_context_tokens"], (
            "model {} would roll over only at its hard limit; roll over earlier so the "
            "handoff summary has room".format(model["id"])
        )
        assert policy["memory_reserved_tokens"] < policy["rollover_threshold"]


def test_local_models_are_pinned_to_a_commit(models: list[dict]) -> None:
    """mlx-community holds community conversions, so downloads must be reproducible.

    Tracking a moving branch means the bytes installed on a child's Mac are whatever the
    namespace happened to contain that day. Pin the SHA; bump it deliberately.
    """
    for model in models:
        if model["provider"] != "mlx":
            continue
        revision = model.get("revision", "")
        assert re.fullmatch(r"[0-9a-f]{40}", revision), (
            f"model {model['id']} must pin a 40-character commit SHA, got {revision!r}"
        )


def test_local_models_record_their_provenance(models: list[dict]) -> None:
    """A community conversion is two trust hops from the original author. Show both."""
    for model in models:
        if model["provider"] != "mlx":
            continue
        for field in ("upstream_model", "license", "download_gb"):
            assert model.get(field), f"model {model['id']} is missing {field}"


def test_cloud_models_are_marked_as_using_the_internet(models: list[dict]) -> None:
    """The UI must never present a cloud model as if it ran on this Mac."""
    for model in models:
        if model["provider"] in {"openai", "anthropic"}:
            assert model.get("requires_internet") is True, model["id"]


def test_default_local_model_exists_and_is_local(models: list[dict]) -> None:
    default_id = _load("models.json")["default_local_model"]
    match = next((m for m in models if m["id"] == default_id), None)
    assert match is not None, f"default_local_model {default_id!r} is not in the list"
    assert match["provider"] == "mlx"


def test_default_local_model_supports_tools(models: list[dict]) -> None:
    """The agent only acts through tools, so the default model has to be able to call them."""
    default_id = _load("models.json")["default_local_model"]
    match = next(m for m in models if m["id"] == default_id)
    assert match["supports_tools"] is True


def test_profile_ids_are_unique(profiles: list[dict]) -> None:
    ids = [p["id"] for p in profiles]
    assert len(ids) == len(set(ids))


def test_all_v1_profiles_are_present(profiles: list[dict]) -> None:
    """WORKORDER_01 section 5's five, plus Image Creation (D6) and Website (Phase 11)."""
    expected = {
        "games", "website", "raspberry_pi", "arduino", "research", "blank",
        "image_creation",
    }
    assert {p["id"] for p in profiles} == expected


def test_the_profile_schema_is_the_phase_11_one() -> None:
    """Schema 2 replaced ``starter_template`` with ``starters`` + ``starter_default``.

    Pinned because a renamed field is the kind of change that leaves one consumer
    quietly reading a key nobody writes any more.
    """
    raw = _load("profiles.json")
    assert raw["schema_version"] == 2
    for profile in raw["profiles"]:
        assert "starter_template" not in profile, (
            "profile {} still carries the schema 1 field".format(profile["id"])
        )
        assert "starters" in profile and "starter_default" in profile, profile["id"]


def test_nothing_still_reads_the_schema_1_starter_field() -> None:
    """The other half of a rename: no code left looking for the old key.

    Comments and docstrings are stripped first, because the modules that made the change
    explain it in prose and should go on doing so -- what must not survive is an
    attribute access or a dictionary key.
    """
    package = paths.package_root()
    offenders = []
    for path in sorted(package.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        with tokenize.open(path) as handle:
            code = "".join(
                token.string
                for token in tokenize.generate_tokens(handle.readline)
                if token.type not in (tokenize.COMMENT, tokenize.STRING)
            )
        if "starter_template" in code:
            offenders.append(str(path.relative_to(package.parent)))
    assert not offenders, f"still referencing starter_template: {offenders}"


def test_every_offered_starter_exists_and_belongs_to_the_profile_offering_it(
    profiles: list[dict],
) -> None:
    """The test that was missing for seven phases, in its Phase 11 form.

    ``profiles.json`` named five starter templates and only ``pygame_basic`` had ever
    existed. ``create_project`` skipped a missing one silently, so four of the five
    profiles created a project containing nothing but ``project.json``, with the
    manifest pointing at an entrypoint that was not there. Nothing failed; the projects
    were simply empty.
    """
    installed = {starter.id: starter for starter in starters.load_starters()}
    for profile in profiles:
        for starter_id in profile["starters"]:
            assert starter_id in installed, "profile {} offers missing starter {}".format(
                profile["id"], starter_id
            )
            assert installed[starter_id].profile == profile["id"], (
                "starter {} is offered by {} but declares profile {}".format(
                    starter_id, profile["id"], installed[starter_id].profile
                )
            )


def test_a_default_starter_is_one_the_profile_actually_offers(profiles: list[dict]) -> None:
    """``starter_default`` is null or a member of ``starters``. Never a third thing."""
    for profile in profiles:
        default = profile["starter_default"]
        if default is None:
            continue
        assert default in profile["starters"], (
            "profile {} defaults to {} which it does not offer".format(
                profile["id"], default
            )
        )


def test_no_profile_uses_an_empty_string_where_it_means_no_default(
    profiles: list[dict],
) -> None:
    """``null``, not ``""``. A falsy-string sentinel is one every consumer must recall."""
    for profile in profiles:
        assert profile["starter_default"] != "", profile["id"]


def test_blank_is_genuinely_blank(profiles: list[dict]) -> None:
    """Section 7 of the Phase 11 work order, pinned.

    A profile whose entire purpose is an empty page should not have a starter to
    decline, so Blank offers none at all rather than offering one and defaulting away
    from it.
    """
    blank = next(p for p in profiles if p["id"] == "blank")
    assert blank["starters"] == []
    assert blank["starter_default"] is None
    assert not (starters.starters_root() / "blank_basic").exists(), (
        "the withdrawn Phase 0 blank kit is back on disk"
    )


def test_every_starter_holds_the_entrypoint_its_profile_expects(
    profiles: list[dict],
) -> None:
    """Checking the entrypoint, not just the directory, is what makes this bite.

    The Arduino kit has to be ``project/project.ino`` rather than ``project.ino``,
    because arduino-cli requires a sketch folder whose name matches its sketch
    (SPIKES.md section 14).
    """
    installed = {starter.id: starter for starter in starters.load_starters()}
    for profile in profiles:
        for starter_id in profile["starters"]:
            starter = installed[starter_id]
            assert starter.entry_point == profile["entrypoint"], (
                "starter {} enters at {} but profile {} expects {}".format(
                    starter_id, starter.entry_point, profile["id"], profile["entrypoint"]
                )
            )
            assert (starter.directory / starter.entry_point).is_file(), (
                f"starter {starter_id} does not contain its own entry point {starter.entry_point}"
            )


def test_every_starter_declares_every_file_it_ships(profiles: list[dict]) -> None:
    """A kit that quietly gains a file is a kit whose tests no longer describe it."""
    for starter in starters.load_starters():
        shipped = {
            str(path.relative_to(starter.directory))
            for path in starter.directory.rglob("*")
            if path.is_file() and path.name != starters.MANIFEST_NAME
        }
        assert shipped == set(starter.files), (
            f"starter {starter.id} ships {sorted(shipped)} but declares {sorted(starter.files)}"
        )


def test_a_starter_id_matches_its_directory(profiles: list[dict]) -> None:
    for starter in starters.load_starters():
        assert starter.id == starter.directory.name


def test_every_profile_prompt_file_exists(profiles: list[dict]) -> None:
    for profile in profiles:
        prompt = paths.prompts_dir() / profile["prompt_file"]
        assert prompt.is_file(), "profile {} points at missing {}".format(
            profile["id"],
            profile["prompt_file"],
        )


def test_every_profile_uses_known_tools_only(profiles: list[dict]) -> None:
    for profile in profiles:
        unknown = set(profile["tools"]) - KNOWN_TOOLS
        assert not unknown, "profile {} requests unknown tools {}".format(
            profile["id"],
            sorted(unknown),
        )


def test_every_profile_package_is_allowlisted(profiles: list[dict]) -> None:
    """A profile cannot quietly widen the curated package set (WORKORDER_01 section 20)."""
    allowed = _allowlisted_packages()
    for profile in profiles:
        extra = {pkg.lower() for pkg in profile["packages"]} - allowed
        assert not extra, "profile {} wants non-allowlisted packages {}".format(
            profile["id"],
            sorted(extra),
        )


def test_every_profile_gives_the_child_a_button_that_does_something(
    profiles: list[dict],
) -> None:
    """Run, compile, preview or generate -- but never nothing.

    Two profiles execute no code at all, for different reasons. Image Creation asks a
    service, because the process sandbox denies network and a child's own code could
    never reach an image model. Website is opened rather than executed, because a page
    has no process and no exit code. Both therefore have neither command, and
    ``run_mode`` is what says which.
    """
    for profile in profiles:
        mode = profile.get("run_mode", "batch")
        acts_without_running = mode in {"generate", "preview"}
        has_command = bool(profile.get("run_command") or profile.get("compile_command"))
        assert acts_without_running or has_command, (
            "profile {} offers the child no way to make anything happen".format(profile["id"])
        )
        # A profile cannot claim both: one executes inside the sandbox, one does not.
        assert not (acts_without_running and has_command), (
            "profile {} both executes and does not execute".format(profile["id"])
        )
        assert profile.get("run_label")


def test_base_and_style_prompts_exist() -> None:
    """Prompt composition is base + profile + build style (WORKORDER_01 section 17)."""
    for name in ("base.txt", "style_build.txt", "style_teach.txt"):
        assert (paths.prompts_dir() / name).is_file(), name


def test_no_prompt_mentions_the_placeholder_product_name() -> None:
    """DESIGN_DOC.md section 21: the product is Open Nest, not Build Lab."""
    for prompt in paths.prompts_dir().glob("*.txt"):
        text = prompt.read_text(encoding="utf-8").lower()
        assert "build lab" not in text and "buildlab" not in text, prompt.name


def test_config_files_are_valid_json() -> None:
    for path in sorted(Path(paths.config_dir()).glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))


def test_no_profile_offers_a_tool_for_what_the_app_already_knows(profiles: list[dict]) -> None:
    """SPIKES.md: the file list and last run result are injected, not fetched.

    Offering them as tools measurably cost tool-selection accuracy, because the model
    reached for them instead of acting on the request.
    """
    for profile in profiles:
        assert "list_project_files" not in profile["tools"], profile["id"]
        assert "inspect_error" not in profile["tools"], profile["id"]


# ------------------------------------- which model can build which kind of project
#
# WORKORDER_01 section 13 makes the application responsible for knowing what a model
# can do. That reaches past attachments: a profile says what it needs, a model says
# what it does, and the mismatch should be stated rather than discovered by a child
# watching nothing happen.


def test_a_model_without_tools_cannot_build_anything() -> None:
    """gemma2-2b is in the catalogue with supports_tools false, and every profile
    works by calling tools. It can discuss a game; it cannot make one."""
    from opennest.ai.router import get_entry, unmet_requirements
    from opennest.projects.profiles import get_profile

    gemma = get_entry("gemma2-2b").info
    assert not gemma.supports_tools
    for profile_id in ("games", "research", "arduino", "raspberry_pi", "blank"):
        problems = unmet_requirements(gemma, get_profile(profile_id))
        assert problems, profile_id
        assert "cannot use tools" in problems[0]


def test_the_default_model_can_build_every_kind_of_project() -> None:
    from opennest.ai.router import default_model_id, get_entry, unmet_requirements
    from opennest.projects.profiles import load_profiles

    info = get_entry(default_model_id()).info
    for profile in load_profiles():
        assert unmet_requirements(info, profile) == (), profile.id


def test_not_being_able_to_see_a_picture_does_not_block_a_project() -> None:
    """It is a limitation the asset layer states honestly, not a reason to refuse."""
    from opennest.ai.router import get_entry, unmet_requirements
    from opennest.projects.profiles import get_profile

    info = get_entry("qwen3-4b-instruct").info
    assert not info.supports_images
    assert unmet_requirements(info, get_profile("games")) == ()


def test_the_picker_can_be_filtered_to_models_that_would_work() -> None:
    from opennest.ai.router import models_for_project
    from opennest.projects.profiles import get_profile

    usable = {e.info.id for e in models_for_project(get_profile("games"))}
    assert "qwen3-4b-instruct" in usable
    assert "gemma2-2b" not in usable
    assert "claude-sonnet" not in usable          # cloud is off by default
    assert "claude-sonnet" in {
        e.info.id for e in models_for_project(get_profile("games"), allow_cloud=True)
    }
