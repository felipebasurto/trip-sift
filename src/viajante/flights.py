"""Flight route parsing, ranking, and the Google Flights search loop."""

from __future__ import annotations

import random
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional, Protocol, Sequence, Tuple

from viajante.google_flights import (
    GoogleFlightsBlocked,
    GoogleFlightsHttpSource,
    GoogleFlightsMarkupError,
    GoogleFlightsRejected,
    GoogleFlightsSource,
    NoFlightsFound,
    RawFlightCard,
)
from viajante.models import (
    FetchBackend,
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
from viajante.orchestration import (
    MAX_ATTEMPTS,
    NON_RETRIABLE_CODES,
    inter_query_delay_seconds,
    retry_backoff_seconds,
    sweep_inter_query_delay_seconds,
)
from viajante.orchestration import (
    classify_failure as classify_provider_failure,
)
from viajante.parsers import (
    normalize_clock,
    parse_duration_hours,
    parse_price_eur,
    parse_stops_count,
)
from viajante.storage import default_state_dir, write_json_atomic

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
REJECTED_MESSAGE = "Google Flights rejected this route or date (unknown airport or invalid query)."

FlightSort = Literal["ranked", "fare", "duration"]
FetchMode = Literal["auto", "sweep", "detail"]
SWEEP_BATCH_THRESHOLD = 3
ROUTE_GRAMMAR = "ORIGIN-DESTINATION:DATE[,DATE...] or ORIGIN-DESTINATION:OUT:BACK"
_RT_DATES = re.compile(r"^(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})$")


def resolve_fetch_mode(fetch: FetchMode, query_count: int) -> Literal["sweep", "detail"]:
    if fetch == "auto":
        return "sweep" if query_count >= SWEEP_BATCH_THRESHOLD else "detail"
    if fetch in ("sweep", "detail"):
        return fetch
    raise ValueError("fetch must be 'auto', 'sweep', or 'detail'")


def _needs_detail_fallback(result: QueryResult) -> bool:
    if isinstance(result, QuerySuccess):
        return result.raw_count == 0
    if not isinstance(result, QueryFailure):
        return False
    if result.error.code == SearchErrorCode.NO_RESULTS:
        return True
    if result.error.code == SearchErrorCode.BLOCKED:
        return True
    if result.error.code == SearchErrorCode.FETCH_FAILED:
        return True
    return False


def sweep_needs_fallback(report: SearchReport) -> bool:
    return any(_needs_detail_fallback(result) for result in report.queries)


def classify_failure(exc: BaseException) -> SearchError:
    if isinstance(exc, NoFlightsFound):
        return SearchError(
            code=SearchErrorCode.NO_RESULTS,
            message=NO_RESULTS_MESSAGE,
        )
    if isinstance(exc, GoogleFlightsRejected):
        return SearchError(
            code=SearchErrorCode.REJECTED,
            message=REJECTED_MESSAGE,
        )
    if isinstance(exc, GoogleFlightsBlocked):
        return SearchError(
            code=SearchErrorCode.BLOCKED,
            message=str(exc) or "Google Flights blocked the request.",
        )
    if isinstance(exc, GoogleFlightsMarkupError):
        return SearchError(
            code=SearchErrorCode.MARKUP_DRIFT,
            message=str(exc) or "Google Flights markup could not be parsed.",
        )
    return classify_provider_failure(exc, provider="Google Flights")


class _SourceConfig(Protocol):
    html_lang: str
    currency: str


class _FlightSource(Protocol):
    config: _SourceConfig

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
            raise ValueError(f"invalid route: {spec!r}. Expected {ROUTE_GRAMMAR}") from exc
        if not origin or not destination:
            raise ValueError(f"invalid route: {spec!r}. Expected {ROUTE_GRAMMAR}")
        stripped = dates_part.strip()
        if not stripped:
            raise ValueError(f"invalid route: {spec!r}. Expected {ROUTE_GRAMMAR}")
        if "," in stripped and ":" in stripped:
            raise ValueError(
                f"invalid route: {spec!r}. Do not mix comma-separated dates with OUT:BACK"
            )
        rt_match = _RT_DATES.fullmatch(stripped)
        if rt_match:
            outbound = date.fromisoformat(rt_match.group(1))
            inbound = date.fromisoformat(rt_match.group(2))
            if inbound <= outbound:
                raise ValueError(f"return date must be after outbound in route {spec!r}")
            queries.append(
                FlightQuery(
                    origin=origin,
                    destination=destination,
                    departure_date=outbound,
                    max_stops=max_stops,
                    adults=adults,
                    cabin=cabin,
                )
            )
            queries.append(
                FlightQuery(
                    origin=destination,
                    destination=origin,
                    departure_date=inbound,
                    max_stops=max_stops,
                    adults=adults,
                    cabin=cabin,
                )
            )
            continue
        for date_text in stripped.split(","):
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
        if not any(part.strip() for part in stripped.split(",")):
            raise ValueError(f"invalid route: {spec!r}. Expected {ROUTE_GRAMMAR}")
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


AIRLINE_CODE_ALIASES = {
    "AF": ("air france",),
    "BA": ("british airways",),
    "FR": ("ryanair",),
    "I2": ("iberia express",),
    "IB": ("iberia",),
    "KL": ("klm",),
    "LH": ("lufthansa",),
    "RK": ("ryanair",),
    "TO": ("transavia",),
    "TP": ("tap", "tap air portugal"),
    "U2": ("easyjet", "easy jet"),
    "UX": ("air europa",),
    "VY": ("vueling",),
    "W6": ("wizz", "wizz air"),
}


def parse_airline_codes(text: Optional[str]) -> Optional[Tuple[str, ...]]:
    if text is None:
        return None
    codes = tuple(part.strip().upper() for part in text.split(",") if part.strip())
    if not codes:
        raise ValueError("airline list must not be empty")
    for code in codes:
        if not (2 <= len(code) <= 3 and code.isalnum()):
            raise ValueError(f"invalid airline code: {code!r}")
    return codes


def parse_depart_window(text: Optional[str]) -> Optional[Tuple[int, int]]:
    if text is None:
        return None
    try:
        start_text, end_text = text.split("-", 1)
        start, end = int(start_text), int(end_text)
    except ValueError as exc:
        raise ValueError("depart window must look like 6-20") from exc
    if not (0 <= start <= 23 and 0 <= end <= 23):
        raise ValueError("depart window hours must be between 0 and 23")
    if start > end:
        raise ValueError("depart window start must be at or before the end hour")
    return start, end


def _airline_filter_hit(raw: RawFlightCard, token: str) -> bool:
    needle = token.strip().upper()
    codes = {code.upper() for code in (raw.airline_codes or ())}
    if needle in codes:
        return True
    name = _normalize_airline(raw.airline)
    if needle.casefold() in name:
        return True
    return any(alias in name for alias in AIRLINE_CODE_ALIASES.get(needle, ()))


def _passes_airline_filters(
    raw: RawFlightCard,
    *,
    airlines: Optional[Sequence[str]],
    exclude_airlines: Optional[Sequence[str]],
) -> bool:
    if airlines and not any(_airline_filter_hit(raw, token) for token in airlines):
        return False
    if exclude_airlines and any(_airline_filter_hit(raw, token) for token in exclude_airlines):
        return False
    return True


def _departure_hour(text: Optional[str]) -> Optional[int]:
    clock = normalize_clock(text)
    if not clock:
        return None
    try:
        return int(clock.split(":", 1)[0])
    except ValueError:
        return None


def _passes_depart_window(raw: RawFlightCard, window: Optional[Tuple[int, int]]) -> bool:
    if window is None:
        return True
    hour = _departure_hour(raw.departure)
    if hour is None:
        return False
    start, end = window
    return start <= hour <= end


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
    max_layover_hours: Optional[float] = None,
    airlines: Optional[Sequence[str]] = None,
    exclude_airlines: Optional[Sequence[str]] = None,
    depart_window: Optional[Tuple[int, int]] = None,
) -> Optional[FlightOffer]:
    price_text = raw.price or ""
    price_eur = parse_price_eur(price_text)
    if price_eur is None or price_eur <= 0:
        return None
    if not _eligible_stops(raw.stops, max_stops):
        return None
    if not _passes_airline_filters(raw, airlines=airlines, exclude_airlines=exclude_airlines):
        return None
    if not _passes_depart_window(raw, depart_window):
        return None
    stops_count = parse_stops_count(raw.stops)
    layover_hours = raw.layover_hours
    if (
        max_layover_hours is not None
        and stops_count
        and stops_count > 0
        and layover_hours is not None
        and layover_hours > max_layover_hours
    ):
        return None
    airline = raw.airline or ""
    return FlightOffer(
        airline=raw.airline,
        departure=normalize_clock(raw.departure) or raw.departure,
        arrival=normalize_clock(raw.arrival) or raw.arrival,
        price=price_text,
        price_eur=price_eur,
        duration=raw.duration,
        duration_hours=parse_duration_hours(raw.duration),
        stops=raw.stops,
        stops_count=stops_count,
        layover_city=raw.layover_city,
        layover_hours=layover_hours,
        flight_numbers=raw.flight_numbers,
        baggage_buffer_eur=baggage_buffer_eur(airline, buffer_eur=buffer_eur),
        needs_bag_verify=is_low_cost(airline),
    )


