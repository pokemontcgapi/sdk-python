"""retry-policy, etag-304."""

from __future__ import annotations

import httpx
import pytest

from pokemontcgapi import NotFoundError, QuotaExceededError, RateLimitedError, ServerError
from pokemontcgapi._http import backoff_seconds

from .conftest import Recorder, load_fixture, make_client, ok


def test_retry_policy(no_sleep: list[float]) -> None:
    # 429 with Retry-After, then 200: one wait of exactly Retry-After seconds.
    handler = Recorder(load_fixture("429-rate-limited"), ok({"status": "ok"}))
    assert make_client(handler, max_retries=2).status() == {"status": "ok"}
    assert len(handler.requests) == 2
    assert no_sleep == [1.0]

    # 5xx every time: max_retries + 1 attempts, then the error surfaces.
    handler = Recorder(load_fixture("500-html"))
    with pytest.raises(ServerError):
        make_client(handler, max_retries=2).status()
    assert len(handler.requests) == 3

    # Quota exhaustion is a 429 too, and is never retried.
    handler = Recorder(load_fixture("429-quota-exceeded-next-step"))
    with pytest.raises(QuotaExceededError):
        make_client(handler, max_retries=2).status()
    assert len(handler.requests) == 1

    # Other 4xx are not retried either.
    handler = Recorder(load_fixture("404-card-not-found-did-you-mean"))
    with pytest.raises(NotFoundError):
        make_client(handler, max_retries=2).cards.get("bs-4x")
    assert len(handler.requests) == 1

    # Connection failures and 408 are.
    calls = 0

    def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("boom", request=request)
        if calls == 2:
            return httpx.Response(408, json={"error": {"code": "REQUEST_TIMEOUT", "message": "slow"}})
        return ok({"status": "ok"})

    assert make_client(flaky, max_retries=2).status() == {"status": "ok"}
    assert calls == 3

    # max_retries=0 means a single attempt.
    handler = Recorder(load_fixture("429-rate-limited"))
    with pytest.raises(RateLimitedError):
        make_client(handler, max_retries=0).status()
    assert len(handler.requests) == 1


def test_retry_policy_post_never_retried(no_sleep: list[float]) -> None:
    handler = Recorder(load_fixture("500-html"))
    with pytest.raises(ServerError):
        make_client(handler, max_retries=2).vision.identify(b"\xff\xd8")
    assert len(handler.requests) == 1
    assert no_sleep == []


def test_retry_policy_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    assert backoff_seconds(0, 5) == 5.0
    assert backoff_seconds(3, 3600) == 60.0
    monkeypatch.setattr("pokemontcgapi._http.random.random", lambda: 1.0)
    assert backoff_seconds(0, None) == 0.5
    assert backoff_seconds(1, None) == 1.0
    assert backoff_seconds(4, None) == 8.0
    assert backoff_seconds(9, None) == 8.0
    monkeypatch.setattr("pokemontcgapi._http.random.random", lambda: 0.0)
    assert backoff_seconds(2, None) == 0.0


def test_etag_304() -> None:
    first = load_fixture("sets-page-1")
    not_modified = load_fixture("304")
    handler = Recorder(first, not_modified, first)
    client = make_client(handler, cache="etag")

    page1 = client.sets.list(region="JP", limit=2)
    page2 = client.sets.list(region="JP", limit=2)
    assert "if-none-match" not in handler.requests[0].headers
    assert handler.requests[1].headers["if-none-match"] == 'W/"sets-1-gzip"'
    assert page2.data == page1.data
    assert client.last_response is not None and client.last_response.status == 304

    # A different URL is a different cache entry.
    client.sets.list(region="JP", limit=3)
    assert "if-none-match" not in handler.requests[2].headers

    # The cache is opt-in.
    handler = Recorder(first, first)
    client = make_client(handler)
    client.sets.list()
    client.sets.list()
    assert all("if-none-match" not in r.headers for r in handler.requests)

    # POST never uses it.
    handler = Recorder(load_fixture("vision-ambiguous"), load_fixture("vision-ambiguous"))
    client = make_client(handler, cache="etag")
    client.vision.identify(b"\xff\xd8")
    client.vision.identify(b"\xff\xd8")
    assert all("if-none-match" not in r.headers for r in handler.requests)
