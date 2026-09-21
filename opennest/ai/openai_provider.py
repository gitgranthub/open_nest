"""OpenAI, on the same provider interface as the local model.

Built against the **Responses API**, which is the direction recorded in PLAN.md Phase 6.
As with :mod:`opennest.ai.anthropic_provider`, nothing above this file knows which kind
of model produced a reply.

The Responses API differs from the chat-completions shape Open Nest uses internally in
three ways, and that is most of what this file does:

- **The system prompt is ``instructions``**, a top-level field rather than a message.
- **The conversation is a flat list of items**, not alternating messages: a tool call and
  its result are ``function_call`` and ``function_call_output`` items sitting alongside
  the messages, keyed by ``call_id``.
- **Tool schemas are flat.** ``{"type": "function", "name": ...}`` rather than the nested
  ``{"function": {...}}`` form. ``agent.tools.SCHEMAS`` stays the single definition and
  is translated here, so a tool is never described twice.

Model-specific request shapes are data: ``provider_options`` in ``models.json`` is passed
through untouched, the same as for Anthropic. A model that declares ``reasoning`` has its
temperature omitted, because the API fixes it -- see the note in the Anthropic provider
about what that does and does not cost.

**Image generation is not here.** PLAN.md keeps ``gpt-image-2`` as decision D6, after this
phase, and records what it inherits from Phase 5 when it lands: a generated picture is an
ordinary imported asset and goes through ``assets.import_file``, and a model that
generated a picture still has not *seen* it, so ``can_interpret`` governs what may be
said about it afterwards.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

from opennest.ai.cloud import Event, Request, RequestsTransport, Transport
from opennest.ai.provider import (
    Chunk,
    Message,
    ModelInfo,
    ModelProvider,
    ProviderError,
    Reply,
    Settings,
    ToolCall,
    TruncatedReply,
)
from opennest.security import keychain

API_URL = "https://api.openai.com/v1/responses"

PROVIDER = "openai"


class OpenAIProvider(ModelProvider):
    """OpenAI through the Responses API."""

    def __init__(
        self,
        info: ModelInfo,
        model_id: str,
        *,
        transport: Transport | None = None,
        credentials: keychain.Credentials | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> None:
        self.info = info
        self.model_id = model_id
        self.transport = transport or RequestsTransport()
        self.credentials = credentials or keychain.default()
        self.provider_options = dict(provider_options or {})
        self._key: str | None = None
        self._reply = Reply()

    # -- lifecycle ----------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._key is not None

    def load(self) -> None:
        if self._key is not None:
            return
        key = self.credentials.get_key(PROVIDER)
        if not key:
            raise ProviderError(
                f"{self.info.name} needs an API key, and none is saved yet.\n\n"
                f"A parent can add one in Settings, under Cloud AI."
            )
        self._key = key

    def unload(self) -> None:
        self._key = None

    # -- generation ---------------------------------------------------------

    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict] | None = None,
        settings: Settings | None = None,
    ) -> Iterator[Chunk]:
        self.load()
        settings = settings or Settings()
        self._reply = Reply()

        request = Request(
            url=API_URL,
            headers=self._headers(),
            body=self._body(messages, tools, settings, stream=True),
        )

        reader = _StreamReader()
        for event in self.transport.stream(request):
            text = reader.consume(event)
            if text:
                yield Chunk(text=text)
        self._reply = reader.result()
        reader.raise_if_silently_truncated()
        yield Chunk(done=True)

    def finish(self) -> Reply:
        return self._reply

    def check_connection(self) -> str:
        """One cheap round-trip for the "Test Connection" button of section 2258."""
        self.load()
        self.transport.send(Request(
            url=API_URL,
            headers=self._headers(),
            body={
                "model": self.model_id,
                "input": [{"role": "user",
                           "content": [{"type": "input_text", "text": "Hi"}]}],
                "max_output_tokens": 16,
            },
        ))
        return f"Connected to {self.info.name}."

    # -- request construction -----------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key or ''}",
            "Content-Type": "application/json",
        }

    def _body(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict] | None,
        settings: Settings,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        instructions, items = split_instructions(messages)
        body: dict[str, Any] = {
            "model": self.model_id,
            "input": items,
            "stream": stream,
            # The cap covers reasoning *and* the visible answer, so a reasoning model
            # needs its own room on top of what the caller asked for. Without this,
            # gpt-5-mini spent an entire 120-token budget reasoning and streamed
            # nothing (SPIKES.md section 11).
            "max_output_tokens": settings.max_tokens + self.info.output_headroom_tokens,
        }
        if instructions:
            body["instructions"] = instructions
        if tools:
            body["tools"] = [to_openai_tool(schema) for schema in tools]

        body.update(self.provider_options)

        # Declared by the model, not inferred from the request. See the note on
        # ``ModelInfo.supports_temperature``.
        if self.info.supports_temperature:
            body["temperature"] = settings.temperature
        return body


def split_instructions(messages: Sequence[Message]) -> tuple[str, list[dict]]:
    """Separate the system prompt from the conversation items.

    Every system message is lifted into ``instructions``, for the same reason the
    Anthropic provider lifts them: the application puts exactly one at index 0, and a
    future mid-conversation system message should degrade into the right thing.
    """
    instructions: list[str] = []
    items: list[dict] = []

    for message in messages:
        if message.role == "system":
            if message.content:
                instructions.append(message.content)
            continue
        items.extend(to_openai_items(message))

    return "\n\n".join(instructions), items


def to_openai_items(message: Message) -> list[dict]:
    """One Open Nest message as Responses API input items.

    An assistant turn that called tools becomes a message item *and* one
    ``function_call`` item per call, because the Responses API keeps them side by side
    rather than nesting calls inside the message.
    """
    if message.role == "tool":
        return [{
            "type": "function_call_output",
            "call_id": message.tool_call_id or message.name,
            "output": message.content or "",
        }]

    items: list[dict] = []
    if message.content:
        content_type = "output_text" if message.role == "assistant" else "input_text"
        items.append({
            "role": message.role,
            "content": [{"type": content_type, "text": message.content}],
        })
    if message.role == "assistant":
        for index, call in enumerate(message.tool_calls):
            items.append({
                "type": "function_call",
                "call_id": call.id or f"call_{index}",
                "name": call.name,
                "arguments": _as_json_string(call.arguments),
            })
    return items


def to_openai_tool(schema: dict) -> dict:
    """Translate one nested tool schema into the Responses API's flat form."""
    function = schema.get("function", schema)
    return {
        "type": "function",
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "parameters": function.get("parameters")
        or {"type": "object", "properties": {}, "required": []},
    }


