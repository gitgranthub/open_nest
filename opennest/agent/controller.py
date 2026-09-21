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

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from opennest import paths
from opennest.agent.budget import (
    CORRECTION,
    PRIMARY,
    RECOVERY,
    REPAIR,
    ROLLOVER,
    BudgetExhausted,
    CallBudget,
    MeteredProvider,
    TurnUsage,
)
from opennest.agent.tools import Toolbox, ToolResult, normalise_tool_name, schemas_for
from opennest.ai.provider import (
    Message,
    ModelProvider,
    Settings,
    ToolCall,
    TruncatedReply,
)
from opennest.assets import manager as assets
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

#: The tool loop used to have its own iteration cap here. It no longer needs one: the
#: loop runs until the model stops asking for tools or the turn's shared call budget is
#: spent (``agent/budget.py``). One ceiling is the point -- a per-loop cap plus a
#: per-repair cap plus a rollover meant nothing counted the total.

#: Phase 1 measured a "call exactly one tool" instruction as worth 30 points of
#: single-turn selection accuracy. Carried into the multi-turn loop verbatim it actively
#: caused failure: the model read a file, then reported an edit it had never made,
#: because it had been told to stop after one call. The "do not explore" property is
#: what mattered; the "exactly one" part had to go.
#: These sentences must agree with what the tools actually do. They did not: this said
#: "to change a file, call write_file", while ``write_file`` refuses to overwrite and
#: its own schema says to use ``edit_file`` -- the Phase 2 decision SPIKES.md section 8
#: measured. Running the repair loop against the real model showed the cost: Luna
#: followed the prompt, ``write_file`` refused, and a whole repair attempt was spent
#: learning what the prompt should have said (SPIKES.md section 13).
TOOL_USE_RULES = (
    "Use your tools to actually change the project. Do not look around first -- the "
    "files in this project are listed below and you already know what exists.\n"
    "- To change a file that already exists, call edit_file with the exact text to "
    "replace. This is how you make almost every change.\n"
    "- write_file only creates a file that does not exist yet. It will refuse to "
    "overwrite one that does.\n"
    "- Never say you changed, added or fixed something unless the tool call succeeded. "
    "Saying it is not doing it.\n"
    "- If they ask to run or play it, call run_project.\n"
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
    #: Every provider call this turn made, and what each cost. Provider-reported.
    usage: TurnUsage = field(default_factory=TurnUsage)
    #: True when the turn stopped because it hit the shared call ceiling.
    hit_call_limit: bool = False
    #: Whether an empty reply was retried once with more room.
    recovered_truncation: bool = False
    #: Ref of the checkpoint saved after this turn, if anything changed.
    checkpoint: str | None = None
    #: Whether the thread rolled over after this turn. For tests and logs only -- the
    #: child must never be told (WORKORDER_01 section 15A).
    rolled_over: bool = False
    #: Whether the model was pulled up for describing a file it has not seen. For tests
    #: and for measuring how often the prompt is not enough (SPIKES.md section 10).
    corrected_invention: bool = False


def build_system_prompt(
    project: Project,
    *,
    build_style: str = "build",
    last_run: RunResult | None = None,
    memory: str = "",
    asset_context: str = "",
) -> str:
    """The new-thread bootstrap of section 15A: base + profile + style + state + memory.

    ``asset_context`` is the imported files and what is honestly known about them
    (WORKORDER_01 section 13). It comes last, nearest the conversation, because when it
    is non-empty the child has usually just attached something and is talking about it.
    """
    base = (paths.prompts_dir() / "base.txt").read_text(encoding="utf-8").strip()
    profile_prompt = project.profile.system_prompt()
    style_file = "style_teach.txt" if build_style == "teach" else "style_build.txt"
    style = (paths.prompts_dir() / style_file).read_text(encoding="utf-8").strip()
    parts = [base, profile_prompt, style, TOOL_USE_RULES, project_state(project, last_run)]
    if memory:
        parts.append(memory)
    if asset_context:
        parts.append(asset_context)
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
    # The base prompt tells the model to stop rather than install a missing package, so
    # it has to be told what it already has. Deterministic, from the profile.
    if project.profile.packages:
        parts.append(
            "Packages you can import (these are installed; there are no others):\n"
            + "\n".join(f"  {name}" for name in project.profile.packages)
        )
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
        #: Files attached to the message being answered. Rebuilt each turn and never
        #: kept, the same way memory's recall hits are -- the asset itself is permanent
        #: and stays in the listing, but "this picture" only means something for the
        #: message it arrived with.
        self._attached: tuple[assets.Asset, ...] = ()
        self.history: list[Message] = []
        self._reset_history()

    def _reset_history(self) -> None:
        """Begin a thread: one system message carrying the whole bootstrap."""
        self.history = [
            Message(role="system", content=build_system_prompt(
                self.project,
                build_style=self.build_style,
                memory=self._memory_block(),
                asset_context=self._asset_block(),
            ))
        ]

    def use_provider(self, provider: ModelProvider) -> None:
        """Change which model this conversation is talking to, keeping the conversation.

        WORKORDER_01 section 4 lets a child switch models; section 38 forbids doing it
        silently, which is the caller's job -- by the time this is called the switch has
        been chosen and, for a cloud model, consented to.

        Three things move with the provider. The context budget, because the new model
        has its own (``MemoryManager.adopt``). The asset block, because what may honestly
        be said about an imported picture depends on whether *this* model can see it --
        which is the Phase 5 capability plumbing doing what it was built for. And the
        project state, which carries both.
        """
        self.provider = provider
        if self.memory is not None:
            self.memory.adopt(provider)
        self.refresh_state()

    def refresh_state(self) -> None:
        """Re-inject the file list and last run result after anything changes."""
        self.history[0] = Message(
            role="system",
            content=build_system_prompt(
                self.project,
                build_style=self.build_style,
                last_run=self.toolbox.last_run,
                memory=self._memory_block(),
                asset_context=self._asset_block(),
            ),
        )

    def _memory_block(self) -> str:
        return self.memory.context_block() if self.memory is not None else ""

    def _asset_block(self) -> str:
        """What the child has imported, and what is honestly known about it.

        Injected, not fetched. Section 18 lists a ``list_assets`` tool; building it would
        repeat the mistake SPIKES.md section 4 measured, so the application states what
        it already knows instead and the tool set stays at four.
        """
        return assets.context_block(
            self.project,
            getattr(self.provider, "info", None),
            attached=self._attached,
        )

    def send(
        self,
        text: str,
        *,
        attachments: Sequence[assets.Asset] = (),
        on_text: Callable[[str], None] | None = None,
    ) -> Turn:
        """One exchange: the child says something, the agent acts, and reports back.

        ``attachments`` are files the child dropped onto this message (WORKORDER_01
        sections 12 and 13). They are already imported into the project by the time they
        arrive here -- what this adds is that *these* are the ones being talked about.
        """
        # Checkpoint whatever state exists before touching anything, so "undo" goes
        # back to what the child had rather than to some earlier assistant turn.
        self._checkpoint(LABEL_BEFORE_CHANGE)

        # "Like we talked about before" is answered from memory, deterministically,
        # before the model sees the message (WORKORDER_01 section 15A, memory retrieval).
        self._attached = tuple(attachments)
        if self.memory is not None:
            self.memory.recall_for(text)
        # Unconditional: a lookup that finds nothing must also clear the previous turn's,
        # or the model keeps being handed an answer to an old question -- and the same is
        # true of an attachment, which must not linger onto the next message.
        self.refresh_state()

        self.history.append(Message(role="user", content=text))
        turn = Turn()
        challenged = False
        corrected = False

        # One budget for this whole turn: the tool loop, both honesty corrections, the
        # repair cycle, a truncation retry and the rollover all spend from it. See
        # agent/budget.py for why the subsystems no longer get separate allowances.
        self._budget = CallBudget()
        turn.usage = self._budget.usage
        self._metered = MeteredProvider(self.provider, self._budget)

        try:
            return self._exchange(turn, text, on_text, challenged, corrected)
        except BudgetExhausted:
            return self._out_of_calls(turn)

    def _out_of_calls(self, turn: Turn) -> Turn:
        """Stop cleanly at the ceiling, with something a child can act on.

        Deliberately not another call: the point of a ceiling is that reaching it costs
        nothing more. The partial work already done is kept and checkpointed by
        ``_finish_turn`` exactly as a successful turn's would be.
        """
        turn.hit_call_limit = True
        turn.text = (
            "That turned into more steps than I can do at once. "
            "Here is where I got to -- tell me what to try next, or ask for something "
            "smaller."
        )
        return self._finish_turn(turn, allow_rollover=False)

    def _exchange(
        self,
        turn: Turn,
        text: str,
        on_text: Callable[[str], None] | None,
        challenged: bool,
        corrected: bool,
    ) -> Turn:
        while True:
            reply = self._generate(on_text, turn=turn)
            self.history.append(
                Message(role="assistant", content=reply.text, tool_calls=reply.tool_calls)
            )
            if reply.text:
                turn.text = reply.text

            if not reply.wants_tool:
                if not challenged and self._claimed_a_change_it_did_not_make(turn, reply.text):
                    challenged = True
                    self._metered.kind = CORRECTION
                    self.history.append(Message(role="user", content=(
                        "You did not actually change any file. Call edit_file now with "
                        "the exact text to replace, or say plainly that you have not "
                        "changed anything yet."
                    )))
                    continue
                if not corrected:
                    invented = self._described_a_file_it_cannot_see(reply.text, text)
                    if invented is not None:
                        corrected = True
                        turn.corrected_invention = True
                        self._metered.kind = CORRECTION
                        self.history.append(Message(role="user", content=(
                            f"You have not seen {invented} and neither has anyone else. "
                            f"Do not say what is in it or what it looks like. Say what you "
                            f"actually did with the file, and tell them plainly that you "
                            f"do not know what the picture shows."
                        )))
                        continue
                return self._finish_turn(turn)

            self._metered.kind = PRIMARY
            should_continue = self._run_tools(reply.tool_calls, turn)
            if not should_continue:
                return self._finish_turn(turn)

    def _finish_turn(self, turn: Turn, *, allow_rollover: bool = True) -> Turn:
        """Save a checkpoint if the assistant changed anything, then update memory."""
        # The attachment belonged to the message just answered. The file stays in the
        # project and keeps appearing in the listing; only "they just added this" goes.
        self._attached = ()
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
        if not turn.text:
            turn.text = self._describe_what_happened(turn)
        if allow_rollover:
            self._roll_over_if_needed(turn)
        return turn

    @staticmethod
    def _describe_what_happened(turn: Turn) -> str:
        """Say what was done when the model did it without saying anything.

        Found by the Anthropic parity run (SPIKES.md section 13). Sonnet 5 repaired a
        broken game correctly -- read, edit, clean run -- and produced no prose at all,
        so ``turn.text`` was empty and the Workbench showed the child **no reply**.
        Their game was fixed and nothing said so.

        Luna narrates and hid this; it is not provider-specific, and the local model can
        do it too. The application knows exactly what happened from the tool results, so
        it says so itself rather than spending a provider call asking the model to
        repeat itself in words.
        """
        changed = sorted({
            path
            for _, result in turn.tool_results
            for path in result.changed_files
        })
        ran = [result for _, result in turn.tool_results if result.run is not None]
        last_run_ok = ran and ran[-1].ok

        if changed and last_run_ok:
            return f"I changed {', '.join(changed)} and ran it. It works."
        if changed:
            return f"I changed {', '.join(changed)}."
        if last_run_ok:
            return "I ran it."
        if ran:
            return "I ran it, and it did not work."
        return ""

    def _roll_over_if_needed(self, turn: Turn) -> None:
        """Hand this thread over to the next one, silently (WORKORDER_01 section 15A).

        This runs only after the turn is complete, so the child has already read the
        reply; nothing here changes what they see. Section 15A step 1 requires exactly
        that ordering, and steps 7 and 8 are the ``_reset_history`` below -- the new
        thread's system prompt is rebuilt with the memory the old one just wrote.

        **A rollover is one more billable call and spends from the same turn budget.**
        If nothing is left it is skipped, not forced: the threshold will still be over
        on the next turn, and closing the project rolls over regardless. Deferring
        costs a slightly longer thread; forcing it would let a turn that already ran
        away spend one more time. That is also what stops repair and rollover
        compounding -- a turn that burned its budget repairing cannot then roll over.
        """
        if self.memory is None or not self.memory.should_roll_over(self.history):
            return
        budget = getattr(self, "_budget", None)
        if budget is not None and budget.exhausted:
            return
        metered = getattr(self, "_metered", None) or self.provider
        if isinstance(metered, MeteredProvider):
            metered.kind = ROLLOVER
        try:
            result = self.memory.roll_over(metered, self.history)
        except BudgetExhausted:
            return
        if result.happened:
            self._reset_history()
            turn.rolled_over = True

    def close(self, *, summarise: bool = True) -> None:
        """End this project's thread. Called when the project closes, not per turn.

        Closing summarises, including on quit. An earlier version skipped the model call
        when quitting, on the reasoning that an application must not pause on Command-Q.
        That traded the wrong thing away: a session long enough for summarising to be
        slow has *already* rolled over, so the transcript left at close is bounded by the
        rollover threshold and is usually far shorter. Quit latency and rollover latency
        are therefore the same unmeasured number, and special-casing quit bought a
        bounded saving at the cost of losing the decisions of every session that never
        crossed the threshold -- which is most short sessions, and exactly the ones
        updating memory at close exists for.

        ``summarise=False`` remains as the lever if that measurement (SPIKES.md section 9)
        comes back badly, and as the way to end a thread without touching the model.
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

    def _described_a_file_it_cannot_see(self, text: str, said: str) -> str | None:
        """Catch the model describing an imported file nobody has looked inside.

        The prompt already forbids this, and SPIKES.md section 10 measured that the
        prompt is not enough: the honesty block took the model from 25% to 50% honest
        and left it answering "does the dragon in my picture have wings?" with "Yes...
        I see them clearly." So the application checks, exactly as it checks for a
        claimed edit that never happened.

        The decision of what counts lives in :func:`assets.invented_description`, and is
        deliberately narrow -- naming the file, and repeating a word the child used, are
        both fine.
        """
        unread = assets.unread_assets(self.project, getattr(self.provider, "info", None))
        return assets.invented_description(text, said, unread)

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

    def _generate(self, on_text: Callable[[str], None] | None, *, turn: Turn | None = None):
        """One provider call, metered, with one retry if the answer came back empty.

        The retry exists because a reasoning model can spend its entire output
        allowance thinking and return a mechanically successful response with nothing
        in it (SPIKES.md section 11). That reaches a child as silence, so it is worth
        one more attempt with more room -- and exactly one, from the shared budget,
        because a model that cannot fit an answer in four times the space will not fit
        it in eight either.
        """
        reply = self._call(on_text, Settings(temperature=0.0), turn=turn)
        return reply

    def _call(self, on_text, settings: Settings, *, turn: Turn | None,
              retried: bool = False):
        provider = getattr(self, "_metered", None) or self.provider
        tools = schemas_for(self.toolbox.allowed)
        try:
            for chunk in provider.chat(self.history, tools=tools, settings=settings):
                if chunk.text and on_text:
                    on_text(chunk.text)
            reply = provider.finish()
        except TruncatedReply:
            if retried:
                # Already given more room once. Stop rather than keep paying.
                raise
            if isinstance(provider, MeteredProvider):
                provider.kind = RECOVERY
            if turn is not None:
                turn.recovered_truncation = True
            roomier = Settings(
                temperature=settings.temperature,
                max_tokens=settings.max_tokens * 4,
                seed=settings.seed,
            )
            return self._call(on_text, roomier, turn=turn, retried=True)

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

        Two ceilings apply, and the tighter one wins. This one is section 28's three
        attempts. The other is the turn's shared call budget, which repair spends from
        like everything else -- so a turn that already used its calls getting here has
        fewer repairs available, or none. That is deliberate: the alternative is each
        subsystem holding its own reserve and the total being nobody's problem.
        """
        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            turn.repair_attempts = attempt
            if isinstance(getattr(self, "_metered", None), MeteredProvider):
                self._metered.kind = REPAIR
            self.history.append(
                Message(
                    role="user",
                    content=(
                        "That failed. Look at the error above, fix the cause by writing "
                        "the corrected file, then run it again."
                    ),
                )
            )
            reply = self._generate(None, turn=turn)
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

        if self._repair_actually_worked(turn):
            return

        turn.gave_up = True
        turn.text = (
            "I tried three times and could not get this working. "
            "Tell me what you want to try next, or we can go back to the last version "
            "that worked."
        )

    def _repair_actually_worked(self, turn: Turn) -> bool:
        """Check the project before declaring failure, if repair changed anything.

        Measured against the real model (SPIKES.md section 13): Luna spent its three
        attempts reading, then being refused an overwrite, then finally making the
        correct ``edit_file`` -- and because nothing ran afterwards, the loop reported
        "I tried three times and could not get this working" about a game that was, by
        then, fixed. Telling a child their working project is broken is worse than the
        original bug.

        This costs **no provider call**: running the project is a local tool. It only
        happens when repair changed something and never got a clean run, so an
        untouched project is not run again for nothing.
        """
        changed = any(result.changed_files for _, result in turn.tool_results)
        if not changed:
            return False
        result = self.toolbox.dispatch("run_project", {})
        turn.tool_results.append(("run_project", result))
        if not result.ok:
            return False
        self.refresh_state()
        turn.text = (
            "That took a few tries, but it works now. "
            "I fixed the problem and ran it to make sure."
        )
        return True


def stream_reply(controller: AgentController, text: str) -> Iterator[str]:
    """Convenience wrapper for callers that want the text as it arrives."""
    pieces: list[str] = []
    controller.send(text, on_text=pieces.append)
    yield from pieces
