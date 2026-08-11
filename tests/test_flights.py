from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from random import Random
from typing import Optional, Sequence
from unittest.mock import patch

from trip_sift.flights import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_JITTER_SECONDS,
    MAX_ATTEMPTS,
    REQUEST_DELAY_SECONDS,
    REQUEST_JITTER_SECONDS,
    _normalize_offer,
    _rank_offers,
    _run_search,
    _stops_text,
    is_low_cost,
    parse_route_specs,
    search_flights,
    write_report_atomic,
)
from trip_sift.models import FlightOffer, FlightQuery, QueryFailure, QuerySuccess, SearchReport


@dataclass
class FakeOffer:
    name: Optional[str]
    departure: Optional[str]
    arrival: Optional[str]
    price: Optional[str]
    duration: Optional[str]
    stops: object


@dataclass
class FakeResult:
    flights: Sequence[FakeOffer]


class FakeSource:
    def __init__(self, responses: dict[tuple, object]) -> None:
        self.responses = responses
        self.fetch_calls = 0
        self.reset_calls = 0
        self.closed = False

    def fetch(self, query: FlightQuery) -> FakeResult:
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

    def test_integer_stops_keep_a_readable_raw_label(self) -> None:
        self.assertEqual(_stops_text(0), "Nonstop")
        self.assertEqual(_stops_text(1), "1 stop")
        self.assertEqual(_stops_text(2), "2 stops")


class FlightsOrchestrationTests(unittest.TestCase):
    def test_retry_reset_backoff_and_continue(self) -> None:
        q_ok = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1)
        q_fail = FlightQuery("MAD", "LHR", date(2026, 9, 2), max_stops=1)
        ok_result = FakeResult(
            flights=[
                FakeOffer("Air One", "08:00", "09:00", "99 €", "1 h", 0),
            ]
        )
        source = FakeSource(
            {
                ("MAD", "BCN", "2026-09-01", 1): ok_result,
                ("MAD", "LHR", "2026-09-02", 1): RuntimeError("network"),
            }
        )
        sleeps: list[float] = []
        expected_rng = Random(0)
        inter_query = REQUEST_DELAY_SECONDS + expected_rng.uniform(
            0, REQUEST_JITTER_SECONDS
        )
        expected_backoffs = [
            BACKOFF_BASE_SECONDS * (2**attempt)
            + expected_rng.uniform(0, BACKOFF_JITTER_SECONDS)
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
        for got, want in zip(sleeps[1:], expected_backoffs):
            self.assertAlmostEqual(got, want)

    def test_max_stops_zero_keeps_only_nonstop(self) -> None:
        nonstop = FakeOffer("Air", "08:00", "09:00", "100 €", "1 h", 0)
        one_stop = FakeOffer("Air", "10:00", "13:00", "80 €", "3 h", 1)
        self.assertIsNotNone(_normalize_offer(nonstop, max_stops=0))
        self.assertIsNone(_normalize_offer(one_stop, max_stops=0))
        self.assertIsNotNone(_normalize_offer(one_stop, max_stops=1))

    def test_unlabelled_stops_are_rejected_when_only_direct_flights_are_wanted(self) -> None:
        unknown = FakeOffer("Air", "14:00", "15:00", "90 €", "1 h", "Unknown")
        self.assertIsNone(_normalize_offer(unknown, max_stops=0))
        self.assertIsNotNone(_normalize_offer(unknown, max_stops=1))

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
        raw = FakeOffer("Air", "08:40", "11:30", "129 €", "2 h 50 min", 0)
        offer = _normalize_offer(raw, max_stops=1)
        assert offer is not None
        self.assertEqual(offer.price, "129 €")
        self.assertEqual(offer.price_eur, 129.0)
        self.assertEqual(offer.duration, "2 h 50 min")
        self.assertAlmostEqual(offer.duration_hours or 0, 2 + 50 / 60)
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

    def test_write_report_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "out.json"
            report = SearchReport(
                searched_at=datetime(2026, 8, 10, 9, 0, 0),
                queries=(),
            )
            write_report_atomic(report, path)
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)

    def test_search_closes_source(self) -> None:
        query = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1)
        source = FakeSource(
            {
                ("MAD", "BCN", "2026-09-01", 1): FakeResult(
                    flights=[
                        FakeOffer(
                            "Air One",
                            "08:00",
                            "09:00",
                            "99 €",
                            "1 h",
                            0,
                        )
                    ]
                )
            }
        )
        with patch("trip_sift.flights._GoogleFlightsSource", return_value=source):
            search_flights((query,), top=1)
        self.assertTrue(source.closed)


if __name__ == "__main__":
    unittest.main()
