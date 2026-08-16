# Phase 7. Offer `legs` and `--max-stops 2`

Back to [overview](overview.md).

## Goal

A 2-stop card keeps every layover. `--max-stops 2` is legal. Schema stays 1.

## Changes

- `src/viajante/models.py` and `src/viajante/google_flights.py`. `RawJourneyLeg` / `RawLayover` / `RawSegment`. `FlightOffer.legs`. Top-level clocks are projections of `legs[0]` in `to_dict()`.
- `src/viajante/flights.py` and `src/viajante/cli.py`. `FlightQuery.max_stops` and `--max-stops` accept 0, 1, 2. 2 means Google's two-or-fewer.
- `tests/test_json_contract.py`. Add `legs` to `OFFER_KEYS`. Assert `schema_version == 1`. A 2-stop offer has `layover_city is None` and the truth in `legs`.
- `tests/test_models.py`. Stop rejecting `max_stops=2`.

`--max-layover` still reads the longest layover until a later change walks `layovers[]`. Say so in the skill.

## Data structures

One priced offer. `legs` length 1, 2, or N. A journey with 2+ stops has `segments[]` and `layovers[]`. No `RoundTripOffer`. No CO2 key.

## Verification

Static. Contract exact-set with `legs`. 2-stop compact fixture. CLI accepts `--max-stops 2` and still rejects 3.

Runtime. One sweep with `--max-stops 2` on a long-haul. Confirm a 2-stop row can appear. Distill the body into a `_live_*` builder. Do not commit the raw dump.
