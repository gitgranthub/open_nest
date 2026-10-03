"""Local model provider built on Apple MLX.

Phase 1 obligation (SPIKES.md section 3): ``mlx_lm.load("<repo-id>")`` contacts the Hub
even when the snapshot is fully cached, and raises under ``HF_HUB_OFFLINE``. Left as-is
that would mean Open Nest needs the internet to use a *local* model, breaking
WORKORDER_01 section 34 outright.

So this provider resolves the pinned snapshot to a directory on disk first and hands
``mlx_lm`` a path. Nothing here touches the network once a model is installed.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

# Tool protocol written as text is recognised in ``opennest.ai.protocol``, shared with
# every provider's replies (``agent.replies.presentable``); re-exported here for callers.
from opennest.ai.protocol import (
    _BARE_JSON,
    _FENCED_JSON,
    _names_a_tool,
    _text_call_spans,
    parse_tool_calls,
    strip_tool_calls,
)
from opennest.ai.provider import (
    Chunk,
    Message,
    ModelInfo,
    ModelProvider,
    ProviderError,
    Reply,
    Settings,
)

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

#: The most pixels a picture is shown at. Qwen3-VL turns every 32x32 square into one
#: token, and its processor's own ceiling is 16 million pixels -- the owner's 1278x1230
#: monster would have been ~1,500 tokens of a 16,000-token window. Measured (SPIKES.md
#: section 32): at 384x384 the 4B named the monster, its purple spots and antennae, and
#: each tree's kind and colours as well as at 512x512, in ~170 tokens and 0.6 s.
PICTURE_PIXELS = 384 * 384


@contextlib.contextmanager
def _no_compiling_on_the_main_thread():
    """Run the model without MLX compilation when this is the main thread.

    **Otherwise quitting can crash.** MLX keeps a cache of compiled functions *per
    thread* (``mlx_lm`` compiles ``swiglu``, so every forward pass fills one), and a
    thread's cache is destroyed when that thread ends. A worker's ends while Python is
    running. The main thread's ends inside ``exit()``, *after* Python has finalised --
    and an entry still in it releases a Python object on the way out, which is a
    segfault and a macOS crash report on quit (SPIKES.md section 26H). The entry is
    only still there when something keeps the model alive past finalisation, which is
    exactly the application's case.

    Measured with no Qt at all: generating on the main thread with the model still
    referenced at exit crashed every time (exit 139, the same stack as the app walks);
    on a worker thread, or on the main thread with this switch, it exited cleanly.

    The main thread's one use of the model is the summary written when a project closes
    (``AgentController.close``). With compilation off it builds no cache entry, so there
    is nothing for ``exit()`` to destroy. The switch is global to MLX, so anything a
    worker runs meanwhile is simply not compiled either -- slower, never wrong -- and it
    is put back straight afterwards. A person who set ``MLX_DISABLE_COMPILE`` keeps it.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    import mlx.core as mx

    mx.disable_compile()
    try:
        yield
    finally:
        if not os.environ.get("MLX_DISABLE_COMPILE"):
            mx.enable_compile()


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
    """Runs a quantised model locally on Apple silicon.

    A vision model (``supports_images`` in the catalogue -- Qwen3-VL) is loaded through
    the vision engine, ``mlx_vlm``, so that a picture on a message reaches it as pixels.
    The same weights answer everything else: text turns go through the vision engine's
    generation with no picture, and the Fast Path's scoring runs the model's language
    half directly. Nothing is loaded twice.

    If the vision engine is missing, a vision model still works as a text model --
    ``mlx_lm`` reads the language half of a Qwen3-VL checkpoint -- and ``sees_images``
    says so: Gary keeps working and nobody is told he has looked at anything.
    """

    def __init__(self, info: ModelInfo, model_id: str, revision: str | None = None) -> None:
        self.info = info
        self.model_id = model_id
        self.revision = revision
        self._model: Any = None
        self._tokenizer: Any = None
        #: The vision engine's processor, when the model was loaded with its vision half.
        self._processor: Any = None
        self._reply = Reply()
        #: The pictures the most recent :meth:`chat` really showed the model.
        self.last_shown: tuple[str, ...] = ()
        #: Prefilled scoring prefixes, most recently used last: (prefix ids, KV cache).
        self._score_cache: list[tuple[list[int], Any]] = []

    # -- lifecycle ----------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def sees_images(self) -> bool:
        return self._processor is not None

    def load(self) -> None:
        if self.is_loaded:
            return
        local_path = resolve_local_model(self.model_id, self.revision)
        if self.info.supports_images:
            try:
                from mlx_vlm import load as vision_load
            except ImportError:
                vision_load = None
            if vision_load is not None:
                try:
                    self._model, self._processor = vision_load(str(local_path))
                except Exception as exc:
                    raise ProviderError(
                        f"The local AI model could not be loaded.\n\n{exc}"
                    ) from exc
                self._tokenizer = self._processor.tokenizer
                return
        try:
            from mlx_lm import load as mlx_load
        except ImportError as exc:
            raise ProviderError(
                "The local AI engine is not installed. Run Setup again to repair it."
            ) from exc

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
        self._processor = None
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
        self.last_shown = ()

        shown, pictures = self._pictures(messages) if self.sees_images else ((), [])
        prompt = self._render(messages, tools, pictures=len(pictures))
        if self.sees_images:
            from mlx_vlm import stream_generate as vision_generate

            stream = vision_generate(
                self._model, self._processor, prompt, image=pictures or None,
                max_tokens=settings.max_tokens, temperature=settings.temperature,
            )
        else:
            from mlx_lm import stream_generate
            from mlx_lm.sample_utils import make_sampler

            stream = stream_generate(
                self._model, self._tokenizer, prompt, max_tokens=settings.max_tokens,
                sampler=make_sampler(temp=settings.temperature),
            )

        pieces: list[str] = []
        last = None
        # Around the loop itself: this is a generator, so the model runs on whichever
        # thread iterates it, and that is the thread that matters.
        with _no_compiling_on_the_main_thread():
            for response in stream:
                pieces.append(response.text)
                last = response
                yield Chunk(text=response.text)
        #: The pictures this reply was given, as pixels -- the evidence ``assets.look``
        #: records, rather than what a caller asked for.
        self.last_shown = shown

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
        with _no_compiling_on_the_main_thread():
            return self._score(system, user, labels)

    def _score(self, system: str, user: str, labels: Sequence[str]) -> list[float]:
        import mlx.core as mx

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
            cache = self._cached_prefix(prefix)
            suffix = ids[len(prefix):]
            logits = self._forward(suffix, cache, len(prefix))[0, -1]
            logprobs = logits - mx.logsumexp(logits)
            chosen = mx.take(logprobs, mx.array(label_ids))
            mx.eval(chosen)
            for layer in cache:
                layer.trim(len(suffix))
        else:
            logits = self._forward(ids, None, 0)[0, -1]
            logprobs = logits - mx.logsumexp(logits)
            chosen = mx.take(logprobs, mx.array(label_ids))
            mx.eval(chosen)
        return [float(value) for value in chosen.tolist()]

    def _forward(self, ids: list[int], cache, offset: int):
        """Logits for ``ids``, continuing ``cache`` from position ``offset``.

        A vision model's language half places each token in three dimensions (time,
        height, width -- Qwen3-VL's multimodal rotary positions) and, left to itself,
        works them out from state kept on the model by the last generation, which may
        have held a picture. Text has all three equal to the token's place in the
        sequence, which is exactly ordinary positions, so they are given explicitly.
        """
        import mlx.core as mx

        if not self.sees_images:
            return self._model(mx.array([ids]), cache=cache)
        positions = mx.broadcast_to(mx.arange(offset, offset + len(ids))[None, None, :],
                                    (3, 1, len(ids)))
        language = self._model.language_model
        return language(mx.array([ids]), cache=cache, position_ids=positions).logits

    def _cached_prefix(self, prefix: list[int]):
        import mlx.core as mx

        for index, (ids, cache) in enumerate(self._score_cache):
            if ids == prefix:
                self._score_cache.append(self._score_cache.pop(index))
                return cache
        if self.sees_images:
            from mlx_vlm.models.cache import make_prompt_cache

            cache = make_prompt_cache(self._model.language_model)
        else:
            from mlx_lm.models.cache import make_prompt_cache

            cache = make_prompt_cache(self._model)
        for layer in cache:
            if hasattr(layer, "step"):
                layer.step = _SCORE_CACHE_STEP
        mx.eval(self._forward(prefix, cache, 0))
        self._score_cache.append((prefix, cache))
        del self._score_cache[:-_SCORE_CACHE_ENTRIES]
        return cache

    def _pictures(self, messages: Sequence[Message]) -> tuple[tuple[str, ...], list]:
        """The pictures to show with this request, ready: (paths, images).

        Those of the latest message that carries any -- the child's message, for every
        call of its turn, including after a correction Open Nest adds. The controller
        takes them off when the turn is settled, so a picture is not sent again every
        turn: what was seen is in the prompt as words from then on (``assets.look``). A
        picture that will not open is left out rather than failing the turn.
        """
        carrying = _carrying(messages)
        shown, pictures = [], []
        for path in (messages[carrying].images if carrying is not None else ()):
            picture = prepare_picture(path)
            if picture is not None:
                shown.append(path)
                pictures.append(picture)
        return tuple(shown), pictures

    def _render(self, messages: Sequence[Message], tools: Sequence[dict] | None, *,
                pictures: int = 0) -> str:
        """Build the prompt, with reasoning switched off where the template offers it.

        ``enable_thinking=False`` is Qwen3's own template mechanism, and Phase 12
        measured what it does to each of the two shapes in the catalogue:

        - **Qwen3 8B / 14B** (the hybrid thinking models) gain a pre-closed
          ``<think>\\n\\n</think>`` in the generation prompt, so the model answers
          instead of reasoning out loud. Without it, the reply a child reads as Gary
          begins *"Okay, the user wants me to respond with exactly..."*.
        - **Qwen3 4B Instruct** ignores the flag completely -- the rendered prompt is
          byte-identical with it, without it, and with it set True.
        - **Qwen3-VL 4B and 8B Instruct** (Gary Fast and Gary Smart) render a tool
          conversation byte for byte as Qwen3 4B Instruct does (SPIKES.md section 32).

        So it is safe to pass unconditionally, and the fallback below covers a template
        that refuses an unexpected argument rather than ignoring it.

        ``pictures``: how many pictures the message being answered carries, as
        :meth:`_pictures` prepared them. Each gets the template's own picture marker,
        ahead of the words, which the vision engine replaces with the picture's pixels.
        """
        payload = [m.as_dict() for m in messages]
        carrying = _carrying(messages) if pictures else None
        if carrying is not None:
            payload[carrying]["content"] = [{"type": "image"} for _ in range(pictures)] + [
                {"type": "text", "text": messages[carrying].content}]
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


