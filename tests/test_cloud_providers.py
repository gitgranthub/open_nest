"""The two cloud providers, against a scripted transport.

Nothing here opens a socket. A provider is handed something that turns a request into
events, exactly as the agent tests hand the controller a ``ScriptedProvider`` -- so what
is checked is the translation, which is the part Open Nest is responsible for and the
part that would otherwise only be found by spending money.

The three Anthropic integration details PLAN.md records as "will otherwise bite" each
have a test here: the ``thinking`` shape differing between models, assistant prefill
being gone, and mid-conversation system messages being rejected. They are asserted
against the *request body* rather than against a live 400, because a test that needs a
400 to pass is a test nobody runs.
"""

from __future__ import annotations

import json

import pytest

from opennest.agent.tools import SCHEMAS
from opennest.ai import cloud
from opennest.ai.anthropic_provider import AnthropicProvider
from opennest.ai.openai_provider import OpenAIProvider
from opennest.ai.provider import (
    Message,
    ModelInfo,
    ProviderError,
    Settings,
    ToolCall,
    TruncatedReply,
)
from opennest.ai.router import build_provider

ANTHROPIC_KEY = "sk-ant-api03-" + "K3" * 30
OPENAI_KEY = "sk-proj-" + "M8" * 30

#: Sonnet-shaped: adaptive thinking, no manual budget, no sampling temperature.
CLAUDE = ModelInfo(
    id="claude-sonnet", name="Claude", provider="anthropic",
    requires_internet=True, may_cost_money=True, supports_images=True,
    supports_temperature=False, supports_thinking_budget=False,
)
#: Haiku-shaped: the other Anthropic request shape, with a manual thinking budget.
HAIKU = ModelInfo(
    id="claude-haiku", name="Claude Haiku", provider="anthropic",
    requires_internet=True, may_cost_money=True, supports_images=True,
    supports_temperature=False, supports_thinking_budget=True,
)
#: A model that takes a temperature. Used to prove the decision is the declaration and
#: not something read off the rest of the request.
PLAIN = ModelInfo(
    id="plain", name="Plain", provider="anthropic",
    requires_internet=True, supports_temperature=True,
)
GPT = ModelInfo(
    id="openai-gpt", name="OpenAI", provider="openai",
    requires_internet=True, may_cost_money=True, supports_images=True,
)


class ScriptedTransport:
    """Replays a canned SSE stream and records every request it was given."""

    def __init__(self, sse: str = "", reply: dict | None = None) -> None:
        self.sse = sse
        self.reply = reply if reply is not None else {}
        self.requests: list[cloud.Request] = []

    def stream(self, request: cloud.Request):
        self.requests.append(request)
        # Through the real parser, so the framing is exercised rather than faked.
        yield from cloud.parse_sse(self.sse.splitlines())

    def send(self, request: cloud.Request) -> dict:
        self.requests.append(request)
        return self.reply

    @property
    def body(self) -> dict:
        return self.requests[-1].body

    @property
    def headers(self) -> dict:
        return self.requests[-1].headers


def drain(provider, messages, **kwargs):
    """Run one exchange and return the completed reply."""
    chunks = [chunk.text for chunk in provider.chat(messages, **kwargs) if chunk.text]
    return provider.finish(), "".join(chunks)


def anthropic(transport, credentials, info: ModelInfo = CLAUDE, **kwargs):
    credentials.save_key("anthropic", ANTHROPIC_KEY)
    return AnthropicProvider(
        info, "claude-sonnet-5",
        transport=transport, credentials=credentials, **kwargs,
    )


def openai(transport, credentials, info: ModelInfo = GPT, **kwargs):
    credentials.save_key("openai", OPENAI_KEY)
    return OpenAIProvider(
        info, "gpt-5.6-luna",
        transport=transport, credentials=credentials, **kwargs,
    )


CONVERSATION = [
    Message(role="system", content="You build games."),
    Message(role="user", content="Make the ship faster."),
    Message(role="assistant", tool_calls=(
        ToolCall(name="edit_file", arguments={"path": "src/game.py"}, id="call_a"),
    )),
    Message(role="tool", name="edit_file", tool_call_id="call_a", content="Changed it."),
    Message(role="user", content="Now run it."),
]


