"""The shapes the API returns, as ``TypedDict``.

Written by hand from the TypeScript SDK's ``types.ts``, field by field and in the same order, and
not generated: the fields carry a comment about what they REALLY contain. Game text is present only
on part of the catalogue, and a type promising ``attacks: list[Attack]`` makes you write code that
never runs. ``| None`` is not enough to say it; the comment above the field is.

Bodies are returned as the decoded JSON, unchanged: a ``TypedDict`` gives the editor the keys at zero
runtime cost and never hides a field the API added since this file was written.
"""

from __future__ import annotations

import sys
from typing import Any, Literal, TypedDict

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:  # pragma: no cover
    from typing_extensions import NotRequired

# The eight locales with rows in the table, measured on 2026-09-16: en 57,421, fr 42,858, de 42,604,
# ja 27,230, it 21,644, es 21,003, pt 13,822, zh 3,492. The API accepts nine, but ``ko`` has zero rows
# and a type does not promise what does not exist.
Locale = Literal["en", "fr", "de", "ja", "it", "es", "pt", "zh"]

#: Print region. ``KR`` exists in the server schema but matches no set: filtering on it returns an
#: empty page, not an error.
PrintRegion = Literal["WEST", "JP", "CN", "KR"]

PriceSource = Literal["TCGPLAYER", "PRICECHARTING", "CARDMARKET", "CARDTRADER", "EBAY", "PTCG_INDEX", "COMMUNITY"]

#: ``DERIVED`` is computed by us; ``GUIDE`` is a value published upstream.
PriceBasis = Literal["GUIDE", "DERIVED", "SOLD", "ASKING"]

CardInclude = Literal["index", "prices", "translations", "images", "set", "artist"]


class Grading(TypedDict):
    company: str
    score: str


class Price(TypedDict):
    source: str
    variant: str
    basis: str
    #: The number, with its currency in the sibling field.
    amount: float
    currency: str
    locale: str | None
    condition: str | None
    printing: str | None
    grading: Grading | None
    #: Day the observation refers to. Never today: every source is published with a delay.
    as_of: str
    #: How many observations sit behind it, where the source says.
    sample_n: int | None
    #: Attribution string to show next to the number.
    provenance: str


class CardImage(TypedDict):
    face: str
    size: str
    locale: str | None
    url: str
    image_source: str | None
    #: Modelled but not populated: use the 5:7 ratio to reserve the space.
    width: int | None
    height: int | None


class Translation(TypedDict):
    locale: str
    name: str


class CardSet(TypedDict):
    id: str
    code: str
    slug: str
    legacy_id: str | None
    name: str
    series: str | None
    region: str
    release_date: str | None
    total: int | None
    printed_total: int | None
    ptcgo_code: str | None
    symbol_url: str | None
    logo_url: str | None
    updated_at: NotRequired[str]


class ArtistLinks(TypedDict, total=False):
    cards: str


class Artist(TypedDict):
    slug: str
    name: str
    card_count: int
    #: Only on ``artists.get()``: the ready-made search of the artist's cards.
    links: NotRequired[ArtistLinks]


class Card(TypedDict):
    id: str
    #: Alternate identifier in the same shape. Resolves on the same route.
    legacy_id: str | None
    name: str
    number: str
    number_sort: int | None
    supertype: str | None
    hp: int | None
    level: str | None
    evolves_from: str | None
    evolves_to: list[str] | None
    rarity: str | None
    regulation_mark: str | None

    set_code: str
    set_name: str
    set_total: int | None
    ptcgo_code: str | None
    series: str | None
    release_date: str | None
    print_region: str

    artist_name: str | None
    artist_slug: str | None

    #: Composite index in euro. Always on the single card; on list or batch rows ONLY with
    #: ``include=["index"]`` (1 credit per 50 cards). Without it the key is absent and
    #: ``meta.withheld`` contains ``"index"``.
    index_eur: NotRequired[float | None]
    last_price_at: NotRequired[str | None]

    tcgplayer_id: int | None
    cardmarket_id: int | None
    #: The Japanese printing of the same card, where the pairing is known.
    jp_twin_id: str | None

    row_version: int
    created_at: str
    updated_at: str

    # Relations, only with include=
    prices: NotRequired[list[Price]]
    images: NotRequired[list[CardImage]]
    translations: NotRequired[list[Translation]]
    set: NotRequired[CardSet]
    artist: NotRequired[Artist]

    # Game text: present in English on Western printings and unevenly (attacks on about a third of
    # the catalogue), none on Japanese and Chinese printings. ``None`` means "data not held", never
    # "the card has no attacks".
    attacks: list[Any] | None
    abilities: list[Any] | None
    weaknesses: list[Any] | None
    resistances: list[Any] | None
    subtypes: list[str]
    retreat_cost: list[str]
    converted_retreat_cost: int | None
    rules: list[str]
    flavor_text: str | None
    types: list[str]
    national_pokedex_numbers: list[int]


