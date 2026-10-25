"""
Comic-Szene «Auffindesituation»: ganze Figur in Haltung, Mimik und mit Verletzungsmarken.

Die Figur übernimmt das Aussehen (Haut, Haare, Kleidung, Brille, Bart) aus ies_ng_avatar.make_look,
damit sie zum Passfoto passt. Nicht drastisch dargestellt (Ausbildung).

Vorschau aller Fälle:  python ies_ng_szene.py -o szenen_vorschau.pdf
"""
from __future__ import annotations

import math

from reportlab.lib.colors import Color, HexColor
from reportlab.pdfgen.canvas import Canvas

from ies_ng_avatar import Look

SW, SH = 160.0, 100.0          # Szenen-Einheitenraum
OUTLINE = HexColor("#2B2B2B")
PANTS = ["#2E3A4F", "#3B3B3B", "#4A5A3C", "#5A4632", "#1F2A44", "#6B6B6B"]
BLOOD, BLOOD_DARK = HexColor("#C8102E"), HexColor("#8E0E1F")

# Körperstellen (Figurkoordinaten stehend: Füsse y=0, Kopf ca. y=90; _l = Bildseite links)
ORTE_STEHEND = {
    "kopf": (0, 97), "stirn": (0, 95), "gesicht": (0, 88), "mund": (0, 85.5),
    "schulter_l": (-12, 74), "schulter_r": (12, 74), "thorax": (0, 66), "abdomen": (0, 55),
    "becken": (0, 47), "leiste": (-6, 44),
    "oberarm_l": (-15.5, 66), "unterarm_l": (-18, 55), "hand_l": (-19.5, 46), "arm_l": (-16.5, 60),
    "oberarm_r": (15.5, 66), "unterarm_r": (18, 55), "hand_r": (19.5, 46), "arm_r": (16.5, 60),
    "oberschenkel_l": (-6.5, 36), "oberschenkel_r": (6.5, 36), "knie_l": (-6.5, 26), "knie_r": (6.5, 26),
    "bein_l": (-6.8, 16), "bein_r": (6.8, 16), "fuss_l": (-7.5, 4), "fuss_r": (7.5, 4),
    "beine": (0, 22), "koerper": (0, 55),
}
# Sitzend (auf Kiste/Stufe): Oberkörper 20 tiefer, Unterschenkel senkrecht
_SIT_DY = -20.0
_SIT_LEGS = {"oberschenkel_l": (-7, 26), "oberschenkel_r": (7, 26), "knie_l": (-7.5, 22), "knie_r": (7.5, 22),
             "bein_l": (-7.8, 13), "bein_r": (7.8, 13), "fuss_l": (-8.5, 4), "fuss_r": (8.5, 4), "beine": (0, 14)}


def orte(pose: str) -> dict:
    if pose != "sitzend":
        return dict(ORTE_STEHEND)
    o = {k: (x, y + _SIT_DY) for k, (x, y) in ORTE_STEHEND.items()}
    o.update(_SIT_LEGS)
    return o


def _col(c) -> Color:
    return HexColor(c) if isinstance(c, str) else c


def _mix(a, b, t: float) -> Color:
    a, b = _col(a), _col(b)
    return Color(a.red + (b.red - a.red) * t, a.green + (b.green - a.green) * t, a.blue + (b.blue - a.blue) * t)


