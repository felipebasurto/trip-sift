from __future__ import annotations

import unittest
from datetime import date
from urllib.parse import parse_qs, urlparse

from viajante.flights import _normalize_offer
from viajante.google_flights import (
    EMPTY_STATE_TEXT,
    GoogleFlightsBlocked,
    GoogleFlightsHttpSource,
    GoogleFlightsMarkupError,
    NoFlightsFound,
    build_search_params,
    build_search_url,
    extract_main_html,
    looks_blocked,
    parse_flight_cards,
    parse_http_flight_cards,
)
from viajante.models import FlightQuery

GOLDEN_TFS_DIRECT = "GhwSCjIwMjYtMTItMDQoAGoFEgNNQURyBRIDQkNOQgEBSAGYAQI="
GOLDEN_TFS_ONE_STOP = "GhwSCjIwMjYtMTItMDQoAWoFEgNNQURyBRIDQkNOQgEBSAGYAQI="
GOLDEN_TFS_TWO_ADULTS = "GhwSCjIwMjYtMTItMDQoAGoFEgNNQURyBRIDQkNOQgIBAUgBmAEC"
GOLDEN_TFS_BUSINESS = "GhwSCjIwMjYtMTItMDQoAGoFEgNNQURyBRIDQkNOQgEBSAOYAQI="
GOLDEN_URL_DIRECT = (
    "https://www.google.com/travel/flights?"
    "tfs=GhwSCjIwMjYtMTItMDQoAGoFEgNNQURyBRIDQkNOQgEBSAGYAQI%3D"
    "&hl=en&tfu=EgQIABABIgA&curr=EUR"
)


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


def build_results_page(*cards: str, include_other: bool = False) -> str:
    best = f'<div jsname="IWWDBc"><ul class="Rk10dc">{"".join(cards)}</ul></div>'
    if not include_other:
        return best
    other = (
        '<div jsname="YdtKid"><ul class="Rk10dc">'
        + build_card(airline="Vueling", price="€99", stops="1 stop")
        + "<li><div>More flights</div></li>"
        + "</ul></div>"
    )
    return best + other


def build_empty_page() -> str:
    return f'<div class="QEk4oc BgYkof"><div>{EMPTY_STATE_TEXT}</div></div>'


class QueryEncodingTests(unittest.TestCase):
    def test_direct_query_matches_the_golden_url(self) -> None:
        query = FlightQuery("MAD", "BCN", date(2026, 12, 4), max_stops=0)
        self.assertEqual(build_search_url(query), GOLDEN_URL_DIRECT)
        params = build_search_params(query)
        self.assertEqual(params["tfs"], GOLDEN_TFS_DIRECT)
        self.assertEqual(params["hl"], "en")
        self.assertEqual(params["curr"], "EUR")
        self.assertEqual(params["tfu"], "EgQIABABIgA")

    def test_one_stop_query_changes_only_the_max_stops_field(self) -> None:
        query = FlightQuery("MAD", "BCN", date(2026, 12, 4), max_stops=1)
        params = build_search_params(query)
        self.assertEqual(params["tfs"], GOLDEN_TFS_ONE_STOP)
        parsed = parse_qs(urlparse(build_search_url(query)).query)
        self.assertEqual(parsed["tfs"], [GOLDEN_TFS_ONE_STOP])
        self.assertEqual(parsed["hl"], ["en"])
        self.assertEqual(parsed["curr"], ["EUR"])
        self.assertEqual(parsed["tfu"], ["EgQIABABIgA"])

    def test_two_adults_query_matches_the_golden_tfs(self) -> None:
        params = build_search_params(
            FlightQuery("MAD", "BCN", date(2026, 12, 4), max_stops=0, adults=2)
        )
        self.assertEqual(params["tfs"], GOLDEN_TFS_TWO_ADULTS)
        self.assertEqual(params["hl"], "en")
        self.assertEqual(params["curr"], "EUR")

    def test_business_cabin_query_matches_the_golden_tfs(self) -> None:
        params = build_search_params(
            FlightQuery(
                "MAD",
                "BCN",
                date(2026, 12, 4),
                max_stops=0,
                cabin="business",
            )
        )
        self.assertEqual(params["tfs"], GOLDEN_TFS_BUSINESS)
        self.assertEqual(params["hl"], "en")
        self.assertEqual(params["curr"], "EUR")

    def test_html_lang_and_currency_args_reach_url_params(self) -> None:
        params = build_search_params(
            FlightQuery("MAD", "BCN", date(2026, 12, 4), max_stops=0),
            html_lang="en",
            currency="USD",
        )
        self.assertEqual(params["hl"], "en")
        self.assertEqual(params["curr"], "USD")


