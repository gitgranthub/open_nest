"""Project memory: the bible, the state file, compaction and lookup.

WORKORDER_01 section 15A. These tests cover the parts that do not need a model at all,
which is most of them by design -- deterministic facts are the application's job, and the
point of these tests is that it does that job without asking.

Thread rollover, which does need a model, is in test_rollover.py.
"""

from __future__ import annotations

from pathlib import Path

from opennest.memory import (
    compactor,
    history_search,
    markdown,
    project_bible,
    project_state,
    safety,
)
from opennest.memory.project_state import StateNotes

# --------------------------------------------------------------------------- markdown

def test_sections_round_trip() -> None:
    text = "# Title\n\n## Goal\nMake a game.\n\n## Decisions\n- Fast asteroids\n"
    sections = markdown.split_sections(text)
    assert sections["Goal"] == ["Make a game."]
    assert markdown.bullets(sections["Decisions"]) == ["Fast asteroids"]


def test_rendering_leaves_out_empty_sections() -> None:
    rendered = markdown.render_sections("T", {"Goal": ["x"], "Decisions": []}, ("Goal",))
    assert "## Goal" in rendered
    assert "## Decisions" not in rendered


def test_an_unknown_section_is_kept_rather_than_lost() -> None:
    """A parent who adds a section of their own should still have it after a save."""
    rendered = markdown.render_sections(
        "T", {"Goal": ["x"], "Notes From Dad": ["be nice"]}, ("Goal",)
    )
    assert "Notes From Dad" in rendered


# ------------------------------------------------------------------------------ bible

def test_bible_records_facts_the_application_owns(project) -> None:
    """Section 15A: file names and project metadata are never asked of the model."""
    bible = project_bible.load(project)
    project_bible.save(project, bible)
    text = project_bible.path_for(project).read_text()
    assert "Asteroid Game" in text
    assert "src/game.py" in text
    assert "Game" in text


def test_asset_files_are_listed_from_disk(project) -> None:
    (project.directory / "assets" / "spaceship.png").write_bytes(b"png")
    project_bible.save(project, project_bible.load(project))
    assert "assets/spaceship.png" in project_bible.path_for(project).read_text()


def test_deterministic_sections_are_rewritten_not_appended(project) -> None:
    project_bible.save(project, project_bible.load(project))
    (project.directory / "assets" / "ship.png").write_bytes(b"png")
    project_bible.save(project, project_bible.load(project))
    text = project_bible.path_for(project).read_text()
    assert text.count("- Name: Asteroid Game") == 1


def test_decisions_survive_a_reload(project) -> None:
    bible = project_bible.load(project)
    bible.add_bullets(project_bible.DECISIONS, ["Do not add shooting yet"])
    project_bible.save(project, bible)
    assert "Do not add shooting yet" in project_bible.load(project).bullets("Decisions")


def test_the_same_decision_is_not_written_twice(project) -> None:
    bible = project_bible.load(project)
    bible.add_bullets(project_bible.DECISIONS, ["Asteroids get faster over time"])
    added = bible.add_bullets(
        project_bible.DECISIONS, ["asteroids get faster over time."]
    )
    assert added == []
    assert len(bible.bullets("Decisions")) == 1


def test_the_goal_is_set_once_and_does_not_drift(project) -> None:
    bible = project_bible.load(project)
    assert bible.set_goal("A spaceship that dodges asteroids")
    assert not bible.set_goal("Something completely different")
    assert bible.lines("Goal") == ["A spaceship that dodges asteroids"]


def test_a_damaged_bible_is_not_fatal(project) -> None:
    project_bible.path_for(project).write_bytes(b"\xff\xfe not text")
    assert project_bible.load(project).is_empty


def test_an_empty_bible_is_reported_as_empty(project) -> None:
    """The application's own sections must not count as remembered knowledge."""
    project_bible.save(project, project_bible.load(project))
    assert project_bible.load(project).is_empty


# --------------------------------------------------------------------------- safety

def test_a_credential_never_reaches_a_memory_file(tmp_path: Path) -> None:
    """Section 15A: no keys, passwords or tokens in project memory. Ever."""
    target = tmp_path / "project_bible.md"
    findings = safety.write_memory_file(
        target,
        "## Decisions\n- Use the arrow keys\n- api_key = 'sk-abcdefghijklmnopqrstuvwx'\n",
    )
    written = target.read_text()
    assert findings
    assert "sk-abcdefghijklmnopqrstuvwx" not in written
    assert "Use the arrow keys" in written


def test_a_key_in_a_decision_is_dropped_on_save(project) -> None:
    bible = project_bible.load(project)
    bible.add_bullets(
        project_bible.DECISIONS,
        ["Keep the token ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA handy", "Dark blue background"],
    )
    project_bible.save(project, bible)
    text = project_bible.path_for(project).read_text()
    assert "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in text
    assert "Dark blue background" in text


# ------------------------------------------------------------------------- compaction

