"""Argument parsing, terminal tables, and optional JSON saves."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Sequence, Tuple

from viajante.flights import (
    DEFAULT_BAGGAGE_BUFFER_EUR,
    FlightSort,
    parse_route_specs,
    search_flights,
    write_report_atomic,
)
from viajante.hotels import search_hotels, write_hotel_report_atomic
from viajante.models import (
    AppliedHotelFilters,
    CancellationEvidence,
    FlightOffer,
    FlightQuery,
    HotelOffer,
    HotelQuery,
    HotelQueryFailure,
    HotelQuerySuccess,
    LodgingKind,
    QueryFailure,
    QuerySuccess,
)

FLIGHTS_EXAMPLES = """\
Examples:
  viajante flights MAD-BCN:2026-09-01
  viajante flights MAD-OPO:2026-10-09:2026-10-12
  viajante flights MAD-LHR:2026-09-25 LHR-MAD:2026-09-27 --max-stops 0
  viajante flights MAD-BCN:2026-09-01,2026-09-02 --top 5 --sort fare --save results/search.json
"""

HOTELS_EXAMPLES = """\
Examples:
  viajante hotels Prague 2026-12-04 2026-12-07
  viajante hotels "Prague, Czech Republic" 2026-12-04 2026-12-10 --top 5
  viajante hotels Prague 2026-12-04 2026-12-07 --entire-home --min-rating 8.5
  viajante hotels Prague 2026-12-04 2026-12-07 --compare-cancellation
  viajante hotels Prague 2026-12-04 2026-12-07 --save results/hotels.json
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


_CLOCK_ON_DATE = re.compile(r"\s+on\s+\S.*$", re.IGNORECASE)


def _format_clock(text: Optional[str]) -> str:
    if not text:
        return "?"
    cleaned = _CLOCK_ON_DATE.sub("", text.replace("\xa0", " ")).strip()
    return cleaned or text.strip()


def _ranked_total(offer: FlightOffer) -> float:
    return offer.price_eur + offer.baggage_buffer_eur


def _sort_value(offer: FlightOffer, sort: FlightSort) -> float:
    return offer.price_eur if sort == "fare" else _ranked_total(offer)


def _format_ranking_columns(offer: FlightOffer) -> str:
    fare = f"{offer.price_eur:>7.0f} €"
    if offer.baggage_buffer_eur:
        return f"{fare}  {_ranked_total(offer):>7.0f} € ranked"
    extra = "  [baggage?]" if offer.needs_bag_verify else ""
    return f"{fare}{extra}"


def _parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc


def _build_hotel_queries(args: argparse.Namespace) -> Tuple[HotelQuery, ...]:
    check_in = _parse_iso_date(args.check_in, "check-in")
    check_out = _parse_iso_date(args.check_out, "check-out")
    if args.compare_cancellation and args.allow_non_refundable:
        raise ValueError("--compare-cancellation cannot be combined with --allow-non-refundable")
    shared = {
        "location": args.location,
        "check_in": check_in,
        "check_out": check_out,
        "adults": args.adults,
        "rooms": args.rooms,
        "min_rating": args.min_rating,
        "entire_home": args.entire_home,
    }
    if args.compare_cancellation:
        return (
            HotelQuery(**shared, free_cancellation=True),
            HotelQuery(**shared, free_cancellation=False),
        )
    return (HotelQuery(**shared, free_cancellation=not args.allow_non_refundable),)


def _validate_hotel_args(args: argparse.Namespace) -> Tuple[HotelQuery, ...]:
    if args.top <= 0:
        raise ValueError("--top must be a positive integer")
    return _build_hotel_queries(args)