def _effective_cost(offer: FlightOffer) -> float:
    return offer.price_eur + offer.baggage_buffer_eur


def _rank_offers(
    offers: Sequence[FlightOffer],
    *,
    top: int,
    sort: FlightSort = "ranked",
) -> Tuple[FlightOffer, ...]:
    def sort_key(offer: FlightOffer) -> tuple[float, float]:
        duration = offer.duration_hours
        if duration is None:
            duration = UNKNOWN_DURATION_SORTS_LAST
        if sort == "duration":
            return (duration, offer.price_eur)
        primary = offer.price_eur if sort == "fare" else _effective_cost(offer)
        return (primary, duration)

    rows = sorted(offers, key=sort_key)
    seen: set[tuple] = set()
    deduped: list[FlightOffer] = []
    for offer in rows:
        key = (
            offer.airline,
            normalize_clock(offer.departure) or offer.departure,
            normalize_clock(offer.arrival) or offer.arrival,
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
    sort: FlightSort = "ranked",
    inter_query_delay: Callable[[random.Random], float] = inter_query_delay_seconds,
    fetch_backend: Optional[FetchBackend] = None,
    fetch_ms: Optional[int] = None,
    max_layover_hours: Optional[float] = None,
    airlines: Optional[Sequence[str]] = None,
    exclude_airlines: Optional[Sequence[str]] = None,
    depart_window: Optional[Tuple[int, int]] = None,
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
                    if (
                        offer := _normalize_offer(
                            raw,
                            query.max_stops,
                            buffer_eur=buffer_eur,
                            max_layover_hours=max_layover_hours,
                            airlines=airlines,
                            exclude_airlines=exclude_airlines,
                            depart_window=depart_window,
                        )
                    )
                    is not None
                ]
                outcome = QuerySuccess(
                    query=query,
                    raw_count=len(cards),
                    eligible_count=len(eligible),
                    offers=_rank_offers(eligible, top=top, sort=sort),
                )
                break
            except Exception as exc:
                failure = classify_failure(exc)
                source.reset()
                if failure.code in NON_RETRIABLE_CODES:
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
            sleep(inter_query_delay(random_gen))
    return SearchReport(
        searched_at=now(),
        queries=tuple(results),
        locale=locale,
        currency=currency,
        fetch_backend=fetch_backend,
        fetch_ms=fetch_ms,
    )


