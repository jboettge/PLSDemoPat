"""Synthetische Personen (Haushalte) aus CH-Adressen und CH-Namensregistern erzeugen."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Optional, Tuple

import re

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365.2425

# -------------------------
# Config / Helpers
# -------------------------

@dataclass(frozen=True)
class Columns:
    street: str = "street"
    house_no: str = "house_number"
    postcode: str = "postcode"
    city: str = "city"
    canton: str = "canton"
    lat: str = "lat"
    lon: str = "lon"

    @property
    def all(self) -> list[str]:
        return [self.street, self.house_no, self.postcode, self.city, self.canton, self.lat, self.lon]


@dataclass(frozen=True)
class NameCols:
    first: str = "first_name"
    gender: str = "gender"
    first_freq: str = "freq"
    last: str = "last_name"
    last_freq: str = "freq"
    year: str = "birth_year"     # optional: Geburtsjahr (Vornamen)
    canton: str = "canton"       # optional: Kanton (Nachnamen, ggf. Vornamen)


GENDER_MAP = {
    "m": "m", "1": "m", "male": "m", "mann": "m", "männlich": "m", "maennlich": "m", "h": "m", "homme": "m",
    "f": "f", "w": "f", "2": "f", "female": "f", "frau": "f", "weiblich": "f", "femme": "f",
}

# Aliase inkl. GWR / amtliches Gebäudeadressverzeichnis (swisstopo)
ADDR_ALIASES = {
    "street": ["strasse", "straße", "str", "road", "strname", "stn_label"],
    "house_no": ["hnr", "hausnummer", "nr", "no", "deinr", "adr_number"],
    "postcode": ["plz", "zip", "postalcode", "dplz4", "zip_code"],
    "city": ["ort", "gemeinde", "place", "stadt", "dplzname", "zip_name", "com_name"],
    "canton": ["kt", "kanton", "state", "gdekt", "com_canton"],
}
FREQ_ALIASES = ["häufigkeit", "anzahl", "count", "frequency", "value", "wert", "obs_value", "anzahl personen"]
YEAR_ALIASES = ["yearofbirth", "geburtsjahr", "jahrgang", "birth year", "birth_year", "année de naissance", "anno di nascita",
                "jahr", "year", "année"]
CANTON_ALIASES = ["kanton", "canton", "cantone", "kt", "gdekt"]
FN_ALIASES = {
    "first": ["firstname", "vorname", "vornamen", "prenom", "prénom", "nome", "given", "first name"],
    "gender": ["geschlecht", "sex", "sexe", "sesso"],
    "first_freq": FREQ_ALIASES,
    "year": YEAR_ALIASES,
    "canton": CANTON_ALIASES,
}
LN_ALIASES = {
    "last": ["lastname", "nachname", "nachnamen", "nom", "nom de famille", "cognome", "name", "surname", "last name"],
    "last_freq": FREQ_ALIASES,
    "canton": CANTON_ALIASES,
}

# Kantonsnamen (de/fr/it/en, BFS-Schreibweisen) -> Kürzel
CANTONS = {
    "ZH": ["zürich", "zurich", "zurigo"], "BE": ["bern", "berne", "berna", "bern / berne"],
    "LU": ["luzern", "lucerne", "lucerna"], "UR": ["uri"], "SZ": ["schwyz", "svitto"],
    "OW": ["obwalden", "obwald", "obvaldo"], "NW": ["nidwalden", "nidwald", "nidvaldo"],
    "GL": ["glarus", "glaris", "glarona"], "ZG": ["zug", "zoug", "zugo"],
    "FR": ["freiburg", "fribourg", "friburgo", "fribourg / freiburg"],
    "SO": ["solothurn", "soleure", "soletta"], "BS": ["basel-stadt", "bâle-ville", "basilea città"],
    "BL": ["basel-landschaft", "bâle-campagne", "basilea campagna"],
    "SH": ["schaffhausen", "schaffhouse", "sciaffusa"],
    "AR": ["appenzell ausserrhoden", "appenzell rh.-ext.", "appenzello esterno"],
    "AI": ["appenzell innerrhoden", "appenzell rh.-int.", "appenzello interno"],
    "SG": ["st. gallen", "saint-gall", "san gallo", "st.gallen"], "GR": ["graubünden", "grisons", "grigioni",
          "graubünden / grigioni / grischun"],
    "AG": ["aargau", "argovie", "argovia"], "TG": ["thurgau", "thurgovie", "turgovia"],
    "TI": ["tessin", "ticino"], "VD": ["waadt", "vaud"], "VS": ["wallis", "valais", "vallese", "valais / wallis"],
    "NE": ["neuenburg", "neuchâtel", "neuchatel"], "GE": ["genf", "genève", "geneve", "ginevra"],
    "JU": ["jura", "giura"],
}
_CANTON_LOOKUP = {n: k for k, names in CANTONS.items() for n in names} | {k.lower(): k for k in CANTONS}
_TOTAL_LABELS = {"total", "totale", "insgesamt", "schweiz", "suisse", "svizzera", "switzerland", "ch", ""}


def normalize_canton(s: pd.Series) -> pd.Series:
    """Kantonsname/-kürzel -> Kürzel; Gesamttotal (Schweiz) -> NA."""
    key = _clean_str(s).str.lower().str.replace(r"^\s*-+\s*", "", regex=True)
    return key.map(lambda k: _CANTON_LOOKUP.get(k) if isinstance(k, str) else None)


def _parse_year(s: pd.Series) -> pd.Series:
    """'1990', '1990-1999' (-> Mitte), sonst NA."""
    parts = _clean_str(s).str.extract(r"(\d{4})(?:\D+(\d{4}))?")
    a = pd.to_numeric(parts[0], errors="coerce")
    b = pd.to_numeric(parts[1], errors="coerce").fillna(a)
    return ((a + b) / 2).round()


def _melt_year_columns(df: pd.DataFrame, freq_col: str, year_col: str) -> pd.DataFrame:
    """Breitformat (Jahre als Spalten, typisch BFS-Export) -> Langformat."""
    # Spalten wie "1990", "Geburtsjahr 1990", "1990 Anzahl"
    years = [c for c in df.columns if re.fullmatch(r"[^\d]*(?<!\d)(1[89]\d\d|20\d\d)(?!\d)[^\d]*", str(c))]
    if not years or freq_col in df.columns:
        return df
    ids = [c for c in df.columns if c not in years]
    out = df.melt(id_vars=ids, value_vars=years, var_name=year_col, value_name=freq_col)
    out[year_col] = out[year_col].astype(str).str.extract(r"(\d{4})")[0]
    return out


HEADER_HINTS = {"vorname", "vornamen", "nachname", "nachnamen", "prénom", "prenom", "nom", "first_name",
                "last_name", "street", "strasse", "stn_label", "name"}


def _read_any(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suf in {".xlsx", ".xls"}:
        # BFS-Excel: Titelzeilen überspringen, Kopfzeile anhand bekannter Spaltennamen finden
        raw = pd.read_excel(path, header=None, dtype=str)
        hdr = next((i for i, row in raw.head(40).iterrows()
                    if HEADER_HINTS & {str(v).strip().lower() for v in row if pd.notna(v)}), 0)
        df = raw.iloc[hdr + 1:].copy()
        df.columns = [str(c).strip() if pd.notna(c) else f"col{i}" for i, c in enumerate(raw.iloc[hdr])]
        df.columns = [c[:-2] if re.fullmatch(r"\d{4}\.0", c) else c for c in df.columns]
        return df.dropna(how="all")
    # sep=None erkennt ',' und ';' (BFS/swisstopo); dtype=str schützt PLZ/Hausnummern
    try:
        return pd.read_csv(path, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:  # ältere BFS-/PX-Exporte
        return pd.read_csv(path, sep=None, engine="python", dtype=str, encoding="latin-1")


def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _apply_aliases(df: pd.DataFrame, aliases: dict[str, list[str]], target: object) -> pd.DataFrame:
    """Benennt den ersten passenden Alias um, falls die Zielspalte fehlt (keine Duplikate)."""
    for attr, alts in aliases.items():
        new = getattr(target, attr)
        if new in df.columns:
            continue
        for old in alts:
            if old in df.columns:
                df = df.rename(columns={old: new})
                break
    return df


def _ensure_columns(df: pd.DataFrame, must_have: list[str], name: str) -> None:
    missing = [c for c in must_have if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}. Present: {list(df.columns)}")


def _as_weights(s: pd.Series) -> np.ndarray:
    w = pd.to_numeric(s, errors="coerce").fillna(1.0).to_numpy(dtype=float)
    w = np.clip(w, 0, None)
    if w.sum() <= 0:
        w = np.ones_like(w, dtype=float)
    return w


def _clean_str(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip()


def normalize_gender(s: pd.Series) -> pd.Series:
    return _clean_str(s).str.lower().map(GENDER_MAP).fillna("x").astype(str)


def lv95_to_wgs84(e: np.ndarray, n: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Näherungsformel swisstopo LV95 -> WGS84 (Genauigkeit ~1 m)."""
    y = (e - 2_600_000) / 1_000_000
    x = (n - 1_200_000) / 1_000_000
    lon = (2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x**2 - 0.0436 * y**3) * 100 / 36
    lat = (16.9023892 + 3.238272 * x - 0.270978 * y**2 - 0.002528 * x**2
           - 0.0447 * y**2 * x - 0.0140 * x**3) * 100 / 36
    return lat, lon

