"""The work order's section 14 comparison: today's path against the Fast Path, end to end.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/fastpath/bench_e2e.py [--arm current|fast|both] [--only G1,W3] [--label run1]

Same conversations, same model, same starter, through the real controller, Toolbox,
sandbox and playtest -- the only difference between the arms is whether
``AgentController`` is given a ``FastPathRouter``. Unwrapped, with HF_HUB_OFFLINE,
because the playtest and every run are confined by the product's own Seatbelt profile
and Seatbelt does not nest (PHASE_12_HANDOFF section 12).

Everything is persisted: every turn's tools, tokens, timings, route and text, and the
final files, so the grade can be checked and a blind grader can read the results.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
RESULTS = HERE / "results"
RAW = RESULTS / "raw"   # full runs, file contents included: local only, gitignored
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox, normalise_tool_name  # noqa: E402
from opennest.ai.router import build_provider, default_model_id  # noqa: E402
from opennest.assets import manager as assets  # noqa: E402
from opennest.execution.python_runner import run_project  # noqa: E402
from opennest.fastpath.kinds import games, website  # noqa: E402
from opennest.fastpath.router import FastPathRouter  # noqa: E402
from opennest.memory.manager import MemoryManager  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402

AVOID = "Make a game where a spaceship moves around and avoids asteroids."

#: (id, profile, [messages], source, setup)
CONVERSATIONS = [
    # -- Games: Phase 12's own requests (12.3, 12.4, 12.2's sample, DoD 22-30) ----------
    ("G1", "games", [AVOID], "phase12", None),
    ("G2", "games", [AVOID, "Make the asteroids move faster."], "phase12", None),
    ("G3", "games", ["Add a ball that bounces around the screen."], "phase12", None),
    ("G4", "games", ["Make the square fall down the screen and start again at the top."], "phase12", None),
    ("G5", "games", ["Add a second square that slides left and right on its own."], "phase12", None),
    ("G6", "games", ["Make a game where you catch falling blocks."], "phase12", None),
    ("G7", "games", ["Add an enemy that chases the player."], "phase12", None),
    ("G8", "games", ["Add a coin that you can collect for points."], "phase12", None),
    ("G9", "games", ["Add stars that drift down the background."], "phase12", None),
    ("G10", "games", ["Add a score that goes up every second."], "phase12", None),
    ("G11", "games", ["Make the player bigger."], "phase12", None),
    ("G12", "games", ["Change the background colour to dark blue."], "phase12", None),
    ("G13", "games", ["Call my game Space Rocks."], "phase12", None),
    ("G14", "games", ["Make the player move faster."], "phase12", None),
    ("G15", "games", ["Change the background to dark green."], "phase12", None),
    ("G16", "games", ["Add a score in the top left corner."], "phase12", None),
    ("G17", "games", ["Make the player bigger.", "Now make it blue."], "phase12", None),
    ("G18", "games", ["Use this picture for my spaceship."], "phase12", "picture"),
    # -- Games: the work order's creative requests (section 15) --------------------------
    ("G19", "games", ["Make this feel more mysterious."], "workorder", None),
    ("G20", "games", ["Make the enemies scared of the player."], "workorder", None),
    # -- Games: mid-build iteration -- recipe, then Gary, then recipe ----------------------
    ("G21", "games", [AVOID, "Make the asteroids zigzag instead of going straight.",
                      "Make the asteroids move faster."], "iteration", None),
    ("G22", "games", ["Make the player move faster.", "Even faster.", "Now make it bigger."],
     "iteration", None),
    # -- Website: new, small (Phase 12 had no website benchmark) -------------------------
    ("W1", "website", ["change the title to \"Maya's Dog Club\""], "new", None),
    ("W2", "website", ["make the background dark blue"], "new", None),
    ("W3", "website", ["add a section about my favourite films"], "new", None),
    ("W4", "website", ["add a button that counts how many times it is pressed"], "new", None),
    ("W5", "website", ["the words are too small make them bigger"], "new", None),
    ("W6", "website", ["make it feel like summer"], "new", None),
    # -- Research: DoD 32-34, and new small ones ------------------------------------------
    ("R1", "research", ["Graph this and tell me what changed the most."], "workorder", "plants"),
    ("R2", "research", ["make a line graph of how tall each plant got every day"], "new", "plants"),
    ("R3", "research", ["work out the average height for each plant"], "new", "plants"),
    ("R4", "research", ["i want to see if more water = taller plants. can you make a scatter plot"], "new", "plants"),
    ("R5", "research", ["what's in my data?"], "new", "plants"),
    ("R6", "research", ["make it look professional like a real scientist made it"], "new", "plants"),
    # -- Arduino ---------------------------------------------------------------------------
    ("A1", "arduino", ["make it blink faster"], "new", "board"),
    ("A2", "arduino", ["i plugged a red led into pin 9, make that one blink too"], "new", "board"),
    ("A3", "arduino", ["add a button on pin 2 that turns the light on when i press it"], "new", "board"),
    ("A4", "arduino", ["add another LED"], "new", "board"),
    ("A5", "arduino", ["make it like a spooky haunted house light"], "new", "board"),
    # -- Raspberry Pi ----------------------------------------------------------------------
    ("P1", "raspberry_pi", ["make it blink 10 times"], "new", None),
    ("P2", "raspberry_pi", ["blink faster pls"], "new", None),
    ("P3", "raspberry_pi", ["change the pin to 18 thats where i put my led"], "new", None),
    ("P4", "raspberry_pi", ["add a button"], "new", None),
    ("P5", "raspberry_pi", ["make it more magical"], "new", None),
]


#: The closure pass (SPIKES.md section 25M): a small cross-project acceptance set, run on
#: the Fast Path arm only. Written by the developer, not blind -- it exercises the three
#: known missing cases, the website gap, Blank projects, and a regression or two per type.
CLOSURE = [
    ("CG1", "games", [AVOID, "Make the asteroids zigzag instead of going straight.",
                      "Make the asteroids move faster."], "known-1", None),
    ("CG2", "games", [AVOID, "can the asteroids bounce around instead"], "known-1", None),
    ("CG3", "games", ["Add a ball that bounces around the screen.",
                      "make the ball go round in circles"], "known-1", None),
    ("CG4", "games", ["Call my game Space Rocks."], "regression", None),
    ("CW1", "website", ["change the footer to say Made by Maya"], "gap", None),
    ("CW2", "website", ["make the tagline say I love skateboarding"], "gap", None),
    ("CW3", "website", ["add a card about my hamster"], "regression", None),
    ("CW4", "website", ["add a section about my favourite films"], "regression", None),
    ("CW5", "website", ["make the font comic sans"], "gap-probe", None),
    ("CR1", "research", ["Graph this and tell me what changed the most."], "known-3", "plants"),
    ("CR2", "research", ["Graph this and tell me what changed the most."], "known-3", "monthly"),
    ("CR3", "research", ["find the windiest day and print it"], "veto", "weather"),
    ("CR4", "research", ["make a line graph of how tall each plant got every day"],
     "regression", "plants"),
    ("CA1", "arduino", ["add a button on pin 2 that turns the light on when i press it"],
     "known-2", "board"),
    ("CA2", "arduino", ["add a button on pin 3 so each press turns the light on and off"],
     "known-2", "board"),
    ("CA3", "arduino", ["make it blink faster"], "regression", "board"),
    ("CP1", "raspberry_pi", ["make it blink 10 times"], "regression", None),
    ("CP2", "raspberry_pi", ["move the led to pin 22"], "regression", None),
    ("CB1", "blank", ["change the footer to say Made by Sam"], "blank", "blank_website"),
    ("CB2", "blank", ["Make the player move faster."], "blank", "blank_game"),
    ("CB3", "blank", ["work out the average height for each plant"], "blank", "blank_research"),
    ("CB4", "blank", ["make it blink faster"], "blank", "blank_arduino"),
    ("CB5", "blank", ["make a little program that tells me a joke"], "blank", None),
]

#: The Phase 12 app walk's own CSV (spikes/phase12/app_walk.py): month names, in order.
MONTHLY = ("month,rainfall_mm,sunshine_hours\n"
           "Jan,88,44\nFeb,71,68\nMar,60,110\nApr,52,150\nMay,49,190\nJun,44,205\n"
           "Jul,42,215\nAug,55,196\nSep,64,150\nOct,86,105\nNov,92,60\nDec,95,40\n")
STARTERS = REPO / "opennest" / "projects" / "starters"


def png_bytes(width: int = 48, height: int = 32) -> bytes:
    """A small valid RGBA PNG, made without Pillow."""
    raw = b"".join(b"\x00" + bytes([200, 220, 255, 255]) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def prepare(profile: str, setup: str | None, root: Path):
    project = create_project("Bench Project", profile, root=root)
    attachments = ()
    if setup == "plants":
        (project.directory / "data").mkdir(exist_ok=True)
        shutil.copy(INPUTS / "plants.csv", project.directory / "data" / "plants.csv")
    if setup == "board":
        project.manifest.arduino_board = "arduino:avr:uno"
        project.save()
    if setup == "monthly":
        (project.directory / "data").mkdir(exist_ok=True)
        (project.directory / "data" / "weather.csv").write_text(MONTHLY)
    if setup == "weather":
        (project.directory / "data").mkdir(exist_ok=True)
        shutil.copy(INPUTS / "weather.csv", project.directory / "data" / "weather.csv")
    if setup and setup.startswith("blank_"):
        src = project.directory / "src"
        src.mkdir(exist_ok=True)
        if setup == "blank_website":
            for name in ("index.html", "styles.css", "script.js"):
                shutil.copy(STARTERS / "website_basic" / name, src / name)
        elif setup == "blank_game":
            shutil.copy(STARTERS / "pygame_basic" / "game.py", src / "main.py")
        elif setup == "blank_research":
            shutil.copy(STARTERS / "research_basic" / "analysis.py", src / "main.py")
            (project.directory / "data").mkdir(exist_ok=True)
            shutil.copy(INPUTS / "plants.csv", project.directory / "data" / "plants.csv")
        elif setup == "blank_arduino":
            shutil.copytree(STARTERS / "arduino_basic" / "project", src / "blink")
            (src / "blink" / "project.ino").rename(src / "blink" / "blink.ino")
    if setup == "picture":
        source = root / "spaceship.png"
        source.write_bytes(png_bytes())
        attachments = (assets.import_file(project, source),)
    return project, attachments


def snapshot_files(project) -> dict[str, str]:
    files = {}
    for path in sorted((project.directory / "src").rglob("*")):
        if path.is_file() and path.suffix in (".py", ".html", ".css", ".js", ".ino", ".md"):
            files[str(path.relative_to(project.directory))] = path.read_text(errors="replace")
    return files


def run_conversation(conv, arm: str, provider) -> dict:
    cid, profile, messages, source, setup = conv
    root = Path(tempfile.mkdtemp(prefix=f"fp-e2e-{cid}-{arm}-"))
    try:
        project, attachments = prepare(profile, setup, root)
        toolbox = Toolbox(project)
        controller = AgentController(
            project, provider, toolbox, build_style=project.manifest.build_style,
            memory=MemoryManager.for_provider(project, provider),
            fastpath=FastPathRouter() if arm == "fast" else None,
        )
        turns = []
        files_after = []
        for index, message in enumerate(messages):
            started = time.monotonic()
            turn = controller.send(message, attachments=attachments if index == 0 else ())
            seconds = time.monotonic() - started
            toolbox.stop_running()
            calls = [(normalise_tool_name(n), r) for n, r in turn.tool_results]
            turns.append({
                "message": message,
                "seconds": round(seconds, 2),
                "route": (turn.fastpath or {}).get("route", "none"),
                "fastpath": turn.fastpath,
                "provider_calls": turn.usage.calls,
                "input_tokens": turn.usage.input_tokens,
                "output_tokens": turn.usage.output_tokens,
                "tools": [{"name": n, "ok": r.ok, "reason": r.reason,
                           "changed": list(r.changed_files), "recovered": r.recovered}
                          for n, r in calls],
                "edit_attempts": sum(1 for n, _ in calls if n == "edit_file"),
                "edits_landed": sum(1 for n, r in calls if n in ("edit_file", "write_file")
                                    and r.ok and r.changed_files),
                "refused": sum(1 for n, r in calls if not r.ok),
                "playtests": [t.verdict for t in turn.playtests],
                "gave_up": turn.gave_up,
                "text": turn.text,
            })
            files_after.append(snapshot_files(project))
        grade = grade_conversation(cid, project, toolbox, turns, files_after)
        return {"id": cid, "profile": profile, "messages": messages, "source": source,
                "arm": arm, "turns": turns, "files": files_after[-1],
                "first_files": files_after[0], "grade": grade}
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------------- grading
#
# Objective checks only. Each returns (working, note). Anything that needs judgement --
# "does the ball really bounce?" -- is left to the blind grader, and says so.

def _playtest(toolbox):
    result = toolbox.playtest()
    return result


def _game(project, toolbox):
    facts = games.facts(project)
    test = _playtest(toolbox)
    return facts, test


def _const(facts, name):
    const = (facts.get("constants") or {}).get(name)
    return None if const is None else const.value


def grade_closure(cid, project, toolbox, turns, files_after) -> dict:
    """Objective checks for the closure set. None where only a reader can say."""
    routes = [t["route"] for t in turns]
    last = files_after[-1]
    result: dict = {"routes": routes}
    if cid.startswith("CG"):
        facts, test = _game(project, toolbox)
        passed = test is not None and test.verdict == "passed"
        motion = (games.motion_of(facts, next(iter(facts.get("things") or {"-": 0})))
                  if facts.get("things") else None)
        result.update(playtest=test.verdict if test else None,
                      motion=motion[0] if motion else None)
        wanted = {"CG1": "zigzag", "CG2": "bounce", "CG3": "orbit"}.get(cid)
        if wanted:
            ok = passed and bool(test.moved_by_itself) and result["motion"] == wanted
            if cid == "CG1":
                # The third turn raised the speed of the zigzagging asteroids.
                before = re.search(r"ASTEROID_SPEED = (\d+)", files_after[1]["src/game.py"])
                after = re.search(r"ASTEROID_SPEED = (\d+)", last["src/game.py"])
                ok = ok and bool(before and after and int(after.group(1)) > int(before.group(1)))
            if cid in ("CG1", "CG2"):
                ok = ok and "collidelist" in last["src/game.py"]
            result.update(working=ok, judged="auto")
        else:
            src = last["src/game.py"]
            result.update(working=passed and "Space Rocks" in src and "set_caption" in src,
                          judged="auto")
        return result
    if cid.startswith("CW") or cid == "CB1":
        facts = website.facts(project)
        page, styles = facts.get("page") or "", facts.get("styles") or ""
        balanced = bool(facts.get("balanced"))
        footer = page.split("<footer", 1)[-1] if "<footer" in page else ""
        checks = {
            "CW1": lambda: "Made by Maya" in footer,
            "CB1": lambda: "Made by Sam" in footer,
            "CW2": lambda: re.search(r'class="tagline">I love skateboarding<', page) is not None,
            "CW3": lambda: re.search(r"<h3>[^<]*hamster[^<]*</h3>", page, re.I) is not None,
            "CW4": lambda: re.search(r'<section id="[^"]*film', page, re.I) is not None and
                           re.search(r'href="#[^"]*film', page, re.I) is not None,
            "CW5": lambda: "comic sans" in styles.lower(),
        }
        result.update(working=balanced and checks[cid](), balanced=balanced, judged="auto")
        return result
    if cid.startswith("CR") or cid == "CB3":
        entry = f"src/{project.manifest.entrypoint}"
        run = run_project(project.directory, project.profile.run_command, timeout=60)
        charts = sorted(p.name for p in (project.directory / "charts").glob("*.png")) \
            if (project.directory / "charts").is_dir() else []
        out = run.stdout
        source = last.get(entry, "")
        checks = {
            "CR1": lambda: "The biggest change was" in out and len(charts) >= 2,
            # Dec 95 - Jan 88 = +7 rainfall; sunshine 40 - 44 = -4. In file order.
            "CR2": lambda: "The biggest change was rainfall_mm: +7.00" in out,
            # The windiest row of weather.csv, and never the "what changed" recipe.
            "CR3": lambda: "biggest_change" not in json.dumps(turns[-1]["fastpath"] or {})
                           or turns[-1]["route"] != "recipe",
            "CR4": lambda: ".plot(" in source and len(charts) >= 2,
            "CB3": lambda: bool(re.search(r"Basil\s+\d", out)) and "mean()" in source,
        }
        result.update(exit=run.exit_code, charts=charts, judged="auto",
                      working=run.ok and checks[cid]())
        if cid == "CR3":
            result["note"] = "safe = no wrong recipe; whether Gary's answer is right is read by hand"
        return result
    if cid.startswith("CA") or cid == "CB4":
        if cid == "CB4":
            sketch = last.get("src/blink/blink.ino", "")
            times = _blink_times(sketch)
            result.update(working=times is not None and all(v < 500 for v in times),
                          judged="auto", note="no compiler in a Blank project")
            return result
        tool = toolbox.dispatch("compile_project", {})
        sketch = last.get("src/project/project.ino", "")
        loop = sketch.split("void loop()", 1)[-1]
        checks = {
            "CA1": lambda: "digitalRead(BUTTON_PIN)" in loop and "HIGH" in loop
                           and "delay(ON_MILLISECONDS)" not in loop,
            "CA2": lambda: "lightOn = !lightOn" in loop,
            "CA3": lambda: _blink_times(sketch) is not None and all(
                v < 500 for v in _blink_times(sketch)),
        }
        result.update(compiled=tool.ok, working=tool.ok and checks[cid](), judged="auto")
        return result
    if cid.startswith("CP"):
        run = run_project(project.directory, project.profile.run_command, timeout=60)
        checks = {"CP1": lambda: "Blink 10 of 10" in run.stdout,
                  "CP2": lambda: "pin 22" in run.stdout}
        result.update(working=run.ok and checks[cid](), judged="auto")
        return result
    if cid == "CB2":
        facts = games.facts(project)
        speed = _const(facts, "PLAYER_SPEED")
        result.update(working=(speed or 0) > 5, judged="auto",
                      note="Gary, guided: a Blank project has no playtest")
        return result
    # CB5: nothing recognisable -- Gary, as before. Whether the joke program works is
    # read by hand.
    result.update(working=None, judged="by hand")
    return result


def grade_conversation(cid, project, toolbox, turns, files_after) -> dict:
    if cid.startswith("C") and cid[1] in "GWRAPB" and cid[2:].isdigit():
        return grade_closure(cid, project, toolbox, turns, files_after)
    text = turns[-1]["text"].lower()
    profile = project.profile.id
    if profile == "games":
        facts, test = _game(project, toolbox)
        passed = test is not None and test.verdict == "passed"
        moves = bool(test and test.moved_by_itself)
        source = facts.get("source") or ""
        result = {"playtest": test.verdict if test else None, "moved_by_itself": moves}
        changed = source != files_after[0].get("src/game.py", source) or any(
            t["edits_landed"] for t in turns)
        speed = _const(facts, facts.get("player_speed", "PLAYER_SPEED"))
        checks = {
            "G11": lambda: (_const(facts, "PLAYER_SIZE") or 0) > 40,
            "G14": lambda: (speed or 0) > 5,
            "G12": lambda: _is_colour(_const(facts, "BACKGROUND"), "blue", dark=True),
            "G15": lambda: _is_colour(_const(facts, "BACKGROUND"), "green", dark=True),
            "G13": lambda: "space rocks" in source.lower() and "set_caption" in source,
            "G17": lambda: (_const(facts, "PLAYER_SIZE") or 0) > 40 and _is_colour(
                _const(facts, "PLAYER_COLOUR"), "blue"),
            "G22": lambda: (speed or 0) > 8 and (_const(facts, "PLAYER_SIZE") or 0) > 40,
            "G18": lambda: "spaceship" in source and "blit" in source and passed,
            "G10": lambda: "score" in source.lower() and "render" in source and (
                "get_ticks" in source or "set_timer" in source or "time" in source),
            "G16": lambda: "score" in source.lower() and "render" in source,
        }
        needs_motion = {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "G9", "G21"}
        if cid in checks:
            ok = passed and bool(checks[cid]())
            result.update(working=ok, judged="auto")
        elif cid in needs_motion:
            ok = passed and moves
            result.update(working=ok, judged="auto-partial",
                          note="runs and something moves by itself; what moves and how is "
                               "for the blind grader")
            if cid in ("G1", "G2", "G21"):
                ok = ok and bool(re.search(r"collide(rect|list|point)|colliderect", source))
                result["working"] = ok
        elif cid == "G8":
            ok = passed and "colliderect" in source and "score" in source.lower()
            result.update(working=ok, judged="auto-partial")
        else:
            result.update(working=None, judged="blind", note="creative: judged blind")
        result["changed"] = changed
        return result
    if profile == "website":
        facts = website.facts(project)
        page = facts.get("page") or ""
        styles = facts.get("styles") or ""
        balanced = bool(facts.get("balanced"))
        checks = {
            "W1": lambda: "Maya's Dog Club" in page or "Maya&#x27;s Dog Club" in page,
            "W2": lambda: _css_dark_blue(styles),
            "W3": lambda: re.search(r'<section id="[^"]*film', page, re.I) is not None and
                          re.search(r'href="#[^"]*film', page, re.I) is not None,
            "W4": lambda: _button_counts(page, facts.get("script") or ""),
            "W5": lambda: (int(facts.get("body_font").value) if facts.has("body_font") else 0) > 17,
        }
        if cid in checks:
            return {"working": balanced and bool(checks[cid]()), "balanced": balanced,
                    "judged": "auto"}
        return {"working": None, "balanced": balanced, "judged": "blind"}
    if profile == "research":
        run = run_project(project.directory, project.profile.run_command, timeout=60)
        charts = sorted(p.name for p in (project.directory / "charts").glob("*.png")) \
            if (project.directory / "charts").is_dir() else []
        out = run.stdout
        checks = {
            "R1": lambda: "change" in out.lower() and len(charts) >= 1,
            "R2": lambda: len(charts) >= 1 and "line" in (files_after[-1].get(
                "src/analysis.py", "") + "").lower() and ".plot(" in files_after[-1].get(
                "src/analysis.py", ""),
            "R3": lambda: bool(re.search(r"Basil\s+\d", out)) and "average" in out.lower() or
                          ("mean" in files_after[-1].get("src/analysis.py", "") and
                           bool(re.search(r"Basil\s+\d", out))),
            "R4": lambda: ".scatter(" in files_after[-1].get("src/analysis.py", "") and
                          len(charts) >= 1,
            "R5": lambda: "rows" in out and "columns" in out and ("84" in text or "rows" in text),
        }
        result = {"exit": run.exit_code, "charts": charts}
        if cid in checks:
            result.update(working=run.ok and bool(checks[cid]()), judged="auto")
        else:
            result.update(working=None, judged="blind")
        return result
    if profile == "arduino":
        tool = toolbox.dispatch("compile_project", {})
        compiled = tool.ok
        sketch = files_after[-1].get("src/project/project.ino", "")
        wiring = files_after[-1].get("src/project/wiring.md", "")
        before = files_after[0].get("src/project/project.ino", "")
        checks = {
            "A1": lambda: _blink_times(sketch) is not None and all(
                value < 500 for value in _blink_times(sketch)),
            "A2": lambda: re.search(r"=\s*9\s*;", sketch) is not None and "OUTPUT" in sketch
                          and "9" in wiring,
            "A3": lambda: re.search(r"=\s*2\s*;", sketch) is not None and "digitalRead" in sketch,
            # No pin was given: the right answer asks, and invents nothing.
            "A4": lambda: sketch == ARDUINO_STARTER and "pin" in text and "?" in text,
        }
        if cid in checks:
            return {"working": compiled and bool(checks[cid]()), "compiled": compiled,
                    "judged": "auto", "unchanged": sketch == before}
        return {"working": None, "compiled": compiled, "judged": "blind"}
    if profile == "raspberry_pi":
        run = run_project(project.directory, project.profile.run_command, timeout=60)
        main = files_after[-1].get("src/main.py", "")
        out = run.stdout
        checks = {
            "P1": lambda: "Blink 10 of 10" in out,
            "P2": lambda: _pi_times(main) is not None and all(v < 0.3 for v in _pi_times(main)),
            "P3": lambda: "pin 18" in out,
            "P4": lambda: main == PI_STARTER and "pin" in text and "?" in text,
        }
        if cid in checks:
            return {"working": run.ok and bool(checks[cid]()), "exit": run.exit_code,
                    "judged": "auto"}
        return {"working": None, "exit": run.exit_code, "judged": "blind"}
    return {"working": None, "judged": "blind"}


ARDUINO_STARTER = (REPO / "opennest/projects/starters/arduino_basic/project/project.ino").read_text()
PI_STARTER = (REPO / "opennest/projects/starters/raspberry_pi_basic/main.py").read_text()


def _is_colour(value, hue, dark=False):
    try:
        r, g, b = value
    except (TypeError, ValueError):
        return False
    channel = {"red": r, "green": g, "blue": b}[hue]
    others = [c for name, c in (("red", r), ("green", g), ("blue", b)) if name != hue]
    if not all(channel > other for other in others):
        return False
    return max(r, g, b) <= 150 if dark else True


def _css_dark_blue(styles: str) -> bool:
    match = re.search(r"--bg\s*:\s*#([0-9a-fA-F]{6})", styles)
    if not match:
        return False
    r, g, b = (int(match.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    return b > r and b > g and max(r, g, b) <= 150


def _button_counts(page: str, script: str) -> bool:
    ids = re.findall(r'<button[^>]*id="([^"]+)"', page)
    return any(f'"{i}"' in script or f"'{i}'" in script for i in ids if i != "surprise") and \
        bool(re.search(r"(\+\+|\+= ?1|\+ 1)", script))


def _blink_times(sketch: str):
    found = re.findall(r"(?:ON|OFF)_MILLISECONDS\s*=\s*(\d+)", sketch)
    if len(found) == 2:
        return [int(v) for v in found]
    delays = re.findall(r"delay\((\d+)\)", sketch)
    return [int(v) for v in delays] if delays else None


def _pi_times(main: str):
    found = re.findall(r"^(?:ON|OFF)_SECONDS\s*=\s*([\d.]+)", main, re.MULTILINE)
    return [float(v) for v in found] if len(found) == 2 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", default="both", choices=("current", "fast", "both"))
    parser.add_argument("--only", default="")
    parser.add_argument("--label", default="e2e")
    parser.add_argument("--model", default=default_model_id())
    parser.add_argument("--set", default="main", choices=("main", "closure"))
    args = parser.parse_args()
    wanted = set(filter(None, args.only.split(",")))
    pool = CLOSURE if args.set == "closure" else CONVERSATIONS
    work = [c for c in pool if not wanted or c[0] in wanted]
    arms = ["current", "fast"] if args.arm == "both" else [args.arm]
    provider = build_provider(args.model)
    provider.load()
    RAW.mkdir(parents=True, exist_ok=True)
    dump = RAW / f"{args.label}.json"
    results = json.loads(dump.read_text()) if dump.exists() else []
    done = {(r["id"], r["arm"]) for r in results}
    for conv in work:
        for arm in arms:
            if (conv[0], arm) in done:
                continue
            result = run_conversation(conv, arm, provider)
            results.append(result)
            dump.write_text(json.dumps(results, indent=1))
            t = result["turns"]
            print(f"{conv[0]:4} {arm:7} working={str(result['grade'].get('working')):5} "
                  f"routes={[x['route'] for x in t]} s={sum(x['seconds'] for x in t):6.1f} "
                  f"calls={sum(x['provider_calls'] for x in t):2} "
                  f"out_tok={sum(x['output_tokens'] for x in t):5} "
                  f"edits={sum(x['edits_landed'] for x in t)}/{sum(x['edit_attempts'] for x in t)}",
                  flush=True)
    print("written", dump)
    return 0


if __name__ == "__main__":
    sys.exit(main())
