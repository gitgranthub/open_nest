"""Export: one file, where a person chose in a save dialog, once -- and only what was checked
is said (HANDOFF section 5, PHASE_12_HANDOFF section 7, PLAN.md D14)."""

from __future__ import annotations

import ast
import dataclasses
import errno
import os
from pathlib import Path

import pytest

from opennest.export import save
from opennest.export.report import Report

PDF = b"%PDF-1.4\n" + b"x" * 2000 + b"\n%%EOF\n"


def _report(**changes) -> Report:
    made = Report(pdf=PDF, pages=3, title="Weather Study", charts=("charts/chart.png",),
                  sections=("charts",), notes=(),
                  words=(("src/findings.md", "It was hot in July.\n"),))
    return dataclasses.replace(made, **changes)


def _left_in(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def test_the_report_goes_where_the_person_chose_and_nowhere_else(tmp_path) -> None:
    target = tmp_path / "Weather Study report.pdf"
    saved = save.write(save.from_dialog(str(target)), _report())
    assert target.read_bytes() == PDF
    assert _left_in(tmp_path) == ["Weather Study report.pdf"], "no temporary file left"
    assert saved.size == len(PDF)
    assert saved.sentence() == (f"Saved “Weather Study report.pdf” in "
                                f"{tmp_path.name}. 3 pages.")
    assert oct(target.stat().st_mode & 0o777) == "0o644"


def test_a_place_not_from_the_dialog_is_refused(tmp_path) -> None:
    forged = save.Destination(tmp_path / "forged.pdf")
    with pytest.raises(save.ExportRefused, match="for one report"):
        save.write(forged, _report())
    assert _left_in(tmp_path) == []


def test_a_destination_changed_after_the_dialog_is_refused(tmp_path) -> None:
    chosen = save.from_dialog(str(tmp_path / "chosen.pdf"))
    moved = dataclasses.replace(chosen, path=tmp_path / "elsewhere.pdf")
    with pytest.raises(save.ExportRefused):
        save.write(moved, _report())
    assert _left_in(tmp_path) == []


def test_a_destination_is_good_for_one_write(tmp_path) -> None:
    target = tmp_path / "once.pdf"
    destination = save.from_dialog(str(target))
    save.write(destination, _report())
    with pytest.raises(save.ExportRefused, match="Press Export PDF again"):
        save.write(destination, _report(pdf=b"%PDF-1.4 second"))
    assert target.read_bytes() == PDF


@pytest.mark.parametrize(("chosen", "said"), [
    ("", "No file name was chosen"),
    ("report.pdf", "whole location"),
    ("{tmp}/report.txt", "ends in .pdf"),
    ("{tmp}/missing/report.pdf", "is not there any more"),
    ("{tmp}/a folder.pdf", "is a folder, not a file"),
])
def test_what_the_dialog_returned_is_checked(tmp_path, chosen, said) -> None:
    (tmp_path / "a folder.pdf").mkdir()
    with pytest.raises(save.ExportRefused, match=said):
        save.from_dialog(chosen.format(tmp=tmp_path))


def test_a_shortcut_to_another_file_is_refused(tmp_path) -> None:
    real = tmp_path / "real.pdf"
    real.write_bytes(b"theirs")
    (tmp_path / "link.pdf").symlink_to(real)
    with pytest.raises(save.ExportRefused, match="shortcut"):
        save.from_dialog(str(tmp_path / "link.pdf"))
    assert real.read_bytes() == b"theirs"


def test_open_nests_own_folders_are_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENNEST_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENNEST_PROJECTS", raising=False)
    project = tmp_path / "home" / "projects" / "Weather Study"
    project.mkdir(parents=True)
    with pytest.raises(save.ExportRefused, match="where Open Nest keeps its own files"):
        save.from_dialog(str(project / "report.pdf"))
    # Compared the way macOS compares paths: without regard to case.
    with pytest.raises(save.ExportRefused, match="where Open Nest keeps its own files"):
        save.from_dialog(str(tmp_path / "home" / "PROJECTS" / "Weather Study" / "r.pdf"))


def test_an_unwritable_folder_is_said_and_nothing_claimed(tmp_path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(save.ExportRefused, match="does not allow writing there"):
            save.from_dialog(str(locked / "report.pdf"))
    finally:
        locked.chmod(0o700)
    assert _left_in(locked) == []


def test_replacing_a_file_replaces_it_whole(tmp_path) -> None:
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4 an older report")
    save.write(save.from_dialog(str(target)), _report())
    assert target.read_bytes() == PDF
    assert _left_in(tmp_path) == ["report.pdf"]


def test_a_write_that_fails_leaves_the_old_file_and_says_why(tmp_path, monkeypatch) -> None:
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4 the one they had")
    destination = save.from_dialog(str(target))

    def full(*_args):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(save.os, "replace", full)
    with pytest.raises(save.ExportRefused, match="not enough space"):
        save.write(destination, _report())
    assert target.read_bytes() == b"%PDF-1.4 the one they had"
    assert _left_in(tmp_path) == ["report.pdf"], "the half-written file is gone"


def test_a_file_that_is_not_there_afterwards_is_not_called_saved(tmp_path, monkeypatch) -> None:
    target = tmp_path / "report.pdf"
    destination = save.from_dialog(str(target))
    monkeypatch.setattr(save.os, "replace", lambda source, _target: os.unlink(source))
    with pytest.raises(save.ExportRefused, match="could not find it"):
        save.write(destination, _report())


def test_a_key_in_the_report_stops_the_export_and_is_never_quoted(tmp_path) -> None:
    key = "sk-ant-api03-" + "Q" * 40
    made = _report(words=(("src/findings.md", f"It was hot.\nmy key {key}\n"),))
    target = tmp_path / "report.pdf"
    with pytest.raises(save.ExportRefused) as refused:
        save.write(save.from_dialog(str(target)), made)
    message = str(refused.value)
    assert message.startswith("The report was not saved")
    # Named by file and line, as a GitHub push names it (the scanner's own wording).
    assert "findings.md line 2 looks like an" in message and "API key" in message
    assert key not in message and "QQQQ" not in message
    assert not target.exists()


def test_the_default_name_is_the_projects_and_safe_as_a_file_name() -> None:
    assert save.default_name("Weather Study") == "Weather Study report.pdf"
    assert save.default_name("Rain/Snow: 2025") == "Rain Snow 2025 report.pdf"
    assert save.default_name(".hidden") == "hidden report.pdf"
    assert save.default_name("///") == "Report report.pdf"


# -- export is the application's, never Gary's --------------------------------------------

def test_export_is_not_a_tool(tmp_path) -> None:
    from opennest.agent.tools import SCHEMAS, Toolbox
    from opennest.projects.manager import create_project

    names = {schema["function"]["name"] if "function" in schema else schema.get("name")
             for schema in SCHEMAS.values()} | set(SCHEMAS)
    assert not any("export" in str(name) or "pdf" in str(name) for name in names)
    project = create_project("Weather", "research", root=tmp_path)
    refused = Toolbox(project).dispatch("export_pdf", {"path": str(tmp_path / "x.pdf")})
    assert not refused.ok
    assert not (tmp_path / "x.pdf").exists()


def test_nothing_gary_can_reach_imports_the_save_module() -> None:
    """The model's side of the application -- the agent, the Fast Path, the recipes'
    executor -- never imports ``export.save``, so no path a model writes can reach it."""
    root = Path(__file__).resolve().parent.parent / "opennest"
    for folder in ("agent", "fastpath", "ai", "memory"):
        for source in (root / folder).rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported = {node.module, *(f"{node.module}.{a.name}" for a in node.names)}
                    assert "opennest.export.save" not in imported, source
                elif isinstance(node, ast.Import):
                    assert all(a.name != "opennest.export.save" for a in node.names), source
