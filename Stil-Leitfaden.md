# Stil-Leitfaden No Comfort Zone (NCZ)

**Status:** eingerichtet am 05.10.2026 aus Vorbild 1 (`referenz/stil_leitfaden/vorbild_1/`). Gemessen und übernommen: 45–60 s, Crew-Einstieg mit Gruppenbild, Drop auf der ersten Station, eine Station je Szene, weiche Überblendungen als Markenzeichen, Fahne/Banner als Klammer, wenig Effekte. Offen (Nutzer gefragt): Musik, Einstieg mit O-Ton oder nur Song-Intro, Look, Logo, No-Gos.

**Vorrang:** das neueste Feedback des Nutzers vor diesem Leitfaden, dieser Leitfaden vor Stil-Matrix und Effekt-Rezepten in `Reel-Studio_Projektanweisungen.md`. Ändert sich hier etwas, `stil.json` und bei Bedarf `Kurzanleitung.md` im selben Zug anpassen.

**Herkunft des Grundstils:** Er stammt aus einem Studio, das über Wochen Trainings- und Event-Reels geschnitten hat, und fasst zusammen, was sich dort in vielen Feedback-Runden bewährt hat: ganze Aktionen statt hektischer Schnitte, Einstieg im Video mit echtem Ton, Szenen mit Jump Cuts, 30–40 s in vollen Phrasen. Alles davon darf der Nutzer ändern.

## Kurzfassung: die Regeln (vor jedem Reel lesen)

Gelten für Reels, in denen der Song führt. Für Interview-Reels, in denen Leute in die Kamera sprechen, gilt stattdessen Abschnitt 10: dort führt die Stimme, Untertitel und Abspann gehören dazu.

