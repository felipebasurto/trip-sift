from __future__ import annotations

import json
import unittest
from datetime import date
from urllib.parse import parse_qs, unquote, urlparse

from viajante.flights import _normalize_offer
from viajante.google_flights import (
    EMPTY_STATE_TEXT,
    GoogleFlightsBlocked,
    GoogleFlightsHttpSource,
    GoogleFlightsMarkupError,
    NoFlightsFound,
    SweepHttpResponse,
    build_search_params,
    build_search_url,
    extract_main_html,
    looks_blocked,
    parse_flight_cards,
    parse_http_flight_cards,
)
from viajante.google_flights_rpc import (
    CompactParseMiss,
    EmptyShoppingResults,
    build_shopping_inner,
    build_shopping_request,
    parse_shopping_body,
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


def _itinerary(
    *,
    airline: str = "Iberia",
    code: str = "IB",
    dep: tuple[int, int] = (8, 40),
    arr: tuple[int, int] = (11, 30),
    minutes: int = 170,
    price: int = 129,
    legs: int = 1,
) -> list[object]:
    flight = [
        code,
        [airline],
        [[] for _ in range(legs)],
        "MAD",
        None,
        list(dep),
        "BCN",
        None,
        list(arr),
        minutes,
    ]
    return [flight, [[None, price], "tok"]]


def _compact_body(*itineraries: list[object], other: tuple[list[object], ...] = ()) -> str:
    data: list[object] = [
        None,
        None,
        [list(itineraries), None, False],
        [list(other), len(other), False],
    ]
    wrb = [["wrb.fr", None, json.dumps(data, separators=(",", ":"))]]
    raw = json.dumps(wrb, separators=(",", ":"))
    return f")]}}'\n\n{len(raw)}\n{raw}"


class _FakeSweepClient:
    def __init__(
        self,
        *,
        post_text: str = "",
        post_status: int = 200,
        post_url: str = "https://www.google.com/_/FlightsFrontendUi/data/shopping",
        get_text: str = "",
        get_status: int = 200,
        get_url: str = "https://www.google.com/travel/flights?hl=en",
    ) -> None:
        self.post_text = post_text
        self.post_status = post_status
        self.post_url = post_url
        self.get_text = get_text
        self.get_status = get_status
        self.get_url = get_url
        self.posts: list[str] = []
        self.gets: list[str] = []

    def post(
        self,
        url: str,
        *,
        data: str,
        headers: object,
        timeout: float,
    ) -> SweepHttpResponse:
        self.posts.append(url)
        self.last_post_data = data
        return SweepHttpResponse(self.post_status, self.post_text, self.post_url)

    def get(self, url: str, *, timeout: float) -> SweepHttpResponse:
        self.gets.append(url)
        return SweepHttpResponse(self.get_status, self.get_text, self.get_url)

    def close(self) -> None:
        return None


class ShoppingRpcTests(unittest.TestCase):
    def test_inner_payload_keeps_owned_airport_nesting(self) -> None:
        query = FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1, adults=2, cabin="business")
        inner = build_shopping_inner(query)
        flight = inner[1][13][0]
        self.assertEqual(flight[0], [[["MAD", 0]]])
        self.assertEqual(flight[1], [[["BCN", 0]]])
        self.assertEqual(flight[3], 2)
        self.assertEqual(flight[6], "2026-09-01")
        self.assertEqual(inner[1][5], 3)
        self.assertEqual(inner[1][6], [2, 0, 0, 0])

    def test_request_body_is_f_req_envelope(self) -> None:
        query = FlightQuery("MAD", "OPO", date(2026, 10, 9), max_stops=0)
        url, body = build_shopping_request(query)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        self.assertEqual(params["hl"], ["en"])
        self.assertEqual(params["curr"], ["EUR"])
        self.assertEqual(params["rt"], ["c"])
        self.assertTrue(body.startswith("f.req="))
        envelope = json.loads(unquote(body[len("f.req=") :]))
        self.assertIsNone(envelope[0])
        inner = json.loads(envelope[1])
        self.assertEqual(inner[1][13][0][1], [[["OPO", 0]]])

    def test_compact_body_yields_raw_card_fields(self) -> None:
        body = _compact_body(
            _itinerary(
                airline="Air Europa",
                dep=(17, 5),
                arr=(21, 10),
                minutes=245,
                price=83,
                legs=2,
            )
        )
        cards = parse_shopping_body(body)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].airline, "Air Europa")
        self.assertEqual(cards[0].departure, "5:05 PM")
        self.assertEqual(cards[0].arrival, "9:10 PM")
        self.assertEqual(cards[0].duration, "4 hr 5 min")
        self.assertEqual(cards[0].stops, "1 stop")
        self.assertEqual(cards[0].price, "€83")
        offer = _normalize_offer(cards[0], max_stops=1)
        assert offer is not None
        self.assertEqual(offer.price_eur, 83.0)
        self.assertEqual(offer.stops_count, 1)
        self.assertEqual(offer.duration_hours, 4 + 5 / 60)

    def test_missing_itinerary_arrival_uses_last_leg(self) -> None:
        item = _itinerary(dep=(13, 40), arr=(16, 20), minutes=160, price=74, legs=2)
        item[0][8] = None
        first = [None] * 11
        first[8] = [13, 40]
        first[10] = [14, 30]
        last = [None] * 11
        last[8] = [15, 10]
        last[10] = [16, 20]
        item[0][2] = [first, last]
        card = parse_shopping_body(_compact_body(item))[0]
        self.assertEqual(card.departure, "1:40 PM")
        self.assertEqual(card.arrival, "4:20 PM")

    def test_midnight_and_noon_clocks(self) -> None:
        body = _compact_body(
            _itinerary(dep=(0, 10), arr=(12, 0), minutes=60, price=40, legs=1),
        )
        card = parse_shopping_body(body)[0]
        self.assertEqual(card.departure, "12:10 AM")
        self.assertEqual(card.arrival, "12:00 PM")
        self.assertEqual(card.duration, "1 hr")
        self.assertEqual(card.stops, "Nonstop")

    def test_empty_itinerary_slots_are_no_flights(self) -> None:
        with self.assertRaises(EmptyShoppingResults):
            parse_shopping_body(_compact_body())

    def test_unreadable_body_is_compact_miss(self) -> None:
        with self.assertRaises(CompactParseMiss):
            parse_shopping_body("not a shopping payload")

    def test_source_uses_compact_post_not_html(self) -> None:
        client = _FakeSweepClient(post_text=_compact_body(_itinerary(price=88, airline="Iberia")))
        source = GoogleFlightsHttpSource(client=client)
        cards = source.fetch(FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1))
        self.assertEqual(cards[0].airline, "Iberia")
        self.assertEqual(cards[0].price, "€88")
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(client.gets, [])

    def test_source_falls_back_to_html_when_compact_misses(self) -> None:
        html = _http_page(build_results_page(build_card(price="€39", airline="Vueling")))
        client = _FakeSweepClient(post_text="totally unrelated", get_text=html)
        source = GoogleFlightsHttpSource(client=client)
        cards = source.fetch(FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1))
        self.assertEqual(cards[0].airline, "Vueling")
        self.assertEqual(cards[0].price, "€39")
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(len(client.gets), 1)

    def test_empty_compact_does_not_download_html(self) -> None:
        client = _FakeSweepClient(post_text=_compact_body())
        source = GoogleFlightsHttpSource(client=client)
        with self.assertRaises(NoFlightsFound):
            source.fetch(FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1))
        self.assertEqual(client.gets, [])

    def test_source_raises_blocked_on_shopping_403(self) -> None:
        client = _FakeSweepClient(post_status=403, post_text="no")
        source = GoogleFlightsHttpSource(client=client)
        with self.assertRaises(GoogleFlightsBlocked):
            source.fetch(FlightQuery("MAD", "BCN", date(2026, 9, 1), max_stops=1))
        self.assertEqual(client.gets, [])


if __name__ == "__main__":
    unittest.main()
