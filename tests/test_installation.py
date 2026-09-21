"""The installation record, and what it lets the next launch notice.

WORKORDER_01 section 35A ("Installation state", "Relaunch behavior") and the DoD 51-53
update path. Two themes run through these, and both are stances the codebase already
takes elsewhere:

**Damaged means repair, never reset.** A record that will not parse sends a parent to
setup and deletes nothing. Losing a parent's configuration because a write was
interrupted is worse than asking them to run setup again -- and losing a *project* that
way would be unforgivable, so there is a test that migration detection touches nothing.

**Nothing here is a secret.** Section 35A says so outright and section 22 lists JSON
configuration by name, so the guard is the same scanner that refuses a Git commit.
"""

from __future__ import annotations

import json

import pytest

from opennest import __version__
from opennest.setup import state
from opennest.setup.state import Change, Fingerprint, InstallationState

# ------------------------------------------------------------------ fresh install

def test_a_mac_with_no_record_needs_setup(tmp_path) -> None:
    """The ordinary first run. Absent is not damaged."""
    loaded = InstallationState.load(tmp_path / "installation.json")
    assert loaded.needs_setup() is True
    assert loaded.unreadable is False
    assert loaded.setup_complete is False


def test_the_defaults_are_the_cautious_ones(tmp_path) -> None:
    fresh = InstallationState()
    assert fresh.setup_complete is False
    assert fresh.cloud_enabled is False
    assert fresh.github_enabled is False
    assert fresh.arduino_installed is False
    assert fresh.installed_models == []


def test_a_completed_setup_launches_the_app_instead(tmp_path) -> None:
    """Section 35A: "setup complete -> Build Lab", otherwise the wizard."""
    target = tmp_path / "installation.json"
    InstallationState(setup_complete=True, preferred_model="qwen3-4b-instruct").save(target)
    assert InstallationState.load(target).needs_setup() is False


# ------------------------------------------------------------------ persistence

def test_the_record_round_trips(tmp_path) -> None:
    target = tmp_path / "installation.json"
    written = InstallationState(
        setup_complete=True,
        preferred_model="qwen3-4b-instruct",
        cloud_enabled=True,
        github_enabled=False,
        child_name="Elliot",
        git_author_name="Elliot",
        git_author_email="elliot@example.com",
        installed_models=["qwen3-4b-instruct"],
        arduino_installed=True,
    )
    written.record_launch()
    written.save(target)

    loaded = InstallationState.load(target)
    assert loaded.setup_complete is True
    assert loaded.preferred_model == "qwen3-4b-instruct"
    assert loaded.cloud_enabled is True
    assert loaded.child_name == "Elliot"
    assert loaded.git_author_email == "elliot@example.com"
    assert loaded.installed_models == ["qwen3-4b-instruct"]
    assert loaded.arduino_installed is True
    assert loaded.fingerprint == written.fingerprint


def test_the_file_matches_the_shape_the_work_order_describes(tmp_path) -> None:
    """Section 35A gives an example object; the file on disk should look like it."""
    target = tmp_path / "installation.json"
    InstallationState(setup_complete=True, preferred_model="qwen-local").save(target)
    raw = json.loads(target.read_text())
    for key in ("setup_complete", "schema_version", "preferred_model",
                "cloud_enabled", "github_enabled"):
        assert key in raw, f"section 35A's example names {key}"


def test_a_half_written_file_means_repair_and_not_a_fresh_start(tmp_path) -> None:
    """Damaged metadata triggers setup or repair. It never silently resets anything."""
    target = tmp_path / "installation.json"
    target.write_text('{"setup_complete": true, "prefer')  # truncated mid-write

    loaded = InstallationState.load(target)
    assert loaded.unreadable is True
    assert loaded.needs_setup() is True
    # The damaged file is still there for a person to look at.
    assert target.exists()