1. **Der Song ist der Chef, der echte Ton spielt mit.** Der Song läuft ohne Soundeffekte von der ersten bis zur letzten Phrase durch. Leiser wird er nur im Einstieg (Regel 11), in höchstens 2 kurzen O-Ton-Momenten an ruhigen Stellen ohne 808, am besten im Break (Rufe, Lachen, Jubel vorn, der Song etwa 10 dB leiser und dumpfer), und im Ausklang (Regel 12). Unter Echtzeit-Szenen darf guter Originalton leise mitlaufen (Atmen, Rufe; nie Musik aus einer Box, kein Wind).
2. **Volle Phrasen, Länge laut `stil.json`** (NCZ: 45–60 s, wie Vorbild 1). Das Reel besteht aus ganzen 4-Takt-Phrasen (eine Phrase dauert 960/BPM Sekunden): so viele, dass es mindestens `laenge_s[0]` Sekunden lang ist, eine Phrase mehr bis `laenge_s[1]`, wenn ganze Aktionen sonst keinen Platz haben. Der Ausschnitt enthält die Hook oder den Drop und darf in die folgenden Songteile weiterlaufen oder mit einer ruhigen Phrase davor beginnen. Start und Ende auf einer Phrasengrenze, nie mitten im Takt enden, nie einen 808 abschneiden (in den letzten 150 ms kein 808-Einsatz).
3. **Story in 4 Kapiteln aus Szenen** (Namen in `stil.json`, NCZ: Crew, Grind, Power, No Comfort Zone). Jedes Kapitel beginnt auf einer Phrasengrenze und dauert 1–3 Phrasen; der Einstieg meist eine, die Mitte am längsten. Reihenfolge nach Story, nicht nach Uhrzeit.
4. **Stations-Montage, Schnitte auf Schlag 1 oder 3.** Eine Szene ist eine Station mit einer Person oder Gruppe und dauert 1–2 Takte (im Vorbild 2–4 s), so dass viele verschiedene Leute und Übungen vorkommen. Sie wird in 1–3 Teilen gezeigt, innen mit Jump Cuts auf dem Beat: derselbe Clip eine ganze Wiederholung später (mindestens 1 s Zeitsprung), ein anderer Winkel derselben Aktion oder die nächste Person vor derselben Kamera. Jeder Teil dauert so lange wie seine ganze Aktion, auf gerade Beats aufgerundet; 2 Beats nur für durchgehende Bewegung ohne Anfang und Ende (Seilspringen, Laufen, Tanzen) und für kurze Reaktionen (Gesicht, Jubel). Ein Clip kommt nur in einer Szene vor.
5. **Jeder Akzent im Beat bekommt seinen Bild-Akzent** (Abschnitt 3): 808 = Zoom-Punch mit Blur, Nachschlag = zweiter Punch, Clap = Schnitt mit Mini-Punch, sonst harter Schnitt. Fällt ein 808 in einen laufenden Teil, bekommt er den Punch im selben Shot. Auf einem Jump Cut ist der Sprung der Akzent, höchstens mit Mini-Punch. Weiche Überblendungen (0,4 s) sind ein NCZ-Markenzeichen: zwischen Szenen ohne frischen 808, etwa jeder zweite bis dritte Szenenwechsel, höchstens `budget.uebergaenge` (8); auf dem 808 und dem Drop bleibt der harte Schnitt.
6. **Kein Teil kürzer als 2 Beats.** Einzige Ausnahme: eine Salve aus höchstens 4 Jump Cuts à 1 Beat in durchgehender Bewegung, einmal pro Reel. Sonst schnelle Bass-Folgen mit Punches im selben Shot spielen.
7. **Ganze, gelungene Aktionen in Echtzeit.** Jede Szene zeigt ihre Aktion ganz, vom Anlauf oder unteren Umkehrpunkt bis zur Landung oder Endposition; der Schnitt kommt danach. Nie schneller als 1,0× (kein Zeitraffer). Lieber eine schwache Szene streichen als eine Aktion abschneiden. Keine gescheiterten Versuche.
8. **Speed-Ramps nur als Ausnahme.** Standard: keine (Vorbild: keine). Erlaubt nur auf explosiven Sprüngen mit Flugphase, als `ramp_hold`, Hit auf einem starken 808, die ganze Landung im Bild. Höchstens `budget.ramps`.
9. **Effekte sparsam, Handkamera-Gefühl:** keine Flashes, kein Shake (`budget` 0). Punches nur leicht (808 0,08, Nachschlag 0,06, Clap 0,04), die Bewegung kommt aus der Kamera nah am Geschehen.
10. **Kein Glitch, Split-Screen, Freeze, Whip, Echo, keine SFX, kein Text**, außer der Nutzer will es (oder `stil.json` → `erlaubt`). Interview-Reels: Untertitel und Abspann gehören dazu.
11. **Einstieg im Video, Wiedererkennung sofort** (`einstieg_im_video` in `stil.json`). Das Reel beginnt mit einem echten Moment und seinem Ton, am liebsten Logo oder Marke vor Ort (leichte Zeitlupe ~0,75× geht, der Ton läuft dann als Atmo in Echtzeit), sonst Leute, die sich sammeln, oder eine Ansage. Der Einstieg dauert 2, 4 oder 8 Beats oder eine ruhige Phrase, der Song klingt dabei gedämpft wie aus einer Box vor Ort; läuft im Clip-Ton schon Musik, setzt der Song erst auf dem Drop ein. NCZ (Vorbild 1): die Crew sammelt sich, dann das Gruppenbild vor dem Banner als Epic-Shot (`epic_opener`) noch vor dem Drop; auf dem Drop kommt mit hartem Schnitt die erste Station. Sonst gilt: auf dem Drop das stärkste Bild, am liebsten ein Epic-Shot (mehrere Leute gleichzeitig in einer gehaltenen, starken Pose) in 0,5× mit langsamem Push-in, nur im Fenster, in dem alle die Pose halten. Ohne Einstieg im Video: das stärkste Bild auf dem ersten Hit, Marke in den ersten 3 Sekunden.
12. **Finale und Ausklang:** Schlussbild mindestens 4 Beats (Standard 8), in Echtzeit mit Push-in ~12 % (laut `stil.json` → `finale`), am liebsten die schwenkende NCZ-Fahne, bis zum Ende des Songs. Danach darf 1 Takt Ausklang mit echtem Ton folgen (Lachen, Jubel, Durchatmen; Song aus). Anfang und Ende zeigen beide die Wiedererkennung, so loopt es sauber.

---

## Stil festlegen (einmalig, vor dem ersten Reel)

