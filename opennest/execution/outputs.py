"""What a run produced, worked out by the application rather than reported by the model.

WORKORDER_01 DoD 34 wants a Research project to produce "Python analysis and a chart",
and a chart is only a result if somebody can see it. The question this module answers is
narrow: which picture files did that run write?

It is deliberately deterministic, and deliberately not a tool. The same reasoning as the
file list (SPIKES.md section 4) and as memory retrieval: the application can know this by
looking, so it should not ask the model to tell it. A model reporting the path it saved a
chart to is a model that can report the wrong path, or forget to, or invent one --
Phase 5's whole problem in a new costume. Comparing the directory before and after cannot
be wrong about what is on disk.

Nothing here assumes a Research project. A game that writes a screenshot gets the same
treatment, because "an image appeared" is a fact about a run and not about a profile.
"""

from __future__ import annotations

from pathlib import Path

from opennest.assets.kinds import EXTENSIONS, IMAGE
from opennest.security.sandbox import visible_files

#: Suffixes that count as a picture, taken from the asset layer so that "is this an
#: image?" has exactly one definition in the codebase.
IMAGE_SUFFIXES: frozenset[str] = frozenset(
    suffix for suffix, kind in EXTENSIONS.items() if kind == IMAGE
)

#: A mapping of project-relative path to modification time.
Snapshot = dict[str, float]


def snapshot(project_dir: Path) -> Snapshot:
    """Every picture in the project right now, with when it last changed.

    Taken before a run so the run's own output can be told apart from the pictures a
    child imported earlier. Uses :func:`visible_files`, so internal directories and
    anything credential-shaped are excluded for free.
    """
    root = Path(project_dir)
    found: Snapshot = {}
    for relative in visible_files(root):
        if Path(relative).suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            found[relative] = (root / relative).stat().st_mtime
        except OSError:
            continue  # Vanished between listing and stat. It is not output either way.
    return found


def images_written(project_dir: Path, before: Snapshot) -> list[str]:
    """Pictures this run created or rewrote, newest first.

    A file counts if it was not there before, or if its modification time moved. An
    unchanged picture the child imported last week is not this run's output, which is
    the distinction that keeps a Games project from showing a sprite every time it runs.
    """
    after = snapshot(project_dir)
    changed = [
        relative
        for relative, mtime in after.items()
        if relative not in before or mtime > before[relative]
    ]
    changed.sort(key=lambda relative: after[relative], reverse=True)
    return changed
