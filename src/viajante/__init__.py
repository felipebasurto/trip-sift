"""Local Google Flights and Booking.com search for scripts and agents."""

from viajante.flights import search_flights
from viajante.hotels import search_hotels
from viajante.models import (
    CancellationEvidence,
    FlightQuery,
    HotelQuery,
    HotelSearchReport,
    PropertyTypeEvidence,
    SearchReport,
)

__all__ = [
    "CancellationEvidence",
    "FlightQuery",
    "HotelQuery",
    "HotelSearchReport",
    "PropertyTypeEvidence",
    "SearchReport",
    "search_flights",
    "search_hotels",
]
