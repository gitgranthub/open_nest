"""What is already here, and what a provider says it has today.

The other two inputs of section 21. Both answer "what exists right now" and neither is
allowed to answer "what should we use" -- that stays with
:mod:`~opennest.models.compatibility`, which is deterministic.

**Looking is not loading, and the two lists are different on purpose.**
:func:`load_paths` is where Open Nest will actually open a model from: its own contained
store, plus anything a parent has explicitly adopted. :func:`discover_paths` is where the
search *looks*, which is wider. Section 31 asks that a model already on the Mac not be
downloaded twice; the containment promise asks that Open Nest not quietly start loading
weights another tool put there. Keeping the lists apart satisfies both -- the search
finds it, a parent adopts it, and only then does it become loadable.

**Local discovery looks in named places, never everywhere** (section 31). Crawling a
family's disk for model-shaped directories is slow, invasive and finds things that are
none of Open Nest's business.

**An unrecognised model is shown, never selected** (section 32). A directory full of
weights is not evidence that Open Nest can drive it. Anything not in the catalogue is
reported separately, labelled as such, and never becomes a default.

**Provider discovery is filtered, never dumped** (sections 34-37). A provider will list
embeddings, speech, moderation and images alongside the two models Open Nest can hold a
conversation with. A parent gets the ones that could work; the child sees Gary.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: How huggingface_hub names a repository's directory inside a cache.
_REPO_PREFIX = "models--"

#: Filenames that make a directory plausibly a model rather than a stray folder. Used
#: only to decide whether an *unknown* directory is worth mentioning.
_MODEL_MARKERS = ("config.json", "tokenizer.json", "tokenizer_config.json")

#: A found model Open Nest could try to load.
USABLE = "usable"
#: Already in the catalogue, so it has real metadata rather than a guess.
CATALOGUED = "catalogued"
#: Found, and Open Nest cannot run it. Listed anyway, with the reason -- a parent who
#: has models on this Mac and is told "none found" will reasonably conclude the search
#: is broken.
UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class InstalledModel:
    """A model found on disk."""

    #: The catalogue id, when Open Nest recognises it. Empty when it does not.
    model_id: str
    #: The Hugging Face repository id, which is what identifies it on disk.
    repo_id: str
    directory: Path
    #: Whether this is a catalogue entry. False means "Other Installed Models".
    known: bool


# --------------------------------------------------------------------------- on disk

def load_paths() -> tuple[Path, ...]:
    """Caches Open Nest will actually *load* a model from.

    **Open Nest's own store, plus whatever a parent has explicitly adopted, and nothing
    else.** This is the containment promise: everything Open Nest downloads lives under
    ``OPENNEST_HOME``, and by default that is also the only place it reads a model from.
    On a work-managed machine that is the whole point -- model weights stay in one known
    place that Open Nest fetched, verified against a pinned commit SHA, and can account
    for.

    The wider sweep belongs to :func:`discover_paths`, and the gap between the two is
    deliberate. Section 31 of the Phase 11 work order asks that a model already on the
    Mac not be downloaded twice; the safety model asks that Open Nest not quietly start
    loading weights some other tool put there. Both are satisfied by making it a
    *choice*: the search finds it, a parent adopts it, and only then does it join this
    list. Silently reading from every cache on the disk would also have failed closed
    under the Seatbelt profile, which confines what a contained run may touch -- so the
    convenient version was not even the working version.
    """
    from opennest import paths

    found: list[Path] = [paths.models_dir()]
    found.extend(adopted_paths())

    ordered: list[Path] = []
    for path in found:
        resolved = Path(path).expanduser()
        if resolved not in ordered:
            ordered.append(resolved)
    return tuple(ordered)


def adopted_paths() -> tuple[Path, ...]:
    """Caches a parent has explicitly told Open Nest it may use.

    Empty by default, which is what keeps the default installation contained. Recorded
    in ``installation.json`` rather than inferred from the environment, so that adopting
    an external model is a decision somebody made and can see.
    """
    try:
        from opennest.setup.state import InstallationState

        return tuple(Path(p) for p in InstallationState.load().extra_model_paths)
    except Exception:
        return ()


def discover_paths() -> tuple[Path, ...]:
    """Caches the *search* will look in. Wider than :func:`load_paths`, and read-only.

    Finding a model here does not make it usable -- it makes it offerable. Nothing in
    this list is loaded from until a parent adopts it.
    """
    found: list[Path] = list(load_paths())

    hub_cache = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hub_cache:
        found.append(Path(hub_cache).expanduser())

    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        found.append(Path(hf_home).expanduser() / "hub")

    found.append(Path.home() / ".cache" / "huggingface" / "hub")

    ordered: list[Path] = []
    for path in found:
        resolved = path.expanduser()
        if resolved not in ordered:
            ordered.append(resolved)
    return tuple(ordered)


def locate(repo_id: str, revision: str | None = None, *, caches=None) -> Path | None:
    """Where this exact model and revision is, or None.

    Asks huggingface_hub with ``local_files_only``, which is the same question
    ``MLXProvider`` asks when it loads -- so a hit here means the thing the application
    will actually do would succeed, rather than that a directory of the right name
    exists.

    Defaults to :func:`load_paths`, so "installed" means "installed somewhere Open Nest
    will load from". Anything looser makes the wizard say "Already on this Mac" about a
    model it would then refuse to open.
    """
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    for cache in (caches if caches is not None else load_paths()):
        cache = Path(cache)
        if not cache.is_dir():
            continue
        try:
            located = snapshot_download(
                repo_id, revision=revision,
                cache_dir=str(cache), local_files_only=True,
            )
        except (LocalEntryNotFoundError, FileNotFoundError, OSError, ValueError):
            continue
        return Path(located)
    return None


def installed(catalog) -> tuple[InstalledModel, ...]:
    """Every catalogue model already on this Mac, at the pinned revision."""
    found: list[InstalledModel] = []
    for entry in catalog:
        if entry.info.requires_internet or not entry.model_id:
            continue
        directory = locate(entry.model_id, entry.revision)
        if directory is not None:
            found.append(
                InstalledModel(entry.info.id, entry.model_id, directory, known=True)
            )
    return tuple(found)


def installed_ids(catalog) -> tuple[str, ...]:
    return tuple(item.model_id for item in installed(catalog))


def unknown_models(catalog) -> tuple[InstalledModel, ...]:
    """Model-shaped directories Open Nest does not recognise (section 32).

    Reported so a parent can see that the disk space is accounted for, and so nobody
    concludes Open Nest lost a model they know they downloaded. Never offered as a
    default, never selected automatically, and not claimed to work: Open Nest has no
    metadata for these and says so.
    """
    catalogued = {
        entry.model_id for entry in catalog
        if entry.model_id and not entry.info.requires_internet
    }
    found: list[InstalledModel] = []
    seen: set[str] = set()
    for cache in discover_paths():
        if not cache.is_dir():
            continue
        for directory in sorted(cache.glob(f"{_REPO_PREFIX}*")):
            if not directory.is_dir():
                continue
            repo_id = directory.name[len(_REPO_PREFIX):].replace("--", "/")
            if repo_id in catalogued or repo_id in seen:
                continue
            if not _looks_like_a_model(directory):
                continue
            seen.add(repo_id)
            found.append(InstalledModel("", repo_id, directory, known=False))
    return tuple(found)


@dataclass(frozen=True)
class FoundModel:
    """A model already on this Mac, and whether Open Nest can actually use it."""

    #: What a parent would call it.
    name: str
    directory: Path
    #: ``catalogued`` | ``usable`` | ``unsupported``
    kind: str
    #: Where it came from: "Open Nest", "Hugging Face", "LM Studio", "Ollama".
    store: str
    #: Empty for a model Open Nest can use. For one it cannot, why not -- in a sentence,
    #: because "not found" and "found but I cannot run it" are different facts and a
    #: parent with models on their Mac deserves the second one.
    reason: str = ""
    #: The catalogue id, when this is a model Open Nest already knows.
    model_id: str = ""
    #: The cache this lives in, when it is outside Open Nest's own store. Adopting the
    #: model means adding this to the short list of places Open Nest may load from, so
    #: it has to be the cache root rather than the snapshot inside it.
    cache_root: Path | None = None

    @property
    def can_attempt(self) -> bool:
        return self.kind in (CATALOGUED, USABLE)

    @property
    def is_contained(self) -> bool:
        """Whether this already sits somewhere Open Nest loads from."""
        return self.cache_root is None or self.cache_root in load_paths()


def extra_search_paths() -> tuple[tuple[str, Path], ...]:
    """Model stores belonging to other applications, as ``(label, directory)``.

    Named explicitly, the same as :func:`discover_paths`: this looks in places models
    are kept, never across a family's disk.

    **None of these were present on the machine this was written on**, so the layouts
    are from each tool's documented conventions rather than from something measured.
    The consequence is bounded by design -- a path that does not exist yields nothing,
    and a directory whose contents are not recognised is reported as unsupported rather
    than guessed at.
    """
    home = Path.home()
    return (
        ("LM Studio", home / ".lmstudio" / "models"),
        ("LM Studio", home / ".cache" / "lm-studio" / "models"),
        ("Ollama", home / ".ollama" / "models"),
    )


def search_local_models(catalog) -> tuple[FoundModel, ...]:
    """Everything model-shaped on this Mac, honestly labelled.

    Behind the "do you already have a model?" button in setup and in Settings. Three
    rules, all of them section 31 and 32:

    - **Named places only.** Never a disk crawl.
    - **Finding is not loading.** This reads ``discover_paths``, which is wider than
      the ``load_paths`` Open Nest will actually open a model from.
    - **Everything found is listed**, including what cannot be used. Silence about an
      Ollama library reads as a broken search.
    - **Nothing found here becomes the default.** ``usable`` means Open Nest will
      *attempt* it, and the attempt is a real inference before anything is adopted.
    """
    found: list[FoundModel] = []
    catalogued = {
        entry.model_id: entry for entry in catalog
        if entry.model_id and not entry.info.requires_internet
    }
    seen: set[Path] = set()

    for cache in discover_paths():
        if not cache.is_dir():
            continue
        for directory in sorted(cache.glob(f"{_REPO_PREFIX}*")):
            repo_id = directory.name[len(_REPO_PREFIX):].replace("--", "/")
            snapshot = _newest_snapshot(directory)
            if snapshot is None or snapshot in seen:
                continue
            seen.add(snapshot)
            entry = catalogued.get(repo_id)
            contained = cache in load_paths()
            if entry is not None:
                found.append(FoundModel(
                    entry.info.name, snapshot, CATALOGUED,
                    "Open Nest" if contained else "Hugging Face",
                    model_id=entry.info.id, cache_root=cache,
                ))
                continue
            kind, reason = _classify_directory(snapshot)
            found.append(FoundModel(
                repo_id, snapshot, kind, "Hugging Face", reason, cache_root=cache
            ))

    for label, root in extra_search_paths():
        if not root.is_dir():
            continue
        if label == "Ollama":
            found.extend(_ollama_models(root))
            continue
        for directory in sorted(_candidate_dirs(root)):
            if directory in seen:
                continue
            seen.add(directory)
            kind, reason = _classify_directory(directory)
            found.append(FoundModel(directory.name, directory, kind, label, reason))

    return tuple(found)


def _candidate_dirs(root: Path, depth: int = 3) -> list[Path]:
    """Directories under a store that hold model files. Shallow, on purpose."""
    found = []
    for marker in ("config.json", "*.gguf"):
        for path in root.glob("/".join(["*"] * depth) + "/" + marker):
            found.append(path.parent)
        for level in range(1, depth):
            for path in root.glob("/".join(["*"] * level) + "/" + marker):
                found.append(path.parent)
    return sorted(set(found))


def _ollama_models(root: Path) -> list[FoundModel]:
    """Ollama's library, listed and declined.

    Ollama keeps GGUF weights under content-addressed blobs with its own manifest
    layout, and serves them through its own runtime. Open Nest runs MLX. Bridging the
    two means adding a second inference engine and a daemon dependency, which is a
    product decision rather than a detection problem -- so these are reported, with the
    reason, and never offered.
    """
    manifests = root / "manifests"
    if not manifests.is_dir():
        return [FoundModel("Ollama library", root, UNSUPPORTED, "Ollama", _OLLAMA_REASON)]
    names = sorted({
        path.parent.name for path in manifests.rglob("*") if path.is_file()
    })
    return [
        FoundModel(name, manifests, UNSUPPORTED, "Ollama", _OLLAMA_REASON)
        for name in names
    ] or [FoundModel("Ollama library", root, UNSUPPORTED, "Ollama", _OLLAMA_REASON)]


_OLLAMA_REASON = (
    "Open Nest cannot use Ollama's models. They are stored in a different format and "
    "run through Ollama's own engine."
)


def _classify_directory(directory: Path) -> tuple[str, str]:
    """Whether Open Nest could attempt this directory, and why not when it cannot.

    Deliberately a cheap read of ``config.json`` rather than a load: loading a 30B model
    to find out whether it loads costs minutes and most of the machine's memory. It is
    a screening step, and the real answer comes from the inference check that runs
    before anything is adopted -- the same check ``setup/downloader.verify`` does, which
    is the only thing in Open Nest entitled to say a model works.
    """
    if any(directory.glob("*.gguf")):
        return UNSUPPORTED, (
            "This is a GGUF model. Open Nest runs MLX models, which are a different "
            "format."
        )
    config = directory / "config.json"
    if not config.is_file():
        return UNSUPPORTED, "Open Nest could not tell what kind of model this is."
    if not any(directory.glob("*.safetensors")):
        # The faster-whisper case: a real model, in the right cache, in CTranslate2's
        # own format. Right folder, wrong thing entirely.
        return UNSUPPORTED, (
            "This is not a model Open Nest can run. It has no MLX weights in it."
        )
    import json

    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UNSUPPORTED, "Open Nest could not read this model's settings."
    if not isinstance(data, dict):
        return UNSUPPORTED, "Open Nest could not read this model's settings."
    # A text model that generates. An embedding or speech model has no business being
    # offered as the thing a child talks to.
    if not data.get("architectures") and not data.get("model_type"):
        return UNSUPPORTED, "Open Nest could not tell what kind of model this is."
    return USABLE, ""


def _newest_snapshot(repo_directory: Path) -> Path | None:
    snapshots = repo_directory / "snapshots"
    if not snapshots.is_dir():
        return None
    revisions = [path for path in snapshots.iterdir() if path.is_dir()]
    if not revisions:
        return None
    return max(revisions, key=lambda path: path.stat().st_mtime)


def _looks_like_a_model(directory: Path) -> bool:
    """Whether a cache directory holds something that is plausibly a model.

    Conservative on purpose. The question is only "is this worth mentioning to a
    parent", and a false positive here is a confusing row in Settings.
    """
    snapshots = directory / "snapshots"
    if not snapshots.is_dir():
        return False
    for revision in snapshots.iterdir():
        if not revision.is_dir():
            continue
        if any((revision / marker).exists() for marker in _MODEL_MARKERS):
            return True
    return False


# ------------------------------------------------------------------ what a provider has

#: Model listing endpoints. GET, not POST, which is why these do not go through
#: ``cloud.Transport`` -- that protocol is the streaming chat path.
PROVIDER_ENDPOINTS = {
    "anthropic": "https://api.anthropic.com/v1/models",
    "openai": "https://api.openai.com/v1/models",
}

#: Substrings that mark a provider model as something Open Nest has no use for. A
#: conversation is the only thing the catalogue is for; an embedding model, a speech
#: model or an image model cannot answer one. Section 34: filter, never dump.
_NOT_A_CONVERSATION = (
    "embedding", "embed", "tts", "whisper", "audio", "speech", "transcribe",
    "moderation", "image", "dall-e", "realtime", "search", "rerank", "codex-mini",
)


@dataclass(frozen=True)
class DiscoveredModel:
    """One model a provider says it has."""

    provider: str
    model_id: str
    #: ``known`` -- already a catalogue entry.
    #: ``available`` -- usable in principle, and NOT recommended by that fact alone.
    #: ``unsupported`` -- not something Open Nest can hold a conversation with.
    state: str
    display_name: str = ""

    @property
    def offerable(self) -> bool:
        return self.state in ("known", "available")


def classify(provider: str, model_id: str, catalog, display_name: str = "") -> DiscoveredModel:
    """Where one provider-reported id stands with Open Nest.

    Section 36: a model appearing here is availability, not endorsement. ``available``
    means a parent may type it into the custom-model field, not that a child is offered
    it.
    """
    lowered = model_id.lower()
    for entry in catalog:
        if entry.info.provider == provider and entry.model_id == model_id:
            return DiscoveredModel(provider, model_id, "known", entry.info.name)
    if any(word in lowered for word in _NOT_A_CONVERSATION):
        return DiscoveredModel(provider, model_id, "unsupported", display_name)
    return DiscoveredModel(provider, model_id, "available", display_name)


def parse_listing(provider: str, payload: dict) -> tuple[tuple[str, str], ...]:
    """``(id, display name)`` out of a provider's own response shape.

    Both services answer ``{"data": [...]}``; only the optional label differs. Anything
    that is not that shape yields nothing, because a provider changing its response is
    not a reason to guess.
    """
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ()
    found: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        label = row.get("display_name") if isinstance(row.get("display_name"), str) else ""
        found.append((model_id, label))
    return tuple(found)


def discover(provider: str, catalog, *, fetch) -> tuple[DiscoveredModel, ...]:
    """Ask a provider what it has, and say where each answer stands.

    ``fetch(url, headers)`` is required rather than defaulted, so that reaching a real
    service is always something the caller decided to do. Section 51: no test in this
    suite depends on a provider being online.
    """
    url = PROVIDER_ENDPOINTS.get(provider)
    if url is None:
        return ()
    payload = fetch(url)
    if not isinstance(payload, dict):
        return ()
    return tuple(
        classify(provider, model_id, catalog, label)
        for model_id, label in parse_listing(provider, payload)
    )
