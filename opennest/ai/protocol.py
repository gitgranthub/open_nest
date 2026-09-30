"""Tool protocol written as text -- found, and kept out of what the child reads.

A model is meant to call a tool through its provider's own mechanism, and the cloud
models do. But any model can write a call out as text instead -- a ``<tool_call>`` block,
a JSON object, a line of Python -- or leave its reasoning in a ``<think>`` block, and none
of that is words for a child. These functions are the one place that recognises it:

- :func:`parse_tool_calls` -- the calls a completion wrote as text, which the local
  provider runs (a Qwen model's native format *is* text);
- :func:`strip_tool_calls` -- the prose that is left once every one of them is gone.

Nothing here knows which model wrote the text. The local provider uses both to build its
reply; ``agent.replies.presentable`` applies :func:`strip_tool_calls` to every reply from
every provider -- local, Claude or OpenAI -- before the chat shows it, so a filter added
for one model protects all of them.
"""

from __future__ import annotations

import ast
import json
import re

from opennest.ai.provider import ToolCall

#: Qwen-family chat templates wrap calls in these tags.
_TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
#: A call written as a JSON object on a line of its own, with no fence and no tag --
#: measured on the parity walk, in the middle of Gary's answer:
#: ``{"name": "edit_file", "arguments": {"path": "src/main.py", ...}}``.
_BARE_JSON = re.compile(r'^[ \t]*(\{"name"\s*:.*\})[ \t]*$', re.MULTILINE)
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
#: A tool call written as a line of Python in the reply's prose -- ``edit_file(path=...,
#: old_text=..., new_text=...)``, bare or in a code fence -- instead of a ``<tool_call>``
#: block. Measured in the owner's first Phase 13 test (SPIKES.md section 27A): after "Call
#: edit_file now", the 4B model wrote the call out as text on four turns running. None
#: was run, and all of it -- escaped newlines and all -- was Gary's reply in the chat.
#: The parameter names are each tool's own, in the order its schema lists them.
_TEXT_CALL_TOOLS = {
    "read_file": ("path",),
    "edit_file": ("path", "old_text", "new_text"),
    "write_file": ("path", "content"),
    "run_project": (),
    "compile_project": (),
    "game_object": ("name",),
}
_TEXT_CALL_START = re.compile(r"\b(" + "|".join(_TEXT_CALL_TOOLS) + r")\s*\(")
#: A fence left empty once the call inside it has gone.
_EMPTY_FENCE = re.compile(r"```[a-zA-Z]*\s*```")


def parse_tool_calls(text: str) -> tuple[ToolCall, ...]:
    """Pull tool calls out of a raw completion.

    Accepts the native ``<tool_call>`` block first, then a fenced JSON object. Tool-name
    normalisation happens in the toolbox, not here -- this layer reports what the model
    said, and dispatch decides what it meant.
    """
    blobs = (_TOOL_CALL_BLOCK.findall(text) or _FENCED_JSON.findall(text)
             or [blob for blob in _BARE_JSON.findall(text) if _names_a_tool(blob)])
    if not blobs:
        # Only when the model wrote no call the ordinary way: a line of Python naming a
        # tool is then the call it meant, and dispatch checks it like any other.
        return tuple(call for _start, _end, call in _text_call_spans(text)[0])
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
    text = _FENCED_JSON.sub("", text)
    text = _BARE_JSON.sub(lambda m: "" if _names_a_tool(m.group(1)) else m.group(0), text)
    # A call written as Python is protocol too, run or not; one that never closes goes
    # from where it starts, the same as an unclosed block.
    spans, begun = _text_call_spans(text)
    cut = min(begun) if begun else len(text)
    kept, position = [], 0
    for start, end, _call in spans:
        if start >= cut:
            break
        kept.append(text[position:start])
        position = end
    kept.append(text[position:cut])
    stripped = "".join(kept)
    return _EMPTY_FENCE.sub("", stripped) if spans or begun else stripped


def _names_a_tool(blob: str) -> bool:
    """Whether a JSON object is a call of one of the tools, and not some other JSON."""
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and parsed.get("name") in _TEXT_CALL_TOOLS


def _text_call_spans(text: str) -> tuple[list[tuple[int, int, ToolCall]], list[int]]:
    """Tool calls written as Python in ``text``: ``(start, end, call)`` for each one that
    reads as a call, and the starts of any that do not (cut off, or not plain values).

    Python's own parser decides, never a pattern: the call must parse as exactly one call
    of that tool with literal arguments -- ``old_text="    x = 1\\n"`` is a string with
    a real newline in it, the way the model meant it. Anything else is not run.
    """
    found: list[tuple[int, int, ToolCall]] = []
    begun: list[int] = []
    position = 0
    while True:
        match = _TEXT_CALL_START.search(text, position)
        if match is None:
            return found, begun
        name, start = match.group(1), match.start(1)
        call, end = None, -1
        close = text.find(")", match.end() - 1)
        while close != -1:
            try:
                tree = ast.parse(text[start:close + 1], mode="eval")
            except SyntaxError:
                close = text.find(")", close + 1)
                continue
            call, end = _as_tool_call(tree.body, name, len(found)), close + 1
            break
        if call is None:
            begun.append(start)
            position = end if end != -1 else len(text)
            if end == -1:
                return found, begun
            continue
        found.append((start, end, call))
        position = end


def _as_tool_call(node: ast.expr, name: str, index: int) -> ToolCall | None:
    """``node`` as a call of tool ``name`` with plain values, or None."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == name):
        return None
    params = _TEXT_CALL_TOOLS[name]
    if len(node.args) > len(params):
        return None
    try:
        arguments = {params[i]: ast.literal_eval(arg) for i, arg in enumerate(node.args)}
        for keyword in node.keywords:
            if keyword.arg is None:
                return None
            arguments[keyword.arg] = ast.literal_eval(keyword.value)
    except (ValueError, SyntaxError, TypeError):
        return None
    return ToolCall(name=name, arguments=arguments, id=f"call_{index}")
