from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from random import Random
from typing import List, Sequence, Tuple, Union
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import trip_sift.hotels as hotels_module
from trip_sift.hotels import (
    CONSENT_SELECTORS,
    DESKTOP_USER_AGENT,
    EMPTY_STATE_SELECTORS,
    PROPERTY_CARD_SELECTOR,
    _BookingHotelsSource,
    _HotelPage,
    _is_eligible,
    _normalize_card,
    _rank_offers,
    _RawHotelCard,
    _run_search,
    build_applied_filters,
    search_hotels,
    write_hotel_report_atomic,
)
from trip_sift.models import (
    AppliedHotelFilters,
    CancellationEvidence,
    HotelOffer,
    HotelQuery,
    HotelQueryFailure,
    HotelQuerySuccess,
    HotelSearchReport,
    PropertyTypeEvidence,
    SearchErrorCode,
)
from trip_sift.orchestration import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_JITTER_SECONDS,
    MAX_ATTEMPTS,
    REQUEST_DELAY_SECONDS,
    REQUEST_JITTER_SECONDS,
)

ScriptedResponse = Union[_HotelPage, Exception]


class FakeSource:
    def __init__(self, responses: Sequence[ScriptedResponse]) -> None:
        self.responses = list(responses)
        self.fetch_calls: List[Tuple[HotelQuery, AppliedHotelFilters, int]] = []
        self.reset_calls = 0
        self.closed = False

    def fetch(
        self,
        query: HotelQuery,
        applied: AppliedHotelFilters,
        limit: int,
    ) -> _HotelPage:
        self.fetch_calls.append((query, applied, limit))
        if not self.responses:
            raise RuntimeError("missing fake response")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def reset(self) -> None:
        self.reset_calls += 1

    def close(self) -> None:
        self.closed = True


class FakeElement:
    def __init__(self, text: str, href: str | None = None) -> None:
        self.text = text
        self.href = href

    def inner_text(self) -> str:
        return self.text

    def get_attribute(self, name: str) -> str | None:
        return self.href if name == "href" else None


class FakeProviderCard:
    def __init__(
        self,
        elements: dict[str, FakeElement],
        details: str,
    ) -> None:
        self.elements = elements
        self.details = details

    def query_selector(self, selector: str) -> FakeElement | None:
        return self.elements.get(selector)

    def inner_text(self) -> str:
        return self.details


class FakeLocator:
    def __init__(
        self,
        *,
        count: int = 0,
        visible: bool = False,
        wait_error: Exception | None = None,
    ) -> None:
        self._count = count
        self._visible = visible
        self._wait_error = wait_error
        self.click_timeouts: List[int] = []

    @property
    def first(self) -> "FakeLocator":
        return self

    def count(self) -> int:
        return self._count

    def is_visible(self) -> bool:
        return self._visible

    def click(self, *, timeout: int) -> None:
        self.click_timeouts.append(timeout)

    def wait_for(self, *, timeout: int) -> None:
        if self._wait_error is not None:
            raise self._wait_error


class FakePage:
    def __init__(
        self,
        cards: Sequence[FakeProviderCard] = (),
        empty_selectors: Sequence[str] = (),
        locators: dict[str, FakeLocator] | None = None,
        wait_error: Exception | None = None,
    ) -> None:
        self.cards = list(cards)
        self.empty_selectors = set(empty_selectors)
        self.locators = locators or {}
        self.wait_error = wait_error
        self.closed = False
        self.wait_timeouts: List[int] = []

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        return None

    def locator(self, selector: str) -> FakeLocator:
        if selector in self.locators:
            return self.locators[selector]
        result_selector = ", ".join((PROPERTY_CARD_SELECTOR,) + EMPTY_STATE_SELECTORS)
        if selector == result_selector:
            return FakeLocator(count=1, visible=True, wait_error=self.wait_error)
        visible = selector in self.empty_selectors
        return FakeLocator(count=int(visible), visible=visible)

    def query_selector_all(self, selector: str) -> List[FakeProviderCard]:
        return self.cards if selector == PROPERTY_CARD_SELECTOR else []

    def wait_for_timeout(self, timeout: int) -> None:
        self.wait_timeouts.append(timeout)

    def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(
        self,
        page: FakePage,
        *,
        storage_error: Exception | None = None,
    ) -> None:
        self.page = page
        self.storage_error = storage_error
        self.closed = False
        self.route_calls: List[Tuple[str, object]] = []
        self.storage_paths: List[str] = []

    def new_page(self) -> FakePage:
        return self.page

    def storage_state(self, *, path: str) -> None:
        self.storage_paths.append(path)
        if self.storage_error is not None:
            raise self.storage_error
        Path(path).write_text('{"cookies": []}', encoding="utf-8")

    def route(self, pattern: str, handler: object) -> None:
        self.route_calls.append((pattern, handler))

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext | None = None) -> None:
        self.context = context
        self.closed = False
        self.context_options: List[dict[str, object]] = []

    def new_context(self, **options: object) -> FakeContext:
        self.context_options.append(options)
        if self.context is None:
            raise RuntimeError("missing fake context")
        return self.context

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.launch_options: List[dict[str, object]] = []

    def launch(self, **options: object) -> FakeBrowser:
        self.launch_options.append(options)
        return self.browser


