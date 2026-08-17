#!/usr/bin/env python3
"""Emit the viajante Solari-board SVGs and the wordmark flip GIF.

Rerun: python3 docs/assets/solari.py
"""

from __future__ import annotations

import itertools
from pathlib import Path

OUT = Path(__file__).resolve().parent

INK = "#F3D06A"
INK_DIM = "#C4A45A"
CREAM = "#F4EDE0"
MUTED = "#8A8070"
STEEL = "#2A2A28"
FACE = "#161614"
FACE_TOP = "#262622"
FACE_BOT = "#0E0E0C"
WELL = "#050504"
CHASSIS = "#0C0C0B"
BEZEL = "#1A1A18"
EMBER = "#E06A3A"
TEAL = "#3D9B8F"
TEAL_INK = "#7EE0D0"
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Courier New', monospace"
DRUM = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_clip = itertools.count(1)


def _esc(ch: str) -> str:
    return (
        ch.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _defs() -> str:
    return f"""
  <defs>
    <linearGradient id="leafTop" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{FACE_TOP}"/>
      <stop offset="1" stop-color="{FACE}"/>
    </linearGradient>
    <linearGradient id="leafBot" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{FACE}"/>
      <stop offset="1" stop-color="{FACE_BOT}"/>
    </linearGradient>
    <linearGradient id="chassis" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#141412"/>
      <stop offset="0.12" stop-color="{CHASSIS}"/>
      <stop offset="1" stop-color="#080807"/>
    </linearGradient>
    <linearGradient id="ember" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{EMBER}"/>
      <stop offset="1" stop-color="{INK}"/>
    </linearGradient>
  </defs>
"""


def flap(
    x: float,
    y: float,
    w: float,
    h: float,
    ch: str,
    *,
    ink: str = INK,
    fold: float = 0.0,
    back: str = " ",
) -> str:
    """One mechanical cell. fold in [0, 1] is the iOS two-phase flip."""
    ch = ch[:1] if ch else " "
    back = back[:1] if back else " "
    fs = h * 0.62
    cx, cy = w / 2, h / 2 + h * 0.03
    r = min(2.6, w * 0.14, h * 0.11)
    mid = h / 2
    gap = max(1.4, h * 0.05)
    show = back if 0 < fold < 0.5 else ch
    if fold <= 0:
        top_k, bot_k = 1.0, 1.0
    elif fold < 0.5:
        top_k = 1.0 - fold * 2
        bot_k = 1.0
    else:
        top_k = 1.0
        bot_k = (fold - 0.5) * 2
    top_h = max(0.01, (mid - gap / 2) * top_k)
    bot_h = max(0.01, (mid - gap / 2) * bot_k)
    bot_y = h - bot_h
    shade = 0.15 + 0.5 * (1.0 - (top_k if fold < 0.5 else bot_k))
    cid = f"c{next(_clip)}"
    glyph = show if show != " " else ""
    letter = ""
    if glyph:
        letter = (
            f'<g clip-path="url(#{cid})">'
            f'<text x="{cx:.1f}" y="{cy:.1f}" fill="{ink}" font-family="{FONT}" '
            f'font-size="{fs:.1f}" font-weight="750" text-anchor="middle" '
            f'dominant-baseline="middle">{_esc(glyph)}</text></g>'
        )
    overlay = ""
    if fold > 0:
        overlay = (
            f'<rect x="0" y="0" width="{w}" height="{h}" fill="#000" '
            f'opacity="{shade:.2f}"/>'
        )
    return f"""<g transform="translate({x:.1f} {y:.1f})">
  <defs><clipPath id="{cid}"><rect width="{w:.1f}" height="{h:.1f}" rx="{r:.1f}"/></clipPath></defs>
  <rect width="{w:.1f}" height="{h:.1f}" rx="{r:.1f}" fill="{WELL}"/>
  <rect x="0.7" y="0.7" width="{w - 1.4:.1f}" height="{top_h:.1f}" rx="{r:.1f}" fill="url(#leafTop)"/>
  <rect x="0.7" y="{bot_y:.1f}" width="{w - 1.4:.1f}" height="{bot_h:.1f}" rx="{r:.1f}" fill="url(#leafBot)"/>
  {letter}
  <rect x="0" y="{mid - gap / 2:.1f}" width="{w:.1f}" height="{gap:.1f}" fill="#000000"/>
  <rect x="0" y="{mid - 0.4:.1f}" width="{w:.1f}" height="0.8" fill="{FACE_TOP}"/>
  {overlay}
</g>"""


def word(
    x: float,
    y: float,
    text: str,
    *,
    w: float = 20,
    h: float = 28,
    gap: float = 2.4,
    ink: str = INK,
    folds: list[float] | None = None,
    backs: list[str] | None = None,
) -> str:
    parts = []
    for i, ch in enumerate(text):
        fold = folds[i] if folds and i < len(folds) else 0.0
        back = backs[i] if backs and i < len(backs) else " "
        parts.append(flap(x + i * (w + gap), y, w, h, ch, ink=ink, fold=fold, back=back))
    return "\n".join(parts)


def word_width(n: int, w: float = 20, gap: float = 2.4) -> float:
    return n * w + max(0, n - 1) * gap


def label(x: float, y: float, text: str, *, fill: str = INK_DIM, size: float = 11, weight: str = "700", anchor: str = "start", tracking: float = 2.2) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-family="{FONT}" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
        f'letter-spacing="{tracking}">{_esc(text)}</text>'
    )


