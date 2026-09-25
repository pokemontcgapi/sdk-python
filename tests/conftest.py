"""Test helpers: fixtures from ``packages/fixtures`` served through ``httpx.MockTransport``.

Every test is offline. A handler receives the ``httpx.Request`` the SDK built and answers with a
fixture, so the tests check exactly what travels on the wire: URL, headers, multipart body.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from pokemontcgapi import AsyncPokemonTcgApi, PokemonTcgApi

# In the public repo the fixtures are copied to tests/fixtures by sync-public.sh; in the monorepo
# they live once, two directories up.
_CANDIDATES = [Path(__file__).parent / "fixtures", Path(__file__).parents[2] / "fixtures"]
FIXTURES = next((p for p in _CANDIDATES if p.is_dir()), _CANDIDATES[0])

Handler = Callable[[httpx.Request], httpx.Response]


def fixture_doc(name: str) -> dict[str, Any]:
    with (FIXTURES / f"{name}.json").open(encoding="utf-8") as fh:
        doc: dict[str, Any] = json.load(fh)
    return doc


def load_fixture(name: str) -> httpx.Response:
    doc = fixture_doc(name)
    if "body_text" in doc:
        return httpx.Response(doc["status"], headers=doc["headers"], content=doc["body_text"].encode())
    return httpx.Response(doc["status"], headers=doc["headers"], json=doc["body"])


def make_client(handler: Handler, **options: Any) -> PokemonTcgApi:
    options.setdefault("api_key", "test")
    options.setdefault("max_retries", 0)
    return PokemonTcgApi(transport=httpx.MockTransport(handler), **options)


def make_async_client(handler: Handler, **options: Any) -> AsyncPokemonTcgApi:
    options.setdefault("api_key", "test")
    options.setdefault("max_retries", 0)
    return AsyncPokemonTcgApi(transport=httpx.MockTransport(handler), **options)


class Recorder:
    """A handler that records every request and answers from a queue of responses."""

    def __init__(self, *responses: httpx.Response | Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        nxt = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        return nxt(request) if callable(nxt) else nxt

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def ok(body: Any, **headers: str) -> httpx.Response:
    return httpx.Response(200, headers=headers, json=body)


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replaces the sync and async sleeps with recorders, so retry tests run instantly."""
    waits: list[float] = []

    def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    async def fake_async_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("pokemontcgapi._http.time.sleep", fake_sleep)
    monkeypatch.setattr("pokemontcgapi._http.asyncio.sleep", fake_async_sleep)
    return waits
