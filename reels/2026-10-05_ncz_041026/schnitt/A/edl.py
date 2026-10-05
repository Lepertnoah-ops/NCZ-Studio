#!/usr/bin/env python3
"""Schnittliste einer Variante -> edl.json, fx.json, audio_spec.json im selben Ordner.

    cd <reel>/schnitt/A && python3 edl.py        # genauso B und C (neues_reel.py legt alle drei an)

Der Nutzer bekommt 3 deutlich verschiedene Varianten zur Auswahl (Songabschnitt, Auswahl/Story, Tempo/Effekt-Dichte;
jedes Paar in mindestens 2 Punkten anders, alle im Stil-Leitfaden). Bauen und vergleichen:
tools/pipeline/varianten.py <reel> (--check nur Unterschied-Check).
Vorher grid.json anlegen (song_analyse.py, gemeinsam in schnitt/ oder hier): {"per": …, "ph": …, "erste_eins": …}.
Regeln: Stil-Leitfaden.md und stil.json (Einstieg im Video, Szenen mit Jump Cuts, volle 4-Takt-Phrasen, Länge laut
stil.json; 4 Kapitel auf Phrasengrenzen; ganze Aktionen in Echtzeit; Akzent-Karte, Effekt-Budget; O-Ton, Überblendung nur ruhig).
Die Prüfung tools/pipeline/edlcheck.py (für alle Reels gemeinsam) meldet Verstöße gegen den Leitfaden; abgebrochen wird
nur bei harten Fehlern (Beat-Summe, Clip in mehreren Szenen). Die Tonspur plant tools/pipeline/tonspur.py.

Szene = eine Übung, Station oder ein Ort (Regel 4), meist 2 Takte, gezeigt in 1–3 Teilen:
  s(beats, kapitel, clip, src, mode, tags, beschreibung, fx=dict(...), prev=Vorschauzeit, **extra)   neue Szene
  j(beats, clip, src, mode, tags, beschreibung, fx=dict(...), **extra)   Jump Cut: nächster Teil derselben Szene
        (gleiches Kapitel): derselbe Clip später (ganze Wiederholung, Zeitsprung mindestens 1 s), anderer Winkel
        derselben Aktion oder nächste Person vor derselben Kamera. Ein Clip darf nur in einer Szene vorkommen.
  clip  Kürzel aus dem Dateinamen, z. B. "6132" für IMG_6132.MOV
  src   Sekunde im Clip, an der der Shot beginnt (Echtzeit-Shot: Endposition der Wiederholung vor dem Schnitt!)
  mode  normal | speed (+ speed=0.75 oder 0.5) | ramp_hold (nur nach Regel 8; explosiv=True, wenn die Beschreibung
        keinen explosiven Sprung nennt, Stichwörter in stil.json) | freeze (+ freeze_at=Beats) | split (+ strips=[…]);
        fast und ramp sind Zeitraffer, nicht verwenden
  tags  Effekt-Tags fürs Storyboard; fx = Parameter für tools/pipeline/render.py (Liste dort im Kopf)
  extra oton="leise" (Originalton leise unter dem Song) | "vorn" (im Einstieg, im Ausklang oder als O-Ton-Moment:
        Song tritt zurück; höchstens 2 Momente, am besten im Break); O-Ton nur mit gutem Ton (tools/analyse/oton.py)
        ueber="blende" Überblendung 0,4 s in diesen Shot, nur an ruhigen Stellen ohne 808 (Regel 5)
Hybrid (z. B. YouTube Shorts): kurzer Dialog im Reel, bis zu 3, im Hauptteil, nie im Einstieg oder Ausklang:
  d(kapitel, clip, "erstes Wort(e)", "letztes Wort(e)", beschreibung, ab=0.0, jump=False)   Szene mit Sprache, Stimme vorn
        (tools/pipeline/dialog.py: Beats, Schnittpunkte in der Stille, Untertitel; braucht TRANSKRIPT, Whisper-Transkript des
        Clips aus analyse/transkript.py, und den Clip-Ton in $REEL_WORK/audio/). Gibt die Beats aus: Summe danach prüfen.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJEKT = next(p for p in HERE.parents if (p / "tools" / "stil.py").exists())
sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
sys.path.insert(0, str(PROJEKT / "tools"))
from stil import STIL  # noqa: E402

g = json.load(open(HERE / "grid.json" if (HERE / "grid.json").exists() else HERE.parent / "grid.json"))
per, ph = g["per"], g["ph"]
# Beat-Nummer von Takt 0 (song.md, erste_eins) im Raster; ph ist nur der erste Beat, nicht die erste Eins
eins = 0 if g.get("erste_eins") is None else round((g["erste_eins"] - ph) / per)
# tools/pipeline (Prüfung, Tonspur) im ersten Elternordner, der es hat
P = next((p / "tools" / "pipeline" for p in HERE.parents if (p / "tools" / "pipeline" / "edlcheck.py").is_file()), None)

S, SZENE = [], [0]
TRANSKRIPT = None    # für d(): in den Reel-Einstellungen unten setzen


def shot(beats, sec, clip, src, mode, tags, desc, fx, prev, **kw):
    tags = list(tags) + (["Blende"] if kw.get("ueber") == "blende" else []) + \
        (["Dialog"] if kw.get("dialog") else [{"leise": "O-Ton", "vorn": "O-Ton vorn"}.get(kw["oton"], "O-Ton")] if kw.get("oton") else [])
    S.append(dict(beats=beats, sec=sec, clip=clip, src=src, mode=mode, fx=tags, fxp=fx or {}, desc=desc,
                  prev=prev if prev is not None else src, szene=SZENE[0], **kw))


def s(beats, sec, clip, src, mode, tags, desc, fx=None, prev=None, **kw):
    SZENE[0] += 1
    shot(beats, sec, clip, src, mode, tags, desc, fx, prev, **kw)


def j(beats, clip, src, mode, tags, desc, fx=None, prev=None, **kw):
    shot(beats, S[-1]["sec"], clip, src, mode, ["Jump Cut"] + list(tags), desc, fx, prev, jump=True, **kw)


def d(sec, clip, von, bis, desc, ab=0.0, jump=False, fx=None, **kw):
    """Dialog: eine gesprochene Phrase als Szene (Stimme vorn, Untertitel), Beats aus dem Transkript (dialog.py)."""
    if P is None or not TRANSKRIPT:
        sys.exit("d(): TRANSKRIPT (Ordner mit <clip>.json aus analyse/transkript.py) und tools/pipeline werden gebraucht")
    sys.path.insert(0, str(P))
    import dialog
    r = dialog.phrase(TRANSKRIPT, clip, von, bis, per, ab)
    print(f"Dialog {clip} „{von} … {bis}“: src {r['src']:.3f} s, {r['beats']} Beats ({r['dauer']:.2f} s)")
    for m in r["warn"]:
        print("   Achtung:", m)
    kw.update(oton="vorn", dialog=True)
    (j if jump else s)(r["beats"], *([clip, r["src"], "normal", [], desc] if jump else [sec, clip, r["src"], "normal", [], desc]),
                       fx=fx, **kw)


# ---- pro Reel anpassen -------------------------------------------------------------------------------
TITEL = "ncz_041026"
VARIANTE, VARIANTE_NAME = "A", "Story"
UNTERSCHIED = "Einstieg mit Banner und echtem Ton, Drop auf der Strophe (T29), Training -> Boxen/Handstand -> Erschöpfung -> Gruppenfoto"
UNTERTITEL = "Variante " + VARIANTE + " · " + VARIANTE_NAME
SONG = "EUROTHUG x OG KEEMO – BUCKS"
SONG_DATEI = "/home/user/reel/song.mp3"
START_TAKT = 29
AUFTAKT = 4
TAKTE = 24
EINSTIEG = 4
EINSTIEG_SONG = "gedämpft"
EINSTIEG_AUF = 0.03
AUSKLANG = 0
DECODER_VERSATZ = 0.0
HITS = [6, 7, 9, 20, 22, 27, 31, 32, 38, 40, 43, 45, 48, 54, 56, 59, 62, 63, 64, 66, 73, 75, 76, 78, 80, 81, 83, 89, 96, 97]
P808, P808_NACH, MINI = STIL["punch"]["808"], STIL["punch"]["nachschlag"], STIL["punch"]["clap"]

K1, K2, K3, K4 = STIL["kapitel"][:4]
# Kapitel 1: Einstieg im Video in der ruhigen Pause (T28) + Drop auf T29
s(4, K1, "20261004_124259", 1.2, "speed", ["Zeitlupe"], "Einstieg: Gruppe sammelt sich im Park, Zurufe",
  dict(push=[1.0, 1.04]), speed=0.75, oton="vorn")
s(8, K1, "6645", 1.0, "speed", ["Zeitlupe", "Push-in", "Punch-in"], "Drop: Handstand-Duo hält, Zuschauer dahinter",
  dict(push=[1.0, 1.08], punch=[[0, P808]]), speed=0.5)
s(8, K1, "20261004_130520", 2.7, "normal", [], "Training beginnt, Banner nocomfort.zone", {})
# Kapitel 2: Aufwärmen und Gruppenübungen
s(8, K2, "20261004_124710", 3.6, "normal", ["Punch-in"], "Aufwärmen: Arme hoch, ganze Gruppe", dict(punch=[[0, P808]]))
s(4, K2, "20261004_130551", 3.2, "normal", [], "Liegestütz Gruppe, Banner hinten", {})
j(4, "6631", 7.5, "normal", ["Mini-Punch"], "Liegestütz, andere Gruppe mit Griffen", dict(punch=[[0, MINI]]))
s(4, K2, "6689", 6.0, "normal", [], "Klimmzug nah", {})
j(6, "02235CDC-6CE8-4BF3-9741-EA778A00274A", 12.3, "normal", ["Mini-Punch"], "Klimmzug, nächster Athlet", dict(punch=[[0, MINI]]))
s(6, K2, "6629", 6.6, "normal", ["Punch-in"], "Dips am Barren", dict(punch=[[0, P808]]))
# Kapitel 3: Stationen
s(4, K3, "6623", 5.4, "normal", ["Shake"], "Pratzen: Schlagserie", dict(shake=[[0, 14, .5]]))
j(4, "6682", 3.1, "normal", [], "Pratzen, nächstes Paar", dict(punch=[[0, MINI]]))
s(8, K3, "FF7D463A-8931-4001-9FC1-74640920CA80", 5.0, "normal", ["Punch-in"], "Handstand-Duo auf Parallettes", dict(punch=[[2, P808]]))
s(4, K3, "6626", 2.0, "normal", ["Punch-in"], "Battle Ropes vor dem Banner", dict(punch=[[0, P808]]))
j(4, "6617", 5.0, "normal", [], "Battle Ropes, nächstes Paar")
s(8, K3, "6620", 21.0, "normal", ["Punch-in"], "Muscle-up an der Stange vor dem Banner", dict(punch=[[0, P808]]))
# Kapitel 4: Erschöpfung, Essen, Gruppenfoto
s(4, K4, "6606", 0.2, "normal", [], "erschöpft am Boden vor dem Banner", {})
s(4, K4, "6735", 1.0, "normal", [], "Essen: genießen", {})
s(8, K4, "6612", 8.0, "speed", ["Zeitlupe", "Push-in"], "Finale: Gruppenfoto aller Teilnehmer",
  dict(push=[1.0, 1.12], punch=[[4, P808]]), speed=0.5)
# -------------------------------------------------------------------------------------------------------

BEATS = AUFTAKT + TAKTE * 4 + AUSKLANG
b = 0
for i, x in enumerate(S):
    x["n"], x["beat"], x["t"] = i + 1, b, b * per
    b += x["beats"]
assert b == BEATS, f"Summe {b} Beats, erwartet {BEATS} (Auftakt {AUFTAKT} + {TAKTE} Takte + Ausklang {AUSKLANG})"
szenen = {}
for x in S:
    for c in ([st["clip"] for st in x["strips"]] if x["clip"] == "split" else [] if x.get("cont") else [x["clip"]]):
        szenen.setdefault(c, set()).add(x["szene"])
dup = sorted(c for c, z in szenen.items() if len(z) > 1)
assert not dup, f"Clip in mehreren Szenen: {dup} (mehrfach nur per Jump Cut j() in derselben Szene)"

start = ph + (eins + 4 * START_TAKT - AUFTAKT) * per   # Reel-Start = erste_eins + (4 × START_TAKT - AUFTAKT) Beats
E = dict(titel=TITEL, untertitel=UNTERTITEL, song=SONG, per=per, hook=start, beats=BEATS, hits=HITS, shots=S,
         variante=VARIANTE, variante_name=VARIANTE_NAME, hinweis=UNTERSCHIED, auftakt=AUFTAKT, takte=TAKTE,
         einstieg=EINSTIEG, einstieg_song=EINSTIEG_SONG, ausklang=AUSKLANG, transkript=TRANSKRIPT)
json.dump(E, open(HERE / "edl.json", "w"), indent=1, ensure_ascii=False)
json.dump({str(x["n"]): x["fxp"] for x in S}, open(HERE / "fx.json", "w"), indent=1)
if P is None:
    sys.exit("tools/pipeline nicht gefunden: audio_spec.json und Stil-Leitfaden-Prüfung fehlen")
sys.dont_write_bytecode = True
sys.path.insert(0, str(P))
import edlcheck
import tonspur

json.dump(tonspur.audio_spec(E, SONG_DATEI, start - DECODER_VERSATZ, EINSTIEG_AUF), open(HERE / "audio_spec.json", "w"),
          indent=1)
print(f"{len(S)} Shots in {SZENE[0]} Szenen, {len(szenen)} Clips, {BEATS} Beats = {BEATS * per:.3f} s, "
      f"Song ab {start:.3f} s")
print(edlcheck.bericht(E, TAKTE, AUFTAKT, HERE, DECODER_VERSATZ))
