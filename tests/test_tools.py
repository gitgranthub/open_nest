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


# ------------------------------------ Phase 12.2: the bounded edit recovery
#
# Measured in SPIKES.md section 22. Across two samples 15 edit_file calls were refused:
# 7 because the model invented text that is in the file at no normalisation (correctly
# refused), 5 because it sent an indentation the line does not have, and 3 because it
# wrote a literal backslash-n where a newline belonged. The fixtures below are those
# three shapes, taken from the real calls rather than imagined.

#: The starter the measurements were taken against, near enough. PLAYER_SPEED sits at
#: column zero, inside no block -- which is what the model kept getting wrong.
_STARTER = (
    "import pygame\n"
    "\n"
    "# Things you can change\n"
    "PLAYER_SPEED = 5\n"
    "PLAYER_SIZE = 40\n"
    "\n"
    "while True:\n"
    "    keys = pygame.key.get_pressed()\n"
    "    if keys[pygame.K_LEFT]:\n"
    "        player.x -= PLAYER_SPEED\n"
)


def _game(box: Toolbox, text: str = _STARTER) -> Path:
    path = box.project.directory / "src" / "game.py"
    path.write_text(text)
    return path


def test_an_indent_the_line_does_not_have_is_repaired(box: Toolbox) -> None:
    """The measured majority of recoverable refusals, and the six-in-a-row failure.

    Asked "make the player move faster", the model sent ``    PLAYER_SPEED = 5`` six
    times against a starter that has it at column zero, and the tool refused six times.
    """
    path = _game(box)
    result = box.dispatch("edit_file", {
        "path": "src/game.py",
        "old_text": "    PLAYER_SPEED = 5",
        "new_text": "    PLAYER_SPEED = 9",
    })
    assert result.ok and result.recovered == "indentation"
    # Re-indented to the file's own column, not written as the model sent it.
    assert "\nPLAYER_SPEED = 9\n" in path.read_text()
    assert "    PLAYER_SPEED" not in path.read_text()


def test_a_literal_backslash_n_is_repaired(box: Toolbox) -> None:
    r"""The model escaped the backslash as well as the n.

    ``spikes/phase12/raw_toolcall.py`` established this is the model double-escaping and
    not Open Nest mis-decoding: the raw completion is well-formed JSON and json.loads
    produces real newlines when the model writes them properly.
    """
    path = _game(box)
    result = box.dispatch("edit_file", {
        "path": "src/game.py",
        "old_text": "    if keys[pygame.K_LEFT]:\\n        player.x -= PLAYER_SPEED",
        "new_text": "    if keys[pygame.K_LEFT]:\\n        player.x -= 99",
    })
    assert result.ok and result.recovered == "escaping"
    assert "player.x -= 99" in path.read_text()
    # The repair must not leave the two characters in the child's file.
    assert "\\n" not in path.read_text()


def test_trailing_whitespace_and_line_endings_are_repaired(box: Toolbox) -> None:
    path = _game(box)
    result = box.dispatch("edit_file", {
        "path": "src/game.py",
        "old_text": "PLAYER_SPEED = 5   \r\nPLAYER_SIZE = 40",
        "new_text": "PLAYER_SPEED = 7\nPLAYER_SIZE = 40",
    })
    assert result.ok and result.recovered == "whitespace"
    assert "PLAYER_SPEED = 7" in path.read_text()


def test_an_exact_match_does_not_go_near_the_repair_path(box: Toolbox) -> None:
    """Exact replacement stays the first path, and says so."""
    path = _game(box)
    result = box.dispatch("edit_file", {"path": "src/game.py",
                                        "old_text": "PLAYER_SPEED = 5",
                                        "new_text": "PLAYER_SPEED = 8"})
    assert result.ok and result.recovered == ""
    assert "PLAYER_SPEED = 8" in path.read_text()


