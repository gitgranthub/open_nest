"""Tool dispatch: permission, path confinement, and tolerance of model sloppiness."""

from __future__ import annotations

from pathlib import Path

import pytest

from opennest.agent.tools import Toolbox, normalise_tool_name
from opennest.projects.manager import create_project
from opennest.security.process_sandbox import sandbox_available

#: run_project fails closed when the process sandbox cannot be applied, which is the
#: correct behaviour and not something to work around -- so tests that start a project
#: skip instead. This is what happens when the suite is run inside scripts/offline.sh,
#: because Seatbelt profiles cannot be nested.
needs_sandbox = pytest.mark.skipif(
    not sandbox_available(), reason="the process sandbox cannot be applied here"
)


@pytest.fixture
def box(tmp_path: Path) -> Toolbox:
    project = create_project("Asteroid Game", "games", root=tmp_path)
    return Toolbox(project)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("run_project", "run_project"),
        ("run_project()", "run_project"),
        ("functions.run_project", "run_project"),
        ("  read_file  ", "read_file"),
        ("tools.write_file()", "write_file"),
        (None, None),
        ("", None),
        (123, None),
    ],
)
def test_tool_names_are_normalised(raw, expected) -> None:
    """Phase 1: 'run_project()' is the right answer, awkwardly spelled."""
    assert normalise_tool_name(raw) == expected


def test_no_profile_offers_an_explore_tool() -> None:
    """SPIKES.md section 4: the file list is injected, never fetched by the model."""
    from opennest.projects.profiles import load_profiles
    for profile in load_profiles():
        assert "list_project_files" not in profile.tools, profile.id
        assert len(profile.tools) <= 4, f"{profile.id} offers {len(profile.tools)} tools"


def test_unknown_tool_is_refused_with_the_available_list(box: Toolbox) -> None:
    result = box.dispatch("delete_everything", {})
    assert not result.ok
    assert "read_file" in result.content


def test_tool_outside_the_profile_is_refused(box: Toolbox) -> None:
    """games has run_project, not compile_project."""
    assert not box.dispatch("compile_project", {}).ok


def test_write_then_read_round_trip(box: Toolbox) -> None:
    written = box.dispatch("write_file", {"path": "src/hello.py", "content": "print('hi')\n"})
    assert written.ok and written.changed_files == ("src/hello.py",)
    assert box.dispatch("read_file", {"path": "src/hello.py"}).content == "print('hi')\n"


def test_write_creates_missing_directories(box: Toolbox) -> None:
    assert box.dispatch("write_file", {"path": "src/deep/nested/x.py", "content": "x=1"}).ok


def test_path_escape_is_refused_not_raised(box: Toolbox) -> None:
    result = box.dispatch("write_file", {"path": "../../evil.py", "content": "bad"})
    assert not result.ok and "outside the project" in result.content


def test_internal_directory_is_refused(box: Toolbox) -> None:
    assert not box.dispatch("read_file", {"path": ".opennest/project_bible.md"}).ok


def test_reading_a_missing_file_explains_plainly(box: Toolbox) -> None:
    result = box.dispatch("read_file", {"path": "nope.py"})
    assert not result.ok and "no file called" in result.content


def test_arguments_as_json_string_are_accepted(box: Toolbox) -> None:
    """Models frequently send arguments as a string instead of an object."""
    assert box.dispatch("write_file", '{"path": "src/a.py", "content": "a=1"}').ok


def test_malformed_argument_json_is_reported(box: Toolbox) -> None:
    result = box.dispatch("write_file", "{not json")
    assert not result.ok and "not valid JSON" in result.content


def test_missing_required_argument_is_reported(box: Toolbox) -> None:
    assert not box.dispatch("read_file", {}).ok
    assert not box.dispatch("write_file", {"path": "x.py"}).ok


def test_inspect_error_is_not_a_tool(box: Toolbox) -> None:
    """The last run result is injected into context instead. See SPIKES.md."""
    assert not box.dispatch("inspect_error", {}).ok


@needs_sandbox
def test_failed_run_is_reported_with_the_error(box: Toolbox) -> None:
    (box.project.directory / "src" / "game.py").write_text("raise ValueError('boom')\n")
    run = box.dispatch("run_project", {})
    assert not run.ok and "boom" in run.content
    assert box.last_run is not None and "boom" in box.last_run.failure_text


@needs_sandbox
def test_successful_run_is_reported(box: Toolbox) -> None:
    (box.project.directory / "src" / "game.py").write_text("print('it works')\n")
    result = box.dispatch("run_project", {})
    assert result.ok and "it works" in result.content


