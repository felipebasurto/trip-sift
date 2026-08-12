"""Flight route parsing, ranking, and the Google Flights search loop."""

from __future__ import annotations

import random
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol, Sequence, Tuple

from trip_sift.google_flights import (
    GoogleFlightsMarkupError,
    GoogleFlightsSource,
    NoFlightsFound,
    RawFlightCard,
)
from trip_sift.models import (
    FlightCabin,
    FlightOffer,
    FlightQuery,
    QueryFailure,
    QueryResult,
    QuerySuccess,
    SearchError,
    SearchErrorCode,
    SearchReport,
)
from trip_sift.orchestration import (
    MAX_ATTEMPTS,
    NON_RETRIABLE_CODES,
    inter_query_delay_seconds,
    retry_backoff_seconds,
)
from trip_sift.orchestration import (
    classify_failure as classify_provider_failure,
)
from trip_sift.parsers import parse_duration_hours, parse_price_eur, parse_stops_count
from trip_sift.storage import default_state_dir, write_json_atomic

DEFAULT_BAGGAGE_BUFFER_EUR = 70

UNKNOWN_DURATION_SORTS_LAST = float("inf")

LOW_COST_NAMES = [
    "AirAsia",
    "Batik Air",
    "Cebu Pacific",
    "easyJet",
    "Eurowings",
    "IndiGo",
    "Jetstar",
    "Jin Air",
    "Norwegian",
    "Peach",
    "Pegasus",
    "Ryanair",
    "Scoot",
    "Transavia",
    "T'way",
    "Vietjet",
    "Volotea",
    "Vueling",
    "Wizz Air",
    "ZIPAIR",
]

NO_RESULTS_MESSAGE = "Google Flights returned no flights for this route and date."


def classify_failure(exc: BaseException) -> SearchError:
    if isinstance(exc, NoFlightsFound):
        return SearchError(
            code=SearchErrorCode.NO_RESULTS,
            message=NO_RESULTS_MESSAGE,
        )
    return classify_provider_failure(exc, provider="Google Flights")


class _FlightSource(Protocol):
    def fetch(self, query: FlightQuery) -> Sequence[RawFlightCard]: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


def parse_route_specs(
    specs: Sequence[str],
    *,
    max_stops: int,
    adults: int = 1,
    cabin: FlightCabin = "economy",
) -> Tuple[FlightQuery, ...]:
    if max_stops not in (0, 1):
        raise ValueError("max_stops must be 0 or 1")
    queries: list[FlightQuery] = []
    for spec in specs:
        try:
            pair, dates_part = spec.split(":", 1)
            origin, destination = pair.split("-", 1)
        except ValueError as exc:
            raise ValueError(
                f"invalid route: {spec!r}. Expected ORIGIN-DESTINATION:DATE[,DATE...]"
            ) from exc
        if not origin or not destination:
            raise ValueError(f"invalid route: {spec!r}")
        for date_text in dates_part.split(","):
            date_text = date_text.strip()
            if not date_text:
                continue
            try:
                departure_date = date.fromisoformat(date_text)
            except ValueError as exc:
                raise ValueError(f"invalid date {date_text!r} in route {spec!r}") from exc
            queries.append(
                FlightQuery(
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    max_stops=max_stops,
                    adults=adults,
                    cabin=cabin,
                )
            )
        if not any(d.strip() for d in dates_part.split(",")):
            raise ValueError(f"invalid route: {spec!r}")
    if not queries:
        raise ValueError("at least one route is required")
    return tuple(queries)


def _normalize_airline(airline_text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (airline_text or "").casefold())


_LOW_COST_PATTERNS = tuple(
    re.compile(r"\b" + re.escape(_normalize_airline(name)) + r"\b") for name in LOW_COST_NAMES
)


def is_low_cost(airline_text: str) -> bool:
    text = _normalize_airline(airline_text)
    return any(pattern.search(text) for pattern in _LOW_COST_PATTERNS)


def baggage_buffer_eur(
    airline_text: str,
    *,
    buffer_eur: int = DEFAULT_BAGGAGE_BUFFER_EUR,
) -> int:
    return buffer_eur if is_low_cost(airline_text) else 0


def _eligible_stops(stops: Optional[str], max_stops: int) -> bool:
    count = parse_stops_count(stops)
    if count is not None:
        return count <= max_stops
    return max_stops >= 1


