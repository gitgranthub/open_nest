"""From a request to a route: a recipe, guidance for Gary, or Gary as he always was.

This is the only place the classifier's numbers are turned into a decision, and the
only place the thresholds live. They were **not chosen before measuring**: the classifier
was run against the Phase 12 requests and an independent set first, with every score
logged, and these values come from those distributions (SPIKES.md section 25).

The escape hatch is the default. Every way this can go wrong -- no model that can
score, a score below threshold, "other", a project that is not the recipe's shape, a
detail the child did not give, an edit the Toolbox refused, a check that failed --
ends in the same place: Gary takes the turn, exactly as before, with the recipe's
guidance when there is one worth giving.
"""

from __future__ import annotations

import re
import string
import time
import zlib
from dataclasses import dataclass, field

from opennest.agent.tools import Step, Toolbox, ToolResult
from opennest.ai.provider import ToolCall
from opennest.fastpath.classifier import OTHER, Classification, IntentClassifier, Option
from opennest.fastpath.executor import RecipeExecutor
from opennest.fastpath.kinds import (
    AlreadyDone,
    Context,
    NeedsAnswer,
    NotApplicable,
    family_for,
    kind_for,
)
from opennest.fastpath.registry import Recipe, RecipeRegistry, guide_for
from opennest.fastpath.verifier import RecipeVerifier

RECIPE = "recipe"
GUIDE = "guide"
NORMAL = "normal"
#: Several separate requests in one message: ``handle`` decides and makes each one.
COMPOUND = "compound"

#: A recipe runs by itself only when the winner holds in **every** ordering and keeps at
#: least this much of the offered mass on average. Measured, not chosen: on both label
#: sets the outcome is flat from 0.8 to 0.99 (one extra wrong route at 0.8), because the
#: agreement requirement and the gate do most of the work (SPIKES.md section 25E).
RECIPE_MIN_SCORE = 0.90
RECIPE_MIN_AGREEMENT = 1.0
#: Below the recipe bar but still the clear favourite: Gary gets the recipe as guidance.
GUIDE_MIN_SCORE = 0.60

#: The intent question is asked in this many option orderings; detail questions in two.
INTENT_ORDERINGS = 3
SLOT_ORDERINGS = 2

#: Before anything is handled or guided, one more closed question: is this one change?
#: Measured in SPIKES.md section 25: asked only "which change is it?", the model answered
#: confidently for messages that were several changes at once ("blink 20 times, use pin
#: 23 and add a buzzer" became just the 20 blinks), a question ("what does empty cells
#: mean?") or a mood. A four-way "what kind of message is this?" was badly biased by
#: where each answer sat and let through 15 of 67 correct requests; blocking questions
#: ("is it several?") drew a yes for nearly everything. This yes/no, asked in both
#: orders, let 43 of 67 through and stopped 13 of 18 of the confident wrong ones.
SHAPE_QUESTION = ("Does this message ask for exactly one specific change to the project, "
                  "and nothing else?")
SHAPE_OPTIONS = (Option("one", "yes"), Option("no", "no"))
SHAPE_MIN_SCORE = 0.8

#: A tweak -- one number, one colour, one title -- gets a second chance at the gate, asked
#: about the intent itself. A misfired tweak changes one value, is checked, and is one
#: Undo away; a misfired addition puts new code in the child's file, so additions keep
#: the strict gate alone. Measured in SPIKES.md section 25 on both label sets: +4 correct
#: routes each ("my guy moves like a snail can he go quicker", "let me use wasd too"),
#: +1 partial each (a message that also asked a question got only its tweak).
TWEAK_OPS = frozenset({
    "set_number", "set_colour", "set_caption", "controls", "thing_look", "set_heading",
    "change_font_size", "blink_timing", "blink_count", "led_pin",
})
TWEAK_QUESTION = "Is this message asking for exactly this, and nothing more: {describe}?"

#: A whole-game recipe skips that gate -- "make a game where you dodge asteroids" is
#: several parts by nature, and the gate stopped both of Phase 12's whole-game asks with
#: the intent certain (1.00 in every ordering). It must be near-certain instead: the one
#: multi-part neighbour measured ("add some walls, put music in, and change the name")
#: scored 0.94. Tuned on the first label set; the held-out set has no whole-game ask
#: that should become a recipe, so this rule is the least tested one here.
WHOLE_MIN_SCORE = 0.99

