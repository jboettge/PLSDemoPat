# IES NG – Übungskarten (DIN A6)

Ausbildungsmaterial mit fiktiven Personen: Schweizer ID (Vorder-/Rückseite, MRZ TD1) und fortlaufender QR-Code.

## Aufbau einer Karte (105 × 148 mm)
1. CI-Kopf: Bundeslogo (vereinfacht oder `--logo`), «Bundesamt für Bevölkerungsschutz BABS», «Ausbildung IES NG»
2. ID Vorderseite, Massstab 1:1 (85.6 × 54 mm, ID-1), Layout Identitätskarte 2023
3. ID Rückseite mit MRZ: 3 × 30 Zeichen, Teilung 2.54 mm, Zeilenabstand 4.23 mm, ruhiger heller Grund
4. Fuss: Kartennummer, Name, Wohnadresse, ggf. Verletzungsmuster, Hinweis «fiktiv»; Prä-Triage-Feld und QR unten rechts

Passfoto: comicartiges Vektor-Porträt passend zu Alter und Geschlecht (`ies_ng_avatar.py`), pro Karte reproduzierbar (Seed + Kartennummer),
wie beim Original in Graustufen.

## Layout Identitätskarte 2023
Vorlage: fedpol-Muster «Front/Back of the Swiss identity card as of 3 March 2023» (Wikimedia Commons, CC BY 3.0 CH).
- Farbset: hellblauer Verlauf, blaue Guilloche, Höhenlinien, Pizzo Rotondo (blau), Dreiecks-Gebirge grün/blau,
  Feldbezeichnungen blau (`#2C68C9`), Daten schwarz in Monospace, Sprachen mit ▪ getrennt, ▲ als Feldende
- Vorderseite: Kopfzeile «SCHWEIZ SUISSE SVIZZERA SVIZRA SWITZERLAND», Kreuz + Dokumentbezeichnung, Dokumentnummer
  oben rechts; Foto links, darunter Mikroschrift und Unterschrift; rechts Name, Vorname(n), Geschlecht/Nationalität,
  Geburtsdatum/Gültig bis; Fenster mit Geisterbild
- Rückseite: Heimatort (mit Kanton), Grösse; Fenster, unscharfes Feld Ablaufjahr/Dokumentnummer, goldener Tropfen,
  senkrechte Seriennummer; Band Ausgestellt am/Behörde; MRZ-Zone mit Kantonskürzeln als blasse Konturschrift
- Sicherheitsmerkmale nur stilisiert angedeutet; Hintergründe als PDF-Form je Datei nur einmal gespeichert
- Daten-Schrift: `--font-mono` (Default DejaVu Sans Mono / Consolas)
Alle IDs tragen «SPECIMEN», Dokumentnummern beginnen mit `X` (fiktiv).

## PNG-Export (Android-Emulator)
```bash
python ies_ng_karten.py -n 50 --png                          # png/CHY0001_card.png, _qr.png, _mrz.png
python ies_ng_karten.py -n 50 --png emulator --png-parts qr mrz back
```
| Teil | Inhalt | Zweck |
|---|---|---|
| `card` | ganze A6-Karte (300 dpi) | Gesamtansicht |
| `front`, `back` | ID-Seite freigestellt, weisser Rand | Ausweis scannen |
| `mrz` | nur MRZ, weisser Rand | MRZ-Erkennung |
| `qr` | nur QR (`segno`, Ruhezone 6 Module) | QR-Scan |

Teile werden **freigestellt** auf weissem Grund gerendert (keine Nachbarelemente, die den Scanner stören).
Optionen: `--png-dpi` (300), `--png-crop-zoom` (2 → 600 dpi für front/back/mrz), `--png-margin` (6 mm).
Benötigt `pymupdf`.

Im Emulator hinterlegen (Android Studio, Bezeichnungen je nach Version leicht abweichend):
1. AVD bearbeiten → *Advanced Settings* → Camera *Back* = **VirtualScene**
2. Emulator starten → *Extended Controls* (`…`) → **Camera** → *Virtual scene images*: PNG für *Wall* bzw. *Table* wählen
3. In der App die Kamera öffnen, mit `Alt`/`Option` + Maus/WASD zum Bild «gehen», bis QR/MRZ gross im Bild ist
- Für QR am besten `_qr.png`, für MRZ `_mrz.png` oder `_back.png` hinterlegen
- Alternative: Webcam als Emulator-Kamera (`webcam0`) und PNG am Bildschirm/Tablet davor zeigen

## Originalgrösse
- ID im PDF exakt 85.6 × 54 mm (ISO/IEC 7810 ID-1), gemessen in A6- und A4-Layout
- PDF-Vorgabe «PrintScaling = None»: Druckdialog startet mit tatsächlicher Grösse
- **Drucken mit 100 % / «Tatsächliche Grösse»**, nie «An Seite anpassen»
  (A6-PDF auf A4 angepasst = 141 %; A4 mit Rand-Anpassung ≈ 94–97 %)
- Kontrolle: Kontrollmass links neben der Vorderseite muss nachgemessen 50 mm sein
- Für A4-Drucker `--layout a4` verwenden, dann mit Papierschneider auf A6 schneiden

## Echte Adressen (Pflicht)
Adressen stammen ausschliesslich aus dem **amtlichen Gebäudeadressverzeichnis** (swisstopo, OGD,
Quellenangabe «Quelle: swisstopo»). Erfundene Adressen gibt es nicht mehr; ohne Daten bricht das Skript ab.
- Übernahme unverändert: Strasse, Hausnummer (inkl. `12a`, `1.1`), PLZ, Ort, Kanton, Koordinaten (LV95 → WGS84)
- Nur Status «real», nur Adressen mit Hausnummer, keine Duplikate
- Mehrere Personen eines Haushalts teilen dieselbe Adresse

