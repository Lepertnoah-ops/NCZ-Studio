# Schriften für Titel und Text-Effekte

Liegen im Projektordner, damit jeder Thread sie ohne Setup-Skript hat.

| Datei | Wirkung | Einsatz |
|---|---|---|
| `BebasNeue-Bold.otf`, `BebasNeue-Regular.otf` | schmal, hoch, sehr Sport | kurze Titel, Kinetic Type |
| `LeagueSpartan-SemiBold/Bold/ExtraBold/Black.otf` | breit, geometrisch, am nächsten an Poppins | Titel, Branding |
| `Oswald-Medium/SemiBold/Bold.ttf` | schmal, kräftig, klassischer Sport-Look | Titel, Branding |
| `Antonio-Bold.ttf` | sehr schmal und fett, gut lesbar in Großbuchstaben | Untertitel und Abspann der Interview-Reels (Grundstil, `untertitel.py`) |
| `CourierPrime-Bold.ttf` | Schreibmaschinenschrift | Untertitelzeile im Abspann, mit Laufweite |

Montserrat (Standard) und Inter kommen aus dem Setup-Skript unter `/usr/share/fonts/truetype/`.

**Nutzung:** In einer `fx.json` bei `title`, `kinetic` oder `typewriter` als `weight` den Dateinamen ohne Endung angeben, zum Beispiel `"weight": "BebasNeue-Bold"`. Ohne Treffer hier nimmt `vfx/reelvfx.py` Montserrat im genannten Schnitt (`"ExtraBold"`).

**Eigene Markenschrift:** Die Datei (.otf oder .ttf) einfach hier ablegen, dann geht sie genauso über `weight`.

Lizenz: alle SIL Open Font License 1.1, frei auch für kommerzielle Videos. Bebas Neue und League Spartan aus dem Ubuntu-Archiv (`fonts-bebas-neue`, `fonts-league-spartan`), Oswald und Antonio aus github.com/google/fonts (statische Schnitte aus der variablen Schrift erzeugt, Lizenzen in `OFL-Oswald.txt` und `OFL-Antonio.txt`), Courier Prime ebenfalls von dort (`OFL-CourierPrime.txt`). Poppins selbst ist in dieser Umgebung nicht erreichbar.
