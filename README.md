<p align="center">
  <img src="docs/assets/trip-sift-hero.svg" alt="trip-sift local flight search" width="100%">
</p>

<p align="center">
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-172A33">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-52636B">
</p>

Compare one-way flight prices in EUR from your own machine, with no API keys and no account. `trip-sift` drives a local Chromium through [fast-flights](https://pypi.org/project/fast-flights/) and Playwright, and hands back typed offers that keep the scraped text next to every parsed number. It is built for scripts and agents that need structured fares, not for browsing.

This is an unofficial project with no affiliation to Google. Google can change markup at any time, which may break parsing. Review the [Google Terms of Service](https://policies.google.com/terms) and your own obligations before use.

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/playwright install chromium
```

Requires Python 3.9 or newer. The `pip` upgrade is not optional on 3.9, whose bundled pip 21.2.4 cannot install a `pyproject.toml`-only project in editable mode. After these steps the CLI is at `.venv/bin/trip-sift`.

## Quick start

```bash
.venv/bin/trip-sift flights MAD-BCN:2026-09-01
```

```text
=== MAD -> BCN  2026-09-01 (max 1 stop(s)) ===
       39 €  1 hr 25 min  direct  07:15 -> 08:40     Vueling  (+70 bag = 109 € ranked)
       88 €  1 hr 20 min  direct  09:30 -> 10:50     Iberia
      131 €  3 hr 55 min  1 stop  14:05 -> 18:00     Air Europa
```

Up to eight offers per query, ordered by the number in the ranking note. Vueling is the cheapest fare here but ranks above Iberia once an estimated checked bag is priced in. Pass `--baggage-buffer 0` to rank on fare alone. Nothing is written to disk unless you ask for it.

## How it works

<p align="center">
  <img src="docs/assets/how-trip-sift-works.svg" alt="trip-sift data flow from user to typed results" width="100%">
</p>

You or an agent pass a route and a date. The CLI validates the input before any browser starts, then paces the queries deliberately. A single local Chromium session scrapes Google Flights with images, media, and fonts blocked. Offers come back ranked, and consent cookies stay in your state directory rather than in this checkout.

## Compare dates and save JSON

```bash
.venv/bin/trip-sift flights \
  MAD-BCN:2026-09-01,2026-09-02,2026-09-03 \
  --max-stops 0 \
  --top 5 \
  --save results/search.trip-sift.json
```

Each date is searched sequentially and printed as its own block. Progress goes to stderr so you can pipe the table on its own. Ten dates spend 40 to 54 seconds asleep between queries before any page even loads, which is deliberate.

## CLI reference

Route grammar is `ORIGIN-DESTINATION:DATE[,DATE...]` with three-letter IATA codes and `YYYY-MM-DD` dates. Codes are case-insensitive. Pass a return leg as a second route, not as a round trip.

| Flag | Default | Behavior |
|---|---|---|
| `--max-stops` | `1` | `0` for direct flights only, `1` to allow one stop. |
| `--top` | `8` | Offers kept per query after ranking and deduplication. |
| `--baggage-buffer` | `70` | EUR added to low-cost fares when ranking. `0` ranks on fare alone. |
| `--save FILE` | off | Write the JSON report atomically. |

| Exit code | Meaning |
|---|---|
| `0` | Every query finished without a fetch failure, including queries that found zero eligible offers. |
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
        "max_stops": 1
      },
      "raw_count": 24,
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

A failed query replaces `raw_count` and `offers` with `"error": {"code": ..., "message": ...}`. Codes are `no_results`, `browser_unavailable`, and `fetch_failed`.

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

This runs a live search with the same Chromium and the same pacing as the CLI.

## Limitations

- One adult, one-way, economy only. Currency is EUR and the scrape locale is English, because `fast-flights` only parses English stop labels.
- `--max-stops` is `0` or `1`. There is no flag to shorten the delays or to parallelize requests.
- Ranking adds a flat estimate for known low-cost carriers, not a fare quote. Confirm the checked bag on Google Flights before booking.
- The low-cost carrier list is partial. An airline missing from it is not evidence of a bag-inclusive fare.
- Zero eligible offers still exits `0` and prints `(no eligible offers)`. Widen `--max-stops` or check the route.
- If Chromium is missing you get `browser_unavailable`. Run `.venv/bin/playwright install chromium`.
- After repeated failures, stop for 30 to 60 minutes and retry a small query set.

## Browser state

Playwright consent cookies persist at the first of these that applies:

1. `$TRIP_SIFT_STATE_DIR/pw_state_google.json`
2. `$XDG_STATE_HOME/trip-sift/pw_state_google.json`
3. `~/.local/state/trip-sift/pw_state_google.json`

Delete that file if consent or scraping breaks. It is recreated on the next run.

## Tests

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests
```

Fully offline. They never launch Chromium and never touch the network. `tests/test_provider_seam.py` drives synthetic markup through the real `fast-flights` parser, because that dependency rewrites text before `trip-sift` ever sees it. CI runs the suite on Python 3.9 through 3.13.

## Privacy boundary

This tree is the public export of a private trip-planning repo. Do not commit scrapes, personal routes, or browser session files. Saved results (`results/`, `*.trip-sift.json`), logs, and Playwright artifacts are gitignored, and consent cookies live outside the checkout entirely. Before pushing a fork, check `git status --short` and `git ls-files`.