def _attach_fetch_meta(
    report: SearchReport,
    *,
    fetch_backend: FetchBackend,
    fetch_ms: int,
) -> SearchReport:
    return SearchReport(
        searched_at=report.searched_at,
        queries=report.queries,
        locale=report.locale,
        currency=report.currency,
        fetch_backend=fetch_backend,
        fetch_ms=fetch_ms,
    )


def _search_with_source(
    queries: Sequence[FlightQuery],
    *,
    source: _FlightSource,
    top: int,
    buffer_eur: int,
    progress: Optional[Callable[[str], None]],
    sort: FlightSort,
    inter_query_delay: Callable[[random.Random], float],
    max_layover_hours: Optional[float] = None,
    airlines: Optional[Sequence[str]] = None,
    exclude_airlines: Optional[Sequence[str]] = None,
    depart_window: Optional[Tuple[int, int]] = None,
) -> SearchReport:
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
            sort=sort,
            inter_query_delay=inter_query_delay,
            max_layover_hours=max_layover_hours,
            airlines=airlines,
            exclude_airlines=exclude_airlines,
            depart_window=depart_window,
        )
    finally:
        source.close()


def search_flights(
    queries: Sequence[FlightQuery],
    *,
    top: int = 8,
    buffer_eur: int = DEFAULT_BAGGAGE_BUFFER_EUR,
    progress: Optional[Callable[[str], None]] = None,
    sort: FlightSort = "ranked",
    fetch: FetchMode = "auto",
    max_layover_hours: Optional[float] = None,
    airlines: Optional[Sequence[str]] = None,
    exclude_airlines: Optional[Sequence[str]] = None,
    depart_window: Optional[Tuple[int, int]] = None,
) -> SearchReport:
    if not queries:
        raise ValueError("at least one query is required")
    if top <= 0:
        raise ValueError("top must be positive")
    if buffer_eur < 0:
        raise ValueError("buffer_eur must not be negative")
    if max_layover_hours is not None and max_layover_hours < 0:
        raise ValueError("max_layover_hours must not be negative")
    if sort not in ("ranked", "fare", "duration"):
        raise ValueError("sort must be 'ranked', 'fare', or 'duration'")
    if fetch not in ("auto", "sweep", "detail"):
        raise ValueError("fetch must be 'auto', 'sweep', or 'detail'")
    planned = resolve_fetch_mode(fetch, len(queries))
    report_progress = progress or (lambda _: None)
    started = time.perf_counter()
    if planned == "sweep":
        noun = "query" if len(queries) == 1 else "queries"
        report_progress(f"fetch: sweep ({len(queries)} {noun})")
        report = _search_with_source(
            queries,
            source=GoogleFlightsHttpSource(),
            top=top,
            buffer_eur=buffer_eur,
            progress=progress,
            sort=sort,
            inter_query_delay=sweep_inter_query_delay_seconds,
            max_layover_hours=max_layover_hours,
            airlines=airlines,
            exclude_airlines=exclude_airlines,
            depart_window=depart_window,
        )
        retry_indexes = [
            index for index, result in enumerate(report.queries) if _needs_detail_fallback(result)
        ]
        if retry_indexes:
            report_progress("sweep empty/markup/block; falling back to detail")
            retry_queries = tuple(report.queries[index].query for index in retry_indexes)
            detail_report = _search_with_source(
                retry_queries,
                source=GoogleFlightsSource(default_state_dir()),
                top=top,
                buffer_eur=buffer_eur,
                progress=progress,
                sort=sort,
                inter_query_delay=inter_query_delay_seconds,
                max_layover_hours=max_layover_hours,
                airlines=airlines,
                exclude_airlines=exclude_airlines,
                depart_window=depart_window,
            )
            merged = list(report.queries)
            for index, detail_result in zip(retry_indexes, detail_report.queries, strict=True):
                merged[index] = detail_result
            report = SearchReport(
                searched_at=report.searched_at,
                queries=tuple(merged),
                locale=report.locale,
                currency=report.currency,
            )
            backend: FetchBackend = "sweep_then_detail"
        else:
            backend = "sweep"
    else:
        noun = "query" if len(queries) == 1 else "queries"
        report_progress(f"fetch: detail ({len(queries)} {noun})")
        report = _search_with_source(
            queries,
            source=GoogleFlightsSource(default_state_dir()),
            top=top,
            buffer_eur=buffer_eur,
            progress=progress,
            sort=sort,
            inter_query_delay=inter_query_delay_seconds,
            max_layover_hours=max_layover_hours,
            airlines=airlines,
            exclude_airlines=exclude_airlines,
            depart_window=depart_window,
        )
        backend = "detail"
    fetch_ms = max(0, int((time.perf_counter() - started) * 1000))
    return _attach_fetch_meta(report, fetch_backend=backend, fetch_ms=fetch_ms)


def write_report_atomic(report: SearchReport, destination: Path) -> None:
    write_json_atomic(report.to_dict(), destination)
