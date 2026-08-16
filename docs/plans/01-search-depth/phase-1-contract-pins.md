# Phase 1. Pin date and explore JSON

Back to [overview](overview.md).

## Goal

Dates and explore already emit `schema_version` 1 and have no exact-set tests. Pin those envelopes before any feature changes `to_dict()`.

## Changes

- Add `tests/test_dates_json_contract.py`.
- Add `tests/test_explore_json_contract.py`.
- Add a forbidden-key set and `test_schema_version_stays_1` to `tests/test_json_contract.py` and `tests/test_hotel_json_contract.py`.

No `models.py` edits.

## Data structures

Four independent `schema_version` integers, all 1. Closed `fetch_backend` sets. Date `{calendar, sweep}`. Explore `{explore}`. Flight `{sweep, detail, sweep_then_detail}`.

## Verification

Static. The four contract modules pass against current `to_dict()`. Full unittest and ruff.

Runtime. None. This phase does not change the CLI.