def sse(*frames: tuple[str, dict]) -> str:
    """Build an SSE stream from (event name, payload) pairs.

    Assembled rather than pasted so the JSON escaping is done by ``json.dumps`` instead
    of by hand -- the tool-argument frames carry quotes inside quoted strings, which is
    exactly the shape that is easy to get subtly wrong in a literal.
    """
    return "".join(
        f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in frames
    )


#: Two text deltas and one tool call, split across argument fragments the way the real
#: stream splits them.
ANTHROPIC_STREAM = sse(
    ("message_start", {"message": {"usage": {"input_tokens": 1200}}}),
    ("content_block_start", {"index": 0, "content_block": {"type": "text"}}),
    ("content_block_delta",
     {"index": 0, "delta": {"type": "text_delta", "text": "On it. "}}),
    ("content_block_delta",
     {"index": 0, "delta": {"type": "text_delta", "text": "Running."}}),
    ("content_block_stop", {"index": 0}),
    ("content_block_start", {"index": 1, "content_block": {
        "type": "tool_use", "id": "toolu_7", "name": "run_project"}}),
    ("content_block_delta",
     {"index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"quiet"'}}),
    ("content_block_delta",
     {"index": 1, "delta": {"type": "input_json_delta", "partial_json": ": true}"}}),
    ("content_block_stop", {"index": 1}),
    ("message_delta", {"usage": {"output_tokens": 42}}),
    ("message_stop", {}),
)

OPENAI_STREAM = sse(
    ("response.output_text.delta", {"delta": "On it. "}),
    ("response.output_text.delta", {"delta": "Running."}),
    ("response.output_item.added", {"item": {
        "type": "function_call", "id": "fc_7",
        "call_id": "call_7", "name": "run_project"}}),
    ("response.function_call_arguments.delta",
     {"item_id": "fc_7", "delta": '{"quiet"'}),
    ("response.function_call_arguments.delta",
     {"item_id": "fc_7", "delta": ": true}"}),
    ("response.completed",
     {"response": {"usage": {"input_tokens": 1200, "output_tokens": 42}}}),
)


# ------------------------------------------------------- the interface holds

def test_anthropic_streams_text_and_returns_a_reply(credentials) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    reply, streamed = drain(anthropic(transport, credentials), CONVERSATION)

    assert streamed == "On it. Running."
    assert reply.text == "On it. Running."
    assert reply.prompt_tokens == 1200
    assert reply.generated_tokens == 42


def test_openai_streams_text_and_returns_a_reply(credentials) -> None:
    transport = ScriptedTransport(OPENAI_STREAM)
    reply, streamed = drain(openai(transport, credentials), CONVERSATION)

    assert streamed == "On it. Running."
    assert reply.text == "On it. Running."
    assert reply.prompt_tokens == 1200
    assert reply.generated_tokens == 42


@pytest.mark.parametrize("build,stream", [(anthropic, ANTHROPIC_STREAM),
                                          (openai, OPENAI_STREAM)])
def test_a_tool_call_arrives_assembled(credentials, build, stream) -> None:
    """Both services send tool arguments as JSON fragments that only parse once whole."""
    reply, _ = drain(build(ScriptedTransport(stream), credentials), CONVERSATION)

    assert reply.wants_tool
    assert len(reply.tool_calls) == 1
    call = reply.tool_calls[0]
    assert call.name == "run_project"
    assert call.arguments == {"quiet": True}


def test_the_reply_shape_is_what_the_agent_loop_already_expects(credentials) -> None:
    """The point of section 21: nothing above the provider changes for a cloud model."""
    reply, _ = drain(anthropic(ScriptedTransport(ANTHROPIC_STREAM), credentials),
                     CONVERSATION)
    assert isinstance(reply.tool_calls, tuple)
    assert reply.wants_tool is True


# ------------------------------------------------- Anthropic message translation

def test_the_system_prompt_is_lifted_out_of_the_messages(credentials) -> None:
    """Sonnet 5 rejects a mid-conversation system message, so none is ever sent."""
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials), CONVERSATION)

    assert transport.body["system"] == "You build games."
    assert all(turn["role"] != "system" for turn in transport.body["messages"])


def test_a_mid_conversation_system_message_is_lifted_too(credentials) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials), [
        Message(role="system", content="First."),
        Message(role="user", content="Hello."),
        Message(role="system", content="Second."),
        Message(role="user", content="Still there?"),
    ])
    assert transport.body["system"] == "First.\n\nSecond."
    assert all(turn["role"] != "system" for turn in transport.body["messages"])


