"""The moments Open Nest stops and asks: cloud use, and parent permission.

Three dialogs, kept together because they are the same idea at different scales and
share one rule -- **say what will actually happen, in the fewest words that are still
true.** WORKORDER_01 section 24 is explicit that the cloud warning must not imply the
conversation stays on the Mac, and DESIGN_DOC section 20 asks for copy that is short,
calm and confident. A dialog that soothes is worse than no dialog.

The parent gate degrades honestly. If no PIN has been set -- and none has, until the
Phase 8 wizard collects one -- the gate is still shown, as a plain confirmation. It
surfaces the decision to whoever is at the keyboard, which is the real protection
available, and Settings says so in as many words rather than implying a lock that is not
there.
"""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from opennest import APP_NAME
from opennest.ai.provider import ModelInfo
from opennest.security import keychain
from opennest.security.permissions import Gate

#: WORKORDER_01 section 23, with the product renamed. Shown wherever a key is entered.
API_KEY_EXPLANATION = (
    "An API key is a secret password that lets Open Nest use an AI service on the "
    "internet.\n\n"
    "A parent can add one here.\n\n"
    "You should never send an API key to another person or put it inside one of your "
    "projects."
)


def company_for(info: ModelInfo) -> str:
    """Who the information actually goes to.

    Distinct from the model's name on purpose: section 24's warning names the company
    ("sent to Anthropic"), not the product ("sent to Claude"). Conflating them is how a
    warning stops being informative.
    """
    return keychain.PROVIDER_LABELS.get(info.provider, info.provider.title())


def cloud_warning_text(info: ModelInfo) -> str:
    """Section 24's warning, for one model. Separated out so it can be tested as text."""
    company = company_for(info)
    lines = [
        f"{info.name} uses the internet.",
        "",
        f"Information from this project may be sent to {company}.",
    ]
    if info.may_cost_money:
        lines += ["", f"Using {info.name} may also cost money."]
    return "\n".join(lines)


def confirm_cloud_use(parent, info: ModelInfo) -> bool:
    """Section 24's "USE CLOUD AI?" step. True when the child may go ahead."""
    box = QMessageBox(parent)
    box.setWindowTitle("Use Cloud AI?")
    box.setText("Use Cloud AI?")
    box.setInformativeText(cloud_warning_text(info))
    use = box.addButton(f"Use {info.name}", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    # Cancel is the default: a dialog whose dangerous answer is one Return away is a
    # dialog that gets dismissed rather than read.
    box.setDefaultButton(box.buttons()[-1])
    box.exec()
    return box.clickedButton() is use


def ask_parent_pin(parent, credentials: keychain.Credentials | None = None,
                   *, reason: str = "") -> bool:
    """Check the parent PIN. True when it matched, or when no PIN is configured.

    The "no PIN configured" case returns True deliberately -- but only after the caller
    has shown its own confirmation. ``keychain.check_parent_pin`` answers False for an
    unset PIN precisely so that this decision is made here, once, in the layer that
    knows a human is looking at the screen.
    """
    store = credentials or keychain.default()
    if not store.parent_pin_set():
        return True

    prompt = "Enter the parent PIN"
    if reason:
        prompt = f"{reason}\n\n{prompt}"
    for remaining in (2, 1, 0):
        pin, accepted = QInputDialog.getText(
            parent, "Parent Settings", prompt, QLineEdit.EchoMode.Password
        )
        if not accepted:
            return False
        if store.check_parent_pin(pin):
            return True
        if remaining:
            prompt = f"That PIN did not match. {remaining} more "\
                     f"{'try' if remaining == 1 else 'tries'}."
    return False


def approve(parent, gate: Gate, credentials: keychain.Credentials | None = None) -> bool:
    """Answer an "Ask Parent" permission at the moment it is needed (section 25)."""
    box = QMessageBox(parent)
    box.setWindowTitle(APP_NAME)
    box.setText(f"Allow this: {gate.label.lower()}?")
    box.setInformativeText(gate.explanation + "\n\nThis needs a parent.")
    allow = box.addButton("Allow Once", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(box.buttons()[-1])
    box.exec()
    if box.clickedButton() is not allow:
        return False
    return ask_parent_pin(parent, credentials, reason=gate.label)


def explain_api_keys(parent) -> None:
    """Section 23's "What is an API key?", shown from wherever a key is entered."""
    box = QMessageBox(parent)
    box.setWindowTitle("What is an API key?")
    box.setText("What is an API key?")
    box.setInformativeText(API_KEY_EXPLANATION)
    box.exec()
