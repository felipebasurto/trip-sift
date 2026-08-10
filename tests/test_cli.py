from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import trip_sift
from trip_sift.cli import main
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


def _sample_hotel_report(
    *,
    offers: tuple[HotelOffer, ...] = (),
    raw_count: int = 5,
    eligible_count: int = 3,
) -> HotelSearchReport:
    query = HotelQuery("Prague", date(2026, 12, 4), date(2026, 12, 7))
    applied = AppliedHotelFilters(chips=("oos=1",), url="https://example.test")
    return HotelSearchReport(
        searched_at=datetime(2026, 8, 10, 9, 0, 0),
        queries=(
            HotelQuerySuccess(
                query=query,
                applied=applied,
                raw_count=raw_count,
                eligible_count=eligible_count,
                offers=offers,
            ),
        ),
    )


def _sample_hotel_offer() -> HotelOffer:
    return HotelOffer(
        title="Old Town Apartment",
        address="Prague 1, Czech Republic",
        total_price="420 €",
        total_price_eur=420.0,
        rating="8.9",
        rating_score=8.9,
        details="Cancelación gratuita · Apartamento entero",
        cancellation_evidence=CancellationEvidence.FREE,
        property_type_evidence=PropertyTypeEvidence.ENTIRE_HOME,
        bedrooms=2,
        bathrooms=1,
        beds=2,
        link="https://www.booking.com/hotel/example.html",
    )


class PublicApiTests(unittest.TestCase):
    def test_exports_hotel_api(self) -> None:
        for name in (
            "FlightQuery",
            "SearchReport",
            "search_flights",
            "HotelQuery",
            "HotelSearchReport",
            "CancellationEvidence",
            "PropertyTypeEvidence",
            "search_hotels",
        ):
            self.assertTrue(hasattr(trip_sift, name), msg=name)
        self.assertEqual(
            set(trip_sift.__all__),
            {
                "FlightQuery",
                "SearchReport",
                "search_flights",
                "HotelQuery",
                "HotelSearchReport",
                "CancellationEvidence",
                "PropertyTypeEvidence",
                "search_hotels",
            },
        )


