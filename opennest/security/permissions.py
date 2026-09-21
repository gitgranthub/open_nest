"""Parent controls: what a child's projects and the AI are allowed to do.

WORKORDER_01 section 25 asks for basic parent controls and is explicit about not
over-engineering them. So this is one small file: a set of named permissions, three
states each, persisted as plain JSON, with a PIN in front of changing them.

Two conventions this follows from elsewhere in the codebase:

**The permissions are data, not a hand-written list of checkboxes.** :data:`GATES`
describes each one -- its label, its explanation, and whether "Ask Parent" is meaningful
for it -- and Settings renders whatever is in the table. This is the same rule
``profiles.json`` and ``models.json`` follow (section 3), and the reason Phase 7 can add
a consumer for ``arduino_upload`` without touching the UI.

**Unanswered means no.** :meth:`ParentControls.gate` returns False for an ``ask``
permission when nothing is available to ask, rather than assuming consent. That is the
same fail-closed stance ``process_sandbox`` takes: an application that cannot obtain
permission has not been given it.

Nothing here is a secret store. The file this writes holds switch positions and is
readable by anyone on the Mac; the API keys are in the Keychain
(:mod:`opennest.security.keychain`), and :func:`_reject_credentials` makes sure a key
never reaches this file by accident.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path

from opennest import paths
from opennest.versioning import secret_scanner

#: The three positions a permission can be in. WORKORDER_01 section 35A step 6 shows all
#: three in the setup wizard: "OFF", "ON", and "Ask Parent".
ALLOW = "allow"
ASK = "ask"
DENY = "deny"
STATES: tuple[str, ...] = (ALLOW, ASK, DENY)

STATE_LABELS = {ALLOW: "Allow", ASK: "Ask Parent", DENY: "Off"}


@dataclass(frozen=True)
class Gate:
    """One parent-controlled permission, as Settings should present it."""

    name: str
    label: str
    explanation: str
    #: False for permissions where a mid-flight prompt makes no sense.
    supports_ask: bool = True


#: WORKORDER_01 section 25's list, plus the two switches section 35A step 6 sets up.
#: ``cloud_ai`` is deliberately not here: it is a master switch with its own
#: "ask before using" flag (sections 22 and 24), not a three-state permission.
GATES: tuple[Gate, ...] = (
    Gate(
        "external_requests",
        "External websites and API requests",
        "Whether a project may reach the internet while it runs. Off means the "
        "project is run with no network at all.",
    ),
    Gate(
        "package_installation",
        "Installing extra Python packages",
        "Whether Open Nest may add a package that is not already installed.",
    ),
    Gate(
        "arduino_upload",
        "Uploading to an Arduino board",
        "Whether Open Nest may send a compiled program to a connected device.",
    ),
    Gate(
        "raspberry_pi_deployment",
        "Deploying to a Raspberry Pi",
        "Whether Open Nest may copy a project onto a Pi and run it there.",
    ),
)

GATES_BY_NAME = {gate.name: gate for gate in GATES}


@dataclass
class ParentControls:
    """The parent-controlled settings, with the defaults setup starts from.

    Every default is the cautious one. WORKORDER_01 section 35A step 6 sets cloud AI and
    external requests to OFF and the three actions to "Ask Parent"; section 2311 requires
    the cloud master switch to default OFF "unless explicitly enabled during setup".
    """

    #: The master switch of section 2311. Off means no cloud request is made at all,
    #: whether or not a key is stored -- turning cloud off must not require deleting keys.
    allow_cloud_ai: bool = False
    #: Section 22's "Ask before using cloud AI", and the trigger for section 24's warning.
    ask_before_cloud_ai: bool = True

    external_requests: str = DENY
    package_installation: str = ASK
    arduino_upload: str = ASK
    raspberry_pi_deployment: str = ASK

    #: Section 35A step 6 shows this ON. Phase 9 owns what it does.
    github_private_backup: bool = True

    #: Where this was loaded from, so save() round-trips without the caller tracking it.
    path: Path | None = field(default=None, compare=False, repr=False)

    # -- persistence --------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> ParentControls:
        """Read the saved settings. Missing or damaged file means the safe defaults.

        A corrupted settings file must not stop Open Nest opening, and must not fail
        *open* either: unreadable JSON gives the same defaults a fresh install has, which
        are the restrictive ones.
        """
        target = Path(path) if path is not None else paths.settings_file()
        controls = cls(path=target)
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return controls
        if not isinstance(raw, dict):
            return controls
        for entry in fields(cls):
            if entry.name == "path" or entry.name not in raw:
                continue
            value = raw[entry.name]
            # The default's type is what a setting is allowed to be. Anything else in
            # the file -- a string where a switch belongs, a state nobody defined -- is
            # ignored in favour of the safe default rather than trusted.
            if isinstance(getattr(controls, entry.name), bool):
                if isinstance(value, bool):
                    setattr(controls, entry.name, value)
            elif isinstance(value, str) and value in STATES:
                setattr(controls, entry.name, value)
        return controls

    def save(self, path: Path | None = None) -> Path:
        """Write the settings. Refuses anything credential-shaped (section 22)."""
        target = Path(path) if path is not None else (self.path or paths.settings_file())
        payload = self.as_dict()
        _reject_credentials(payload)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Written via a temporary file so an interrupted save cannot leave a truncated
        # settings file, which load() would read as "all defaults" -- silently turning a
        # parent's choices off.
        scratch = target.with_suffix(target.suffix + ".tmp")
        scratch.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        scratch.replace(target)
        self.path = target
        return target

    def as_dict(self) -> dict:
        return {
            entry.name: getattr(self, entry.name)
            for entry in fields(self)
            if entry.name != "path"
        }

    # -- decisions ----------------------------------------------------------

    def state(self, name: str) -> str:
        """The configured position of one three-state permission."""
        if name not in GATES_BY_NAME:
            raise KeyError(f"There is no parent control called {name!r}.")
        return getattr(self, name)

    def set_state(self, name: str, state: str) -> None:
        if name not in GATES_BY_NAME:
            raise KeyError(f"There is no parent control called {name!r}.")
        if state not in STATES:
            raise ValueError(f"{state!r} is not one of: {', '.join(STATES)}.")
        setattr(self, name, state)

    def gate(self, name: str, approver: Callable[[Gate], bool] | None = None) -> bool:
        """Whether this action may proceed now.

        ``approver`` is how "Ask Parent" is answered -- the UI passes a function that
        shows the PIN prompt. With no approver, an ``ask`` permission is refused: an
        application that could not ask has not been told yes.
        """
        state = self.state(name)
        if state == ALLOW:
            return True
        if state == DENY:
            return False
        if approver is None:
            return False
        return bool(approver(GATES_BY_NAME[name]))

    # -- cloud --------------------------------------------------------------

    def cloud_allowed(self) -> bool:
        """The master switch. Checked before a cloud provider is even built."""
        return bool(self.allow_cloud_ai)

    def cloud_needs_confirmation(self) -> bool:
        """Whether section 24's warning is shown before each cloud use."""
        return bool(self.allow_cloud_ai and self.ask_before_cloud_ai)

    def network_for_runs(self, approver: Callable[[Gate], bool] | None = None) -> bool:
        """What ``allow_network`` should be for a project run.

        This is the value ``process_sandbox.build_profile`` has carried since Phase 2
        with nothing to supply it. Section 25 is what supplies it.
        """
        return self.gate("external_requests", approver)


def _reject_credentials(payload: dict) -> None:
    """Stop a key reaching the settings file.

    Nothing should ever put one here, which is exactly why it is worth checking: the
    failure this guards against is a future change that stores "the OpenAI key" in
    settings for convenience. Section 22 lists plaintext preferences by name.
    """
    findings = secret_scanner.scan_text(json.dumps(payload, indent=2), "settings.json")
    if findings:
        raise ValueError(
            "Open Nest refused to save settings because something in them looks like a "
            "password or key. Keys belong in the macOS Keychain."
        )


_loaded: ParentControls | None = None


def current() -> ParentControls:
    """The application's parent controls, read once per session."""
    global _loaded
    if _loaded is None:
        _loaded = ParentControls.load()
    return _loaded


def reload() -> ParentControls:
    """Re-read from disk. Used after Settings saves, and by tests."""
    global _loaded
    _loaded = ParentControls.load()
    return _loaded