def caption(x: float, y: float, text: str, *, fill: str = MUTED, size: float = 12, anchor: str = "start") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-family="{FONT}" '
        f'font-size="{size}" font-weight="500" text-anchor="{anchor}">{_esc(text)}</text>'
    )


def screw(x: float, y: float) -> str:
    return (
        f'<circle cx="{x}" cy="{y}" r="3.4" fill="#2A2A26" stroke="#3A3A36" stroke-width="0.7"/>'
        f'<circle cx="{x}" cy="{y}" r="1.2" fill="#0C0C0A"/>'
    )


def plane(x: float, y: float, *, fill: str = INK) -> str:
    return (
        f'<path transform="translate({x} {y}) scale(0.95)" fill="{fill}" '
        f'd="M2 11 L22 8 L28 10 L22 12 L16 12 L12 17 L9 17 L11 12 L6 12 L4 14 L2 14 L3 11 Z"/>'
    )


def chassis(w: float, h: float, *, title: str, poles: bool = True) -> str:
    parts = [
        f'<rect width="{w}" height="{h}" rx="22" fill="#050504"/>',
        f'<rect x="18" y="28" width="{w - 36}" height="{h - 46}" rx="14" fill="url(#chassis)" stroke="{BEZEL}" stroke-width="1.4"/>',
        f'<rect x="26" y="36" width="{w - 52}" height="{h - 62}" rx="8" fill="#090908"/>',
    ]
    if poles:
        parts.append(
            f'<rect x="168" y="0" width="11" height="36" rx="3" fill="#2A2A26"/>'
            f'<rect x="{w - 179}" y="0" width="11" height="36" rx="3" fill="#2A2A26"/>'
            f'<circle cx="173.5" cy="32" r="5.5" fill="#3A3A36"/>'
            f'<circle cx="{w - 173.5}" cy="32" r="5.5" fill="#3A3A36"/>'
        )
    parts += [
        screw(38, 46),
        screw(w - 38, 46),
        screw(38, h - 28),
        screw(w - 38, h - 28),
        label(60, 60, title, size=12, tracking=4.6, fill=INK),
    ]
    return "\n".join(parts)


def _pad(text: str, n: int) -> str:
    return text.ljust(n)[:n]


