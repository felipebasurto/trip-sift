"""Encode a one-way Google Flights tfs query from FlightQuery."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence

from viajante.models import FlightCabin, FlightQuery

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
_PASSENGER_ADULT = 1


def encode_tfs(query: FlightQuery) -> str:
    """Encode a one-way Google Flights `tfs` query parameter."""
    return base64.b64encode(_info(query)).decode("ascii")


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


def _flight_data(query: FlightQuery) -> bytes:
    return (
        _string(_FLIGHT_DATE, query.departure_date.isoformat())
        + _varint_field(_FLIGHT_MAX_STOPS, query.max_stops)
        + _len_delim(_FLIGHT_FROM, _airport(query.origin))
        + _len_delim(_FLIGHT_TO, _airport(query.destination))
    )


def _info(query: FlightQuery) -> bytes:
    passengers = (_PASSENGER_ADULT,) * query.adults
    return (
        _len_delim(_INFO_DATA, _flight_data(query))
        + _packed_enums(_INFO_PASSENGERS, passengers)
        + _varint_field(_INFO_SEAT, _SEAT[query.cabin])
        + _varint_field(_INFO_TRIP, _TRIP_ONE_WAY)
    )
