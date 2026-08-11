from __future__ import annotations

import atexit
import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from fast_flights import FlightData, Passengers
from fast_flights.core import parse_response
from fast_flights.filter import TFSData
from fast_flights.schema import Result
from playwright.sync_api import sync_playwright

from trip_sift.models import FlightQuery

SEARCH_URL = "https://www.google.com/travel/flights"
STATE_FILENAME = "pw_state_google.json"

PAGE_TIMEOUT_MS = 60_000
CONSENT_CLICK_TIMEOUT_MS = 5_000
CONSENT_SETTLE_MS = 1_500
RESULTS_SELECTOR = ".eQ35Ce"

CONSENT_SELECTORS = [
    'text="Accept all"',
    'text="Reject all"',
    'text="Aceptar todo"',
    'text="Rechazar todo"',
    'button:has-text("Accept")',
]

BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})


@dataclass(frozen=True)
class BrowserSessionConfig:
    state_filename: str
    locale: str
    viewport: Optional[Mapping[str, int]] = None
    user_agent: Optional[str] = None


class ChromiumSession:
    def __init__(self, state_dir: Path, config: BrowserSessionConfig) -> None:
        self._state_dir = state_dir
        self._config = config
        self._state_path = state_dir / config.state_filename
        self._pw = None
        self._browser = None
        self._context = None
        self._atexit_registered = False

    def new_page(self) -> object:
        return self._ensure_context().new_page()

    def reset(self) -> None:
        with contextlib.suppress(Exception):
            self._persist_state()
        self._teardown()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._persist_state()
        self._teardown()

    def _ensure_context(self) -> object:
        if self._context is None:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            options: dict[str, object] = {
                "locale": self._config.locale,
                "storage_state": str(self._state_path) if self._state_path.exists() else None,
            }
            if self._config.viewport is not None:
                options["viewport"] = dict(self._config.viewport)
            if self._config.user_agent is not None:
                options["user_agent"] = self._config.user_agent
            self._context = self._browser.new_context(**options)
            self._context.route("**/*", self._block_heavy_resources)
            if not self._atexit_registered:
                atexit.register(self.close)
                self._atexit_registered = True
        return self._context

    @staticmethod
    def _block_heavy_resources(route) -> None:
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
            route.abort()
        else:
            route.continue_()

    def _persist_state(self) -> None:
        if self._context is None:
            return
        self._state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(".json.tmp")
        try:
            self._context.storage_state(path=str(temporary))
            os.replace(temporary, self._state_path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()

    def _teardown(self) -> None:
        for handle in (self._context, self._browser):
            if handle is not None:
                with contextlib.suppress(Exception):
                    handle.close()
        if self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()
        self._pw = self._browser = self._context = None


class HtmlResponse:
    """Satisfies the shape fast-flights' parser expects, so we own the transport."""

    status_code = 200

    def __init__(self, html: str) -> None:
        self.text = html
        self.text_markdown = html


class GoogleFlightsSource:
    def __init__(self, state_dir: Path, session: Optional[ChromiumSession] = None) -> None:
        self._session = session or ChromiumSession(
            state_dir,
            BrowserSessionConfig(state_filename=STATE_FILENAME, locale="en-US"),
        )

    def fetch(self, query: FlightQuery) -> Result:
        params = self._fetch_params(self._build_tfs(query))
        qs = "&".join(f"{key}={value}" for key, value in params.items())
        return parse_response(HtmlResponse(self._fetch_html(f"{SEARCH_URL}?{qs}")))

    def reset(self) -> None:
        self._session.reset()

    def close(self) -> None:
        self._session.close()

    def _fetch_html(self, url: str) -> str:
        page = self._session.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            if "consent.google" in page.url:
                self._dismiss_consent(page)
            page.locator(RESULTS_SELECTOR).wait_for(timeout=PAGE_TIMEOUT_MS)
            return page.evaluate("() => document.querySelector('[role=\"main\"]')?.innerHTML || ''")
        finally:
            with contextlib.suppress(Exception):
                page.close()

    @staticmethod
    def _dismiss_consent(page) -> None:
        for selector in CONSENT_SELECTORS:
            try:
                button = page.locator(selector).first
                if button.count() > 0:
                    button.click(timeout=CONSENT_CLICK_TIMEOUT_MS)
                    break
            except Exception:
                continue
        page.wait_for_timeout(CONSENT_SETTLE_MS)

    @staticmethod
    def _build_tfs(query: FlightQuery) -> TFSData:
        leg = FlightData(
            date=query.departure_date.isoformat(),
            from_airport=query.origin,
            to_airport=query.destination,
            max_stops=query.max_stops,
        )
        return TFSData.from_interface(
            flight_data=[leg],
            trip="one-way",
            passengers=Passengers(adults=1),
            seat="economy",
            max_stops=query.max_stops,
        )

    @staticmethod
    def _fetch_params(tfs: TFSData) -> dict[str, str]:
        return {
            "tfs": tfs.as_b64().decode("utf-8"),
            "hl": "en",
            "tfu": "EgQIABABIgA",
            "curr": "EUR",
        }
