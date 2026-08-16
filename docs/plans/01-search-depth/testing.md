# Testing

Back to [overview](overview.md).

## Static, every phase

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run ruff check src tests
```

Tests must not launch Chromium or use the network. CI already runs 3.10 through 3.14.

## Contract honesty

- A renamed or dropped `--save` key fails the exact-set tests.
- `schema_version` stays 1 unless a query object would lie.
- Forbidden offer keys. `co2`, `co2_kg`, `emissions`, `carbon`.
- A 2-stop offer with a string `layover_city` fails.
- A Google Hotels report with `provider: "booking.com"` fails.

## CLI surface

viajante is not a prompt TUI. `control-cli` here means invoke, capture stdout and stderr, assert exit code. No PTY.

Offline always (phase 4+):

```bash
uv run viajante flights --help
uv run viajante flights --trip rt MAD-BCN:2026-09-01
uv run viajante flights BADROUTE
uv run viajante flights MAD-BCN:2000-01-01
```

Live sweep, maintainer only, one query, stop on block:

```bash
uv run viajante flights MAD-BCN:DATE --fetch sweep --top 3
uv run viajante flights --trip rt MAD-OPO:OUT:BACK --fetch sweep --top 3
uv run viajante hotels Prague IN OUT --source google --top 3
```

## Fixture capture

Write live bodies to `/tmp`. Distill into `_live_*` builders in `tests/test_google_flights.py`. Redact tokens to `"tok"`. Do not commit raw `wrb.fr`, personal routes, or `booking-last-failure` files.