def test_a_tool_result_becomes_a_tool_result_block_in_a_user_turn(credentials) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials), CONVERSATION)

    turns = transport.body["messages"]
    # user / assistant / user -- the tool result merged into the following user turn.
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    blocks = turns[2]["content"]
    assert blocks[0]["type"] == "tool_result"
    assert blocks[0]["tool_use_id"] == "call_a"
    assert blocks[0]["content"] == "Changed it."
    assert blocks[1] == {"type": "text", "text": "Now run it."}


def test_an_assistant_tool_call_becomes_a_tool_use_block(credentials) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials), CONVERSATION)

    assistant = transport.body["messages"][1]
    assert assistant["content"] == [{
        "type": "tool_use", "id": "call_a",
        "name": "edit_file", "input": {"path": "src/game.py"},
    }]


def test_nothing_prefills_the_assistant_turn(credentials) -> None:
    """Assistant prefill was removed on Sonnet 5 and returns a 400.

    So the last thing sent must be whatever the conversation actually ended with --
    the provider never seeds an assistant turn to shape the reply.
    """
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials), CONVERSATION)
    assert transport.body["messages"][-1]["role"] == "user"


def test_an_empty_message_is_dropped_rather_than_sent_blank(credentials) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials), [
        Message(role="user", content="Hello."),
        Message(role="assistant", content=""),
    ])
    assert len(transport.body["messages"]) == 1


def test_tool_schemas_are_translated_not_duplicated(credentials) -> None:
    """``agent.tools.SCHEMAS`` stays the single definition of what a tool is."""
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials), CONVERSATION,
          tools=[SCHEMAS["edit_file"]])

    tool = transport.body["tools"][0]
    assert tool["name"] == "edit_file"
    assert tool["input_schema"] == SCHEMAS["edit_file"]["function"]["parameters"]
    assert "function" not in tool


# -------------------------------------- the per-model request shape, from data

def test_adaptive_thinking_comes_from_the_catalogue(credentials) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    provider = anthropic(transport, credentials,
                         provider_options={"thinking": {"type": "adaptive"}})
    drain(provider, CONVERSATION, settings=Settings(temperature=0.0))

    assert transport.body["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in transport.body


def test_temperature_is_omitted_when_the_model_says_it_cannot_take_one(
    credentials,
) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials, CLAUDE), CONVERSATION,
          settings=Settings(temperature=0.0))
    assert "temperature" not in transport.body


def test_temperature_is_sent_when_the_model_says_it_can(credentials) -> None:
    """Phase 1's temperature-0 rule still applies wherever the model allows it."""
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials, PLAIN), CONVERSATION,
          settings=Settings(temperature=0.0))
    assert transport.body["temperature"] == 0.0


def test_thinking_does_not_by_itself_suppress_temperature(credentials) -> None:
    """The test that distinguishes a capability from an inference.

    An earlier version omitted temperature whenever a thinking block was present. That
    produced the right request for both catalogue entries and was still wrong: a model
    that thinks *and* accepts a temperature would have been silently denied one. The
    declaration decides, and nothing else does.
    """
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    provider = anthropic(transport, credentials, PLAIN,
                         provider_options={"thinking": {"type": "adaptive"}})
    drain(provider, CONVERSATION, settings=Settings(temperature=0.0))

    assert transport.body["thinking"] == {"type": "adaptive"}
    assert transport.body["temperature"] == 0.0


def test_a_manual_thinking_budget_passes_through_for_a_model_that_takes_one(
    credentials,
) -> None:
    """Haiku 4.5 takes what Sonnet 5 rejects. The provider must not assume either."""
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    provider = anthropic(
        transport, credentials, HAIKU,
        provider_options={"thinking": {"type": "enabled", "budget_tokens": 4000}},
    )
    drain(provider, CONVERSATION)
    assert transport.body["thinking"] == {"type": "enabled", "budget_tokens": 4000}