class OwnedCardParserTests(unittest.TestCase):
    def test_nonstop_survives_direct_only_search(self) -> None:
        card = parse_flight_cards(build_results_page(build_card(stops="Nonstop")))[0]
        offer = _normalize_offer(card, max_stops=0)
        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual(offer.stops, "Nonstop")
        self.assertEqual(offer.stops_count, 0)

    def test_every_priced_card_is_kept(self) -> None:
        cards_html = [build_card(price=f"€{eur}", stops="Nonstop") for eur in (129, 154, 188)]
        cards = parse_flight_cards(build_results_page(*cards_html))
        self.assertEqual(len(cards), 3)
        kept = [
            offer
            for offer in (_normalize_offer(card, max_stops=0) for card in cards)
            if offer is not None
        ]
        self.assertEqual(len(kept), 3)

    def test_secondary_group_keeps_priced_cards_and_skips_structural_rows(self) -> None:
        cards = parse_flight_cards(build_results_page(build_card(price="€129"), include_other=True))
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[1].airline, "Vueling")
        self.assertEqual(cards[1].price, "€99")

    def test_one_stop_is_filtered_by_max_stops_but_kept_otherwise(self) -> None:
        card = parse_flight_cards(build_results_page(build_card(stops="1 stop")))[0]
        self.assertIsNone(_normalize_offer(card, max_stops=0))
        offer = _normalize_offer(card, max_stops=1)
        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual(offer.stops, "1 stop")
        self.assertEqual(offer.stops_count, 1)

    def test_raw_price_and_duration_reach_the_offer(self) -> None:
        card = parse_flight_cards(
            build_results_page(build_card(price="€1,234.56", duration="2 hr 50 min"))
        )[0]
        self.assertEqual(card.price, "€1,234.56")
        offer = _normalize_offer(card, max_stops=1)
        assert offer is not None
        self.assertEqual(offer.price, "€1,234.56")
        self.assertEqual(offer.price_eur, 1234.56)
        self.assertAlmostEqual(offer.duration_hours or 0, 2 + 50 / 60)

    def test_spanish_labels_are_preserved_and_normalized(self) -> None:
        card = parse_flight_cards(
            build_results_page(build_card(stops="Sin escalas", price="1.234,56 €"))
        )[0]
        self.assertEqual(card.stops, "Sin escalas")
        self.assertEqual(card.price, "1.234,56 €")
        offer = _normalize_offer(card, max_stops=0)
        assert offer is not None
        self.assertEqual(offer.stops, "Sin escalas")
        self.assertEqual(offer.stops_count, 0)
        self.assertEqual(offer.price_eur, 1234.56)

    def test_cards_beat_stale_empty_state_markup(self) -> None:
        html = build_empty_page() + build_results_page(build_card(price="€88"))
        cards = parse_flight_cards(html)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].price, "€88")

    def test_explicit_empty_state_raises_no_flights_found(self) -> None:
        with self.assertRaises(NoFlightsFound) as ctx:
            parse_flight_cards(build_empty_page())
        self.assertEqual(ctx.exception.observed_text, EMPTY_STATE_TEXT)

    def test_empty_card_list_is_no_flights_found(self) -> None:
        with self.assertRaises(NoFlightsFound):
            parse_flight_cards('<div jsname="IWWDBc"><ul class="Rk10dc"></ul></div>')

    def test_unknown_markup_raises_markup_error(self) -> None:
        with self.assertRaises(GoogleFlightsMarkupError):
            parse_flight_cards("<div>completely unrelated page</div>")


def _http_page(inner: str) -> str:
    return (
        f'<html><body><div role="main">{inner}</div>'
        "<footer>chrome chrome chrome</footer></body></html>"
    )


class HttpSweepParseTests(unittest.TestCase):
    def test_http_body_yields_the_same_raw_cards(self) -> None:
        html = _http_page(build_results_page(build_card(price="€39", airline="Vueling")))
        cards = parse_http_flight_cards(html)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].airline, "Vueling")
        self.assertEqual(cards[0].price, "€39")
        self.assertEqual(cards[0].stops, "Nonstop")
        offer = _normalize_offer(cards[0], max_stops=1)
        assert offer is not None
        self.assertEqual(offer.price, "€39")
        self.assertEqual(offer.price_eur, 39.0)

    def test_extract_main_drops_chrome_outside_main(self) -> None:
        inner = build_results_page(build_card(price="€88"))
        extracted = extract_main_html(_http_page(inner))
        self.assertIn("€88", extracted)
        self.assertNotIn("chrome chrome chrome", extracted)

    def test_http_empty_state_is_no_flights(self) -> None:
        with self.assertRaises(NoFlightsFound):
            parse_http_flight_cards(_http_page(build_empty_page()))

    def test_http_unknown_shell_is_markup_error(self) -> None:
        with self.assertRaises(GoogleFlightsMarkupError):
            parse_http_flight_cards(_http_page("<div>completely unrelated page</div>"))

    def test_consent_and_sorry_urls_are_blocks(self) -> None:
        self.assertTrue(looks_blocked("<html></html>", "https://consent.google.com/ml"))
        self.assertTrue(looks_blocked("<html></html>", "https://www.google.com/sorry/index"))
        self.assertTrue(looks_blocked("Our systems have detected unusual traffic", ""))
        self.assertFalse(looks_blocked(_http_page(build_results_page(build_card())), ""))

    def test_http_source_uses_fixture_body_not_the_network(self) -> None:
        html = _http_page(build_results_page(build_card(price="€131", airline="Iberia")))

        class _Resp:
            def __init__(self) -> None:
                self.headers = {"Content-Encoding": ""}
                self.status = 200

            def read(self) -> bytes:
                return html.encode("utf-8")

            def geturl(self) -> str:
                return "https://www.google.com/travel/flights?hl=en"

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        class _Opener:
            def open(self, request: object, timeout: float = 0) -> _Resp:
                return _Resp()

        source = GoogleFlightsHttpSource(opener=_Opener())
        cards = source.fetch(FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1))
        self.assertEqual(cards[0].airline, "Iberia")
        self.assertEqual(cards[0].price, "€131")

    def test_http_source_raises_blocked_on_sorry_redirect(self) -> None:
        class _Resp:
            headers = {"Content-Encoding": ""}
            status = 200

            def read(self) -> bytes:
                return b"<html>sorry</html>"

            def geturl(self) -> str:
                return "https://www.google.com/sorry/index?continue=flights"

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        class _Opener:
            def open(self, request: object, timeout: float = 0) -> _Resp:
                return _Resp()

        source = GoogleFlightsHttpSource(opener=_Opener())
        with self.assertRaises(GoogleFlightsBlocked):
            source.fetch(FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1))


if __name__ == "__main__":
    unittest.main()
