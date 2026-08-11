from __future__ import annotations

import unittest

from fast_flights.core import parse_response

from trip_sift.browser import HtmlResponse
from trip_sift.flights import _normalize_offer


def build_card(
    *,
    airline: str = "Iberia",
    departure: str = "08:40",
    arrival: str = "11:30",
    duration: str = "2 hr 50 min",
    stops: str = "Nonstop",
    price: str = "€129",
) -> str:
    return (
        "<li>"
        f'<div class="sSHqwe tPgKwe ogfYpf"><span>{airline}</span></div>'
        f'<span class="mv1WYe"><div>{departure}</div><div>{arrival}</div></span>'
        f'<div class="Ak5kof"><div>{duration}</div></div>'
        f'<div class="BbR8Ec"><div class="ogfYpf">{stops}</div></div>'
        f'<div class="YMlIz FpEdX"><span>{price}</span></div>'
        "</li>"
    )


def build_results_page(*cards: str) -> str:
    return f'<div jsname="IWWDBc"><ul class="Rk10dc">{"".join(cards)}</ul></div>'


def scrape(*cards: str):
    return parse_response(HtmlResponse(build_results_page(*cards))).flights


class ProviderSeamTests(unittest.TestCase):
    """Exercises the real fast-flights parser, which mutates text before trip-sift sees it."""

    def test_nonstop_survives_direct_only_search(self) -> None:
        raw = scrape(build_card(stops="Nonstop"))[0]
        offer = _normalize_offer(raw, max_stops=0)
        self.assertIsNotNone(offer, "a nonstop flight must survive --max-stops 0")
        assert offer is not None
        self.assertEqual(offer.stops_count, 0)

    def test_every_nonstop_offer_is_kept_for_a_direct_only_search(self) -> None:
        cards = [build_card(price=f"€{eur}", stops="Nonstop") for eur in (129, 154, 188)]
        kept = [
            offer
            for offer in (_normalize_offer(raw, max_stops=0) for raw in scrape(*cards))
            if offer is not None
        ]
        self.assertEqual(len(kept), 3)

    def test_one_stop_is_filtered_by_max_stops_but_kept_otherwise(self) -> None:
        raw = scrape(build_card(stops="1 stop"))[0]
        self.assertIsNone(_normalize_offer(raw, max_stops=0))
        offer = _normalize_offer(raw, max_stops=1)
        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual(offer.stops_count, 1)

    def test_two_stops_are_always_filtered(self) -> None:
        raw = scrape(build_card(stops="2 stops"))[0]
        self.assertIsNone(_normalize_offer(raw, max_stops=0))
        self.assertIsNone(_normalize_offer(raw, max_stops=1))

    def test_thousands_separator_survives_the_provider_comma_strip(self) -> None:
        raw = scrape(build_card(price="€1,234"))[0]
        offer = _normalize_offer(raw, max_stops=1)
        assert offer is not None
        self.assertEqual(offer.price_eur, 1234.0)

    def test_decimal_price_survives_the_provider_comma_strip(self) -> None:
        raw = scrape(build_card(price="€1,234.56"))[0]
        offer = _normalize_offer(raw, max_stops=1)
        assert offer is not None
        self.assertEqual(offer.price_eur, 1234.56)

    def test_duration_and_schedule_reach_the_offer(self) -> None:
        raw = scrape(build_card(duration="2 hr 50 min"))[0]
        offer = _normalize_offer(raw, max_stops=1)
        assert offer is not None
        self.assertAlmostEqual(offer.duration_hours or 0, 2 + 50 / 60)
        self.assertEqual(offer.departure, "08:40")
        self.assertEqual(offer.arrival, "11:30")

    def test_offer_keeps_raw_text_beside_every_parsed_field(self) -> None:
        raw = scrape(build_card(price="€1,234", duration="2 hr 50 min", stops="1 stop"))[0]
        offer = _normalize_offer(raw, max_stops=1)
        assert offer is not None
        raw_and_parsed = (
            (offer.price, offer.price_eur),
            (offer.duration, offer.duration_hours),
        )
        for text, number in raw_and_parsed:
            self.assertTrue(text)
            self.assertIsNotNone(number)
        self.assertIsNotNone(offer.stops)
        self.assertIsNotNone(offer.stops_count)


class SpanishLocaleRegressionTests(unittest.TestCase):
    """fast-flights 2.2 only understands English labels, which is why the locale is pinned to en."""

    def test_spanish_nonstop_label_is_unparseable_by_the_provider(self) -> None:
        for label in ("Sin escalas", "Directo"):
            with self.subTest(label=label):
                self.assertEqual(scrape(build_card(stops=label))[0].stops, "Unknown")

    def test_spanish_decimal_price_is_corrupted_by_the_provider(self) -> None:
        raw = scrape(build_card(price="1.234,56 €"))[0]
        self.assertEqual(raw.price, "1.23456 €")


if __name__ == "__main__":
    unittest.main()
