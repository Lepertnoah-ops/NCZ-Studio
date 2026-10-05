# Fehlerquellen, Lösungen und Grenzen der Werkzeuge

Erfahrungen aus dem Betrieb des Studios, aus dem diese Vorlage stammt: was typischerweise schiefgeht, wie die Werkzeuge es abfangen und wo sie an Grenzen stoßen. Für Claude zum Nachschlagen, wenn ein Werkzeug hakt oder ein Ergebnis seltsam aussieht.

## 1. Kurzfassung

1. **Die meisten Fehler kommen von außen, nicht aus dem Schnitt:** Drive (Freigabe, doppelte Einträge, Fehlerseiten statt Video), die Umgebung (OpenCV 5 ohne Personen- und Gesichtsdetektor, gesperrte Hosts, frischer Container) und Hintergrundläufe. Dafür gibt es `drive.py`, `personen.py`, eine robuste Sichtung und einen Syntax-Check im Selbsttest.
2. **Fehler im Schnitt** (abgeschnittene Aktion, gescheiterter Versuch, abgeschnittenes Wort) prüft `edlcheck.py` nur, soweit sie sich zählen lassen. Ob eine Aktion ganz im Bild ist, misst `pipeline/aktionen.py` als Hinweis (Abschnitt 9). Ob ein Versuch gelingt, erkennt kein Werkzeug: das bleibt Sichtprüfung mit `ansicht.py szenen`.
3. **Zwei Lieferformen:** Export, Pegel, Safe Zones und Abspann hängen an einem Profil (`pipeline/plattform.py`). Mit `--plattform youtube` entstehen Dateien mit der Endung `_yt`.
4. **YouTube ist nicht am Original geprüft.** Die YouTube-Zahlen stammen aus Web-Recherche. Ein privater Test-Upload durch den Nutzer klärt, wie YouTube die Dateien verarbeitet.

## 2. Typische Fehlerquellen und wie sie gelöst sind

### Drive und Download

| Fehler | Lösung |
|---|---|
| Freigabe fehlt: jeder Download leitet auf die Google-Anmeldung um (HTTP 403 über den Proxy) | Freigabe am Ordner prüfen („Jeder mit dem Link – Betrachter“); `drive.py holen` meldet „nicht freigegeben“ sofort |
| Listing mit doppelten Einträgen | `drive.py manifest`: dieselbe ID zählt einmal, gleicher Name und gleiche Größe gilt als Duplikat, gleicher Name mit anderer Größe wird umbenannt (`~<id>`); `reelcfg.manifest()` warnt bei doppeltem Dateistamm |
| Fehlerseite als Video abgelegt (eine falsche ID liefert eine kleine HTML-Seite) | Range-Vorabfrage (Gesamtgröße), HTML-Erkennung, Dateikopf muss zur Endung passen, Download in `.part` mit Fortsetzen |
| Endgültige Fehler (403, 404) wurden mehrfach mit Wartezeit wiederholt | 400, 401, 403 und 404 brechen sofort ab, alles andere bis zu 5 Versuche |
| Ein defekter oder abgeschnittener Clip beendete die ganze Sichtung | `ingest.py` fängt Fehler je Clip ab, die Zusammenfassung nennt fehlende Clips mit Grund |
| Unterordner bleiben unsichtbar: `search_files` mit `parentId` liefert nur eine Ebene, Ordnernamen haben manchmal ein Leerzeichen am Ende | `drive.py manifest` meldet Unterordner mit Name und ID, gesucht wird immer über die ID |

### Video

| Fehler | Lösung |
|---|---|
| HLG-Clips (iPhone-HDR) wirken ohne Tonemapping grau | `reelcfg.tonemap_for(trc)` auf allen Wegen, auch in `reframe.py` |
| Weiche Frames bei Zoom mit Sub-Pixel-Versatz | Lanczos in der Pipeline; im Tracking `INTER_CUBIC` (deutlich schneller) |
| Punch, Shake und Flash saßen einen Frame zu spät | setzen auf dem Frame ein, der dem Beat am nächsten liegt |
| Querformat: der Mitteschnitt auf 9:16 zeigt nur 32 % der Breite | Warnung in `ingest.py` und `extract.py`; `reframe.py` folgt den Personen (YOLOX) und der Bewegung |
| Peaks in der 1-Bild-pro-Sekunde-Vorschau täuschen | dichte Frames mit `ansicht.py clip` vor dem Rendern |
| Szene endet vor ihrer Aktion, Kamera schwenkt am Clipende weg, Material doppelt am Schnitt | vor dem Vorlegen `ansicht.py szenen` (4 Bilder je Shot) und `aktionen.py edl`; bei 30-fps-Clips den In-Punkt auf ein Quellbild legen (src = Bildnummer / 30), sonst kann das erste Bild doppelt erscheinen |
| `-shortest` bei Stream-Copy verliert die letzten Bilder | die Exportprüfung meldet Länge Bild gegen Ton |
| Titelbild bei 0,5 s war oft ein Blinzeln | `interview.py --titelbild <s>` zieht nur das Bild neu |

