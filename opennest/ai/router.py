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
                ),
                model_id=item.get("model_id"),
                revision=item.get("revision"),
                upstream_model=item.get("upstream_model"),
                license=item.get("license"),
                download_gb=item.get("download_gb"),
                recommended=bool(item.get("recommended", False)),
                verified=bool(item.get("verified", False)),
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


def build_provider(model_id: str, *, allow_cloud: bool = False) -> ModelProvider:
    """Create the provider for a model.

    ``allow_cloud`` is the parent's master switch (WORKORDER_01 section 21). With it off,
    a cloud model is refused outright rather than quietly falling back to something else.
    """
    entry = get_entry(model_id)

    if entry.info.requires_internet and not allow_cloud:
        raise ProviderError(
            f"{entry.info.name} uses the internet, and cloud AI is turned off.\n\n"
            f"A parent can turn it on in Settings."
        )

    if entry.info.provider == "mlx":
        from opennest.ai.mlx_provider import MLXProvider

        if not entry.model_id:
            raise ProviderError(f"{entry.info.name} has no model configured.")
        return MLXProvider(entry.info, entry.model_id, entry.revision)

    # OpenAI and Anthropic arrive in Phase 6 through this same interface.
    raise ProviderError(
        f"{entry.info.name} is not available yet in this version of Open Nest."
    )