def test_text_that_is_in_the_file_nowhere_is_still_refused(box: Toolbox) -> None:
    """Seven of fifteen measured refusals, and no rule should rescue them.

    The model was editing code it had imagined writing earlier. There is no correct
    match at any normalisation, and picking the closest line is exactly the fuzzy
    editing this must not do.
    """
    original = _STARTER
    path = _game(box, original)
    for invented in ("player_size = 20",
                     "background = (255, 255, 255)",
                     "    # Move asteroid\n    asteroid_x -= 2"):
        result = box.dispatch("edit_file", {"path": "src/game.py",
                                            "old_text": invented, "new_text": "x = 1"})
        assert not result.ok, invented
        assert result.reason == "not_found"
    assert path.read_text() == original


def test_two_exact_matches_are_refused_before_any_repair_is_tried(box: Toolbox) -> None:
    original = "if a:\n    value = 1\nif b:\n        value = 1\n"
    path = _game(box, original)
    result = box.dispatch("edit_file", {"path": "src/game.py",
                                        "old_text": "  value = 1", "new_text": "  value = 2"})
    assert not result.ok and result.reason == "ambiguous"
    assert path.read_text() == original


def test_a_match_that_is_only_ambiguous_after_normalising_is_refused(box: Toolbox) -> None:
    """The safety rule the whole ladder rests on: exactly one match, or no repair.

    A tab indent puts the exact count at zero, so this reaches the repair path -- and
    the repair must still decline, because ignoring indentation makes it match two
    different lines and nothing here may pick one.
    """
    original = "if a:\n    value = 1\nif b:\n        value = 1\n"
    path = _game(box, original)
    result = box.dispatch("edit_file", {"path": "src/game.py",
                                        "old_text": "\tvalue = 1", "new_text": "\tvalue = 2"})
    assert not result.ok and result.reason == "not_found"
    assert path.read_text() == original


def test_a_repair_that_would_break_python_is_refused(box: Toolbox) -> None:
    """The syntax gate runs on a repaired edit exactly as on an exact one."""
    original = _STARTER
    path = _game(box, original)
    result = box.dispatch("edit_file", {"path": "src/game.py",
                                        "old_text": "    PLAYER_SPEED = 5",
                                        "new_text": "    PLAYER_SPEED = ((("})
    assert not result.ok and result.reason == "syntax_error"
    assert path.read_text() == original


def test_a_repair_never_dedents_further_than_the_line_allows(box: Toolbox) -> None:
    """Shifting a replacement out of its block would change what the code means."""
    from opennest.agent.tools import repair_edit

    text = "def f():\n        deeply = 1\n"
    # The model sends it far more indented than it is; the replacement cannot be moved
    # back by that much without leaving the function body.
    assert repair_edit(text, "                deeply = 1", "deeply = 2") is None


def test_an_exact_match_with_escaped_newlines_in_new_text_is_repaired(box: Toolbox) -> None:
    r"""The worst shape of the escaping fault, found by the verification walk.

    ``old_text`` matched perfectly, so the match-side repair never ran, and ``new_text``
    carried the two characters ``\`` and ``n``. Written verbatim the whole block became
    one comment line -- it compiled, the tool reported success, and the child's game
    silently lost the code that drew the player.
    """
    path = _game(box)
    result = box.dispatch("edit_file", {
        "path": "src/game.py",
        "old_text": "PLAYER_SIZE = 40",
        "new_text": "PLAYER_SIZE = 40\\nPLAYER_COLOUR = (1, 2, 3)",
    })
    assert result.ok and result.recovered == "escaping"
    written = path.read_text()
    assert "\\n" not in written
    assert "\nPLAYER_COLOUR = (1, 2, 3)\n" in written


