"""MCP tool handlers. Import the public API only; do not import the MCP SDK."""

from __future__ import annotations

import threading
from datetime import date
from typing import Mapping, Optional, Sequence

from viajante.airports import lookup_airports
from viajante.dates import parse_route_pair, search_dates, validate_date_window
from viajante.explore import search_explore, validate_explore_window
from viajante.flights import parse_flight_plan, search_flights
from viajante.hotels import HotelSourceName, search_hotels
from viajante.models import FlightCabin, HotelQuery, MultiCity, RoundTrip, Trip

_SEARCH_LOCK = threading.Lock()


def _as_trips(plan: object) -> tuple[Trip, ...]:
    if isinstance(plan, (RoundTrip, MultiCity)):
        return (plan,)
    return tuple(plan)  # type: ignore[arg-type]


def _reject_past(dates: Sequence[date], *, label: str = "departure") -> None:
    today = date.today()
    for value in dates:
        if value < today:
            raise ValueError(f"{label} date is in the past: {value.isoformat()}")


def _with_search_lock(fn):
    if not _SEARCH_LOCK.acquire(blocking=False):
        raise ValueError("a viajante search is already running in this process")
    try:
        return fn()
    finally:
        _SEARCH_LOCK.release()


def lookup_airports_tool(query: str, *, limit: int = 20) -> list[Mapping[str, str]]:
    return [row.to_dict() for row in lookup_airports(query, limit=limit)]


def search_flights_tool(
    routes: Sequence[str],
    *,
    trip: str = "one-way",
    max_stops: int = 1,
    adults: int = 1,
    cabin: FlightCabin = "economy",
    top: int = 8,
    fetch: str = "auto",
) -> Mapping[str, object]:
    plan = parse_flight_plan(
        routes,
        trip=trip,  # type: ignore[arg-type]
        max_stops=max_stops,
        adults=adults,
        cabin=cabin,
    )
    trips = _as_trips(plan)
    _reject_past([leg.departure_date for item in trips for leg in item.legs])
    report = _with_search_lock(lambda: search_flights(trips, top=top, fetch=fetch))  # type: ignore[arg-type]
    return dict(report.to_dict())


def search_dates_tool(
    route: str,
    start: str,
    end: str,
    *,
    max_stops: int = 1,
    adults: int = 1,
    cabin: FlightCabin = "economy",
) -> Mapping[str, object]:
    origin, destination = parse_route_pair(route)
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    validate_date_window(start_date, end_date)
    _reject_past((start_date,))
    report = _with_search_lock(
        lambda: search_dates(
            origin,
            destination,
            start_date,
            end_date,
            max_stops=max_stops,
            adults=adults,
            cabin=cabin,
        )
    )
    return dict(report.to_dict())


def search_explore_tool(
    origin: str,
    start: str,
    *,
    days: int = 7,
    top: int = 8,
) -> Mapping[str, object]:
    start_date = date.fromisoformat(start)
    validate_explore_window(start_date, days)
    _reject_past((start_date,))
    report = _with_search_lock(
        lambda: search_explore(origin, start_date, days=days, top=top)
    )
    return dict(report.to_dict())


def search_hotels_tool(
    location: str,
    check_in: str,
    check_out: str,
    *,
    adults: int = 2,
    rooms: int = 1,
    top: int = 8,
    min_rating: Optional[float] = None,
    entire_home: bool = False,
    free_cancellation: bool = True,
    source: HotelSourceName = "booking",
) -> Mapping[str, object]:
    if source == "google" and min_rating is not None and min_rating > 5:
        raise ValueError("min_rating must be at most 5 with source google")
    check_in_date = date.fromisoformat(check_in)
    check_out_date = date.fromisoformat(check_out)
    _reject_past((check_in_date,), label="check-in")
    query = HotelQuery(
        location,
        check_in_date,
        check_out_date,
        adults=adults,
        rooms=rooms,
        min_rating=min_rating,
        entire_home=entire_home,
        free_cancellation=free_cancellation,
    )
    report = _with_search_lock(lambda: search_hotels((query,), top=top, source=source))
    return dict(report.to_dict())
