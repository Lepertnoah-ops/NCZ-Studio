# Reel {NAME} ({DATUM})

| | |
|---|---|
| Auftrag | Thread bzw. Session „…“, Nutzer am {DATUM}: „(wörtlich)“ |
| Drive-Ordner | Ordner-ID, Clips (Dateinamen, Aufnahmedatum, Länge), Freigabe |
| Song | Interpret – Titel (prod. …), BPM, Länge, Drive-Ordner |
| Stil | Interview-Reel (Stil-Leitfaden Abschnitt 10, Kurzanleitung „Interview-Reels“); Abweichungen laut Auftrag: … |
| Status | Vorschau geschickt (Pflicht-Stopp) / Export geliefert |
| Fertig (nach OK) | `{NAME}_mit_song.mp4` (Stimme + Song), `{NAME}_ohne_song.mp4` (nur Stimme, Song in Instagram dazulegen), `{NAME}_titelbild.jpg` |

## Schnitt

- Werkzeuge: `tools/analyse/transkript.py` → `schnitt/transkript/`; `tools/pipeline/interview.py` baut aus `schnitt/schnitt.py` → `schnitt.json` Vorschau, Storyboard und Export.
- Story in 4 Kapiteln, … Teile, … s: **Kapitel 1** (#1–…) → **Kapitel 2** (#…) → …
- Schnitte in den Sprechpausen; von Hand gesetzt nach Spektrum und Pegel: #… (`anfang=`/`ende=` in `schnitt.py`).
- Song: Intro unter Kapitel 1, erster 808 (Takt …) auf Teil #…, Ende auf Takt … (Eins) mit 2 s Ausblende.
- Abspann: Event, Zeit, Ort und woher die Angaben stammen (Auftrag des Nutzers, Flyer oder Ankündigung).
- Nicht verwendet: … und warum.

## Unsichere Stellen (gemessen und gegengeprüft, nicht gehört)

- Wörter mit p < 0,5, eigene Deutungen (`ersetzen`), Schnitte im Redefluss (Warnungen von `interview.py`).

## Versionen

- Vorschau 1 (Datum): …

## Feedback des Nutzers

- (wörtlich, mit Datum und Uhrzeit UTC) → Umsetzung

## Prüfwerte (`interview.py --export`)

- Format … / Länge … s / Lautheit … LUFS / True Peak … dBTP
