# Phase 8. Google Hotels

Back to [overview](overview.md).

## Goal

A no-Chromium hotel shortlist. Booking stays the default evidence path.

## Changes

Gate first, not committed. Live-capture one `AtySUc` batchexecute body. If the list price is not a total-stay amount, stop. Do not ship Google prices under `price_basis: "total_stay"`.

Then, in order:

- `src/viajante/google_hotels_rpc.py`. Owned encode and compact parse. Mandatory request-meta tail. Typed empty, reject, parse-miss.
- `src/viajante/models.py`. Move `RawHotelCard` / `HotelPage` here. Widen `HotelSearchReport.provider` to `"booking.com" | "google-hotels"`.
- `src/viajante/google_hotels.py`. `GoogleHotelsSource` on `ChromeSweepClient`.
- `src/viajante/hotels.py` and `src/viajante/cli.py`. `--source {booking,google}`, default `booking`. Reject `--compare-cancellation --source google` and `--min-rating > 5 --source google`.

Do not add hotel `--fetch`. Do not sweep Booking. Do not convert 4.5/5 into a fake 9/10.

## Data structures

`HotelQuery` unchanged. Per-source `build_applied_filters`. Google cards may have `address=None` and `cancellation_evidence=unknown`. Print `filter applied; card silent` when `oos`-equivalent was sent and the card is silent.

## Verification

Static. Encode bytes, fixture-to-card, widened hotel contract, no Playwright import in `google_hotels*.py`. Full suite and ruff.

Runtime. Same city and dates through `--source booking` and `--source google`. Toggle free cancellation on Google and confirm the set changes. That is the only guard against silent filter drop. `interrogate` this phase before review.
