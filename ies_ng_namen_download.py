"""
Download der BFS-Namensstatistiken für die IES-NG-Übungskarten.

Ziel (in data/, dort findet ies_ng_karten.py die Dateien automatisch):
    data/vornamen_bfs.<csv|xlsx>    Vornamen der ständigen Wohnbevölkerung nach Geburtsjahr und Geschlecht
    data/nachnamen_bfs.<csv|xlsx>   Nachnamen der ständigen Wohnbevölkerung nach Kanton
    data/*.source.json              Herkunft (Datensatz, URL, Datum) für die Quellenangabe

Quellen:
    1. opendata.swiss (CKAN-API): sucht die aktuellen BFS-Datensätze und wählt die passende Ressource
    2. BFS STAT-TAB (PXWeb-API): --px-vornamen / --px-nachnamen mit Tabellen-ID aus der STAT-TAB-URL
    3. Direkte URL: --url-vornamen / --url-nachnamen

Nach dem Download wird jede Datei eingelesen und geprüft (Zeilen, Geschlecht, Jahrgang, Kanton).

Beispiele:
    python ies_ng_namen_download.py                    # automatisch über opendata.swiss
    python ies_ng_namen_download.py --list             # Kandidaten anzeigen, nichts laden
    python ies_ng_namen_download.py --px-vornamen px-x-0102020000_101
    python ies_ng_namen_download.py --url-nachnamen https://.../nachnamen.csv
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from synthetic_people import read_first_names, read_last_names

DATA_DIR = Path(__file__).resolve().parent / "data"
CKAN = "https://ckan.opendata.swiss"
PXWEB = "https://www.pxweb.bfs.admin.ch/api/v1/de"
UA = {"User-Agent": "ies-ng-uebungskarten/1.0 (Ausbildung BABS)"}
FORMAT_RANK = {"CSV": 0, "XLSX": 1, "XLS": 2, "PX": 3}


@dataclass(frozen=True)
class Spec:
    kind: str
    queries: tuple[str, ...]
    must: tuple[str, ...]      # mind. ein Begriff muss vorkommen
    prefer: tuple[str, ...]    # Pluspunkte
    avoid: tuple[str, ...]     # Abzug (falsche Grundgesamtheit)


SPECS = {
    "vornamen": Spec(
        "vornamen",
        ("Vornamen Geburtsjahr", "Vornamen Bevölkerung", "Vornamen ständige Wohnbevölkerung",
         "prénoms année de naissance"),
        ("vorname", "prénom", "prenom"),
        ("geburtsjahr", "jahrgang", "année de naissance", "ständige wohnbevölkerung", "geschlecht"),
        ("neugeboren", "nouveau-né", "nouveau-nés", "babynamen", "geburten"),
    ),
    "nachnamen": Spec(
        "nachnamen",
        ("Nachnamen Kanton", "Nachnamen Bevölkerung", "noms de famille canton"),
        ("nachname", "nom de famille", "noms de famille"),
        ("kanton", "canton", "ständige wohnbevölkerung"),
        (),
    ),
}


# -------------------------
# HTTP
# -------------------------

def _get_json(url: str, data: Optional[bytes] = None) -> dict:
    req = urllib.request.Request(url, data=data, headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8-sig"))


def _download(url: str, dest: Path, data: Optional[bytes] = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, data=data, headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dest)
    return dest


def _text(v) -> str:
    """CKAN-Felder sind teils mehrsprachig {'de':..,'fr':..}."""
    if isinstance(v, dict):
        return " ".join(str(x) for x in v.values() if x)
    return str(v or "")


# -------------------------
# opendata.swiss (CKAN)
# -------------------------

@dataclass
class Candidate:
    score: float
    dataset: str
    resource: str
    fmt: str
    url: str
    modified: str
    gender: Optional[str] = None   # BFS veröffentlicht Vornamen je Geschlecht separat
    year: Optional[str] = None     # Stichjahr aus dem Titel, z. B. '2025'


_GENDER_RE = {
    "f": re.compile(r"\b(weiblich\w*|féminin\w*|feminin\w*|femminil\w*|female|frauen)\b", re.I),
    "m": re.compile(r"\b(männlich\w*|maennlich\w*|masculin\w*|maschil\w*|male|männer)\b", re.I),
}


def _gender_of(text: str) -> Optional[str]:
    hits = [g for g, rx in _GENDER_RE.items() if rx.search(text)]
    return hits[0] if len(hits) == 1 else None


def ckan_candidates(spec: Spec, ckan: str = CKAN) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for q in spec.queries:
        url = f"{ckan}/api/3/action/package_search?" + urllib.parse.urlencode({"q": q, "rows": 50})
        try:
            res = _get_json(url)["result"]["results"]
        except Exception as e:  # noqa: BLE001
            print(f"  Suche '{q}' fehlgeschlagen: {e}", file=sys.stderr)
            continue
        for pkg in res:
            org = _text(pkg.get("organization", {}).get("title")) + " " + _text(pkg.get("organization", {}).get("name"))
            if not re.search(r"statisti|bfs|ofs|ust", org, re.I):
                continue
            ptitle = _text(pkg.get("title"))
            for rsc in pkg.get("resources", []):
                rurl = rsc.get("download_url") or rsc.get("url") or ""
                fmt = (rsc.get("format") or Path(urllib.parse.urlparse(rurl).path).suffix.lstrip(".")).upper()
                if not rurl or rurl in seen or fmt not in FORMAT_RANK:
                    continue
                seen.add(rurl)
                text = f"{ptitle} {_text(rsc.get('title'))} {_text(rsc.get('name'))} {_text(pkg.get('description'))}"
                low = text.lower()
                if not any(m in low for m in spec.must):
                    continue
                score = (2.0 * sum(p in low for p in spec.prefer) - 5.0 * sum(a in low for a in spec.avoid)
                         - 0.5 * FORMAT_RANK[fmt])
                yr = re.search(r"\b(20\d\d)\b", ptitle)
                out.append(Candidate(score, ptitle.strip()[:90], _text(rsc.get("title")).strip()[:60], fmt, rurl,
                                     rsc.get("last_modified") or rsc.get("modified") or pkg.get("metadata_modified")
                                     or "", _gender_of(f"{ptitle} {_text(rsc.get('title'))}"),
                                     yr.group(1) if yr else None))
    out.sort(key=lambda c: c.modified, reverse=True)  # neueste zuerst ...
    return sorted(out, key=lambda c: -c.score)          # ... dann stabil nach Punktzahl


# -------------------------
# BFS STAT-TAB (PXWeb)
# -------------------------

def px_download(table: str, dest: Path, pxweb: str = PXWEB) -> Path:
    """Ganze PX-Tabelle als CSV (alle Werte aller Dimensionen)."""
    table = table.removesuffix(".px")
    url = f"{pxweb}/{table}/{table}.px"
    meta = _get_json(url)
    query = {"query": [{"code": v["code"], "selection": {"filter": "all", "values": ["*"]}}
                       for v in meta["variables"]],
             "response": {"format": "csv"}}
    print(f"  STAT-TAB {table}: {', '.join(v['text'] for v in meta['variables'])}")
    return _download(url, dest, json.dumps(query).encode())


# -------------------------
# Ablauf
# -------------------------

def _ext_from(url: str, fmt: str) -> str:
    suf = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suf if suf in (".csv", ".xlsx", ".xls") else {"CSV": ".csv", "XLSX": ".xlsx", "XLS": ".xls"}.get(fmt, ".csv")


def _clear_old(kind: str, data_dir: Path) -> None:
    for old in data_dir.glob(f"{kind}_bfs.*"):
        old.unlink()


def pick_by_gender(cands: list[Candidate]) -> list[Candidate]:
    """Bester Kandidat je Geschlecht, möglichst gleiches Stichjahr; sonst nur der beste insgesamt."""
    by_g = {g: [c for c in cands if c.gender == g] for g in ("m", "f")}
    if not (by_g["m"] and by_g["f"]):
        return cands[:1]
    for c in sorted(by_g["m"] + by_g["f"], key=lambda c: (-c.score, -int(c.year or 0))):
        other = "f" if c.gender == "m" else "m"
        match = next((o for o in by_g[other] if o.year == c.year), None)
        if match:
            return [c, match] if c.gender == "m" else [match, c]
    return [by_g["m"][0], by_g["f"][0]]


def merge_gendered(parts: list[tuple[str, Path]], dest: Path) -> Path:
    """Vornamen-Dateien je Geschlecht zu einer Datei mit Spalte 'gender' zusammenführen."""
    import pandas as pd
    frames = []
    for g, p in parts:
        df = pd.read_csv(p, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
        df["gender"] = g
        frames.append(df)
        p.unlink()
    pd.concat(frames, ignore_index=True).to_csv(dest, index=False, encoding="utf-8")
    return dest


def validate(kind: str, path: Path) -> bool:
    try:
        if kind == "vornamen":
            df = read_first_names(path)
            yrs = (f"{int(df['birth_year'].min())}–{int(df['birth_year'].max())}"
                   if "birth_year" in df else "FEHLT")
            print(f"  OK {path.name}: {df['first_name'].nunique()} Vornamen, "
                  f"Geschlecht {sorted(df['gender'].unique())}, Jahrgänge {yrs}")
            if "birth_year" not in df:
                print("  Warnung: ohne Geburtsjahr -> Vornamen werden unabhängig vom Alter gezogen.")
        else:
            df = read_last_names(path)
            kt = df["canton"].nunique() if "canton" in df else 0
            print(f"  OK {path.name}: {df['last_name'].nunique()} Nachnamen, "
                  f"{kt or 'keine'} Kantone")
            if not kt:
                print("  Warnung: ohne Kanton -> Nachnamen national gezogen.")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  FEHLER beim Einlesen von {path.name}: {e}")
        return False


def fetch(kind: str, args: argparse.Namespace) -> Optional[Path]:
    print(f"== {kind}")
    data_dir = Path(args.data_dir)
    url, px = getattr(args, f"url_{kind}"), getattr(args, f"px_{kind}")
    source: dict = {"kind": kind, "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "attribution": "Quelle: Bundesamt für Statistik (BFS)"}
    try:
        if px:
            _clear_old(kind, data_dir)
            dest = px_download(px, data_dir / f"{kind}_bfs.csv", args.pxweb)
            source.update(method="pxweb", table=px, url=f"{args.pxweb}/{px}/{px}.px")
        elif url:
            _clear_old(kind, data_dir)
            dest = _download(url, data_dir / f"{kind}_bfs{_ext_from(url, '')}")
            source.update(method="url", url=url)
        else:
            cands = ckan_candidates(SPECS[kind], args.ckan)
            if not cands:
                print("  Keine passende Ressource auf opendata.swiss gefunden.\n"
                      "  -> Tabellen-ID aus STAT-TAB (--px-" + kind + ") oder direkte URL (--url-" + kind + ").")
                return None
            for c in cands[: args.show]:
                print(f"  [{c.score:+.1f}] {c.fmt:<4} {c.gender or '-'} {c.dataset} | {c.resource}\n"
                      f"         {c.url}")
            if args.list:
                return None
            picks = pick_by_gender(cands) if kind == "vornamen" else cands[:1]
            if len(picks) == 2 and all(c.fmt == "CSV" for c in picks):
                _clear_old(kind, data_dir)
                parts = []
                for c in picks:
                    print(f"  -> lade ({c.gender}): {c.dataset} ({c.fmt})")
                    parts.append((c.gender, _download(c.url, data_dir / f"{kind}_bfs_{c.gender}.part.csv")))
                dest = merge_gendered(parts, data_dir / f"{kind}_bfs.csv")
                source.update(method="ckan", resources=[
                    {"gender": c.gender, "dataset": c.dataset, "resource": c.resource, "url": c.url,
                     "modified": c.modified} for c in picks])
            else:
                best = picks[0]
                print(f"  -> lade: {best.dataset} ({best.fmt})")
                if kind == "vornamen" and best.gender:
                    print("  Warnung: nur ein Geschlecht gefunden.")
                _clear_old(kind, data_dir)
                dest = _download(best.url, data_dir / f"{kind}_bfs{_ext_from(best.url, best.fmt)}")
                source.update(method="ckan", dataset=best.dataset, resource=best.resource, url=best.url,
                              modified=best.modified)
    except Exception as e:  # noqa: BLE001
        print(f"  Download fehlgeschlagen: {e}")
        return None

    (data_dir / f"{kind}_bfs.source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), "utf-8")
    return dest if validate(kind, dest) else None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="BFS-Namensstatistiken herunterladen und prüfen")
    ap.add_argument("--only", choices=["vornamen", "nachnamen"], help="nur eine Datei")
    ap.add_argument("--list", action="store_true", help="nur Kandidaten auf opendata.swiss anzeigen")
    ap.add_argument("--show", type=int, default=5, help="Anzahl angezeigter Kandidaten")
    ap.add_argument("--url-vornamen")
    ap.add_argument("--url-nachnamen")
    ap.add_argument("--px-vornamen", help="STAT-TAB Tabellen-ID, z. B. px-x-0102020000_101")
    ap.add_argument("--px-nachnamen", help="STAT-TAB Tabellen-ID")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--ckan", default=CKAN, help=argparse.SUPPRESS)
    ap.add_argument("--pxweb", default=PXWEB, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    kinds = [args.only] if args.only else ["vornamen", "nachnamen"]
    results = {k: fetch(k, args) for k in kinds}
    if args.list:
        return 0
    ok = all(results.values())
    print("\nFertig: " + ", ".join(f"{k}={'ok' if v else 'fehlt'}" for k, v in results.items()))
    if ok:
        print("Karten erzeugen: python ies_ng_karten.py -n 50 --layout a4")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
