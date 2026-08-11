from __future__ import annotations

import unittest
from datetime import date, datetime
from random import Random
from types import SimpleNamespace
from typing import Sequence
from unittest.mock import patch

from trip_sift.flights import (
    _normalize_offer,
    _rank_offers,
    _run_search,
    classify_failure,
    is_low_cost,
    parse_route_specs,
    search_flights,
)
from trip_sift.google_flights import GoogleFlightsMarkupError, NoFlightsFound, RawFlightCard
from trip_sift.models import (
    FlightOffer,
    FlightQuery,
    QueryFailure,
    QuerySuccess,
    SearchErrorCode,
)
from trip_sift.orchestration import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_JITTER_SECONDS,
    MAX_ATTEMPTS,
    REQUEST_DELAY_SECONDS,
    REQUEST_JITTER_SECONDS,
)


def card(
    *,
    airline: str = "Air",
    departure: str = "08:00",
    arrival: str = "09:00",
    price: str = "99 €",
    duration: str = "1 h",
    stops: str = "Nonstop",
) -> RawFlightCard:
    return RawFlightCard(
        airline=airline,
        departure=departure,
        arrival=arrival,
        price=price,
        duration=duration,
        stops=stops,
    )


class FakeSource:
    def __init__(self, responses: dict[tuple, object]) -> None:
        self.responses = responses
        self.fetch_calls = 0
        self.reset_calls = 0
        self.closed = False
        self.config = SimpleNamespace(html_lang="en", currency="EUR")

    def fetch(self, query: FlightQuery) -> Sequence[RawFlightCard]:
        self.fetch_calls += 1
        key = (
            query.origin,
            query.destination,
            query.departure_date.isoformat(),
            query.max_stops,
        )
        response = self.responses.get(key)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise RuntimeError("missing fake response")
        return response

    def reset(self) -> None:
        self.reset_calls += 1

    def close(self) -> None:
        self.closed = True


class LowCostClassificationTests(unittest.TestCase):
    def test_matching_ignores_case_and_punctuation(self) -> None:
        for variant in ("Ryanair", "ryanair", "RYANAIR", "EasyJet", "easyJet"):
            with self.subTest(variant=variant):
                self.assertTrue(is_low_cost(variant))
        self.assertTrue(is_low_cost("T'Way Air"))
        self.assertTrue(is_low_cost("Tway Air"))

    def test_european_carriers_on_the_documented_routes_are_covered(self) -> None:
        for airline in ("Vueling", "Wizz Air", "Transavia", "Volotea", "Norwegian"):
            with self.subTest(airline=airline):
                self.assertTrue(is_low_cost(airline))

    def test_full_service_carriers_are_not_penalised(self) -> None:
        for airline in ("Iberia", "Air Europa", "Lufthansa", "Iberia Express", ""):
            with self.subTest(airline=airline):
                self.assertFalse(is_low_cost(airline))

    def test_matching_respects_word_boundaries(self) -> None:
        self.assertFalse(is_low_cost("Peachtree Air"))


class FailureClassificationTests(unittest.TestCase):
    def test_empty_results_are_not_a_fetch_failure(self) -> None:
        error = classify_failure(NoFlightsFound("No options matching your search"))
        self.assertEqual(error.code, SearchErrorCode.NO_RESULTS)
        self.assertEqual(
            error.message,
            "Google Flights returned no flights for this route and date.",
        )

    def test_missing_chromium_is_reported_as_browser_unavailable(self) -> None:
        error = classify_failure(
            RuntimeError("Executable doesn't exist at /ms-playwright/chromium/headless")
        )
        self.assertEqual(error.code, SearchErrorCode.BROWSER_UNAVAILABLE)
        self.assertIn("playwright install chromium", error.message)

    def test_markup_errors_are_fetch_failures(self) -> None:
        error = classify_failure(GoogleFlightsMarkupError("no results grid"))
        self.assertEqual(error.code, SearchErrorCode.FETCH_FAILED)
        self.assertIn("no results grid", error.message)

    def test_unrecognised_failures_keep_their_original_text(self) -> None:
        error = classify_failure(TimeoutError("Timeout 60000ms exceeded"))
        self.assertEqual(error.code, SearchErrorCode.FETCH_FAILED)
        self.assertIn("Timeout 60000ms exceeded", error.message)