# -------------------------
# 1) Adressen lesen
# -------------------------

def read_ch_addresses(path: str | Path, cols: Columns = Columns()) -> pd.DataFrame:
    """
    Mindestens: street, house_number, postcode, city. Optional: canton, lat, lon.
    LV95-Koordinaten (adr_easting/adr_northing bzw. gkode/gkodn) werden zu lat/lon umgerechnet.
    swisstopo 'zip_label' ("8001 Zürich") wird in PLZ und Ort zerlegt.
    """
    df = _apply_aliases(_normalize_cols(_read_any(Path(path))), ADDR_ALIASES, cols)

    if "zip_label" in df.columns and (cols.postcode not in df.columns or cols.city not in df.columns):
        parts = _clean_str(df["zip_label"]).str.extract(r"^(\d{4})\s+(.+)$")
        if cols.postcode not in df.columns:
            df[cols.postcode] = parts[0]
        if cols.city not in df.columns:
            df[cols.city] = parts[1]

    if cols.lat not in df.columns or cols.lon not in df.columns:
        for e_col, n_col in (("adr_easting", "adr_northing"), ("gkode", "gkodn"), ("e", "n")):
            if e_col in df.columns and n_col in df.columns:
                e = pd.to_numeric(df[e_col], errors="coerce").to_numpy(dtype=float)
                n = pd.to_numeric(df[n_col], errors="coerce").to_numpy(dtype=float)
                df[cols.lat], df[cols.lon] = lv95_to_wgs84(e, n)
                break

    _ensure_columns(df, [cols.street, cols.house_no, cols.postcode, cols.city], "addresses")

    keep = [c for c in cols.all if c in df.columns]
    df = df[keep].copy()
    for c in (cols.street, cols.house_no, cols.postcode, cols.city, cols.canton):
        if c in df.columns:
            df[c] = _clean_str(df[c]).replace("", pd.NA)
    for c in (cols.lat, cols.lon):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=[cols.street, cols.postcode, cols.city]).reset_index(drop=True)

