from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone

from trip_sift.models import (
    AppliedHotelFilters,
    CancellationEvidence,
    HotelOffer,
    HotelQuery,
    HotelQueryFailure,
    HotelQuerySuccess,
    HotelSearchReport,
    PropertyTypeEvidence,
    SearchError,
    SearchErrorCode,
)

REPORT_KEYS = {
    "schema_version",
    "provider",
    "searched_at",
    "currency",
    "locale",
    "price_basis",
    "queries",
}
QUERY_KEYS = {
    "location",
    "check_in",
    "check_out",
    "adults",
    "rooms",
    "min_rating",
    "entire_home",
    "free_cancellation",
    "nights",
}
APPLIED_KEYS = {"chips", "url"}
SUCCESS_KEYS = {"status", "query", "applied", "raw_count", "eligible_count", "offers"}
FAILURE_KEYS = {"status", "query", "applied", "error"}
OFFER_KEYS = {
    "title",
    "address",
    "total_price",
    "total_price_eur",
    "rating",
    "rating_score",
    "details",
    "cancellation_evidence",
    "property_type_evidence",
    "bedrooms",
    "bathrooms",
    "beds",
    "link",
}
ERROR_KEYS = {"code", "message"}


def _offer() -> HotelOffer:
    return HotelOffer(
        title="Old Town Apartment",
        address="Prague 1",
        total_price="246 €",
        total_price_eur=246.0,
        rating="8,9",
        rating_score=8.9,
        details="Cancelación gratis. Apartamento entero.",
        cancellation_evidence=CancellationEvidence.FREE,
        property_type_evidence=PropertyTypeEvidence.ENTIRE_HOME,
        bedrooms=1,
        bathrooms=1,
        beds=2,
        link="https://www.booking.com/hotel/cz/example.html",
    )


def _report() -> HotelSearchReport:
    query = HotelQuery("Prague", date(2026, 12, 4), date(2026, 12, 7), min_rating=8.5)
    applied = AppliedHotelFilters(
        chips=("oos=1",),
        url="https://www.booking.com/searchresults.html?ss=Prague",
    )
    return HotelSearchReport(
        searched_at=datetime(2026, 8, 11, 10, 32, 0, tzinfo=timezone.utc),
        queries=(
            HotelQuerySuccess(
                query=query,
                applied=applied,
                raw_count=40,
                eligible_count=12,
                offers=(_offer(),),
            ),
            HotelQueryFailure(
                query=query,
                applied=applied,
                error=SearchError(
                    code=SearchErrorCode.FETCH_FAILED,
                    message="Booking.com hotel search failed after 3 attempts.",
                ),
            ),
        ),
    )


class HotelJsonContractTests(unittest.TestCase):
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
        self.assertEqual(set(success["applied"]), APPLIED_KEYS)
        self.assertEqual(set(success["offers"][0]), OFFER_KEYS)
        self.assertEqual(set(failure["error"]), ERROR_KEYS)

    def test_declared_constants_are_stable(self) -> None:
        self.assertEqual(self.data["schema_version"], 1)
        self.assertEqual(self.data["provider"], "booking.com")
        self.assertEqual(self.data["currency"], "EUR")
        self.assertEqual(self.data["locale"], "es")
        self.assertEqual(self.data["price_basis"], "total_stay")

    def test_timestamp_is_utc_iso_with_a_trailing_z(self) -> None:
        self.assertEqual(self.data["searched_at"], "2026-08-11T10:32:00Z")

    def test_aware_non_utc_timestamp_is_normalized_to_utc(self) -> None:
        report = HotelSearchReport(
            searched_at=datetime(2026, 8, 11, 12, 32, 0, tzinfo=timezone(timedelta(hours=2))),
            queries=(),
        )
        self.assertEqual(report.to_dict()["searched_at"], "2026-08-11T10:32:00Z")

    def test_evidence_enums_serialise_as_their_string_values(self) -> None:
        offer = self.data["queries"][0]["offers"][0]
        self.assertEqual(offer["cancellation_evidence"], "free")
        self.assertEqual(offer["property_type_evidence"], "entire_home")

    def test_error_codes_serialise_as_their_string_values(self) -> None:
        self.assertEqual(self.data["queries"][1]["error"]["code"], "fetch_failed")

    def test_the_whole_report_is_json_serialisable(self) -> None:
        json.loads(json.dumps(self.data, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
