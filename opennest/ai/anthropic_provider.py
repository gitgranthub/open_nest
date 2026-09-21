"""Anthropic Claude, on the same provider interface as the local model.

WORKORDER_01 section 21: cloud providers use the same interface as local MLX, and the
application works without any of them. Nothing above :class:`AnthropicProvider` knows
which kind of model it is talking to -- the agent loop, the memory layer and the asset
layer are unchanged.

The Messages API is not shaped like the chat-completions format the rest of Open Nest
uses, so most of this file is translation:

- **System messages are lifted out.** Anthropic takes the system prompt as a top-level
  field, and Sonnet 5 rejects a mid-conversation ``role: "system"`` message outright.
  Open Nest only ever puts one at index 0, but lifting every one of them means a future
  mid-conversation system message degrades into the right thing instead of a 400.
- **Tool results are user messages.** A ``role: "tool"`` turn becomes a ``tool_result``
  content block inside a user message, and consecutive same-role turns are merged so the
  conversation alternates the way the API expects.
- **Nothing is prefilled.** Assistant prefill was removed on Sonnet 5 and returns a 400,
  so the reply is never shaped by seeding the assistant turn. Everything that shapes a
  reply goes through the system prompt, which is where Open Nest already puts it.

Model-specific request shapes are **data, not code** (section 3). ``provider_options`` in
``models.json`` is passed through to the request body untouched, which is what lets
Sonnet 5 declare ``thinking: {"type": "adaptive"}`` while Haiku 4.5 declares a
``budget_tokens`` form -- Sonnet 5 returns a 400 for ``budget_tokens`` and this provider
must not assume either shape.

**Request parameters follow declared capabilities, never an inference.** An earlier
version omitted ``temperature`` whenever a thinking block was present, which happened to
produce the right request for both models in the catalogue and was still wrong: whether
a model accepts a sampling temperature is a fact about that model, not something
derivable from the rest of the request. A model could reason and still accept one, or
reject one without thinking at all. So ``ModelInfo.supports_temperature`` and
``supports_thinking_budget`` are declared per entry, and this provider reads them.
:meth:`AnthropicProvider._check_thinking_budget` turns the ``budget_tokens`` mismatch
into a named configuration error rather than a 400 on every turn.

One consequence worth stating plainly. **Sonnet 5 cannot be pinned to temperature 0.**
Phase 1 measured temperature 0 as load-bearing for tool selection *on a 4B local model*;
it is not the same risk here, and the application's deterministic checks -- a claimed
edit with no write, a described file nobody read -- run regardless of which model
produced the sentence.
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

API_URL = "https://api.anthropic.com/v1/messages"

#: Pinned deliberately. An API version is a third-party interface contract, and the same
#: reasoning that pins every model to a commit SHA applies: it should change because
#: someone decided to change it.
API_VERSION = "2023-06-01"

PROVIDER = "anthropic"


class AnthropicProvider(ModelProvider):
    """Claude through the Messages API."""

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
        """Fetch the key. There are no weights, so this is the readiness check.

        The key is held for the life of the provider and never written down. Open Nest
        unloads a provider when a project closes, which is also when this is forgotten.
        """
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
            headers={
                "x-api-key": self._key or "",
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
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
        """One cheap round-trip, for the "Test Connection" button of section 2258.

        Deliberately a real request rather than a reachability ping: a key that is
        present but rejected is exactly the case this exists to catch.
        """
        self.load()
        request = Request(
            url=API_URL,
            headers={
                "x-api-key": self._key or "",
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            body={
                "model": self.model_id,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
            },
        )
        self.transport.send(request)
        return f"Connected to {self.info.name}."

    # -- request construction -----------------------------------------------

    def _body(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict] | None,
        settings: Settings,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        system, turns = split_system(messages)
        body: dict[str, Any] = {
            "model": self.model_id,
            # Same rule as the OpenAI provider: ``max_tokens`` covers hidden work as
            # well as the visible answer, so a model that thinks needs room beyond what
            # the caller asked for. This used to be applied on one provider only, which
            # left Sonnet -- adaptive thinking, no separate budget -- running on the
            # bare 1200 default with no detection either. See SPIKES.md section 13.
            "max_tokens": settings.max_tokens + self.info.output_headroom_tokens,
            "messages": turns,
            "stream": stream,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [to_anthropic_tool(schema) for schema in tools]

        # Model-specific shapes come from the catalogue, never from a branch in here.
        self._check_thinking_budget()
        body.update(self.provider_options)
        _make_room_for_thinking(body, settings.max_tokens)

        # Whether temperature may be sent is a declared capability of the model, not
        # something inferred from the presence of a thinking block. Sonnet 5 rejects it;
        # a future model might accept it alongside thinking, or reject it without any.
        # Only the catalogue can know, so only the catalogue decides.
        if self.info.supports_temperature:
            body["temperature"] = settings.temperature
        return body

    def _check_thinking_budget(self) -> None:
        """Refuse a manual thinking budget for a model that does not take one.

        Sonnet 5 returns a 400 for ``budget_tokens``. Catching it here turns a confusing
        runtime failure on every turn into a configuration error naming the model and
        the field, which is what it actually is.
        """
        thinking = self.provider_options.get("thinking")
        if not isinstance(thinking, dict) or "budget_tokens" not in thinking:
            return
        if self.info.supports_thinking_budget:
            return
        raise ProviderError(
            f"{self.info.name} does not accept a manual thinking budget, but "
            f"models.json sets budget_tokens for it. Remove it, or set "
            f"supports_thinking_budget on that entry."
        )


def _make_room_for_thinking(body: dict[str, Any], wanted_output: int) -> None:
    """Keep ``max_tokens`` above any thinking budget, which the API requires.

    Found by running the spike (SPIKES.md section 11): Anthropic rejects a request whose
    ``max_tokens`` is not greater than ``thinking.budget_tokens``, and on this API
    ``max_tokens`` covers thinking *and* the visible answer. With a 4000-token budget
    declared and the ``Settings`` default of 1200, **every call failed**.

    Neither side could have prevented that alone: the budget comes from the catalogue
    and ``max_tokens`` from the caller, and neither knows about the other. So the
    provider -- the one place that sees both -- reconciles them, by leaving the caller's
    requested output room *on top of* the budget rather than inside it. Silently
    shrinking the answer to fit would be the other option, and it would make a model
    that thinks quietly worse at replying.
    """
    thinking = body.get("thinking")
    if not isinstance(thinking, dict):
        return
    budget = thinking.get("budget_tokens")
    if not isinstance(budget, int) or budget <= 0:
        return
    if body.get("max_tokens", 0) <= budget:
        body["max_tokens"] = budget + max(1, wanted_output)


def split_system(messages: Sequence[Message]) -> tuple[str, list[dict]]:
    """Separate the system prompt from the conversation.

    Every system message is lifted, not just the first. Open Nest puts exactly one at
    index 0 today; if that ever changes, the alternative is a 400 from Sonnet 5 rather
    than a degraded but working conversation.
    """
    system_parts: list[str] = []
    turns: list[dict] = []

    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
            continue
        converted = to_anthropic_message(message)
        if converted is None:
            continue
        if turns and turns[-1]["role"] == converted["role"]:
            # The API expects alternating turns. Two tool results in a row, or a
            # follow-up nudge straight after one, would otherwise be two user messages.
            turns[-1]["content"].extend(converted["content"])
        else:
            turns.append(converted)

    return "\n\n".join(system_parts), turns


def to_anthropic_message(message: Message) -> dict | None:
    """One Open Nest message as an Anthropic turn, or None if it carries nothing."""
    if message.role == "tool":
        return {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": message.tool_call_id or message.name,
                "content": message.content or "",
            }],
        }

    blocks: list[dict] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    if message.role == "assistant":
        for index, call in enumerate(message.tool_calls):
            blocks.append({
                "type": "tool_use",
                "id": call.id or f"call_{index}",
                "name": call.name,
                "input": _as_object(call.arguments),
            })
    if not blocks:
        return None
    return {"role": message.role, "content": blocks}


def to_anthropic_tool(schema: dict) -> dict:
    """Translate one OpenAI-shaped tool schema into Anthropic's form.

    ``agent.tools.SCHEMAS`` is written once, in the shape the local model's chat template
    wants. Translating here keeps a single definition of what a tool is, rather than a
    second copy that can drift from the first.
    """
    function = schema.get("function", schema)
    return {
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "input_schema": function.get("parameters")
        or {"type": "object", "properties": {}, "required": []},
    }


def _as_object(arguments) -> dict:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class _StreamReader:
    """Assembles one reply out of the Messages API event stream.

    Tool arguments arrive as ``input_json_delta`` fragments that are only valid JSON once
    the whole block has been seen, so they are accumulated per content-block index and
    parsed at ``content_block_stop``.
    """

    def __init__(self) -> None:
        self._text: list[str] = []
        self._blocks: dict[int, dict] = {}
        self._calls: list[ToolCall] = []
        self._prompt_tokens = 0
        self._generated_tokens = 0
        self._stop_reason = ""

    def consume(self, event: Event) -> str:
        data = event.data or {}
        name = event.name or str(data.get("type", ""))

        if name == "error":
            detail = (data.get("error") or {}).get("message", "")
            raise ProviderError(
                "That AI service stopped part-way through."
                + (f"\n\n{detail}" if detail else "")
            )

        if name == "message_start":
            usage = ((data.get("message") or {}).get("usage")) or {}
            self._prompt_tokens = int(usage.get("input_tokens") or 0)
            return ""

        if name == "content_block_start":
            block = data.get("content_block") or {}
            if block.get("type") == "tool_use":
                self._blocks[int(data.get("index", 0))] = {
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "json": [],
                }
            return ""

        if name == "content_block_delta":
            delta = data.get("delta") or {}
            if delta.get("type") == "text_delta":
                piece = delta.get("text") or ""
                self._text.append(piece)
                return piece
            if delta.get("type") == "input_json_delta":
                pending = self._blocks.get(int(data.get("index", 0)))
                if pending is not None:
                    pending["json"].append(delta.get("partial_json") or "")
            # "thinking" deltas are deliberately not surfaced: the child sees the reply,
            # not the model working itself up to it.
            return ""

        if name == "content_block_stop":
            self._close_block(int(data.get("index", 0)))
            return ""

        if name == "message_delta":
            usage = data.get("usage") or {}
            self._generated_tokens = int(
                usage.get("output_tokens") or self._generated_tokens
            )
            delta = data.get("delta") or {}
            if isinstance(delta, dict) and delta.get("stop_reason"):
                self._stop_reason = str(delta["stop_reason"])
            return ""

        return ""

    def _close_block(self, index: int) -> None:
        pending = self._blocks.pop(index, None)
        if pending is None:
            return
        blob = "".join(pending["json"]).strip()
        arguments: dict = {}
        if blob:
            try:
                parsed = json.loads(blob)
            except json.JSONDecodeError:
                parsed = {}
            arguments = parsed if isinstance(parsed, dict) else {}
        self._calls.append(
            ToolCall(
                name=pending["name"],
                arguments=arguments,
                id=pending["id"] or f"call_{index}",
            )
        )

    def raise_if_silently_truncated(self) -> None:
        """The Anthropic half of the guard the OpenAI provider has had since section 11.

        Sonnet 5 runs adaptive thinking against the caller's ``max_tokens`` with no
        separate budget, so it can spend the whole allowance thinking and stop with
        ``stop_reason: max_tokens`` having said nothing. Nothing errors -- the response
        is well-formed and empty, which reaches a child as silence.

        This was a real asymmetry: ``output_headroom_tokens`` is applied by the OpenAI
        provider only, so Anthropic had both less room and no detection. Adding the
        detection makes the "one truncation recovery" guarantee true on both providers
        rather than on one.
        """
        if self._text or self._calls or self._blocks:
            return
        if self._stop_reason != "max_tokens":
            return
        raise TruncatedReply(
            "That AI service used up its whole answer allowance before it finished "
            "thinking, so there is nothing to show.\n\n"
            "Try asking for something smaller, or use the model on this Mac."
        )

    def result(self) -> Reply:
        # A stream cut off before content_block_stop still holds a usable call.
        for index in sorted(self._blocks):
            self._close_block(index)
        return Reply(
            text="".join(self._text).strip(),
            tool_calls=tuple(self._calls),
            prompt_tokens=self._prompt_tokens,
            generated_tokens=self._generated_tokens,
        )
