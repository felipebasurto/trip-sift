from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import trip_sift
from trip_sift.cli import _print_report, main
from trip_sift.hotels import write_hotel_report_atomic
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

FUTURE_DATE = date.today() + timedelta(days=30)
PAST_DATE = date.today() - timedelta(days=1)
ROUTE = f"MAD-BCN:{FUTURE_DATE.isoformat()}"

QUERY = FlightQuery("MAD", "BCN", FUTURE_DATE, max_stops=1)
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
                code = main(["flights", ROUTE, "--max-stops", "3"])
            self.assertEqual(code, 1)
            search.assert_not_called()

    def test_prints_results(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_report()):
            with patch("trip_sift.cli._print_report") as printer:
                code = main(["flights", ROUTE])
                self.assertEqual(code, 0)
                printer.assert_called_once()

    def test_save_only_when_requested(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_report()):
            with patch("trip_sift.cli.write_report_atomic") as writer:
                with patch("trip_sift.cli._print_report"):
                    main(["flights", ROUTE])
                writer.assert_not_called()

    def test_atomic_save(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_report()):
            with patch("trip_sift.cli._print_report"), redirect_stdout(io.StringIO()):
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / "out.json"
                    code = main(["flights", ROUTE, "--save", str(out)])
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
                self.assertEqual(main(["flights", ROUTE]), 2)

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
                self.assertEqual(main(["flights", ROUTE]), 3)

    def test_baggage_buffer_flag_reaches_the_search(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_report()) as search:
            with patch("trip_sift.cli._print_report"):
                main(["flights", ROUTE, "--baggage-buffer", "0"])
        self.assertEqual(search.call_args.kwargs["buffer_eur"], 0)

    def test_negative_baggage_buffer_is_rejected_before_searching(self) -> None:
        with patch("trip_sift.cli.search_flights") as search:
            self.assertEqual(main(["flights", ROUTE, "--baggage-buffer", "-1"]), 1)
            search.assert_not_called()

    def test_past_dates_are_rejected_before_starting_chromium(self) -> None:
        with patch("trip_sift.cli.search_flights") as search:
            code = main(["flights", f"MAD-BCN:{PAST_DATE.isoformat()}"])
            self.assertEqual(code, 1)
            search.assert_not_called()

    def test_today_is_accepted(self) -> None:
        with patch("trip_sift.cli.search_flights", return_value=_report()) as search:
            with patch("trip_sift.cli._print_report"):
                main(["flights", f"MAD-BCN:{date.today().isoformat()}"])
            search.assert_called_once()


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

    def test_baggage_reminder_after_successful_flight_results(self) -> None:
        output = _rendered(_report(_offer()))
        self.assertIn("Verify checked baggage on Google Flights before booking.", output)

    def test_baggage_reminder_omitted_when_all_queries_fail(self) -> None:
        report = SearchReport(
            searched_at=SEARCHED_AT,
            queries=(
                QueryFailure(
                    query=QUERY,
                    error=SearchError(SearchErrorCode.FETCH_FAILED, "blocked"),
                ),
            ),
        )
        output = _rendered(report)
        self.assertNotIn("Verify checked baggage", output)
        self.assertIn("ERROR: blocked", output)

    def test_long_airline_names_are_truncated_visibly(self) -> None:
        output = _rendered(_report(_offer(airline="A" * 60)))
        self.assertIn("…", output)
        self.assertNotIn("A" * 41, output)

    def test_flights_help_preserves_examples_epilog(self) -> None:
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            code = main(["flights", "--help"])
        self.assertEqual(code, 0)
        help_text = buffer.getvalue()
        self.assertIn("Examples:", help_text)
        self.assertIn("trip-sift flights MAD-BCN", help_text)

    def test_root_help_preserves_flight_examples_and_lists_subcommands(self) -> None:
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            code = main(["--help"])
        self.assertEqual(code, 0)
        help_text = buffer.getvalue()
        self.assertIn("flights", help_text)
        self.assertIn("hotels", help_text)
        self.assertIn("Examples:", help_text)
        self.assertIn("trip-sift flights MAD-BCN", help_text)


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


