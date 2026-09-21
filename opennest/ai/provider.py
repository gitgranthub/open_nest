"""The interface every model provider implements.

WORKORDER_01 section 2: the rest of the application must not depend on a specific model
service. Local MLX, OpenAI and Anthropic all arrive through this one shape.

Deviation from the sketch in the work order, noted deliberately: ``chat`` is a synchronous
generator rather than an ``async def``. MLX generation is synchronous and CPU/GPU bound,
so it gains nothing from asyncio and would need a thread anyway. The UI keeps responsive
by running providers in a Qt worker thread. Cloud providers will stream the same way.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] | str
    id: str = ""


@dataclass
class Message:
    role: str                      # system | user | assistant | tool
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    #: For role="tool": which call this is answering.
    tool_call_id: str = ""
    name: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id or f"call_{index}",
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for index, call in enumerate(self.tool_calls)
            ]
        if self.role == "tool":
            payload["name"] = self.name
            if self.tool_call_id:
                payload["tool_call_id"] = self.tool_call_id
        return payload


@dataclass
class Chunk:
    """One streamed piece of a reply."""

    text: str = ""
    done: bool = False


@dataclass
class Reply:
    """A complete assistant turn."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    prompt_tokens: int = 0
    generated_tokens: int = 0
    #: Of ``generated_tokens``, how many were spent reasoning where the service says so.
    #: Billed as output and never shown to the child, so it is the part of a bill that
    #: cannot be inferred from what appeared on screen. Zero when unreported -- Anthropic
    #: folds thinking into ``output_tokens`` without breaking it out.
    reasoning_tokens: int = 0

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class Settings:
    """Per-request generation settings.

    Temperature defaults to 0. Phase 1 measured tool selection at temperature 0 and that
    is the configuration the agent relies on; sampling is for prose, not for choosing
    which file to write.
    """

    temperature: float = 0.0
    max_tokens: int = 1200
    seed: int | None = None


@dataclass
class ModelInfo:
    """What the application needs to know about a model without loading it."""

    id: str
    name: str
    provider: str
    description: str = ""
    supports_images: bool = False
    supports_documents: bool = True
    supports_tools: bool = True
    requires_internet: bool = False
    may_cost_money: bool = False
    context_policy: dict[str, int] = field(default_factory=dict)

    #: Whether this model accepts a sampling temperature. Declared per model rather than
    #: inferred from anything else about the request: a model that reasons or thinks may
    #: fix its own sampling and reject the parameter outright, and which models do that
    #: is a fact about the model, not a rule the application can derive. Local MLX models
    #: accept it and Phase 1 measured that Open Nest needs them to (temperature 0 for
    #: tool selection), so the default is True and a model that cannot opts out.
    supports_temperature: bool = True

    #: Whether this model accepts a manually-set thinking budget. Sonnet 5 uses adaptive
    #: thinking and returns a 400 for ``budget_tokens``; Haiku 4.5 still takes one. False
    #: by default because most models have no thinking to budget.
    supports_thinking_budget: bool = False

    #: Extra output room this model needs beyond what the caller asks for, because its
    #: output cap covers hidden work as well as the visible answer. Zero for a model
    #: with nothing hidden to pay for.
    #:
    #: **Renamed from ``output_headroom_tokens`` once it was measured.** It was
    #: introduced for reasoning -- gpt-5-mini given 120 output tokens spent all 64 it
    #: used on reasoning and streamed an empty reply. But measuring Luna properly
    #: (SPIKES.md section 13) showed reasoning is the *smaller* claim on it: 14-334
    #: tokens, against a long answer that wanted 2179 output tokens with a default cap
    #: of 1200. So the field is what it does -- headroom for the whole output -- and
    #: not what first motivated it. A name that describes only half the reason is how
    #: the next person sets it to 400 and truncates a good answer.
    output_headroom_tokens: int = 0

    @property
    def is_local(self) -> bool:
        return not self.requires_internet


#: Whether **any** provider can currently put image bytes in front of a model.
#:
#: Flip this to True in the same change that implements it, and not before. It is a
#: statement about the transport, not about the models: ``models.json`` has entries with
#: ``supports_images: true`` and those flags are correct -- Claude and OpenAI really can
#: see pictures. What was missing until this existed is that **Open Nest never sends
#: them any**, so a vision model receives exactly as many pixels as a 4B local one.
#:
#: Phase 6 made that gap dangerous rather than merely incomplete. Before it, no cloud
#: model was reachable, so ``assets.can_interpret`` answered False for every image and
#: Phase 5's honesty machinery stayed on. With a key configured and Claude selected it
#: began answering True -- which removed the "NOBODY HAS LOOKED" block from the prompt
#: *and* took the image out of ``unread_assets``, which is the set
#: ``assets.invented_description`` checks. Both defences off, no pixels sent: the exact
#: configuration SPIKES.md section 10 measured as producing "Yes, the dragon in the
#: picture has wings. I see them clearly."
#:
#: Found by running spikes/spike_image_generation.py (SPIKES.md section 12).
IMAGE_INPUT_IMPLEMENTED = False


class ProviderError(Exception):
    """Something went wrong talking to a model, phrased for a person to read."""


class TruncatedReply(ProviderError):
    """The model used its whole output allowance and said nothing.

    Its own class because it is the one provider failure worth *retrying*: the request
    was fine and the answer simply did not fit. Everything else -- a bad key, no credit,
    a refused model -- will fail again identically, and retrying it just spends a
    parent's money twice.
    """


class ModelProvider(ABC):
    """A source of model replies."""

    info: ModelInfo

    @abstractmethod
    def load(self) -> None:
        """Make the model ready. Safe to call repeatedly."""

    @abstractmethod
    def unload(self) -> None:
        """Release the model. Called when idle to give memory back on an 8 GB Mac."""

    @property
    @abstractmethod
    def is_loaded(self) -> bool: ...

    @abstractmethod
    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict] | None = None,
        settings: Settings | None = None,
    ) -> Iterator[Chunk]:
        """Stream a reply. Call :meth:`finish` afterwards for the parsed result."""

    @abstractmethod
    def finish(self) -> Reply:
        """The completed reply from the most recent :meth:`chat`."""