#: When Gary takes a message the classifier did recognise -- it was more than one change,
#: or a whole game it was not sure of -- the recipe's pattern goes with the project facts.
#: Never for a veto ("the windiest day"), "other", or an intent it was not confident of.
_PATTERN_REASONS = frozenset({"not one single change", "a whole-game ask it is not certain of"})

#: A compound request the gate rightly calls two things, where one of the two is only
#: "graph this": nothing a recipe would have to decide. "Graph this and tell me what
#: changed the most" is the Phase 12 walk's own step 33 and its one failure (SPIKES.md
#: section 25H). When the *other* part, decided on its own (``_covered_compound``), goes
#: to a recipe that itself draws and saves a chart, that recipe answers both parts.
#: Nothing else is composed: every other compound still goes to Gary.
_BARE_CHART = re.compile(
    r"^(?:(?:can|could) you\s+|please\s+|pls\s+)?"
    r"(?:(?:graph|chart|plot|draw)\s+(?:this|it|that|the data|my data|them)"
    r"|(?:make|draw|show me|give me)\s+(?:a|the)\s+(?:graph|chart|plot))"
    r"(?:\s+(?:for me|please|pls))?[\s.!?]*$",
    re.IGNORECASE,
)
_JOIN = re.compile(r"\s*,?\s*\b(?:and then|and also|and|then|also)\b\s*|\s*;\s*", re.IGNORECASE)


#: "and make the background a sunset orange": a message that only continues the last.
#: Measured: with the message before it shown, the leading "and" had it read as several
#: changes at once ("other"); without the "and", the colour recipe at 1.00. Not "and
#: then", which in both label sets adds a step to what came before.
_CONTINUES = re.compile(r"^\s*(?:(?:oh|ok|okay)\s+)?(?:and also|and|also|plus)\b(?!\s+then\b)"
                        r"[\s,]*", re.IGNORECASE)


def two_parts(request: str) -> tuple[str, str] | None:
    """The two halves of "X and Y", or None when it is not exactly two."""
    pieces = [piece.strip(" ,.;!?") for piece in _JOIN.split(request.strip())]
    pieces = [piece for piece in pieces if piece]
    return (pieces[0], pieces[1]) if len(pieces) == 2 else None


#: Where one request ends and the next begins: "and", "then", "also", a comma or a
#: semicolon, or a numbered list ("1. ... 2. ...").
_PIECES = re.compile(r"\s*[,;]?\s*\b(?:and then|and also|and|then|also|plus)\b\s*|\s*;\s*|"
                     r"\s*,\s*(?=\S)|(?:^|\s)\d+[.)]\s+", re.IGNORECASE)
#: How a request -- or a question -- starts when it stands on its own.
_REQUEST_LEAD = re.compile(
    r"^(?:(?:can|could|will|would)\s+(?:you|u|it|i|we|the|there|my|they)\b|please\b|pls\b|"
    r"i\s+(?:want|need|would like|wanna)\b|let\s+me\b|"
    r"(?:make|add|speed|slow|change|put|give|use|set|turn|move|call|rename|remove|delete|"
    r"take|show|"
    r"draw|graph|plot|chart|tell|work|find|print|stop|keep|write|label|blink|swap|"
    r"replace|colou?r|paint|resize)\b|"
    r"(?:what|why|how|does|do|is|are|where|which|who)\b)", re.IGNORECASE)


def split_parts(request: str) -> list[str] | None:
    """Two or three requests a message is plainly made of, or None.

    Conservative on purpose, and measured on both label sets before it was used: a split
    only counts when *every* piece stands on its own as a request or a question -- it
    starts like one and is more than a word. "make the tagline say i like cats and
    minecraft", "red yellow and green", "sweep back and forth" and "make the asteroids red
    and bigger" stay whole; "make the player green and add a score and can the background
    be purple" becomes three. Of 279 labelled requests, 21 split, and every one of them
    was several requests.
    """
    pieces = [piece.strip(" ,.;:!?") for piece in _PIECES.split(request.strip())]
    pieces = [piece for piece in pieces if piece]

    def standalone(piece: str) -> bool:
        return len(piece.split()) >= 2 and _REQUEST_LEAD.match(piece) is not None

    # "the cars are too slow, speed them up and give me a score": a first piece that only
    # says what is wrong belongs to the request after it. Only at the start -- a fragment
    # later on ("... and minecraft", "... and forth") still means it is not several
    # requests. Measured: no labelled request splits differently for it.
    if len(pieces) >= 3 and not standalone(pieces[0]) and standalone(pieces[1]):
        pieces = [f"{pieces[0]}, {pieces[1]}", *pieces[2:]]
        leading = True
    else:
        leading = False
    if not 2 <= len(pieces) <= 3:
        return None
    first = pieces[0].split(", ", 1)[1] if leading else pieces[0]
    if standalone(first) and all(standalone(piece) for piece in pieces[1:]):
        return pieces
    return None


