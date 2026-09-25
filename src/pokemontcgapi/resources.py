"""The resources, mirroring the paths (``client.cards.get``, ``client.sets.cards``) so that going from
the documentation to the code needs no conversion table.

Every method exists twice, sync and async, over the same parameter builders: the builders decide
what travels on the wire, the two variants only decide whether to ``await`` it.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any, cast

from ._http import AsyncHttpClient, HttpClient
from ._http import path_segment as _p
from ._page import AsyncPage, Page
from .types import (
    Artist,
    Card,
    CardBatchResult,
    CardInclude,
    CardPricesBatchResult,
    CardPricesResponse,
    CardSet,
    ChangesResponse,
    HistoryResponse,
    Locale,
    MoversResponse,
    PriceSourceInfo,
    PrintRegion,
    SealedPricesResponse,
    SealedProduct,
    Series,
    StatsResponse,
    VisionResponse,
)

BATCH_MAX_IDS = 100
PRICES_CURRENT_MAX_IDS = 50

# ── parameter builders (shared by the sync and the async resources) ─────────


def _drop_none(**params: object) -> dict[str, object]:
    return {key: value for key, value in params.items() if value is not None}


def _card_list_params(
    q: str | None,
    select: Sequence[str] | str | None,
    order_by: str | None,
    limit: int | None,
    cursor: str | None,
    include: Sequence[CardInclude] | str | None,
    lang: Locale | None,
    set: str | Sequence[str] | None,  # noqa: A002 - the API parameter is called `set`
) -> dict[str, object]:
    return _drop_none(
        q=q, select=select, orderBy=order_by, limit=limit, cursor=cursor, include=include, lang=lang, set=set
    )


def _card_get_params(
    select: Sequence[str] | str | None, include: Sequence[CardInclude] | str | None, lang: Locale | None
) -> dict[str, object]:
    return _drop_none(select=select, include=include, lang=lang)


def _batch_ids(ids: Sequence[str], limit: int, what: str) -> list[str]:
    if len(ids) > limit:
        raise ValueError(f"{what} accepts at most {limit} ids, received {len(ids)}. Chunk the list.")
    return list(ids)


def _empty_batch() -> dict[str, Any]:
    return {"data": [], "requested": 0, "found": 0}


def _price_filter_params(source: str | None, variant: str | None, locale: str | None) -> dict[str, object]:
    return _drop_none(source=source, variant=variant, locale=locale)


def _history_params(
    source: str | None,
    variant: str | None,
    locale: str | None,
    printing: str | None,
    from_: str | None,
    to: str | None,
    bucket: str | None,
) -> dict[str, object]:
    params = _price_filter_params(source, variant, locale)
    params.update(_drop_none(printing=printing, to=to, bucket=bucket))
    if from_ is not None:
        params["from"] = from_
    return params


def _image_payload(image: bytes | bytearray | IO[bytes] | os.PathLike[str] | str) -> Any:
    """What goes in the ``image`` part: bytes as they are, a path read once, a file object passed through.

    The generic content type and not ``image/jpeg``: the server recognises the format from the magic
    bytes, and declaring the wrong one would be worse than saying nothing.
    """
    if isinstance(image, (bytes, bytearray)):
        data: Any = bytes(image)
    elif isinstance(image, (str, os.PathLike)):
        data = Path(image).read_bytes()
    else:
        data = image
    return {"image": ("card", data, "application/octet-stream")}


def _identify_fields(top_k: int | None, set: str | None, region: PrintRegion | None) -> dict[str, str]:  # noqa: A002
    fields: dict[str, str] = {}
    if top_k is not None:
        fields["top_k"] = str(top_k)
    if set is not None:
        fields["set"] = set
    if region is not None:
        fields["region"] = region
    return fields


# ── sync ────────────────────────────────────────────────────────────────────


class CardsResource:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def search(
        self,
        *,
        q: str | None = None,
        select: Sequence[str] | str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        include: Sequence[CardInclude] | str | None = None,
        lang: Locale | None = None,
        set: str | Sequence[str] | None = None,  # noqa: A002
    ) -> Page[Card]:
        """Search the catalogue. Returns the first page, iterable to the end.

        Field names in ``q`` are camelCase and dotted (``set.code``, ``nationalPokedexNumbers``) while
        the response keys are snake_case (``set_code``). Not a typo: two vocabularies, and writing one
        in place of the other produces a 400 with the list of valid ones.
        """
        params = _card_list_params(q, select, order_by, limit, cursor, include, lang, set)
        return Page(self._http, self._http.get("/v1/cards", params))

    def get(
        self,
        id: str,  # noqa: A002
        *,
        select: Sequence[str] | str | None = None,
        include: Sequence[CardInclude] | str | None = None,
        lang: Locale | None = None,
    ) -> Card:
        """One card by id. Accepts both our id and the alternate legacy id."""
        return cast(Card, self._http.get(f"/v1/cards/{_p(id)}", _card_get_params(select, include, lang)))

    def batch(
        self,
        ids: Sequence[str],
        *,
        select: Sequence[str] | str | None = None,
        include: Sequence[CardInclude] | str | None = None,
        lang: Locale | None = None,
    ) -> CardBatchResult:
        """Up to 100 ids in one request.

        The response carries ``requested`` and ``found``, and when something does not resolve also
        ``missing``: one element per id, with ``suggested_id`` where the id is a historical alias of a
        card that now sits in another set.
        """
        if len(ids) == 0:
            return cast(CardBatchResult, _empty_batch())
        params: dict[str, object] = {"ids": _batch_ids(ids, BATCH_MAX_IDS, "batch()")}
        params.update(_card_get_params(select, include, lang))
        return cast(CardBatchResult, self._http.get("/v1/cards/batch", params))


class SetsResource:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        q: str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        region: PrintRegion | None = None,
        series: str | None = None,
        lang: Locale | None = None,
    ) -> Page[CardSet]:
        """The sets. ``region`` is the filter worth knowing: ``JP`` returns the Japanese releases, which
        are the largest part of the catalogue and are not translations of the Western ones."""
        params = _drop_none(q=q, orderBy=order_by, limit=limit, cursor=cursor, region=region, series=series, lang=lang)
        return Page(self._http, self._http.get("/v1/sets", params))

    def get(self, code: str, *, lang: Locale | None = None) -> CardSet:
        """One set by code, slug or alternate id."""
        return cast(CardSet, self._http.get(f"/v1/sets/{_p(code)}", _drop_none(lang=lang)))

    def cards(
        self,
        code: str,
        *,
        q: str | None = None,
        select: Sequence[str] | str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        include: Sequence[CardInclude] | str | None = None,
        lang: Locale | None = None,
    ) -> Page[Card]:
        """The cards of a set, in collection order."""
        params = _card_list_params(q, select, order_by, limit, cursor, include, lang, None)
        return Page(self._http, self._http.get(f"/v1/sets/{_p(code)}/cards", params))


class ArtistsResource:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def list(
        self, *, q: str | None = None, order_by: str | None = None, limit: int | None = None, cursor: str | None = None
    ) -> Page[Artist]:
        params = _drop_none(q=q, orderBy=order_by, limit=limit, cursor=cursor)
        return Page(self._http, self._http.get("/v1/artists", params))

    def get(self, slug: str) -> Artist:
        return cast(Artist, self._http.get(f"/v1/artists/{_p(slug)}"))


class SeriesResource:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def list(self, *, order_by: str | None = None, limit: int | None = None, cursor: str | None = None) -> Page[Series]:
        """The series (Scarlet & Violet, Sword & Shield, ...) with their set count."""
        params = _drop_none(orderBy=order_by, limit=limit, cursor=cursor)
        return Page(self._http, self._http.get("/v1/series", params))


class SealedResource:
    """Sealed products: booster boxes, ETBs, tins, blisters, collections."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        q: str | None = None,
        set: str | Sequence[str] | None = None,  # noqa: A002
        kind: str | None = None,
        lang: Locale | None = None,
        include: Sequence[str] | str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[SealedProduct]:
        params = _drop_none(
            q=q, set=set, kind=kind, lang=lang, include=include, orderBy=order_by, limit=limit, cursor=cursor
        )
        return Page(self._http, self._http.get("/v1/sealed", params))

    def get(self, id: str, *, lang: Locale | None = None) -> SealedProduct:  # noqa: A002
        return cast(SealedProduct, self._http.get(f"/v1/sealed/{_p(id)}", _drop_none(lang=lang)))

    def prices(
        self,
        id: str,  # noqa: A002
        *,
        source: str | None = None,
        variant: str | None = None,
        locale: str | None = None,
    ) -> SealedPricesResponse:
        """Current prices of a product. 2 credits. The composite index does not cover sealed
        products: ``index`` is ``None``."""
        params = _price_filter_params(source, variant, locale)
        return cast(SealedPricesResponse, self._http.get(f"/v1/sealed/{_p(id)}/prices", params))