class FakePlaywright:
    def __init__(self, chromium: FakeChromium | None = None) -> None:
        self.chromium = chromium
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakePlaywrightStarter:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright
        self.start_calls = 0

    def start(self) -> FakePlaywright:
        self.start_calls += 1
        return self.playwright


class FakeRoute:
    def __init__(self, resource_type: str) -> None:
        self.request = type("Request", (), {"resource_type": resource_type})()
        self.aborted = False
        self.continued = False

    def abort(self) -> None:
        self.aborted = True

    def continue_(self) -> None:
        self.continued = True


def query(**overrides: object) -> HotelQuery:
    values = {
        "location": "Lisboa",
        "check_in": date(2026, 12, 4),
        "check_out": date(2026, 12, 8),
        "adults": 2,
        "rooms": 1,
        "min_rating": None,
        "entire_home": False,
        "free_cancellation": True,
    }
    values.update(overrides)
    return HotelQuery(**values)


def card(
    *,
    title: str = "Casa Azul",
    address: str | None = "Centro, Lisboa",
    total_price: str = "400 €",
    rating: str | None = "Puntuación: 8,7",
    details: str = "Cancelación gratis · Apartamento entero · 2 dormitorios · 1 baño · 3 camas",
    link: str | None = "https://www.booking.com/hotel/pt/casa-azul.html",
) -> _RawHotelCard:
    return _RawHotelCard(
        title=title,
        address=address,
        total_price=total_price,
        rating=rating,
        details=details,
        link=link,
    )


def provider_card(
    *,
    title: str | None = "Casa Azul",
    total_price: str | None = "400 €",
    rating: str | None = "8,7 Fabuloso\n1.234 comentarios",
    address: str | None = "Centro, Lisboa",
    link: str | None = "/hotel/pt/casa-azul.html?aid=123#reviews",
    details: str = "Cancelación gratis · Apartamento entero",
) -> FakeProviderCard:
    elements = {}
    if title is not None:
        elements['[data-testid="title"]'] = FakeElement(title)
    if total_price is not None:
        elements['[data-testid="price-and-discounted-price"]'] = FakeElement(total_price)
    if rating is not None:
        elements['[data-testid="review-score"]'] = FakeElement(rating)
    if address is not None:
        elements['[data-testid="address-link"]'] = FakeElement(address)
    if link is not None:
        elements['a[data-testid="title-link"]'] = FakeElement("", href=link)
    return FakeProviderCard(elements, details)


def offer(
    *,
    title: str = "Casa Azul",
    address: str | None = "Centro, Lisboa",
    total_price_eur: float = 400.0,
    rating_score: float | None = 8.7,
    cancellation: CancellationEvidence = CancellationEvidence.FREE,
    property_type: PropertyTypeEvidence = PropertyTypeEvidence.ENTIRE_HOME,
) -> HotelOffer:
    return HotelOffer(
        title=title,
        address=address,
        total_price=f"{total_price_eur:g} €",
        total_price_eur=total_price_eur,
        rating=None if rating_score is None else f"{rating_score:g}",
        rating_score=rating_score,
        details="details",
        cancellation_evidence=cancellation,
        property_type_evidence=property_type,
        bedrooms=None,
        bathrooms=None,
        beds=None,
        link=None,
    )