```bash
python ies_ng_adressen.py --download                        # Register nach data/ (nicht im Repo)
python ies_ng_adressen.py --canton BE --wohngebaeude -o data/adressen_be.csv   # optionaler Auszug
python ies_ng_karten.py -n 50 --canton BE --wohngebaeude    # Karten mit echten Berner Wohnadressen
```

## Namen nach BFS-Verteilung
Download (sucht die aktuellen BFS-Datensätze auf opendata.swiss, lädt nach `data/` und prüft sie):
```bash
python ies_ng_namen_download.py            # beide Dateien
python ies_ng_namen_download.py --list     # nur Kandidaten anzeigen
python ies_ng_namen_download.py --px-vornamen <STAT-TAB-ID>   # alternativ direkt aus STAT-TAB
python ies_ng_namen_download.py --url-nachnamen <URL>          # alternativ direkte URL
```
Auswahl: nur Datensätze des BFS; bevorzugt «nach Geburtsjahr/Geschlecht» bzw. «nach Kanton»,
Neugeborenen-Statistiken werden ausgeschlossen; CSV vor XLSX; bei Gleichstand der neueste.
Herkunft je Datei in `data/*_bfs.source.json` (Quellenangabe «Quelle: BFS»).

Alternativ Dateien manuell in `data/` ablegen (werden automatisch gefunden) oder per `--first-names/--last-names` übergeben:
- `data/vornamen*.csv|xlsx`: BFS Vornamen der ständigen Wohnbevölkerung **nach Geburtsjahr und Geschlecht**
- `data/nachnamen*.csv|xlsx`: BFS Nachnamen der ständigen Wohnbevölkerung **nach Kanton**

Ziehung:
- Vorname nach Häufigkeit, bedingt auf Geschlecht und Geburtsjahr ± `--name-year-window` (Default 2)
- Nachname nach Häufigkeit im **Kanton der echten Adresse** (sonst national)
- Ohne BFS-Dateien: eingebaute Demo-Listen (Hinweis in der Ausgabe)

Format-Toleranz: CSV/XLSX, Titelzeilen im Excel, Lang- oder Breitformat (Jahre als Spalten),
Spalten de/fr/it/en, Geschlecht `Männlich/Weiblich`/`M/F`/`1/2`, Kantonsnamen → Kürzel,
Jahresbereiche (`1990-1999`) → Mitte; Total-/Schweiz-Zeilen und unterdrückte Werte (`X`) werden entfernt.

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
| `--no-photos` | aus | Platzhalter statt Comic-Passfoto |
| `--png [ORDNER]`, `--png-parts` | aus; card qr mrz | PNG-Export, z. B. für Android-Emulator |
| `--p-red`, `--p-yellow` | 0.15, 0.30 | Prä-Triage Rot/Gelb, Rest Grün (0.55) |
| `--p-red-pattern` | 0.40 | Anteil Roter mit genau einem Verletzungsmuster |
| `--addresses` | neuestes Register in `data/` | amtliches Gebäudeadressverzeichnis oder eigener Auszug |
| `--canton`, `--plz`, `--gemeinde`, `--wohngebaeude` | – | Adressfilter |
| `--first-names/--last-names` | Demo-Listen | Namensregister (siehe `synthetic_people.py`) |
| `--logo`, `--font-*` | gezeichnet / Liberation / DejaVu Mono | CI-Assets |

## Prä-Triage
- Verteilung exakt nach Anteilen (Methode der grössten Reste), Karten zufällig zugeordnet
- 40 % der Roten erhalten **genau ein** zufälliges Verletzungsmuster:
  behebbare Atemwegsverlegung, arterielle Blutung, Verbrennung Grad 2–3 > 60 % KOF, Schnappatmung
- Bei wenigen Roten wird der Rest zufällig gerundet (Erwartungswert 40 %)
- Lösungsliste: Spalten `triage`, `injury_pattern`

## Comic-Passfotos
- Alter: Babys (kaum Haare), Kinder (runder Kopf, grosse Augen, Wangen), ab 40 Stirnfalten, ab 45 Nasolabialfalten,
  ab 50 Tränensäcke, ab 60 Krähenfüsse; Grau-/Weissanteil der Haare und Brillenquote steigen mit dem Alter
- Geschlecht: Frisuren, Bart (Männer ab 18), Wimpern, Lippenfarbe, Ohrringe; `x` = zufällige Darstellung
- Vielfalt: 6 Hauttöne, 6 Haarfarben, 12 Frisuren, Kleiderfarben
- Passbild-Ausschnitt: Kopf ca. 75 % der Bildhöhe, frontal, neutraler Ausdruck, heller Hintergrund
- Vorschau aller Altersstufen: `python ies_ng_avatar.py -o avatar_vorschau.pdf`

## Unterschriften
- Individuell je Person (deterministisch): Handschrift-Schrift, Schreibweise (`Anna Müller`, `A. Müller`, `Müller`,
  Kürzel, abgekürzt mit auslaufender Wellenlinie), Grösse, Neigung, schräge/wellige Grundlinie, Zittern, Tinte, Schnörkel
- Kinder 7–13: voller Name in Druckschrift, gerade, ohne Schnörkel; unter 7 keine Unterschrift
- Schriften: eigene TTF/OTF in `fonts/handschrift/` (Dateiname mit `print`/`druck` = Druckschrift), sonst die
  Windows-Script-Schriften (Segoe Script/Print, Ink Free, Lucida Handwriting, Brush Script, Mistral …); ohne beide Ersatzschrift
- Vorschau: `python ies_ng_signatur.py -o signatur_vorschau.pdf`

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
