# Phase 9. MCP

Back to [overview](overview.md).

## Goal

Agents can call viajante without scraping CLI tables.

## Changes

- `pyproject.toml`. `optional-dependencies.mcp`.
- Handler module that does not import the SDK. Five functions call `search_flights`, `search_dates`, `search_explore`, `search_hotels`, `lookup_airports` and return `to_dict()`.
- Stdio entry `viajante-mcp`, importable only with the extra.
- One process lock around every `search_*` except `lookup_airports`.
- Skill Invocation. Prefer MCP if connected, else `uv run viajante`. Policy stays in the skill.

No booking tool. No CLI wrapper. No generic travel-agent router. No `{success, flights}` envelope.

## Data structures

Tool args parse into the same `Trip` / `HotelQuery` builders the CLI uses. Past dates fail at the tool boundary.

## Verification

Static. Handler tests on the default suite (patch the public functions). Lock test for overlapping calls. Server import test skipped unless the extra is installed.

Runtime. None in CI. A maintainer may point Cursor at `viajante-mcp` and run one `lookup_airports` call.
