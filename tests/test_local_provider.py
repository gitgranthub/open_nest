"""What the local provider hands back as Gary's words.

Phase 12 downloaded Qwen3 8B to turn one ``verified: false`` into ``true``, and the
download bought something the flag flip would not have: **the 8B and 14B entries are a
different kind of model from the 4B.** ``Qwen3-4B-Instruct-2507`` answers.
``Qwen3-8B`` and ``Qwen3-14B`` are the hybrid *thinking* models, and asked for the
verification phrase the 8B replied:

    <think>
    Okay, the user wants me to respond with exactly "OPEN NEST READY". Let me make ...

Nothing in the local path removed that or asked the template not to produce it, so a
parent who picked the model Open Nest itself recommends for a 16 GB Mac would have got
the model's internal monologue as Gary's side of the conversation.

The real fix is ``_render`` passing ``enable_thinking=False``, measured against both
shapes: the 8B's template gains a pre-closed ``<think></think>`` and the 4B's ignores
the flag entirely (byte-identical prompt). These tests cover the second half -- the
string-level guard behind it -- because the prompt flag is a request to a chat template
and this is a fact about the text.
"""

from __future__ import annotations

from opennest.ai.mlx_provider import (
    parse_tool_calls,
    reply_from_completion,
    strip_tool_calls,
)


def test_a_reasoning_block_never_reaches_the_child() -> None:
    raw = (
        "<think>\nOkay, the user wants me to respond with exactly OPEN NEST READY. "
        "Let me make sure I understand.\n</think>\n\nOPEN NEST READY"
    )
    assert strip_tool_calls(raw).strip() == "OPEN NEST READY"


def test_an_unclosed_reasoning_block_is_removed_too() -> None:
    """The case with the most reasoning on screen, so the one worth covering.

    A reply cut off by ``max_tokens`` mid-thought has an opening tag and no closing
    one. Matching only the closed form would leave the entire monologue visible in
    exactly the situation where it is longest.
    """
    raw = "<think>\nI should start by reading the file, then work out which line"
    assert strip_tool_calls(raw).strip() == ""


def test_the_empty_block_the_flag_itself_inserts_is_removed() -> None:
    """``enable_thinking=False`` pre-closes the block, and the model may echo it."""
    assert strip_tool_calls("<think>\n\n</think>\n\nDone.").strip() == "Done."


def test_a_tool_call_after_a_reasoning_block_is_still_found() -> None:
    """The half that would have broken the product rather than just embarrassed it."""
    raw = (
        "<think>The player asked for speed, so I should edit game.py.</think>\n"
        '<tool_call>{"name": "edit_file", "arguments": {"path": "src/game.py"}}</tool_call>'
    )
    calls = parse_tool_calls(raw)
    assert [c.name for c in calls] == ["edit_file"]
    assert strip_tool_calls(raw).strip() == ""


#: The shape Phase 12.4 measured, shortened: the model looped inside an ``edit_file``
#: argument until the output cap, so the block never closed.
CUT_OFF_CALL = (
    '<tool_call>\n{"name": "edit_file", "arguments": {"path": "src/game.py", '
    '"old_text": "    screen.fill(BACKGROUND)", "new_text": "    screen.fill(BACKGROUND)\\n'
    '    second_square.x = 0\\n        second_square.x = WIDTH\\n        second_square.x = 0'
)


def test_a_tool_call_cut_off_by_the_output_cap_never_reaches_the_child() -> None:
    reply = reply_from_completion(CUT_OFF_CALL)
    assert reply.text == ""
    assert reply.tool_calls == () and reply.dropped_tool_call


def test_prose_before_a_cut_off_call_is_kept_and_the_call_is_not() -> None:
    reply = reply_from_completion("I'll add a second square.\n" + CUT_OFF_CALL)
    assert reply.text == "I'll add a second square."
    assert "<tool_call>" not in reply.text and "edit_file" not in reply.text
    assert reply.dropped_tool_call


def test_a_closed_call_that_is_not_json_is_dropped_and_said_so() -> None:
    reply = reply_from_completion('<tool_call>{"name": "edit_file", "arguments": {</tool_call>')
    assert reply.text == "" and reply.tool_calls == () and reply.dropped_tool_call


def test_a_call_that_parsed_is_not_reported_as_dropped() -> None:
    raw = ('<tool_call>{"name": "run_project", "arguments": {}}</tool_call>\n'
           "Run it and look for the square.")
    reply = reply_from_completion(raw)
    assert [c.name for c in reply.tool_calls] == ["run_project"]
    assert reply.text == "Run it and look for the square."
    assert not reply.dropped_tool_call


def test_ordinary_prose_is_left_alone() -> None:
    """The 4B is not a thinking model and must not be touched by any of this."""
    raw = "Player now moves faster. Look for the increased speed with the arrow keys."
    assert strip_tool_calls(raw) == raw


def test_a_mention_of_thinking_in_prose_is_not_a_block() -> None:
    text = "I was thinking we could make the asteroids faster. <think is not a tag."
    assert strip_tool_calls(text) == text


def test_the_renderer_asks_the_template_not_to_think() -> None:
    """Measured on the real templates; pinned here so it cannot be dropped.

    A fake tokenizer stands in for the two real ones, because the suite is hermetic and
    a chat template means a downloaded model. What it checks is that the provider sends
    the flag at all -- ``spikes/phase12/probe_enable_thinking.py`` is what established
    that the flag does the right thing to each real template.
    """
    from opennest.ai.mlx_provider import MLXProvider
    from opennest.ai.provider import Message, ModelInfo

    seen: dict = {}

    class FakeTokenizer:
        def apply_chat_template(self, payload, **kwargs):
            seen.update(kwargs)
            return "PROMPT"

    provider = MLXProvider(ModelInfo(id="x", name="X", provider="mlx"), "repo/x")
    provider._tokenizer = FakeTokenizer()
    assert provider._render([Message(role="user", content="hi")], None) == "PROMPT"
    assert seen.get("enable_thinking") is False


def test_a_template_that_refuses_the_flag_still_renders() -> None:
    """An older or third-party template may reject an unexpected argument.

    Failing to render a conversation because a model does not support a flag that only
    suppresses reasoning would be a worse outcome than the reasoning.
    """
    from opennest.ai.mlx_provider import MLXProvider
    from opennest.ai.provider import Message, ModelInfo

    class PickyTokenizer:
        def apply_chat_template(self, payload, **kwargs):
            if "enable_thinking" in kwargs:
                raise TypeError("unexpected keyword argument 'enable_thinking'")
            return "PROMPT"

    provider = MLXProvider(ModelInfo(id="x", name="X", provider="mlx"), "repo/x")
    provider._tokenizer = PickyTokenizer()
    assert provider._render([Message(role="user", content="hi")], None) == "PROMPT"
