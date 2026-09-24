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

from opennest.execution import arduino, playtest
from opennest.execution.python_runner import RunResult, run_project, stop_project
from opennest.projects.manager import Project
from opennest.security.sandbox import PathNotAllowed, resolve_in_project

#: Refuse to hand the model a file so large it destroys the context window.
MAX_READ_CHARS = 60_000


class ToolError(Exception):
    """A tool refused or failed. The message goes back to the model to react to.

    ``reason`` is the same refusal in one machine-readable word. The prose is for the
    model to read; the code is for Open Nest to count, test and branch on without
    matching on English that is free to be reworded.
    """

    def __init__(self, message: str, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class ToolResult:
    ok: bool
    content: str
    #: Set when a tool changed the project, so the caller knows to save or snapshot.
    changed_files: tuple[str, ...] = ()
    #: Carried through so the repair loop can look at an actual failure.
    run: RunResult | None = None
    #: Why a tool refused, in one word: ``not_found``, ``ambiguous``, ``missing_file``,
    #: ``syntax_error``, ``exists``, ``not_text``, ``too_long``, ``missing_argument``,
    #: ``outside_project``, ``unavailable``. Empty on success.
    reason: str = ""
    #: Which bounded repair made an edit land, empty when the text matched exactly.
    #: Phase 12.2 measures the recovery path's usage through this.
    recovered: str = ""


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
            return ToolResult(False, "No tool name was given.", reason="no_tool_name")
        if tool not in self.allowed:
            offered = ", ".join(self.allowed)
            return ToolResult(False, f"{tool!r} is not available here. You can use: {offered}.",
                              reason="not_available")

        args = _coerce_arguments(arguments)
        if args is None:
            return ToolResult(False, "The tool arguments were not valid JSON.",
                              reason="bad_arguments")

        handler: Callable[[dict], ToolResult] = getattr(self, f"_{tool}")
        try:
            return handler(args)
        except PathNotAllowed as exc:
            return ToolResult(False, str(exc), reason="outside_project")
        except ToolError as exc:
            return ToolResult(False, str(exc), reason=exc.reason)
        except OSError as exc:
            return ToolResult(False, f"That did not work: {exc}", reason="os_error")

    # -- individual tools ---------------------------------------------------

    def _read_file(self, args: dict) -> ToolResult:
        path = resolve_in_project(self.project.directory, _require(args, "path"))
        if not path.is_file():
            raise ToolError(f"There is no file called {args['path']!r} in this project.",
                            reason="missing_file")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(
                f"{args['path']!r} is not a text file, so it cannot be read as code.",
                reason="not_text",
            ) from exc
        if len(text) > MAX_READ_CHARS:
            raise ToolError(
                f"{args['path']!r} is too long to read in one go "
                f"({len(text)} characters). Ask for a smaller file.",
                reason="too_long",
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
            raise ToolError("write_file needs both a path and the content to write.",
                            reason="missing_argument")
        if not isinstance(content, str):
            content = str(content)
        path = resolve_in_project(self.project.directory, relative, for_write=True)
        if path.exists():
            raise ToolError(
                f"{relative!r} already exists. Use edit_file to change part of it, "
                f"giving the exact text to replace.",
                reason="exists",
            )
        # Same hazard as edit_file's new_text, and worse here: a whole new file written
        # as one commented line looks created and does nothing.
        content, unescaped = repair_written_text(relative, content)
        _reject_broken_python(relative, content)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        rel = str(path.relative_to(self.project.directory.resolve()))
        return ToolResult(True, f"Wrote {rel} ({len(content)} characters).",
                          changed_files=(rel,),
                          recovered="escaping" if unescaped else "")

    def _edit_file(self, args: dict) -> ToolResult:
        """Replace one exact snippet, with a bounded repair when the match is near.

        Phase 2 measured a 4B model emitting Python triple-quotes inside the JSON string
        when asked to reproduce a whole file, which makes the call unparseable. A single
        line survives JSON escaping intact, so targeted replacement is the right shape
        and stays the first path here.

        Phase 12.2 measured what it costs when the model gets that single line *nearly*
        right. Asked "make the player move faster", the model sent
        ``    PLAYER_SPEED = 5`` six times against a starter that has it at column zero,
        and the tool refused six times. Exact reproduction is not something a
        probabilistic model does reliably, and it will be a different model next year, so
        :func:`repair_edit` absorbs the near misses instead -- deterministically, and
        only ever when the text is found in exactly one place.
        """
        relative = _require(args, "path")
        old = args.get("old_text")
        new = args.get("new_text")
        if old is None or new is None:
            raise ToolError("edit_file needs a path, the exact old_text, and the new_text.",
                            reason="missing_argument")
        old, new = str(old), str(new)
        if not old:
            raise ToolError("edit_file needs the exact text to replace. To make a new "
                            "file, use write_file.", reason="missing_argument")

        path = resolve_in_project(self.project.directory, relative, for_write=True)
        if not path.is_file():
            raise ToolError(
                f"There is no file called {relative!r} yet. Use write_file to create it.",
                reason="missing_file",
            )
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"{relative!r} is not a text file.", reason="not_text") from exc

        occurrences = text.count(old)
        if occurrences > 1:
            raise ToolError(
                f"That text appears {occurrences} times in {relative!r}. Include a bit "
                f"more of the surrounding line so it matches only once.",
                reason="ambiguous",
            )

        recovered = ""
        if occurrences == 1:
            # The exact path still has to look at what is being written: old_text can
            # match perfectly while new_text carries literal escapes, and that writes a
            # whole block into the file as one comment.
            new, unescaped = repair_written_text(relative, new)
            if unescaped:
                recovered = "escaping"
            updated = text.replace(old, new, 1)
        else:
            repair = repair_edit(text, old, new)
            if repair is None:
                raise ToolError(
                    f"That exact text is not in {relative!r}. Read the file again and "
                    f"copy the line you want to change exactly as it appears.",
                    reason="not_found",
                )
            updated, recovered = repair

        _reject_broken_python(relative, updated)
        path.write_text(updated, encoding="utf-8")
        rel = str(path.relative_to(self.project.directory.resolve()))
        return ToolResult(True, f"Changed {rel}.", changed_files=(rel,), recovered=recovered)

    def stop_running(self) -> None:
        """Stop the project if it is still running. Safe to call when it is not.

        ``last_run`` holds one result, and an interactive profile's run does not finish
        on its own -- so every extra ``run_project`` used to overwrite the only reference
        to a live process and orphan it. Nothing could reach it afterwards: Stop reads
        ``last_run``, so does ``Workbench.release``, so the window stayed on screen until
        the child killed it themselves, and a conversation where Gary tested the game
        three times left three of them. Phase 12.2 measured five stacked up across two
        walks, all reparented to init.

        One project runs one copy of itself. Starting again stops the last one first.
        """
        if self.last_run is not None and self.last_run.still_running:
            stop_project(self.last_run)

    def _run_project(self, args: dict) -> ToolResult:
        command = self.project.profile.run_command
        if not command:
            raise ToolError("This kind of project cannot be run.", reason="unavailable")
        self.stop_running()
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

    def playtest(self) -> playtest.Playtest | None:
        """Run the game once without a window and report what it did, or None.

        **Not a tool.** It is in no schema and ``dispatch`` cannot reach it: the
        application decides when a game gets tested, the way it already decides what
        the file list is. Offering the model a fifth tool costs selection accuracy
        (SPIKES.md section 4), and a check the model can choose to skip is not a check.

        None when the profile has no headless test or there is nothing to run yet.
        Deliberately leaves ``last_run`` alone: that is the game on the child's screen,
        which Stop and closing the project have to be able to reach.
        """
        profile = self.project.profile
        if profile.playtest != "pygame" or not profile.run_command:
            return None
        if not self.project.entrypoint_path.is_file():
            return None
        return playtest.run(
            self.project.directory,
            profile.run_command,
            python_executable=self.python_executable,
        )

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
            raise ToolError("This kind of project cannot be compiled.", reason="unavailable")
        if command[0] != arduino.EXECUTABLE:
            raise ToolError(f"Open Nest does not know how to compile with {command[0]!r}.",
                            reason="unavailable")

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


# ------------------------------------------------------- the bounded edit recovery

def _unescape(text: str) -> str:
    r"""Undo a model that wrote ``\n`` as two characters where a newline belonged."""
    return text.replace("\\n", "\n").replace("\\t", "\t")


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _unique_window(text: str, old: str, *, ignore_indent: bool) -> tuple[int, int] | None:
    """The one line window matching ``old``, or None if there is not exactly one.

    Line-aligned on purpose. A character-span match in normalised space would have to be
    mapped back onto the original bytes to be applied, and getting that wrong edits the
    wrong region silently -- which is the whole failure this tool refuses to risk.
    """
    normalise = (lambda s: s.strip()) if ignore_indent else (lambda s: s.rstrip())
    wanted = [normalise(line) for line in old.replace("\r\n", "\n").split("\n")]
    while wanted and not wanted[-1]:
        wanted.pop()
    if not wanted:
        return None

    haystack = [normalise(line) for line in text.split("\n")]
    hits = [
        index
        for index in range(len(haystack) - len(wanted) + 1)
        if haystack[index:index + len(wanted)] == wanted
    ]
    if len(hits) != 1:
        return None
    return hits[0], hits[0] + len(wanted)


def _shift_indent(lines: list[str], columns: int) -> list[str] | None:
    """Move every non-blank line by ``columns``. None when it cannot be done safely."""
    if columns == 0:
        return lines
    shifted = []
    for line in lines:
        if not line.strip():
            shifted.append(line)
        elif columns > 0:
            shifted.append(" " * columns + line)
        else:
            available = len(line) - len(line.lstrip(" "))
            if available < -columns:
                # Dedenting further than the line is indented would join it to the
                # previous block. Refuse the whole repair rather than guess.
                return None
            shifted.append(line[-columns:])
    return shifted


def _splice(text: str, window: tuple[int, int], new: str,
            *, shift: int = 0) -> str | None:
    start, end = window
    lines = text.split("\n")
    replacement = new.replace("\r\n", "\n").split("\n")
    while replacement and not replacement[-1]:
        replacement.pop()
    if shift:
        replacement = _shift_indent(replacement, shift)
        if replacement is None:
            return None
    return "\n".join(lines[:start] + replacement + lines[end:])


def repair_edit(text: str, old: str, new: str) -> tuple[str, str] | None:
    r"""Try the bounded repairs in order; return ``(updated_text, which)`` or None.

    Phase 12.2 measured why every ``edit_file`` in a real Games conversation was refused
    (SPIKES.md section 22). The model was not failing to understand the file -- it was
    reproducing the right lines and getting the *encoding* wrong: writing ``\\n`` for a
    newline, or carrying an indentation the line does not have. Demanding byte-perfect
    reproduction from a probabilistic model is a requirement it cannot meet reliably, and
    the tool has to be the thing that changes.

    Every rung obeys the same two rules, and they are what keeps this from being fuzzy
    matching:

    - **Exactly one match, or no repair.** Two candidates is ambiguity and stays a
      refusal. Nothing here ever picks the "closest" text.
    - **Line-aligned and deterministic.** No edit distance, no similarity score, no
      partial-line guessing. Each rung is a normalisation anyone can reproduce by hand.

    ``_reject_broken_python`` still runs on whatever comes back, so a repair that would
    leave the child's file unparseable is refused like any other.
    """
    attempts: list[tuple[str, str, str]] = [(old, new, "")]
    if "\\n" in old or "\\t" in old:
        attempts.append((_unescape(old), _unescape(new), "escaping"))

    for candidate_old, candidate_new, label in attempts:
        # The escaping repair alone may be all that was wrong.
        if label and text.count(candidate_old) == 1:
            return text.replace(candidate_old, candidate_new, 1), label

        # Trailing whitespace and line endings. Neither can change what Python means.
        window = _unique_window(text, candidate_old, ignore_indent=False)
        if window is not None:
            updated = _splice(text, window, candidate_new)
            if updated is not None:
                return updated, _label(label, "whitespace")

        # Leading whitespace. In Python this IS the block structure, so the replacement
        # is moved by the same amount the model was out by rather than written as sent.
        window = _unique_window(text, candidate_old, ignore_indent=True)
        if window is not None:
            first_old = candidate_old.replace("\r\n", "\n").split("\n")[0]
            actual = _indent_of(text.split("\n")[window[0]])
            sent = _indent_of(first_old)
            if "\t" not in actual and "\t" not in sent:
                updated = _splice(text, window, candidate_new,
                                  shift=len(actual) - len(sent))
                if updated is not None:
                    return updated, _label(label, "indentation")
    return None


def _label(*parts: str) -> str:
    return "+".join(part for part in parts if part)


def repair_written_text(relative: str, new: str) -> tuple[str, bool]:
    r"""Undo a literal ``\n`` in text about to be written, when it cannot be intended.

    Phase 12.2's verification walk found the nastiest version of the escaping fault, and
    the recovery above does not reach it. The model matched ``old_text`` **exactly** and
    then sent a ``new_text`` whose newlines were the two characters ``\`` and ``n``::

        # Draw spaceship with image\n    try:\n        spaceship_surface = ...

    Written verbatim that is a single comment line. It compiles, so the syntax gate
    passes, the tool reports success -- and the child's game silently loses the code that
    drew the player. A refusal would have been better than that.

    The discriminator is Python's own parser rather than a guess about intent, which is
    what keeps this from being the fuzzy editing the design forbids:

    - A ``\n`` the model meant as **newline** unescapes into valid code.
    - A ``\n`` the model meant as **string content** (``print("a\nb")``) unescapes into a
      broken string literal, fails to compile, and is left exactly as sent.

    Only considered when the text has literal escapes and no real newline at all. Mixed
    text is ambiguous about which the model meant, so it is left alone.
    """
    if not relative.endswith(".py"):
        return new, False
    if "\n" in new or "\\n" not in new:
        return new, False
    candidate = _unescape(new)
    try:
        compile(candidate, relative, "exec")
    except (SyntaxError, ValueError):
        try:
            # A fragment is usually indented and will not compile on its own; judge the
            # dedented form rather than refusing every in-block edit.
            compile(_dedent_for_check(candidate), relative, "exec")
        except (SyntaxError, ValueError):
            return new, False
    return candidate, True


def _dedent_for_check(text: str) -> str:
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return text
    common = min(len(line) - len(line.lstrip()) for line in lines)
    return "\n".join(line[common:] if line.strip() else line for line in text.split("\n"))


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
            f"Nothing was saved. Fix the code and try again.",
            reason="syntax_error",
        ) from exc
    except ValueError as exc:  # e.g. NUL bytes
        raise ToolError(f"That content cannot be saved to {relative}: {exc}",
                        reason="bad_content") from exc


def _require(args: dict, key: str) -> str:
    value = args.get(key)
    if value is None or not str(value).strip():
        raise ToolError(f"That tool needs a {key}.", reason="missing_argument")
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
