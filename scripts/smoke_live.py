"""A short check against the real API. Spends about four credits.

    PTCG_LIVE=1 PTCG_API_KEY=... python scripts/smoke_live.py

It asserts the shape of things (classes, headers, that the second page came from ``links.next``), not
catalogue values, which move every day.
"""

from __future__ import annotations

import os
import sys

from pokemontcgapi import NotFoundError, PermissionDeniedError, PokemonTcgApi, RateLimitedError


def main() -> int:
    if os.environ.get("PTCG_LIVE") != "1" or not os.environ.get("PTCG_API_KEY"):
        print("set PTCG_LIVE=1 and PTCG_API_KEY to run the live smoke test")
        return 0

    client = PokemonTcgApi(cache="etag")

    status = client.status()
    assert status["catalog"]["cards"] > 0, status
    assert client.last_response is not None and client.last_response.credits_cost in (0, None)
    print("status ok:", status["catalog"])

    page = client.cards.search(limit=1)
    assert len(page.data) == 1 and client.last_response.request_id
    print("search ok, cost", client.last_response.credits_cost, "quota left", client.last_response.quota_remaining)

    try:
        client.cards.get("bs-4x")
        raise AssertionError("bs-4x should not exist")
    except NotFoundError as error:
        print("404 ok:", error.code, (error.details or {}).get("did_you_mean"))

    first = client.sets.list(limit=5)
    second = first.next_page()
    assert second is not None and client.last_response.url.startswith("https://api.pokemontcgapi.com/v1/sets?")
    third = second.next_page()
    assert third is not None
    print("pagination ok: three pages via links.next")

    client.sets.list(limit=5)
    assert client.last_response.status == 304, client.last_response
    print("etag ok: 304 on the repeated page, cost", client.last_response.credits_cost)

    try:
        client.prices.movers(window="7d")
        print("movers ok (the key is Growth or above)")
    except PermissionDeniedError as error:
        print("movers refused as expected on this plan:", error.code)

    hits = 0
    burst = PokemonTcgApi(max_retries=0)
    try:
        for _ in range(40):
            burst.reference.all()
            burst.reference._data = None  # force a new request: reference is cached per client
            hits += 1
    except RateLimitedError as error:
        assert isinstance(error.retry_after, int)
        print(f"rate limit ok after {hits} calls, retry_after {error.retry_after}s")
    else:
        print("no 429 within 40 free calls; rate-limit check skipped")

    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
