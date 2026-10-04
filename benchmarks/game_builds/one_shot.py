"""Can the model write the game at all? One reply, the whole program, no Open Nest loop.

    OPENNEST_HOME=$PWD/.opennest-sandbox HF_HUB_OFFLINE=1 .venv/bin/python \
        benchmarks/game_builds/one_shot.py <label> [model-id]

The owner's question after the game builds (SPIKES.md section 33): is "Gary cannot build
a whole game" a limit of the model or of Open Nest's setup -- the edit tool's exact-match
rule, write_file refusing to overwrite, the call budget, the prompts? So this asks the
same games of the bare model, the way any coding assistant would be asked: one short
system prompt, the request (with the follow-ups folded in), one reply, temperature 0,
room for a whole program. The code it writes is run by Open Nest's own playtest -- the
same sandbox and harness as after every change in the app -- and its last frame kept.
Grades nothing by itself: the verdict says whether it runs and responds, the frame says
whether it is the game asked for.

With ``--repair``, a game that crashed, froze or showed nothing is handed back up to
twice with Open Nest's own playtest feedback (``Playtest.feedback``, what the app's repair
loop says) and its code, and the whole corrected program is asked for -- what "write the
whole file, then let Open Nest test and repair it" would give.

Writes ``results/<label>.json`` and ``results/<label>/<game>.png``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from opennest.ai.provider import Message, Settings  # noqa: E402
from opennest.ai.router import build_provider, default_model_id, get_entry  # noqa: E402
from opennest.execution import playtest  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402

SYSTEM = (
    "You write complete, working Python games with pygame for a child. Reply with the "
    "whole program in one ```python code block and nothing else. Use only pygame and the "
    "Python standard library, no image or sound files. The window is 640x480. The game "
    "must run by itself: set things up above the game loop, move them inside it, draw "
    "every frame after filling the screen, call pygame.display.flip() and clock.tick(60), "
    "and quit cleanly when the window is closed.")

#: The game builds' requests, follow-ups folded in, as one message each.
GAMES = {
    "cat": "Make a game where a cat catches falling pizzas. Move the cat with the arrow "
           "keys and show a score that goes up when it catches one.",
    "space": "Make a space game: I fly a ship with the arrow keys among stars, and "
             "asteroids come at me that I have to dodge. If one hits me I lose a life.",
    "platform": "Make a platform game where I run left and right and jump with space onto "
                "platforms, with gravity, and a gap in the ground I have to jump over.",
    "sidescroll": "Make a side scrolling game where I run to the right and jump over rocks "
                  "with space. The trees and ground scroll past as I run. Add coins to "
                  "collect and a score.",
    "block3d": "Create a simple, block 3D game in first person. The world is made of 1 "
               "meter cubes, with a sky and ground. I use W and S to walk forward and back "
               "and A and D to turn around. Show a simple pair of hands at the bottom.",
}

CODE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def ask(provider, messages) -> tuple[str, bool, float]:
    """One reply: the code in it, whether a code block was found, and the seconds."""
    started = time.monotonic()
    for _chunk in provider.chat(messages, settings=Settings(temperature=0.0, max_tokens=4000)):
        pass
    reply = provider.finish()
    found = CODE.search(reply.text or "")
    return (found.group(1) if found else (reply.text or "")), bool(found), \
        round(time.monotonic() - started, 1)


def test(code: str, name: str):
    root = Path(tempfile.mkdtemp(prefix=f"oneshot-{name}-"))
    project = create_project(name, "games", root=root, starter_id=None)
    entry = project.directory / "src" / "game.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(code, encoding="utf-8")
    result = playtest.run(project.directory, project.profile.run_command)
    still = project.directory / result.still if result.still else None
    return result, root, still


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    repair = "--repair" in sys.argv
    label = args[0] if args else "one_shot"
    model = args[1] if len(args) > 1 else default_model_id()
    provider = build_provider(model, allow_cloud=not get_entry(model).info.is_local)
    provider.load()
    out_dir = HERE / "results" / label
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {"model": model, "system": SYSTEM, "games": {}}
    for name, request in GAMES.items():
        messages = [Message(role="system", content=SYSTEM),
                    Message(role="user", content=request)]
        code, found, seconds = ask(provider, messages)
        result, root, still = test(code, name)
        rounds = [{"verdict": result.verdict, "seconds": seconds, "lines": code.count("\n") + 1,
                   "truncated": not found, "error": result.error[-600:]}]
        while repair and result.failed and len(rounds) <= 2:
            shutil.rmtree(root, ignore_errors=True)
            messages = [*messages, Message(role="assistant", content=f"```python\n{code}```"),
                        Message(role="user", content=result.feedback() + "\n\nReply with the "
                                "whole corrected program in one ```python code block.")]
            code, found, seconds = ask(provider, messages)
            result, root, still = test(code, name)
            rounds.append({"verdict": result.verdict, "seconds": seconds,
                           "lines": code.count("\n") + 1, "truncated": not found,
                           "error": result.error[-600:]})
        frame = ""
        if still is not None and still.is_file():
            frame = str((out_dir / f"{name}.png").relative_to(HERE))
            shutil.copy(still, out_dir / f"{name}.png")
        out["games"][name] = {
            "request": request, "rounds": rounds, "verdict": result.verdict,
            "moved_by_itself": result.moved_by_itself,
            "responded_to": list(result.responded_to), "frame": frame, "code": code,
        }
        print(f"{name:11} {' -> '.join(r['verdict'] for r in rounds):40} "
              f"{rounds[-1]['lines']:4} lines {sum(r['seconds'] for r in rounds):6.1f} s  "
              f"moves={result.moved_by_itself} keys={','.join(result.responded_to)}"
              f"{'  ' + result.error.strip().splitlines()[-1] if result.error else ''}",
              flush=True)
        shutil.rmtree(root, ignore_errors=True)
        (HERE / "results" / f"{label}.json").write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    sys.exit(main())
