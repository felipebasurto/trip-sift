"""Cheapest-per-day calendar via the owned Google Flights date-grid RPC."""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol, Sequence

from viajante.flights import _normalize_offer, classify_failure
from viajante.google_flights import GoogleFlightsHttpSource, RawFlightCard
from viajante.google_flights_rpc import CompactCalendarDay, CompactParseMiss
from viajante.models import (
    DateCalendarReport,
    DatePriceRow,
    FlightCabin,
    FlightQuery,
    SearchError,
    SearchErrorCode,
)
from viajante.storage import write_json_atomic

MAX_DATE_WINDOW_DAYS = 31


class CalendarSource(Protocol):
    def fetch_calendar(
        self, query: FlightQuery, start: date, end: date
    ) -> Sequence[CompactCalendarDay]: ...

    def fetch(self, query: FlightQuery) -> Sequence[RawFlightCard]: ...

    def close(self) -> None: ...


def parse_route_pair(spec: str) -> tuple[str, str]:
    try:
        origin, destination = spec.split("-", 1)
    except ValueError as exc:
        raise ValueError(f"invalid route: {spec!r}. Expected ORIGIN-DEST") from exc
    origin, destination = origin.strip(), destination.strip()
    if not origin or not destination or "-" in destination:
        raise ValueError(f"invalid route: {spec!r}. Expected ORIGIN-DEST")
    return origin, destination


def date_window_days(start: date, end: date) -> int:
    return (end - start).days + 1


def validate_date_window(start: date, end: date, *, today: Optional[date] = None) -> None:
    if end < start:
        raise ValueError("end date must be on or after the start date")
    span = date_window_days(start, end)
    if span > MAX_DATE_WINDOW_DAYS:
        raise ValueError(f"date window is at most {MAX_DATE_WINDOW_DAYS} days (got {span})")
    check = today or date.today()
    if start < check:
        raise ValueError(f"start date is in the past: {start.isoformat()}")


def search_dates(
    origin: str,
    destination: str,
    start: date,
    end: date,
    *,
    adults: int = 1,
    cabin: FlightCabin = "economy",
    max_stops: int = 1,
    progress: Optional[Callable[[str], None]] = None,
    source: Optional[CalendarSource] = None,
) -> DateCalendarReport:
    validate_date_window(start, end)
    query = FlightQuery(
        origin=origin,
        destination=destination,
        departure_date=start,
        max_stops=max_stops,
        adults=adults,
        cabin=cabin,
    )
    report_progress = progress or (lambda _: None)
    report_progress(
        f"dates: {query.origin} -> {query.destination} "
        f"{start.isoformat()} .. {end.isoformat()} (max {MAX_DATE_WINDOW_DAYS} days)"
    )
    started = time.perf_counter()
    client = source or GoogleFlightsHttpSource()
    backend = "calendar"
    try:
        try:
            compact = client.fetch_calendar(query, start, end)
            days = _rows_from_calendar(start, end, compact)
        except CompactParseMiss:
            report_progress("calendar miss; pricing each day with shopping sweep")
            days = _sweep_per_day(client, query, start, end, report_progress)
            backend = "sweep"
        except Exception as exc:
            error = classify_failure(exc)
            days = _error_rows(start, end, error)
    finally:
        client.close()
    fetch_ms = max(0, int((time.perf_counter() - started) * 1000))
    return DateCalendarReport(
        searched_at=datetime.now(timezone.utc),
        origin=query.origin,
        destination=query.destination,
        start_date=start,
        end_date=end,
        days=days,
        fetch_backend=backend,
        fetch_ms=fetch_ms,
    )


def write_dates_report_atomic(report: DateCalendarReport, destination: Path) -> None:
    write_json_atomic(report.to_dict(), destination)


def _rows_from_calendar(
    start: date,
    end: date,
    compact: Sequence[CompactCalendarDay],
) -> tuple[DatePriceRow, ...]:
    by_day = {row.departure_date: row for row in compact}
    rows: list[DatePriceRow] = []
    cursor = start
    while cursor <= end:
        found = by_day.get(cursor)
        if found is None or found.price_eur is None:
            rows.append(DatePriceRow(departure_date=cursor, status="empty"))
        else:
            rows.append(
                DatePriceRow(
                    departure_date=cursor,
                    price_eur=found.price_eur,
                    status="ok",
                )
            )
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
    return tuple(rows)


def _sweep_per_day(
    source: CalendarSource,
    query: FlightQuery,
    start: date,
    end: date,
    progress: Callable[[str], None],
) -> tuple[DatePriceRow, ...]:
    rows: list[DatePriceRow] = []
    cursor = start
    span = date_window_days(start, end)
    index = 0
    while cursor <= end:
        index += 1
        progress(f"[{index}/{span}] {query.origin} -> {query.destination} {cursor.isoformat()}")
        day_query = FlightQuery(
            origin=query.origin,
            destination=query.destination,
            departure_date=cursor,
            max_stops=query.max_stops,
            adults=query.adults,
            cabin=query.cabin,
        )
        try:
            cards = source.fetch(day_query)
        except Exception as exc:
            error = classify_failure(exc)
            if error.code in {SearchErrorCode.NO_RESULTS, SearchErrorCode.REJECTED}:
                rows.append(DatePriceRow(departure_date=cursor, status="empty"))
            else:
                rows.append(DatePriceRow(departure_date=cursor, status="error", error=error))
            cursor = cursor.fromordinal(cursor.toordinal() + 1)
            continue
        offers = [
            offer
            for raw in cards
            if (offer := _normalize_offer(raw, query.max_stops, buffer_eur=0)) is not None
        ]
        if not offers:
            rows.append(DatePriceRow(departure_date=cursor, status="empty"))
        else:
            best = min(offers, key=lambda offer: offer.price_eur)
            rows.append(
                DatePriceRow(
                    departure_date=cursor,
                    price_eur=best.price_eur,
                    airline=best.airline,
                    stops_count=best.stops_count,
                    status="ok",
                )
            )
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
    return tuple(rows)


def _error_rows(start: date, end: date, error: SearchError) -> tuple[DatePriceRow, ...]:
    rows: list[DatePriceRow] = []
    cursor = start
    while cursor <= end:
        rows.append(DatePriceRow(departure_date=cursor, status="error", error=error))
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
    return tuple(rows)