class PricesResource:
    """The dedicated price routes.

    Every row says where it comes from (``source``), what it rests on (``basis``: sold, asking, guide,
    derived) and which day it is for (``as_of``). The rows the plan does not cover are missing from
    the body: ``client.last_response.plan_withheld`` says which.
    """

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def card(
        self,
        id: str,  # noqa: A002
        *,
        source: str | None = None,
        variant: str | None = None,
        locale: str | None = None,
    ) -> CardPricesResponse:
        """Index and current quotes of a card. 2 credits."""
        params = _price_filter_params(source, variant, locale)
        return cast(CardPricesResponse, self._http.get(f"/v1/cards/{_p(id)}/prices", params))

    def current(
        self, ids: Sequence[str], *, source: str | None = None, variant: str | None = None, locale: str | None = None
    ) -> CardPricesBatchResult:
        """Up to 50 cards in one call, 4 credits per 25."""
        if len(ids) == 0:
            return cast(CardPricesBatchResult, _empty_batch())
        params: dict[str, object] = {"ids": _batch_ids(ids, PRICES_CURRENT_MAX_IDS, "prices.current()")}
        params.update(_price_filter_params(source, variant, locale))
        return cast(CardPricesBatchResult, self._http.get("/v1/prices/current", params))

    def history(
        self,
        id: str,  # noqa: A002
        *,
        source: str | None = None,
        variant: str | None = None,
        locale: str | None = None,
        printing: str | None = None,
        from_: str | None = None,
        to: str | None = None,
        bucket: str | None = None,
    ) -> HistoryResponse:
        """Daily history. 5 credits. The window depends on the plan (7 days on the trial, 30 on
        Developer, everything from Growth): asking for a wider one raises ``UpgradeRequiredError``.
        ``from_`` is sent as ``from``, which is a reserved word in Python."""
        params = _history_params(source, variant, locale, printing, from_, to, bucket)
        return cast(HistoryResponse, self._http.get(f"/v1/cards/{_p(id)}/prices/history", params))

    def stats(self, id: str, *, window: str | None = None, locale: str | None = None) -> StatsResponse:  # noqa: A002
        """Low, high, median and change of the index over a window. 2 credits."""
        params = _drop_none(window=window, locale=locale)
        return cast(StatsResponse, self._http.get(f"/v1/cards/{_p(id)}/prices/stats", params))

    def movers(
        self,
        *,
        window: str | None = None,
        direction: str | None = None,
        min_value: float | None = None,
        locale: str | None = None,
        limit: int | None = None,
    ) -> MoversResponse:
        """The cards that moved the most. 3 credits, from the Growth plan (``PlanRequiredError`` below)."""
        params = _drop_none(window=window, direction=direction, min_value=min_value, locale=locale, limit=limit)
        return cast(MoversResponse, self._http.get("/v1/prices/movers", params))

    def sources(self) -> list[PriceSourceInfo]:
        """The sources, with the declared delay of each. Free."""
        return cast(list[PriceSourceInfo], self._http.get("/v1/prices/sources")["data"])