class StatusSource(TypedDict):
    source: str
    last_success_at: str | None
    age_hours: float | None
    #: ``fresh``, ``stale``, ``critical`` or ``never_run``.
    state: str


class StatusCatalog(TypedDict):
    sets: int
    cards: int
    sealed: int
    artists: int


class StatusUpstream(TypedDict):
    contract_ok: bool
    error: str | None


class CatalogStatus(TypedDict):
    status: str
    catalog: StatusCatalog
    sources: list[StatusSource]
    upstream: StatusUpstream
    version: str


class Health(TypedDict):
    status: str
    db: bool
    uptime_s: int
    version: str


# ── envelope ────────────────────────────────────────────────────────────────


class SearchHint(TypedDict, total=False):
    """One of ``NUMBER_NORMALIZED``, ``TRY_POKEDEX_NUMBER``, ``SET_ALIAS_MATCHED``, ``SET_WORDS_MATCHED``,
    ``SET_ALIAS_ELSEWHERE``; the other keys depend on ``code``."""

    code: str
    message: str
    received: str
    matched: str
    suggested_q: str
    #: Capped at 50; read ``at_least`` when the actual count is higher.
    matches: int
    at_least: bool
    set_code: str
    set_name: str


class CollectionMeta(TypedDict, total=False):
    limit: int
    count: int
    total_count: int
    has_more: bool
    #: What the response left out: ``"index"`` when ``select`` names ``index_eur`` without
    #: ``include=["index"]``, or the price rows the plan does not cover with ``include=["prices"]``.
    withheld: list[str]
    #: Grace-period parameter warnings; distinct from search suggestions.
    warnings: list[str]
    #: Present when a search by number or set name has a useful suggestion.
    hints: list[SearchHint]


class Links(TypedDict, total=False):
    next: str


class MissingCard(TypedDict):
    id: str
    #: Present only for an existing historical alias in a different canonical set.
    suggested_id: NotRequired[str]


class CardBatchResult(TypedDict):
    data: list[Card]
    requested: int
    found: int
    #: Absent when every requested id resolves; repeated ids appear once.
    missing: NotRequired[list[MissingCard]]
    withheld: NotRequired[list[str]]


# ── series and sealed ───────────────────────────────────────────────────────


class Series(TypedDict):
    id: str
    slug: str
    name: str
    set_count: int


class SealedProduct(TypedDict):
    id: str
    sku: str
    slug: str
    name: str
    #: ``BOOSTER_BOX`` and the like.
    kind: str
    set_code: str | None
    set_name: str | None
    image_url: str | None
    release_date: str | None
    pack_count: int | None
    languages: list[str]
    #: On lists only with ``include=["index"]``; on the single product always.
    index_eur: NotRequired[float | None]
    last_price_at: NotRequired[str | None]
    created_at: str
    updated_at: str


# ── prices ──────────────────────────────────────────────────────────────────


class PriceIndexByLocale(TypedDict):
    locale: str
    printing: str | None
    eur: float
    as_of: str
    sample_n: int | None


class PriceIndex(TypedDict):
    eur: float
    as_of: str
    sample_n: int | None
    #: One series per (locale, printing): the head index is the English one.
    by_locale: list[PriceIndexByLocale]


class CardPrices(TypedDict):
    card_id: str
    index: PriceIndex | None
    quotes: list[Price]


class SealedPrices(TypedDict):
    sealed_id: str
    index: PriceIndex | None
    quotes: list[Price]


class PricesMeta(TypedDict):
    quotes: int
    delayed_hours: int
    #: The rows the plan does not cover: ``graded``, ``non_english_locales``. Absent if nothing is withheld.
    withheld: NotRequired[list[str]]


class CardPricesResponse(TypedDict):
    data: CardPrices
    meta: PricesMeta


class SealedPricesResponse(TypedDict):
    data: SealedPrices
    meta: PricesMeta