def _as_json_string(arguments) -> str:
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments or {})
    except (TypeError, ValueError):
        return "{}"


class _StreamReader:
    """Assembles one reply out of the Responses API event stream."""

    def __init__(self) -> None:
        self._text: list[str] = []
        self._pending: dict[str, dict] = {}
        self._order: list[str] = []
        self._prompt_tokens = 0
        self._generated_tokens = 0
        self._reasoning_tokens = 0
        self._incomplete_reason = ""

    def raise_if_silently_truncated(self) -> None:
        """Turn "the model ran out of room and said nothing" into something readable.

        A reasoning model that spends its whole output budget thinking returns a
        perfectly successful response containing no text and no tool call. Left alone
        that reaches the child as silence, which is the worst possible failure: nothing
        happened and nothing said why. Measured on gpt-5-mini (SPIKES.md section 11).
        """
        if self._text or self._order:
            return
        if self._incomplete_reason != "max_output_tokens":
            return
        raise TruncatedReply(
            "That AI service used up its whole answer allowance before it finished "
            "thinking, so there is nothing to show.\n\n"
            "Try asking for something smaller, or use the model on this Mac."
        )

    def consume(self, event: Event) -> str:
        data = event.data or {}
        name = event.name or str(data.get("type", ""))

        if name in ("error", "response.failed"):
            detail = _error_message(data)
            raise ProviderError(
                "That AI service stopped part-way through."
                + (f"\n\n{detail}" if detail else "")
            )

        if name == "response.output_text.delta":
            piece = data.get("delta") or ""
            if isinstance(piece, str) and piece:
                self._text.append(piece)
                return piece
            return ""

        if name == "response.output_item.added":
            item = data.get("item") or {}
            if item.get("type") == "function_call":
                key = str(item.get("id") or item.get("call_id") or len(self._order))
                self._pending[key] = {
                    "call_id": item.get("call_id") or item.get("id") or key,
                    "name": item.get("name", ""),
                    "arguments": [],
                }
                self._order.append(key)
            return ""

        if name == "response.function_call_arguments.delta":
            key = str(data.get("item_id") or (self._order[-1] if self._order else ""))
            pending = self._pending.get(key)
            if pending is not None:
                pending["arguments"].append(data.get("delta") or "")
            return ""

        if name == "response.function_call_arguments.done":
            key = str(data.get("item_id") or (self._order[-1] if self._order else ""))
            pending = self._pending.get(key)
            # "done" carries the complete string; prefer it over the reassembled deltas.
            if pending is not None and isinstance(data.get("arguments"), str):
                pending["arguments"] = [data["arguments"]]
            return ""

        if name in ("response.completed", "response.incomplete"):
            response = data.get("response") or {}
            usage = response.get("usage") or {}
            self._prompt_tokens = int(usage.get("input_tokens") or self._prompt_tokens)
            self._generated_tokens = int(
                usage.get("output_tokens") or self._generated_tokens
            )
            output_details = usage.get("output_tokens_details") or {}
            if isinstance(output_details, dict):
                self._reasoning_tokens = int(
                    output_details.get("reasoning_tokens") or self._reasoning_tokens
                )
            details = response.get("incomplete_details") or {}
            if isinstance(details, dict) and details.get("reason"):
                self._incomplete_reason = str(details["reason"])
            return ""

        return ""

    def result(self) -> Reply:
        calls: list[ToolCall] = []
        for index, key in enumerate(self._order):
            pending = self._pending.get(key)
            if pending is None:
                continue
            blob = "".join(pending["arguments"]).strip()
            arguments: dict = {}
            if blob:
                try:
                    parsed = json.loads(blob)
                except json.JSONDecodeError:
                    parsed = {}
                arguments = parsed if isinstance(parsed, dict) else {}
            calls.append(ToolCall(
                name=pending["name"],
                arguments=arguments,
                id=str(pending["call_id"]) or f"call_{index}",
            ))
        return Reply(
            text="".join(self._text).strip(),
            tool_calls=tuple(calls),
            prompt_tokens=self._prompt_tokens,
            generated_tokens=self._generated_tokens,
            reasoning_tokens=self._reasoning_tokens,
        )


def _error_message(data: dict) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "")
    response = data.get("response")
    if isinstance(response, dict) and isinstance(response.get("error"), dict):
        return str(response["error"].get("message") or "")
    return ""
