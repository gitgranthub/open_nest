"""The model registry: what this Mac can run, and where that answer comes from.

Section 51 of the Phase 11 work order lists the cases. Two rules shape the whole file.

**Every test names the Mac it means.** The target hardware is an 8 GB Apple silicon Mac
and this was written on a 48 GB one. A test that inherits whichever machine it runs on
is a test that passes for the wrong reason on somebody else's, so :class:`MachineProfile`
is constructed here and handed in, never detected.

**No test reaches a network.** Section 51 again: the suite must not depend on a provider
or a catalogue server being online. Every remote path takes an injected fetcher.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opennest.models import catalog, compatibility, discovery, remote
from opennest.models.catalog import CatalogError
from opennest.models.machine import MachineProfile, problems

# --------------------------------------------------------------------------- the Macs

#: The baseline WORKORDER_01 targets, and the one that matters most.
AIR_8GB = MachineProfile(
    architecture="arm64", chip="Apple M1", macos_version="26.0",
    memory_gb=8.0, free_disk_gb=120.0, cpu_cores=8, mlx_available=True,
)
PRO_16GB = MachineProfile(
    architecture="arm64", chip="Apple M2 Pro", macos_version="26.0",
    memory_gb=16.0, free_disk_gb=300.0, cpu_cores=10, mlx_available=True,
)
STUDIO_64GB = MachineProfile(
    architecture="arm64", chip="Apple M4 Max", macos_version="26.0",
    memory_gb=64.0, free_disk_gb=1000.0, cpu_cores=16, mlx_available=True,
)
#: A Mac with plenty of memory and no room to put anything.
FULL_DISK = MachineProfile(
    architecture="arm64", chip="Apple M3", macos_version="26.0",
    memory_gb=32.0, free_disk_gb=3.0, cpu_cores=12, mlx_available=True,
)
INTEL = MachineProfile(
    architecture="x86_64", chip="Intel Core i7", macos_version="15.0",
    memory_gb=32.0, free_disk_gb=500.0, cpu_cores=8, mlx_available=False,
)
NO_ENGINE = MachineProfile(
    architecture="arm64", chip="Apple M2", macos_version="26.0",
    memory_gb=16.0, free_disk_gb=200.0, cpu_cores=8, mlx_available=False,
)


@pytest.fixture()
def entries():
    from opennest.ai import router

    return router.local_models()


def entry_for(entries, model_id):
    return next(e for e in entries if e.info.id == model_id)


# ------------------------------------------------------------------- machine profile

def test_a_profile_leaves_the_mac_room_to_work() -> None:
    """Usable memory is not installed memory. macOS is also running."""
    assert AIR_8GB.usable_memory_gb == pytest.approx(4.0)
    assert STUDIO_64GB.usable_memory_gb == pytest.approx(60.0)


def test_an_intel_mac_is_told_plainly() -> None:
    found = problems(INTEL)
    assert any("Apple silicon" in line for line in found)


def test_a_missing_engine_is_a_problem_worth_naming() -> None:
    found = problems(NO_ENGINE)
    assert any("local AI engine" in line for line in found)
    # And not a memory complaint: this Mac has plenty.
    assert not any("memory" in line for line in found)


def test_a_small_mac_is_warned_about_memory() -> None:
    tiny = MachineProfile(architecture="arm64", memory_gb=4.0, free_disk_gb=100.0,
                          mlx_available=True)
    assert any("memory" in line for line in problems(tiny))


# --------------------------------------------------------- recommendations per machine

def test_the_same_catalogue_gives_different_answers_on_different_macs(entries) -> None:
    """The entire reason this exists.

    Before Phase 11B every local entry claimed ``recommended_ram_gb: 8``, so an 8 GB Air
    and a 64 GB Studio were shown the same list and told the same thing.
    """
    big = entry_for(entries, "qwen3-coder-30b-a3b")
    assert compatibility.assess(big, AIR_8GB).state == compatibility.NOT_RECOMMENDED
    assert compatibility.assess(big, STUDIO_64GB).state == compatibility.RECOMMENDED


def test_an_8gb_mac_is_recommended_the_model_the_product_is_designed_around(entries):
    small = entry_for(entries, "qwen3-4b-instruct")
    assert compatibility.assess(small, AIR_8GB).state == compatibility.RECOMMENDED


def test_can_run_is_between_the_minimum_and_the_recommendation(entries) -> None:
    """Section 25's middle class, which is the one that has to be honest.

    Qwen3 14B asks for 16 GB minimum and 24 GB to be comfortable, so a 16 GB Mac is
    told it will work and be slower rather than either being refused or being promised
    it is fine.
    """
    middling = entry_for(entries, "qwen3-14b")
    verdict = compatibility.assess(middling, PRO_16GB)
    assert verdict.state == compatibility.CAN_RUN
    assert "slower" in verdict.reason


def test_insufficient_disk_is_not_recommended_and_says_so(entries) -> None:
    big = entry_for(entries, "qwen3-coder-30b-a3b")
    verdict = compatibility.assess(big, FULL_DISK)
    assert verdict.state == compatibility.NOT_RECOMMENDED
    assert "free" in verdict.reason


def test_disk_is_not_checked_for_a_model_already_downloaded(entries) -> None:
    """It has been paid for. Re-charging a Mac for space it already spent is nonsense."""
    big = entry_for(entries, "qwen3-coder-30b-a3b")
    assert compatibility.assess(big, FULL_DISK, installed=True).state != (
        compatibility.NOT_RECOMMENDED
    )


def test_an_intel_mac_is_incompatible_rather_than_short_of_memory(entries) -> None:
    """Order matters: more memory would not help, so it must not be implied."""
    small = entry_for(entries, "qwen3-4b-instruct")
    verdict = compatibility.assess(small, INTEL)
    assert verdict.state == compatibility.INCOMPATIBLE
    assert "Apple silicon" in verdict.reason


def test_a_missing_engine_is_incompatible_with_an_actionable_reason(entries) -> None:
    small = entry_for(entries, "qwen3-4b-instruct")
    verdict = compatibility.assess(small, NO_ENGINE)
    assert verdict.state == compatibility.INCOMPATIBLE
    assert "Setup" in verdict.reason


def test_a_cloud_model_is_not_judged_on_this_macs_hardware(entries) -> None:
    """Its requirements are a key and a switch, which is a different question."""
    from opennest.ai import router

    claude = next(e for e in router.cloud_models() if e.info.id == "claude-sonnet")
    verdict = compatibility.assess(claude, AIR_8GB)
    assert verdict.state == compatibility.RECOMMENDED
    assert "not on this Mac" in verdict.reason


def test_every_class_carries_a_sentence(entries) -> None:
    """Section 54: a test should be able to say *why*, so there is always a why."""
    for machine in (AIR_8GB, PRO_16GB, STUDIO_64GB, FULL_DISK, INTEL, NO_ENGINE):
        for verdict in compatibility.assess_all(entries, machine):
            assert verdict.reason.strip(), (verdict.model_id, machine.chip)
            assert verdict.label in compatibility.LABELS.values()


def test_the_label_is_about_fit_not_ranking() -> None:
    """Section 26: "Recommended for this Mac", never "Best Model"."""
    for label in compatibility.LABELS.values():
        assert "best" not in label.lower()
    assert "this Mac" in compatibility.LABELS[compatibility.RECOMMENDED]


# --------------------------------------------------------------------- the suggestion

def test_the_suggestion_fits_the_machine(entries) -> None:
    small = compatibility.suggestion(entries, AIR_8GB)
    big = compatibility.suggestion(entries, STUDIO_64GB)
    assert small[0].info.id == "qwen3-4b-instruct"
    assert big[0].download_gb > small[0].download_gb, (
        "a 64 GB Studio was suggested the same model as an 8 GB Air"
    )


def test_an_installed_model_is_suggested_over_a_download(entries) -> None:
    """Section 31, at the moment it matters most.

    Suggesting a 17 GB download to somebody who already has a working model is the
    wrong suggestion however roomy their Mac is.
    """
    chosen, verdict = compatibility.suggestion(
        entries, STUDIO_64GB, installed_ids=["qwen3-4b-instruct"]
    )
    assert chosen.info.id == "qwen3-4b-instruct"
    assert verdict.installed


def test_a_model_that_cannot_use_tools_is_never_suggested(entries) -> None:
    """It can discuss a game and cannot build one, so it is not an answer."""
    chosen, _ = compatibility.suggestion(entries, AIR_8GB)
    assert chosen.info.supports_tools


def test_a_mac_that_can_run_nothing_is_suggested_nothing(entries) -> None:
    assert compatibility.suggestion(entries, INTEL) is None


# ------------------------------------------------------------------------- the catalog

def test_the_bundled_catalogue_stands_alone() -> None:
    """Section 27: setup works offline, and a catalogue server is not required."""
    merged = catalog.merge(catalog.bundled_payload(), None)
    assert merged.entries
    assert not merged.used_remote
    assert merged.default_local_model == "qwen3-4b-instruct"


def test_a_remote_entry_revises_a_bundled_one() -> None:
    bundled = catalog.bundled_payload()
    merged = catalog.merge(bundled, {
        "schema_version": 4,
        "models": [{
            "id": "qwen3-4b-instruct", "name": "Qwen3 4B", "provider": "mlx",
            "runtime": "mlx", "model_id": "mlx-community/Qwen3-4B-Instruct-2507-4bit",
            "revision": "0" * 40, "status": "deprecated",
            "description": "Superseded", "minimum_memory_gb": 8,
        }],
    })
    entry = merged.get("qwen3-4b-instruct")
    assert entry.status == "deprecated"
    assert entry.source == "remote"
    assert merged.used_remote


def test_a_remote_catalogue_cannot_change_what_a_fresh_mac_downloads() -> None:
    """``default_local_model`` decides for a Mac nobody has looked at yet."""
    merged = catalog.merge(
        catalog.bundled_payload(),
        {"schema_version": 4, "default_local_model": "something-else", "models": []},
    )
    assert merged.default_local_model == "qwen3-4b-instruct"


def test_a_withdrawn_model_stops_being_offered() -> None:
    merged = catalog.merge(catalog.bundled_payload(), {
        "schema_version": 4,
        "models": [{
            "id": "gemma2-2b", "name": "Gemma 2 2B", "provider": "mlx", "runtime": "mlx",
            "model_id": "mlx-community/gemma-2-2b-it-4bit", "revision": "0" * 40,
            "status": "withdrawn", "description": "gone",
        }],
    })
    assert merged.get("gemma2-2b") is None


def test_one_bad_entry_does_not_cost_the_others() -> None:
    """A malformed row in a remote file must not take a family's model list with it."""
    kept, refused = catalog.validate({
        "schema_version": 4,
        "models": [
            {"id": "good", "name": "Good", "provider": "mlx", "runtime": "mlx",
             "model_id": "org/name", "revision": "a" * 40},
            {"id": "bad", "name": "Bad", "provider": "not-a-provider"},
        ],
    })
    assert [item["id"] for item in kept] == ["good"]
    assert refused == ["bad"]


