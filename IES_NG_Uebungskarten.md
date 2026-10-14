# IES NG – Übungskarten (DIN A6)

Ausbildungsmaterial mit fiktiven Personen: Schweizer ID (Vorder-/Rückseite, MRZ TD1) und fortlaufender QR-Code.

## Aufbau einer Karte (105 × 148 mm)
1. CI-Kopf: Bundeslogo (vereinfacht oder `--logo`), «Bundesamt für Bevölkerungsschutz BABS», «Ausbildung IES NG»
2. ID Vorderseite, Massstab 1:1 (85.6 × 54 mm, ID-1)
3. ID Rückseite mit MRZ: 3 × 30 Zeichen, Teilung 2.54 mm, Zeilenabstand 4.23 mm, weisse Zone ohne Wasserzeichen
4. Fuss: Kartennummer, Name, Wohnadresse, ggf. Verletzungsmuster, Hinweis «fiktiv»; Prä-Triage-Feld und QR unten rechts

Alle IDs tragen «SPECIMEN», Dokumentnummern beginnen mit `X` (fiktiv).

## Originalgrösse
- ID im PDF exakt 85.6 × 54 mm (ISO/IEC 7810 ID-1), gemessen in A6- und A4-Layout
- PDF-Vorgabe «PrintScaling = None»: Druckdialog startet mit tatsächlicher Grösse
- **Drucken mit 100 % / «Tatsächliche Grösse»**, nie «An Seite anpassen»
  (A6-PDF auf A4 angepasst = 141 %; A4 mit Rand-Anpassung ≈ 94–97 %)
- Kontrolle: Kontrollmass links neben der Vorderseite muss nachgemessen 50 mm sein
- Für A4-Drucker `--layout a4` verwenden, dann mit Papierschneider auf A6 schneiden

## Nutzung
```bash
pip install -r requirements.txt
python ies_ng_karten.py -n 40                       # CHY0001–CHY0040, 1 Karte/Seite A6
python ies_ng_karten.py -n 200 --layout a4          # 4 Karten/A4 mit Schnittlinien
python ies_ng_karten.py -n 50 --start 151           # CHY0151–CHY0200
python ies_ng_karten.py -n 100 --p-invalid-mrz 0.1 --p-expired 0.05   # Negativfälle
python ies_ng_karten.py @karten.args                # Argumente aus Datei (1 pro Zeile)
```
Ausgabe: `ies_ng_karten.pdf` + `ies_ng_karten_loesungen.csv` (Lösungsliste, `;`-getrennt).

### Wichtige Optionen
| Option | Default | Zweck |
|---|---|---|
| `-n/--count` | 20 | Anzahl Karten |
| `--start` | 1 | erste Nummer |
| `--prefix`, `--digits`, `--max-number` | CHY, 4, 2000 | Nummernkreis CHY0001–CHY2000 (Überschreitung = Abbruch) |
| `--qr-format` | `{id}` | Payload nur Kartennummer (z. B. `CHY0003`); CHA-Format `(dc\|{id}\|{id})` wird von der IES-NG-App als `DCCHY0003CHY0003` gelesen |
| `--qr-error` | m | ECC (L/M/Q; H passt nicht in Version 2) |
| `--layout` | a6 | `a6` oder `a4` (4-up) |
| `--p-invalid-mrz` | 0 | Anteil falscher Prüfziffern (Feld in Lösungsliste) |
| `--p-expired` | 0 | Anteil abgelaufener Ausweise |
| `--adults-only` | aus | nur Erwachsene |
| `--p-red`, `--p-yellow` | 0.15, 0.30 | Prä-Triage Rot/Gelb, Rest Grün (0.55) |
| `--p-red-pattern` | 0.40 | Anteil Roter mit genau einem Verletzungsmuster |
| `--addresses/--first-names/--last-names` | Demo-Daten | echte Register (siehe `synthetic_people.py`) |
| `--logo`, `--font-*` | gezeichnet / Liberation / DejaVu Mono | CI-Assets |

## Prä-Triage
- Verteilung exakt nach Anteilen (Methode der grössten Reste), Karten zufällig zugeordnet
- 40 % der Roten erhalten **genau ein** zufälliges Verletzungsmuster:
  behebbare Atemwegsverlegung, arterielle Blutung, Verbrennung Grad 2–3 > 60 % KOF, Schnappatmung
- Bei wenigen Roten wird der Rest zufällig gerundet (Erwartungswert 40 %)
- Lösungsliste: Spalten `triage`, `injury_pattern`

## Umsetzung der Erkenntnisse (`QR_MRZ_Erkenntnisse.md`)
| Erkenntnis | Umsetzung |
|---|---|
| QR Version 2, Byte-Modus, `(dc\|id\|label)` | `segno`, fix Version 2; Payload `{id}`, da die App das CHA-Format nicht auf die ID reduziert |
| ECC unbestimmt | `--qr-error`, Default M |
| MRZ TD1, 7-3-1, Gesamtprüfziffer | `ies_ng_mrz.py`, gegen Specimen (Dok.-Nr. 9, Geb. 5) und Lib `mrz` geprüft |
| Specimen-MRZ ungültig | nicht verwendet; Negativfälle gezielt via `--p-invalid-mrz` |
| Namen | ICAO-Transliteration: Ä→AE, Ö→OE, Ü→UE, Akzente weg, `-`/Leerzeichen → `<` |
| Laserbild «Jahr / Dok.-Nr.», vertikale Seriennummer | nachgebildet, Serie `..TRNG<nr>` (fiktiv) |

## Verifikation (2000 Karten, A4)
- QR: 2000/2000 dekodiert (zxing-cpp, 300 dpi), Reihenfolge korrekt
- MRZ: Prüfziffern = Lösungsliste = Lib `mrz`; Ausstellung ≥ Geburt, Ablauf > Ausstellung
- Prä-Triage (2000 Karten): 300 Rot / 600 Gelb / 1100 Grün, 120 Rote mit Muster
- MRZ-Schrift: OCR-B (OFL, `fonts/OCR-B.ttf`); OCR mit Lesegerät nicht getestet

## Offen
1. **CI**: offizielles Logo (`--logo`) und Frutiger einsetzen; Farbe Rot `#DC0018` prüfen
2. QR-Präfix `dc` und ECC-Stufe mit Zielsystem klären (siehe Erkenntnisse)
3. Ablauf-Prüfziffer Specimen gegen fedpol-Spezifikation prüfen