def hero_svg(*, wordmark: str = "VIAJANTE", folds: list[float] | None = None, backs: list[str] | None = None) -> str:
    w, h = 1200, 660
    # cell 20px including gap. Columns keep every original fact.
    fw, fh, fg = 18, 30, 2.0
    col = {
        "flight": (48, 6),
        "dest": (180, 13),
        "dep": (454, 5),
        "arr": (566, 5),
        "st": (678, 2),
        "dur": (730, 5),
        "eur": (842, 3),
        "via": (914, 3),
        "lane": (986, 5),
    }
    headers = [
        ("flight", "FLIGHT"),
        ("dest", "DESTINATION"),
        ("dep", "DEP"),
        ("arr", "ARR"),
        ("st", "ST"),
        ("dur", "DUR"),
        ("eur", "EUR"),
        ("via", "VIA"),
        ("lane", "LANE"),
    ]
    flights = [
        ("JFKNRT", "TOKYO NARITA", "16:30", "06:35", "1", "14H05", "588", "JAL", "SWEEP", INK),
        ("JFKNRT", "TOKYO NARITA", "11:15", "22:55", "1", "13H40", "612", "ANA", "SWEEP", INK),
        ("JFKNRT", "TOKYO NARITA", "10:05", "21:25", "2", "19H20", "441", "CZ", "SWEEP", MUTED),
    ]
    stays = [
        ("TOKYO", "KANDA CHIYODA", "4NITE", "", "--", "4.2", "312", "GGL", "HTTP", TEAL_INK),
        ("TOKYO", "SHIMOKITAZAWA", "4NITE", "", "--", "4.6", "401", "GGL", "HTTP", TEAL_INK),
    ]

    bits = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">',
        "<title>viajante, local flight and hotel search</title>",
        "<desc>Solari departures board. VIAJANTE wordmark, JFK–NRT sweep quotes in EUR with times and stops, Tokyo stay totals, sweep/detail/MCP lanes. No API keys. Raw card text kept beside every number.</desc>",
        _defs(),
        chassis(w, h, title="DEPARTURES"),
        plane(178, 48),
        label(212, 60, "VIAJANTE", size=12, tracking=3.2, fill=EMBER),
        caption(60, 80, "LOCAL  ·  NO KEYS  ·  NO ACCOUNT", fill=MUTED, size=11),
    ]

    mark_w, mark_h, mark_g = 52, 74, 6
    mark_x = (w - word_width(8, mark_w, mark_g)) / 2
    bits.append(word(mark_x, 94, _pad(wordmark, 8), w=mark_w, h=mark_h, gap=mark_g, ink=CREAM, folds=folds, backs=backs))

    bits.append(caption(48, 188, "Shortlist any IATA pair. Stays too.", fill=CREAM, size=14))
    bits.append(caption(48, 208, "Your machine. Owned parsers. EUR so a New York fare and a Tokyo fare compare.", fill=MUTED, size=12))

    ix = 760
    for code, color in (("LAX", INK_DIM), ("JFK", EMBER), ("LHR", INK), ("NRT", EMBER), ("GRU", TEAL), ("JNB", INK_DIM)):
        bits.append(word(ix, 180, code, w=16, h=24, gap=1.8, ink=color))
        ix += word_width(3, 16, 1.8) + 10

    bits.append(word(48, 228, "SWEEP", w=22, h=32, gap=2.2, ink=TEAL_INK))
    bits.append(word(186, 228, "DETAIL", w=22, h=32, gap=2.2, ink=EMBER))
    bits.append(word(340, 228, "MCP", w=22, h=32, gap=2.2, ink=INK))
    bits.append(caption(508, 248, "$ viajante flights JFK-NRT:2026-10-12 --fetch sweep", fill=MUTED, size=11))
    bits.append(caption(508, 264, "JFK → NRT  2026-10-12  ·  sweep  799 ms  ·  quotes EUR", fill="#6E675C", size=10))

    for key, head in headers:
        bits.append(label(col[key][0], 286, head, size=10, tracking=1.6, fill=INK_DIM))

    def emit_row(y: float, row: tuple) -> None:
        flt, dest, dep, arr, st, dur, eur, via, lane, ink = row
        values = {
            "flight": _pad(flt, 6),
            "dest": _pad(dest, 13),
            "dep": _pad(dep, 5),
            "arr": _pad(arr, 5),
            "st": _pad(st, 2),
            "dur": _pad(dur, 5),
            "eur": eur.rjust(3)[:3],
            "via": _pad(via, 3),
            "lane": _pad(lane, 5),
        }
        for key, (x, n) in col.items():
            bits.append(word(x, y, values[key][:n], w=fw, h=fh, gap=fg, ink=ink))

    for i, row in enumerate(flights):
        emit_row(300 + i * 36, row)

    bits.append(label(48, 416, "STAYS", size=10, tracking=2.4, fill=TEAL_INK))
    bits.append(caption(110, 416, "total stay  ·  ratings 0–5  ·  --source google", fill=MUTED, size=11))
    for i, row in enumerate(stays):
        emit_row(428 + i * 36, row)

    bits.append(caption(48, 508, "$ viajante hotels Tokyo 2026-10-12 2026-10-16", fill=MUTED, size=11))
    bits.append(caption(48, 526, "raw card text kept beside every number  ·  verify before booking", fill="#6E675C", size=11))

    bits.append(f'<rect x="40" y="540" width="1120" height="88" rx="8" fill="#10100E" stroke="{STEEL}" stroke-width="1"/>')
    bits.append(f'<rect x="40" y="540" width="5" height="88" rx="2" fill="url(#ember)"/>')
    bits.append(label(58, 564, "OWNED", size=10, tracking=2.4, fill=INK))
    bits.append(caption(128, 564, "Sweep is HTTP shopping RPC. Detail is Chromium at a 4.5 s pace. MCP is stdio, no auth.", fill=CREAM, size=12))
    bits.append(label(58, 592, "LANES", size=10, tracking=2.4, fill=INK))
    bits.append(caption(128, 592, "One process. Two lanes. Nothing in parallel. Empty sweep may fall back to detail once.", fill=CREAM, size=12))
    bits.append(label(58, 618, "STATE", size=10, tracking=2.4, fill=INK))
    bits.append(caption(128, 618, "Cookies stay in VIAJANTE_STATE_DIR. No API keys. No account.", fill=CREAM, size=12))
    bits.append("</svg>")
    return "\n".join(bits)


