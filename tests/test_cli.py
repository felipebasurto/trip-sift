from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from trip_sift.cli import _print_report, main
from trip_sift.models import (
    FlightOffer,
    FlightQuery,
    QueryFailure,
    QuerySuccess,
    SearchError,
    SearchErrorCode,
    SearchReport,
)

QUERY = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1)
SEARCHED_AT = datetime(2026, 8, 10, 9, 0, 0)


def _offer(
    *,
    airline: Optional[str] = "Example Air",
    departure: Optional[str] = "08:40",
    arrival: Optional[str] = "11:30",
    duration: Optional[str] = "2 h 50 min",
    duration_hours: Optional[float] = 2.8333333333333335,
    stops: Optional[str] = "Nonstop",
    stops_count: Optional[int] = 0,
    price_eur: float = 129.0,
    baggage_buffer_eur: int = 0,
    needs_bag_verify: bool = False,
) -> FlightOffer:
    return FlightOffer(
        airline=airline,
        departure=departure,
        arrival=arrival,
        price=f"€{price_eur:.0f}",
        price_eur=price_eur,
        duration=duration,
        duration_hours=duration_hours,
        stops=stops,
        stops_count=stops_count,
        baggage_buffer_eur=baggage_buffer_eur,
        needs_bag_verify=needs_bag_verify,
    )


def _report(*offers: FlightOffer) -> SearchReport:
    return SearchReport(
        searched_at=SEARCHED_AT,
        queries=(QuerySuccess(query=QUERY, raw_count=3, offers=offers or (_offer(),)),),
    )


def _rendered(report: SearchReport) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _print_report(report)
    return buffer.getvalue()


class CliTests(unittest.TestCase):
    def test_validation_before_search(self) -> None:
        with patch("trip_sift.cli.search_flights") as search:
            code = main(["flights", "BADROUTE"])
            self.assertEqual(code, 1)
            search.assert_not_called()

    def test_invalid_max_stops(self) -> None:
        with patch("trip_sift.cli.search_flights") as search:
            with redirect_stdout(io.StringIO()):
                code = main(["flights", "MAD-BCN:2026-09-01", "--max-stops", "3"])
            self.assertEqual(code, 1)
            search.assert_not_called()

    def test_prints_results(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_report()):
            with patch("trip_sift.cli._print_report") as printer:
                code = main(["flights", "MAD-BCN:2026-09-01"])
                self.assertEqual(code, 0)
                printer.assert_called_once()

    def test_save_only_when_requested(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_report()):
            with patch("trip_sift.cli.write_report_atomic") as writer:
                with patch("trip_sift.cli._print_report"):
                    main(["flights", "MAD-BCN:2026-09-01"])
                writer.assert_not_called()

    def test_atomic_save(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_report()):
            with patch("trip_sift.cli._print_report"), redirect_stdout(io.StringIO()):
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / "out.json"
                    code = main(["flights", "MAD-BCN:2026-09-01", "--save", str(out)])
                    self.assertEqual(code, 0)
                    self.assertTrue(out.exists())
                    self.assertFalse(out.with_suffix(".json.tmp").exists())
                    data = json.loads(out.read_text(encoding="utf-8"))
                    self.assertEqual(data["schema_version"], 1)

    def test_failed_search_returns_nonzero(self) -> None:
        report = SearchReport(
            searched_at=SEARCHED_AT,
            queries=(
                QueryFailure(
                    query=QUERY,
                    error=SearchError(
                        SearchErrorCode.FETCH_FAILED,
                        "Google Flights search failed after 3 attempts.",
                    ),
                ),
            ),
        )
        with patch("trip_sift.cli.search_flights", return_value=report):
            with patch("trip_sift.cli._print_report"):
                self.assertEqual(main(["flights", "MAD-BCN:2026-09-01"]), 2)

    def test_partial_failure_returns_three(self) -> None:
        report = SearchReport(
            searched_at=SEARCHED_AT,
            queries=(
                QuerySuccess(query=QUERY, raw_count=3, offers=(_offer(),)),
                QueryFailure(
                    query=QUERY,
                    error=SearchError(SearchErrorCode.FETCH_FAILED, "boom"),
                ),
            ),
        )
        with patch("trip_sift.cli.search_flights", return_value=report):
            with patch("trip_sift.cli._print_report"):
                self.assertEqual(main(["flights", "MAD-BCN:2026-09-01"]), 3)

    def test_baggage_buffer_flag_reaches_the_search(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_report()) as search:
            with patch("trip_sift.cli._print_report"):
                main(["flights", "MAD-BCN:2026-09-01", "--baggage-buffer", "0"])
        self.assertEqual(search.call_args.kwargs["buffer_eur"], 0)

    def test_negative_baggage_buffer_is_rejected_before_searching(self) -> None:
        with patch("trip_sift.cli.search_flights") as search:
            self.assertEqual(
                main(["flights", "MAD-BCN:2026-09-01", "--baggage-buffer", "-1"]), 1
            )
            search.assert_not_called()


class ReportRenderingTests(unittest.TestCase):
    def test_missing_fields_never_render_as_none(self) -> None:
        blank = _offer(
            airline=None,
            departure=None,
            arrival=None,
            duration=None,
            duration_hours=None,
            stops=None,
            stops_count=None,
        )
        output = _rendered(_report(blank))
        self.assertNotIn("None", output)
        self.assertIn("? -> ?", output)

    def test_stops_are_shown(self) -> None:
        output = _rendered(_report(_offer(stops_count=0), _offer(stops_count=2)))
        self.assertIn("direct", output)
        self.assertIn("2 stops", output)

    def test_ranking_note_shows_the_effective_total(self) -> None:
        low_cost = _offer(
            airline="Ryanair", price_eur=50.0, baggage_buffer_eur=70, needs_bag_verify=True
        )
        self.assertIn("(+70 bag = 120 € ranked)", _rendered(_report(low_cost)))

    def test_disabled_buffer_still_flags_the_carrier(self) -> None:
        low_cost = _offer(
            airline="Ryanair", price_eur=50.0, baggage_buffer_eur=0, needs_bag_verify=True
        )
        output = _rendered(_report(low_cost))
        self.assertIn("[baggage?]", output)
        self.assertNotIn("ranked", output)

    def test_long_airline_names_are_truncated_visibly(self) -> None:
        output = _rendered(_report(_offer(airline="A" * 60)))
        self.assertIn("…", output)
        self.assertNotIn("A" * 41, output)


if __name__ == "__main__":
    unittest.main()
