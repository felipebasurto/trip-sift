from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Sequence, Tuple

from trip_sift.flights import (
    DEFAULT_BAGGAGE_BUFFER_EUR,
    parse_route_specs,
    search_flights,
    write_report_atomic,
)
from trip_sift.hotels import search_hotels, write_hotel_report_atomic
from trip_sift.models import (
    AppliedHotelFilters,
    CancellationEvidence,
    FlightQuery,
    HotelQuery,
    HotelQueryFailure,
    HotelQuerySuccess,
    PropertyTypeEvidence,
    QueryFailure,
    QuerySuccess,
)

FLIGHTS_EXAMPLES = """\
Examples:
  trip-sift flights MAD-BCN:2026-09-01
  trip-sift flights MAD-LHR:2026-09-25 LHR-MAD:2026-09-27 --max-stops 0
  trip-sift flights MAD-BCN:2026-09-01,2026-09-02 --top 5 --save results/search.json
"""

HOTELS_EXAMPLES = """\
Examples:
  trip-sift hotels Prague 2026-12-04 2026-12-07
  trip-sift hotels "Prague, Czech Republic" 2026-12-04 2026-12-10 --top 5
  trip-sift hotels Prague 2026-12-04 2026-12-07 --entire-home --min-rating 8.5
  trip-sift hotels Prague 2026-12-04 2026-12-07 --save results/hotels.json
"""


def _parse_and_validate(args: argparse.Namespace) -> Tuple[FlightQuery, ...]:
    if args.top <= 0:
        raise ValueError("--top must be a positive integer")
    if args.baggage_buffer < 0:
        raise ValueError("--baggage-buffer must not be negative")
    if args.adults < 1:
        raise ValueError("--adults must be at least 1")
    queries = parse_route_specs(
        args.routes,
        max_stops=args.max_stops,
        adults=args.adults,
        cabin=args.cabin,
    )
    today = date.today()
    for query in queries:
        if query.departure_date < today:
            raise ValueError(f"departure date is in the past: {query.departure_date.isoformat()}")
    return queries


def _format_stops(stops_count: Optional[int]) -> str:
    if stops_count is None:
        return "?"
    if stops_count == 0:
        return "direct"
    return f"{stops_count} stop" + ("s" if stops_count > 1 else "")


def _format_airline(airline: Optional[str]) -> str:
    text = airline or "?"
    return text if len(text) <= 40 else text[:39] + "…"


def _format_ranking_note(offer) -> str:
    if offer.baggage_buffer_eur:
        total = offer.price_eur + offer.baggage_buffer_eur
        return f"  (+{offer.baggage_buffer_eur} bag = {total:.0f} € ranked)"
    return "  [baggage?]" if offer.needs_bag_verify else ""


def _parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc


def _build_hotel_query(args: argparse.Namespace) -> HotelQuery:
    check_in = _parse_iso_date(args.check_in, "check-in")
    check_out = _parse_iso_date(args.check_out, "check-out")
    return HotelQuery(
        location=args.location,
        check_in=check_in,
        check_out=check_out,
        adults=args.adults,
        rooms=args.rooms,
        min_rating=args.min_rating,
        entire_home=args.entire_home,
        free_cancellation=not args.allow_non_refundable,
    )


def _validate_hotel_args(args: argparse.Namespace) -> HotelQuery:
    if args.top <= 0:
        raise ValueError("--top must be a positive integer")
    return _build_hotel_query(args)


def _print_report(report) -> None:
    any_success = False
    for result in report.queries:
        query = result.query
        header = (
            f"\n=== {query.origin} -> {query.destination}  "
            f"{query.departure_date.isoformat()} (max {query.max_stops} stop(s)) ==="
        )
        print(header)
        if isinstance(result, QuerySuccess):
            any_success = True
            if not result.offers:
                print("  (no eligible offers)")
            for offer in result.offers:
                times = f"{offer.departure or '?'} -> {offer.arrival or '?'}"
                print(
                    f"  {offer.price_eur:>7.0f} €  {offer.duration or '?':<12} "
                    f"{_format_stops(offer.stops_count):<7} {times:<18} "
                    f"{_format_airline(offer.airline)}{_format_ranking_note(offer)}"
                )
            print(
                f"  Raw: {result.raw_count}; "
                f"eligible: {result.eligible_count}; "
                f"shown: {len(result.offers)}"
            )
        elif isinstance(result, QueryFailure):
            print(f"  ERROR: {result.error.message}")
    if any_success:
        print("\nVerify checked baggage on Google Flights before booking.")


def _format_hotel_filter_gloss(query: HotelQuery) -> str:
    parts: list[str] = []
    if query.free_cancellation:
        parts.append("Free cancellation required")
    else:
        parts.append("Non-refundable rates allowed")
    if query.entire_home:
        parts.append(
            "Entire homes/apartments required (cards with unknown property type may remain)"
        )
    if query.min_rating is not None:
        parts.append(f"Minimum rating {query.min_rating:g}")
    return "; ".join(parts)


def _print_hotel_filters(query: HotelQuery, applied: AppliedHotelFilters) -> None:
    chips = "; ".join(applied.chips) if applied.chips else "(none)"
    print(f"  Filters: {_format_hotel_filter_gloss(query)}")
    print(f"  Booking chips: {chips}")


def _format_cancellation_evidence(evidence: CancellationEvidence) -> str:
    if evidence is CancellationEvidence.FREE:
        return "Cancellation: free"
    if evidence is CancellationEvidence.NON_REFUNDABLE:
        return "Cancellation: non-refundable"
    return "Cancellation: unknown"