@pytest.mark.parametrize("payload", [
    "not a dict",
    {"models": []},
    {"schema_version": "four", "models": []},
    {"schema_version": 4},
    {"schema_version": catalog.SUPPORTED_SCHEMA + 1, "models": []},
])
def test_a_payload_that_is_not_a_catalogue_is_refused(payload) -> None:
    with pytest.raises(CatalogError):
        catalog.validate(payload)


@pytest.mark.parametrize("bad", [
    {"id": "x", "name": "X", "provider": "mlx", "model_id": "no-slash",
     "revision": "a" * 40},
    {"id": "x", "name": "X", "provider": "mlx", "model_id": "org/name",
     "revision": "not-a-sha"},
    {"id": "x", "name": "X", "provider": "mlx", "model_id": "org/name",
     "revision": "a" * 40, "runtime": "cuda"},
    {"id": "x", "name": "X", "provider": "mlx", "model_id": "org/name",
     "revision": "a" * 40, "capabilities": ["mind-reading"]},
    {"id": "x", "name": "X", "provider": "mlx", "model_id": "org/name",
     "revision": "a" * 40, "minimum_memory_gb": -5},
    {"id": "x", "name": "X", "provider": "mlx", "model_id": "org/name",
     "revision": "a" * 40, "minimum_open_nest_version": "99.0.0"},
    {"id": "UPPER", "name": "X", "provider": "mlx", "model_id": "org/name",
     "revision": "a" * 40},
])
def test_a_hostile_or_broken_entry_is_dropped(bad) -> None:
    kept, refused = catalog.validate({"schema_version": 4, "models": [bad]})
    assert kept == []
    assert refused


