from __future__ import annotations

import re


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
