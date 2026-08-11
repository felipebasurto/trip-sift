from __future__ import annotations

import unittest

from trip_sift.parsers import parse_duration_hours, parse_price_eur, parse_stops_count


PRICE_CASES = [
    ("€129", 129.0),
    ("€1234", 1234.0),
    ("€1234.56", 1234.56),
    ("1.024 €", 1024.0),
    ("520 €", 520.0),
    ("12,50 €", 12.5),
    ("€1,024.50", 1024.5),
    ("1.234.567 €", 1234567.0),
    ("235\xa0€", 235.0),
    ("€ 99", 99.0),
    ("120.50", 120.5),
    ("", None),
    ("gratis", None),
]

DURATION_CASES = [
    ("15 h 45 min", 15.75),
    ("8 h 20 min", 8 + 20 / 60),
    ("55 min", 55 / 60),
    ("2 h", 2.0),
    ("", None),
    (None, None),
]

STOPS_CASES = [
    ("Directo", 0),
    ("Nonstop", 0),
    ("Direct", 0),
    ("1 escala", 1),
    ("1 stop", 1),
    (0, 0),
    (1, 1),
    ("Unknown", None),
    (None, None),
]


class ParserTests(unittest.TestCase):
    def test_parse_price_eur(self) -> None:
        for text, want in PRICE_CASES:
            with self.subTest(text=text):
                self.assertEqual(parse_price_eur(text), want)

    def test_parse_duration_hours(self) -> None:
        for text, want in DURATION_CASES:
            with self.subTest(text=text):
                got = parse_duration_hours(text)
                if want is None:
                    self.assertIsNone(got)
                else:
                    self.assertIsNotNone(got)
                    assert got is not None
                    self.assertAlmostEqual(got, want)

    def test_parse_stops_count(self) -> None:
        for text, want in STOPS_CASES:
            with self.subTest(text=text):
                self.assertEqual(parse_stops_count(text), want)


if __name__ == "__main__":
    unittest.main()
