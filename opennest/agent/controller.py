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
from opennest.execution import playtest
from opennest.execution.python_runner import RunResult
from opennest.memory.manager import MemoryManager
from opennest.projects import starters as starter_kits
from opennest.projects.manager import Project
from opennest.security.sandbox import visible_files
from opennest.versioning.checkpoint import (
    LABEL_AFTER_CHANGE,
    LABEL_BEFORE_CHANGE,
    VersionHistory,
)

#: WORKORDER_01 section 28: "Maximum automatic repair attempts: 3". Per turn, and shared
#: between a run that crashed and a game that failed its headless test -- one repair
#: budget, for the same reason there is one call budget.
MAX_REPAIR_ATTEMPTS = 3

#: What the child is told when the game still fails its test and the repairs are spent.
#: Each is the measured result in plain words, never a guess at the cause.
_PLAYTEST_GAVE_UP = {
    playtest.CRASHED: "it stopped with an error",
    playtest.NO_PICTURE: "the window stayed empty",
    playtest.CLOSED_ITSELF: "the window closed by itself straight away",
    playtest.FROZEN: "nothing on screen moved, even when I pressed keys",
}

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

#: The verbs a model reaches for when it believes it changed the project, as
#: (past, participle, progressive). Generated into phrases below rather than written
#: out, because the hand-written list this replaced had grown asymmetric: it carried
#: ``i increased`` and not ``i've increased``, and no progressive form at all. Phase
#: 12.1 drove three real Games turns through the interface and the model said
#: **"I've increased asteroid speed to 3.0"** and **"I'm adding image loading for the
#: spaceship"** with every ``edit_file`` refused and the file byte-identical -- both
#: forms the list happened not to hold. SPIKES.md section 21 has the transcripts.
_CHANGE_VERBS = (
    ("changed", "changed", "changing"),
    ("increased", "increased", "increasing"),
    ("decreased", "decreased", "decreasing"),
    ("updated", "updated", "updating"),
    ("added", "added", "adding"),
    ("set", "set", "setting"),
    ("fixed", "fixed", "fixing"),
    ("made", "made", "making"),
    ("replaced", "replaced", "replacing"),
    ("removed", "removed", "removing"),
    ("renamed", "renamed", "renaming"),
    ("created", "created", "creating"),
    ("wrote", "written", "writing"),
)


def _claim_phrases() -> tuple[str, ...]:
    """Past simple, present perfect and present progressive, for each verb.

    Deliberately **not** the future or modal forms. "I'll add a score" is a suggestion,
    and the Games prompt actively asks for one; flagging it would make an honest turn
    look like a lie. What is caught is the model asserting the work is done or underway.
    """
    phrases: list[str] = []
    for past, participle, progressive in _CHANGE_VERBS:
        phrases += [f"i {past}", f"i've {participle}", f"i have {participle}"]
        phrases += [f"i'm {progressive}", f"i am {progressive}"]
    return tuple(phrases)


#: Phrases a model uses when it believes it edited something. Used to catch the failure
#: above deterministically rather than trusting the prompt to have fixed it.
_CLAIMED_CHANGE = _claim_phrases()

