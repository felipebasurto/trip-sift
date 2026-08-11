from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone

from trip_sift.models import (
    AppliedHotelFilters,
    CancellationEvidence,
    FlightOffer,
    FlightQuery,
    HotelOffer,
    HotelQuery,
    HotelQueryFailure,
    HotelQuerySuccess,
    HotelSearchReport,
    PropertyTypeEvidence,
    QueryFailure,
    QuerySuccess,
    SearchError,
    SearchErrorCode,
    SearchReport,
)


class ModelTests(unittest.TestCase):
    def test_flight_query_validation(self) -> None:
        q = FlightQuery("mad", "bcn", date(2026, 9, 1), max_stops=1)
        self.assertEqual(q.origin, "MAD")
        self.assertEqual(q.destination, "BCN")
        with self.assertRaises(ValueError):
            FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=2)

    def test_flight_offer_requires_positive_price(self) -> None:
        with self.assertRaises(ValueError):
            FlightOffer(
                airline="Air",
                departure="08:00",
                arrival="09:00",
                price="0 €",
                price_eur=0.0,
                duration="1 h",
                duration_hours=1.0,
                stops="Directo",
                stops_count=0,
                baggage_buffer_eur=0,
                needs_bag_verify=False,
            )

    def test_query_result_variants(self) -> None:
        query = FlightQuery("MAD", "BCN", date(2026, 9, 1))
        offer = FlightOffer(
            airline="Air",
            departure="08:00",
            arrival="09:00",
            price="100 €",
            price_eur=100.0,
            duration="1 h",
            duration_hours=1.0,
            stops="Directo",
            stops_count=0,
            baggage_buffer_eur=0,
            needs_bag_verify=False,
        )
        success = QuerySuccess(query=query, raw_count=1, offers=(offer,))
        failure = QueryFailure(
            query=query,
            error=SearchError(SearchErrorCode.FETCH_FAILED, "failed"),
        )
        self.assertEqual(success.status, "ok")
        self.assertEqual(failure.status, "error")

    def test_search_report_json(self) -> None:
        query = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=0)
        report = SearchReport(
            searched_at=datetime(2026, 8, 10, 9, 20, 0),
            queries=(
                QueryFailure(
                    query=query,
                    error=SearchError(
                        SearchErrorCode.FETCH_FAILED,
                        "Google Flights search failed after 3 attempts.",
                    ),
                ),
            ),
        )
        data = report.to_dict()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["locale"], "en")
        self.assertEqual(data["queries"][0]["status"], "error")
        self.assertEqual(data["queries"][0]["error"]["code"], "fetch_failed")
        json.dumps(data)


class ReportTimestampTests(unittest.TestCase):
    def test_offset_aware_timestamps_are_converted_to_real_utc(self) -> None:
        madrid = datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        report = SearchReport(searched_at=madrid, queries=())
        self.assertEqual(report.to_dict()["searched_at"], "2026-08-10T07:00:00Z")

    def test_naive_timestamps_are_treated_as_utc(self) -> None:
        report = SearchReport(searched_at=datetime(2026, 8, 10, 9, 0, 0), queries=())
        self.assertEqual(report.to_dict()["searched_at"], "2026-08-10T09:00:00Z")


class BaggageInvariantTests(unittest.TestCase):
    def _offer(self, *, buffer_eur: int, needs_verify: bool) -> FlightOffer:
        return FlightOffer(
            airline="Ryanair",
            departure="08:00",
            arrival="09:00",
            price="€50",
            price_eur=50.0,
            duration="1 hr",
            duration_hours=1.0,
            stops="Nonstop",
            stops_count=0,
            baggage_buffer_eur=buffer_eur,
            needs_bag_verify=needs_verify,
        )

    def test_a_buffer_cannot_be_applied_without_flagging_the_carrier(self) -> None:
        with self.assertRaises(ValueError):
            self._offer(buffer_eur=70, needs_verify=False)

    def test_a_flagged_carrier_may_carry_no_buffer(self) -> None:
        self.assertEqual(self._offer(buffer_eur=0, needs_verify=True).baggage_buffer_eur, 0)

    def test_negative_buffers_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._offer(buffer_eur=-1, needs_verify=True)


