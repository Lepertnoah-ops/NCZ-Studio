#!/usr/bin/env python3
"""Schnittliste Interview-Reel „{NAME}“ ({DATUM}): Interview-Highlights mit Untertiteln, Song leise darunter.

    cd <reel>/schnitt && python3 schnitt.py      # schreibt schnitt.json
    cd /home/user && python3 <projekt>/tools/pipeline/interview.py <reel>/schnitt/schnitt.json [--enden | --export]

Der Stil steht in der Kurzanleitung („Interview-Reels“) und im Stil-Leitfaden (Abschnitt 10). Angepasst werden nur CLIPS,
TEILE, der Song (DROP_TAKT, DROP_TEIL) und die Texte des Abspanns. Alle Felder: Kopf von tools/pipeline/interview.py.

Teile: von/bis als Phrase aus dem Transkript (erstes bzw. letztes Wort, geschnitten wird in der Stille davor bzw.
danach) oder als Quellzeit in s. ab = Phrase erst ab dieser Quellzeit suchen. zoom 1 = ganzes Bild (4K-Quelle, bis ~1,6
ohne Verlust), Gesicht automatisch in die Mitte, fokus = [x, y] von Hand. stil="frage": Frage hinter der Kamera, steht als
Text oben und blendet kopf_nach s nach dem Ende der Frage aus. text = Untertitel dieses Teils ersetzen („_“ blendet ein
Wort aus). plus = Sekunden nach dem Schnitt dranhängen. anfang/ende = Schnittzeit von Hand in s Quellzeit (Untertitel
bleiben bei der Phrase): nötig, wenn `interview.py --enden` ein angeschnittenes Wort zeigt oder eine Warnung „Ende ohne
Pause“ bleibt. Feedback per Nummer: #N in Vorschau und Storyboard = N-ter Eintrag in TEILE.
"""
import json
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
PROJEKT = next(p for p in HIER.parents if (p / "tools" / "stil.py").exists())
sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
sys.path.insert(0, str(PROJEKT / "tools"))
from stil import STIL  # noqa: E402

MARKE = (STIL["marke"] or "MEINE MARKE").lstrip("@").upper()   # erste Zeile im Abspann
W = "/home/user/reel"
CLIPS = {c: f"{W}/dl/{c}.MOV" for c in ("IMG_0001", "IMG_0002")}  # ANPASSEN: Kürzel = Dateiname in $W/dl/


def t(clip, von, bis=None, **kw):
    return dict(clip=clip, von=von, bis=bis if bis is not None else von, **kw)


def abspann_event(event=None, untertitel=None, zeit=None, ort=None, link=True):
    """Abspann (Grundstil): Marke, Event, Untertitel, Linie, Zeit, Ort (bis 3 Zeilen), LINK IN BIO, alles weiß in
    schmaler Schrift; die Zeilen blenden nacheinander ein. Nur Angaben einsetzen, die der Nutzer genannt hat (fehlt
    etwas, None lassen statt raten)."""
    z = [dict(text=MARKE, breite=640, start=0.55)]
    if event:
        z.append(dict(text=event, breite=960, abstand=66, start=0.90))
    if untertitel:
        z.append(dict(text=untertitel, art="mono", cap=34, spur=0.13, abstand=38, start=1.15))
    if (event or untertitel) and (zeit or ort):
        z.append(dict(linie=110, abstand=74, start=1.35))
    if zeit:
        z.append(dict(text=zeit, cap=76, abstand=74, start=1.55))
    for k, zeile in enumerate(ort or ()):
        z.append(dict(text=zeile, cap=64, abstand=52 if k == 0 else 34, start=round(1.85 + 0.15 * k, 2)))
    if link:
        z.append(dict(text="LINK IN BIO", cap=42, spur=0.18, abstand=92, start=2.55))
    return dict(mitte=0.44, mindestens=4.8, blende=0.6, zeilen=z)


# Song: Intro (ohne 808) unter Kapitel 1, der erste 808 (Takt DROP_TAKT laut song.md) genau auf Teil DROP_TEIL
# (Kapitelwechsel), Ende auf einer Eins nach dem Abspann.
DROP_TAKT, DROP_TEIL = 10, 5  # ANPASSEN

TEILE = [
    # Kapitel 1: <Thema> (Song-Intro ohne 808)
    t("IMG_0001", "erstes Wort der Aussage", "letztes Wort der Aussage", notiz="Einstieg"),
    t("IMG_0002", "erstes Wort der Frage", "letztes Wort der Frage", stil="frage"),  # Frage hinter der Kamera
    t("IMG_0002", 12.30, "letztes Wort der Antwort", zoom=1.25),  # Antwort direkt nach der Frage, Punch-in
    # Kapitel 2: <Thema> (hier setzt der 808 ein, DROP_TEIL)
    t("IMG_0001", "erstes Wort", "letztes Wort", ende=20.00),  # ende = Schnitt von Hand, wenn ein Wortende angeschnitten wird
    # Kapitel 3 und 4: <Thema>, zuletzt die Einladung
    t("IMG_0002", "erstes Wort", "letztes Wort", plus=1.0, notiz="Winken, geht"),
]

SCHNITT = dict(
    name="{NAME}",
    clips=CLIPS,
    transkript=str(HIER / "transkript"),
    song=dict(datei=f"{W}/song.mp3", grid=str(HIER / "grid.json"), drop_takt=DROP_TAKT, drop_teil=DROP_TEIL,
              ende_auf_phrase=True, unter_sprache=13, in_pausen=6, fade_ende=2.0),
    abspann=abspann_event(event=None, untertitel=None, zeit=None, ort=None),  # ANPASSEN: Event, Untertitel, Zeit, Ort (Zeilen)
    untertitel_zeile=f"Untertitel weiß ohne Rand (Antonio Bold, weicher Schein) · Ende: {MARKE} mit Zeit, Ort, Link in Bio",
    kopf_nach=1.0,  # Fragetext nicht lange stehen lassen: 1,0 s nach der Frage ausblenden (Ausblendung 0,45 s)
    # titelbild=0.5,  # Sekunde im Reel für das Titelbild (Bild ohne Untertitel): Augen offen, Blick in die Kamera, Gesicht im
    #                 mittleren 1080×1440-Bereich. Ansehen und ggf. neu ziehen: interview.py schnitt.json --titelbild <s>
    ersetzen={},  # Whisper-Fehler fürs ganze Reel: {"falsch": "richtig"}; nur mit Beleg (Transkript, zweiter Lauf)
    teile=TEILE,
)

if __name__ == "__main__":
    (HIER / "schnitt.json").write_text(json.dumps(SCHNITT, ensure_ascii=False, indent=1))
    print(f"schnitt.json: {len(TEILE)} Teile")