def _print_best_pairs(report, sort: FlightSort) -> None:
    results = report.queries
    index = 0
    while index + 1 < len(results):
        outbound, inbound = results[index], results[index + 1]
        if not (
            isinstance(outbound, QuerySuccess)
            and isinstance(inbound, QuerySuccess)
            and outbound.query.origin == inbound.query.destination
            and outbound.query.destination == inbound.query.origin
            and outbound.offers
            and inbound.offers
        ):
            index += 1
            continue
        out_offer = min(outbound.offers, key=lambda offer: _sort_value(offer, sort))
        back_offer = min(inbound.offers, key=lambda offer: _sort_value(offer, sort))
        out_value = _sort_value(out_offer, sort)
        back_value = _sort_value(back_offer, sort)
        unit = "ranked" if sort == "ranked" else "fare"
        print(
            f"\nBest pair ({unit}): "
            f"{outbound.query.origin}->{outbound.query.destination} {out_value:.0f} € {unit} + "
            f"{inbound.query.origin}->{inbound.query.destination} {back_value:.0f} € {unit} = "
            f"{out_value + back_value:.0f} €"
        )
        index += 2


def _print_report(report, *, sort: FlightSort = "ranked") -> None:
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
                times = f"{_format_clock(offer.departure)} -> {_format_clock(offer.arrival)}"
                print(
                    f"  {_format_ranking_columns(offer)}  {offer.duration or '?':<12} "
                    f"{_format_stops(offer.stops_count):<7} {times:<18} "
                    f"{_format_airline(offer.airline)}"
                )
            print(
                f"  Raw: {result.raw_count}; "
                f"eligible: {result.eligible_count}; "
                f"shown: {len(result.offers)}"
            )
        elif isinstance(result, QueryFailure):
            print(f"  ERROR: {result.error.message}")
    _print_best_pairs(report, sort)
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


def _format_cancellation_evidence(
    evidence: CancellationEvidence,
    *,
    query: HotelQuery,
    applied: AppliedHotelFilters,
) -> str:
    if evidence is CancellationEvidence.FREE:
        return "Cancellation: free"
    if evidence is CancellationEvidence.NON_REFUNDABLE:
        return "Cancellation: non-refundable"
    if query.free_cancellation and "oos=1" in applied.chips:
        return "Cancellation: filter applied; card silent"
    return "Cancellation: unknown"


def _format_lodging_kind(kind: LodgingKind) -> str:
    if kind is LodgingKind.ENTIRE_HOME:
        return "Lodging: entire home"
    if kind is LodgingKind.PRIVATE_ROOM:
        return "Lodging: private room"
    if kind is LodgingKind.HOTEL:
        return "Lodging: hotel"
    return "Lodging: unknown"


def _format_unit_hints(offer: HotelOffer) -> Optional[str]:
    parts: list[str] = []
    if offer.bedrooms is not None:
        parts.append(f"{offer.bedrooms} bedroom" + ("" if offer.bedrooms == 1 else "s"))
    if offer.bathrooms is not None:
        parts.append(f"{offer.bathrooms} bathroom" + ("" if offer.bathrooms == 1 else "s"))
    if offer.beds is not None:
        parts.append(f"{offer.beds} bed" + ("" if offer.beds == 1 else "s"))
    return ", ".join(parts) if parts else None


def _print_hotel_offer_details(
    offer: HotelOffer,
    *,
    query: HotelQuery,
    applied: AppliedHotelFilters,
) -> None:
    cancellation = _format_cancellation_evidence(
        offer.cancellation_evidence,
        query=query,
        applied=applied,
    )
    print(f"    {cancellation}")
    print(f"    {_format_lodging_kind(offer.lodging_kind)}")
    units = _format_unit_hints(offer)
    if units:
        print(f"    {units}")


def _hotel_offer_identity(offer: HotelOffer) -> Tuple[str, str]:
    title = " ".join(offer.title.split()).casefold()
    address = " ".join((offer.address or "").split()).casefold()
    return (title, address)


