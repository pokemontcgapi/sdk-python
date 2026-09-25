"""The async client: the same checklist items where ``await`` changes the code path
(pagination-follows-links-next, retry-policy, etag-304, error-mapping-table, vision-multipart,
reference-single-request, route-table)."""

from __future__ import annotations

import httpx
import pytest

from pokemontcgapi import ApiTimeoutError, AsyncPage, AsyncPokemonTcgApi, NotFoundError, ServerError

from .conftest import Recorder, fixture_doc, load_fixture, make_async_client, ok


def sets_handler() -> Recorder:
    pages = {
        "https://api.pokemontcgapi.com/v1/sets?limit=2&region=JP": "sets-page-1",
        fixture_doc("sets-page-1")["body"]["links"]["next"]: "sets-page-2",
        fixture_doc("sets-page-2")["body"]["links"]["next"]: "sets-page-3",
    }
    return Recorder(lambda request: load_fixture(pages[str(request.url)]))


async def test_pagination_follows_links_next() -> None:
    handler = sets_handler()
    async with make_async_client(handler) as client:
        page = await client.sets.list(region="JP", limit=2)
        assert isinstance(page, AsyncPage) and page.has_more
        codes = [s["code"] async for s in page]
        assert codes == ["m6", "m5", "m4", "m3", "m2"]
        assert handler.urls[1] == fixture_doc("sets-page-1")["body"]["links"]["next"]
        second = await page.next_page()
        assert second is not None
        assert [s["code"] for s in await second.to_list(max=1)] == ["m4"]
        assert [p.meta["count"] async for p in page.pages()] == [2, 2, 1]


async def test_retry_policy(no_sleep: list[float]) -> None:
    handler = Recorder(load_fixture("429-rate-limited"), ok({"status": "ok"}))
    client = make_async_client(handler, max_retries=2)
    assert await client.status() == {"status": "ok"}
    assert len(handler.requests) == 2 and no_sleep == [1.0]

    handler = Recorder(load_fixture("500-html"))
    with pytest.raises(ServerError):
        await make_async_client(handler, max_retries=1).status()
    assert len(handler.requests) == 2

    handler = Recorder(load_fixture("500-html"))
    with pytest.raises(ServerError):
        await make_async_client(handler, max_retries=2).vision.identify(b"\xff\xd8")
    assert len(handler.requests) == 1


async def test_etag_304() -> None:
    handler = Recorder(load_fixture("sets-page-1"), load_fixture("304"))
    client = make_async_client(handler, cache="etag")
    first = await client.sets.list(region="JP", limit=2)
    again = await client.sets.list(region="JP", limit=2)
    assert handler.requests[1].headers["if-none-match"] == 'W/"sets-1-gzip"'
    assert again.data == first.data
    await client.aclose()


async def test_error_mapping_table() -> None:
    client = make_async_client(Recorder(load_fixture("404-card-not-found-did-you-mean")))
    with pytest.raises(NotFoundError) as excinfo:
        await client.cards.get("bs-4x")
    assert excinfo.value.details is not None and excinfo.value.details["did_you_mean"] == "bs-4"
    assert client.last_response is not None and client.last_response.error_code == "CARD_NOT_FOUND"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ApiTimeoutError):
        await make_async_client(timeout).status()


async def test_vision_multipart_and_reference_single_request() -> None:
    handler = Recorder(load_fixture("vision-ambiguous"))
    client = make_async_client(handler)
    response = await client.vision.identify(b"\xff\xd8\xff", set="bs")
    assert response["data"]["candidates"][0]["id"] == "bs-4"
    assert b'name="image"; filename="card"' in handler.requests[0].content
    assert b'name="set"\r\n\r\nbs' in handler.requests[0].content

    handler = Recorder(load_fixture("reference"))
    client = make_async_client(handler)
    assert await client.reference.types()
    assert await client.reference.rarities()
    assert len(handler.requests) == 1


async def test_route_table() -> None:
    handler = Recorder(ok({"data": [], "meta": {}, "requested": 0, "found": 0, "status": "ok"}))
    client: AsyncPokemonTcgApi = make_async_client(handler)
    await client.cards.search(limit=1)
    await client.cards.get("bs-4")
    await client.cards.batch(["bs-4"])
    await client.sets.list()
    await client.sets.get("sv3")
    await client.sets.cards("sv3")
    await client.artists.list()
    await client.artists.get("mitsuhiro-arita")
    await client.series.list()
    await client.sealed.list()
    await client.sealed.get("x")
    await client.sealed.prices("x")
    await client.prices.card("bs-4")
    await client.prices.current(["bs-4"])
    await client.prices.history("bs-4", from_="2026-09-01")
    await client.prices.stats("bs-4")
    await client.prices.movers()
    await client.prices.sources()
    await client.changes()
    await client.status()
    await client.health()
    assert [u.removeprefix("https://api.pokemontcgapi.com") for u in handler.urls] == [
        "/v1/cards?limit=1",
        "/v1/cards/bs-4",
        "/v1/cards/batch?ids=bs-4",
        "/v1/sets",
        "/v1/sets/sv3",
        "/v1/sets/sv3/cards",
        "/v1/artists",
        "/v1/artists/mitsuhiro-arita",
        "/v1/series",
        "/v1/sealed",
        "/v1/sealed/x",
        "/v1/sealed/x/prices",
        "/v1/cards/bs-4/prices",
        "/v1/prices/current?ids=bs-4",
        "/v1/cards/bs-4/prices/history?from=2026-09-01",
        "/v1/cards/bs-4/prices/stats",
        "/v1/prices/movers",
        "/v1/prices/sources",
        "/v1/changes",
        "/v1/status",
        "/v1/health",
    ]
