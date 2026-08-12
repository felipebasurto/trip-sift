<p align="center">
  <img src="docs/assets/trip-sift-hero.svg" alt="trip-sift local flight and hotel search" width="100%">
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-172A33">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-52636B">
</p>

Compare flight and hotel prices in EUR from your own machine, with no API keys and no account. `trip-sift` drives a local Chromium over Google Flights and Booking.com, and hands back typed offers that keep the scraped text next to every parsed number. Query encoding and card parsing are owned by trip-sift. It is built for scripts and agents that need structured prices, not for browsing.

This is an unofficial project with no affiliation to Google or Booking.com. Either provider can change markup at any time, which may break parsing. Review the [Google Terms of Service](https://policies.google.com/terms), [Booking.com terms](https://www.booking.com/content/terms.html), and your own obligations before use.

## Install

Needs [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer.

```bash
uv sync
uv run playwright install chromium
```

After that, run the CLI with `uv run trip-sift`. The lockfile (`uv.lock`) pins the exact dependency graph used in CI. A plain `pip install -e .` still works if you prefer pip, but then you must install Chromium yourself and you lose the locked transitive versions.

## Search flights

```bash
uv run trip-sift flights MAD-BCN:2026-09-01
```

```text
=== MAD -> BCN  2026-09-01 (max 1 stop(s)) ===
       88 €  1 hr 20 min  direct  09:30 -> 10:50     Iberia
       39 €      109 € ranked  1 hr 25 min  direct  07:15 -> 08:40     Vueling
      131 €  3 hr 55 min  1 stop  14:05 -> 18:00     Air Europa
```

One adult, one-way, economy. Up to eight offers per query, ordered by ranked total (fare plus baggage buffer). Vueling is cheaper on fare, but the buffer puts it behind Iberia at 109 € ranked. Pass `--sort fare` to order by cabin fare, or `--baggage-buffer 0` to rank on fare alone. `MAD-OPO:2026-10-09:2026-10-12` expands to outbound plus return as two one-way queries. Nothing is written to disk unless you ask for it.

## Search hotels

```bash
uv run trip-sift hotels Prague 2026-12-04 2026-12-07 --min-rating 8.5
```

```text
=== Prague  2026-12-04 -> 2026-12-07 (3 nights, 2 adult(s), 1 room(s)) ===
  Filters: Free cancellation required; Minimum rating 8.5
  Booking chips: oos=1
  246 € total stay  rating 8.9  Hotel Golden Key  Praga 1
    Cancellation: free
    Lodging: hotel
  291 € total stay  rating 9.2  Vinohrady Apartment  Praga 2
    Cancellation: free
    Lodging: entire home
    2 bedrooms, 1 bathroom, 3 beds
  Raw cards: 40; eligible: 12; shown: 2
```

Prices are totals for the whole stay, not per night. Free cancellation is required by default; use `--allow-non-refundable` only when you explicitly want other stays. `--compare-cancellation` runs two sequential searches (with the free-cancellation chip, then without) and prints a joined price table; do not combine it with `--allow-non-refundable`.

The CLI does not scrape Kayak, Lastminute, or official hotel sites. For a second opinion on 1–3 finalists, an agent can use the user's browser to Google the property and list whatever sources show up (official site, aggregators, others) without ranking them; those quotes stay outside `--save` JSON.

The output separates what you asked for (`Filters`), what Booking was actually told (`Booking chips`), and what each card actually showed (`Cancellation`, `Lodging`, beds), because those can disagree. Note that `--min-rating 8.5` appears under `Filters` but produces no chip: only free cancellation and `--entire-home` are pushed to Booking, and the rating is applied locally to the scraped cards.

## How it works

<p align="center">
  <img src="docs/assets/how-trip-sift-works.svg" alt="trip-sift data flow from user to typed results" width="100%">
</p>

You or an agent pass a route and dates. The CLI validates the input before any browser starts, then paces the queries deliberately. A single local Chromium session does the scraping with images, media, and fonts blocked. Offers come back ranked, and consent cookies stay in your state directory rather than in this checkout.

## Compare dates and save JSON

```bash
uv run trip-sift flights \
  MAD-BCN:2026-09-01,2026-09-02,2026-09-03 \
  --max-stops 0 \
  --top 5 \
  --save results/search.trip-sift.json
```

Each date is searched sequentially and printed as its own block. Progress goes to stderr so you can pipe the table on its own. Ten dates spend 40 to 54 seconds asleep between queries before any page even loads, which is deliberate.

## CLI reference

Flight route grammar is `ORIGIN-DESTINATION:DATE[,DATE...]` with three-letter IATA codes and `YYYY-MM-DD` dates, or `ORIGIN-DESTINATION:OUT:BACK` for outbound plus return as two one-way searches. Codes are case-insensitive. You can still pass a return leg as a second route.

| `flights` flag | Default | Behavior |
|---|---|---|
| `--max-stops` | `1` | `0` for direct flights only, `1` to allow one stop. |
| `--adults` | `1` | Number of adults on the search. |
| `--cabin` | `economy` | `economy`, `premium-economy`, `business`, or `first`. |
| `--top` | `8` | Offers kept per query after ranking and deduplication. |
| `--baggage-buffer` | `70` | EUR added to low-cost fares when ranking. `0` ranks on fare alone. |
| `--sort` | `ranked` | `ranked` uses fare+buffer for `--top`; `fare` uses cabin fare. |
| `--save FILE` | off | Write the JSON report atomically. |

| `hotels` flag | Default | Behavior |
|---|---|---|
| `--adults` / `--rooms` | `2` / `1` | Occupancy for the stay. |
| `--top` | `8` | Stays shown after filtering and ranking. |
| `--min-rating` | off | Minimum Booking review score, 0 to 10. |
| `--entire-home` | off | Require entire homes. Cards with unknown property type may remain. |
| `--allow-non-refundable` | off | Include stays without free cancellation. |
| `--compare-cancellation` | off | Two sequential searches (free cancellation on, then off) and a joined price table. |
| `--save FILE` | off | Write the JSON report atomically. |

| Exit code | Meaning |
|---|---|
| `0` | Every query finished without a fetch failure, including queries that found nothing eligible. |
| `1` | The command input is invalid. |
| `2` | Every query failed. |
| `3` | Some queries finished and some failed. |

## JSON output

`--save` writes one report per run. Every offer carries the scraped text beside its parsed value, so a better parser can be run over old results.

```json
{
  "schema_version": 1,
  "searched_at": "2026-08-11T10:32:00Z",
  "currency": "EUR",
  "locale": "en",
  "queries": [
    {
      "status": "ok",
      "query": {
        "origin": "MAD",
        "destination": "BCN",
        "departure_date": "2026-09-01",
        "max_stops": 1,
        "adults": 1,
        "cabin": "economy"
      },
      "raw_count": 24,
      "eligible_count": 1,
      "offers": [
        {
          "airline": "Vueling",
          "departure": "07:15",
          "arrival": "08:40",
          "price": "€39",
          "price_eur": 39.0,
          "duration": "1 hr 25 min",
          "duration_hours": 1.42,
          "stops": "Nonstop",
          "stops_count": 0,
          "baggage_buffer_eur": 70,
          "needs_bag_verify": true
        }
      ]
    }
  ]
}
```

A failed query replaces `raw_count`, `eligible_count`, and `offers` with `"error": {"code": ..., "message": ...}`. Codes are `no_results`, `browser_unavailable`, and `fetch_failed`. Hotel reports follow the same envelope, with `provider`, `price_basis: "total_stay"`, and an `applied` block recording the Booking filters that were actually used.

## Python API

```python
from datetime import date

from trip_sift import FlightQuery, search_flights

report = search_flights(
    [
        FlightQuery(
            origin="MAD",
            destination="BCN",
            departure_date=date(2026, 9, 1),
            max_stops=1,
        )
    ],
    top=5,
)

for result in report.queries:
    if result.status == "ok":
        for offer in result.offers:
            print(offer.price_eur, offer.airline)
```

Hotels use the same report pattern:

```python
from datetime import date

from trip_sift import HotelQuery, search_hotels

report = search_hotels(
    [
        HotelQuery(
            location="Prague",
            check_in=date(2026, 12, 4),
            check_out=date(2026, 12, 7),
        )
    ],
    top=5,
)

for result in report.queries:
    if result.status == "ok":
        for offer in result.offers:
            print(offer.total_price_eur, offer.title)
```

Both run a live search with the same Chromium and the same pacing as the CLI.

## Limitations

- Flights are one-way only, and `--max-stops` is `0` or `1`. Adults and cabin are configurable (`--adults`, `--cabin`). There is no flag to shorten the delays or to parallelize requests.
- The flight scrape runs in English (`hl=en`) for stable rendered evidence; prices are still EUR. Hotels scrape in Spanish against our own parser.
- Flight ranking adds a flat estimate for known low-cost carriers, not a fare quote. The low-cost list is partial, so an airline missing from it is not evidence of a bag-inclusive fare. Confirm the checked bag on Google Flights before booking.
- Hotel cancellation, lodging kind, and bed counts are reported as observed evidence, and `unknown` means the card did not say. `--entire-home` therefore cannot remove every non-home. Confirm the final total and the cancellation terms on Booking.com before booking.
- Finding nothing eligible still exits `0` and prints `(no eligible offers)` or `(no eligible stays)`. Widen the filters or check the route.
- If Chromium is missing you get `browser_unavailable`. Run `uv run playwright install chromium`.
- After repeated failures, stop for 30 to 60 minutes and retry a small query set.

## Browser state

Playwright consent cookies persist as `pw_state_google.json` and `pw_state_booking.json` at the first of these that applies:

1. `$TRIP_SIFT_STATE_DIR/`
2. `$XDG_STATE_HOME/trip-sift/`
3. `~/.local/state/trip-sift/`

Delete the affected provider file if consent or scraping breaks. It is recreated on the next run.

## Tests

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check src tests
```

Fully offline. They never launch Chromium and never touch the network. `tests/test_google_flights.py` pins query encoding and drives synthetic markup through the owned Google Flights card parser. CI runs the suite on Python 3.10 through 3.14.

## Privacy boundary

This tree is the public export of a private trip-planning repo. Do not commit scrapes, personal routes, or browser session files. Saved results (`results/`, `*.trip-sift.json`), logs, and Playwright artifacts are gitignored, and consent cookies live outside the checkout entirely. Before pushing a fork, check `git status --short` and `git ls-files`.