Ziel: aus dem Grundstil den Stil des Nutzers machen, mit möglichst wenig Fragen. So ist auch das Original-Studio entstanden: Vorbild-Reels, die dem Nutzer gefielen, wurden vermessen, seine Kritik an den ersten Schnitten wurde zu Regeln.

1. **Fragen, eine Nachricht, alles optional** (was fehlt, entscheidest du und nennst es):
   - Account bzw. Marke, dein Name für den Nutzer, worum es in den Reels geht, für wen.
   - 1–3 Reels, die ihm gefallen (eigene oder fremde), **als Videodatei im Drive-Ordner**: Instagram-Links kann der Server nicht öffnen. Was genau gefällt daran?
   - Musik: welche Genres, gern ein typischer Song.
   - Länge: eher kurz (15–25 s) oder ausführlich (30–40 s, Grundstil)?
   - Einstieg: mit echtem Moment und O-Ton (Grundstil) oder sofort mit dem Song?
   - Look: natürlich, kräftig, dunkel/moody, Film, Schwarzweiß? Gibt es schon einen Filter/Preset (.cube aus Lightroom, DaVinci, CapCut)?
   - Text im Video, Untertitel, Soundeffekte: nie, manchmal, immer? Interviews oder Gesprochenes geplant?
   - Logo (PNG/SVG), Schrift, Farben, Wiedererkennung (Ort, Shirt, Banner, Maskottchen).
   - No-Gos.
2. **Vorbilder vermessen:** je Vorbild-Reel `python3 $T/analyse/referenz_analyse.py <reel.mp4> -o $W/ref_1` (Übergänge, Shots, Jump Cuts, Szenen, Beat, Tonschichten; `referenz.md` lesen) und `python3 $T/analyse/reel_qc.py <reel.mp4> -o $W/ref_1` (Schnittlängen, Punches, Flashes, Lautheit, Ende auf Taktgrenze), dazu `python3 $T/ansicht.py reel <reel.mp4>` einmal ansehen (Look, Motive, Text, Übergänge). Befunde als Tabelle in Abschnitt 1 unten.
3. **Werte ableiten:** Länge (`laenge_s`), Szenenlänge (`budget.min_beats`, `budget.aktion_beats`), Effekt-Budget, Einstieg im Video (`einstieg_im_video`), Epic-Shot am Anfang (`epic_opener`), erlaubte Extras, Kapitel-Namen passend zum Inhalt (Beispiele in Abschnitt 4), Stichwörter für durchgehende Bewegung, Sprünge und Schläge (`stichwoerter`), Varianten A/B/C (Namen und Ideen dürfen zum Inhalt passen).
4. **Look wählen:** ein typisches Standbild aus dem Material des Nutzers (Keyframe aus `$W/kf/…` nach `ingest.py`) in allen Looks zeigen: `python3 $T/vfx/looks.py vergleich <bild.jpg>` (ein Bild, beschriftet; Looks in `tools/vfx/README.md`). Der Nutzer wählt. Eigene `.cube` nach `referenz/marke/` und in `stil.json` eintragen.
5. **Eintragen:** `stil.json` (`eingerichtet: true`, `marke`, `nutzer`, `inhalt`, `look`, `kapitel`, `laenge_s`, `budget`, `erlaubt`, `varianten` …), diesen Leitfaden (Status oben, Kurzfassung, Abschnitte 1–10), Logo und Schriften nach `referenz/marke/` bzw. `tools/fonts/`. `python3 tools/stil.py` muss „Stil eingerichtet“ melden.
6. **Erstes Reel als Test:** Feedback wörtlich mit Datum ins Änderungsprotokoll, was dauerhaft gilt, als Regel hier und in `stil.json` (Vorgehen: Kurzanleitung, „Neues Feedback wird zur Regel“).

## 1. Marke und Inhalt (ausfüllen)

