from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from trip_sift.cli import main
from trip_sift.models import (
    FlightOffer,
    FlightQuery,
    QueryFailure,
    QuerySuccess,
    SearchError,
    SearchErrorCode,
    SearchReport,
)


def _sample_report() -> SearchReport:
    query = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1)
    offer = FlightOffer(
        airline="Example Air",
        departure="08:40",
        arrival="11:30",
        price="129 €",
        price_eur=129.0,
        duration="2 h 50 min",
        duration_hours=2.8333333333333335,
        stops="Directo",
        stops_count=0,
        baggage_buffer_eur=0,
        needs_bag_verify=False,
    )
    return SearchReport(
        searched_at=datetime(2026, 8, 10, 9, 0, 0),
        queries=(QuerySuccess(query=query, raw_count=3, offers=(offer,)),),
    )


class CliTests(unittest.TestCase):
    def test_validation_before_search(self) -> None:
        with patch("trip_sift.cli.search_flights") as search:
            code = main(["flights", "BADROUTE"])
            self.assertEqual(code, 1)
            search.assert_not_called()

    def test_invalid_max_stops(self) -> None:
        with patch("trip_sift.cli.search_flights") as search:
            code = main(["flights", "MAD-BCN:2026-09-01", "--max-stops", "3"])
            self.assertEqual(code, 1)
            search.assert_not_called()

    def test_prints_results(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_sample_report()):
            with patch("trip_sift.cli._print_report") as printer:
                code = main(["flights", "MAD-BCN:2026-09-01"])
                self.assertEqual(code, 0)
                printer.assert_called_once()

    def test_save_only_when_requested(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_sample_report()):
            with patch("trip_sift.cli.write_report_atomic") as writer:
                main(["flights", "MAD-BCN:2026-09-01"])
                writer.assert_not_called()

    def test_atomic_save(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_sample_report()):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out.json"
                code = main(["flights", "MAD-BCN:2026-09-01", "--save", str(out)])
                self.assertEqual(code, 0)
                self.assertTrue(out.exists())
                data = json.loads(out.read_text(encoding="utf-8"))
                self.assertEqual(data["schema_version"], 1)

    def test_failed_search_returns_nonzero(self) -> None:
        query = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1)
        report = SearchReport(
            searched_at=datetime(2026, 8, 10, 9, 0, 0),
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
        with patch("trip_sift.cli.search_flights", return_value=report):
            self.assertEqual(main(["flights", "MAD-BCN:2026-09-01"]), 2)


if __name__ == "__main__":
    unittest.main()