def test_a_catalogue_cannot_name_a_download_location() -> None:
    """Section 29's structural half.

    The strongest version of "a catalogue may not execute anything" is that there is no
    field for a URL, a path or a command -- so a hostile catalogue's worst case is
    naming a repository that does not exist, which fails closed at download time.
    """
    kept, _ = catalog.validate({
        "schema_version": 4,
        "models": [{
            "id": "sneaky", "name": "Sneaky", "provider": "mlx", "runtime": "mlx",
            "model_id": "org/name", "revision": "a" * 40,
            "url": "https://evil.example.com/payload.bin",
            "command": "rm -rf /", "path": "/etc/passwd",
        }],
    })
    built = catalog.build_entry(kept[0], source="remote")
    for attribute in vars(built).values():
        assert "evil.example.com" not in str(attribute)
        assert "rm -rf" not in str(attribute)


# --------------------------------------------------------------- the remote catalogue

@pytest.fixture()
def cache(tmp_path, monkeypatch):
    target = tmp_path / "model_catalog.json"
    monkeypatch.setattr(remote, "cache_file", lambda: target)
    catalog.load.cache_clear()
    yield target
    catalog.load.cache_clear()


GOOD_REMOTE = {
    "schema_version": 4,
    "models": [{
        "id": "future-qwen-test-model", "name": "Future Qwen", "provider": "mlx",
        "runtime": "mlx", "model_id": "mlx-community/Future-Qwen-4bit",
        "revision": "b" * 40, "description": "A model from the future",
        "capabilities": ["chat", "code"], "download_gb": 5.0,
        "estimated_memory_gb": 6.3, "minimum_memory_gb": 16,
        "recommended_memory_gb": 16, "supports_tools": True,
    }],
}