def test_a_file_holding_the_wrong_shape_is_not_trusted(tmp_path) -> None:
    target = tmp_path / "installation.json"
    target.write_text('["not", "an", "object"]')
    assert InstallationState.load(target).needs_setup() is True


def test_a_field_of_the_wrong_type_falls_back_to_the_safe_default(tmp_path) -> None:
    """The default's type is what a field is allowed to be -- ParentControls' rule."""
    target = tmp_path / "installation.json"
    target.write_text(json.dumps({
        "setup_complete": "yes",          # a string where a switch belongs
        "preferred_model": 17,            # a number where a name belongs
        "installed_models": "qwen",       # a string where a list belongs
        "cloud_enabled": True,            # this one is fine
    }))
    loaded = InstallationState.load(target)
    assert loaded.setup_complete is False
    assert loaded.preferred_model == ""
    assert loaded.installed_models == []
    assert loaded.cloud_enabled is True


def test_an_interrupted_save_cannot_truncate_the_previous_record(tmp_path) -> None:
    """save() writes through a temporary file, so there is no partial state on disk."""
    target = tmp_path / "installation.json"
    InstallationState(setup_complete=True, child_name="Elliot").save(target)
    assert not list(tmp_path.glob("*.tmp")), "the scratch file should not be left behind"
    assert InstallationState.load(target).child_name == "Elliot"


# ------------------------------------------------------------------ no secrets

def test_the_record_refuses_anything_credential_shaped(tmp_path) -> None:
    """Section 35A: do not store secrets in this configuration."""
    record = InstallationState(
        setup_complete=True,
        # A plausible mistake: stashing the key next to the switch that uses it.
        child_name="sk-ant-api03-" + "A" * 80,
    )
    with pytest.raises(ValueError, match="Keychain"):
        record.save(tmp_path / "installation.json")
    assert not (tmp_path / "installation.json").exists()


def test_no_field_is_named_like_a_credential() -> None:
    """A guard against the change that one day adds one "just for convenience"."""
    banned = ("key", "token", "secret", "password", "pin")
    for name in InstallationState().as_dict():
        assert not any(word in name.lower() for word in banned), name


# ------------------------------------------------------------------ fingerprints

def test_the_fingerprint_describes_the_checkout_it_was_taken_from() -> None:
    current = Fingerprint.current()
    assert current.app_version == __version__
    assert current.profiles_schema >= 1
    assert current.models_schema >= 1
    assert "base.txt" in current.requirements
    assert "projects.txt" in current.requirements, "Phase 7 put this in the bootstrap"
    # Every local model is pinned to a commit, so every one contributes a pin.
    assert "qwen3-4b-instruct" in current.model_pins


def test_nothing_changed_means_no_migration() -> None:
    current = Fingerprint.current()
    assert state.changes_since(current, current) == ()


def test_a_fresh_install_is_not_treated_as_an_update() -> None:
    """Never recorded is a setup question. A migration prompt here would be nonsense."""
    assert state.changes_since(Fingerprint(), Fingerprint.current()) == ()


def test_a_changed_requirements_file_is_a_dependency_change() -> None:
    """Section "Repository update behavior": "dependency manifest changes"."""
    before = Fingerprint(app_version="0.1.0", requirements={"base.txt": "aaa"})
    after = Fingerprint(app_version="0.1.0", requirements={"base.txt": "bbb"})
    kinds = [change.kind for change in state.changes_since(before, after)]
    assert kinds == ["dependencies"]


def test_a_new_requirements_file_counts_too() -> None:
    """Phase 7 adding projects.txt to the bootstrap is exactly this case."""
    before = Fingerprint(app_version="0.1.0", requirements={"base.txt": "aaa"})
    after = Fingerprint(
        app_version="0.1.0", requirements={"base.txt": "aaa", "projects.txt": "ccc"}
    )
    changes = state.changes_since(before, after)
    assert [change.kind for change in changes] == ["dependencies"]
    assert "projects.txt" in changes[0].summary


