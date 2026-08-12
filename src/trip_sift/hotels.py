"""Hotel eligibility, ranking, and the Booking.com search loop."""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol, Sequence, Tuple

from trip_sift.booking import (
    BookingHotelsSource,
    HotelPage,
    RawHotelCard,
    build_applied_filters,
)
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


class _HotelSource(Protocol):
    def fetch(
        self,
        query: HotelQuery,
        applied: AppliedHotelFilters,
        limit: int,
    ) -> HotelPage: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


def _normalize_card(card: RawHotelCard) -> Optional[HotelOffer]:
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
    html_lang: str = "es",
    currency: str = "EUR",
) -> HotelSearchReport:
    if not queries:
        raise ValueError("at least one query is required")
    if top <= 0:
        raise ValueError("top must be positive")

    results: list[HotelQueryResult] = []
    fetch_limit = max(top * 3, 24)
    for index, query in enumerate(queries):
        applied = build_applied_filters(query, html_lang=html_lang, currency=currency)
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
    return HotelSearchReport(
        searched_at=now(),
        queries=tuple(results),
        locale=html_lang,
        currency=currency,
    )


def search_hotels(
    queries: Sequence[HotelQuery],
    *,
    top: int = 8,
) -> HotelSearchReport:
    if not queries:
        raise ValueError("at least one query is required")
    if top <= 0:
        raise ValueError("top must be positive")
    source = BookingHotelsSource(default_state_dir())
    try:
        return _run_search(
            queries,
            top=top,
            source=source,
            sleep=time.sleep,
            random_gen=random.Random(),
            now=lambda: datetime.now(timezone.utc),
            html_lang=source.config.html_lang,
            currency=source.config.currency,
        )
    finally:
        source.close()


def write_hotel_report_atomic(
    report: HotelSearchReport,
    destination: Path,
) -> None:
    write_json_atomic(report.to_dict(), destination)
