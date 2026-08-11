---
name: trip-sift
description: Search Google Flights and Booking.com locally for trip planning. Use when the user asks about flight prices, route/date comparisons, hotels, accommodation, or a trip that may need both.
---

# trip-sift

Local flight and hotel search. Prices in EUR. Flights are one adult, one-way, economy; hotel prices are totals for the full stay.

## Commands

```bash
trip-sift flights ORIGIN-DEST:YYYY-MM-DD[,YYYY-MM-DD...] [--max-stops {0,1}] [--top N] [--baggage-buffer EUR] [--save FILE]
trip-sift hotels LOCATION CHECK_IN CHECK_OUT [--adults N] [--rooms N] [--top N] [--min-rating SCORE] [--entire-home] [--allow-non-refundable] [--save FILE]
```

Route grammar: `MAD-BCN:2026-09-01`, or several dates comma-separated on one route. Pass a return leg as a second route, not as a round trip.

For trip-planning requests that specify flights but leave accommodation intent unclear, ask once whether the user also wants a Booking.com hotel search. Do not ask for a flight-only price check, and do not run a hotel search without confirmation.

## Agent rules

- Use the CLI or the installed `search_flights` / `search_hotels` APIs. Do not write a one-off scraper.
- Run provider queries sequentially. Never parallelize Google Flights or Booking.com requests.
- Do not add flags or code that shorten built-in delays or backoff.
- Add `--save` only when a downstream task needs structured JSON.
- After rate-limit failures, stop for 30-60 minutes before another search.

### Flights

- Do not change the flight scrape locale away from English. `fast_flights` only parses English stop labels, and any other locale breaks `--max-stops 0`. Hotels are unaffected and stay on Spanish.
- Ranking adds 70 EUR to known low-cost fares by default. Report the ranked total, not just the fare, and use `--baggage-buffer 0` when the user is travelling with hand luggage only.
- The low-cost list is partial. Never tell the user an airline includes a bag because it is absent from the list.
- Remind the user to verify checked baggage on Google Flights before booking.

### Hotels

- Free cancellation is on by default; use `--allow-non-refundable` only after explicit user consent.
- Treat cancellation and property type as observed evidence. Do not present unknown card evidence as confirmed.
- Remind the user to verify the final total and cancellation terms on Booking.com before booking.

## Error codes

- `no_results` means that search found nothing. Do not retry and do not wait.
- `browser_unavailable` means Chromium is missing. Run `playwright install chromium`.
- `fetch_failed` carries the underlying error text. After repeated ones, stop for 30-60 minutes.

Exit codes: `0` all queries finished, `1` bad input, `2` all queries failed, `3` some failed.

## Browser state

Stored outside the repo at `TRIP_SIFT_STATE_DIR` or XDG state dir. Delete `pw_state_google.json` or `pw_state_booking.json` if that provider's consent flow breaks.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