def test_a_bumped_config_schema_is_a_schema_change() -> None:
    before = Fingerprint(app_version="0.1.0", profiles_schema=1, models_schema=3)
    after = Fingerprint(app_version="0.1.0", profiles_schema=2, models_schema=3)
    changes = state.changes_since(before, after)
    assert [change.kind for change in changes] == ["schema"]
    assert "1" in changes[0].summary and "2" in changes[0].summary


def test_a_moved_model_pin_is_reported_as_costly() -> None:
    """PLAN.md: a moved pin implies a multi-gigabyte download. Shown, never started."""
    before = Fingerprint(app_version="0.1.0", model_pins={"qwen3-4b-instruct": "aaa"})
    after = Fingerprint(app_version="0.1.0", model_pins={"qwen3-4b-instruct": "bbb"})
    changes = state.changes_since(before, after)
    assert len(changes) == 1
    assert changes[0].kind == "models"
    assert changes[0].costly is True, "a re-download must be flagged before it starts"


def test_a_new_model_is_not_costly_on_its_own() -> None:
    """Offering a model nobody has downloaded costs nothing until someone picks it."""
    before = Fingerprint(app_version="0.1.0", model_pins={"a": "1"})
    after = Fingerprint(app_version="0.1.0", model_pins={"a": "1", "b": "2"})
    changes = state.changes_since(before, after)
    assert [change.costly for change in changes] == [False]


def test_a_withdrawn_model_is_reported() -> None:
    before = Fingerprint(app_version="0.1.0", model_pins={"a": "1", "b": "2"})
    after = Fingerprint(app_version="0.1.0", model_pins={"a": "1"})
    changes = state.changes_since(before, after)
    assert len(changes) == 1 and changes[0].kind == "models"


def test_several_kinds_of_change_are_all_reported() -> None:
    """A real pull moves more than one thing, and a parent should see all of it."""
    before = Fingerprint(
        app_version="0.1.0", requirements={"base.txt": "aaa"},
        profiles_schema=1, models_schema=3, model_pins={"a": "1"},
    )
    after = Fingerprint(
        app_version="0.2.0", requirements={"base.txt": "bbb"},
        profiles_schema=2, models_schema=4, model_pins={"a": "2"},
    )
    kinds = {change.kind for change in state.changes_since(before, after)}
    assert kinds == {"dependencies", "schema", "models"}


def test_every_change_says_something_a_parent_could_read() -> None:
    before = Fingerprint(app_version="0.1.0", requirements={"base.txt": "aaa"},
                         profiles_schema=1, model_pins={"qwen3-4b-instruct": "aaa"})
    after = Fingerprint(app_version="0.2.0", requirements={"base.txt": "bbb"},
                        profiles_schema=2, model_pins={"qwen3-4b-instruct": "bbb"})
    for change in state.changes_since(before, after):
        assert isinstance(change, Change)
        assert change.summary.endswith("."), change.summary
        assert "sha256" not in change.summary.lower()
        assert len(change.summary) < 200, "a summary is a sentence, not a diff"


# ------------------------------------------------------------------ safety of the check

def test_detecting_changes_writes_nothing(tmp_path) -> None:
    """DoD 52: an update must not lose projects. The detection step touches no disk."""
    target = tmp_path / "installation.json"
    record = InstallationState(setup_complete=True)
    record.fingerprint = Fingerprint(app_version="0.0.1", requirements={"base.txt": "old"})
    record.save(target)

    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    loaded = InstallationState.load(target)
    assert loaded.pending_changes(), "the scenario should report an update"
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_recording_a_launch_adopts_the_current_checkout(tmp_path) -> None:
    """The fingerprint means "known to work against this", so it is written after."""
    record = InstallationState(setup_complete=True)
    record.fingerprint = Fingerprint(app_version="0.0.1", requirements={"base.txt": "old"})
    assert record.pending_changes()
    record.record_launch()
    assert record.pending_changes() == ()