class HotelModelTests(unittest.TestCase):
    def test_hotel_query_validation_and_nights(self) -> None:
        q = HotelQuery("  Praga  ", date(2026, 12, 4), date(2026, 12, 8))
        self.assertEqual(q.location, "Praga")
        q2 = HotelQuery("New   York", date(2026, 12, 4), date(2026, 12, 8))
        self.assertEqual(q2.location, "New York")
        self.assertEqual(q.nights, 4)
        self.assertTrue(q.free_cancellation)
        with self.assertRaises(ValueError):
            HotelQuery("   ", date(2026, 12, 4), date(2026, 12, 8))
        with self.assertRaises(ValueError):
            HotelQuery("Praga", date(2026, 12, 8), date(2026, 12, 4))
        with self.assertRaises(ValueError):
            HotelQuery("Praga", date(2026, 12, 4), date(2026, 12, 8), adults=0)
        with self.assertRaises(ValueError):
            HotelQuery("Praga", date(2026, 12, 4), date(2026, 12, 8), rooms=0)
        with self.assertRaises(ValueError):
            HotelQuery(
                "Praga",
                date(2026, 12, 4),
                date(2026, 12, 8),
                min_rating=10.1,
            )

    def test_hotel_query_to_dict(self) -> None:
        q = HotelQuery(
            "Praga",
            date(2026, 12, 4),
            date(2026, 12, 8),
            adults=2,
            rooms=1,
            min_rating=8.0,
            entire_home=True,
            free_cancellation=False,
        )
        data = q.to_dict()
        self.assertEqual(data["location"], "Praga")
        self.assertEqual(data["check_in"], "2026-12-04")
        self.assertEqual(data["check_out"], "2026-12-08")
        self.assertEqual(data["nights"], 4)
        self.assertEqual(data["min_rating"], 8.0)
        self.assertTrue(data["entire_home"])
        self.assertFalse(data["free_cancellation"])

    def test_hotel_offer_validation(self) -> None:
        with self.assertRaises(ValueError):
            HotelOffer(
                title="   ",
                address=None,
                total_price="100 €",
                total_price_eur=100.0,
                rating=None,
                rating_score=None,
                details="",
                cancellation_evidence=CancellationEvidence.UNKNOWN,
                property_type_evidence=PropertyTypeEvidence.UNKNOWN,
                bedrooms=None,
                bathrooms=None,
                beds=None,
                link=None,
            )
        with self.assertRaises(ValueError):
            HotelOffer(
                title="Hotel",
                address=None,
                total_price="0 €",
                total_price_eur=0.0,
                rating=None,
                rating_score=None,
                details="",
                cancellation_evidence=CancellationEvidence.UNKNOWN,
                property_type_evidence=PropertyTypeEvidence.UNKNOWN,
                bedrooms=None,
                bathrooms=None,
                beds=None,
                link=None,
            )
        with self.assertRaises(ValueError):
            HotelOffer(
                title="Hotel",
                address=None,
                total_price="100 €",
                total_price_eur=100.0,
                rating="11",
                rating_score=11.0,
                details="",
                cancellation_evidence=CancellationEvidence.UNKNOWN,
                property_type_evidence=PropertyTypeEvidence.UNKNOWN,
                bedrooms=None,
                bathrooms=None,
                beds=None,
                link=None,
            )

    def test_hotel_query_success_count_invariant(self) -> None:
        query = HotelQuery("Praga", date(2026, 12, 4), date(2026, 12, 8))
        applied = AppliedHotelFilters(chips=("free_cancellation",), url="https://example.com")
        offer = HotelOffer(
            title="Hotel Test",
            address="Praga 1",
            total_price="200 €",
            total_price_eur=200.0,
            rating="Puntuación: 8,4",
            rating_score=8.4,
            details="2 dormitorios",
            cancellation_evidence=CancellationEvidence.FREE,
            property_type_evidence=PropertyTypeEvidence.ENTIRE_HOME,
            bedrooms=2,
            bathrooms=1,
            beds=3,
            link="https://booking.com/hotel",
        )
        success = HotelQuerySuccess(
            query=query,
            applied=applied,
            raw_count=10,
            eligible_count=5,
            offers=(offer,),
        )
        self.assertEqual(success.status, "ok")
        with self.assertRaises(ValueError):
            HotelQuerySuccess(
                query=query,
                applied=applied,
                raw_count=1,
                eligible_count=5,
                offers=(offer,),
            )
        offer_two = HotelOffer(
            title="Hotel Two",
            address="Praga 2",
            total_price="150 €",
            total_price_eur=150.0,
            rating=None,
            rating_score=None,
            details="",
            cancellation_evidence=CancellationEvidence.UNKNOWN,
            property_type_evidence=PropertyTypeEvidence.UNKNOWN,
            bedrooms=None,
            bathrooms=None,
            beds=None,
            link=None,
        )
        with self.assertRaises(ValueError):
            HotelQuerySuccess(
                query=query,
                applied=applied,
                raw_count=10,
                eligible_count=1,
                offers=(offer, offer_two),
            )

    def test_hotel_query_result_variants_json(self) -> None:
        query = HotelQuery("Praga", date(2026, 12, 4), date(2026, 12, 8))
        applied = AppliedHotelFilters(chips=("free_cancellation",), url="https://example.com")
        offer = HotelOffer(
            title="Hotel Test",
            address="Praga 1",
            total_price="200 €",
            total_price_eur=200.0,
            rating="8,4",
            rating_score=8.4,
            details="",
            cancellation_evidence=CancellationEvidence.FREE,
            property_type_evidence=PropertyTypeEvidence.UNKNOWN,
            bedrooms=None,
            bathrooms=None,
            beds=None,
            link=None,
        )
        success = HotelQuerySuccess(
            query=query,
            applied=applied,
            raw_count=3,
            eligible_count=2,
            offers=(offer,),
        )
        failure = HotelQueryFailure(
            query=query,
            applied=applied,
            error=SearchError(SearchErrorCode.FETCH_FAILED, "failed"),
        )
        success_data = success.to_dict()
        failure_data = failure.to_dict()
        self.assertEqual(success_data["status"], "ok")
        self.assertEqual(success_data["raw_count"], 3)
        self.assertEqual(success_data["eligible_count"], 2)
        self.assertEqual(
            success_data["offers"][0]["cancellation_evidence"],
            "free",
        )
        self.assertEqual(failure_data["status"], "error")
        self.assertEqual(failure_data["applied"]["url"], "https://example.com")
        json.dumps(success_data)
        json.dumps(failure_data)

    def test_hotel_search_report_json(self) -> None:
        query = HotelQuery("Praga", date(2026, 12, 4), date(2026, 12, 8))
        applied = AppliedHotelFilters(chips=(), url="https://example.com")
        report = HotelSearchReport(
            searched_at=datetime(2026, 8, 10, 9, 20, 0),
            queries=(
                HotelQueryFailure(
                    query=query,
                    applied=applied,
                    error=SearchError(
                        SearchErrorCode.FETCH_FAILED,
                        "Booking search failed.",
                    ),
                ),
            ),
        )
        data = report.to_dict()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["provider"], "booking.com")
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["locale"], "es")
        self.assertEqual(data["price_basis"], "total_stay")
        self.assertEqual(data["searched_at"], "2026-08-10T09:20:00Z")
        self.assertEqual(data["queries"][0]["status"], "error")
        json.dumps(data)


if __name__ == "__main__":
    unittest.main()
