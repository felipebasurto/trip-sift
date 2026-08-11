---
name: trip-sift
description: Search Google Flights locally for flight prices and route comparisons. Use when the user asks about Google Flights, flight prices, or comparing routes and dates.
---

# trip-sift

Local Google Flights scraper. One adult, one-way, economy, EUR prices.

## Commands

```bash
trip-sift flights ORIGIN-DEST:YYYY-MM-DD[,YYYY-MM-DD...] [--max-stops {0,1}] [--top N] [--baggage-buffer EUR] [--save FILE]
```

Route grammar: `MAD-BCN:2026-09-01`, or several dates comma-separated on one route. Pass a return leg as a second route.

## Agent rules

- Use the CLI or `search_flights` from the installed package. Do not write a one-off scraper.
- Run queries sequentially. Never parallelize Google Flights requests.
- Do not add flags or code that shorten built-in delays or backoff.
- Do not change the scrape locale away from English. `fast_flights` only parses English stop labels, and any other locale breaks `--max-stops 0`.
- Add `--save` only when a downstream task needs structured JSON.
- Ranking adds 70 EUR to known low-cost fares by default. Report the ranked total, not just the fare, and use `--baggage-buffer 0` when the user is travelling with hand luggage only.
- The low-cost list is partial. Never tell the user an airline includes a bag because it is absent from the list.
- Remind the user to verify checked baggage on Google Flights before booking.

## Error codes

- `no_results` means that route and date have no flights. Do not retry and do not wait.
- `browser_unavailable` means Chromium is missing. Run `playwright install chromium`.
- `fetch_failed` carries the underlying error text. After repeated ones, stop for 30-60 minutes.

## Browser state

Stored outside the repo at `TRIP_SIFT_STATE_DIR` or XDG state dir. Delete `pw_state_google.json` if consent breaks.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
