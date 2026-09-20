"""The agent loop: prompt, tool calls, and the repair cycle.

WORKORDER_01 sections 17, 18 and 28.

Prompt composition is base + profile + build style + current project context + project
memory. The project context is assembled by the application from what it
deterministically knows -- the file list above all -- rather than being something the
model must go and fetch. Phase 1 measured that choice as worth 19 points of tool-selection
accuracy (SPIKES.md section 4), and section 15A applies the same rule to memory.

Both collaborators here are optional. Without a :class:`VersionHistory` nothing is
checkpointed; without a :class:`MemoryManager` nothing is remembered between threads. The
loop itself behaves identically either way, which is what keeps them separately testable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from opennest import paths
from opennest.agent.tools import Toolbox, ToolResult, normalise_tool_name, schemas_for
from opennest.ai.provider import Message, ModelProvider, Settings, ToolCall
from opennest.execution.python_runner import RunResult
from opennest.memory.manager import MemoryManager
from opennest.projects.manager import Project
from opennest.security.sandbox import visible_files
from opennest.versioning.checkpoint import (
    LABEL_AFTER_CHANGE,
    LABEL_BEFORE_CHANGE,
    VersionHistory,
)

#: WORKORDER_01 section 28: "Maximum automatic repair attempts: 3".
MAX_REPAIR_ATTEMPTS = 3

#: A hard stop on tool calls per turn, so a confused model cannot loop forever.
MAX_TOOL_CALLS_PER_TURN = 8

#: Phase 1 measured a "call exactly one tool" instruction as worth 30 points of
#: single-turn selection accuracy. Carried into the multi-turn loop verbatim it actively
#: caused failure: the model read a file, then reported an edit it had never made,
#: because it had been told to stop after one call. The "do not explore" property is
#: what mattered; the "exactly one" part had to go.
TOOL_USE_RULES = (
    "Use your tools to actually change the project. Do not look around first -- the "
    "files in this project are listed below and you already know what exists.\n"
    "- To change a file, call write_file with the complete new contents.\n"
    "- Never say you changed, added or fixed something unless you actually called "
    "write_file and it succeeded. Saying it is not doing it.\n"
    "- If they ask to run or play it, call run_project.\n"
    "- To create a file that does not exist yet, call write_file.\n"
    "- Read a file first only when you do not already know what is in it."
)

#: Phrases a model uses when it believes it edited something. Used to catch the failure
#: above deterministically rather than trusting the prompt to have fixed it.
_CLAIMED_CHANGE = (
    "i changed", "i've changed", "i have changed", "i increased", "i decreased",
    "i updated", "i've updated", "i added", "i've added", "i set", "i fixed",
    "i've fixed", "i made", "i replaced", "i removed", "i renamed",
)


@dataclass
class Turn:
    """What happened during one exchange, for the UI to render."""

    text: str = ""
    tool_results: list[tuple[str, ToolResult]] = field(default_factory=list)
    repair_attempts: int = 0
    gave_up: bool = False
    #: Ref of the checkpoint saved after this turn, if anything changed.
    checkpoint: str | None = None
    #: Whether the thread rolled over after this turn. For tests and logs only -- the
    #: child must never be told (WORKORDER_01 section 15A).
    rolled_over: bool = False


def build_system_prompt(
    project: Project,
    *,
    build_style: str = "build",
    last_run: RunResult | None = None,
    memory: str = "",
) -> str:
    """The new-thread bootstrap of section 15A: base + profile + style + state + memory."""
    base = (paths.prompts_dir() / "base.txt").read_text(encoding="utf-8").strip()
    profile_prompt = project.profile.system_prompt()
    style_file = "style_teach.txt" if build_style == "teach" else "style_build.txt"
    style = (paths.prompts_dir() / style_file).read_text(encoding="utf-8").strip()
    parts = [base, profile_prompt, style, TOOL_USE_RULES, project_state(project, last_run)]
    if memory:
        parts.append(memory)
    return "\n\n".join(parts)


def project_state(project: Project, last_run: RunResult | None = None) -> str:
    """Facts the application knows for certain. Never asked of the model.

    The file list and the last run result both live here rather than behind tools. They
    are application knowledge, and Phase 1 measured that offering them as tools costs
    real accuracy because the model reaches for them instead of acting.
    """
    files = visible_files(project.directory)
    listing = "\n".join(f"  {name}" for name in files) or "  (no files yet)"
    parts = [
        "CURRENT PROJECT",
        f"Name: {project.name}",
        f"Type: {project.profile.name}",
        f"Entry point: src/{project.manifest.entrypoint}",
        f"Run action: {project.profile.run_label}",
        f"Files in this project (you already know these):\n{listing}",
    ]
    if last_run is not None:
        if last_run.still_running:
            parts.append("Last run: the project started and is running now.")
        elif last_run.ok:
            parts.append("Last run: it worked.")
        else:
            parts.append(
                "The last run FAILED. This is the error, you do not need to ask for it:\n"
                + last_run.failure_text[:3000]
            )
    return "\n".join(parts)


class AgentController:
    """Drives one project's conversation with one model."""

    def __init__(
        self,
        project: Project,
        provider: ModelProvider,
        toolbox: Toolbox,
        *,
        build_style: str = "build",
        versions: VersionHistory | None = None,
        memory: MemoryManager | None = None,
    ) -> None:
        self.project = project
        self.provider = provider
        self.toolbox = toolbox
        self.build_style = build_style
        #: Saved versions. Named `versions`, not `history`, because `self.history` is
        #: already the message list -- conflating the two silently broke checkpointing.
        #: Optional so tests and headless use do not require Git.
        self.versions = versions
        #: Project memory and thread rollover. Optional for the same reason.
        self.memory = memory
        self.history: list[Message] = []
        self._reset_history()

    def _reset_history(self) -> None:
        """Begin a thread: one system message carrying the whole bootstrap."""
        self.history = [
            Message(role="system", content=build_system_prompt(
                self.project, build_style=self.build_style, memory=self._memory_block()))
        ]

    def refresh_state(self) -> None:
        """Re-inject the file list and last run result after anything changes."""
        self.history[0] = Message(
            role="system",
            content=build_system_prompt(
                self.project,
                build_style=self.build_style,
                last_run=self.toolbox.last_run,
                memory=self._memory_block(),
            ),
        )

    def _memory_block(self) -> str:
        return self.memory.context_block() if self.memory is not None else ""

    def send(
        self,
        text: str,
        *,
        on_text: Callable[[str], None] | None = None,
    ) -> Turn:
        """One exchange: the child says something, the agent acts, and reports back."""
        # Checkpoint whatever state exists before touching anything, so "undo" goes
        # back to what the child had rather than to some earlier assistant turn.
        self._checkpoint(LABEL_BEFORE_CHANGE)

        # "Like we talked about before" is answered from memory, deterministically,
        # before the model sees the message (WORKORDER_01 section 15A, memory retrieval).
        # The refresh is unconditional: a lookup that finds nothing must also clear the
        # previous turn's, or the model keeps being handed an answer to an old question.
        if self.memory is not None:
            self.memory.recall_for(text)
            self.refresh_state()

        self.history.append(Message(role="user", content=text))
        turn = Turn()
        challenged = False

        for _ in range(MAX_TOOL_CALLS_PER_TURN):
            reply = self._generate(on_text)
            self.history.append(
                Message(role="assistant", content=reply.text, tool_calls=reply.tool_calls)
            )
            if reply.text:
                turn.text = reply.text

            if not reply.wants_tool:
                if not challenged and self._claimed_a_change_it_did_not_make(turn, reply.text):
                    challenged = True
                    self.history.append(Message(role="user", content=(
                        "You did not actually change any file. Call write_file with the "
                        "complete new contents now, or say plainly that you have not "
                        "changed anything yet."
                    )))
                    continue
                return self._finish_turn(turn)

            should_continue = self._run_tools(reply.tool_calls, turn)
            if not should_continue:
                return self._finish_turn(turn)

        turn.text = turn.text or "I tried several steps but could not finish that."
        return self._finish_turn(turn)

    def _finish_turn(self, turn: Turn) -> Turn:
        """Save a checkpoint if the assistant changed anything, then update memory."""
        changed = any(result.changed_files for _, result in turn.tool_results)
        # State is refreshed before the checkpoint so the saved version contains both the
        # change and the note describing it.
        if self.memory is not None:
            self.memory.note_turn(
                changed_files=changed,
                ran_project=any(result.run is not None for _, result in turn.tool_results),
                last_run=self.toolbox.last_run,
            )
        if changed:
            turn.checkpoint = self._checkpoint(LABEL_AFTER_CHANGE)
        self._roll_over_if_needed(turn)
        return turn

    def _roll_over_if_needed(self, turn: Turn) -> None:
        """Hand this thread over to the next one, silently (WORKORDER_01 section 15A).

        This runs only after the turn is complete, so the child has already read the
        reply; nothing here changes what they see. Section 15A step 1 requires exactly
        that ordering, and steps 7 and 8 are the ``_reset_history`` below -- the new
        thread's system prompt is rebuilt with the memory the old one just wrote.
        """
        if self.memory is None or not self.memory.should_roll_over(self.history):
            return
        result = self.memory.roll_over(self.provider, self.history)
        if result.happened:
            self._reset_history()
            turn.rolled_over = True

    def close(self, *, summarise: bool = True) -> None:
        """End this project's thread. Called when the project closes, not per turn.

        ``summarise=False`` archives the thread and updates memory from facts alone,
        skipping the model call. Use it when quitting: a Mac application that pauses on
        Command-Q is broken, and an instant close with a slightly plainer handoff is the
        better trade. Returning to the Flight Deck is a pause rather than an exit, so
        that path keeps the summary.
        """
        if self.memory is not None:
            self.memory.close(self.provider if summarise else None, self.history)
            self._reset_history()

    def _checkpoint(self, label: str) -> str | None:
        if self.versions is None:
            return None
        # Versioning must never break the thing the child is doing -- except for a
        # credential, which save_quietly still raises for.
        return self.versions.save_quietly(label)

    @staticmethod
    def _claimed_a_change_it_did_not_make(turn: Turn, text: str) -> bool:
        """Catch the model reporting an edit it never performed.

        Phase 2 saw exactly this: read_file, then "I increased the player speed from 5
        to 8" with no write. The base prompt forbids it, but a 4B model does it anyway,
        so the application checks rather than trusts.
        """
        if any(result.changed_files for _, result in turn.tool_results):
            return False
        lowered = (text or "").lower()
        return any(phrase in lowered for phrase in _CLAIMED_CHANGE)

    def _generate(self, on_text: Callable[[str], None] | None):
        tools = schemas_for(self.toolbox.allowed)
        for chunk in self.provider.chat(
            self.history, tools=tools, settings=Settings(temperature=0.0)
        ):
            if chunk.text and on_text:
                on_text(chunk.text)
        reply = self.provider.finish()
        # The provider already counted the prompt, so the context budget never needs to
        # re-tokenise anything (conversations.context_budget).
        if self.memory is not None:
            self.memory.observe(reply)
        return reply

    def _run_tools(self, calls: tuple[ToolCall, ...], turn: Turn) -> bool:
        """Execute calls and append results. Returns whether to keep going."""
        for call in calls:
            result = self.toolbox.dispatch(call.name, call.arguments)
            turn.tool_results.append((call.name, result))
            self.history.append(
                Message(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=result.content,
                )
            )
            if result.changed_files or result.run is not None:
                self.refresh_state()

            # A failed run is the repair loop's trigger, not an ordinary tool reply.
            if normalise_tool_name(call.name) in ("run_project", "compile_project") \
                    and not result.ok:
                self._repair(turn)
                return False
        return True

    def _repair(self, turn: Turn) -> None:
        """Try to fix a failing project, at most MAX_REPAIR_ATTEMPTS times.

        After that, stop and explain. WORKORDER_01 section 28 is explicit that this must
        not loop indefinitely -- a child watching an AI fail the same way five times is a
        worse experience than being told plainly that it is stuck.
        """
        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            turn.repair_attempts = attempt
            self.history.append(
                Message(
                    role="user",
                    content=(
                        "That failed. Look at the error above, fix the cause by writing "
                        "the corrected file, then run it again."
                    ),
                )
            )
            reply = self._generate(None)
            self.history.append(
                Message(role="assistant", content=reply.text, tool_calls=reply.tool_calls)
            )
            if reply.text:
                turn.text = reply.text

            if not reply.wants_tool:
                return

            succeeded = False
            for call in reply.tool_calls:
                result = self.toolbox.dispatch(call.name, call.arguments)
                turn.tool_results.append((call.name, result))
                self.history.append(
                    Message(role="tool", name=call.name, tool_call_id=call.id,
                            content=result.content)
                )
                if result.changed_files or result.run is not None:
                    self.refresh_state()
                if result.run is not None and result.ok:
                    succeeded = True
            if succeeded:
                return

        turn.gave_up = True
        turn.text = (
            "I tried three times and could not get this working. "
            "Tell me what you want to try next, or we can go back to the last version "
            "that worked."
        )


def stream_reply(controller: AgentController, text: str) -> Iterator[str]:
    """Convenience wrapper for callers that want the text as it arrives."""
    pieces: list[str] = []
    controller.send(text, on_text=pieces.append)
    yield from pieces
