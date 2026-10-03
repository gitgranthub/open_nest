"""Does a local vision model see the child's pictures? Measured through Open Nest's code.

    scripts/offline.sh .venv/bin/python benchmarks/vision/look.py <label> [model-id]

SPIKES.md section 32. Through the shipped provider and ``assets.look`` -- the code a
project uses, not a reimplementation -- with no network:

- **looks**: each picture shown as a project would show it (see-through laid on white,
  scaled to ``PICTURE_PIXELS``), what the model says it shows, how long, how many tokens;
  the Open Nest eagle always, the owner's test04 pictures when ``assets/test_builds/`` is
  there (not in git -- point ``TEST04_PICTURES`` elsewhere);
- **the colour check** setup runs (``downloader.verify``);
- **blind**: the same weights loaded *without* the vision engine and asked about the
  eagle -- what a model says about a picture it was never shown, which is why the
  honesty checks stay on until the pixels really arrive;
- **memory**: MLX's peak.

Writes ``results/<label>.json``. Grades nothing: the descriptions are for a person.
"""

from __future__ import annotations

import builtins
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from opennest.ai.provider import Message, Settings  # noqa: E402
from opennest.ai.router import build_provider  # noqa: E402
from opennest.assets import look  # noqa: E402
from opennest.assets import manager as assets  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from opennest.setup import downloader  # noqa: E402

EAGLE = REPO / "assets/open_nest_asset_delivery/03_eagle_animation/frames_128/eagle_01.png"
OWNER = Path(os.environ.get("TEST04_PICTURES", REPO / "assets/test_builds"))


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "look"
    model = sys.argv[2] if len(sys.argv) > 2 else "qwen3-vl-4b-instruct"
    import mlx.core as mx

    pictures = [EAGLE] + sorted(OWNER.glob("*.png")) if OWNER.is_dir() else [EAGLE]
    root = Path(tempfile.mkdtemp(prefix="vision-look-"))
    project = create_project("Looking", "games", root=root)
    out: dict = {"model": model, "looks": []}

    provider = build_provider(model)
    started = time.monotonic()
    provider.load()
    out["load_s"] = round(time.monotonic() - started, 2)
    out["sees_images"] = provider.sees_images
    print(f"{model}: loaded in {out['load_s']} s, sees pictures: {provider.sees_images}")

    for source in pictures:
        asset = assets.import_file(project, source)
        started = time.monotonic()
        saw = look.look(project, provider, asset.path)
        reply = provider.finish()
        row = {"picture": source.name, "summary": asset.summary, "saw": saw,
               "seconds": round(time.monotonic() - started, 2),
               "prompt_tokens": reply.prompt_tokens}
        out["looks"].append(row)
        print(f"  {source.name:18} {row['seconds']:>5} s {row['prompt_tokens']:>4} tok  {saw}")

    check = downloader._sees_pictures(provider)
    out["colour_check"] = {"passed": check, "answer": provider.finish().text}
    print(f"  colour check: {check} ({provider.finish().text!r})")
    out["peak_memory_gb"] = round(mx.get_peak_memory() / 1e9, 2)
    print(f"  peak memory {out['peak_memory_gb']} GB")
    provider.unload()

    # The same weights, read without the vision engine: what is said about a picture
    # that never arrived.
    real_import = builtins.__import__

    def without_vision(name, *args, **kwargs):
        if name == "mlx_vlm" or name.startswith("mlx_vlm."):
            raise ImportError("the vision engine, left out on purpose")
        return real_import(name, *args, **kwargs)

    blind = build_provider(model)
    builtins.__import__ = without_vision
    try:
        blind.load()
    finally:
        builtins.__import__ = real_import
    question = [Message(role="system", content="You are Gary, a project helper."),
                Message(role="user", content="What is in my picture? One sentence.",
                        images=(str(EAGLE),))]
    for _ in blind.chat(question, settings=Settings(temperature=0.0, max_tokens=60)):
        pass
    out["blind"] = {"sees_images": blind.sees_images, "shown": list(blind.last_shown),
                    "said": blind.finish().text}
    print(f"  without the vision engine (sees {blind.sees_images}): "
          f"{blind.finish().text!r}")
    blind.unload()

    shutil.rmtree(root, ignore_errors=True)
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"{label}.json").write_text(json.dumps(out, indent=1) + "\n")
    print("written", HERE / "results" / f"{label}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