def _format_property_type_evidence(evidence: PropertyTypeEvidence) -> str:
    if evidence is PropertyTypeEvidence.ENTIRE_HOME:
        return "Property type: entire home confirmed"
    if evidence is PropertyTypeEvidence.NOT_ENTIRE_HOME:
        return "Property type: not entire home"
    return "Property type: unknown"


def _print_hotel_report(report) -> None:
    any_success = False
    for result in report.queries:
        query = result.query
        nights_label = "night" if query.nights == 1 else "nights"
        header = (
            f"\n=== {query.location}  "
            f"{query.check_in.isoformat()} -> {query.check_out.isoformat()} "
            f"({query.nights} {nights_label}, {query.adults} adult(s), "
            f"{query.rooms} room(s)) ==="
        )
        print(header)
        _print_hotel_filters(query, result.applied)
        if isinstance(result, HotelQuerySuccess):
            any_success = True
            if not result.offers:
                print("  (no eligible stays)")
            for offer in result.offers:
                rating = offer.rating or "-"
                address = f"  {offer.address}" if offer.address else ""
                print(f"  {offer.total_price} total stay  rating {rating}  {offer.title}{address}")
                print(f"    {_format_cancellation_evidence(offer.cancellation_evidence)}")
                if query.entire_home:
                    print(f"    {_format_property_type_evidence(offer.property_type_evidence)}")
            print(
                f"  Raw cards: {result.raw_count}; "
                f"eligible: {result.eligible_count}; "
                f"shown: {len(result.offers)}"
            )
        elif isinstance(result, HotelQueryFailure):
            print(f"  ERROR: {result.error.message}")
    if any_success:
        print(
            "\nVerify the final total stay price and cancellation terms on Booking.com "
            "before booking."
        )


def _exit_code(report) -> int:
    failures = sum(result.status == "error" for result in report.queries)
    if failures == 0:
        return 0
    if failures == len(report.queries):
        return 2
    return 3


def _run_flights(args: argparse.Namespace) -> int:
    try:
        queries = _parse_and_validate(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = search_flights(
        queries,
        top=args.top,
        buffer_eur=args.baggage_buffer,
        progress=lambda line: print(line, file=sys.stderr),
    )
    _print_report(report)

    if args.save:
        destination = Path(args.save)
        write_report_atomic(report, destination)
        print(f"\nSaved {destination}")

    return _exit_code(report)


def _run_hotels(args: argparse.Namespace) -> int:
    try:
        query = _validate_hotel_args(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = search_hotels((query,), top=args.top)
    _print_hotel_report(report)

    if args.save:
        destination = Path(args.save)
        write_hotel_report_atomic(report, destination)
        print(f"\nSaved {destination}")

    return _exit_code(report)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search Google Flights and Booking.com locally (prices in EUR)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=FLIGHTS_EXAMPLES,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    flights = sub.add_parser(
        "flights",
        help="One-way Google Flights search (EUR prices)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=FLIGHTS_EXAMPLES,
    )
    flights.add_argument(
        "routes",
        nargs="+",
        help="ORIGIN-DESTINATION:DATE[,DATE...] (IATA codes)",
    )
    flights.add_argument(
        "--max-stops",
        type=int,
        default=1,
        choices=[0, 1],
        help="Maximum stops (default 1)",
    )
    flights.add_argument(
        "--adults",
        type=int,
        default=1,
        help="Number of adults (default 1)",
    )
    flights.add_argument(
        "--cabin",
        default="economy",
        choices=["economy", "premium-economy", "business", "first"],
        help="Cabin class (default economy)",
    )
    flights.add_argument(
        "--top",
        type=int,
        default=8,
        help="Offers per query (default 8)",
    )
    flights.add_argument(
        "--baggage-buffer",
        type=int,
        default=DEFAULT_BAGGAGE_BUFFER_EUR,
        metavar="EUR",
        help=(
            f"EUR added to low-cost fares when ranking (default {DEFAULT_BAGGAGE_BUFFER_EUR}, "
            "0 to rank on fare alone)"
        ),
    )
    flights.add_argument(
        "--save",
        default=None,
        metavar="FILE",
        help="Write JSON report atomically to FILE",
    )

    hotels = sub.add_parser(
        "hotels",
        help="Booking.com hotel search (EUR, es, total-stay prices)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HOTELS_EXAMPLES,
    )
    hotels.add_argument("location", help="City or area name")
    hotels.add_argument("check_in", help="Check-in date (YYYY-MM-DD)")
    hotels.add_argument("check_out", help="Check-out date (YYYY-MM-DD)")
    hotels.add_argument(
        "--adults",
        type=int,
        default=2,
        help="Number of adults (default 2)",
    )
    hotels.add_argument(
        "--rooms",
        type=int,
        default=1,
        help="Number of rooms (default 1)",
    )
    hotels.add_argument(
        "--top",
        type=int,
        default=8,
        help="Stays to show (default 8)",
    )
    hotels.add_argument(
        "--min-rating",
        type=float,
        default=None,
        dest="min_rating",
        metavar="SCORE",
        help="Minimum review score (0-10)",
    )
    hotels.add_argument(
        "--entire-home",
        action="store_true",
        help=("Require entire homes/apartments (cards with unknown property type may remain)"),
    )
    hotels.add_argument(
        "--allow-non-refundable",
        action="store_true",
        help="Include non-refundable stays (default filters to free cancellation)",
    )
    hotels.add_argument(
        "--save",
        default=None,
        metavar="FILE",
        help="Write JSON report atomically to FILE",
    )

    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return 0 if code == 0 else 1

    if args.cmd == "flights":
        return _run_flights(args)
    if args.cmd == "hotels":
        return _run_hotels(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
