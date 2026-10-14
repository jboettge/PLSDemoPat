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
from dataclasses import dataclass, field
from datetime import date, timedelta
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
    card_bg: Color = HexColor("#F4F1EF")
    card_front_tint: Color = HexColor("#F9E7E9")
    dept_lines: tuple[str, ...] = ("Bundesamt für Bevölkerungsschutz BABS",)
    conf_lines: tuple[str, ...] = (
        "Schweizerische Eidgenossenschaft",
        "Confédération suisse",
        "Confederazione Svizzera",
        "Confederaziun svizra",
    )


TRIAGE = {  # Kategorie: (Beschriftung, Hintergrund, Schrift)
    "rot": ("ROT", HexColor("#E30613"), white),
    "gelb": ("GELB", HexColor("#FFD500"), HexColor("#1F1F1F")),
    "gruen": ("GRÜN", HexColor("#009A44"), white),
}
INJURY_PATTERNS = (
    "Behebbare Atemwegsverlegung",
    "Arterielle Blutung",
    "Verbrennung Grad 2–3 > 60 % KOF",
    "Schnappatmung",
)

HERE = Path(__file__).resolve().parent
ID_W, ID_H, ID_R = 85.6, 54.0, 3.18      # ID-1 (ISO/IEC 7810), mm
MRZ_PITCH, MRZ_LINE = 2.54, 4.23          # 10 Zeichen/Zoll, 6 Zeilen/Zoll
MRZ_CAP_MM = 2.4                          # Zeichenhöhe OCR-B Grösse 1

