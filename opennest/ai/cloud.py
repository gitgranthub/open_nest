"""Shared plumbing for the cloud providers: HTTP, streaming, and honest errors.

Both cloud providers speak a different wire format but need the same three things: a
POST with a bearer credential, a server-sent-event stream to read back, and a failure
translated into something a child or a parent can act on. Those live here so
``openai_provider`` and ``anthropic_provider`` contain only the part that actually
differs -- the shape of the request and how a reply is assembled.

Two decisions worth knowing.

**The transport is injectable, and that is what keeps the test suite hermetic.** A
provider is handed something that turns a :class:`Request` into events. In the
application that is :class:`RequestsTransport`; in tests it is a scripted list, exactly
as ``ScriptedProvider`` stands in for the local model. No test in this suite opens a
socket, and adding these providers did not change that.

**No error text reaches a person without being scrubbed.** WORKORDER_01 section 22 keeps
API keys out of logs, and an error message is a log with a nicer font -- it lands in a
dialog, a traceback, and eventually a bug report. So :func:`redact` removes the key from
any server response before it is shown, and runs the same secret scanner Git commits go
through over what is left, in case a service ever echoes a credential back.

No SDK. ``requests`` is already an application dependency and the two APIs used here are
a POST and an event stream; adding two vendor SDKs would pull a dependency tree onto a
work-managed machine to save very little.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from opennest.ai.provider import ProviderError
from opennest.versioning import secret_scanner

#: Long enough for a slow first token, short enough that a hung connection does not look
#: like a hung application.
CONNECT_TIMEOUT_SECONDS = 15
READ_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class Request:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Event:
    """One server-sent event: its name, and its parsed JSON payload."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


class Transport(Protocol):
    """How a provider reaches a service. Swapped wholesale in tests."""

    def stream(self, request: Request) -> Iterator[Event]: ...

    def send(self, request: Request) -> dict[str, Any]: ...


