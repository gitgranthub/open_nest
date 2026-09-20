"""Every location Open Nest writes to is defined in one place. Keep it that way."""

from __future__ import annotations

from pathlib import Path

from opennest import paths


def test_internal_project_dirname_matches_the_product_name() -> None:
    """DESIGN_DOC.md section 21: .buildlab became .opennest."""
    assert paths.PROJECT_INTERNAL_DIRNAME == ".opennest"


def test_bundled_config_and_prompts_ship_with_the_package() -> None:
    assert (paths.config_dir() / "models.json").is_file()
    assert (paths.config_dir() / "profiles.json").is_file()
    assert (paths.prompts_dir() / "base.txt").is_file()


def test_internal_state_stays_out_of_the_repository() -> None:
    """Projects, logs and models must not be written into the cloned repo."""
    repo = paths.repo_root()
    for path in (
        paths.app_support_dir(),
        paths.logs_dir(),
        paths.models_dir(),
        paths.projects_root(),
        paths.installation_state_file(),
    ):
        assert repo not in path.parents, f"{path} would be written inside the repository"


def test_projects_root_is_somewhere_a_child_can_find_it() -> None:
    root = paths.projects_root()
    assert root.is_relative_to(Path.home())
    assert "Library" not in root.parts


def test_projects_root_can_be_overridden_for_testing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENNEST_PROJECTS_DIR", str(tmp_path / "Somewhere"))
    assert paths.projects_root() == tmp_path / "Somewhere"


def test_project_internal_dir_is_inside_the_project(tmp_path) -> None:
    internal = paths.project_internal_dir(tmp_path)
    assert internal.parent == tmp_path
    assert internal.name == ".opennest"


def test_ensure_app_dirs_is_idempotent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENNEST_PROJECTS_DIR", str(tmp_path / "Projects"))
    monkeypatch.setattr(paths, "app_support_dir", lambda: tmp_path / "Support")
    monkeypatch.setattr(paths, "logs_dir", lambda: tmp_path / "Logs")
    monkeypatch.setattr(paths, "models_dir", lambda: tmp_path / "Support" / "models")

    paths.ensure_app_dirs()
    paths.ensure_app_dirs()

    assert (tmp_path / "Projects").is_dir()
    assert (tmp_path / "Support" / "models").is_dir()
    assert (tmp_path / "Logs").is_dir()
