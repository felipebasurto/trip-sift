from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone

from viajante.models import DateCalendarReport, DatePriceRow, SearchError, SearchErrorCode

REPORT_KEYS = {
    "schema_version",
    "searched_at",
    "currency",
    "locale",
    "origin",
    "destination",
    "from",
    "to",
    "fetch_backend",
    "fetch_ms",
    "days",
}
DAY_KEYS = {"date", "price_eur", "airline", "stops_count", "status"}
DAY_ERROR_KEYS = DAY_KEYS | {"error"}
ERROR_KEYS = {"code", "message"}
DATE_FETCH_BACKENDS = {"calendar", "sweep"}
FORBIDDEN_KEYS = {"co2", "co2_kg", "emissions", "carbon"}


def _report() -> DateCalendarReport:
    return DateCalendarReport(
        searched_at=datetime(2026, 8, 11, 10, 32, 0, tzinfo=timezone.utc),
        origin="MAD",
        destination="BCN",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        days=(
            DatePriceRow(
                departure_date=date(2026, 9, 1),
                price_eur=39.0,
                airline="Vueling",
                stops_count=0,
            ),
            DatePriceRow(
                departure_date=date(2026, 9, 2),
                status="error",
                error=SearchError(
                    code=SearchErrorCode.FETCH_FAILED,
                    message="Google Flights search failed after 3 attempts.",
                ),
            ),
        ),
        fetch_backend="calendar",
        fetch_ms=1200,
    )


class DatesJsonContractTests(unittest.TestCase):
    """A renamed or dropped key is a breaking change for anyone reading --save output."""

    def setUp(self) -> None:
        self.data = _report().to_dict()

    def test_report_keys_are_exactly_the_documented_set(self) -> None:
        self.assertEqual(set(self.data), REPORT_KEYS)

    def test_day_shapes_are_exact(self) -> None:
        priced, failed = self.data["days"]
        self.assertEqual(set(priced), DAY_KEYS)
        self.assertEqual(set(failed), DAY_ERROR_KEYS)
        self.assertEqual(set(failed["error"]), ERROR_KEYS)

    def test_declared_constants_are_stable(self) -> None:
        self.assertEqual(self.data["schema_version"], 1)
        self.assertEqual(self.data["currency"], "EUR")
        self.assertEqual(self.data["locale"], "en")
        self.assertEqual(self.data["origin"], "MAD")
        self.assertEqual(self.data["destination"], "BCN")
        self.assertEqual(self.data["from"], "2026-09-01")
        self.assertEqual(self.data["to"], "2026-09-02")
        self.assertEqual(self.data["fetch_backend"], "calendar")
        self.assertEqual(self.data["fetch_ms"], 1200)

    def test_schema_version_stays_1(self) -> None:
        self.assertEqual(self.data["schema_version"], 1)

    def test_fetch_backend_is_in_the_closed_set(self) -> None:
        self.assertIn(self.data["fetch_backend"], DATE_FETCH_BACKENDS)
        sweep = DateCalendarReport(
            searched_at=datetime(2026, 8, 11, 10, 32, 0),
            origin="MAD",
            destination="BCN",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 1),
            days=(),
            fetch_backend="sweep",
        )
        self.assertIn(sweep.to_dict()["fetch_backend"], DATE_FETCH_BACKENDS)

    def test_forbidden_keys_are_absent(self) -> None:
        blob = json.dumps(self.data)
        for key in FORBIDDEN_KEYS:
            self.assertNotIn(f'"{key}"', blob)

    def test_timestamp_is_utc_iso_with_a_trailing_z(self) -> None:
        self.assertEqual(self.data["searched_at"], "2026-08-11T10:32:00Z")

    def test_the_whole_report_is_json_serialisable(self) -> None:
        json.loads(json.dumps(self.data, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