FONT_CANDIDATES = {
    "Sans": ["fonts/Frutiger-Roman.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
    "Sans-Bold": ["fonts/Frutiger-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
    "Sign": ["/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"],
    "MRZ": ["fonts/OCR-B.ttf", "fonts/OCRB.ttf", "fonts/ocrb10.ttf", "fonts/OCRB Regular.otf", "fonts/OCRB.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
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
    triage: str = "gruen"
    photo_seed: Optional[tuple[int, int]] = None
    injury: str = ""
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


def allocate_exact(n: int, shares: dict[str, float], r: np.random.Generator) -> list[str]:
    """Exakte Anteile (Methode der grössten Reste), zufällig verteilt."""
    total = sum(shares.values())
    raw = {k: n * v / total for k, v in shares.items()}
    counts = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[: n - sum(counts.values())]:
        counts[k] += 1
    labels = [k for k, c in counts.items() for _ in range(c)]
    r.shuffle(labels)
    return labels


def assign_triage(cards: list, args: argparse.Namespace, r: np.random.Generator) -> None:
    p_green = 1 - args.p_red - args.p_yellow
    if min(args.p_red, args.p_yellow, p_green) < 0:
        raise SystemExit("--p-red + --p-yellow darf 1 nicht überschreiten")
    for card, cat in zip(cards, allocate_exact(len(cards), {
            "rot": args.p_red, "gelb": args.p_yellow, "gruen": p_green}, r)):
        card.triage = cat
    reds = [c for c in cards if c.triage == "rot"]
    # Rest zufällig runden: Erwartungswert stimmt auch bei wenigen Roten
    expected = len(reds) * args.p_red_pattern
    n_pattern = int(expected) + int(r.random() < expected - int(expected))
    for idx in r.choice(len(reds), size=n_pattern, replace=False) if reds else []:
        reds[int(idx)].injury = str(r.choice(INJURY_PATTERNS))


def build_cards(people: pd.DataFrame, args: argparse.Namespace, r: np.random.Generator) -> list[CardPerson]:
    today = date.today()
    cities = people[["city"]].dropna()["city"].unique().tolist() or ["Bern"]
    used_docs: set[str] = set()
    cards = []
    for i, p in enumerate(people.itertuples(index=False)):
        n = args.start + i
        cid = f"{args.prefix}{n:0{args.digits}d}"
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
            origin=str(r.choice(cities)), height_cm=height, doc_number=doc,
            serial=f"{int(r.integers(10, 99))}TRNG{n:09d}", issue_date=issue, expiry=expiry,
            authority=f"Kanton {canton}" if canton else str(p.city), td1=td1, mrz_error=err,
            checks=validate_td1(td1),
            photo_seed=None if args.no_photos else (args.seed, n),
        ))
    assign_triage(cards, args, r)
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


def watermark(c: Canvas, cx: float, cy: float, ci: CI, size: float = 24) -> None:
    c.saveState()
    c.setFillColor(ci.red)
    c.setFillAlpha(0.10)
    c.translate(cx, cy)
    c.rotate(18)
    text(c, 0, 0, "SPECIMEN", "Sans-Bold", size, anchor="c")
    c.restoreState()


def card_shape(c: Canvas, x: float, y: float, fill: Color, ci: CI) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(ci.line)
    c.setLineWidth(0.3)
    c.roundRect(x, y, ID_W * mm, ID_H * mm, ID_R * mm, stroke=1, fill=1)


def label_value(c: Canvas, x, y, label: str, value: str, max_w: float, ci: CI, vsize=7.0) -> None:
    text(c, x, y + 2.9 * mm, label, "Sans", 3.6, ci.grey)
    fit_text(c, x, y, value, max_w, "Sans-Bold", vsize, color=ci.text)


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


def draw_id_front(c: Canvas, x: float, y: float, p: CardPerson, ci: CI) -> None:
    card_shape(c, x, y, ci.card_front_tint, ci)
    top = y + ID_H * mm
    swiss_cross(c, x + 3 * mm, top - 8.2 * mm, 5.2 * mm, ci)
    text(c, x + 9.8 * mm, top - 4.3 * mm,
         "SCHWEIZERISCHE EIDGENOSSENSCHAFT  CONFÉDÉRATION SUISSE", "Sans", 3.5, ci.text)
    text(c, x + 9.8 * mm, top - 5.9 * mm,
         "CONFEDERAZIONE SVIZZERA  CONFEDERAZIUN SVIZRA", "Sans", 3.5, ci.text)
    text(c, x + 9.8 * mm, top - 8.2 * mm,
         "IDENTITÄTSKARTE  CARTE D'IDENTITÉ  CARTA D'IDENTITÀ  IDENTITY CARD", "Sans-Bold", 4.0, ci.red)

    px, py, pw, ph = x + 3 * mm, y + 9 * mm, 23 * mm, 30 * mm
    if p.photo_seed is None:
        photo_placeholder(c, px, py, pw, ph, ci)
    else:
        age = date.today().year - p.dob.year - ((date.today().month, date.today().day) < (p.dob.month, p.dob.day))
        draw_avatar(c, px, py, pw, ph, age, p.gender, np.random.default_rng(p.photo_seed))
        c.setStrokeColor(ci.line)
        c.setLineWidth(0.3)
        c.rect(px, py, pw, ph, stroke=1, fill=0)
    text(c, px + pw / 2, py - 3.2 * mm, f"{p.expiry.year} / {p.doc_number}", "Sans", 4.2, ci.grey, "c")

    fx, fw = x + 29.5 * mm, 52 * mm
    rows = top - 15 * mm
    step = 6.6 * mm
    label_value(c, fx, rows, "Name / Nom / Cognome / Surname", p.last_name.upper(), fw, ci)
    label_value(c, fx, rows - step, "Vorname(n) / Prénom(s) / Nome(i) / Given name(s)", p.first_name, fw, ci)
    y3 = rows - 2 * step
    label_value(c, fx, y3, "Geburtsdatum / Date of birth", fmt_date(p.dob), 23 * mm, ci, 6.5)
    sx = {"m": "M", "f": "F"}.get(p.gender, "X")
    label_value(c, fx + 25 * mm, y3, "Geschlecht / Sex", sx, 9 * mm, ci, 6.5)
    label_value(c, fx + 37 * mm, y3, "Nationalität", "CHE", 15 * mm, ci, 6.5)
    y4 = rows - 3 * step
    label_value(c, fx, y4, "Gültig bis / Date of expiry", fmt_date(p.expiry), 23 * mm, ci, 6.5)
    label_value(c, fx + 25 * mm, y4, "Dokument-Nr. / Document no.", p.doc_number, 27 * mm, ci, 6.5)

    age = (date.today() - p.dob).days // 365
    text(c, fx, y + 6.5 * mm, "Unterschrift / Signature / Firma", "Sans", 3.4, ci.grey)
    if age >= 7:
        fit_text(c, fx + 2 * mm, y + 2.4 * mm, f"{p.first_name.split('-')[0]} {p.last_name}",
                 45 * mm, "Sign", 9, color=HexColor("#23315C"))

    c.saveState()
    c.translate(x + ID_W * mm - 1.6 * mm, y + 12 * mm)
    c.rotate(90)
    text(c, 0, 0, p.serial, "Sans", 4.2, ci.grey)
    c.restoreState()
    watermark(c, x + 55 * mm, y + 22 * mm, ci, 22)


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
    card_shape(c, x, y, ci.card_bg, ci)
    top = y + ID_H * mm
    swiss_cross(c, x + ID_W * mm - 8 * mm, top - 8 * mm, 5 * mm, ci)

    fx, step = x + 4 * mm, 6.4 * mm
    r0 = top - 7.5 * mm
    label_value(c, fx, r0, "Heimatort / Lieu d'origine / Luogo di attinenza", p.origin, 55 * mm, ci, 6.5)
    label_value(c, fx, r0 - step, "Grösse / Taille / Statura / Height", f"{p.height_cm} cm", 25 * mm, ci, 6.5)
    label_value(c, fx + 30 * mm, r0 - step, "Ausgestellt am / Date of issue", fmt_date(p.issue_date),
                25 * mm, ci, 6.5)
    label_value(c, fx, r0 - 2 * step, "Behörde / Autorité / Autorità / Authority", p.authority, 55 * mm, ci, 6.5)
    watermark(c, x + 62 * mm, y + 31 * mm, ci, 18)

    # MRZ-Zone frei von Hintergrund/Wasserzeichen halten
    zone_h = 16.5 * mm
    c.setFillColor(white)
    c.roundRect(x + 0.8 * mm, y + 0.8 * mm, (ID_W - 1.6) * mm, zone_h - 0.8 * mm, (ID_R - 0.8) * mm,
                stroke=0, fill=1)
    draw_mrz(c, x, y, p.td1)


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


def draw_card(c: Canvas, ox: float, oy: float, p: CardPerson, ci: CI, args: argparse.Namespace) -> None:
    """Eine A6-Karte (105 x 148 mm) mit Ursprung unten links."""
    W, H = A6
    x = ox + (W - ID_W * mm) / 2
    y_top = oy + H - 4 * mm
    y = draw_header(c, x, y_top, ID_W * mm, ci, args.logo)

    front_y = y - 2 * mm - ID_H * mm
    draw_id_front(c, x, front_y, p, ci)
    control_scale(c, x - 4.5 * mm, front_y, ci)
    back_y = front_y - 2 * mm - ID_H * mm
    draw_id_back(c, x, back_y, p, ci)

    # Fuss: Text links, QR unten rechts (Modulkante bündig mit ID-Rand)
    qs = args.qr_size * mm
    quiet = qs * 4 / 33
    qx = x + ID_W * mm + quiet - qs
    qy = oy + 2 * mm
    draw_qr(c, qx, qy, qs, p.qr_payload, args.qr_error)

    # Prä-Triage-Feld links neben dem QR, gleiche Höhe wie die QR-Module
    bw, bh = 19 * mm, qs - 2 * quiet
    bx, by = qx + quiet - 2.5 * mm - bw, qy + quiet
    draw_triage(c, bx, by, bw, bh, p.triage)

    tx, ty = x, back_y - 4.6 * mm
    max_w = bx - tx - 2 * mm
    text(c, tx, ty, f"Übungskarte {p.card_id}", "Sans-Bold", 8, ci.text)
    fit_text(c, tx, ty - 3.4 * mm, f"{p.first_name} {p.last_name}, geb. {p.dob:%d.%m.%Y}",
             max_w, "Sans", 6.5, color=ci.text)
    fit_text(c, tx, ty - 6.2 * mm, f"{p.street} {p.house_number}, {p.postcode} {p.city}".replace(" ,", ","),
             max_w, "Sans", 6.5, color=ci.text)
    if p.injury:
        fit_text(c, tx, ty - 9.4 * mm, f"Verletzungsmuster: {p.injury}", max_w, "Sans-Bold", 6.2,
                 color=TRIAGE["rot"][1])
    fit_text(c, tx, ty - 12.2 * mm, "Fiktive Personendaten – kein amtliches Dokument – nur Ausbildung IES NG",
             max_w, "Sans", 4.6, min_size=3.5, color=ci.grey)


def draw_triage(c: Canvas, x: float, y: float, w: float, h: float, cat: str) -> None:
    label, bg, fg = TRIAGE[cat]
    c.setFillColor(bg)
    c.setStrokeColor(HexColor("#1F1F1F"))
    c.setLineWidth(0.4)
    c.roundRect(x, y, w, h, 1.2 * mm, stroke=1, fill=1)
    text(c, x + w / 2, y + h - 3.2 * mm, "PRÄ-TRIAGE", "Sans-Bold", 4.8, fg, "c")
    size = 13.0
    while size > 6 and pdfmetrics.stringWidth(label, "Sans-Bold", size) > w - 2 * mm:
        size -= 0.5
    text(c, x + w / 2, y + 2.6 * mm, label, "Sans-Bold", size, fg, "c")


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
    W, H = A6
    if args.layout == "a6":
        c = Canvas(str(out), pagesize=A6)
        for p in cards:
            draw_card(c, 0, 0, p, ci, args)
            c.showPage()
    else:  # 4 x A6 auf A4 hoch
        c = Canvas(str(out), pagesize=A4)
        cell_h = A4[1] / 2
        slots = [(0, cell_h), (W, cell_h), (0, 0), (W, 0)]
        for i, p in enumerate(cards):
            ox, oy = slots[i % 4]
            oy += (cell_h - H) / 2
            draw_card(c, ox, oy, p, ci, args)
            if args.cut_marks:
                cut_marks(c, ox, oy - (cell_h - H) / 2, W, cell_h)
            if i % 4 == 3:
                c.showPage()
        if len(cards) % 4:
            c.showPage()
    c.setTitle("Ausbildung IES NG – Übungskarten")
    c.setViewerPreference("PrintScaling", "None")  # Druckdialog: tatsächliche Grösse
    c.setAuthor("BABS – Ausbildung IES NG")
    c.save()


def write_key(cards: list[CardPerson], path: Path) -> None:
    cols = ["card_id", "qr_payload", "last_name", "first_name", "gender", "dob", "street", "house_number",
            "postcode", "city", "canton", "origin", "height_cm", "doc_number", "issue_date", "expiry",
            "expired", "triage", "injury_pattern", "mrz_line1", "mrz_line2", "mrz_line3", "mrz_valid", "mrz_error"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for p in cards:
            w.writerow([p.card_id, p.qr_payload, p.last_name, p.first_name, p.gender, p.dob.isoformat(),
                        p.street, p.house_number, p.postcode, p.city, p.canton, p.origin, p.height_cm,
                        p.doc_number, p.issue_date.isoformat(), p.expiry.isoformat(), p.expired,
                        TRIAGE[p.triage][0], p.injury,
                        *p.td1.lines, all(p.checks.values()), p.mrz_error])

# -------------------------
# CLI
# -------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="IES NG Übungskarten (A6) erzeugen", fromfile_prefix_chars="@")
    g = ap.add_argument_group("Karten")
    g.add_argument("-n", "--count", type=int, default=20, help="Anzahl Karten")
    g.add_argument("--start", type=int, default=1, help="erste laufende Nummer")
    g.add_argument("--prefix", default="CHY")
    g.add_argument("--digits", type=int, default=4)
    g.add_argument("--max-number", type=int, default=2000, help="höchste erlaubte Nummer (CHY2000)")
    g.add_argument("--layout", choices=["a6", "a4"], default="a6", help="a6 = 1 Karte/Seite, a4 = 4 Karten/Seite")
    g.add_argument("--no-cut-marks", dest="cut_marks", action="store_false")
    g.add_argument("-o", "--out", default="ies_ng_karten.pdf")
    g.add_argument("--key", default=None, help="Lösungsliste CSV (Default: <out>_loesungen.csv)")
    g.add_argument("--seed", type=int, default=2026)
    g.add_argument("--doc-prefix", default="X", help="1. Zeichen der fiktiven Dokumentnummer")

    g = ap.add_argument_group("QR")
    g.add_argument("--qr-format", default="{id}",
                   help="Payload, {id} = Kartennummer; CHA-Format: \"(dc|{id}|{id})\"")
    g.add_argument("--qr-error", choices=["l", "m", "q"], default="m", help="ECC-Stufe (Version 2)")
    g.add_argument("--qr-size", type=float, default=17.0, help="Kantenlänge inkl. Ruhezone, mm")

    g = ap.add_argument_group("Übungsfälle")
    g.add_argument("--p-invalid-mrz", type=float, default=0.0, help="Anteil MRZ mit falscher Prüfziffer")
    g.add_argument("--p-expired", type=float, default=0.0, help="Anteil abgelaufener Ausweise")
    g.add_argument("--adults-only", action="store_true")
    g.add_argument("--no-photos", action="store_true", help="Platzhalter statt Comic-Passfoto")

    g = ap.add_argument_group("Prä-Triage")
    g.add_argument("--p-red", type=float, default=0.15, help="Anteil Rot")
    g.add_argument("--p-yellow", type=float, default=0.30, help="Anteil Gelb (Rest = Grün)")
    g.add_argument("--p-red-pattern", type=float, default=0.40,
                   help="Anteil Roter mit genau einem Verletzungsmuster")

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
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    last = args.start + args.count - 1
    if args.count <= 0 or args.start < 1 or last > args.max_number:
        raise SystemExit(f"Nummernbereich {args.start}..{last} ausserhalb 1..{args.max_number}")
    fonts = register_fonts({"Sans": args.font_regular, "Sans-Bold": args.font_bold, "MRZ": args.font_mrz})
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
    render_pdf(cards, out, args, CI())
    key = Path(args.key) if args.key else out.with_name(out.stem + "_loesungen.csv")
    write_key(cards, key)
    print(f"{len(cards)} Karten {cards[0].card_id}–{cards[-1].card_id} -> {out} ({args.layout}), Lösungen -> {key}")


if __name__ == "__main__":
    main()