### Ton

| Fehler | Lösung |
|---|---|
| `-ss` als Output-Option mit `afade st=` macht die Tonspur ab der Mitte stumm | `atrim`, Pegel über die volle Länge prüfen |
| Tempo ändern: `pedalboard.time_stretch` driftet bis 30 ms, ffmpeg `atempo` hat ~17 ms Versatz | `rubberband-cli` |
| MP3 mit Cover bricht ab, weil ffmpeg das Cover als Videospur schreiben will | `-vn` |
| Whisper setzt Wortenden 0,2–0,55 s zu früh, Wörter werden abgeschnitten | Schnitt nur in Sprechpausen, `interview.py --enden` zeigt die Pegel |
| Musik aus einer Box im Clip-Ton (bei Trainings und Events häufig) | `analyse/oton.py` (YAMNet) erkennt sie, im Schnitt nur im Einstieg mit Song aus; auf YouTube kommt das Content-ID-Risiko dazu |
| `verify.py` meldet bei Songs mit durchgehendem 808-Bass (MP3) „808 gegen Bild“ oder „808 vor dem Ende“, obwohl dort kein neuer Einsatz liegt | mit dem Pegelverlauf je Beat gegenprüfen (`song.json` „onsets“, Akzent-Karte); bestätigte Fehlalarme im Steckbrief begründen |
| Ein Pegel für alles: YouTube regelt auf etwa −14 LUFS und will True Peak unter −1 dBTP, Instagram behält den Songpegel | Pegel pro Profil; die Prüfung meldet einen Instagram-Pegel gegen das YouTube-Profil als FEHLER |

### Umgebung und Arbeitsweise

| Fehler | Lösung |
|---|---|
| Jeder Chat bzw. jede Session startet in einem frischen Container | Setup-Skript der Umgebung, `selftest.py` als Schritt 0, Downloads nur im Arbeitsordner |
| Hintergrundprozesse sterben mit dem Tool-Aufruf | `run_in_background` oder `setsid nohup` |
| Die Fertig-Meldung eines Hintergrundlaufs sagt „exit code 0“, obwohl der Lauf mit Traceback endete (der Wrapper mit `; echo` oder `tail` verdeckt den Exit-Code) | Exit-Code ins Log schreiben (`…; echo "exit $?" >> log`) und die letzte Logzeile lesen |
| Ein halb gespeicherter Edit in einem Skript fällt erst im langen Lauf auf | `selftest.py` prüft die Syntax aller Werkzeug-Skripte |
| librosa und numba brechen mit dem Projektordner als Arbeitsverzeichnis ab (`getcwd`) | Werkzeuge aus `/tmp` oder `/home/user` starten |
| OpenCV 5 hat keine Haar-Kaskaden und keinen `HOGDescriptor` | YuNet (Gesicht) und YOLOX-S (Person) als ONNX in `tools/modelle/`, `tools/personen.py` für Einzelframes |
| Gesperrte Hosts (je nach Umgebung z. B. Hugging Face, raw.githubusercontent.com, storage.googleapis.com) | Modelle über GitHub-Releases oder `media.githubusercontent.com` (Git LFS), Herkunft in `tools/modelle/*/README.md` |
| Das Nutzungslimit ist schnell erreicht | Sparregeln der Kurzanleitung: kleine Ansichten, Logs nur kurz, lange Läufe im Hintergrund |
| Die automatische Freigabe von Befehlen hängt („no verdict“) | kurz warten und erneut versuchen; hilft das nicht, den Nutzer bitten, die Befehle manuell zu bestätigen |

## 3. Werkzeuge im Überblick

