"""
Ausbildung IES NG: DIN-A6-Übungskarten mit fiktiven Personen.

Pro Karte: CI-Kopf (Bund/BABS), Schweizer ID (Vorder- und Rückseite, Massstab 1:1,
MRZ TD1), fortlaufender QR-Code unten rechts (CHY0001 ... CHY2000).
Zusätzlich eine Lösungsliste (CSV) mit allen Daten und Prüfergebnissen.

Beispiel:
    python ies_ng_karten.py -n 40 --layout a4 -o karten.pdf
    python ies_ng_karten.py -n 100 --start 101 --p-invalid-mrz 0.1 --p-expired 0.05
    python ies_ng_karten.py @karten.args      # Argumente aus Datei
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import segno
from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4, A6
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from ies_ng_avatar import draw_avatar
from ies_ng_signatur import draw_signature, register_hand_fonts
from ies_ng_swisspre import (KATEGORIEN, Fall, allocate_pre, befund_zeilen, erzeuge_fall, parse_mix,
                             pls_capacity, pls_id)
from ies_ng_szene import draw_scene
from ies_ng_avatar import make_look
from ies_ng_mrz import TD1, corrupt, make_td1, validate_td1
from ies_ng_adressen import find_register, is_register, load_register
from synthetic_people import GenConfig, generate_people, read_ch_addresses, read_ch_names

# -------------------------
# CI / Layout
# -------------------------

@dataclass(frozen=True)
class CI:
    """Corporate Design Bund (BABS). Frutiger ist lizenzpflichtig -> Pfad per CLI setzbar."""
    red: Color = HexColor("#DC0018")
    text: Color = HexColor("#1F1F1F")
    grey: Color = HexColor("#6B6B6B")
    line: Color = HexColor("#CCCCCC")
    dept_lines: tuple[str, ...] = ("Bundesamt für Bevölkerungsschutz BABS",)
    conf_lines: tuple[str, ...] = (
        "Schweizerische Eidgenossenschaft",
        "Confédération suisse",
        "Confederazione Svizzera",
        "Confederaziun svizra",
    )


HERE = Path(__file__).resolve().parent
ID_W, ID_H, ID_R = 85.6, 54.0, 3.18      # ID-1 (ISO/IEC 7810), mm
MRZ_PITCH, MRZ_LINE = 2.54, 4.23          # 10 Zeichen/Zoll, 6 Zeilen/Zoll
MRZ_CAP_MM = 2.4                          # Zeichenhöhe OCR-B Grösse 1
MRZ_ZONE_MM = 16.5                        # Höhe des MRZ-Bereichs auf der ID-Rückseite
MRZ_W_MM, MRZ_BASE_MM = 30 * 2.54, 3.0    # Breite Zeichenblock, Grundlinie unterste Zeile über ID-Unterkante
MRZ_H_MM = 2 * 4.23 + 2.4                 # Grundlinie unten bis Oberkante oberste Zeile
MRZ_MARGIN_MM = 3.0                       # weisser Rand beim PNG «mrz»

FONT_CANDIDATES = {
    "Sans": ["fonts/Frutiger-Roman.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
             "C:/Windows/Fonts/arial.ttf"],
    "Sans-Bold": ["fonts/Frutiger-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                  "C:/Windows/Fonts/arialbd.ttf"],
    "Sign": ["/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf", "C:/Windows/Fonts/timesi.ttf"],
    "Mono": ["fonts/Mono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "C:/Windows/Fonts/consola.ttf",
             "fonts/OCR-B.ttf"],
    "MRZ": ["fonts/OCR-B.ttf", "fonts/OCRB.ttf", "fonts/ocrb10.ttf", "fonts/OCRB Regular.otf", "fonts/OCRB.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "C:/Windows/Fonts/consola.ttf"],
}


def otf_to_ttf(src: Path) -> Path:
    """CFF-basierte OTF (von reportlab nicht unterstützt) einmalig nach TrueType wandeln (fontTools)."""
    dst = src.with_suffix(".ttf")
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont as FTFont, newTable

    f = FTFont(str(src))
    if "CFF " not in f:
        return src
    gs = f.getGlyphSet()
    glyf = newTable("glyf")
    glyf.glyphOrder = f.getGlyphOrder()
    glyf.glyphs = {}
    for gname in glyf.glyphOrder:
        pen = TTGlyphPen(gs)
        gs[gname].draw(Cu2QuPen(pen, max_err=1.0, reverse_direction=True))
        glyf.glyphs[gname] = pen.glyph()
    del f["CFF "]
    f["glyf"] = glyf
    f["loca"] = newTable("loca")
    f["maxp"] = newTable("maxp")
    f["maxp"].tableVersion = 0x00010000
    for attr in ("maxZones", "maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs",
                 "maxStackElements", "maxSizeOfInstructions", "maxComponentElements"):
        setattr(f["maxp"], attr, 0)
    f["maxp"].maxZones = 1
    f["head"].glyphDataFormat = 0
    f["post"].formatType = 2.0
    f["post"].extraNames, f["post"].mapping = [], {}
    f.sfntVersion = "\x00\x01\x00\x00"
    f.save(str(dst))
    return dst


def register_fonts(overrides: dict[str, Optional[str]]) -> dict[str, str]:
    used = {}
    for name, candidates in FONT_CANDIDATES.items():
        paths = [overrides[name]] if overrides.get(name) else candidates
        for p in paths:
            if not Path(p).is_absolute() and (HERE / p).is_file():
                p = str(HERE / p)
            if Path(p).is_file():
                if Path(p).suffix.lower() == ".otf":
                    p = str(otf_to_ttf(Path(p)))
                pdfmetrics.registerFont(TTFont(name, p))
                used[name] = p
                break
        else:
            raise FileNotFoundError(f"font {name}: none of {paths} found")
    register_hand_fonts()
    return used

# -------------------------
# Daten
# -------------------------

DEMO_FIRST = [
    ("Noah", "m", 120), ("Luca", "m", 110), ("Leon", "m", 90), ("Daniel", "m", 140), ("Thomas", "m", 130),
    ("Peter", "m", 150), ("Marco", "m", 100), ("Jonas", "m", 70), ("Elias", "m", 80), ("Andreas", "m", 120),
    ("Lukas", "m", 90), ("Matteo", "m", 60), ("Hans", "m", 80), ("Urs", "m", 60), ("Jean-Luc", "m", 30),
    ("Mia", "f", 120), ("Emma", "f", 110), ("Lea", "f", 90), ("Anna", "f", 140), ("Maria", "f", 150),
    ("Sandra", "f", 120), ("Laura", "f", 100), ("Sofia", "f", 70), ("Nicole", "f", 110), ("Ursula", "f", 70),
    ("Elena", "f", 80), ("Chloé", "f", 40), ("Zoë", "f", 30), ("Anne-Sophie", "f", 20), ("Ruth", "f", 50),
    ("Robin", "x", 20), ("Andrea", "x", 40),
]
DEMO_LAST = [
    ("Müller", 300), ("Meier", 200), ("Schmid", 190), ("Keller", 150), ("Weber", 140), ("Huber", 130),
    ("Schneider", 120), ("Meyer", 120), ("Steiner", 110), ("Fischer", 110), ("Gerber", 100), ("Brunner", 100),
    ("Baumann", 90), ("Frei", 90), ("Zimmermann", 80), ("Moser", 80), ("Widmer", 70), ("Wyss", 70),
    ("Graf", 60), ("Roth", 60), ("Rossi", 50), ("Favre", 40), ("Bianchi", 40), ("Kälin", 30),
    ("Bürgi", 30), ("Lüthi", 30), ("Dubois", 25), ("Rüegg", 20), ("von Gunten", 15), ("Da Silva", 15),
]
def demo_names() -> tuple[pd.DataFrame, pd.DataFrame]:
    return (pd.DataFrame(DEMO_FIRST, columns=["first_name", "gender", "freq"]),
            pd.DataFrame(DEMO_LAST, columns=["last_name", "freq"]))


def _find_data(pattern: str) -> Optional[Path]:
    hits = sorted(p for ext in ("csv", "xlsx", "parquet") for p in (HERE / "data").glob(f"{pattern}.{ext}"))
    return hits[-1] if hits else None


def load_addresses(args: argparse.Namespace) -> pd.DataFrame:
    """Nur echte Adressen: amtliches Gebäudeadressverzeichnis (swisstopo) oder eigene Adressdatei."""
    src = Path(args.addresses) if args.addresses else find_register()
    if src is None:
        raise SystemExit(
            "Keine Adressdaten. Echte Adressen sind Pflicht:\n"
            "  python ies_ng_adressen.py --download        (amtliches Gebäudeadressverzeichnis nach data/)\n"
            "  oder --addresses <register.csv.zip | auszug.csv>")
    if is_register(src):
        addr = load_register(src, args.canton, args.plz, args.gemeinde, args.wohngebaeude)
    else:
        addr = read_ch_addresses(src)
        if args.canton and "canton" in addr:
            addr = addr[addr["canton"].str.upper().isin([c.upper() for c in args.canton])]
        if args.plz:
            addr = addr[addr["postcode"].isin(args.plz)]
    if addr.empty:
        raise SystemExit("Nach Filter keine Adressen übrig.")
    print(f"{len(addr)} echte Adressen aus {src.name}")
    return addr


@dataclass
class CardPerson:
    card_no: int
    card_id: str
    qr_payload: str
    first_name: str
    last_name: str
    gender: str
    dob: date
    street: str
    house_number: str
    postcode: str
    city: str
    canton: str
    origin: str
    height_cm: int
    doc_number: str
    serial: str
    issue_date: date
    expiry: date
    authority: str
    td1: TD1
    mrz_error: str = ""
    photo_seed: Optional[tuple[int, int]] = None
    fall: Optional[Fall] = None
    checks: dict = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return self.expiry < date.today()


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29. Februar
        return d.replace(year=d.year + years, day=28)


def _doc_number(r: np.random.Generator, prefix: str) -> str:
    """Muster wie Modell 2023 (z. B. S1A00A00), fiktiver Präfix."""
    L = lambda: chr(int(r.integers(65, 91)))
    D = lambda: str(int(r.integers(0, 10)))
    return f"{prefix}{D()}{L()}{D()}{D()}{L()}{D()}{D()}"


def assign_faelle(cards: list, args: argparse.Namespace, r: np.random.Generator) -> None:
    """Prä-Triage exakt nach --pre-mix (Swiss Pre), je Karte ein Fall mit Befunden und ärztlicher Triage."""
    ages = [_age(c.dob) for c in cards]
    for card, age, pre in zip(cards, ages, allocate_pre(ages, parse_mix(args.pre_mix), r)):
        card.fall = erzeuge_fall(pre, age, r)


def build_cards(people: pd.DataFrame, args: argparse.Namespace, r: np.random.Generator) -> list[CardPerson]:
    today = date.today()
    places = people[["city", "canton"]].dropna().drop_duplicates()
    origins = [f"{ct} {kt}" for ct, kt in places.itertuples(index=False)] or ["Bern BE"]
    used_docs: set[str] = set()
    cards = []
    for i, p in enumerate(people.itertuples(index=False)):
        n = args.start + i
        cid = pls_id(n, args.id_start)
        dob = p.dob if isinstance(p.dob, date) else pd.Timestamp(p.dob).date()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        # Gültigkeit: 10 Jahre, bei Ausstellung < 18 Jahre: 5 Jahre
        validity = 5 if age < 18 else 10
        expired = r.random() < args.p_expired
        if expired:
            expiry = today - timedelta(days=int(r.integers(1, 3 * 365)))
            issue = _add_years(expiry, -validity) + timedelta(days=1)
            expired = issue >= dob  # Ausweis muss nach der Geburt ausgestellt sein
        if not expired:
            issue = today - timedelta(days=int(r.integers(0, validity * 365 - 30)))
            issue = max(issue, dob)
            expiry = _add_years(issue, validity) - timedelta(days=1)

        doc = _doc_number(r, args.doc_prefix)
        while doc in used_docs:
            doc = _doc_number(r, args.doc_prefix)
        used_docs.add(doc)

        if age < 16:
            height = int(np.clip(75 + 6.2 * age + r.normal(0, 4), 50, 190))
        else:
            height = int(r.normal(178, 7) if p.gender == "m" else r.normal(165, 6.5) if p.gender == "f"
                         else r.normal(171, 8))

        td1 = make_td1(doc, p.last_name, p.first_name, dob, p.gender, expiry)
        err = ""
        if r.random() < args.p_invalid_mrz:
            err = str(r.choice(["document", "birth", "expiry", "composite"]))
            td1 = corrupt(td1, err)

        canton = "" if pd.isna(getattr(p, "canton", None)) else str(p.canton)
        cards.append(CardPerson(
            card_no=n, card_id=cid, qr_payload=args.qr_format.format(id=cid),
            first_name=p.first_name, last_name=p.last_name, gender=p.gender, dob=dob,
            street=str(p.street), house_number="" if pd.isna(p.house_number) else str(p.house_number),
            postcode=str(p.postcode), city=str(p.city), canton=canton,
            origin=str(r.choice(origins)), height_cm=height, doc_number=doc,
            serial=f"{int(r.integers(10, 99))}TRNG{n:09d}", issue_date=issue, expiry=expiry,
            authority=f"Kanton {canton}" if canton else str(p.city), td1=td1, mrz_error=err,
            checks=validate_td1(td1),
            photo_seed=None if args.no_photos else (args.seed, n),
        ))
    assign_faelle(cards, args, r)
    return cards

# -------------------------
# Zeichnen
# -------------------------

def fmt_date(d: date) -> str:
    return d.strftime("%d %m %Y")


def swiss_cross(c: Canvas, x: float, y: float, s: float, ci: CI) -> None:
    """Quadrat mit Schweizerkreuz (Proportionen 6:7 Arm-Verhältnis vereinfacht)."""
    c.setFillColor(ci.red)
    c.rect(x, y, s, s, stroke=0, fill=1)
    c.setFillColor(white)
    arm_w, arm_l = s * 6 / 32, s * 20 / 32
    c.rect(x + (s - arm_w) / 2, y + (s - arm_l) / 2, arm_w, arm_l, stroke=0, fill=1)
    c.rect(x + (s - arm_l) / 2, y + (s - arm_w) / 2, arm_l, arm_w, stroke=0, fill=1)


def text(c: Canvas, x, y, s, font="Sans", size=6.0, color=None, anchor="l") -> None:
    c.setFont(font, size)
    if color is not None:
        c.setFillColor(color)
    {"l": c.drawString, "r": c.drawRightString, "c": c.drawCentredString}[anchor](x, y, s)


def fit_text(c: Canvas, x, y, s, max_w, font="Sans-Bold", size=7.0, min_size=4.0, color=None) -> None:
    while size > min_size and pdfmetrics.stringWidth(s, font, size) > max_w:
        size -= 0.25
    text(c, x, y, s, font, size, color)


def photo_placeholder(c: Canvas, x, y, w, h, ci: CI) -> None:
    c.saveState()
    path = c.beginPath()
    path.rect(x, y, w, h)
    c.clipPath(path, stroke=0, fill=0)
    c.setFillColor(HexColor("#E2DEDB"))
    c.rect(x, y, w, h, stroke=0, fill=1)
    c.setFillColor(HexColor("#B9B3AE"))
    c.circle(x + w / 2, y + h * 0.62, w * 0.22, stroke=0, fill=1)
    c.ellipse(x + w * 0.12, y - h * 0.15, x + w * 0.88, y + h * 0.42, stroke=0, fill=1)
    c.restoreState()
    c.setStrokeColor(ci.line)
    c.rect(x, y, w, h, stroke=1, fill=0)


# -------------------------
# Identitätskarte Modell 2023 (Masse nach fedpol-Muster, in mm ab oberem linkem Kartenrand)
# -------------------------

@dataclass(frozen=True)
class IDColors:
    bg_top: Color = HexColor("#E4EFF6")
    bg_bottom: Color = HexColor("#CFE3EE")
    label: Color = HexColor("#2C68C9")         # Feldbezeichnungen
    data: Color = HexColor("#1A1A1A")          # Personalisierung (Lasergravur)
    guilloche: Color = HexColor("#7FB2D6")
    guilloche_warm: Color = HexColor("#EDA97C")
    contour: Color = HexColor("#5FBFCB")
    teal: Color = HexColor("#4DB8B0")
    mountain: Color = HexColor("#4F86D3")
    kine_green: Color = HexColor("#38A55A")
    gold: Color = HexColor("#C9A233")
    window: Color = HexColor("#B9BEC2")


IDC = IDColors()
SEP = "▪"   # ▪ Trenner zwischen den Sprachen (als Quadrat gezeichnet)


def _at(top: float, v_mm: float) -> float:
    """y-Koordinate für einen Abstand v_mm ab Kartenoberkante."""
    return top - v_mm * mm


def _age(dob: date) -> int:
    t = date.today()
    return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))


def ml_label(c: Canvas, x: float, y: float, s: str, size: float = 3.5, color: Color = IDC.label) -> None:
    """Mehrsprachige Feldbezeichnung, Teile mit ▪ getrennt."""
    c.setFillColor(color)
    c.setFont("Sans", size)
    sq = size * 0.30
    for i, part in enumerate(p.strip() for p in s.split(SEP)):
        if i:
            x += size * 0.32
            c.rect(x, y + size * 0.18, sq, sq, stroke=0, fill=1)
            x += sq + size * 0.32
        c.drawString(x, y, part)
        x += pdfmetrics.stringWidth(part, "Sans", size)


def mono_label(c: Canvas, x: float, y: float, s: str, size: float) -> None:
    """Dokumentbezeichnung in Monospace, ▪ als Quadrat."""
    c.setFillColor(IDC.data)
    c.setFont("Mono", size)
    gap = pdfmetrics.stringWidth(" ", "Mono", size)
    for i, part in enumerate(p.strip() for p in s.split(SEP)):
        if i:
            c.rect(x + gap * 0.3, y + size * 0.2, size * 0.32, size * 0.32, stroke=0, fill=1)
            x += 2 * gap
        c.drawString(x, y, part)
        x += pdfmetrics.stringWidth(part, "Mono", size) + gap


def mono_label_width(s: str, size: float) -> float:
    """Breite wie von mono_label gezeichnet (inkl. Trenner)."""
    gap = pdfmetrics.stringWidth(" ", "Mono", size)
    parts = [p.strip() for p in s.split(SEP)]
    return sum(pdfmetrics.stringWidth(p, "Mono", size) for p in parts) + gap * (len(parts) - 1) * 3


def data_text(c: Canvas, x: float, y: float, s: str, size: float = 8.0, max_w: Optional[float] = None,
              end_mark: bool = False, color: Color = IDC.data) -> None:
    """Personalisierte Daten in Monospace, optional ▲ als Feldende."""
    extra = size * 0.6 if end_mark else 0
    while max_w and size > 4.5 and pdfmetrics.stringWidth(s, "Mono", size) + extra > max_w:
        size -= 0.2
    text(c, x, y, s, "Mono", size, color)
    if end_mark:
        ex = x + pdfmetrics.stringWidth(s, "Mono", size) + size * 0.12
        h = size * 0.36
        p = c.beginPath()
        p.moveTo(ex, y + size * 0.08)
        p.lineTo(ex + h * 1.1, y + size * 0.08)
        p.lineTo(ex + h * 0.55, y + size * 0.08 + h)
        p.close()
        c.drawPath(p, stroke=0, fill=1)


# --- Hintergrund (einmal je PDF als Form-XObject; Koordinaten in mm ab unten links) ---

def _poly(c: Canvas, pts, close: bool = True):
    p = c.beginPath()
    p.moveTo(pts[0][0] * mm, pts[0][1] * mm)
    for x, y in pts[1:]:
        p.lineTo(x * mm, y * mm)
    if close:
        p.close()
    return p


def _wave_lines(c: Canvas, color: Color, n: int, y0: float, y1: float, x0: float = 0.0, x1: float = ID_W,
                alpha: float = 0.22, lw: float = 0.1) -> None:
    """Guilloche: feine, gegeneinander verschobene Wellenlinien."""
    c.setStrokeColor(color)
    c.setStrokeAlpha(alpha)
    c.setLineWidth(lw)
    xs = np.linspace(x0, x1, 70)
    for k in range(n):
        base = y0 + (y1 - y0) * k / max(n - 1, 1)
        ph = k * 0.37
        ys = base + 0.55 * np.sin(2 * np.pi * xs / 13.0 + ph) + 0.22 * np.sin(2 * np.pi * xs / 4.7 - 2 * ph)
        c.drawPath(_poly(c, list(zip(xs, ys)), close=False), stroke=1, fill=0)
    c.setStrokeAlpha(1)


def _contours(c: Canvas, rng: np.random.Generator, cx: float, cy: float, n: int, r0: float, dr: float,
              alpha: float = 0.3) -> None:
    """Höhenlinien: unregelmässige, verschachtelte Kurven um (cx, cy)."""
    c.setStrokeColor(IDC.contour)
    c.setStrokeAlpha(alpha)
    c.setLineWidth(0.18)
    ph = rng.uniform(0, 2 * np.pi, 3)
    th = np.linspace(0, 2 * np.pi, 90)
    for k in range(n):
        r = (r0 + k * dr) * (1 + 0.16 * np.sin(3 * th + ph[0] + 0.15 * k) + 0.07 * np.sin(5 * th + ph[1])
                             + 0.04 * np.sin(9 * th + ph[2] - 0.3 * k))
        c.drawPath(_poly(c, list(zip(cx + r * np.cos(th), cy + 0.75 * r * np.sin(th)))), stroke=1, fill=0)
    c.setStrokeAlpha(1)


def _triangles(c: Canvas, rng: np.random.Generator, x0: float, x1: float, y0: float, y1: float, n: int) -> None:
    """Dreiecks-Gebirge in Grün-/Blautönen."""
    cols = [HexColor("#3FB5A5"), HexColor("#5B9BD5"), HexColor("#2E9B62"), HexColor("#9AD3C8"), HexColor("#7FA9E0")]
    for _ in range(n):
        s = float(rng.uniform(2.0, 6.0))
        x, y = float(rng.uniform(x0, x1 - s)), float(rng.uniform(y0, y1 - s * 0.87))
        c.setFillColor(cols[int(rng.integers(len(cols)))])
        c.setFillAlpha(float(rng.uniform(0.12, 0.45)))
        c.drawPath(_poly(c, [(x, y), (x + s, y), (x + s / 2, y + s * 0.87)]), stroke=0, fill=1)
    c.setFillAlpha(1)


def _microline(c: Canvas, y: float, x0: float, x1: float, s: str, color: Color, h: float = 0.55) -> None:
    """Farbiges Band mit Mikroschrift."""
    c.setFillColor(color)
    c.setFillAlpha(0.8)
    c.rect(x0 * mm, y * mm, (x1 - x0) * mm, h * mm, stroke=0, fill=1)
    c.setFillAlpha(1)
    c.setFillColor(white)
    c.setFont("Sans", 1.3)
    unit = s + "  "
    reps = int((x1 - x0) * mm / max(pdfmetrics.stringWidth(unit, "Sans", 1.3), 1)) + 1
    c.drawString(x0 * mm + 0.5, y * mm + h * mm * 0.25, (unit * reps)[: reps * len(unit)])


def _mountain(c: Canvas) -> None:
    """Stilisierter Pizzo Rotondo (blaue Schraffur), Vorderseite Mitte."""
    ridge = [(30, 30.5), (34, 33), (37, 36.5), (39.5, 35), (42, 39.5), (44, 38.2), (46.5, 41.5), (48, 40),
             (50.5, 37.5), (53, 38.8), (56, 35.5), (59, 34), (61, 30.5)]
    p = _poly(c, [(30, 28)] + ridge + [(61, 28)])
    c.saveState()
    c.setFillColor(IDC.mountain)
    c.setFillAlpha(0.05)
    c.drawPath(p, stroke=0, fill=1)
    c.clipPath(p, stroke=0, fill=0)
    c.setStrokeColor(IDC.mountain)
    c.setStrokeAlpha(0.22)
    c.setLineWidth(0.1)
    for i in range(45):
        x = 26 + i * 0.8
        c.line(x * mm, 28 * mm, (x + 6) * mm, 42 * mm)
    c.restoreState()


def _green_mountain(c: Canvas) -> None:
    """Grünes Berg-Symbol mit Bewegungsstreifen und Kreuz (stilisiert), Vorderseite rechts."""
    _triangles(c, np.random.default_rng(7), 62, 85, 26, 40, 14)
    c.setFillColor(IDC.kine_green)
    c.drawPath(_poly(c, [(71, 31.8), (80.5, 31.8), (77, 37.2)]), stroke=0, fill=1)
    c.setFillColor(IDC.bg_top)
    for i, (x0, w) in enumerate([(70.5, 6.5), (69.5, 5.8), (71.0, 6.2), (70.0, 5.0)]):
        c.rect(x0 * mm, (32.6 + i * 1.05) * mm, w * mm, 0.35 * mm, stroke=0, fill=1)
    c.setFillColor(IDC.kine_green)
    for i, (x0, w) in enumerate([(66.5, 3.2), (67.8, 2.4), (66.0, 3.0)]):
        c.rect(x0 * mm, (32.2 + i * 1.3) * mm, w * mm, 0.6 * mm, stroke=0, fill=1)
    c.rect(79.6 * mm, 37.3 * mm, 1.6 * mm, 0.45 * mm, stroke=0, fill=1)
    c.rect(80.17 * mm, 36.73 * mm, 0.45 * mm, 1.6 * mm, stroke=0, fill=1)


def _gold_drop(c: Canvas) -> None:
    """Goldener Wassertropfen mit Wellenringen (stilisiert), Rückseite rechts."""
    c.setStrokeColor(IDC.gold)
    c.setLineWidth(0.9)
    for k, (rx, ry) in enumerate([(4.8, 1.3), (3.2, 0.85)]):
        c.ellipse((69.8 - rx) * mm, (28.4 - ry) * mm, (69.8 + rx) * mm, (28.4 + ry) * mm, stroke=1, fill=0)
    c.setFillColor(IDC.gold)
    p = c.beginPath()
    p.moveTo(70 * mm, 37.6 * mm)
    p.curveTo(71.5 * mm, 35.2 * mm, 73.6 * mm, 33.0 * mm, 73.2 * mm, 31.2 * mm)
    p.curveTo(72.8 * mm, 29.0 * mm, 67.2 * mm, 29.0 * mm, 66.8 * mm, 31.2 * mm)
    p.curveTo(66.4 * mm, 33.0 * mm, 68.5 * mm, 35.2 * mm, 70 * mm, 37.6 * mm)
    c.drawPath(p, stroke=0, fill=1)
    c.setFillColor(HexColor("#5B9BD5"))
    c.setFillAlpha(0.5)
    for dx, dy, s in [(76.5, 31.5, 1.0), (78.6, 32.4, 0.8)]:
        c.circle(dx * mm, dy * mm, s * mm, stroke=0, fill=1)
    c.setFillAlpha(1)


def _bubbles(c: Canvas, rng: np.random.Generator) -> None:
    """Wassermoleküle (Kreise mit Verbindungen), Rückseite oben."""
    c.setStrokeColor(IDC.guilloche)
    c.setStrokeAlpha(0.55)
    c.setLineWidth(0.2)
    pts = [(float(rng.uniform(28, 82)), float(rng.uniform(36, 52))) for _ in range(16)]
    for x, y in pts:
        c.circle(x * mm, y * mm, float(rng.uniform(0.8, 2.2)) * mm, stroke=1, fill=0)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if abs(x1 - x0) < 12:
            c.line(x0 * mm, y0 * mm, x1 * mm, y1 * mm)
    c.setStrokeAlpha(1)


def _bg_base(c: Canvas) -> None:
    p = c.beginPath()
    p.roundRect(0, 0, ID_W * mm, ID_H * mm, ID_R * mm)
    c.clipPath(p, stroke=0, fill=0)
    # Verlauf als feine Streifen statt linearGradient: Shadings in Form-XObjects legt reportlab
    # in den Seiten-Ressourcen ab -> «cannot find Shading resource» (MuPDF) bzw. fehlender Verlauf.
    top, bot, n = IDC.bg_top, IDC.bg_bottom, 120
    band = ID_H * mm / n
    for i in range(n):
        t = (i + 0.5) / n
        c.setFillColor(Color(top.red + (bot.red - top.red) * t, top.green + (bot.green - top.green) * t,
                             top.blue + (bot.blue - top.blue) * t))
        c.rect(0, ID_H * mm - (i + 1) * band - 0.05, ID_W * mm, band + 0.1, stroke=0, fill=1)


def _form_front(c: Canvas) -> None:
    rng = np.random.default_rng(2023)
    _bg_base(c)
    _wave_lines(c, IDC.guilloche, 58, 1, 53)
    _wave_lines(c, IDC.guilloche_warm, 14, 30, 47, 30, 75, alpha=0.2)
    _contours(c, rng, 10, 47, 7, 3, 2.2)
    _contours(c, rng, 18, 6, 6, 4, 2.4, alpha=0.25)
    _contours(c, rng, 72, 12, 5, 4, 2.6, alpha=0.2)
    _mountain(c)
    _green_mountain(c)
    _microline(c, ID_H - 6.9, 31.8, ID_W, "CONFOEDERATIO HELVETICA •", IDC.teal)
    _microline(c, 3.6, 2.5, 31, "SCHWEIZ • SUISSE • SVIZZERA • SVIZRA • SWITZERLAND •",
               IDC.contour, 0.4)


CANTON_ROWS = ("VS BE GR UR GL TI SG OW VD", "NW SZ AR AI FR LU ZG NE SO", "JU ZH BL TG SH AG BS GE")
CANTON_YEARS = " • ".join(
    "UR 1291|SZ 1291|OW 1291|NW 1291|LU 1332|ZH 1351|GL 1352|ZG 1352|BE 1353|FR 1481|SO 1481|BS 1501|BL 1501|"
    "SH 1501|AI 1513|AR 1513|SG 1803|GR 1803|AG 1803|TG 1803|TI 1803|VD 1803|VS 1815|NE 1815|GE 1815|JU 1979|"
    "CONFOEDERATIO HELVETICA".split("|")) + " •"


def _form_back(c: Canvas) -> None:
    rng = np.random.default_rng(2024)
    _bg_base(c)
    _wave_lines(c, IDC.guilloche, 58, 1, 53)
    _contours(c, rng, 40, 44, 6, 3, 2.3, alpha=0.25)
    _bubbles(c, rng)
    _triangles(c, rng, 0.5, 16, 27, 43, 22)
    c.setFillColor(HexColor("#1E1E1E"))                      # schwarzes Dreieck (stilisiertes Kinegramm)
    c.drawPath(_poly(c, [(4.2, 31.3), (11.4, 31.3), (7.8, 36.8)]), stroke=0, fill=1)
    _gold_drop(c)
    # Band Ausstellung/Behörde: aufgehellt, wellige Unterkante, Mikroschrift-Linie mit Kantonen
    xs = np.linspace(ID_W, 0, 60)
    c.setFillColor(white)
    c.setFillAlpha(0.45)
    c.drawPath(_poly(c, [(0, ID_H - 26.6), (ID_W, ID_H - 26.6)]
                     + [(xx, ID_H - 32.4 + 0.25 * np.sin(xx * 1.7) + 0.15 * np.sin(xx * 4.1)) for xx in xs]),
               stroke=0, fill=1)
    c.setFillAlpha(1)
    _microline(c, ID_H - 33.0, 0.8, ID_W - 0.8, CANTON_YEARS, HexColor("#E7A274"), 0.45)
    # MRZ-Zone: ruhiger Grund, Kantonskürzel als blasse Konturschrift
    c.setFillColor(HexColor("#E2EFF3"))
    c.setFillAlpha(0.7)
    c.rect(0, 0, ID_W * mm, (ID_H - 33.0) * mm, stroke=0, fill=1)
    c.setFillAlpha(1)
    c.setStrokeColor(HexColor("#A9D3D8"))
    c.setStrokeAlpha(0.45)
    c.setLineWidth(0.15)
    for i, row in enumerate(CANTON_ROWS):
        t = c.beginText()
        t.setTextRenderMode(1)
        t.setFont("Sans", 11)
        for j, kt in enumerate(row.split()):
            t.setTextOrigin((5.5 + j * 8.9) * mm, (ID_H - 37.0 - i * 6.3) * mm)
            t.textOut(kt)
        c.drawText(t)
    c.setStrokeAlpha(1)


class _FlatAlpha:
    """Canvas-Hülle für Form-XObjects: Transparenz als Mischung mit der Grundfarbe (viewer-unabhängig)."""

    def __init__(self, c: Canvas, bg: Color):
        self._c, self._bg = c, bg
        self._fill, self._stroke = (Color(0, 0, 0), 1.0), (Color(0, 0, 0), 1.0)

    def __getattr__(self, name):
        return getattr(self._c, name)

    def _mix(self, col: Color, a: float) -> Color:
        b = self._bg
        return Color(b.red + (col.red - b.red) * a, b.green + (col.green - b.green) * a,
                     b.blue + (col.blue - b.blue) * a)

    def setFillColor(self, col, alpha=None):
        self._fill = (col, self._fill[1])
        self._c.setFillColor(self._mix(*self._fill))

    def setStrokeColor(self, col, alpha=None):
        self._stroke = (col, self._stroke[1])
        self._c.setStrokeColor(self._mix(*self._stroke))

    def setFillAlpha(self, a):
        self._fill = (self._fill[0], a)
        self._c.setFillColor(self._mix(*self._fill))

    def setStrokeAlpha(self, a):
        self._stroke = (self._stroke[0], a)
        self._c.setStrokeColor(self._mix(*self._stroke))


def _use_form(c: Canvas, name: str, x: float, y: float, build) -> None:
    """Hintergrund einmal je PDF als Form-XObject anlegen und wiederverwenden."""
    done = c.__dict__.setdefault("_id_forms", set())
    if name not in done:
        c.beginForm(name, lowerx=0, lowery=0, upperx=ID_W * mm, uppery=ID_H * mm)
        c.saveState()
        build(_FlatAlpha(c, Color(0.86, 0.92, 0.95)))
        c.restoreState()
        c.endForm()
        done.add(name)
    c.saveState()
    c.translate(x, y)
    c.doForm(name)
    c.restoreState()


# --- Personalisierung ---

def card_outline(c: Canvas, x: float, y: float, ci: CI) -> None:
    c.setStrokeColor(ci.line)
    c.setLineWidth(0.3)
    c.roundRect(x, y, ID_W * mm, ID_H * mm, ID_R * mm, stroke=1, fill=0)


def specimen(c: Canvas, x: float, y: float, size: float, angle: float = 0, spacing: float = 0) -> None:
    """SPECIMEN als Konturschrift (wie fedpol-Muster)."""
    c.saveState()
    c.translate(x, y)
    c.rotate(angle)
    c.setStrokeColor(HexColor("#333333"))
    c.setLineWidth(0.3)
    t = c.beginText()
    t.setTextRenderMode(1)
    t.setFont("Sans-Bold", size)
    t.setCharSpace(spacing)
    t.setTextOrigin(0, 0)
    t.textOut("SPECIMEN")
    c.drawText(t)
    c.restoreState()


def ghost_window(c: Canvas, x: float, y: float, w: float, h: float, p: CardPerson) -> None:
    """Transparentes Fenster mit blassem Geisterbild."""
    k = w * 0.18
    path = c.beginPath()
    path.moveTo(x + k, y)
    path.curveTo(x + w * 0.5, y + h * 0.04, x + w - k * 0.5, y - h * 0.02, x + w - k * 0.3, y + k)
    path.curveTo(x + w - k * 0.9, y + h * 0.5, x + w, y + h * 0.8, x + w - k * 0.6, y + h - k * 0.6)
    path.curveTo(x + w * 0.6, y + h * 1.01, x + k * 0.5, y + h, x + k * 0.3, y + h - k)
    path.curveTo(x + k * 0.9, y + h * 0.5, x, y + h * 0.25, x + k, y)
    path.close()
    c.saveState()
    c.setFillColor(IDC.window)
    c.setFillAlpha(0.6)
    c.drawPath(path, stroke=0, fill=1)
    c.clipPath(path, stroke=0, fill=0)
    if p.photo_seed is not None:
        draw_avatar(c, x + w * 0.1, y + h * 0.05, w * 0.8, h * 0.92, _age(p.dob), p.gender,
                    np.random.default_rng(p.photo_seed), gray=True)
        c.setFillColor(IDC.window)
        c.setFillAlpha(0.72)
        c.rect(x, y, w, h, stroke=0, fill=1)
    c.restoreState()


def draw_id_front(c: Canvas, x: float, y: float, p: CardPerson, ci: CI) -> None:
    _use_form(c, "IDFront2023", x, y, _form_front)
    top = y + ID_H * mm
    X = lambda v: x + v * mm  # noqa: E731

    fit_text(c, X(3.8), _at(top, 4.9), "SCHWEIZ SUISSE SVIZZERA SVIZRA SWITZERLAND", 77.5 * mm, "Mono", 10.5,
             color=IDC.data)
    swiss_cross(c, X(32.3), _at(top, 11.2), 3.3 * mm, ci)
    # Dokumentnummer rechtsbündig; Titelzeilen links davon, bei Bedarf verkleinert (kein Überlappen)
    doc_size = 10.0
    while doc_size > 6 and pdfmetrics.stringWidth(p.doc_number, "Mono", doc_size) > 19 * mm:
        doc_size -= 0.2
    doc_x = X(ID_W - 2.0) - pdfmetrics.stringWidth(p.doc_number, "Mono", doc_size)
    titles = (f"IDENTITÄTSKARTE {SEP} CARTE D'IDENTITÉ", f"CARTA D'IDENTITÀ {SEP} CARTA D'IDENTITAD", "IDENTITY CARD")
    title_size, title_max = 3.9, doc_x - X(36.9) - 1.2 * mm
    while title_size > 2.8 and max(mono_label_width(t, title_size) for t in titles) > title_max:
        title_size -= 0.05
    for i, ln in enumerate(titles):
        mono_label(c, X(36.9), _at(top, 8.9 + i * 1.25), ln, title_size)
    data_text(c, doc_x, _at(top, 10.1), p.doc_number, doc_size)

    px, py, pw, ph = X(3.9), _at(top, 42.2), 26.4 * mm, 31.6 * mm
    if p.photo_seed is None:
        photo_placeholder(c, px, py, pw, ph, ci)
    else:
        draw_avatar(c, px, py, pw, ph, _age(p.dob), p.gender, np.random.default_rng(p.photo_seed), gray=True)
    ghost_window(c, X(59.6), _at(top, 25.6), 9.8 * mm, 12.6 * mm, p)
    micro = f"{p.dob:%d/%m/%Y}<{p.height_cm}<{p.doc_number}<{p.expiry:%d/%m/%Y}"
    fit_text(c, X(6.4), _at(top, 43.1), f"{micro}<{micro}", 22 * mm, "Mono", 1.75, min_size=1.2, color=IDC.data)

    if _age(p.dob) >= 7:
        rng = np.random.default_rng([p.card_no, zlib.crc32(f"{p.doc_number}{p.last_name}".encode())])
        draw_signature(c, X(4.6), _at(top, 49.4), 26 * mm, p.first_name, p.last_name, rng, _age(p.dob),
                       max_h=6.5 * mm)

    fx, fw = X(32.6), (ID_W - 32.6 - 3.0) * mm
    ml_label(c, fx, _at(top, 27.3), f"Name {SEP} Nom {SEP} Cognome {SEP} Num {SEP} Surname")
    data_text(c, fx, _at(top, 30.9), p.last_name, max_w=fw, end_mark=True)
    ml_label(c, fx, _at(top, 33.6), f"Vorname(n) {SEP} Prénom(s) {SEP} Nome(i) {SEP} Prenum(s) {SEP} Given name(s)")
    data_text(c, fx, _at(top, 37.3), p.first_name, max_w=fw, end_mark=True)

    rows3 = lambda xx, v, lines: [ml_label(c, xx, _at(top, v + i * 1.25), ln)  # noqa: E731
                                  for i, ln in enumerate(lines)]
    rows3(fx, 40.0, (f"Geschlecht {SEP} Sexe", f"Sesso {SEP} Schlattaina", "Sex"))
    rows3(X(47.5), 40.0, (f"Nationalität {SEP} Nationalité", f"Cittadinanza {SEP} Naziunalitad", "Nationality"))
    data_text(c, fx, _at(top, 44.9), {"m": "M", "f": "F"}.get(p.gender, "X"), 7.4)
    data_text(c, X(47.5), _at(top, 44.9), "CHE", 7.4)
    rows3(fx, 46.3, (f"Geburtsdatum {SEP} Date de naissance", f"Data di nascita {SEP} Data da naschientscha",
                     "Date of birth"))
    rows3(X(59.6), 46.3, (f"Gültig bis {SEP} Date d'expiration", f"Data di scadenza {SEP} Data da scadenza",
                          "Date of expiry"))
    data_text(c, fx, _at(top, 51.3), fmt_date(p.dob))
    data_text(c, X(59.6), _at(top, 51.3), fmt_date(p.expiry))

    specimen(c, X(7.3), _at(top, 41.0), 13.5, angle=90, spacing=1.0)
    card_outline(c, x, y, ci)


def draw_mrz(c: Canvas, x: float, y: float, td1: TD1) -> None:
    """MRZ: feste Teilung 2.54 mm, Zeilenabstand 4.23 mm, Zeichen zentriert in der Zelle."""
    font = pdfmetrics.getFont("MRZ")
    cap = getattr(font.face, "capHeight", 730) / 1000
    size = (MRZ_CAP_MM / cap) * mm
    c.setFont("MRZ", size)
    c.setFillColorRGB(0, 0, 0)
    x0 = x + (ID_W - 30 * MRZ_PITCH) / 2 * mm
    for li, line in enumerate(td1.lines):
        by = y + (3.0 + (2 - li) * MRZ_LINE) * mm
        for ci_, ch in enumerate(line):
            c.drawCentredString(x0 + (ci_ + 0.5) * MRZ_PITCH * mm, by, ch)


def draw_id_back(c: Canvas, x: float, y: float, p: CardPerson, ci: CI) -> None:
    _use_form(c, "IDBack2023", x, y, _form_back)
    top = y + ID_H * mm
    X = lambda v: x + v * mm  # noqa: E731

    ml_label(c, X(5.0), _at(top, 4.4),
             f"Heimatort {SEP} Lieu d'origine {SEP} Luogo di attinenza {SEP} Lieu d'origin {SEP} Place of origin")
    data_text(c, X(5.0), _at(top, 7.4), p.origin, max_w=40 * mm)
    ml_label(c, X(5.0), _at(top, 8.9), f"Grösse {SEP} Taille {SEP} Statura {SEP} Grondezza {SEP} Height")
    data_text(c, X(5.0), _at(top, 11.8), f"{p.height_cm} cm")

    ghost_window(c, X(16.2), _at(top, 25.6), 9.8 * mm, 12.8 * mm, p)
    c.saveState()   # optisch variables Feld: Ablaufjahr und Dokumentnummer, unscharf
    c.setFillColor(HexColor("#4A4A4A"))
    c.setFillAlpha(0.13)
    for dx, dy in [(-0.25, 0), (0.25, 0), (0, 0.25), (0, -0.25), (0.18, 0.18), (-0.18, -0.18), (0, 0)]:
        c.setFont("Sans", 9.5)
        c.drawString(X(34.0 + dx), _at(top, 18.4 + dy), str(p.expiry.year))
        c.drawString(X(33.6 + dx), _at(top, 22.6 + dy), p.doc_number)
    c.restoreState()

    ml_label(c, X(5.2), _at(top, 28.4),
             f"Ausgestellt am {SEP} Délivrée le {SEP} Rilasciata il {SEP} Emessa ils {SEP} Date of issue")
    data_text(c, X(5.2), _at(top, 31.6), fmt_date(p.issue_date))
    ml_label(c, X(44.2), _at(top, 28.4), f"Behörde {SEP} Autorité {SEP} Autorità {SEP} Autoritad {SEP} Authority")
    data_text(c, X(44.2), _at(top, 31.6), p.authority, max_w=(ID_W - 44.2 - 3) * mm)

    c.saveState()
    c.translate(X(82.6), _at(top, 26.6))
    c.rotate(90)
    text(c, 0, 0, p.serial, "Mono", 5.6, IDC.data)
    c.restoreState()
    specimen(c, X(48.5), _at(top, 6.6), 13, spacing=3.2)
    draw_mrz(c, x, y, p.td1)
    card_outline(c, x, y, ci)


def draw_header(c: Canvas, x: float, y_top: float, w: float, ci: CI, logo: Optional[str]) -> float:
    """CI-Kopf: Bundeslogo links, Amt rechts. Gibt Unterkante zurück."""
    h = 10.5 * mm
    if logo:
        img = ImageReader(logo)
        iw, ih = img.getSize()
        lh = h - 1 * mm
        c.drawImage(img, x, y_top - lh, lh * iw / ih, lh, mask="auto")
    else:
        s = 6.2 * mm
        swiss_cross(c, x, y_top - s - 0.3 * mm, s, ci)
        for i, ln in enumerate(ci.conf_lines):
            text(c, x + s + 2.2 * mm, y_top - 2.0 * mm - i * 2.1 * mm, ln, "Sans", 5.0, ci.text)
    for i, ln in enumerate(ci.dept_lines):
        text(c, x + w, y_top - 2.0 * mm - i * 2.6 * mm, ln, "Sans-Bold", 5.6, ci.text, "r")
    text(c, x + w, y_top - 4.6 * mm - (len(ci.dept_lines) - 1) * 2.6 * mm,
         "Ausbildung IES NG", "Sans", 5.6, ci.red, "r")
    c.setStrokeColor(ci.line)
    c.setLineWidth(0.3)
    c.line(x, y_top - h, x + w, y_top - h)
    return y_top - h


def draw_qr(c: Canvas, x: float, y: float, size: float, payload: str, error: str) -> None:
    qr = segno.make_qr(payload, version=2, mode="byte", error=error, boost_error=False)
    border = 4
    n = len(qr.matrix)
    m = size / (n + 2 * border)
    c.setFillColor(white)
    c.rect(x, y, size, size, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    for ri, row in enumerate(qr.matrix):
        yy = y + size - (border + ri + 1) * m
        ci_ = 0
        while ci_ < n:
            if row[ci_]:
                start = ci_
                while ci_ < n and row[ci_]:
                    ci_ += 1
                c.rect(x + (border + start) * m, yy, (ci_ - start) * m, m, stroke=0, fill=1)
            else:
                ci_ += 1


def wrap(s: str, font: str, size: float, max_w: float) -> list[str]:
    lines, cur = [], ""
    for w in s.split():
        t = f"{cur} {w}".strip()
        if pdfmetrics.stringWidth(t, font, size) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def draw_kat(c: Canvas, x: float, y: float, w: float, h: float, titel: str, kat: str) -> None:
    """Farbfeld einer PLS-Farbkategorie."""
    label, roman, bg, fg = KATEGORIEN[kat]
    bg, fg = HexColor(bg), HexColor(fg)
    c.setFillColor(bg)
    c.setStrokeColor(HexColor("#1F1F1F"))
    c.setLineWidth(0.5)
    c.roundRect(x, y, w, h, 1.2 * mm, stroke=1, fill=1)
    text(c, x + 1.6 * mm, y + h - 3.0 * mm, titel, "Sans-Bold", 4.8, fg)
    text(c, x + w - 1.6 * mm, y + h - 3.0 * mm, roman, "Sans-Bold", 5.5, fg, "r")
    size = 13.0
    while size > 6 and pdfmetrics.stringWidth(label, "Sans-Bold", size) > w - 3 * mm:
        size -= 0.5
    text(c, x + w / 2, y + 2.4 * mm, label, "Sans-Bold", size, fg, "c")


def draw_card(c: Canvas, ox: float, oy: float, p: CardPerson, ci: CI, args: argparse.Namespace,
              side: str = "front") -> None:
    """A6-Karte (105 x 148 mm), Ursprung unten links. front = Patientenkarte, back = Ausweis."""
    (draw_card_front if side == "front" else draw_card_back)(c, ox, oy, p, ci, args)


def draw_card_front(c: Canvas, ox: float, oy: float, p: CardPerson, ci: CI, args: argparse.Namespace) -> None:
    """Vorderseite: PLS-ID mit QR, Prä-Triage (Swiss Pre), Triage, Auffindesituation, Verletzung, Befunde."""
    W, H = A6
    f = p.fall
    w = ID_W * mm
    x = ox + (W - w) / 2
    y = draw_header(c, x, oy + H - 4 * mm, w, ci, args.logo)

    # QR oben rechts (Modulkante bündig mit Inhaltsrand)
    qs = args.qr_size * mm
    quiet = qs * 4 / 33
    qx, qy = x + w + quiet - qs, y - 2.5 * mm - qs + quiet
    draw_qr(c, qx, qy, qs, p.qr_payload, args.qr_error)

    lw = qx + quiet - x - 3 * mm               # Breite links vom QR
    by = qy + quiet                            # Farbfelder unten bündig mit den QR-Modulen
    bw, bh = (lw - 2 * mm) / 2, min(12 * mm, y - 13.5 * mm - by)
    text(c, x, y - 7.6 * mm, p.card_id, "Sans-Bold", 19, ci.text)
    text(c, x, y - 11.0 * mm, "Patientenkarte – Übung IES NG", "Sans", 6.2, ci.grey)
    draw_kat(c, x, by, bw, bh, "PRÄ-TRIAGE", f.pre)
    draw_kat(c, x + bw + 2 * mm, by, bw, bh, "TRIAGE", f.triage)

    # Auffindesituation (Szene mit Figur im Aussehen des Passfotos)
    sh = 60 * mm
    sy = by - 3 * mm - sh
    look = make_look(_age(p.dob), p.gender, np.random.default_rng(p.photo_seed or (args.seed, p.card_no)))
    draw_scene(c, x, sy, w, sh, look, f.pose, f.mimik, f.marks, f.env)
    c.setStrokeColor(ci.line)
    c.setLineWidth(0.4)
    c.rect(x, sy, w, sh, stroke=1, fill=0)
    c.setFillColor(white)
    c.setFillAlpha(0.85)
    c.roundRect(x + 1.2 * mm, sy + sh - 5.2 * mm, 26 * mm, 4 * mm, 1 * mm, stroke=0, fill=1)
    c.setFillAlpha(1)
    text(c, x + 2.4 * mm, sy + sh - 4.1 * mm, "AUFFINDESITUATION", "Sans-Bold", 5.6, ci.text)

    # Verletzung + Beschreibung
    ty = sy - 4.4 * mm
    fit_text(c, x, ty, f.titel, w, "Sans-Bold", 8.5, color=ci.text)
    for i, ln in enumerate(wrap(f.text, "Sans", 6.3, w)[:3]):
        text(c, x, ty - (3.6 + i * 2.8) * mm, ln, "Sans", 6.3, ci.text)

    # Befunde (Grundlage für Swiss Pre)
    fy = ty - 13.4 * mm
    c.setStrokeColor(ci.line)
    c.line(x, fy + 2.6 * mm, x + w, fy + 2.6 * mm)
    text(c, x, fy, "BEFUNDE", "Sans-Bold", 5.4, ci.grey)
    for i, ln in enumerate(befund_zeilen(f.befund)):
        fit_text(c, x, fy - (2.8 + i * 2.6) * mm, ln, w, "Sans", 6.0, min_size=4.2, color=ci.text)
    fit_text(c, x, oy + 3.2 * mm, "Fiktiver Übungsfall – kein amtliches Dokument – nur Ausbildung IES NG",
             w, "Sans", 4.6, min_size=3.5, color=ci.grey)


def draw_card_back(c: Canvas, ox: float, oy: float, p: CardPerson, ci: CI, args: argparse.Namespace) -> None:
    """Rückseite: Ausweis (Vorder- und Rückseite, Originalgrösse) und Angaben zur Person."""
    W, H = A6
    x = ox + (W - ID_W * mm) / 2
    y = draw_header(c, x, oy + H - 4 * mm, ID_W * mm, ci, args.logo)
    front_y = y - 2 * mm - ID_H * mm
    draw_id_front(c, x, front_y, p, ci)
    if not getattr(args, "_enlarged", False):  # Kontrollmass nur bei Originalgrösse sinnvoll
        control_scale(c, x - 4.5 * mm, front_y, ci)
    back_y = front_y - 2 * mm - ID_H * mm
    draw_id_back(c, x, back_y, p, ci)

    w = ID_W * mm
    ty = back_y - 4.6 * mm
    text(c, x, ty, f"Angaben zur Person · {p.card_id}", "Sans-Bold", 7.5, ci.text)
    fit_text(c, x, ty - 3.4 * mm, f"{p.last_name} {p.first_name}, geb. {p.dob:%d.%m.%Y}", w, "Sans", 6.5,
             color=ci.text)
    fit_text(c, x, ty - 6.2 * mm, f"{p.street} {p.house_number}, {p.postcode} {p.city}".replace(" ,", ","),
             w, "Sans", 6.5, color=ci.text)
    fit_text(c, x, oy + 3.2 * mm, "Fiktive Personendaten – kein amtliches Dokument – nur Ausbildung IES NG",
             w, "Sans", 4.6, min_size=3.5, color=ci.grey)


def control_scale(c: Canvas, x: float, y: float, ci: CI, length_mm: int = 50) -> None:
    """Senkrechtes Kontrollmass (mm-Teilung) zur Prüfung des Drucks in Originalgrösse."""
    c.setStrokeColor(ci.grey)
    c.setLineWidth(0.25)
    c.line(x, y, x, y + length_mm * mm)
    for i in range(length_mm + 1):
        t = 2.0 if i % 10 == 0 else 1.3 if i % 5 == 0 else 0.7
        c.line(x, y + i * mm, x + t * mm, y + i * mm)
    c.saveState()
    c.translate(x - 0.8 * mm, y + length_mm / 2 * mm)
    c.rotate(90)
    text(c, 0, 0, f"Kontrollmass {length_mm} mm – Druck 100 %", "Sans", 4.2, ci.grey, "c")
    c.restoreState()


def cut_marks(c: Canvas, ox: float, oy: float, w: float, h: float) -> None:
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setLineWidth(0.25)
    c.setDash(1, 2)
    c.rect(ox, oy, w, h, stroke=1, fill=0)
    c.setDash()


def render_pdf(cards: list[CardPerson], out: Path, args: argparse.Namespace, ci: CI) -> None:
    """Beidseitig: je Karte Vorderseite (Patientenkarte) und Rückseite (Ausweis), Wenden an der langen Kante."""
    W, H = A6
    if args.layout == "a6":
        c = Canvas(str(out), pagesize=A6)
        for p in cards:
            for side in ("front", "back"):
                draw_card(c, 0, 0, p, ci, args, side)
                c.showPage()
    elif args.layout == "a4-1":  # 1 Karte je A4, Originalgrösse, zentriert mit Schnittlinien
        c = Canvas(str(out), pagesize=A4)
        ox, oy = (A4[0] - W) / 2, (A4[1] - H) / 2
        for p in cards:
            for side in ("front", "back"):
                draw_card(c, ox, oy, p, ci, args, side)
                if args.cut_marks:
                    cut_marks(c, ox, oy, W, H)
                c.showPage()
    elif args.layout == "a4-gross":  # 1 Karte je A4, vergrössert (A6 -> A4 = Faktor 2)
        c = Canvas(str(out), pagesize=A4)
        scale = min(A4[0] / W, A4[1] / H)
        ox, oy = (A4[0] - W * scale) / 2, (A4[1] - H * scale) / 2
        args._enlarged = True
        for p in cards:
            for side in ("front", "back"):
                c.saveState()
                c.translate(ox, oy)
                c.scale(scale, scale)
                draw_card(c, 0, 0, p, ci, args, side)
                c.restoreState()
                text(c, A4[0] / 2, 4 * mm, f"Vergrössert ({scale:.0%}) – nicht Originalgrösse", "Sans", 7,
                     ci.grey, "c")
                c.showPage()
        args._enlarged = False
    else:  # 4 x A6 auf A4: Seite mit 4 Vorderseiten, dann Seite mit 4 Rückseiten (Spalten gespiegelt)
        c = Canvas(str(out), pagesize=A4)
        cell_h = A4[1] / 2
        front_slots = [(0, cell_h), (W, cell_h), (0, 0), (W, 0)]
        back_slots = [(W, cell_h), (0, cell_h), (W, 0), (0, 0)]
        for i in range(0, len(cards), 4):
            for side, slots in (("front", front_slots), ("back", back_slots)):
                for p, (ox, oy) in zip(cards[i:i + 4], slots):
                    draw_card(c, ox, oy + (cell_h - H) / 2, p, ci, args, side)
                    if args.cut_marks:
                        cut_marks(c, ox, oy, W, cell_h)
                c.showPage()
    c.setTitle("Ausbildung IES NG – Patientenkarten (Übung)")
    c.setViewerPreference("PrintScaling", "None")  # Druckdialog: tatsächliche Grösse
    c.setViewerPreference("Duplex", "DuplexFlipLongEdge")
    c.setAuthor("BABS – Ausbildung IES NG")
    c.save()


PNG_PARTS = ("card", "front", "back", "mrz", "qr")


def export_png(cards: list[CardPerson], out_dir: Path, args: argparse.Namespace, ci: CI) -> int:
    """
    PNG je Karte und Teil (z. B. für die virtuelle Kamera des Android-Emulators).
    Teile werden freigestellt auf weissem Grund gerendert (keine Nachbarelemente im Bild).
    """
    try:
        import pymupdf
    except ImportError:
        raise SystemExit("PNG-Export benötigt pymupdf: pip install pymupdf")
    import io

    pad = args.png_margin * mm
    sizes = {"card": A6, "front": (ID_W * mm + 2 * pad, ID_H * mm + 2 * pad),
             "back": (ID_W * mm + 2 * pad, ID_H * mm + 2 * pad),
             "mrz": ((MRZ_W_MM + 2 * MRZ_MARGIN_MM) * mm, (MRZ_H_MM + 2 * MRZ_MARGIN_MM) * mm)}
    pdf_parts = [pt for pt in args.png_parts if pt in sizes]

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A6)
    order = []
    for p in cards:
        for part in pdf_parts:
            c.setPageSize(sizes[part])
            c.setFillColor(white)
            c.rect(0, 0, *sizes[part], stroke=0, fill=1)
            if part == "card":
                draw_card(c, 0, 0, p, ci, args, "front")
                c.showPage()
                order.append((p.card_id, "card"))
                c.setPageSize(sizes[part])
                draw_card(c, 0, 0, p, ci, args, "back")
                part = "card_back"
            elif part == "front":
                draw_id_front(c, pad, pad, p, ci)
            elif part == "back":
                draw_id_back(c, pad, pad, p, ci)
            else:
                # eng freigestellt: Zeichenblock + MRZ_MARGIN_MM weisser Rand
                draw_mrz(c, (MRZ_MARGIN_MM - (ID_W - MRZ_W_MM) / 2) * mm, (MRZ_MARGIN_MM - MRZ_BASE_MM) * mm, p.td1)
            c.showPage()
            order.append((p.card_id, part))
    c.save()

    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    if order:
        doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
        for page, (cid, part) in zip(doc, order):
            if part.startswith("card"):
                zoom = args.png_dpi / 72
            elif part == "mrz":   # lange Kante = --png-long-edge
                zoom = args.png_long_edge / max(page.rect.width, page.rect.height)
            else:
                zoom = args.png_dpi * args.png_crop_zoom / 72
            page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(out_dir / f"{cid}_{part}.png")
            n += 1
    if "qr" in args.png_parts:
        for p in cards:
            qr = segno.make_qr(p.qr_payload, version=2, mode="byte", error=args.qr_error, boost_error=False)
            border = 4                                          # Ruhezone 4 Module (ISO/IEC 18004)
            scale = max(1, round(args.png_long_edge / (len(qr.matrix) + 2 * border)))
            qr.save(out_dir / f"{p.card_id}_qr.png", scale=scale, border=border)
            n += 1
    return n


def write_key(cards: list[CardPerson], path: Path) -> None:
    cols = ["card_id", "qr_payload", "pre_triage", "triage", "swiss_pre_kriterium", "fall", "verletzung",
            "beschreibung", "gehfaehig", "atmung", "af", "stridor", "atemwege_offenhalten", "radialispuls",
            "rekap_s", "blutung", "befolgt_aufforderungen", "starke_schmerzen", "last_name", "first_name", "gender",
            "dob", "street", "house_number", "postcode", "city", "canton", "origin", "height_cm", "doc_number",
            "issue_date", "expiry", "expired", "mrz_line1", "mrz_line2", "mrz_line3", "mrz_valid", "mrz_error"]
    lab = lambda k: KATEGORIEN[k][0]  # noqa: E731
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for p in cards:
            fa, b = p.fall, p.fall.befund
            w.writerow([p.card_id, p.qr_payload, lab(fa.pre), lab(fa.triage), fa.kriterium, fa.key, fa.titel,
                        fa.text, b.gehfaehig, b.atmung, b.af, b.stridor, b.offenhalten, b.radialispuls, b.rekap_s,
                        b.blutung, b.kommando, b.schmerzen_stark,
                        p.last_name, p.first_name, p.gender, p.dob.isoformat(),
                        p.street, p.house_number, p.postcode, p.city, p.canton, p.origin, p.height_cm,
                        p.doc_number, p.issue_date.isoformat(), p.expiry.isoformat(), p.expired,
                        *p.td1.lines, all(p.checks.values()), p.mrz_error])

# -------------------------
# CLI
# -------------------------

def describe_params(ap: argparse.ArgumentParser) -> list[dict]:
    """Parameter als JSON-taugliche Liste (für UIs wie DroidSim)."""
    out = []
    for grp in ap._action_groups:
        for a in grp._group_actions:
            if a.dest in ("help",) or a.help == argparse.SUPPRESS:
                continue
            if isinstance(a, argparse._StoreTrueAction):
                typ = "bool"
            elif isinstance(a, argparse._StoreFalseAction):
                typ = "bool_neg"
            elif a.nargs in ("+", "*"):
                typ = "list"
            else:
                typ = {int: "int", float: "float"}.get(a.type, "str")
            out.append({"name": a.option_strings[-1], "dest": a.dest, "group": grp.title, "type": typ,
                        "default": a.default, "choices": list(a.choices) if a.choices else None,
                        "help": a.help, "flag_without_value_const": a.const if a.nargs == "?" else None})
    return out


def _png_size(f: Path) -> tuple[int, int]:
    """Breite/Höhe aus dem PNG-Header (ohne zusätzliche Abhängigkeit)."""
    with f.open("rb") as fh:
        head = fh.read(24)
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def write_manifest(cards: list[CardPerson], path: Path, png_dir: Optional[Path], pdf: Path, key: Path,
                   args: argparse.Namespace) -> None:
    """Maschinenlesbare Übersicht je Patient inkl. Bildpfaden (relativ zum Manifest)."""
    def rel(f: Path) -> str:
        try:
            return str(f.resolve().relative_to(path.parent.resolve())).replace("\\", "/")
        except ValueError:
            return str(f.resolve())

    params = {k: v for k, v in vars(args).items() if not k.startswith("_")}
    items = []
    for p in cards:
        fa = p.fall
        imgs, info = {}, {}
        if png_dir:
            for part in ("card", "card_back", "front", "back", "mrz", "qr"):
                f = png_dir / f"{p.card_id}_{part}.png"
                if f.is_file():
                    imgs[part] = rel(f)
                    info[part] = dict(zip(("width", "height"), _png_size(f)))
        items.append({
            "card_id": p.card_id, "label": f"{p.card_id} – {p.last_name} {p.first_name} – {fa.titel}",
            "qr_payload": p.qr_payload,
            "pre_triage": fa.pre, "triage": fa.triage, "swiss_pre_kriterium": fa.kriterium,
            "fall": fa.key, "verletzung": fa.titel, "beschreibung": fa.text, "befund": fa.befund_dict(),
            "person": {"first_name": p.first_name, "last_name": p.last_name, "gender": p.gender,
                       "dob": p.dob.isoformat(), "street": p.street, "house_number": p.house_number,
                       "postcode": p.postcode, "city": p.city, "canton": p.canton},
            "ausweis": {"doc_number": p.doc_number, "expiry": p.expiry.isoformat(), "mrz": list(p.td1.lines),
                        "mrz_valid": all(p.checks.values())},
            "images": imgs, "image_info": info,
        })
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    data = {"schema": "ies-ng-karten/1", "generated": now, "generated_at": now,
            "pdf": rel(pdf), "loesungen": rel(key), "params": params, "count": len(items), "cards": items}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="IES NG Übungskarten (A6) erzeugen", fromfile_prefix_chars="@")
    g = ap.add_argument_group("Karten")
    g.add_argument("-n", "--count", type=int, default=20, help="Anzahl Karten")
    g.add_argument("--start", type=int, default=1, help="erste laufende Nummer (1 = --id-start)")
    g.add_argument("--id-start", default="CHYY001", help="erste PLS-ID: CH + 2 Buchstaben + 3 Ziffern")
    g.add_argument("--layout", choices=["a6", "a4", "a4-1", "a4-gross"], default="a6",
                   help="a6 = 1 Karte/Seite A6; a4 = 4 Karten/A4; a4-1 = 1 Karte/A4 in Originalgrösse; "
                        "a4-gross = 1 Karte/A4 vergrössert")

    g = ap.add_argument_group("PNG-Export (z. B. Android-Emulator, virtuelle Kamera)")
    g.add_argument("--png", nargs="?", const="png", metavar="ORDNER",
                   help="PNGs erzeugen (Default-Ordner: png/ neben dem PDF)")
    g.add_argument("--png-parts", nargs="+", choices=PNG_PARTS, default=["card", "qr", "mrz"],
                   help="card = ganze Karte, front/back = ID-Seite, mrz = nur MRZ, qr = nur QR-Code")
    g.add_argument("--png-dpi", type=int, default=300, help="Auflösung ganze Karte")
    g.add_argument("--png-crop-zoom", type=float, default=2.0, help="Faktor auf --png-dpi für front/back")
    g.add_argument("--png-long-edge", type=int, default=1400, help="lange Kante in px für qr und mrz")
    g.add_argument("--png-margin", type=float, default=6.0, help="weisser Rand um front/back/mrz, mm")
    g.add_argument("--manifest", nargs="?", const="auto", metavar="DATEI",
                   help="JSON je Patient mit Bildpfaden (Default bei --png: <png-ordner>/manifest.json)")
    g.add_argument("--describe-params", action="store_true",
                   help="alle Parameter als JSON ausgeben und beenden (für UIs, z. B. DroidSim)")
    g.add_argument("--no-cut-marks", dest="cut_marks", action="store_false")
    g.add_argument("-o", "--out", default="ies_ng_karten.pdf")
    g.add_argument("--key", default=None, help="Lösungsliste CSV (Default: <out>_loesungen.csv)")
    g.add_argument("--seed", type=int, default=2026)
    g.add_argument("--doc-prefix", default="X", help="1. Zeichen der fiktiven Dokumentnummer")

    g = ap.add_argument_group("QR")
    g.add_argument("--qr-format", default="{id}",
                   help="Payload, {id} = Kartennummer; CHA-Format: \"(dc|{id}|{id})\"")
    g.add_argument("--qr-error", choices=["l", "m", "q"], default="m", help="ECC-Stufe (Version 2)")
    g.add_argument("--qr-size", type=float, default=30.0, help="Kantenlänge inkl. Ruhezone, mm")

    g = ap.add_argument_group("Übungsfälle")
    g.add_argument("--p-invalid-mrz", type=float, default=0.0, help="Anteil MRZ mit falscher Prüfziffer")
    g.add_argument("--p-expired", type=float, default=0.0, help="Anteil abgelaufener Ausweise")
    g.add_argument("--adults-only", action="store_true")
    g.add_argument("--no-photos", action="store_true", help="Platzhalter statt Comic-Passfoto")

    g = ap.add_argument_group("Prä-Triage (Swiss Pre) / Triage")
    g.add_argument("--pre-mix", default=None,
                   help="Anteile Prä-Triage, Default rot=15,gelb=30,gruen=45,weiss=7,schwarz=3; "
                        "Triage (inkl. Blau) folgt fallbezogen")

    g = ap.add_argument_group("Adressen (nur echte; Default: Register in data/)")
    g.add_argument("--addresses", help="Gebäudeadressverzeichnis (.csv/.csv.zip) oder eigener Auszug")
    g.add_argument("--canton", nargs="*", help="z. B. BE FR")
    g.add_argument("--plz", nargs="*")
    g.add_argument("--gemeinde", nargs="*")
    g.add_argument("--wohngebaeude", action="store_true", help="nur Wohngebäude")

    g = ap.add_argument_group("Namen (Default: BFS-Dateien data/vornamen*, data/nachnamen*; sonst Demo-Listen)")
    g.add_argument("--first-names", help="BFS Vornamen nach Geburtsjahr/Geschlecht (CSV/XLSX)")
    g.add_argument("--last-names", help="BFS Nachnamen nach Kanton (CSV/XLSX)")
    g.add_argument("--name-year-window", type=int, default=2, help="Vornamen: Geburtsjahr ± Jahre")

    g = ap.add_argument_group("CI")
    g.add_argument("--logo", help="offizielles Logo Bund/BABS (PNG/JPG) statt gezeichnetem Kopf")
    g.add_argument("--font-regular", help="z. B. Frutiger Roman TTF")
    g.add_argument("--font-bold", help="z. B. Frutiger Bold TTF")
    g.add_argument("--font-mrz", help="OCR-B TTF (empfohlen)")
    g.add_argument("--font-mono", help="Monospace-TTF für die Personalisierung (ID 2023)")
    args = ap.parse_args(argv)
    if args.describe_params:
        json.dump(describe_params(ap), sys.stdout, ensure_ascii=False, indent=2, default=str)
        print()
        raise SystemExit(0)
    return args


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    last = args.start + args.count - 1
    try:
        cap = pls_capacity(args.id_start)
    except Exception:
        raise SystemExit(f"--id-start {args.id_start}: PLS-Format CH + 2 Buchstaben + 3 Ziffern (z. B. CHYY001)")
    if args.count <= 0 or args.start < 1 or last > cap:
        raise SystemExit(f"Nummernbereich {args.start}..{last} ab {args.id_start} überschreitet CHZZ999 ({cap})")
    fonts = register_fonts({"Sans": args.font_regular, "Sans-Bold": args.font_bold, "MRZ": args.font_mrz, "Mono": args.font_mono})
    if "ocr" not in Path(fonts["MRZ"]).name.lower():
        print(f"Hinweis: MRZ mit Ersatzschrift {Path(fonts['MRZ']).name}; für maschinelles Lesen OCR-B verwenden "
              "(--font-mrz oder fonts/OCRB.ttf).")

    r = np.random.default_rng(args.seed)
    addr = load_addresses(args)
    fn_path = args.first_names or _find_data("vornamen*")
    ln_path = args.last_names or _find_data("nachnamen*")
    if fn_path and ln_path:
        fn, ln = read_ch_names(fn_path, ln_path)
        info = [c for c in ("birth_year", "canton") if c in fn.columns]
        print(f"BFS-Namen: {len(fn)} Vornamen-Zeilen ({', '.join(info) or 'ohne Jahrgang/Kanton'}), "
              f"{len(ln)} Nachnamen-Zeilen ({'nach Kanton' if 'canton' in ln.columns else 'national'})")
    else:
        print("Hinweis: keine BFS-Namensdateien (data/vornamen*, data/nachnamen*) – Demo-Listen verwendet.")
        fn, ln = demo_names()

    cfg = GenConfig(name_year_window=args.name_year_window)
    people = generate_people(args.count * (3 if args.adults_only else 1), addr, fn, ln, cfg=cfg,
                             seed=args.seed, exact_n=True)
    if args.adults_only:
        people = people[people["role"] == "adult"]
        while len(people) < args.count:  # selten: Nachschub
            extra = generate_people(args.count, addr, fn, ln, cfg=cfg, seed=int(r.integers(1e9)), exact_n=True)
            people = pd.concat([people, extra[extra["role"] == "adult"]])
    people = people.head(args.count).reset_index(drop=True)

    cards = build_cards(people, args, r)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(cards, out, args, CI())
    key = Path(args.key) if args.key else out.with_name(out.stem + "_loesungen.csv")
    write_key(cards, key)
    if args.png:
        png_dir = Path(args.png) if Path(args.png).is_absolute() else out.parent / args.png
        n = export_png(cards, png_dir, args, CI())
        print(f"{n} PNG -> {png_dir}")
    else:
        png_dir = None
    if args.manifest or args.png:
        man = Path(args.manifest) if args.manifest and args.manifest != "auto" else \
            (png_dir / "manifest.json" if png_dir else out.with_name(out.stem + "_manifest.json"))
        man.parent.mkdir(parents=True, exist_ok=True)
        write_manifest(cards, man, png_dir, out, key, args)
        print(f"Manifest -> {man}")
    print(f"{len(cards)} Karten {cards[0].card_id}–{cards[-1].card_id} -> {out} ({args.layout}), Lösungen -> {key}")


if __name__ == "__main__":
    main()