class HotelCliTests(unittest.TestCase):
    def test_hotels_help_returns_zero_without_search(self) -> None:
        with patch("trip_sift.cli.search_hotels") as search:
            code = main(["hotels", "--help"])
            self.assertEqual(code, 0)
            search.assert_not_called()

    def test_valid_args_build_exact_hotel_query(self) -> None:
        with patch("trip_sift.cli.search_hotels", return_value=_sample_hotel_report()):
            with patch("trip_sift.cli._print_hotel_report"):
                code = main(
                    [
                        "hotels",
                        "Prague",
                        "2026-12-04",
                        "2026-12-07",
                        "--adults",
                        "2",
                        "--rooms",
                        "1",
                        "--top",
                        "5",
                        "--min-rating",
                        "8.0",
                        "--entire-home",
                    ]
                )
                self.assertEqual(code, 0)
                search_hotels = __import__("trip_sift.cli").cli.search_hotels
                search_hotels.assert_called_once()
                queries, kwargs = search_hotels.call_args
                self.assertEqual(kwargs, {"top": 5})
                self.assertEqual(len(queries[0]), 1)
                query = queries[0][0]
                self.assertEqual(
                    query,
                    HotelQuery(
                        location="Prague",
                        check_in=date(2026, 12, 4),
                        check_out=date(2026, 12, 7),
                        adults=2,
                        rooms=1,
                        min_rating=8.0,
                        entire_home=True,
                        free_cancellation=True,
                    ),
                )

    def test_allow_non_refundable_flips_cancellation_only(self) -> None:
        with patch("trip_sift.cli.search_hotels", return_value=_sample_hotel_report()):
            with patch("trip_sift.cli._print_hotel_report"):
                main(
                    [
                        "hotels",
                        "Prague",
                        "2026-12-04",
                        "2026-12-07",
                        "--allow-non-refundable",
                    ]
                )
                query = __import__("trip_sift.cli").cli.search_hotels.call_args[0][0][0]
                self.assertFalse(query.free_cancellation)
                self.assertFalse(query.entire_home)
                self.assertIsNone(query.min_rating)

    def test_validation_before_search(self) -> None:
        cases = [
            ["hotels", "Prague", "not-a-date", "2026-12-07"],
            ["hotels", "Prague", "2026-12-07", "2026-12-04"],
            ["hotels", "Prague", "2026-12-04", "2026-12-04"],
            ["hotels", "   ", "2026-12-04", "2026-12-07"],
            ["hotels", "Prague", "2026-12-04", "2026-12-07", "--adults", "0"],
            ["hotels", "Prague", "2026-12-04", "2026-12-07", "--rooms", "0"],
            ["hotels", "Prague", "2026-12-04", "2026-12-07", "--top", "0"],
            ["hotels", "Prague", "2026-12-04", "2026-12-07", "--min-rating", "11"],
            ["hotels", "Prague", "2026-12-04", "2026-12-07", "--min-rating", "-1"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                with patch("trip_sift.cli.search_hotels") as search:
                    self.assertEqual(main(argv), 1)
                    search.assert_not_called()

    def test_success_output_contract(self) -> None:
        report = _sample_hotel_report(offers=(_sample_hotel_offer(),))
        with patch("trip_sift.cli.search_hotels", return_value=report):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["hotels", "Prague", "2026-12-04", "2026-12-07"])
            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("Prague", output)
            self.assertIn("2026-12-04", output)
            self.assertIn("2026-12-07", output)
            self.assertIn("3 night", output)
            self.assertIn("oos=1", output)
            self.assertIn("total stay", output.casefold())
            self.assertIn("420", output)
            self.assertIn("Old Town Apartment", output)
            self.assertIn("Prague 1, Czech Republic", output)
            self.assertIn("cancellation: free", output.casefold())
            self.assertIn("raw cards: 5", output.casefold())
            self.assertIn("eligible: 3", output.casefold())
            self.assertIn("shown: 1", output.casefold())
            self.assertIn("booking.com", output.casefold())

    def test_entire_home_output_shows_property_evidence(self) -> None:
        query = HotelQuery(
            "Prague",
            date(2026, 12, 4),
            date(2026, 12, 7),
            entire_home=True,
        )
        applied = AppliedHotelFilters(
            chips=("oos=1", "privacy_type=3", "ht_id=201"),
            url="https://example.test",
        )
        report = HotelSearchReport(
            searched_at=datetime(2026, 8, 10, 9, 0, 0),
            queries=(
                HotelQuerySuccess(
                    query=query,
                    applied=applied,
                    raw_count=5,
                    eligible_count=3,
                    offers=(_sample_hotel_offer(),),
                ),
            ),
        )
        with patch("trip_sift.cli.search_hotels", return_value=report):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                main(
                    [
                        "hotels",
                        "Prague",
                        "2026-12-04",
                        "2026-12-07",
                        "--entire-home",
                    ]
                )
            output = buffer.getvalue().casefold()
            self.assertIn("entire home", output)
            self.assertIn("property type", output)

    def test_empty_success_output(self) -> None:
        report = _sample_hotel_report(offers=(), raw_count=2, eligible_count=0)
        with patch("trip_sift.cli.search_hotels", return_value=report):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["hotels", "Prague", "2026-12-04", "2026-12-07"])
            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("(no eligible stays)", output)
            self.assertIn("shown: 0", output.casefold())

    def test_failure_output_and_exit_code(self) -> None:
        query = HotelQuery("Prague", date(2026, 12, 4), date(2026, 12, 7))
        applied = AppliedHotelFilters(chips=("oos=1",), url="https://example.test")
        report = HotelSearchReport(
            searched_at=datetime(2026, 8, 10, 9, 0, 0),
            queries=(
                HotelQueryFailure(
                    query=query,
                    applied=applied,
                    error=SearchError(
                        SearchErrorCode.FETCH_FAILED,
                        "Booking.com hotel search failed after 3 attempts.",
                    ),
                ),
            ),
        )
        with patch("trip_sift.cli.search_hotels", return_value=report):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["hotels", "Prague", "2026-12-04", "2026-12-07"])
            self.assertEqual(code, 2)
            self.assertIn("ERROR:", buffer.getvalue())

    def test_save_only_when_requested(self) -> None:
        with patch("trip_sift.cli.search_hotels", return_value=_sample_hotel_report()):
            with patch("trip_sift.cli.write_hotel_report_atomic") as writer:
                main(["hotels", "Prague", "2026-12-04", "2026-12-07"])
                writer.assert_not_called()

    def test_atomic_save(self) -> None:
        with patch("trip_sift.cli.search_hotels", return_value=_sample_hotel_report()):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out.json"
                code = main(
                    [
                        "hotels",
                        "Prague",
                        "2026-12-04",
                        "2026-12-07",
                        "--save",
                        str(out),
                    ]
                )
                self.assertEqual(code, 0)
                self.assertTrue(out.exists())
                data = json.loads(out.read_text(encoding="utf-8"))
                self.assertEqual(data["schema_version"], 1)
                self.assertEqual(data["price_basis"], "total_stay")


if __name__ == "__main__":
    unittest.main()