| Werkzeug | Was es tut | Aufruf |
|---|---|---|
| `pipeline/plattform.py` | Profile Instagram und YouTube (Export, Pegel, Grenzen, Safe Zones, Lieferhinweise), Prüfung, Safe-Zone-Bild, Umwandlung einer Instagram-Datei | `plattform.py show youtube`, `check <video> --plattform youtube`, `ui <video> --plattform youtube`, `umwandeln <datei>` |
| `export.py`, `varianten.py`, `interview.py` | `--plattform youtube` (bei `varianten.py --wahl` auch `instagram,youtube` in einem Lauf); Abspann ohne „LINK IN BIO“, Text höchstens 77 % der Breite | `varianten.py <reel> --wahl A --plattform instagram,youtube` |
| `pipeline/drive.py` | Manifest aus der Connector-Ausgabe bauen, Dateien sicher laden, Manifest prüfen (auch online) | `drive.py manifest <json>… -o manifest.tsv`, `holen <id> <ziel>`, `pruefen [--online]` |
| `personen.py`, `modelle/yolox/` | Personenerkennung auf der CPU, ~1 s je Frame | `personen.py <clip> --t 3` |
| `pipeline/reframe.py` | Querformat auf 9:16 mit Tracking (`--modus mitte` und `blur` als Alternativen), Kontaktbogen vorab | `reframe.py <clip> [--analyse]` |
| `pipeline/aktionen.py` | Je Clip: unsaubere Stellen (Schwenk, unscharf, Wackeln, Schnitt), ganze Aktionen, Ruhepunkte, bessere In-Punkte; je Schnittliste: Anlauf und Landung sichtbar, Jump Cut von Ruhe zu Ruhe | `aktionen.py clip <clip> --laenge 1.7 [--bild]`, `aktionen.py edl <edl.json> [--nur 5,8] [--bild]` |

## 4. YouTube Shorts gegenüber Instagram Reels

| Punkt | Instagram | YouTube Shorts |
|---|---|---|
| Länge | laut `stil.json` (Grundstil 30–40 s) | bis 3 min, der Stil bleibt gleich |
| Video | 18/25 Mbit/s, GOP 60, 3 B-Frames, leicht vorgeschärft | 12/16 Mbit/s, GOP 15, 2 B-Frames, nicht vorgeschärft |
| Ton | AAC 320k, Songpegel bleibt, Limiter −0,3 dBTP | AAC 384k, −14 LUFS, True Peak höchstens −1 dBTP |
| Safe Zones | oben 10 %, unten 20 %, rechts 10 %, links 6 % | oben 10 %, unten 21 %, rechts 11,5 %, links 6 % |
| Text mittig | bis 84 % der Breite | bis 77 % der Breite |
| Interview-Abspann | mit „LINK IN BIO“ | ohne (Links in Shorts sind nicht klickbar) |
| Titelbild | eigenes Bild, Motiv im Bereich 1080×1440 | Bild aus dem Video im Bildwähler der App |
| Dateinamen | `<name>_mit_song.mp4` | `<name>_yt_mit_song.mp4` |
| Song | Instagram-Musikbibliothek (stumme Version) | Content ID prüft den Ton: stumme Version hochladen, Sound aus der YouTube-Bibliothek dazulegen |

Alle Zahlen stehen in `PROFILE` in `plattform.py` und lassen sich dort einzeln ändern.

## 5. Grundannahmen (gelten, bis der Nutzer etwas anderes sagt)

1. YouTube Shorts bekommen denselben Stil wie die Reels (Stil-Leitfaden, Interview-Reels Abschnitt 10).
2. Der Abspann für YouTube hat keine Zeile „LINK IN BIO“.
3. Als sichere Lieferung gilt die stumme Version. Die Fassung mit Song wird mitgeliefert, trägt aber das Content-ID-Risiko.
4. 30 fps wie bei den Reels: die Beat-Effekte sind in 30-fps-Frames gerechnet.
5. Keine Titel, Beschreibungen oder Hashtags vorschlagen (Reichweite-Extras), außer der Nutzer fragt.
6. `aktionen.py` gibt nur Hinweise und Vorschläge (bessere In-Punkte und Beat-Längen) und schneidet nichts selbst.
7. Ein Short ist ein Reel mit 1 bis 3 Dialog-Szenen im Hauptteil, hochkant 9:16.

## 6. Was noch fehlt

