"""The remaining profiles: do they create something, and does it run?

Phase 7's exit criterion is "each profile creates and runs or compiles its template",
and before this phase that was true of exactly one of them. Four profiles named starter
templates that had never existed, and ``create_project`` skipped a missing template
silently, so a Raspberry Pi project was a directory containing ``project.json`` and
nothing else. Nothing failed; there was simply no project.

These tests are the guard against that returning. The expensive one actually runs each
template, because "the file was copied in" and "the file works" are different claims and
only the second is worth anything to a child.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opennest.execution import outputs
from opennest.execution.python_runner import run_project, stop_project
from opennest.projects.manager import ProjectError, create_project
from opennest.projects.profiles import load_profiles
from opennest.security.process_sandbox import sandbox_available

ALL_PROFILES = [profile.id for profile in load_profiles()]


@pytest.mark.parametrize("profile_id", ALL_PROFILES)
def test_a_new_project_contains_its_entrypoint(tmp_path: Path, profile_id: str) -> None:
    """The bug this phase existed to fix, per profile."""
    project = create_project("Test Project", profile_id, root=tmp_path)
    assert project.entrypoint_path.is_file(), (
        f"{profile_id} created a project with no {project.manifest.entrypoint}"
    )
    assert project.entrypoint_path.stat().st_size > 0


def test_a_missing_template_is_a_loud_failure(tmp_path: Path, monkeypatch) -> None:
    """Silence here cost four broken profiles for seven phases.

    Also checks it fails *before* creating anything: a half-made directory would block
    the child retrying with the same name, which turns a packaging fault into a name
    they can never use again.
    """
    from opennest.projects import manager

    monkeypatch.setattr(manager, "template_dir", lambda profile: tmp_path / "nope")
    with pytest.raises(ProjectError) as caught:
        manager.create_project("Doomed", "games", root=tmp_path)
    assert "starter files" in str(caught.value)
    assert not (tmp_path / "Doomed").exists(), "left a half-made project behind"


def test_the_arduino_sketch_is_in_a_folder_named_after_itself(tmp_path: Path) -> None:
    """arduino-cli requires it, and nothing in the docs says so.

    ``arduino-cli compile src/`` fails with "main file missing from sketch: src/src.ino".
    Measured in SPIKES.md section 14. If someone flattens this layout back to
    ``src/project.ino``, compiling stops working and the only symptom is a confusing
    message about a file nobody wrote.
    """
    project = create_project("Blinker", "arduino", root=tmp_path)
    sketch = project.entrypoint_path
    assert sketch.name == "project.ino"
    assert sketch.parent.name == "project"
    # Section 8's three primary outputs, kept together where a child will find them.
    assert (sketch.parent / "README.md").is_file()
    assert (sketch.parent / "wiring.md").is_file()


def test_the_arduino_sketch_names_no_pin_number(tmp_path: Path) -> None:
    """Section 8: never invent pin assignments.

    ``LED_BUILTIN`` is every board's own onboard LED, so the starter sketch asserts
    nothing about how anything is wired. A bare pin number here would be a guess
    shipped to every child regardless of what they own.
    """
    project = create_project("Blinker", "arduino", root=tmp_path)
    sketch = project.entrypoint_path.read_text(encoding="utf-8")
    assert "LED_BUILTIN" in sketch


@pytest.mark.parametrize(
    "profile_id", [p.id for p in load_profiles() if p.run_command]
)
@pytest.mark.skipif(not sandbox_available(), reason="macOS Seatbelt not available")
def test_every_runnable_template_actually_runs(tmp_path: Path, profile_id: str) -> None:
    """Runs the starter code under the real sandbox, as a child would.

    Interactive profiles (a game, a Pi loop) are allowed to still be running: that is
    success for them. Batch profiles have to exit 0.
    """
    project = create_project("Test Project", profile_id, root=tmp_path)
    result = run_project(
        project.directory,
        project.profile.run_command,
        python_executable=sys.executable,
        interactive=project.profile.is_interactive,
        timeout=120,
    )
    try:
        assert result.ok, (
            f"{profile_id} template failed:\n{result.failure_text or result.stderr}"
        )
    finally:
        if result.still_running:
            stop_project(result)


@pytest.mark.skipif(not sandbox_available(), reason="macOS Seatbelt not available")
def test_a_research_project_turns_a_dropped_csv_into_analysis_and_a_chart(
    tmp_path: Path,
) -> None:
    """DoD 32-34, end to end.

    Phase 5 moved this here because it is a Research requirement that happens to involve
    an asset rather than the other way round. The asset half was already done; what was
    missing was a Research project that does anything at all.

    Deliberately asserts on the three things a child would check: it read my file, it
    told me about it, and there is a picture.
    """
    project = create_project("Rainfall", "research", root=tmp_path)
    (project.directory / "data" / "rainfall.csv").write_text(
        "month,rain_cm,sunshine_hours\n"
        "Jan,3.1,44\nFeb,9.4,51\nMar,4.2,98\nApr,2.0,140\nMay,1.1,190\n",
        encoding="utf-8",
    )

    before = outputs.snapshot(project.directory)
    result = run_project(
        project.directory,
        project.profile.run_command,
        python_executable=sys.executable,
        timeout=180,
    )

    assert result.ok, result.failure_text or result.stderr
    assert "rainfall.csv" in result.stdout
    assert "5 rows" in result.stdout
    assert "rain_cm" in result.stdout

    # The chart exists, and the application can find it without being told where it is.
    produced = outputs.images_written(project.directory, before)
    assert produced, "the analysis produced no picture"
    chart = project.directory / produced[0]
    assert chart.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.skipif(not sandbox_available(), reason="macOS Seatbelt not available")
def test_a_research_project_with_no_data_yet_says_so_instead_of_crashing(
    tmp_path: Path,
) -> None:
    """The state every Research project starts in.

    A traceback on the first press of Run Analysis is the worst possible introduction,
    and a fresh project has an empty ``data/`` by definition.
    """
    project = create_project("Empty Study", "research", root=tmp_path)
    result = run_project(
        project.directory,
        project.profile.run_command,
        python_executable=sys.executable,
        timeout=180,
    )
    assert result.ok, result.failure_text
    assert "no data here yet" in result.stdout.lower()
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(not sandbox_available(), reason="macOS Seatbelt not available")
def test_matplotlib_keeps_its_cache_inside_the_project(tmp_path: Path) -> None:
    """Measured, and the reason is speed rather than correctness.

    Without MPLCONFIGDIR, matplotlib finds ~/.matplotlib unwritable under Seatbelt and
    rebuilds its font cache on every run: 6.6 s and three lines of stderr warning each
    time, against 0.3 s and silence once it persists (SPIKES.md section 14). The chart
    was always written either way, which is why PLAN.md was wrong to call this a
    blocker for DoD 32-34.
    """
    project = create_project("Cache Check", "research", root=tmp_path)
    (project.directory / "data" / "tiny.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    run_project(
        project.directory,
        project.profile.run_command,
        python_executable=sys.executable,
        timeout=180,
    )
    cache = project.directory / ".opennest" / "tmp" / "matplotlib"
    assert cache.is_dir(), "matplotlib fell back to a temporary directory again"


def test_the_raspberry_pi_template_separates_mac_code_from_pi_code(
    tmp_path: Path,
) -> None:
    """Section 7's one explicit requirement of this profile.

    The distinction has to be in the starter code, not only in the system prompt: the
    child reads the file, and a GPIO import at the top level would make the template
    unrunnable on the Mac it is supposed to be developed on.
    """
    project = create_project("Blinky", "raspberry_pi", root=tmp_path)
    source = project.entrypoint_path.read_text(encoding="utf-8")
    assert "RUNS ON THIS MAC" in source
    assert "RUNS ON THE PI" in source
    # The GPIO import must be guarded, not top-level.
    assert "import RPi.GPIO" in source
    assert "except ImportError" in source
    for line in source.splitlines():
        if line.startswith("import RPi") or line.startswith("from RPi"):
            pytest.fail("RPi.GPIO is imported at the top level; this cannot run on a Mac")
