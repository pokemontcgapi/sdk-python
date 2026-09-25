"""Rigenera le fixture condivise degli SDK.

Le catture reali vengono da rapidapi/esempi (con la data che quel README dichiara);
i casi sintetici seguono il contratto dell'API e i test dell'SDK TypeScript.
Eseguire dalla radice del monorepo: `py -3.12 packages/fixtures/make_fixtures.py`.
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "rapidapi" / "esempi"
OUT = ROOT / "packages" / "fixtures"
KEEP = {"content-type", "etag", "x-request-id", "cache-control"}
API = "https://api.pokemontcgapi.com"
J = {"content-type": "application/json; charset=utf-8"}


def headers_of(name: str) -> dict[str, str]:
    text = (SRC / f"{name}.headers.txt").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key in KEEP:
            out[key] = value.strip()
    return out


def write(name: str, status: int, headers: dict[str, str], body=None, body_text: str | None = None) -> None:
    doc: dict = {"status": status, "headers": headers}
    if body_text is not None:
        doc["body_text"] = body_text
    else:
        doc["body"] = body
    (OUT / f"{name}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def rid(n: int) -> str:
    return f"{n:032x}"


def sample(anchor: str) -> dict:
    spec = (ROOT / "web" / "src" / "lib" / "api-spec.ts").read_text(encoding="utf-8")
    match = re.search(r"response: `(\{\n" + anchor + r".*?\n\})`", spec, re.S)
    assert match, anchor
    return json.loads(match.group(1))


def main() -> None:
    OUT.mkdir(exist_ok=True)

    # Catture reali (README di rapidapi/esempi: 2026-09-05, le pubbliche ricatturate il 2026-09-18).
    for name in ("status", "reference", "prices-sources", "health"):
        write(name, 200, headers_of(name), json.loads((SRC / f"{name}.json").read_text(encoding="utf-8")))
    write(
        "401-missing-key",
        401,
        {**headers_of("401"), "x-error-code": "MISSING_API_KEY"},
        json.loads((SRC / "401-missing-key.json").read_text(encoding="utf-8")),
    )

    # Sintetiche: dai test dell'SDK TypeScript e dal contratto.
    write(
        "batch-missing",
        200,
        {**J, "x-request-id": rid(1), "x-credits-cost": "3", "x-quota-limit": "800", "x-quota-remaining": "797",
         "x-quota-reset": "2026-10-01T00:00:00Z"},
        {
            "data": [{"id": "sv8-100"}],
            "requested": 3,
            "found": 1,
            "missing": [{"id": "sv8-116", "suggested_id": "ssp-116"}, {"id": "inventato-xyz"}],
            "withheld": ["index"],
        },
    )
    subscribe = {
        "action": "subscribe",
        "actor": "account_owner",
        "plans_url": "https://example.test/pricing",
        "checkout_url": "https://example.test/subscribe?plan=developer&interval=monthly",
        "handoff": "The account owner needs to open https://example.test/subscribe?plan=developer&interval=monthly.",
    }
    write(
        "403-plan-required-next-step",
        403,
        {**J, "x-error-code": "PLAN_REQUIRED", "x-request-id": rid(2)},
        {"error": {"code": "PLAN_REQUIRED", "message": "This route requires the Growth plan.", "request_id": rid(2),
                   "details": {"min_plan": "GROWTH",
                               "next_step": {**subscribe, "action": "upgrade", "manage_url": "https://example.test/account"}}}},
    )
    write(
        "403-trial-expired",
        403,
        {**J, "x-error-code": "TRIAL_EXPIRED", "x-request-id": rid(3)},
        {"error": {"code": "TRIAL_EXPIRED", "message": "The trial ended.", "request_id": rid(3),
                   "details": {"next_step": subscribe}}},
    )
    write(
        "429-quota-exceeded-next-step",
        429,
        {**J, "x-error-code": "QUOTA_EXCEEDED", "x-request-id": rid(4), "retry-after": "3600",
         "x-quota-limit": "800", "x-quota-remaining": "0"},
        {"error": {"code": "QUOTA_EXCEEDED", "message": "Exhausted", "request_id": rid(4),
                   "details": {"quota_limit": 800, "retry_after_s": 3600, "next_step": subscribe}}},
    )
    write(
        "429-rate-limited",
        429,
        {**J, "x-error-code": "RATE_LIMITED", "x-request-id": rid(5), "retry-after": "1", "ratelimit-remaining": "0"},
        {"error": {"code": "RATE_LIMITED", "message": "Too many requests. Retry after 1 s.", "request_id": rid(5)}},
    )
    write(
        "404-card-not-found-did-you-mean",
        404,
        {**J, "x-error-code": "CARD_NOT_FOUND", "x-request-id": rid(6)},
        {"error": {"code": "CARD_NOT_FOUND",
                   "message": 'No card found with id "bs-4x". Did you mean "bs-4" (Charizard, Base)?',
                   "request_id": rid(6),
                   "details": {"id": "bs-4x", "did_you_mean": "bs-4", "did_you_mean_name": "Charizard",
                               "did_you_mean_set": "Base"}}},
    )
    write(
        "400-invalid-parameter",
        400,
        {**J, "x-error-code": "INVALID_PARAMETER", "x-request-id": rid(7)},
        {"error": {"code": "INVALID_PARAMETER", "message": 'Unknown parameter "page". Use "cursor".',
                   "request_id": rid(7),
                   "details": {"param": "page", "field": "page", "did_you_mean": "cursor",
                               "valid_params": ["q", "select", "orderBy", "limit", "cursor", "include", "lang", "set"]}}},
    )
    write(
        "401-invalid-key",
        401,
        {**J, "x-error-code": "INVALID_API_KEY", "x-request-id": rid(8)},
        {"error": {"code": "INVALID_API_KEY", "message": "The API key is not valid.", "request_id": rid(8)}},
    )
    write("500-html", 502, {"content-type": "text/html"}, body_text="<html><body><h1>502 Bad Gateway</h1></body></html>")
    write("304", 304, {"etag": 'W/"abc-gzip"'}, body_text="")

    def setrow(code: str, name: str, date: str) -> dict:
        return {
            "id": code, "code": code, "slug": name.lower().replace(" ", "-"), "legacy_id": None, "name": name,
            "series": None, "region": "JP", "release_date": date, "total": 100, "printed_total": None,
            "ptcgo_code": None, "symbol_url": None,
            "logo_url": f"https://media.rarebit.app/sets/{code}/logo-normal.webp",
            "updated_at": "2026-08-26T17:47:39.900Z",
        }

    pages = [
        [setrow("m6", "Storm Emeralda", "2026-07-31"), setrow("m5", "Abyss Eye", "2026-05-22")],
        [setrow("m4", "Ultimate Sun", "2026-03-13"), setrow("m3", "Heat Gale", "2026-01-23")],
        [setrow("m2", "Mega Brave", "2025-12-05")],
    ]
    for i, rows in enumerate(pages, 1):
        body: dict = {"data": rows, "meta": {"limit": 2, "count": len(rows), "total_count": 5, "has_more": i < 3}}
        if i < 3:
            body["links"] = {"next": f"{API}/v1/sets?limit=2&region=JP&cursor=eyJwIjp7{i}fQ.sig{i}"}
        write(
            f"sets-page-{i}", 200,
            {**J, "etag": f'W/"sets-{i}-gzip"', "x-request-id": rid(10 + i), "x-credits-cost": "1",
             "x-quota-remaining": str(790 - i)},
            body,
        )

    card = sample('  "id": "bs-4"')
    write(
        "card-bs-4-with-prices", 200,
        {**J, "etag": 'W/"card-bs-4-gzip"', "x-request-id": rid(20), "x-credits-cost": "3",
         "x-plan-withheld": "graded, non_english_locales", "x-quota-limit": "800", "x-quota-remaining": "780",
         "x-quota-reset": "2026-10-01T00:00:00Z", "ratelimit-remaining": "4",
         "x-trial-expires-at": "2026-10-18T09:00:00Z"},
        card,
    )
    quotes = [q for q in card["prices"] if q["grading"] is None and q["locale"] == "en"]
    write(
        "prices-card-withheld", 200,
        {**J, "x-request-id": rid(21), "x-credits-cost": "2"},
        {"data": {"card_id": "bs-4",
                  "index": {"eur": 556.23, "as_of": "2026-09-02", "sample_n": 16,
                            "by_locale": [{"locale": "en", "printing": None, "eur": 556.23, "as_of": "2026-09-02",
                                           "sample_n": 16}]},
                  "quotes": quotes},
         "meta": {"quotes": len(quotes), "delayed_hours": 24, "withheld": ["graded", "non_english_locales"]}},
    )
    write("vision-ambiguous", 200, {**J, "x-request-id": rid(30), "x-credits-cost": "25"},
          sample('  "data": \\{\n    "decision": "ambiguous"'))
    write(
        "changes-page", 200, {**J, "x-request-id": rid(40), "x-credits-cost": "1"},
        {"data": [{"id": 43, "kind": "CARD", "entity_id": "bs-4", "op": "UPDATE", "version": 7,
                   "changed_at": "2026-09-20T10:00:00Z"}],
         "meta": {"count": 1, "has_more": False, "next_since": 43, "watermark": 43, "oldest_available": 1, "behind": 0}},
    )
    print(sorted(p.name for p in OUT.glob("*.json")))


if __name__ == "__main__":
    main()
