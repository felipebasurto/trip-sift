# Agent notes for trip-sift

## Module map

- `src/trip_sift/models.py` owns the domain types and JSON mapping.
- `src/trip_sift/parsers.py` owns pure text parsers for flight and hotel card fields.
- `src/trip_sift/browser.py` owns `BrowserSessionConfig`, `ChromiumSession`, Google consent, and Google Flights URL building. Both providers compose a session.
- `src/trip_sift/orchestration.py` owns shared pacing, backoff, and failure classification for both providers.
- `src/trip_sift/flights.py` owns route parsing, filtering, ranking, and the flight search loop. It is pure and offline-testable outside the browser source.
- `src/trip_sift/hotels.py` owns Booking.com page interaction, filters, evidence checks, ranking, and the hotel search loop. Session lifecycle lives in `browser.py`.
- `src/trip_sift/storage.py` owns the external state directory and atomic JSON writes. Anything that writes to disk goes through it, except Playwright's own `storage_state`, which writes the file itself and so is renamed into place by `ChromiumSession`.
- `src/trip_sift/cli.py` owns argument parsing, terminal output, and optional atomic JSON saves.

## Invariants

- Validate CLI input before starting Chromium. That includes rejecting departure dates in the past.
- One lazy Chromium per process; block images, media, and fonts.
- Fixed delays: 4.5s + up to 1.5s jitter between queries; 3 attempts with 8s exponential backoff + jitter; browser reset after each failed attempt.
- No flags to shorten delays or parallelize requests. Progress output is allowed and goes to stderr.
- Retry only what can succeed on a second try. `NO_RESULTS` and `BROWSER_UNAVAILABLE` fail immediately.
- Every offer keeps raw text beside parsed fields (`price`/`price_eur`, `duration`/`duration_hours`, `stops`/`stops_count`).
- JSON output only with `--save`. Browser state lives outside the checkout (`TRIP_SIFT_STATE_DIR` or XDG state dir), and is always written to a temp file and renamed.

### Flights

- The flight scrape locale is `hl=en` with `locale="en-US"`. This is load-bearing, not cosmetic: `fast_flights` 2.2 compares stop labels against the literal string `"Nonstop"` and strips commas from prices, so any other locale silently breaks `--max-stops 0` and can corrupt prices. Currency comes from `curr=EUR`, independently of `hl`. This does not apply to hotels, which use `lang=es` against our own parser.
- `max_stops` is 0 or 1 per query; filtering follows each query's value.
- The baggage buffer is an input (`--baggage-buffer`, default 70 EUR), not a constant. A non-zero buffer implies `needs_bag_verify`. Whatever the ranking adds must be visible in the printed row. Callers must verify baggage on Google Flights before booking.
- The low-cost carrier list is partial. Absence from it is not evidence that a fare includes a bag.

### Hotels

- Hotel prices are total-stay prices. Keep requested filters, applied Booking chips, and observed card evidence distinct.
- Hotel searches require free cancellation by default. Only an explicit caller or CLI opt-out may include non-refundable stays.
- Do not claim cancellation or property type when card evidence is unknown.
- Callers must verify the final total and cancellation terms on Booking.com before booking.

## Tests

Prefer the locked checkout workflow:

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run ruff check src tests
```

`pip install -e .` still works, but `uv` is the reproducible path for this tree. Tests are offline. They must not launch Chromium or use the network. CI runs the suite on Python 3.9 through 3.13.

`tests/test_provider_seam.py` is the important one for flights. It drives synthetic markup through the real `fast_flights.parse_response`, because trip-sift never receives Google's text, only what the dependency made of it. Test a parser against the dependency's output, not the site's. Anchoring at the wrong layer is how a broken `--max-stops 0` passed 24 green tests.

`tests/test_json_contract.py` and `tests/test_hotel_json_contract.py` pin the flight and hotel JSON shapes. A renamed or dropped key is a breaking change for anything reading `--save` output.

## Private-data boundary

This tree is the public export. Do not add scraped caches, CSVs, personal trip scripts or routes, reservation data, browser session files, or paths from a private repository.