| | |
|---|---|
| Marke / Account | No Comfort Zone (NCZ), Schriftzug „nocomfort zone“ |
| Nutzer (so nennst du ihn) | Noah |
| Inhalt, Zielgruppe | Outdoor-Community-Workouts im Calisthenics-Park (Battle Ropes, Klimmzüge, Dips, Liegestütze, Box Jumps, Kettlebell, Front Lever), für Leute, die mittrainieren wollen |
| Wiedererkennung | schwarze Fahne und Banner mit weißem „nocomfort zone“, blauer Boden, Stangen-Parcours, Battle Ropes mit gelben Griffen; Person, die die Fahne schwenkt, als wiederkehrendes Motiv |
| Vorbild-Reels | Vorbild 1 (`referenz/stil_leitfaden/vorbild_1/`), Messwerte unten |
| Musik | Vorbild: ~103 BPM, Intro ohne Bass, Drop auf der ersten Station; Genres offen |
| No-Gos | offen |

**Vorbild 1, gemessen** (61,8 s, 720×1280, 30 fps; Shots an dichten Frames gezählt, die Schnitterkennung sieht die Überblendungen nicht):

| | |
|---|---|
| Länge | 60,4 s Bild + 1,4 s Schwarz, ~6 Phrasen à 9,3 s |
| Einstieg | 0–7,7 s: Crew läuft zusammen, dann Gruppenbild sitzend/stehend vor dem Banner (~3,5 s gehalten); Song-Intro ohne Bass, leise (−26 LUFS kurzzeitig) |
| Drop | ~8 s, harter Schnitt auf die erste Station (Dips), Bass setzt ein |
| Szenen | ~28 Shots in 52 s, meist 1,5–3 s (3–5 Beats), eine Station je Szene, fast nur verschiedene Leute; Jump Cuts selten (nächste Person an derselben Station) |
| Überblendungen | ~12 weiche Blenden à 0,3–0,5 s zwischen Stationen, sonst harte Schnitte |
| Effekte | keine Flashes, kein Shake, keine Ramps, kein Text, keine SFX; Bewegung aus der Handkamera (nah, Weitwinkel, leichte Untersicht) |
| Motiv | Fahne „nocomfort zone“ 5× als Zwischenschnitt (≈ alle 10–15 s), Banner oft im Hintergrund, Schlussbild Fahne |
| Ton | Song durchgehend, kein O-Ton hörbar, −14,3 LUFS |
| Look | natürlich, sonnig, kräftiges Blau und Grün ohne Grading (`clean`) |
| Schwächen, die wir besser machen | Schnitte nur zur Hälfte auf dem Beat, Ende nicht auf der Taktgrenze (808 abgeschnitten), 720p |

## 2. Rhythmus und Schnitt (Grundstil)

- **Raster:** Schnitte auf Schlag 1 oder 3, Dramaturgie in Phrasen zu 4 Takten. Kapitel beginnen auf Phrasengrenzen.
- **Länge:** volle 4-Takt-Phrasen, mindestens `laenge_s[0]` (NCZ 45 s), weitere Phrasen bis `laenge_s[1]` (60 s), wenn ganze Aktionen sonst keinen Platz haben (bei 103 BPM: 5–6 Phrasen). Kürzer (8 Takte) nur auf Wunsch. Beispiel: 140 BPM → 20 Takte, 167 BPM → 24 Takte.
- **Start:** die Eins der Hook (oder des Drops) ist der Taktanfang der Phrase, nicht der erste laute Bass-Schlag. Ein Einstieg im Video (Auftakt von 2, 4 oder 8 Beats) verlängert das Reel und gehört zu Kapitel 1, er kürzt nie das Ende. Ende auf einer Phrasengrenze, 30–40 ms Fade, in den letzten 150 ms kein 808.
- **Szenenlänge:** so lang wie die ganze Aktion, meist 4–8 Beats je Teil. Kürzer als `budget.aktion_beats` nur für durchgehende Bewegung und kurze Reaktionen; kein Teil unter `budget.min_beats` (außer einer Salve). „Mehr Szenen“ heißt ein längeres Reel mit mehr Material, nicht schnellere Schnitte. Es gibt keine Zielzahl für Szenen pro Sekunde.
- **Andere Genres:** Stil-Matrix in `Reel-Studio_Projektanweisungen.md` Abschnitt 3 (z. B. House: 8-Takt-Phrasen, Drop = Highlight; Cinematic: lange Shots, kaum Punches). Wird ein Genre zum Standard, hier eintragen.

## 3. Akzente: Ton → Bild

