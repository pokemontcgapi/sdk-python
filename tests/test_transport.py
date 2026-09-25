"""params-encoding, env-key-fallback, headers-sent, response-info, on-response-called-on-errors,
timeout-maps-to-timeout-error."""

from __future__ import annotations

import httpx
import pytest

from pokemontcgapi import ApiConnectionError, ApiTimeoutError, NotFoundError, PokemonTcgApi, ResponseInfo, __version__
from pokemontcgapi._http import serialize_params

from .conftest import Recorder, fixture_doc, load_fixture, make_client, ok


def test_params_encoding() -> None:
    assert serialize_params(
        {
            "ids": ["a", "b"],
            "select": ("id", "name"),
            "empty": [],
            "none": None,
            "flag": True,
            "off": False,
            "limit": 25,
        }
    ) == {"ids": "a,b", "select": "id,name", "flag": "true", "off": "false", "limit": "25"}
    assert serialize_params(None) == {}

    handler = Recorder(ok({"id": "x"}))
    make_client(handler).cards.get("a/b c?d", include=["prices", "images"], select="id")
    assert handler.urls == ["https://api.pokemontcgapi.com/v1/cards/a%2Fb%20c%3Fd?select=id&include=prices%2Cimages"]


def test_env_key_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = Recorder(ok({}))
    monkeypatch.setenv("PTCG_API_KEY", "from-env")
    PokemonTcgApi(transport=httpx.MockTransport(handler)).status()
    assert handler.requests[0].headers["x-api-key"] == "from-env"

    monkeypatch.delenv("PTCG_API_KEY")
    PokemonTcgApi(transport=httpx.MockTransport(handler)).status()
    assert "x-api-key" not in handler.requests[1].headers

    PokemonTcgApi("explicit", transport=httpx.MockTransport(handler)).status()
    assert handler.requests[2].headers["x-api-key"] == "explicit"


def test_headers_sent() -> None:
    handler = Recorder(ok({}))
    make_client(handler).status()
    headers = handler.requests[0].headers
    assert headers["accept"] == "application/json"
    assert headers["x-api-key"] == "test"
    assert headers["user-agent"] == f"pokemontcgapi-python/{__version__}"

    make_client(handler, user_agent="my-bot/1.0").status()
    assert handler.requests[1].headers["user-agent"] == "my-bot/1.0"


def test_response_info() -> None:
    client = make_client(Recorder(load_fixture("card-bs-4-with-prices")))
    client.cards.get("bs-4", include=["prices"])
    info = client.last_response
    assert info == ResponseInfo(
        url="https://api.pokemontcgapi.com/v1/cards/bs-4?include=prices",
        status=200,
        request_id=fixture_doc("card-bs-4-with-prices")["headers"]["x-request-id"],
        error_code=None,
        credits_cost=3,
        quota_limit=800,
        quota_remaining=780,
        quota_reset="2026-10-01T00:00:00Z",
        rate_limit_remaining=4,
        plan_withheld=("graded", "non_english_locales"),
        trial_expires_at="2026-10-18T09:00:00Z",
    )

    client = make_client(Recorder(ok({}, **{"x-credits-cost": "n/a", "x-quota-limit": "12.0", "x-plan-withheld": ""})))
    client.status()
    assert client.last_response is not None
    assert client.last_response.credits_cost is None
    assert client.last_response.quota_limit == 12
    assert client.last_response.plan_withheld == ()


def test_on_response_called_on_errors() -> None:
    seen: list[ResponseInfo] = []
    client = make_client(Recorder(load_fixture("404-card-not-found-did-you-mean")), on_response=seen.append)
    with pytest.raises(NotFoundError) as excinfo:
        client.cards.get("bs-4x")
    assert [s.status for s in seen] == [404]
    assert seen[0].error_code == "CARD_NOT_FOUND"
    assert excinfo.value.details is not None
    assert excinfo.value.details["did_you_mean"] == "bs-4"
    assert client.last_response is seen[0]


def test_timeout_maps_to_timeout_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ApiTimeoutError) as excinfo:
        make_client(timeout, timeout=2.5).status()
    assert excinfo.value.timeout == 2.5
    assert isinstance(excinfo.value, ApiConnectionError)
    assert isinstance(excinfo.value.__cause__, httpx.ReadTimeout)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ApiConnectionError) as conn:
        make_client(refused).status()
    assert not isinstance(conn.value, ApiTimeoutError)