class AppliedFiltersTests(unittest.TestCase):
    def test_provider_pacing_constants(self) -> None:
        self.assertEqual(
            (
                REQUEST_DELAY_SECONDS,
                REQUEST_JITTER_SECONDS,
                MAX_ATTEMPTS,
                BACKOFF_BASE_SECONDS,
                BACKOFF_JITTER_SECONDS,
            ),
            (4.5, 1.5, 3, 8.0, 3.0),
        )

    def test_default_url_and_free_cancellation_chip(self) -> None:
        applied = build_applied_filters(query())
        params = parse_qs(urlparse(applied.url).query)

        self.assertEqual(applied.chips, ("oos=1",))
        self.assertEqual(
            params,
            {
                "ss": ["Lisboa"],
                "checkin": ["2026-12-04"],
                "checkout": ["2026-12-08"],
                "group_adults": ["2"],
                "no_rooms": ["1"],
                "group_children": ["0"],
                "selected_currency": ["EUR"],
                "lang": ["es"],
                "nflt": ["oos=1"],
            },
        )

    def test_non_refundable_opt_in_has_no_filter_chip(self) -> None:
        applied = build_applied_filters(query(free_cancellation=False))

        self.assertEqual(applied.chips, ())
        self.assertNotIn("nflt", parse_qs(urlparse(applied.url).query))

    def test_entire_home_uses_exact_chips(self) -> None:
        applied = build_applied_filters(query(entire_home=True))

        self.assertEqual(
            applied.chips,
            ("oos=1", "privacy_type=3", "ht_id=201"),
        )
        self.assertEqual(
            parse_qs(urlparse(applied.url).query)["nflt"],
            ["oos=1;privacy_type=3;ht_id=201"],
        )


class PureHotelLogicTests(unittest.TestCase):
    def test_normalize_card_preserves_raw_values_and_parses_details(self) -> None:
        normalized = _normalize_card(card())

        assert normalized is not None
        self.assertEqual(normalized.total_price, "400 €")
        self.assertEqual(normalized.total_price_eur, 400.0)
        self.assertEqual(normalized.rating, "Puntuación: 8,7")
        self.assertEqual(normalized.rating_score, 8.7)
        self.assertEqual(normalized.details, card().details)
        self.assertEqual(normalized.cancellation_evidence, CancellationEvidence.FREE)
        self.assertEqual(
            normalized.property_type_evidence,
            PropertyTypeEvidence.ENTIRE_HOME,
        )
        self.assertEqual(
            (normalized.bedrooms, normalized.bathrooms, normalized.beds),
            (2, 1, 3),
        )

    def test_rating_is_never_parsed_from_card_details(self) -> None:
        normalized = _normalize_card(
            card(rating=None, details="Puntuación: 9,9 · Cancelación gratis")
        )

        assert normalized is not None
        self.assertIsNone(normalized.rating_score)

    def test_normalize_card_parses_realistic_dedicated_rating_text(self) -> None:
        normalized = _normalize_card(
            card(
                rating="8,7 Fabuloso",
                details="2 dormitorios · Puntuación del barrio: 4,1",
            )
        )

        assert normalized is not None
        self.assertEqual(normalized.rating_score, 8.7)

    def test_normalize_card_does_not_publish_review_count_as_rating(self) -> None:
        normalized = _normalize_card(card(rating="Fabuloso 1.234 comentarios"))

        assert normalized is not None
        self.assertIsNone(normalized.rating_score)

    def test_invalid_prices_are_dropped(self) -> None:
        for price in ("", "consultar", "0 €", "-20 €"):
            with self.subTest(price=price):
                self.assertIsNone(_normalize_card(card(total_price=price)))

    def test_strict_minimum_rating_rejects_unknown_and_low_scores(self) -> None:
        strict_query = query(min_rating=8.0)

        self.assertFalse(_is_eligible(offer(rating_score=None), strict_query))
        self.assertFalse(_is_eligible(offer(rating_score=7.9), strict_query))
        self.assertTrue(_is_eligible(offer(rating_score=8.0), strict_query))

    def test_requested_evidence_rejects_only_explicit_contradictions(self) -> None:
        strict_query = query(entire_home=True, free_cancellation=True)

        self.assertFalse(
            _is_eligible(
                offer(cancellation=CancellationEvidence.NON_REFUNDABLE),
                strict_query,
            )
        )
        self.assertFalse(
            _is_eligible(
                offer(property_type=PropertyTypeEvidence.NOT_ENTIRE_HOME),
                strict_query,
            )
        )
        self.assertTrue(
            _is_eligible(
                offer(
                    cancellation=CancellationEvidence.UNKNOWN,
                    property_type=PropertyTypeEvidence.UNKNOWN,
                ),
                strict_query,
            )
        )
        self.assertTrue(
            _is_eligible(
                offer(cancellation=CancellationEvidence.NON_REFUNDABLE),
                query(free_cancellation=False),
            )
        )

    def test_rank_deduplicates_normalized_identity_and_sorts_ties(self) -> None:
        ranked = _rank_offers(
            (
                offer(title="Beta", total_price_eur=200, rating_score=None),
                offer(title="alpha", total_price_eur=200, rating_score=8.5),
                offer(
                    title=" ALPHA ",
                    address="  Centro,   Lisboa ",
                    total_price_eur=200,
                    rating_score=9.0,
                ),
                offer(title="Cheap", total_price_eur=150, rating_score=7.0),
            ),
            top=3,
        )

        self.assertEqual([row.title for row in ranked], ["Cheap", "ALPHA", "Beta"])
        with self.assertRaises(ValueError):
            _rank_offers((), top=0)


