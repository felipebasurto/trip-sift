from __future__ import annotations

import re

from trip_sift.models import CancellationEvidence, PropertyTypeEvidence


def parse_price_eur(price_text: str | None) -> float | None:
    if not price_text:
        return None
    cleaned = (
        price_text.replace("\xa0", "").replace(" ", "").replace("€", "").strip()
    )
    m = re.search(r"([\d.,]+)", cleaned)
    if not m:
        return None
    num = m.group(1)
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            return float(num.replace(".", "").replace(",", "."))
        return float(num.replace(",", ""))
    if "," in num:
        frac = num.rsplit(",", 1)[-1]
        if len(frac) <= 2 and frac.isdigit():
            return float(num.replace(",", "."))
        return float(num.replace(",", ""))
    if "." in num:
        parts = num.split(".")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
            return float(parts[0] + parts[1])
        if len(parts) > 2 and all(len(p) == 3 for p in parts[1:]):
            return float(parts[0] + "".join(parts[1:]))
        if len(parts) == 2 and len(parts[1]) <= 2:
            return float(num)
    try:
        return float(num)
    except ValueError:
        return None


def parse_duration_hours(duration: str | None) -> float | None:
    if not duration:
        return None
    text = duration.replace("\xa0", " ").strip().lower()
    h = m = 0.0
    hm = re.search(r"(\d+)\s*h", text)
    mm = re.search(r"(\d+)\s*min", text)
    if hm:
        h = float(hm.group(1))
    if mm:
        m = float(mm.group(1))
    if hm or mm:
        return h + m / 60.0
    return None


def parse_stops_count(stops: object) -> int | None:
    if stops is None:
        return None
    if isinstance(stops, int):
        return stops
    if isinstance(stops, str):
        text = stops.replace("\xa0", " ").strip()
        lower = text.lower()
        if lower in ("unknown",):
            return None
        if lower in ("nonstop", "directo", "direct"):
            return 0
        m = re.search(r"(\d+)", lower)
        if m:
            return int(m.group(1))
    return None


def parse_rating(rating_text: str | None) -> float | None:
    if not rating_text:
        return None
    text = rating_text.replace("\xa0", " ")
    label_patterns = (
        r"(?:puntuaci[oó]n|valoraci[oó]n|rating|scored)\s*:?\s*(\d+[.,]\d+|\d+)",
        r"^(\d+[.,]\d+|\d+)$",
    )
    for pattern in label_patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            try:
                score = float(m.group(1).replace(",", "."))
            except ValueError:
                continue
            if 0.0 <= score <= 10.0:
                return score
            return None
    return None


_FREE_CANCEL_PATTERNS = (
    r"cancelaci[oó]n\s+gratuita",
    r"cancelaci[oó]n\s+gratis",
    r"free\s+cancell?ation",
    r"free\s+cancel",
)

_NON_REFUNDABLE_PATTERNS = (
    r"no\s+reembolsable",
    r"non[\s-]?refundable",
    r"no\s+cancell?ation",
    r"no\s+se\s+puede\s+cancelar",
)


def parse_cancellation_evidence(card_text: str | None) -> CancellationEvidence:
    if not card_text:
        return CancellationEvidence.UNKNOWN
    text = card_text.replace("\xa0", " ").lower()
    has_free = any(re.search(pat, text) for pat in _FREE_CANCEL_PATTERNS)
    has_non_refundable = any(
        re.search(pat, text) for pat in _NON_REFUNDABLE_PATTERNS
    )
    if has_non_refundable:
        return CancellationEvidence.NON_REFUNDABLE
    if has_free:
        return CancellationEvidence.FREE
    return CancellationEvidence.UNKNOWN


_ENTIRE_HOME_PATTERNS = (
    r"apartamento\s+entero",
    r"alojamiento\s+entero",
    r"entire\s+home",
    r"entire\s+apartment",
    r"whole\s+place",
    r"casa\s+entera",
)

_NOT_ENTIRE_HOME_PATTERNS = (
    r"habitaci[oó]n\s+privada",
    r"private\s+room",
    r"shared\s+room",
    r"habitaci[oó]n\s+compartida",
    r"hotel\s+room",
    r"habitaci[oó]n\s+de\s+hotel",
)


def parse_property_type_evidence(card_text: str | None) -> PropertyTypeEvidence:
    if not card_text:
        return PropertyTypeEvidence.UNKNOWN
    text = card_text.replace("\xa0", " ").lower()
    if any(re.search(pat, text) for pat in _NOT_ENTIRE_HOME_PATTERNS):
        return PropertyTypeEvidence.NOT_ENTIRE_HOME
    if any(re.search(pat, text) for pat in _ENTIRE_HOME_PATTERNS):
        return PropertyTypeEvidence.ENTIRE_HOME
    return PropertyTypeEvidence.UNKNOWN


def parse_unit_hints(card_text: str | None) -> dict[str, int | None]:
    text = (card_text or "").replace("\xa0", " ").lower()
    bathrooms = None
    bedrooms = None
    beds = None

    for pat in (
        r"(\d+)\s*baños?",
        r"(\d+)\s*bathrooms?",
        r"(\d+)\s*bathroom",
    ):
        m = re.search(pat, text)
        if m:
            bathrooms = int(m.group(1))
            break

    for pat in (
        r"(\d+)\s*dormitorios?",
        r"(\d+)\s*habitaciones?",
        r"(\d+)\s*bedrooms?",
        r"(\d+)\s*bedroom",
    ):
        m = re.search(pat, text)
        if m:
            bedrooms = int(m.group(1))
            break

    for pat in (
        r"(\d+)\s*camas?\b",
        r"(\d+)\s*beds\b",
        r"(\d+)\s*bed\b(?!room)",
    ):
        m = re.search(pat, text)
        if m:
            beds = int(m.group(1))
            break

    return {"bedrooms": bedrooms, "bathrooms": bathrooms, "beds": beds}
