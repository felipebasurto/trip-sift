from __future__ import annotations

import json
import unittest
from datetime import date, datetime

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
        self.assertEqual(data["locale"], "es")
        self.assertEqual(data["queries"][0]["status"], "error")
        self.assertEqual(data["queries"][0]["error"]["code"], "fetch_failed")
        json.dumps(data)


if __name__ == "__main__":
    unittest.main()
