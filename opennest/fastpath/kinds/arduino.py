"""Arduino: what Open Nest can read about a sketch, and the changes the recipes make.

Hardware is where a confident wrong answer costs more than a question, and the
Arduino prompt's first rule -- never invent a pin -- is enforced here rather than hoped
for. A recipe that needs a pin takes it **only from the child's own message**, refuses
pins 0 and 1 (the board's USB connection) and pins already in use, and otherwise steps
aside so Gary asks. Every part it adds gets a row in ``wiring.md`` saying what connects
where, and an LED's row says it needs a resistor.

Verification is a real compile through the same ``compile_project`` tool a child's
Compile button uses. With no board chosen, or no toolchain installed, that check is
*unavailable* -- never passed -- and the reply says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from opennest.agent.tools import ToolResult
from opennest.ai.provider import ToolCall
from opennest.fastpath import slots
from opennest.fastpath.classifier import OTHER, Option
from opennest.fastpath.kinds import (
    Change,
    Context,
    Facts,
    NeedsAnswer,
    NotApplicable,
    confident,
    game_things,
)

_CONST = re.compile(
    r"^(\s*)const\s+((?:unsigned\s+)?(?:int|long|byte|float|bool|uint8_t|uint16_t))\s+"
    r"(\w+)\s*=\s*([^;]+);"
)
_WRITE = re.compile(r"^(\s*)digitalWrite\(\s*(\w+)\s*,\s*(HIGH|LOW)\s*\);")

#: Board pins a sketch may use for a part. 0 and 1 are the USB serial connection on an
#: Uno-class board: wiring something there breaks uploading.
_DIGITAL = {str(n) for n in range(2, 14)}
_ANALOG = {f"A{n}" for n in range(6)}


@dataclass(frozen=True)
class Const:
    name: str
    type: str
    value: str
    line: int
    start: int
    end: int


def _paths(project) -> tuple[str, str]:
    sketch = f"src/{project.manifest.entrypoint}"
    return sketch, sketch.rsplit("/", 1)[0] + "/wiring.md"


def _block(lines: list[str], header: str) -> tuple[int, int] | None:
    """(first line, closing-brace line) of ``void setup() {`` or ``void loop() {``."""
    start = next((i for i, line in enumerate(lines)
                  if re.match(rf"^\s*void\s+{header}\s*\(\s*\)\s*\{{\s*$", line)), None)
    if start is None:
        return None
    depth = 0
    for index in range(start, len(lines)):
        depth += lines[index].count("{") - lines[index].count("}")
        if depth == 0:
            return start, index
    return None


def facts(project, attachments=()) -> Facts:
    sketch_path, wiring_path = _paths(project)
    values: dict = {"entry": sketch_path, "wiring_path": wiring_path,
                    "board": project.manifest.arduino_board}
    wiring = project.directory / wiring_path
    if wiring.is_file():
        values["wiring"] = wiring.read_text(encoding="utf-8")
    sketch = project.directory / sketch_path
    if not sketch.is_file():
        return Facts(values)
    source = sketch.read_text(encoding="utf-8")
    values["source"] = source
    lines = source.split("\n")
    constants = {}
    for number, line in enumerate(lines):
        match = _CONST.match(line)
        if match:
            start = line.index(match.group(4), match.end(3))
            constants[match.group(3)] = Const(match.group(3), match.group(2),
                                              match.group(4).strip(), number, start,
                                              start + len(match.group(4).rstrip()))
    values["constants"] = constants or None
    values["last_constant"] = max((c.line for c in constants.values()), default=None)
    values["setup"] = _block(lines, "setup")
    values["loop"] = _block(lines, "loop")
    values["serial"] = True if "Serial.begin" in source else None
    values["pins_used"] = tuple(c.value for name, c in constants.items()
                                if name.endswith("_PIN")) or None
    if values["loop"]:
        start, end = values["loop"]
        values["led_writes"] = [
            (index, match.group(2), match.group(3))
            for index in range(start, end)
            if (match := _WRITE.match(lines[index])) and match.group(2) == "LED_PIN"
        ] or None
    # The blink timing is only a fact while loop() still waits on it: after a button
    # that holds the light steady, changing these numbers would change nothing.
    loop_text = "\n".join(lines[values["loop"][0]:values["loop"][1]]) if values["loop"] else ""
    if all(name in constants and re.search(rf"\b{name}\b", loop_text)
           for name in ("ON_MILLISECONDS", "OFF_MILLISECONDS")):
        values["blink_times"] = True
    return Facts(values)


def where(facts: Facts) -> str:
    notes = ["WHERE THINGS ARE IN THIS SKETCH RIGHT NOW"]
    constants = facts.get("constants") or {}
    if constants:
        notes.append("- Named constants at the top: "
                     + ", ".join(f"{c.name} = {c.value}" for c in constants.values()))
    if facts.get("pins_used"):
        notes.append(f"- Pins already in use: {', '.join(facts.get('pins_used'))}. "
                     "Pins 0 and 1 are the USB connection; never use them for a part.")
    if facts.has("setup"):
        notes.append(f"- setup() is lines {facts.get('setup')[0] + 1}-"
                     f"{facts.get('setup')[1] + 1}; loop() is lines "
                     f"{facts.get('loop')[0] + 1}-{facts.get('loop')[1] + 1}.")
    notes.append(f"- Add a row to the Connections table in {facts.get('wiring_path')} for "
                 "every part, with what it needs (an LED needs a resistor).")
    return "\n".join(notes)


# ------------------------------------------------------------------------ editing

class _Lines:
    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self.inserts: dict[int, list[str]] = {}
        self.spans: list[tuple[int, int, int, str]] = []
        self.whole: dict[int, str] = {}

    def before(self, index: int, block: list[str]) -> None:
        self.inserts.setdefault(index, []).extend(block)

    def replace(self, line: int, start: int, end: int, text: str) -> None:
        self.spans.append((line, start, end, text))

    def rewrite(self, line: int, text: str | None) -> None:
        self.whole[line] = text

    def text(self) -> str:
        lines = list(self.lines)
        for line, text in self.whole.items():
            lines[line] = text
        for line, start, end, text in sorted(self.spans, reverse=True):
            lines[line] = lines[line][:start] + text + lines[line][end:]
        for index in sorted(self.inserts, reverse=True):
            lines[index:index] = self.inserts[index]
        # A line rewritten to None is removed, after the inserts have found their places.
        return "\n".join(line for line in lines if line is not None)


def _require(facts: Facts, *names: str) -> None:
    missing = facts.missing(names)
    if missing:
        raise NotApplicable(f"the sketch does not have: {', '.join(missing)}")


def _pin(ctx: Context, part: str) -> str:
    """The pin the child named for this part. Never inferred, never defaulted."""
    pin = slots.arduino_pin_in(ctx.request)
    if pin is None:
        raise NeedsAnswer(f"the message does not say which pin the {part} is on")
    if pin in ("0", "1"):
        raise NeedsAnswer(f"pin {pin} is the board's USB connection, so the {part} needs a "
                          f"different pin")
    if pin not in _DIGITAL | _ANALOG:
        raise NeedsAnswer(f"pin {pin} is not a pin an Uno-style board has")
    if pin in (ctx.facts.get("pins_used") or ()):
        raise NeedsAnswer(f"pin {pin} is already used by something else in the sketch")
    return pin


def _wiring_row(ctx: Context, what: str, pin: str, notes: str) -> dict[str, str]:
    """A new row in wiring.md's Connections table, or nothing if the table is not there."""
    text = ctx.facts.get("wiring")
    path = ctx.facts.get("wiring_path")
    if not text:
        return {}
    lines = text.split("\n")
    heading = next((i for i, line in enumerate(lines) if line.strip() == "## Connections"),
                   None)
    if heading is None:
        return {}
    rows = [i for i in range(heading, len(lines)) if lines[i].startswith("|")]
    if not rows:
        return {}
    last = rows[0]
    for index in rows:
        if index == last or index == last + 1:
            last = index
    lines.insert(last + 1, f"| {what} | {pin} | {notes} |")
    return {path: "\n".join(lines)}


def blink_timing(ctx: Context) -> Change:
    """Faster or slower blinking -- the on time, the off time, or both, as the child said.

    "Stay on for 1 second" changes only the on time and "a longer gap" only the off
    time; "blink faster" changes both. A message that pulls them different ways ("on
    longer and off shorter") is not one direction, and goes to Gary.
    """
    _require(ctx.facts, "blink_times")
    constants = ctx.facts.get("constants")
    on, off = constants["ON_MILLISECONDS"], constants["OFF_MILLISECONDS"]
    old_on, old_off = int(on.value), int(off.value)
    halves = slots.on_or_off(ctx.request)
    lowered = ctx.request.lower()
    if halves == ("on", "off") and re.search(r"\bon\b.*\b(longer|shorter)\b.*\boff\b", lowered):
        raise NotApplicable("the on and off times are asked to move different ways")
    duration = slots.duration_in(ctx.request)
    amount = slots.explicit_amount(ctx.request)
    if duration is not None:
        seconds, whole_cycle = duration
        each = seconds / 2 if whole_cycle and halves == ("on", "off") else seconds
        new_on = new_off = round(each * 1000)
    elif amount is not None and amount.value is not None:
        new_on = new_off = int(amount.value)
    else:
        if ctx.choose is None:
            raise NotApplicable("no model to ask which way")
        answer = confident(ctx.choose("Should the light blink faster or slower?", [
            Option("faster", "faster, quicker or shorter"),
            Option("slower", "slower or longer"),
            Option(OTHER, "neither, or something else"),
        ]))
        if answer not in ("faster", "slower"):
            raise NotApplicable("not sure which way")
        factor = 0.5 if answer == "faster" else 2.0
        if amount is not None and amount.factor:
            factor = 1 / amount.factor if answer == "faster" else amount.factor
        new_on, new_off = round(old_on * factor), round(old_off * factor)
    if "on" not in halves:
        new_on = old_on
    if "off" not in halves:
        new_off = old_off
    new_on, new_off = (max(20, min(10000, value)) for value in (new_on, new_off))
    if (new_on, new_off) == (old_on, old_off):
        raise NotApplicable("the timing would not change")
    edit = _Lines(ctx.facts.get("source"))
    edit.replace(on.line, on.start, on.end, str(new_on))
    edit.replace(off.line, off.start, off.end, str(new_off))
    return Change(files={ctx.facts.get("entry"): edit.text()},
                  values={"on": str(new_on), "off": str(new_off), "old_on": str(old_on),
                          "old_off": str(old_off)},
                  expect={"constants": {"ON_MILLISECONDS": str(new_on),
                                        "OFF_MILLISECONDS": str(new_off)}})


def add_serial(ctx: Context) -> Change:
    """Messages to the serial monitor: the light's state each time it changes."""
    _require(ctx.facts, "setup", "loop", "led_writes")
    if ctx.facts.has("serial"):
        raise NotApplicable("the sketch already uses the serial port")
    lines = ctx.facts.get("source").split("\n")
    edit = _Lines(ctx.facts.get("source"))
    start, end = ctx.facts.get("setup")
    body = "  " if end == start + 1 else re.match(r"^(\s*)", lines[start + 1]).group(1)
    edit.before(end, [f"{body}Serial.begin(9600);  // talk to the computer at 9600 baud"])
    message = slots.title_in(ctx.request)
    loop_start, _ = ctx.facts.get("loop")
    for index, _name, level in ctx.facts.get("led_writes"):
        indent = re.match(r"^(\s*)", lines[index]).group(1)
        text = "LED on" if level == "HIGH" else "LED off"
        edit.before(index + 1, [f'{indent}Serial.println("{text}");'])
    if message:
        first = loop_start + 1
        indent = re.match(r"^(\s*)", lines[first]).group(1) or "  "
        edit.before(first, [f'{indent}Serial.println("{message.replace(chr(34), "")}");'])
    return Change(files={ctx.facts.get("entry"): edit.text()},
                  values={"extra": f' and "{message}" each time round' if message else ""},
                  expect={"present": ["Serial.begin(9600);"]})


def add_led(ctx: Context) -> Change:
    """A second LED on the pin the child named, blinking with the first or opposite it."""
    _require(ctx.facts, "setup", "loop", "led_writes", "last_constant")
    pin = _pin(ctx, "LED")
    colour = game_things.colour_in(ctx.request)
    label = colour[0].upper().replace(" ", "_") if colour and colour[0] != "that colour" \
        else "SECOND"
    name = f"{label}_LED_PIN"
    if name in (ctx.facts.get("constants") or {}):
        raise NotApplicable(f"there is already a {name}")
    opposite = bool(re.search(r"\b(alternat|opposite|take turns|other one|swap|turns)",
                              ctx.request.lower()))
    lines = ctx.facts.get("source").split("\n")
    edit = _Lines(ctx.facts.get("source"))
    spoken = f"{colour[0]} LED" if colour and colour[0] != "that colour" else "second LED"
    edit.before(ctx.facts.get("last_constant") + 1,
                [f"const int {name} = {pin};  // the {spoken}: see wiring.md"])
    _, setup_end = ctx.facts.get("setup")
    edit.before(setup_end, [f"  pinMode({name}, OUTPUT);"])
    for index, _pin_name, level in ctx.facts.get("led_writes"):
        indent = re.match(r"^(\s*)", lines[index]).group(1)
        other = ({"HIGH": "LOW", "LOW": "HIGH"}[level]) if opposite else level
        edit.before(index + 1, [f"{indent}digitalWrite({name}, {other});"])
    files = {ctx.facts.get("entry"): edit.text()}
    files.update(_wiring_row(
        ctx, spoken[0].upper() + spoken[1:], pin,
        "Pin -> a 220 ohm resistor -> the LED's long leg. The short leg goes to GND. "
        "Without the resistor the LED or the pin can be damaged."))
    return Change(files=files,
                  values={"led": spoken, "pin": pin, "name": name,
                          "how": "takes turns with the built-in one" if opposite
                          else "blinks along with the built-in one"},
                  expect={"present": [f"const int {name} = {pin};"], "pin": pin})


#: What pressing the button does, read from the child's own words. Measured in SPIKES.md
#: section 25J: "a button on pin 2 that turns the light on when I press it" got a light
#: that *blinked* while held, because the behaviour was fixed. Toggle is looked for
#: first, since "turns the light on and off" also says "turns the light on".
_BUTTON_HOW = (
    ("toggle", r"\btoggle|\bstays? on (after|when|until)\b|\bpress(es|ed)? (it )?again\b|"
               r"\bon and off\b|\boff and on\b|\b(each|every) (press|time i press)\b"),
    ("blink", r"\bblink|\bflash"),
    ("steady", r"\bturns? (the |my |an? )?(light|led|lamp) on\b|"
               r"\b(light|led|lamp)s? (only )?(comes?|goes|turns?) on\b|"
               r"\blights? (it )?up\b|\bswitch(es)? (the |my )?(light|led) on\b|"
               r"\bturn(s)? (it )?on\b"),
)

#: A loop() that is only the blink: LED_PIN writes, delays and comments.
_BLINK_LINE = re.compile(r"^\s*(?:(?:digitalWrite\(\s*LED_PIN\s*,\s*(?:HIGH|LOW)\s*\)|"
                         r"delay\([^;()]*\))\s*;)?\s*(?://.*)?$")


def _button_how(request: str) -> str | None:
    """"steady", "blink" or "toggle" from the child's words; "blink" when they named
    none (the recipe's measured behaviour); None when they asked for two at once."""
    lowered = request.lower()
    said = {how for how, pattern in _BUTTON_HOW if re.search(pattern, lowered)}
    if "toggle" in said:
        said.discard("steady")
    if len(said) > 1:
        return None
    return said.pop() if said else "blink"


def add_button(ctx: Context) -> Change:
    """A button on the child's pin, doing what they said pressing it should do.

    - **blink** (and when they did not say): the light blinks only while it is held
    - **steady**: the light is on while it is held, off when it is let go
    - **toggle**: each press turns the light on or off, and it stays that way

    Steady and toggle replace the blink, so they only apply to a loop() that is still
    nothing but the blink; anything more is Gary's to fit the button into.
    """
    _require(ctx.facts, "setup", "loop", "last_constant")
    if "BUTTON_PIN" in (ctx.facts.get("constants") or {}):
        raise NotApplicable("there is already a button")
    pin = _pin(ctx, "button")
    how = _button_how(ctx.request)
    if how is None:
        raise NotApplicable("the message asks the button to do two different things")
    source = ctx.facts.get("source")
    lines = source.split("\n")
    loop_start, loop_end = ctx.facts.get("loop")
    body = lines[loop_start + 1:loop_end]
    if not any(line.strip() for line in body):
        raise NotApplicable("loop() is empty")
    if how != "blink" and not (ctx.facts.get("led_writes")
                               and all(_BLINK_LINE.match(line) for line in body)):
        raise NotApplicable("loop() does more than blink the light")
    edit = _Lines(source)
    constants = [f"const int BUTTON_PIN = {pin};  // the button: see wiring.md"]
    if how == "toggle":
        constants += ["",
                      "bool lightOn = false;        // what the light is doing now",
                      "bool buttonWasDown = false;  // so one press is one change, however "
                      "long it is held"]
    edit.before(ctx.facts.get("last_constant") + 1, constants)
    _, setup_end = ctx.facts.get("setup")
    edit.before(setup_end, ["  pinMode(BUTTON_PIN, INPUT_PULLUP);  // pressed reads LOW"])
    if how == "blink":
        for offset, line in enumerate(body):
            edit.rewrite(loop_start + 1 + offset, ("  " + line) if line.strip() else line)
        edit.before(loop_start + 1, ["  if (digitalRead(BUTTON_PIN) == LOW) {"])
        off = ("    digitalWrite(LED_PIN, LOW);" if ctx.facts.get("led_writes") else
               "    // nothing happens while the button is up")
        edit.before(loop_end, ["  } else {", off, "  }"])
        said = "the light blinks only while you hold it down"
        present = "if (digitalRead(BUTTON_PIN) == LOW) {"
    else:
        for offset in range(len(body)):
            edit.rewrite(loop_start + 1 + offset, None)
        if how == "steady":
            block = ["  if (digitalRead(BUTTON_PIN) == LOW) {  // held down",
                     "    digitalWrite(LED_PIN, HIGH);",
                     "  } else {",
                     "    digitalWrite(LED_PIN, LOW);",
                     "  }"]
            said = "the light is on while you hold it down and off when you let go"
            present = "digitalWrite(LED_PIN, HIGH);"
        else:
            block = ["  bool buttonDown = digitalRead(BUTTON_PIN) == LOW;",
                     "  if (buttonDown && !buttonWasDown) {  // it has just been pressed",
                     "    lightOn = !lightOn;",
                     "    digitalWrite(LED_PIN, lightOn ? HIGH : LOW);",
                     "    delay(50);  // a button bounces for a moment when pressed; wait it out",
                     "  }",
                     "  buttonWasDown = buttonDown;"]
            said = "each press turns the light on, or off again, and it stays that way"
            present = "lightOn = !lightOn;"
        edit.before(loop_start + 1, block)
    files = {ctx.facts.get("entry"): edit.text()}
    files.update(_wiring_row(
        ctx, "Button", pin,
        "One leg to the pin, the other leg to GND. The sketch turns on the pin's own "
        "pull-up resistor, so no extra resistor is needed."))
    return Change(files=files, values={"pin": pin, "how": said, "behaviour": how},
                  expect={"present": [f"const int BUTTON_PIN = {pin};", present],
                          "pin": pin})


OPS = {
    "blink_timing": blink_timing,
    "add_serial": add_serial,
    "add_led": add_led,
    "add_button": add_button,
}


# ------------------------------------------------------------------------ checks

def _compile(ctx):
    def run():
        call = ToolCall(name="compile_project", arguments={}, id="fastpath_compile")
        result: ToolResult = ctx.toolbox.dispatch(call.name, call.arguments)
        ctx.once("calls", list)
        ctx._cache["calls"].append((call, result))
        return result
    return ctx.once("compile", run)


def _check_compiles(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    result = _compile(ctx)
    if result.run is None:
        # No toolchain, or no board chosen: nothing was compiled, so nothing is known.
        return Check("compiles", UNAVAILABLE, result.content[:200])
    if result.ok:
        return Check("compiles", PASS, ctx.project.manifest.arduino_board or "")
    return Check("compiles", FAIL, result.content[-800:])


def _check_constants(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    constants = ctx.facts_after.get("constants") or {}
    for name, wanted in (ctx.expect.get("constants") or {}).items():
        if name not in constants or constants[name].value != wanted:
            return Check("value_set", FAIL, f"{name} is not {wanted}")
    return Check("value_set", PASS)


def _check_present(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, Check

    source = ctx.facts_after.get("source") or ""
    missing = [text for text in ctx.expect.get("present", []) if text not in source]
    return Check("added_present", FAIL, f"missing {missing[0]!r}") if missing else \
        Check("added_present", PASS)


def _check_wiring(ctx):
    from opennest.fastpath.verifier import FAIL, PASS, UNAVAILABLE, Check

    wiring = ctx.facts_after.get("wiring")
    pin = ctx.expect.get("pin")
    if wiring is None:
        return Check("wiring_noted", UNAVAILABLE, "there is no wiring.md")
    if pin and f"| {pin} |" in wiring:
        return Check("wiring_noted", PASS, f"pin {pin}")
    return Check("wiring_noted", FAIL, f"wiring.md does not mention pin {pin}")


CHECKS = {
    "compiles": _check_compiles,
    "value_set": _check_constants,
    "added_present": _check_present,
    "wiring_noted": _check_wiring,
}


#: How a change Gary makes here is checked, for his context (router._context).
CHECKED = ("Check a change with compile_project. A pin must come from the child, never a "
           "guess.")


def verifiable(project) -> bool:
    """Whether this project can compile a sketch at all. A Blank one cannot."""
    return project.profile.can_compile and "compile_project" in project.profile.tools


def confirmation(verification, project=None) -> str:
    from opennest.fastpath.verifier import PASS, UNAVAILABLE

    status = verification.status_of("compiles")
    if status == PASS:
        return "I compiled it and it compiles cleanly."
    if status == UNAVAILABLE:
        return ("I couldn't compile it here yet -- choose your board next to Compile and "
                "press it to check.")
    return ""


def brief(facts: Facts) -> str:
    """What the classifier is told about the sketch, from the facts alone."""
    constants = facts.get("constants") or {}
    parts = ["The sketch blinks the built-in LED."] if "LED_PIN" in constants else []
    pins = [f"{name} on {c.value}" for name, c in constants.items()
            if name.endswith("_PIN") and name != "LED_PIN"]
    parts.append(f"Parts wired so far: {', '.join(pins)}." if pins else
                 "Nothing else is wired yet.")
    return " ".join(parts)
