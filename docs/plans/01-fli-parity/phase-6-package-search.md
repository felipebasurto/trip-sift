# Phase 6. Native package search

Back to [overview](overview.md).

## Goal

`--trip rt` and `--trip multi` POST one package and print one fare. No `Best pair`. No local sum.

## Changes

- `src/viajante/flights.py`. `search_flights` takes `Sequence[Trip]`. Delete `lower_to_probes` for `RoundTrip` and `MultiCity`. One fetch per package. `--fetch auto` counts units.
- `src/viajante/cli.py`. Print one header. Progress is one stderr line. Do not print `Best pair` on `--trip rt`.
- `src/viajante/google_flights_rpc.py` parse walk. Accept a compact item whose journey list is 2 or N flights with one price. If the first POST is outbound-only, emit one leg. Do not invent the return. The `selected_flight` follow-up loop lives here if the captured body needs it.

Docs in the same PR. README, skill, and AGENTS.md must say the sugar is still two one-ways.

## Data structures

`QuerySuccess.query` may stay the first priced probe until a flight v2 query object exists. The offer carries the package price. If that pair would lie, stop and bump flight `schema_version` to 2 in this PR using the honesty rule in phase 7.

## Verification

Static. Equivalence tests for one-way. New tests that `--trip rt` calls search once. Reject the old two-probe path for that flag.

Runtime, after encode goldens exist:

```bash
uv run viajante flights --trip rt MAD-OPO:2026-10-09:2026-10-12 --fetch sweep --top 3
```

Expect one `[1/1]` line, one header, no `Best pair`, exit 0 or a typed error. Stop on block.
