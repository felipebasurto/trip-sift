---
name: trip-sift
description: Search Google Flights locally for flight prices and route comparisons. Use when the user asks about Google Flights, flight prices, or comparing routes and dates.
---

# trip-sift

Local Google Flights scraper. EUR prices, Spanish locale.

## Commands

```bash
trip-sift flights ORIGIN-DEST:YYYY-MM-DD[,YYYY-MM-DD...] [--max-stops {0,1}] [--top N] [--save FILE]
```

Route grammar: `MAD-BCN:2026-09-01` or several dates comma-separated on one route.

## Agent rules

- Use the CLI or `search_flights` from the installed package. Do not write a one-off scraper.
- Run queries sequentially. Never parallelize Google Flights requests.
- Do not add flags or code that shorten built-in delays or backoff.
- Add `--save` only when a downstream task needs structured JSON.
- After rate-limit failures, stop for 30-60 minutes before another search.
- Remind the user to verify checked baggage on Google Flights before booking. Ranking uses a 70 EUR low-cost baggage estimate.

## Browser state

Stored outside the repo at `TRIP_SIFT_STATE_DIR` or XDG state dir. Delete `pw_state_google.json` if consent breaks.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
