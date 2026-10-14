# IES NG – Übungskarten (DIN A6)

Ausbildungsmaterial mit fiktiven Personen: Schweizer ID (Vorder-/Rückseite, MRZ TD1) und fortlaufender QR-Code.

## Aufbau einer Karte (105 × 148 mm)
1. CI-Kopf: Bundeslogo (vereinfacht oder `--logo`), «Bundesamt für Bevölkerungsschutz BABS», «Ausbildung IES NG»
2. ID Vorderseite, Massstab 1:1 (85.6 × 54 mm, ID-1)
3. ID Rückseite mit MRZ: 3 × 30 Zeichen, Teilung 2.54 mm, Zeilenabstand 4.23 mm, weisse Zone ohne Wasserzeichen
4. Fuss: Kartennummer, Name, Wohnadresse, Hinweis «fiktiv»; QR unten rechts

Alle IDs tragen «SPECIMEN», Dokumentnummern beginnen mit `X` (fiktiv).

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
| `--qr-format` | `(dc\|{id}\|{id})` | Payload wie CHA-Etiketten |
| `--qr-error` | m | ECC (L/M/Q; H passt nicht in Version 2) |
| `--layout` | a6 | `a6` oder `a4` (4-up) |
| `--p-invalid-mrz` | 0 | Anteil falscher Prüfziffern (Feld in Lösungsliste) |
| `--p-expired` | 0 | Anteil abgelaufener Ausweise |
| `--adults-only` | aus | nur Erwachsene |
| `--addresses/--first-names/--last-names` | Demo-Daten | echte Register (siehe `synthetic_people.py`) |
| `--logo`, `--font-*` | gezeichnet / Liberation / DejaVu Mono | CI-Assets |

## Umsetzung der Erkenntnisse (`QR_MRZ_Erkenntnisse.md`)
| Erkenntnis | Umsetzung |
|---|---|
| QR Version 2, Byte-Modus, `(dc\|id\|label)` | `segno`, fix Version 2, Payload konfigurierbar |
| ECC unbestimmt | `--qr-error`, Default M |
| MRZ TD1, 7-3-1, Gesamtprüfziffer | `ies_ng_mrz.py`, gegen Specimen (Dok.-Nr. 9, Geb. 5) und Lib `mrz` geprüft |
| Specimen-MRZ ungültig | nicht verwendet; Negativfälle gezielt via `--p-invalid-mrz` |
| Namen | ICAO-Transliteration: Ä→AE, Ö→OE, Ü→UE, Akzente weg, `-`/Leerzeichen → `<` |
| Laserbild «Jahr / Dok.-Nr.», vertikale Seriennummer | nachgebildet, Serie `..TRNG<nr>` (fiktiv) |

## Verifikation (2000 Karten, A4)
- QR: 2000/2000 dekodiert (zxing-cpp, 300 dpi), Reihenfolge korrekt
- MRZ: Prüfziffern = Lösungsliste = Lib `mrz`; Ausstellung ≥ Geburt, Ablauf > Ausstellung
- OCR der MRZ nicht getestet (kein Tesseract)

## Offen
1. **OCR-B-Schrift** in `fonts/` ablegen; ohne sie ist die MRZ für Menschen lesbar, für Lesegeräte nur bedingt
2. **CI**: offizielles Logo (`--logo`) und Frutiger einsetzen; Farbe Rot `#DC0018` prüfen
3. QR-Präfix `dc` und ECC-Stufe mit Zielsystem klären (siehe Erkenntnisse)
4. Ablauf-Prüfziffer Specimen gegen fedpol-Spezifikation prüfen
