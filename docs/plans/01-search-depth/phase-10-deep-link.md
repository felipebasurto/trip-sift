# Phase 10. Booking deep link

Back to [overview](overview.md).

## Goal

Hand the user the Google Flights itinerary page. Do not book.

## Changes

- `src/viajante/cli.py` (and the table printer). When `booking_token` is present, print a Google Flights URL.
- `AGENTS.md`. Bound in the same PR. URL emission only. No passenger fields. No payment. No POST to a booking endpoint.

Skip this phase if sweep tokens prove to be continuation tokens rather than book tokens. Phase 6's outbound-only capture decides that.

## Data structures

Reuse `FlightOffer.booking_token`. No new report key unless the URL must be saved. If saved, add `booking_url` as schema 1 additive and grow `OFFER_KEYS`.

## Verification

Static. A fixture offer with `booking_token="tok"` prints a URL that contains the token. A missing token prints nothing extra.

Runtime. Open one printed URL in a browser. Confirm it is `/travel/flights` for that itinerary, not a checkout POST.
