"""
PLS Schweiz: Farbkategorien, Algorithmus Swiss Pre (Pre-Triage), Fallkatalog und PLS-ID.

Quelle: Gebrauchsanweisung PLS Schweiz (Arbeitsgruppe PLS Schweiz, KSD, 2019).
Pre-Triage vergibt Schwarz, Rot, Gelb, Grün, Weiss (nie Blau); die ärztliche Triage zusätzlich Blau.
Jeder Fall erzeugt Befunde, deren Auswertung mit Swiss Pre die Prä-Triage-Farbe ergibt (geprüft).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

# Farbkategorie: (Beschriftung, Kürzel, Hintergrund, Schrift)
KATEGORIEN = {
    "grau": ("GRAU", "–", "#9E9E9E", "#FFFFFF"),
    "weiss": ("WEISS", "0", "#FFFFFF", "#1F1F1F"),
    "gruen": ("GRÜN", "III", "#009A44", "#FFFFFF"),
    "gelb": ("GELB", "II", "#FFD500", "#1F1F1F"),
    "rot": ("ROT", "I", "#E30613", "#FFFFFF"),
    "blau": ("BLAU", "IV", "#1E5AB4", "#FFFFFF"),
    "schwarz": ("SCHWARZ", "EX", "#1A1A1A", "#FFFFFF"),
}
PRE_KATEGORIEN = ("rot", "gelb", "gruen", "weiss", "schwarz")
DEFAULT_PRE_MIX = {"rot": 15, "gelb": 30, "gruen": 45, "weiss": 7, "schwarz": 3}
MIN_AGE_EXITUS = 16  # Schwarz/Blau in der Übung nur bei Erwachsenen


# -------------------------
# PLS-ID: CH + 2 Buchstaben + 3 Ziffern (z. B. CHYY001)
# -------------------------

def _pair_index(pair: str) -> int:
    return (ord(pair[0]) - 65) * 26 + (ord(pair[1]) - 65)


def pls_id(n: int, start: str = "CHYY001") -> str:
    """n-te ID ab start (n = 1 -> start). Nach 999 folgt das nächste Buchstabenpaar: CHYY999 -> CHYZ001."""
    m = re.fullmatch(r"CH([A-Z]{2})(\d{3})", start)
    if not m or m.group(2) == "000":
        raise ValueError(f"PLS-ID muss CH + 2 Buchstaben + 001..999 sein: {start}")
    idx = _pair_index(m.group(1)) * 999 + int(m.group(2)) - 1 + (n - 1)
    pair, num = divmod(idx, 999)
    if pair >= 26 * 26:
        raise ValueError("PLS-ID-Bereich überschritten (> CHZZ999)")
    return f"CH{chr(65 + pair // 26)}{chr(65 + pair % 26)}{num + 1:03d}"


def pls_capacity(start: str = "CHYY001") -> int:
    """Anzahl IDs ab start bis CHZZ999."""
    m = re.fullmatch(r"CH([A-Z]{2})(\d{3})", start)
    return 26 * 26 * 999 - (_pair_index(m.group(1)) * 999 + int(m.group(2)) - 1)


# -------------------------
# Befund und Algorithmus
# -------------------------

@dataclass
class Befund:
    gehfaehig: bool
    atmung: bool = True            # Atmung nach Freimachen der Atemwege
    nicht_vereinbar: bool = False  # mit dem Leben nicht vereinbare Verletzung
    todeszeichen: bool = False
    stridor: bool = False          # Inhalationstrauma mit Stridor
    offenhalten: bool = False      # Offenhalten der Atemwege erforderlich
    af: int = 16                   # Atemfrequenz /min
    radialispuls: bool = True
    rekap_s: float = 1.0           # Rekapillarisierungszeit
    blutung: str = "keine"         # keine | leicht | gestillt | unstillbar
    kommando: bool = True          # befolgt Aufforderungen
    schmerzen_stark: bool = False
    verletzt: bool = True


def swiss_pre(b: Befund) -> tuple[str, str]:
    """Algorithmus Swiss Pre. Gibt (Farbkategorie, auslösendes Kriterium) zurück."""
    if not b.atmung or b.nicht_vereinbar or b.todeszeichen:
        return "schwarz", "A/(E): keine Atmung / nicht vereinbar / Todeszeichen"
    if b.stridor or b.offenhalten:
        return "rot", "A: Inhalationstrauma mit Stridor / Atemwege offenhalten"
    if b.af < 10 or b.af > 30:
        return "rot", "B: Atemfrequenz < 10 oder > 30"
    if not b.radialispuls or b.rekap_s > 2 or b.blutung == "unstillbar":
        return "rot", "C: kein Radialispuls / Rekap > 2 s / unstillbare Blutung"
    if b.blutung == "gestillt":
        return "gelb", "C: sicher gestillte Blutung"
    if not b.kommando:
        return "rot", "D: befolgt Aufforderungen nicht"
    if not b.gehfaehig or b.schmerzen_stark:
        return "gelb", "E: nicht gehfähig / starke Schmerzen"
    if b.verletzt:
        return "gruen", "E: verletzt / erkrankt"
    return "weiss", "E: unverletzt / nicht erkrankt"


def befund_zeilen(b: Befund) -> list[str]:
    """Kurzdarstellung der Befunde für die Karte (ohne Kategorie)."""
    ja = lambda v: "ja" if v else "nein"  # noqa: E731
    if not b.atmung:
        atm = "keine Atmung nach Freimachen der Atemwege"
    else:
        atm = f"AF {b.af}/min" + (" · Stridor" if b.stridor else "") + \
              (" · Atemwege müssen offengehalten werden" if b.offenhalten else "")
    bl = {"keine": "keine", "leicht": "leicht", "gestillt": "stark, sicher gestillt",
          "unstillbar": "unstillbar"}[b.blutung]
    puls = "tastbar" if b.radialispuls else "nicht tastbar"
    return [
        f"Gehfähig: {ja(b.gehfaehig)}   ·   Atmung: {atm}",
        f"Radialispuls: {puls}   ·   Rekap: {b.rekap_s:.0f} s   ·   Blutung: {bl}",
        f"Befolgt Aufforderungen: {ja(b.kommando)}   ·   Starke Schmerzen: {ja(b.schmerzen_stark)}",
    ]


# -------------------------
# Fallkatalog
# -------------------------
# pose: stehend | sitzend | liegend ; mimik: neutral | schmerz | angst | bewusstlos | leblos
# env: innen | brand | verkehr | truemmer | aussen
# marks: (Typ, Körperstelle) – siehe ies_ng_szene.MARKS / ORTE
# befund: feste Werte oder (min, max) für af/rekap_s
# triage: Gewichte der ärztlichen Triage (Blau/Schwarz nur ab MIN_AGE_EXITUS)

FAELLE: list[dict] = [
    # --- Schwarz ---
    dict(key="keine_atmung", pre="schwarz", min_age=MIN_AGE_EXITUS,
         titel="Keine Atmung nach Freimachen der Atemwege",
         text="Liegt reglos unter Trümmerteilen. Nach Freimachen der Atemwege setzt keine Atmung ein.",
         env="truemmer", pose="liegend", mimik="leblos", marks=[("truemmer", "beine")],
         befund=dict(gehfaehig=False, atmung=False, af=0, radialispuls=False, rekap_s=(4, 5), kommando=False),
         triage={"schwarz": 1}),
    dict(key="nicht_vereinbar", pre="schwarz", min_age=MIN_AGE_EXITUS,
         titel="Mit dem Leben nicht vereinbare Verletzung",
         text="Nach Sturz aus grosser Höhe schwerstes Schädel-Hirn-Trauma, keine Lebenszeichen.",
         env="aussen", pose="liegend", mimik="leblos", marks=[("blut", "kopf"), ("prellung", "thorax")],
         befund=dict(gehfaehig=False, atmung=False, nicht_vereinbar=True, af=0, radialispuls=False,
                     rekap_s=(4, 5), kommando=False),
         triage={"schwarz": 1}),
    # --- Rot ---
    dict(key="atemweg", pre="rot", titel="Behebbare Atemwegsverlegung",
         text="Bewusstlos in Rückenlage, schnarchende Atmung. Nach Esmarch-Handgriff atmet die Person frei, "
              "Atemwege müssen offengehalten werden (Wendl-Tubus).",
         env="innen", pose="liegend", mimik="bewusstlos", marks=[("schnarchen", "mund")],
         befund=dict(gehfaehig=False, offenhalten=True, af=(12, 18), kommando=False),
         triage={"rot": 0.75, "gelb": 0.25}),
    dict(key="stridor", pre="rot", titel="Inhalationstrauma mit Stridor",
         text="Aus verrauchtem Treppenhaus gerettet. Russ an Mund und Nase, heisere Stimme, pfeifende "
              "Einatmung.",
         env="brand", pose="sitzend", mimik="angst", marks=[("russ", "gesicht"), ("stridor", "mund")],
         befund=dict(gehfaehig=False, stridor=True, af=(24, 30)),
         triage={"rot": 0.85, "gelb": 0.15}),
    dict(key="schnappatmung", pre="rot", titel="Schnappatmung",
         text="Bewusstlos neben dem Fahrzeug, nur vereinzelte schnappende Atemzüge ({af}/min).",
         env="verkehr", pose="liegend", mimik="bewusstlos", marks=[("blut", "stirn")],
         befund=dict(gehfaehig=False, af=(4, 8), rekap_s=(2, 3), kommando=False),
         triage={"rot": 0.5, "blau": 0.3, "schwarz": 0.2}),
    dict(key="verbrennung_gross", pre="rot", min_age=MIN_AGE_EXITUS, titel="Verbrennung Grad 2–3 > 60 % KOF",
         text="Ausgedehnte Verbrennungen an Rumpf, Armen und Beinen. Rasche, flache Atmung ({af}/min).",
         env="brand", pose="liegend", mimik="schmerz", marks=[("verbrennung_gross", "koerper")],
         befund=dict(gehfaehig=False, af=(32, 40), schmerzen_stark=True),
         triage={"blau": 0.6, "rot": 0.4}),
    dict(key="blutung_unstillbar", pre="rot", titel="Arterielle Blutung, unstillbar",
         text="Spritzende Blutung aus der Leiste. Tourniquet nicht anlegbar, Druckverband blutet durch.",
         env="verkehr", pose="liegend", mimik="schmerz", marks=[("blut_stark", "leiste")],
         befund=dict(gehfaehig=False, blutung="unstillbar", af=(22, 28), schmerzen_stark=True),
         triage={"rot": 0.9, "gelb": 0.1}),
    dict(key="schock_becken", pre="rot", titel="Schock bei Beckenverletzung",
         text="War im Fahrzeug eingeklemmt. Blass, kaltschweissig, Radialispuls nicht tastbar.",
         env="verkehr", pose="liegend", mimik="schmerz", marks=[("prellung", "becken"), ("schweiss", "kopf")],
         befund=dict(gehfaehig=False, radialispuls=False, rekap_s=(3, 4), af=(24, 30), schmerzen_stark=True),
         triage={"rot": 0.85, "blau": 0.15}),
    dict(key="sht", pre="rot", titel="Schädel-Hirn-Trauma",
         text="Kopfplatzwunde nach Sturz. Öffnet die Augen kaum, befolgt keine Aufforderungen.",
         env="innen", pose="liegend", mimik="bewusstlos", marks=[("blut", "stirn")],
         befund=dict(gehfaehig=False, af=(14, 20), kommando=False),
         triage={"rot": 0.7, "gelb": 0.3}),
    dict(key="thorax", pre="rot", titel="Thoraxtrauma mit Atemnot",
         text="Prellmarke an der Brustwand nach Aufprall auf das Lenkrad. Stark beschleunigte Atmung "
              "({af}/min), Atemnot.",
         env="verkehr", pose="sitzend", mimik="schmerz", marks=[("prellung", "thorax"), ("atemnot", "mund")],
         befund=dict(gehfaehig=False, af=(32, 38), schmerzen_stark=True),
         triage={"rot": 0.8, "gelb": 0.2}),
    # --- Gelb ---
    dict(key="blutung_gestillt", pre="gelb", titel="Arterielle Blutung, mit Tourniquet gestillt",
         text="Starke Blutung am Unterarm durch Glassplitter, mit Tourniquet sicher gestillt.",
         env="truemmer", pose="sitzend", mimik="schmerz",
         marks=[("blut", "unterarm_r"), ("tourniquet", "oberarm_r")],
         befund=dict(gehfaehig=False, blutung="gestillt", af=(18, 24)),
         triage={"gelb": 0.8, "rot": 0.2}),
    dict(key="fraktur_unterschenkel", pre="gelb", titel="Offene Unterschenkelfraktur",
         text="Sitzt auf einer Stufe, Unterschenkel fehlgestellt mit offener Wunde. Kann nicht aufstehen.",
         env="aussen", pose="sitzend", mimik="schmerz", marks=[("fraktur", "bein_l"), ("blut", "bein_l")],
         befund=dict(gehfaehig=False, blutung="leicht", af=(18, 24), schmerzen_stark=True),
         triage={"gelb": 0.85, "rot": 0.15}),
    dict(key="fraktur_oberschenkel", pre="gelb", titel="Oberschenkelfraktur",
         text="Liegt nach Sturz, Bein verkürzt und nach aussen gedreht, starke Schmerzen.",
         env="innen", pose="liegend", mimik="schmerz", marks=[("fraktur", "oberschenkel_r")],
         befund=dict(gehfaehig=False, af=(18, 26), schmerzen_stark=True),
         triage={"gelb": 0.85, "rot": 0.15}),
    dict(key="verbrennung_beine", pre="gelb", titel="Verbrennung Grad 2 an den Beinen (ca. 15 % KOF)",
         text="Verbrühung beider Unterschenkel mit Blasenbildung. Kann nicht gehen.",
         env="brand", pose="sitzend", mimik="schmerz",
         marks=[("verbrennung", "bein_l"), ("verbrennung", "bein_r")],
         befund=dict(gehfaehig=False, af=(18, 24), schmerzen_stark=True),
         triage={"gelb": 0.8, "gruen": 0.2}),
    dict(key="rauchgas", pre="gelb", titel="Rauchgasexposition",
         text="Hustet stark nach Rauchgasexposition, Atemnot bei Belastung, kann nicht gehen. Kein Stridor.",
         env="brand", pose="sitzend", mimik="angst", marks=[("russ", "gesicht"), ("husten", "mund")],
         befund=dict(gehfaehig=False, af=(22, 28)),
         triage={"gelb": 0.6, "gruen": 0.3, "rot": 0.1}),
    dict(key="ruecken", pre="gelb", titel="Rückenverletzung nach Sturz",
         text="Liegt nach Sturz von der Leiter, starke Rückenschmerzen, bewegt beide Beine.",
         env="aussen", pose="liegend", mimik="schmerz", marks=[("prellung", "abdomen")],
         befund=dict(gehfaehig=False, af=(16, 24), schmerzen_stark=True),
         triage={"gelb": 0.7, "gruen": 0.3}),
    # --- Grün (gehfähig) ---
    dict(key="schnitt_hand", pre="gruen", titel="Schnittwunde an der Hand",
         text="Schnittwunde an der rechten Hand durch Glassplitter, mit Verband versorgt.",
         env="truemmer", pose="stehend", mimik="neutral", marks=[("verband", "hand_r")],
         befund=dict(gehfaehig=True, blutung="leicht"),
         triage={"gruen": 0.95, "gelb": 0.05}),
    dict(key="prellung_schulter", pre="gruen", titel="Schulterprellung",
         text="Prellung der linken Schulter, hält den Arm. Geht selbständig.",
         env="verkehr", pose="stehend", mimik="neutral", marks=[("prellung", "schulter_l"), ("schlinge", "arm_l")],
         befund=dict(gehfaehig=True),
         triage={"gruen": 0.9, "gelb": 0.1}),
    dict(key="verstauchung", pre="gruen", titel="Verstauchung des Fussgelenks",
         text="Humpelt, Fussgelenk geschwollen. Geht mit Unterstützung.",
         env="aussen", pose="stehend", mimik="neutral", marks=[("prellung", "fuss_r")],
         befund=dict(gehfaehig=True),
         triage={"gruen": 0.9, "gelb": 0.1}),
    dict(key="schuerfung", pre="gruen", titel="Schürfwunden an Knie und Händen",
         text="Schürfwunden an beiden Knien und Handflächen nach Sturz auf Asphalt.",
         env="verkehr", pose="stehend", mimik="neutral", marks=[("schuerfung", "knie_l"), ("schuerfung", "knie_r")],
         befund=dict(gehfaehig=True, blutung="leicht"),
         triage={"gruen": 1.0}),
    dict(key="rauchgas_leicht", pre="gruen", titel="Leichte Rauchgasexposition",
         text="Hustet gelegentlich nach Aufenthalt im Rauch, atmet ruhig ({af}/min), geht selbständig.",
         env="brand", pose="stehend", mimik="neutral", marks=[("husten", "mund")],
         befund=dict(gehfaehig=True, af=(16, 22)),
         triage={"gruen": 0.85, "gelb": 0.15}),
    dict(key="verbrennung_hand", pre="gruen", titel="Verbrennung Grad 1 an der Hand",
         text="Gerötete, schmerzende Haut am linken Handrücken nach Kontakt mit heissem Metall.",
         env="brand", pose="stehend", mimik="neutral", marks=[("verbrennung", "hand_l")],
         befund=dict(gehfaehig=True),
         triage={"gruen": 1.0}),
    # --- Weiss ---
    dict(key="unverletzt_zeuge", pre="weiss", titel="Unverletzt",
         text="Augenzeuge, unverletzt und ohne Beschwerden, aufgeregt, gibt bereitwillig Auskunft.",
         env="aussen", pose="stehend", mimik="angst", marks=[],
         befund=dict(gehfaehig=True, verletzt=False),
         triage={"weiss": 1.0}),
    dict(key="unverletzt_insasse", pre="weiss", titel="Unverletzt",
         text="Mitfahrende Person, konnte das Fahrzeug selbst verlassen, keine Verletzungen, keine Beschwerden.",
         env="verkehr", pose="stehend", mimik="neutral", marks=[],
         befund=dict(gehfaehig=True, verletzt=False),
         triage={"weiss": 1.0}),
]


@dataclass
class Fall:
    key: str
    pre: str            # Prä-Triage (Swiss Pre)
    triage: str         # ärztliche Triage (inkl. Blau)
    titel: str
    text: str
    befund: Befund
    kriterium: str
    env: str
    pose: str
    mimik: str
    marks: list

    def befund_dict(self) -> dict:
        return asdict(self.befund)


def _draw_value(v, r: np.random.Generator, is_float: bool = False):
    if isinstance(v, tuple):
        lo, hi = v
        return round(float(r.uniform(lo, hi)), 1) if is_float else int(r.integers(lo, hi + 1))
    return v


def erzeuge_fall(pre: str, age: int, r: np.random.Generator) -> Fall:
    """Wählt einen passenden Fall und erzeugt Befunde; prüft sie mit Swiss Pre."""
    opts = [f for f in FAELLE if f["pre"] == pre and age >= f.get("min_age", 0)]
    if not opts:
        raise ValueError(f"kein Fall für {pre} bei Alter {age}")
    f = opts[int(r.integers(len(opts)))]
    kw = {k: _draw_value(v, r, k == "rekap_s") for k, v in f["befund"].items()}
    if "rekap_s" in kw and isinstance(kw["rekap_s"], float):
        kw["rekap_s"] = float(round(kw["rekap_s"]))
    b = Befund(**kw)
    cat, crit = swiss_pre(b)
    if cat != pre:
        raise AssertionError(f"Fall {f['key']}: Swiss Pre ergibt {cat}, erwartet {pre}")

    tri = {k: v for k, v in f["triage"].items()
           if age >= MIN_AGE_EXITUS or k not in ("blau", "schwarz") or pre == "schwarz"}
    keys, w = zip(*tri.items())
    w = np.asarray(w, float)
    triage = keys[int(r.choice(len(keys), p=w / w.sum()))]
    return Fall(key=f["key"], pre=pre, triage=triage, titel=f["titel"], text=f["text"].format(af=b.af),
                befund=b, kriterium=crit, env=f["env"], pose=f["pose"], mimik=f["mimik"], marks=list(f["marks"]))


def parse_mix(s: Optional[str]) -> dict[str, float]:
    """'rot=15,gelb=30,gruen=45,weiss=7,schwarz=3' -> Anteile."""
    if not s:
        return dict(DEFAULT_PRE_MIX)
    out = {}
    for part in s.split(","):
        k, v = part.split("=")
        k = k.strip().lower().replace("ü", "ue")
        if k not in PRE_KATEGORIEN:
            raise ValueError(f"unbekannte Prä-Triage-Kategorie {k!r} (erlaubt: {', '.join(PRE_KATEGORIEN)})")
        out[k] = float(v)
    if sum(out.values()) <= 0:
        raise ValueError("Summe der Anteile muss > 0 sein")
    return out


def allocate_pre(ages: list[int], mix: dict[str, float], r: np.random.Generator) -> list[str]:
    """Exakte Anteile (grösste Reste), zufällig verteilt; Schwarz nur bei Erwachsenen (Tausch)."""
    n = len(ages)
    total = sum(mix.values())
    raw = {k: n * v / total for k, v in mix.items()}
    counts = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[: n - sum(counts.values())]:
        counts[k] += 1
    labels = [k for k, c in counts.items() for _ in range(c)]
    r.shuffle(labels)
    adults = [i for i, a in enumerate(ages) if a >= MIN_AGE_EXITUS]
    for i, a in enumerate(ages):
        if labels[i] == "schwarz" and a < MIN_AGE_EXITUS:
            swap = [j for j in adults if labels[j] != "schwarz"]
            if swap:
                j = swap[int(r.integers(len(swap)))]
                labels[i], labels[j] = labels[j], labels[i]
            else:
                labels[i] = "rot"
    return labels