class RequestsTransport:
    """The real one. The only place in Open Nest that opens an outbound connection."""

    def stream(self, request: Request) -> Iterator[Event]:
        response = self._post(request, stream=True)
        try:
            yield from parse_sse(response.iter_lines(decode_unicode=True))
        finally:
            response.close()

    def send(self, request: Request) -> dict[str, Any]:
        response = self._post(request, stream=False)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(
                "That AI service sent back something Open Nest could not read."
            ) from exc
        finally:
            response.close()

    def _post(self, request: Request, *, stream: bool):
        import requests

        try:
            response = requests.post(
                request.url,
                headers=request.headers,
                json=request.body,
                stream=stream,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
        except requests.exceptions.Timeout as exc:
            raise ProviderError(
                "That AI service did not answer in time. It needs the internet -- "
                "check the connection, or switch back to the model on this Mac."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderError(
                "Open Nest could not reach that AI service. It needs the internet -- "
                "check the connection, or switch back to the model on this Mac."
            ) from exc

        if response.status_code >= 400:
            body = _safe_body(response, request)
            response.close()
            raise http_error(response.status_code, body)
        return response


def parse_sse(lines: Iterator[str] | Sequence[str]) -> Iterator[Event]:
    """Turn a server-sent-event byte stream into events.

    Both services frame their streams the same way -- ``event:`` then ``data:``, blank
    line between -- so one reader serves both. A ``data: [DONE]`` sentinel ends the
    stream; unparseable data is skipped rather than raised, because one malformed frame
    should not lose a reply that is otherwise arriving fine.
    """
    name = ""
    payloads: list[str] = []

    for raw in lines:
        line = (raw or "").rstrip("\r")
        if not line:
            if payloads:
                blob = "\n".join(payloads)
                payloads = []
                if blob.strip() == "[DONE]":
                    return
                parsed = _load(blob)
                if parsed is not None:
                    yield Event(name or str(parsed.get("type", "")), parsed)
            name = ""
            continue
        if line.startswith(":"):
            continue  # A comment/keepalive.
        field_name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field_name == "event":
            name = value
        elif field_name == "data":
            payloads.append(value)

    # A stream that ends without a trailing blank line still has a final event in hand.
    if payloads:
        blob = "\n".join(payloads)
        if blob.strip() != "[DONE]":
            parsed = _load(blob)
            if parsed is not None:
                yield Event(name or str(parsed.get("type", "")), parsed)


def _load(blob: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def http_error(status: int, body: str) -> ProviderError:
    """A failed request, explained without blaming the child for it.

    ``body`` has already been through :func:`redact`. The status is what decides the
    wording, because the useful distinction for a parent is "the key is wrong" versus
    "you have run out of credit" versus "the service is having a bad day".
    """
    detail = f"\n\n{body.strip()}" if body.strip() else ""

    # The body is consulted before the status throughout, because the status alone is
    # not dependable. Every ordering below was fixed by running the spike against a
    # real account (SPIKES.md section 11), not reasoned out.

    # Ahead of the auth case deliberately: OpenAI returns **403** for "this project
    # does not have access to that model", which read as "your key was rejected" and
    # sent a parent off to replace a key that was perfectly good.
    if status == 404 or "model_not_found" in body or "does not have access to model" in body:
        # Open Nest must NOT quietly answer with a different model -- WORKORDER_01
        # section 38 forbids substituting one behind the user's back, and a child being
        # answered by something other than what the picker says is that failure exactly.
        # So: say so, and stop.
        return ProviderError(
            "That AI model is not available to this API key.\n\n"
            "The account may not have access to it yet, or the key may be limited to "
            "certain models. A parent can check the account, or pick a different model "
            "in Settings." + detail
        )
    if status in (401, 403):
        return ProviderError(
            "That AI service did not accept the API key. A parent can check or replace "
            "it in Settings, under Cloud AI." + detail
        )
    # Anthropic returns **400**, not 402, when an account is out of credit. A parent
    # reading "the request was refused (error 400)" would have no idea they need to
    # top up.
    if "credit balance is too low" in body or status == 402:
        return ProviderError(
            "That AI service says the account has run out of credit, so it will not "
            "answer.\n\n"
            "A parent can add credit to the account, or switch back to the model on "
            "this Mac, which is free and needs no internet."
        )
    if status == 429:
        return ProviderError(
            "That AI service is asking Open Nest to slow down, or the account has "
            "reached its limit. Wait a little, or use the model on this Mac." + detail
        )
    if 500 <= status < 600:
        return ProviderError(
            "That AI service is having a problem at their end. Try again in a moment, "
            "or use the model on this Mac." + detail
        )
    if status == 400 and "not scoped to a workspace" in body:
        # Found by running the spike against a real account (SPIKES.md section 11).
        # An organisation-level Anthropic key needs a workspace named on every request;
        # a key created inside a workspace does not. Without this the parent gets a
        # raw JSON blob about a header they have no way to set.
        return ProviderError(
            "That API key belongs to a whole organisation rather than to one "
            "workspace, and Open Nest cannot use it.\n\n"
            "A parent can create a key inside a workspace at console.anthropic.com "
            "and add that one instead, in Settings under Cloud AI."
        )
    return ProviderError(
        f"That AI service refused the request (error {status})." + detail
    )


def redact(text: str, key: str | None = None) -> str:
    """Remove anything credential-shaped from text that is about to be shown.

    Belt and braces on purpose. Neither service echoes a key back today; this exists so
    that if one ever does, or if a future header lands in an error string, the result is
    a redaction rather than a key in a dialog box a child is looking at.
    """
    cleaned = text or ""
    if key:
        cleaned = cleaned.replace(key, "[key removed]")
        # A truncated echo ("sk-ant-api03-Ab...") would slip past an exact match.
        if len(key) > 12:
            cleaned = cleaned.replace(key[:12], "[key removed]")
    if not cleaned.strip():
        return cleaned
    flagged = {finding.line for finding in secret_scanner.scan_text(cleaned)}
    if not flagged:
        return cleaned
    return "\n".join(
        "[line removed: it looked like a key]" if number in flagged else line
        for number, line in enumerate(cleaned.splitlines(), start=1)
    )


def credential_in(headers: dict[str, str]) -> str | None:
    """The key a request carried, so an error can be scrubbed of it.

    The transport never receives the key as an argument -- it only ever sees the headers
    a provider built -- so this is how :func:`redact` gets an exact string to remove
    rather than relying on the scanner's shape patterns alone.
    """
    for name, value in (headers or {}).items():
        lowered = name.lower()
        if lowered == "x-api-key" and value:
            return value
        if lowered == "authorization" and value:
            return value.split(" ", 1)[-1] if " " in value else value
    return None


def _safe_body(response, request: Request | None = None) -> str:
    """As much of an error body as is useful, with credentials taken out."""
    try:
        text = response.text or ""
    except Exception:
        return ""
    key = credential_in(request.headers) if request is not None else None
    return redact(text, key)[:1000]
