from __future__ import annotations

import atexit
import contextlib
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol, Sequence, Tuple
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from trip_sift.models import (
    AppliedHotelFilters,
    CancellationEvidence,
    HotelOffer,
    HotelQuery,
    HotelQueryFailure,
    HotelQueryResult,
    HotelQuerySuccess,
    HotelSearchReport,
    PropertyTypeEvidence,
    SearchError,
    SearchErrorCode,
)
from trip_sift.orchestration import (
    MAX_ATTEMPTS,
    NON_RETRIABLE_CODES,
    classify_failure,
    inter_query_delay_seconds,
    retry_backoff_seconds,
)
from trip_sift.parsers import (
    parse_cancellation_evidence,
    parse_price_eur,
    parse_property_type_evidence,
    parse_rating,
    parse_unit_hints,
)
from trip_sift.storage import default_state_dir, write_json_atomic

BOOKING_SEARCH_URL = "https://www.booking.com/searchresults.html"
PROPERTY_CARD_SELECTOR = '[data-testid="property-card"]'
EMPTY_STATE_SELECTORS = (
    '[data-testid="searchresults-empty"]',
    '[data-testid="empty-state"]',
    '[data-testid="no-results"]',
)
CONSENT_SELECTORS = (
    "#onetrust-accept-btn-handler",
    'button:has-text("Accept")',
    'button:has-text("Aceptar")',
    'button:has-text("Accept all")',
    'button:has-text("Aceptar todas")',
    '[id*="accept"]',
)
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class _RawHotelCard:
    title: str
    address: Optional[str]
    total_price: str
    rating: Optional[str]
    details: str
    link: Optional[str]


@dataclass(frozen=True)
class _HotelPage:
    cards: Tuple[_RawHotelCard, ...]


class _HotelSource(Protocol):
    def fetch(
        self,
        query: HotelQuery,
        applied: AppliedHotelFilters,
        limit: int,
    ) -> _HotelPage: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


def build_applied_filters(query: HotelQuery) -> AppliedHotelFilters:
    chips: list[str] = []
    if query.free_cancellation:
        chips.append("oos=1")
    if query.entire_home:
        chips.extend(("privacy_type=3", "ht_id=201"))

    params = {
        "ss": query.location,
        "checkin": query.check_in.isoformat(),
        "checkout": query.check_out.isoformat(),
        "group_adults": str(query.adults),
        "no_rooms": str(query.rooms),
        "group_children": "0",
        "selected_currency": "EUR",
        "lang": "es",
    }
    if chips:
        params["nflt"] = ";".join(chips)
    return AppliedHotelFilters(
        chips=tuple(chips),
        url=f"{BOOKING_SEARCH_URL}?{urlencode(params)}",
    )


def _normalize_card(card: _RawHotelCard) -> Optional[HotelOffer]:
    if not card.title.strip() or not card.total_price.strip():
        return None
    total_price_eur = parse_price_eur(card.total_price)
    if total_price_eur is None or total_price_eur <= 0:
        return None
    hints = parse_unit_hints(card.details)
    return HotelOffer(
        title=card.title,
        address=card.address,
        total_price=card.total_price,
        total_price_eur=total_price_eur,
        rating=card.rating,
        rating_score=parse_rating(card.rating),
        details=card.details,
        cancellation_evidence=parse_cancellation_evidence(card.details),
        property_type_evidence=parse_property_type_evidence(card.details),
        bedrooms=hints["bedrooms"],
        bathrooms=hints["bathrooms"],
        beds=hints["beds"],
        link=card.link,
    )


def _is_eligible(offer: HotelOffer, query: HotelQuery) -> bool:
    if query.min_rating is not None:
        if offer.rating_score is None or offer.rating_score < query.min_rating:
            return False
    if (
        query.free_cancellation
        and offer.cancellation_evidence is CancellationEvidence.NON_REFUNDABLE
    ):
        return False
    if query.entire_home and offer.property_type_evidence is PropertyTypeEvidence.NOT_ENTIRE_HOME:
        return False
    return True


