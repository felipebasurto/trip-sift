# Agent notes for trip-sift

## Where to edit

- `tfs` bytes, cabin, or adults in the Google Flights URL: `src/trip_sift/tfs.py`
- Google CSS, consent, empty vs markup: `src/trip_sift/google_flights.py`
- Routes, LCC buffer, or flight ranking: `src/trip_sift/flights.py`
- Booking URL, chips, or DOM cards: `src/trip_sift/booking.py`
- Hotel evidence filters or ranking: `src/trip_sift/hotels.py`
- Delays or retry classification: `src/trip_sift/orchestration.py`
- Chromium session: `src/trip_sift/browser.py`
- `--save` or the state directory: `src/trip_sift/storage.py`
- Flags or printed tables: `src/trip_sift/cli.py`
- Domain types or JSON keys: `src/trip_sift/models.py`
- Raw card text to numbers/enums: `src/trip_sift/parsers.py`

`google_flights.py` owns URL building, consent, card parsing, typed provider failures, and `GoogleFlightsSource`. `booking.py` owns Booking.com URL/chips, consent, card extract, and `BookingHotelsSource`. Session lifecycle lives in `browser.py`. `flights.py` and `hotels.py` are the search loops: pure and offline-testable outside the browser source.

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
- `max_stops` is 0 or 1 per query; filtering follows each query's value. Flights stay one-way; `adults` and `cabin` are query fields (CLI `--adults` / `--cabin`). `ORIGIN-DEST:OUT:BACK` is sugar for two one-way queries (out then return), not a round-trip `tfs`.
- The baggage buffer is an input (`--baggage-buffer`, default 70 EUR), not a constant. A non-zero buffer implies `needs_bag_verify`. Default `--sort ranked` selects `--top` by fare+buffer; `--sort fare` uses fare. The ranked total must be visible when a buffer was added. Callers must verify baggage on Google Flights before booking.
- The low-cost carrier list is partial. Absence from it is not evidence that a fare includes a bag.

### Hotels

- Hotel prices are total-stay prices. Keep requested filters, applied Booking chips, and observed card evidence distinct. Booking search URLs include `order=price`.
- Hotel searches require free cancellation by default. Only an explicit caller or CLI opt-out may include non-refundable stays. If `oos=1` is applied and the card does not mention cancellation, print `filter applied; card silent` — do not store `free` in JSON.
- `--compare-cancellation` runs two sequential Booking scrapes (free cancellation on, then off) and joins stays by title+address. Do not parallelize. If one query fails, print both results and skip the join.
- `lodging_kind` is observed card evidence (`entire_home` / `private_room` / `hotel` / `unknown`). If the card is silent, apartment/apartamento/casa in the title may infer `entire_home`. Do not infer `hotel` from the word hotel in the title. Do not claim cancellation, lodging kind, or unit counts when unknown.
- Callers must verify the final total and cancellation terms on Booking.com before booking.
- Other OTAs are not scrapers in this tree. After Booking, for 1–3 finalists, the trip-sift skill says to use the user's browser harness (Google the property; list official site, aggregators, and other hits as options, without preferring one). Unverified second opinion. Do not invent prices from snippets or write them into `--save` JSON.

## Tests

Prefer the locked checkout workflow:

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run ruff check src tests
```

`pip install -e .` still works, but `uv` is the reproducible path for this tree. Tests are offline. They must not launch Chromium or use the network. CI runs the suite on Python 3.10 through 3.14.

`tests/test_google_flights.py` pins owned TFS encoding and drives synthetic markup through the owned card parser. Test the owned boundary (`RawFlightCard`, typed empty/markup failures), not upstream HTML rewriting. `tests/test_booking.py` is the Booking page seam (`build_applied_filters`, cards, empty vs markup). `tests/test_hotels.py` is eligibility, ranking, and the search loop.

`tests/test_json_contract.py` and `tests/test_hotel_json_contract.py` pin the flight and hotel JSON shapes. A renamed or dropped key is a breaking change for anything reading `--save` output.

## Trip-planning search strategy

When helping pick destinations (not a single named route/date), follow `.cursor/skills/trip-sift/SKILL.md` → **Destination triage**: shortlist by vibe and rough MAD price band, scrape fixed natural dates first, and only then expand ±1 day on 1–3 finalists. Do not brute-force full date matrices across a long destination list in one run.

## Private-data boundary

This tree is the public export. Do not add scraped caches, CSVs, personal trip scripts or routes, reservation data, browser session files, or paths from a private repository. Heuristic price *bands* in the trip-sift skill are allowed; live scrapes and personal trip JSON are not.