def test_anthropic_gets_output_headroom_too(credentials) -> None:
    """The field means the same thing on both providers.

    It was applied by the OpenAI provider only, which left Sonnet -- adaptive thinking,
    no separate budget -- running on the bare default with no detection either
    (SPIKES.md section 13).
    """
    roomy = ModelInfo(id="claude-sonnet", name="Claude", provider="anthropic",
                      requires_internet=True, supports_temperature=False,
                      output_headroom_tokens=2000)
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials, roomy), CONVERSATION,
          settings=Settings(max_tokens=400))
    assert transport.body["max_tokens"] == 2400


def test_anthropic_reports_a_silently_truncated_reply(credentials) -> None:
    """Sonnet can spend the whole allowance thinking and stop having said nothing.

    Nothing errors -- the response is well-formed and empty -- so without this the
    child gets silence. The OpenAI provider has had this guard since section 11; this
    is the other half.
    """
    empty = sse(
        ("message_start", {"message": {"usage": {"input_tokens": 900}}}),
        ("message_delta", {"delta": {"stop_reason": "max_tokens"},
                           "usage": {"output_tokens": 1200}}),
        ("message_stop", {}),
    )
    with pytest.raises(TruncatedReply):
        drain(anthropic(ScriptedTransport(empty), credentials), CONVERSATION)


def test_anthropic_truncation_after_real_output_is_not_an_error(credentials) -> None:
    """Only *silent* truncation is worth raising. A cut-off answer is still an answer."""
    partial = ANTHROPIC_STREAM + sse(
        ("message_delta", {"delta": {"stop_reason": "max_tokens"},
                           "usage": {"output_tokens": 1200}}),
    )
    reply, streamed = drain(anthropic(ScriptedTransport(partial), credentials),
                            CONVERSATION)
    assert streamed == "On it. Running."
    assert reply.tool_calls


def test_max_tokens_is_raised_above_a_thinking_budget(credentials) -> None:
    """Found by running the spike (SPIKES.md section 11): the API rejects a request
    whose ``max_tokens`` is not greater than ``thinking.budget_tokens``.

    With a budget declared in the catalogue and the ``Settings`` default of 1200, every
    single call failed. Neither side could see the problem alone.
    """
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    provider = anthropic(
        transport, credentials, HAIKU,
        provider_options={"thinking": {"type": "enabled", "budget_tokens": 1024}},
    )
    drain(provider, CONVERSATION, settings=Settings(max_tokens=400))

    # The caller's 400 tokens of answer survive on top of the budget, not inside it.
    assert transport.body["max_tokens"] == 1424


def test_max_tokens_is_left_alone_when_it_already_clears_the_budget(
    credentials,
) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    provider = anthropic(
        transport, credentials, HAIKU,
        provider_options={"thinking": {"type": "enabled", "budget_tokens": 1024}},
    )
    drain(provider, CONVERSATION, settings=Settings(max_tokens=4000))
    assert transport.body["max_tokens"] == 4000


def test_a_model_without_a_thinking_budget_keeps_the_requested_max_tokens(
    credentials,
) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials, CLAUDE), CONVERSATION,
          settings=Settings(max_tokens=400))
    assert transport.body["max_tokens"] == 400


def test_a_manual_budget_for_a_model_that_refuses_one_is_a_config_error(
    credentials,
) -> None:
    """Better than a 400 on every turn: an error naming the model and the field."""
    provider = anthropic(
        ScriptedTransport(ANTHROPIC_STREAM), credentials, CLAUDE,
        provider_options={"thinking": {"type": "enabled", "budget_tokens": 4000}},
    )
    with pytest.raises(ProviderError) as caught:
        drain(provider, CONVERSATION)
    assert "budget_tokens" in str(caught.value)
    assert "Claude" in str(caught.value)


def test_the_catalogue_supplies_the_options_and_the_capabilities(credentials) -> None:
    """The wiring from models.json through the router to the request body."""
    credentials.save_key("anthropic", ANTHROPIC_KEY)
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    provider = build_provider(
        "claude-sonnet", allow_cloud=True,
        transport=transport, credentials=credentials,
    )
    drain(provider, CONVERSATION, settings=Settings(temperature=0.0))

    assert transport.body["model"] == "claude-sonnet-5"
    assert transport.body["thinking"] == {"type": "adaptive"}
    assert "temperature" not in transport.body


