# VFX-Bibliothek (`tools/vfx/`)

61 Videoeffekte in 6 Gruppen und 7 Looks für Reels (1080×1920 @30 fps), beat-gesteuert über eine `fx.json`.
Das ist eine **Auswahl-Bibliothek**, kein Pflichtprogramm: Was im Stil ist, sagen `Stil-Leitfaden.md` und `stil.json`. Jeder Effekt hat
eine dezente Standardstärke; `check` warnt, wenn eine spec über das Effekt-Budget aus `stil.json` geht.

| Datei | Zweck |
|---|---|
| `reelvfx.py` | Bibliothek + Renderer + Kommandozeile (`list`, `check`, `render`, `stills`, `cuts`, `stabilize`, `slowmo`, `safezones`) |
| `looks.py` | 7 Looks als 33³-LUT, dazu eigene Looks per Parameter oder `.cube` (Stil in `stil.json`, Feld `look`) |
| `luts/*.cube` | gebackene Looks, anwenden mit `lut3d=…:interp=tetrahedral` |
| `untertitel.py` | Untertitel Wort für Wort als ASS-Datei (Interview-Reels und Dialog-Szenen): Antonio Bold, Großbuchstaben 96 px, einheitlich weiß ohne Rand mit weichem dunklem Schein, 1–3 Wörter gleichmäßig verteilt, Pop-Animation; Fragen hinter der Kamera oben (54 px) mit Ausblendung. Stil-Leitfaden Abschnitt 10, Aufruf im Kopf der Datei. |
| `gallery.py` | baut eine Vorschau-Galerie am eigenen Reel (`python3 gallery.py <reel>_ohne_ton.mp4 [ordner]`): Demo pro Effekt (`NN_name.mp4`), alle in einem Video (`vfx_galerie_alle.mp4`), Übersicht (`galerie_uebersicht.jpg`). Gut nach dem ersten fertigen Reel, damit der Nutzer Effekte am eigenen Material sieht. |
| `beispiele/` | drei specs: Akzente auf einem fertigen Schnitt, direkt aus Rohmaterial, Intro mit Text |

## Schnellstart

```bash
cd $P/tools/vfx                                            # P = Projektordner
python3 reelvfx.py list                                   # alle Effekte mit Standardwerten
python3 reelvfx.py check  beispiele/intro_text_fx.json    # Budget laut stil.json
python3 reelvfx.py render beispiele/intro_text_fx.json /tmp/intro.mp4 --bis 6    # Vorschau (CRF 18)
python3 reelvfx.py render spec.json master.mp4 --master   # Master wie render.py: yuv444p, CRF 1, LUT am Ende
python3 reelvfx.py stills spec.json /tmp/stills 1.2 3.4   # Standbilder zum Prüfen
```

## Zwei Arbeitsweisen

- **A) Effekte über einen fertigen Schnitt:** `"video": "schnitt.mp4"` plus `"cuts"` (Liste in Sekunden oder `"auto"` per
  Szenenerkennung). Übergänge frieren dabei das letzte Bild von A und das erste von B kurz ein; deshalb Übergänge kurz halten.
- **B) Direkt aus dem Rohmaterial:** `"clips": [...]` mit `file`, `src` (Sekunden in der Datei), `beats` oder `dur`, `speed`,
  `focus`, `push`, `gain` (`"auto"` = Belichtungsformel aus Abschnitt 4), `hdr` (HLG-Tonemapping). Hier laufen Übergänge mit echtem
  Vor- und Nachlauf beider Clips. 4K/60-fps-Clips werden nur im benötigten Ausschnitt dekodiert.
  `speed`: Zahl, `"ramp"`/`"ramp_hold"` (Rezept), `"ramp_in"`, `"ramp_out"`, `"slow_in"`, `"bullet"` (0,25× mit
  Zwischenbildern), `"fast"`, `"slow"` oder Keyframes `[[beat, tempo], ...]`.

## Zeitangaben pro Effekt

