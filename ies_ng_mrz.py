"""MRZ TD1 (ICAO Doc 9303) für die Schweizer Identitätskarte: Erzeugen und Prüfen."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

TD1_LEN = 30
WEIGHTS = (7, 3, 1)
TRANSLIT = {"Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS", "Æ": "AE", "Ø": "OE", "Å": "AA", "Œ": "OE"}


def char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if c == "<":
        return 0
    if "A" <= c <= "Z":
        return ord(c) - 55
    raise ValueError(f"invalid MRZ character {c!r}")


def check_digit(s: str) -> int:
    """Gewichte 7-3-1 zyklisch, Summe mod 10."""
    return sum(char_value(c) * WEIGHTS[i % 3] for i, c in enumerate(s)) % 10


def composite_td1(l1: str, l2: str) -> int:
    return check_digit(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29])


def transliterate(s: str) -> str:
    """ICAO-Transliteration: Umlaute -> AE/OE/UE, Akzente entfernen, Trenner -> '<'."""
    s = "".join(TRANSLIT.get(c, c) for c in s.upper())
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^A-Z]+", "<", s)
    return s.strip("<")


def name_field(last: str, first: str, length: int = TD1_LEN) -> str:
    """NACHNAME<<VORNAME; bei Überlänge zuerst Vornamen, dann Nachnamen kürzen."""
    ln, fn = transliterate(last), transliterate(first)
    ln = ln[: length - 2] if len(ln) > length - 2 else ln
    s = f"{ln}<<{fn}"[:length]
    return s.ljust(length, "<")


def yymmdd(d: date) -> str:
    return d.strftime("%y%m%d")


@dataclass(frozen=True)
class TD1:
    line1: str
    line2: str
    line3: str

    @property
    def lines(self) -> tuple[str, str, str]:
        return self.line1, self.line2, self.line3

    def __str__(self) -> str:
        return "\n".join(self.lines)


def make_td1(
    doc_number: str,
    last_name: str,
    first_name: str,
    dob: date,
    sex: str,
    expiry: date,
    doc_type: str = "ID",
    issuer: str = "CHE",
    nationality: str = "CHE",
) -> TD1:
    doc = doc_number.upper()
    if not re.fullmatch(r"[A-Z0-9]{1,9}", doc):
        raise ValueError("doc_number must be 1-9 chars A-Z/0-9")
    doc = doc.ljust(9, "<")
    sx = {"m": "M", "f": "F"}.get(sex.lower(), "<")

    l1 = f"{doc_type:<2}{issuer}{doc}{check_digit(doc)}".ljust(TD1_LEN, "<")
    b, e = yymmdd(dob), yymmdd(expiry)
    l2 = f"{b}{check_digit(b)}{sx}{e}{check_digit(e)}{nationality}".ljust(TD1_LEN - 1, "<")
    l2 += str(composite_td1(l1, l2 + "<"))
    l3 = name_field(last_name, first_name)
    return TD1(l1, l2, l3)


# Positionen der Prüfziffern (Zeile, Index 0-basiert)
CHECK_POSITIONS = {"document": (0, 14), "birth": (1, 6), "expiry": (1, 14), "composite": (1, 29)}


def corrupt(td1: TD1, field: str) -> TD1:
    """Verfälscht eine Prüfziffer (für Negativ-Übungsfälle)."""
    li, pos = CHECK_POSITIONS[field]
    lines = list(td1.lines)
    ln = lines[li]
    lines[li] = ln[:pos] + str((int(ln[pos]) + 1 + (int(ln[pos]) % 3)) % 10) + ln[pos + 1:]
    return TD1(*lines)


def validate_td1(td1: TD1) -> dict[str, bool]:
    l1, l2, _ = td1.lines
    return {
        "document": check_digit(l1[5:14]) == int(l1[14]),
        "birth": check_digit(l2[0:6]) == int(l2[6]),
        "expiry": check_digit(l2[8:14]) == int(l2[14]),
        "composite": composite_td1(l1, l2) == int(l2[29]),
    }
