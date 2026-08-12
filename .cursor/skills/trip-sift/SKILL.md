---
name: trip-sift
description: Search Google Flights and Booking.com locally for trip planning. Use when the user asks about flight prices, route/date comparisons, hotels, accommodation, or a trip that may need both.
---

# trip-sift

Local flight and hotel search. Prices in EUR. Flights are one-way; defaults are one adult and economy. Hotel prices are totals for the full stay.

## Invocation

Prefer the checkout CLI:

```bash
uv run trip-sift ...
```

After `uv sync` and `uv run playwright install chromium`, the entry point is available. Do not use a global `trip-sift` binary from another checkout.

## Commands

```bash
uv run trip-sift flights ORIGIN-DEST:YYYY-MM-DD[,YYYY-MM-DD...] [--max-stops {0,1}] [--adults N] [--cabin CABIN] [--top N] [--baggage-buffer EUR] [--save FILE]
uv run trip-sift hotels LOCATION CHECK_IN CHECK_OUT [--adults N] [--rooms N] [--top N] [--min-rating SCORE] [--entire-home] [--allow-non-refundable] [--compare-cancellation] [--save FILE]
```

Route grammar: `MAD-BCN:2026-09-01`, or several dates comma-separated on one route. Pass a return leg as a second route, not as a round trip.

## Smoke

```bash
# Offline (always safe)
uv run python -m unittest discover -s tests -v

# One live flight query
uv run trip-sift flights MAD-BCN:2026-12-04 --top 3

# One live hotel query
uv run trip-sift hotels Prague 2026-12-04 2026-12-07 --top 3
```

## Hotels: ask once

| User intent | Action |
|-------------|--------|
| Price check for a named route/date only | Flights only. Do not ask about hotels. |
| Trip with dates and unclear lodging | Ask once whether to search Booking.com hotels. |
| Explicit flights and hotels | Run both. Do not ask. |
| Hotels only | Hotels only. |
| Explicit "no hotel" / "flights only" | Flights only. Do not ask. |

Do not run a hotel search without confirmation when lodging intent is unclear.

## Multi-leg trips

```bash
uv run trip-sift flights MAD-LHR:2026-09-25 LHR-MAD:2026-09-27 --max-stops 0
```

Each route and each comma-separated date is a separate sequential query. `--max-stops` applies to every leg in that invocation. Progress lines go to stderr as `[i/N] ORIGIN -> DEST DATE`.

## Timing

Between queries the CLI sleeps about 4.5 to 6 seconds on purpose. N queries cost roughly N scrapes plus (N-1) delays. Never shorten delays or parallelize Google Flights or Booking.com requests.

## Destination triage (before date buffers)

Do **not** open with a full outbound×return date matrix across many cities. Each `ORIGIN-DEST:date` is a sequential scrape (~5–6 s between queries). Prefer:

1. **Shortlist from vibe + expected band** (table below). Drop cities that are clearly out of budget before scraping.
2. **Fixed natural dates first** — one outbound + one return per destination (e.g. Fri→Tue for a Monday holiday bridge). `--top 3`, `--save` if comparing.
3. **±1 day only on 1–3 finalists** the user picks or that already look competitive. Never expand dates on the whole longlist in one batch.
4. On partial failure, retry only the failed legs.

### Rough MAD direct RT bands (cabin only)

Order-of-magnitude for short MAD weekend/puente trips, **direct** ida+vuelta, `--baggage-buffer 0`. Not live quotes; holidays and lead time move them a lot. Recheck with a fixed-date scrape before recommending.

| Band | Typical RT (EUR) | Destinations (examples) | When to bother with ±1 |
|------|------------------|-------------------------|------------------------|
| Cheap short-haul | ~50–100 | OPO, LIS, other nearby Iberia/Ryanair hops | Often worth it: small EUR swings, more useful daylight |
| Mid classic | ~150–250 | FCO/ROM, BUD, RAK | Only if fixed dates are already near budget or user wants that vibe |
| Expensive for a puente | ~280+ | PRG, PMO, NAP (and similar on holiday peaks) | Skip ±1 unless the user insists; fixed dates usually already expensive |