def test_the_catalogue_gives_haiku_the_other_shape(credentials) -> None:
    credentials.save_key("anthropic", ANTHROPIC_KEY)
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    provider = build_provider(
        "claude-haiku", allow_cloud=True,
        transport=transport, credentials=credentials,
    )
    drain(provider, CONVERSATION)

    assert transport.body["model"] == "claude-haiku-4-5"
    assert transport.body["thinking"]["budget_tokens"] == 1024
    # And the budget did not eat the answer: max_tokens clears it.
    assert transport.body["max_tokens"] > transport.body["thinking"]["budget_tokens"]


# --------------------------------------------------- OpenAI message translation

def test_the_system_prompt_becomes_instructions(credentials) -> None:
    transport = ScriptedTransport(OPENAI_STREAM)
    drain(openai(transport, credentials), CONVERSATION)

    assert transport.body["instructions"] == "You build games."
    assert all(item.get("role") != "system" for item in transport.body["input"])


def test_calls_and_results_are_flat_items_keyed_by_call_id(credentials) -> None:
    transport = ScriptedTransport(OPENAI_STREAM)
    drain(openai(transport, credentials), CONVERSATION)

    items = transport.body["input"]
    call = next(i for i in items if i.get("type") == "function_call")
    output = next(i for i in items if i.get("type") == "function_call_output")
    assert call["call_id"] == output["call_id"] == "call_a"
    assert call["name"] == "edit_file"
    # Arguments travel as a JSON string in this API, not an object.
    assert call["arguments"] == '{"path": "src/game.py"}'
    assert output["output"] == "Changed it."


def test_assistant_and_user_text_use_the_right_content_types(credentials) -> None:
    transport = ScriptedTransport(OPENAI_STREAM)
    drain(openai(transport, credentials), [
        Message(role="user", content="Hello."),
        Message(role="assistant", content="Hi."),
    ])
    items = transport.body["input"]
    assert items[0]["content"][0]["type"] == "input_text"
    assert items[1]["content"][0]["type"] == "output_text"


def test_openai_tool_schemas_are_flat(credentials) -> None:
    transport = ScriptedTransport(OPENAI_STREAM)
    drain(openai(transport, credentials), CONVERSATION, tools=[SCHEMAS["run_project"]])

    tool = transport.body["tools"][0]
    assert tool["type"] == "function"
    assert tool["name"] == "run_project"
    assert "function" not in tool


def test_openai_follows_the_same_declared_capability(credentials) -> None:
    """Same rule on the other provider: the model says, the provider does."""
    no_sampling = ModelInfo(id="openai-gpt", name="OpenAI", provider="openai",
                            requires_internet=True, supports_temperature=False)
    transport = ScriptedTransport(OPENAI_STREAM)
    provider = openai(transport, credentials, no_sampling,
                      provider_options={"reasoning": {"effort": "medium"}})
    drain(provider, CONVERSATION)
    assert "temperature" not in transport.body
    assert transport.body["reasoning"] == {"effort": "medium"}


def test_a_reasoning_model_gets_room_to_think_on_top_of_the_answer(credentials) -> None:
    """Found by running the spike: the output cap covers reasoning *and* the answer.

    gpt-5-mini given 120 output tokens spent all 64 it used on reasoning and streamed
    an empty reply. The caller's requested answer length has to survive that.
    """
    reasoning = ModelInfo(id="openai-gpt", name="OpenAI", provider="openai",
                          requires_internet=True, supports_temperature=False,
                          output_headroom_tokens=2000)
    transport = ScriptedTransport(OPENAI_STREAM)
    drain(openai(transport, credentials, reasoning), CONVERSATION,
          settings=Settings(max_tokens=400))
    assert transport.body["max_output_tokens"] == 2400


def test_a_model_that_does_not_reason_gets_exactly_what_was_asked(credentials) -> None:
    transport = ScriptedTransport(OPENAI_STREAM)
    drain(openai(transport, credentials), CONVERSATION, settings=Settings(max_tokens=400))
    assert transport.body["max_output_tokens"] == 400


def test_running_out_of_room_while_thinking_is_explained_not_silent(credentials) -> None:
    """The worst failure mode: a successful response containing nothing at all.

    Left alone this reaches the child as silence -- nothing happened, and nothing said
    why. Measured on gpt-5-mini (SPIKES.md section 11).
    """
    truncated = sse(("response.incomplete", {"response": {
        "usage": {"input_tokens": 34, "output_tokens": 64},
        "incomplete_details": {"reason": "max_output_tokens"},
    }}))
    with pytest.raises(ProviderError) as caught:
        drain(openai(ScriptedTransport(truncated), credentials), CONVERSATION)
    assert "before it finished thinking" in str(caught.value)


