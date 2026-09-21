"""Shared test fixtures.

The scripted provider is the reason the agent, memory and rollover layers can be tested
at all without the real model. It replays a fixed list of replies and records what it was
asked, so a test asserts on the prompt the model *would* have received. Real-model
behaviour is measured separately and recorded in SPIKES.md; these tests are about whether
the application wires itself together correctly.

:class:`FakeKeyring` is the same idea for credentials, added in Phase 6. Nothing in this
suite may touch the real macOS Keychain: a test whose result depends on whether the
developer happens to have saved an API key is not a test. Anything that reads a
credential takes an injected store, and this is what gets injected.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from opennest.ai.provider import Chunk, Message, ModelInfo, ModelProvider, Reply
from opennest.projects.manager import create_project
from opennest.security import keychain

# No test may open a window on the developer's screen.
#
# Phase 7 added tests that genuinely run each profile's starter template, because "the
# file was copied in" and "the file works" are different claims. The Games template is
# real Pygame, so those tests opened an actual game window, took focus, and closed it
# four seconds later -- on every run of the suite. The window was never the thing under
# test: that the template imports Pygame, creates a display and survives startup is.
#
# Set here rather than per-test so this cannot come back the next time something runs a
# project. ``python_runner._child_environment`` forwards SDL_VIDEODRIVER, which is what
# carries it into the sandboxed child process.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


class ScriptedProvider(ModelProvider):
    """Replays a fixed list of replies, recording what it was asked."""

    def __init__(self, replies: list[Reply], *, context_policy: dict | None = None) -> None:
        self.info = ModelInfo(
            id="fake", name="Fake", provider="fake",
            context_policy=dict(context_policy or {}),
        )
        self.replies = list(replies)
        self.calls: list[list[Message]] = []
        self.tools_offered: list[list[dict]] = []
        self._current = Reply()
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def chat(self, messages: Sequence[Message], *, tools=None, settings=None) -> Iterator[Chunk]:
        self.calls.append(list(messages))
        self.tools_offered.append(list(tools or []))
        self._current = self.replies.pop(0) if self.replies else Reply(text="(nothing left)")
        if self._current.text:
            yield Chunk(text=self._current.text)
        yield Chunk(done=True)

    def finish(self) -> Reply:
        return self._current

    @property
    def system_prompt(self) -> str:
        """The system message of the most recent request."""
        if not self.calls or not self.calls[-1]:
            return ""
        first = self.calls[-1][0]
        return first.content if first.role == "system" else ""


class PasswordDeleteError(Exception):
    """What ``keyring`` raises when deleting an item that is not there.

    Named rather than imported: ``keychain._is_missing_entry`` recognises it by class
    name, so this reproduces the real backend's behaviour without the test suite
    depending on the library's exception hierarchy.
    """


class FakeKeyring:
    """An in-memory stand-in for the macOS Keychain."""

    def __init__(self, items: dict | None = None) -> None:
        self.items: dict[tuple[str, str], str] = dict(items or {})

    def get_password(self, service: str, account: str):
        return self.items.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.items[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        if (service, account) not in self.items:
            raise PasswordDeleteError(account)
        del self.items[(service, account)]


@pytest.fixture
def credentials():
    """An empty credential store that touches nothing outside the test."""
    return keychain.Credentials(backend=FakeKeyring())


@pytest.fixture
def configured_credentials():
    """A store with both cloud keys saved, for the "a parent has set this up" cases."""
    store = keychain.Credentials(backend=FakeKeyring())
    store.save_key("anthropic", "sk-ant-api03-" + "a" * 40)
    store.save_key("openai", "sk-proj-" + "b" * 40)
    return store


@pytest.fixture
def can_send_images(monkeypatch):
    """Pretend a provider can put image bytes in front of a model.

    None can, today (``provider.IMAGE_INPUT_IMPLEMENTED``). Tests of the *capability
    rule* -- "a model that can see should not be told it cannot" -- need the
    precondition to hold, and those rules are correct and worth keeping tested. Tests of
    today's behaviour must not use this fixture.

    Delete it in the change that implements image transmission, along with the constant.
    """
    from opennest.ai import provider as provider_module

    monkeypatch.setattr(provider_module, "IMAGE_INPUT_IMPLEMENTED", True)


@pytest.fixture
def project(tmp_path: Path):
    return create_project("Asteroid Game", "games", root=tmp_path)