Use bands to **exclude or deprioritize**, not to invent prices in the reply. After a live scrape, report real numbers; if a city lands far above its band, say so and do not expand dates unless asked.

## `--save`

Use `--save results/<name>.trip-sift.json` for date matrices, round trips, or downstream parsing. Skip it for a single price answer in chat. Paths under `results/` and `*.trip-sift.json` are gitignored.

Read `queries[].status`. `"ok"` with empty `offers` is not a fetch failure. Hotel reports also carry `provider`, `price_basis`, `applied`, `eligible_count`, and evidence enums. Do not invent keys.

## Agent rules

- Use the CLI or the installed `search_flights` / `search_hotels` APIs. Do not write a one-off scraper.
- Run provider queries sequentially.
- Do not add flags or code that shorten built-in delays or backoff.
- After rate-limit failures, stop for 30-60 minutes before another search.

### Flights

- Keep the flight scrape locale on English (`hl=en`, `locale=en-US`) for stable rendered evidence and the JSON `locale: "en"` contract. Hotels stay on Spanish.
- Ranking adds 70 EUR to known low-cost fares by default. Report the ranked total, not just the fare. Use `--baggage-buffer 0` for hand luggage only.
- The low-cost list is partial. Never tell the user an airline includes a bag because it is absent from the list.
- Remind the user to verify checked baggage on Google Flights before booking.

### Hotels

- Free cancellation is on by default; use `--allow-non-refundable` only after explicit user consent.
- `--compare-cancellation` runs two sequential Booking searches (with the free-cancellation chip, then without) and prints a joined price table. Do not combine it with `--allow-non-refundable`. Do not parallelize. If one of the two queries fails, skip the join.
- `--adults` defaults to 2. Override for solo travelers.
- `--min-rating` is applied locally after the scrape. It is not a Booking chip.
- Treat cancellation, `lodging_kind`, and bed/bedroom/bathroom counts as observed evidence. Do not present unknown card evidence as confirmed. Do not guess “hotel” from the property title.
- Remind the user to verify the final total and cancellation terms on Booking.com before booking.

## Second opinion in the browser

trip-sift does not scrape Kayak, Lastminute, or hotel official sites. After Booking, for **1–3 finalists** (the stays you would actually book, or the ones the user names), use the user's browser harness (Cursor browser / computer-use / Playwright MCP — whatever this session has). Skip this step if there is no browser tool.

1. Google the property title + city + check-in + check-out + adult count.
2. List whatever useful options show up: official site, Kayak, Lastminute, chain site, other aggregators. Do not rank or prefer one source over another.
3. Only quote a price if the page shows the **same dates, occupancy, and a visible total**. Snippets, ads, and “from €X” are not quotes.
4. Report those figures as an **unverified second opinion**, with the URL. Do not merge them into `--save` JSON, do not write a scraper, and do not run this for every card in a long Booking list.
5. If dates or cancellation terms do not match, say so. The user still confirms the total on the site they book.

## Recovery

| Situation | Action |
|-----------|--------|
| `no_results` | Stop. Do not retry. Do not wait. |
| `(no eligible offers)` / `(no eligible stays)` with exit 0 | Widen filters or try other dates. Do not retry the same query as a fetch failure. |
| `browser_unavailable` | Run `uv run playwright install chromium`. |
| `fetch_failed` / exit 2 | Wait 30-60 minutes. Retry failed queries only. For Booking, inspect `booking-last-failure.html` in the state dir before retrying. |
| Exit 3 (partial failure) | Re-run only the failed route or date legs. Do not re-run the whole batch. |
| Consent or markup break | Delete `pw_state_google.json` or `pw_state_booking.json` in the state dir, then retry one query. |

Exit codes: `0` all queries finished, `1` bad input, `2` all queries failed, `3` some failed.

## Browser state

Stored outside the repo at `TRIP_SIFT_STATE_DIR` or the XDG state dir. Delete `pw_state_google.json` or `pw_state_booking.json` if that provider's consent flow breaks. Booking dumps `booking-last-failure.html` next to the session file when cards never appear.

## Tests

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check src tests
```
