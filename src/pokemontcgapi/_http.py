"""The transport.

One runtime dependency, httpx: it gives the sync and the async client the same request and response
objects, a multipart encoder, per-attempt timeouts and a mock transport for the tests. Everything
that decides something (parameter encoding, retry policy, backoff, header parsing, error mapping)
is a pure function here, so the two clients share it instead of drifting.
"""

from __future__ import annotations

import asyncio
import math
import os
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

import httpx

from ._version import __version__
from .errors import (
    ApiConnectionError,
    ApiErrorBody,
    ApiTimeoutError,
    PokemonTcgApiError,
    QuotaExceededError,
    RateLimitedError,
    ServerError,
    to_api_error,
)

DEFAULT_BASE_URL = "https://api.pokemontcgapi.com"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
USER_AGENT = f"pokemontcgapi-python/{__version__}"

CacheMode = Literal["none", "etag"]


@dataclass(frozen=True)
class ResponseInfo:
    """What the response says in its headers and the body does not carry.

    ``plan_withheld`` is the reason this exists: on ``cards.get(id, include=["prices"])`` the rows the
    plan does not cover (graded quotes below Growth) are silently missing from the body, and only the
    ``X-Plan-Withheld`` header says so.
    """

    url: str
    status: int
    request_id: str | None
    #: Same as ``error.code`` on API errors; ``None`` on successful responses.
    error_code: str | None
    #: Credits charged by this call. 0 on free routes, 304s and client errors.
    credits_cost: int | None
    quota_limit: int | None
    quota_remaining: int | None
    quota_reset: str | None
    rate_limit_remaining: int | None
    plan_withheld: tuple[str, ...]
    #: Trial only: when it ends.
    trial_expires_at: str | None


def _header_number(headers: httpx.Headers, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value) if math.isfinite(value) and value.is_integer() else None


def response_info(url: str, response: httpx.Response) -> ResponseInfo:
    headers = response.headers
    withheld = headers.get("x-plan-withheld")
    return ResponseInfo(
        url=url,
        status=response.status_code,
        request_id=headers.get("x-request-id"),
        error_code=headers.get("x-error-code"),
        credits_cost=_header_number(headers, "x-credits-cost"),
        quota_limit=_header_number(headers, "x-quota-limit"),
        quota_remaining=_header_number(headers, "x-quota-remaining"),
        quota_reset=headers.get("x-quota-reset"),
        rate_limit_remaining=_header_number(headers, "ratelimit-remaining"),
        plan_withheld=tuple(v.strip() for v in withheld.split(",")) if withheld else (),
        trial_expires_at=headers.get("x-trial-expires-at"),
    )


def path_segment(value: str) -> str:
    """URL-escape one path segment: ``/``, ``?`` and ``#`` in an id must not change the route."""
    return quote(value, safe="")


def serialize_params(params: Mapping[str, object] | None) -> dict[str, str]:
    """Query parameters as the API expects them.

    Lists (``select``, ``include``, ``ids``) travel as a comma-separated value, not as repeated keys.
    ``None`` and empty lists are dropped; booleans are lowercased, because ``str(True)`` is ``"True"``.
    """
    out: dict[str, str] = {}
    if not params:
        return out
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            if len(value) == 0:
                continue
            out[key] = ",".join(str(item) for item in value)
        else:
            out[key] = str(value)
    return out


def is_retryable(error: BaseException) -> bool:
    """Network failures, 5xx and 429: the only set where retrying makes sense."""
    if isinstance(error, QuotaExceededError):
        return False
    if isinstance(error, (RateLimitedError, ServerError, ApiConnectionError)):
        return True
    if isinstance(error, PokemonTcgApiError):
        return error.status == 408
    return False


def backoff_seconds(attempt: int, retry_after: int | None) -> float:
    """Exponential backoff with full jitter.

    The jitter is not a detail: without it, a thousand clients that took the same 429 all retry in
    the same millisecond and rebuild the queue they were trying to drain.
    """
    if retry_after is not None:
        return min(float(retry_after), 60.0)
    ceiling: float = min(0.5 * (2.0**attempt), 8.0)
    return random.random() * ceiling


def error_body(response: httpx.Response) -> ApiErrorBody:
    """A 5xx can come from a proxy in front of the API, so in HTML: build an error anyway."""
    try:
        parsed = response.json()
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return error  # type: ignore[return-value]
    reason = response.reason_phrase or f"HTTP {response.status_code}"
    return {"code": f"HTTP_{response.status_code}", "message": reason}


