# IES NG – Übungskarten (DIN A6, beidseitig)

Ausbildungsmaterial mit fiktiven Patienten nach PLS Schweiz: Patientenkarte (Vorderseite) und
Schweizer ID mit MRZ TD1 (Rückseite).

## Aufbau einer Karte (105 × 148 mm)
**Vorderseite – Patientenkarte**
1. CI-Kopf: Bundeslogo (vereinfacht oder `--logo`), «Bundesamt für Bevölkerungsschutz BABS», «Ausbildung IES NG»
2. PLS-ID (`CHYY001`) gross und als QR-Code (30 mm) oben rechts
3. Farbfelder **Prä-Triage** (Swiss Pre, ohne Blau) und **Triage** (ärztlich, inkl. Blau)
4. **Auffindesituation**: gezeichnete Figur im Aussehen des Passfotos, Haltung/Mimik/Verletzungsmarken passend zum Fall
5. Verletzung (Titel), kurze Beschreibung, **Befunde** (Grundlage für Swiss Pre)

**Rückseite – Ausweis**
1. CI-Kopf
2. ID Vorderseite, Massstab 1:1 (85.6 × 54 mm, ID-1), Layout Identitätskarte 2023, Kontrollmass 50 mm
3. ID Rückseite mit MRZ: 3 × 30 Zeichen, Teilung 2.54 mm, Zeilenabstand 4.23 mm
4. Angaben zur Person: PLS-ID, Name, Geburtsdatum, Wohnadresse

Druck: beidseitig, **an der langen Kante wenden** (PDF-Vorgabe gesetzt); bei `--layout a4` sind die Rückseiten
spaltenweise gespiegelt, damit Vorder- und Rückseite übereinander liegen.

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
python ies_ng_karten.py -n 50 --png                          # png/CHYY001_card.png, _card_back.png, _qr.png, _mrz.png
python ies_ng_karten.py -n 50 --png emulator --png-parts qr mrz back
```
| Teil | Inhalt | Zweck |
|---|---|---|
| `card` | Vorderseite (`_card.png`) und Rückseite (`_card_back.png`), 300 dpi | Gesamtansicht, QR-Scan |
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
python ies_ng_karten.py -n 40                       # CHYY001–CHYY040, A6 beidseitig
python ies_ng_karten.py -n 200 --layout a4          # 4 Karten/A4 mit Schnittlinien
python ies_ng_karten.py -n 10 --layout a4-1         # 1 Karte/A4 in Originalgrösse
python ies_ng_karten.py -n 10 --layout a4-gross     # 1 Karte/A4 vergrössert (Beamer, Aushang)
python ies_ng_karten.py -n 50 --start 151           # CHYY151–CHYY200
python ies_ng_karten.py -n 20 --id-start CHAB001     # anderer Nummernkreis
python ies_ng_karten.py -n 100 --pre-mix rot=20,gelb=30,gruen=40,weiss=5,schwarz=5
python ies_ng_karten.py -n 100 --p-invalid-mrz 0.1 --p-expired 0.05   # Negativfälle
python ies_ng_karten.py @karten.args                # Argumente aus Datei (1 pro Zeile)
```
Ausgabe: `ies_ng_karten.pdf` + `ies_ng_karten_loesungen.csv` (Lösungsliste, `;`-getrennt).