class _P:
    """Zeichenhelfer (Einheitenraum)."""

    def __init__(self, c: Canvas):
        self.c = c

    def fill(self, col, alpha: float = 1.0):
        self.c.setFillColor(_col(col))
        self.c.setFillAlpha(alpha)

    def stroke(self, col, lw: float, alpha: float = 1.0):
        self.c.setStrokeColor(_col(col))
        self.c.setLineWidth(lw)
        self.c.setStrokeAlpha(alpha)
        self.c.setLineCap(1)
        self.c.setLineJoin(1)

    def ell(self, x, y, rx, ry, col, outline=True, lw=1.1, alpha=1.0):
        self.fill(col, alpha)
        self.stroke(OUTLINE, lw)
        self.c.ellipse(x - rx, y - ry, x + rx, y + ry, stroke=int(outline), fill=1)
        self.c.setFillAlpha(1)

    def poly(self, pts, col, outline=True, lw=1.1, alpha=1.0, close=True):
        self.fill(col, alpha)
        self.stroke(OUTLINE, lw)
        p = self.c.beginPath()
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        if close:
            p.close()
        self.c.drawPath(p, stroke=int(outline), fill=int(close))
        self.c.setFillAlpha(1)

    def line(self, pts, col=OUTLINE, lw=1.0, alpha=1.0):
        self.stroke(col, lw, alpha)
        p = self.c.beginPath()
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        self.c.drawPath(p, stroke=1, fill=0)
        self.c.setStrokeAlpha(1)

    def curve(self, p0, p1, p2, p3, col=OUTLINE, lw=1.0):
        self.stroke(col, lw)
        p = self.c.beginPath()
        p.moveTo(*p0)
        p.curveTo(*p1, *p2, *p3)
        self.c.drawPath(p, stroke=1, fill=0)

    def limb(self, pts, width, col):
        """Gliedmasse mit Comic-Kontur."""
        self.line(pts, OUTLINE, width + 2.0)
        self.line(pts, col, width)

    def rrect(self, x, y, w, h, r, col, outline=True, lw=1.1):
        self.fill(col)
        self.stroke(OUTLINE, lw)
        self.c.roundRect(x, y, w, h, r, stroke=int(outline), fill=1)

    def drop(self, x, y, s, col=BLOOD):
        self.fill(col)
        p = self.c.beginPath()
        p.moveTo(x, y + 1.6 * s)
        p.curveTo(x + 0.9 * s, y + 0.4 * s, x + 0.9 * s, y - 0.9 * s, x, y - 0.9 * s)
        p.curveTo(x - 0.9 * s, y - 0.9 * s, x - 0.9 * s, y + 0.4 * s, x, y + 1.6 * s)
        self.c.drawPath(p, stroke=0, fill=1)


# -------------------------
# Umgebung
# -------------------------