def _cheapest_by_identity(offers: Sequence[HotelOffer]) -> dict[Tuple[str, str], HotelOffer]:
    chosen: dict[Tuple[str, str], HotelOffer] = {}
    for offer in offers:
        key = _hotel_offer_identity(offer)
        current = chosen.get(key)
        if current is None or offer.total_price_eur < current.total_price_eur:
            chosen[key] = offer
    return chosen


def _join_cancellation_rows(
    free_offers: Sequence[HotelOffer],
    open_offers: Sequence[HotelOffer],
) -> Tuple[Tuple[HotelOffer, Optional[HotelOffer], Optional[HotelOffer]], ...]:
    free_map = _cheapest_by_identity(free_offers)
    open_map = _cheapest_by_identity(open_offers)
    rows: list[Tuple[HotelOffer, Optional[HotelOffer], Optional[HotelOffer]]] = []
    for key in set(free_map) | set(open_map):
        free_offer = free_map.get(key)
        open_offer = open_map.get(key)
        sample = free_offer or open_offer
        assert sample is not None
        rows.append((sample, free_offer, open_offer))
    rows.sort(
        key=lambda row: (
            min(offer.total_price_eur for offer in (row[1], row[2]) if offer is not None),
            row[0].title.casefold(),
        )
    )
    return tuple(rows)


def _print_cancellation_compare(
    free_result: HotelQuerySuccess,
    open_result: HotelQuerySuccess,
) -> None:
    print("\n=== Cancellation compare ===")
    rows = _join_cancellation_rows(free_result.offers, open_result.offers)
    if not rows:
        print("  (no matching stays)")
        return
    for sample, free_offer, open_offer in rows:
        free_label = f"{free_offer.total_price_eur:.0f} €" if free_offer is not None else "—"
        open_label = f"{open_offer.total_price_eur:.0f} €" if open_offer is not None else "—"
        delta = ""
        if free_offer is not None and open_offer is not None:
            diff = free_offer.total_price_eur - open_offer.total_price_eur
            delta = f"  delta {diff:.0f} €"
        print(f"  {sample.title}  free cancel {free_label}  no free cancel {open_label}{delta}")
        detail_query = free_result.query if free_offer is not None else open_result.query
        detail_applied = free_result.applied if free_offer is not None else open_result.applied
        _print_hotel_offer_details(sample, query=detail_query, applied=detail_applied)


def _print_hotel_report(report) -> None:
    any_success = False
    queries = report.queries
    if (
        len(queries) == 2
        and isinstance(queries[0], HotelQuerySuccess)
        and isinstance(queries[1], HotelQuerySuccess)
        and queries[0].query.free_cancellation
        and not queries[1].query.free_cancellation
    ):
        _print_cancellation_compare(queries[0], queries[1])
    for result in queries:
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
                rating = f"{offer.rating_score:.1f}" if offer.rating_score is not None else "-"
                address = f"  {offer.address}" if offer.address else ""
                print(f"  {offer.total_price} total stay  rating {rating}  {offer.title}{address}")
                _print_hotel_offer_details(offer, query=query, applied=result.applied)
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
        sort=args.sort,
    )
    _print_report(report, sort=args.sort)

    if args.save:
        destination = Path(args.save)
        write_report_atomic(report, destination)
        print(f"\nSaved {destination}")

    return _exit_code(report)


def _run_hotels(args: argparse.Namespace) -> int:
    try:
        queries = _validate_hotel_args(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = search_hotels(
        queries,
        top=args.top,
        progress=lambda line: print(line, file=sys.stderr),
    )
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
        help="ORIGIN-DESTINATION:DATE[,DATE...] or ORIGIN-DESTINATION:OUT:BACK (IATA codes)",
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
        "--sort",
        default="ranked",
        choices=["ranked", "fare"],
        help="Order and select --top by ranked total (default) or fare",
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
        "--compare-cancellation",
        action="store_true",
        help=(
            "Run two sequential searches (free cancellation, then rates without that chip) "
            "and print a joined price table"
        ),
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
