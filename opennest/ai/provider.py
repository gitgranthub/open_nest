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

    @property
    def is_local(self) -> bool:
        return not self.requires_internet


class ProviderError(Exception):
    """Something went wrong talking to a model, phrased for a person to read."""


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