`"beat": 4` (ab `beat0`, Sekunden pro Beat = `per`), `"t": 1.71` (Sekunden), `"beats"`/`"dur"` (Länge), mehrere Zeitpunkte mit
`"at_beats": [0, 4, 8]` oder `"at": [...]`, Raster mit `"every": 2, "until": 32`, oder Treffer aus einer Analyse-Datei mit
`"hits": "hits808.json"` (Liste von Sekunden oder Objekten mit `t`). Direkt aus der Song-Analyse (`analyse/song_analyse.py`):
`{"fx": "punch", "hits": "song.json", "kind": "808", "song_start": 12.861}` setzt einen Punch auf jeden frischen 808 im Reel
(`kind`: `808`, `808_nachschlag`, `clap`; `song_start` = Songzeit am Reel-Anfang). Alle Zeiten rasten auf ganze Frames ein.
Übergänge liegen mittig auf dem Schnitt. Ohne Zeitangabe gilt ein Effekt für das ganze Reel (z. B. `grain`, `vignette`).

## Budget (`stil.json`)

`check` und `render` warnen, wenn Flashes, Shakes, Speed-Ramps (nur als Ausnahme auf explosiven Sprüngen) oder Übergangseffekte über dem
Budget in `stil.json` liegen, bei Zeitraffer (Aktionen nie schneller als 1,0×) und bei allem, was nur auf ausdrücklichen Wunsch kommt
(Glitch, Split, Freeze, Whip, Echo, Text …). Was der Nutzer für ein Reel ausdrücklich will, kommt in die spec als
`"erlaubt": ["text", "split", "whip"]`; was immer erlaubt ist, in `stil.json` unter `erlaubt`.

## Effekte

### Übergang (17)

| Effekt | Was | Standard |
|---|---|---|
| `cut` | Harter Schnitt (Standard, zum Vergleich) | Dauer 0.03 s |
| `crossfade` | Weiche Überblendung (Cinematic/R&B, 1–2 Beats) | Dauer 0.86 s |
| `dip_black` | Kurz über Schwarz (Kapitelwechsel, ruhig) | Dauer 0.86 s |
| `dip_white` | Kurz über Weiß (weicher als Flash) | Dauer 0.57 s |
| `zoom_in` | Zoom-Durchflug: A zoomt mit Blur rein, B kommt aus dem Zoom (dezent: 35 %) | Dauer 0.43 s, zoom=0.35, blur=0.1 |
| `zoom_out` | Zoom-Out mit gespiegelten Rändern, B kommt von klein | Dauer 0.43 s, zoom=0.25, blur=0.08 |
| `whip` | Whip-Pan: Bild reißt seitlich weg, Bewegungsunschärfe proportional zum Tempo | Dauer 0.29 s, direction=left, blur=0.35 |
| `slide` | B schiebt A aus dem Bild (Push), wenig Unschärfe | Dauer 0.43 s, direction=up, blur=0.06 |
| `luma_wipe` | Helle Bildteile von A blenden zuerst zu B über (organisch, ruhig) | Dauer 0.86 s, soft=0.25 |
| `wipe` | Weiche Wischblende in eine Richtung (Winkel in Grad, 90 = von oben) | Dauer 0.57 s, angle=90, soft=0.12 |
| `iris` | Kreis öffnet sich aus der Mitte zu B | Dauer 0.57 s, soft=0.06, fx=0.5, fy=0.45 |
| `blur_dip` | A wird unscharf, B wird scharf (weich, fast unsichtbar) | Dauer 0.57 s, sigma=36 |
| `leak_cross` | Überblendung durch ein warmes Light-Leak (emotional) | Dauer 0.86 s, amount=0.7, seed=2 |
| `glitch` | Glitch light: 2–3 Frames Zeilenversatz + RGB-Split um den Schnitt (nur auf Wunsch) | Dauer 0.20 s, amount=0.6 |
| `flash_cut` | Schnitt mit Weißblitz (0,55·e^(−t/0,045 s)), zählt zum Flash-Budget | Dauer 0.30 s, amp=0.55, tau=0.045 |
| `spin` | Dreh-Übergang mit Rotationsunschärfe (20°), eher für Party/Afrobeats | Dauer 0.43 s, angle=20 |
| `doors` | A teilt sich in der Mitte und fährt nach oben/unten weg, dahinter B | Dauer 0.57 s |

