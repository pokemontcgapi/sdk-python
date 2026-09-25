# pokemontcgapi

[![PyPI](https://img.shields.io/pypi/v/pokemontcgapi)](https://pypi.org/project/pokemontcgapi/) [![license](https://img.shields.io/pypi/l/pokemontcgapi)](./LICENSE) [![CI](https://github.com/pokemontcgapi/sdk-python/actions/workflows/ci.yml/badge.svg)](https://github.com/pokemontcgapi/sdk-python/actions/workflows/ci.yml)

Python client for the Pokémon TCG API at [pokemontcgapi.com](https://pokemontcgapi.com): cards,
sets, illustrators, the reference vocabularies and photo recognition, across three print lines,
international, Japanese and Simplified Chinese, with card names in eight locales, images, and prices
that state their source, basis, grade and sample size. The current counts are live at
[/v1/status](https://api.pokemontcgapi.com/v1/status).

**Every data route has a method**: cards, sets, series, artists, sealed products, the dedicated
price routes (current, batch, history, stats, movers, sources), the `/v1/changes` feed, the reference
vocabularies and photo recognition. Account and billing routes (`/v1/me`, keys, checkout) are not
wrapped: they belong to the dashboard.

**One runtime dependency**, [httpx](https://www.python-httpx.org/), which gives the synchronous
client and the asynchronous one the same request and response objects. Python 3.10 or newer. Fully
typed (`py.typed`), with `TypedDict` response shapes that never hide a field the API added.

Unofficial. Not produced, endorsed, supported by or affiliated with Nintendo, Creatures Inc.,
GAME FREAK inc. or The Pokémon Company International. Pokémon and all related marks are trademarks of
their respective owners.

## Get a key

Generate the Idempotency-Key once per signup and keep it with the request body:

```bash
IDEM=$(uuidgen)
```

```bash
curl -s -X POST "https://api.pokemontcgapi.com/v1/accounts/free" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $IDEM" \
  -d '{"email":"you@example.com"}'
```

Lost the response? Repeat the exact same request (same Idempotency-Key, same body byte for byte, same network: same public IPv4 or the same IPv6 /64) within 24 hours and the response comes back, if stored, secret included; it is the original response, so a key rotated or revoked since then is not revived. A new Idempotency-Key for the same email returns 409 ACCOUNT_EXISTS; the same key with a different body returns 409 IDEMPOTENCY_CONFLICT.

We store only a hash of the key; the signup response is kept for 24 hours so the same request can be replayed. Save `data.key.secret` now.

If replay is unavailable, [sign in](https://pokemontcgapi.com/account) and rotate the key, or use /v1/accounts/recover with an already verified email to get a new secret.

The key comes back in `data.key.secret`. Confirming the address we email raises the trial from
80 to 800 credits, and the trial ends 30 days after signup. Paid plans start at 29 EUR a month:
[pricing](https://pokemontcgapi.com/pricing).

## Install

```bash
pip install pokemontcgapi
```

## Use

```python
from pokemontcgapi import PokemonTcgApi

client = PokemonTcgApi()  # reads PTCG_API_KEY from the environment; or PokemonTcgApi("your-key")

card = client.cards.get("base1-4", include=["prices"])
print(card["id"], card["name"], card.get("index_eur"))
# bs-4 Charizard 523.76   ← the index on 16 September 2026; it moves, yours will differ
```

`base1-4` and `bs-4` both resolve: the id is the printed coordinate — set code, dash, collector
number — and the alternate legacy id resolves on the same route, so a catalogue you already have does
not start with a matching problem.

Responses are the decoded JSON, typed as `TypedDict`: read `card["name"]` as in the documentation,
and `card.get("index_eur")` for the keys that are only present with an `include`. The same client
exists as `AsyncPokemonTcgApi`, with the same methods to `await` and pages to `async for` over:

```python
from pokemontcgapi import AsyncPokemonTcgApi

async with AsyncPokemonTcgApi() as client:
    card = await client.cards.get("base1-4")
    async for set_ in await client.sets.list(region="JP"):
        print(set_["code"], set_["name"])
```

### Pagination that you never have to think about

Every list method returns a `Page`, which is also iterable. Iterating it follows
`links.next` for you. For an initial import of all cards, use the flat card list so pages fill
across set boundaries:

```python
for card in client.cards.search(limit=250, order_by="id"):
    print(card["id"], card["name"], card["set_code"])
```

For Japanese cards, add `q="set.region:JP"`; for Simplified Chinese cards, use
`q="set.region:CN"`. Add `include=["translations"]` when you need localized names;
this keeps the plain catalogue cost. `include=["index"]` and `include=["prices"]`
have different credit costs. `lang` selects a name translation, not a print region.

Use `client.sets.list(region="JP", limit=250)` to browse set metadata and
`client.sets.cards("obf", limit=250)` when you need one particular set. For all cards,
the flat list uses fewer requests than a card loop for every set. The
[quickstart](https://pokemontcgapi.com/docs/quickstart#page-the-whole-catalogue) includes dated
measurements, and the [migration guide](https://pokemontcgapi.com/docs/migrate-from-pokemontcg-io)
explains capturing the change feed watermark before an import and keeping the replica current.

The cursor carries a signature of the sort order, so it must never be reconstructed by hand — the SDK
follows the URL the API returned, which is the failure mode this avoids. `page.next_page()` gives you
one page at a time, `page.pages()` every page, and `.to_list(max=...)` requires an explicit
ceiling, because the catalogue is large enough that an unbounded materialisation is a mistake rather
than a choice.

### One call for a hundred cards

```python
result = client.cards.batch(
    ["sv8-116", "sv8-100", "inventato-xyz"],
    include=["index"],  # index_eur on list and batch rows is opt-in: 1 credit per 50 cards
    select=["id", "name", "index_eur"],
)
data, requested, found = result["data"], result["requested"], result["found"]
missing = result.get("missing", [])
```

`missing` is optional: it is absent when every id resolves. Otherwise each unresolved id appears once
as `{"id": ..., "suggested_id": ...}`, the suggestion only for an existing historical candidate in a
different canonical set. In this example only `sv8-100` is returned; `sv8-116` suggests `ssp-116`,
and `inventato-xyz` has no suggestion. A canonical set prefix binds the lookup to that set;
`base1-4` still resolves to `bs-4` because `base1` is only a historical alias.

`data` contains distinct cards. Repeated ids count towards `requested` and credits, but do not
repeat rows in `data` or `missing`. Two valid aliases for one card can make `found` smaller than
`requested` with no missing ids. Missing entries ignore case and retain the first spelling and
request order after whitespace trimming. `withheld` remains an optional top-level key. More than
100 ids raise `ValueError` before any request: chunk the list.

### Japanese, and the other seven locales

```python
page = client.sets.cards("sv8", lang="ja", limit=1)
print(page.data[0]["name"])  # タマタマ
```

`lang` replaces the `name` field itself and falls back to English where a translation is missing.
Locales, with the rows each one actually has on 16 September 2026: `en` 57,421, `fr` 42,858,
`de` 42,604, `ja` 27,230, `it` 21,644, `es` 21,003, `pt` 13,822, `zh` 3,492. A thin locale answers
mostly in English, because the fallback is per card and not per request.

### Conditional requests are free

```python
client = PokemonTcgApi(cache="etag")
```

Every collection carries an ETag. We compute it strong, from the body; the edge rewrites it weak with
an encoding suffix when it compresses, so what you receive looks like `W/"…-gzip"` and you send back
exactly that. With the cache on, the client stores it and replays a `304` without a body, and a `304`
consumes no quota. A mirror that re-syncs often pays only for what changed.

### A photo instead of an id

**Included from the Growth plan up.** On a trial or a Developer key the call answers `403
PLAN_REQUIRED` with `details.min_plan`, before reading the image and without spending credits.

```python
result = client.vision.identify("photo.jpg", set="sv3")  # a path, bytes or an open binary file
data = result["data"]

# Read `decision` before `id`. Always.
if data["decision"] == "match":
    # One candidate, close, and clear of the next.
    add(data["id"])
elif data["decision"] == "ambiguous":
    # Two printings share this illustration. `data["id"]` is None on purpose.
    show_picker(data["candidates"])
else:
    ask_for_a_better_photo()
```

Reprints and regional twins share their artwork, so artwork alone cannot name a printing — not here
and not anywhere. The endpoint returns candidates with a `distance` (0–512, lower is closer; real
matches land well under 150) and refuses to pick when two are within a few bits of each other.
Passing `set` or `region` when your workflow knows them is what resolves the tie.

It costs 25 credits a call against 1 for a lookup: it is the whole image index answering, not a row
being read. Do not put it in a loop.

### Errors you can branch on

```python
from pokemontcgapi import NotFoundError, QuotaExceededError, RateLimitedError

try:
    client.cards.get("nope-1")
except NotFoundError:
    ...
except RateLimitedError as error:
    ...  # error.retry_after
except QuotaExceededError:
    ...  # retrying will never help
```

Every error carries `code`, `status`, `details` and `request_id` — quote the request id in a support
message, it is the only thing that can be looked up. Retries use exponential backoff with full
jitter on 429, 5xx and network failures, honour `Retry-After`, and never retry a quota exhaustion.
Network failures raise `ApiConnectionError` (and `ApiTimeoutError` after the per-attempt `timeout`),
which are not API errors and carry no code.

Commercial refusals include `details.next_step`, exposed as the typed `error.next_step`. If `error.next_step` exists, show `error.next_step["handoff"]` and its URL to the account owner verbatim and do not retry. `error.action_url` returns the URL for any action: `checkout_url` for subscribe, `manage_url` for upgrade, `verify_url` for email verification, or `contact_url` for sales and support. Show it alongside `error.handoff`. Upgrades point to the account page, where the owner opens the billing portal to change plan. `error.checkout_url` remains a shortcut for subscribe only.

```python
except PokemonTcgApiError as error:
    if error.next_step:
        show_to_user(error.next_step["handoff"])
```

## What this API does not have

Stated up front so you find out here rather than three days into an integration:

- **No Korean cards.** Zero `KR` sets, zero `ko` translations. Both are modelled in the schema and
  carry no data.
- **Card game text is English, and uneven.** `attacks`, `abilities`, `weaknesses`, `resistances`,
  `subtypes`, `retreat_cost`, `rules` and `flavor_text` carry rows since 3 September 2026, on the
  20,725 Western printings. Measured on 16 September 2026 against 57,450 cards: `attacks` on 29.9% of
  the whole catalogue and 82.9% of the Western part, `subtypes` 35.0%, `abilities` 7.0%.
  Japanese and Chinese printings carry none. The types in this package keep them `| None`, so the
  type checker makes you handle the part that is absent.
- **No format legalities.** The card object has no `legalities` field and `include` rejects the
  value with a 400. If you are building a deck checker, this is not the data source you need.

What it does have: the printing itself — set, number, rarity, region, release date, illustrator,
image, marketplace ids, names in eight locales — and prices.

## Prices

```python
card = client.cards.get("base1-4", include=["prices"])
for price in card.get("prices", []):
    print(price["source"], price["basis"], price["amount"], price["currency"], price["as_of"], price["sample_n"])
```

The dedicated price routes have their own methods, and they are the ones to use when prices are the
point of the call:

```python
prices = client.prices.card("base1-4")                                  # index + quotes, 2 credits
many = client.prices.current(["base1-4", "sv3-125"])                    # up to 50 ids, 4 credits per 25
history = client.prices.history("base1-4", bucket="week")               # 5 credits
stats = client.prices.stats("base1-4", window="30d")                    # 2 credits
movers = client.prices.movers(window="7d", direction="gainers")         # Growth and up
box = client.sealed.prices("evolving-skies-booster-box")
```

`history` is bounded by your plan (7 days on the trial, 30 on Developer, everything from Growth): a
wider window raises `UpgradeRequiredError`, whose `permitted_window` says what you may ask for. Its
date bounds are `from_` and `to` (`from` is a reserved word in Python; it is sent as `from`).
`movers` below Growth raises `PlanRequiredError`, and a trial past its 30 days raises
`TrialExpiredError` on every route that costs credits. Both extend `PermissionDeniedError`.

There is no printing filter on `include=["prices"]`: first edition, holofoil and graded rows come back together, so read
`printing`, `condition` and `grading` per row. `basis` separates `GUIDE` (published upstream) from
`DERIVED` (computed by us). `PTCG_INDEX` is a composite index in EUR carrying `sample_n`, and the same
number sits on the card row as `index_eur` wherever we have enough observations to compute one: 51,636
cards of 57,450 on 16 September 2026, so treat it as nullable. On a list or batch it comes with `include=["index"]`
(1 credit per 50 rows), so a list still has a comparable number without a second request per card.

What your plan withholds is named rather than hidden, but it is named in three different places, so
read the one that matches the call you made:

| call | where the exclusions are |
|---|---|
| `client.prices.card(id)` | `["meta"]["withheld"]` |
| `client.cards.get(id, include=["prices"])` | the `X-Plan-Withheld` header: `client.last_response.plan_withheld` |
| `client.cards.batch(ids, …)` | a top-level `withheld` key |

The values are `graded` and `non_english_locales`: a trial key gets both, Developer keeps `graded`,
and from Growth up nothing is withheld, in which case the key is absent rather than an empty list.
Read it before concluding that a card has no graded observations: it may be your plan, not the
catalogue. Prices also carry their own `locale`, and a card read with `include=["prices"]` returns
every locale your plan allows, so the currency does not tell you the language.

## Credits and quota

Every response says what it cost. The SDK keeps the headers of the last one, and hands each one to
`on_response` if you want a running total:

```python
spent = 0

def count(info):
    global spent
    spent += info.credits_cost or 0

client = PokemonTcgApi(on_response=count)

client.cards.search(q="name:charizard", include=["index"])
print(client.last_response.credits_cost, client.last_response.quota_remaining)
```

The trial is 800 credits, once, for 30 days, with at most 400 spent in a day; `trial_expires_at` on
the same object says when it ends.

## The change feed

```python
since = int(store.get("ptcg_since") or 0)
while True:
    page = client.changes(since=since, limit=500)
    for change in page["data"]:
        apply(change)  # kind, entity_id, op, version
    since = page["meta"]["next_since"]
    store.set("ptcg_since", since)
    if not page["meta"]["has_more"]:
        break
```

## Also available

- **TypeScript SDK**: [`@pokemontcgapi/sdk`](https://www.npmjs.com/package/@pokemontcgapi/sdk) — [source](https://github.com/pokemontcgapi/sdk-typescript)
- **Go SDK**: `go get github.com/pokemontcgapi/sdk-go` — [source](https://github.com/pokemontcgapi/sdk-go)
- **MCP server** for agents: [`@pokemontcgapi/mcp`](https://www.npmjs.com/package/@pokemontcgapi/mcp) — [source](https://github.com/pokemontcgapi/mcp-server)
- **Docs**: <https://pokemontcgapi.com/docs>
- **Coverage, measured live**: <https://pokemontcgapi.com/coverage>

## Build from source

```bash
python -m venv .venv && . .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e .[dev]
ruff check src tests && mypy src && pytest
python -m build
```

Python >= 3.10. `pytest` runs the offline suite in `tests/` against the recorded responses in
`tests/fixtures/`; `PTCG_LIVE=1 PTCG_API_KEY=... python scripts/smoke_live.py` runs a short check
against the real API (about four credits). CI enforces lint, types and the suite on every supported
Python, and that the built wheel installs and imports in a clean environment.

This package is developed inside the private monorepo that runs
[pokemontcgapi.com](https://pokemontcgapi.com) and mirrored here on each release,
so a merged pull request travels back by hand rather than by merge button. That
is not a reason to send patches elsewhere — open the issue or the PR here, it is
the address that gets read. The prose of this README is kept identical to the TypeScript SDK's
(synced from its README as of commit 86a725a); only the code differs.

## Licence

MIT. Data served by the API carries per-source redistribution terms — see
<https://pokemontcgapi.com/legal/attribution>.
