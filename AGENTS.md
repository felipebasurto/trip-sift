# Agent notes for trip-sift

## Module map

- `src/trip_sift/models.py` owns the domain types and JSON mapping.
- `src/trip_sift/parsers.py` owns pure text parsers for price, duration, and stops.
- `src/trip_sift/browser.py` owns the only Playwright code, the consent flow, and browser state. It is the sole impure module.
- `src/trip_sift/flights.py` owns route parsing, retries, delays, filtering, ranking, and orchestration. It is pure and offline-testable.
- `src/trip_sift/cli.py` owns argument parsing, terminal output, and optional atomic JSON saves.

## Invariants

- Validate CLI input before starting Chromium. That includes rejecting departure dates in the past.
- Scrape locale is `hl=en` with `locale="en-US"`. This is load-bearing, not cosmetic: `fast_flights` 2.2 compares stop labels against the literal string `"Nonstop"` and strips commas from prices, so any other locale silently breaks `--max-stops 0` and can corrupt prices. Currency comes from `curr=EUR`, independently of `hl`.
- One lazy Chromium per process; block images, media, and fonts.
- Fixed delays: 4.5s + up to 1.5s jitter between queries; 3 attempts with 8s exponential backoff + jitter; browser reset after each failed attempt.
- No flags to shorten delays or parallelize requests. Progress output is allowed and goes to stderr.
- Retry only what can succeed on a second try. `NO_RESULTS` and `BROWSER_UNAVAILABLE` fail immediately.
- `max_stops` is 0 or 1 per query; filtering follows each query's value.
- Every offer keeps raw text beside parsed fields (`price`/`price_eur`, `duration`/`duration_hours`, `stops`/`stops_count`).
- JSON output only with `--save`. Browser state lives outside the checkout (`TRIP_SIFT_STATE_DIR` or XDG state dir), and is always written to a temp file and renamed.
- The baggage buffer is an input (`--baggage-buffer`, default 70 EUR), not a constant. A non-zero buffer implies `needs_bag_verify`. Whatever the ranking adds must be visible in the printed row. Callers must verify baggage on Google Flights before booking.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests are offline. They must not launch Chromium or use the network.

`tests/test_provider_seam.py` is the important one. It drives synthetic markup through the real `fast_flights.parse_response`, because trip-sift never receives Google's text, only what the dependency made of it. Test a parser against the dependency's output, not Google's. Anchoring at the wrong layer is how a broken `--max-stops 0` passed 24 green tests.

## Private-data boundary

This tree is the public export. Do not add scraped caches, CSVs, trip scripts, hotel code, personal routes, reservation data, browser session files, or paths from the private flights repository.