# -------------------------
# 2) Namen lesen
# -------------------------

def read_first_names(path: str | Path, ncols: NameCols = NameCols()) -> pd.DataFrame:
    """
    Vornamen: first_name, freq [, gender, birth_year, canton].
    Unterstützt BFS-Exporte (CSV/XLSX, Lang- oder Breitformat mit Jahren als Spalten).
    Gender -> m/f/x, Kanton -> Kürzel, Jahresbereiche -> Mitte. Totale/unterdrückte Werte entfernt.
    """
    fn = _apply_aliases(_normalize_cols(_read_any(Path(path))), FN_ALIASES, ncols)
    fn = _melt_year_columns(fn, ncols.first_freq, ncols.year)
    _ensure_columns(fn, [ncols.first, ncols.first_freq], "first_names")
    fn[ncols.gender] = normalize_gender(fn[ncols.gender]) if ncols.gender in fn.columns else "x"
    fn[ncols.first] = _clean_str(fn[ncols.first])
    fn[ncols.first_freq] = pd.to_numeric(fn[ncols.first_freq], errors="coerce")
    fn = fn[fn[ncols.first].notna() & ~fn[ncols.first].str.lower().isin(_TOTAL_LABELS)]
    fn = fn[fn[ncols.first_freq] > 0].copy()  # BFS: 'X'/'...' (unterdrückt) und 0 entfernen

    keys = [ncols.first, ncols.gender]
    if ncols.year in fn.columns:
        fn[ncols.year] = _parse_year(fn[ncols.year])
        fn = fn[fn[ncols.year].notna()]
        keys.append(ncols.year)
    fn = _canton_rows(fn, ncols.canton, keys)
    fn = fn.groupby(keys, as_index=False)[ncols.first_freq].sum().astype({ncols.first: str})
    if fn.empty:
        raise ValueError(f"{path}: keine Vornamen nach Bereinigung.")
    return fn


