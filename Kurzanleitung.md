# Reel-Kurzanleitung (Standardfall)

Für Claude: Diese Datei ersetzt im Standardfall das Lesen von `README.md`, `Reel-Studio_Projektanweisungen.md` und den Tool-READMEs. Dazu vor jedem Reel die Kurzfassung des Stils: `sed -n '1,/^---$/p' $P/Stil-Leitfaden.md`. Vorrang: neuestes Feedback des Nutzers > Stil-Leitfaden > Projektanweisungen. Deutsch, kurz, handyfreundlich. Fehlende Angaben selbst entscheiden und nennen, nicht nachfragen. Einziger Pflicht-Stopp: der Nutzer wählt eine von 3 Varianten (Interview-Reels: eine Vorschau, dann sein OK).

## Erster Start

- `python3 $P/tools/stil.py` meldet „NOCH NICHT EINGERICHTET“? Dann vor dem ersten Reel mit dem Nutzer den Abschnitt „Stil festlegen“ im Stil-Leitfaden abarbeiten (eine Nachricht mit Fragen, alles optional). Will er sofort ein Reel, mit dem Grundstil schneiden und das sagen.
- Name und Marke des Nutzers stehen in `stil.json` (`nutzer`, `marke`).

## Sparsam arbeiten (Nutzungslimit)

Jeder Tool-Aufruf schickt den ganzen bisherigen Thread noch einmal mit. Was früh im Kontext landet, zahlt man bei jedem weiteren Schritt erneut.

1. Nur diese Datei und die Stil-Kurzfassung lesen. Lange Dokumente nur gezielt nachschlagen (`grep -n`, dann `sed -n` für den Abschnitt), siehe Tabelle am Ende.
2. Nicht pollen: lange Läufe (ingest, Clip-Analyse, `varianten.py`, Transkript) im Hintergrund starten (Bash `run_in_background` bzw. `setsid nohup … &`), den Exit-Code ins Log schreiben (`…; echo "exit $?" >> log`) und auf die Fertig-Meldung warten. Kein `sleep`, kein wiederholtes `tail` aufs Log.
3. Schritte bündeln: mehrere Befehle in einem Bash-Aufruf (`&&`), Ausgabe kappen (`2>&1 | tail -n 15`).
4. Keine großen Dateien ausgeben: `song.json`, `clips.json`, `shotliste.json`, `qc.json`, Transkript-JSON und Logs nie mit `cat`. Die `.md`-Berichte reichen, einzelne Werte per `python3 -c`.
5. Bilder nur über `tools/ansicht.py` (ein kleines Raster statt vieler Einzelbilder): je Variante einmal `ansicht.py szenen`, dichte Frames nur für unsichere Stellen. Storyboards (1080×5500) nie ganz öffnen, sonst `ansicht.py bild … --teil 1/4`. Jedes Bild einmal ansehen, Befund sofort notieren.
6. Schon Gesichtetes nicht neu ansehen: Sichtungen stehen als Tags-Datei im Reel-Ordner bzw. in `referenz/rohmaterial/`. Neue Sichtung einmal als `tags.json` festhalten.
7. Dateien per Edit ändern statt neu schreiben, in `edl.py` nur den Block „pro Reel anpassen“.
8. Antworten kurz, Zwischenstände nur in einer Status-Checkliste.

## Ablauf

`P=` Projektordner: `/mnt/project-files`, wenn es dort `tools/` gibt, sonst die Repository-Kopie (`P=$(git rev-parse --show-toplevel)`). Dazu `T=$P/tools; W=/home/user/reel` (Arbeitsordner im Container; Downloads, Frames, Master und Mix bleiben dort). Werkzeuge aus `/home/user` oder `/tmp` starten, nie im Projektordner als Arbeitsverzeichnis.