def _env(p: _P, env: str, floor: float, lying: bool, top: float = SH) -> None:
    c = p.c
    up = top - SH  # zusätzliche Höhe bei höheren Boxen (Rauch o. Ä. oben ausrichten)
    sky = {"innen": "#EDE6DA", "brand": "#D9D1C7", "verkehr": "#DDEAF3", "truemmer": "#E3E2DC",
           "aussen": "#DCEBF5"}[env]
    ground = {"innen": "#C9A47E", "brand": "#9C928A", "verkehr": "#767676", "truemmer": "#A99D8C",
              "aussen": "#A7C882"}[env]
    p.fill(sky)
    c.rect(0, floor, SW, top - floor, stroke=0, fill=1)
    p.fill(ground)
    c.rect(0, 0, SW, floor, stroke=0, fill=1)

    if env == "innen":
        for i in range(1, 9):  # Dielen
            y = floor * i / 9 if lying else None
            if lying:
                p.line([(0, y), (SW, y)], _mix(ground, "#000000", 0.18), 0.5)
            else:
                p.line([(i * 18, 0), (i * 18 - 6, floor)], _mix(ground, "#000000", 0.18), 0.5)
        if not lying:
            p.rrect(122, floor, 24, 46, 1.5, "#B9946B")
            p.ell(141, floor + 22, 1.2, 1.2, "#6B5235", outline=False)
    elif env == "brand":
        for x, y, r in ((20, 92, 14), (45, 96, 12), (75, 94, 16), (110, 97, 13), (140, 92, 15), (128, 82, 10)):
            p.ell(x, y + up, r * 1.3, r * 0.8, "#6E6A66", outline=False, alpha=0.35)
        fx = 140 if not lying else 145
        for dx, h, col in ((-6, 16, "#F28C28"), (0, 22, "#E8541E"), (6, 14, "#F28C28"), (0, 11, "#FFD24A")):
            base = floor if not lying else 6
            p.poly([(fx + dx - 5, base), (fx + dx, base + h), (fx + dx + 5, base)], col, outline=False)
    elif env == "verkehr":
        if lying:
            for x in range(4, int(SW), 26):
                p.rrect(x, floor * 0.5 - 1.2, 14, 2.4, 1, "#F2F2F2", outline=False)
            p.rrect(118, floor - 10, 44, 18, 4, "#B5382F")
            p.rrect(124, floor - 6, 14, 10, 2, "#CFE3F0")
        else:
            for x in range(4, int(SW), 26):
                p.rrect(x, floor * 0.45, 14, 2.2, 1, "#F2F2F2", outline=False)
            p.rrect(112, floor + 2, 46, 15, 4, "#B5382F")
            p.poly([(120, floor + 17), (126, floor + 27), (146, floor + 27), (152, floor + 17)], "#B5382F")
            p.poly([(124, floor + 18), (128, floor + 25), (136, floor + 25), (136, floor + 18)], "#CFE3F0")
            for wx in (122, 148):
                p.ell(wx, floor + 2, 5, 5, "#2B2B2B")
                p.ell(wx, floor + 2, 2, 2, "#9A9A9A", outline=False)
    elif env == "truemmer":
        p.poly([(0, floor), (0, floor + 40), (14, floor + 46), (22, floor + 30), (30, floor + 34), (34, floor)],
               "#B8B2A6")
        for x, y, s, col in ((40, 4, 7, "#8F877A"), (128, 6, 9, "#9C9487"), (146, 14, 6, "#7F786C"),
                             (10, 10, 5, "#A39B8E"), (112, 2, 5, "#8A8275")):
            p.poly([(x - s, y), (x - s * 0.4, y + s), (x + s * 0.8, y + s * 0.7), (x + s, y - s * 0.2)], col)
    elif env == "aussen":
        if lying:
            for x, y in ((12, 10), (30, 64), (140, 70), (150, 12), (100, 6), (60, 72)):
                p.ell(x, y, 1.6, 1.6, "#F5F5F5", outline=False)
                p.ell(x, y, 0.7, 0.7, "#F2C230", outline=False)
        else:
            p.rrect(138, floor, 5, 22, 1, "#7A5634")
            p.ell(140.5, floor + 30, 13, 12, "#5F9445")


# -------------------------
# Figur
# -------------------------

def _pants(lk: Look) -> str:
    return PANTS[sum(map(ord, lk.clothes + lk.hair)) % len(PANTS)]


