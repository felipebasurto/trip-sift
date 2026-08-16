# Phase 5. Round-trip encode

Back to [overview](overview.md).

## Goal

Own the bytes Google sees for a package. Do not search yet.

## Changes

Split across two commits if the file cap bites. Same PR is fine if both stay green.

- `src/viajante/google_flights_rpc.py`. `constraints[13]` becomes the full segment list. `constraints[2]` follows trip kind. Return classifier 1 on round-trip leg 1. Optional `selected_flight` at segment[8] with one pinned fixture.
- `src/viajante/tfs.py`. Repeat field 3 once per leg. Set field 19 from the trip table. Keep the four current goldens. Add a derived one-way two-stop golden (`0x28 0x02`).
- `tests/test_google_flights.py`. Offline list fixtures. Do not import a third-party shopping client. Cross-check slot numbers against a captured Google search URL and the owned shopping fixture.

Trip type map:

| kind | TFS field 19 | shopping constraints[2] | segment[14] |
|---|---|---|---|
| one-way | 2 | 2 | 3 |
| round-trip | 1 | 1 | 3 then 1 |
| multi-city | capture first | 3 | 3 on every leg |

Gate. Do not merge hypothesized multi-city TFS field 19 until a captured Google search URL confirms it. A booking-page `tfs` is a different token. Do not use it.

## Data structures

Encoders take `Trip`. One-way wraps `FlightQuery`. No second itinerary type.

## Verification

Static. Encode goldens and the existing TFS four. Full suite and ruff.

Runtime. One offline capture on a maintainer machine, written to `/tmp`, distilled into a `_live_*` builder. Not committed raw. `interrogate` this phase before review.