Vor der Schnittliste pro Halbbeat bestimmen, was im Song passiert (`song_analyse.py` schreibt die Akzent-Karte; ist sie dünn, Akzente aus dem Pegel je Beat). Dann gilt:

| Im Song | Im Bild | Rezept (Stärke in `stil.json` → `punch`) |
|---|---|---|
| frischer 808 / Kick | Schnitt oder Punch mit Zoom-Blur | Zoom 1 + 0,14·e^(−t/0,09 s), Blur auf den ersten 3 Frames; am Ramp-Hit 0,126 |
| Nachschlag 1 Beat später | zweiter Punch im selben Shot | 0,12 mit Blur; in einer Zeitlupe 0,05 ohne Blur |
| Clap/Snare auf Schlag 3, kein 808 | Schnitt mit Mini-Punch | 1 + 0,06·e^(−t/0,09 s), ohne Blur, aus der Bildmitte |
| Schlag 1 ohne 808 und Clap | harter Schnitt | kein Effekt |
| Jump Cut | der Sprung ist der Akzent | höchstens Mini-Punch |
| Break (kein 808, kein Clap) | kein Akzent | Zeitlupe, ruhiger Push-in, Überblendung oder O-Ton-Moment |

Der Mini-Punch fällt auf den Schnitt: Man sieht kein Hineinzoomen, nur wie das neue Bild in ~0,27 s um 6 % zurückzoomt. Das macht den Schnitt weich. Wer keine Punches will: `punch` in `stil.json` auf 0 setzen und hier streichen.

**Speed-Ramp (Ausnahme, 4 Beats, `ramp_hold`):** Schnitt mit Mini-Punch (~1,0×), Tempo steigt auf ~2×, auf dem Hit (Beat 2, Punch 0,126) in ~3 Frames auf 0,5× und bleibt dort (Landung, Abschluss). Der Höhepunkt der Bewegung liegt genau auf dem Hit, an dichten Frames prüfen. Zeitlupe nur aus 60-fps-Material.

## 4. Story und Kapitel

- 4 Kapitel auf Phrasengrenzen, je 1–3 Phrasen; unter 4 Phrasen teilen sich die beiden mittleren eine.
- Muster: **Einstieg** (wer/was, Wiedererkennung, Epic-Shot) → **Aufbau** (Arbeit, Prozess, Vielfalt) → **Höhepunkt** (stärkste Action, Showpieces) → **Finale** (Payoff, Emotion, Gruppe, Schlussbild).
- Namen passend zum Inhalt in `stil.json` → `kapitel`, zum Beispiel:
  - Sport/Fitness: Identität, Grind, Power, Crew
  - Food: Zutaten, Zubereitung, Anrichten, Genuss
  - Event/Konzert: Anreise, Aufbau, Show, Crowd
  - Handwerk/Produkt: Material, Arbeit, Detail, Ergebnis
- Shot-Auswahl nach Thema des Kapitels, nicht nach Uhrzeit. Payoff-Clips (Ergebnis, Ziel, Auftritt) nur im letzten Kapitel.

## 5. Shot-Auswahl

- **Opener:** Einstieg im Video mit echtem Moment (Regel 11), auf dem Drop das stärkste Bild. Ohne Einstieg: das stärkste, klarste Bild auf dem ersten Hit, kein Intro.
- **Epic-Shot:** mehrere Leute gleichzeitig in einer gehaltenen Pose; so lang, wie das Fenster der Pose in 0,5× trägt (Fensterdauer ÷ 0,5, auf gerade Beats abgerundet), nur der Moment, in dem alle die Pose halten. Die Clip-Analyse bewertet solche Clips schlecht („kaum Bewegung“): gezielt suchen.
- **Wiedererkennung** in den ersten 3 Sekunden (Logo, Ort, Kleidung, Banner), danach immer wieder im Hintergrund.
- **Vielfalt:** jeder Clip nur in einer Szene. Wechsel zwischen total und nah, Einzelnen und Gruppe. Ein wiederkehrendes Motiv ist erlaubt (immer andere Leute und Perspektiven).
- **In jedem Shot passiert etwas.** Ausnahmen: Branding am Anfang, Epic-Pose, Emotion nach der Leistung, Finale. Gekürzt wird an Szenen, in denen nichts passiert, nie an starken.
- **Ganze Aktionen im sauberen Fenster:** pro Shot notieren, welcher Teil zu sehen ist, nie nur die Ausholbewegung. Die Szene bleibt im sauberen Fenster des Clips (kein Schwenk, Wischer, Unschärfe am Rand; `aktionen.py` hilft). Nur gelungene Versuche.
- **Showpieces** (Sprünge, Tricks, Höhepunkte) je Kapitel einmal, ganz gezeigt.
- **Ausschuss:** versehentliche Clips, Person winzig oder weit weg, Selfie- und Talking-Head-Monologe (außer im Interview-Reel), schon geschnittene Videos (`copy_…`, CapCut-Exporte), Duplikate, gescheiterte Versuche, Fotos ohne Wunsch.

