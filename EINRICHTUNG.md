# Einrichtung (einmalig, ca. 20 Minuten)

Diese Vorlage ist ein komplettes KI-Reel-Studio für Claude: Claude sichtet deine Clips aus Google Drive, analysiert den Song, schneidet beatgenau drei Varianten zur Auswahl und liefert das fertige Reel in Instagram-Qualität, auf Wunsch auch als YouTube Short. Dazu kann es Interview-Reels mit Untertiteln schneiden (die Stimme führt) und Shorts mit kurzen Dialogen. Deinen eigenen Stil legt ihr beim ersten Mal gemeinsam fest.

Die Vorlage liegt öffentlich auf GitHub: **https://github.com/Dodekagamer/ki-studio-vorlage**. Du brauchst sie nicht selbst herunterzuladen, Claude holt sie mit dem Start-Prompt unten.

Es gibt zwei Wege. **Weg A** (Claude-Projekt) ist der bequemste und läuft komplett in der Claude-App. **Weg B** (Claude Code mit GitHub) ist für dich, wenn du GitHub nutzt und jede Änderung versioniert haben willst. Die Namen der Menüpunkte können sich je nach App-Version leicht unterscheiden.

## Was du brauchst

- Ein Claude-Abo mit Codeausführung (Code execution) und Netzwerkzugriff.
- Google Drive mit deinen Clips und dem Song (je Reel ein Ordner).
- Für Weg B ein GitHub-Konto.

**Netzwerkzugriff** (in beiden Wegen in der Domain-Liste erlauben, sonst „Alle Domains“):
- `github.com`, `codeload.github.com`: Vorlage laden
- `drive.google.com`, `drive.usercontent.google.com`: Clips und Song
- `pypi.org`, `files.pythonhosted.org` und die Paketquellen des Systems (apt, z. B. `archive.ubuntu.com`, `security.ubuntu.com`): Setup
- nur für Interview-Reels, Sprecher-Trennung und Querformat: `openaipublic.azureedge.net` (Whisper-Modell, 3 GB), `objects.githubusercontent.com`, `release-assets.githubusercontent.com` und `media.githubusercontent.com` (Modelle)

## Weg A: Claude-Projekt

1. **Projekt anlegen:** in Claude unter „Projekte“ ein neues Projekt, z. B. „Reel-Studio“.
2. **Funktionen prüfen** (Einstellungen → Funktionen bzw. Settings → Capabilities): „Codeausführung und Dateierstellung“ an, „Netzwerkzugriff erlauben“ an, Domains wie oben.
3. **Google-Drive-Connector** verbinden (Einstellungen → Connectors).
4. **Projektanweisungen** („Projektanweisungen festlegen“ bzw. Set project instructions) mit diesem Text:
   > Du bist mein Reel-Studio. Projektordner ist /mnt/project-files. Liegen dort noch keine tools/, lade die Vorlage von https://github.com/Dodekagamer/ki-studio-vorlage/archive/refs/heads/main.zip und entpacke sie so, dass README.md, CLAUDE.md und tools/ direkt in /mnt/project-files liegen (nichts Vorhandenes überschreiben). Lies danach immer zuerst /mnt/project-files/CLAUDE.md und arbeite danach.
5. **Erster Chat im Projekt:** den Start-Prompt A unten schicken. Claude lädt die Vorlage, richtet die Werkzeuge ein, prüft sie (Selbsttest) und stellt dir ein paar Fragen zu deinem Stil.

## Weg B: Claude Code mit GitHub

1. Auf GitHub ein **leeres, privates** Repository anlegen, z. B. `mein-reel-studio` (privat, weil dort später dein Stil und deine Schnittlisten liegen).
2. Auf claude.ai/code eine **Umgebung** anlegen: Netzwerkzugriff wie oben, als Setup-Skript den Inhalt von `tools/setup.sh` (auf der GitHub-Seite der Vorlage öffnen und kopieren). Ohne Setup-Skript installiert Claude zu Beginn jeder Session selbst (ca. 70 s).
3. Google-Drive-Connector verbinden und der Claude-GitHub-App Zugriff auf das neue Repository geben.
4. Neue Session mit dem Repository und der Umgebung starten und den Start-Prompt B unten schicken.
5. Videos kommen nicht ins Repository (`.gitignore`) und liegen nur im Container der Session: Fertige Reels also gleich herunterladen.

## Start-Prompts (zum Kopieren)

**Start-Prompt A (Claude-Projekt):**
```
Richte mein KI-Reel-Studio ein: Lade die Vorlage von https://github.com/Dodekagamer/ki-studio-vorlage/archive/refs/heads/main.zip, entpacke sie so, dass README.md, CLAUDE.md und tools/ direkt in /mnt/project-files liegen, und lies dann CLAUDE.md. Installiere die Werkzeuge mit bash tools/setup.sh, führe den Selbsttest aus (python3 tools/selftest.py) und sag mir kurz, ob alles grün ist. Danach lass uns meinen Stil festlegen (Stil-Leitfaden, Abschnitt „Stil festlegen“): stell mir die Fragen in einer Nachricht.
```

