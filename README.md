<p align="center">
  <img src="docs/assets/trip-sift-hero.svg" alt="trip-sift local flight and hotel search" width="100%">
</p>

<p align="center">
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-172A33">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-52636B">
  <img alt="Offline tests" src="https://img.shields.io/badge/tests-offline-52636B">
  <img alt="Runs locally" src="https://img.shields.io/badge/runtime-local-172A33">
</p>

`trip-sift` searches one-way economy flights and Booking.com stays through local Chromium. It returns EUR prices with raw and normalized fields for each offer, using Spanish (`es-ES`) locale data. It uses [fast-flights](https://pypi.org/project/fast-flights/) and Playwright on your machine.

This is an unofficial project with no affiliation to Google or Booking.com. Either provider can change markup at any time, which may break parsing. Review the [Google Terms of Service](https://policies.google.com/terms), [Booking.com terms](https://www.booking.com/content/terms.html), and your own obligations before use.

## Install

```bash
python3.9 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/playwright install chromium
```

Requires Python 3.9 or newer. After these steps, the `trip-sift` CLI is available in `.venv/bin/`.

## Search flights

```bash
.venv/bin/trip-sift flights MAD-BCN:2026-09-01
```

Prints up to eight eligible offers in a table. No result file is created.

## Search hotels

```bash
.venv/bin/trip-sift hotels Prague 2026-12-04 2026-12-07
```

Hotel prices are totals for the complete stay. Free cancellation is required by default; use `--allow-non-refundable` only when you explicitly want to include other stays.

## At a glance

| Capability | Behavior |
|---|---|
| Flights | Compares comma-separated dates, with direct or one-stop filtering. |
| Hotels | Searches Booking.com by location and stay dates. |
| Hotel filters | Free cancellation by default; optional minimum rating and entire-home filter. |
| Output | Prints a table and writes JSON only with `--save`. |
| Rate limits | Keeps fixed delays, jitter, and exponential backoff. |
| Privacy | Stores browser state outside the checkout. |

## How it works

<p align="center">
  <img src="docs/assets/how-trip-sift-works.svg" alt="trip-sift data flow from user to typed results" width="100%">
</p>

## Compare dates and save JSON

```bash
.venv/bin/trip-sift flights \
  MAD-BCN:2026-09-01,2026-09-02,2026-09-03 \
  --max-stops 0 \
  --top 5 \
  --save results/search.trip-sift.json
```

Searches each date sequentially, prints a table per date, and writes combined results to `results/search.trip-sift.json`.

Route grammar: `ORIGIN-DESTINATION:DATE[,DATE...]` with three-letter IATA codes and `YYYY-MM-DD` dates.

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

## Baggage

Low-cost carriers include a 70 EUR baggage buffer in ranking. That is an estimate, not a fare quote. Confirm checked-bag rules and price on Google Flights before booking.

## Browser state

Playwright consent cookies persist as `pw_state_google.json` and `pw_state_booking.json` at:

1. `$TRIP_SIFT_STATE_DIR/`
2. `$XDG_STATE_HOME/trip-sift/`
3. `~/.local/state/trip-sift/`

Delete the affected provider file if consent or scraping breaks; it will be recreated on the next run.

## Rate limits

If searches start failing repeatedly, stop for 30-60 minutes before trying again with a small query set.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Every query completed. |
| `1` | The command input is invalid. |
| `2` | Every query failed. |
| `3` | Some queries completed and some failed. |

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Privacy boundary

Browser state, saved results, logs, Playwright artifacts, and local scratch files are excluded by `.gitignore`. Inspect `git status --short` and `git ls-files` before pushing a fork.
