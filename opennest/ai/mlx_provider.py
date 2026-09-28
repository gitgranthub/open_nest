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
#: What is left of a tool call once every closed block is gone: an opening tag the model
#: never closed, because it ran out of output while writing the call. The same reasoning
#: as the unclosed ``<think>`` above. Measured in Phase 12.4 (SPIKES.md section 24F): the
#: model looped inside an ``edit_file`` argument until the cap, and the whole raw block
#: was shown to the child as Gary's reply.
_UNCLOSED_TOOL_CALL = re.compile(r"<tool_call>.*\Z", re.DOTALL)

#: How many scoring prefixes stay prefilled. One Fast Path decision asks the intent
#: question in three orderings and the "one change?" question in two, so five prefixes
#: are reused every turn -- measured in SPIKES.md section 25, four entries thrashed and
#: every decision cost 2.05 s instead of 0.44 s. Three more are room for a tweak's second
#: gate question and a detail question; those prefixes are short. ``unload`` frees all.
_SCORE_CACHE_ENTRIES = 8

#: KV space is reserved in steps of this many tokens. mlx_lm's default is 256, which for
#: a 363-token prefix reserves 512 -- measured at ~300 MB for the five prefixes a
#: decision uses. A prefix never grows past its suffix, so a fine step wastes nothing.
_SCORE_CACHE_STEP = 16

#: Stands in for the user's text while the fixed part of a scoring prompt is rendered, so
#: the rendered string can be split where the variable part begins.
_SCORE_SENTINEL = "⁣OPENNEST-SCORE⁣"


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
        #: Prefilled scoring prefixes, most recently used last: (prefix ids, KV cache).
        self._score_cache: list[tuple[list[int], Any]] = []

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
        self._score_cache = []
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

        self._reply = reply_from_completion(
            "".join(pieces),
            prompt_tokens=int(getattr(last, "prompt_tokens", 0) or 0),
            generated_tokens=int(getattr(last, "generation_tokens", 0) or 0),
        )
        yield Chunk(done=True)

    def finish(self) -> Reply:
        return self._reply

    # -- scoring, for the Fast Path -----------------------------------------

    def score_choices(self, system: str, user: str, labels: Sequence[str]) -> list[float]:
        """How likely each label is as the first token of the answer. Nothing generated.

        The Fast Path's classifier (``opennest.fastpath.classifier``) asks the model a
        closed question -- "which of these kinds of change is it? A, B, C..." -- and
        reads the next-token distribution at the point the answer would begin. One
        forward pass over the prompt, no sampling, no decoding loop. Measured in SPIKES.md
        section 25: ~50 ms with the fixed part cached, against 15-76 s for a generative
        turn.

        Returns natural-log probabilities over the **whole vocabulary**, one per label, so
        a caller can see how much of the model's mass the offered labels received at all
        and is not handed something already renormalised. Every label must be a single
        token; a label that is not is refused rather than scored on its first piece.

        The fixed part of the prompt -- everything before ``user`` -- is prefilled once
        and reused, then trimmed back after each question. Same weights, same thread as
        generation: nothing extra is loaded.
        """
        self.load()
        import mlx.core as mx
        from mlx_lm.models.cache import make_prompt_cache, trim_prompt_cache

        label_ids = []
        for label in labels:
            encoded = self._tokenizer.encode(label, add_special_tokens=False)
            if len(encoded) != 1:
                raise ProviderError(f"A scoring label must be one token: {label!r}")
            label_ids.append(encoded[0])

        rendered = self._render(
            [Message(role="system", content=system),
             Message(role="user", content=user)], None,
        )
        ids = self._tokenizer.encode(rendered, add_special_tokens=False)

        template = self._render(
            [Message(role="system", content=system),
             Message(role="user", content=_SCORE_SENTINEL)], None,
        )
        split = template.find(_SCORE_SENTINEL)
        prefix = (self._tokenizer.encode(template[:split], add_special_tokens=False)
                  if split > 0 else [])

        # A tokenizer may merge across the boundary; then the cached prefix is not a
        # prefix of this prompt and the whole thing is simply run uncached.
        if prefix and ids[:len(prefix)] == prefix and len(ids) > len(prefix):
            cache = self._cached_prefix(prefix, make_prompt_cache, mx)
            suffix = ids[len(prefix):]
            logits = self._model(mx.array([suffix]), cache=cache)[0, -1]
            logprobs = logits - mx.logsumexp(logits)
            chosen = mx.take(logprobs, mx.array(label_ids))
            mx.eval(chosen)
            trim_prompt_cache(cache, len(suffix))
        else:
            logits = self._model(mx.array([ids]))[0, -1]
            logprobs = logits - mx.logsumexp(logits)
            chosen = mx.take(logprobs, mx.array(label_ids))
            mx.eval(chosen)
        return [float(value) for value in chosen.tolist()]

    def _cached_prefix(self, prefix: list[int], make_prompt_cache, mx):
        for index, (ids, cache) in enumerate(self._score_cache):
            if ids == prefix:
                self._score_cache.append(self._score_cache.pop(index))
                return cache
        cache = make_prompt_cache(self._model)
        for layer in cache:
            if hasattr(layer, "step"):
                layer.step = _SCORE_CACHE_STEP
        mx.eval(self._model(mx.array([prefix]), cache=cache))
        self._score_cache.append((prefix, cache))
        del self._score_cache[:-_SCORE_CACHE_ENTRIES]
        return cache

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


def reply_from_completion(raw: str, *, prompt_tokens: int = 0,
                          generated_tokens: int = 0) -> Reply:
    """A finished completion as a :class:`Reply`: the calls, and only the prose."""
    calls = parse_tool_calls(raw)
    return Reply(
        text=strip_tool_calls(raw).strip(),
        tool_calls=calls,
        # More calls begun than could be read: cut off, or not JSON. Tool protocol is
        # never prose, so the text above has already lost it either way.
        dropped_tool_call=raw.count("<tool_call>") > len(calls),
        prompt_tokens=prompt_tokens,
        generated_tokens=generated_tokens,
    )


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

    An unclosed ``<tool_call>`` goes too, from its tag to the end: tool protocol is
    never something to show a child, finished or not, and the model cannot have meant
    anything it wrote after starting a call it never closed.
    """
    text = _TOOL_CALL_BLOCK.sub("", _THINK_BLOCK.sub("", text))
    text = _UNCLOSED_TOOL_CALL.sub("", text).replace("</tool_call>", "")
    return _FENCED_JSON.sub("", text)