## 6. Effekte und Budget

- „Smooth und klein“: Obergrenze ist das Budget in `stil.json` (NCZ: 1 Ramp nur als Ausnahme, 0 Flashes, 0 Shakes, 8 Überblendungen). `edl.py` (über `edlcheck.py`), `shotliste.py` und `vfx/reelvfx.py check` warnen darüber.
- Push-in +6–12 % nur auf ruhigen Shots (Marke, Epic-Shot, Nahaufnahme, Schlussbild). Start-Zoom bis ~1,33× nur bei 4K-Material. Alles andere in Echtzeit, nie schneller.
- Split-Screen nur auf Wunsch, dann mindestens 4 Beats und nicht direkt in einen kurzen Shot.
- Kein Korn, keine extreme Schärfe (Instagram macht daraus Blockrauschen bzw. Halos).

## 7. Look

- Look aus `stil.json` (Grundstil `clean`: nur leichte Kontrastkurve, keine Farbverschiebung), dazu Belichtungsangleich pro Shot und Vignette (`vignette`, Standard 12 %).
- Grading zurückhaltend: erst korrigieren (Belichtung, Weißabgleich), dann stylen; Hauttöne schützen, kein schweres Teal-Orange.
- HDR-Clips (HLG vom iPhone) werden automatisch getonemappt.

## 8. Ton, Text und Extras

- Song ohne SFX, Pegel unverändert außer im Einstieg (gedämpft), in O-Ton-Momenten (~10 dB leiser, dumpfer) und im Ausklang (aus). Die Pegel setzt `tools/pipeline/tonspur.py`, nichts von Hand. Limiter nur wenn nötig (Decke −0,3 dBTP). Ende mit 30–40 ms Fade-out auf einer Phrasengrenze.
- O-Ton (`analyse/oton.py`): vorn nur an guten Stellen (Rufe, Jubel, Lachen, Keuchen, kurze Zurufe), leise nur ohne Musik aus einer Box und ohne Wind, Gespräche nur im Einstieg. Clips mit Musik im Ton nur im Einstieg und dann `EINSTIEG_SONG = "aus"`. O-Ton gehört zu Echtzeit-Shots; unter Zeitlupe nur Atmo ohne sichtbares Sprechen.
- Standard ohne SFX; auf Wunsch höchstens 1–2 leise (−14 bis −18 dB).
- Text nur auf Wunsch: höchstens 5 Wörter, kinetisch, in den Safe Zones (oben 10 %, unten 20 %, rechts 10 % frei). Schrift aus `tools/fonts/` oder die eigene Markenschrift dort.
- Keine Reichweite-Extras (Text-Hooks, Captions, Hashtags), außer der Nutzer fragt danach.

## 9. Checkliste

**Vor dem Storyboard**
- [ ] Start auf der Eins von Hook oder Drop, Länge in vollen Phrasen laut `stil.json`, Ende auf einer Phrasengrenze ohne 808 in den letzten 150 ms.
- [ ] Akzent-Karte pro Halbbeat: 808, Nachschlag, Clap, Break.
- [ ] 4 Kapitel mit Thema, jedes startet auf einer Phrase.
- [ ] Einstieg im Video mit O-Ton (falls `einstieg_im_video`), auf dem Drop das stärkste Bild.
- [ ] Jede Szene zeigt ihre ganze Aktion im sauberen Fenster, Jump Cuts von ganzer Wiederholung zu ganzer Wiederholung.
- [ ] Jeder Schnitt und Punch hat den Akzent aus Abschnitt 3, kein Teil unter der Mindestlänge.
- [ ] Effekt-Budget aus `stil.json` eingehalten, keine Ramps außer auf explosiven Sprüngen, keine Extras ohne Wunsch.
- [ ] O-Ton nur an guten Stellen, höchstens 2 Momente, keine Musik aus einer Box.
- [ ] Finale laut `stil.json` (Länge, Zeitlupe, Push-in), Ausklang falls genutzt.
- [ ] `edl.py` ohne WARNUNG (oder begründet), `aktionen.py edl` gesichtet, `ansicht.py szenen` je Variante angesehen.