def test_a_replaced_decision_is_superseded_not_deleted(project) -> None:
    """The section 15A example: player speed was 5, then 8."""
    bible = project_bible.load(project)
    compactor.add_decisions(bible, ["Player speed is 5"])
    report = compactor.add_decisions(bible, ["Player speed is 8 after play testing"])

    assert report.superseded == ["Player speed is 5"]
    assert bible.bullets("Decisions") == ["Player speed is 8 after play testing"]
    assert "Player speed is 5" in bible.bullets("Superseded Decisions")


def test_an_unrelated_decision_does_not_supersede(project) -> None:
    bible = project_bible.load(project)
    compactor.add_decisions(bible, ["Player speed is 5"])
    compactor.add_decisions(bible, ["Asteroids spawn from the top"])
    assert len(bible.bullets("Decisions")) == 2
    assert bible.bullets("Superseded Decisions") == []


def test_a_reversed_decision_supersedes_the_original(project) -> None:
    bible = project_bible.load(project)
    compactor.add_decisions(bible, ["Do not add shooting yet"])
    compactor.add_decisions(bible, ["Add shooting now"])
    assert bible.bullets("Decisions") == ["Add shooting now"]
    assert "Do not add shooting yet" in bible.bullets("Superseded Decisions")


def test_superseded_decisions_are_capped(project) -> None:
    bible = project_bible.load(project)
    for n in range(compactor.MAX_SUPERSEDED + 5):
        compactor.add_decisions(bible, [f"Player speed is {n}"])
    assert len(bible.bullets("Superseded Decisions")) == compactor.MAX_SUPERSEDED


def test_trimming_never_drops_a_live_decision(project) -> None:
    """Only superseded entries and stale ideas are capped. Decisions are the record."""
    bible = project_bible.load(project)
    bible.add_bullets(project_bible.DECISIONS, [f"Keep rule {n}" for n in range(60)])
    compactor.trim(bible)
    assert len(bible.bullets("Decisions")) == 60


def test_subject_ignores_numbers_so_a_changed_value_matches() -> None:
    assert compactor.same_subject(
        compactor.subject("Player speed is 5"),
        compactor.subject("Player speed is 8 after play testing"),
    )


def test_one_word_in_common_is_not_the_same_subject() -> None:
    assert not compactor.same_subject(
        compactor.subject("Shooting is allowed"),
        compactor.subject("Shooting sounds are too loud"),
    )


# ------------------------------------------------------------------------- state file

def test_state_records_files_and_dependencies_from_fact(project) -> None:
    project_state.save(project)
    text = project_state.path_for(project).read_text()
    assert "src/game.py" in text
    assert "pygame" in text


def test_state_reports_a_failed_run_as_a_known_problem(project) -> None:
    from opennest.execution.python_runner import RunResult

    failed = RunResult(exit_code=1, stdout="", stderr="NameError: ship", seconds=0.1,
                       timed_out=False)
    project_state.save(project, last_run=failed)
    text = project_state.path_for(project).read_text()
    assert "NameError: ship" in text
    assert project_state.NOTHING_WRONG not in text


def test_state_says_nothing_is_wrong_when_nothing_is(project) -> None:
    project_state.save(project)
    assert project_state.NOTHING_WRONG in project_state.path_for(project).read_text()


def test_carried_notes_survive_closing_the_application(project) -> None:
    project_state.save(project, notes=StateNotes(current_task="Adding a score counter"))
    assert project_state.load_notes(project).current_task == "Adding a score counter"


def test_carried_notes_are_the_part_the_live_prompt_does_not_know(project) -> None:
    """The file list is already injected live, so memory must not repeat it."""
    notes = StateNotes(current_task="Adding a score", problems=("Sound does not play",))
    rendered = project_state.carried_notes(notes)
    assert "Adding a score" in rendered
    assert "Sound does not play" in rendered
    assert "game.py" not in rendered


# ----------------------------------------------------------------------------- recall

def test_a_reference_to_the_past_is_recognised() -> None:
    assert history_search.looks_like_a_memory_question("like we talked about before")
    assert history_search.looks_like_a_memory_question("what did we decide about lives?")


def test_an_ordinary_request_is_not_a_memory_question() -> None:
    assert not history_search.looks_like_a_memory_question("make the asteroids faster")
    assert not history_search.looks_like_a_memory_question("add a score counter")


def test_search_finds_a_decision_in_the_bible(project) -> None:
    bible = project_bible.load(project)
    bible.add_bullets(project_bible.DECISIONS, ["The boss level should appear at score 100"])
    project_bible.save(project, bible)

    hits = history_search.search(project, "add the boss level we talked about")
    assert any("boss level" in hit.text for hit in hits)
    assert hits[0].source == project_bible.FILENAME


def test_search_ignores_an_unrelated_question(project) -> None:
    bible = project_bible.load(project)
    bible.add_bullets(project_bible.DECISIONS, ["The boss level appears at score 100"])
    project_bible.save(project, bible)
    assert history_search.search(project, "remember the trombone concerto") == []


def test_recall_context_tells_the_model_to_trust_it(project) -> None:
    hits = [history_search.Hit(source="project_bible.md", text="No shooting yet")]
    rendered = history_search.as_context(hits)
    assert "No shooting yet" in rendered
    assert "do not ask them to repeat it" in rendered