def _carrying(messages: Sequence[Message]) -> int | None:
    """Where the latest message with pictures on it is, if any."""
    return next((index for index in range(len(messages) - 1, -1, -1)
                 if messages[index].images), None)


def prepare_picture(path: str):
    """A picture as the model is shown it, or ``None`` if it will not open.

    Two things the vision engine would get wrong left to itself, both measured on the
    pictures the owner tested with (SPIKES.md section 32):

    - **See-through pixels became black.** The engine converts to plain colour, and a
      transparent pixel's colour is usually black: the Open Nest eagle, a dark bird on
      nothing, was "a completely black image with no discernible content". A child's
      sprite is very often see-through, so it is laid on white first.
    - **Size.** Shown at full size, the owner's 1278x1230 monster is ~1,500 tokens.
      Scaled to ``PICTURE_PIXELS`` it is ~170 and described just as well.
    """
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as opened:
            picture = ImageOps.exif_transpose(opened)
            picture.load()
    except Exception:  # noqa: BLE001 - an unreadable picture is left out, never fatal
        return None
    if picture.mode in ("RGBA", "LA", "PA") or (
            picture.mode == "P" and "transparency" in picture.info):
        picture = picture.convert("RGBA")
        picture = Image.alpha_composite(Image.new("RGBA", picture.size, "white"), picture)
    picture = picture.convert("RGB")
    scale = (PICTURE_PIXELS / (picture.width * picture.height)) ** 0.5
    if scale < 1:
        picture = picture.resize((max(32, int(picture.width * scale)),
                                  max(32, int(picture.height * scale))),
                                 Image.Resampling.LANCZOS)
    return picture


def reply_from_completion(raw: str, *, prompt_tokens: int = 0,
                          generated_tokens: int = 0) -> Reply:
    """A finished completion as a :class:`Reply`: the calls, and only the prose."""
    calls = parse_tool_calls(raw)
    begun = raw.count("<tool_call>") or len(
        [blob for blob in _BARE_JSON.findall(raw) if _names_a_tool(blob)])
    if not begun and not _FENCED_JSON.search(raw):
        read, unreadable = _text_call_spans(raw)
        begun = len(read) + len(unreadable)
    return Reply(
        text=strip_tool_calls(raw).strip(),
        tool_calls=calls,
        # More calls begun than could be read: cut off, or not JSON. Tool protocol is
        # never prose, so the text above has already lost it either way.
        dropped_tool_call=begun > len(calls),
        prompt_tokens=prompt_tokens,
        generated_tokens=generated_tokens,
    )


