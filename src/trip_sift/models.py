from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Literal, Mapping, Optional, Tuple, Union


@dataclass(frozen=True)
class FlightQuery:
    origin: str
    destination: str
    departure_date: date
    max_stops: int = 1

    def __post_init__(self) -> None:
        origin = self.origin.strip().upper()
        destination = self.destination.strip().upper()
        if len(origin) != 3 or not origin.isalpha():
            raise ValueError(f"invalid origin IATA code: {self.origin!r}")
        if len(destination) != 3 or not destination.isalpha():
            raise ValueError(f"invalid destination IATA code: {self.destination!r}")
        if self.max_stops not in (0, 1):
            raise ValueError("max_stops must be 0 or 1")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)

    def to_dict(self) -> Mapping[str, object]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "departure_date": self.departure_date.isoformat(),
            "max_stops": self.max_stops,
        }


@dataclass(frozen=True)
class FlightOffer:
    airline: Optional[str]
    departure: Optional[str]
    arrival: Optional[str]
    price: str
    price_eur: float
    duration: Optional[str]
    duration_hours: Optional[float]
    stops: Optional[str]
    stops_count: Optional[int]
    baggage_buffer_eur: int
    needs_bag_verify: bool

    def __post_init__(self) -> None:
        if self.price_eur <= 0:
            raise ValueError("price_eur must be positive")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "airline": self.airline,
            "departure": self.departure,
            "arrival": self.arrival,
            "price": self.price,
            "price_eur": self.price_eur,
            "duration": self.duration,
            "duration_hours": self.duration_hours,
            "stops": self.stops,
            "stops_count": self.stops_count,
            "baggage_buffer_eur": self.baggage_buffer_eur,
            "needs_bag_verify": self.needs_bag_verify,
        }


class SearchErrorCode(str, Enum):
    FETCH_FAILED = "fetch_failed"


@dataclass(frozen=True)
class SearchError:
    code: SearchErrorCode
    message: str

    def to_dict(self) -> Mapping[str, str]:
        return {"code": self.code.value, "message": self.message}


@dataclass(frozen=True)
class QuerySuccess:
    query: FlightQuery
    raw_count: int
    offers: Tuple[FlightOffer, ...]
    status: Literal["ok"] = field(init=False, default="ok")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "query": self.query.to_dict(),
            "raw_count": self.raw_count,
            "offers": [offer.to_dict() for offer in self.offers],
        }


@dataclass(frozen=True)
class QueryFailure:
    query: FlightQuery
    error: SearchError
    status: Literal["error"] = field(init=False, default="error")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "query": self.query.to_dict(),
            "error": self.error.to_dict(),
        }


QueryResult = Union[QuerySuccess, QueryFailure]


@dataclass(frozen=True)
class SearchReport:
    searched_at: datetime
    queries: Tuple[QueryResult, ...]
    schema_version: int = field(init=False, default=1)
    currency: Literal["EUR"] = field(init=False, default="EUR")
    locale: Literal["es"] = field(init=False, default="es")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "searched_at": self.searched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "currency": self.currency,
            "locale": self.locale,
            "queries": [result.to_dict() for result in self.queries],
        }
