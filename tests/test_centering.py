"""Offline conformance tests against the shared synthetic P1 captures."""

import json

import httpx
import pytest

from pokemontcgapi import ServerError

from .conftest import Recorder, fixture_doc, load_fixture, make_async_client, make_client


def test_centering_multipart() -> None:
    handler = Recorder(load_fixture("centering-measure"))
    client = make_client(handler)
    geometry = fixture_doc("centering-confirm-input")["geometry"]
    response = client.centering.measure(b"synthetic", face="front", card_size="standard", corners=geometry["corners"])
    assert response == fixture_doc("centering-measure")["body"]
    assert response["data"]["status"] == "needs-review" and response["data"]["ceilings"] is None
    assert response["data"]["geometry"]["geometry_version"] == 1
    request = handler.requests[0]
    assert request.method == "POST" and request.url.path == "/v1/centering/measure"
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="image"; filename="card"' in request.content and b"synthetic" in request.content
    assert b'name="face"\r\n\r\nfront' in request.content
    assert b'name="card_size"\r\n\r\nstandard' in request.content
    assert json.dumps(geometry["corners"]).encode() in request.content
    assert client.last_response.credits_cost == 25
    client.centering.measure(b"synthetic", face="front")
    assert b'name="corners"' not in handler.requests[1].content
    assert b'name="card_size"' not in handler.requests[1].content


def test_centering_confirm() -> None:
    handler = Recorder(load_fixture("centering-confirm"))
    client = make_client(handler)
    payload = fixture_doc("centering-confirm-input")
    response = client.centering.confirm(payload)
    request = handler.requests[0]
    assert request.method == "POST" and request.url.path == "/v1/centering/confirm"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == payload
    assert response == fixture_doc("centering-confirm")["body"]
    assert response["data"]["basis"] == "client-confirmed-lines"
    assert response["data"]["ceilings"]["PSA"]["maximum_grade"] is not None
    assert "ceiling from centering alone, not a prediction of the final grade" in response["data"]["disclaimer"]


def test_centering_grade() -> None:
    handler = Recorder(load_fixture("centering-grade"))
    client = make_client(handler)
    response = client.centering.grade({"front_lr": 55, "front_tb": 52, "house": "PSA"})
    request = handler.requests[0]
    assert request.method == "POST" and request.url.path == "/v1/centering/grade"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {"front_lr": 55, "front_tb": 52, "house": "PSA"}
    assert response == fixture_doc("centering-grade")["body"]
    assert response["data"]["incomplete"] and response["data"]["back"] is None


def test_centering_standards() -> None:
    handler = Recorder(load_fixture("centering-standards"))
    client = make_client(handler)
    response = client.centering.standards(house="PSA", face="front")
    request = handler.requests[0]
    assert request.method == "GET" and request.url.path == "/v1/centering/standards"
    assert dict(request.url.params) == {"house": "PSA", "face": "front"}
    assert response == fixture_doc("centering-standards")["body"]
    assert response["data"]["standards"][0]["bands"][0]["value"] == 10


def test_centering_post_no_retry() -> None:
    handler = Recorder(
        httpx.Response(503, json={"error": {"code": "PROVIDER_UNAVAILABLE", "message": "Retry shortly."}})
    )
    client = make_client(handler, max_retries=3)
    for call in [
        lambda: client.centering.measure(b"x", face="front"),
        lambda: client.centering.confirm(fixture_doc("centering-confirm-input")),
        lambda: client.centering.grade({"front_lr": 55}),
    ]:
        with pytest.raises(ServerError):
            call()
    assert len(handler.requests) == 3


async def test_centering_async() -> None:
    handler = Recorder(
        load_fixture("centering-measure"),
        load_fixture("centering-confirm"),
        load_fixture("centering-grade"),
        load_fixture("centering-standards"),
    )
    async with make_async_client(handler) as client:
        assert (await client.centering.measure(b"x", face="front"))["data"]["status"] == "needs-review"
        assert (await client.centering.confirm(fixture_doc("centering-confirm-input")))["data"][
            "basis"
        ] == "client-confirmed-lines"
        assert (await client.centering.grade({"front_lr": 55}))["data"]["incomplete"]
        assert (await client.centering.standards(house="PSA"))["data"]["standards"][0]["house"] == "PSA"
    assert [r.method for r in handler.requests] == ["POST", "POST", "POST", "GET"]