### Motion (13)

| Effekt | Was | Standard |
|---|---|---|
| `punch` | Zoom-Punch auf 808: 1 + amp·e^(−t/τ), Zoom-Blur auf den ersten 3 Frames (Rezept) | Dauer 0.60 s, amp=0.14, tau=0.09, blur=3 |
| `punch2` | Zweiter Punch auf dem 808-Nachschlag (0,12 mit Blur) | Dauer 0.60 s, amp=0.12, tau=0.09, blur=3 |
| `mini_punch` | Mini-Punch auf den Clap: 1 + 0,06·e^(−t/0,09 s), ohne Blur, aus der Mitte | Dauer 0.50 s, amp=0.06, tau=0.09, blur=0 |
| `punch_rot` | Punch mit leichter Drehung (1,2°), wirkt lebendiger als der gerade Punch | Dauer 0.60 s, amp=0.1, tau=0.09, rot=1.2, blur=2 |
| `pulse` | Weicher Zoom-Puls: steigt in 60 ms an und fällt wieder, kein Sprung (Groove statt Hit) | Dauer 0.50 s, amp=0.035, attack=0.06 |
| `zoom_step` | Zoom-Stufe: springt in 2 Frames auf +12 % und bleibt bis zum Ende des Fensters | Dauer 0.86 s, amp=0.12, frames=2 |
| `push` | Push-in über das Fenster (typisch +6 bis +12 %), Kurve linear/smooth/ease_out | Dauer 1.71 s, z0=1.0, z1=1.06, curve=linear |
| `pull` | Pull-out: startet 8 % näher und zieht ruhig auf | Dauer 1.71 s, z0=1.08, z1=1.0, curve=ease_out |
| `drift` | Ken-Burns-Schwenk (für Fotos/ruhige Shots): langsam verschieben bei leichtem Zoom | Dauer 1.71 s, dx0=-30, dx1=30, dy0=0, dy1=0, z=1.08, curve=smooth |
| `shake` | Shake auf Schlägen/Treffern: ~18 px, 0,6°, τ 0,14 s, Zoom +5 % mit gleichem Abklingen | Dauer 0.60 s, px=18, deg=0.6, tau=0.14, zoom=0.05 |
| `handheld` | Sehr leichte Handkamera-Bewegung (5 px, 0,2°), macht Stative lebendig | Dauer 1.71 s, px=5.0, deg=0.2, speed=0.6, seed=3 |
| `rotate` | Langsames Kippen (Dutch Angle) von deg0 nach deg1 mit Zoom-Ausgleich | Dauer 1.71 s, deg0=0.0, deg1=2.0, curve=smooth |
| `whip_zoom` | Beschleunigter Zoom zum Shot-Ende mit Zoom-Blur (bisheriges 'whip' aus render.py) | Dauer 0.86 s, amp=0.75 |

### Zeit (5)

| Effekt | Was | Standard |
|---|---|---|
| `freeze` | Freeze-Frame mit Blitz 0,35 und Push +5 % (Shutter-SFX dazu), nur auf Wunsch | Dauer 0.86 s, flash=0.35, push=0.05, bw=False |
| `stutter` | Stotter-Wiederholung: kurzes Stück (¼ Beat) mehrfach (808-Roll, nur auf Wunsch) | Dauer 0.86 s, slice_beats=0.25 |
| `rewind` | Rückspulen: spielt das Vorherige rückwärts (2×), passt zu rewind.wav | Dauer 0.86 s, speed=2.0 |
| `velocity` | Velocity-Edit im Shot: schnell–langsam–schnell, Shot-Länge bleibt (Zwischenbilder per Fluss) | Dauer 1.71 s, shape=hit, interp=flow |
| `echo` | Echo-Nachzieher: 3 frühere Bilder durchscheinend (bisheriges 'echo', nur auf Wunsch) | Dauer 0.86 s, gap=0.05 |

### Look (16)

