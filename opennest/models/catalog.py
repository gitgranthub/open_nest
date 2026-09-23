"""Which models Open Nest knows about, from the bundled list and any update to it.

Section 21 of the Phase 11 work order names four inputs to model selection. This module
owns two of them -- the catalogue shipped with the release, and the small remote
metadata file that may revise it -- and merges them into one list for everything else.
:mod:`~opennest.models.machine` supplies the third and
:mod:`~opennest.models.discovery` the fourth.

**The bundled catalogue is the fallback truth** (section 27). It ships in the package, so
setup works with no network, an installed model can always be identified, and a catalogue
server that is down or does not exist yet changes nothing about installing Open Nest.
That last case is the current one: no remote catalogue is published, and the code path is
exercised by tests rather than by a server.

**A remote catalogue is data, and is never allowed to become anything else** (section 29).
It cannot carry Python, a shell command, a URL or a path -- there is no field for any of
those. The strongest version of that guarantee is structural rather than defensive: a
local model is named by a Hugging Face repository id and a commit SHA, both of which are
validated, and the *place* those are fetched from is a constant in Open Nest. So the
worst a hostile catalogue can do is name a repository that does not exist, or one whose
SHA does not match, and both fail closed at download time. :func:`validate` rejects
anything that is not the shape described here, field by field, and an entry that fails
is dropped rather than taking the rest of the catalogue with it.

**A new entry is not an install** (section 30). Nothing in this module downloads
anything. A catalogue changes what is on offer; a person still has to choose.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from opennest import __version__, paths
from opennest.ai.provider import ModelInfo

#: The newest catalogue shape this release understands. A remote catalogue declaring a
#: higher one is ignored: a field we do not know about may be load-bearing, and guessing
#: is how a child ends up with a model this code cannot drive.
SUPPORTED_SCHEMA = 4

#: Providers a catalogue entry may name. Anything else is an entry describing a model
#: this release has no code to talk to.
KNOWN_PROVIDERS = frozenset({"mlx", "anthropic", "openai"})

#: Runtimes a catalogue entry may name.
KNOWN_RUNTIMES = frozenset({"mlx", "cloud"})

#: Capability words an entry may declare. A vocabulary rather than free text, so that
#: routing can depend on them -- section 33 asks for behaviour to follow capabilities
#: rather than a chain of ``if model_name ==``.
KNOWN_CAPABILITIES = frozenset({"chat", "code", "vision", "tools", "documents"})

KNOWN_STATUSES = frozenset({"supported", "deprecated", "withdrawn"})

#: ``org/name``. Deliberately strict: this string is handed to huggingface_hub, and a
#: repository id is the only thing a catalogue gets to say about where a model is.
_REPO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_MODEL_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class CatalogError(Exception):
    """A catalogue could not be read at all. A single bad entry is dropped instead."""


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

    # -- Phase 11B: what the recommendation engine compares against a Mac ------
    #: "mlx" or "cloud". What Open Nest would have to drive to run this.
    runtime: str = ""
    family: str = ""
    parameters: str = ""
    quantization: str = ""
    capabilities: tuple[str, ...] = ()
    #: Working memory this is expected to want. Guidance derived by a stated rule, not
    #: a measurement -- see the note in ``models.json``.
    estimated_memory_gb: float = 0.0
    minimum_memory_gb: float = 0.0
    recommended_memory_gb: float = 0.0
    status: str = "supported"
    #: Where this entry came from: "bundled" or "remote". Carried so a person can be
    #: told, and so a test can prove the layering did what it claims.
    source: str = "bundled"

    def has(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class Catalog:
    """The merged list, and what it is made of."""

    entries: tuple[ModelEntry, ...] = ()
    default_local_model: str = ""
    #: True when a cached remote catalogue contributed anything.
    used_remote: bool = False
    #: Entries a remote catalogue offered and validation refused, by id. Kept so a
    #: parent pressing "Check for New Models" can be told something was ignored rather
    #: than silently getting fewer models.
    rejected: tuple[str, ...] = field(default_factory=tuple)

    def __iter__(self):
        return iter(self.entries)

    def get(self, model_id: str) -> ModelEntry | None:
        for entry in self.entries:
            if entry.info.id == model_id:
                return entry
        return None


# --------------------------------------------------------------------------- validation

def validate(raw: object) -> tuple[list[dict], list[str]]:
    """Split a catalogue payload into entries worth keeping and ids that were refused.

    Never raises for a bad *entry*; raises :class:`CatalogError` only when the payload
    is not a catalogue at all. One malformed row in a remote file must not cost a
    family the other nine.
    """
    if not isinstance(raw, dict):
        raise CatalogError("A model catalogue has to be a JSON object.")
    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise CatalogError("A model catalogue has to declare a numeric schema_version.")
    if version > SUPPORTED_SCHEMA:
        raise CatalogError(
            f"This catalogue is version {version}; this copy of Open Nest understands "
            f"up to {SUPPORTED_SCHEMA}."
        )
    models = raw.get("models")
    if not isinstance(models, list):
        raise CatalogError("A model catalogue has to carry a list of models.")

    kept: list[dict] = []
    refused: list[str] = []
    for item in models:
        name = item.get("id") if isinstance(item, dict) else None
        if _entry_is_valid(item):
            kept.append(item)
        else:
            refused.append(str(name) if name else "<unnamed>")
    return kept, refused


def _entry_is_valid(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    model_key = item.get("id")
    if not isinstance(model_key, str) or not _MODEL_KEY.match(model_key):
        return False
    if not isinstance(item.get("name"), str) or not item["name"].strip():
        return False
    if item.get("provider") not in KNOWN_PROVIDERS:
        return False

    runtime = item.get("runtime", "")
    if runtime and runtime not in KNOWN_RUNTIMES:
        return False

    status = item.get("status", "supported")
    if status not in KNOWN_STATUSES:
        return False

    capabilities = item.get("capabilities", [])
    if not isinstance(capabilities, list) or any(
        c not in KNOWN_CAPABILITIES for c in capabilities
    ):
        return False

    for numeric in ("download_gb", "estimated_memory_gb", "minimum_memory_gb",
                    "recommended_memory_gb"):
        value = item.get(numeric)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return False

    if not _version_is_met(item.get("minimum_open_nest_version")):
        return False

    # A local model is a repository id and a commit SHA, and nothing else. This is the
    # structural half of section 29: there is no URL to validate because a catalogue
    # never gets to supply one.
    if item["provider"] == "mlx":
        repo = item.get("model_id")
        if not isinstance(repo, str) or not _REPO_ID.match(repo):
            return False
        revision = item.get("revision")
        if not isinstance(revision, str) or not _SHA.match(revision):
            return False

    options = item.get("provider_options")
    return options is None or isinstance(options, dict)


def _version_is_met(required) -> bool:
    """Whether this release is new enough for an entry that asks for one (section 28)."""
    if required is None:
        return True
    if not isinstance(required, str):
        return False
    try:
        wanted = tuple(int(part) for part in required.split("."))
        have = tuple(int(part) for part in __version__.split("."))
    except ValueError:
        return False
    return have >= wanted


# --------------------------------------------------------------------------- building

def build_entry(item: dict, *, source: str = "bundled") -> ModelEntry:
    """One validated row as the object the rest of Open Nest uses."""
    return ModelEntry(
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
            supports_thinking_budget=bool(item.get("supports_thinking_budget", False)),
            output_headroom_tokens=int(item.get("output_headroom_tokens", 0) or 0),
        ),
        model_id=item.get("model_id"),
        revision=item.get("revision"),
        upstream_model=item.get("upstream_model"),
        license=item.get("license"),
        download_gb=item.get("download_gb"),
        recommended=bool(item.get("recommended", False)),
        verified=bool(item.get("verified", False)),
        provider_options=dict(item.get("provider_options") or {}) or None,
        runtime=item.get("runtime", ""),
        family=item.get("family", ""),
        parameters=item.get("parameters", ""),
        quantization=item.get("quantization", ""),
        capabilities=tuple(item.get("capabilities", ())),
        estimated_memory_gb=float(item.get("estimated_memory_gb") or 0),
        minimum_memory_gb=float(item.get("minimum_memory_gb") or 0),
        recommended_memory_gb=float(item.get("recommended_memory_gb") or 0),
        status=item.get("status", "supported"),
        source=source,
    )


def bundled_payload(config_path: Path | None = None) -> dict:
    path = config_path or (paths.config_dir() / "models.json")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def merge(bundled: dict, remote: dict | None) -> Catalog:
    """Lay a remote catalogue over the bundled one.

    An entry with an id the bundled list already has *replaces* it, which is how a
    recommendation is revised or a model marked deprecated without an application
    release. An entry with a new id is appended. Bundled order is preserved so the
    curated list does not reshuffle itself under a parent.

    ``default_local_model`` is deliberately not something a remote catalogue may change.
    It decides what a fresh installation downloads, and that is a decision this release
    was tested with.
    """
    kept, _ = validate(bundled)
    entries = [build_entry(item, source="bundled") for item in kept]
    rejected: list[str] = []
    used_remote = False

    if remote is not None:
        try:
            remote_kept, rejected_ids = validate(remote)
        except CatalogError:
            remote_kept, rejected_ids = [], []
        rejected = list(rejected_ids)
        by_id = {entry.info.id: index for index, entry in enumerate(entries)}
        for item in remote_kept:
            replacement = build_entry(item, source="remote")
            used_remote = True
            if replacement.info.id in by_id:
                entries[by_id[replacement.info.id]] = replacement
            else:
                by_id[replacement.info.id] = len(entries)
                entries.append(replacement)

    # A withdrawn model is one the catalogue is retracting. It stays out of the offered
    # list entirely; a copy already on disk keeps working, because nothing here deletes
    # anything and the provider only needs the id.
    offered = tuple(e for e in entries if e.status != "withdrawn")
    return Catalog(
        entries=offered,
        default_local_model=bundled.get("default_local_model", ""),
        used_remote=used_remote,
        rejected=tuple(rejected),
    )


@lru_cache(maxsize=1)
def load(config_path: Path | None = None) -> Catalog:
    """The merged catalogue: bundled, plus a cached remote one if there is a good one.

    Cached rather than fetched. Nothing here reaches the network -- section 45 is
    explicit that a launch must never wait on a catalogue server, so the refresh is
    something a parent asks for and this only ever reads what that left behind.
    """
    from opennest.models import remote as remote_module

    return merge(bundled_payload(config_path), remote_module.cached())


def reload() -> Catalog:
    """Re-read after a refresh. ``load`` caches, so something has to clear it."""
    load.cache_clear()
    return load()
