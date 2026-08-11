from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from trip_sift.flights import parse_route_specs, search_flights, write_report_atomic
from trip_sift.models import QueryFailure, QuerySuccess


FLIGHTS_EXAMPLES = """\
Examples:
  trip-sift flights MAD-BCN:2026-09-01
  trip-sift flights MAD-LHR:2026-09-25 LHR-MAD:2026-09-27 --max-stops 0
  trip-sift flights MAD-BCN:2026-09-01,2026-09-02 --top 5 --save results/search.json
"""


def _validate_args(args: argparse.Namespace) -> None:
    if args.max_stops not in (0, 1):
        raise ValueError("--max-stops must be 0 or 1")
    if args.top <= 0:
        raise ValueError("--top must be a positive integer")
    parse_route_specs(args.routes, max_stops=args.max_stops)


def _print_report(report) -> None:
    for result in report.queries:
        query = result.query
        header = (
            f"\n=== {query.origin} -> {query.destination}  "
            f"{query.departure_date.isoformat()} (max {query.max_stops} stop(s)) ==="
        )
        print(header)
        if isinstance(result, QuerySuccess):
            if not result.offers:
                print("  (no eligible offers)")
            for offer in result.offers:
                bag = " [baggage?]" if offer.needs_bag_verify else ""
                airline = (offer.airline or "")[:40]
                duration = offer.duration or "?"
                print(
                    f"  {offer.price_eur:>7.0f} €  {duration:<12} "
                    f"{offer.departure} -> {offer.arrival}  {airline}{bag}"
                )
        elif isinstance(result, QueryFailure):
            print(f"  ERROR: {result.error.message}")


def _exit_code(report) -> int:
    failures = sum(isinstance(result, QueryFailure) for result in report.queries)
    if failures == 0:
        return 0
    if failures == len(report.queries):
        return 2
    return 3


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search Google Flights locally (EUR prices, en locale)",
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
        "--top",
        type=int,
        default=8,
        help="Offers per query (default 8)",
    )
    flights.add_argument(
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

    if args.cmd != "flights":
        parser.print_help()
        return 1

    try:
        _validate_args(args)
        queries = parse_route_specs(args.routes, max_stops=args.max_stops)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = search_flights(queries, top=args.top)
    _print_report(report)

    if args.save:
        destination = Path(args.save)
        write_report_atomic(report, destination)
        print(f"\nSaved {destination}")

    return _exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
