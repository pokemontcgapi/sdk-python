"""A page that is also an iterator.

``for card in client.cards.search(...)`` walks the whole collection following ``links.next``, without
the caller ever seeing a cursor. It is the reason the SDK is worth using instead of raw httpx:
cursor pagination is correct but tedious, and it is where hand-written integrations lose rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any, Generic, TypeVar

from ._http import AsyncHttpClient, HttpClient
from .types import CollectionMeta

T = TypeVar("T")


class Page(Generic[T]):
    def __init__(self, http: HttpClient, body: dict[str, Any]) -> None:
        self._http = http
        self.data: list[T] = list(body.get("data", []))
        self.meta: CollectionMeta = body.get("meta", {})
        links = body.get("links") or {}
        self._next_url: str | None = links.get("next")

    @property
    def has_more(self) -> bool:
        return self._next_url is not None

    def next_page(self) -> Page[T] | None:
        """The next page, or ``None`` after the last one. Requests exactly the URL the API returned."""
        if self._next_url is None:
            return None
        return Page(self._http, self._http.follow(self._next_url))

    def pages(self) -> Iterator[Page[T]]:
        page: Page[T] | None = self
        while page is not None:
            yield page
            page = page.next_page()

    def __iter__(self) -> Iterator[T]:
        for page in self.pages():
            yield from page.data

    def to_list(self, *, max: int) -> list[T]:  # noqa: A002 - mirrors toArray({ max })
        """Materialise into a list. ``max`` is REQUIRED: the catalogue has tens of thousands of cards,
        and an unbounded materialisation is the quickest way to fill a process's memory by mistake."""
        out: list[T] = []
        for item in self:
            out.append(item)
            if len(out) >= max:
                break
        return out


class AsyncPage(Generic[T]):
    def __init__(self, http: AsyncHttpClient, body: dict[str, Any]) -> None:
        self._http = http
        self.data: list[T] = list(body.get("data", []))
        self.meta: CollectionMeta = body.get("meta", {})
        links = body.get("links") or {}
        self._next_url: str | None = links.get("next")

    @property
    def has_more(self) -> bool:
        return self._next_url is not None

    async def next_page(self) -> AsyncPage[T] | None:
        if self._next_url is None:
            return None
        return AsyncPage(self._http, await self._http.follow(self._next_url))

    async def pages(self) -> AsyncIterator[AsyncPage[T]]:
        page: AsyncPage[T] | None = self
        while page is not None:
            yield page
            page = await page.next_page()

    async def __aiter__(self) -> AsyncIterator[T]:
        async for page in self.pages():
            for item in page.data:
                yield item

    async def to_list(self, *, max: int) -> list[T]:  # noqa: A002
        out: list[T] = []
        async for item in self:
            out.append(item)
            if len(out) >= max:
                break
        return out