0. **Start:** `cd /tmp && python3 $T/selftest.py 2>&1 | tail -n 4` muss grün sein (prüft auch die Syntax aller Werkzeug-Skripte). Fehlt ffmpeg: `bash $T/setup.sh`.
1. **Ordner:** `python3 $T/neues_reel.py <name>` legt `R=$P/reels/<heute>_<name>` mit `schnitt/A|B|C/edl.py` an (Interview-Reel: `--interview`, Abschnitt unten).
2. **Material:** Drive-Connector `search_files`, Query `parentId = '<Ordner-ID>'`, pageSize 100, alle Seiten. `get_file_permissions` am Ordner: ohne `type: anyone` stoppen und um „Jeder mit dem Link – Betrachter“ bitten (bei `writer`: Betrachter reicht). Manifest: `python3 $T/pipeline/drive.py manifest <Ausgabedateien von search_files> -o $W/manifest.tsv` (dedupliziert, nennt Unterordner mit Namen und ID: die brauchen eine eigene Suche mit `parentId`), dann `drive.py pruefen $W/manifest.tsv` (`--online` fragt jede ID ab). Song: `python3 $T/pipeline/drive.py holen <ID> $W/song.mp3` (prüft Größe, Fehlerseite und Dateikopf, setzt Abbrüche fort). Fotos nur auf Wunsch (`manifest --fotos`). Fehlt der Drive-Connector: den Nutzer bitten, ihn zu verbinden (`EINRICHTUNG.md`).
3. **Sichtung** (Hintergrund): `python3 $T/pipeline/ingest.py` (nennt fehlende Clips mit Grund und Querformat-Clips: die mit `python3 $T/pipeline/reframe.py <clip>` umsetzen, Kontaktbogen ansehen, sonst Ausschuss). Neues Material zusätzlich `python3 $T/analyse/clip_analyse.py --manifest $W/manifest.tsv --schnell -o $R/schnitt/analyse` (Kandidaten genauer mit `--only IMG_…`), `clips.md` und Kontaktbögen einmal ansehen. Kapitel, Tags, besten Moment, sauberes Fenster und Ausschuss als `$R/schnitt/tags.json` im Format von `$T/analyse/tags_beispiel.json`; sauberes Fenster als `"sauber": [von, bis]` in Sekunden, Schwenk, Wischer und Unschärfe am Clip-Rand mit Zeit in `desc`. Hilfe dafür: `python3 $T/pipeline/aktionen.py clip <clip> --laenge <s>` (unsaubere Stellen, ganze Aktionen mit Ruhepunkten, bessere In-Punkte; nur Hinweise). Highlight-Tags `epic` (Gruppe in gehaltener Pose) und `explosiv` (Sprung mit Flugphase) an dichten Frames prüfen; Epic-Shots gezielt suchen, die Clip-Analyse bewertet sie schlecht („kaum Bewegung“). Ausschuss: Stil-Leitfaden Abschnitt 5. O-Ton: `cd /home/user && python3 $T/analyse/oton.py -o $R/schnitt/analyse`, nur `oton.md` lesen (Stellen für `oton="vorn"` mit Quellzeit, `leise` ja/nein, Musik aus einer Box, Wind).
4. **Song:** `python3 $T/analyse/song_analyse.py $W/song.mp3 -o $R/schnitt` schreibt `grid.json` und `song.md` (nur die lesen: Songteile, Eins der Hook, Akzent-Karte je Takt). Die Fenster in `song.md` haben nur 16 oder 8 Takte: Start dort nehmen, Länge nach Regel 2 selbst wählen (volle 4-Takt-Phrasen, so viele, dass `laenge_s` aus `stil.json` erreicht ist; Grundstil 30–40 s: bei 140 BPM 20 Takte, bei 167 BPM 24). „Keine Hook erkannt“: Wiederholung per Takt-Ähnlichkeit suchen, Hook, Break und Drop im README notieren. Akzent-Karte dünn (Bass zwischen den Halbbeats): Akzente aus dem Pegel je Beat. Eine ruhige Phrase oder Bass-Pause vor dem Drop passt zum Einstieg im Video.
5. **Entwurf je Variante:** `python3 $T/analyse/shotliste.py --song $R/schnitt/song.json --tags $R/schnitt/tags.json [--clips …/clips.json] --start-takt N [--takte T] [--auftakt 2] [--meiden $R/schnitt/A/edl.json] -o $R/schnitt/X` (ohne `--takte` nach Regel 2), dann `shotliste.md` lesen. Es bleibt ein Entwurf (ein Shot je Szene, ohne Einstieg und O-Ton): Jump Cuts, Einstieg und O-Ton kommen in Schritt 6 dazu.
6. **Schnittliste:** in `schnitt/X/edl.py` den Block „pro Reel anpassen“ füllen (SONG, START_TAKT = Takt des Drops laut `song.md`, AUFTAKT, TAKTE, EINSTIEG, EINSTIEG_SONG, AUSKLANG, HITS, UNTERSCHIED), dann die Szenen: `s(…)` beginnt eine Szene, `j(…)` ist ein Jump Cut in derselben Szene, `d(…)` eine Dialog-Szene, `oton="leise"` oder `"vorn"` holt den Clip-Ton dazu, `ueber="blende"` blendet 0,4 s über (Beispiel und Erklärung im Kopf der Vorlage). `cd $R/schnitt/X && python3 edl.py`. Die Prüfung (`tools/pipeline/edlcheck.py`, Schwellen aus `stil.json`) meldet Verstöße: Länge, Phrasen, Zeitraffer, Ramps, kurze Teile, Szenenlänge, Jump Cuts, Überblendungen, Einstieg, O-Ton-Momente, Ausklang, 808 am Ende. Jede WARNUNG beheben oder im Steckbrief begründen. Danach `python3 $T/pipeline/aktionen.py edl $R/schnitt/*/edl.json` (Anlauf oder Landung fehlt, Schwenk, unscharf, Jump Cut mitten in eine Aktion, je Shot mit Vorschlag; `--nur 5,8` für einzelne Shots): Hinweise beheben oder begründen. Dann `python3 $T/pipeline/varianten.py $R --check` (jedes Paar in 2 von 3 Punkten verschieden; sonst nachschärfen oder begründen, siehe „Drei Varianten“).
7. **Bauen** (Hintergrund, etwa 8–10 min je Variante): `cd /home/user && python3 $T/pipeline/varianten.py $R 2>&1 | tail -n 25`. Eine Variante neu: `--nur X`.
8. **Sichtprüfung vor dem Vorlegen:** je Variante `python3 $T/ansicht.py szenen $W/master_X.mp4 --edl $R/schnitt/X/edl.json` (4 Bilder je Shot: Anfang, 1/3, 2/3, Ende; #Nr wie im Storyboard). Prüfen: Aktion ganz im Bild (Anlauf bis Landung oder Endposition), Versuch gelungen, kein Schwenk am Anfang oder Ende, im Epic-Shot alle in der Pose, Jump Cuts zwischen ganzen Wiederholungen. Nach Änderungen nur `--von N --bis M`. Dichte Frames einzelner Stellen: `python3 $T/ansicht.py clip <clip> <von> <bis>` (Quellzeit). Dateien aus früheren Läufen nie blind übernehmen.
9. **Pflicht-Stopp:** die 3 Vorschau-Videos und 3 Storyboards (`$R/<name>_X_vorschau.mp4`, `$R/<name>_X_storyboard.jpg`) an den Nutzer (im Claude-Projekt als Anhang; in einer eigenen Session per Datei-Versand oder Pfade nennen, er öffnet sie in der App), je Variante eine Zeile: Songpart (Takte, Zeit), Länge, was sie anders macht. Dazu eine Zeile, was nicht verwendet wird und warum, und wo O-Ton läuft (nur gemessen, der Nutzer hört ab). Dann stoppen.
10. **Feedback vor der Wahl** (gilt für alle Varianten): Schnittlisten nach `archiv/vN_vorschlag/A|B|C/`, Feedback wörtlich ins README, alle drei ändern, Schritt 6–9 wiederholen. „Preview B35“ = Variante B, #35 der zuletzt geschickten Vorschau; Nummern verschieben sich, also in deren `edl.json` nachschlagen und den Clip am Inhalt gegenprüfen. Gescheiterter Versuch: in allen Varianten ersetzen, ähnliche Clips prüfen, in `tags.json` als Ausschuss mit Grund.
11. **Nach der Wahl:** Änderungswünsche (Shot-Nummern) in `schnitt/X/edl.py`, `varianten.py $R --nur X` (neue Vorschau nur bei großen Umbauten schicken), dann `varianten.py $R --wahl X [--titel <frame>]`: Export, `verify.py` muss „alles OK“ melden (YouTube Shorts: `--plattform instagram,youtube`). Bestätigte Fehlalarme (z. B. 808-Meldungen bei durchgehendem Bass) im Steckbrief begründen. Container neu gestartet (Arbeitsordner leer)? Vorher Schritt 2, 3 und `--nur X`. Steckbrief `$R/README.md` ausfüllen.
12. **Liefern:** `<name>_mit_song.mp4`, `_ohne_ton.mp4`, `_titelbild.jpg` an den Nutzer, dazu kurz:
    - Datei unverändert aufs Handy (Download aus Claude, Drive oder AirDrop, nicht WhatsApp). In Instagram „In höchster Qualität hochladen“ an, Upload über WLAN, keine Filter, kein Zuschneiden, keine Effekte. Eigenes Titelbild, Motiv im mittleren 1080×1440-Bereich.
    - Stumme Version: Song in der Instagram-Musikbibliothek am Start des Ausschnitts ansetzen (Zeitstempel nennen).
    - Ordnerfreigabe wieder auf „Eingeschränkt“.
    - Zu große Dateien für den Versand (Grenze je nach App, z. B. 30 MB): Pfade nennen oder eine kleinere HEVC-Kopie zum Herunterladen anbieten (`ffmpeg … -c:v libx265 -b:v 5M -tag:v hvc1 -c:a copy`), das Original bleibt die Upload-Datei.
13. **Feedback nach der Lieferung:** alte Fassung samt Schnittliste nach `archiv/v1/`, `edl.py` ändern, `--nur X`, `--wahl X --fassung v2`. Zum Schluss `python3 $T/ordnung.py`.

## Handwerk, das kein Werkzeug prüft

- Eins der Hook = Taktanfang der Phrase, nicht der erste laute 808. Start und Ende auf einer Phrasengrenze, dort 30–40 ms Fade, in den letzten 150 ms kein 808. Ein Auftakt verlängert das Reel und gehört zu Kapitel 1, er kürzt nie das Ende.
- „Mehr Szenen“ heißt ein längeres Reel mit mehr verschiedenem Material, nicht schnellere Schnitte. Es gibt keine Zielzahl für Szenen pro Sekunde.
- Jede Szene zeigt ihre ganze Aktion, vom Anlauf oder unteren Umkehrpunkt bis zur Landung oder Endposition. Die Szene passt ins saubere Fenster ihres Clips; reicht es nicht: weniger Beats oder ein anderer Clip, nie darüber hinaus. Lieber eine schwache Szene streichen als eine starke kürzen oder beschleunigen. Nie Zeitraffer bei Bewegungen.
- Epic-Shot (mehrere Leute in einer gehaltenen, starken Pose): so lang, wie das Fenster der Pose in 0,5× trägt (Fensterdauer ÷ 0,5, auf gerade Beats abgerundet), nur der Moment, in dem alle die Pose halten, niemand kommt gerade hinein oder fällt heraus.
- Nur gelungene Versuche. Bei der Auswahl reicht der erste saubere, im Schnitt die ganze Wiederholung zeigen.
- In jedem Shot passiert etwas. Ausnahmen: Branding am Anfang, Epic-Pose, Erschöpfung nach der Leistung, Jubel, Finale.
- Jump Cut im selben Clip: von einer ganzen Wiederholung zur nächsten (mindestens 1 s Zeitsprung, von Ruhe zu Ruhe). Anderer Winkel oder nächste Person nur bei derselben Aktion, sonst ist es eine neue Szene.
- Jeder Clip nur in einer Szene. Wechsel total und nah, Einzelne und Gruppe. Wiedererkennung (Logo, Marke, Ort) immer wieder im Hintergrund.
- Peak der Bewegung genau auf dem Hit, an dichten Frames prüfen (Keyframes im Abstand von 1 s täuschen). Zeitlupe nur aus 60-fps-Material. Bei 30-fps-Clips den In-Punkt auf ein Quellbild legen, sonst kann am Schnitt ein Bild doppelt stehen.
- Ramp nur als Ausnahme: `ramp_hold` auf einem explosiven Sprung, Hit auf einem starken 808, die ganze Landung im Bild.
- Push-in nur auf ruhigen Shots (Logo, Epic-Shot, Nahaufnahme, Gruppenbild). Schlussbild: niemanden am Rand anschneiden.
- Ton: Der Song läuft ohne SFX durch und wird nur im Einstieg, in O-Ton-Momenten und im Ausklang leiser; die Pegel setzt `tools/pipeline/tonspur.py`, nichts von Hand. O-Ton vorn nur an guten Stellen (Rufe, Jubel, Lachen, kurze Zurufe), nie mit Musik aus einer Box oder Wind; Gespräche nur im Einstieg. O-Ton gehört zu Echtzeit-Shots. Limiter nur wenn nötig (Decke −0,3 dBTP).
- Keine Reichweite-Extras (Text-Hooks, Captions, Hashtags), außer der Nutzer fragt danach.

## Drei Varianten

Namen und Ideen stehen in `stil.json` (Standard: A Story = Stil-Leitfaden 1:1, Einstieg im Video, Drop auf der Eins der Hook, Szenen mit Jump Cuts, 1 O-Ton-Moment; B Power = andere Songstelle, z. B. Break → Drop, andere Clips per `--meiden`, kurzer Einstieg, kurze Szenen mit Jump Cuts auf den 808, die meisten Punches; C Musikvideo = langer Einstieg, der Song öffnet sich langsam, lange Szenen, Überblendungen an ruhigen Stellen, O-Ton-Momente und Ausklang, die wenigsten Punches). Jedes Paar unterscheidet sich in mindestens 2 von 3 Punkten: Songabschnitt/Länge, Auswahl/Story, Tempo/Effekt-Dichte. Feste Vorgaben des Nutzers (Länge, Opener, ganze Aktionen, Part, Muss rein) gelten für alle drei. Bei 30–40 s teilen sich die Varianten oft viele Clips; dann Songabschnitt, Länge und Dramaturgie (wo Opener, Drop und Highlights liegen) bewusst verschieden wählen und, falls `--check` trotzdem warnt, den Grund im Steckbrief und in der Pflicht-Stopp-Nachricht in einem Satz nennen.

## Interview-Reels (die Stimme führt)

Wenn Leute in die Kamera sprechen (Fragen hinter der Kamera, Antworten) und der Nutzer „Interview-Highlights“ will. Die Stil-Regeln oben gelten hier nicht (dort führt der Song); Grundstil im Stil-Leitfaden Abschnitt 10, Vorlage `reels/_vorlage/interview/`, Werkzeug `tools/pipeline/interview.py` (Kopf erklärt alle Felder).

**Stil** (Grundstil, Zahlen für 1080×1920)
1. **Die Stimme führt, der Song liegt leise darunter.** Unter Sprache 13 LU unter der Stimme, in Pausen ab 0,6 s 6 LU, Mix −14 LUFS, True Peak höchstens −1 dBTP. Das Intro (ohne 808) liegt unter Kapitel 1, der erste 808 genau auf dem Schnitt ins Kapitel 2. Kein SFX.
2. **40–60 s einschließlich Abspann, 4 Kapitel nach dem Gesagten** (z. B. Das erste Mal, Fortschritt, Gemeinschaft, Kommt vorbei). Nur Highlights, ganze Aussagen, nichts doppelt; zum Schluss die Einladung, dann der Abspann. Harte Schnitte, im selben Clip Jump Cuts mit Punch-in (Zoom 1,15–1,35× aus 4K, Gesicht in der Bildmitte), sonst das ganze Bild, Look aus `stil.json`, keine Effekte.
3. **Kein Wort abschneiden.** Geschnitten wird nur in Sprechpausen: Anfang 100 ms vor dem ersten Wort, Ende in der ersten echten Pause nach dem letzten Wort plus bis 0,15 s Ausklang (Whisper setzt Wortenden oft zu früh). Bei „Ende ohne Pause“ oder Zweifel zeigt `--enden` je Teil das letzte Wort mit Pegelverlauf; dann `ende=` oder `anfang=` von Hand setzen.
4. **Untertitel zu jedem gesprochenen Wort:** Antonio Bold, Großbuchstaben, 96 px hoch, einheitlich weiß, kein Rand, dahinter nur ein weicher dunkler Schein. Waagrecht mittig, 65 % Höhe. 1–3 Wörter je Einblendung, gleichmäßig verteilt, ploppt auf, das gesprochene Wort wird kurz größer. Eigene Schrift: `tools/vfx/untertitel.py` (SCHRIFT, SCHRIFT_DATEI, CAP).
5. **Fragen hinter der Kamera** stehen als kleiner weißer Text oben (54 px, 16 % Höhe, bis 3 Zeilen) und blenden 1,0 s nach dem Ende der Frage weich aus.
6. **Abspann:** 0,6 s Überblendung auf Schwarz, alles weiß: Marke (aus `stil.json`) in einer Zeile, darunter Event und Untertitel, Linie, Zeit, Ort, „LINK IN BIO“. Die Zeilen blenden nacheinander ein, zuletzt 0,5 s Blende nach Schwarz, mindestens 4,8 s, Ende auf einer Eins des Songs mit 2 s Ausblende. Event, Zeit und Ort nur aus dem Auftrag; fehlt etwas, weglassen statt raten und in der Nachricht sagen.
7. **Eine Vorschau statt drei Varianten, dann Export.** Der Pflicht-Stopp bleibt: Export erst nach dem OK des Nutzers.

**Ablauf** (Schritt 0 und 2 wie oben; Clip-Analyse, Song-Fenster und Varianten entfallen)
1. `python3 $T/pipeline/ingest.py --keep` (Clips nach `$W/dl/`, Ton nach `$W/audio/`; die 4K-Originale bleiben, der Schnitt zoomt aus ihnen). `python3 $T/neues_reel.py <name> --interview` legt `R` mit Steckbrief und `schnitt/schnitt.py` an. Song laden, `python3 $T/analyse/song_analyse.py $W/song.mp3 -o $R/schnitt`.
2. Transkript (Hintergrund, 2–3× Echtzeit, beim ersten Lauf werden Whisper und das Modell geladen, ~8 GB): `cd /home/user && python3 $T/analyse/transkript.py $W/audio/*.flac -o $R/schnitt/transkript`. Nur `transkript.md` lesen (Fragen hinter der Kamera sind lauter, Wörter mit (?) unsicher). Mehrere Sprecher: `python3 $T/analyse/sprecher.py` (Abschnitt „Hybrid-Shorts“).
3. `schnitt.py` anpassen: Teile `t(clip, "erstes Wort", "letztes Wort", …)`, Fragen mit `stil="frage"`, `DROP_TEIL`, Abspann-Texte. `python3 schnitt.py`, dann `python3 $T/pipeline/interview.py schnitt.json --enden` (Zeiten, Warnungen, Wortenden).
4. Bauen (Hintergrund): `cd /home/user && python3 $T/pipeline/interview.py $R/schnitt/schnitt.json 2>&1 | tail -n 25` schreibt `<name>_vorschau.mp4` und `<name>_storyboard.jpg`. Jede WARNUNG beheben oder benennen.
5. **Pflicht-Stopp:** Vorschau und Storyboard an den Nutzer, Länge, Kapitel in einem Satz, unsichere Stellen (Wörter mit p < 0,5, Deutungen: gemessen, nicht gehört) und „Feedback per #Nummer“.
6. Nach dem OK: `interview.py … --export` (mit `--plattform youtube` die Shorts-Fassung `<name>_yt_…`, ohne „LINK IN BIO“) schreibt `<name>_mit_song.mp4`, `<name>_ohne_song.mp4` und `<name>_titelbild.jpg` und prüft Format, Länge, Lautheit und True Peak. Titelbild ansehen (Augen offen, Blick in die Kamera, Gesicht im mittleren 1080×1440-Bereich), sonst `interview.py … --titelbild <s>`. Liefern wie Schritt 12 oben.

## YouTube Shorts

Nur wenn der Nutzer ein Short will oder „auch für YouTube“ sagt. Der Schnitt bleibt derselbe (gleicher Stil wie die Reels bzw. Interview-Reels); anders sind Export, Pegel, Safe Zones, Abspann und Lieferhinweise. Alle Zahlen stehen als Profil in `tools/pipeline/plattform.py` (`python3 $T/pipeline/plattform.py show youtube`; die YouTube-Angaben stammen aus Web-Recherche).

- **Querformat:** meldet `ingest.py`, `reframe.py` setzt es mit Tracking auf 9:16 um (braucht das YOLOX-Modell, `tools/modelle/yolox/README.md`).
- **Export:** `varianten.py $R --wahl X --plattform instagram,youtube` schreibt beide Fassungen in einem Lauf; Interview-Reels `interview.py … --export --plattform youtube`; ein einzelnes Video `export.py … --plattform youtube`. Dateien `<name>_yt_mit_song.mp4`, `_yt_ohne_ton.mp4`, `_yt_titelbild.jpg`: −14 LUFS, True Peak höchstens −1 dBTP, Länge bis 180 s. Eine fertige Instagram-Fassung wandelt `plattform.py umwandeln <datei> --nach youtube` um.
- **Prüfen:** `plattform.py check <video> --plattform youtube` (Exit 1 bei FEHLER). `plattform.py ui <video> --plattform youtube --zeiten 3,20` legt die Safe Zones als rote Bänder über Frames: Text und Logo bleiben draußen.
- **Liefern:** die Hinweise aus `plattform.py show youtube`: Upload in der App, Titel ist Pflicht, Links in Shorts sind nicht klickbar, Titelbild aus dem Video wählen, Song-Rechte (Content ID): stumme Version hochladen und den Sound aus der YouTube-Bibliothek dazulegen.

## Hybrid-Shorts: Action mit Dialogen

Ein Short darf ein Reel nach den Stil-Regeln sein (Song und Beat-Raster führen) mit **1 bis 3 kurzen Dialog-Szenen** im Hauptteil, hochkant 9:16, Untertitel im Interview-Stil nur in den Dialogen. Die Hilfswerkzeuge gelten ebenso für Interview-Reels. Alles bleibt Vorschlag: der Nutzer wählt weiter eine der 3 Varianten.

- **Dialog-Szene im Reel:** Transkript des Clips (`analyse/transkript.py`), in `edl.py` `TRANSKRIPT = …` und `d(K2, "5315", "erste Wörter", "letzte Wörter", "Beschreibung")` statt `s(...)`. `dialog.py` legt Anfang und Ende in die Stille und rechnet ganze Beats aus (Beat-Summe danach prüfen); die Szene läuft in Echtzeit, der Song geht 16 dB tiefer und gefiltert zurück, `render.py` brennt die Untertitel ein. `edlcheck.py` meldet mehr als 3 Dialoge, Zeitlupe, Dialog in Einstieg oder Ausklang und angeschnittene Wörter.
- **Pausen und Füllwörter kürzen** (Interview-Reels): `"kuerzen": true` in `schnitt.json` (oder `{"pause_max": 0.7, "stark": true}`; je Teil `"kuerzen": false`). Vorschau der Schnitte ohne Bauen: `python3 $T/pipeline/kuerzen.py <ton.flac> --transkript <ordner>`. Füllwörter ohne Stille drumherum schneidet es nicht, es meldet sie zum Abhören.
- **B-Roll über die Stimme:** `python3 $T/pipeline/broll.py schnitt.json --tags <tags.json> [--einsetzen]` schlägt zu Stichwörtern im Gesagten passende Clips vor (Stichwortvergleich mit `tags`/`desc`, keine Bilderkennung). Übernehmen heißt `"bild": [{"clip": "6365", "src": 14.0, "bei": 23.4, "dauer": 1.6}]` im Teil.
- **Mehrkamera:** `python3 $T/pipeline/sync.py 5315 5316 -o sync.json` legt Clips derselben Szene über den Ton auf eine Zeitachse. Läuft Musik aus einer Box in Schleife, ist die Zuordnung mehrdeutig und wird nicht benutzt. In `schnitt.json` `"sync": "sync.json"` und `"bild": [{"kamera": "5316", "ab": 2.0, "dauer": 1.5}]`.
- **Sprecher trennen:** `cd /tmp && python3 $T/analyse/sprecher.py <stamm> -o <ordner> --transkript <ordner> [--sprecher N]` schreibt `sprecher.md` (eine Zeile je Sprecherwechsel). Wer fragt, steht nur als Hinweis da, nie automatisch. Der erste Lauf installiert `sherpa-onnx` und lädt die Modelle (`modelle/sprecher/README.md`).
- **Nicht gebaut:** Querformat 16:9, Langform, Highlights aus langen Videos finden, B-Roll nach Bildinhalt.

## Nachschlagen nur bei Bedarf

| Wenn | Dann |
|---|---|
| Stil noch nicht eingerichtet | `Stil-Leitfaden.md`, Abschnitt „Stil festlegen“ |
| Song-Genre ohne Regel im Leitfaden | `Reel-Studio_Projektanweisungen.md` Abschnitt 3 (Stil-Matrix) und 5 (Looks) |
| O-Ton-Pegel, Einstieg, Ausklang | Kopf von `tools/pipeline/tonspur.py`, `Stil-Leitfaden.md` Abschnitt 8 |
| Sonderwunsch (Text, Split, SFX, anderer Look) | `tools/vfx/README.md`, `sfx/README.md` |
| mehrere Songs, SFX-Mix | Kopf von `tools/reel_audio.py` |
| bessere Ausschnitte, Schwellen von `aktionen.py` | Kopf von `tools/pipeline/aktionen.py`, `referenz/studio/fehlerquellen.md` Abschnitt 9 |
| Werkzeug-Fehler | Kopf des Skripts, `tools/README.md`, `tools/analyse/README.md`, `referenz/studio/fehlerquellen.md` |
| YouTube Shorts: Zahlen, Unterschiede | Kopf von `tools/pipeline/plattform.py`, `referenz/studio/fehlerquellen.md` Abschnitt 4 |
| Hybrid-Short: Dialog, Kürzen, B-Roll, Mehrkamera, Sprecher | Köpfe von `tools/pipeline/dialog.py`, `kuerzen.py`, `broll.py`, `sync.py`, `tools/analyse/sprecher.py`, `referenz/studio/fehlerquellen.md` Abschnitt 10 |
| Interview-Reel: Felder von `schnitt.py`, Transkript-Einrichtung | Kopf von `tools/pipeline/interview.py`, `tools/analyse/transkript.py`, `tools/vfx/untertitel.py` |
| Ordnerregeln, Einrichtung | `README.md`, `EINRICHTUNG.md` |

## Neues Feedback wird zur Regel

Kommt neues Feedback des Nutzers, erst im Reel umsetzen, dann entscheiden: nur dieses Reel (Clip, Shot, Material) oder allgemein (Länge, Szenenlänge, Tempo, Effekte, Opener, Prüfung)? Allgemeines so festhalten:
- Als Prinzip formulieren, ohne Clip-, Shot- oder Songnamen; Zahlen, die vom Tempo abhängen, in Sekunden oder als Formel.
- Die überholte Regel an ihrer Stelle ändern (Kurzfassung und Abschnitte im Stil-Leitfaden, diese Datei, `stil.json`), nicht nur „gilt ab jetzt“ anhängen. Widerspricht neues Feedback einer Regel vom selben Tag, gewinnt das neueste.
- Alle Stellen mitziehen: `grep -rn` nach dem alten Wert in dieser Datei, `Stil-Leitfaden.md`, `stil.json`, `Reel-Studio_Projektanweisungen.md`, `reels/_vorlage/` und den Prüfungen (`tools/pipeline/edlcheck.py`, `tools/analyse/shotliste.py`, `tools/analyse/reel_qc.py`, `tools/pipeline/varianten.py`, `tools/vfx/reelvfx.py`). Was sich nicht sofort anpassen lässt, als offen notieren.
- Eine Zeile ins Änderungsprotokoll des Stil-Leitfadens: Datum, wörtliches Zitat, neue Regel in einem Satz. Im Reel-README nur Zitat, Umsetzung und Verweis auf die Regel.
- Eigene Prüfschritte von Claude sind keine Regeln des Nutzers und werden nicht ihm zugeschrieben.
