"""Should a Blank project that has become a game have game_object? Four tools against five.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/graphics/tool_choice_blank.py [label]

``tool_choice.py`` measured the fifth tool for Games projects (SPIKES.md section 28C). A
Blank ("Something Else") project whose files turn out to be a pygame game is the other
place it could go: the Fast Path already treats one as a game (``family_for``), and it
plays in the panel. Whether its tool choice survives a fifth tool is measured, not
assumed, with the same 94 requests and the same acceptable first moves as the Games run:

- **four**: the Blank prompt and tools exactly as they ship, for a Blank project whose
  ``src/main.py`` is the Basic Game, with the eagle picture in its assets;
- **five**: the same, plus ``game_object`` and the Games prompt's PICTURES, DRAWINGS AND
  THE SCENE section -- what turning it on for such a project would mean.

The real 4B, temperature 0, the first move only. Writes ``results/<label>.json``.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from tool_choice import REPO, first_move, requests  # noqa: E402

from opennest.agent.controller import build_system_prompt, scene_prompt  # noqa: E402
from opennest.agent.tools import SCHEMAS, Toolbox  # noqa: E402
from opennest.ai.provider import Message, Settings  # noqa: E402
from opennest.ai.router import build_provider, default_model_id  # noqa: E402
from opennest.assets import manager as assets  # noqa: E402
from opennest.fastpath.kinds import family_for  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402

STARTER = REPO / "opennest/projects/starters/pygame_basic/game.py"


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "tool_choice_blank"
    root = Path(tempfile.mkdtemp(prefix="toolchoice-blank-"))
    project = create_project("Eagle Game", "blank", root=root)
    project.entrypoint_path.parent.mkdir(parents=True, exist_ok=True)
    project.entrypoint_path.write_text(STARTER.read_text(encoding="utf-8"))
    family, why = family_for(project)
    assert family == "games", why
    picture = root / "eagle.png"
    shutil.copy(REPO / "assets/open_nest_asset_delivery/03_eagle_animation/frames_128/"
                "eagle_01.png", picture)
    assets.import_file(project, picture)
    toolbox = Toolbox(project)
    provider = build_provider(default_model_id())
    provider.load()
    asset_block = assets.context_block(project, provider.info)
    # Since the measurement, a Blank game *is* offered game_object (tools.offers_graphics),
    # so the four-tool prompt is the one it had before: without the scene section.
    five = build_system_prompt(project, toolbox=toolbox, asset_context=asset_block)
    blank = project.profile.system_prompt()
    four = five.replace(blank + "\n\n" + scene_prompt(), blank)
    assert four != five and "game_object" not in four
    tools = [SCHEMAS[name] for name in project.profile.tools]
    conditions = {"four": (four, tools), "five": (five, tools + [SCHEMAS["game_object"]])}
    settings = Settings(temperature=0.0, max_tokens=700)
    out = []
    for text, accept, gold in requests():
        row = {"request": text, "gold": gold, "accept": sorted(accept)}
        for name, (system, offered) in conditions.items():
            started = time.monotonic()
            messages = [Message(role="system", content=system),
                        Message(role="user", content=text)]
            for _ in provider.chat(messages, tools=offered, settings=settings):
                pass
            reply = provider.finish()
            move = first_move(reply)
            row[name] = move
            row[f"{name}_ok"] = move in accept
            row[f"{name}_args"] = reply.tool_calls[0].arguments if reply.tool_calls else None
            row[f"{name}_s"] = round(time.monotonic() - started, 1)
        out.append(row)
        print(f"{'ok ' if row['four_ok'] else 'BAD'} {row['four']:12} | "
              f"{'ok ' if row['five_ok'] else 'BAD'} {row['five']:12} | {text[:70]}",
              flush=True)
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
        {"summary": summary, "rows": out}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
