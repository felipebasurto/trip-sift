# Beat fli where it matters

## Context

viajante is six days old and has zero stars. [fli](https://github.com/punitarani/fli) has about 3,100. Both POST the same Google shopping RPC. Copying fli's flag list would make a worse fli, a year behind.

The work is to keep viajante's identity (evidence, baggage ranking, hotels, triage) and close the gaps that actually change a search. Real round-trip and multi-city packages. Two-or-fewer stops on the wire. Google Hotels as a fast hotel shortlist. An MCP server agents can discover.

Ten planning slices wrote reports under `/tmp/viajante-plan/worker-01.md` through `worker-10.md`. This directory is the reconciled program. Do not implement from a worker file when this overview disagrees with it.

## Scope

Included:

- A `Trip` sum type. One-way stays `FlightQuery`. Round-trip and multi-city are their own variants.
- Owned TFS and shopping encode for those trips, plus a stop table that stops lying on sweep.
- One priced offer with `legs[]`. Combined fare stays one `price_eur`.
- `--trip {one-way,rt,multi}` on the existing `flights` command. Today's tokens keep today's meaning until the flag is set.
- `--max-stops 2` after encode and parse both ask Google for two-or-fewer.
- Google Hotels over `batchexecute`, behind `--source google`. Booking stays the default evidence path.
- Five MCP tools that call the public Python API and return `to_dict()`.
- A Google Flights URL printed from `booking_token`. URL only.

Excluded:

- Duffel, LetsFG, or any ticketing POST.
- A Booking HTTP sweep. One GET of `searchresults.html` returned AWS WAF `challenge` (HTTP 202). Chromium stays the Booking path.
- Kayak, Lastminute, official hotel sites.
- Price-watch daemons, hidden-city hacks, a TypeScript port, weekday flags, `--currency` / `--language` / `--country`, alliance tables, children or infants.
- A community or stars phase.
- Flags that shorten detail delays or parallelize Google or Booking.

## Constraints

- Sweep stays HTTP, Chrome TLS, no Chromium. Tests stay offline.
- JSON key rename or drop is breaking. `schema_version` stays 1 unless a query object would lie.
- EUR and `hl=en` for flights. Hotels stay `lang=es` on Booking. Google Hotels locale is `en`.
- Retry only what can succeed. Challenge pages fail immediately.
- Public export. No live `wrb.fr` dumps, personal routes, or session files in the tree.
- viajante has no external API users. Migrate callers and delete the old path in the same wave. No dual-write shims.

## Alternatives

**A. Extend owned types and encoders.** Chosen. The tree already owns search `tfs` and shopping JSON. fli's useful file is the shopping list shape, not a dependency.

**B. Vendor fli.** Rejected. Extra pydantic, a generated airport enum, a booking-page `tfs` that is a different token, and a second HTTP client.

**C. Feature-table race (watches, hacks, Duffel, TS).** Rejected. Those delete the no-keys promise or the honest-totals stance.

## Applicable skills

- viajante skill for CLI meaning and triage.
- `how` before changing `tfs.py`, `google_flights_rpc.py`, or `booking.py`.
- `control-cli` for live smoke after a phase that changes argv or stdout.
- `create-skill` only if a phase edits `.cursor/skills/viajante/SKILL.md`.
- `unslop` and `/technical-writing` on every prose file in the same PR as the behavior.

## Phases

Land in this order. Each phase is one PR. Stop if a gate fails.

1. [Pin date and explore JSON](phase-1-contract-pins.md)
2. [Trip types](phase-2-trip-types.md)
3. [Shopping stop table](phase-3-stop-table.md)
4. [`--trip` parse and reject](phase-4-trip-flag.md)
5. [Round-trip encode](phase-5-rt-encode.md)
6. [Native package search](phase-6-package-search.md)
7. [Offer `legs` and `--max-stops 2`](phase-7-legs-and-stops.md)
8. [Google Hotels](phase-8-google-hotels.md)
9. [MCP](phase-9-mcp.md)
10. [Booking deep link](phase-10-deep-link.md)

[testing.md](testing.md) lists the suite and the live smokes.

## Verification

Every phase ends with:

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run ruff check src tests
```

Live Google or Booking calls are maintainer-only, never CI. See [testing.md](testing.md).

## Implementation guidance

The implementer must:

- Run the `how` skill on each unfamiliar subsystem before editing it.
- Run `interrogate` before shipping phase 5 or 8. Those are contested encode and hotel-source designs.
- Run `/deslop` on each diff before commit. Run `unslop` on README, skill, AGENTS.md, and commit bodies.
- Keep a row in `docs/plans/01-fli-parity/decisions.tsv` when a phase picks a fork the overview did not name.
- Use Cursor babysit after the PR opens.

Do not implement `--trip rt` as two one-ways. Exit 1 until phase 6 can POST a package. Do not add `--currency`. Do not add a Booking sweep. Do not bump `schema_version` because you added `legs`.

## Coordinator calls that overrode a slice

- One `Trip` union (slice 1). Encoders take that union. Do not add a second `FlightItinerary` type (slice 2).
- `legs` on the offer is schema 1 additive (slice 9). Slice 3 asked for a v2 bump. That bump waits until a query object stops being one-way.
- Copy no fli filters (slice 8).
- Skip Booking HTTP (slice 6). Google Hotels is the hotel sweep (slice 5). Default source stays Booking.
- MCP is five named tools (slice 7), not a trvl router.
- Ticketing, watches, OTAs, hacks, and TypeScript stay out (slice 10).
