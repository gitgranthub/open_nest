"""Asking a service for a picture, for the Image Creation profile.

PLAN.md decision D6. Three things about this are deliberate.

**The image model is not in ``models.json``.** A catalogue entry is something that
answers a conversation, and this one cannot: it takes a sentence and returns a PNG. It
lives on the profile instead, so the Image Creation profile carries its own provider and
model name and nothing has to special-case a chat model that is not one.

**Generating is not a project run.** The process sandbox denies network, so a child's own
code could never call an image service -- and should not be able to. This is the
application making one request on an explicit instruction, which is what
``run_mode: generate`` means.

**A generated picture is an ordinary asset, and nothing has seen it.** Both rules come
from Phase 5 and both were checked against the real service (SPIKES.md sections 12 and
14): the PNG goes through :func:`assets.import_file` like a dragged-in file, and
``can_interpret`` still answers False afterwards, so the honesty block stays in the
prompt. Measured: 798 KB and 10.9 s for a 1024x1024 image at ``quality=low``.
"""

from __future__ import annotations

import base64
import binascii

from opennest.ai import cloud
from opennest.ai.provider import ProviderError
from opennest.assets import manager as assets
from opennest.projects.manager import Project
from opennest.projects.profiles import Profile

#: Where each supported provider takes an image request. One entry today; a second
#: provider would be a line here rather than a branch in the caller.
ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/images/generations",
}

#: Cheapest useful setting. Quality is a cost knob, and the default belongs on the
#: cautious side of one -- a parent can be shown the difference before it moves.
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "low"


def unmet_requirements(
    profile: Profile,
    *,
    allow_cloud: bool,
    credentials=None,
) -> str | None:
    """Why this profile cannot be used right now, in a sentence, or None.

    Two separate permissions with two different remedies, exactly as Phase 6 settled for
    cloud models: the master switch is a parent decision, and a missing key is a
    different parent decision. Conflating them tells a parent to fix the wrong thing.
    """
    provider = profile.requires_cloud_provider
    if not provider:
        return None

    if not allow_cloud:
        return (
            "Making pictures uses the internet, and cloud AI is turned off.\n\n"
            "A parent can turn it on in Settings."
        )
    if credentials is None or not credentials.has_key(provider):
        return (
            f"Making pictures needs an {provider.upper()} key, and there is not one "
            f"saved yet.\n\nA parent can add one in Settings."
        )
    if provider not in ENDPOINTS:
        return f"Open Nest does not know how to make pictures with {provider}."
    return None


def generate(
    profile: Profile,
    description: str,
    *,
    credentials,
    transport: cloud.Transport | None = None,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
) -> bytes:
    """One image, as PNG bytes.

    Returned inline as base64 rather than as a URL, which is why there is no second
    fetch here and nothing that can expire before it is saved.
    """
    provider = profile.image_provider
    model = profile.image_model
    if not provider or not model:
        raise ProviderError("This project type is not set up to make pictures.")
    endpoint = ENDPOINTS.get(provider)
    if endpoint is None:
        raise ProviderError(f"Open Nest cannot make pictures with {provider}.")

    key = credentials.get_key(provider)
    if not key:
        raise ProviderError(
            f"There is no {provider.upper()} key saved. A parent can add one in Settings."
        )

    payload = (transport or cloud.RequestsTransport()).send(
        cloud.Request(
            url=endpoint,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            body={
                "model": model,
                "prompt": description,
                "size": size,
                "quality": quality,
                "n": 1,
            },
        )
    )

    items = payload.get("data") or []
    if not items:
        raise ProviderError("The picture service did not send a picture back.")
    encoded = items[0].get("b64_json")
    if not encoded:
        raise ProviderError("The picture service sent something Open Nest could not read.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProviderError("The picture came back damaged.") from exc
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        # Described, never assumed: describe.py reads real headers, so handing it
        # something that is not a PNG would produce a confidently wrong description.
        raise ProviderError("The picture service sent a file that is not a PNG.")
    return raw


def filename_for(description: str, existing: int = 0) -> str:
    """A filename made from the child's own words, so they can find it again."""
    words = [word for word in "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in description.lower()
    ).split()][:4]
    stem = "-".join(words) or "picture"
    suffix = f"-{existing + 1}" if existing else ""
    return f"{stem}{suffix}.png"


def generate_into(
    project: Project,
    description: str,
    *,
    credentials,
    transport: cloud.Transport | None = None,
) -> assets.Asset:
    """Generate a picture and import it into the project as an ordinary asset.

    The import is the Phase 5 path, not a second way into the project: the file is
    classified, copied into ``assets/`` and described from its real header, which is
    what keeps ``can_interpret`` and ``invented_description`` working on it afterwards.
    """
    raw = generate(project.profile, description, credentials=credentials, transport=transport)

    staging = project.internal_dir / "tmp"
    staging.mkdir(parents=True, exist_ok=True)
    existing = len(list((project.directory / "assets").glob("*.png")))
    scratch = staging / filename_for(description, existing)
    scratch.write_bytes(raw)
    try:
        return assets.import_file(project, scratch)
    finally:
        scratch.unlink(missing_ok=True)
