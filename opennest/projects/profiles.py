"""Project profiles, loaded from configuration.

WORKORDER_01 section 5: a profile defines the system prompt, starter template, allowed
tools, package allowlist, run and compile commands, asset types and starter ideas. It is
data. Adding a project type should not require changing Python.
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
    starter_template: str
    entrypoint: str
    run_label: str
    tools: tuple[str, ...]
    #: "interactive" projects stay on screen until the child closes them (games, Pi
    #: loops); "batch" projects run to completion and are captured (analyses, compiles).
    run_mode: str = "batch"
    packages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    asset_types: tuple[str, ...] = ()
    starter_ideas: tuple[str, ...] = ()
    run_command: tuple[str, ...] | None = None
    compile_command: tuple[str, ...] | None = None

    @property
    def can_run(self) -> bool:
        return self.run_command is not None

    @property
    def is_interactive(self) -> bool:
        return self.run_mode == "interactive"

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
        starter_template=raw["starter_template"],
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
    )


@lru_cache(maxsize=1)
def load_profiles(config_path: Path | None = None) -> ProfileSet:
    path = config_path or (paths.config_dir() / "profiles.json")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return ProfileSet(tuple(_build(entry) for entry in raw["profiles"]))


def get_profile(profile_id: str) -> Profile:
    return load_profiles().get(profile_id)
