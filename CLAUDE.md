# KI-Reel-Studio

Instagram-Reels und YouTube Shorts für den Nutzer, der in `stil.json` steht (`nutzer`, `marke`, `inhalt`). Antworten auf Deutsch, kurz und handyfreundlich.

## Projektordner

- **Claude-Projekt** (`/mnt/project-files/tools` existiert): Dort wird gearbeitet, Werkzeuge immer von dort starten. Liegt eine Repository-Kopie daneben, ist sie nur eine Sicherung (`README.md`, „Sicherung“).
- **Eigene Session** (claude.ai/code, ohne `/mnt/project-files`): Dieser Ordner ist der Projektordner, `P=$(git rev-parse --show-toplevel)`.

## Vor jedem Reel

1. `Kurzanleitung.md` lesen und abarbeiten.
2. `python3 tools/stil.py`: meldet es „NOCH NICHT EINGERICHTET“, zuerst mit dem Nutzer `Stil-Leitfaden.md`, Abschnitt „Stil festlegen“ (eine Nachricht mit Fragen, alles optional). Will er sofort ein Reel, im Grundstil schneiden und das sagen.
3. Bei jedem Reel 3 deutlich verschiedene Varianten, zu jeder Vorschau-Video und Storyboard mit einem Satz, worin sie sich unterscheidet. Vor dem Vorlegen jede Szene mit `tools/ansicht.py szenen` (4 Bilder je Shot) prüfen: ganze Aktion, kein Schwenk, gelungener Versuch. Einziger Pflicht-Stopp: der Nutzer wählt eine, gern mit Feedback per Shot-Nummer. Erst danach Export, Prüfung und Lieferung. Interview-Reels: eine Vorschau, Export nach dem OK (Kurzanleitung, „Interview-Reels“).
4. Vorrang: neuestes Feedback des Nutzers, dann `Stil-Leitfaden.md` und `stil.json`, dann `Reel-Studio_Projektanweisungen.md`. Feedback, das dauerhaft gelten soll, im selben Zug in Leitfaden und `stil.json` eintragen.

## Dateien an den Nutzer

- Im Claude-Projekt: Vorschauen, Storyboards und fertige Videos als Anhang schicken.
- In einer eigenen Session: per Datei-Versand schicken, wenn es ihn gibt (Größengrenze beachten, sonst eine kleinere HEVC-Kopie zum Herunterladen anbieten), sonst im Reel-Ordner lassen und die Pfade nennen, der Nutzer öffnet sie in der App. Videos kommen nicht ins Repository und sind weg, sobald der Container gelöscht wird. Schnittlisten, Skripte und Steckbrief des Reels committen und pushen.
- Drive-Ordner listen wie in der Kurzanleitung; fehlt der Drive-Connector, den Nutzer bitten, ihn zu verbinden (`EINRICHTUNG.md`).
