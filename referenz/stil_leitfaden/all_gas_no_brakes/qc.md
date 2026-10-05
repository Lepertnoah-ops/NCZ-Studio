ERGEBNIS: FEHLER – 7 Fehler, 7 Warnungen

Reel: `d8da2876-__All_gas_no_brakes.mp4` · Dauer 23.760 s · 63.41 Beats · Laufzeit 8.8 s

| Check | Ergebnis | Wert |
|---|---|---|
| Format: Auflösung | FEHLER | 360x640 |
| Format: Bildrate 30 fps konstant | FEHLER | r=12521/500, avg=12521/500, Sprünge=594, doppelt=0 |
| Format: Codec H.264 High | WARNUNG | h264 Main |
| Format: Pixelformat yuv420p | OK | yuv420p |
| Format: Farb-Tags bt709 | OK | bt709/bt709/bt709 |
| Format: Video-Bitrate | WARNUNG | 0.5 Mbit/s |
| Format: Audio AAC 48 kHz | WARNUNG | aac 44100 Hz 2 ch 97 kbit/s |
| Format: Dauer Audio = Video | FEHLER | Diff +200.1 ms, Start +0.0 ms |
| Format: Faststart (moov vor mdat) | OK | moov → mdat |
| Format: Dateigröße | OK | 1.7 MB |
| Beat-Sync: Beat-Raster | OK | 160.11 BPM, Periode 0.37473 s, Residuen RMS 6.1 ms / max 14.5 ms |
| Bild: Schwarzbilder | FEHLER | 48 Frames |
| Bild: Standbilder | WARNUNG | 1 Bereich(e) |
| Bild: Schnitte / Punches / Flashes | INFO | 29 Schnitte, 4 Punches, 6 Flashes, 3 Übergänge |
| Bild: Szenen ≥ 2 Beats | WARNUNG | kürzeste 0.27 Beats |
| Bild: Szenen pro 16 Takte | INFO | 33.3 |
| Beat-Sync: Schnitte auf Beat/Halbbeat | FEHLER | max 84.5 ms = 2.54 Frames (29 Schnitte) |
| Beat-Sync: Punches auf Beat/Halbbeat | FEHLER | max 78.2 ms (4 Punches) |
| Beat-Sync: 808 ↔ Schnitt/Punch | OK | max 32.3 ms bei 10 von 31 Treffern |
| Beat-Sync: 808 mit Bild-Treffer | INFO | 10 von 110 808-Onsets |
| Audio: Lautheit integriert | INFO | -14.1 LUFS |
| Audio: True Peak ≤ −0,3 dBTP | WARNUNG | -0.12 dBTP |
| Audio: Keine stillen 100-ms-Blöcke | OK | 0 Blöcke < −60 dBFS, min -52.1 dB |
| Audio: Keine Aussetzer | OK | 0 Nullstrecken > 10 ms |
| Audio: Fade-in ≤ 10 ms | OK | Start-Amplitude 0.001 |
| Audio: Fade-out 30–40 ms | OK | End-Amplitude 0.000 |
| Audio: Ende auf Taktgrenze | WARNUNG | +245.2 ms |
| Audio: Keine 808 in letzten 150 ms | FEHLER | 1 Onset(s) bei 23.703 s |
| Loop: Letztes ↔ erstes Bild | INFO | Histogramm-Korrelation 0.01 |

## Details