def test_a_newline_inside_a_string_literal_is_left_alone(box: Toolbox) -> None:
    r"""The discriminator is the parser, not a guess about what the model meant.

    ``print("a\nb")`` is a legitimate use of the escape. Unescaping it would produce an
    unterminated string, so it does not compile and the text is written as sent.
    """
    path = _game(box)
    result = box.dispatch("edit_file", {
        "path": "src/game.py",
        "old_text": "PLAYER_SIZE = 40",
        "new_text": 'print("a\\nb")',
    })
    assert result.ok and result.recovered == ""
    assert 'print("a\\nb")' in path.read_text()


def test_a_whole_new_file_is_not_written_as_one_comment(box: Toolbox) -> None:
    result = box.dispatch("write_file", {
        "path": "src/helper.py",
        "content": "# helper\\nimport pygame\\n\\nSPEED = 3",
    })
    assert result.ok and result.recovered == "escaping"
    written = (box.project.directory / "src" / "helper.py").read_text()
    assert "\\n" not in written
    assert written.split("\n")[1] == "import pygame"


def test_text_that_already_has_real_newlines_is_never_touched(box: Toolbox) -> None:
    """Mixed text is ambiguous about which the model meant, so it is left as sent."""
    path = _game(box)
    result = box.dispatch("edit_file", {
        "path": "src/game.py",
        "old_text": "PLAYER_SIZE = 40",
        "new_text": 'PLAYER_SIZE = 40\nMESSAGE = "a\\nb"',
    })
    assert result.ok and result.recovered == ""
    assert 'MESSAGE = "a\\nb"' in path.read_text()


# ------------------------------------- Phase 12.2: one project runs one copy of itself

def test_running_again_stops_the_copy_that_is_still_running(box: Toolbox, monkeypatch) -> None:
    """Otherwise every extra run orphans a window nothing can ever reach.

    ``last_run`` holds one result and an interactive profile's run never finishes on its
    own, so a second ``run_project`` used to overwrite the only reference to a live
    process. Stop reads ``last_run`` and so does ``Workbench.release``, which meant the
    first window could not be closed from inside Open Nest at all. Phase 12.2 found five
    stacked up on the owner's screen across two walks, all reparented to init.
    """
    from opennest.execution.python_runner import RunResult

    stopped: list = []
    monkeypatch.setattr("opennest.agent.tools.stop_project", lambda run: stopped.append(run))
    monkeypatch.setattr(
        "opennest.agent.tools.run_project",
        lambda *a, **k: RunResult(None, "", "", 0.1, False, still_running=True),
    )
    box.dispatch("run_project", {})
    first = box.last_run
    box.dispatch("run_project", {})

    assert stopped == [first], "the first game was left running with nothing owning it"


def test_running_again_does_not_stop_a_run_that_already_finished(box: Toolbox, monkeypatch) -> None:
    """A batch run is over; there is nothing to terminate and nothing to report."""
    from opennest.execution.python_runner import RunResult

    stopped: list = []
    monkeypatch.setattr("opennest.agent.tools.stop_project", lambda run: stopped.append(run))
    monkeypatch.setattr(
        "opennest.agent.tools.run_project",
        lambda *a, **k: RunResult(None, "done", "", 0.1, False, still_running=False),
    )
    box.dispatch("run_project", {})
    box.dispatch("run_project", {})
    assert stopped == []


def test_stop_running_is_safe_before_anything_has_run(box: Toolbox) -> None:
    box.stop_running()


def test_every_refusal_carries_a_machine_readable_reason(box: Toolbox) -> None:
    """The prose is for the model; the code is for Open Nest to count and branch on."""
    _game(box)
    cases = {
        "missing_file": {"path": "src/nope.py", "old_text": "a", "new_text": "b"},
        "not_found": {"path": "src/game.py", "old_text": "zzz", "new_text": "b"},
        "missing_argument": {"path": "src/game.py", "old_text": "", "new_text": "b"},
        "outside_project": {"path": "../../x.py", "old_text": "a", "new_text": "b"},
    }
    for expected, args in cases.items():
        result = box.dispatch("edit_file", args)
        assert not result.ok, args
        assert result.reason == expected, f"{args} gave {result.reason!r}"
