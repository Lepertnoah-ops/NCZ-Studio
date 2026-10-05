# Referenz: „All gas no brakes“ (Sport/Motivation, Boxen)

Datei: `__All_gas_no_brakes.mp4` (vom Nutzer im Chat geschickt, 2026-10-05; nicht im Drive). 360×640, ~25 fps (variabel), 23,8 s.
Messwerte: `referenz.md` (`referenz_analyse.py`), `qc.md` (`reel_qc.py`), Bilder: `uebersicht.jpg`, `zeitleiste.jpg`, `flare_uebergang.jpg` (15,0–16,2 s, jedes Bild).

## Inhalt

Ein Boxer, ein Gym (MACH1, WBC-Banner), Training ohne Gegner: Vorbereitung → Schattenboxen → Sandsack → Schattenboxen im Ring. Kein Text, kein Logo-Overlay, kein Gesprochenes, nur der Song.

| Zeit | Teil | Was passiert |
|---|---|---|
| 0–1 s | Hook-Bild | Untersicht, Kopf gesenkt, Handschuhe hängen: Ruhe vor dem Sturm |
| 1–5,7 s | Aufbau | Totale im Gym, dann WBC-Banner (Wiedererkennung bei 2 s), Schattenboxen nah, Schnitte alle 1,3–1,5 Beats |
| 5,7–7 s | Break | Song gefiltert (Höhen weg), Sandsack-Shots, Spannung |
| ab 7 s | Drop | Sub und Höhen voll, Sandsackarbeit, Kamera fliegt mit, Schnitte 0,6–2 Beats |
| 15–16 s | Flare | Gegenlicht-Flare als Übergang, danach Schattenboxen frontal |
| 16–22 s | Finale | schnellste Folge (Shots ~1 Beat), Schattenboxen im Ring |
| 22–24 s | Ende | Abblende auf Schwarz, Song blendet in ~1,5 s aus (kein Loop) |

## Messwerte

| | Wert | Grundstil zum Vergleich |
|---|---|---|
| Länge | 23,8 s | 30–40 s |
| Tempo | ~110 BPM (`reel_qc` schätzt 160, Raster unsicher) | – |
| Shots | 24 (harte Erkennung) bis 33 (inkl. Flackern), Median 0,78 s = 1,4 Beats | Teile ab 2 Beats, Aktionen 4–8 |
| Jump Cuts | 1 | Szenen aus Jump Cuts |
| Schnitte auf Beat/Halbbeat | 11 von 23 (±45 ms) | alle, ±1 Frame |
| Überblendungen | 0; 3 Licht-Flares als Übergang (4,9 / 7,4 / 15,4 s) | max. 4 Überblendungen |
| Punches | 4–6, dazu Zoom-raus-Bewegungen | auf jedem 808 |
| Flashes | 1 echter (10,9 s) + Flares | max. 2 |
| Zeitlupe | leicht, nur in einzelnen Sandsack-Shots | Finale 0,5× |
| Kamera | Handkamera / Gimbal ganz nah, Untersicht, Kamera kreist und wischt mit (Bewegungsunschärfe), Vordergrund (Sandsack) im Bild | ruhiges Fenster, kein Schwenk |
| Look | entsättigt, kühl-grau, harte Kontraste, abgesoffene Schwarztöne, Haut matt-dunkel | `clean` |
| Ton | nur Song, −14,1 LUFS, kein O-Ton, Break mit Tiefpass vor dem Drop | O-Ton-Einstieg |

## Was den Stil ausmacht (für Sport/Motivation)

1. **Energie über Kamera, nicht über Effekte:** Die Bewegung kommt aus der fliegenden Nah-Kamera (Kreisen, Mitziehen, Wischer), nicht aus Ramps oder Glitch. Effekte bleiben wenige (1 Flash, ein paar Punches).
2. **Kurze Schnitte, 1–1,5 Beats.** Gezeigt wird Intensität, nicht die ganze Aktion. Schnitte sind nur lose auf dem Beat (die Hälfte daneben); es wirkt trotzdem, weil die Bewegung im Bild die Akzente trägt.
3. **Ein Held, ein Ort.** Wiedererkennung über Gym und Banner (WBC, MACH1) in den ersten 2 s, Person immer dieselbe.
4. **Dunkler Gritty-Look:** Entsättigung, Kühle, Gegenlicht und Lens-Flares als Lichtakzente und Übergänge.
5. **Dramaturgie Ruhe → Break → Drop → Finale:** Hook-Bild in Ruhe, gefilterter Break vor dem Drop, schnellste Schnitte am Schluss, dann Abblende.
6. **Kein Text, kein Gesprochenes** (der Titel steht nur in der Caption).

## Was nicht übernommen werden sollte

- Lose Beat-Synchronität (bis 85 ms daneben) und eine 808 im letzten Moment: unsere Prüfung (`reel_qc.py`) würde das als Fehler melden.
- Abblende auf Schwarz mit ~2 s fast schwarzem Ende: kostet Wiedergabezeit und loopt nicht.
- 360×640 und 0,5 Mbit/s: das ist die Download-Qualität, nicht das Original.
