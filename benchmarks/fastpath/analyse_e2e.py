"""The work order's section 14 table, from e2e.json (and blind grades, when present).

    .venv/bin/python benchmarks/fastpath/analyse_e2e.py e2e.json [blind_grades.json blind_key.json]
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
RESULTS = HERE / "results"
RAW = RESULTS / "raw"   # full runs, file contents included: local only, gitignored
_source = next((c for c in (RESULTS / sys.argv[1], RAW / sys.argv[1], Path(sys.argv[1])) if c.is_file()))
results = json.loads(_source.read_text())

#: What each message is, for "intent correct". Mirrors labels.json where the text is there.
GOLD = {
    "Make a game where a spaceship moves around and avoids asteroids.": {"make_avoid_game"},
    "Make the asteroids move faster.": {"change_thing_speed"},
    "Add a ball that bounces around the screen.": {"add_moving_thing"},
    "Make the square fall down the screen and start again at the top.": {
        "player_moves_itself", "add_moving_thing"},
    "Add a second square that slides left and right on its own.": {"add_moving_thing"},
    "Make a game where you catch falling blocks.": {"make_catch_game"},
    "Add an enemy that chases the player.": {"add_enemy"},
    "Add a coin that you can collect for points.": {"add_collectible"},
    "Add stars that drift down the background.": {"add_moving_thing"},
    "Add a score that goes up every second.": {"add_score"},
    "Make the player bigger.": {"change_player_size"},
    "Change the background colour to dark blue.": {"change_background"},
    "Call my game Space Rocks.": {"set_title"},
    "Make the player move faster.": {"change_player_speed"},
    "Change the background to dark green.": {"change_background"},
    "Add a score in the top left corner.": {"add_score"},
    "Now make it blue.": {"change_player_colour"},
    "Use this picture for my spaceship.": {"replace_player_sprite"},
    "Make this feel more mysterious.": {"other"},
    "Make the enemies scared of the player.": {"other"},
    "Make the asteroids zigzag instead of going straight.": {"other", "change_thing_look"},
    "Even faster.": {"change_player_speed"},
    "Now make it bigger.": {"change_player_size"},
    "change the title to \"Maya's Dog Club\"": {"change_heading"},
    "make the background dark blue": {"change_colours"},
    "add a section about my favourite films": {"add_section"},
    "add a button that counts how many times it is pressed": {"add_button"},
    "the words are too small make them bigger": {"change_font_size"},
    "make it feel like summer": {"other", "change_colours"},
    "Graph this and tell me what changed the most.": {"biggest_change"},
    "make a line graph of how tall each plant got every day": {"line_chart"},
    "work out the average height for each plant": {"group_average"},
    "i want to see if more water = taller plants. can you make a scatter plot": {"scatter_plot"},
    "what's in my data?": {"describe_data"},
    "make it look professional like a real scientist made it": {"other", "restyle_chart"},
    "make it blink faster": {"change_blink_speed"},
    "i plugged a red led into pin 9, make that one blink too": {"add_led"},
    "add a button on pin 2 that turns the light on when i press it": {"add_button"},
    "add another LED": {"add_led"},
    "make it like a spooky haunted house light": {"other", "change_blink_pattern"},
    "make it blink 10 times": {"change_blink_count"},
    "blink faster pls": {"change_blink_speed"},
    "change the pin to 18 thats where i put my led": {"change_led_pin"},
    "add a button": {"add_button"},
    "make it more magical": {"other"},
}
#: Where the right answer is to ask, not act: no pin given.
MUST_ASK = {"A4", "P4"}

blind = {}
if len(sys.argv) > 3:
    grades = json.loads(Path(sys.argv[2]).read_text())
    key = json.loads(Path(sys.argv[3]).read_text())
    for case, grade in grades.items():
        blind[(key[case]["id"], key[case]["arm"])] = grade


def _files_key(result):
    """The final files, or their hash in the tracked summary (summarise_e2e.py)."""
    if "files_sha" in result:
        return result["files_sha"]
    return hashlib.sha256(json.dumps(result["files"], sort_keys=True).encode()).hexdigest()


def _twin_verdict(result):
    """The other arm's blind verdict, when both arms ended identically -- same files, same
    words -- because the Fast Path stepped aside and Gary gave the same answer. Identical
    outcomes must not be graded differently just because one was sampled."""
    other = "current" if result["arm"] == "fast" else "fast"
    twin = next((r for r in results if r["id"] == result["id"] and r["arm"] == other), None)
    if twin is None or (result["id"], other) not in blind:
        return None
    same = _files_key(twin) == _files_key(result) and [t["text"] for t in twin["turns"]] == [
        t["text"] for t in result["turns"]]
    return blind[(result["id"], other)] if same else None


def working(result) -> bool | None:
    """The blind judgement where there is one -- it is the semantic judge, and it sees the
    measured facts too -- except that an objective failure the automatic grader found
    (a crash, a missing chart) still counts against an "auto-partial" case. Applied the
    same way to both arms."""
    auto = result["grade"].get("working")
    judged = result["grade"].get("judged")
    verdict = blind.get((result["id"], result["arm"])) or _twin_verdict(result)
    if verdict is not None:
        blind_ok = verdict.get("does_what_was_asked") == "yes"
        if judged == "auto-partial":
            return blind_ok and (auto is not False)
        return blind_ok
    return None if auto is None else bool(auto)


def truthful(result) -> bool | None:
    verdict = blind.get((result["id"], result["arm"])) or _twin_verdict(result)
    return None if verdict is None else verdict.get("truthful") == "yes"


def table(rows, title):
    arms = {"current": [], "fast": []}
    for r in rows:
        arms[r["arm"]].append(r)
    ids = sorted({r["id"] for r in rows})
    lines = [f"\n### {title}  ({len(ids)} conversations, "
             f"{sum(len(r['messages']) for r in arms['fast'])} messages per arm)\n",
             "| Metric | Current Path | Fast Path |", "|---|---:|---:|"]

    def per_arm(fn):
        return [fn(arms["current"]), fn(arms["fast"])]

    def turns(rs):
        return [t for r in rs for t in r["turns"]]

    def fmt_frac(ok, n):
        return f"{ok}/{n}" if n else "--"

    def intent(rs):
        ok = n = 0
        for r in rs:
            for t in r["turns"]:
                fp = t.get("fastpath") or {}
                if "intent" not in fp:
                    continue
                n += 1
                ok += fp["intent"] in GOLD.get(t["message"], set())
        return fmt_frac(ok, n)

    def worked(rs):
        judged = [working(r) for r in rs if working(r) is not None]
        return f"{sum(judged)}/{len(judged)}"

    def latency(rs):
        ts = turns(rs)
        return f"{sum(t['seconds'] for t in ts) / max(len(ts), 1):.1f} s"

    def median_latency(rs):
        ts = sorted(t["seconds"] for t in turns(rs))
        return f"{ts[len(ts) // 2]:.1f} s" if ts else "--"

    def tokens(rs):
        return f"{sum(t['output_tokens'] for t in turns(rs)):,}"

    def calls(rs):
        return f"{sum(t['provider_calls'] for t in turns(rs))}"

    def edits(rs):
        ts = turns(rs)
        return f"{sum(t['edits_landed'] for t in ts)}/{sum(t['edit_attempts'] for t in ts)}"

    def retries(rs):
        return f"{sum(t['refused'] for t in turns(rs))}"

    def refusals(rs):
        relevant = [r for r in rs if r["id"] in MUST_ASK]
        return fmt_frac(sum(bool(r["grade"].get("working")) for r in relevant), len(relevant))

    def false_routes(rs):
        bad = 0
        n = 0
        for r in rs:
            for i, t in enumerate(r["turns"]):
                if t["route"] != "recipe" or (t.get("fastpath") or {}).get("result") != "success":
                    continue
                n += 1
                wrong_intent = t["fastpath"]["intent"] not in GOLD.get(t["message"], set())
                failed = i == len(r["turns"]) - 1 and working(r) is False
                bad += wrong_intent or failed
        return f"{bad}/{n}" if n else "--"

    def routes(rs):
        counts = defaultdict(int)
        for t in turns(rs):
            counts[t["route"]] += 1
        return ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))

    def truth(rs):
        judged = [truthful(r) for r in rs if truthful(r) is not None]
        return fmt_frac(sum(judged), len(judged))

    for label, fn in (("Intent correct (classifier)", intent), ("Working result", worked),
                      ("Gary truthful (blind-graded cases)", truth),
                      ("Avg latency per message", latency), ("Median latency", median_latency),
                      ("Generated tokens", tokens), ("Model calls", calls),
                      ("Edits landed / attempted", edits), ("Tool refusals (retries)", retries),
                      ("Correct refusals (no pin given)", refusals),
                      ("False fast-path routes", false_routes), ("Routes", routes)):
        current, fast = per_arm(fn)
        if label == "Intent correct (classifier)":
            current = "n/a"
        if label in ("False fast-path routes",):
            current = "n/a"
        lines.append(f"| {label} | {current} | {fast} |")
    print("\n".join(lines))


table(results, "All project types")
table([r for r in results if r["source"] == "phase12"], "Games -- Phase 12's own requests")
for profile in ("games", "website", "research", "arduino", "raspberry_pi"):
    table([r for r in results if r["profile"] == profile], profile)

print("\n### Per conversation\n")
print("| id | messages | current: working, s, tokens | fast: route, working, s, tokens |")
print("|---|---|---|---|")
by_id = defaultdict(dict)
for r in results:
    by_id[r["id"]][r["arm"]] = r
for cid in sorted(by_id, key=lambda c: (c[0], int(c[1:]))):
    c, f = by_id[cid].get("current"), by_id[cid].get("fast")
    if not (c and f):
        continue

    def cell(r, with_route=False):
        s = sum(t["seconds"] for t in r["turns"])
        tok = sum(t["output_tokens"] for t in r["turns"])
        route = "/".join(t["route"] for t in r["turns"]) + ", " if with_route else ""
        return f"{route}{working(r)}, {s:.0f} s, {tok}"

    print(f"| {cid} | {' / '.join(m[:38] for m in c['messages'])} | {cell(c)} | {cell(f, True)} |")
