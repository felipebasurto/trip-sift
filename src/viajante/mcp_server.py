"""Stdio MCP entry. Importable only when the mcp extra is installed."""

from __future__ import annotations

from viajante.mcp_handlers import (
    lookup_airports_tool,
    search_dates_tool,
    search_explore_tool,
    search_flights_tool,
    search_hotels_tool,
)


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit(
            "viajante-mcp requires the mcp extra. Install with: uv sync --extra mcp"
        ) from exc

    server = FastMCP("viajante")

    @server.tool()
    def search_flights(
        routes: list[str],
        trip: str = "one-way",
        max_stops: int = 1,
        adults: int = 1,
        cabin: str = "economy",
        top: int = 8,
        fetch: str = "auto",
    ) -> dict:
        return dict(
            search_flights_tool(
                routes,
                trip=trip,
                max_stops=max_stops,
                adults=adults,
                cabin=cabin,  # type: ignore[arg-type]
                top=top,
                fetch=fetch,
            )
        )

    @server.tool()
    def search_dates(
        route: str,
        start: str,
        end: str,
        max_stops: int = 1,
        adults: int = 1,
        cabin: str = "economy",
    ) -> dict:
        return dict(
            search_dates_tool(
                route,
                start,
                end,
                max_stops=max_stops,
                adults=adults,
                cabin=cabin,  # type: ignore[arg-type]
            )
        )

    @server.tool()
    def search_explore(origin: str, start: str, days: int = 7, top: int = 8) -> dict:
        return dict(search_explore_tool(origin, start, days=days, top=top))

    @server.tool()
    def search_hotels(
        location: str,
        check_in: str,
        check_out: str,
        adults: int = 2,
        rooms: int = 1,
        top: int = 8,
        min_rating: float | None = None,
        entire_home: bool = False,
        free_cancellation: bool = True,
        source: str = "booking",
    ) -> dict:
        return dict(
            search_hotels_tool(
                location,
                check_in,
                check_out,
                adults=adults,
                rooms=rooms,
                top=top,
                min_rating=min_rating,
                entire_home=entire_home,
                free_cancellation=free_cancellation,
                source=source,  # type: ignore[arg-type]
            )
        )

    @server.tool()
    def lookup_airports(query: str, limit: int = 20) -> list:
        return lookup_airports_tool(query, limit=limit)

    server.run()


if __name__ == "__main__":
    main()
