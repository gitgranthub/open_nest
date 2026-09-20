"""Models, profiles and prompts are data. These tests keep that data honest."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from opennest import paths

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


def test_all_five_v1_profiles_are_present(profiles: list[dict]) -> None:
    expected = {"games", "raspberry_pi", "arduino", "research", "blank"}
    assert {p["id"] for p in profiles} == expected


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


def test_every_profile_can_be_run_or_compiled(profiles: list[dict]) -> None:
    for profile in profiles:
        assert profile.get("run_command") or profile.get("compile_command"), (
            "profile {} offers the child no way to run what they made".format(profile["id"])
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