class ReferenceResource:
    """The vocabularies, to populate a UI's filters without guessing the strings.

    One network request per client instance even when calling all of them: the response is the
    same and is remembered for the lifetime of the client.
    """

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._data: dict[str, list[str]] | None = None

    def all(self) -> dict[str, list[str]]:
        """Every vocabulary at once: ``locales``, ``print_regions``, ``conditions``, ``printings``,
        ``grading_companies``, ``price_variants``, ``price_bases``, ``change_kinds`` and the others
        ``/v1/reference`` lists, besides the four below."""
        if self._data is None:
            self._data = cast(dict[str, list[str]], self._http.get("/v1/reference")["data"])
        return self._data

    def _list(self, key: str) -> list[str]:
        return self.all().get(key, [])

    def types(self) -> list[str]:
        return self._list("types")

    def subtypes(self) -> list[str]:
        return self._list("subtypes")

    def supertypes(self) -> list[str]:
        return self._list("supertypes")

    def rarities(self) -> list[str]:
        return self._list("rarities")


class VisionResource:
    """Recognition of a card from a photograph.

    It costs 25 credits a call against the one of a lookup: it is the only route that does not return
    a row but the outcome of a comparison with the whole image index. Worth knowing before putting it
    in a loop.
    """

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def identify(
        self,
        image: bytes | bytearray | IO[bytes] | os.PathLike[str] | str,
        *,
        top_k: int | None = None,
        set: str | None = None,  # noqa: A002
        region: PrintRegion | None = None,
    ) -> VisionResponse:
        """Send a photo, receive the ranked candidates.

        ``image`` is raw bytes, an open binary file, or a path. **Read ``decision`` before ``id``.**
        ``id`` is set only on ``match``; on ``ambiguous`` it is ``None`` on purpose, because two
        printings of the same illustration are not distinguishable from the image alone. If your flow
        knows the set, pass it in ``set``: it is what breaks the tie.
        """
        files = _image_payload(image)
        data = _identify_fields(top_k, set, region)
        return cast(VisionResponse, self._http.post("/v1/vision/identify", data=data or None, files=files))


