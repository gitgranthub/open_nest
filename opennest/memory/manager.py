"""One project's memory, as the agent sees it.

WORKORDER_01 section 15A, assembled. :class:`AgentController` holds one of these and
talks to nothing else in ``memory/`` or ``conversations/`` -- the same arrangement as
``VersionHistory``, and for the same reason: the agent loop should stay about the
conversation.

Memory is optional. Constructed without one, the controller behaves exactly as it did in
Phase 3, which keeps Git, memory and the agent independently testable.

WHEN MEMORY IS WRITTEN
----------------------
Section 15A: "Do not rewrite memory after every trivial chat message."

- ``project_state.md`` is rewritten after any turn that changed a file. It is pure fact
  and costs a file write, so there is nothing to ration.
- ``project_bible.md`` and the thread archive are written at a **rollover** and at
  **close**. Both need a model call, so both are events, not habits.

Closing a project ends its thread. A session boundary is a natural thread boundary: the
transcript is archived, the bible is brought up to date, and the next launch starts a new
thread already knowing what the last one decided. Without this, a child who works below
the rollover threshold for weeks would accumulate no memory at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from opennest.ai.provider import Message, ModelInfo, ModelProvider, Reply
from opennest.conversations import rollover
from opennest.conversations.context_budget import ContextBudget, ContextPolicy, fit
from opennest.execution.python_runner import RunResult
from opennest.memory import history_search, project_bible, project_state
from opennest.memory.project_state import StateNotes
from opennest.projects.manager import Project
from opennest.versioning.checkpoint import VersionHistory
from opennest.versioning.git_manager import GitError


@dataclass
class MemoryManager:
    """Project memory and thread rollover for one open project."""

    project: Project
    policy: ContextPolicy = ContextPolicy()
    #: Only ever read from, for the Git state section 15A wants recorded programmatically.
    #: Optional, because memory must not require Git any more than the agent does.
    versions: VersionHistory | None = None

    def __post_init__(self) -> None:
        self.budget = ContextBudget(self.policy)
        self.notes: StateNotes = project_state.load_notes(self.project)
        #: Hits from the current turn's memory lookup. Rebuilt every turn, never kept.
        self._recalled: str = ""

    @classmethod
    def for_provider(
        cls,
        project: Project,
        provider: ModelProvider | None,
        *,
        versions: VersionHistory | None = None,
    ) -> MemoryManager:
        """Build with the policy of whichever model this project is using."""
        info: ModelInfo | None = getattr(provider, "info", None)
        policy = ContextPolicy.for_model(info) if info else ContextPolicy()
        return cls(project=project, policy=policy, versions=versions)

    def adopt(self, provider: ModelProvider | None) -> None:
        """Switch to a different model's context budget, mid-thread.

        The conversation carries over unchanged; only the budget does not. Token counts
        reported by the previous model were produced by a different tokeniser, so the
        running total is reset rather than reinterpreted -- the next reply re-establishes
        it, and until then the estimate backstop in ``ContextBudget`` covers the gap.
        """
        info: ModelInfo | None = getattr(provider, "info", None)
        self.policy = ContextPolicy.for_model(info) if info else ContextPolicy()
        self.budget = ContextBudget(self.policy)

    @property
    def thread_number(self) -> int:
        return self.project.manifest.active_thread

    # -- what goes into the prompt ------------------------------------------

    def context_block(self) -> str:
        """The memory half of the new-thread bootstrap (section 15A).

        The bible, whatever was carried over from the last thread, and -- only when the
        child referred to something earlier -- what a deterministic search turned up.

        Section 15A also lists "recent handoff summary" here. Both halves of that summary
        are already present: its decisions were merged into the bible, and its "where we
        left off" line *is* the carried task. Injecting the summary file as well would
        put the same sentences in the prompt twice. The file still exists for a parent to
        read and for :mod:`opennest.memory.history_search` to search.

        Trimmed to the model's ``memory_reserved_tokens``. That number exists to stop
        memory from crowding out the conversation it is supposed to support.
        """
        parts: list[str] = []

        bible = project_bible.load(self.project)
        if not bible.is_empty:
            parts.append(
                "PROJECT MEMORY\n"
                "What you already know about this project from earlier work. Treat it as "
                "true. Do not ask them to tell you again.\n\n"
                + bible.render_for_prompt()
            )

        carried = project_state.carried_notes(self.notes)
        if carried:
            parts.append(carried)

        block = fit("\n\n".join(parts), self.policy.memory_reserved_tokens)

        # The recall block is answering the message in front of them, so it is worth more
        # than the general memory and is added after the trim rather than inside it.
        if self._recalled:
            block = f"{block}\n\n{self._recalled}" if block else self._recalled
        return block

    def recall_for(self, text: str) -> str:
        """Search memory when the child refers to something earlier. See history_search."""
        self._recalled = ""
        if history_search.looks_like_a_memory_question(text):
            hits = history_search.search(self.project, text)
            self._recalled = history_search.as_context(hits)
        return self._recalled

    # -- keeping up to date -------------------------------------------------

    def observe(self, reply: Reply | None) -> None:
        self.budget.observe(reply)

    def note_turn(
        self,
        *,
        changed_files: bool,
        ran_project: bool = False,
        last_run: RunResult | None = None,
    ) -> None:
        """Refresh the deterministic state file after a turn that did something.

        Both flags describe *this* turn. ``last_run`` is the most recent run whenever it
        happened, because that is what the file records -- but a turn that only exchanged
        words has changed nothing in it, and section 15A is explicit about not rewriting
        memory after every message.
        """
        if not (changed_files or ran_project):
            return
        project_state.save(
            self.project,
            notes=self.notes,
            last_run=last_run,
            checkpoint_label=self._checkpoint_label(),
        )

    def _checkpoint_label(self) -> str | None:
        """The most recent saved version, or None when there is no Git to ask."""
        if self.versions is None:
            return None
        try:
            recent = self.versions.checkpoints(limit=1)
        except GitError:
            return None
        return recent[0].label if recent else None

    def should_roll_over(self, messages: Sequence[Message]) -> bool:
        return self.budget.should_roll_over(messages)

    # -- handing over -------------------------------------------------------

    def roll_over(
        self,
        provider: ModelProvider | None,
        messages: Sequence[Message],
    ) -> rollover.RolloverResult:
        """Archive this thread and start the next. Invisible to the child."""
        result = rollover.perform(
            self.project,
            provider,
            messages,
            policy=self.policy,
            notes=self.notes,
            checkpoint_label=self._checkpoint_label(),
        )
        self.notes = result.notes
        if result.happened:
            self.budget.reset()
            self._recalled = ""
        return result

    def close(
        self,
        provider: ModelProvider | None,
        messages: Sequence[Message],
    ) -> rollover.RolloverResult:
        """End the session's thread, so the next launch starts already knowing things."""
        return self.roll_over(provider, messages)
