ERGEBNIS: FEHLER – 6 Fehler, 7 Warnungen

Reel: `vorbild1.mp4` · Dauer 61.800 s · 106.09 Beats · Laufzeit 14.9 s

| Check | Ergebnis | Wert |
|---|---|---|
| Format: Auflösung | FEHLER | 720x1280 |
| Format: Bildrate 30 fps konstant | OK | r=30/1, avg=30/1, Sprünge=0, doppelt=0 |
| Format: Codec H.264 High | OK | h264 High |
| Format: Pixelformat yuv420p | OK | yuv420p |
| Format: Farb-Tags bt709 | OK | bt709/bt709/bt709 |
| Format: Video-Bitrate | WARNUNG | 3.6 Mbit/s |
| Format: Audio AAC 48 kHz | WARNUNG | aac 44100 Hz 2 ch 132 kbit/s |
| Format: Dauer Audio = Video | OK | Diff -13.2 ms, Start +0.0 ms |
| Format: Faststart (moov vor mdat) | WARNUNG | mdat → moov |
| Format: Dateigröße | OK | 29.3 MB |
| Beat-Sync: Beat-Raster | OK | 103.00 BPM, Periode 0.58250 s, Residuen RMS 7.9 ms / max 18.3 ms |
| Bild: Schwarzbilder | FEHLER | 43 Frames |
| Bild: Standbilder | WARNUNG | 1 Bereich(e) |
| Bild: Schnitte / Punches / Flashes | INFO | 9 Schnitte, 1 Punches, 0 Flashes, 4 Übergänge |
| Bild: Szenen ≥ 2 Beats | WARNUNG | kürzeste 0.69 Beats |
| Bild: Szenen pro 16 Takte | INFO | 8.4 |
| Beat-Sync: Schnitte auf Beat/Halbbeat | FEHLER | max 144.6 ms = 4.34 Frames (9 Schnitte) |
| Beat-Sync: Punches auf Beat/Halbbeat | FEHLER | max 137.9 ms (1 Punches) |
| Beat-Sync: 808 ↔ Schnitt/Punch | WARNUNG | max 44.3 ms bei 3 von 10 Treffern |
| Beat-Sync: 808 mit Bild-Treffer | INFO | 1 von 159 808-Onsets |
| Audio: Lautheit integriert | INFO | -14.3 LUFS |
| Audio: True Peak ≤ −0,3 dBTP | FEHLER | 0.33 dBTP |
| Audio: Keine stillen 100-ms-Blöcke | OK | 0 Blöcke < −60 dBFS, min -43.8 dB |
| Audio: Keine Aussetzer | OK | 0 Nullstrecken > 10 ms |
| Audio: Fade-in ≤ 10 ms | OK | Start-Amplitude 0.000 |
| Audio: Fade-out 30–40 ms | OK | End-Amplitude 0.001 |
| Audio: Ende auf Taktgrenze | WARNUNG | -664.4 ms |
| Audio: Keine 808 in letzten 150 ms | FEHLER | 1 Onset(s) bei 61.652 s |
| Loop: Letztes ↔ erstes Bild | INFO | Histogramm-Korrelation 0.01 |

## Details

- **Auflösung**: Soll 1080x1920
- **Bildrate 30 fps konstant**: r_frame_rate 30/1, keine Lücken
- **Farb-Tags bt709**: space/transfer/primaries
- **Video-Bitrate**: Ziel ~18, max 25
- **Dauer Audio = Video**: < 1 Frame
- **Dateigröße**: 61.80 s
- **Beat-Raster**: Reel-Ton (librosa, geschätzt), Phase an 808 -29.7 ms
- **Schwarzbilder**: 60.37–61.80 s
- **Standbilder**: 60.37–61.80 s
- **Schnitte / Punches / Flashes**: animierte Übergänge (kein harter Schnitt): 13.63–14.03 s, 26.53–26.77 s, 28.50–28.90 s, 48.37–48.67 s
- **Szenen ≥ 2 Beats**: keine neue Szene unter 2 Beats: #4 @26.67 s (0.69), #9 @47.37 s (1.83), #11 @51.93 s (1.09), #12 @52.57 s (1.49)
- **Szenen pro 16 Takte**: nur Info (Stil-Richtwert 16–24)
- **Schnitte auf Beat/Halbbeat**: 21.50 s (+114 ms), 27.07 s (-145 ms), 32.57 s (+113 ms), 43.00 s (+61 ms), 47.37 s (+59 ms), 60.37 s (-47 ms)
- **Punches auf Beat/Halbbeat**: 31.73 s (-138 ms)
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
| 1 | 645 | 21.500 s | 36.70 | +113.8 ms |
| 2 | 812 | 27.067 s | 46.25 | -144.6 ms |
| 3 | 977 | 32.567 s | 55.69 | +112.9 ms |
| 4 | 1290 | 43.000 s | 73.61 | +61.2 ms |
| 5 | 1421 | 47.367 s | 81.10 | +59.1 ms |
| 6 | 1558 | 51.933 s | 88.94 | -34.3 ms |
| 7 | 1577 | 52.567 s | 90.03 | +16.5 ms |
| 8 | 1603 | 53.433 s | 91.52 | +9.4 ms |
| 9 | 1811 | 60.367 s | 103.42 | -47.3 ms |

### Punches

- 31.733 s (Mitte, Skala 0.058)

Bilder: `qc_timeline.png`, `qc_shots.jpg` · Rohdaten: `qc.json`
