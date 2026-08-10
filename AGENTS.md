# Agent notes for trip-sift

## Module map

- `src/trip_sift/models.py` owns the domain types and JSON mapping.
- `src/trip_sift/parsers.py` owns pure text parsers for flight and hotel card fields.
- `src/trip_sift/flights.py` owns Google Flights access, retries, delays, filtering, ranking, and browser state.
- `src/trip_sift/hotels.py` owns Booking.com access, retries, filters, evidence checks, ranking, and browser state.
- `src/trip_sift/storage.py` owns the external state directory and atomic JSON writes.
- `src/trip_sift/cli.py` owns argument parsing, terminal output, and optional atomic JSON saves.

## Invariants

- Validate CLI input before starting Chromium.
- One lazy Chromium per process; block images, media, and fonts.
- Fixed delays: 4.5s + up to 1.5s jitter between queries; 3 attempts with 8s exponential backoff + jitter; browser reset after each failed attempt.
- No flags to shorten delays or parallelize requests.
- `max_stops` is 0 or 1 per query; filtering follows each query's value.
- Every offer keeps raw text beside parsed fields (`price`/`price_eur`, `duration`/`duration_hours`, `stops`/`stops_count`).
- Hotel prices are total-stay prices. Keep requested filters, applied Booking chips, and observed card evidence distinct.
- Hotel searches require free cancellation by default. Only an explicit caller or CLI opt-out may include non-refundable stays.
- Do not claim cancellation or property type when card evidence is unknown.
- JSON output only with `--save`. Browser state lives outside the checkout (`TRIP_SIFT_STATE_DIR` or XDG state dir).
- Low-cost carriers get a 70 EUR baggage buffer estimate; callers must verify baggage on Google Flights before booking.
- Callers must verify the final total and cancellation terms on Booking.com before booking.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests are offline. They must not launch Chromium or use the network.

## Private-data boundary

This tree is the public export. Do not add scraped caches, CSVs, personal trip scripts or routes, reservation data, browser session files, or paths from a private repository.