#: ...and phrases that plainly say it did not. A reply holding one of these is not a
#: completion claim whatever else it says, which matters for two reasons. It is exactly
#: what the correction below asks the model to produce -- "say plainly that you have not
#: changed anything yet" -- so treating a compliant answer as a fresh lie would punish
#: the model for doing the right thing. And it keeps an honest admission that happens to
#: contain a claim verb ("I haven't changed anything -- I made a mistake reading the
#: file") on the right side of the line.
_DENIED_CHANGE = (
    "haven't changed", "have not changed", "didn't change", "did not change",
    "haven't edited", "have not edited", "didn't edit", "did not edit",
    "nothing changed", "nothing has changed", "nothing was changed",
    "nothing was saved", "no changes were made", "couldn't change",
    "could not change", "wasn't able to change", "was not able to change",
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
    #: Every headless test of the game this turn, in order. Empty when nothing changed or
    #: the profile has no test. For tests and for measuring the loop (SPIKES.md
    #: section 24).
    playtests: list[playtest.Playtest] = field(default_factory=list)


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


def _starter_facts(project: Project) -> list[str]:
    """What foundation this project was built on, when there is one recorded.

    Section 13 of the Phase 11 work order: Gary should not ask "are you using HTML?"
    about a project Open Nest knows began from the Basic Website kit. Deterministic
    application knowledge, injected like the file list rather than guessed from
    filenames -- which is the same argument SPIKES.md section 4 makes about tools.

    Silence when nothing is recorded, and that covers two different cases on purpose: a
    project started empty, and a project made before Phase 11 whose files might be a
    shipped template or might by now be entirely the child's. Saying "started empty"
    about the second would be asserting something nobody measured.
    """
    starter_id = project.manifest.starter_id
    if not starter_id:
        return []
    try:
        starter = starter_kits.get_starter(starter_id)
    except starter_kits.StarterError:
        # The kit was withdrawn from a later release. The project still has the files,
        # so name what was recorded rather than dropping the fact.
        return [f"Started from the {starter_id} starter."]
    line = f"Started from the {starter.name} starter: {starter.description}"
    if project.manifest.starter_version != starter.version:
        return [line]
    return [
        line,
        "Those files are the child's now. Change them, remove them or replace them as "
        "the project needs -- they are a beginning, not something to preserve.",
    ]


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
    ]
    parts.extend(_starter_facts(project))
    parts.append(f"Files in this project (you already know these):\n{listing}")
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
        #: How many of this turn's tool results the last headless test already covers.
        self._tested_through = 0

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
                if reply.dropped_tool_call and not self._changed_anything(turn):
                    # A call the model could not finish -- it ran out of output while
                    # writing it -- so nothing ran and nothing changed. The provider has
                    # already kept the raw protocol off the screen; without this the
                    # child would be told nothing at all, or a half-sentence that came
                    # before the call. Not retried: measured, it was a repetition loop,
                    # and at temperature 0 the same prompt loops the same way.
                    turn.text = self._nothing_changed_text(turn)
                    return self._finish_turn(turn)
                # Checked against ``turn.text`` -- what the child will actually be told
                # -- and not against ``reply.text``. The two differ whenever a reply
                # comes back empty, because the assignment above only overwrites on
                # non-empty text, and that is not a corner case: it is how the Phase
                # 12.1 verification walk still leaked step 22's claim after the
                # correction was already in place. The model answered the pushback with
                # nothing at all, ``reply.text`` was "", the check saw no claim, and the
                # *previous* reply's "I replaced the old player movement" went to the
                # child unexamined. Gary is answerable for the sentence on screen.
                if self._claimed_a_change_it_did_not_make(turn, turn.text):
                    if not challenged:
                        challenged = True
                        self._metered.kind = CORRECTION
                        self.history.append(Message(role="user", content=(
                            "You did not actually change any file. Call edit_file now "
                            "with the exact text to replace, or say plainly that you "
                            "have not changed anything yet."
                        )))
                        continue
                    # The correction has been spent and the claim came back anyway.
                    # Phase 12.1 measured that reaching a child verbatim: three real
                    # Games turns, every edit_file refused, the file byte-identical, and
                    # Gary announcing a white spaceship and a red asteroid that were
                    # never written. The application knows exactly what happened, so it
                    # says that instead of relaying the claim -- the same move
                    # _describe_what_happened makes when the model says nothing at all,
                    # and it costs no further provider call.
                    turn.text = self._nothing_changed_text(turn)
                    return self._finish_turn(turn)
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
                if self._playtest_wants_repair(turn):
                    continue
                return self._finish_turn(turn)

            self._metered.kind = PRIMARY
            should_continue = self._run_tools(reply.tool_calls, turn)
            if not should_continue:
                # The crash repair has had its go. A game it got running still has to
                # pass the same test as any other.
                if self._playtest_wants_repair(turn):
                    continue
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
    def _changed_anything(turn: Turn) -> bool:
        return any(result.changed_files for _, result in turn.tool_results)

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

        **"It works." is only said for a run that finished.** An interactive run is
        ``ok`` the moment it survives four seconds, and Phase 12.4 measured how little
        that says: a game can launch and do nothing at all (SPIKES.md section 24). So a
        game that launched is described as having started -- which is all a launch
        shows -- and nothing here claims the child's feature was checked.
        """
        changed = sorted({
            path
            for _, result in turn.tool_results
            for path in result.changed_files
        })
        ran = [result for _, result in turn.tool_results if result.run is not None]
        last_run_ok = ran and ran[-1].ok
        only_launched = last_run_ok and ran[-1].run.still_running

        if changed and only_launched:
            return f"I changed {', '.join(changed)} and started it."
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

        A reply that plainly denies changing anything is never a claim, however it is
        phrased afterwards. That branch is the *permitted* outcome -- the acceptance
        rule asks for a real tool call or a plain "I have not changed it yet", and this
        is what keeps the second one from being mistaken for the first.
        """
        if any(result.changed_files for _, result in turn.tool_results):
            return False
        lowered = (text or "").lower()
        if any(phrase in lowered for phrase in _DENIED_CHANGE):
            return False
        return any(phrase in lowered for phrase in _CLAIMED_CHANGE)

    @staticmethod
    def _nothing_changed_text(turn: Turn) -> str:
        """What the child is told when the model insists on a change that did not happen.

        Composed by the application from the tool results, never by the model, for the
        reason ``_describe_what_happened`` exists: the application knows the answer
        deterministically and asking again costs a provider call and can come back
        wrong a third time.

        It says the one thing that is certainly true -- nothing changed -- and then what
        is blocking, which WORKORDER_01's acceptance direction asks for. Two things it
        deliberately does not do:

        - **It does not quote the refused tool's own message.** That text is written for
          the model ("Read the file again and copy the line you want to change exactly
          as it appears") and putting it in front of a child is instructions meant for
          somebody else.
        - **It does not name a cause it has not checked.** ``edit_file`` refuses for
          four different reasons and ``write_file`` for four more; an earlier draft of
          this said "the text I tried to replace was not in the file", which was the
          measured case and would have been a fresh invention in the other seven. The
          application knows a change was attempted and refused, so that is what it says.

        Brand guide section 9: an error is something unexpected, not a failure, and the
        reply ends with the way forward rather than the fault.
        """
        refused = {
            normalise_tool_name(name)
            for name, result in turn.tool_results
            if not result.ok
        }
        if refused & {"edit_file", "write_file"}:
            return (
                "I haven't changed that yet. My edit didn't match the file cleanly, so "
                "I left it alone. Say it again and I'll take another look."
            )
        if refused:
            return (
                "I haven't changed that yet. What I tried didn't work. "
                "Tell me again what you want different."
            )
        return (
            "I haven't changed anything yet. Tell me again what you want different, or "
            "ask for one small change to start with."
        )

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

        The attempt count is the turn's, not this method's: a game that failed its
        headless test and was sent back for repair has already spent some of the three,
        and a crash that repair then causes gets what is left rather than three more.
        """
        while turn.repair_attempts < MAX_REPAIR_ATTEMPTS:
            turn.repair_attempts += 1
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

    def _playtest_wants_repair(self, turn: Turn) -> bool:
        """Test the game after a change; hand a failure back for repair. True to go on.

        Phase 12.4. ``RunResult.ok`` means only that an interactive game outlived its
        four-second startup, so the crash repair above could never react to a game that
        runs and does nothing -- and that was most of what Phase 12.3 measured. Worse,
        all ten of the games in that sample that *did* crash crashed on their first
        frame, where the existing repair would have caught them, had anything run them:
        the model often ends a turn without calling ``run_project``. So the application
        runs the test itself, whenever the turn has changed something since the last one
        (SPIKES.md section 24).

        What counts as failing, and why the list is short, is in
        :mod:`opennest.execution.playtest`. A failure goes back to the model once per
        attempt as the measured result, and the ordinary tool loop carries the fix; the
        next time the model stops, this tests again. Three things bound it:

        - **The turn's repair attempts**, shared with the crash repair: three in all.
        - **The turn's call budget**, which every attempt spends from like everything
          else, so this can never be the thing that runs a turn away.
        - **Unchanged code is never tested twice.** An answer that changes no file has
          fixed nothing, and a second run would only say so again. It still spends an
          attempt, and the model is pulled up rather than let off: measured, handed the
          exact traceback, it replied *"I added the import for random at the top of the
          file"* and called no tool -- the Phase 12.1 fault, which the claim guard cannot
          see here because the turn changed a file earlier on.

        Whichever ends it, the child is told what the test saw, in the application's
        words -- the model's own reply will usually be describing a working game.
        """
        if turn.gave_up:
            return False
        fresh = turn.tool_results[self._tested_through:]
        if not any(result.changed_files for _, result in fresh):
            last = turn.playtests[-1] if turn.playtests else None
            if last is None or not last.failed:
                return False
            return self._send_back(turn, last, last.reminder())

        self._tested_through = len(turn.tool_results)
        result = self.toolbox.playtest()
        if result is None:
            return False
        turn.playtests.append(result)
        if not result.failed:
            return False
        return self._send_back(turn, result, result.feedback())

    def _send_back(self, turn: Turn, result: playtest.Playtest, message: str) -> bool:
        """Spend one repair attempt on ``message``, or give up if none are left."""
        if turn.repair_attempts >= MAX_REPAIR_ATTEMPTS:
            self._gave_up_on_playtest(turn, result)
            return False
        turn.repair_attempts += 1
        self._metered.kind = REPAIR
        self.history.append(Message(role="user", content=message))
        return True

    @staticmethod
    def _gave_up_on_playtest(turn: Turn, result: playtest.Playtest) -> None:
        """Stop, and say what the test saw rather than what the model hoped.

        Same shape as the crash repair's giving up, and it replaces the model's text for
        the same reason ``_nothing_changed_text`` does: the application knows the game
        failed its test, and the reply it would otherwise relay is usually announcing a
        game that works. Only the measured result is named, never a cause.
        """
        turn.gave_up = True
        turn.text = (
            f"I made the change, but when I tested the game "
            f"{_PLAYTEST_GAVE_UP[result.verdict]}, and I couldn't fix that yet. "
            f"Tell me what you want to try next, or we can go back to the last version "
            f"that worked."
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
        if result.run is not None and result.run.still_running:
            # A game that got past its startup: all that proves is that it starts, and
            # the headless playtest that follows is what says any more (Phase 12.4).
            turn.text = (
                "That took a few tries, but it starts now. "
                "I changed it and started it again to check."
            )
        else:
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
