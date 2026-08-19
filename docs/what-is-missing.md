# What viajante still needs

viajante is already a strong *local search primitive*: typed offers, two fetch modes, a calendar, explore, offline IATA, and an MCP surface. It is not yet a travel *agent*. The gap is composition, not another OTA scraper.

Do not add booking, parallel Google/Booking, or flags that shorten detail delays. Those would make it louder, not better.

## What is already right

- Sweep is the fast path: one Chrome TLS session, owned shopping RPC, no Chromium. A one-route sweep is about two seconds.
- Detail is evidence, not the default shortlist. Hotels on Google are the same idea: HTTP first.
- Destination triage in the skill is the correct search strategy. Brute-force date matrices are the thing to refuse.
- The JSON contract keeps raw card text next to parsed numbers. Agents can switch on `error.code`.
- Sequential pacing and the MCP one-search lock are load policy, not slowness for its own sake.

## Speed: the actual bottlenecks

1. **`--fetch auto` picks detail for 1–2 flight queries.** The common agent case (one route, one date) starts Chromium and sleeps 4.5s+. Sweep already returns a usable shortlist. Auto should prefer sweep; detail should be opt-in when the user asks for bags, the full card set, or a second look.
2. **CLI hotels default to Booking/Playwright.** MCP already defaults to Google HTTP. For agents, Google shortlist then Booking on 1–3 finalists is the fast path. The CLI default fights that.
3. **`explore` prices each destination with a shopping fetch.** Catalog + N sequential POSTs. A priced explore of 12 cities is the slowest *intended* HTTP loop. Needs a cheaper price field from the explore body, or a hard cap the skill already implies (price 5, not 12, unless asked).
4. **Calendar miss falls back to one sweep per day.** A 31-day window becomes 31 shopping calls. The compact calendar must stay the happy path; the fallback should be rare and visible.
5. **No session cache.** Agents re-ask the same MAD-OPO Friday. A TTL cache in the state dir (not in git) would cut repeat work without becoming a fare database.
6. **No metro / nearby airports.** `NYC` is not a query. London is LHR or LGW, never both. The fastest “cheap flight” win is expanding a city to its passenger airports in one sweep batch, then ranking.

## Product: what an AI travel tool still cannot do

Ranked by how often a real trip question hits the hole.

| Gap | Why it matters | Fits this tree? |
| --- | --- | --- |
| City → IATA in `flights` / `dates` | Users and agents say “Tokyo”, not `HND`. `airports` exists; the search commands do not use it. | Yes. Resolve, then search. Reject ambiguous cities. |
| Nearby-airport groups | Best fare is often the other airport in the same city. | Yes. Local expansion, same sweep session. |
| Children / infants | `adults` only. Booking hard-codes `group_children=0`. | Yes. Query fields, not a new source. |
| Observed bags, not a name list | Ranked sort adds 70 EUR to a partial LCC list. Norse is in the README example and **not** in `LOW_COST_NAMES`. Absence is not “bag included”. | Yes. Parse card/RPC bag text when present; keep the buffer as fallback. |
| Flight + hotel as one trip | Two reports, no package total, no shared dates. | Yes. A composer on top of existing search loops. Do not scrape packages. |
| Round-trip calendar | `dates` is one-way, 31 days. “When is this weekend cheap?” is still N one-ways or a packaged RT per pair. | Yes, if the date-grid RPC can carry a return. Do not emulate with a matrix. |
| First-class ±1 day on finalists | The skill does this by hand. A `flex` window on 1–3 routes would stop agents from inventing matrices. | Yes. Small CLI/MCP flag, same sweep session. |
| Hotel neighborhood / distance | Cards have title + address. No geo, no “walk to center”. | Partial. Only if the owned parse already has it. Do not invent maps. |
| Multi-city detail | Sweep can POST a package; Playwright cannot. | Later. Sweep is enough until someone needs the full card set. |
| Trains / buses | Europe weekend trips are often rail. | No, not in this tree. Different source, different contract. Point the agent at another tool. |
| Price alerts / history | “Tell me when MAD-LIS drops.” | No. That is a watcher plus stored fares. Conflicts with the public-export boundary. |
| Checkout | Booking token is a Google URL, nothing more. | No. Verify on the site. Stay a searcher. |

## AI surface

The MCP tools match the CLI. They do not yet match how an agent plans.

- No `plan_trip` / `score_itinerary` that returns one ranked list of (route, dates, flight EUR, hotel EUR, total).
- No compact MCP payload. Agents get the full `--save` shape, including raw strings they then re-summarize.
- Stdio only, one lock. Correct for a local Cursor tool. Wrong if the goal is a hosted multi-user server.
- Skill price bands are MAD-only. An origin-agnostic shortlist needs either more honest bands or live `explore` first, never invented prices.
- Hotel MCP is missing `--compare-cancellation`. Fine. Do not add it until Booking is an explicit opt-in.

## Suggested order

1. **Make the default path sweep.** `auto` → sweep for 1–2 queries; detail only on request or fallback. This is the single largest speed win.
2. **City and metro airports.** `viajante flights Tokyo-London:DATE` resolves, expands, sweeps, ranks. Same for `dates`.
3. **Fix bag evidence.** Parse inclusion when the card/RPC says so; expand the LCC list; stop documenting Norse as buffered if the code does not.
4. **Trip composer.** One MCP tool: fixed dates, optional hotel, one total, no date matrix.
5. **`flex=1` on a shortlist.** Only after a fixed-date winner exists.
6. **Session TTL cache** in the state dir. Never commit it.

Stop before trains, alerts, checkout, or a second OTA. Those are other products.