def _sample_hotel_offer(*, total_price: str = "420 €") -> HotelOffer:
    return HotelOffer(
        title="Old Town Apartment",
        address="Prague 1, Czech Republic",
        total_price=total_price,
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
        with patch("trip_sift.cli.search_hotels", return_value=_sample_hotel_report()) as search:
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
                search.assert_called_once()
                queries, kwargs = search.call_args
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
        with patch("trip_sift.cli.search_hotels", return_value=_sample_hotel_report()) as search:
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
                query = search.call_args[0][0][0]
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

    def test_entire_home_help_is_strict_filter_wording(self) -> None:
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            code = main(["hotels", "--help"])
        self.assertEqual(code, 0)
        help_text = buffer.getvalue().casefold()
        self.assertNotIn("prefer entire", help_text)
        self.assertIn("entire home", help_text)
        self.assertIn("unknown", help_text)

    def test_default_filter_gloss_and_booking_chips(self) -> None:
        report = _sample_hotel_report(offers=(_sample_hotel_offer(),))
        with patch("trip_sift.cli.search_hotels", return_value=report):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                main(["hotels", "Prague", "2026-12-04", "2026-12-07"])
            output = buffer.getvalue()
            lowered = output.casefold()
            self.assertIn("free cancellation required", lowered)
            self.assertIn("booking chips: oos=1", lowered)

    def test_non_refundable_opt_out_filter_gloss(self) -> None:
        query = HotelQuery(
            "Prague",
            date(2026, 12, 4),
            date(2026, 12, 7),
            free_cancellation=False,
        )
        applied = AppliedHotelFilters(chips=(), url="https://example.test")
        report = HotelSearchReport(
            searched_at=datetime(2026, 8, 10, 9, 0, 0),
            queries=(
                HotelQuerySuccess(
                    query=query,
                    applied=applied,
                    raw_count=1,
                    eligible_count=1,
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
                        "--allow-non-refundable",
                    ]
                )
            output = buffer.getvalue().casefold()
            self.assertIn("non-refundable rates allowed", output)
            self.assertIn("booking chips: (none)", output)

    def test_success_output_contract(self) -> None:
        report = _sample_hotel_report(
            offers=(_sample_hotel_offer(total_price="419,50 €"),),
        )
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
            self.assertIn("free cancellation required", output.casefold())
            self.assertIn("booking chips: oos=1", output.casefold())
            self.assertIn("419,50 € total stay", output)
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
            self.assertIn("entire homes/apartments required", output)
            self.assertIn("property type", output)
            self.assertIn("booking chips:", output)

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
            output = buffer.getvalue()
            self.assertIn("ERROR:", output)
            self.assertIn("free cancellation required", output.casefold())
            self.assertIn("booking chips: oos=1", output.casefold())
            self.assertNotIn("verify the final total stay", output.casefold())

    def test_save_only_when_requested(self) -> None:
        with patch("trip_sift.cli.search_hotels", return_value=_sample_hotel_report()):
            with patch("trip_sift.cli.write_hotel_report_atomic") as writer:
                main(["hotels", "Prague", "2026-12-04", "2026-12-07"])
                writer.assert_not_called()

    def test_atomic_save(self) -> None:
        with patch("trip_sift.cli.search_hotels", return_value=_sample_hotel_report()):
            with patch(
                "trip_sift.cli.write_hotel_report_atomic",
                wraps=write_hotel_report_atomic,
            ) as writer:
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
                    writer.assert_called_once()
                    self.assertTrue(out.exists())
                    data = json.loads(out.read_text(encoding="utf-8"))
                    self.assertEqual(data["schema_version"], 1)
                    self.assertEqual(data["price_basis"], "total_stay")


if __name__ == "__main__":
    unittest.main()
