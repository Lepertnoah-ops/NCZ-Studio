# Reel ncz_041026 (2026-10-05)

| | |
|---|---|
| Auftrag | Anfrage vom 2026-10-05: … |
| Drive-Ordner | Link bzw. Ordner-ID |
| Song | Interpret – Titel, BPM (Abschnitt je Variante unten) |
| Stil | Stil-Leitfaden, Abweichungen laut Auftrag: … |
| Status | Sichtung / 3 Varianten zur Auswahl / Variante … gewählt / geliefert |
| Fertig | `ncz_041026_mit_song.mp4`, `ncz_041026_ohne_ton.mp4`, `ncz_041026_titelbild.jpg` |

## Varianten (Pflicht-Stopp: der Nutzer wählt eine)

| | Idee | Songabschnitt | Länge, Shots | Unterschied in einem Satz |
|---|---|---|---|---|
| A | … | Takt a.1 bis b.1 (von–bis s) | … s, … Szenen, … Shots | … |
| B | … | … | … | … |
| C | … | … | … | … |

- Unterschied-Check (`tools/pipeline/varianten.py <reel> --check`): … (Warnung begründen, falls sie bleibt)
- Stil-Leitfaden-Prüfung (`edl.py` je Variante): keine WARNUNG, oder jede hier begründet
- Szenen-Ansicht (`tools/ansicht.py szenen`, 4 Frames je Shot) vor dem Vorlegen: jede Aktion ganz drin, Jump Cuts springen zwischen ganzen Wiederholungen
- O-Ton (`tools/analyse/oton.py`): welche Clips mit welchem Ton, im Einstieg, leise, als Moment; Musik aus einer Box im Clip-Ton nur im Einstieg mit `EINSTIEG_SONG = "aus"`
- Gewählt: Variante … am … („wörtlich“), Änderungswünsche: …

## Ordner

- oben vor der Wahl: je Variante `ncz_041026_A_vorschau.mp4` und `ncz_041026_A_storyboard.jpg` (B und C genauso); nach der Wahl nur die aktuelle Fassung (Videos, Titelbild, Storyboard)
- `schnitt/`: `grid.json` (Beat-Raster, gilt für alle Varianten), `A/`, `B/`, `C/` je mit `edl.py` → `edl.json`, `fx.json`, `audio_spec.json`
- `archiv/varianten/`: Vorschau-Videos und Storyboards aller Varianten (verschiebt `varianten.py --wahl`)
- `archiv/v1_vorschlag/`, `archiv/v2_vorschlag/` …: Schnittlisten früherer Vorschlagsrunden (Feedback vor der Wahl)
- `archiv/v1/`, `archiv/v2/` …: ältere gelieferte Fassungen samt ihrer Schnittliste, nie löschen

## Versionen

- v1 (Datum): Variante …, Shots, Länge, was drin ist

## Feedback

- (wörtlich, mit Datum; was davon dauerhaft gilt, kommt in Stil-Leitfaden.md und stil.json)

## Prüfwerte (tools/pipeline/verify.py)

- Schnitte: … / 808-Versatz: … Frames / Lautheit: … LUFS / True Peak: … dBTP