### Wichtige Optionen
| Option | Default | Zweck |
|---|---|---|
| `-n/--count` | 20 | Anzahl Karten |
| `--start` | 1 | erste laufende Nummer (1 = `--id-start`) |
| `--id-start` | CHYY001 | PLS-ID: CH + 2 Buchstaben + 3 Ziffern; nach 999 folgt das nächste Paar (CHYY999 → CHYZ001), Ende CHZZ999 |
| `--qr-format` | `{id}` | Payload nur Kartennummer (z. B. `CHYY003`); CHA-Format `(dc\|{id}\|{id})` wird von der IES-NG-App als `DCCHYY003CHYY003` gelesen |
| `--qr-size` | 30 | QR-Kantenlänge inkl. Ruhezone, mm |
| `--qr-error` | m | ECC (L/M/Q; H passt nicht in Version 2) |
| `--layout` | a6 | `a6` (1 Karte/A6), `a4` (4 Karten/A4), `a4-1` (1 Karte/A4, Originalgrösse, Schnittlinie), `a4-gross` (1 Karte/A4, vergrössert ×2, ohne Kontrollmass) |
| `--p-invalid-mrz` | 0 | Anteil falscher Prüfziffern (Feld in Lösungsliste) |
| `--p-expired` | 0 | Anteil abgelaufener Ausweise |
| `--adults-only` | aus | nur Erwachsene |
| `--no-photos` | aus | Platzhalter statt Comic-Passfoto |
| `--png [ORDNER]`, `--png-parts` | aus; card qr mrz | PNG-Export, z. B. für Android-Emulator |
| `--pre-mix` | rot=15,gelb=30,gruen=45,weiss=7,schwarz=3 | Anteile Prä-Triage (exakt); Triage folgt je Fall |
| `--addresses` | neuestes Register in `data/` | amtliches Gebäudeadressverzeichnis oder eigener Auszug |
| `--canton`, `--plz`, `--gemeinde`, `--wohngebaeude` | – | Adressfilter |
| `--first-names/--last-names` | Demo-Listen | Namensregister (siehe `synthetic_people.py`) |
| `--logo`, `--font-*` | gezeichnet / Liberation / DejaVu Mono | CI-Assets |

## Prä-Triage (Swiss Pre) und Triage
Grundlage: Gebrauchsanweisung PLS Schweiz (KSD, 2019), Algorithmus Swiss Pre (`ies_ng_swisspre.py`).

| Schritt | Kriterium | ja → |
|---|---|---|
| A/(E) | keine Atmung nach Freimachen · nicht vereinbare Verletzung · sichere Todeszeichen | Schwarz |
| A | Inhalationstrauma mit Stridor · Atemwege offenhalten | Rot |
| B | AF < 10 oder > 30 | Rot |
| C | kein Radialispuls · Rekap > 2 s · unstillbare Blutung | Rot |
| C | sicher gestillte Blutung | Gelb |
| D | befolgt Aufforderungen nicht | Rot |
| E | nicht gehfähig · starke Schmerzen | Gelb |
| E | verletzt / erkrankt → Grün; unverletzt → Weiss | |

- **Prä-Triage**: Schwarz, Rot, Gelb, Grün, Weiss (nie Blau); Verteilung exakt nach `--pre-mix`
- **Fallkatalog** (24 Fälle): je Fall Verletzung, Beschreibung, Befunde, Auffindesituation (Umgebung, Haltung,
  Mimik, Marken). Befunde werden zufällig im plausiblen Bereich erzeugt und **mit Swiss Pre geprüft** –
  ein Fall, der nicht die Prä-Triage-Farbe ergibt, bricht die Erzeugung ab
- Enthalten u. a.: behebbare Atemwegsverlegung, Inhalationstrauma mit Stridor, Schnappatmung,
  Verbrennung Grad 2–3 > 60 % KOF (Rot über B: AF > 30), unstillbare arterielle Blutung (Rot) bzw. mit
  Tourniquet gestillt (Gelb), Schock, SHT, Frakturen, Rauchgas, leichte Verletzungen, Unverletzte
- **Triage** (ärztlich, inkl. Blau): fallbezogene Verteilung, z. B. Verbrennung > 60 % KOF → Blau 60 % / Rot 40 %;
  Rot → teils Gelb (Übertriage), Grün → teils Gelb
- Schwarz und Blau nur bei Personen ab 16 Jahren (Übungsrahmen)
- Lösungsliste: `pre_triage`, `triage`, `swiss_pre_kriterium`, `fall`, `verletzung`, `beschreibung` und alle Befunde
- Vorschau aller Szenen: `python ies_ng_szene.py -o szenen_vorschau.pdf`

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
- Prä-Triage (200 Karten): 30 Rot / 60 Gelb / 90 Grün / 14 Weiss / 6 Schwarz (exakt); Swiss Pre aus den Befunden
  der Lösungsliste nachgerechnet: 0 Abweichungen; QR 200/200 auf den Vorderseiten (A4, beidseitig)
- MRZ-Schrift: OCR-B (OFL, `fonts/OCR-B.ttf`); OCR mit Lesegerät nicht getestet

## Offen
1. **CI**: offizielles Logo (`--logo`) und Frutiger einsetzen; Farbe Rot `#DC0018` prüfen
2. QR-Präfix `dc` und ECC-Stufe mit Zielsystem klären (siehe Erkenntnisse)
3. Ablauf-Prüfziffer Specimen gegen fedpol-Spezifikation prüfen
