from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from random import Random
from typing import List, Sequence, Tuple, Union
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import trip_sift.hotels as hotels_module
from trip_sift.hotels import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_JITTER_SECONDS,
    MAX_ATTEMPTS,
    REQUEST_DELAY_SECONDS,
    REQUEST_JITTER_SECONDS,
    _HotelPage,
    _RawHotelCard,
    _is_eligible,
    _normalize_card,
    _rank_offers,
    _run_search,
    build_applied_filters,
    search_hotels,
    write_hotel_report_atomic,
)
from trip_sift.models import (
    AppliedHotelFilters,
    CancellationEvidence,
    HotelOffer,
    HotelQuery,
    HotelQueryFailure,
    HotelQuerySuccess,
    HotelSearchReport,
    PropertyTypeEvidence,
    SearchErrorCode,
)


ScriptedResponse = Union[_HotelPage, Exception]


class FakeSource:
    def __init__(self, responses: Sequence[ScriptedResponse]) -> None:
        self.responses = list(responses)
        self.fetch_calls: List[Tuple[HotelQuery, AppliedHotelFilters, int]] = []
        self.reset_calls = 0
        self.closed = False

    def fetch(
        self,
        query: HotelQuery,
        applied: AppliedHotelFilters,
        limit: int,
    ) -> _HotelPage:
        self.fetch_calls.append((query, applied, limit))
        if not self.responses:
            raise RuntimeError("missing fake response")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def reset(self) -> None:
        self.reset_calls += 1

    def close(self) -> None:
        self.closed = True


def query(**overrides: object) -> HotelQuery:
    values = {
        "location": "Lisboa",
        "check_in": date(2026, 12, 4),
        "check_out": date(2026, 12, 8),
        "adults": 2,
        "rooms": 1,
        "min_rating": None,
        "entire_home": False,
        "free_cancellation": True,
    }
    values.update(overrides)
    return HotelQuery(**values)


def card(
    *,
    title: str = "Casa Azul",
    address: str | None = "Centro, Lisboa",
    total_price: str = "400 €",
    rating: str | None = "Puntuación: 8,7",
    details: str = "Cancelación gratis · Apartamento entero · 2 dormitorios · 1 baño · 3 camas",
    link: str | None = "https://www.booking.com/hotel/pt/casa-azul.html",
) -> _RawHotelCard:
    return _RawHotelCard(
        title=title,
        address=address,
        total_price=total_price,
        rating=rating,
        details=details,
        link=link,
    )


def offer(
    *,
    title: str = "Casa Azul",
    address: str | None = "Centro, Lisboa",
    total_price_eur: float = 400.0,
    rating_score: float | None = 8.7,
    cancellation: CancellationEvidence = CancellationEvidence.FREE,
    property_type: PropertyTypeEvidence = PropertyTypeEvidence.ENTIRE_HOME,
) -> HotelOffer:
    return HotelOffer(
        title=title,
        address=address,
        total_price=f"{total_price_eur:g} €",
        total_price_eur=total_price_eur,
        rating=None if rating_score is None else f"{rating_score:g}",
        rating_score=rating_score,
        details="details",
        cancellation_evidence=cancellation,
        property_type_evidence=property_type,
        bedrooms=None,
        bathrooms=None,
        beds=None,
        link=None,
    )


class AppliedFiltersTests(unittest.TestCase):
    def test_provider_pacing_constants(self) -> None:
        self.assertEqual(
            (
                REQUEST_DELAY_SECONDS,
                REQUEST_JITTER_SECONDS,
                MAX_ATTEMPTS,
                BACKOFF_BASE_SECONDS,
                BACKOFF_JITTER_SECONDS,
            ),
            (4.5, 1.5, 3, 8.0, 3.0),
        )

    def test_default_url_and_free_cancellation_chip(self) -> None:
        applied = build_applied_filters(query())
        params = parse_qs(urlparse(applied.url).query)

        self.assertEqual(applied.chips, ("oos=1",))
        self.assertEqual(
            params,
            {
                "ss": ["Lisboa"],
                "checkin": ["2026-12-04"],
                "checkout": ["2026-12-08"],
                "group_adults": ["2"],
                "no_rooms": ["1"],
                "group_children": ["0"],
                "selected_currency": ["EUR"],
                "lang": ["es"],
                "nflt": ["oos=1"],
            },
        )

    def test_non_refundable_opt_in_has_no_filter_chip(self) -> None:
        applied = build_applied_filters(query(free_cancellation=False))

        self.assertEqual(applied.chips, ())
        self.assertNotIn("nflt", parse_qs(urlparse(applied.url).query))

    def test_entire_home_uses_exact_chips(self) -> None:
        applied = build_applied_filters(query(entire_home=True))

        self.assertEqual(
            applied.chips,
            ("oos=1", "privacy_type=3", "ht_id=201"),
        )
        self.assertEqual(
            parse_qs(urlparse(applied.url).query)["nflt"],
            ["oos=1;privacy_type=3;ht_id=201"],
        )