def test_a_successful_refresh_updates_and_caches(cache) -> None:
    result = remote.refresh(fetch=lambda url, t, m: json.dumps(GOOD_REMOTE))
    assert result.ok and result.outcome == "updated"
    assert json.loads(cache.read_text()) == GOOD_REMOTE


def test_a_second_identical_refresh_says_so(cache) -> None:
    remote.refresh(fetch=lambda url, t, m: json.dumps(GOOD_REMOTE))
    again = remote.refresh(fetch=lambda url, t, m: json.dumps(GOOD_REMOTE))
    assert again.outcome == "unchanged"
    assert "up to date" in again.message


def test_being_offline_is_an_answer_not_an_error(cache) -> None:
    """Section 46, and the copy section 44 asks for."""
    def boom(url, timeout, limit):
        raise OSError("no route to host")

    result = remote.refresh(fetch=boom)
    assert not result.ok
    assert result.outcome == "unavailable"
    assert "offline" in result.message.lower()
    assert "saved model list" in result.message


def test_a_catalogue_server_returning_nothing_changes_nothing(cache) -> None:
    result = remote.refresh(fetch=lambda url, t, m: None)
    assert result.outcome == "unavailable"
    assert not cache.exists()


def test_a_malformed_remote_catalogue_is_refused_and_not_cached(cache) -> None:
    result = remote.refresh(fetch=lambda url, t, m: "{not json")
    assert result.outcome == "rejected"
    assert not cache.exists()


def test_a_refresh_only_ever_speaks_https(cache) -> None:
    result = remote.refresh(url="http://example.com/models.json",
                            fetch=lambda url, t, m: json.dumps(GOOD_REMOTE))
    assert result.outcome == "rejected"
    assert "https" in result.message


def test_a_damaged_cache_reads_as_absent_and_is_left_alone(cache) -> None:
    cache.write_text("{{{ not json", encoding="utf-8")
    assert remote.cached() is None
    assert cache.exists(), "a damaged cache was deleted rather than left for repair"


def test_the_bundled_list_still_works_when_a_refresh_failed(cache) -> None:
    """Section 46's headline, and the case every installation is in today."""
    remote.refresh(fetch=lambda url, t, m: None)
    merged = catalog.merge(catalog.bundled_payload(), remote.cached())
    assert merged.get("qwen3-4b-instruct") is not None
    assert not merged.used_remote


# ------------------------------------------------------- a model written after the code

