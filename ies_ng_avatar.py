"""
Comicartige Passfotos (Vektor, reportlab) passend zu Alter und Geschlecht.

Zeichnet in eine Box beliebiger Grösse; intern Einheitenraum 100 x 130 (Passfoto 35 x 45).
Deterministisch über den übergebenen Zufallsgenerator.

Vorschau:  python ies_ng_avatar.py -o avatar_vorschau.pdf
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from reportlab.lib.colors import Color, HexColor
from reportlab.pdfgen.canvas import Canvas

UW, UH = 100.0, 130.0
ZOOM = 1.28
OUTLINE = HexColor("#2B2B2B")
BG = HexColor("#DCE3E9")

# (Haut, Schatten), grob gewichtet nach Bevölkerung CH
SKIN = [
    (("#F6D7C3", "#E2B59B"), 30), (("#EFC7A8", "#D9A784"), 30), (("#E2B08A", "#C98F68"), 16),
    (("#C68A5E", "#A86E45"), 10), (("#9C6640", "#7E4E2E"), 8), (("#6E4429", "#55321C"), 6),
]
HAIR_YOUNG = [("#1E1A18", 22), ("#3B2A20", 30), ("#6A4A30", 22), ("#B58A4C", 12), ("#D8B66A", 8), ("#9C4A22", 6)]
HAIR_GREY = ["#8C8C8C", "#A7A7A7"]
HAIR_WHITE = ["#D9D9D9", "#EDEDED"]
CLOTHES = ["#2F4B7C", "#4F6D7A", "#7A7A7A", "#2E2E2E", "#8E3B46", "#3C6E47", "#C9A227", "#5B5F97",
           "#E8E8E8", "#A65E2E", "#1F6F8B"]
IRIS = ["#4B3621", "#5C4033", "#3B5B7A", "#4E7A4E", "#6B6B3A"]


def _pick(r: np.random.Generator, items_w):
    items, w = zip(*items_w)
    w = np.asarray(w, float)
    return items[int(r.choice(len(items), p=w / w.sum()))]


def _darker(hex_: str, f: float = 0.75) -> Color:
    c = HexColor(hex_)
    return Color(c.red * f, c.green * f, c.blue * f)


class _GrayCanvas:
    """Canvas-Hülle: alle Farben als Graustufen (Passfoto ID 2023 ist schwarz-weiss)."""

    def __init__(self, c: Canvas, contrast: float = 1.15):
        self._c, self._k = c, contrast

    def __getattr__(self, name):
        return getattr(self._c, name)

    def _g(self, col) -> Color:
        col = HexColor(col) if isinstance(col, str) else col
        lum = 0.299 * col.red + 0.587 * col.green + 0.114 * col.blue
        lum = min(1.0, max(0.0, 0.5 + (lum - 0.5) * self._k))
        return Color(lum, lum, lum, alpha=getattr(col, "alpha", 1))

    def setFillColor(self, col, alpha=None):
        self._c.setFillColor(self._g(col), alpha)

    def setStrokeColor(self, col, alpha=None):
        self._c.setStrokeColor(self._g(col), alpha)

    def setFillColorRGB(self, r, g, b, alpha=None):
        self.setFillColor(Color(r, g, b), alpha)

    def setStrokeColorRGB(self, r, g, b, alpha=None):
        self.setStrokeColor(Color(r, g, b), alpha)


@dataclass
class Look:
    age: int
    gender: str
    skin: str
    skin_shade: str
    hair: str
    hair_style: str
    beard: str
    glasses: bool
    clothes: str
    iris: str
    earrings: bool
    face_w: float
    face_h: float


def make_look(age: int, gender: str, r: np.random.Generator) -> Look:
    g = gender if gender in ("m", "f") else str(r.choice(["m", "f"]))
    skin, shade = _pick(r, SKIN)

    # Haarfarbe: ab ca. 40 zunehmend grau, ab 70 meist weiss
    p_grey = float(np.clip((age - 38) / 35, 0, 0.95))
    if r.random() < p_grey:
        hair = str(r.choice(HAIR_WHITE if age > 70 and r.random() < 0.6 else HAIR_GREY))
    else:
        hair = _pick(r, HAIR_YOUNG)
        if age < 6 and r.random() < 0.4:  # Kinder öfter heller
            hair = "#C9A060"

    if age < 2:
        style = "baby"
    elif g == "m":
        p_bald = float(np.clip((age - 30) / 70, 0, 0.45))
        x = r.random()
        if age >= 25 and x < p_bald * 0.5:
            style = "bald"
        elif age >= 25 and x < p_bald:
            style = "receding"
        else:
            style = str(r.choice(["short", "short", "side", "buzz", "curly"] if age >= 12
                                 else ["short", "side", "curly", "bowl"]))
    else:
        opts = ["long", "long", "bob", "bun", "ponytail", "curly_long"] if age < 60 \
            else ["short_f", "short_f", "bob", "bun", "curly_short"]
        if age < 12:
            opts = ["long", "ponytail", "bob", "pigtails"]
        style = str(r.choice(opts))

    beard = "none"
    if g == "m" and age >= 18:
        x = r.random()
        beard = "full" if x < 0.15 else "moustache" if x < 0.23 else "stubble" if x < 0.40 else "none"

    p_glasses = 0.06 if age < 12 else 0.18 if age < 40 else 0.4 if age < 60 else 0.6
    child = age < 12
    return Look(
        age=age, gender=g, skin=skin, skin_shade=shade, hair=hair, hair_style=style, beard=beard,
        glasses=r.random() < p_glasses, clothes=str(r.choice(CLOTHES)), iris=str(r.choice(IRIS)),
        earrings=g == "f" and age >= 10 and r.random() < 0.35,
        face_w=(27.0 if child else 24.0) + r.normal(0, 1.0) + (1.2 if g == "m" and not child else 0),
        face_h=(30.0 if child else 33.0) + r.normal(0, 1.0),
    )


class _Pen:
    """Kleiner Helfer für Pfade im Einheitenraum."""

    def __init__(self, c: Canvas):
        self.c = c

    def fill(self, col, stroke: bool = True, lw: float = 1.4):
        self.c.setFillColor(col if isinstance(col, Color) else HexColor(col))
        self.c.setStrokeColor(OUTLINE)
        self.c.setLineWidth(lw)
        return stroke

    def ellipse(self, cx, cy, rx, ry, col, stroke=True, lw=1.4):
        s = self.fill(col, stroke, lw)
        self.c.ellipse(cx - rx, cy - ry, cx + rx, cy + ry, stroke=int(s), fill=1)

    def path(self, pts_fn, col, stroke=True, lw=1.4, fill=True):
        s = self.fill(col, stroke, lw)
        p = self.c.beginPath()
        pts_fn(p)
        self.c.drawPath(p, stroke=int(s), fill=int(fill))

    def line(self, pts_fn, lw=1.1, col=OUTLINE):
        self.c.setStrokeColor(col if isinstance(col, Color) else HexColor(col))
        self.c.setLineWidth(lw)
        self.c.setLineCap(1)
        p = self.c.beginPath()
        pts_fn(p)
        self.c.drawPath(p, stroke=1, fill=0)


def draw_avatar(c: Canvas, x: float, y: float, w: float, h: float, age: int, gender: str,
                r: np.random.Generator, look: Optional[Look] = None, gray: bool = False) -> Look:
    """Zeichnet ein Porträt in die Box (x, y, w, h) in Punkten. Gibt die verwendeten Merkmale zurück."""
    lk = look or make_look(age, gender, r)
    if gray:
        c = _GrayCanvas(c)
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, y, w, h)
    c.clipPath(clip, stroke=0, fill=0)
    c.translate(x, y)
    c.scale(w / UW, h / UH)
    c.setFillColor(BG)
    c.rect(0, 0, UW, UH, stroke=0, fill=1)

    pen = _Pen(c)
    child = lk.age < 12
    fw, fh = lk.face_w, lk.face_h
    cx = 50.0
    cy = 66.0 if child else 72.0
    # Passbild-Ausschnitt: Kopf füllt ca. 75 % der Bildhöhe
    c.translate(cx, cy + 3)
    c.scale(ZOOM, ZOOM)
    c.translate(-cx, -(cy + 3))
    hair = lk.hair

    _hair_back(pen, lk, cx, cy, fw, fh)
    _torso(pen, lk, cx, cy, fh, child)
    # Hals
    pen.path(lambda p: (p.moveTo(cx - fw * 0.42, cy - fh * 0.6), p.lineTo(cx - fw * 0.45, cy - fh - 12),
                        p.lineTo(cx + fw * 0.45, cy - fh - 12), p.lineTo(cx + fw * 0.42, cy - fh * 0.6),
                        p.close()), lk.skin_shade)
    # Ohren
    for sx in (-1, 1):
        pen.ellipse(cx + sx * (fw + 1.5), cy - 1, 4.2, 6.5, lk.skin)
        if lk.earrings:
            pen.ellipse(cx + sx * (fw + 1.8), cy - 8.5, 1.4, 1.4, "#E0C060", lw=0.6)
    # Gesicht: oben breiter, Kinn je nach Alter
    chin = fh * (0.95 if child else 1.0)
    pen.path(lambda p: (
        p.moveTo(cx - fw, cy + 4),
        p.curveTo(cx - fw, cy + fh + 2, cx + fw, cy + fh + 2, cx + fw, cy + 4),
        p.curveTo(cx + fw, cy - chin * 0.55, cx + fw * 0.45, cy - chin, cx, cy - chin),
        p.curveTo(cx - fw * 0.45, cy - chin, cx - fw, cy - chin * 0.55, cx - fw, cy + 4),
        p.close()), lk.skin)

    _features(pen, lk, cx, cy, fw, fh, child, hair)
    _hair_front(pen, lk, cx, cy, fw, fh)
    _beard(pen, lk, cx, cy, fw, fh)
    if lk.glasses:
        _glasses(pen, lk, cx, cy + (0 if child else 3), fw)
    c.restoreState()
    return lk


def _torso(pen: _Pen, lk: Look, cx, cy, fh, child):
    sw = 36 if child else 46
    top = cy - fh - 6
    pen.path(lambda p: (p.moveTo(cx - sw, -2), p.curveTo(cx - sw, top - 2, cx - sw * 0.6, top + 4, cx - 10, top + 4),
                        p.lineTo(cx + 10, top + 4),
                        p.curveTo(cx + sw * 0.6, top + 4, cx + sw, top - 2, cx + sw, -2), p.close()), lk.clothes)
    if not child and lk.age >= 16:  # Kragen
        pen.path(lambda p: (p.moveTo(cx - 10, top + 4), p.lineTo(cx, top - 8), p.lineTo(cx + 10, top + 4)),
                 lk.skin_shade, lw=1.1)


def _hair_back(pen: _Pen, lk: Look, cx, cy, fw, fh):
    s = lk.hair_style
    col = lk.hair
    if s in ("long", "curly_long"):
        bottom = 14 if lk.age >= 12 else 24
        pen.path(lambda p: (p.moveTo(cx - fw - 7, cy + 6),
                            p.curveTo(cx - fw - 9, cy + fh + 14, cx + fw + 9, cy + fh + 14, cx + fw + 7, cy + 6),
                            p.curveTo(cx + fw + 10, cy - 20, cx + fw + 8, bottom + 6, cx + fw + 4, bottom),
                            p.lineTo(cx - fw - 4, bottom),
                            p.curveTo(cx - fw - 8, bottom + 6, cx - fw - 10, cy - 20, cx - fw - 7, cy + 6),
                            p.close()), col)
    elif s == "bob":
        pen.path(lambda p: (p.moveTo(cx - fw - 6, cy + 6),
                            p.curveTo(cx - fw - 8, cy + fh + 14, cx + fw + 8, cy + fh + 14, cx + fw + 6, cy + 6),
                            p.curveTo(cx + fw + 7, cy - 12, cx + fw + 6, cy - fh * 0.6, cx + fw + 2, cy - fh * 0.62),
                            p.lineTo(cx - fw - 2, cy - fh * 0.62),
                            p.curveTo(cx - fw - 6, cy - fh * 0.6, cx - fw - 7, cy - 12, cx - fw - 6, cy + 6),
                            p.close()), col)
    elif s == "bun":
        pen.ellipse(cx, cy + fh + 4.5, 7, 5.5, col)
    elif s == "pigtails":
        for sx in (-1, 1):
            pen.ellipse(cx + sx * (fw + 8), cy + 2, 6, 11, col)
    elif s == "ponytail":
        pen.ellipse(cx + fw + 4, cy + fh * 0.5, 5, 9, col)


def _hair_front(pen: _Pen, lk: Look, cx, cy, fw, fh):
    s, col = lk.hair_style, lk.hair
    top = cy + fh + 2
    if s == "bald":
        for sx in (-1, 1):
            pen.path(lambda p, sx=sx: (p.moveTo(cx + sx * fw, cy + 12), p.curveTo(cx + sx * (fw + 3), cy + 8,
                     cx + sx * (fw + 2), cy, cx + sx * (fw - 0.5), cy - 3), p.lineTo(cx + sx * (fw - 2), cy + 10),
                     p.close()), col, lw=1.0)
        return
    if s == "baby":
        pen.line(lambda p: (p.moveTo(cx - 3, top - 1), p.curveTo(cx - 2, top + 6, cx + 4, top + 5, cx + 2, top + 1)),
                 lw=1.6, col=col)
        return

    vol = {"buzz": 2.0, "receding": 3.0, "short": 5.0, "side": 5.5, "curly": 7.5, "bowl": 6.0,
           "short_f": 6.5, "curly_short": 8.0}.get(s, 6.0)
    # Haaransatz: Höhe der Stirn
    line_y = {"receding": cy + fh * 0.72, "buzz": cy + fh * 0.62, "bowl": cy + fh * 0.32}.get(s, cy + fh * 0.5)
    side_y = cy + (2 if s in ("long", "curly_long", "bob", "short_f", "curly_short", "bowl") else 8)
    part = {"side": 0.55, "long": 0.3, "bob": 0.2}.get(s, 0.0)

    def cap(p):
        p.moveTo(cx - fw - 1.5, side_y)
        p.curveTo(cx - fw - vol, top + vol, cx + fw + vol, top + vol, cx + fw + 1.5, side_y)
        if s == "receding":  # Geheimratsecken
            p.curveTo(cx + fw * 0.6, line_y + 2, cx + fw * 0.4, line_y - 3, cx, line_y - 1)
            p.curveTo(cx - fw * 0.4, line_y - 3, cx - fw * 0.6, line_y + 2, cx - fw - 1.5, side_y)
        else:
            px = cx + part * fw
            p.curveTo(cx + fw * 0.7, line_y - 4, px + fw * 0.3, line_y - 2, px, line_y + 3)
            p.curveTo(px - fw * 0.5, line_y - 4, cx - fw * 0.8, line_y - 2, cx - fw - 1.5, side_y)
        p.close()

    if s in ("curly", "curly_short", "curly_long"):
        for i in range(9):
            ang = np.pi * (0.06 + 0.88 * i / 8)
            pen.ellipse(cx - np.cos(ang) * (fw + 0.5), side_y + np.sin(ang) * (top + vol * 0.6 - side_y),
                        5.6, 5.6, col, lw=1.0)
    pen.path(cap, col, stroke=s not in ("curly", "curly_short", "curly_long"))
    # Comic-Glanzlicht innerhalb der Haarkappe
    peak = 0.25 * side_y + 0.75 * (top + vol)
    hy = side_y + (peak - side_y) * 0.82
    pen.line(lambda p: (p.moveTo(cx - fw * 0.45, hy - 2.2), p.curveTo(cx - fw * 0.2, hy,
             cx + fw * 0.05, hy, cx + fw * 0.25, hy - 1.2)), lw=1.2, col=_lighten(col))


def _lighten(hex_: str, f: float = 0.35) -> Color:
    c = HexColor(hex_)
    return Color(c.red + (1 - c.red) * f, c.green + (1 - c.green) * f, c.blue + (1 - c.blue) * f)


def _features(pen: _Pen, lk: Look, cx, cy, fw, fh, child, hair):
    ey = cy + (-1 if child else 4)
    ex = fw * (0.42 if child else 0.40)
    erx, ery = (4.6, 3.8) if child else (4.2, 2.8)
    brow_col = lk.hair if lk.hair_style != "baby" else lk.skin_shade
    brow_w = 1.9 if lk.gender == "m" and not child else 1.3
    for sx in (-1, 1):
        exx = cx + sx * ex
        pen.ellipse(exx, ey, erx, ery, "#FFFFFF", lw=1.1)
        pen.ellipse(exx, ey - 0.2, ery * 0.85, ery * 0.85, lk.iris, stroke=False)
        pen.ellipse(exx, ey - 0.2, ery * 0.4, ery * 0.4, "#111111", stroke=False)
        pen.ellipse(exx + 0.8, ey + 0.8, 0.7, 0.7, "#FFFFFF", stroke=False)
        if lk.gender == "f" and lk.age >= 12:  # Wimpern
            pen.line(lambda p, exx=exx, sx=sx: (p.moveTo(exx + sx * erx * 0.8, ey + ery * 0.6),
                     p.lineTo(exx + sx * (erx + 1.6), ey + ery + 0.8)), lw=0.9)
        if lk.age >= 2:
            by = ey + ery + (4.5 if not child else 4.0)
            pen.line(lambda p, exx=exx, sx=sx, by=by: (p.moveTo(exx - sx * erx * 0.9, by - 0.5),
                     p.curveTo(exx - sx * erx * 0.3, by + 1.6, exx + sx * erx * 0.4, by + 1.6,
                               exx + sx * erx * 1.1, by)), lw=brow_w, col=brow_col)
        # Alter: Tränensäcke, Krähenfüsse
        if lk.age >= 50:
            pen.line(lambda p, exx=exx: (p.moveTo(exx - erx * 0.7, ey - ery - 1.2),
                     p.curveTo(exx - 1, ey - ery - 2.4, exx + 1, ey - ery - 2.4, exx + erx * 0.7, ey - ery - 1.2)),
                     lw=0.6, col=_darker(lk.skin_shade, 0.85))
        if lk.age >= 60:
            ox = exx + sx * (erx + 2.2)
            for d in (-1.4, 1.4):
                pen.line(lambda p, ox=ox, d=d, sx=sx: (p.moveTo(ox, ey + d * 0.6), p.lineTo(ox + sx * 2.2, ey + d)),
                         lw=0.6, col=_darker(lk.skin_shade, 0.85))

    # Nase
    ny = cy - (6 if child else 7)
    pen.line(lambda p: (p.moveTo(cx - 0.5, ey - 2), p.curveTo(cx - 2.5, ny + 1, cx - 3.2, ny - 1, cx - 1.6, ny - 1.6),
             p.curveTo(cx - 0.4, ny - 2.2, cx + 1.6, ny - 2.0, cx + 2.6, ny - 1.0)),
             lw=1.0, col=_darker(lk.skin_shade, 0.8))
    # Mund (neutral, leicht)
    my = cy - fh * (0.52 if child else 0.55)
    mw = 5.0 if child else 6.5
    if lk.gender == "f" and lk.age >= 14:
        pen.path(lambda p: (p.moveTo(cx - mw, my + 0.5), p.curveTo(cx - mw * 0.4, my + 2.4, cx + mw * 0.4, my + 2.4,
                 cx + mw, my + 0.5), p.curveTo(cx + mw * 0.4, my - 2.2, cx - mw * 0.4, my - 2.2, cx - mw, my + 0.5),
                 p.close()), "#C46A6A", lw=0.8)
    pen.line(lambda p: (p.moveTo(cx - mw, my + 0.5), p.curveTo(cx - mw * 0.3, my - 0.6, cx + mw * 0.3, my - 0.6,
             cx + mw, my + 0.5)), lw=1.1)
    # Wangen bei Kindern, Falten bei Älteren
    if child:
        for sx in (-1, 1):
            pen.ellipse(cx + sx * fw * 0.62, cy - fh * 0.3, 4, 2.6, Color(0.95, 0.55, 0.55, alpha=0.35), stroke=False)
    if lk.age >= 45:
        for sx in (-1, 1):
            pen.line(lambda p, sx=sx: (p.moveTo(cx + sx * 4.5, ny - 1), p.curveTo(cx + sx * 7.5, my + 1, cx + sx * 8,
                     my - 1, cx + sx * 8.5, my - 2.5)), lw=0.7, col=_darker(lk.skin_shade, 0.85))
    if lk.age >= 40:
        n = 1 if lk.age < 60 else 2 if lk.age < 75 else 3
        for i in range(n):
            fy = cy + fh * 0.5 + i * 2.6
            pen.line(lambda p, fy=fy: (p.moveTo(cx - fw * 0.45, fy), p.curveTo(cx - fw * 0.15, fy + 1, cx + fw * 0.15,
                     fy + 1, cx + fw * 0.45, fy)), lw=0.6, col=_darker(lk.skin_shade, 0.85))


def _beard(pen: _Pen, lk: Look, cx, cy, fw, fh):
    if lk.beard == "none":
        return
    col = lk.hair if lk.hair_style != "bald" or lk.age < 50 else HAIR_GREY[0]
    my = cy - fh * 0.55
    if lk.beard == "stubble":
        c = HexColor(col)
        stub = Color(c.red, c.green, c.blue, alpha=0.35)
        pen.path(lambda p: (p.moveTo(cx - fw + 1, cy - 6), p.curveTo(cx - fw, cy - fh * 0.8, cx - fw * 0.4, cy - fh,
                 cx, cy - fh), p.curveTo(cx + fw * 0.4, cy - fh, cx + fw, cy - fh * 0.8, cx + fw - 1, cy - 6),
                 p.curveTo(cx + fw * 0.5, my + 6, cx - fw * 0.5, my + 6, cx - fw + 1, cy - 6), p.close()),
                 stub, stroke=False)
        return
    if lk.beard in ("moustache", "full"):
        pen.path(lambda p: (p.moveTo(cx - 8, my + 1.5), p.curveTo(cx - 5, my + 6, cx + 5, my + 6, cx + 8, my + 1.5),
                 p.curveTo(cx + 4, my + 3, cx - 4, my + 3, cx - 8, my + 1.5), p.close()), col, lw=1.0)
    if lk.beard == "full":
        pen.path(lambda p: (p.moveTo(cx - fw, cy - 2), p.curveTo(cx - fw, cy - fh - 3, cx - fw * 0.4, cy - fh - 6,
                 cx, cy - fh - 6), p.curveTo(cx + fw * 0.4, cy - fh - 6, cx + fw, cy - fh - 3, cx + fw, cy - 2),
                 p.curveTo(cx + fw * 0.6, my - 1, cx + 7, my - 3, cx, my - 3.5),
                 p.curveTo(cx - 7, my - 3, cx - fw * 0.6, my - 1, cx - fw, cy - 2), p.close()), col, lw=1.2)


def _glasses(pen: _Pen, lk: Look, cx, ey, fw):
    ex = fw * 0.40
    frame = "#2B2B2B" if lk.age < 60 or lk.gender == "m" else "#7A4A2A"
    pen.c.setFillColor(Color(1, 1, 1, alpha=0.12))
    pen.c.setStrokeColor(HexColor(frame))
    pen.c.setLineWidth(1.3)
    for sx in (-1, 1):
        pen.c.roundRect(cx + sx * ex - 6.5, ey - 4.6, 13, 9.2, 3, stroke=1, fill=1)
    pen.line(lambda p: (p.moveTo(cx - ex + 6.5, ey + 1), p.curveTo(cx - 2, ey + 3, cx + 2, ey + 3, cx + ex - 6.5, ey + 1)),
             lw=1.2, col=frame)
    for sx in (-1, 1):
        pen.line(lambda p, sx=sx: (p.moveTo(cx + sx * (ex + 6.5), ey + 2), p.lineTo(cx + sx * (fw + 1), ey + 3)),
                 lw=1.2, col=frame)


if __name__ == "__main__":
    import argparse

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    ap = argparse.ArgumentParser(description="Vorschau Comic-Passfotos")
    ap.add_argument("-o", "--out", default="avatar_vorschau.pdf")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    ages = [0, 3, 6, 9, 13, 17, 22, 30, 40, 50, 60, 70, 80, 90]
    c = Canvas(args.out, pagesize=A4)
    bw, bh = 23 * mm, 30 * mm
    rng = np.random.default_rng(args.seed)
    for page in range(2):
        for i, age in enumerate(ages):
            for j, g in enumerate(["m", "f", "m", "f"] if page == 0 else ["f", "m", "f", "m"]):
                col, row = j + (4 if i >= 7 else 0), i % 7
                x = 8 * mm + col * (bw + 1.2 * mm)
                y = A4[1] - 14 * mm - (row + 1) * (bh + 9 * mm)
                draw_avatar(c, x, y, bw, bh, age, g, rng)
                c.setFont("Helvetica", 6)
                c.drawString(x, y - 3 * mm, f"{age} J., {g}")
        c.showPage()
    c.save()
    print(f"-> {args.out}")
