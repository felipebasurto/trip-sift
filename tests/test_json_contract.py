from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone

from trip_sift.models import (
    FlightOffer,
    FlightQuery,
    QueryFailure,
    QuerySuccess,
    SearchError,
    SearchErrorCode,
    SearchReport,
)

REPORT_KEYS = {"schema_version", "searched_at", "currency", "locale", "queries"}
QUERY_KEYS = {"origin", "destination", "departure_date", "max_stops"}
SUCCESS_KEYS = {"status", "query", "raw_count", "offers"}
FAILURE_KEYS = {"status", "query", "error"}
OFFER_KEYS = {
    "airline",
    "departure",
    "arrival",
    "price",
    "price_eur",
    "duration",
    "duration_hours",
    "stops",
    "stops_count",
    "baggage_buffer_eur",
    "needs_bag_verify",
}
ERROR_KEYS = {"code", "message"}


def _report() -> SearchReport:
    query = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1)
    offer = FlightOffer(
        airline="Vueling",
        departure="07:15",
        arrival="08:40",
        price="€39",
        price_eur=39.0,
        duration="1 hr 25 min",
        duration_hours=1.4166666666666667,
        stops="Nonstop",
        stops_count=0,
        baggage_buffer_eur=70,
        needs_bag_verify=True,
    )
    return SearchReport(
        searched_at=datetime(2026, 8, 11, 10, 32, 0, tzinfo=timezone.utc),
        queries=(
            QuerySuccess(query=query, raw_count=24, offers=(offer,)),
            QueryFailure(
                query=query,
                error=SearchError(
                    code=SearchErrorCode.NO_RESULTS,
                    message="Google Flights returned no flights for this route and date.",
                ),
            ),
        ),
    )


class JsonContractTests(unittest.TestCase):
    """A renamed or dropped key is a breaking change for anyone reading --save output."""

    def setUp(self) -> None:
        self.data = _report().to_dict()

    def test_report_keys_are_exactly_the_documented_set(self) -> None:
        self.assertEqual(set(self.data), REPORT_KEYS)

    def test_success_and_failure_shapes_are_exact(self) -> None:
        success, failure = self.data["queries"]
        self.assertEqual(set(success), SUCCESS_KEYS)
        self.assertEqual(set(failure), FAILURE_KEYS)
        self.assertEqual(set(success["query"]), QUERY_KEYS)
        self.assertEqual(set(success["offers"][0]), OFFER_KEYS)
        self.assertEqual(set(failure["error"]), ERROR_KEYS)

    def test_declared_constants_are_stable(self) -> None:
        self.assertEqual(self.data["schema_version"], 1)
        self.assertEqual(self.data["currency"], "EUR")
        self.assertEqual(self.data["locale"], "en")

    def test_timestamp_is_utc_iso_with_a_trailing_z(self) -> None:
        self.assertEqual(self.data["searched_at"], "2026-08-11T10:32:00Z")

    def test_a_nonstop_offer_carries_a_real_stop_count(self) -> None:
        offer = self.data["queries"][0]["offers"][0]
        self.assertEqual(offer["stops_count"], 0)
        self.assertIsNotNone(offer["stops"])

    def test_error_codes_serialise_as_their_string_values(self) -> None:
        self.assertEqual(self.data["queries"][1]["error"]["code"], "no_results")

    def test_the_whole_report_is_json_serialisable(self) -> None:
        json.loads(json.dumps(self.data, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