1. **Erfolg eines Versuchs** (z. B. Klimmzug bis über die Stange): dafür bräuchte es eine Haltungserkennung, die es im Container nicht gibt. Bis dahin: Sichtung und Ausschuss-Tag in der Tags-Datei.
2. **Ein privater Test-Upload eines Shorts** (nur der Nutzer kann das): zeigt, ob YouTube die Datei so verarbeitet wie in `plattform.py` angenommen.
3. **Nicht möglich und daher nicht gebaut:** automatischer Upload (keine Zugangsdaten, und ein Upload wäre nach außen wirksam), Content-ID-Vorprüfung, Querformat 16:9 und Langform, Highlights aus langen Videos finden, B-Roll nach Bildinhalt.

## 7. Grenzen

- **YouTube-Zahlen** (Bitraten, GOP, Safe Zones, 3 Minuten, −14 LUFS) stammen aus Web-Recherche und sind nicht am Original geprüft. Wie YouTube die Dateien verarbeitet und was Content ID tut, ist nicht getestet.
- **`reframe.py`** ist an Testmaterial geprüft; ein echtes Querformat-Video zeigt, ob das Tracking reicht.
- **`aktionen.py`** ist an Trainingsmaterial eines Tages geeicht. Bei anderem Licht, Ort oder anderen Bewegungen können die Schwellen nachjustiert werden müssen (`REGELN` im Kopf der Datei).

## 8. Tests ohne Drive

| Lauf | Dauer |
|---|---|
| `selftest.py` (mit Syntax-Check aller Skripte) | 1–2 min |
| `pipeline/test_pipeline.py` (Ende-zu-Ende mit Foto, Vorschau, Varianten, Einstieg, Jump Cut, Überblendung, O-Ton, Ausklang, `--wahl … --plattform instagram,youtube`) | ~6 min |
| `pipeline/test_drive.py` (lokaler Testserver) | ~2 s |
| `pipeline/test_plattform.py` | ~1,5 min |
| `pipeline/test_interview.py` | ~2 min |
| `pipeline/test_aktionen.py` (künstlicher Clip mit 3 Aktionen, Schwenk, Unschärfe) | ~20 s |
| `pipeline/test_dialog.py`, `test_kuerzen.py`, `test_broll.py`, `test_sync.py`, `test_hybrid.py`, `analyse/test_sprecher.py` | Sekunden bis 2 min |

## 9. `aktionen.py`: bessere Szenenausschnitte

Zweck: helfen, innerhalb eines Videos bessere Ausschnitte auszuwählen. Zwei Wege: beim Sichten (`aktionen.py clip`, statt das „saubere Fenster“ von Hand zu schätzen) und nach `edl.py` (`aktionen.py edl`, statt jeden Shot von Hand zu suchen).

**Methode.** Je Clip eine Zeitreihe mit 10 Werten je s (`clip_analyse.analyse_clip`, nur der gebrauchte Bereich): Bewegung des Motivs ohne Kamerabewegung, Kamerageschwindigkeit, Wackeln, Schärfe, Schnitte im Clip. Schwellen sind relativ zum Clip:
- **Aktion:** Bewegung über der Ruhe-Grenze (10. Perzentil plus 35 % des Weges zum 90. Perzentil), mit Schwellenpaar gegen Flackern. **Höhepunkt:** Stelle mit Bewegung über der Hälfte zwischen Ruhe-Grenze und Spitze.
- **Anlauf fehlt / Landung fehlt:** In- oder Out-Punkt liegt mehr als 0,1 s im Höhepunkt einer Aktion. Ein Anfang im schwachen Anlauf gilt nicht als Fehler. Phasen über 2,5 s und Clips ohne Ruhe (unter 15 %) sind Dauertätigkeit und bleiben ungeprüft, ebenso Clips ohne Hub und Shots mit den Stichwörtern für durchgehende Bewegung (`stil.json` „stichwoerter“).
- **Unsauber:** Schwenk (über 800 px/s), Wackeln (über 250 px/s), unscharf (Schärfe unter 45 % des 80. Perzentils der Umgebung von ±1 s), Schnitt im Clip. Hinweis, wenn mehr als 10 % des Ausschnitts betroffen sind oder die ersten oder letzten 0,3 s.
- **Vorschlag:** In-Punkt und Länge so, dass Anfang und Ende in Ruhe liegen, der bisherige Moment im Bild bleibt, nichts Unsauberes drin ist und der Schnitt nah am bisherigen In-Punkt bleibt (Suche ±3 s). Bei Beat-Szenen probiert es 2 Beats weniger bis 4 mehr und nennt die Beats, mit denen die Aktion ganz passt.
- **Personen:** nur im Epic-Shot und im Finale: vier Stichproben, ob jemand den linken oder rechten Bildrand berührt.