| Effekt | Was | Standard |
|---|---|---|
| `flash` | Weißblitz 0,55·e^(−t/0,045 s), sparsam (Budget in stil.json), z. B. Kapitelstart, Finale | amp=0.55, tau=0.045 |
| `fade` | Ein-/Ausblenden über Schwarz (mode in/out) | mode=out |
| `vignette` | Vignette 18 % ab 35 % des Radius | amount=0.18, start=0.35 |
| `grain` | Film-Korn, fein und in den Mitten am stärksten (3,5 %) | amount=0.035, size=1.6 |
| `chroma` | Chromatische Aberration am Bildrand (2,5 px), wie ein echtes Objektiv | px=2.5 |
| `rgb_split` | RGB-Versatz auf dem Beat, klingt in ~0,1 s ab (Glitch-Akzent, nur auf Wunsch) | px=10, tau=0.07 |
| `glitch_light` | Kurzer Glitch im Shot (Zeilenversatz + RGB), 3 Frames (nur auf Wunsch) | amount=0.5 |
| `bloom` | Weiches Leuchten der Lichter (Sonne, Himmel), dezent | amount=0.22, thr=0.72, radius=30 |
| `halation` | Film-Halation: rötlicher Schein um helle Kanten | amount=0.2, thr=0.75, radius=14 |
| `light_leak` | Wandernder warmer Lichteinfall (Screen), im Fenster weich ein- und ausgeblendet | amount=0.28, seed=1 |
| `glow_pulse` | Kurzes Aufhellen auf dem Beat (+6 %), weicher Akzent ohne Zoom | amp=0.06, tau=0.1 |
| `exposure` | Belichtung angleichen (gain) im Fenster | gain=1.0 |
| `bw` | Schwarzweiß (weich eingeblendet), z. B. unter einem Freeze | amount=1.0, fade=0.1 |
| `letterbox` | Kino-Balken fahren rein (9 % oben/unten), z. B. fürs Intro | size=0.09, ramp=0.3 |
| `sharpen` | Leichtes Nachschärfen gegen Instagram-Kompression | amount=0.35, sigma=1.2 |
| `focus_pull` | Schärfe ziehen: startet unscharf und wird scharf (Intro/Kapitelstart) | sigma=14, curve=ease_out |

### Text (7)

| Effekt | Was | Standard |
|---|---|---|
| `title` | Titel mit Animation (slide_up, fade, pop, track, blur), automatisch in der Safe Zone | Dauer 1.71 s, text=DEIN TITEL, size=110, y=0.42, weight=ExtraBold, anim=slide_up, t_in=0.35, t_out=0.25, track=4, color=[255, 255, 255] |
| `kinetic` | Kinetic Type: ein Wort pro Beat mit Pop (max. 5 Wörter), replace oder stack | Dauer 1.71 s, text=DEIN TEXT HIER, size=150, y=0.42, weight=Black, step_beats=1.0, mode=replace, color=[255, 255, 255] |
| `typewriter` | Schreibmaschinen-Text, Buchstabe für Buchstabe (typing.wav dazu) | Dauer 1.71 s, text=TAG EINS, size=90, y=0.42, weight=SemiBold, cps=14, cursor=True |
| `lower_third` | Bauchbinde: Balken fährt rein, Name + Zeile darunter (über der unteren Safe Zone) | Dauer 2.57 s, title=NAME, sub=Marke aus stil.json, y=0.72, size=64 |
| `wordmark` | Kleines Wortzeichen (Marke aus stil.json) oben links in der Safe Zone (Branding) | text=Marke aus stil.json, size=34, opacity=0.85, track=6 |
| `counter` | Zahl zählt hoch (z. B. 0 → 10 KM), ease_out über das Fenster | Dauer 1.71 s, start=0, end=10, suffix= KM, decimals=0, size=160, y=0.42 |
| `safezones` | Prüf-Overlay: Instagram-Safe-Zones rot (nie im fertigen Reel lassen) |  |

### Split (3)

| Effekt | Was | Standard |
|---|---|---|
| `split` | 2er/3er-Split übereinander, Streifen fahren gestaffelt rein; mind. 4 Beats stehen lassen | Dauer 2.57 s, gap=8, stagger_beats=0.5, expand_beats=None |
| `grid` | 2×2-Raster, jede Zelle ploppt auf einem Beat auf (4 Quellen) | Dauer 2.57 s, gap=8, stagger_beats=1.0 |
| `pip` | Bild-im-Bild mit runden Ecken und Schatten, fährt von unten rein | Dauer 2.57 s, size=0.44, x=0.5, y=0.36, radius=28 |

