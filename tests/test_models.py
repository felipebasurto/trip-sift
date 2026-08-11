from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone

from trip_sift.models import (
    FlightOffer,
    FlightQuery,
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


if __name__ == "__main__":
    unittest.main()
