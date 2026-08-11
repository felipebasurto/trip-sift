from __future__ import annotations

from typing import Optional, Sequence

from trip_sift.models import SearchError, SearchErrorCode

REQUEST_DELAY_SECONDS = 4.5
REQUEST_JITTER_SECONDS = 1.5
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 8.0
BACKOFF_JITTER_SECONDS = 3.0

BROWSER_UNAVAILABLE_MARKERS = (
    "executable doesn't exist",
    "playwright install",
    "browsertype.launch",
    "no module named 'playwright'",
)

NON_RETRIABLE_CODES = frozenset({SearchErrorCode.NO_RESULTS, SearchErrorCode.BROWSER_UNAVAILABLE})


def classify_failure(
    exc: BaseException,
    *,
    provider: str,
    no_results_markers: Sequence[str] = (),
    no_results_message: Optional[str] = None,
) -> SearchError:
    text = f"{type(exc).__name__}: {exc}".strip()
    lowered = text.casefold()
    if no_results_markers and any(marker in lowered for marker in no_results_markers):
        return SearchError(
            code=SearchErrorCode.NO_RESULTS,
            message=no_results_message or f"{provider} returned no results.",
        )
    if any(marker in lowered for marker in BROWSER_UNAVAILABLE_MARKERS):
        return SearchError(
            code=SearchErrorCode.BROWSER_UNAVAILABLE,
            message=("Chromium is not available to Playwright. Run 'playwright install chromium'."),
        )
    return SearchError(code=SearchErrorCode.FETCH_FAILED, message=text)


def retry_backoff_seconds(attempt: int, random_gen) -> float:
    return BACKOFF_BASE_SECONDS * (2**attempt) + random_gen.uniform(0, BACKOFF_JITTER_SECONDS)


def inter_query_delay_seconds(random_gen) -> float:
    return REQUEST_DELAY_SECONDS + random_gen.uniform(0, REQUEST_JITTER_SECONDS)
