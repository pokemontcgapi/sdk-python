"""pagination-follows-links-next, to-list-max, batch-limits, prices-current-limits,
reference-single-request, vision-multipart, route-table."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest

from pokemontcgapi import PokemonTcgApi

from .conftest import FIXTURES, Recorder, fixture_doc, load_fixture, make_client, ok


def sets_handler() -> Recorder:
    pages = {
        "https://api.pokemontcgapi.com/v1/sets?limit=2&region=JP": "sets-page-1",
        fixture_doc("sets-page-1")["body"]["links"]["next"]: "sets-page-2",
        fixture_doc("sets-page-2")["body"]["links"]["next"]: "sets-page-3",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return load_fixture(pages[str(request.url)])

    return Recorder(handler)


def test_pagination_follows_links_next() -> None:
    handler = sets_handler()
    page = make_client(handler).sets.list(region="JP", limit=2)
    assert page.has_more and page.meta["total_count"] == 5
    assert [s["code"] for s in page.data] == ["m6", "m5"]

    second = page.next_page()
    assert second is not None
    assert handler.urls[1] == fixture_doc("sets-page-1")["body"]["links"]["next"]
    third = second.next_page()
    assert third is not None and not third.has_more
    assert third.next_page() is None
    assert handler.urls[2] == fixture_doc("sets-page-2")["body"]["links"]["next"]

    handler = sets_handler()
    codes = [s["code"] for s in make_client(handler).sets.list(region="JP", limit=2)]
    assert codes == ["m6", "m5", "m4", "m3", "m2"]
    assert len(handler.requests) == 3
    assert [p.meta["count"] for p in make_client(sets_handler()).sets.list(region="JP", limit=2).pages()] == [2, 2, 1]


def test_to_list_max() -> None:
    handler = sets_handler()
    rows = make_client(handler).sets.list(region="JP", limit=2).to_list(max=3)
    assert [s["code"] for s in rows] == ["m6", "m5", "m4"]
    assert len(handler.requests) == 2
    with pytest.raises(TypeError):
        make_client(sets_handler()).sets.list(region="JP", limit=2).to_list()  # type: ignore[call-arg]


def test_batch_limits() -> None:
    handler = Recorder(load_fixture("batch-missing"))
    client = make_client(handler)
    assert client.cards.batch([]) == {"data": [], "requested": 0, "found": 0}
    with pytest.raises(ValueError, match="at most 100"):
        client.cards.batch([f"x-{i}" for i in range(101)])
    assert handler.requests == []

    result = client.cards.batch(["sv8-116", "sv8-100", "inventato-xyz"], include=["index"], select=["id", "name"])
    assert handler.urls == [
        "https://api.pokemontcgapi.com/v1/cards/batch?ids=sv8-116%2Csv8-100%2Cinventato-xyz&select=id%2Cname&include=index"
    ]
    assert result["missing"][0]["suggested_id"] == "ssp-116"
    assert "suggested_id" not in result["missing"][1]
    assert result["withheld"] == ["index"]

    client.cards.batch([f"x-{i}" for i in range(100)])
    assert handler.requests[-1].url.params["ids"].count(",") == 99


def test_prices_current_limits() -> None:
    handler = Recorder(ok({"data": [], "requested": 2, "found": 0}))
    client = make_client(handler)
    assert client.prices.current([]) == {"data": [], "requested": 0, "found": 0}
    with pytest.raises(ValueError, match="at most 50"):
        client.prices.current([f"x-{i}" for i in range(51)])
    assert handler.requests == []
    client.prices.current(["base1-4", "bs-4"], source="CARDMARKET")
    assert handler.urls == ["https://api.pokemontcgapi.com/v1/prices/current?ids=base1-4%2Cbs-4&source=CARDMARKET"]


def test_reference_single_request() -> None:
    handler = Recorder(load_fixture("reference"))
    client = make_client(handler)
    assert client.reference.types()[:2] == ["Colorless", "Darkness"]
    assert client.reference.rarities()
    assert client.reference.subtypes() and client.reference.supertypes()
    assert "locales" in client.reference.all()
    assert len(handler.requests) == 1
    assert client.reference.all().get("nonexistent", []) == []


def test_vision_multipart(tmp_path: Path) -> None:
    handler = Recorder(load_fixture("vision-ambiguous"))
    client = make_client(handler)
    response = client.vision.identify(b"\xff\xd8\xff", top_k=3, set="bs", region="WEST")
    assert response["data"]["decision"] == "ambiguous" and response["data"]["id"] is None
    request = handler.requests[0]
    assert request.method == "POST" and request.url.path == "/v1/vision/identify"
    content_type = request.headers["content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    body = request.content
    assert b'name="image"; filename="card"' in body
    assert b"\xff\xd8\xff" in body
    assert b'name="top_k"\r\n\r\n3' in body and b'name="set"\r\n\r\nbs' in body and b'name="region"\r\n\r\nWEST' in body

    # Bytes only: no optional field travels.
    client.vision.identify(bytearray(b"\x89PNG"))
    assert b'name="top_k"' not in handler.requests[1].content

    photo = tmp_path / "card.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0")
    client.vision.identify(photo)
    assert b"\xff\xd8\xff\xe0" in handler.requests[2].content
    client.vision.identify(str(photo))
    client.vision.identify(io.BytesIO(b"\x89PNG\r\n"))
    assert b"\x89PNG\r\n" in handler.requests[4].content


def test_route_table() -> None:
    handler = Recorder(ok({"data": [], "meta": {}, "requested": 0, "found": 0, "status": "ok"}))
    client = make_client(handler)
    client.cards.search(q="name:charizard", order_by="-release_date", limit=1)
    client.cards.get("bs-4", lang="ja")
    client.cards.batch(["bs-4"])
    client.sets.list(region="JP", series="Scarlet & Violet")
    client.sets.get("sv3")
    client.sets.cards("sv3", include=["images"])
    client.artists.list(q="arita")
    client.artists.get("mitsuhiro-arita")
    client.series.list(limit=5)
    client.sealed.list(set=["evs", "fst"], include=["index"])
    client.sealed.get("evolving-skies-booster-box")
    client.sealed.prices("evolving-skies-booster-box", locale="en")
    client.prices.card("bs-4", source="CARDMARKET")
    client.prices.current(["bs-4"])
    client.prices.history("bs-4", bucket="week", from_="2026-09-01", to="2026-09-20")
    client.prices.stats("bs-4", window="30d")
    client.prices.movers(window="7d", direction="losers", min_value=5)
    client.prices.sources()
    client.reference.all()
    client.changes(since=42, limit=500)
    client.status()
    client.health()
    assert [u.removeprefix("https://api.pokemontcgapi.com") for u in handler.urls] == [
        "/v1/cards?q=name%3Acharizard&orderBy=-release_date&limit=1",
        "/v1/cards/bs-4?lang=ja",
        "/v1/cards/batch?ids=bs-4",
        "/v1/sets?region=JP&series=Scarlet+%26+Violet",
        "/v1/sets/sv3",
        "/v1/sets/sv3/cards?include=images",
        "/v1/artists?q=arita",
        "/v1/artists/mitsuhiro-arita",
        "/v1/series?limit=5",
        "/v1/sealed?set=evs%2Cfst&include=index",
        "/v1/sealed/evolving-skies-booster-box",
        "/v1/sealed/evolving-skies-booster-box/prices?locale=en",
        "/v1/cards/bs-4/prices?source=CARDMARKET",
        "/v1/prices/current?ids=bs-4",
        "/v1/cards/bs-4/prices/history?to=2026-09-20&bucket=week&from=2026-09-01",
        "/v1/cards/bs-4/prices/stats?window=30d",
        "/v1/prices/movers?window=7d&direction=losers&min_value=5",
        "/v1/prices/sources",
        "/v1/reference",
        "/v1/changes?since=42&limit=500",
        "/v1/status",
        "/v1/health",
    ]
    assert all(r.method == "GET" for r in handler.requests)


def test_route_table_context_manager_and_fixture_dir() -> None:
    assert FIXTURES.is_dir()
    with make_client(Recorder(load_fixture("health"))) as client:
        assert isinstance(client, PokemonTcgApi)
        assert client.health()["status"] == "ok"
