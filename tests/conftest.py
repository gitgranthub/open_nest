"""Shared test fixtures.

The scripted provider is the reason the agent, memory and rollover layers can be tested
at all without the real model. It replays a fixed list of replies and records what it was
asked, so a test asserts on the prompt the model *would* have received. Real-model
behaviour is measured separately and recorded in SPIKES.md; these tests are about whether
the application wires itself together correctly.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from opennest.ai.provider import Chunk, Message, ModelInfo, ModelProvider, Reply
from opennest.projects.manager import create_project


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


@pytest.fixture
def project(tmp_path: Path):
    return create_project("Asteroid Game", "games", root=tmp_path)
