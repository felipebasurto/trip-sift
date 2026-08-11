from __future__ import annotations

import atexit
import contextlib
import json
import os
import random
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional, Protocol, Sequence, Tuple

from fast_flights import FlightData, Passengers
from fast_flights.core import parse_response
from fast_flights.filter import TFSData
from fast_flights.schema import Result

from trip_sift.models import (
    FlightOffer,
    FlightQuery,
    QueryFailure,
    QueryResult,
    QuerySuccess,
    SearchError,
    SearchErrorCode,
    SearchReport,
)
from trip_sift.parsers import parse_duration_hours, parse_price_eur, parse_stops_count

REQUEST_DELAY_SECONDS = 4.5
REQUEST_JITTER_SECONDS = 1.5
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 8.0
BACKOFF_JITTER_SECONDS = 3.0

DEFAULT_BAGGAGE_BUFFER_EUR = 70

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

CONSENT_SELECTORS = [
    'text="Accept all"',
    'text="Reject all"',
    'text="Aceptar todo"',
    'text="Rechazar todo"',
    'button:has-text("Accept")',
]

BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}

NO_RESULTS_MARKERS = ("no flights found",)
BROWSER_UNAVAILABLE_MARKERS = (
    "executable doesn't exist",
    "playwright install",
    "browsertype.launch",
    "no module named 'playwright'",
)


def classify_failure(exc: BaseException) -> SearchError:
    text = f"{type(exc).__name__}: {exc}".strip()
    lowered = text.casefold()
    if any(marker in lowered for marker in NO_RESULTS_MARKERS):
        return SearchError(
            code=SearchErrorCode.NO_RESULTS,
            message="Google Flights returned no flights for this route and date.",
        )
    if any(marker in lowered for marker in BROWSER_UNAVAILABLE_MARKERS):
        return SearchError(
            code=SearchErrorCode.BROWSER_UNAVAILABLE,
            message=(
                "Chromium is not available to Playwright. "
                "Run 'playwright install chromium'."
            ),
        )
    return SearchError(code=SearchErrorCode.FETCH_FAILED, message=text)


NON_RETRIABLE_CODES = frozenset(
    {SearchErrorCode.NO_RESULTS, SearchErrorCode.BROWSER_UNAVAILABLE}
)


class _ProviderOffer(Protocol):
    name: Optional[str]
    departure: Optional[str]
    arrival: Optional[str]
    price: Optional[str]
    duration: Optional[str]
    stops: object


class _ProviderResult(Protocol):
    flights: Sequence[_ProviderOffer]


class _FlightSource(Protocol):
    def fetch(self, query: FlightQuery) -> _ProviderResult:
        ...

    def reset(self) -> None:
        ...

    def close(self) -> None:
        ...