## Looks

| Look | Wirkung |
|---|---|
| `moody` | Phonk/nachts: weniger Farbe, härter, dunklere Schatten |
| `bold` | House/Afrobeats: kräftiger, weniger Teal |
| `natural` | Cinematic/R&B: weiche Kurve, halbes Split-Toning |
| `film` | warmer Film-Look, angehobene Schwarzwerte, weiche Lichter (gut mit Grain) |
| `night` | kühler für Abendaufnahmen und Kunstlicht |
| `clean` | neutral: nur leichte Kontrastkurve, keine Farbverschiebung (Grundstil) |
| `mono` | Schwarzweiß mit Kontrast, z. B. für ein Freeze oder das Intro |

Nicht kombinieren und nicht übertreiben. Vergleich am eigenen Material: `python3 looks.py vergleich <bild.jpg> [look …]` legt ein
Standbild (z. B. einen Keyframe aus `$REEL_WORK/kf/`) in allen oder den genannten Looks beschriftet nebeneinander
(`$REEL_WORK/ansicht/looks_vergleich.jpg`, höchstens ~1,1 MP). Einen ganzen Frame des Reels in einem anderen Look:
`REEL_LOOK=<look> python3 ../pipeline/render.py preview <frame>`.

**Eigener Look** in `stil.json`: `"look": {"basis": "natural", "sat": 1.05, "warm": 0.01}` (Parameter wie `grade()` in
`looks.py`: `sat`, `curve`, `lift`, `split`, `teal`, `hue`, `skin`, `shadows`, `warm`, `roll`, `mono`) oder eine fertige
`.cube` aus Lightroom/DaVinci/CapCut: `"look": "referenz/marke/mein_look.cube"` (Pfad relativ zum Projektordner).

## In eigene render.py-Pipelines einbauen

```python
import sys; sys.path.insert(0, "<projekt>/tools/vfx")
import reelvfx as rv
img = rv.apply("grain", img, i=frame_index)            # float32 BGR 0..1
img = rv.apply("punch", img, u=t - t_hit)              # Kamera-Effekt, gibt fertig gewarptes Bild zurück
img = rv.apply("zoom_in", a, u=x, b=b)                 # Übergang, x = 0..1
```

## Passende Soundeffekte (nur auf Wunsch, leise: `gain_db` −14 bis −18)

whip ↔ `swoosh_short`, slide ↔ `swipe_up`/`swipe_down`, zoom_in ↔ `zoom_whoosh`, crossfade/luma_wipe ↔ `whoosh_soft`,
flash/flash_cut ↔ `flash_pop`, freeze ↔ `shutter`, rewind ↔ `rewind`, glitch ↔ `glitch`, kinetic ↔ `pop`, typewriter ↔ `typing`,
title/wordmark ↔ `shimmer`, velocity (Zeitlupe) ↔ `heartbeat`, Start eines Rennens/Events ↔ `startschuss`/`countdown`. Liste: `../../sfx/README.md`.

## Tempo und Grenzen

- Ein Frame braucht je nach Effekt 0,05–0,8 s pro Prozess; `render` nutzt 4 Prozesse. Ein 28-s-Reel dauert etwa 1–4 Minuten.
- Dekodierte Quellen liegen in `/tmp/reelvfx_cache` (anders: Umgebungsvariable `REELVFX_CACHE`). Nach dem Reel löschen, sie sind groß.
- Zwischenbilder (optischer Fluss) können bei sehr schnellen Bewegungen schlieren; Zeitlupe weiter bevorzugt aus 60-fps-Material.
- Text nutzt Montserrat (oder eine Schrift aus `../fonts/`) und bleibt automatisch in den Instagram-Safe-Zones
  (oben 10 %, unten 20 %, rechts 10 %). Text hinter Personen geht nicht (keine Segmentierung).
- `stabilize` nutzt vidstab (2 Pässe, 4 % Zoom), `slowmo` erzeugt Zwischenbilder für Clips ohne 60 fps.
