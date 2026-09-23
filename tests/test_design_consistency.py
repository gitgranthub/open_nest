"""The design system holds together — checked mechanically rather than by eye.

`opennest/ui/theme.py` opens with a promise: *"Widgets should never hard-code a colour.
Use these tokens, or a ``role`` property that the stylesheet below knows about."* Phase
10D is where that stops being a comment and becomes a test, because both halves fail
silently:

* a ``role`` the stylesheet does not know about is not an error. Qt applies no style and
  the widget renders in the default system appearance — legible, plausible, and wrong in
  a way that only shows up beside a correctly styled sibling. A typo produces it;
  renaming a rule in the stylesheet and missing a call site produces it;
* a hard-coded colour looks right in whichever scheme it was written against and is
  invisibly wrong in the other. Nothing in the suite loads both schemes.

The reverse direction — a style nobody uses — is deliberately **not** asserted, and the
reason is a measurement trap worth keeping. A first pass reported ``idle``, ``ready`` and
``working`` as unused dead styles. They are the most-used states in the product;
``common.status_row`` sets them from a *variable*, so a scan for literals cannot see
them. Dead style is found by reading, not by grepping.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "opennest"
THEME = PACKAGE / "ui" / "theme.py"

#: Starter kits are a child's own code and are excluded from ruff for the same
#: reason — they are not application source.
SKIP_PARTS = {"__pycache__", "starters"}


def _modules():
    for path in sorted(PACKAGE.rglob("*.py")):
        if SKIP_PARTS & set(path.parts):
            continue
        yield path


def _styled(kind: str) -> set[str]:
    """Every value the stylesheet has a selector for, e.g. ``role="panel"``."""
    return set(re.findall(rf'\[{kind}="([^"]+)"\]', THEME.read_text(encoding="utf-8")))


def _properties_set(kind: str) -> dict[str, list[str]]:
    """Every literal ``setProperty(kind, value)`` in the package, with where it is."""
    found: dict[str, list[str]] = {}
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setProperty"
                and len(node.args) == 2
                and all(isinstance(arg, ast.Constant) for arg in node.args)
            ):
                continue
            key, value = node.args[0].value, node.args[1].value
            if key == kind and isinstance(value, str):
                found.setdefault(value, []).append(
                    f"{path.relative_to(PACKAGE.parent)}:{node.lineno}"
                )
    return found


@pytest.mark.parametrize("kind", ["role", "state"])
def test_every_property_a_widget_sets_is_actually_styled(kind):
    """An unstyled ``role`` renders in the system appearance instead of the theme.

    Silent by construction: Qt does not warn, the widget still draws, and it only looks
    wrong next to a sibling that matched. This is the check that turns a typo into a
    failure.
    """
    styled = _styled(kind)
    unstyled = {
        value: where
        for value, where in _properties_set(kind).items()
        if value not in styled
    }
    assert not unstyled, (
        f"{kind} values with no rule in theme.py: "
        + "; ".join(f"{v!r} at {', '.join(w)}" for v, w in sorted(unstyled.items()))
    )


def test_no_widget_hard_codes_a_colour():
    """``theme.py``'s opening promise, enforced.

    A literal colour is correct in whichever scheme its author had open and wrong in the
    other, and the suite never renders both. The palette is the only place a colour is
    allowed to exist.
    """
    offenders = []
    for path in _modules():
        if path == THEME:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"#[0-9a-fA-F]{6}\b", line):
                offenders.append(f"{path.relative_to(PACKAGE.parent)}:{number}: {line.strip()}")
    assert not offenders, "hard-coded colours outside the palette:\n" + "\n".join(offenders)


def test_only_the_theme_sets_a_stylesheet():
    """One stylesheet, applied once, or light and dark stop being reliable.

    A local ``setStyleSheet`` overrides the cascade for that widget and its children,
    which is how one panel ends up not following the system appearance.
    """
    offenders = []
    for path in _modules():
        if path == THEME:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "setStyleSheet" in line and not line.strip().startswith("#"):
                offenders.append(f"{path.relative_to(PACKAGE.parent)}:{number}")
    assert not offenders, "setStyleSheet outside theme.py: " + ", ".join(offenders)


def test_every_dialog_marks_its_primary_action():
    """A surface with a choice should show which one is the way through.

    Found in 10D by rendering the device-flow dialog: ``Connect GitHub`` and ``Cancel``
    were visually identical, so a parent had to read both to find the way forward. Every
    other action surface already marked its primary -- Settings' Done, the wizard's
    Continue, the Workbench's Send and Run, the migration dialog's Update -- which is
    what made the omission a consistency defect rather than a style preference.

    Dialogs using ``QDialogButtonBox`` are exempt: Qt marks the default button itself,
    which is the platform convention and is why ``new_project`` uses one.
    """
    offenders = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef) and _subclasses_dialog(node)):
                continue
            calls = [
                child.func.id
                for child in ast.walk(node)
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
            ]
            if "QDialogButtonBox" in calls:
                continue
            if calls.count("QPushButton") < 2:
                continue
            # Checked by walking the tree rather than by searching ``ast.unparse``:
            # unparse renders literals in single quotes, so a substring search for
            # '"role", "primary"' silently matches nothing and reports every dialog as
            # an offender -- including ones that plainly do set it.
            if not _sets_primary(node):
                offenders.append(f"{path.relative_to(PACKAGE.parent)}:{node.name}")
    assert not offenders, (
        "dialogs offering a choice without marking the primary action: "
        + ", ".join(offenders)
    )


def _sets_primary(node: ast.ClassDef) -> bool:
    """Whether anything inside this class calls ``setProperty("role", "primary")``."""
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "setProperty"
            and len(child.args) == 2
            and all(isinstance(arg, ast.Constant) for arg in child.args)
            and child.args[0].value == "role"
            and child.args[1].value == "primary"
        ):
            return True
    return False


def _subclasses_dialog(node: ast.ClassDef) -> bool:
    return any(
        (isinstance(base, ast.Name) and base.id == "QDialog")
        or (isinstance(base, ast.Attribute) and base.attr == "QDialog")
        for base in node.bases
    )


def test_both_palettes_define_every_colour():
    """Dark is a complete scheme, not light with a few overrides.

    ``Palette`` is a frozen dataclass so a missing field is a construction error, but a
    field accidentally sharing light's value is not. This catches the copy-paste.
    """
    from opennest.ui import theme

    shared = [
        field
        for field in theme.LIGHT.__dataclass_fields__
        if getattr(theme.LIGHT, field) == getattr(theme.DARK, field)
    ]
    assert not shared, f"dark reuses light's value for: {shared}"


def test_the_stylesheet_builds_for_both_schemes():
    """Every token the template references exists in both palettes.

    A stylesheet is a format string, so a token added to the template and not to
    ``Palette`` raises — but only when something actually renders that scheme, which in
    practice means on a user's Mac rather than here.
    """
    from opennest.ui import theme

    for palette in (theme.LIGHT, theme.DARK):
        # A token missing from Palette raises here rather than returning a bad sheet.
        sheet = theme.stylesheet(palette)
        # Checking for a surviving *placeholder*, not for "{": the template escapes CSS
        # braces as "{{", so every rule block legitimately contains one after
        # formatting. A leftover looks like "{p.surface}" or "{radius}".
        leftover = re.findall(r"\{[a-z_][a-z_.]*\}", sheet)
        assert not leftover, f"unsubstituted tokens in the stylesheet: {leftover}"
        assert palette.window in sheet, "the palette is not reaching the stylesheet"
        assert len(sheet) > 1000
