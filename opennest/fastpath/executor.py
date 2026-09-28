"""Apply a recipe's change -- through the Toolbox, never around it.

An operation returns the text it wants each file to have. This turns that into the small
anchored edits of :mod:`opennest.fastpath.edits` and sends each one to
``Toolbox.dispatch("edit_file", ...)``, exactly as a model's tool call would arrive. So
the path confinement in ``security/sandbox.py``, the refusal to overwrite, the
"exactly once" rule and ``_reject_broken_python`` all apply to Open Nest's own edits
too. Fast does not mean fewer checks.

The calls are kept as ``ToolCall`` / ``ToolResult`` pairs, because they go into the
conversation history as what they are: the edits that were made this turn. Gary reads
them on the next turn the same way he reads his own.

If any edit is refused, or verification later fails, every file is put back **exactly**
as it was -- the original bytes, written through the same sandboxed path resolution --
and the turn goes to Gary as if the Fast Path had never touched it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from opennest.agent.tools import Step, Toolbox, ToolResult
from opennest.ai.provider import ToolCall
from opennest.fastpath import edits
from opennest.fastpath.kinds import Change, NotApplicable
from opennest.security.sandbox import resolve_in_project


class EditRefused(NotApplicable):
    """The Toolbox refused one of the edits. Everything already applied is undone."""


@dataclass
class Applied:
    change: Change
    calls: list[tuple[ToolCall, ToolResult]] = field(default_factory=list)
    #: The bytes each touched file had before anything was applied.
    originals: dict[str, str] = field(default_factory=dict)

    @property
    def changed_files(self) -> tuple[str, ...]:
        seen: list[str] = []
        for _, result in self.calls:
            for path in result.changed_files:
                if path not in seen:
                    seen.append(path)
        return tuple(seen)


class RecipeExecutor:
    """Turns a :class:`Change` into edits the Toolbox makes, and can undo them."""

    def apply(self, change: Change, toolbox: Toolbox) -> Applied:
        applied = Applied(change=change)
        try:
            return self._apply(change, toolbox, applied)
        except EditRefused:
            raise
        except BaseException:
            self.rollback(applied, toolbox)
            raise

    def _apply(self, change: Change, toolbox: Toolbox, applied: Applied) -> Applied:
        project_dir = toolbox.project.directory
        number = 0
        for relative, wanted in change.files.items():
            path = resolve_in_project(project_dir, relative, for_write=True)
            if not path.is_file():
                self.rollback(applied, toolbox)
                raise EditRefused(f"{relative} does not exist")
            before = path.read_text(encoding="utf-8")
            applied.originals[relative] = before
            for old, new in edits.hunks(before, wanted):
                call = ToolCall(
                    name="edit_file",
                    arguments={"path": relative, "old_text": old, "new_text": new},
                    id=f"fastpath_{number}",
                )
                number += 1
                result = toolbox.dispatch(call.name, call.arguments)
                applied.calls.append((call, result))
                if not result.ok:
                    self.rollback(applied, toolbox)
                    raise EditRefused(f"edit_file refused ({result.reason}): {result.content}")
            if path.read_text(encoding="utf-8") != wanted:
                # Every hunk landed and the file still is not what was computed -- the
                # bounded repair in edit_file moved something. Not worth guessing about.
                self.rollback(applied, toolbox)
                raise EditRefused(f"{relative} did not come out as intended")
        return applied

    @staticmethod
    def rollback(applied: Applied, toolbox: Toolbox) -> None:
        """Put every touched file back to its original bytes."""
        project_dir = toolbox.project.directory
        for relative, original in applied.originals.items():
            path = resolve_in_project(project_dir, relative, for_write=True)
            path.write_text(original, encoding="utf-8")
            toolbox.report(Step("undone", f"put {relative} back the way it was",
                                path=relative, content=original))
