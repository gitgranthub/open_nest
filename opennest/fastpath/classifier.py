"""What is the child asking for? A closed question to the model already in memory.

The one fuzzy question the Fast Path has to answer, and the only place it asks the model
anything. Everything else -- what files exist, what the speed constant is called, where
the game loop starts -- Open Nest reads for itself (:mod:`opennest.fastpath.kinds`).

**No generation.** The options are lettered and the model is asked for one letter; the
provider reads its next-token distribution at the point the answer would begin
(``MLXProvider.score_choices``) and nothing is decoded. Measured in SPIKES.md section 25:
~50 ms per question with the fixed part of the prompt cached, and every letter is a
single token that takes essentially all of the model's mass.

**What the score is, and what it is not.** A 4B instruct model is wildly overconfident on
a question like this: the first measurement put 1.000 on the winner for the right answers
*and* for the wrong ones. So the share of one ordering is not a confidence. What did
separate them was **stability** -- ask the same question with the options in a different
order, and a request the model genuinely recognises keeps the same winner while an
ambiguous one moves. So each question is asked in a few fixed orderings, and:

- ``share`` is each option's probability renormalised over the offered letters, then
  averaged across the orderings. A normalised score, **not a calibrated probability** --
  it is named for what it is.
- ``agreement`` is the fraction of orderings whose winner was the overall winner.
- ``margin`` is the gap, in nats, between the first and second choice in the first
  ordering.

The router decides what those numbers mean (:mod:`opennest.fastpath.router`); this module
only measures them.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from opennest import paths

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: The option every question ends with, so "none of these" is always an answer. It is
#: kept last in every ordering: it is the answer for everything the recipes do not cover,
#: and moving it around would make the fallback compete with position.
OTHER = "other"

#: Signature of the one capability this needs from a provider: log-probabilities, over
#: the whole vocabulary, of each single-token label as the start of the answer.
Scorer = Callable[[str, str, Sequence[str]], list[float]]


@dataclass(frozen=True)
class Option:
    name: str
    description: str


@dataclass(frozen=True)
class Scored:
    name: str
    #: Renormalised over the offered options and averaged over orderings. Not a
    #: probability.
    share: float


@dataclass(frozen=True)
class Classification:
    """One closed question, answered."""

    ranked: tuple[Scored, ...]
    #: Nats between the first and second choice, in the first ordering.
    margin: float
    #: Fraction of orderings whose own winner was ``ranked[0]``.
    agreement: float
    orderings: int
    #: The least total probability the offered letters received in any ordering. Near
    #: 1.0 means the model answered in the format; low means the numbers mean little.
    letter_mass: float
    seconds: float
    #: Each ordering's own winner, by option name, in order.
    winners: tuple[str, ...] = ()

    @property
    def top(self) -> Scored:
        return self.ranked[0]

    @property
    def name(self) -> str:
        return self.ranked[0].name

    @property
    def score(self) -> float:
        return self.ranked[0].share

    def share_of(self, name: str) -> float:
        return next((s.share for s in self.ranked if s.name == name), 0.0)

    def as_record(self) -> dict:
        """For the Turn record and the benchmark log. Never shown to a child."""
        return {
            "intent": self.name,
            "score": round(self.score, 4),
            "margin": round(self.margin, 2),
            "agreement": round(self.agreement, 3),
            "orderings": self.orderings,
            "letter_mass": round(self.letter_mass, 4),
            "runner_up": self.ranked[1].name if len(self.ranked) > 1 else "",
            "ms": round(self.seconds * 1000),
        }


def orderings(count: int, n: int, *, keep_last: bool = True) -> list[list[int]]:
    """``n`` fixed orderings of ``count`` options.

    Deterministic so a classification can be reproduced: the registry order, then its
    reverse, then evens-before-odds. Enough to move every option to a different letter
    at least once without a random seed anyone has to remember.

    ``keep_last`` holds the final option -- "other" -- in place, which is right for the
    intent question. A yes/no question has no fallback to hold still, and with two
    options holding one still would leave nothing to reorder at all.
    """
    head = list(range(count - 1)) if keep_last else list(range(count))
    candidates = [head, head[::-1], head[0::2] + head[1::2], head[1::2] + head[0::2]]
    chosen = []
    for order in candidates:
        if order not in chosen:
            chosen.append(order)
        if len(chosen) == n:
            break
    return [order + [count - 1] for order in chosen] if keep_last else chosen


def _message(request: str, previous: str | None, about: str) -> str:
    """The variable part of a question: what is known, what came before, what was said."""
    lines = []
    if about:
        lines.append(f"About the project: {about.strip()}")
    if previous:
        lines.append(f"Their message before this one: {previous.strip()}")
    lines.append(f"Message: {request.strip()}")
    return "\n".join(lines)


def _template(name: str) -> str:
    return (paths.prompts_dir() / name).read_text(encoding="utf-8").strip()


class IntentClassifier:
    """Asks the loaded model closed questions and reports what the answers are worth."""

    def __init__(self, scorer: Scorer, *, orderings: int = 3) -> None:
        self.scorer = scorer
        self.orderings = orderings

    def classify(
        self,
        building: str,
        options: Sequence[Option],
        request: str,
        *,
        previous: str | None = None,
        about: str = "",
    ) -> Classification:
        """Which kind of change is ``request``? ``options`` must end with ``other``.

        ``about`` is what Open Nest already knows about the project, in a sentence or
        two -- "the player is the orange square; nothing else is in the game yet". It
        goes in the question, not the fixed part of the prompt, so the fixed part stays
        cached. Measured in SPIKES.md section 25: without it the model read "make the
        square go faster" as a request about something other than the player.
        """
        template = _template("fastpath_classify.txt")

        def system(listing: str) -> str:
            return template.replace("{building}", building).replace("{options}", listing)

        return self._ask(system, options, _message(request, previous, about))

    def choose(self, question: str, options: Sequence[Option], request: str, *,
               previous: str | None = None, about: str = "",
               keep_last: bool = True) -> Classification:
        """A closed question about one detail of the request -- a colour, a direction."""
        template = _template("fastpath_choose.txt")

        def system(listing: str) -> str:
            return template.replace("{question}", question).replace("{options}", listing)

        return self._ask(system, options, _message(request, previous, about),
                         keep_last=keep_last)

    def _ask(self, system: Callable[[str], str], options: Sequence[Option],
             user: str, *, keep_last: bool = True) -> Classification:
        if not 2 <= len(options) <= len(LETTERS):
            raise ValueError(f"A closed question needs 2 to {len(LETTERS)} options.")
        started = time.monotonic()
        totals = [0.0] * len(options)
        winners: list[int] = []
        margin = 0.0
        least_mass = 1.0
        runs = orderings(len(options), self.orderings, keep_last=keep_last)
        for run, order in enumerate(runs):
            letters = LETTERS[: len(order)]
            listing = "\n".join(
                f"{letter}. {options[index].description}"
                for letter, index in zip(letters, order)
            )
            logprobs = self.scorer(system(listing), user, list(letters))
            mass = sum(math.exp(value) for value in logprobs)
            least_mass = min(least_mass, mass)
            peak = max(logprobs)
            weights = [math.exp(value - peak) for value in logprobs]
            total = sum(weights)
            for position, index in enumerate(order):
                totals[index] += weights[position] / total
            best = max(range(len(order)), key=lambda p: logprobs[p])
            winners.append(order[best])
            if run == 0:
                ranked_lp = sorted(logprobs, reverse=True)
                margin = ranked_lp[0] - ranked_lp[1]

        shares = [value / len(runs) for value in totals]
        ranked = tuple(sorted(
            (Scored(options[i].name, shares[i]) for i in range(len(options))),
            key=lambda s: -s.share,
        ))
        top = next(i for i, option in enumerate(options) if option.name == ranked[0].name)
        return Classification(
            ranked=ranked,
            margin=margin,
            agreement=winners.count(top) / len(runs),
            orderings=len(runs),
            letter_mass=least_mass,
            seconds=time.monotonic() - started,
            winners=tuple(options[index].name for index in winners),
        )