def test_a_model_that_did_not_exist_when_this_was_written_needs_no_code_change(
    cache, tmp_path
) -> None:
    """Section 63, which is the proof the architecture is actually dynamic.

    Nothing anywhere special-cases ``future-qwen-test-model``. It arrives as metadata,
    is validated, is classified against a Mac, and could be presented -- all through the
    same paths the bundled entries take.
    """
    cache.write_text(json.dumps(GOOD_REMOTE), encoding="utf-8")
    merged = catalog.merge(catalog.bundled_payload(), remote.cached())

    entry = merged.get("future-qwen-test-model")
    assert entry is not None, "a catalogue-only model did not appear"
    assert entry.source == "remote"

    # And it is judged, not merely listed: 16 GB minimum against the two Macs.
    assert compatibility.assess(entry, AIR_8GB).state == compatibility.NOT_RECOMMENDED
    assert compatibility.assess(entry, PRO_16GB).state == compatibility.RECOMMENDED

    # It could even become the suggestion on a Mac that suits it, which is the whole
    # point -- without a line of UI changing.
    chosen, _ = compatibility.suggestion([entry], PRO_16GB)
    assert chosen.info.id == "future-qwen-test-model"


def test_a_new_catalogue_entry_downloads_nothing(cache, monkeypatch) -> None:
    """Section 30. A catalogue changes choices; it does not consume gigabytes."""
    from opennest.setup import downloader

    calls = []
    monkeypatch.setattr(downloader, "download", lambda *a, **k: calls.append(a))

    remote.refresh(fetch=lambda url, t, m: json.dumps(GOOD_REMOTE))
    catalog.merge(catalog.bundled_payload(), remote.cached())
    assert calls == [], "merging a catalogue started a download"


# ------------------------------------------------------------------ provider discovery

ANTHROPIC_LISTING = {
    "data": [
        {"id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"},
        {"id": "claude-opus-9", "display_name": "Claude Opus 9"},
    ]
}

OPENAI_LISTING = {
    "data": [
        {"id": "gpt-5.6-luna"},
        {"id": "gpt-7-nova"},
        {"id": "text-embedding-4-large"},
        {"id": "whisper-2"},
        {"id": "dall-e-4"},
    ]
}


def test_a_known_cloud_model_is_recognised(entries) -> None:
    from opennest.ai import router

    found = discovery.discover(
        "anthropic", router.load_catalogue(), fetch=lambda url: ANTHROPIC_LISTING
    )
    known = [item for item in found if item.state == "known"]
    assert [item.model_id for item in known] == ["claude-sonnet-5"]


def test_a_newly_discovered_cloud_model_is_available_not_recommended() -> None:
    """Section 36: appearing in a provider's list is availability, not endorsement."""
    from opennest.ai import router

    found = discovery.discover(
        "anthropic", router.load_catalogue(), fetch=lambda url: ANTHROPIC_LISTING
    )
    new = next(item for item in found if item.model_id == "claude-opus-9")
    assert new.state == "available"
    assert new.offerable
    # And it is not in the catalogue, so nothing offers it to a child.
    assert router.load_catalogue() and not any(
        e.model_id == "claude-opus-9" for e in router.load_catalogue()
    )


def test_a_provider_wall_of_models_is_filtered_not_dumped() -> None:
    """Section 34. Embeddings, speech and images cannot answer a conversation."""
    from opennest.ai import router

    found = discovery.discover(
        "openai", router.load_catalogue(), fetch=lambda url: OPENAI_LISTING
    )
    by_state = {item.model_id: item.state for item in found}
    assert by_state["gpt-5.6-luna"] == "known"
    assert by_state["gpt-7-nova"] == "available"
    for irrelevant in ("text-embedding-4-large", "whisper-2", "dall-e-4"):
        assert by_state[irrelevant] == "unsupported", irrelevant


def test_a_provider_answering_nonsense_yields_nothing() -> None:
    from opennest.ai import router

    assert discovery.discover(
        "anthropic", router.load_catalogue(), fetch=lambda url: {"oops": True}
    ) == ()
    assert discovery.parse_listing("openai", {"data": "not a list"}) == ()


def test_an_unknown_provider_is_not_guessed_at() -> None:
    from opennest.ai import router

    assert discovery.discover("hypothetical", router.load_catalogue(),
                              fetch=lambda url: OPENAI_LISTING) == ()


# ------------------------------------------------------------------------- containment