def _figure(p: _P, lk: Look, pose: str, mimik: str) -> None:
    """Figur in Figurkoordinaten (Füsse y=0). Sitzend: Oberkörper abgesenkt, Beine gespreizt."""
    child = lk.age < 12
    hr = 12.0 if child else 10.0
    dy = _SIT_DY if pose == "sitzend" else 0.0
    hy = 80 + hr + dy                     # Kopfmitte
    skin = _mix(lk.skin, "#9AA3A8", 0.45) if mimik == "leblos" else _col(lk.skin)
    clothes, pants = _col(lk.clothes), _col(_pants(lk))
    long_hair = lk.hair_style in ("long", "curly_long", "bob", "pigtails", "ponytail")

    # Haare hinten
    if long_hair:
        bottom = hy - (hr * 1.5 if lk.hair_style in ("long", "curly_long") else hr * 0.6)
        p.rrect(-hr - 2.6, bottom, 2 * hr + 5.2, hy + hr + 2.5 - bottom, hr * 0.9, lk.hair)
    if lk.hair_style == "bun":
        p.ell(0, hy + hr + 3, 4.2, 3.6, lk.hair)
    if lk.hair_style == "pigtails":
        for sx in (-1, 1):
            p.ell(sx * (hr + 3), hy - 1, 3, 5.5, lk.hair)

    # Beine + Schuhe
    if pose == "sitzend":
        p.rrect(-22, 0, 44, 26, 2, "#8A7A66")            # Kiste / Stufe
        p.line([(-22, 13), (22, 13)], _mix("#8A7A66", "#000000", 0.25), 0.6)
        for sx in (-1, 1):
            p.limb([(sx * 7.8, 22), (sx * 8.2, 6)], 8.5, pants)       # Unterschenkel
            p.ell(sx * 9, 3, 6, 3, "#2A2A2A")
            p.rrect(sx * 7.5 - 5.5, 20, 11, 10, 4, pants)             # Oberschenkel (verkürzt)
    else:
        for sx in (-1, 1):
            p.limb([(sx * 6, 46), (sx * 7, 6)], 8.5, pants)
            p.ell(sx * 8, 3, 6, 3, "#2A2A2A")

    # Rumpf
    p.rrect(-14, 44 + dy, 28, 35, 6, clothes)
    p.rrect(-13, 42 + dy, 26, 9, 3, pants)
    # Arme + Hände
    for sx in (-1, 1):
        p.limb([(sx * 12.5, 74 + dy), (sx * 17, 60 + dy), (sx * 19.5, 49 + dy)], 6.5, clothes)
        p.ell(sx * 19.8, 46 + dy, 3.3, 3.3, skin)
    # Hals + Kopf
    p.rrect(-3.5, 77 + dy, 7, 6, 1, skin)
    p.ell(0, hy, hr, hr * 1.05, skin)

    _face(p, lk, mimik, hy, hr)
    _hair_front(p, lk, hy, hr, child)
    if lk.beard == "full":
        p.poly([(-hr * 0.9, hy - hr * 0.1), (-hr * 0.6, hy - hr * 1.0), (0, hy - hr * 1.25),
                (hr * 0.6, hy - hr * 1.0), (hr * 0.9, hy - hr * 0.1), (hr * 0.4, hy - hr * 0.45),
                (-hr * 0.4, hy - hr * 0.45)], lk.hair, lw=0.8)
    elif lk.beard == "moustache":
        p.poly([(-hr * 0.4, hy - hr * 0.42), (0, hy - hr * 0.3), (hr * 0.4, hy - hr * 0.42), (0, hy - hr * 0.5)],
               lk.hair, lw=0.6)
    if lk.glasses:
        for sx in (-1, 1):
            p.c.setFillAlpha(0)
            p.stroke("#2B2B2B", 0.8)
            p.c.circle(sx * hr * 0.38, hy + hr * 0.08, hr * 0.26, stroke=1, fill=0)
            p.c.setFillAlpha(1)
        p.line([(-hr * 0.12, hy + hr * 0.1), (hr * 0.12, hy + hr * 0.1)], "#2B2B2B", 0.7)


def _face(p: _P, lk: Look, mimik: str, hy: float, hr: float) -> None:
    ex, ey, mr = hr * 0.38, hy + hr * 0.08, hr * 0.11
    my = hy - hr * 0.48
    if mimik in ("bewusstlos", "leblos"):
        for sx in (-1, 1):
            if mimik == "leblos":
                p.line([(sx * ex - mr * 2, ey), (sx * ex + mr * 2, ey)], OUTLINE, 0.8)
            else:
                p.curve((sx * ex - mr * 2, ey + mr), (sx * ex - mr, ey - mr), (sx * ex + mr, ey - mr),
                        (sx * ex + mr * 2, ey + mr), OUTLINE, 0.8)
        if mimik == "bewusstlos":
            p.ell(0, my, hr * 0.12, hr * 0.09, "#6B2D2D", lw=0.5)
        else:
            p.line([(-hr * 0.2, my), (hr * 0.2, my)], OUTLINE, 0.7)
        return
    for sx in (-1, 1):
        if mimik == "schmerz":
            p.line([(sx * ex - mr * 2, ey + mr), (sx * ex + mr * 1.6, ey), (sx * ex - mr * 2, ey - mr)][::sx],
                   OUTLINE, 0.8)
            p.line([(sx * ex - sx * mr * 2.2, ey + mr * 4.2), (sx * ex + sx * mr * 2, ey + mr * 2.8)], OUTLINE, 0.8)
        else:
            if mimik == "angst":
                p.ell(sx * ex, ey, mr * 1.7, mr * 1.9, "#FFFFFF", lw=0.5)
                p.curve((sx * ex - mr * 2, ey + mr * 3.4), (sx * ex - mr, ey + mr * 4.6), (sx * ex + mr, ey + mr * 4.6),
                        (sx * ex + mr * 2, ey + mr * 3.4), OUTLINE, 0.8)
            p.ell(sx * ex, ey, mr, mr, "#1A1A1A", outline=False)
    if mimik == "schmerz":
        p.curve((-hr * 0.28, my - hr * 0.08), (-hr * 0.12, my + hr * 0.12), (hr * 0.12, my + hr * 0.12),
                (hr * 0.28, my - hr * 0.08), OUTLINE, 0.9)
        p.drop(hr * 0.95, hy + hr * 0.45, hr * 0.13, HexColor("#7FB8E6"))
    elif mimik == "angst":
        p.ell(0, my, hr * 0.12, hr * 0.15, "#6B2D2D", lw=0.5)
    else:
        p.curve((-hr * 0.25, my + hr * 0.05), (-hr * 0.1, my - hr * 0.1), (hr * 0.1, my - hr * 0.1),
                (hr * 0.25, my + hr * 0.05), OUTLINE, 0.8)