class CardPricesBatchResult(TypedDict):
    data: list[CardPrices]
    requested: int
    found: int
    missing: NotRequired[list[MissingCard]]
    withheld: NotRequired[list[str]]


class HistoryPoint(TypedDict):
    date: str
    source: str
    variant: str
    locale: str | None
    printing: str | None
    amount: float
    currency: str
    sample_n: int | None


class HistoryMeta(TypedDict):
    card_id: str
    from_: NotRequired[str]  # see ``HistoryResponse``: the JSON key is ``from``
    to: str
    bucket: str
    count: int
    truncated: bool
    capped: bool
    #: ``None`` when the plan gives the whole history.
    plan_window_days: int | None


class HistoryResponse(TypedDict):
    """``meta`` also carries ``from`` (a ``YYYY-MM-DD`` string), which cannot be a TypedDict key name in
    Python source: read it as ``response["meta"]["from"]``."""

    data: list[HistoryPoint]
    meta: HistoryMeta


class PriceStats(TypedDict):
    window: str
    to: str
    low: float | None
    high: float | None
    median: float | None
    first: float | None
    last: float | None
    change_pct: float | None
    sample_n: int
    currency: str


class StatsMeta(TypedDict):
    card_id: str
    source: str


class StatsResponse(TypedDict):
    """``data`` also carries ``from``: read it as ``response["data"]["from"]``."""

    data: PriceStats
    meta: StatsMeta


class Mover(TypedDict):
    card_id: str
    name: str
    set_code: str
    to: float
    change_pct: float
    currency: str


class MoversMeta(TypedDict):
    window: str
    to: str
    direction: str
    min_value: float
    count: int
    source: str


class MoversResponse(TypedDict):
    """Rows and ``meta`` also carry ``from``: read it as ``row["from"]``."""

    data: list[Mover]
    meta: MoversMeta


class PriceSourceInfo(TypedDict):
    source: str
    label: str
    min_delay_hours: int
    is_own: bool


# ── incremental feed ────────────────────────────────────────────────────────


class Change(TypedDict):
    id: int
    #: ``SET``, ``CARD``, ...: the real list is ``change_kinds`` in ``/v1/reference``.
    kind: str
    entity_id: str
    op: str
    version: int
    changed_at: str


class ChangesMeta(TypedDict):
    count: int
    has_more: bool
    #: Save it and send it back as ``since``: the feed has no other state.
    next_since: int
    watermark: int
    oldest_available: int
    behind: int


class ChangesResponse(TypedDict):
    data: list[Change]
    meta: ChangesMeta
    links: NotRequired[Links]


# ── recognition from a photo ────────────────────────────────────────────────

#: ``ambiguous`` is not a failure: it is the normal case on reprints, where two printings share the
#: illustration and are not distinguishable from the image alone. A client that treats ``ambiguous``
#: as ``no_match`` throws away the right answer; one that treats it as ``match`` delivers the wrong
#: printing.
VisionDecision = Literal["match", "ambiguous", "no_match"]


class VisionCandidateSet(TypedDict):
    code: str
    name: str
    print_region: str


class VisionCandidate(TypedDict):
    id: str
    name: str
    number: str
    set: VisionCandidateSet
    rarity: str | None
    image_url: str | None
    #: Hamming distance, 0..512. Real matches sit below 150 even on a noisy photo; nothing above 170
    #: is returned.
    distance: int
    #: The same information rescaled to 0..1. Convenient, not more informative.
    confidence: float


class VisionResult(TypedDict):
    decision: str
    decision_reason: str
    #: Set ONLY when ``decision`` is ``match``. Otherwise ``None``.
    id: str | None
    candidates: list[VisionCandidate]


class VisionOcr(TypedDict, total=False):
    applied: bool
    eligible: int
    level: int
    number: int
    ms: int
    crop_ms: int
    reason: str
    set_code: str
    set_reason: str


class VisionMeta(TypedDict):
    count: int
    cards_indexed: int
    index_built_at: str
    index_loaded_at: str
    signature_version: int
    #: How many card-like quadrilaterals were isolated in the photo. Zero with a ``no_match`` means
    #: "the card was not found in the image", not "it is not in the catalogue".
    regions_detected: int
    hypotheses_tried: int
    elapsed_ms: int
    ocr: NotRequired[VisionOcr]


class VisionResponse(TypedDict):
    data: VisionResult
    meta: VisionMeta