def test_open_nest_loads_models_only_from_its_own_store(monkeypatch, tmp_path) -> None:
    """The containment promise, and the reason it is not simply "look everywhere".

    Everything Open Nest downloads lives under ``OPENNEST_HOME``. Reading a model some
    other tool left in a shared cache would widen that silently, on a machine where the
    whole point is that model weights stay somewhere known.
    """
    from opennest import paths

    monkeypatch.setattr(paths, "models_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(discovery, "adopted_paths", lambda: ())
    assert discovery.load_paths() == (tmp_path / "store",)


def test_the_search_looks_wider_than_the_loader(monkeypatch, tmp_path) -> None:
    """Finding is not loading. The gap is what makes adopting a model a choice."""
    from opennest import paths

    monkeypatch.setattr(paths, "models_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(discovery, "adopted_paths", lambda: ())
    assert len(discovery.discover_paths()) > len(discovery.load_paths())


def test_an_adopted_cache_becomes_loadable_and_nothing_else_does(
    monkeypatch, tmp_path
) -> None:
    from opennest import paths

    monkeypatch.setattr(paths, "models_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(discovery, "adopted_paths", lambda: (tmp_path / "theirs",))
    assert discovery.load_paths() == (tmp_path / "store", tmp_path / "theirs")


# -------------------------------------------------------- models already on this Mac

def _make_hf_model(cache: Path, repo: str, files: dict) -> Path:
    directory = cache / ("models--" + repo.replace("/", "--")) / "snapshots" / "abc123"
    directory.mkdir(parents=True)
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")
    return directory


def test_a_model_in_another_format_is_listed_and_declined(monkeypatch, tmp_path) -> None:
    """Section 32, and the real case on the machine this was written on.

    A ``faster-whisper`` model sits in the standard Hugging Face cache: a genuine model,
    in the right folder, that Open Nest cannot run. Saying "none found" would be wrong;
    offering it would be worse.
    """
    from opennest.ai import router

    cache = tmp_path / "hub"
    cache.mkdir()
    _make_hf_model(cache, "Systran/faster-whisper-large-v3",
                   {"config.json": "{}", "model.bin": "x"})
    monkeypatch.setattr(discovery, "discover_paths", lambda: (cache,))
    monkeypatch.setattr(discovery, "extra_search_paths", lambda: ())

    found = discovery.search_local_models(router.load_catalogue())
    assert len(found) == 1
    assert found[0].kind == discovery.UNSUPPORTED
    assert not found[0].can_attempt
    assert "MLX" in found[0].reason


def test_a_gguf_model_is_named_as_the_wrong_format(monkeypatch, tmp_path) -> None:
    from opennest.ai import router

    cache = tmp_path / "hub"
    cache.mkdir()
    directory = _make_hf_model(cache, "someone/a-gguf-model", {"config.json": "{}"})
    (directory / "weights.gguf").write_text("x", encoding="utf-8")
    monkeypatch.setattr(discovery, "discover_paths", lambda: (cache,))
    monkeypatch.setattr(discovery, "extra_search_paths", lambda: ())

    found = discovery.search_local_models(router.load_catalogue())
    assert found[0].kind == discovery.UNSUPPORTED
    assert "GGUF" in found[0].reason


def test_an_mlx_model_is_offered_as_something_to_attempt(monkeypatch, tmp_path) -> None:
    from opennest.ai import router

    cache = tmp_path / "hub"
    cache.mkdir()
    directory = _make_hf_model(cache, "someone/an-mlx-model", {
        "config.json": json.dumps({"model_type": "qwen3", "architectures": ["Qwen3"]}),
    })
    (directory / "model.safetensors").write_text("x", encoding="utf-8")
    monkeypatch.setattr(discovery, "discover_paths", lambda: (cache,))
    monkeypatch.setattr(discovery, "extra_search_paths", lambda: ())

    found = discovery.search_local_models(router.load_catalogue())
    assert found[0].kind == discovery.USABLE
    assert found[0].can_attempt
    assert found[0].reason == ""


def test_an_ollama_library_is_listed_with_the_reason(monkeypatch, tmp_path) -> None:
    """Silence here reads as a broken search to somebody who knows what they have."""
    from opennest.ai import router

    ollama = tmp_path / "ollama"
    manifests = ollama / "manifests" / "registry.ollama.ai" / "library" / "llama3"
    manifests.mkdir(parents=True)
    (manifests / "latest").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(discovery, "discover_paths", lambda: ())
    monkeypatch.setattr(discovery, "extra_search_paths", lambda: (("Ollama", ollama),))

    found = discovery.search_local_models(router.load_catalogue())
    assert found and all(item.kind == discovery.UNSUPPORTED for item in found)
    assert all("Ollama" in item.reason for item in found)


def test_finding_nothing_is_an_empty_list_not_an_error(monkeypatch, tmp_path) -> None:
    from opennest.ai import router

    monkeypatch.setattr(discovery, "discover_paths", lambda: (tmp_path / "nowhere",))
    monkeypatch.setattr(discovery, "extra_search_paths", lambda: ())
    assert discovery.search_local_models(router.load_catalogue()) == ()


# --------------------------------------------------------------------------- migration

class _State:
    """Just enough of InstallationState to migrate."""

    def __init__(self, preferred="", installed=None):
        self.preferred_model = preferred
        self.installed_models = list(installed or [])


def test_a_valid_preference_survives_migration() -> None:
    """Section 55, and the case Phase 12 depends on."""
    from opennest.models.migration import migrate

    state = _State("qwen3-4b-instruct", ["qwen3-4b-instruct"])
    result = migrate(state, installed_ids=["qwen3-4b-instruct"])
    assert state.preferred_model == "qwen3-4b-instruct"
    assert not result.changed


def test_a_preference_the_catalogue_dropped_is_cleared_not_repointed() -> None:
    """Section 38 forbids substituting a model behind somebody's back."""
    from opennest.models.migration import migrate

    state = _State("a-model-that-was-withdrawn", [])
    migrate(state, installed_ids=[])
    assert state.preferred_model == ""


def test_a_model_found_on_disk_is_adopted_rather_than_redownloaded() -> None:
    """The owner's Mac, on the launch after an upgrade."""
    from opennest.models.migration import migrate

    state = _State("", [])
    result = migrate(state, installed_ids=["qwen3-4b-instruct"])
    assert state.preferred_model == "qwen3-4b-instruct"
    assert state.installed_models == ["qwen3-4b-instruct"]
    assert any("already installed" in note for note in result.notes)


def test_a_record_claiming_a_model_that_is_gone_is_corrected() -> None:
    from opennest.models.migration import migrate

    state = _State("", ["qwen3-4b-instruct"])
    migrate(state, installed_ids=[])
    assert state.installed_models == []


# --------------------------------------------------------------- what a parent reads

def test_an_untested_model_already_on_disk_is_not_promised_a_download() -> None:
    """Two sentences that appeared together and contradicted each other.

    Phase 12 drove the wizard and read what came out, for a model that was already on
    the Mac:

        It is already on this Mac, so nothing will be downloaded. Open Nest has not
        tested this model itself yet. It should work on this Mac, and it will be
        checked after it downloads.

    Nothing was going to download. The check does still happen either way, so only the
    clause naming a download was wrong.
    """
    from opennest.ai import router
    from opennest.models import compatibility

    entry = router.get_entry("qwen3-14b")      # pinned, described, never run
    assert not entry.verified, "pick an unverified entry for this test"

    fresh = compatibility.untested_note(entry, installed=False)
    here = compatibility.untested_note(entry, installed=True)

    assert "after it downloads" in fresh
    assert "download" not in here, here
    assert "checked" in here, "an untested model must still say it will be checked"


def test_a_verified_model_says_nothing_either_way() -> None:
    from opennest.ai import router
    from opennest.models import compatibility

    entry = router.get_entry("qwen3-4b-instruct")
    assert entry.verified
    assert compatibility.untested_note(entry, installed=False) == ""
    assert compatibility.untested_note(entry, installed=True) == ""


def test_the_second_local_model_is_verified_now() -> None:
    """Phase 12 ran Qwen3 8B through downloader.verify: 3.0 s, all three ticks.

    Worth pinning as a fact rather than a comment, because ``verified`` is what
    ``untested_note`` keys off and because Phase 11 shipped a bug that rested on
    exactly one entry holding it -- a tiebreak only one row can win never moves.
    """
    from opennest.ai import router

    verified = {e.info.id for e in router.local_models() if e.verified}
    assert {"qwen3-4b-instruct", "qwen3-8b"} <= verified, verified