def _normalized_text(value: Optional[str]) -> str:
    return " ".join((value or "").split()).casefold()


def _sorted_deduplicated_offers(
    offers: Sequence[HotelOffer],
) -> Tuple[HotelOffer, ...]:
    rows = sorted(
        offers,
        key=lambda offer: (
            offer.total_price_eur,
            offer.rating_score is None,
            -(offer.rating_score or 0.0),
            _normalized_text(offer.title),
        ),
    )
    seen: set[tuple[str, str, float]] = set()
    deduplicated: list[HotelOffer] = []
    for offer in rows:
        identity = (
            _normalized_text(offer.title),
            _normalized_text(offer.address),
            offer.total_price_eur,
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(offer)
    return tuple(deduplicated)


def _rank_offers(
    offers: Sequence[HotelOffer],
    top: int,
) -> Tuple[HotelOffer, ...]:
    if top <= 0:
        raise ValueError("top must be positive")
    return _sorted_deduplicated_offers(offers)[:top]


def _run_search(
    queries: Sequence[HotelQuery],
    *,
    top: int,
    source: _HotelSource,
    sleep: Callable[[float], None],
    random_gen: random.Random,
    now: Callable[[], datetime],
) -> HotelSearchReport:
    if not queries:
        raise ValueError("at least one query is required")
    if top <= 0:
        raise ValueError("top must be positive")

    results: list[HotelQueryResult] = []
    fetch_limit = max(top * 3, 24)
    for index, query in enumerate(queries):
        applied = build_applied_filters(query)
        outcome: Optional[HotelQueryResult] = None
        failure: Optional[SearchError] = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                page = source.fetch(query, applied, fetch_limit)
                normalized = tuple(
                    offer for raw in page.cards if (offer := _normalize_card(raw)) is not None
                )
                eligible = tuple(offer for offer in normalized if _is_eligible(offer, query))
                rank_limit = max(top, len(eligible))
                ranked = _rank_offers(
                    eligible,
                    top=rank_limit,
                )
                outcome = HotelQuerySuccess(
                    query=query,
                    applied=applied,
                    raw_count=len(page.cards),
                    eligible_count=len(ranked),
                    offers=ranked[:top],
                )
                break
            except Exception as exc:
                failure = classify_failure(exc, provider="Booking.com")
                source.reset()
                if failure.code in NON_RETRIABLE_CODES:
                    break
                if attempt + 1 < MAX_ATTEMPTS:
                    sleep(retry_backoff_seconds(attempt, random_gen))
        if outcome is None:
            outcome = HotelQueryFailure(
                query=query,
                applied=applied,
                error=failure
                or SearchError(
                    code=SearchErrorCode.FETCH_FAILED,
                    message="Booking.com hotel search failed.",
                ),
            )
        results.append(outcome)
        if index + 1 < len(queries):
            sleep(inter_query_delay_seconds(random_gen))
    return HotelSearchReport(searched_at=now(), queries=tuple(results))


def search_hotels(
    queries: Sequence[HotelQuery],
    *,
    top: int = 8,
) -> HotelSearchReport:
    if not queries:
        raise ValueError("at least one query is required")
    if top <= 0:
        raise ValueError("top must be positive")
    source = _BookingHotelsSource(default_state_dir())
    try:
        return _run_search(
            queries,
            top=top,
            source=source,
            sleep=time.sleep,
            random_gen=random.Random(),
            now=lambda: datetime.now(timezone.utc),
        )
    finally:
        source.close()


def write_hotel_report_atomic(
    report: HotelSearchReport,
    destination: Path,
) -> None:
    write_json_atomic(report.to_dict(), destination)


class _BookingHotelsSource:
    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir
        self._state_path = state_dir / "pw_state_booking.json"
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
            self._context = self._browser.new_context(
                locale="es-ES",
                viewport={"width": 1280, "height": 900},
                user_agent=DESKTOP_USER_AGENT,
                storage_state=storage,
            )
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

    @staticmethod
    def _dismiss_consent(page) -> None:
        for selector in CONSENT_SELECTORS:
            try:
                button = page.locator(selector).first
                if button.count() > 0 and button.is_visible():
                    button.click(timeout=3_000)
                    page.wait_for_timeout(800)
                    return
            except Exception:
                continue

    @staticmethod
    def _clean_link(link: Optional[str]) -> Optional[str]:
        if not link:
            return None
        absolute = urljoin("https://www.booking.com/", link)
        parsed = urlsplit(absolute)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    @classmethod
    def _extract_card(cls, card) -> Optional[_RawHotelCard]:
        title_element = card.query_selector('[data-testid="title"]')
        price_element = card.query_selector('[data-testid="price-and-discounted-price"]')
        if title_element is None:
            return None

        title = title_element.inner_text().strip()
        if not title:
            return None
        total_price = price_element.inner_text().strip() if price_element is not None else ""

        rating_element = card.query_selector('[data-testid="review-score"]')
        address_element = card.query_selector('[data-testid="address-link"]')
        if address_element is None:
            address_element = card.query_selector('[data-testid="address"]')
        link_element = card.query_selector('a[data-testid="title-link"]')

        rating = None
        if rating_element is not None:
            rating_text = rating_element.inner_text()
            rating = rating_text.splitlines()[0].strip() if rating_text else None
        address = address_element.inner_text().strip() if address_element is not None else None
        link = (
            cls._clean_link(link_element.get_attribute("href"))
            if link_element is not None
            else None
        )
        return _RawHotelCard(
            title=title,
            address=address or None,
            total_price=total_price,
            rating=rating or None,
            details=card.inner_text(),
            link=link,
        )

    @staticmethod
    def _has_empty_state(page) -> bool:
        for selector in EMPTY_STATE_SELECTORS:
            try:
                if page.locator(selector).first.is_visible():
                    return True
            except Exception:
                continue
        return False

    def fetch(
        self,
        query: HotelQuery,
        applied: AppliedHotelFilters,
        limit: int,
    ) -> _HotelPage:
        if limit <= 0:
            raise ValueError("limit must be positive")
        page = self._ensure_context().new_page()
        try:
            page.goto(
                applied.url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            self._dismiss_consent(page)
            result_selector = ", ".join((PROPERTY_CARD_SELECTOR,) + EMPTY_STATE_SELECTORS)
            page.locator(result_selector).first.wait_for(timeout=20_000)
            provider_cards = page.query_selector_all(PROPERTY_CARD_SELECTOR)
            if not provider_cards:
                if self._has_empty_state(page):
                    return _HotelPage(cards=())
                raise RuntimeError("Booking results page has no recognized result state")

            cards: list[_RawHotelCard] = []
            for provider_card in provider_cards[:limit]:
                try:
                    normalized = self._extract_card(provider_card)
                    if normalized is not None:
                        cards.append(normalized)
                except Exception:
                    continue
            if not cards:
                raise RuntimeError("Booking property cards could not be parsed")
            return _HotelPage(cards=tuple(cards))
        finally:
            with contextlib.suppress(Exception):
                page.close()

    def _persist_state(self) -> None:
        if self._context is None:
            return
        self._state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(".json.tmp")
        try:
            self._context.storage_state(path=str(temporary))
            os.replace(temporary, self._state_path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()

    def _teardown(self) -> None:
        for obj in (self._context, self._browser):
            if obj is not None:
                with contextlib.suppress(Exception):
                    obj.close()
        if self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()
        self._pw = self._browser = self._context = None

    def reset(self) -> None:
        with contextlib.suppress(Exception):
            self._persist_state()
        self._teardown()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._persist_state()
        self._teardown()