# ── async ───────────────────────────────────────────────────────────────────


class AsyncCardsResource:
    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http

    async def search(
        self,
        *,
        q: str | None = None,
        select: Sequence[str] | str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        include: Sequence[CardInclude] | str | None = None,
        lang: Locale | None = None,
        set: str | Sequence[str] | None = None,  # noqa: A002
    ) -> AsyncPage[Card]:
        params = _card_list_params(q, select, order_by, limit, cursor, include, lang, set)
        return AsyncPage(self._http, await self._http.get("/v1/cards", params))

    async def get(
        self,
        id: str,  # noqa: A002
        *,
        select: Sequence[str] | str | None = None,
        include: Sequence[CardInclude] | str | None = None,
        lang: Locale | None = None,
    ) -> Card:
        return cast(Card, await self._http.get(f"/v1/cards/{_p(id)}", _card_get_params(select, include, lang)))

    async def batch(
        self,
        ids: Sequence[str],
        *,
        select: Sequence[str] | str | None = None,
        include: Sequence[CardInclude] | str | None = None,
        lang: Locale | None = None,
    ) -> CardBatchResult:
        if len(ids) == 0:
            return cast(CardBatchResult, _empty_batch())
        params: dict[str, object] = {"ids": _batch_ids(ids, BATCH_MAX_IDS, "batch()")}
        params.update(_card_get_params(select, include, lang))
        return cast(CardBatchResult, await self._http.get("/v1/cards/batch", params))


class AsyncSetsResource:
    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http

    async def list(
        self,
        *,
        q: str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        region: PrintRegion | None = None,
        series: str | None = None,
        lang: Locale | None = None,
    ) -> AsyncPage[CardSet]:
        params = _drop_none(q=q, orderBy=order_by, limit=limit, cursor=cursor, region=region, series=series, lang=lang)
        return AsyncPage(self._http, await self._http.get("/v1/sets", params))

    async def get(self, code: str, *, lang: Locale | None = None) -> CardSet:
        return cast(CardSet, await self._http.get(f"/v1/sets/{_p(code)}", _drop_none(lang=lang)))

    async def cards(
        self,
        code: str,
        *,
        q: str | None = None,
        select: Sequence[str] | str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        include: Sequence[CardInclude] | str | None = None,
        lang: Locale | None = None,
    ) -> AsyncPage[Card]:
        params = _card_list_params(q, select, order_by, limit, cursor, include, lang, None)
        return AsyncPage(self._http, await self._http.get(f"/v1/sets/{_p(code)}/cards", params))


class AsyncArtistsResource:
    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http

    async def list(
        self, *, q: str | None = None, order_by: str | None = None, limit: int | None = None, cursor: str | None = None
    ) -> AsyncPage[Artist]:
        params = _drop_none(q=q, orderBy=order_by, limit=limit, cursor=cursor)
        return AsyncPage(self._http, await self._http.get("/v1/artists", params))

    async def get(self, slug: str) -> Artist:
        return cast(Artist, await self._http.get(f"/v1/artists/{_p(slug)}"))


class AsyncSeriesResource:
    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http

    async def list(
        self, *, order_by: str | None = None, limit: int | None = None, cursor: str | None = None
    ) -> AsyncPage[Series]:
        params = _drop_none(orderBy=order_by, limit=limit, cursor=cursor)
        return AsyncPage(self._http, await self._http.get("/v1/series", params))


