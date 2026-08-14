"""Owned Google Flights shopping RPC: request encode and compact parse."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote, urlencode

from viajante.models import FlightCabin, FlightQuery

SHOPPING_RESULTS_URL = (
    "https://www.google.com/_/FlightsFrontendUi/data/"
    "travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
)

_SEAT: Mapping[FlightCabin, int] = {
    "economy": 1,
    "premium-economy": 2,
    "business": 3,
    "first": 4,
}
_TRIP_ONE_WAY = 2
_ANTI_XSSI = ")]}'"


class CompactParseMiss(ValueError):
    """Compact shopping body was not a readable itinerary payload."""


class EmptyShoppingResults(Exception):
    """Shopping RPC returned itinerary slots with no priced offers."""


@dataclass(frozen=True)
class CompactFlightCard:
    airline: Optional[str]
    departure: Optional[str]
    arrival: Optional[str]
    duration: Optional[str]
    stops: Optional[str]
    price: Optional[str]


def build_shopping_inner(query: FlightQuery, token: Optional[str] = None) -> list[Any]:
    flight = [
        [[[query.origin, 0]]],
        [[[query.destination, 0]]],
        None,
        _TRIP_ONE_WAY,
        None,
        None,
        query.departure_date.isoformat(),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        3,
    ]
    return [
        [None, None, None, token],
        [
            None,
            None,
            2,
            None,
            [],
            _SEAT[query.cabin],
            [query.adults, 0, 0, 0],
            None,
            None,
            None,
            None,
            None,
            None,
            [flight],
            None,
            None,
            None,
            1,
        ],
        0,
        1,
        0,
        1,
    ]


def build_shopping_request(
    query: FlightQuery,
    *,
    html_lang: str = "en",
    currency: str = "EUR",
) -> tuple[str, str]:
    inner = json.dumps(build_shopping_inner(query), separators=(",", ":"))
    envelope = json.dumps([None, inner], separators=(",", ":"))
    params = {
        "hl": html_lang,
        "curr": currency,
        "soc-app": "162",
        "soc-platform": "1",
        "soc-device": "1",
        "rt": "c",
    }
    url = f"{SHOPPING_RESULTS_URL}?{urlencode(params)}"
    return url, f"f.req={quote(envelope, safe='')}"


SHOPPING_POST_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "X-Same-Domain": "1",
    "Origin": "https://www.google.com",
    "Referer": "https://www.google.com/travel/flights",
}


def parse_shopping_body(text: str) -> tuple[CompactFlightCard, ...]:
    payload = _first_wrb_data(text)
    if payload is None:
        raise CompactParseMiss("no wrb.fr shopping payload")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CompactParseMiss("wrb.fr data is not JSON") from exc
    if not isinstance(data, list):
        raise CompactParseMiss("wrb.fr data is not a list")
    items = _collect_itineraries(data)
    if not items:
        if _has_itinerary_slots(data):
            raise EmptyShoppingResults()
        raise CompactParseMiss("no itinerary groups in shopping payload")
    cards = tuple(card for item in items if (card := _itinerary_to_card(item)) is not None)
    if not cards:
        raise CompactParseMiss("itineraries had no priced offers")
    return cards


def _first_wrb_data(text: str) -> Optional[str]:
    body = text.lstrip()
    if body.startswith(_ANTI_XSSI):
        body = body[len(_ANTI_XSSI) :].lstrip()
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(body):
        while idx < len(body) and body[idx] in " \t\r\n":
            idx += 1
        if idx >= len(body):
            break
        if body[idx].isdigit():
            newline = body.find("\n", idx)
            if newline < 0:
                break
            length_text = body[idx:newline].strip()
            if length_text.isdigit():
                size = int(length_text)
                chunk = body[newline + 1 : newline + 1 + size]
                try:
                    obj, _ = decoder.raw_decode(chunk)
                except json.JSONDecodeError:
                    idx = newline + 1
                    continue
                found = _wrb_data_string(obj)
                if found is not None:
                    return found
                idx = newline + 1 + size
                continue
        try:
            obj, _ = decoder.raw_decode(body, idx)
        except json.JSONDecodeError:
            break
        return _wrb_data_string(obj)
    return None


def _wrb_data_string(obj: object) -> Optional[str]:
    if (
        isinstance(obj, list)
        and obj
        and isinstance(obj[0], list)
        and obj[0]
        and obj[0][0] == "wrb.fr"
    ):
        obj = obj[0]
    if isinstance(obj, list) and len(obj) >= 3 and obj[0] == "wrb.fr" and isinstance(obj[2], str):
        return obj[2]
    return None


def _has_itinerary_slots(data: list[Any]) -> bool:
    return len(data) > 3 and isinstance(data[2], list)


def _collect_itineraries(data: list[Any]) -> list[Any]:
    found: list[Any] = []
    seen: set[int] = set()
    for index in (2, 3):
        if index >= len(data):
            continue
        for item in _iter_group(data[index]):
            marker = id(item)
            if marker in seen:
                continue
            seen.add(marker)
            found.append(item)
    return found


def _iter_group(group: object) -> list[Any]:
    if not isinstance(group, list) or not group:
        return []
    first = group[0]
    if isinstance(first, list) and first and _looks_like_itinerary(first[0]):
        return [item for item in first if _looks_like_itinerary(item)]
    if _looks_like_itinerary(first):
        return [item for item in group if _looks_like_itinerary(item)]
    return []


def _looks_like_itinerary(item: object) -> bool:
    if not isinstance(item, list) or len(item) < 2:
        return False
    flight = item[0]
    if not isinstance(flight, list) or len(flight) < 10:
        return False
    airlines = flight[1]
    if not isinstance(airlines, list) or not airlines or not isinstance(airlines[0], str):
        return False
    departure = flight[5]
    if not (
        isinstance(departure, list)
        and len(departure) >= 2
        and isinstance(departure[0], int)
        and isinstance(departure[1], int)
    ):
        return False
    return isinstance(flight[9], int)


def _itinerary_to_card(item: list[Any]) -> Optional[CompactFlightCard]:
    flight = item[0]
    airlines = [name for name in flight[1] if isinstance(name, str)]
    price = _price_text(item[1])
    if price is None:
        return None
    return CompactFlightCard(
        airline=", ".join(airlines) or None,
        departure=_format_clock(flight[5]) or _clock_from_leg(flight[2], 0, 8),
        arrival=_format_clock(flight[8]) or _clock_from_leg(flight[2], -1, 10),
        duration=_format_duration_minutes(flight[9]),
        stops=_format_stops(flight[2]),
        price=price,
    )


def _price_text(block: object) -> Optional[str]:
    if not isinstance(block, list) or not block:
        return None
    first = block[0]
    if not isinstance(first, list) or len(first) < 2:
        return None
    amount = first[1]
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return None
    if float(amount).is_integer():
        return f"€{int(amount)}"
    return f"€{amount}"


def _clock_from_leg(legs: object, index: int, field: int) -> Optional[str]:
    if not isinstance(legs, list) or not legs:
        return None
    try:
        leg = legs[index]
    except IndexError:
        return None
    if not isinstance(leg, list) or field >= len(leg):
        return None
    return _format_clock(leg[field])


def _format_clock(value: object) -> Optional[str]:
    if not isinstance(value, list) or len(value) < 2:
        return None
    hour, minute = value[0], value[1]
    if not isinstance(hour, int) or not isinstance(minute, int):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12
    if hour12 == 0:
        hour12 = 12
    return f"{hour12}:{minute:02d} {suffix}"


def _format_duration_minutes(minutes: int) -> str:
    hours, mins = divmod(max(0, minutes), 60)
    if hours and mins:
        return f"{hours} hr {mins} min"
    if hours:
        return f"{hours} hr"
    return f"{mins} min"


def _format_stops(legs: object) -> Optional[str]:
    if not isinstance(legs, list) or not legs or not all(isinstance(leg, list) for leg in legs):
        return None
    count = len(legs) - 1
    if count <= 0:
        return "Nonstop"
    if count == 1:
        return "1 stop"
    return f"{count} stops"
