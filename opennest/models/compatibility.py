"""Whether a model suits a particular Mac, and why.

Section 54 of the Phase 11 work order asks for a recommendation system that is
*inspectable*: a test should be able to say why a model came out Recommended rather than
Can Run. So this is a small pile of explicit rules over declared metadata, and every
function takes the machine as an argument -- nothing here detects anything, which is what
lets an 8 GB Air, a 16 GB Pro and a 64 GB Studio all be tested on a machine that is none
of them.

Two rules that are easy to get wrong and are written down because of it:

**No language model is asked which model to install.** Section 53. This is arithmetic
over declared requirements, and a generative judgement here would be unreproducible,
unexplainable and, on a bad day, wrong about gigabytes.

**Nothing is benchmarked during setup.** Section 52. Downloading three models to find
out which is fastest is hours and tens of gigabytes to answer a question the metadata
already answers well enough.

The four classes are the child-facing translation of all of it (section 25). A parent
sees "Recommended for this Mac"; the arithmetic stays here.
"""

from __future__ import annotations

from dataclasses import dataclass

from opennest.models.machine import MachineProfile

#: Comfortably. The Mac meets the model's recommended memory.
RECOMMENDED = "recommended"
#: Expected to work, with less room to spare. Meets the minimum, not the recommendation.
CAN_RUN = "can_run"
#: Below the operating envelope, or not enough disk to install it.
NOT_RECOMMENDED = "not_recommended"
#: Known not to work here at all -- wrong architecture, missing runtime.
INCOMPATIBLE = "incompatible"

#: Worst first. Used to order a list so the honest answer is not buried.
_SEVERITY = {RECOMMENDED: 0, CAN_RUN: 1, NOT_RECOMMENDED: 2, INCOMPATIBLE: 3}

#: What a parent sees. Section 26: about fit, never an absolute ranking.
LABELS = {
    RECOMMENDED: "Recommended for this Mac",
    CAN_RUN: "Should work on this Mac",
    NOT_RECOMMENDED: "Not recommended for this Mac",
    INCOMPATIBLE: "Will not run on this Mac",
}

#: Runtimes Open Nest can actually drive. A catalogue entry naming anything else is
#: describing a model this release cannot load, whatever the machine.
KNOWN_RUNTIMES = frozenset({"mlx", "cloud"})

#: Room to leave on the disk after a download, so installing a model does not fill it.
DISK_HEADROOM_GB = 5.0


@dataclass(frozen=True)
class Verdict:
    """One model against one Mac, and the sentence explaining it."""

    model_id: str
    state: str
    #: Why, in a sentence a parent can read. Always populated, including for
    #: ``recommended`` -- "it fits" is also worth saying.
    reason: str
    #: Whether this model is already downloaded, so nothing offers to fetch it twice.
    installed: bool = False

    @property
    def label(self) -> str:
        return LABELS[self.state]

    @property
    def usable(self) -> bool:
        """Whether Open Nest would let this be installed or selected at all."""
        return self.state in (RECOMMENDED, CAN_RUN, NOT_RECOMMENDED)


