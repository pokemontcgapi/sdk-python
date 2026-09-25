"""The error hierarchy.

Subclasses rather than one type with a ``code`` field, for a practical reason: whoever integrates
writes ``except RateLimitedError:``, and with a single type they would have to compare strings, which
means rewriting by hand the taxonomy we already know, getting the names wrong.

``QuotaExceededError`` is separate from ``RateLimitedError`` on purpose: they look like the same error
(both are 429) but are handled in opposite ways. A rate limit passes by waiting; a monthly quota that
ran out never passes, and retrying is only a way to spend time. The automatic retry in this client
retries the first and never retries the second.
"""

from __future__ import annotations

import sys
from typing import Any, Literal, TypedDict

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:  # pragma: no cover
    from typing_extensions import NotRequired

NextStepAction = Literal["subscribe", "upgrade", "contact_sales", "contact_support", "verify_email"]
_ACTIONS: frozenset[str] = frozenset({"subscribe", "upgrade", "contact_sales", "contact_support", "verify_email"})


class NextStepPlan(TypedDict):
    code: str
    name: str
    monthly_eur: NotRequired[str]
    yearly_eur: NotRequired[str]
    credits_per_month: NotRequired[int]


class NextStep(TypedDict):
    """The human hand-off attached to a commercial refusal (``details.next_step``)."""

    action: NextStepAction
    actor: Literal["account_owner"]
    plan: NotRequired[NextStepPlan]
    checkout_url: NotRequired[str]
    checkout_url_yearly: NotRequired[str]
    manage_url: NotRequired[str]
    contact_url: NotRequired[str]
    verify_url: NotRequired[str]
    plans_url: str
    handoff: str


class ApiErrorBody(TypedDict):
    code: str
    message: str
    details: NotRequired[dict[str, Any]]
    request_id: NotRequired[str]


class PokemonTcgApiError(Exception):
    """Base of every error the API answered with. Carries the stable ``code`` and the ``request_id``."""

    #: Stable code from the taxonomy, e.g. ``CARD_NOT_FOUND``.
    code: str
    status: int
    #: Always set when the response came through the API: it is the only thing support can look up
    #: in the logs. Include it in every bug report.
    request_id: str | None
    details: dict[str, Any] | None

    def __init__(self, status: int, body: ApiErrorBody) -> None:
        super().__init__(f"{body['code']}: {body['message']}")
        self.code = body["code"]
        self.status = status
        self.request_id = body.get("request_id")
        self.details = body.get("details")

    @property
    def next_step(self) -> NextStep | None:
        """``details.next_step`` when it is well formed, else ``None``. Never invents data."""
        details = self.details
        value = details.get("next_step") if details else None
        if not isinstance(value, dict):
            return None
        if (
            value.get("actor") != "account_owner"
            or not isinstance(value.get("handoff"), str)
            or not isinstance(value.get("plans_url"), str)
            or str(value.get("action")) not in _ACTIONS
        ):
            return None
        return value  # type: ignore[return-value]

    @property
    def checkout_url(self) -> str | None:
        step = self.next_step
        value = step.get("checkout_url") if step else None
        return value if isinstance(value, str) else None

    @property
    def action_url(self) -> str | None:
        """The URL for the action: checkout for subscribe, manage for upgrade, verify, or contact."""
        step = self.next_step
        if step is None:
            return None
        action = step["action"]
        if action == "subscribe":
            value: object = step.get("checkout_url")
        elif action == "upgrade":
            value = step.get("manage_url")
        elif action == "verify_email":
            value = step.get("verify_url")
        else:
            value = step.get("contact_url")
        return value if isinstance(value, str) else None

    @property
    def handoff(self) -> str | None:
        step = self.next_step
        return step["handoff"] if step else None


class AuthenticationError(PokemonTcgApiError):
    """401: the key is missing, malformed or revoked."""


class PermissionDeniedError(PokemonTcgApiError):
    """403: the key is valid but cannot do this."""


class PlanRequiredError(PermissionDeniedError):
    """403 ``PLAN_REQUIRED``: the route is not in the plan (movers and photos start at Growth)."""


class TrialExpiredError(PermissionDeniedError):
    """403 ``TRIAL_EXPIRED``: the trial ended (30 days) and the route costs credits. A plan is needed."""


class UpgradeRequiredError(PokemonTcgApiError):
    """403 ``UPGRADE_REQUIRED``: the requested window is wider than the plan's."""

    @property
    def permitted_window(self) -> Any:
        """The window the current plan grants, when the API states it."""
        return self.details.get("permitted_window") if self.details else None


class NotFoundError(PokemonTcgApiError):
    """404: the resource does not exist. Not a network error: not retried."""


class InvalidRequestError(PokemonTcgApiError):
    """400 / 422: the request is wrong. ``field`` says which parameter."""

    @property
    def field(self) -> str | None:
        value = self.details.get("field") if self.details else None
        return value if isinstance(value, str) else None


class RateLimitedError(PokemonTcgApiError):
    """429 with Retry-After: passes by waiting."""

    #: Seconds to wait, from the ``Retry-After`` header, if there was one.
    retry_after: int | None

    def __init__(self, status: int, body: ApiErrorBody, retry_after: int | None = None) -> None:
        super().__init__(status, body)
        self.retry_after = retry_after


class QuotaExceededError(PokemonTcgApiError):
    """429 for an exhausted period quota: does NOT pass by waiting, and is never retried."""


class ServerError(PokemonTcgApiError):
    """5xx."""


class ApiConnectionError(Exception):
    """The request never arrived: DNS, TLS, socket. ``__cause__`` holds the transport error."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class ApiTimeoutError(ApiConnectionError):
    """The request was abandoned by us after ``timeout`` seconds."""

    timeout: float

    def __init__(self, timeout: float, cause: BaseException | None = None) -> None:
        super().__init__(f"Request timed out after {timeout:g}s", cause)
        self.timeout = timeout


def to_api_error(status: int, body: ApiErrorBody, retry_after: int | None = None) -> PokemonTcgApiError:
    """From the error body to the right class.

    The ``code`` is checked BEFORE the status: the status says the family, the code says the case,
    and the two cases that matter most (limit versus quota) share the same status.
    """
    code = body["code"]
    if code == "QUOTA_EXCEEDED":
        return QuotaExceededError(status, body)
    if code == "UPGRADE_REQUIRED":
        return UpgradeRequiredError(status, body)
    if code == "PLAN_REQUIRED":
        return PlanRequiredError(status, body)
    if code == "TRIAL_EXPIRED":
        return TrialExpiredError(status, body)
    if status == 429:
        return RateLimitedError(status, body, retry_after)
    if status == 401:
        return AuthenticationError(status, body)
    if status == 403:
        return PermissionDeniedError(status, body)
    if status == 404 or code.endswith("_NOT_FOUND"):
        return NotFoundError(status, body)
    if status >= 500:
        return ServerError(status, body)
    if status >= 400:
        return InvalidRequestError(status, body)
    return PokemonTcgApiError(status, body)