@dataclass
class Decision:
    route: str
    reason: str
    recipe: Recipe | None = None
    classification: Classification | None = None
    #: When a two-part message was taken by one recipe: the part it covered, and the
    #: part that was decided on its own.
    compound: dict | None = None
    #: For a COMPOUND decision: the separate requests, in the order they were made.
    parts: tuple[str, ...] = ()


@dataclass
class FastPathResult:
    """What the Fast Path did with one request. The controller acts on it."""

    route: str
    #: Everything that happened, for the Turn and the benchmark. Never shown to a child.
    record: dict = field(default_factory=dict)
    #: The edits a recipe made, as tool calls -- empty unless the recipe ran.
    calls: list[tuple[ToolCall, ToolResult]] = field(default_factory=list)
    #: Gary's words to the child, when the recipe handled the request.
    text: str = ""
    #: Guidance for Gary's system prompt this turn, when Gary is taking it.
    guidance: str = ""
    #: When a recipe handled the request: what Gary is told on the *next* turn, so a
    #: follow-up he handles builds on what Open Nest just did rather than guessing.
    note: str = ""
    playtests: list = field(default_factory=list)
    #: When a message was several requests and only some were made by recipes: the
    #: rest, for Gary to do in the same turn. Empty otherwise.
    remaining: tuple[str, ...] = ()

    @property
    def handled(self) -> bool:
        return self.route == RECIPE


def _yes(answer: Classification) -> bool:
    return answer.name == "one" and answer.agreement >= 1.0 and answer.score >= SHAPE_MIN_SCORE


def scorer_of(provider):
    """The provider's closed-question scorer, or None. Probed by attribute, then by use.

    Only a local model offers one today: neither cloud service returns the next-token
    distribution this needs (SPIKES.md section 25). So a cloud Gary gets no classifier
    unless a local one is supplied separately -- which the caller can do, and which is
    open decision D13.
    """
    method = getattr(provider, "score_choices", None)
    return method if callable(method) else None