def _normalize_offer(
    raw: RawFlightCard,
    max_stops: int,
    *,
    buffer_eur: int = DEFAULT_BAGGAGE_BUFFER_EUR,
) -> Optional[FlightOffer]:
    price_text = raw.price or ""
    price_eur = parse_price_eur(price_text)
    if price_eur is None or price_eur <= 0:
        return None
    if not _eligible_stops(raw.stops, max_stops):
        return None
    airline = raw.airline or ""
    return FlightOffer(
        airline=raw.airline,
        departure=raw.departure,
        arrival=raw.arrival,
        price=price_text,
        price_eur=price_eur,
        duration=raw.duration,
        duration_hours=parse_duration_hours(raw.duration),
        stops=raw.stops,
        stops_count=parse_stops_count(raw.stops),
        baggage_buffer_eur=baggage_buffer_eur(airline, buffer_eur=buffer_eur),
        needs_bag_verify=is_low_cost(airline),
    )


def _effective_cost(offer: FlightOffer) -> float:
    return offer.price_eur + offer.baggage_buffer_eur


def _rank_offers(
    offers: Sequence[FlightOffer],
    *,
    top: int,
) -> Tuple[FlightOffer, ...]:
    rows = sorted(
        offers,
        key=lambda o: (
            _effective_cost(o),
            o.duration_hours if o.duration_hours is not None else UNKNOWN_DURATION_SORTS_LAST,
        ),
    )
    seen: set[tuple] = set()
    deduped: list[FlightOffer] = []
    for offer in rows:
        key = (
            offer.airline,
            offer.departure,
            offer.arrival,
            offer.price_eur,
            offer.stops_count,
            offer.duration_hours,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(offer)
        if len(deduped) >= top:
            break
    return tuple(deduped)


def _run_search(
    queries: Sequence[FlightQuery],
    *,
    top: int,
    source: _FlightSource,
    sleep: Callable[[float], None],
    random_gen: random.Random,
    now: Callable[[], datetime],
    buffer_eur: int = DEFAULT_BAGGAGE_BUFFER_EUR,
    progress: Optional[Callable[[str], None]] = None,
    locale: str = "en",
    currency: str = "EUR",
) -> SearchReport:
    report_progress = progress or (lambda _: None)
    results: list[QueryResult] = []
    for index, query in enumerate(queries):
        report_progress(
            f"[{index + 1}/{len(queries)}] {query.origin} -> {query.destination} "
            f"{query.departure_date.isoformat()}"
        )
        outcome: Optional[QueryResult] = None
        failure: Optional[SearchError] = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                cards = source.fetch(query)
                eligible = [
                    offer
                    for raw in cards
                    if (offer := _normalize_offer(raw, query.max_stops, buffer_eur=buffer_eur))
                    is not None
                ]
                outcome = QuerySuccess(
                    query=query,
                    raw_count=len(cards),
                    eligible_count=len(eligible),
                    offers=_rank_offers(eligible, top=top),
                )
                break
            except Exception as exc:
                failure = classify_failure(exc)
                source.reset()
                if failure.code in NON_RETRIABLE_CODES or isinstance(exc, GoogleFlightsMarkupError):
                    break
                if attempt + 1 < MAX_ATTEMPTS:
                    sleep(retry_backoff_seconds(attempt, random_gen))
        if outcome is None:
            outcome = QueryFailure(
                query=query,
                error=failure
                or SearchError(
                    code=SearchErrorCode.FETCH_FAILED,
                    message="Google Flights search failed.",
                ),
            )
            report_progress(f"  {outcome.error.code.value}: {outcome.error.message}")
        results.append(outcome)
        if index + 1 < len(queries):
            sleep(inter_query_delay_seconds(random_gen))
    return SearchReport(
        searched_at=now(),
        queries=tuple(results),
        locale=locale,
        currency=currency,
    )


def search_flights(
    queries: Sequence[FlightQuery],
    *,
    top: int = 8,
    buffer_eur: int = DEFAULT_BAGGAGE_BUFFER_EUR,
    progress: Optional[Callable[[str], None]] = None,
) -> SearchReport:
    if not queries:
        raise ValueError("at least one query is required")
    if top <= 0:
        raise ValueError("top must be positive")
    if buffer_eur < 0:
        raise ValueError("buffer_eur must not be negative")
    source = GoogleFlightsSource(default_state_dir())
    try:
        return _run_search(
            queries,
            top=top,
            source=source,
            sleep=time.sleep,
            random_gen=random.Random(),
            now=lambda: datetime.now(timezone.utc),
            buffer_eur=buffer_eur,
            progress=progress,
            locale=source.config.html_lang,
            currency=source.config.currency,
        )
    finally:
        source.close()


def write_report_atomic(report: SearchReport, destination: Path) -> None:
    write_json_atomic(report.to_dict(), destination)
