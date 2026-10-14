"""
Echte Adressen aus dem amtlichen Gebäudeadressverzeichnis (swisstopo, OGD).

Quelle: data.geo.admin.ch, Datensatz ch.swisstopo.amtliches-gebaeudeadressverzeichnis
Lizenz: Open Government Data, freie Nutzung, Quellenangabe Pflicht («Quelle: swisstopo»).

Beispiele:
    python ies_ng_adressen.py --download                      # Register nach data/ laden
    python ies_ng_adressen.py --canton BE -o adressen_be.csv  # Auszug erstellen
    python ies_ng_adressen.py --plz 3011 3012 -o bern.csv
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from synthetic_people import Columns, lv95_to_wgs84

STAC_ITEMS = ("https://data.geo.admin.ch/api/stac/v0.9/collections/"
              "ch.swisstopo.amtliches-gebaeudeadressverzeichnis/items")
DATA_DIR = Path(__file__).resolve().parent / "data"
REGISTER_GLOB = "amtliches-gebaeudeadressverzeichnis*.csv*"

RAW_COLS = ["STN_LABEL", "ADR_NUMBER", "ZIP_LABEL", "COM_NAME", "COM_CANTON", "ADR_STATUS",
            "BDG_CATEGORY", "ADR_EASTING", "ADR_NORTHING", "EGAID", "BDG_EGID"]


def download_register(dest: Path = DATA_DIR) -> Path:
    """Lädt die aktuelle CSV (LV95) über die STAC-API von data.geo.admin.ch."""
    dest.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(STAC_ITEMS, timeout=60) as r:
        items = json.load(r)["features"]
    hrefs = [a["href"] for it in items for a in it["assets"].values()
             if a["href"].endswith(".csv.zip") and "_ch" in a["href"]]
    if not hrefs:
        raise RuntimeError(f"keine CSV im STAC-Katalog gefunden: {STAC_ITEMS}")
    url = sorted(hrefs, key=lambda h: ("2056" not in h, h))[0]
    out = dest / Path(url).name
    print(f"Download {url} -> {out}")
    urllib.request.urlretrieve(url, out)
    return out


def find_register(dest: Path = DATA_DIR) -> Optional[Path]:
    hits = sorted(dest.glob(REGISTER_GLOB))
    return hits[-1] if hits else None


def is_register(path: Path) -> bool:
    head = pd.read_csv(path, sep=";", nrows=0, dtype=str, encoding="utf-8-sig")
    return {"STN_LABEL", "ADR_NUMBER", "ZIP_LABEL"} <= {c.upper() for c in head.columns}


def load_register(
    path: str | Path,
    cantons: Optional[Iterable[str]] = None,
    postcodes: Optional[Iterable[str]] = None,
    municipalities: Optional[Iterable[str]] = None,
    residential_only: bool = False,
    cols: Columns = Columns(),
) -> pd.DataFrame:
    """
    Liest das Register (CSV oder CSV.ZIP, ';'-getrennt) und gibt Standardspalten zurück.
    Adressen werden unverändert übernommen (nur Leerzeichen getrimmt); nur Status «real/existing».
    """
    path = Path(path)
    head = pd.read_csv(path, sep=";", nrows=0, dtype=str, encoding="utf-8-sig")
    upper = {c.upper(): c for c in head.columns}
    use = [upper[c] for c in RAW_COLS if c in upper]
    df = pd.read_csv(path, sep=";", dtype=str, usecols=use, encoding="utf-8-sig", keep_default_na=False)
    df.columns = [c.upper() for c in df.columns]
    df = df.apply(lambda s: s.str.strip())

    if "ADR_STATUS" in df:
        st = df["ADR_STATUS"].str.lower()
        df = df[st.isin(["real", "existing", "bestehend", "existant", "esistente", ""])]
    if residential_only and "BDG_CATEGORY" in df:
        cat = df["BDG_CATEGORY"].str.lower()
        mask = cat.str.contains("resid|wohn|habit|abitat", regex=True)
        if mask.any():
            df = df[mask]
        else:
            print("Hinweis: BDG_CATEGORY ohne Wohn-Kategorie erkannt, Filter ignoriert.")

    zip_parts = df["ZIP_LABEL"].str.extract(r"^(\d{4})\s+(.+)$")
    out = pd.DataFrame({
        cols.street: df["STN_LABEL"],
        cols.house_no: df["ADR_NUMBER"],
        cols.postcode: zip_parts[0],
        cols.city: zip_parts[1],
        cols.canton: df.get("COM_CANTON", ""),
    })
    if "COM_NAME" in df:
        out["municipality"] = df["COM_NAME"]
    if "EGAID" in df:
        out["egaid"] = df["EGAID"]
    if {"ADR_EASTING", "ADR_NORTHING"} <= set(df.columns):
        e = pd.to_numeric(df["ADR_EASTING"], errors="coerce").to_numpy(float)
        n = pd.to_numeric(df["ADR_NORTHING"], errors="coerce").to_numpy(float)
        out[cols.lat], out[cols.lon] = lv95_to_wgs84(e, n)

    if cantons:
        out = out[out[cols.canton].str.upper().isin([c.upper() for c in cantons])]
    if postcodes:
        out = out[out[cols.postcode].isin([str(p) for p in postcodes])]
    if municipalities:
        m = {x.lower() for x in municipalities}
        out = out[out[cols.city].str.lower().isin(m) | out.get("municipality", out[cols.city]).str.lower().isin(m)]

    # Nur vollständige Adressen (mit Hausnummer)
    out = out[(out[cols.street] != "") & (out[cols.house_no] != "") & out[cols.postcode].notna()]
    return out.drop_duplicates(subset=[cols.street, cols.house_no, cols.postcode]).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Amtliches Gebäudeadressverzeichnis laden/filtern")
    ap.add_argument("--download", action="store_true", help="aktuelles Register nach data/ laden")
    ap.add_argument("-i", "--input", help="Register-Datei (Default: neueste in data/)")
    ap.add_argument("--canton", nargs="*")
    ap.add_argument("--plz", nargs="*")
    ap.add_argument("--gemeinde", nargs="*")
    ap.add_argument("--wohngebaeude", action="store_true", help="nur Wohngebäude")
    ap.add_argument("-o", "--out", help="Auszug als CSV schreiben")
    a = ap.parse_args()

    src = download_register() if a.download else Path(a.input) if a.input else find_register()
    if src is None:
        raise SystemExit("Kein Register gefunden: --download oder -i <datei> angeben.")
    if a.out:
        df = load_register(src, a.canton, a.plz, a.gemeinde, a.wohngebaeude)
        df.to_csv(a.out, index=False, sep=";", encoding="utf-8-sig")
        print(f"{len(df)} Adressen -> {a.out}  (Quelle: swisstopo)")


if __name__ == "__main__":
    main()