class FastPathRouter:
    """Classifies a request, and runs the recipe when it is safe to."""

    def __init__(
        self,
        registry: RecipeRegistry | None = None,
        *,
        recipe_min_score: float = RECIPE_MIN_SCORE,
        guide_min_score: float = GUIDE_MIN_SCORE,
        classifier_provider=None,
    ) -> None:
        self.registry = registry or RecipeRegistry()
        self.recipe_min_score = recipe_min_score
        self.guide_min_score = guide_min_score
        #: A provider to classify with regardless of which model Gary is. None means
        #: "classify with Gary's own model, if it can" -- the default and the measured
        #: configuration.
        self.classifier_provider = classifier_provider
        self.executor = RecipeExecutor()
        self.verifier = RecipeVerifier()
        #: The last "is this one change?" answer, for the record.
        self.last_shape = None

    # -- deciding ------------------------------------------------------------

    def decide(self, profile: str | None, request: str, scorer, *,
               previous: str | None = None, about: str = "",
               attached_image: bool = False, compose: bool = True,
               part: bool = False) -> Decision:
        if profile is None:
            return Decision(NORMAL, "no recipes for this kind of project")
        recipes = self.registry.for_profile(profile)
        if recipes is None or kind_for(profile) is None:
            return Decision(NORMAL, "no recipes for this kind of project")
        if scorer is None:
            return Decision(NORMAL, "no model here can score a closed question")
        request = _CONTINUES.sub("", request, count=1) or request
        parts = tuple(split_parts(request) or ()) if compose else ()
        if attached_image:
            # A picture came with this message, so this message is about the picture. The
            # one before it is not: measured, with "i want a game where i'm flying around
            # and have to dodge cars" before it, "use this as my eagle" split between the
            # player's look and a whole dodging game, and went to Gary; without it, all
            # four natural phrasings measured were the player's look, certain.
            previous = None

        def normal(reason: str, classification=None) -> Decision:
            # A message the whole-message rules would hand to Gary may still be several
            # requests Open Nest can make one by one.
            if parts:
                return Decision(COMPOUND, "several requests in one message",
                                classification=classification, parts=parts)
            return Decision(NORMAL, reason, classification=classification)

        classifier = IntentClassifier(scorer, orderings=INTENT_ORDERINGS)
        try:
            classification = classifier.classify(
                recipes.building, recipes.options(), request, previous=previous,
                about=about,
            )
        except Exception as exc:  # noqa: BLE001 - a classifier failure is not the child's
            return Decision(NORMAL, f"the classifier could not run: {exc}")
        if classification.name == OTHER:
            return normal("not one of the known kinds of change", classification)
        if classification.score < self.guide_min_score:
            return normal("not confident", classification)
        recipe = recipes.for_intent(classification.name)
        if recipe is not None and not recipe.mentioned(request, previous):
            # A veto the recipe carries for a confusion measured on it -- "the windiest
            # day" read as "what changed the most". Gary, with no misleading guidance.
            return normal("the message does not say what that recipe is about",
                          classification)
        if parts:
            # Several requests that each stand on their own: each is decided by itself
            # (``run_parts``), rather than the one-change gate guessing about the whole --
            # a gate that said "one" would have one recipe drop the rest, and the tweak's
            # second question is how "make it blink faster also what does BCM mean and
            # can i have a second light" got only its faster blink (SPIKES.md 25E). A
            # "graph this and ..." that one charting recipe answers is checked first,
            # and a whole game or a picture is decided as a part like anything else.
            covered = self._covered_compound(profile, request, scorer,
                                             previous=previous, about=about)
            if covered is not None:
                return covered
            return normal("several requests in one message", classification)
        picture = self._picture_capability(recipes, classification) if attached_image \
            else None
        if picture is not None:
            # Measured in SPIKES.md section 25: both gate questions said no to "Use this
            # picture for my spaceship" with the picture attached, and Gary then failed
            # it -- eleven refused edits. The attachment answers what the gate guesses.
            return Decision(RECIPE, "confident, and the picture is attached", picture,
                            classification)
        if recipe is not None and recipe.whole:
            if (classification.agreement >= RECIPE_MIN_AGREEMENT
                    and classification.score >= WHOLE_MIN_SCORE):
                return Decision(RECIPE, "confident, whole game", recipe, classification)
            return normal("a whole-game ask it is not certain of", classification)
        try:
            shape = IntentClassifier(scorer, orderings=SLOT_ORDERINGS).choose(
                SHAPE_QUESTION, list(SHAPE_OPTIONS), request, previous=previous, about=about,
                keep_last=False,
            )
        except Exception as exc:  # noqa: BLE001
            return Decision(NORMAL, f"the classifier could not run: {exc}",
                            classification=classification)
        self.last_shape = shape
        if not _yes(shape) and compose:
            covered = self._covered_compound(profile, request, scorer,
                                             previous=previous, about=about)
            if covered is not None:
                return covered
        # A tweak -- and one part of a "graph this and ..." message, which the split has
        # already made a single clause -- gets the question about the recipe itself.
        if not _yes(shape) and recipe is not None and (recipe.op in TWEAK_OPS or part):
            try:
                shape = IntentClassifier(scorer, orderings=SLOT_ORDERINGS).choose(
                    TWEAK_QUESTION.format(describe=recipe.describe), list(SHAPE_OPTIONS),
                    request, previous=previous, about=about, keep_last=False,
                )
            except Exception as exc:  # noqa: BLE001
                return Decision(NORMAL, f"the classifier could not run: {exc}",
                                classification=classification)
            self.last_shape = shape
        if not _yes(shape):
            return Decision(NORMAL, "not one single change",
                            classification=classification)
        if (classification.agreement >= RECIPE_MIN_AGREEMENT
                and classification.score >= self.recipe_min_score):
            return Decision(RECIPE, "confident", recipe, classification)
        if classification.score >= self.guide_min_score:
            return Decision(GUIDE, "likely, not certain", recipe, classification)
        return Decision(NORMAL, "not confident", classification=classification)

    @staticmethod
    def _picture_capability(recipes, classification) -> Recipe | None:
        """The picture recipe, when a picture came with the message and the model is sure
        this is about the player's look -- whichever of the options it used to say so.

        Measured on the real model with a picture attached: "use this as my eagle" was
        *the player's look* at 1.00, "make my eagle look like this" *use a picture for
        the player* at 0.97 -- the same capability, split between two options, and each
        went to Gary. With a picture attached they are one thing: the picture is the new
        look. What "eagle", "character" or "guy" means is the classifier's to resolve
        against the project; no noun is listed here. Every ordering must still have
        chosen one of them, with near-certainty between them.
        """
        picture = next((r for r in recipes.recipes if r.attachment_confirms), None)
        if picture is None:
            return None
        same = {picture.intent, *picture.attachment_covers}
        share = sum(classification.share_of(intent) for intent in same)
        steady = bool(classification.winners) and all(w in same for w in
                                                      classification.winners)
        if classification.name in same and steady and share >= WHOLE_MIN_SCORE:
            return picture
        return None

    def _covered_compound(self, profile, request, scorer, *, previous, about):
        """A "graph this and <one change>" message a single charting recipe answers.

        The other part is decided as a message of its own would be -- intent, every
        threshold, the recipe's own words -- with one difference: the general "exactly
        one change?" gate is followed, as for a tweak, by the question about the recipe
        itself. Measured on the real model: the general gate says no even to "tell me
        what changed the most" alone, because it is a question and not a change; the
        recipe question says yes to it and no to "find the windiest day". Only a RECIPE
        route to a recipe whose own checks include writing a chart is accepted.
        Anything less is None, and the message goes to Gary as it did before.
        """
        parts = two_parts(request)
        if parts is None:
            return None
        bare = [part for part in parts if _BARE_CHART.match(part)]
        if len(bare) != 1:
            return None
        other = parts[1] if bare[0] == parts[0] else parts[0]
        shape = self.last_shape
        decision = self.decide(profile, other, scorer, previous=previous, about=about,
                               compose=False, part=True)
        part_shape, self.last_shape = self.last_shape, shape
        recipe = decision.recipe
        if (decision.route != RECIPE or recipe is None or not recipe.deterministic
                or "chart_written" not in recipe.verify):
            return None
        return Decision(RECIPE, "two parts, and one recipe draws the chart the other asks for",
                        recipe, decision.classification,
                        compound={"covered": bare[0], "decided": other,
                                  "shape": part_shape.as_record() if part_shape else None})

    # -- acting --------------------------------------------------------------

    def handle(
        self,
        project,
        toolbox: Toolbox,
        request: str,
        *,
        provider,
        previous: str | None = None,
        attachments: tuple = (),
        build_style: str = "build",
    ) -> FastPathResult:
        """Everything the Fast Path does with one request, start to finish."""
        started = time.monotonic()
        # Which recipes apply comes from the project: its type, or -- for a Blank one --
        # what its files turn out to be. Only that family is put to the classifier.
        family, why = family_for(project)
        scorer = scorer_of(self.classifier_provider or provider)
        kind = kind_for(family)
        facts = kind.facts(project, attachments) if kind is not None else None
        brief = getattr(kind, "brief", None)
        about = brief(facts) if brief is not None and facts is not None else ""
        self.last_shape = None
        attached_image = any(getattr(a, "kind", "") == "image" for a in attachments)
        if family is None:
            decision = Decision(NORMAL, why)
        else:
            decision = self.decide(family, request, scorer, previous=previous, about=about,
                                   attached_image=attached_image)
        record: dict = {"route": decision.route, "reason": decision.reason}
        if family is not None and family != project.profile.id:
            record["family"] = family
            record["family_reason"] = why
        if decision.compound is not None:
            record["compound"] = decision.compound
        if decision.classification is not None:
            record.update(decision.classification.as_record())
        if self.last_shape is not None:
            record["shape"] = self.last_shape.as_record()
        if decision.recipe is not None:
            record["recipe"] = decision.recipe.id
        result = FastPathResult(route=decision.route, record=record)

        if decision.route == COMPOUND:
            return self.run_parts(project, toolbox, request, decision.parts,
                                  provider=provider, previous=previous,
                                  attachments=attachments, build_style=build_style,
                                  result=result, started=started)

        if decision.route == NORMAL:
            # Gary is writing it himself -- still with what Open Nest knows about this
            # project, and a recipe's pattern when one was likely but not one change.
            if kind is not None and facts is not None:
                pattern = None
                if decision.reason in _PATTERN_REASONS and decision.classification:
                    pattern = self.registry.for_profile(family).for_intent(
                        decision.classification.name)
                result.guidance = self._context(kind, facts, project, pattern)
                record["context"] = "facts" + (f"+{pattern.id}" if pattern else "")
            record["seconds"] = round(time.monotonic() - started, 3)
            return result

        recipe = decision.recipe
        slot_questions: list[dict] = []

        def choose(question: str, options: list[Option]):
            answer = IntentClassifier(scorer, orderings=SLOT_ORDERINGS).choose(
                question, options, request, previous=previous, about=about,
            )
            slot_questions.append({"question": question, **answer.as_record()})
            return answer

        if decision.route == RECIPE and recipe.deterministic and not kind.verifiable(project):
            # The recipe knows how, but this project cannot run the check it is
            # verified by -- a game in a Blank project has no headless test. An edit
            # nobody can check is Gary's to make, with the recipe as his guidance.
            record["route"] = result.route = GUIDE
            record["stepped_aside"] = "this project cannot run the check that change needs"
        elif decision.route == RECIPE and recipe.deterministic:
            toolbox.report(Step("recipe", "using a known way to do this"))
            outcome = self._run_recipe(recipe, kind, project, toolbox, facts, request,
                                       choose, attachments, previous, build_style, result)
            record["slot_questions"] = slot_questions
            if outcome is None:
                record["seconds"] = round(time.monotonic() - started, 3)
                return result
            # Fell through: the recipe stepped aside. Gary takes it, with guidance.
            record["route"] = result.route = GUIDE
            record["stepped_aside"] = outcome
        elif decision.route == RECIPE:
            record["route"] = result.route = GUIDE
            record["stepped_aside"] = "guide-only recipe"

        result.guidance = self._guidance(recipe, kind, facts, record.get("stepped_aside"),
                                         record.get("needs_answer"), project.profile.tools)
        record["seconds"] = round(time.monotonic() - started, 3)
        return result

    def run_parts(self, project, toolbox: Toolbox, request: str, parts, *, provider,
                  previous: str | None = None, attachments: tuple = (),
                  build_style: str = "build", result: FastPathResult | None = None,
                  started: float | None = None) -> FastPathResult:
        """Make each of several requests that a recipe can make, in order; leave the rest.

        Each part is decided as a message of its own would be -- the classifier, the
        one-change gate, every threshold -- against the project *as the parts before it
        left it*, so "add an enemy and make it faster" can find the enemy. A part is made
        by a recipe only when it is a confident single change to a deterministic recipe
        this project can check. A whole game only ever as the first part, and only when
        the child said "game" (the recipe's ``needs_words``): measured on the label sets,
        "add some walls i have to get around" was read as "make a dodging game" at 1.00.
        Everything else is left, in order, for Gary to do in the same turn with the
        guidance the parts produced. Each made part was verified on its own; one that
        fails is rolled back and left too.

        Used for a message the child split themselves ("make the cars faster and add a
        score") and for the steps a plan split a too-big request into.
        """
        started = time.monotonic() if started is None else started
        family, _ = family_for(project)
        kind = kind_for(family)
        scorer = scorer_of(self.classifier_provider or provider)
        result = result or FastPathResult(route=NORMAL, record={})
        record = result.record
        record["parts"] = []
        done: list[str] = []
        remaining: list[str] = []
        guidance: list[str] = []
        before = previous
        for number, part in enumerate(parts):
            facts = kind.facts(project, attachments) if kind is not None else None
            brief = getattr(kind, "brief", None)
            about = brief(facts) if brief is not None and facts is not None else ""
            self.last_shape = None
            decision = (self.decide(family, part, scorer, previous=before, about=about,
                                    compose=False, attached_image=any(
                                        getattr(a, "kind", "") == "image" for a in attachments))
                        if kind is not None else Decision(NORMAL, "no recipes here"))
            entry = {"part": part, "route": decision.route, "reason": decision.reason}
            if decision.classification is not None:
                entry.update(decision.classification.as_record())
            record["parts"].append(entry)
            recipe = decision.recipe
            # A whole game can only be where a message starts ("make a game where you
            # dodge asteroids and add a score"); built later, it would be built over the
            # parts before it.
            if (decision.route == RECIPE and recipe is not None and recipe.deterministic
                    and (not recipe.whole or number == 0) and kind.verifiable(project)):
                entry["recipe"] = recipe.id
                made = FastPathResult(route=RECIPE, record={})
                questions: list[dict] = []
                toolbox.report(Step("recipe", "using a known way to do this"))
                outcome = self._run_recipe(
                    recipe, kind, project, toolbox, facts, part,
                    self._chooser(scorer, part, before, about, questions),
                    attachments, before, build_style, made)
                entry["result"] = made.record.get("result")
                if outcome is None:
                    done.append(made.text)
                    result.calls += made.calls
                    result.playtests += made.playtests
                    entry["changed_files"] = made.record.get("changed_files")
                    before = part
                    continue
                entry["stepped_aside"] = outcome
            remaining.append(part)
            if recipe is not None and kind is not None:
                guidance.append(self._guidance(recipe, kind, facts, entry.get("stepped_aside"),
                                               made.record.get("needs_answer")
                                               if entry.get("recipe") else None,
                                               project.profile.tools))
            before = part

        record["remaining"] = list(remaining)
        record["seconds"] = round(time.monotonic() - started, 3)
        from_recipes = any(guidance)
        if kind is not None and remaining:
            # Read again: a recipe part may have moved every line Gary is about to edit.
            now = kind.facts(project, attachments)
            guidance.insert(0, self._context(kind, now, project))
        result.guidance = "\n\n".join(dict.fromkeys(g for g in guidance if g))
        if not done:
            # Nothing a recipe could make: Gary takes the whole message, as before.
            record["route"] = result.route = GUIDE if from_recipes else NORMAL
            record["reason"] = "several requests, none of them one a recipe makes"
            return result
        record["route"] = result.route = RECIPE
        record["result"] = "success" if not remaining else "partial"
        result.text = "\n\n".join(done)
        result.remaining = tuple(remaining)
        made_ids = [entry["recipe"] for entry in record["parts"]
                    if entry.get("result") == "success"]
        result.note = (
            "WHAT OPEN NEST JUST DID\n"
            f"Their last message was several requests. Open Nest made {len(done)} of them "
            f"itself with known recipes ({', '.join(made_ids)}), each checked, and the "
            "edits and what you told them are in the conversation above. Work from the "
            "code as it is in the files now."
        )
        return result

    def _chooser(self, scorer, text, previous, about, questions):
        def choose(question: str, options: list[Option]):
            answer = IntentClassifier(scorer, orderings=SLOT_ORDERINGS).choose(
                question, options, text, previous=previous, about=about,
            )
            questions.append({"question": question, **answer.as_record()})
            return answer
        return choose

    def _run_recipe(self, recipe, kind, project, toolbox, facts, request, choose,
                    attachments, previous, build_style, result) -> str | None:
        """Run a deterministic recipe. None when it succeeded; else why it stepped aside."""
        record = result.record
        missing = facts.missing(recipe.requires)
        if missing:
            record["result"] = "not_applicable"
            return f"the project does not have: {', '.join(missing)}"
        context = Context(project=project, facts=facts, request=request,
                          params=recipe.params, choose=choose,
                          attachments=tuple(attachments), previous=previous)
        try:
            change = kind.OPS[recipe.op](context)
        except AlreadyDone as exc:
            # Nothing to change, and the file says so. Open Nest answers; nothing is
            # edited, nothing is checked, and Gary is not handed code that is fine.
            record["result"] = "already"
            result.text = str(exc)
            result.note = (
                "WHAT OPEN NEST JUST DID\n"
                f"For their last message, Open Nest checked the project ({recipe.id}) and "
                f"told them it was already that way: {exc} Nothing was changed."
            )
            return None
        except NeedsAnswer as exc:
            record["result"] = "needs_answer"
            record["needs_answer"] = str(exc)
            return str(exc)
        except NotApplicable as exc:
            record["result"] = "not_applicable"
            return str(exc)
        try:
            applied = self.executor.apply(change, toolbox)
        except NotApplicable as exc:
            record["result"] = "refused"
            return str(exc)

        try:
            verification = self.verifier.verify(recipe, kind, project, toolbox,
                                                change.expect)
        except BaseException:
            # Nothing unverified is left in the child's project, whatever went wrong.
            self.executor.rollback(applied, toolbox)
            raise
        record["verification"] = verification.as_record()
        test = verification.evidence.get("playtest")
        if test is not None:
            result.playtests.append(test)
        if verification.failed:
            self.executor.rollback(applied, toolbox)
            record["result"] = "verification_failed"
            record["rolled_back"] = True
            return "the change did not pass its checks, so it was undone"

        record["result"] = "success"
        record["changed_files"] = list(applied.changed_files)
        # A check that ran the project did it through the Toolbox, as a tool call. It
        # belongs in the history beside the edits, so Gary knows it was run.
        result.calls = applied.calls + list(verification.evidence.get("calls", []))
        result.text = self._report(recipe, kind, change, verification, build_style,
                                   project=project, before=applied.originals)
        passed = [c.name for c in verification.checks if c.status == "pass"]
        result.note = (
            "WHAT OPEN NEST JUST DID\n"
            f"For their last message, Open Nest made the change itself with a known recipe "
            f"({recipe.id}) and checked it"
            + (f" ({', '.join(passed)} passed)" if passed else "")
            + f". It changed {', '.join(applied.changed_files) or 'no files'}; the edits "
            "and what you told them are in the conversation above. If they now want it "
            "different, work from the code as it is in the file now -- it is theirs to change."
        )
        return None

    @staticmethod
    def _report(recipe, kind, change, verification, build_style, *, project=None,
                before: dict | None = None) -> str:
        """Gary's reply: what was measured to have changed, and what was checked.

        Which phrasing is used is seeded by the project and the file as it was, so the
        same change to the same file always reads the same -- reproducible for a test --
        while the next change, or another child's project, reads differently.
        """
        values = {key: str(value) for key, value in change.values.items()}
        seed = zlib.crc32("|".join([getattr(project, "name", ""), recipe.id,
                                    *sorted(v or "" for v in (before or {}).values())]
                                   ).encode("utf-8"))
        phrasing = recipe.report[seed % len(recipe.report)] if recipe.report else ""
        # A value that is empty or ends in a space must not leave a gap in the sentence.
        said = " ".join(string.Template(phrasing).safe_substitute(values).split())
        # A phrasing may open with a value ("$part is $colour now"): a sentence still starts
        # with a capital, whatever the value was.
        said = said[:1].upper() + said[1:]
        if build_style == "teach" and recipe.teach:
            said += " " + " ".join(string.Template(recipe.teach).safe_substitute(values).split())
        confirm = getattr(kind, "confirmation", None)
        sentence = confirm(verification, project) if confirm is not None else ""
        if not sentence:
            return said
        # What a run printed is quoted as it was printed, line breaks and all.
        return f"{said}\n\n{sentence}" if "\n" in sentence else f"{said} {sentence}"

    @staticmethod
    def _context(kind, facts, project, pattern: Recipe | None = None) -> str:
        """What Gary is given when no recipe makes the change: the project, and a pattern.

        The facts -- where things are in the file, what the constants are called -- can
        only help: half of Phase 12.2's refused edits were the model editing code it had
        imagined. A recipe's pattern is added only when the classifier found one likely
        and the gate stopped it for being more than one change, and it is labelled for
        what it is: measured, a recipe's strategy given to a question or a mood misleads.
        """
        where = getattr(kind, "where", None)
        lines = [where(facts) if where is not None else ""]
        checked = getattr(kind, "CHECKED", "")
        if checked and kind.verifiable(project):
            lines.append(f"HOW IT WILL BE CHECKED: {checked}")
        guide = guide_for(pattern, project.profile.tools) if pattern is not None else ""
        if guide.strip():
            lines += ["A PATTERN THIS PROJECT CAN USE -- only if it fits what they asked; if "
                      "they asked a question, answer it and change nothing:",
                      guide.strip()]
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _guidance(recipe, kind, facts, why: str | None, needs_answer: str | None,
                  tools=()) -> str:
        """What Gary is given when he writes the change himself."""
        lines = ["A KNOWN WAY TO DO THIS", guide_for(recipe, tools).strip()]
        if needs_answer:
            lines.append(f"Open Nest did not make this change by itself because "
                         f"{needs_answer}. Ask them before changing anything.")
        where = getattr(kind, "where", None)
        placement = where(facts) if where is not None else ""
        if placement:
            lines += ["", placement]
        return "\n".join(line for line in lines if line is not None)
