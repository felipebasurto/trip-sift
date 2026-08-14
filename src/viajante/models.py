"""Domain types and JSON mapping for flight and hotel reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal, Mapping, Optional, Tuple, Union

FlightCabin = Literal["economy", "premium-economy", "business", "first"]


@dataclass(frozen=True)
class FlightQuery:
    origin: str
    destination: str
    departure_date: date
    max_stops: int = 1
    adults: int = 1
    cabin: FlightCabin = "economy"

    def __post_init__(self) -> None:
        origin = self.origin.strip().upper()
        destination = self.destination.strip().upper()
        if len(origin) != 3 or not origin.isalpha():
            raise ValueError(f"invalid origin IATA code: {self.origin!r}")
        if len(destination) != 3 or not destination.isalpha():
            raise ValueError(f"invalid destination IATA code: {self.destination!r}")
        if self.max_stops not in (0, 1):
            raise ValueError("max_stops must be 0 or 1")
        if self.adults < 1:
            raise ValueError("adults must be at least 1")
        if self.cabin not in ("economy", "premium-economy", "business", "first"):
            raise ValueError(f"invalid cabin: {self.cabin!r}")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)

    def to_dict(self) -> Mapping[str, object]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "departure_date": self.departure_date.isoformat(),
            "max_stops": self.max_stops,
            "adults": self.adults,
            "cabin": self.cabin,
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
    layover_city: Optional[str] = None
    layover_hours: Optional[float] = None

    def __post_init__(self) -> None:
        if self.price_eur <= 0:
            raise ValueError("price_eur must be positive")
        if self.baggage_buffer_eur < 0:
            raise ValueError("baggage_buffer_eur must not be negative")
        if self.baggage_buffer_eur > 0 and not self.needs_bag_verify:
            raise ValueError("a baggage buffer only applies to a carrier flagged for verification")

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
            "layover_city": self.layover_city,
            "layover_hours": self.layover_hours,
            "baggage_buffer_eur": self.baggage_buffer_eur,
            "needs_bag_verify": self.needs_bag_verify,
        }


class SearchErrorCode(str, Enum):
    FETCH_FAILED = "fetch_failed"
    NO_RESULTS = "no_results"
    BROWSER_UNAVAILABLE = "browser_unavailable"


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
    eligible_count: int
    offers: Tuple[FlightOffer, ...]
    status: Literal["ok"] = field(init=False, default="ok")

    def __post_init__(self) -> None:
        if self.raw_count < self.eligible_count:
            raise ValueError("raw_count must be >= eligible_count")
        if self.eligible_count < len(self.offers):
            raise ValueError("eligible_count must be >= number of offers")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "query": self.query.to_dict(),
            "raw_count": self.raw_count,
            "eligible_count": self.eligible_count,
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

FetchBackend = Literal["sweep", "detail", "sweep_then_detail"]


@dataclass(frozen=True)
class SearchReport:
    searched_at: datetime
    queries: Tuple[QueryResult, ...]
    locale: str = "en"
    currency: str = "EUR"
    fetch_backend: Optional[FetchBackend] = None
    fetch_ms: Optional[int] = None
    schema_version: int = field(init=False, default=1)

    def __post_init__(self) -> None:
        if self.searched_at.tzinfo is not None:
            object.__setattr__(
                self,
                "searched_at",
                self.searched_at.astimezone(timezone.utc).replace(tzinfo=None),
            )

    def to_dict(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "searched_at": self.searched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "currency": self.currency,
            "locale": self.locale,
            "fetch_backend": self.fetch_backend,
            "fetch_ms": self.fetch_ms,
            "queries": [result.to_dict() for result in self.queries],
        }


class CancellationEvidence(str, Enum):
    FREE = "free"
    NON_REFUNDABLE = "non_refundable"
    UNKNOWN = "unknown"


class PropertyTypeEvidence(str, Enum):
    ENTIRE_HOME = "entire_home"
    NOT_ENTIRE_HOME = "not_entire_home"
    UNKNOWN = "unknown"


class LodgingKind(str, Enum):
    ENTIRE_HOME = "entire_home"
    PRIVATE_ROOM = "private_room"
    HOTEL = "hotel"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HotelQuery:
    location: str
    check_in: date
    check_out: date
    adults: int = 2
    rooms: int = 1
    min_rating: Optional[float] = None
    entire_home: bool = False
    free_cancellation: bool = True

    def __post_init__(self) -> None:
        location = " ".join(self.location.split())
        if not location:
            raise ValueError("location must not be blank")
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        if self.adults <= 0:
            raise ValueError("adults must be positive")
        if self.rooms <= 0:
            raise ValueError("rooms must be positive")
        if self.min_rating is not None and not 0.0 <= self.min_rating <= 10.0:
            raise ValueError("min_rating must be between 0.0 and 10.0")
        object.__setattr__(self, "location", location)

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    def to_dict(self) -> Mapping[str, object]:
        return {
            "location": self.location,
            "check_in": self.check_in.isoformat(),
            "check_out": self.check_out.isoformat(),
            "adults": self.adults,
            "rooms": self.rooms,
            "min_rating": self.min_rating,
            "entire_home": self.entire_home,
            "free_cancellation": self.free_cancellation,
            "nights": self.nights,
        }


@dataclass(frozen=True)
class AppliedHotelFilters:
    chips: Tuple[str, ...]
    url: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "chips": list(self.chips),
            "url": self.url,
        }


@dataclass(frozen=True)
class HotelOffer:
    title: str
    address: Optional[str]
    total_price: str
    total_price_eur: float
    rating: Optional[str]
    rating_score: Optional[float]
    details: str
    cancellation_evidence: CancellationEvidence
    property_type_evidence: PropertyTypeEvidence
    lodging_kind: LodgingKind
    bedrooms: Optional[int]
    bathrooms: Optional[int]
    beds: Optional[int]
    link: Optional[str]

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title:
            raise ValueError("title must not be blank")
        if self.total_price_eur <= 0:
            raise ValueError("total_price_eur must be positive")
        if self.rating_score is not None and not 0.0 <= self.rating_score <= 10.0:
            raise ValueError("rating_score must be between 0.0 and 10.0")
        object.__setattr__(self, "title", title)

    def to_dict(self) -> Mapping[str, object]:
        return {
            "title": self.title,
            "address": self.address,
            "total_price": self.total_price,
            "total_price_eur": self.total_price_eur,
            "rating": self.rating,
            "rating_score": self.rating_score,
            "details": self.details,
            "cancellation_evidence": self.cancellation_evidence.value,
            "property_type_evidence": self.property_type_evidence.value,
            "lodging_kind": self.lodging_kind.value,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "beds": self.beds,
            "link": self.link,
        }


@dataclass(frozen=True)
class HotelQuerySuccess:
    query: HotelQuery
    applied: AppliedHotelFilters
    raw_count: int
    eligible_count: int
    offers: Tuple[HotelOffer, ...]
    status: Literal["ok"] = field(init=False, default="ok")

    def __post_init__(self) -> None:
        if self.raw_count < self.eligible_count:
            raise ValueError("raw_count must be >= eligible_count")
        if self.eligible_count < len(self.offers):
            raise ValueError("eligible_count must be >= number of offers")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "query": self.query.to_dict(),
            "applied": self.applied.to_dict(),
            "raw_count": self.raw_count,
            "eligible_count": self.eligible_count,
            "offers": [offer.to_dict() for offer in self.offers],
        }


@dataclass(frozen=True)
class HotelQueryFailure:
    query: HotelQuery
    applied: AppliedHotelFilters
    error: SearchError
    status: Literal["error"] = field(init=False, default="error")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "query": self.query.to_dict(),
            "applied": self.applied.to_dict(),
            "error": self.error.to_dict(),
        }


HotelQueryResult = Union[HotelQuerySuccess, HotelQueryFailure]


@dataclass(frozen=True)
class HotelSearchReport:
    searched_at: datetime
    queries: Tuple[HotelQueryResult, ...]
    locale: str = "es"
    currency: str = "EUR"
    schema_version: int = field(init=False, default=1)
    provider: Literal["booking.com"] = field(init=False, default="booking.com")
    price_basis: Literal["total_stay"] = field(init=False, default="total_stay")

    def __post_init__(self) -> None:
        if self.searched_at.tzinfo is not None:
            object.__setattr__(
                self,
                "searched_at",
                self.searched_at.astimezone(timezone.utc).replace(tzinfo=None),
            )

    def to_dict(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "searched_at": self.searched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "currency": self.currency,
            "locale": self.locale,
            "price_basis": self.price_basis,
            "queries": [result.to_dict() for result in self.queries],
        }