def _hair_front(p: _P, lk: Look, hy: float, hr: float, child: bool) -> None:
    s, col = lk.hair_style, lk.hair
    if s == "baby":
        p.curve((-1, hy + hr), (-0.5, hy + hr + 4), (2.5, hy + hr + 3.5), (1.5, hy + hr + 1), col, 1.2)
        return
    if s == "bald":
        for sx in (-1, 1):
            p.ell(sx * hr * 0.92, hy + hr * 0.15, hr * 0.18, hr * 0.38, col, lw=0.6)
        return
    line = {"receding": hy + hr * 0.75, "buzz": hy + hr * 0.6, "bowl": hy + hr * 0.25}.get(s, hy + hr * 0.45)
    vol = {"buzz": 1.0, "curly": 3.0, "curly_short": 3.0, "curly_long": 3.0}.get(s, 2.0)
    p.fill(col)
    p.stroke(OUTLINE, 1.0)
    path = p.c.beginPath()
    path.moveTo(-hr - 0.6, hy + hr * 0.1)
    path.curveTo(-hr - vol, hy + hr * 1.5 + vol, hr + vol, hy + hr * 1.5 + vol, hr + 0.6, hy + hr * 0.1)
    path.curveTo(hr * 0.6, line + 1.5, hr * 0.2, line - 1, 0, line)
    path.curveTo(-hr * 0.3, line - 1.5, -hr * 0.7, line + 1, -hr - 0.6, hy + hr * 0.1)
    path.close()
    p.c.drawPath(path, stroke=1, fill=1)
    if s.startswith("curly"):
        for i in range(6):
            a = math.pi * (0.1 + 0.8 * i / 5)
            p.ell(-math.cos(a) * hr * 0.95, hy + math.sin(a) * hr * 1.05 + 1, 2.4, 2.4, col, lw=0.6)


# -------------------------
# Verletzungsmarken
# -------------------------

def _mark_under(p: _P, typ: str, x: float, y: float) -> None:
    if typ == "blut_stark":
        p.ell(x - 3, y - 4, 13, 8, BLOOD_DARK, outline=False, alpha=0.85)


def _burn(p: _P, x: float, y: float, s: float) -> None:
    p.ell(x, y, 4.2 * s, 3.4 * s, "#E2553B", outline=False, alpha=0.85)
    p.ell(x + 1.5 * s, y + 1 * s, 2.6 * s, 2 * s, "#F29A6E", outline=False, alpha=0.9)
    for dx, dy in ((-1.8, 0.6), (1.2, -1.1), (2.6, 1.4)):
        p.ell(x + dx * s, y + dy * s, 0.7 * s, 0.7 * s, "#FFF6EE", lw=0.3)


