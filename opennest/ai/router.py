"""Choosing a model and building its provider.

WORKORDER_01 section 4: the picker must clearly separate models running on this Mac from
models reached over the internet, and section 38 forbids silently switching between them.
The router therefore refuses to substitute a cloud model for a local one; it reports the
problem and lets a person choose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from opennest import paths
from opennest.ai import provider as provider_module
from opennest.ai.provider import ModelInfo, ModelProvider, ProviderError


@dataclass(frozen=True)
class ModelEntry:
    """One row of the curated model list, as configured."""

    info: ModelInfo
    model_id: str | None
    revision: str | None = None
    upstream_model: str | None = None
    license: str | None = None
    download_gb: float | None = None
    recommended: bool = False
    verified: bool = False
    #: Passed to a cloud provider's request body untouched. This is how a model declares
    #: its own request shape -- Sonnet 5's adaptive thinking versus Haiku's
    #: ``budget_tokens`` -- without a branch in Python (WORKORDER_01 section 3).
    provider_options: dict | None = None


@lru_cache(maxsize=1)
def load_catalogue(config_path: Path | None = None) -> tuple[ModelEntry, ...]:
    path = config_path or (paths.config_dir() / "models.json")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = []
    for item in raw["models"]:
        entries.append(
            ModelEntry(
                info=ModelInfo(
                    id=item["id"],
                    name=item["name"],
                    provider=item["provider"],
                    description=item.get("description", ""),
                    supports_images=bool(item.get("supports_images", False)),
                    supports_documents=bool(item.get("supports_documents", True)),
                    supports_tools=bool(item.get("supports_tools", True)),
                    requires_internet=bool(item.get("requires_internet", False)),
                    may_cost_money=bool(item.get("may_cost_money", False)),
                    context_policy=dict(item.get("context_policy", {})),
                    supports_temperature=bool(item.get("supports_temperature", True)),
                    supports_thinking_budget=bool(
                        item.get("supports_thinking_budget", False)
                    ),
                    output_headroom_tokens=int(
                        item.get("output_headroom_tokens", 0) or 0
                    ),
                ),
                model_id=item.get("model_id"),
                revision=item.get("revision"),
                upstream_model=item.get("upstream_model"),
                license=item.get("license"),
                download_gb=item.get("download_gb"),
                recommended=bool(item.get("recommended", False)),
                verified=bool(item.get("verified", False)),
                provider_options=dict(item.get("provider_options") or {}) or None,
            )
        )
    return tuple(entries)


@lru_cache(maxsize=1)
def default_model_id(config_path: Path | None = None) -> str:
    path = config_path or (paths.config_dir() / "models.json")
    return json.loads(Path(path).read_text(encoding="utf-8"))["default_local_model"]


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
    """Models able to interpret an attachment of this kind.

    Section 13 requires that when the selected model cannot interpret an attachment, the
    application says so and offers one that can. This is a lookup against
    ``models.json`` rather than a list written in code, which is section 3's rule and
    also the point: a local vision model added to the catalogue starts being offered
    without a line of Python changing, and the same is true of OpenAI and Anthropic once
    a key is configured and ``allow_cloud`` is on.

    With cloud off, this returns nothing for an image -- all four local entries are
    ``supports_images: false`` -- so the child is told the limitation and not sent after
    a model they cannot use. With cloud on *and a key saved*, Claude and OpenAI appear
    here on their own, which is what makes Phase 6 light up the offer with no change to
    the asset layer. A key that is not saved keeps the model out of the list for the
    same reason: an offer the child cannot act on is worse than an honest limitation.
    """
    attribute = _CAPABILITY_FOR_KIND.get(kind)
    if attribute is None:
        return ()
    # Offering a switch that would not help is the same lie as claiming to have looked.
    # Until a provider transmits image bytes, no model reads a picture here, however
    # many of them could in principle -- see ``provider.IMAGE_INPUT_IMPLEMENTED``.
    if kind == "image" and not provider_module.IMAGE_INPUT_IMPLEMENTED:
        return ()
    return tuple(
        entry for entry in load_catalogue()
        if getattr(entry.info, attribute)
        and is_available(entry, allow_cloud=allow_cloud, credentials=credentials)
    )


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
