# Phase 2. Trip types

Back to [overview](overview.md).

## Goal

Make round-trip and multi-city representable without hanging `return_date` on `FlightQuery`.

## Changes

- `src/viajante/models.py`. Add `FlightLeg`, `RoundTrip`, `MultiCity`, and `Trip = FlightQuery | RoundTrip | MultiCity`. Give `FlightQuery` a `legs` property. Widen model-level `max_stops` on `FlightLeg` to 0..2. Keep `FlightQuery.max_stops` at 0 or 1 so `--save` cannot leak a 2 yet.
- `src/viajante/__init__.py`. Export the new names.
- `tests/test_models.py`. Construction and illegal-state coverage.

`FlightQuery.to_dict()` stays byte-identical. `schema_version` stays 1.

## Data structures

- `FlightLeg(origin, destination, departure_date, max_stops)`
- `RoundTrip(origin, destination, departure_date, return_date, max_stops, adults, cabin)` with mirrored legs. Open jaw is unbuildable.
- `MultiCity(legs, adults, cabin)` with at least two legs and non-decreasing dates.
- Shared reads. `.legs`, `.adults`, `.cabin`.

## Verification

Static. `test_models` plus `test_json_contract` (unchanged keys). Full suite and ruff.

Runtime. None.
