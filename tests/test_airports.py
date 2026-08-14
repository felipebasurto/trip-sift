from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest.mock import patch

from viajante.airports import get_airport, is_known_iata, lookup_airports
from viajante.cli import main
from viajante.models import FlightQuery


class AirportLookupTests(unittest.TestCase):
    def test_mad_resolves(self) -> None:
        airport = get_airport("mad")
        assert airport is not None
        self.assertEqual(airport.iata, "MAD")
        self.assertIn("Madrid", airport.city)
        self.assertTrue(is_known_iata("MAD"))

    def test_london_finds_heathrow_and_gatwick(self) -> None:
        rows = lookup_airports("london")
        codes = {row.iata for row in rows}
        self.assertTrue({"LHR", "LGW", "STN"} <= codes)

    def test_barcelona_finds_bcn(self) -> None:
        rows = lookup_airports("barcelona")
        self.assertIn("BCN", {row.iata for row in rows})

    def test_xxx_is_not_an_airport(self) -> None:
        self.assertFalse(is_known_iata("XXX"))
        self.assertIsNone(get_airport("XXX"))
        with self.assertRaises(ValueError):
            FlightQuery("XXX", "BCN", date(2026, 9, 1))

    def test_blank_query_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            lookup_airports("   ")


class AirportCliTests(unittest.TestCase):
    def test_airports_mad_prints_the_code(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["airports", "MAD"])
        self.assertEqual(code, 0)
        self.assertIn("MAD", buffer.getvalue())
        self.assertIn("Madrid", buffer.getvalue())

    def test_airports_london_prints_major_codes(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["airports", "london"])
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("LHR", output)
        self.assertIn("LGW", output)

    def test_airports_help_lists_examples(self) -> None:
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            code = main(["airports", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("viajante airports london", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