class PureHotelLogicTests(unittest.TestCase):
    def test_normalize_card_preserves_raw_values_and_parses_details(self) -> None:
        normalized = _normalize_card(card())

        assert normalized is not None
        self.assertEqual(normalized.total_price, "400 €")
        self.assertEqual(normalized.total_price_eur, 400.0)
        self.assertEqual(normalized.rating, "Puntuación: 8,7")
        self.assertEqual(normalized.rating_score, 8.7)
        self.assertEqual(normalized.details, card().details)
        self.assertEqual(normalized.cancellation_evidence, CancellationEvidence.FREE)
        self.assertEqual(
            normalized.property_type_evidence,
            PropertyTypeEvidence.ENTIRE_HOME,
        )
        self.assertEqual(
            (normalized.bedrooms, normalized.bathrooms, normalized.beds),
            (2, 1, 3),
        )

    def test_rating_is_never_parsed_from_card_details(self) -> None:
        normalized = _normalize_card(
            card(rating=None, details="Puntuación: 9,9 · Cancelación gratis")
        )

        assert normalized is not None
        self.assertIsNone(normalized.rating_score)

    def test_invalid_prices_are_dropped(self) -> None:
        for price in ("", "consultar", "0 €", "-20 €"):
            with self.subTest(price=price):
                self.assertIsNone(_normalize_card(card(total_price=price)))

    def test_strict_minimum_rating_rejects_unknown_and_low_scores(self) -> None:
        strict_query = query(min_rating=8.0)

        self.assertFalse(_is_eligible(offer(rating_score=None), strict_query))
        self.assertFalse(_is_eligible(offer(rating_score=7.9), strict_query))
        self.assertTrue(_is_eligible(offer(rating_score=8.0), strict_query))

    def test_requested_evidence_rejects_only_explicit_contradictions(self) -> None:
        strict_query = query(entire_home=True, free_cancellation=True)

        self.assertFalse(
            _is_eligible(
                offer(cancellation=CancellationEvidence.NON_REFUNDABLE),
                strict_query,
            )
        )
        self.assertFalse(
            _is_eligible(
                offer(property_type=PropertyTypeEvidence.NOT_ENTIRE_HOME),
                strict_query,
            )
        )
        self.assertTrue(
            _is_eligible(
                offer(
                    cancellation=CancellationEvidence.UNKNOWN,
                    property_type=PropertyTypeEvidence.UNKNOWN,
                ),
                strict_query,
            )
        )

    def test_rank_deduplicates_normalized_identity_and_sorts_ties(self) -> None:
        ranked = _rank_offers(
            (
                offer(title="Beta", total_price_eur=200, rating_score=None),
                offer(title="alpha", total_price_eur=200, rating_score=8.5),
                offer(
                    title=" ALPHA ",
                    address="  Centro,   Lisboa ",
                    total_price_eur=200,
                    rating_score=9.0,
                ),
                offer(title="Cheap", total_price_eur=150, rating_score=7.0),
            ),
            top=3,
        )

        self.assertEqual([row.title for row in ranked], ["Cheap", "ALPHA", "Beta"])
        with self.assertRaises(ValueError):
            _rank_offers((), top=0)