@needs_sandbox
def test_a_successful_run_is_remembered_in_the_manifest(box: Toolbox) -> None:
    """Section 15A: run status is a fact the application records, not one it asks for."""
    from opennest.projects.manager import read_manifest

    (box.project.directory / "src" / "game.py").write_text("print('ok')\n")
    assert box.project.manifest.last_successful_run is None
    box.dispatch("run_project", {})
    assert read_manifest(box.project.directory).last_successful_run is not None


@needs_sandbox
def test_a_failed_run_is_not_remembered_as_a_success(box: Toolbox) -> None:
    (box.project.directory / "src" / "game.py").write_text("raise ValueError('no')\n")
    box.dispatch("run_project", {})
    assert box.project.manifest.last_successful_run is None


def test_edit_file_replaces_one_exact_line(box: Toolbox) -> None:
    (box.project.directory / "src" / "game.py").write_text("SPEED = 5\nSIZE = 40\n")
    result = box.dispatch("edit_file", {"path": "src/game.py",
                                        "old_text": "SPEED = 5", "new_text": "SPEED = 9"})
    assert result.ok and result.changed_files == ("src/game.py",)
    assert (box.project.directory / "src" / "game.py").read_text() == "SPEED = 9\nSIZE = 40\n"


def test_edit_file_refuses_text_that_is_not_there(box: Toolbox) -> None:
    (box.project.directory / "src" / "game.py").write_text("SPEED = 5\n")
    result = box.dispatch("edit_file", {"path": "src/game.py",
                                        "old_text": "SPEED = 7", "new_text": "SPEED = 9"})
    assert not result.ok and "not in" in result.content


def test_edit_file_refuses_ambiguous_text(box: Toolbox) -> None:
    """Replacing the first of several matches silently would corrupt the file."""
    (box.project.directory / "src" / "game.py").write_text("x = 1\ny = 2\nx = 1\n")
    result = box.dispatch("edit_file", {"path": "src/game.py",
                                        "old_text": "x = 1", "new_text": "x = 3"})
    assert not result.ok and "appears 2 times" in result.content


def test_edit_file_on_a_missing_file_points_at_write_file(box: Toolbox) -> None:
    result = box.dispatch("edit_file", {"path": "src/nope.py", "old_text": "a", "new_text": "b"})
    assert not result.ok and "write_file" in result.content


def test_edit_file_cannot_escape_the_project(box: Toolbox) -> None:
    result = box.dispatch("edit_file", {"path": "../../x.py", "old_text": "a", "new_text": "b"})
    assert not result.ok and "outside the project" in result.content


def test_binary_file_read_is_refused(box: Toolbox) -> None:
    (box.project.directory / "assets" / "ship.png").write_bytes(b"\x89PNG\x00\xff\xfe")
    result = box.dispatch("read_file", {"path": "assets/ship.png"})
    assert not result.ok and "not a text file" in result.content


def test_oversized_file_read_is_refused(box: Toolbox) -> None:
    (box.project.directory / "src" / "big.py").write_text("x" * 70_000)
    result = box.dispatch("read_file", {"path": "src/big.py"})
    assert not result.ok and "too long" in result.content


def test_write_file_refuses_to_overwrite(box: Toolbox) -> None:
    """Phase 2: whole-file rewrites of existing files corrupted working code."""
    result = box.dispatch("write_file", {"path": "src/game.py", "content": "x = 1"})
    assert not result.ok and "edit_file" in result.content


def test_write_file_refuses_broken_python(box: Toolbox) -> None:
    result = box.dispatch("write_file", {"path": "src/new.py", "content": "def broken(:\n"})
    assert not result.ok and "would break" in result.content
    assert not (box.project.directory / "src" / "new.py").exists()


def test_edit_file_refuses_a_change_that_breaks_python(box: Toolbox) -> None:
    """A child's working game must not be left unparseable."""
    original = "SPEED = 5\nprint(SPEED)\n"
    (box.project.directory / "src" / "game.py").write_text(original)
    result = box.dispatch("edit_file", {"path": "src/game.py",
                                        "old_text": "SPEED = 5", "new_text": "SPEED = ((("})
    assert not result.ok and "would break" in result.content
    assert (box.project.directory / "src" / "game.py").read_text() == original


def test_non_python_files_are_not_syntax_checked(box: Toolbox) -> None:
    assert box.dispatch("write_file", {"path": "docs/notes.md", "content": "# not python ((("}).ok