def read_last_names(path: str | Path, ncols: NameCols = NameCols()) -> pd.DataFrame:
    """Nachnamen: last_name, freq [, canton]. Gleiche Format-Toleranz wie Vornamen."""
    ln = _apply_aliases(_normalize_cols(_read_any(Path(path))), LN_ALIASES, ncols)
    _ensure_columns(ln, [ncols.last, ncols.last_freq], "last_names")
    ln[ncols.last] = _clean_str(ln[ncols.last])
    ln[ncols.last_freq] = pd.to_numeric(ln[ncols.last_freq], errors="coerce")
    ln = ln[ln[ncols.last].notna() & ~ln[ncols.last].str.lower().isin(_TOTAL_LABELS)]
    ln = ln[ln[ncols.last_freq] > 0].copy()
    keys = [ncols.last]
    ln = _canton_rows(ln, ncols.canton, keys)
    ln = ln.groupby(keys, as_index=False)[ncols.last_freq].sum().astype({ncols.last: str})
    if ln.empty:
        raise ValueError(f"{path}: keine Nachnamen nach Bereinigung.")
    return ln


def _canton_rows(df: pd.DataFrame, col: str, keys: list[str]) -> pd.DataFrame:
    """Kantonszeilen behalten (Schweiz-Total verwerfen); ohne Kantonsangaben Spalte entfernen."""
    if col not in df.columns:
        return df
    df[col] = normalize_canton(df[col])
    if df[col].notna().any():
        keys.append(col)
        return df[df[col].notna()]
    return df.drop(columns=[col])


def read_ch_names(
    first_names_path: str | Path,
    last_names_path: str | Path,
    ncols: NameCols = NameCols(),
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    return read_first_names(first_names_path, ncols), read_last_names(last_names_path, ncols)

# -------------------------
# 3) Generator
# -------------------------

FamilyType = Literal["single", "couple", "couple_kids", "single_parent"]
FAMILY_TYPES: tuple[FamilyType, ...] = ("single", "couple", "couple_kids", "single_parent")


@dataclass
class GenConfig:
    # Haushaltsmix (wird normiert)
    p_single: float = 0.33
    p_couple: float = 0.22
    p_couple_kids: float = 0.35
    p_single_parent: float = 0.10
    # Kinder pro Haushalt mit Kindern
    kids_min: int = 1
    kids_max: int = 3
    # Altersbänder
    adult_min: int = 20
    adult_max: int = 85
    child_max: int = 19
    # Elternalter bei Geburt des Kindes
    parent_age_at_birth_min: int = 18
    parent_age_at_birth_max: int = 48
    # max. Altersdifferenz im Paar
    couple_age_diff_max: int = 12
    # Anteil gemischtgeschlechtlicher Paare
    p_mixed_couple: float = 0.9
    # Anteil x bei Gender (Vorname dann aus Gesamtpool)
    p_gender_x: float = 0.0
    # Vornamen: Geburtsjahr ± Fenster (bei BFS-Daten nach Jahrgang)
    name_year_window: int = 2
    # Ankerdatum (bei Instanziierung, nicht beim Import)
    today: date = field(default_factory=date.today)

    def __post_init__(self) -> None:
        if not (0 <= self.adult_min < self.adult_max):
            raise ValueError("adult_min must be < adult_max")
        if not (1 <= self.kids_min <= self.kids_max):
            raise ValueError("require 1 <= kids_min <= kids_max")
        if self.parent_age_at_birth_min >= self.parent_age_at_birth_max:
            raise ValueError("parent_age_at_birth_min must be < parent_age_at_birth_max")

    @property
    def family_probs(self) -> np.ndarray:
        p = np.array([self.p_single, self.p_couple, self.p_couple_kids, self.p_single_parent], dtype=float)
        if p.sum() <= 0 or (p < 0).any():
            raise ValueError("invalid household probabilities")
        return p / p.sum()


class NameSampler:
    """
    Ziehung nach Häufigkeit, optional bedingt auf Geschlecht, Geburtsjahr (± Fenster) und Kanton.
    Wahrscheinlichkeiten werden je Bedingung einmal berechnet und gecacht.
    """

    def __init__(self, names: np.ndarray, weights: np.ndarray, genders: Optional[np.ndarray] = None,
                 years: Optional[np.ndarray] = None, cantons: Optional[np.ndarray] = None, year_window: int = 2):
        if len(names) == 0:
            raise ValueError("name table is empty")
        self.names = names
        self.w = np.asarray(weights, float)
        self.genders = genders
        self.years = None if years is None else np.asarray(years, float)
        self.cantons = cantons
        self.window = year_window
        self._uniq_years = None if self.years is None else np.unique(self.years[~np.isnan(self.years)])
        self._cache: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}

    def _dist(self, gender: Optional[str], year: Optional[int], canton: Optional[str]):
        key = (gender if gender in ("m", "f") else None,
               None if self.years is None or year is None else int(year),
               canton if self.cantons is not None else None)
        if key in self._cache:
            return self._cache[key]
        mask = np.ones(len(self.names), bool)
        if key[0] and self.genders is not None:
            gm = np.isin(self.genders, [key[0], "x"])
            mask &= gm if (self.w * gm).sum() > 0 else True
        if key[1] is not None:
            ym = np.abs(self.years - key[1]) <= self.window
            if not (mask & ym).any():  # nächstgelegenes verfügbares Jahr
                ny = self._uniq_years[np.argmin(np.abs(self._uniq_years - key[1]))]
                ym = np.abs(self.years - ny) <= self.window
            mask &= ym
        if key[2] is not None:
            cm = self.cantons == key[2]
            if (mask & cm).any():
                mask &= cm
        idx = np.flatnonzero(mask)
        if idx.size == 0 or self.w[idx].sum() <= 0:
            idx = np.arange(len(self.names))
        p = self.w[idx] / self.w[idx].sum()
        self._cache[key] = (idx, p)
        return idx, p

    def pick(self, r: np.random.Generator, gender: Optional[str] = None, year: Optional[int] = None,
             canton: Optional[str] = None) -> Tuple[str, str]:
        idx, p = self._dist(gender, year, canton)
        i = int(idx[int(r.choice(len(idx), p=p))])
        if gender in ("m", "f"):
            g = gender
        elif self.genders is not None:
            g = str(self.genders[i])
        else:
            g = "x"
        return str(self.names[i]), g