**Vor der Abgabe**
- [ ] `verify.py` meldet „alles OK“ (bestätigte Fehlalarme im Steckbrief begründet).
- [ ] Letztes Sample auf der Phrasengrenze, kein 808-Einsatz in den letzten 150 ms.
- [ ] Jede Bewegung an dichten Frames komplett (Endposition im Bild), kein doppeltes Bild am Schnitt.
- [ ] Loop Ende zu Anfang angesehen.
- [ ] YouTube Shorts: `plattform.py check … --plattform youtube` ohne FEHLER, Safe Zones angesehen.

## 10. Interview-Reels (Grundstil)

Wenn Leute in die Kamera sprechen und der Nutzer „Interview-Highlights“ will. Die Stimme führt, der Song liegt leise darunter; Ablauf und Zahlen in `Kurzanleitung.md`, Abschnitt „Interview-Reels“. Kurz:

- **Länge** 40–60 s einschließlich Abspann, **4 Kapitel nach dem Gesagten**, nur Highlights, ganze Aussagen, zum Schluss die Einladung, dann der Abspann.
- **Ton:** Stimme vorn, Song 13 LU darunter, in Pausen 6 LU, Mix −14 LUFS, True Peak höchstens −1 dBTP. Das Song-Intro liegt unter Kapitel 1, der erste 808 genau auf dem Schnitt ins Kapitel 2.
- **Schnitt:** nur in Sprechpausen, nie ein Wort abschneiden (Whisper setzt Wortenden oft zu früh: `interview.py --enden` prüfen). Jump Cuts im selben Clip mit Punch-in 1,15–1,35× (Gesicht in der Mitte), sonst das ganze Bild, keine Effekte.
- **Untertitel** zu jedem Wort: schmale fette Schrift (Antonio Bold) in Großbuchstaben, weiß ohne Rand mit weichem Schein, 1–3 Wörter je Einblendung, 65 % Höhe. **Fragen hinter der Kamera** klein oben, blenden 1,0 s nach der Frage aus.
- **Abspann:** Marke (aus `stil.json`), Event, Zeit, Ort, „LINK IN BIO“ (YouTube ohne), Zeilen blenden nacheinander ein, Ende auf einer Eins des Songs. Nur Angaben aus dem Auftrag, nichts raten.
- **Eine Vorschau statt drei Varianten**, Export erst nach dem OK des Nutzers.
- **YouTube Shorts:** derselbe Stil, Export und Pegel nach `plattform.py` (Kurzanleitung, Abschnitt „YouTube Shorts“). Hybrid-Shorts (Reel mit 1–3 Dialog-Szenen): Kurzanleitung, Abschnitt „Hybrid-Shorts“.

Eigene Schrift, Farbe oder Abspann des Nutzers: hier eintragen und in `tools/vfx/untertitel.py` (SCHRIFT, SCHRIFT_DATEI, CAP) bzw. in `abspann_event` der Vorlage `reels/_vorlage/interview/schnitt.py` umsetzen.

---

## Änderungsprotokoll

- (Datum): Vorlage übernommen, Grundstil gilt.
- 05.10.2026: „Bitte analysiere dieses Reel und bau daraus unseren Stil im NCZ Studio“ – Vorbild 1 vermessen; Länge 45–60 s, Kapitel Crew/Grind/Power/No Comfort Zone, Stations-Montage, bis 8 weiche Überblendungen ohne 808, Gruppenbild-Opener, leichte Punches, keine Flashes/Shakes, Finale in Echtzeit mit Fahne.