**Erfahrung:** Es findet Schwenks, die im Schnitt landen, und Jump Cuts mitten in eine Aktion, die bei der Sichtung durchrutschen. Meist bekommen 15–30 % der Shots einen Hinweis: es zeigt die Stellen zum Nachsehen, es bewertet keine Fassung.

**Grenzen.**
- **Gescheiterte Versuche** erkennt es nicht: die Bewegungskurven zeigen nur Phasen, gelungen und gescheitert sehen in den Zahlen ähnlich aus. Das bleibt Sichtung und Ausschuss-Tag.
- Kleine Aktionen mit geringer Bewegung gelten als „statisch“: dort keine Anfang-Ende-Prüfung.
- Schwenk-Hinweise treffen auch bewusste, weiche Schwenks.
- Eine Schnittliste zu prüfen lädt die Clips aus dem Drive nach (bei 4K-HEVC bis etwa 2,5 s je Clip-Sekunde, nur der gebrauchte Bereich); das Werkzeug löscht sie danach wieder, Messwerte bleiben klein in `$REEL_WORK/aktionen/`.

Test ohne Drive: `python3 aktionen.py selbsttest` (~20 s).

## 10. Hybrid-Werkzeuge: Dialog, Kürzen, B-Roll, Mehrkamera, Sprecher

Ein Hybrid-Short ist ein Reel nach den Stilregeln mit 1 bis 3 kurzen Dialog-Szenen im Hauptteil; gekürzt wird nur an Pausen (`stark` und `zoegern` sind aus, bis der Nutzer sie will); B-Roll-Vorschläge sind Entwürfe zum Ansehen; die Sprecher-Rolle (wer fragt) entscheidet das Werkzeug nie allein.

| Werkzeug | Was es tut | Grenze |
|---|---|---|
| `pipeline/dialog.py` (+ `d()` in `edl.py`) | Phrase im Transkript suchen, Anfang und Ende in die Stille legen, ganze Beats, Untertitel, Song −16 dB | braucht Transkript und Clip-Ton |
| `pipeline/kuerzen.py` | lange Pausen auf 0,22 s (nach Satzende 0,32 s), Füllwörter samt Stille weg, optional Zögerlaute | Whisper lässt „äh“ oft weg und erfindet mit einem Füllwort-Prompt manchmal eines; Füllwörter ohne Stille drumherum schneidet es deshalb nicht, es meldet sie zum Abhören |
| `pipeline/broll.py` | zu Stichwörtern im Gesagten Action-Clips aus den Tags vorschlagen (Anfang 0,15 s vor dem Stichwort, nicht in den ersten 0,8 s und letzten 0,6 s) | Stichwortvergleich, keine Bilderkennung; ob das Bild zum Satz passt, zeigt nur die Vorschau |
| `bild` in `interview.py` | Bild ersetzt das Video, Stimme und Untertitel laufen weiter; `kamera` nimmt die Zeit aus `sync.json` | nur an Testmaterial geprüft |
| `pipeline/sync.py` | Clips über den Ton auf eine Zeitachse (GCC-PHAT, Drift in ppm, Konfidenz, Mehrdeutigkeit), Abweichung unter 0,5 ms an verfälschten Tonproben | Musik aus einer Box in Schleife ohne Sprache ist mehrdeutig (`brauchbar: false`, wird nie still benutzt) |
| `analyse/sprecher.py` | Sprecherwechsel, Sprecher je Wort, Fragesteller als Hinweis | Antworten unter 0,7 s und Überlappung unsicher, Sprecherzahl eher zu hoch |

**Wo die Werkzeuge ansetzen:** Vor dem Schnitt `sprecher.py` (Fragen und Antworten trennen, `sprecher.md` lesen) und `sync.py` (wenn es zwei Kameras gibt); beim Schnitt `kuerzen` und `bild`, `broll.py` zum Vorschlagen; im Reel `d()` für Dialoge. Alles ist gemessen, nicht gehört: Ergebnisse in der Vorschau prüfen.