class AsyncSealedResource:
    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http

    async def list(
        self,
        *,
        q: str | None = None,
        set: str | Sequence[str] | None = None,  # noqa: A002
        kind: str | None = None,
        lang: Locale | None = None,
        include: Sequence[str] | str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPage[SealedProduct]:
        params = _drop_none(
            q=q, set=set, kind=kind, lang=lang, include=include, orderBy=order_by, limit=limit, cursor=cursor
        )
        return AsyncPage(self._http, await self._http.get("/v1/sealed", params))

    async def get(self, id: str, *, lang: Locale | None = None) -> SealedProduct:  # noqa: A002
        return cast(SealedProduct, await self._http.get(f"/v1/sealed/{_p(id)}", _drop_none(lang=lang)))

    async def prices(
        self,
        id: str,  # noqa: A002
        *,
        source: str | None = None,
        variant: str | None = None,
        locale: str | None = None,
    ) -> SealedPricesResponse:
        params = _price_filter_params(source, variant, locale)
        return cast(SealedPricesResponse, await self._http.get(f"/v1/sealed/{_p(id)}/prices", params))


class AsyncPricesResource:
    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http

    async def card(
        self,
        id: str,  # noqa: A002
        *,
        source: str | None = None,
        variant: str | None = None,
        locale: str | None = None,
    ) -> CardPricesResponse:
        params = _price_filter_params(source, variant, locale)
        return cast(CardPricesResponse, await self._http.get(f"/v1/cards/{_p(id)}/prices", params))

    async def current(
        self, ids: Sequence[str], *, source: str | None = None, variant: str | None = None, locale: str | None = None
    ) -> CardPricesBatchResult:
        if len(ids) == 0:
            return cast(CardPricesBatchResult, _empty_batch())
        params: dict[str, object] = {"ids": _batch_ids(ids, PRICES_CURRENT_MAX_IDS, "prices.current()")}
        params.update(_price_filter_params(source, variant, locale))
        return cast(CardPricesBatchResult, await self._http.get("/v1/prices/current", params))

    async def history(
        self,
        id: str,  # noqa: A002
        *,
        source: str | None = None,
        variant: str | None = None,
        locale: str | None = None,
        printing: str | None = None,
        from_: str | None = None,
        to: str | None = None,
        bucket: str | None = None,
    ) -> HistoryResponse:
        params = _history_params(source, variant, locale, printing, from_, to, bucket)
        return cast(HistoryResponse, await self._http.get(f"/v1/cards/{_p(id)}/prices/history", params))

    async def stats(self, id: str, *, window: str | None = None, locale: str | None = None) -> StatsResponse:  # noqa: A002
        params = _drop_none(window=window, locale=locale)
        return cast(StatsResponse, await self._http.get(f"/v1/cards/{_p(id)}/prices/stats", params))

    async def movers(
        self,
        *,
        window: str | None = None,
        direction: str | None = None,
        min_value: float | None = None,
        locale: str | None = None,
        limit: int | None = None,
    ) -> MoversResponse:
        params = _drop_none(window=window, direction=direction, min_value=min_value, locale=locale, limit=limit)
        return cast(MoversResponse, await self._http.get("/v1/prices/movers", params))

    async def sources(self) -> list[PriceSourceInfo]:
        return cast(list[PriceSourceInfo], (await self._http.get("/v1/prices/sources"))["data"])


class AsyncReferenceResource:
    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http
        self._data: dict[str, list[str]] | None = None

    async def all(self) -> dict[str, list[str]]:
        if self._data is None:
            self._data = cast(dict[str, list[str]], (await self._http.get("/v1/reference"))["data"])
        return self._data

    async def _list(self, key: str) -> list[str]:
        return (await self.all()).get(key, [])

    async def types(self) -> list[str]:
        return await self._list("types")

    async def subtypes(self) -> list[str]:
        return await self._list("subtypes")

    async def supertypes(self) -> list[str]:
        return await self._list("supertypes")

    async def rarities(self) -> list[str]:
        return await self._list("rarities")


class AsyncVisionResource:
    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http

    async def identify(
        self,
        image: bytes | bytearray | IO[bytes] | os.PathLike[str] | str,
        *,
        top_k: int | None = None,
        set: str | None = None,  # noqa: A002
        region: PrintRegion | None = None,
    ) -> VisionResponse:
        files = _image_payload(image)
        data = _identify_fields(top_k, set, region)
        return cast(VisionResponse, await self._http.post("/v1/vision/identify", data=data or None, files=files))


__all__ = [
    "ArtistsResource",
    "AsyncArtistsResource",
    "AsyncCardsResource",
    "AsyncPricesResource",
    "AsyncReferenceResource",
    "AsyncSealedResource",
    "AsyncSeriesResource",
    "AsyncSetsResource",
    "AsyncVisionResource",
    "CardsResource",
    "PricesResource",
    "ReferenceResource",
    "SealedResource",
    "SeriesResource",
    "SetsResource",
    "VisionResource",
]

# Silence the unused-import check for the response types used only inside casts.
_ = (ChangesResponse,)
