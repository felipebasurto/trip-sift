# Phase 3. Shopping stop table

Back to [overview](overview.md).

## Goal

Sweep must ask Google for the stop cap the query named. Today every shopping POST writes segment[3] = 2 (`ONE_STOP_OR_FEWER`) even when TFS says nonstop.

## Changes

- `src/viajante/google_flights_rpc.py`. `build_search_constraints` reads a `Trip` (or `FlightQuery` via `.legs`). Map viajante `max_stops` through one table. Never send the same integer on TFS and shopping.
- `src/viajante/google_flights.py` and `src/viajante/google_flights_rpc.py`. Delete `CompactFlightCard`. `parse_shopping_body` returns `RawFlightCard`.
- `tests/test_google_flights.py`. Pin inner JSON for stops 0, 1, and 2. Rewrite `test_inner_payload_keeps_owned_airport_nesting` so `flight[3] == 2` because `max_stops=1`.

Stop map:

| viajante | TFS field 5 | shopping segment[3] |
|---|---|---|
| 0 | 0 | 1 |
| 1 | 1 | 2 |
| 2 | 2 | 3 |

CLI still rejects `--max-stops 2`. Library callers can build a `FlightLeg` with 2 for encode tests only.

## Data structures

One mapping table next to the encoders. `TripKind` dispatch for constraints[2] stays one-way in this phase.

## Verification

Static. `tests.test_google_flights` and `tests.test_models`. Full suite and ruff.

Runtime. Optional maintainer sweep. `viajante flights MAD-BCN:DATE --max-stops 0 --fetch sweep`. Confirm the compact body is nonstop-shaped. One query. Stop on block.