def _dob_from_age(r: np.random.Generator, age_min: float, age_max: float, today: date) -> date:
    """Exaktes Alter in [age_min, age_max] Jahren (gleichverteilt, schaltjahrkorrekt)."""
    age_years = r.uniform(age_min, age_max)
    return today - timedelta(days=int(age_years * DAYS_PER_YEAR))


def _age(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _household_layout(ft: FamilyType, r: np.random.Generator, cfg: GenConfig) -> Tuple[int, int]:
    kids = int(r.integers(cfg.kids_min, cfg.kids_max + 1))
    return {
        "single": (1, 0),
        "couple": (2, 0),
        "single_parent": (1, kids),
        "couple_kids": (2, kids),
    }[ft]


def _adult_gender(r: np.random.Generator, cfg: GenConfig) -> str:
    if r.random() < cfg.p_gender_x:
        return "x"
    return "m" if r.random() < 0.5 else "f"


def generate_people(
    n_people: int,
    addresses: pd.DataFrame,
    first_names: pd.DataFrame,
    last_names: pd.DataFrame,
    addr_cols: Columns = Columns(),
    ncols: NameCols = NameCols(),
    cfg: Optional[GenConfig] = None,
    seed: Optional[int] = 42,
    exact_n: bool = False,
) -> pd.DataFrame:
    """
    Gibt person_id, family_id, first_name, last_name, gender, dob, age, family_type,
    role sowie die Adressspalten zurück.
    exact_n=False: nur vollständige Haushalte (>= n_people Personen, keine abgeschnittenen Familien).
    exact_n=True: genau n_people; der letzte Haushalt wird zu einem passenden Typ verkleinert.
    """
    cfg = cfg or GenConfig()
    out_cols = (["person_id", "family_id", "first_name", "last_name", "gender", "dob", "age",
                 "family_type", "role"] + addr_cols.all)
    if n_people <= 0:
        return pd.DataFrame(columns=out_cols)

    addr = addresses.reset_index(drop=True)
    if addr.empty:
        raise ValueError("Addresses dataframe is empty.")
    addr_records = addr.reindex(columns=addr_cols.all).to_dict("records")

    r = np.random.default_rng(seed)
    col = lambda df, c: df[c].to_numpy() if c in df.columns else None  # noqa: E731
    fn_sampler = NameSampler(
        first_names[ncols.first].to_numpy(),
        _as_weights(first_names[ncols.first_freq]),
        col(first_names, ncols.gender),
        col(first_names, ncols.year),
        col(first_names, ncols.canton),
        year_window=cfg.name_year_window,
    )
    ln_sampler = NameSampler(last_names[ncols.last].to_numpy(), _as_weights(last_names[ncols.last_freq]),
                             cantons=col(last_names, ncols.canton))
    probs = cfg.family_probs

    rows: list[dict] = []
    family_id = 0

    def add(first: str, last: str, gender: str, dob: date, ft: FamilyType, role: str, a: dict) -> None:
        rows.append({
            "person_id": len(rows) + 1,
            "family_id": family_id,
            "first_name": first,
            "last_name": last,
            "gender": gender,
            "dob": dob,
            "age": _age(dob, cfg.today),
            "family_type": ft,
            "role": role,
            **a,
        })

    while len(rows) < n_people:
        family_id += 1
        ft: FamilyType = FAMILY_TYPES[int(r.choice(len(FAMILY_TYPES), p=probs))]
        n_adults, n_kids = _household_layout(ft, r, cfg)

        if exact_n:
            remaining = n_people - len(rows)
            if n_adults + n_kids > remaining:
                if remaining == 1:
                    ft, n_adults, n_kids = "single", 1, 0
                elif ft in ("couple_kids", "single_parent"):
                    n_kids = remaining - n_adults
                    if n_kids < 1:
                        ft, n_adults, n_kids = "couple", 2, 0
                else:
                    n_adults = remaining

        a = addr_records[int(r.integers(len(addr_records)))]
        canton = a.get(addr_cols.canton)
        canton = canton if isinstance(canton, str) and canton else None
        family_last, _ = ln_sampler.pick(r, canton=canton)

        # Alter: bei Kindern muss das jüngste Elternteil alt genug sein
        adult_lo, adult_hi = cfg.adult_min, cfg.adult_max
        if n_kids:
            adult_lo = max(adult_lo, cfg.parent_age_at_birth_min + 1)
            adult_hi = min(adult_hi, cfg.parent_age_at_birth_max + cfg.child_max)
        first_age = r.uniform(adult_lo, adult_hi + 1)
        ages = [first_age]
        if n_adults == 2:
            lo = max(adult_lo, first_age - cfg.couple_age_diff_max)
            hi = min(adult_hi + 1, first_age + cfg.couple_age_diff_max)
            ages.append(r.uniform(lo, hi))

        g1 = _adult_gender(r, cfg)
        genders = [g1]
        if n_adults == 2:
            if g1 in ("m", "f") and r.random() < cfg.p_mixed_couple:
                genders.append("f" if g1 == "m" else "m")
            else:
                genders.append(_adult_gender(r, cfg))

        for age, g in zip(ages, genders):
            dob = _dob_from_age(r, age, age, cfg.today)
            first, g_eff = fn_sampler.pick(r, g, dob.year, canton)
            add(first, family_last, g_eff, dob, ft, "adult", a)

        # Kinder: Elternalter bei Geburt in [min, max] bzgl. jüngstem Elternteil
        youngest = min(ages)
        kid_lo = max(0.0, youngest - cfg.parent_age_at_birth_max)
        kid_hi = min(cfg.child_max + 1, youngest - cfg.parent_age_at_birth_min)
        for _ in range(n_kids):
            g = "m" if r.random() < 0.5 else "f"
            dob = _dob_from_age(r, kid_lo, kid_hi, cfg.today)
            first, g_eff = fn_sampler.pick(r, g, dob.year, canton)
            add(first, family_last, g_eff, dob, ft, "child", a)

    return pd.DataFrame(rows, columns=out_cols)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Synthetische CH-Personen erzeugen")
    ap.add_argument("--addresses", default="addresses.csv")
    ap.add_argument("--first-names", default="first_names.csv")
    ap.add_argument("--last-names", default="last_names.csv")
    ap.add_argument("-n", "--n-people", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--exact", action="store_true", help="genau n Personen")
    ap.add_argument("-o", "--out", default="synthetic_people.parquet")
    args = ap.parse_args()

    people = generate_people(
        n_people=args.n_people,
        addresses=read_ch_addresses(args.addresses),
        first_names=(names := read_ch_names(args.first_names, args.last_names))[0],
        last_names=names[1],
        seed=args.seed,
        exact_n=args.exact,
    )
    print(people.head())
    if args.out.endswith((".parquet", ".pq")):
        people.to_parquet(args.out, index=False)
    else:
        people.to_csv(args.out, index=False)
