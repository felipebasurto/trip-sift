"""Offline IATA airport lookup. No network."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

import airportsdata

_IATA: Optional[dict[str, Mapping[str, object]]] = None


@dataclass(frozen=True)
class Airport:
    iata: str
    name: str
    city: str
    country: str

    def to_dict(self) -> Mapping[str, str]:
        return {
            "iata": self.iata,
            "name": self.name,
            "city": self.city,
            "country": self.country,
        }


def _iata_table() -> dict[str, Mapping[str, object]]:
    global _IATA
    if _IATA is None:
        _IATA = airportsdata.load("IATA")
    return _IATA


def is_known_iata(code: str) -> bool:
    text = code.strip().upper()
    return len(text) == 3 and text.isalpha() and text in _iata_table()


def get_airport(code: str) -> Optional[Airport]:
    text = code.strip().upper()
    row = _iata_table().get(text)
    if row is None:
        return None
    return _from_row(text, row)


def lookup_airports(query: str, *, limit: int = 20) -> Tuple[Airport, ...]:
    needle = " ".join(query.split()).casefold()
    if not needle:
        raise ValueError("airport query must not be blank")
    table = _iata_table()
    exact = get_airport(needle.upper()) if len(needle) == 3 and needle.isalpha() else None
    city_hits: list[Airport] = []
    other_hits: list[Airport] = []
    seen = {exact.iata} if exact is not None else set()
    for code, row in table.items():
        if code in seen:
            continue
        airport = _from_row(code, row)
        city = airport.city.casefold()
        name = airport.name.casefold()
        if city == needle:
            city_hits.append(airport)
        elif needle in city or needle in name or needle == airport.iata.casefold():
            other_hits.append(airport)
    city_hits.sort(key=lambda item: (item.iata, item.name))
    other_hits.sort(key=lambda item: (item.iata, item.name))
    rows = ([exact] if exact is not None else []) + city_hits + other_hits
    return tuple(rows[:limit])


def _from_row(code: str, row: Mapping[str, object]) -> Airport:
    return Airport(
        iata=code,
        name=str(row.get("name") or code),
        city=str(row.get("city") or ""),
        country=str(row.get("country") or ""),
    )