- **Auflösung**: Soll 1080x1920
- **Bildrate 30 fps konstant**: r_frame_rate 30/1, keine Lücken
- **Farb-Tags bt709**: space/transfer/primaries
- **Video-Bitrate**: Ziel ~18, max 25
- **Dauer Audio = Video**: < 1 Frame
- **Dateigröße**: 23.76 s
- **Beat-Raster**: Reel-Ton (librosa, geschätzt), Phase an 808 -18.1 ms
- **Schwarzbilder**: 9.03–9.07 s, 15.33–15.37 s, 15.40–15.47 s, 15.53–15.57 s, 15.60–15.63 s, 15.67–15.70 s, 15.73–15.77 s, 18.50–19.83 s
- **Standbilder**: 18.50–19.83 s
- **Schnitte / Punches / Flashes**: animierte Übergänge (kein harter Schnitt): 4.90–5.30 s, 7.43–7.63 s, 8.23–8.37 s
- **Szenen ≥ 2 Beats**: keine neue Szene unter 2 Beats: #3 @2.10 s (1.69), #4 @2.73 s (1.60), #5 @3.33 s (0.89), #6 @3.67 s (1.60), #10 @7.10 s (0.98), #11 @7.47 s (0.62), #12 @7.70 s (0.89), #13 @8.03 s (0.62), #19 @12.67 s (0.27), #21 @13.83 s (1.25), #22 @14.30 s (1.25), #23 @14.77 s (1.42), #25 @16.47 s (0.71), #26 @16.73 s (0.98), #27 @17.10 s (0.89), #28 @17.43 s (0.98), #29 @17.80 s (0.27), #30 @17.90 s (0.44), #31 @18.07 s (0.36), #32 @18.20 s (0.27)
- **Szenen pro 16 Takte**: nur Info (Stil-Richtwert 16–24)
- **Schnitte auf Beat/Halbbeat**: 0.87 s (-65 ms), 2.10 s (+44 ms), 2.73 s (-72 ms), 3.67 s (-76 ms), 4.27 s (-38 ms), 9.07 s (+78 ms), 11.67 s (+55 ms), 12.67 s (-69 ms)
- **Punches auf Beat/Halbbeat**: 8.10 s (+48 ms), 9.07 s (+78 ms), 18.13 s (-36 ms)
- **808 ↔ Schnitt/Punch**: Projektregel max. 1 Frame (Treffer mit 808 im Umkreis von 1,5 Frames)
- **True Peak ≤ −0,3 dBTP**: 4x Oversampling
- **Fade-in ≤ 10 ms**: ohne --song nur Knackser-Test
- **Fade-out 30–40 ms**: ohne --song nur Knackser-Test
- **Ende auf Taktgrenze**: ±20 ms, Takt-1 geschätzt
- **Keine 808 in letzten 150 ms**: 808 nie abschneiden
- **Letztes ↔ erstes Bild**: sichtbarer Loop-Sprung

### Schnitte

| # | Frame | Zeit | Beat | Versatz |
|---|---|---|---|---|
| 1 | 26 | 0.867 s | 1.33 | -65.1 ms |
| 2 | 63 | 2.100 s | 4.62 | +44.1 ms |
| 3 | 82 | 2.733 s | 6.31 | -72.1 ms |
| 4 | 100 | 3.333 s | 7.91 | -34.2 ms |
| 5 | 110 | 3.667 s | 8.80 | -75.6 ms |
| 6 | 128 | 4.267 s | 10.40 | -37.7 ms |
| 7 | 175 | 5.833 s | 14.58 | +30.1 ms |
| 8 | 213 | 7.100 s | 17.96 | -14.8 ms |
| 9 | 231 | 7.700 s | 19.56 | +23.1 ms |
| 10 | 241 | 8.033 s | 20.45 | -18.3 ms |
| 11 | 272 | 9.067 s | 23.21 | +78.2 ms |
| 12 | 297 | 9.900 s | 25.43 | -25.3 ms |
| 13 | 326 | 10.867 s | 28.01 | +4.5 ms |
| 14 | 350 | 11.667 s | 30.15 | +55.0 ms |
| 15 | 380 | 12.667 s | 32.81 | -69.2 ms |
| 16 | 383 | 12.767 s | 33.08 | +30.8 ms |
| 17 | 415 | 13.833 s | 35.93 | -26.7 ms |
| 18 | 429 | 14.300 s | 37.17 | +65.2 ms |
| 19 | 443 | 14.767 s | 38.42 | -30.2 ms |
| 20 | 459 | 15.300 s | 39.84 | -59.0 ms |
| 21 | 494 | 16.467 s | 42.96 | -16.5 ms |
| 22 | 502 | 16.733 s | 43.67 | +62.8 ms |
| 23 | 513 | 17.100 s | 44.65 | +54.7 ms |
| 24 | 523 | 17.433 s | 45.54 | +13.3 ms |
| 25 | 534 | 17.800 s | 46.51 | +5.2 ms |
| 26 | 537 | 17.900 s | 46.78 | -82.1 ms |
| 27 | 542 | 18.067 s | 47.23 | +84.5 ms |
| 28 | 546 | 18.200 s | 47.58 | +30.5 ms |
| 29 | 549 | 18.300 s | 47.85 | -56.9 ms |

### Punches

- 8.100 s (Mitte, Skala 0.047)
- 9.067 s (Schnitt, Skala 0.476)
- 12.767 s (Schnitt, Skala 0.085)
- 18.133 s (Mitte, Skala 0.110)

### Flashes

- 4.000 s (Beat-Versatz 70.4 ms)
- 5.867 s (Beat-Versatz 63.4 ms)
- 11.500 s (Beat-Versatz 75.7 ms)
- 11.833 s (Beat-Versatz 34.3 ms)
- 15.467 s (Beat-Versatz -79.7 ms)
- 17.167 s (Beat-Versatz -66.0 ms)

Bilder: `qc_timeline.png`, `qc_shots.jpg` · Rohdaten: `qc.json`