def test_truncation_after_real_output_is_not_an_error(credentials) -> None:
    """Only *silent* truncation is worth raising. A cut-off answer is still an answer."""
    partial = OPENAI_STREAM + sse(("response.incomplete", {"response": {
        "usage": {"input_tokens": 34, "output_tokens": 500},
        "incomplete_details": {"reason": "max_output_tokens"},
    }}))
    reply, streamed = drain(openai(ScriptedTransport(partial), credentials), CONVERSATION)
    assert streamed == "On it. Running."
    assert reply.tool_calls


def test_openai_sends_temperature_by_default(credentials) -> None:
    transport = ScriptedTransport(OPENAI_STREAM)
    drain(openai(transport, credentials), CONVERSATION,
          settings=Settings(temperature=0.0))
    assert transport.body["temperature"] == 0.0


# -------------------------------------------------------------- the credential

def test_the_key_travels_in_the_header_and_nowhere_else(credentials) -> None:
    transport = ScriptedTransport(ANTHROPIC_STREAM)
    drain(anthropic(transport, credentials), CONVERSATION)

    assert transport.headers["x-api-key"] == ANTHROPIC_KEY
    assert ANTHROPIC_KEY not in json.dumps(transport.body)


def test_openai_uses_a_bearer_header(credentials) -> None:
    transport = ScriptedTransport(OPENAI_STREAM)
    drain(openai(transport, credentials), CONVERSATION)

    assert transport.headers["Authorization"] == f"Bearer {OPENAI_KEY}"
    assert OPENAI_KEY not in json.dumps(transport.body)


def test_no_key_gives_a_message_that_says_what_to_do(credentials) -> None:
    provider = AnthropicProvider(CLAUDE, "claude-sonnet-5",
                                 transport=ScriptedTransport(), credentials=credentials)
    with pytest.raises(ProviderError) as caught:
        provider.load()
    assert "Settings" in str(caught.value)
    assert provider.is_loaded is False


def test_unloading_forgets_the_key(credentials) -> None:
    provider = anthropic(ScriptedTransport(ANTHROPIC_STREAM), credentials)
    provider.load()
    assert provider.is_loaded
    provider.unload()
    assert provider.is_loaded is False


# ------------------------------------------------------------------- failures

def test_an_error_event_mid_stream_becomes_a_readable_problem(credentials) -> None:
    transport = ScriptedTransport(
        'event: error\ndata: {"type":"error","error":{"message":"overloaded"}}\n\n'
    )
    with pytest.raises(ProviderError) as caught:
        drain(anthropic(transport, credentials), CONVERSATION)
    assert "overloaded" in str(caught.value)


def test_a_rejected_key_points_at_settings() -> None:
    message = str(cloud.http_error(401, ""))
    assert "did not accept the API key" in message
    assert "Settings" in message


def test_a_rate_limit_offers_the_model_on_this_mac() -> None:
    assert "on this Mac" in str(cloud.http_error(429, ""))


def test_a_server_problem_is_not_blamed_on_the_child() -> None:
    message = str(cloud.http_error(503, ""))
    assert "their end" in message


def test_an_organisation_scoped_key_is_explained_rather_than_dumped() -> None:
    """Found by running the spike against a real account -- SPIKES.md section 11.

    An organisation-level Anthropic key needs a workspace named on every request. The
    service says so clearly, but in terms of an HTTP header a parent cannot set, so the
    raw body is the wrong thing to show them.
    """
    body = ('{"type":"error","error":{"type":"invalid_request_error","message":'
            '"This API key is not scoped to a workspace, so this request must include '
            'the anthropic-workspace-id header with the ID of the workspace to use."}}')
    message = str(cloud.http_error(400, body))

    assert "belongs to a whole organisation" in message
    assert "console.anthropic.com" in message
    # The header name is the part they can do nothing with.
    assert "anthropic-workspace-id" not in message


def test_an_ordinary_400_still_shows_what_the_service_said() -> None:
    """The friendly cases are narrow; everything else keeps the real detail."""
    message = str(cloud.http_error(400, '{"error":"max_tokens must be positive"}'))
    assert "max_tokens must be positive" in message


