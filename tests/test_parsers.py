from __future__ import annotations

import unittest

from trip_sift.models import CancellationEvidence, PropertyTypeEvidence
from trip_sift.parsers import (
    parse_cancellation_evidence,
    parse_duration_hours,
    parse_price_eur,
    parse_property_type_evidence,
    parse_rating,
    parse_stops_count,
    parse_unit_hints,
)


PRICE_CASES = [
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

    def test_parse_rating(self) -> None:
        cases = [
            ("Puntuación: 8,4", 8.4),
            ("Scored 8.5", 8.5),
            ("9", 9.0),
            ("Valoración 7,2", 7.2),
            ("Rating: 10.0", 10.0),
            ("", None),
            (None, None),
            ("2 dormitorios 3 camas", None),
            ("Puntuación: 11,0", None),
            ("Scored -1", None),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_rating(text), want)

    def test_parse_cancellation_evidence(self) -> None:
        cases = [
            ("Cancelación gratuita", CancellationEvidence.FREE),
            ("Free cancellation", CancellationEvidence.FREE),
            ("No reembolsable", CancellationEvidence.NON_REFUNDABLE),
            ("Non-refundable", CancellationEvidence.NON_REFUNDABLE),
            (
                "Cancelación gratuita. No reembolsable",
                CancellationEvidence.NON_REFUNDABLE,
            ),
            (
                "Free cancellation. No cancellation fees.",
                CancellationEvidence.FREE,
            ),
            ("No free cancellation", CancellationEvidence.UNKNOWN),
            ("Sin cancelación gratuita", CancellationEvidence.UNKNOWN),
            (
                "Sin cancelación gratuita. No reembolsable",
                CancellationEvidence.NON_REFUNDABLE,
            ),
            (
                "No free cancellation. Non-refundable",
                CancellationEvidence.NON_REFUNDABLE,
            ),
            (
                "Desayuno\nCancelación gratuita",
                CancellationEvidence.FREE,
            ),
            (
                "Hotel Bruno\nCancelación gratuita",
                CancellationEvidence.FREE,
            ),
            (
                "Apartamento moderno\nCancelación gratuita",
                CancellationEvidence.FREE,
            ),
            ("Casino free cancellation", CancellationEvidence.FREE),
            ("", CancellationEvidence.UNKNOWN),
            (None, CancellationEvidence.UNKNOWN),
            ("Precio por noche", CancellationEvidence.UNKNOWN),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_cancellation_evidence(text), want)

    def test_parse_property_type_evidence(self) -> None:
        cases = [
            ("Apartamento entero", PropertyTypeEvidence.ENTIRE_HOME),
            ("Entire home", PropertyTypeEvidence.ENTIRE_HOME),
            ("Whole place", PropertyTypeEvidence.ENTIRE_HOME),
            ("Habitación privada", PropertyTypeEvidence.NOT_ENTIRE_HOME),
            ("Private room", PropertyTypeEvidence.NOT_ENTIRE_HOME),
            ("Shared room", PropertyTypeEvidence.NOT_ENTIRE_HOME),
            ("Hotel room", PropertyTypeEvidence.NOT_ENTIRE_HOME),
            ("2 dormitorios", PropertyTypeEvidence.UNKNOWN),
            ("", PropertyTypeEvidence.UNKNOWN),
            (None, PropertyTypeEvidence.UNKNOWN),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_property_type_evidence(text), want)

    def test_parse_unit_hints(self) -> None:
        cases = [
            (
                "2 dormitorios · 1 baño · 3 camas",
                {"bedrooms": 2, "bathrooms": 1, "beds": 3},
            ),
            (
                "2 bedrooms · 1 bathroom · 3 beds",
                {"bedrooms": 2, "bathrooms": 1, "beds": 3},
            ),
            (
                "1 habitación · 1 baño",
                {"bedrooms": 1, "bathrooms": 1, "beds": None},
            ),
            ("", {"bedrooms": None, "bathrooms": None, "beds": None}),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_unit_hints(text), want)


if __name__ == "__main__":
    unittest.main()