**Start-Prompt B (Claude Code mit eigenem Repository):**
```
Richte in diesem Repository mein KI-Reel-Studio ein: Klone https://github.com/Dodekagamer/ki-studio-vorlage mit --depth 1 in einen temporären Ordner und kopiere den ganzen Inhalt ohne .git in dieses Repository (README.md, CLAUDE.md und tools/ direkt im Hauptverzeichnis). Committe und pushe das als „KI-Reel-Studio aus der Vorlage“. Lies danach CLAUDE.md, installiere die Werkzeuge mit bash tools/setup.sh, führe den Selbsttest aus (python3 tools/selftest.py) und sag mir kurz, ob alles grün ist. Danach lass uns meinen Stil festlegen (Stil-Leitfaden, Abschnitt „Stil festlegen“): stell mir die Fragen in einer Nachricht.
```

Updates der Vorlage später übernehmen: „Hol die neueste Fassung von github.com/Dodekagamer/ki-studio-vorlage und übernimm die Werkzeuge (tools/, reels/_vorlage/, referenz/studio/). Mein Stil (stil.json, Stil-Leitfaden.md) und meine Reels bleiben unverändert; neue Regeln aus Kurzanleitung und Stil-Leitfaden zeig mir vorher.“

## Stil festlegen (erster Chat)

Claude fragt in einer Nachricht nach (alles optional):

- Account/Marke, wie Claude dich nennen soll, worum es in deinen Reels geht und für wen.
- 1–3 Reels, die dir gefallen (eigene oder fremde), **als Videodatei in einem Drive-Ordner** (Instagram-Links kann Claude nicht öffnen). Claude vermisst sie (Schnitttempo, Jump Cuts, Übergänge, Effekte, Ton, Lautheit) und leitet daraus deine Werte ab.
- Länge, Einstieg (mit echtem Moment und Originalton oder sofort mit dem Song), Musik, Look (natürlich, kräftig, dunkel, Film, Schwarzweiß oder dein eigenes Preset als `.cube`), Text im Video ja/nein, Interviews geplant?, Logo, Schrift, No-Gos.

Das Ergebnis landet in `Stil-Leitfaden.md` (für Menschen lesbar) und `stil.json` (für die Werkzeuge). Nach jedem Reel kannst du Feedback geben, Claude übernimmt es als Regel in den Leitfaden. Ohne Einrichtung schneidet Claude im Grundstil (30–40 s, ganze Aktionen, Einstieg im Video, Szenen mit Jump Cuts).

## Pro Reel

1. In Google Drive einen Ordner mit Clips und Song anlegen. Freigabe: **„Jeder mit dem Link – Betrachter“** (nicht „Bearbeiter“), sonst kann Claude nicht laden.
2. Im Projekt bzw. in der Session schreiben (nur der Ordner ist Pflicht):
   ```
   Neues Reel
   Ordner: <Drive-Link>
   Song: <Dateiname – oder leer lassen, wenn nur einer im Ordner liegt>
   Part: <Hook / Drop / Strophe – oder leer = Claude entscheidet>
   Länge: <z. B. 30–35 s – oder leer>
   Anlass/Fokus: <optional>
   Text im Video: <nein / ja: „…“>
   Muss rein / muss raus: <optional>
   Auch als YouTube Short: <ja / nein>
   ```
   Für ein Interview-Reel „Neues Interview-Reel“ schreiben und Event, Zeit und Ort für den Abspann dazu.
3. Du bekommst drei Varianten (Vorschau-Video mit Song, Shot-Nummern und Loop, dazu Storyboard). Du wählst eine, gern mit Änderungen per Shot-Nummer („#7 raus, #12 länger“). Interview-Reels kommen als eine Vorschau.
4. Danach kommen die fertigen Dateien: `…_mit_song.mp4`, `…_ohne_ton.mp4` (für die Instagram-Musikbibliothek) und ein Titelbild, für YouTube zusätzlich `…_yt_…`.
5. Freigabe des Drive-Ordners danach wieder auf „Eingeschränkt“.

## Instagram-App (einmalig)

Einstellungen und Privatsphäre → „Datennutzung und Medienqualität“ → **„In höchster Qualität hochladen“ an** (ist standardmäßig aus), „Weniger mobile Daten verwenden“ aus. Dateien unverändert aufs Handy bringen (Download, Drive oder AirDrop, **nicht WhatsApp**), in Instagram keine Filter und kein Zuschneiden.

## Wenn etwas hakt

- „Kein Zugriff“ beim Download: Ordnerfreigabe prüfen (Punkt 1 bei „Pro Reel“) und ob die Drive-Domains erlaubt sind.
- Vorlage lädt nicht: `github.com` und `codeload.github.com` in der Domain-Liste erlauben, oder die ZIP von der GitHub-Seite („Code“ → „Download ZIP“) selbst in den Chat hängen.
- Werkzeuge fehlen oder Selbsttest rot: Claude soll `bash tools/setup.sh` ausführen; dafür braucht es Netzwerkzugriff auf die Paketquellen.
- Fertiges Video zu groß zum Herunterladen aus dem Chat: Claude bitten, eine kleinere Kopie zum Herunterladen zu machen, oder das Video im Claude-Projekt rendern lassen.
- Das Nutzungslimit ist schnell erreicht: Claude arbeitet nach `Kurzanleitung.md` sparsam. Lange Chats lieber pro Reel neu beginnen.
- Typische Fehler und ihre Lösungen: `referenz/studio/fehlerquellen.md`.