def _mark(p: _P, typ: str, x: float, y: float, o: dict) -> None:
    if typ == "blut":
        p.ell(x, y, 3.2, 2.6, BLOOD, outline=False)
        for dx, dy, s in ((2.5, -4.5, 0.9), (-1.5, -6.5, 0.7), (1, -8.5, 0.55)):
            p.drop(x + dx, y + dy, s)
    elif typ == "blut_stark":
        p.ell(x, y, 4.6, 3.6, BLOOD, outline=False)
        for a in (-0.6, 0, 0.6):
            p.line([(x + 4 * math.cos(a), y + 4 * math.sin(a)), (x + 9 * math.cos(a), y + 9 * math.sin(a))],
                   BLOOD, 1.2)
        for dx, dy, s in ((4, -6, 1.0), (-3, -7, 0.8)):
            p.drop(x + dx, y + dy, s)
    elif typ == "tourniquet":
        p.line([(x - 5, y + 0.6), (x + 5, y - 0.6)], "#1F1F1F", 3.2)
        p.rrect(x - 1, y - 3.5, 2, 7, 0.6, "#4A4A4A", lw=0.4)
    elif typ == "fraktur":
        p.ell(x, y, 3, 2.4, BLOOD, outline=False, alpha=0.8)
        p.line([(x - 4, y + 3), (x - 1, y + 0.5), (x - 3, y - 0.5), (x + 1, y - 3), (x - 0.5, y - 4)], OUTLINE, 1.0)
        for a in (0.3, 1.2, 2.2):  # Schmerzstrahlen
            p.line([(x + 5 * math.cos(a), y + 5 * math.sin(a)), (x + 8 * math.cos(a), y + 8 * math.sin(a))],
                   "#E8541E", 0.8)
    elif typ == "verbrennung":
        _burn(p, x, y, 1.0)
    elif typ == "verbrennung_gross":
        for k in ("thorax", "abdomen", "oberarm_l", "unterarm_r", "oberschenkel_l", "bein_r", "oberschenkel_r"):
            _burn(p, *o[k], 1.5)
    elif typ == "russ":
        for dx, dy, r in ((-2.5, -2.5, 2.2), (2.2, -3, 2.0), (0, -4.5, 1.8), (-4, 1, 1.3), (3.8, 0.5, 1.2)):
            p.ell(x + dx, y + dy, r, r * 0.8, "#2E2E2E", outline=False, alpha=0.55)
    elif typ in ("stridor", "atemnot"):
        col = "#E8541E" if typ == "stridor" else "#2F7FC1"
        for i, r in enumerate((4, 7, 10)):
            p.c.setStrokeColor(_col(col))
            p.c.setLineWidth(1.0)
            p.c.arc(x + 6 - r, y - r, x + 6 + r, y + r, -35, 70)
        if typ == "stridor":
            p.line([(x + 18, y + 3), (x + 20, y - 1), (x + 22, y + 3), (x + 24, y - 1)], col, 0.9)
    elif typ == "schnarchen":
        p.c.setFillColor(_col("#4A6B8A"))
        for i, (dx, dy, s) in enumerate(((7, 3, 4.5), (11, 8, 5.5), (16, 14, 6.5))):
            p.c.saveState()
            p.c.translate(x + dx, y + dy)
            p.c.rotate(o.get("_text_rot", 0))   # Schrift bleibt aufrecht
            p.c.setFont("Helvetica-Bold", s)
            p.c.drawString(0, 0, "Z")
            p.c.restoreState()
    elif typ == "husten":
        for dx, dy, r in ((6, 1, 1.6), (9.5, 3, 2.1), (13.5, 5.5, 2.6)):
            p.ell(x + dx, y + dy, r, r, "#BFBFBF", lw=0.4, alpha=0.85)
    elif typ == "prellung":
        p.ell(x, y, 4.8, 3.6, "#6F4C9B", outline=False, alpha=0.55)
        p.ell(x + 0.6, y + 0.4, 2.6, 1.9, "#3F5FA8", outline=False, alpha=0.45)
    elif typ == "schweiss":
        for dx, dy in ((-12, 2), (12, 4), (11, -3)):
            p.drop(x + dx, y + dy, 0.9, HexColor("#7FB8E6"))
    elif typ == "verband":
        p.rrect(x - 4, y - 3.5, 8, 7, 2.2, "#FAFAFA", lw=0.7)
        p.ell(x + 0.8, y + 0.6, 1.1, 1.1, BLOOD, outline=False, alpha=0.8)
    elif typ == "schlinge":
        sx = -1 if x < 0 else 1
        p.poly([(sx * 2, 78), (sx * 21, 50), (sx * 9, 47)], "#FAFAFA", lw=0.7)
    elif typ == "schuerfung":
        for i in range(4):
            p.line([(x - 3 + i * 1.8, y - 2.5), (x - 1.5 + i * 1.8, y + 2.5)], BLOOD, 0.7)
    elif typ == "truemmer":
        for dx, dy, s, col in ((-8, 30, 8, "#8F877A"), (6, 22, 9, "#9C9487"), (-3, 12, 7, "#7F786C"),
                               (9, 6, 6, "#A39B8E")):
            p.poly([(dx - s, dy - s * 0.6), (dx - s * 0.3, dy + s * 0.8), (dx + s, dy + s * 0.5),
                    (dx + s * 0.8, dy - s * 0.7)], col)