def assess(entry, machine: MachineProfile, *, installed: bool = False) -> Verdict:
    """Classify one catalogue entry for one Mac.

    Order matters. Architecture and runtime come first because they are absolute: a Mac
    that cannot load the model at all should not then be told it is short of memory,
    which would imply that more memory would help.
    """
    model_id = entry.info.id

    # A cloud model's requirements are a key and a switch, not this Mac's hardware.
    # Section 21 keeps those two questions apart, and router.why_unavailable answers
    # the other one.
    if entry.info.requires_internet:
        return Verdict(model_id, RECOMMENDED, "Runs on the internet, not on this Mac.",
                       installed=installed)

    runtime = (entry.runtime or "").lower()
    if runtime and runtime not in KNOWN_RUNTIMES:
        return Verdict(
            model_id, INCOMPATIBLE,
            f"This version of Open Nest cannot run {runtime} models.",
            installed=installed,
        )

    if not machine.is_apple_silicon:
        return Verdict(
            model_id, INCOMPATIBLE,
            "Models run on this Mac need Apple silicon (M1 or newer).",
            installed=installed,
        )

    if runtime == "mlx" and not machine.mlx_available:
        return Verdict(
            model_id, INCOMPATIBLE,
            "The local AI engine is not installed yet. Running Setup again adds it.",
            installed=installed,
        )

    # Memory. An already-installed model is still assessed on memory -- being on disk
    # says nothing about whether it will run well -- but disk is not checked for one,
    # because it has already been paid for.
    memory = machine.memory_gb
    minimum = float(entry.minimum_memory_gb or 0)
    recommended = float(entry.recommended_memory_gb or minimum)

    if memory and minimum and memory < minimum:
        return Verdict(
            model_id, NOT_RECOMMENDED,
            f"Needs about {minimum:.0f} GB of memory. This Mac has "
            f"{memory:.0f} GB.",
            installed=installed,
        )

    if not installed:
        needed = float(entry.download_gb or 0) + DISK_HEADROOM_GB
        if machine.free_disk_gb and needed and machine.free_disk_gb < needed:
            return Verdict(
                model_id, NOT_RECOMMENDED,
                f"Needs about {entry.download_gb:.1f} GB to download, and this Mac has "
                f"{machine.free_disk_gb:.0f} GB free.",
                installed=installed,
            )

    if memory and recommended and memory < recommended:
        return Verdict(
            model_id, CAN_RUN,
            f"This Mac can run it, but with {memory:.0f} GB of memory it will be "
            f"slower and leave less room for everything else.",
            installed=installed,
        )

    return Verdict(model_id, RECOMMENDED, "Runs comfortably on this Mac.",
                   installed=installed)


def assess_all(entries, machine: MachineProfile, installed_ids=()) -> tuple[Verdict, ...]:
    """Every entry against this Mac, in catalogue order."""
    already = set(installed_ids)
    return tuple(
        assess(entry, machine, installed=entry.info.id in already) for entry in entries
    )


def suggestion(entries, machine: MachineProfile, installed_ids=()):
    """The one local model Open Nest suggests for this Mac, or None.

    What the setup wizard puts in front of a parent, so the tie-breaks are the ones that
    matter to somebody who has not asked a question yet:

    1. Something already downloaded, if it suits -- section 31 is emphatic that an
       installed model is reused rather than duplicated, and a suggestion that starts a
       17 GB download when a working model is already there is the wrong suggestion.
    2. Comfortable over merely possible.
    3. Larger over smaller, since everything still standing already fits.

    **``verified`` is deliberately not one of the keys, and that was a bug once.** It
    ranked above size, and exactly one local entry has been run end to end through Open
    Nest's own provider -- so a 64 GB Studio was suggested the same 2.3 GB model as an
    8 GB Air, and would have gone on being suggested it until somebody downloaded and
    verified every other entry. That makes a flag about *Open Nest's testing* behave
    like a claim about the *model*, which it is not. What the flag is for is saying so
    out loud: :func:`untested_note` is the sentence, and the wizard shows it beside the
    suggestion rather than quietly resolving it in a sort order.

    Returns ``(entry, verdict)`` or ``None`` when nothing here can run at all.
    """
    already = set(installed_ids)
    candidates = [
        (entry, assess(entry, machine, installed=entry.info.id in already))
        for entry in entries
        if not entry.info.requires_internet
    ]
    usable = [
        (entry, verdict) for entry, verdict in candidates
        if verdict.state in (RECOMMENDED, CAN_RUN)
        # A model that cannot build anything is not a suggestion, whatever it fits in.
        and entry.info.supports_tools
    ]
    if not usable:
        return None

    def rank(pair):
        entry, verdict = pair
        return (
            0 if verdict.installed else 1,
            _SEVERITY[verdict.state],
            -float(entry.download_gb or 0),
        )

    return min(usable, key=rank)


def untested_note(entry) -> str:
    """Said when Open Nest has not itself run this model. Empty when it has.

    A catalogue entry is metadata somebody wrote down; ``verified`` means a real
    inference completed through the application's own provider code. Only the default
    model has had that done to it, and a parent about to spend seventeen gigabytes is
    entitled to know which kind of claim they are acting on.
    """
    if entry.verified:
        return ""
    return (
        "Open Nest has not tested this model itself yet. It should work on this Mac, "
        "and it will be checked after it downloads."
    )


def sort_for_display(pairs):
    """Best fit first, so a parent reads down rather than hunting."""
    return sorted(pairs, key=lambda pair: (_SEVERITY[pair[1].state],
                                           -float(pair[0].download_gb or 0)))
