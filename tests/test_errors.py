"""error-mapping-table, error-body-fallback, next-step-accessors."""

from __future__ import annotations

from typing import Any

import pytest

from pokemontcgapi import (
    AuthenticationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    PlanRequiredError,
    PokemonTcgApiError,
    QuotaExceededError,
    RateLimitedError,
    ServerError,
    TrialExpiredError,
    UpgradeRequiredError,
    to_api_error,
)

from .conftest import Recorder, load_fixture, make_client


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (429, "QUOTA_EXCEEDED", QuotaExceededError),
        (403, "UPGRADE_REQUIRED", UpgradeRequiredError),
        (403, "PLAN_REQUIRED", PlanRequiredError),
        (403, "TRIAL_EXPIRED", TrialExpiredError),
        (429, "RATE_LIMITED", RateLimitedError),
        (401, "MISSING_API_KEY", AuthenticationError),
        (403, "FORBIDDEN", PermissionDeniedError),
        (404, "CARD_NOT_FOUND", NotFoundError),
        (400, "SET_NOT_FOUND", NotFoundError),
        (503, "UPSTREAM_DOWN", ServerError),
        (400, "INVALID_PARAMETER", InvalidRequestError),
        (422, "INVALID_BODY", InvalidRequestError),
        (302, "ODD", PokemonTcgApiError),
    ],
)
def test_error_mapping_table(status: int, code: str, cls: type[PokemonTcgApiError]) -> None:
    error = to_api_error(status, {"code": code, "message": "m", "request_id": "r1", "details": {"field": "x"}})
    assert type(error) is cls
    assert str(error) == f"{code}: m"
    assert error.code == code and error.status == status and error.request_id == "r1"
    assert isinstance(error, PokemonTcgApiError)


def test_error_mapping_table_subclasses_and_fields() -> None:
    assert issubclass(PlanRequiredError, PermissionDeniedError)
    assert issubclass(TrialExpiredError, PermissionDeniedError)
    rate = to_api_error(429, {"code": "RATE_LIMITED", "message": "m"}, retry_after=7)
    assert isinstance(rate, RateLimitedError) and rate.retry_after == 7
    assert to_api_error(429, {"code": "RATE_LIMITED", "message": "m"}).retry_after is None  # type: ignore[attr-defined]
    upgrade = to_api_error(403, {"code": "UPGRADE_REQUIRED", "message": "m", "details": {"permitted_window": "30d"}})
    assert isinstance(upgrade, UpgradeRequiredError) and upgrade.permitted_window == "30d"
    invalid = to_api_error(400, {"code": "INVALID_PARAMETER", "message": "m", "details": {"field": "page"}})
    assert isinstance(invalid, InvalidRequestError) and invalid.field == "page"
    assert to_api_error(400, {"code": "INVALID_PARAMETER", "message": "m"}).field is None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("fixture", "cls"),
    [
        ("401-missing-key", AuthenticationError),
        ("401-invalid-key", AuthenticationError),
        ("403-plan-required-next-step", PlanRequiredError),
        ("403-trial-expired", TrialExpiredError),
        ("404-card-not-found-did-you-mean", NotFoundError),
        ("400-invalid-parameter", InvalidRequestError),
        ("429-rate-limited", RateLimitedError),
        ("429-quota-exceeded-next-step", QuotaExceededError),
    ],
)
def test_error_mapping_table_from_fixtures(fixture: str, cls: type[PokemonTcgApiError]) -> None:
    client = make_client(Recorder(load_fixture(fixture)))
    with pytest.raises(cls) as excinfo:
        client.prices.movers()
    assert excinfo.value.request_id is not None
    assert client.last_response is not None
    assert client.last_response.error_code == excinfo.value.code


def test_error_mapping_table_retry_after_from_header() -> None:
    client = make_client(Recorder(load_fixture("429-rate-limited")))
    with pytest.raises(RateLimitedError) as excinfo:
        client.status()
    assert excinfo.value.retry_after == 1


def test_error_body_fallback() -> None:
    client = make_client(Recorder(load_fixture("500-html")))
    with pytest.raises(ServerError) as excinfo:
        client.status()
    assert excinfo.value.code == "HTTP_502"
    assert excinfo.value.status == 502
    assert str(excinfo.value).startswith("HTTP_502: ")
    assert excinfo.value.request_id is None


def test_next_step_accessors() -> None:
    next_step: dict[str, Any] = {
        "action": "subscribe",
        "actor": "account_owner",
        "plans_url": "https://example.test/pricing",
        "checkout_url": "https://example.test/subscribe?plan=custom&interval=monthly",
        "handoff": "The account owner needs to open https://example.test/subscribe?plan=custom&interval=monthly.",
    }
    error = to_api_error(
        429, {"code": "QUOTA_EXCEEDED", "message": "Exhausted", "details": {"quota_limit": 800, "next_step": next_step}}
    )
    assert isinstance(error, QuotaExceededError)
    assert error.details is not None and error.details["quota_limit"] == 800
    assert error.next_step == next_step
    assert error.handoff == next_step["handoff"]
    assert error.checkout_url == next_step["checkout_url"]
    assert error.action_url == next_step["checkout_url"]

    for malformed in [None, "wrong", {}, {"action": "pay", "actor": "agent"}]:
        error = to_api_error(403, {"code": "PLAN_REQUIRED", "message": "Denied", "details": {"next_step": malformed}})
        assert error.next_step is None
        assert error.checkout_url is None and error.action_url is None and error.handoff is None
    assert to_api_error(403, {"code": "PLAN_REQUIRED", "message": "Denied"}).next_step is None

    for action in ["verify_email", "contact_support", "contact_sales"]:
        error = to_api_error(
            403,
            {
                "code": "PLAN_REQUIRED",
                "message": "Denied",
                "details": {
                    "next_step": {
                        "action": action,
                        "actor": "account_owner",
                        "plans_url": "https://example.test/pricing",
                        "handoff": "Contact the owner.",
                    }
                },
            },
        )
        assert error.next_step is not None and error.next_step["action"] == action
        assert error.checkout_url is None and error.action_url is None


@pytest.mark.parametrize(
    ("action", "field", "url"),
    [
        ("subscribe", "checkout_url", "https://example.test/subscribe?plan=developer&interval=monthly"),
        ("upgrade", "manage_url", "https://example.test/account"),
        ("verify_email", "verify_url", "https://example.test/account"),
        ("contact_sales", "contact_url", "mailto:sales@example.test"),
        ("contact_support", "contact_url", "mailto:support@example.test"),
    ],
)
def test_next_step_accessors_action_url(action: str, field: str, url: str) -> None:
    step = {
        "action": action,
        "actor": "account_owner",
        "plans_url": "https://example.test/pricing",
        "handoff": "Contact the owner.",
        field: url,
    }
    error = to_api_error(403, {"code": "PLAN_REQUIRED", "message": "Denied", "details": {"next_step": step}})
    assert error.action_url == url
    assert error.checkout_url == (url if action == "subscribe" else None)
    malformed = to_api_error(
        403, {"code": "PLAN_REQUIRED", "message": "Denied", "details": {"next_step": {**step, field: 123}}}
    )
    assert malformed.action_url is None


def test_next_step_accessors_from_fixture() -> None:
    client = make_client(Recorder(load_fixture("403-plan-required-next-step")))
    with pytest.raises(PlanRequiredError) as excinfo:
        client.prices.movers()
    assert excinfo.value.action_url == "https://example.test/account"
    assert excinfo.value.handoff is not None
