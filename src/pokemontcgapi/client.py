"""The client of pokemontcgapi.com, sync and async.

from pokemontcgapi import PokemonTcgApi

client = PokemonTcgApi()  # reads PTCG_API_KEY from the environment

card = client.cards.get("base1-4", include=["prices"])
print(card["name"], card.get("index_eur"))

for set_ in client.sets.list(region="JP"):
    print(set_["code"], set_["name"], set_["release_date"])
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import cast

import httpx

from ._http import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    AsyncHttpClient,
    CacheMode,
    HttpClient,
    ResponseInfo,
)
from .resources import (
    ArtistsResource,
    AsyncArtistsResource,
    AsyncCardsResource,
    AsyncPricesResource,
    AsyncReferenceResource,
    AsyncSealedResource,
    AsyncSeriesResource,
    AsyncSetsResource,
    AsyncVisionResource,
    CardsResource,
    PricesResource,
    ReferenceResource,
    SealedResource,
    SeriesResource,
    SetsResource,
    VisionResource,
)
from .types import CatalogStatus, ChangesResponse, Health


class PokemonTcgApi:
    """Synchronous client. Use it as a context manager to release the connection pool, or call ``close()``."""

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
        """
        :param api_key: the key; when omitted, ``PTCG_API_KEY`` from the environment.
        :param timeout: seconds per attempt, not per operation.
        :param max_retries: REPEATED attempts beyond the first. 0 disables retrying.
        :param cache: ``"etag"`` remembers ETags and sends ``If-None-Match``: a 304 has no body and
            costs no quota. The cache is in memory and per instance, on purpose.
        :param on_response: called for every response received, errors included: the place for a
            credit counter.
        :param transport: an ``httpx`` transport, for tests or environments that wrap the network.
        """
        self._http = HttpClient(
            api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            cache=cache,
            user_agent=user_agent,
            on_response=on_response,
            transport=transport,
        )
        self.cards = CardsResource(self._http)
        self.sets = SetsResource(self._http)
        self.artists = ArtistsResource(self._http)
        self.series = SeriesResource(self._http)
        self.sealed = SealedResource(self._http)
        self.prices = PricesResource(self._http)
        self.reference = ReferenceResource(self._http)
        self.vision = VisionResource(self._http)

    @property
    def last_response(self) -> ResponseInfo | None:
        """The headers of the last response: credits charged, quota left and what the plan withheld
        (``plan_withheld``). With concurrent requests it is the last one to arrive: to count them all
        use ``on_response``."""
        return self._http.last_response

    def changes(
        self, *, since: int | None = None, kind: str | None = None, limit: int | None = None
    ) -> ChangesResponse:
        """The incremental feed: what changed after ``since``. Save ``meta.next_since`` and send it
        back on the next call."""
        params = {k: v for k, v in {"since": since, "kind": kind, "limit": limit}.items() if v is not None}
        return cast(ChangesResponse, self._http.get("/v1/changes", params))

    def status(self) -> CatalogStatus:
        """Catalogue counts and freshness per source."""
        return cast(CatalogStatus, self._http.get("/v1/status"))

    def health(self) -> Health:
        """Liveness. Separate from ``status()``: a stalled ingest is not a service that is down."""
        return cast(Health, self._http.get("/v1/health"))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PokemonTcgApi:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()


class AsyncPokemonTcgApi:
    """Asynchronous client over ``httpx.AsyncClient``. Same methods, ``await`` them; list methods return an
    ``AsyncPage`` to ``async for`` over."""

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
        self._http = AsyncHttpClient(
            api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            cache=cache,
            user_agent=user_agent,
            on_response=on_response,
            transport=transport,
        )
        self.cards = AsyncCardsResource(self._http)
        self.sets = AsyncSetsResource(self._http)
        self.artists = AsyncArtistsResource(self._http)
        self.series = AsyncSeriesResource(self._http)
        self.sealed = AsyncSealedResource(self._http)
        self.prices = AsyncPricesResource(self._http)
        self.reference = AsyncReferenceResource(self._http)
        self.vision = AsyncVisionResource(self._http)

    @property
    def last_response(self) -> ResponseInfo | None:
        return self._http.last_response

    async def changes(
        self, *, since: int | None = None, kind: str | None = None, limit: int | None = None
    ) -> ChangesResponse:
        params = {k: v for k, v in {"since": since, "kind": kind, "limit": limit}.items() if v is not None}
        return cast(ChangesResponse, await self._http.get("/v1/changes", params))

    async def status(self) -> CatalogStatus:
        return cast(CatalogStatus, await self._http.get("/v1/status"))

    async def health(self) -> Health:
        return cast(Health, await self._http.get("/v1/health"))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncPokemonTcgApi:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.aclose()
