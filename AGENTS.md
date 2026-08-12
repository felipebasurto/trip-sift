# Agent notes for trip-sift

## Module map

- `src/trip_sift/models.py` owns the domain types and JSON mapping.
- `src/trip_sift/parsers.py` owns pure text parsers for flight and hotel card fields.
- `src/trip_sift/browser.py` owns `BrowserSessionConfig` and `ChromiumSession`. Both providers compose a session.
- `src/trip_sift/tfs.py` owns Google Flights `tfs` query encoding for the one-way `FlightQuery` surface.
- `src/trip_sift/google_flights.py` owns Google Flights URL building, consent, card parsing, typed provider failures, and `GoogleFlightsSource`.
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
- Retry only what can succeed on a second try. `NO_RESULTS`, `BROWSER_UNAVAILABLE`, and owned Google markup drift (`GoogleFlightsMarkupError`, still reported as `fetch_failed`) fail immediately.
- Every offer keeps raw text beside parsed fields (`price`/`price_eur`, `duration`/`duration_hours`, `stops`/`stops_count`).
- JSON output only with `--save`. Browser state lives outside the checkout (`TRIP_SIFT_STATE_DIR` or XDG state dir), and is always written to a temp file and renamed.

### Flights

- The flight scrape locale is `hl=en` with `locale="en-US"` for stable rendered evidence and the existing JSON `locale: "en"` contract. Currency comes from `curr=EUR`, independently of `hl`. Card parsing is owned by trip-sift and keeps raw stop/price labels. This does not apply to hotels, which use `lang=es` against our own parser.
- `max_stops` is 0 or 1 per query; filtering follows each query's value. Flights stay one-way; `adults` and `cabin` are query fields (CLI `--adults` / `--cabin`).
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

`pip install -e .` still works, but `uv` is the reproducible path for this tree. Tests are offline. They must not launch Chromium or use the network. CI runs the suite on Python 3.10 through 3.14.

`tests/test_google_flights.py` is the important one for flights. It pins owned TFS encoding and drives synthetic markup through the owned card parser. Test the owned boundary (`RawFlightCard`, typed empty/markup failures), not upstream HTML rewriting.

`tests/test_json_contract.py` and `tests/test_hotel_json_contract.py` pin the flight and hotel JSON shapes. A renamed or dropped key is a breaking change for anything reading `--save` output.

## Trip-planning search strategy

When helping pick destinations (not a single named route/date), follow `.cursor/skills/trip-sift/SKILL.md` → **Destination triage**: shortlist by vibe and rough MAD price band, scrape fixed natural dates first, and only then expand ±1 day on 1–3 finalists. Do not brute-force full date matrices across a long destination list in one run.

## Private-data boundary

This tree is the public export. Do not add scraped caches, CSVs, personal trip scripts or routes, reservation data, browser session files, or paths from a private repository. Heuristic price *bands* in the trip-sift skill are allowed; live scrapes and personal trip JSON are not.
