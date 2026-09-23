"""Project profiles, loaded from configuration.

WORKORDER_01 section 5: a profile defines the system prompt, starter kits, allowed
tools, package allowlist, run and compile commands, asset types and starter ideas. It is
data. Adding a project type should not require changing Python.

Phase 11 (config schema 2) replaced one field with two. ``starter_template`` named a
single directory that was always copied in; ``starters`` is the list of kit ids a profile
offers, and ``starter_default`` names which of them a new project begins with -- or
``None`` for empty, which is how starting with nothing became possible. A profile may
offer no kits at all: the schema allows a starter, it does not require one. See
:mod:`opennest.projects.starters`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from opennest import paths


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    symbol: str
    tagline: str
    prompt_file: str
    default_language: str
    #: Starter kit ids this profile offers, most useful first. May be empty.
    starters: tuple[str, ...]
    entrypoint: str
    run_label: str
    tools: tuple[str, ...]
    #: Which kit a new project begins with when nobody chooses. ``None`` means the
    #: project begins empty, and Blank uses that deliberately. Kept as an explicit
    #: ``null`` in the configuration rather than an empty string, so no consumer has to
    #: remember that a falsy string is a sentinel.
    starter_default: str | None = None
    #: "interactive" projects stay on screen until the child closes them (games, Pi
    #: loops); "batch" projects run to completion and are captured (analyses, compiles);
    #: "preview" projects are opened rather than executed (a website); "generate"
    #: projects run nothing at all -- see :attr:`generates`.
    run_mode: str = "batch"
    packages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    asset_types: tuple[str, ...] = ()
    starter_ideas: tuple[str, ...] = ()
    run_command: tuple[str, ...] | None = None
    compile_command: tuple[str, ...] | None = None
    #: Which cloud provider this profile cannot work without, if any. Image Creation
    #: needs OpenAI; every other profile works with the local model and no key.
    requires_cloud_provider: str | None = None
    #: Image generation, for a "generate" profile. Deliberately not a models.json entry
    #: (PLAN.md D6): a catalogue entry is something that answers a conversation.
    image_provider: str | None = None
    image_model: str | None = None

    @property
    def can_run(self) -> bool:
        return self.run_command is not None

    @property
    def can_compile(self) -> bool:
        return self.compile_command is not None

    @property
    def is_interactive(self) -> bool:
        return self.run_mode == "interactive"

    @property
    def generates(self) -> bool:
        """Whether pressing the main button asks a service for something.

        The distinction that matters: a run or a compile executes something inside the
        process sandbox, and generation happens in the application instead. The sandbox
        denies network, so a child's own code could never call an image service -- which
        is why this is not simply another run command.
        """
        return self.run_mode == "generate"

    @property
    def previews(self) -> bool:
        """Whether pressing the main button opens the project rather than running it.

        A website is not executed: there is no process, no sandbox profile and no exit
        code, because the files *are* the thing. Open Nest shows the page instead, with
        network access refused at the request level -- see
        :mod:`opennest.execution.web_preview`. Separate from ``generate`` because that
        one calls a service and this one touches nothing outside the project.
        """
        return self.run_mode == "preview"

    def system_prompt(self) -> str:
        return (paths.prompts_dir() / self.prompt_file).read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class ProfileSet:
    profiles: tuple[Profile, ...] = field(default_factory=tuple)

    def __iter__(self):
        return iter(self.profiles)

    def __len__(self) -> int:
        return len(self.profiles)

    def get(self, profile_id: str) -> Profile:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        known = ", ".join(p.id for p in self.profiles)
        raise KeyError(f"Unknown project profile {profile_id!r}. Known profiles: {known}")


def _as_tuple(value) -> tuple:
    if value is None:
        return ()
    return tuple(value)


def _build(raw: dict) -> Profile:
    return Profile(
        id=raw["id"],
        name=raw["name"],
        symbol=raw.get("symbol", ""),
        tagline=raw.get("tagline", ""),
        prompt_file=raw["prompt_file"],
        default_language=raw["default_language"],
        starters=_as_tuple(raw.get("starters")),
        starter_default=raw.get("starter_default"),
        entrypoint=raw["entrypoint"],
        run_label=raw["run_label"],
        run_mode=raw.get("run_mode", "batch"),
        tools=_as_tuple(raw["tools"]),
        packages=_as_tuple(raw.get("packages")),
        frameworks=_as_tuple(raw.get("frameworks")),
        asset_types=_as_tuple(raw.get("asset_types")),
        starter_ideas=_as_tuple(raw.get("starter_ideas")),
        run_command=_as_tuple(raw["run_command"]) or None if raw.get("run_command") else None,
        compile_command=(
            _as_tuple(raw["compile_command"]) or None if raw.get("compile_command") else None
        ),
        requires_cloud_provider=raw.get("requires_cloud_provider"),
        image_provider=raw.get("image_provider"),
        image_model=raw.get("image_model"),
    )


@lru_cache(maxsize=1)
def load_profiles(config_path: Path | None = None) -> ProfileSet:
    path = config_path or (paths.config_dir() / "profiles.json")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return ProfileSet(tuple(_build(entry) for entry in raw["profiles"]))


def get_profile(profile_id: str) -> Profile:
    return load_profiles().get(profile_id)