def how_svg() -> str:
    w, h = 1200, 460
    bits = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">',
        "<title>How viajante runs a search</title>",
        "<desc>CLI or MCP into validation, then a fork: sweep is HTTP shopping RPC with no Chromium; detail is paced local Chromium. Both land on ranked offers with raw card text. Hotel defaults and local cookie state sit on the rail below.</desc>",
        _defs(),
        chassis(w, h, title="HOW A SEARCH RUNS"),
        caption(60, 80, "One process. Two lanes. Nothing in parallel.", fill=CREAM, size=16),
    ]

    sw, sh, sg = 18, 28, 2.0
    stations = [
        (56, 148, "YOU AGENT", INK, "YOU / AGENT", "CLI or stdio MCP"),
        (280, 148, "VALIDATE", INK, "VALIDATE", "IATA · dates · no Chromium yet"),
        (504, 148, "PICK LANE", INK, "PICK A LANE", "auto: sweep if 3+ queries"),
        (728, 108, "SWEEP", TEAL_INK, "SWEEP", "HTTP shopping RPC"),
        (728, 188, "DETAIL", EMBER, "DETAIL", "Chromium · 4.5 s pace"),
        (968, 148, "EVIDENCE", INK, "EVIDENCE", "typed + raw card"),
    ]
    for x, y, text, ink, title, sub in stations:
        bits.append(word(x, y, text, w=sw, h=sh, gap=sg, ink=ink))
        bits.append(label(x, y + 46, title, size=10, tracking=1.6, fill=CREAM if ink == INK else ink))
        bits.append(caption(x, y + 62, sub, fill=MUTED, size=11))

    def rail(d: str, color: str) -> str:
        return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round"/>'

    bits.append(rail("M240 162 H272", STEEL))
    bits.append(rail("M464 162 H496", STEEL))
    bits.append(rail("M688 162 C708 162 718 122 728 122", TEAL))
    bits.append(rail("M688 162 C708 162 718 202 728 202", EMBER))
    bits.append(rail("M832 122 C900 122 940 162 968 162", INK_DIM))
    bits.append(rail("M850 202 C910 202 940 162 968 162", INK_DIM))

    bits.append(f'<rect x="40" y="284" width="1120" height="132" rx="8" fill="#10100E" stroke="{STEEL}" stroke-width="1"/>')
    bits.append(f'<rect x="40" y="284" width="5" height="132" rx="2" fill="url(#ember)"/>')
    bits.append(label(58, 312, "HOTELS", size=11, tracking=2.6, fill=INK))
    bits.append(caption(140, 312, "Agents get Google HTTP. The CLI still opens Booking when you want the evidence path.", fill=CREAM, size=13))
    bits.append(label(58, 348, "STATE", size=11, tracking=2.6, fill=INK))
    bits.append(caption(140, 348, "Cookies stay in VIAJANTE_STATE_DIR. Sweep miss may fall back to detail once. Never a second browser hammer.", fill=CREAM, size=13))
    bits.append(label(58, 384, "PACE", size=11, tracking=2.6, fill=INK))
    bits.append(caption(140, 384, "Sweep inter-query delay is 0. Detail sleeps 4.5 to 6 seconds on purpose. Nothing in parallel.", fill=CREAM, size=13))
    bits.append("</svg>")
    return "\n".join(bits)


def _drum_char(target: str, t: float) -> tuple[str, float, str]:
    target = target if target in DRUM else " "
    idx = DRUM.index(target)
    steps = idx + 1
    pos = min(steps, t * (steps + 0.001))
    i = int(pos)
    frac = pos - i
    if i <= 0:
        return " ", 0.0, " "
    if i >= steps:
        return target, 0.0, DRUM[max(0, i - 1)]
    return DRUM[i], frac, DRUM[i - 1]


