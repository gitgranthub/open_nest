"""Local model provider built on Apple MLX.

Phase 1 obligation (SPIKES.md section 3): ``mlx_lm.load("<repo-id>")`` contacts the Hub
even when the snapshot is fully cached, and raises under ``HF_HUB_OFFLINE``. Left as-is
that would mean Open Nest needs the internet to use a *local* model, breaking
WORKORDER_01 section 34 outright.

So this provider resolves the pinned snapshot to a directory on disk first and hands
``mlx_lm`` a path. Nothing here touches the network once a model is installed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from opennest.ai.provider import (
    Chunk,
    Message,
    ModelInfo,
    ModelProvider,
    ProviderError,
    Reply,
    Settings,
    ToolCall,
)

#: Qwen-family chat templates wrap calls in these tags.
_TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
#: A reasoning model's internal monologue. Also matches an unclosed block, because a
#: reply cut off by ``max_tokens`` mid-thought has an opening tag and no closing one --
#: and that is the case where the most reasoning is on screen.
_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)


def resolve_local_model(model_id: str, revision: str | None = None) -> Path:
    """Find an installed model on disk without any network access.

    Searches every cache Open Nest is willing to look in, not just its own. Until Phase
    11B this looked in ``paths.models_dir()`` alone, which meant a model already sitting
    in the standard Hugging Face cache was invisible -- so Open Nest would offer to
    download a second copy of something already on the Mac, and a family who had run
    anything else that uses that cache would pay for it twice in gigabytes. Section 31
    of the Phase 11 work order names that case directly.

    The list of places is fixed and short (``models.discovery.search_paths``): approved
    caches, never a crawl of the disk.

    Raises :class:`ProviderError` with a plain-language message if it is not installed.
    """
    from opennest.models.discovery import locate

    located = locate(model_id, revision)
    if located is None:
        raise ProviderError(
            f"The local AI model is not installed yet.\n\n{model_id}\n\n"
            f"Open Settings and download it, or run Setup again."
        )
    return located


class MLXProvider(ModelProvider):
    """Runs a quantised model locally on Apple silicon."""

    def __init__(self, info: ModelInfo, model_id: str, revision: str | None = None) -> None:
        self.info = info
        self.model_id = model_id
        self.revision = revision
        self._model: Any = None
        self._tokenizer: Any = None
        self._reply = Reply()

    # -- lifecycle ----------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self.is_loaded:
            return
        try:
            from mlx_lm import load as mlx_load
        except ImportError as exc:
            raise ProviderError(
                "The local AI engine is not installed. Run Setup again to repair it."
            ) from exc

        local_path = resolve_local_model(self.model_id, self.revision)
        try:
            self._model, self._tokenizer = mlx_load(str(local_path))
        except Exception as exc:
            raise ProviderError(
                f"The local AI model could not be loaded.\n\n{exc}"
            ) from exc

    def unload(self) -> None:
        """Give the memory back. Reloading costs about a third of a second."""
        self._model = None
        self._tokenizer = None
        try:
            import mlx.core as mx

            mx.clear_cache()
        except (ImportError, AttributeError):
            pass

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

        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        prompt = self._render(messages, tools)
        sampler = make_sampler(temp=settings.temperature)

        pieces: list[str] = []
        last = None
        for response in stream_generate(
            self._model,
            self._tokenizer,
            prompt,
            max_tokens=settings.max_tokens,
            sampler=sampler,
        ):
            pieces.append(response.text)
            last = response
            yield Chunk(text=response.text)

        raw = "".join(pieces)
        calls = parse_tool_calls(raw)
        self._reply = Reply(
            text=strip_tool_calls(raw).strip(),
            tool_calls=calls,
            prompt_tokens=int(getattr(last, "prompt_tokens", 0) or 0),
            generated_tokens=int(getattr(last, "generation_tokens", 0) or 0),
        )
        yield Chunk(done=True)

    def finish(self) -> Reply:
        return self._reply

    def _render(self, messages: Sequence[Message], tools: Sequence[dict] | None) -> str:
        """Build the prompt, with reasoning switched off where the template offers it.

        ``enable_thinking=False`` is Qwen3's own template mechanism, and Phase 12
        measured what it does to each of the two shapes in the catalogue:

        - **Qwen3 8B / 14B** (the hybrid thinking models) gain a pre-closed
          ``<think>\\n\\n</think>`` in the generation prompt, so the model answers
          instead of reasoning out loud. Without it, the reply a child reads as Gary
          begins *"Okay, the user wants me to respond with exactly..."*.
        - **Qwen3 4B Instruct** ignores the flag completely -- the rendered prompt is
          byte-identical with it, without it, and with it set True.

        So it is safe to pass unconditionally, and the fallback below covers a template
        that refuses an unexpected argument rather than ignoring it.
        """
        payload = [m.as_dict() for m in messages]
        kwargs: dict[str, Any] = {"add_generation_prompt": True, "tokenize": False}
        if tools:
            kwargs["tools"] = list(tools)
        try:
            return self._tokenizer.apply_chat_template(
                payload, enable_thinking=False, **kwargs
            )
        except TypeError:
            pass
        except Exception as exc:
            raise ProviderError(f"The conversation could not be prepared: {exc}") from exc
        try:
            return self._tokenizer.apply_chat_template(payload, **kwargs)
        except Exception as exc:
            raise ProviderError(f"The conversation could not be prepared: {exc}") from exc


def parse_tool_calls(text: str) -> tuple[ToolCall, ...]:
    """Pull tool calls out of a raw completion.

    Accepts the native ``<tool_call>`` block first, then a fenced JSON object. Tool-name
    normalisation happens in the toolbox, not here -- this layer reports what the model
    said, and dispatch decides what it meant.
    """
    blobs = _TOOL_CALL_BLOCK.findall(text) or _FENCED_JSON.findall(text)
    calls: list[ToolCall] = []
    for index, blob in enumerate(blobs):
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        name = parsed.get("name") or parsed.get("tool")
        if not name and isinstance(parsed.get("function"), dict):
            name = parsed["function"].get("name")
        if not name:
            continue
        arguments = parsed.get("arguments", parsed.get("parameters", {}))
        calls.append(ToolCall(name=str(name), arguments=arguments, id=f"call_{index}"))
    return tuple(calls)


def strip_tool_calls(text: str) -> str:
    """The prose part of a reply: no call blocks, and no reasoning monologue.

    The ``<think>`` half is belt and braces behind ``_render``'s
    ``enable_thinking=False``. It is worth having because the prompt flag is a request
    to a chat template and this is a fact about the string: a model that reasons anyway,
    a future catalogue entry whose template spells the flag differently, or the
    pre-closed ``<think></think>`` the flag itself inserts would each otherwise reach
    the child as Gary's words.
    """
    return _FENCED_JSON.sub(
        "", _TOOL_CALL_BLOCK.sub("", _THINK_BLOCK.sub("", text))
    )
