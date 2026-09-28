"""What a recipe must be seen to do before anyone says it did.

Every recipe names its checks, and every check answers one of three ways:

- ``pass`` -- measured, and it did what the recipe says it does
- ``fail`` -- measured, and it did not. The change is rolled back and Gary takes over.
- ``unavailable`` -- could not be measured here: no sandbox, no toolchain, no board
  chosen. Never counted as a pass, and never described as one to the child.

The checks themselves live with the project type they understand
(``fastpath.kinds.<profile>.CHECKS``). What is shared is the discipline: a check that
could not run is reported as not run, which is SPIKES.md section 17F's rule for the
drivers applied to the product.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PASS = "pass"
FAIL = "fail"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class VerifyContext:
    """What a check may look at. Expensive evidence is gathered once and shared."""

    project: Any
    toolbox: Any
    expect: dict
    facts_after: Any = None
    _cache: dict = field(default_factory=dict)

    def once(self, key: str, compute: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = compute()
        return self._cache[key]


@dataclass
class Verification:
    checks: list[Check]
    #: Evidence the checks gathered, for the Turn record: a playtest, a run.
    evidence: dict = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return any(check.status == FAIL for check in self.checks)

    def status_of(self, name: str) -> str:
        return next((c.status for c in self.checks if c.name == name), UNAVAILABLE)

    def as_record(self) -> list[dict]:
        return [{"check": c.name, "status": c.status, "detail": c.detail[:300]}
                for c in self.checks]


class RecipeVerifier:
    """Runs a recipe's checks against the project as it now is."""

    def verify(self, recipe, kind, project, toolbox, expect: dict) -> Verification:
        context = VerifyContext(project=project, toolbox=toolbox, expect=dict(expect))
        context.facts_after = kind.facts(project)
        checks = []
        for name in recipe.verify:
            check = kind.CHECKS.get(name)
            if check is None:
                checks.append(Check(name, FAIL, "no such check"))
                continue
            try:
                checks.append(check(context))
            except Exception as exc:  # noqa: BLE001 - a broken check proves nothing
                checks.append(Check(name, UNAVAILABLE, f"the check could not run: {exc}"))
        evidence = {key: value for key, value in context._cache.items()}
        return Verification(checks=checks, evidence=evidence)