def default_state_dir() -> Path:
    env = os.environ.get("TRIP_SIFT_STATE_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "trip-sift"
    return Path.home() / ".local" / "state" / "trip-sift"


def parse_route_specs(
    specs: Sequence[str],
    *,
    max_stops: int,
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
    re.compile(r"\b" + re.escape(_normalize_airline(name)) + r"\b")
    for name in LOW_COST_NAMES
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


def _stops_text(stops: object) -> Optional[str]:
    if stops is None:
        return None
    if isinstance(stops, str):
        return stops
    if isinstance(stops, int):
        return "Nonstop" if stops == 0 else f"{stops} stop" + ("s" if stops > 1 else "")
    return str(stops)


def _eligible_stops(stops: object, max_stops: int) -> bool:
    count = parse_stops_count(stops)
    if count is not None:
        return count <= max_stops
    if isinstance(stops, str):
        lower = stops.lower()
        if any(x in lower for x in ("2 stop", "2 escala", "3 stop", "3 escala", "2 ", "3 ")):
            return False
        if max_stops == 0:
            return lower in ("nonstop", "directo", "direct")
    return max_stops >= 1


def _normalize_offer(
    raw: _ProviderOffer,
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
    airline = raw.name or ""
    return FlightOffer(
        airline=raw.name,
        departure=raw.departure,
        arrival=raw.arrival,
        price=price_text,
        price_eur=price_eur,
        duration=raw.duration,
        duration_hours=parse_duration_hours(raw.duration),
        stops=_stops_text(raw.stops),
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
        key=lambda o: (_effective_cost(o), o.duration_hours if o.duration_hours is not None else 99.0),
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
                provider_result = source.fetch(query)
                offers = [
                    offer
                    for raw in provider_result.flights
                    if (
                        offer := _normalize_offer(
                            raw, query.max_stops, buffer_eur=buffer_eur
                        )
                    )
                    is not None
                ]
                outcome = QuerySuccess(
                    query=query,
                    raw_count=len(provider_result.flights),
                    offers=_rank_offers(offers, top=top),
                )
                break
            except Exception as exc:
                failure = classify_failure(exc)
                source.reset()
                if failure.code in NON_RETRIABLE_CODES:
                    break
                if attempt + 1 < MAX_ATTEMPTS:
                    backoff = BACKOFF_BASE_SECONDS * (2**attempt) + random_gen.uniform(
                        0, BACKOFF_JITTER_SECONDS
                    )
                    sleep(backoff)
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
            delay = REQUEST_DELAY_SECONDS + random_gen.uniform(0, REQUEST_JITTER_SECONDS)
            sleep(delay)
    return SearchReport(searched_at=now(), queries=tuple(results))


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
    state_dir = default_state_dir()
    source = _GoogleFlightsSource(state_dir)
    try:
        return _run_search(
            queries,
            top=top,
            source=source,
            sleep=time.sleep,
            random_gen=random.Random(),
            now=lambda: datetime.utcnow(),
            buffer_eur=buffer_eur,
            progress=progress,
        )
    finally:
        source.close()


def write_report_atomic(report: SearchReport, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, destination)


class _HtmlResponse:
    status_code = 200

    def __init__(self, html: str) -> None:
        self.text = html
        self.text_markdown = html


class _GoogleFlightsSource:
    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir
        self._state_path = state_dir / "pw_state_google.json"
        self._pw = None
        self._browser = None
        self._context = None
        self._atexit_registered = False

    def _ensure_context(self) -> object:
        if self._context is None:
            from playwright.sync_api import sync_playwright

            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            storage = str(self._state_path) if self._state_path.exists() else None
            self._context = self._browser.new_context(locale="en-US", storage_state=storage)
            self._context.route("**/*", self._block_heavy_resources)
            if not self._atexit_registered:
                atexit.register(self.close)
                self._atexit_registered = True
        return self._context

    @staticmethod
    def _block_heavy_resources(route) -> None:
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
            route.abort()
        else:
            route.continue_()

    def _fetch_html(self, url: str) -> str:
        page = self._ensure_context().new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if "consent.google" in page.url:
                for sel in CONSENT_SELECTORS:
                    try:
                        btn = page.locator(sel).first
                        if btn.count() > 0:
                            btn.click(timeout=5_000)
                            break
                    except Exception:
                        continue
                page.wait_for_timeout(1_500)
            page.locator(".eQ35Ce").wait_for(timeout=60_000)
            return page.evaluate(
                "() => document.querySelector('[role=\"main\"]')?.innerHTML || ''"
            )
        finally:
            with contextlib.suppress(Exception):
                page.close()

    def _build_tfs(self, query: FlightQuery) -> TFSData:
        fd = FlightData(
            date=query.departure_date.isoformat(),
            from_airport=query.origin,
            to_airport=query.destination,
            max_stops=query.max_stops,
        )
        return TFSData.from_interface(
            flight_data=[fd],
            trip="one-way",
            passengers=Passengers(adults=1),
            seat="economy",
            max_stops=query.max_stops,
        )

    def _fetch_params(self, tfs: TFSData) -> dict[str, str]:
        return {
            "tfs": tfs.as_b64().decode("utf-8"),
            "hl": "en",
            "tfu": "EgQIABABIgA",
            "curr": "EUR",
        }

    def fetch(self, query: FlightQuery) -> Result:
        tfs = self._build_tfs(query)
        params = self._fetch_params(tfs)
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"https://www.google.com/travel/flights?{qs}"
        return parse_response(_HtmlResponse(self._fetch_html(url)))

    def reset(self) -> None:
        if self._context is not None:
            with contextlib.suppress(Exception):
                self._context.storage_state(path=str(self._state_path))
        for obj in (self._context, self._browser):
            if obj is not None:
                with contextlib.suppress(Exception):
                    obj.close()
        if self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()
        self._pw = self._browser = self._context = None

    def close(self) -> None:
        if self._context is not None:
            with contextlib.suppress(Exception):
                self._state_dir.mkdir(parents=True, exist_ok=True)
                tmp = self._state_path.with_suffix(".json.tmp")
                self._context.storage_state(path=str(tmp))
                os.replace(tmp, self._state_path)
        for obj in (self._context, self._browser):
            if obj is not None:
                with contextlib.suppress(Exception):
                    obj.close()
        if self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()
        self._pw = self._browser = self._context = None
