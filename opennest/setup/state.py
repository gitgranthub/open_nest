"""``installation.json`` -- whether this Mac is set up, and what it was set up against.

WORKORDER_01 section 35A ("Installation state") asks for a machine-level record of setup
status, and section "Repository update behavior" (DoD 51-53) asks the *next launch after
a ``git pull``* to detect dependency, configuration-schema and model-definition changes
and migrate before starting. Those are the same file: you cannot tell what changed
without having written down what you last ran against.

``paths.installation_state_file()`` has declared this file since Phase 0 and nothing ever
wrote it. This is what writes it.

Three rules it follows:

**No secrets, and that is enforced rather than intended.** Section 35A says so in as many
words, and section 22 lists JSON configuration among the places a key must never appear.
:func:`_reject_credentials` runs the same scanner ``permissions.save()`` uses, for the
same reason: the failure being guarded against is a future change that stores "the OpenAI
key" here for convenience.

**Damaged or old metadata means repair, never reset.** A file that will not parse gives
back a state whose ``setup_complete`` is False and whose ``unreadable`` flag is True, so
the launcher offers setup or repair. Nothing is deleted and no project is touched --
losing a parent's settings because a write was interrupted is a worse outcome than asking
them to run setup again.

**Fingerprints are recorded, never inferred.** :class:`Fingerprint` is a snapshot of the
things a ``git pull`` can move: the requirement manifests, the schema versions of the two
config files, and every pinned model revision. Comparing two of those is the whole of
"detect dependency, configuration schema and model-definition changes".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields
from pathlib import Path

from opennest import __version__, paths
from opennest.versioning import secret_scanner

#: Version of this file's own layout. Bumped when a field changes meaning, so a future
#: Open Nest can tell "written by an older version" from "written by a broken one".
SCHEMA_VERSION = 1

#: The manifests a pull can change. Section "Repository update behavior" calls this
#: "dependency manifest changes"; Phase 7 made it bigger by adding projects.txt to the
#: bootstrap, so a moved pin here is a real reinstall rather than a formality.
REQUIREMENT_FILES: tuple[str, ...] = (
    "base.txt",
    "macos-apple-silicon.txt",
    "projects.txt",
)


@dataclass(frozen=True)
class Change:
    """One difference between what was last run and what is on disk now."""

    #: ``dependencies`` | ``schema`` | ``models``
    kind: str
    #: One line a parent can read. Never a diff, never a path they cannot act on.
    summary: str
    #: True when acting on this change downloads gigabytes. Shown, never auto-started.
    costly: bool = False


@dataclass(frozen=True)
class Fingerprint:
    """What the application looked like the last time it launched successfully."""

    app_version: str = ""
    #: requirements filename -> sha256 of its contents
    requirements: dict = field(default_factory=dict)
    profiles_schema: int = 0
    models_schema: int = 0
    #: local model id -> pinned commit revision
    model_pins: dict = field(default_factory=dict)

    @classmethod
    def current(cls, repo_root: Path | None = None, config_dir: Path | None = None) -> Fingerprint:
        """Read the fingerprint of the checkout as it stands right now."""
        root = Path(repo_root) if repo_root is not None else paths.repo_root()
        config = Path(config_dir) if config_dir is not None else paths.config_dir()

        digests: dict = {}
        for name in REQUIREMENT_FILES:
            candidate = root / "requirements" / name
            try:
                digests[name] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            except OSError:
                # A manifest that is not there is a fact worth recording as absence
                # rather than as an error: the set of manifests can legitimately change.
                continue

        profiles = _read_json(config / "profiles.json")
        models = _read_json(config / "models.json")
        pins = {
            entry.get("id", ""): entry.get("revision", "")
            for entry in models.get("models", [])
            if isinstance(entry, dict) and entry.get("revision")
        }
        return cls(
            app_version=__version__,
            requirements=digests,
            profiles_schema=_as_int(profiles.get("schema_version")),
            models_schema=_as_int(models.get("schema_version")),
            model_pins=pins,
        )

    @classmethod
    def from_dict(cls, raw: object) -> Fingerprint:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            app_version=_as_str(raw.get("app_version")),
            requirements=_as_str_map(raw.get("requirements")),
            profiles_schema=_as_int(raw.get("profiles_schema")),
            models_schema=_as_int(raw.get("models_schema")),
            model_pins=_as_str_map(raw.get("model_pins")),
        )

    def as_dict(self) -> dict:
        return {
            "app_version": self.app_version,
            "requirements": dict(self.requirements),
            "profiles_schema": self.profiles_schema,
            "models_schema": self.models_schema,
            "model_pins": dict(self.model_pins),
        }

    def recorded(self) -> bool:
        """Whether this fingerprint came from a real recording rather than a default."""
        return bool(self.app_version or self.requirements or self.model_pins)


def changes_since(recorded: Fingerprint, current: Fingerprint | None = None) -> tuple[Change, ...]:
    """What a ``git pull`` moved, in the three categories the work order names.

    An unrecorded fingerprint yields no changes. "We have never run before" is a setup
    question, not a migration one, and reporting every manifest as changed on a fresh
    install would put a migration prompt in front of a parent who just finished setup.
    """
    now = current if current is not None else Fingerprint.current()
    if not recorded.recorded():
        return ()

    found: list[Change] = []

    moved = [
        name
        for name in sorted(set(recorded.requirements) | set(now.requirements))
        if recorded.requirements.get(name) != now.requirements.get(name)
    ]
    if moved:
        found.append(
            Change(
                "dependencies",
                "The list of things Open Nest needs has changed "
                f"({', '.join(moved)}). They need reinstalling.",
            )
        )

    if recorded.profiles_schema != now.profiles_schema:
        found.append(
            Change(
                "schema",
                f"Project types were updated (version {recorded.profiles_schema} "
                f"to {now.profiles_schema}).",
            )
        )
    if recorded.models_schema != now.models_schema:
        found.append(
            Change(
                "schema",
                f"The AI model list was updated (version {recorded.models_schema} "
                f"to {now.models_schema}).",
            )
        )

    added = sorted(set(now.model_pins) - set(recorded.model_pins))
    removed = sorted(set(recorded.model_pins) - set(now.model_pins))
    repinned = sorted(
        name
        for name in set(recorded.model_pins) & set(now.model_pins)
        if recorded.model_pins[name] != now.model_pins[name]
    )
    if repinned:
        # Gigabytes. PLAN.md's Phase 8 section is explicit that this is shown and never
        # silently started, which is why the Change carries the fact rather than the
        # caller deciding from the kind.
        found.append(
            Change(
                "models",
                f"A new version of {_join(repinned)} is available. Downloading it is "
                "several gigabytes, so Open Nest will not start it on its own.",
                costly=True,
            )
        )
    if added:
        found.append(Change("models", f"New AI models are available: {_join(added)}."))
    if removed:
        found.append(
            Change("models", f"Open Nest no longer offers {_join(removed)}.")
        )
    return tuple(found)


@dataclass
class InstallationState:
    """The machine-level record behind "is this Mac set up?".

    Field names follow section 35A's example object where it gives one, so the file on
    disk looks like the thing the work order describes.
    """

    setup_complete: bool = False
    schema_version: int = SCHEMA_VERSION
    preferred_model: str = ""
    cloud_enabled: bool = False
    github_enabled: bool = False

    #: Section 35A step 2. The child-facing name and the Git identity are separate
    #: fields there, and separate here; none of the three is a secret.
    child_name: str = ""
    git_author_name: str = ""
    git_author_email: str = ""

    #: Model ids setup downloaded and verified, so a health check knows what to look for.
    installed_models: list = field(default_factory=list)
    #: Whether the parent chose the Arduino toolchain (D7: arduino-cli plus the AVR core).
    arduino_installed: bool = False

    #: What the application looked like at the last successful launch.
    fingerprint: Fingerprint = field(default_factory=Fingerprint)

    #: Where this was loaded from, so save() round-trips. Not persisted.
    path: Path | None = field(default=None, compare=False, repr=False)
    #: True when the file existed but could not be read. Not persisted -- it is a fact
    #: about this load, and it means "offer repair", never "delete and start again".
    unreadable: bool = field(default=False, compare=False, repr=False)

    # -- persistence --------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> InstallationState:
        """Read the record. Missing means "not set up"; damaged means "needs repair"."""
        target = Path(path) if path is not None else paths.installation_state_file()
        state = cls(path=target)
        try:
            text = target.read_text(encoding="utf-8")
        except OSError:
            # Absent is the ordinary first-run case, not a fault.
            return state
        try:
            raw = json.loads(text)
        except ValueError:
            state.unreadable = True
            return state
        if not isinstance(raw, dict):
            state.unreadable = True
            return state

        for entry in fields(cls):
            if entry.name in ("path", "unreadable", "fingerprint"):
                continue
            if entry.name not in raw:
                continue
            value = raw[entry.name]
            existing = getattr(state, entry.name)
            # The default's type is what a field is allowed to be. Anything else is
            # ignored in favour of the safe default rather than trusted -- the same
            # stance ParentControls.load takes.
            if isinstance(existing, bool):
                if isinstance(value, bool):
                    setattr(state, entry.name, value)
            elif isinstance(existing, int):
                if isinstance(value, int) and not isinstance(value, bool):
                    setattr(state, entry.name, value)
            elif isinstance(existing, str):
                if isinstance(value, str):
                    setattr(state, entry.name, value)
            elif isinstance(existing, list) and isinstance(value, list):
                setattr(state, entry.name, [v for v in value if isinstance(v, str)])
        state.fingerprint = Fingerprint.from_dict(raw.get("fingerprint"))
        return state

    def save(self, path: Path | None = None) -> Path:
        """Write the record. Refuses anything credential-shaped (section 22)."""
        target = Path(path) if path is not None else (self.path or paths.installation_state_file())
        payload = self.as_dict()
        _reject_credentials(payload)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Temporary file then replace, so an interrupted write cannot leave truncated
        # JSON. load() would read that as "unreadable" and send a parent to repair --
        # recoverable, but a save should not be able to cause it.
        scratch = target.with_suffix(target.suffix + ".tmp")
        scratch.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        scratch.replace(target)
        self.path = target
        self.unreadable = False
        return target

    def as_dict(self) -> dict:
        payload = {
            entry.name: getattr(self, entry.name)
            for entry in fields(self)
            if entry.name not in ("path", "unreadable", "fingerprint")
        }
        payload["fingerprint"] = self.fingerprint.as_dict()
        return payload

    # -- questions the launcher asks ----------------------------------------

    def needs_setup(self) -> bool:
        """Whether the launcher should show the wizard rather than the app.

        Damaged metadata counts. Section 35A's relaunch rule is "setup complete -> Build
        Lab, otherwise -> Setup Wizard", and a record that cannot be read has not told us
        setup is complete.
        """
        return self.unreadable or not self.setup_complete

    def pending_changes(self, current: Fingerprint | None = None) -> tuple[Change, ...]:
        """What changed since this installation last launched (DoD 51-53)."""
        return changes_since(self.fingerprint, current)

    def record_launch(self, current: Fingerprint | None = None) -> None:
        """Adopt the current checkout as the thing we last ran successfully.

        Called after migrations have been applied, never before -- the fingerprint means
        "this is what we are known to work against".
        """
        self.fingerprint = current if current is not None else Fingerprint.current()


def load(path: Path | None = None) -> InstallationState:
    """Read the installation record. Deliberately not cached: setup rewrites it."""
    return InstallationState.load(path)


# --------------------------------------------------------------------------- internals

def _reject_credentials(payload: dict) -> None:
    findings = secret_scanner.scan_text(json.dumps(payload, indent=2), "installation.json")
    if findings:
        raise ValueError(
            "Open Nest refused to save the installation record because something in it "
            "looks like a password or key. Keys belong in the macOS Keychain."
        )


def _read_json(path: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _as_str_map(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}


def _join(names: list) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"