def _hex(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def write_flip_gif(path: Path) -> None:
    """Wordmark drum, same two-phase fold as yannickl/Splitflap. Pillow, no browser."""
    from PIL import Image, ImageDraw, ImageFont

    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")
    if not font_path.exists():
        font_path = Path("/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf")
    W, H = 960, 200
    cell_w, cell_h, gap = 88, 120, 10
    letters = "VIAJANTE"
    total_w = len(letters) * cell_w + (len(letters) - 1) * gap
    x0 = (W - total_w) // 2
    y0 = 52
    n = 28
    frames: list[Image.Image] = []
    try:
        font = ImageFont.truetype(str(font_path), 72)
        small = ImageFont.truetype(str(font_path), 14)
    except OSError:
        font = ImageFont.load_default()
        small = font

    def draw_cell(draw: ImageDraw.ImageDraw, x: int, y: int, ch: str, fold: float, back: str) -> None:
        show = back if 0 < fold < 0.5 else ch
        r = 6
        draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), r, fill=_hex(WELL))
        mid = y + cell_h // 2
        gap_h = 5
        if fold <= 0:
            top_k, bot_k = 1.0, 1.0
        elif fold < 0.5:
            top_k, bot_k = 1.0 - fold * 2, 1.0
        else:
            top_k, bot_k = 1.0, (fold - 0.5) * 2
        top_h = max(2, int((cell_h / 2 - gap_h / 2) * top_k))
        bot_h = max(2, int((cell_h / 2 - gap_h / 2) * bot_k))
        draw.rounded_rectangle((x + 2, y + 2, x + cell_w - 2, y + 2 + top_h), r, fill=(44, 44, 38))
        draw.rounded_rectangle((x + 2, y + cell_h - 2 - bot_h, x + cell_w - 2, y + cell_h - 2), r, fill=(28, 28, 24))
        if show != " ":
            bbox = draw.textbbox((0, 0), show, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = x + (cell_w - tw) / 2 - bbox[0]
            ty = y + (cell_h - th) / 2 - bbox[1] + 2
            draw.text((tx, ty), show, font=font, fill=_hex(CREAM))
        draw.rectangle((x, mid - gap_h // 2, x + cell_w, mid + gap_h // 2), fill=(0, 0, 0))
        draw.rectangle((x, mid - 1, x + cell_w, mid + 1), fill=_hex(FACE_TOP))
        if fold > 0:
            shade = int(40 + 120 * (1.0 - (top_k if fold < 0.5 else bot_k)))
            draw.rectangle((x, y, x + cell_w, y + cell_h), fill=(0, 0, 0, shade))

    for frame in range(n):
        t = frame / (n - 1)
        im = Image.new("RGBA", (W, H), (5, 5, 4, 255))
        draw = ImageDraw.Draw(im, "RGBA")
        draw.rounded_rectangle((8, 8, W - 8, H - 8), 16, fill=_hex(CHASSIS))
        draw.text((28, 18), "DEPARTURES", font=small, fill=_hex(INK))
        draw.text((170, 18), "VIAJANTE", font=small, fill=_hex(EMBER))
        draw.text((W - 28, 18), "LOCAL  ·  NO KEYS", font=small, fill=_hex(MUTED), anchor="ra")
        for i, ch in enumerate(letters):
            local = max(0.0, min(1.0, (t - i * 0.07) / 0.45))
            shown, fold, back = _drum_char(ch, local)
            if local >= 1:
                fold = 0.0
            draw_cell(draw, x0 + i * (cell_w + gap), y0, shown, fold, back)
        frames.append(im.convert("P", palette=Image.Palette.ADAPTIVE, colors=48))

    # Hold the finished word a beat, then loop.
    hold = frames[-1]
    frames.extend([hold] * 14)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=70,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    (OUT / "viajante-hero.svg").write_text(hero_svg() + "\n", encoding="utf-8")
    (OUT / "how-viajante-works.svg").write_text(how_svg() + "\n", encoding="utf-8")
    write_flip_gif(OUT / "viajante-flip.gif")
    print(f"wrote {OUT / 'viajante-hero.svg'}")
    print(f"wrote {OUT / 'how-viajante-works.svg'}")
    print(f"wrote {OUT / 'viajante-flip.gif'}")


if __name__ == "__main__":
    main()
