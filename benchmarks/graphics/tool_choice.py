"""Does a fifth Games tool cost Gary his choice of tool? Four tools against five.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/graphics/tool_choice.py [label] [--model=<id>] [--conditions=five]

``--conditions=five`` measures only the current prompt and tools (a model comparison
needs nothing else), at the 700-token cap ``five`` re-runs used -- the cap the committed
results (``tool_choice_3``, ``tool_choice_4``) were measured at.
``--model`` is the catalogue id (default: the catalogue's default model, which is Gary
Fast since SPIKES.md section 32 -- every result before ``tool_choice_vl4b`` was Qwen3 4B). A model that can see is shown the eagle picture first, as the
product does at import (``assets.look``), so its prompt says what the picture shows
instead of "NOBODY HAS LOOKED" -- SPIKES.md section 32.

SPIKES.md section 4 measured selection falling as the tool set grew -- and the tool that
did the damage was ``list_project_files``, a lookup the model reached for instead of
acting. ``game_object`` acts. Whether it still costs accuracy is measured here rather
than assumed, the way section 4 was: every Games request in both Fast Path label sets
plus the Phase 13C graphics requests, one message each, temperature 0, the real Gary
system prompt for a Games project with an eagle picture in it, and the first thing the
real 4B model does:

- **four**: the Games prompt and tools as they were before 13C;
- **five**: the prompt with its PICTURES, DRAWINGS AND THE SCENE section, and
  ``game_object``.

Each request carries which first moves are acceptable (``ACCEPT``): a code tool for how
the game plays, no tool for a question, and for how things look either a code tool or
``game_object``. Writes ``results/<label>.json``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from opennest.agent.controller import build_system_prompt  # noqa: E402
from opennest.agent.tools import SCHEMAS, Toolbox  # noqa: E402
from opennest.ai.provider import Message, Settings  # noqa: E402
from opennest.ai.router import build_provider  # noqa: E402
from opennest.assets import look  # noqa: E402
from opennest.assets import manager as assets  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402

CODE = {"edit_file", "read_file", "write_file"}
QUESTION = {"none"}
LOOKS = CODE | {"game_object"}

#: The first moves that can do what a request asks, by the Fast Path's gold intent. For
#: "other" the label is by hand, below.
BY_GOLD = {
    "change_player_speed": CODE, "change_player_size": CODE | {"game_object"},
    "set_title": CODE, "change_controls": CODE, "add_score": CODE, "add_jump": CODE,
    "change_thing_speed": CODE, "player_moves_itself": CODE, "add_collision": CODE,
    "fix_problem": CODE, "add_game_rules": CODE, "make_avoid_game": LOOKS,
    "make_catch_game": LOOKS, "change_player_colour": LOOKS, "change_background": LOOKS,
    "add_moving_thing": LOOKS, "add_enemy": LOOKS, "add_collectible": LOOKS,
    "replace_player_sprite": LOOKS, "change_thing_look": LOOKS,
}
OTHER = {
    "make my guy a circle not a square": LOOKS,
    "the square goes off the screen and disapears!! make it stop at the edges": CODE,
    "add a timer that counts down from 60": CODE,
    "i want 3 lives and you lose one every time an enemy touches you": CODE,
    "add a game over screen with a play again button": CODE,
    "make it a snake game": CODE,
    "make it spookier": LOOKS, "its kinda boring make it more exciting": LOOKS,
    "can it feel like ur in space": LOOKS,
    "make the player green and add a score and can the background be purple": LOOKS,
    "add some walls i have to get around, put music in, and change the name to Maze Runner":
        LOOKS,
    "how does the speed work?": QUESTION, "add movement": CODE,
    "Make this feel more mysterious.": LOOKS, "Make the enemies scared of the player.": CODE,
    "Turn this into something weird.": LOOKS,
    "Make the game feel like you're lost inside an old television.": LOOKS,
    "i want lava blocks and if you touch one you go back to the start": LOOKS,
    "can my little brother play too on the same keyboard? he can be a diffrent colour": CODE,
    "i want to shoot little lasers out of the square when i press x": CODE,
    "its kinda boring": LOOKS, "make it feel more spooky and mysterious idk": LOOKS,
    "i dont know what i want it to be yet": QUESTION,
    "change the square to green, give me a score in the corner, and make the window bigger":
        LOOKS,
    "add a start screen and also make my guy a cat and can there be music": LOOKS,
    "what does PLAYER_SPEED even do": QUESTION,
    "how does it know when im pressing the arrow keys?": QUESTION,
    "nah undo that i liked orange better": LOOKS | QUESTION,
    "turn it into a whole platformer like mario with 5 levels and a boss at the end and "
    "power ups": CODE,
    "make it a whole dungeon crawler with rooms and keys and a dragon boss at the end": CODE,
    # Falling rocks to dodge are things that move by themselves and send you back: a
    # game_object first is as good a start as code.
    "ok so me and my friend want a game where ur a little square and rocks fall from the "
    "sky and u have to dodge them and every one u dodge is a point and it gets faster and "
    "faster and if u get hit its game over and it shows ur score and a play again button":
        LOOKS,
}
GRAPHICS = [
    ("Use my eagle picture as the player.", LOOKS),
    ("Use this image for the player.", LOOKS),
    ("Make the cars look like cars.", LOOKS),
    ("Build out the background into a little town with a sky and road. Make it feel like a "
     "clean modern mobile game.", LOOKS),
    ("Add three cars to the road.", LOOKS),
    ("Add buildings and clouds in the background.", LOOKS),
    ("Put coins along the road.", LOOKS),
    ("Make everything look more colorful and friendly.", LOOKS),
    ("Make it look like a colorful little town with the eagle flying above the road.", LOOKS),
    ("make the eagle bigger", LOOKS),
    ("put a sign that says Trent Motors", LOOKS),
    ("add some trees", LOOKS),
    ("make the eagle flap its wings", LOOKS),
    ("when I press space the eagle should drop an egg", CODE),
    ("make the eagle go faster", CODE),
    ("what does the eagle do?", QUESTION),
]


def requests() -> list[tuple[str, set[str], str]]:
    rows = []
    for name in ("labels.json", "labels_heldout.json"):
        path = REPO / "spikes" / "fastpath" / name
        for row in json.loads(path.read_text()):
            if row.get("profile") != "games":
                continue
            text = row["text"]
            accept = BY_GOLD.get(row["gold"]) or OTHER.get(text)
            if accept is None:
                raise SystemExit(f"no label for {text!r}")
            rows.append((text, accept, row["gold"]))
    rows += [(text, accept, "graphics") for text, accept in GRAPHICS]
    return rows


def first_move(reply) -> str:
    return reply.tool_calls[0].name if reply.tool_calls else "none"


def main() -> int:
    from opennest.ai.router import default_model_id

    model = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--model=")),
                 default_model_id())
    wanted = next((arg.split("=", 1)[1].split(",") for arg in sys.argv
                   if arg.startswith("--conditions=")), ["four", "five"])
    sys.argv = [arg for arg in sys.argv if not arg.startswith(("--model=", "--conditions="))]
    label = sys.argv[1] if len(sys.argv) > 1 else "tool_choice"
    #: "five" re-runs only the five-tool condition -- after a change to game_object's
    #: description -- and keeps the four-tool answers from an earlier run, named second.
    only_five = len(sys.argv) > 3 and sys.argv[2] == "five"
    earlier = {}
    if only_five:
        earlier = {row["request"]: row for row in json.loads(
            (HERE / "results" / f"{sys.argv[3]}.json").read_text())["rows"]}
    #: Only the first move is measured, so a reply need not run to the end.
    settings = Settings(temperature=0.0, max_tokens=700)
    root = Path(tempfile.mkdtemp(prefix="toolchoice-"))
    project = create_project("Eagle Town", "games", root=root)
    picture = root / "eagle.png"
    shutil.copy(REPO / "assets/open_nest_asset_delivery/03_eagle_animation/frames_128/"
                "eagle_01.png", picture)
    eagle = assets.import_file(project, picture)
    toolbox = Toolbox(project)
    provider = build_provider(model)
    provider.load()
    saw = look.look(project, provider, eagle.path)
    print(f"model {model}; sees pictures: {provider.sees_images}; the eagle: {saw!r}",
          flush=True)
    old_games = subprocess.run(["git", "-C", str(REPO), "show", "7df1694:opennest/prompts/"
                                "games.txt"], capture_output=True, text=True,
                               check=True).stdout.strip()
    asset_block = assets.context_block(project, provider.info)
    five = build_system_prompt(project, toolbox=toolbox, asset_context=asset_block)
    current = project.profile.system_prompt()
    four = five.replace(current, old_games)
    assert four != five
    conditions = {
        "four": (four, [SCHEMAS[n] for n in ("read_file", "edit_file", "write_file",
                                             "run_project")]),
        "five": (five, [SCHEMAS[n] for n in ("read_file", "edit_file", "write_file",
                                             "run_project", "game_object")]),
    }
    conditions = {name: value for name, value in conditions.items() if name in wanted}
    out = []
    for text, accept, gold in requests():
        row = {"request": text, "gold": gold, "accept": sorted(accept)}
        for name, (system, tools) in conditions.items():
            if only_five and name == "four":
                for key in ("four", "four_ok", "four_args", "four_s"):
                    row[key] = earlier[text][key]
                continue
            started = time.monotonic()
            messages = [Message(role="system", content=system),
                        Message(role="user", content=text)]
            for _ in provider.chat(messages, tools=tools,
                                   settings=settings if only_five or "four" not in
                                   wanted else Settings(temperature=0.0)):
                pass
            reply = provider.finish()
            move = first_move(reply)
            row[name] = move
            row[f"{name}_ok"] = move in accept
            row[f"{name}_args"] = reply.tool_calls[0].arguments if reply.tool_calls else None
            row[f"{name}_s"] = round(time.monotonic() - started, 1)
        out.append(row)
        print(" | ".join(f"{'ok ' if row[f'{name}_ok'] else 'BAD'} {row[name]:12}"
                         for name in conditions) + f" | {text[:70]}", flush=True)
    summary = {}
    for name in conditions:
        summary[name] = {
            "acceptable": sum(r[f"{name}_ok"] for r in out), "of": len(out),
            "code_requests_sent_to_game_object": sum(
                1 for r in out if r[name] == "game_object" and "game_object" not in r["accept"]),
            "questions_given_a_tool": sum(
                1 for r in out if r["accept"] == ["none"] and r[name] != "none"),
            "requests_with_no_tool": sum(
                1 for r in out if r[name] == "none" and "none" not in r["accept"]),
            "looks_requests_with_game_object": sum(
                1 for r in out if r[name] == "game_object" and r["gold"] == "graphics"),
        }
    print(json.dumps(summary, indent=1))
    (HERE / "results" / f"{label}.json").write_text(json.dumps(
        {"model": model, "eagle_seen": saw, "summary": summary, "rows": out}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