class HotelOrchestrationTests(unittest.TestCase):
    def test_failure_then_success_resets_once(self) -> None:
        source = FakeSource(
            [
                RuntimeError("temporary"),
                _HotelPage(cards=(card(title="Recovered"),)),
            ]
        )
        sleeps: List[float] = []

        report = _run_search(
            (query(),),
            top=8,
            source=source,
            sleep=sleeps.append,
            random_gen=Random(3),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        self.assertIsInstance(report.queries[0], HotelQuerySuccess)
        self.assertEqual(source.reset_calls, 1)
        self.assertEqual(len(source.fetch_calls), 2)
        self.assertEqual(len(sleeps), 1)

    def test_retries_same_applied_filters_then_returns_typed_failure(self) -> None:
        hotel_query = query(entire_home=True)
        source = FakeSource([RuntimeError("blocked")] * MAX_ATTEMPTS)
        sleeps: List[float] = []
        expected_random = Random(7)
        expected_backoffs = [
            BACKOFF_BASE_SECONDS * (2**attempt) + expected_random.uniform(0, BACKOFF_JITTER_SECONDS)
            for attempt in range(MAX_ATTEMPTS - 1)
        ]

        report = _run_search(
            (hotel_query,),
            top=5,
            source=source,
            sleep=sleeps.append,
            random_gen=Random(7),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        self.assertEqual(len(source.fetch_calls), MAX_ATTEMPTS)
        self.assertEqual(source.reset_calls, MAX_ATTEMPTS)
        first_applied = source.fetch_calls[0][1]
        self.assertTrue(all(call[1] is first_applied for call in source.fetch_calls))
        self.assertEqual(
            first_applied.chips,
            ("oos=1", "privacy_type=3", "ht_id=201"),
        )
        self.assertTrue(all(call[2] == 24 for call in source.fetch_calls))
        self.assertEqual(sleeps, expected_backoffs)
        result = report.queries[0]
        self.assertIsInstance(result, HotelQueryFailure)
        assert isinstance(result, HotelQueryFailure)
        self.assertEqual(result.error.code, SearchErrorCode.FETCH_FAILED)
        self.assertEqual(result.error.message, "RuntimeError: blocked")

    def test_missing_chromium_fails_immediately_without_backoff(self) -> None:
        source = FakeSource(
            [
                RuntimeError(
                    "Executable doesn't exist at /ms-playwright/chromium/headless"
                )
            ]
        )
        sleeps: List[float] = []

        report = _run_search(
            (query(),),
            top=8,
            source=source,
            sleep=sleeps.append,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        result = report.queries[0]
        self.assertIsInstance(result, HotelQueryFailure)
        assert isinstance(result, HotelQueryFailure)
        self.assertEqual(result.error.code, SearchErrorCode.BROWSER_UNAVAILABLE)
        self.assertEqual(len(source.fetch_calls), 1)
        self.assertEqual(source.reset_calls, 1)
        self.assertEqual(sleeps, [])

    def test_two_queries_sleep_once_between_queries(self) -> None:
        source = FakeSource([_HotelPage(cards=()), _HotelPage(cards=())])
        sleeps: List[float] = []
        expected = REQUEST_DELAY_SECONDS + Random(11).uniform(0, REQUEST_JITTER_SECONDS)

        _run_search(
            (query(), query(location="Porto")),
            top=8,
            source=source,
            sleep=sleeps.append,
            random_gen=Random(11),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        self.assertEqual(sleeps, [expected])

    def test_explicit_empty_page_is_success(self) -> None:
        source = FakeSource([_HotelPage(cards=())])

        report = _run_search(
            (query(),),
            top=8,
            source=source,
            sleep=lambda _: None,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        result = report.queries[0]
        self.assertIsInstance(result, HotelQuerySuccess)
        assert isinstance(result, HotelQuerySuccess)
        self.assertEqual((result.raw_count, result.eligible_count), (0, 0))
        self.assertEqual(result.offers, ())
        self.assertEqual(source.reset_calls, 0)

    def test_counts_use_raw_cards_and_deduplicated_eligible_offers(self) -> None:
        source = FakeSource(
            [
                _HotelPage(
                    cards=(
                        card(title="Cheap", total_price="100 €"),
                        card(title="Cheap", total_price="100 €"),
                        card(title="Second", total_price="200 €"),
                        card(title="Broken", total_price="consultar"),
                    )
                )
            ]
        )

        report = _run_search(
            (query(),),
            top=1,
            source=source,
            sleep=lambda _: None,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        result = report.queries[0]
        assert isinstance(result, HotelQuerySuccess)
        self.assertEqual(result.raw_count, 4)
        self.assertEqual(result.eligible_count, 2)
        self.assertEqual([row.title for row in result.offers], ["Cheap"])
        self.assertEqual(source.fetch_calls[0][2], 24)

    def test_run_search_uses_rank_offers_for_full_eligible_count(self) -> None:
        source = FakeSource(
            [
                _HotelPage(
                    cards=(
                        card(title="One", total_price="100 €"),
                        card(title="One", total_price="100 €"),
                        card(title="Two", total_price="200 €"),
                    )
                )
            ]
        )

        with patch(
            "trip_sift.hotels._rank_offers",
            wraps=_rank_offers,
        ) as rank_offers:
            report = _run_search(
                (query(),),
                top=1,
                source=source,
                sleep=lambda _: None,
                random_gen=Random(0),
                now=lambda: datetime(2026, 8, 10, 10, 0, 0),
            )

        result = report.queries[0]
        assert isinstance(result, HotelQuerySuccess)
        rank_offers.assert_called_once()
        self.assertEqual(result.eligible_count, 2)
        self.assertEqual([row.title for row in result.offers], ["One"])

    def test_run_search_validates_without_fetching(self) -> None:
        source = FakeSource([])
        kwargs = {
            "source": source,
            "sleep": lambda _: None,
            "random_gen": Random(0),
            "now": lambda: datetime(2026, 8, 10, 10, 0, 0),
        }

        with self.assertRaises(ValueError):
            _run_search((), top=8, **kwargs)
        with self.assertRaises(ValueError):
            _run_search((query(),), top=0, **kwargs)

        self.assertEqual(source.fetch_calls, [])

    def test_search_validates_before_source_construction(self) -> None:
        with patch("trip_sift.hotels._BookingHotelsSource") as source_class:
            with self.assertRaises(ValueError):
                search_hotels(())
            with self.assertRaises(ValueError):
                search_hotels((query(),), top=0)

        source_class.assert_not_called()

    def test_search_always_closes_source(self) -> None:
        source = FakeSource([RuntimeError("blocked")] * MAX_ATTEMPTS)

        with (
            patch("trip_sift.hotels._BookingHotelsSource", return_value=source),
            patch("trip_sift.hotels.time.sleep"),
        ):
            report = search_hotels((query(),))

        self.assertTrue(source.closed)
        self.assertIsInstance(report.queries[0], HotelQueryFailure)

    def test_report_writer_delegates_to_atomic_storage(self) -> None:
        report = HotelSearchReport(
            searched_at=datetime(2026, 8, 10, 10, 0, 0),
            queries=(),
        )
        destination = Path("hotels.json")

        with patch("trip_sift.hotels.write_json_atomic") as writer:
            write_hotel_report_atomic(report, destination)

        writer.assert_called_once_with(report.to_dict(), destination)

    def test_report_writer_produces_json_atomically(self) -> None:
        report = HotelSearchReport(
            searched_at=datetime(2026, 8, 10, 10, 0, 0),
            queries=(),
        )

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "nested" / "hotels.json"
            write_hotel_report_atomic(report, destination)

            self.assertTrue(destination.exists())
            self.assertFalse(destination.with_suffix(".json.tmp").exists())
            self.assertIn('"provider": "booking.com"', destination.read_text())

    def test_module_has_no_city_specific_or_private_policy(self) -> None:
        source = Path(hotels_module.__file__).read_text(encoding="utf-8").casefold()

        for forbidden in ("praga", "prague", "median", "suburb", "tram"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class BookingHotelsSourceTests(unittest.TestCase):
    def source_for(self, page: FakePage, state_dir: Path) -> _BookingHotelsSource:
        source = _BookingHotelsSource(state_dir)
        source._context = FakeContext(page)
        return source

    def test_ensure_context_configures_browser_and_registers_atexit_once(self) -> None:
        context = FakeContext(FakePage())
        browser = FakeBrowser(context)
        chromium = FakeChromium(browser)
        playwright = FakePlaywright(chromium)
        starter = FakePlaywrightStarter(playwright)

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            state_path = state_dir / "pw_state_booking.json"
            state_path.write_text('{"cookies": []}', encoding="utf-8")
            source = _BookingHotelsSource(state_dir)

            with (
                patch(
                    "playwright.sync_api.sync_playwright",
                    return_value=starter,
                ),
                patch("trip_sift.hotels.atexit.register") as register,
            ):
                first = source._ensure_context()
                second = source._ensure_context()

            self.assertIs(first, context)
            self.assertIs(second, context)
            self.assertEqual(starter.start_calls, 1)
            self.assertEqual(chromium.launch_options, [{"headless": True}])
            self.assertEqual(
                browser.context_options,
                [
                    {
                        "locale": "es-ES",
                        "viewport": {"width": 1280, "height": 900},
                        "user_agent": DESKTOP_USER_AGENT,
                        "storage_state": str(state_path),
                    }
                ],
            )
            self.assertEqual(context.route_calls[0][0], "**/*")
            register.assert_called_once_with(source.close)
            source.close()

    def test_resource_blocking_aborts_heavy_and_continues_other_requests(self) -> None:
        image_route = FakeRoute("image")
        script_route = FakeRoute("script")

        _BookingHotelsSource._block_heavy_resources(image_route)
        _BookingHotelsSource._block_heavy_resources(script_route)

        self.assertTrue(image_route.aborted)
        self.assertFalse(image_route.continued)
        self.assertFalse(script_route.aborted)
        self.assertTrue(script_route.continued)

    def test_visible_consent_button_is_clicked(self) -> None:
        button = FakeLocator(count=1, visible=True)
        page = FakePage(locators={CONSENT_SELECTORS[0]: button})

        _BookingHotelsSource._dismiss_consent(page)

        self.assertEqual(button.click_timeouts, [3_000])
        self.assertEqual(page.wait_timeouts, [800])

    def test_selector_timeout_closes_page_and_propagates(self) -> None:
        page = FakePage(wait_error=RuntimeError("selector timeout"))

        with tempfile.TemporaryDirectory() as tmp:
            source = self.source_for(page, Path(tmp))
            with self.assertRaisesRegex(RuntimeError, "selector timeout"):
                source.fetch(query(), build_applied_filters(query()), 24)

        self.assertTrue(page.closed)

    def test_recognized_empty_state_returns_empty_page_and_closes_page(self) -> None:
        page = FakePage(empty_selectors=(EMPTY_STATE_SELECTORS[0],))

        with tempfile.TemporaryDirectory() as tmp:
            source = self.source_for(page, Path(tmp))
            result = source.fetch(query(), build_applied_filters(query()), 24)

        self.assertEqual(result.cards, ())
        self.assertTrue(page.closed)

    def test_unrecognized_no_card_state_raises_and_closes_page(self) -> None:
        page = FakePage()

        with tempfile.TemporaryDirectory() as tmp:
            source = self.source_for(page, Path(tmp))
            with self.assertRaises(RuntimeError):
                source.fetch(query(), build_applied_filters(query()), 24)

        self.assertTrue(page.closed)

    def test_malformed_cards_are_skipped_while_good_cards_survive(self) -> None:
        page = FakePage(cards=(provider_card(title=None), provider_card(title="Good")))

        with tempfile.TemporaryDirectory() as tmp:
            source = self.source_for(page, Path(tmp))
            result = source.fetch(query(), build_applied_filters(query()), 24)

        self.assertEqual([row.title for row in result.cards], ["Good"])
        self.assertTrue(page.closed)

    def test_fetch_honors_limit(self) -> None:
        page = FakePage(
            cards=(
                provider_card(title="One"),
                provider_card(title="Two"),
                provider_card(title="Three"),
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            source = self.source_for(page, Path(tmp))
            result = source.fetch(query(), build_applied_filters(query()), 2)

        self.assertEqual([row.title for row in result.cards], ["One", "Two"])

    def test_fetch_cleans_relative_link_and_keeps_rating_first_line(self) -> None:
        page = FakePage(cards=(provider_card(),))

        with tempfile.TemporaryDirectory() as tmp:
            source = self.source_for(page, Path(tmp))
            result = source.fetch(query(), build_applied_filters(query()), 24)

        extracted = result.cards[0]
        self.assertEqual(extracted.rating, "8,7 Fabuloso")
        self.assertEqual(
            extracted.link,
            "https://www.booking.com/hotel/pt/casa-azul.html",
        )
        self.assertTrue(page.closed)

    def test_blank_price_crosses_boundary_and_normalizes_to_empty_success(self) -> None:
        page = FakePage(cards=(provider_card(total_price=None),))

        with tempfile.TemporaryDirectory() as tmp:
            provider_source = self.source_for(page, Path(tmp))
            provider_page = provider_source.fetch(
                query(),
                build_applied_filters(query()),
                24,
            )

        report = _run_search(
            (query(),),
            top=8,
            source=FakeSource([provider_page]),
            sleep=lambda _: None,
            random_gen=Random(0),
            now=lambda: datetime(2026, 8, 10, 10, 0, 0),
        )

        result = report.queries[0]
        assert isinstance(result, HotelQuerySuccess)
        self.assertEqual((result.raw_count, result.eligible_count), (1, 0))
        self.assertEqual(result.offers, ())

    def test_close_persists_state_atomically_and_tears_down(self) -> None:
        page = FakePage()
        context = FakeContext(page)
        browser = FakeBrowser()
        playwright = FakePlaywright()

        with tempfile.TemporaryDirectory() as tmp:
            source = _BookingHotelsSource(Path(tmp))
            source._context = context
            source._browser = browser
            source._pw = playwright
            source.close()

            state_path = Path(tmp) / "pw_state_booking.json"
            self.assertEqual(
                state_path.read_text(encoding="utf-8"),
                '{"cookies": []}',
            )
            self.assertFalse((Path(tmp) / "pw_state_booking.json.tmp").exists())
            self.assertEqual(
                context.storage_paths,
                [str(Path(tmp) / "pw_state_booking.json.tmp")],
            )

        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertTrue(playwright.stopped)
        self.assertIsNone(source._context)
        self.assertIsNone(source._browser)
        self.assertIsNone(source._pw)

    def test_reset_tears_down_when_state_persistence_fails(self) -> None:
        context = FakeContext(FakePage(), storage_error=RuntimeError("state write"))
        browser = FakeBrowser()
        playwright = FakePlaywright()

        with tempfile.TemporaryDirectory() as tmp:
            source = _BookingHotelsSource(Path(tmp))
            source._context = context
            source._browser = browser
            source._pw = playwright
            source.reset()

        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertTrue(playwright.stopped)
        self.assertIsNone(source._context)
        self.assertIsNone(source._browser)
        self.assertIsNone(source._pw)


if __name__ == "__main__":
    unittest.main()
