# Phase 4. `--trip` parse and reject

Back to [overview](overview.md).

## Goal

Humans can type a real package. The CLI refuses to pretend it already works.

## Changes

- `src/viajante/flights.py`. `parse_route_specs` (or a sibling `parse_flight_plan`) returns a typed plan. Default `--trip one-way` keeps today's sugar.
- `src/viajante/cli.py`. Add `--trip {one-way,rt,multi}`. Validate before any source starts. `--trip rt` and `--trip multi` exit 1 with a stable `error:` line until phase 6.
- `tests/test_cli.py` and `tests/test_flights.py`. Reject matrix. Existing sugar tests stay green.

Grammar:

- `--trip one-way` (default). Today's tokens. `OUT:BACK` is still two one-ways.
- `--trip rt`. Exactly one `ORIGIN-DEST:OUT:BACK`. No comma list. No extra tokens.
- `--trip multi`. Two to six `ORIGIN-DEST:DATE` tokens. Open jaw allowed. No `OUT:BACK`. No comma lists.

`--fetch auto` counts trip units, not expanded legs.

## Data structures

A plan object. `one-way` is `tuple[FlightQuery, ...]`. `rt` is one `RoundTrip`. `multi` is one `MultiCity`.

## Verification

Static. The reject matrix in `test_cli.py`. Help still lists `MAD-OPO:2026-10-09:2026-10-12` as two one-ways.

Runtime via `control-cli` (invoke, no PTY):

```bash
uv run viajante flights --trip rt MAD-BCN:2026-09-01
uv run viajante flights --trip multi MAD-BCN:2026-09-01
uv run viajante flights --trip rt MAD-OPO:2026-10-09:2026-10-12
```

Expect exit 1, no Chromium, stderr starts with `error:`.
