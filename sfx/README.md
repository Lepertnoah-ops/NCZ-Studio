# SFX-Grundkit (synthetisch, 48 kHz Stereo)

Anker = welcher Punkt der Datei auf `at` gelegt wird (reel_audio.py `align`).

Hörprobe ab = Zeitpunkt in `sfx_vorschau.mp3` (alle Sounds in Tabellenreihenfolge, je 0,8 s Pause).

| Datei | Anker | Länge | Einsatz | Hörprobe ab |
|---|---|---|---|---|
| whoosh.wav | peak | 0.70 s | Übergang, Peak auf den Schnitt legen | 0:00.0 |
| swoosh_short.wav | peak | 0.28 s | kurzer, heller Swipe für schnelle Cuts | 0:01.5 |
| whoosh_low.wav | peak | 0.90 s | tiefer, schwerer Übergang | 0:02.6 |
| impact.wav | start | 1.80 s | cinematischer Einschlag mit Sub, für Titel/Payoff | 0:04.3 |
| punch.wav | start | 0.35 s | trockener Schlag, für Treffer/Slams | 0:06.9 |
| bass_drop.wav | start | 1.20 s | Sub-Drop unter einen Drop/Hit | 0:08.0 |
| riser.wav | end | 3.00 s | 3-s-Aufbau, Ende auf den Drop | 0:10.0 |
| reverse_swell.wav | end | 1.50 s | Rückwärts-Becken, Ende auf den Schnitt | 0:13.8 |
| tick.wav | start | 0.06 s | Klick für Text-Pops | 0:16.1 |
| shutter.wav | start | 0.25 s | Kamera-Auslöser für Freeze-Frames | 0:17.0 |
| sub_hit.wav | start | 0.60 s | leiser Sub unter einen Zoom-Punch legen | 0:18.0 |
| whoosh_soft.wav | peak | 0.80 s | sehr weicher, luftiger Übergang für ruhige Schnitte | 0:19.4 |
| swipe_up.wav | peak | 0.40 s | steigender Swipe für Slide-/Push-up-Übergänge | 0:21.0 |
| swipe_down.wav | peak | 0.40 s | fallender Swipe für Slide-down-Übergänge | 0:22.2 |
| zoom_whoosh.wav | peak | 0.60 s | Whoosh mit steigendem Ton für Zoom-in-Übergänge | 0:23.4 |
| glitch.wav | start | 0.35 s | kurzer, dezenter Digital-Glitch für Glitch-Cuts | 0:24.8 |
| tape_stop.wav | start | 0.80 s | Tape-Stop/Power-down, z. B. vor einer Pause oder einem Musikstopp | 0:26.0 |
| rewind.wav | start | 0.90 s | Zurückspulen für Rewind-/Rückblenden-Momente | 0:27.6 |
| flash_pop.wav | start | 0.50 s | Blitz-Pop für Weißblitze/Flash-Übergänge | 0:29.3 |
| heartbeat.wav | start | 1.00 s | zwei leise Herzschläge für Slow-Motion-Momente | 0:30.6 |
| pop.wav | start | 0.12 s | weicher Pop für Text-Einblendungen (sanfter als tick) | 0:32.4 |
| typing.wav | start | 1.20 s | Tastenklicks für Schreibmaschinen-Text | 0:33.3 |
| boom_far.wav | start | 2.50 s | ferner, dunkler Kino-Boom mit langem Hall | 0:35.3 |
| downlifter.wav | start | 2.00 s | fallendes Rauschen, lässt einen Drop/Hit ausklingen | 0:38.6 |
| vinyl_scratch.wav | start | 0.50 s | kurzer DJ-Scratch für Beat-Wechsel oder Rewinds | 0:41.4 |
| shimmer.wav | start | 1.50 s | sanftes Glitzern für Logo-/Titel-Reveals | 0:42.7 |
| startschuss.wav | start | 1.80 s | Startschuss mit Echo für den Rennstart | 0:45.0 |
| countdown.wav | start | 4.00 s | Zeitnahme-Pieptöne bei 0/1/2 s, langer Startton bei +3,0 s (at = Startmoment − 3 s) | 0:47.6 |

Standard im Reel: keine oder höchstens 1–2 leise SFX, deutlich unter der Musik (etwa −14 bis −18 dB, `gain_db` in reel_audio.py).