def test_a_model_the_key_cannot_reach_is_not_blamed_on_the_key() -> None:
    """OpenAI returns **403** for this, which the auth branch was swallowing.

    Found by pointing the shipped catalogue entry at a real key without access to it
    (SPIKES.md section 11). "Your key was rejected" sends a parent off to replace a key
    that is perfectly good.
    """
    body = ('{"error":{"message":"Project `proj_abc` does not have access to model '
            '`gpt-5.6-luna`","type":"invalid_request_error","code":"model_not_found"}}')
    for status in (403, 404):
        message = str(cloud.http_error(status, body))
        assert "not available to this API key" in message
        assert "did not accept the API key" not in message
        # The real detail is kept: a parent needs to see which model and which project.
        assert "gpt-5.6-luna" in message


def test_a_genuine_auth_failure_still_says_so() -> None:
    """The model-access case is narrow; a real 401 must not be mistaken for it."""
    message = str(cloud.http_error(401, '{"error":{"message":"invalid x-api-key"}}'))
    assert "did not accept the API key" in message


def test_running_out_of_credit_is_recognised_whatever_status_carries_it() -> None:
    """Anthropic sends **400** for this, not 402 -- found by running the spike.

    Mapping it on the status alone would have told a parent "the request was refused
    (error 400)", which gives them nothing to act on. The body is what identifies it.
    """
    body = ('{"type":"error","error":{"type":"invalid_request_error","message":'
            '"Your credit balance is too low to access the Anthropic API. Please go '
            'to Plans & Billing to upgrade or purchase credits."}}')
    for status in (400, 402):
        message = str(cloud.http_error(status, body))
        assert "run out of credit" in message
        assert "model on this Mac" in message


def test_an_error_body_is_scrubbed_of_the_key() -> None:
    leaked = f'{{"error":"bad key {ANTHROPIC_KEY}"}}'
    assert ANTHROPIC_KEY not in cloud.redact(leaked, ANTHROPIC_KEY)


def test_a_truncated_echo_of_the_key_is_scrubbed_too() -> None:
    """Services often echo a prefix rather than the whole thing."""
    leaked = f"key {ANTHROPIC_KEY[:12]}... was rejected"
    assert ANTHROPIC_KEY[:12] not in cloud.redact(leaked, ANTHROPIC_KEY)


def test_a_key_shaped_string_is_scrubbed_even_without_knowing_the_key() -> None:
    leaked = f"something went wrong with {ANTHROPIC_KEY}"
    cleaned = cloud.redact(leaked)
    assert ANTHROPIC_KEY not in cleaned
    assert "looked like a key" in cleaned


def test_the_credential_is_found_in_either_header_style() -> None:
    assert cloud.credential_in({"x-api-key": "abc"}) == "abc"
    assert cloud.credential_in({"Authorization": "Bearer abc"}) == "abc"
    assert cloud.credential_in({}) is None


# ------------------------------------------------------------- the SSE reader

def test_the_reader_handles_comments_and_the_done_sentinel() -> None:
    events = list(cloud.parse_sse([
        ": keepalive",
        "event: one",
        'data: {"a": 1}',
        "",
        "data: [DONE]",
        "",
        "event: never",
        'data: {"b": 2}',
        "",
    ]))
    assert [(e.name, e.data) for e in events] == [("one", {"a": 1})]


def test_a_multi_line_data_field_is_joined() -> None:
    events = list(cloud.parse_sse(["event: one", 'data: {"a":', 'data: 1}', ""]))
    assert events[0].data == {"a": 1}


def test_a_stream_that_ends_without_a_blank_line_still_yields_its_last_event() -> None:
    events = list(cloud.parse_sse(["event: one", 'data: {"a": 1}']))
    assert len(events) == 1


def test_one_unparseable_frame_does_not_lose_the_rest() -> None:
    events = list(cloud.parse_sse([
        "event: one", "data: not json", "",
        "event: two", 'data: {"b": 2}', "",
    ]))
    assert [e.name for e in events] == ["two"]


def test_an_event_name_falls_back_to_the_payload_type() -> None:
    """OpenAI's stream carries the name in the data as well; either is enough."""
    events = list(cloud.parse_sse(['data: {"type": "response.completed"}', ""]))
    assert events[0].name == "response.completed"
