"""The tools the AI may use, and the dispatcher that runs them.

WORKORDER_01 section 18: the AI interacts with a project only through explicit tools.
No shell, no network, no path outside the project.

Two things here come straight out of Phase 1 (SPIKES.md section 4):

- There is no ``list_project_files``. The file list is deterministic application
  knowledge and is injected into context instead. Offering it as a tool cost 19 points of
  selection accuracy because the model reached for it instead of acting.
- :func:`normalise_tool_name` exists because models emit ``run_project()`` and
  ``functions.run_project``. Both are the right answer, awkwardly spelled. Rejecting them
  would look like a hallucination rate that is not real.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from opennest.execution import arduino
from opennest.execution.python_runner import RunResult, run_project
from opennest.projects.manager import Project
from opennest.security.sandbox import PathNotAllowed, resolve_in_project

#: Refuse to hand the model a file so large it destroys the context window.
MAX_READ_CHARS = 60_000


class ToolError(Exception):
    """A tool refused or failed. The message goes back to the model to react to."""


@dataclass
class ToolResult:
    ok: bool
    content: str
    #: Set when a tool changed the project, so the caller knows to save or snapshot.
    changed_files: tuple[str, ...] = ()
    #: Carried through so the repair loop can look at an actual failure.
    run: RunResult | None = None


def normalise_tool_name(name: str | None) -> str | None:
    """``run_project()``, ``functions.run_project`` and ``run_project`` are all the same."""
    if not isinstance(name, str):
        return None
    cleaned = name.strip().rstrip("()").split(".")[-1].strip()
    return cleaned or None


# --------------------------------------------------------------------------- schemas

def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


SCHEMAS: dict[str, dict] = {
    "read_file": _schema(
        "read_file",
        "Read one file from the project.",
        {"path": {"type": "string",
                  "description": "Path relative to the project, e.g. src/game.py"}},
        ["path"],
    ),
    "edit_file": _schema(
        "edit_file",
        "Change one exact piece of text in an existing file. Use this for every change "
        "to a file that already exists.",
        {
            "path": {"type": "string", "description": "Path relative to the project."},
            "old_text": {
                "type": "string",
                "description": "The exact text to find, usually a single line. "
                               "It must appear in the file exactly once.",
            },
            "new_text": {"type": "string", "description": "What to put in its place."},
        },
        ["path", "old_text", "new_text"],
    ),
    "write_file": _schema(
        "write_file",
        "Create a NEW file that does not exist yet. To change an existing file, "
        "use edit_file instead.",
        {
            "path": {"type": "string", "description": "Path relative to the project."},
            "content": {"type": "string", "description": "The contents of the new file."},
        },
        ["path", "content"],
    ),
    "run_project": _schema(
        "run_project", "Run the project and capture its output.", {}, []
    ),
    "compile_project": _schema(
        "compile_project", "Compile the project and capture any errors.", {}, []
    ),
    "inspect_error": _schema(
        "inspect_error", "Look at the error from the last failed run.", {}, []
    ),
}


def schemas_for(tool_names: tuple[str, ...]) -> list[dict]:
    """Tool schemas for a profile, in a stable order the model sees consistently."""
    return [SCHEMAS[name] for name in tool_names if name in SCHEMAS]


# --------------------------------------------------------------------------- the tools

class Toolbox:
    """Executes tool calls against one project. Holds the last run for inspect_error."""

    def __init__(
        self,
        project: Project,
        *,
        python_executable: str | None = None,
        network_policy: Callable[[], bool] | None = None,
    ) -> None:
        self.project = project
        self.python_executable = python_executable
        #: Answers "may this run reach the internet?" at the moment of the run
        #: (WORKORDER_01 section 25). A callable rather than a flag because the answer
        #: can be "Ask Parent", which is a dialog, not a value known at construction.
        #: None means no -- the same fail-closed default the sandbox has always had.
        self.network_policy = network_policy
        self.last_run: RunResult | None = None

    def _network_allowed(self) -> bool:
        if self.network_policy is None:
            return False
        try:
            return bool(self.network_policy())
        except Exception:
            # A permission check that fails is not a permission granted.
            return False

    @property
    def allowed(self) -> tuple[str, ...]:
        return tuple(self.project.profile.tools)

    def dispatch(self, name: str | None, arguments: dict | str | None) -> ToolResult:
        """Run one tool call. Never raises for model error -- it returns a message."""
        tool = normalise_tool_name(name)
        if tool is None:
            return ToolResult(False, "No tool name was given.")
        if tool not in self.allowed:
            offered = ", ".join(self.allowed)
            return ToolResult(False, f"{tool!r} is not available here. You can use: {offered}.")

        args = _coerce_arguments(arguments)
        if args is None:
            return ToolResult(False, "The tool arguments were not valid JSON.")

        handler: Callable[[dict], ToolResult] = getattr(self, f"_{tool}")
        try:
            return handler(args)
        except PathNotAllowed as exc:
            return ToolResult(False, str(exc))
        except ToolError as exc:
            return ToolResult(False, str(exc))
        except OSError as exc:
            return ToolResult(False, f"That did not work: {exc}")

    # -- individual tools ---------------------------------------------------

    def _read_file(self, args: dict) -> ToolResult:
        path = resolve_in_project(self.project.directory, _require(args, "path"))
        if not path.is_file():
            raise ToolError(f"There is no file called {args['path']!r} in this project.")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(
                f"{args['path']!r} is not a text file, so it cannot be read as code."
            ) from exc
        if len(text) > MAX_READ_CHARS:
            raise ToolError(
                f"{args['path']!r} is too long to read in one go "
                f"({len(text)} characters). Ask for a smaller file."
            )
        return ToolResult(True, text)

    def _write_file(self, args: dict) -> ToolResult:
        """Create a new file. Existing files must be changed with edit_file.

        Overwriting is refused on purpose. Phase 2 measured a 4B model asked to reproduce
        a whole existing file returning syntactically broken Python -- it silently
        destroyed a working game. Refusing turns that into a clear, recoverable error.
        """
        relative = _require(args, "path")
        content = args.get("content")
        if content is None:
            raise ToolError("write_file needs both a path and the content to write.")
        if not isinstance(content, str):
            content = str(content)
        path = resolve_in_project(self.project.directory, relative, for_write=True)
        if path.exists():
            raise ToolError(
                f"{relative!r} already exists. Use edit_file to change part of it, "
                f"giving the exact text to replace."
            )
        _reject_broken_python(relative, content)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        rel = str(path.relative_to(self.project.directory.resolve()))
        return ToolResult(True, f"Wrote {rel} ({len(content)} characters).", changed_files=(rel,))

    def _edit_file(self, args: dict) -> ToolResult:
        """Replace one exact snippet. Far more reliable than whole-file rewrites.

        Phase 2 measured a 4B model emitting Python triple-quotes inside the JSON string
        when asked to reproduce a whole file, which makes the call unparseable. A single
        line survives JSON escaping intact.
        """
        relative = _require(args, "path")
        old = args.get("old_text")
        new = args.get("new_text")
        if old is None or new is None:
            raise ToolError("edit_file needs a path, the exact old_text, and the new_text.")
        old, new = str(old), str(new)
        if not old:
            raise ToolError("edit_file needs the exact text to replace. To make a new "
                            "file, use write_file.")

        path = resolve_in_project(self.project.directory, relative, for_write=True)
        if not path.is_file():
            raise ToolError(
                f"There is no file called {relative!r} yet. Use write_file to create it."
            )
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"{relative!r} is not a text file.") from exc

        occurrences = text.count(old)
        if occurrences == 0:
            raise ToolError(
                f"That exact text is not in {relative!r}. Read the file again and copy "
                f"the line you want to change exactly as it appears."
            )
        if occurrences > 1:
            raise ToolError(
                f"That text appears {occurrences} times in {relative!r}. Include a bit "
                f"more of the surrounding line so it matches only once."
            )

        updated = text.replace(old, new, 1)
        _reject_broken_python(relative, updated)
        path.write_text(updated, encoding="utf-8")
        rel = str(path.relative_to(self.project.directory.resolve()))
        return ToolResult(True, f"Changed {rel}.", changed_files=(rel,))

    def _run_project(self, args: dict) -> ToolResult:
        command = self.project.profile.run_command
        if not command:
            raise ToolError("This kind of project cannot be run.")
        result = run_project(
            self.project.directory,
            command,
            python_executable=self.python_executable,
            interactive=self.project.profile.is_interactive,
            allow_network=self._network_allowed(),
        )
        self.last_run = result
        if result.ok:
            self._record_success()
        if result.still_running:
            return ToolResult(True, "It started and is running now.", run=result)
        if result.ok:
            body = result.stdout.strip() or "(the project produced no output)"
            return ToolResult(True, f"It ran successfully.\n\n{body}", run=result)
        return ToolResult(False, result.failure_text or "It failed with no output.", run=result)

    def _record_success(self) -> None:
        """Remember that the project worked, so memory can say so after a restart.

        WORKORDER_01 section 15A names successful run status as a fact the application
        populates programmatically. Without this the manifest field stays None forever
        and ``project_state.md`` can never report it.
        """
        self.project.manifest.last_successful_run = (
            datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        with contextlib.suppress(OSError):
            self.project.save()

    def _compile_project(self, args: dict) -> ToolResult:
        """Compile, for the one profile that compiles.

        The profile's ``compile_command`` names the toolchain; it is not a complete
        command line, because a real compile needs the board out of the manifest and a
        sketch path derived from the entrypoint. :mod:`opennest.execution.arduino`
        assembles it -- and had to, since a bare ``arduino-cli compile`` cannot work
        (SPIKES.md section 14).
        """
        command = self.project.profile.compile_command
        if not command:
            raise ToolError("This kind of project cannot be compiled.")
        if command[0] != arduino.EXECUTABLE:
            raise ToolError(f"Open Nest does not know how to compile with {command[0]!r}.")

        if not arduino.available():
            return ToolResult(False, arduino.missing_message())

        board = self.project.manifest.arduino_board
        if not board:
            # Section 8: never invent hardware details. Guessing a board guesses every
            # pin on it, so the honest move is to ask.
            return ToolResult(
                False,
                "I do not know which Arduino board this is for yet. Ask the child which "
                "board they have and tell them to choose it next to the Compile button.",
            )

        try:
            result = arduino.compile_sketch(self.project, board)
        except arduino.ArduinoUnavailable as exc:
            return ToolResult(False, str(exc))
        self.last_run = result
        if result.ok:
            self._record_success()
            body = result.stdout.strip()
            return ToolResult(True, f"It compiled successfully.\n\n{body}", run=result)
        return ToolResult(False, result.failure_text or "Compiling failed.", run=result)

    def _inspect_error(self, args: dict) -> ToolResult:
        if self.last_run is None:
            return ToolResult(False, "Nothing has been run yet, so there is no error to look at.")
        if self.last_run.ok:
            return ToolResult(True, "The last run worked, so there is no error.")
        return ToolResult(True, self.last_run.failure_text, run=self.last_run)


def _reject_broken_python(relative: str, content: str) -> None:
    """Never let the AI leave a child's Python file unparseable.

    A broken game is a much worse outcome than a refused edit, and the model can act on
    the SyntaxError to try again.
    """
    if not relative.endswith(".py"):
        return
    try:
        compile(content, relative, "exec")
    except SyntaxError as exc:
        raise ToolError(
            f"That change would break {relative}: {exc.msg} on line {exc.lineno}. "
            f"Nothing was saved. Fix the code and try again."
        ) from exc
    except ValueError as exc:  # e.g. NUL bytes
        raise ToolError(f"That content cannot be saved to {relative}: {exc}") from exc


def _require(args: dict, key: str) -> str:
    value = args.get(key)
    if value is None or not str(value).strip():
        raise ToolError(f"That tool needs a {key}.")
    return str(value)


def _coerce_arguments(arguments: dict | str | None) -> dict | None:
    """Models sometimes send arguments as a JSON string rather than an object."""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