class HotelOrchestrationTests(unittest.TestCase):
    def test_retries_same_applied_filters_then_returns_typed_failure(self) -> None:
        hotel_query = query(entire_home=True)
        source = FakeSource([RuntimeError("blocked")] * MAX_ATTEMPTS)
        sleeps: List[float] = []
        expected_random = Random(7)
        expected_backoffs = [
            BACKOFF_BASE_SECONDS * (2**attempt)
            + expected_random.uniform(0, BACKOFF_JITTER_SECONDS)
            for attempt in range(MAX_ATTEMPTS - 1)
        ]

        report = _run_search(
            (hotel_query,),
            top=5,
            source=source,
            sleep=sleeps.append,
            random_gen=Random(7),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        self.assertEqual(len(source.fetch_calls), MAX_ATTEMPTS)
        self.assertEqual(source.reset_calls, MAX_ATTEMPTS)
        first_applied = source.fetch_calls[0][1]
        self.assertTrue(all(call[1] is first_applied for call in source.fetch_calls))
        self.assertEqual(
            first_applied.chips,
            ("oos=1", "privacy_type=3", "ht_id=201"),
        )
        self.assertTrue(all(call[2] == 24 for call in source.fetch_calls))
        self.assertEqual(sleeps, expected_backoffs)
        result = report.queries[0]
        self.assertIsInstance(result, HotelQueryFailure)
        assert isinstance(result, HotelQueryFailure)
        self.assertEqual(result.error.code, SearchErrorCode.FETCH_FAILED)
        self.assertEqual(
            result.error.message,
            "Booking.com hotel search failed after 3 attempts.",
        )

    def test_two_queries_sleep_once_between_queries(self) -> None:
        source = FakeSource([_HotelPage(cards=()), _HotelPage(cards=())])
        sleeps: List[float] = []
        expected = REQUEST_DELAY_SECONDS + Random(11).uniform(
            0, REQUEST_JITTER_SECONDS
        )

        _run_search(
            (query(), query(location="Porto")),
            top=8,
            source=source,
            sleep=sleeps.append,
            random_gen=Random(11),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        self.assertEqual(sleeps, [expected])

    def test_explicit_empty_page_is_success(self) -> None:
        source = FakeSource([_HotelPage(cards=())])

        report = _run_search(
            (query(),),
            top=8,
            source=source,
            sleep=lambda _: None,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        result = report.queries[0]
        self.assertIsInstance(result, HotelQuerySuccess)
        assert isinstance(result, HotelQuerySuccess)
        self.assertEqual((result.raw_count, result.eligible_count), (0, 0))
        self.assertEqual(result.offers, ())

    def test_counts_use_raw_cards_and_deduplicated_eligible_offers(self) -> None:
        source = FakeSource(
            [
                _HotelPage(
                    cards=(
                        card(title="Cheap", total_price="100 €"),
                        card(title="Cheap", total_price="100 €"),
                        card(title="Second", total_price="200 €"),
                        card(title="Broken", total_price="consultar"),
                    )
                )
            ]
        )

        report = _run_search(
            (query(),),
            top=1,
            source=source,
            sleep=lambda _: None,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        result = report.queries[0]
        assert isinstance(result, HotelQuerySuccess)
        self.assertEqual(result.raw_count, 4)
        self.assertEqual(result.eligible_count, 2)
        self.assertEqual([row.title for row in result.offers], ["Cheap"])
        self.assertEqual(source.fetch_calls[0][2], 24)

    def test_search_validates_before_source_construction(self) -> None:
        with patch("trip_sift.hotels._BookingHotelsSource") as source_class:
            with self.assertRaises(ValueError):
                search_hotels(())
            with self.assertRaises(ValueError):
                search_hotels((query(),), top=0)

        source_class.assert_not_called()

    def test_search_always_closes_source(self) -> None:
        source = FakeSource([RuntimeError("blocked")] * MAX_ATTEMPTS)

        with (
            patch("trip_sift.hotels._BookingHotelsSource", return_value=source),
            patch("trip_sift.hotels.time.sleep"),
        ):
            report = search_hotels((query(),))

        self.assertTrue(source.closed)
        self.assertIsInstance(report.queries[0], HotelQueryFailure)

    def test_report_writer_delegates_to_atomic_storage(self) -> None:
        report = HotelSearchReport(
            searched_at=datetime(2026, 8, 10, 10, 0, 0),
            queries=(),
        )
        destination = Path("hotels.json")

        with patch("trip_sift.hotels.write_json_atomic") as writer:
            write_hotel_report_atomic(report, destination)

        writer.assert_called_once_with(report.to_dict(), destination)

    def test_report_writer_produces_json_atomically(self) -> None:
        report = HotelSearchReport(
            searched_at=datetime(2026, 8, 10, 10, 0, 0),
            queries=(),
        )

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "nested" / "hotels.json"
            write_hotel_report_atomic(report, destination)

            self.assertTrue(destination.exists())
            self.assertFalse(destination.with_suffix(".json.tmp").exists())
            self.assertIn('"provider": "booking.com"', destination.read_text())

    def test_module_has_no_city_specific_or_private_policy(self) -> None:
        source = Path(hotels_module.__file__).read_text(encoding="utf-8").casefold()

        for forbidden in ("praga", "prague", "median", "suburb", "tram"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