# -------------------------
# Szene
# -------------------------

def draw_scene(c: Canvas, x: float, y: float, w: float, h: float, lk: Look, pose: str, mimik: str,
               marks: list, env: str) -> None:
    """Zeichnet die Auffindesituation in die Box (x, y, w, h) in Punkten."""
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, y, w, h)
    c.clipPath(clip, stroke=0, fill=0)
    c.translate(x, y)
    k = w / SW                       # einheitlicher Massstab (keine Verzerrung)
    top = h / k                      # Szenenhöhe in Einheiten
    c.scale(k, k)
    p = _P(c)
    lying = pose == "liegend"
    _env(p, env, top * 0.72 if lying else 20.0, lying, top)

    child = lk.age < 12
    s = (0.74 if pose == "stehend" else 0.86 if pose == "sitzend" else 1.08) * (0.78 if child else 1.0)
    c.saveState()
    if lying:      # Draufsicht: Kopf links, Füsse rechts
        c.translate(SW / 2 + 50 * s, top * 0.38)
        c.rotate(90)
    else:
        c.translate(SW * 0.42, 14.0)
    c.scale(s, s)
    o = orte(pose)
    o["_text_rot"] = -90 if lying else 0
    for typ, ort in marks:
        _mark_under(p, typ, *o[ort])
    _figure(p, lk, pose, mimik)
    for typ, ort in marks:
        _mark(p, typ, *o[ort], o)
    c.restoreState()
    c.restoreState()


if __name__ == "__main__":
    import argparse

    import numpy as np
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    from ies_ng_avatar import make_look
    from ies_ng_swisspre import FAELLE, KATEGORIEN

    ap = argparse.ArgumentParser(description="Vorschau Auffindesituationen")
    ap.add_argument("-o", "--out", default="szenen_vorschau.pdf")
    a = ap.parse_args()
    cv = Canvas(a.out, pagesize=A4)
    bw, bh = 85.6 * mm, 53.5 * mm
    rng = np.random.default_rng(3)
    for i, f in enumerate(FAELLE):
        col, row = i % 2, (i // 2) % 5
        if i and i % 10 == 0:
            cv.showPage()
        x, yy = 12 * mm + col * (bw + 6 * mm), A4[1] - 15 * mm - (row + 1) * (bh + 4 * mm)
        age = int(rng.integers(20, 80)) if f.get("min_age") else int(rng.choice([8, 30, 45, 70]))
        lk = make_look(age, str(rng.choice(["m", "f"])), rng)
        draw_scene(cv, x, yy, bw, bh, lk, f["pose"], f["mimik"], f["marks"], f["env"])
        cv.setFillColor(HexColor(KATEGORIEN[f["pre"]][2]))
        cv.rect(x, yy - 3.4 * mm, 3 * mm, 3 * mm, stroke=1, fill=1)
        cv.setFillColor(OUTLINE)
        cv.setFont("Helvetica", 7)
        cv.drawString(x + 4 * mm, yy - 3 * mm, f"{f['titel']} ({age} J.)")
    cv.save()
    print(f"-> {a.out}")
