"""Encode a Google Flights tfs query from a Trip."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence

from viajante.models import FlightCabin, FlightLeg, FlightQuery, MultiCity, RoundTrip, Trip

_VARINT = 0
_LEN = 2

_INFO_DATA = 3
_INFO_PASSENGERS = 8
_INFO_SEAT = 9
_INFO_TRIP = 19

_FLIGHT_DATE = 2
_FLIGHT_MAX_STOPS = 5
_FLIGHT_FROM = 13
_FLIGHT_TO = 14

_AIRPORT_CODE = 2

_SEAT: Mapping[FlightCabin, int] = {
    "economy": 1,
    "premium-economy": 2,
    "business": 3,
    "first": 4,
}
_TRIP_ONE_WAY = 2
_TRIP_ROUND_TRIP = 1
_PASSENGER_ADULT = 1


def encode_tfs(trip: Trip) -> str:
    """Encode a Google Flights `tfs` query parameter."""
    if isinstance(trip, MultiCity):
        raise ValueError("multi-city tfs is gated on a captured Google search URL")
    return _encode_legs(
        trip.legs,
        adults=trip.adults,
        cabin=trip.cabin,
        trip_kind=_tfs_trip_kind(trip),
    )


def _tfs_trip_kind(trip: Trip) -> int:
    if isinstance(trip, RoundTrip):
        return _TRIP_ROUND_TRIP
    if isinstance(trip, FlightQuery):
        return _TRIP_ONE_WAY
    raise ValueError("multi-city tfs is gated on a captured Google search URL")


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        bits = n & 0x7F
        n >>= 7
        if n:
            out.append(bits | 0x80)
        else:
            out.append(bits)
            return bytes(out)


def _key(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _len_delim(field: int, payload: bytes) -> bytes:
    return _key(field, _LEN) + _varint(len(payload)) + payload


def _string(field: int, value: str) -> bytes:
    return _len_delim(field, value.encode("ascii"))


def _varint_field(field: int, value: int) -> bytes:
    return _key(field, _VARINT) + _varint(value)


def _packed_enums(field: int, values: Sequence[int]) -> bytes:
    payload = b"".join(_varint(value) for value in values)
    return _len_delim(field, payload)


def _airport(code: str) -> bytes:
    return _string(_AIRPORT_CODE, code)


def _flight_data(leg: FlightLeg) -> bytes:
    return (
        _string(_FLIGHT_DATE, leg.departure_date.isoformat())
        + _varint_field(_FLIGHT_MAX_STOPS, leg.max_stops)
        + _len_delim(_FLIGHT_FROM, _airport(leg.origin))
        + _len_delim(_FLIGHT_TO, _airport(leg.destination))
    )


def _encode_legs(
    legs: Sequence[FlightLeg],
    *,
    adults: int,
    cabin: FlightCabin,
    trip_kind: int,
) -> str:
    passengers = (_PASSENGER_ADULT,) * adults
    flights = b"".join(_len_delim(_INFO_DATA, _flight_data(leg)) for leg in legs)
    payload = (
        flights
        + _packed_enums(_INFO_PASSENGERS, passengers)
        + _varint_field(_INFO_SEAT, _SEAT[cabin])
        + _varint_field(_INFO_TRIP, trip_kind)
    )
    return base64.b64encode(payload).decode("ascii")