class NonRetriableFailureTests(unittest.TestCase):
    def _run(self, exc: Exception) -> tuple:
        source = FakeSource({("MAD", "BCN", "2026-09-01", 1): exc})
        sleeps: list[float] = []
        report = _run_search(
            (FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1),),
            top=8,
            source=source,
            sleep=sleeps.append,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10),
        )
        return report.queries[0], source, sleeps

    def test_no_results_is_not_retried(self) -> None:
        outcome, source, sleeps = self._run(NoFlightsFound())
        self.assertEqual(source.fetch_calls, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(outcome.error.code, SearchErrorCode.NO_RESULTS)

    def test_missing_browser_is_not_retried(self) -> None:
        outcome, source, sleeps = self._run(RuntimeError("Executable doesn't exist"))
        self.assertEqual(source.fetch_calls, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(outcome.error.code, SearchErrorCode.BROWSER_UNAVAILABLE)

    def test_markup_errors_are_not_retried(self) -> None:
        outcome, source, sleeps = self._run(GoogleFlightsMarkupError("selectors rotted"))
        self.assertEqual(source.fetch_calls, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(outcome.error.code, SearchErrorCode.FETCH_FAILED)

    def test_transient_failures_are_still_retried(self) -> None:
        outcome, source, sleeps = self._run(RuntimeError("network"))
        self.assertEqual(source.fetch_calls, MAX_ATTEMPTS)
        self.assertEqual(len(sleeps), MAX_ATTEMPTS - 1)
        self.assertEqual(outcome.error.code, SearchErrorCode.FETCH_FAILED)


class ProgressTests(unittest.TestCase):
    def test_each_query_is_announced_before_it_runs(self) -> None:
        lines: list[str] = []
        queries = (
            FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1),
            FlightQuery("MAD", "LHR", date(2026, 9, 2), max_stops=1),
        )
        source = FakeSource(
            {
                ("MAD", "BCN", "2026-09-01", 1): (card(),),
                ("MAD", "LHR", "2026-09-02", 1): NoFlightsFound(),
            }
        )
        _run_search(
            queries,
            top=8,
            source=source,
            sleep=lambda _: None,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10),
            progress=lines.append,
        )
        self.assertIn("[1/2] MAD -> BCN 2026-09-01", lines)
        self.assertIn("[2/2] MAD -> LHR 2026-09-02", lines)
        self.assertTrue(any("no_results" in line for line in lines))


class FlightsOrchestrationTests(unittest.TestCase):
    def test_retry_reset_backoff_and_continue(self) -> None:
        q_ok = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1)
        q_fail = FlightQuery("MAD", "LHR", date(2026, 9, 2), max_stops=1)
        source = FakeSource(
            {
                ("MAD", "BCN", "2026-09-01", 1): (card(airline="Air One"),),
                ("MAD", "LHR", "2026-09-02", 1): RuntimeError("network"),
            }
        )
        sleeps: list[float] = []
        expected_rng = Random(0)
        inter_query = REQUEST_DELAY_SECONDS + expected_rng.uniform(0, REQUEST_JITTER_SECONDS)
        expected_backoffs = [
            BACKOFF_BASE_SECONDS * (2**attempt) + expected_rng.uniform(0, BACKOFF_JITTER_SECONDS)
            for attempt in range(MAX_ATTEMPTS - 1)
        ]

        report = _run_search(
            (q_ok, q_fail),
            top=8,
            source=source,
            sleep=sleeps.append,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10, 9, 0, 0),
        )

        self.assertEqual(source.reset_calls, MAX_ATTEMPTS)
        self.assertEqual(source.fetch_calls, 1 + MAX_ATTEMPTS)
        self.assertIsInstance(report.queries[0], QuerySuccess)
        self.assertIsInstance(report.queries[1], QueryFailure)
        self.assertEqual(report.queries[1].error.code.value, "fetch_failed")
        self.assertEqual(len(sleeps), len(expected_backoffs) + 1)
        self.assertAlmostEqual(sleeps[0], inter_query)
        for got, want in zip(sleeps[1:], expected_backoffs, strict=True):
            self.assertAlmostEqual(got, want)

    def test_max_stops_zero_keeps_only_nonstop(self) -> None:
        nonstop = card(stops="Nonstop", price="100 €")
        one_stop = card(stops="1 stop", price="80 €", departure="10:00", arrival="13:00")
        self.assertIsNotNone(_normalize_offer(nonstop, max_stops=0))
        self.assertIsNone(_normalize_offer(one_stop, max_stops=0))
        self.assertIsNotNone(_normalize_offer(one_stop, max_stops=1))

    def test_unlabelled_stops_are_rejected_when_only_direct_flights_are_wanted(self) -> None:
        unknown = card(stops="Unknown", price="90 €", departure="14:00", arrival="15:00")
        self.assertIsNone(_normalize_offer(unknown, max_stops=0))
        self.assertIsNotNone(_normalize_offer(unknown, max_stops=1))

    def test_eligible_count_is_zero_when_all_offers_fail_normalize(self) -> None:
        query = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=0)
        source = FakeSource(
            {
                ("MAD", "BCN", "2026-09-01", 0): (
                    card(stops="Unknown", price="90 €", departure="14:00", arrival="15:00"),
                    card(stops="1 stop", price="80 €", departure="10:00", arrival="13:00"),
                ),
            }
        )
        report = _run_search(
            (query,),
            top=8,
            source=source,
            sleep=lambda _: None,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10),
        )
        outcome = report.queries[0]
        self.assertIsInstance(outcome, QuerySuccess)
        self.assertEqual(outcome.raw_count, 2)
        self.assertEqual(outcome.eligible_count, 0)
        self.assertEqual(outcome.offers, ())

    def test_rank_dedupe_and_baggage(self) -> None:
        offers = (
            FlightOffer(
                airline="Ryanair",
                departure="07:00",
                arrival="09:00",
                price="50 €",
                price_eur=50.0,
                duration="2 h",
                duration_hours=2.0,
                stops="Directo",
                stops_count=0,
                baggage_buffer_eur=70,
                needs_bag_verify=True,
            ),
            FlightOffer(
                airline="Legacy",
                departure="08:00",
                arrival="10:00",
                price="100 €",
                price_eur=100.0,
                duration="2 h",
                duration_hours=2.0,
                stops="Directo",
                stops_count=0,
                baggage_buffer_eur=0,
                needs_bag_verify=False,
            ),
            FlightOffer(
                airline="Ryanair",
                departure="07:00",
                arrival="09:00",
                price="50 €",
                price_eur=50.0,
                duration="2 h",
                duration_hours=2.0,
                stops="Directo",
                stops_count=0,
                baggage_buffer_eur=70,
                needs_bag_verify=True,
            ),
        )
        ranked = _rank_offers(offers, top=5)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].airline, "Legacy")
        self.assertEqual(ranked[1].airline, "Ryanair")

    def test_raw_normalized_pairing(self) -> None:
        raw = card(
            airline="Air",
            departure="08:40",
            arrival="11:30",
            price="129 €",
            duration="2 h 50 min",
            stops="Nonstop",
        )
        offer = _normalize_offer(raw, max_stops=1)
        assert offer is not None
        self.assertEqual(offer.price, "129 €")
        self.assertEqual(offer.price_eur, 129.0)
        self.assertEqual(offer.duration, "2 h 50 min")
        self.assertAlmostEqual(offer.duration_hours or 0, 2 + 50 / 60)
        self.assertEqual(offer.stops, "Nonstop")
        self.assertEqual(offer.stops_count, 0)

    def test_dedupe_keeps_flights_that_differ_only_in_stops(self) -> None:
        def offer(stops_count: int, hours: float) -> FlightOffer:
            return FlightOffer(
                airline="Iberia",
                departure="08:00",
                arrival="09:00",
                price="100 €",
                price_eur=100.0,
                duration=f"{hours} h",
                duration_hours=hours,
                stops="Nonstop" if stops_count == 0 else "1 stop",
                stops_count=stops_count,
                baggage_buffer_eur=0,
                needs_bag_verify=False,
            )

        ranked = _rank_offers((offer(0, 1.0), offer(1, 5.0)), top=5)
        self.assertEqual(len(ranked), 2)

    def test_parse_route_specs(self) -> None:
        queries = parse_route_specs(["MAD-BCN:2026-09-01,2026-09-02"], max_stops=0)
        self.assertEqual(len(queries), 2)
        self.assertEqual(queries[0].max_stops, 0)

    def test_search_closes_source(self) -> None:
        query = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1)
        source = FakeSource({("MAD", "BCN", "2026-09-01", 1): (card(airline="Air One"),)})
        with patch("trip_sift.flights.GoogleFlightsSource", return_value=source):
            search_flights((query,), top=1)
        self.assertTrue(source.closed)


if __name__ == "__main__":
    unittest.main()
