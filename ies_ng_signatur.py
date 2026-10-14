"""
Handschriftliche Unterschriften (Vektor, reportlab), individuell je Person.

Pro Person deterministisch über den übergebenen Zufallsgenerator:
Schriftform (Handschrift-Schrift), Schreibweise (Vorname Name, V. Name, nur Name, Kürzel ...),
Grösse, Neigung, schräge/wellige Grundlinie, Zittern je Buchstabe, Tinte und Schnörkel.
Kinder (7–13 Jahre) schreiben den vollen Namen in Druckschrift, gerade und ohne Schnörkel.

Schriften: eigene Handschrift-TTF/OTF in fonts/handschrift/ (z. B. OFL-Schriften), sonst
die unter Windows mitgelieferten Script-Schriften; ohne beides die Ersatzschrift 'Sign'.

Vorschau:  python ies_ng_signatur.py -o signatur_vorschau.pdf
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

HERE = Path(__file__).resolve().parent
OWN_DIR = HERE / "fonts" / "handschrift"
WINFONTS = Path("C:/Windows/Fonts")


@dataclass(frozen=True)
class HandFont:
    file: str
    cursive: bool      # verbundene Schreibschrift (sonst Druckschrift)
    scale: float       # Grössenausgleich (optisch gleiche Höhe)
    jitter: float      # erlaubtes Zittern je Buchstabe (verbundene Schriften wenig)


WINDOWS_FONTS = (
    HandFont("segoesc.ttf", True, 0.80, 0.5),     # Segoe Script
    HandFont("LHANDW.TTF", True, 0.78, 0.4),      # Lucida Handwriting
    HandFont("BRUSHSCI.TTF", True, 1.10, 0.4),    # Brush Script
    HandFont("MISTRAL.TTF", True, 1.05, 0.6),
    HandFont("FRSCRIPT.TTF", True, 1.15, 0.3),    # French Script
    HandFont("KUNSTLER.TTF", True, 1.20, 0.3),
    HandFont("VIVALDII.TTF", True, 1.05, 0.3),
    HandFont("RAGE.TTF", True, 1.00, 0.4),
    HandFont("PRISTINA.TTF", True, 1.05, 0.6),
    HandFont("Inkfree.ttf", False, 0.95, 1.0),
    HandFont("segoepr.ttf", False, 0.85, 1.0),    # Segoe Print
)

# Tinte: (Farbe, Gewicht) – Kugelschreiber blau/schwarz, selten Filzstift
INKS = [((0.10, 0.17, 0.42), 40), ((0.07, 0.10, 0.22), 25), ((0.08, 0.08, 0.10), 25),
        ((0.16, 0.24, 0.55), 8), ((0.20, 0.12, 0.35), 2)]


@dataclass
class _Reg:
    name: str
    font: HandFont


_REGISTERED: list[_Reg] = []


def register_hand_fonts() -> list[str]:
    """Handschrift-Schriften einmalig registrieren; liefert die reportlab-Namen."""
    if _REGISTERED:
        return [r.name for r in _REGISTERED]
    cands: list[tuple[Path, HandFont]] = []
    if OWN_DIR.is_dir():
        for p in sorted(OWN_DIR.iterdir()):
            if p.suffix.lower() in (".ttf", ".otf"):
                print_style = "print" in p.stem.lower() or "druck" in p.stem.lower()
                cands.append((p, HandFont(p.name, not print_style, 1.0, 0.4 if not print_style else 1.0)))
    for f in WINDOWS_FONTS:
        if (WINFONTS / f.file).is_file():
            cands.append((WINFONTS / f.file, f))
    for i, (path, hf) in enumerate(cands):
        if path.suffix.lower() == ".otf":
            from ies_ng_karten import otf_to_ttf
            path = otf_to_ttf(path)
        name = f"Hand{i}"
        try:
            pdfmetrics.registerFont(TTFont(name, str(path)))
        except Exception:  # noqa: BLE001  (z. B. CFF-OTF ohne fontTools, defekte Datei)
            continue
        _REGISTERED.append(_Reg(name, hf))
    return [r.name for r in _REGISTERED]


def _covers(font_name: str, s: str) -> bool:
    face = pdfmetrics.getFont(font_name).face
    cmap = getattr(face, "charToGlyph", None)
    return cmap is None or all(ord(ch) in cmap for ch in s if not ch.isspace())


def _wchoice(rng: np.random.Generator, items: list, weights: list[float]):
    w = np.asarray(weights, float)
    return items[int(rng.choice(len(items), p=w / w.sum()))]


def signature_text(first: str, last: str, rng: np.random.Generator, child: bool) -> tuple[str, bool]:
    """Schreibweise; zweiter Wert True, wenn der Name abgekürzt ausläuft (-> Wellenlinie)."""
    first = first.split()[0]                     # nur erster Vorname
    fi = first[0]
    if child:
        return f"{first} {last}", False
    last_main = last.split()[-1] if " " in last and rng.random() < 0.5 else last
    variants = [
        (f"{first} {last}", 30), (f"{fi}. {last}", 22), (last, 16), (f"{first} {last_main}", 8),
        (f"{fi}.{last[0]}.", 4), (f"{fi}{last}", 6), (f"{first[:2]} {last}", 4),
    ]
    if len(last_main) > 5:
        variants.append((f"{fi}. {last_main[:int(rng.integers(3, 5))]}", 10))
    s = _wchoice(rng, [v for v, _ in variants], [w for _, w in variants])
    return s, len(last_main) > 5 and not s.endswith(last_main) and len(s) > 4


def draw_signature(c: Canvas, x: float, y: float, max_w: float, first: str, last: str,
                   rng: np.random.Generator, age: int = 30, fallback: str = "Sign",
                   max_h: Optional[float] = None) -> None:
    """Unterschrift mit linker Grundlinie bei (x, y), höchstens max_w breit."""
    child = age < 14
    s, trails = signature_text(first, last, rng, child)
    regs = [r for r in _REGISTERED if r.font.cursive != child and _covers(r.name, s)]
    if not regs:
        regs = [r for r in _REGISTERED if _covers(r.name, s)]
    reg = regs[int(rng.integers(len(regs)))] if regs else None
    font = reg.name if reg else fallback
    hf = reg.font if reg else HandFont("", True, 1.0, 0.6)

    size = float(rng.uniform(8.5, 12.5)) * hf.scale * (0.9 if child else 1.0)
    slant = 0.0 if child else float(rng.normal(6, 7))           # Grad, Rechts-/Linksneigung
    tilt = float(rng.normal(1.5, 2.5)) if not child else float(rng.normal(0, 1))
    wave_a, wave_f = float(rng.uniform(0, 0.06)) * size, float(rng.uniform(0.8, 2.2))
    track = float(rng.uniform(-0.04, 0.06)) * size * (0 if hf.cursive else 1)
    jit = hf.jitter * (1.4 if child else 1.0)
    shrink = float(rng.uniform(0.0, 0.25)) if not child else 0.0  # Schrift wird zum Ende kleiner

    # Breite vorab, dann auf max_w einpassen
    widths = [pdfmetrics.stringWidth(ch, font, size) + track for ch in s]
    total = sum(w * (1 - shrink * i / max(len(s), 1)) for i, w in enumerate(widths))
    k = min(1.0, max_w / max(total, 1e-6) * 0.92)
    if max_h:
        k = min(k, max_h / (size * 1.1))
    size, track, wave_a = size * k, track * k, wave_a * k

    ink_rgb = _wchoice(rng, [i for i, _ in INKS], [w for _, w in INKS])
    ink = Color(*ink_rgb, alpha=float(rng.uniform(0.82, 0.97)))

    c.saveState()
    c.translate(x, y)
    c.rotate(tilt)
    c.transform(1, 0, math.tan(math.radians(slant)), 1, 0, 0)   # Neigung (horizontaler Shear)
    c.setFillColor(ink)
    c.setStrokeColor(ink)

    cx, phase = 0.0, float(rng.uniform(0, 2 * math.pi))
    pts: list[tuple[float, float]] = []
    for i, ch in enumerate(s):
        fs = size * (1 - shrink * i / max(len(s), 1)) * float(1 + rng.normal(0, 0.03 * jit))
        dy = wave_a * math.sin(phase + wave_f * cx / max(size, 1e-6)) + float(rng.normal(0, 0.025 * jit)) * size
        if i == 0 and not child:
            fs *= float(rng.uniform(1.05, 1.3))   # betonter Anfangsbuchstabe
        c.saveState()
        c.translate(cx, dy)
        c.rotate(float(rng.normal(0, 2.5 * jit)))
        c.setFont(font, fs)
        c.drawString(0, 0, ch)
        c.restoreState()
        pts.append((cx, dy))
        cx += pdfmetrics.stringWidth(ch, font, fs) + track * (1 + float(rng.normal(0, 0.3)))

    if trails:
        _trail(c, cx, size, rng)
    elif not child:
        _flourish(c, cx, size, pts, rng)
    c.restoreState()


def _trail(c: Canvas, x0: float, size: float, rng: np.random.Generator) -> None:
    """Auslaufende Wellenlinie nach abgekürztem Namen (flacher werdend)."""
    c.setLineCap(1)
    c.setLineJoin(1)
    c.setLineWidth(float(rng.uniform(0.35, 0.6)) * size / 10)
    length, waves = size * float(rng.uniform(1.2, 2.6)), int(rng.integers(2, 5))
    amp, y = size * float(rng.uniform(0.12, 0.22)), size * float(rng.uniform(0.05, 0.2))
    p = c.beginPath()
    p.moveTo(x0 - size * 0.05, y)
    n = 6 * waves
    for i in range(1, n + 1):
        t = i / n
        p.lineTo(x0 + length * t, y * (1 - t) + amp * (1 - 0.8 * t) * math.sin(2 * math.pi * waves * t))
    c.drawPath(p, stroke=1, fill=0)


def _flourish(c: Canvas, width: float, size: float, pts: list[tuple[float, float]],
              rng: np.random.Generator) -> None:
    """Schnörkel: Unterstrich, Rückschwung, Endhaken oder Punkt – oder keiner."""
    kind = _wchoice(rng, ["none", "under", "swoosh", "tail", "double", "dot"], [30, 22, 20, 15, 6, 7])
    if kind == "none":
        return
    c.setLineCap(1)
    c.setLineJoin(1)
    lw = float(rng.uniform(0.35, 0.65)) * size / 10
    c.setLineWidth(lw)
    r = lambda a, b: float(rng.uniform(a, b))  # noqa: E731
    p = c.beginPath()
    if kind in ("under", "double"):
        y0 = -size * r(0.22, 0.38)
        x0, x1 = width * r(-0.05, 0.15), width * r(0.85, 1.12)
        p.moveTo(x0, y0 + size * r(-0.05, 0.08))
        p.curveTo(width * r(0.3, 0.45), y0 - size * r(0.05, 0.18), width * r(0.6, 0.75),
                  y0 + size * r(-0.05, 0.12), x1, y0 + size * r(0.0, 0.2))
        if kind == "double":
            p.moveTo(x0 + width * 0.1, y0 - size * 0.14)
            p.curveTo(width * 0.4, y0 - size * 0.24, width * 0.7, y0 - size * 0.08, x1 * 0.9, y0 - size * 0.1)
    elif kind == "swoosh":       # vom Ende zurück unter den Namen
        ex, ey = pts[-1][0] + size * 0.25, pts[-1][1]
        p.moveTo(ex, ey + size * 0.05)
        p.curveTo(ex + size * r(0.3, 0.7), ey - size * r(0.1, 0.3), ex + size * r(0.1, 0.4),
                  -size * r(0.45, 0.6), width * r(0.45, 0.7), -size * r(0.3, 0.45))
        p.curveTo(width * r(0.2, 0.4), -size * r(0.2, 0.35), width * r(-0.05, 0.1),
                  -size * r(0.15, 0.3), width * r(-0.1, 0.05), -size * r(0.05, 0.2))
    elif kind == "tail":         # Endhaken nach rechts oben
        ex = width + size * 0.05
        p.moveTo(ex - size * 0.15, size * r(0.0, 0.1))
        p.curveTo(ex + size * r(0.1, 0.3), -size * r(0.1, 0.25), ex + size * r(0.4, 0.7),
                  size * r(-0.05, 0.1), ex + size * r(0.6, 1.0), size * r(0.25, 0.55))
    else:                        # Punkt hinter dem Namen
        c.circle(width + size * r(0.15, 0.35), size * r(0.0, 0.1), lw * 0.9, stroke=0, fill=1)
        return
    c.drawPath(p, stroke=1, fill=0)


# -------------------------
# Vorschau
# -------------------------

def _preview(out: str, n: int = 40, seed: int = 1) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    names = register_hand_fonts()
    print(f"{len(names)} Handschrift-Schriften: {', '.join(r.font.file for r in _REGISTERED) or 'keine'}")
    if "Sign" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Sign", "C:/Windows/Fonts/timesi.ttf"))
    people = [("Anna", "Müller", 34), ("Hans-Peter", "Schneider", 61), ("Lea", "Brunner", 9),
              ("François", "Rochat", 47), ("Giulia", "Bernasconi", 23), ("Noah", "Ammann", 12),
              ("Elisabeth", "von Gunten", 80), ("Mehmet", "Yilmaz", 41), ("Ursula", "Zbinden", 72),
              ("Luca", "Keller", 17)]
    c = Canvas(out, pagesize=A4)
    c.setFont("Helvetica", 6)
    for i in range(n):
        first, last, age = people[i % len(people)]
        col, row = i % 2, i // 2
        x, y = 15 * mm + col * 95 * mm, A4[1] - 20 * mm - row * 13 * mm
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(x, y + 6 * mm, f"{first} {last} ({age})")
        draw_signature(c, x + 2 * mm, y, 45 * mm, first, last, np.random.default_rng((seed, i)), age)
    c.save()
    print(f"-> {out}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Vorschau individueller Unterschriften")
    ap.add_argument("-o", "--out", default="signatur_vorschau.pdf")
    ap.add_argument("-n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    _preview(a.out, a.n, a.seed)