def retry_after_of(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class _Transport:
    """What the sync and the async client share: options, headers, ETag cache, response handling."""

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str,
        timeout: float,
        max_retries: int,
        cache: CacheMode,
        user_agent: str | None,
        on_response: Callable[[ResponseInfo], None] | None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key if api_key is not None else os.environ.get("PTCG_API_KEY")
        self.timeout = timeout
        self.max_retries = max_retries
        self._user_agent = user_agent or USER_AGENT
        self._etags: dict[str, tuple[str, Any]] | None = {} if cache == "etag" else None
        self._on_response = on_response
        #: The headers of the last response this instance received.
        self.last_response: ResponseInfo | None = None

    def url(self, path: str, params: Mapping[str, object] | None = None) -> str:
        query = httpx.QueryParams(serialize_params(params))
        return f"{self.base_url}{path}{'?' + str(query) if query else ''}"

    def _headers(self, url: str, *, write: bool) -> tuple[dict[str, str], tuple[str, Any] | None]:
        headers = {"accept": "application/json", "user-agent": self._user_agent}
        if self._api_key is not None:
            headers["x-api-key"] = self._api_key
        # No conditional cache on writes: the ETag is the fingerprint of a body, and on a response
        # that depends on what you just uploaded it would mean nothing.
        cached = self._etags.get(url) if self._etags is not None and not write else None
        if cached is not None:
            headers["if-none-match"] = cached[0]
        return headers, cached

    def _interpret(self, url: str, response: httpx.Response, cached: tuple[str, Any] | None, *, write: bool) -> Any:
        self.last_response = response_info(url, response)
        if self._on_response is not None:
            self._on_response(self.last_response)

        # 304: the body is empty by definition, the answer is the cached one.
        if response.status_code == 304 and cached is not None:
            return cached[1]

        if response.status_code >= 400:
            raise to_api_error(response.status_code, error_body(response), retry_after_of(response))

        body = response.json()
        etag = response.headers.get("etag")
        if not write and self._etags is not None and etag is not None:
            self._etags[url] = (etag, body)
        return body

    def _timeout_error(self, error: httpx.TimeoutException) -> ApiTimeoutError:
        return ApiTimeoutError(self.timeout, error)

    @staticmethod
    def _connection_error(url: str, error: httpx.HTTPError) -> ApiConnectionError:
        return ApiConnectionError(f"Request to {url} failed", error)


class HttpClient(_Transport):
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        cache: CacheMode = "none",
        user_agent: str | None = None,
        on_response: Callable[[ResponseInfo], None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            cache=cache,
            user_agent=user_agent,
            on_response=on_response,
        )
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def get(self, path: str, params: Mapping[str, object] | None = None) -> Any:
        return self._request(self.url(path, params))

    def follow(self, absolute_url: str) -> Any:
        """Follow a URL the API built (``links.next``).

        Public because the cursor carries the signature of the sort order: rebuilding the URL by hand
        and putting the cursor back is exactly what the API refuses with ``INVALID_CURSOR``.
        """
        return self._request(absolute_url)

    def post(self, path: str, *, data: Mapping[str, str] | None = None, files: Mapping[str, Any] | None = None) -> Any:
        """POST with a body. Never retried: a POST that may have arrived is not idempotent."""
        return self._attempt(self.url(path), method="POST", data=data, files=files)

    def _request(self, url: str) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                return self._attempt(url)
            except Exception as error:
                if attempt == self.max_retries or not is_retryable(error):
                    raise
                retry_after = error.retry_after if isinstance(error, RateLimitedError) else None
                time.sleep(backoff_seconds(attempt, retry_after))
        raise AssertionError("unreachable")  # pragma: no cover

    def _attempt(
        self,
        url: str,
        *,
        method: str = "GET",
        data: Mapping[str, str] | None = None,
        files: Mapping[str, Any] | None = None,
    ) -> Any:
        write = method != "GET"
        headers, cached = self._headers(url, write=write)
        try:
            response = self._client.request(method, url, headers=headers, data=data, files=files)
        except httpx.TimeoutException as error:
            raise self._timeout_error(error) from error
        except httpx.HTTPError as error:
            raise self._connection_error(url, error) from error
        return self._interpret(url, response, cached, write=write)

    def close(self) -> None:
        self._client.close()


class AsyncHttpClient(_Transport):
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        cache: CacheMode = "none",
        user_agent: str | None = None,
        on_response: Callable[[ResponseInfo], None] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            cache=cache,
            user_agent=user_agent,
            on_response=on_response,
        )
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def get(self, path: str, params: Mapping[str, object] | None = None) -> Any:
        return await self._request(self.url(path, params))

    async def follow(self, absolute_url: str) -> Any:
        return await self._request(absolute_url)

    async def post(
        self, path: str, *, data: Mapping[str, str] | None = None, files: Mapping[str, Any] | None = None
    ) -> Any:
        return await self._attempt(self.url(path), method="POST", data=data, files=files)

    async def _request(self, url: str) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                return await self._attempt(url)
            except Exception as error:
                if attempt == self.max_retries or not is_retryable(error):
                    raise
                retry_after = error.retry_after if isinstance(error, RateLimitedError) else None
                await asyncio.sleep(backoff_seconds(attempt, retry_after))
        raise AssertionError("unreachable")  # pragma: no cover

    async def _attempt(
        self,
        url: str,
        *,
        method: str = "GET",
        data: Mapping[str, str] | None = None,
        files: Mapping[str, Any] | None = None,
    ) -> Any:
        write = method != "GET"
        headers, cached = self._headers(url, write=write)
        try:
            response = await self._client.request(method, url, headers=headers, data=data, files=files)
        except httpx.TimeoutException as error:
            raise self._timeout_error(error) from error
        except httpx.HTTPError as error:
            raise self._connection_error(url, error) from error
        return self._interpret(url, response, cached, write=write)

    async def aclose(self) -> None:
        await self._client.aclose()
