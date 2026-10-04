"""Choosing a model and building its provider.

WORKORDER_01 section 4: the picker must clearly separate models running on this Mac from
models reached over the internet, and section 38 forbids silently switching between them.
The router therefore refuses to substitute a cloud model for a local one; it reports the
problem and lets a person choose.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opennest.ai import provider as provider_module
from opennest.ai.provider import ModelInfo, ModelProvider, ProviderError
from opennest.models.catalog import ModelEntry, load

#: Re-exported. ``ModelEntry`` moved to :mod:`opennest.models.catalog` in Phase 11B,
#: when it gained the fields a machine-aware recommendation compares against and stopped
#: being something the router alone built. Everything that imported it from here still
#: can -- the router remains the place you ask "which models, and give me a provider for
#: one", and the catalogue is now the place that answers the first half.
__all__ = [
    "ModelEntry", "load_catalogue", "default_model_id", "startup_model_id", "get_entry",
    "local_models",
    "cloud_models", "is_available", "models_that_can_read", "unmet_requirements",
    "models_for_project", "why_unavailable", "model_advice", "ModelAdvice", "build_provider",
]


def load_catalogue(config_path: Path | None = None) -> tuple[ModelEntry, ...]:
    """The merged catalogue: bundled, plus any cached remote revision of it.

    A single function call away from where it used to read ``models.json`` directly,
    which is the point -- one source of truth, and a remote catalogue that revises a
    recommendation reaches every caller at once.
    """
    return load(config_path).entries


def default_model_id(config_path: Path | None = None) -> str:
    """What a fresh installation downloads.

    Deliberately not something a remote catalogue may change: it decides what happens on
    a Mac nobody has looked at yet, and this release was tested with this answer.
    """
    return load(config_path).default_local_model


def startup_model_id(preferred: str = "") -> str:
    """The local model the application starts with: the one setup installed and chose,
    when it still can be, else :func:`default_model_id`.

    Until the vision models arrived the app always started the default, whatever a
    parent picked in setup -- choosing Qwen3 8B there still gave a child the 4B. That
    was invisible while the default was the model nearly everyone had; with Gary Fast
    as the default it would have told every existing installation its model was not
    installed. A preference for a cloud model, or one no longer in the catalogue or no
    longer on this Mac, falls back rather than failing -- and is never a cloud model.

    **A replaced model gives way to its replacement once that is here** (the owner's
    ruling when the vision models measured better, SPIKES.md section 32): a family set
    up with Qwen3 4B gets Gary Fast as soon as Gary Fast is on the Mac, and keeps Qwen3
    4B, working, until then -- never a model that is not installed. Not silent: the
    model picker names the model that is answering.
    """
    default = default_model_id()
    if preferred:
        try:
            entry = get_entry(preferred)
        except ProviderError:
            entry = None
        if entry is not None and entry.info.is_local and _installed(entry):
            if entry.offered_for_install:
                return entry.info.id
            try:
                replacement = get_entry(default)
            except ProviderError:
                replacement = None
            if replacement is not None and _installed(replacement):
                return default
            return entry.info.id
    return default


def get_entry(model_id: str) -> ModelEntry:
    for entry in load_catalogue():
        if entry.info.id == model_id:
            return entry
    raise ProviderError(f"There is no model called {model_id!r}.")


def local_models() -> tuple[ModelEntry, ...]:
    return tuple(e for e in load_catalogue() if e.info.is_local)


def cloud_models() -> tuple[ModelEntry, ...]:
    return tuple(e for e in load_catalogue() if not e.info.is_local)


#: Which capability flag governs which kind of attachment (WORKORDER_01 section 13:
#: ``model.supports_images``, ``model.supports_documents``).
_CAPABILITY_FOR_KIND = {"image": "supports_images", "document": "supports_documents"}


def is_available(
    entry: ModelEntry,
    *,
    allow_cloud: bool = False,
    credentials=None,
) -> bool:
    """Whether this model could actually be used right now.

    A local model is available. A cloud model needs two separate things: the parent's
    master switch (WORKORDER_01 section 21) *and* a key in the Keychain (section 22).
    Both are checked here so that nothing offers a child a model they cannot reach --
    section 13's rule about not sending them after an unusable model, applied to the
    catalogue rather than repeated at each call site.

    The Keychain is only consulted once cloud is allowed, so the default path touches
    no credential store at all.
    """
    if not entry.info.requires_internet:
        return True
    if not allow_cloud:
        return False
    from opennest.security import keychain

    store = credentials or keychain.default()
    return store.has_key(entry.info.provider)


def models_that_can_read(
    kind: str,
    *,
    allow_cloud: bool = False,
    credentials=None,
) -> tuple[ModelEntry, ...]:
    """Models able to interpret an attachment of this kind, usable now.

    Section 13 requires that when the selected model cannot interpret an attachment, the
    application says so and offers one that can. This is a lookup against
    ``models.json`` rather than a list written in code, which is section 3's rule: a
    local vision model in the catalogue is offered without a line of Python changing.

    **For a picture, "can read" means Open Nest can show it the pixels**
    (``provider.can_send_images``) -- today a local vision model, never a cloud one,
    whose ``supports_images`` is true and whose provider sends none. Offering a switch
    that would not help is the same lie as claiming to have looked. And a local model
    must be **installed**: "Gary Fast can read it. You can choose it" about a model
    that is not on this Mac is an offer the child cannot act on, which is worse than
    the honest limitation. A cloud model still needs the switch and a key.
    """
    attribute = _CAPABILITY_FOR_KIND.get(kind)
    if attribute is None:
        return ()
    found = []
    for entry in load_catalogue():
        if not getattr(entry.info, attribute):
            continue
        if kind == "image" and not provider_module.can_send_images(entry.info):
            continue
        if not is_available(entry, allow_cloud=allow_cloud, credentials=credentials):
            continue
        if kind == "image" and entry.info.is_local and not _installed(entry):
            continue
        found.append(entry)
    return tuple(found)


def _installed(entry: ModelEntry) -> bool:
    from opennest.models.discovery import locate

    try:
        return entry.model_id is not None and locate(entry.model_id, entry.revision) \
            is not None
    except Exception:  # noqa: BLE001 - an unreadable cache is "not installed", not a crash
        return False


def unmet_requirements(info: ModelInfo, profile) -> tuple[str, ...]:
    """Why this model cannot build this kind of project. Empty when it can.

    WORKORDER_01 section 13 makes the application responsible for knowing model
    capabilities, and the same reasoning reaches further than attachments: a project
    profile states what it needs, a model states what it does, and the application
    should compare them rather than let a child discover the mismatch by watching
    nothing happen.

    This is currently one check because there is currently one hard blocker.
    ``gemma2-2b`` is in the catalogue with ``supports_tools: false``, and every profile
    in ``profiles.json`` works by calling tools -- so that model can discuss a game and
    cannot build one. Not being able to see a picture is *not* a blocker: that is a
    limitation the asset layer already states honestly and works around.
    """
    problems: list[str] = []
    if profile.tools and not info.supports_tools:
        problems.append(
            f"{info.name} cannot use tools, so it can talk about a "
            f"{profile.name.lower()} but cannot build or change one."
        )
    return tuple(problems)


def models_for_project(profile, *, allow_cloud: bool = False) -> tuple[ModelEntry, ...]:
    """Catalogue entries that could build this kind of project.

    Deliberately *not* filtered by whether a key is saved. A picker should show that
    Claude exists and say it needs a key, rather than hide it and leave a parent
    wondering where the cloud models went -- DESIGN_DOC section 13 shows the INTERNET
    section as a visible part of the picker. :func:`why_unavailable` supplies the
    sentence that goes under a row the child cannot pick yet.
    """
    return tuple(
        entry for entry in load_catalogue()
        if not unmet_requirements(entry.info, profile)
        and (allow_cloud or not entry.info.requires_internet)
        # A replaced local model only where it is on this Mac: choosing one that is not
        # would just say it is not installed, and it is never to be downloaded again.
        and (entry.offered_for_install or _installed(entry))
    )


def why_unavailable(
    entry: ModelEntry,
    *,
    allow_cloud: bool = False,
    credentials=None,
) -> str | None:
    """Why this model cannot be picked right now, or None when it can.

    DESIGN_DOC section 13 forbids presenting cloud models as better than local ones, so
    this says what is missing and nothing about quality.
    """
    if not entry.info.requires_internet:
        return None
    if not allow_cloud:
        return "Cloud AI is turned off. A parent can turn it on in Settings."
    if not is_available(entry, allow_cloud=True, credentials=credentials):
        return "Needs an API key. A parent can add one in Settings."
    return None


@dataclass(frozen=True)
class ModelAdvice:
    """What to say when a project is begun with a model measured to struggle with it."""

    #: The model in use, and the kind of project, as a child reads them.
    model_name: str
    project_kind: str
    #: Models that would do better and could be used on this Mac right now, best first:
    #: (model id, name). Switching to one still goes through the usual consent.
    choices: tuple[tuple[str, str], ...]
    #: What a parent could do to make another model possible -- download it, turn cloud
    #: on, add a key -- or why this Mac cannot.
    parent_steps: tuple[str, ...]

    @property
    def headline(self) -> str:
        return f"{self.model_name} struggles to build a {self.project_kind} that works."

    @property
    def explanation(self) -> str:
        return (f"A whole {self.project_kind} is more than {self.model_name} can build "
                f"reliably: it often leaves one half-made. For a {self.project_kind}, use "
                f"at least Gary Smart or a cloud model.")


def model_advice(model_id: str, profile, machine, *, allow_cloud: bool = False,
                 credentials=None) -> ModelAdvice | None:
    """Whether to warn that this model struggles with this kind of project, and how.

    The owner's ruling after the game builds pass (2026-10-04, SPIKES.md section 33):
    a Game begun on Gary Fast says that Gary Fast will struggle to build a usable game,
    and points at Gary Smart or a cloud model. The model's ``struggles_with`` decides
    (``models.json``, measured), never a name in code. What it offers is only what this
    Mac can really use now -- a local model that is installed and fits its memory, a
    cloud model with the parent's switch on and a key saved -- and anything else is said
    as a step for a parent, or as the reason it cannot be. None when there is nothing to
    say: the model is not marked, or is not in the catalogue.

    ``machine`` is a :class:`~opennest.models.machine.MachineProfile`: only
    ``models.machine.detect()`` looks at the hardware.
    """
    from opennest.models import compatibility  # lazily: it is only needed here

    try:
        current = get_entry(model_id)
    except ProviderError:
        return None
    if profile.id not in current.struggles_with:
        return None
    choices: list[tuple[str, str]] = []
    steps: list[str] = []
    cloud_step = ""
    for entry in load_catalogue():
        info = entry.info
        if info.id == model_id or profile.id in entry.struggles_with or \
                not entry.offered_for_install or unmet_requirements(info, profile):
            continue
        if info.requires_internet:
            if is_available(entry, allow_cloud=allow_cloud, credentials=credentials):
                choices.append((info.id, info.name))
            elif not cloud_step:
                cloud_step = ("A parent can turn on Cloud AI and add a key in Settings."
                              if not allow_cloud else
                              "A parent can add a Cloud AI key in Settings.")
            continue
        installed = _installed(entry)
        verdict = compatibility.assess(entry, machine, installed=installed)
        if verdict.state not in (compatibility.RECOMMENDED, compatibility.CAN_RUN):
            reason = verdict.reason[:1].lower() + verdict.reason[1:]
            steps.append(f"{info.name} cannot run on this Mac: it {reason}" if reason.startswith(
                "needs ") else f"{info.name} cannot run on this Mac. {verdict.reason}")
        elif installed:
            choices.append((info.id, info.name))
        else:
            steps.append(f"A parent can download {info.name} in Settings.")
    if cloud_step:
        steps.append(cloud_step)
    return ModelAdvice(current.info.name, profile.name.lower(), tuple(choices), tuple(steps))


def build_provider(
    model_id: str,
    *,
    allow_cloud: bool = False,
    transport=None,
    credentials=None,
) -> ModelProvider:
    """Create the provider for a model.

    ``allow_cloud`` is the parent's master switch (WORKORDER_01 section 21). With it off,
    a cloud model is refused outright rather than quietly falling back to something else
    -- section 38 forbids silently switching between local and cloud, and a fallback is
    that switch with the notification removed.

    ``transport`` and ``credentials`` exist so the cloud providers can be exercised
    without a network or a Keychain, the same way ``ScriptedProvider`` stands in for the
    local model. The application passes neither.
    """
    entry = get_entry(model_id)

    if entry.info.requires_internet and not allow_cloud:
        raise ProviderError(
            f"{entry.info.name} uses the internet, and cloud AI is turned off.\n\n"
            f"A parent can turn it on in Settings."
        )

    if not entry.model_id:
        raise ProviderError(f"{entry.info.name} has no model configured.")

    if entry.info.provider == "mlx":
        from opennest.ai.mlx_provider import MLXProvider

        return MLXProvider(entry.info, entry.model_id, entry.revision)

    if entry.info.provider == "anthropic":
        from opennest.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            entry.info, entry.model_id,
            transport=transport, credentials=credentials,
            provider_options=entry.provider_options,
        )

    if entry.info.provider == "openai":
        from opennest.ai.openai_provider import OpenAIProvider

        return OpenAIProvider(
            entry.info, entry.model_id,
            transport=transport, credentials=credentials,
            provider_options=entry.provider_options,
        )

    raise ProviderError(
        f"{entry.info.name} is not available yet in this version of Open Nest."
    )
