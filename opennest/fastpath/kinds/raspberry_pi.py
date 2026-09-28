"""Raspberry Pi: what Open Nest can read about the project, and the changes it makes.

The starter keeps the thinking (when to blink, how many times) apart from the pins, and
runs on a Mac with pretend GPIO -- so every change here can be verified the same way a
child tests it: run it on this Mac and read what it printed. A run that prints every
blink it was asked for, on the pin it was asked for, is evidence; a run that timed out
or printed something else is not.

Same rule as Arduino for pins: only from the child's message, BCM 2-27, never 0 or 1
(the Pi's ID EEPROM pins), and never one already in use. Anything with a motor or a
sensor is Gary's, with guidance, because the right answer depends on the part.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from opennest.agent.tools import Step
from opennest.execution.python_runner import run_project
from opennest.fastpath import slots
from opennest.fastpath.classifier import OTHER, Option
from opennest.fastpath.kinds import (
    AlreadyDone,
    Change,
    Context,
    Facts,
    NeedsAnswer,
    NotApplicable,
    confident,
)

_RUN_SECONDS = 30


@dataclass(frozen=True)
class Const:
    name: str
    value: object
    line: int
    start: int
    end: int


def _chars(line: str, byte_col: int) -> int:
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def facts(project, attachments=()) -> Facts:
    path = f"src/{project.manifest.entrypoint}"
    values: dict = {"entry": path}
    file = project.directory / path
    if not file.is_file():
        return Facts(values)
    source = file.read_text(encoding="utf-8")
    values["source"] = source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return Facts(values)
    lines = source.split("\n")
    constants = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id.isupper()
                and node.lineno == node.end_lineno):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            line = lines[node.lineno - 1]
            constants[node.targets[0].id] = Const(
                node.targets[0].id, value, node.lineno - 1,
                _chars(line, node.value.col_offset), _chars(line, node.value.end_col_offset))
    values["constants"] = constants or None
    for name in ("LED_PIN", "BLINKS"):
        if name in constants:
            values[name.lower()] = constants[name]
    if "ON_SECONDS" in constants and "OFF_SECONDS" in constants:
        values["blink_times"] = True
    values["pins_used"] = tuple(str(c.value) for n, c in constants.items()
                                if n.endswith("_PIN")) or None
    return Facts(values)


def where(facts: Facts) -> str:
    constants = facts.get("constants") or {}
    notes = ["WHAT IS IN THIS PROJECT RIGHT NOW"]
    if constants:
        notes.append("- Named constants at the top of " + facts.get("entry") + ": "
                     + ", ".join(f"{c.name} = {c.value!r}" for c in constants.values()))
    notes.append("- The pin code lives in the Lights class, which pretends on a Mac and uses "
                 "RPi.GPIO on a Pi. Put any new part behind the same kind of class, so the "
                 "project still runs on this Mac.")
    if facts.get("pins_used"):
        notes.append(f"- BCM pins in use: {', '.join(facts.get('pins_used'))}.")
    return "\n".join(notes)


def _replace(source: str, const: Const, text: str) -> str:
    lines = source.split("\n")
    line = lines[const.line]
    lines[const.line] = line[:const.start] + text + line[const.end:]
    return "\n".join(lines)


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0")


def blink_timing(ctx: Context) -> Change:
    """Faster or slower blinking -- the on time, the off time, or both, as the child said.

    "Stay on for 1 second" changes only the on time and "a longer gap" only the off
    time; "blink faster" changes both. A message that pulls them different ways ("on
    longer and off shorter") is not one direction, and goes to Gary.
    """
    if not ctx.facts.has("blink_times"):
        raise NotApplicable("no ON_SECONDS and OFF_SECONDS")
    constants = ctx.facts.get("constants")
    on, off = constants["ON_SECONDS"], constants["OFF_SECONDS"]
    old_on, old_off = float(on.value), float(off.value)
    halves = slots.on_or_off(ctx.request)
    lowered = ctx.request.lower()
    if halves == ("on", "off") and re.search(r"\bon\b.*\b(longer|shorter)\b.*\boff\b", lowered):
        raise NotApplicable("the on and off times are asked to move different ways")
    duration = slots.duration_in(ctx.request)
    amount = slots.explicit_amount(ctx.request)
    if duration is not None:
        seconds, whole_cycle = duration
        each = seconds / 2 if whole_cycle and halves == ("on", "off") else seconds
        new_on = new_off = each
    elif amount is not None and amount.value is not None:
        # A bare number that big is milliseconds, the way a child reads a timer.
        new_on = new_off = float(amount.value) / (1000 if amount.value > 20 else 1)
    else:
        if ctx.choose is None:
            raise NotApplicable("no model to ask which way")
        answer = confident(ctx.choose("Should the LED blink faster or slower?", [
            Option("faster", "faster, quicker or shorter"),
            Option("slower", "slower or longer"),
            Option(OTHER, "neither, or something else"),
        ]))
        if answer not in ("faster", "slower"):
            raise NotApplicable("not sure which way")
        factor = 0.5 if answer == "faster" else 2.0
        if amount is not None and amount.factor:
            factor = 1 / amount.factor if answer == "faster" else amount.factor
        new_on, new_off = old_on * factor, old_off * factor
    if "on" not in halves:
        new_on = old_on
    if "off" not in halves:
        new_off = old_off
    new_on, new_off = (round(max(0.05, min(5.0, value)), 2) for value in (new_on, new_off))
    if (new_on, new_off) == (old_on, old_off):
        raise NotApplicable("the timing would not change")
    source = _replace(ctx.facts.get("source"), off, _number(new_off))
    source = _replace(source, on, _number(new_on))
    return Change(files={ctx.facts.get("entry"): source},
                  values={"on": _number(new_on), "off": _number(new_off),
                          "old_on": _number(old_on), "old_off": _number(old_off)},
                  expect={"constants": {"ON_SECONDS": new_on, "OFF_SECONDS": new_off}})


def blink_count(ctx: Context) -> Change:
    """How many times it blinks: a number the child gave, or double / half."""
    const = ctx.facts.get("blinks")
    if const is None or not isinstance(const.value, int):
        raise NotApplicable("no BLINKS number")
    count = slots.count_in(ctx.request)
    amount = slots.explicit_amount(ctx.request)
    if count is None and amount is not None and amount.value is not None:
        count = int(amount.value)
    if count is None:
        match = re.search(r"\b(\d{1,3})\s*times\b", ctx.request.lower())
        count = int(match.group(1)) if match else None
    if count is None:
        if ctx.choose is None:
            raise NotApplicable("no model to ask")
        answer = confident(ctx.choose("Should it blink more times or fewer?", [
            Option("more", "more times"), Option("fewer", "fewer times"),
            Option(OTHER, "neither, or something else")]))
        if answer not in ("more", "fewer"):
            raise NotApplicable("not sure how many")
        count = const.value * 2 if answer == "more" else max(1, const.value // 2)
    count = max(1, min(100, count))
    if count == const.value:
        raise AlreadyDone(f"It already blinks {count} times.")
    return Change(files={ctx.facts.get("entry"): _replace(ctx.facts.get("source"), const,
                                                          str(count))},
                  values={"count": str(count), "old": str(const.value)},
                  expect={"constants": {"BLINKS": count}})


def led_pin(ctx: Context) -> Change:
    """Move the LED to the pin the child named."""
    const = ctx.facts.get("led_pin")
    if const is None:
        raise NotApplicable("no LED_PIN")
    pin = slots.pin_in(ctx.request)
    if pin is None:
        raise NeedsAnswer("the message does not say which pin to use")
    if pin in (0, 1):
        raise NeedsAnswer(f"BCM pin {pin} is reserved on a Raspberry Pi")
    if not 2 <= pin <= 27:
        raise NeedsAnswer(f"BCM {pin} is not a GPIO pin on a Raspberry Pi")
    if pin == const.value:
        raise AlreadyDone(f"The LED is already on BCM pin {pin}.")
    if str(pin) in (ctx.facts.get("pins_used") or ()):
        raise NeedsAnswer(f"pin {pin} is already used by something else")
    return Change(files={ctx.facts.get("entry"): _replace(ctx.facts.get("source"), const,
                                                          str(pin))},
                  values={"pin": str(pin), "old": str(const.value)},
                  expect={"constants": {"LED_PIN": pin}})


OPS = {
    "blink_timing": blink_timing,
    "blink_count": blink_count,
    "led_pin": led_pin,
}


# ------------------------------------------------------------------------ checks

def _run(ctx):
    """Run it the way Test on Mac does, but to the end: it is a short batch here."""
    def run():
        profile = ctx.project.profile
        # Not a tool call -- it runs to the end rather than as Test on Mac does -- so it
        # reports itself, or the chat would go quiet for the whole run.
        ctx.toolbox.report(Step("tool", "running it on this Mac with pretend pins"))
        return run_project(ctx.project.directory, profile.run_command,
                           python_executable=ctx.toolbox.python_executable,
                           timeout=_RUN_SECONDS)
    return ctx.once("run", run)


def _check_runs(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    result = _run(ctx)
    if result.exit_code is None and not result.timed_out:
        return Check("runs_on_mac", UNAVAILABLE, result.stderr[:200])
    if result.timed_out:
        return Check("runs_on_mac", UNAVAILABLE, "it runs until it is stopped")
    if result.ok:
        return Check("runs_on_mac", PASS)
    return Check("runs_on_mac", FAIL, result.failure_text[-800:])


def _check_constants(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    constants = ctx.facts_after.get("constants") or {}
    for name, wanted in (ctx.expect.get("constants") or {}).items():
        if name not in constants or constants[name].value != wanted:
            return Check("value_set", FAIL, f"{name} is not {wanted}")
    return Check("value_set", PASS)


def _check_blinks(ctx):
    """It printed every blink it was asked for, on the pin it was asked for."""
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    result = _run(ctx)
    if not result.ok:
        return Check("prints_blinks", UNAVAILABLE, "it did not finish")
    constants = ctx.facts_after.get("constants") or {}
    blinks = getattr(constants.get("BLINKS"), "value", None)
    pin = getattr(constants.get("LED_PIN"), "value", None)
    out = result.stdout
    if blinks and f"Blink {blinks} of {blinks}" not in out:
        return Check("prints_blinks", FAIL, f"it never printed blink {blinks} of {blinks}")
    if pin is not None and f"pin {pin}" not in out:
        return Check("prints_blinks", FAIL, f"it never mentioned pin {pin}")
    ctx._cache["blinked"] = blinks
    return Check("prints_blinks", PASS, f"{blinks} blinks on pin {pin}")


CHECKS = {
    "runs_on_mac": _check_runs,
    "value_set": _check_constants,
    "prints_blinks": _check_blinks,
}


#: How a change Gary makes here is checked, for his context (router._context).
CHECKED = ("Test a change with run_project: it runs on this Mac with pretend pins.")


def verifiable(project) -> bool:
    """Whether this project can run the file on this Mac -- the check these rely on."""
    return project.profile.can_run and "run_project" in project.profile.tools


def confirmation(verification, project=None) -> str:
    from opennest.fastpath.verifier import PASS

    if verification.status_of("prints_blinks") == PASS:
        count = verification.evidence.get("blinked")
        return (f"I ran it on this Mac with pretend pins, and it printed every blink -- "
                f"{count} of them. On the Pi it will light the real LED.")
    if verification.status_of("runs_on_mac") == PASS:
        return "I ran it on this Mac with pretend pins, and it finished cleanly."
    button = getattr(getattr(project, "profile", None), "run_label", "Test on Mac")
    return f"I haven't been able to run it here, so press {button} to try it."


def brief(facts: Facts) -> str:
    """What the classifier is told about the project, from the facts alone."""
    pin, blinks = facts.get("led_pin"), facts.get("blinks")
    if pin is None:
        return ""
    count = f", {blinks.value} times" if blinks is not None else ""
    return (f"It blinks an LED on BCM pin {pin.value}{count}, and runs on this Mac with "
            "pretend pins.")
