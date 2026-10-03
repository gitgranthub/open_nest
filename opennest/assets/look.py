"""Looking at a child's picture once, with a model that can see -- and keeping what it saw.

SPIKES.md section 32. Until a local vision model arrived nothing in Open Nest had ever
seen a picture, and section 6A's rule was the whole of the policy: the application may
state facts about the file, never about the picture. A vision model changes the second
half only where it is *true*: a picture whose pixels have reached a model, and whose
answer is recorded, has been looked at. Nothing else has.

So this is evidence, not a capability flag. ``provider.can_send_images`` says a model
*could* be shown a picture; a record here says one *was* -- the picture went through
``MLXProvider.chat`` as pixels (``last_shown`` names it) and the model said what it shows.
The record is keyed by the file's bytes, so a picture replaced under the same name is
unread again until it is looked at again, which is section 6A's reason for deriving
assets live, kept.

**Why once, and in words.** A picture is looked at when it comes into the project, and
what was seen goes into the prompt every turn as one sentence (``manager.context_block``)
-- not as pixels every turn. Pixels cost ~170 tokens a picture at ``PICTURE_PIXELS`` and
the owner's test04 had seven; a sentence costs fifteen, works for whichever model is
Gary afterwards, and leaves every check that reads the prompt as text unchanged. A
picture attached to a message still travels as pixels with that message
(``AgentController``), so "what is this?" is answered by looking.

**Not a turn.** Looking is done for the picture, once, before or between turns: it is
one short local call per new picture and spends nothing from a turn's call budget --
the owner's six trees would otherwise have been half of one message's twelve calls.
It only ever runs on a provider that really sends pixels, which today is local.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from opennest.ai.provider import Message, ModelProvider, Settings, can_send_images
from opennest.assets import kinds
from opennest.versioning.autosave import atomic_write_text
from opennest.versioning.secret_scanner import scan_text

#: Where what was seen is kept, inside the project: it is part of the project's own
#: knowledge (versioned with it, like the bible), and small.
RECORD = ".opennest/looked.json"

#: The one question. A sentence a child can read, what the thing is and its colours --
#: the two things a game needs -- and never the background: a see-through picture is
#: shown on white (``mlx_provider.prepare_picture``), and measured, the 4B then said
#: "against a white background" of a sprite with no background at all.
QUESTION = (
    "What does this picture show? Answer in one short sentence a child would "
    "understand: what it is, and its main colours. Do not mention the background."
)

#: One sentence. Measured answers were 13-24 tokens.
MAX_TOKENS = 60

#: A sentence longer than this is cut at its last full stop inside it.
MAX_CHARS = 220

_LEAD = re.compile(
    r"^\s*(?:(?:this|the) (?:picture|image|photo|drawing) (?:shows|is of|is)|it shows|"
    r"this is|it is|it's|here is|i see|i can see)\s+",
    re.IGNORECASE)


def digest(path: Path) -> str:
    """The file's SHA-256 -- remembered while its size and modification time stand, since
    the prompt is rebuilt several times a turn and the owner's pictures are 0.5-2 MB."""
    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    known = _DIGESTS.get(key)
    if known is None:
        known = hashlib.sha256(path.read_bytes()).hexdigest()
        if len(_DIGESTS) > 512:
            _DIGESTS.clear()
        _DIGESTS[key] = known
    return known


_DIGESTS: dict[tuple, str] = {}


def _record(project) -> dict:
    try:
        data = json.loads((project.directory / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def seen(project) -> dict[str, str]:
    """What was seen in each picture, by project-relative path -- only where the file is
    still exactly the one that was looked at."""
    found: dict[str, str] = {}
    for relative, entry in _record(project).items():
        if not isinstance(entry, dict) or not isinstance(entry.get("saw"), str):
            continue
        path = project.directory / relative
        try:
            if path.is_file() and digest(path) == entry.get("sha256"):
                found[relative] = entry["saw"]
        except OSError:
            continue
    return found


def can_look(provider: ModelProvider | None) -> bool:
    """Whether this provider could be shown a picture -- before loading anything."""
    return can_send_images(getattr(provider, "info", None))


def look(project, provider: ModelProvider, relative: str) -> str:
    """Show one picture to the model and keep what it says it shows. Empty when it
    could not be looked at: the model cannot see, the picture would not open, or the
    answer was nothing usable."""
    if not can_look(provider):
        return ""
    provider.load()
    if not getattr(provider, "sees_images", False):
        return ""
    path = project.directory / relative
    try:
        before = digest(path)
    except OSError:
        return ""
    message = Message(role="user", content=QUESTION, images=(str(path),))
    for _ in provider.chat([message], settings=Settings(temperature=0.0,
                                                         max_tokens=MAX_TOKENS)):
        pass
    if str(path) not in getattr(provider, "last_shown", ()):
        return ""
    saw = tidy(provider.finish().text)
    # A screenshot can hold a key, and a model can read it out. What was seen is written
    # into the project, so it meets the same scan as everything else written there.
    if not saw or scan_text(saw):
        return ""
    record = _record(project)
    record[relative] = {"sha256": before, "saw": saw,
                        "by": getattr(getattr(provider, "info", None), "id", "")}
    atomic_write_text(project.directory / RECORD,
                      json.dumps(record, indent=1, sort_keys=True) + "\n")
    return saw


def tidy(text: str) -> str:
    """The model's answer as the words for "it shows: ...": its first sentence, without
    "This picture shows", with no closing full stop."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = _LEAD.sub("", text)
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS].rfind(".")
        text = text[:cut] if cut > 40 else text[:MAX_CHARS].rsplit(" ", 1)[0]
    return text.strip().rstrip(".!").strip()


def unlooked(project, assets) -> list:
    """The pictures among ``assets`` that nothing has looked at yet."""
    return [asset for asset in assets if asset.kind == kinds.IMAGE and not asset.seen]
