#!/usr/bin/env python3
"""Kurze Dialoge im Reel (Hybrid aus Action und Interview, seit 30.09.2026): eine gesprochene Phrase als Szene mit O-Ton
vorn, Song leiser und Untertiteln, eingeschnitten in ein Reel auf dem Beat-Raster.

In schnitt/X/edl.py (Vorlage `reels/_vorlage/schnitt/edl.py`):

    TRANSKRIPT = "/home/user/reel/transkript"       # Ordner mit <clip>.json aus analyse/transkript.py
    d(K2, "5315", "Jungs ihr seid das", "dritte Mal da", "Frage an die Gäste")           # 1 Phrase, Beats ergeben sich
    d(K2, "5315", "Sehr anstrengend", "alles abgedeckt", "Antwort", ab=14.0)             # ab = Quellzeit, ab der gesucht wird

`d()` sucht die Phrase (erstes Wort „von“ bis letztes Wort „bis“, Groß-/Kleinschreibung und Satzzeichen egal) im Transkript
des Clips und legt Anfang und Ende in die Stille davor und danach (Pegel des Clip-Tons, nicht die Wortzeiten von Whisper,
die oft 0,2–0,55 s zu früh enden). Daraus werden ganze Beats: aufgerundet, wenn danach noch Stille folgt (oder die nächste
Phrase erst später beginnt), sonst abgerundet; beginnt das nächste Wort noch im letzten Beat, meldet `d()` es und die Szene
wird einen Beat länger. `d()` gibt die Beats aus, die Summe der Schnittliste muss danach wieder stimmen.
Die Szene läuft in Echtzeit (nie Zeitlupe, sonst klingt der Ton falsch). Die Tonspur (tonspur.py) senkt den Song in der
Szene um 16 dB und filtert ihn, die Stimme liegt 4 LU unter dem ungesenkten Song; render.py brennt die Untertitel (Schrift
und Stil wie bei Interview-Reels, vfx/untertitel.py) über die Dialog-Szenen ein. Die Prüfung edlcheck.py zählt Dialoge nicht
als O-Ton-Momente, meldet aber: mehr als 3 Dialoge, Zeitlupe, angeschnittene Wörter am Anfang oder Ende.
Test ohne Drive: test_dialog.py.
"""
import json
import math
import os
import re
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True      # kein __pycache__ im geteilten Projektordner
PIPE = Path(__file__).resolve().parent
TOOLS = PIPE.parent
for _p in (PIPE, TOOLS, TOOLS / "vfx"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

WORK = Path(os.environ.get("REEL_WORK", "/home/user/reel"))
HZ = 200
REGELN = dict(
    vorlauf=0.12,               # s Stille (oder Luft) vor dem ersten Wort
    luft=0.12,                  # s Stille nach dem letzten Wort (höchstens, sonst die halbe Pause)
    max_dialoge=3,              # mehr als so viele Dialoge im Reel: Hinweis
    pegel_song=-16.0,           # dB Song in der Dialog-Szene (tonspur.py)
    pegel_stimme=-4.0,          # LU der Stimme relativ zum ungesenkten Song (tonspur.py)
    text_breite=0.77,           # Anteil der Bildbreite für eine Untertitelzeile (passt für Instagram und YouTube Shorts)
)


def norm(w):
    return re.sub(r"[^\wÄÖÜäöüß]", "", w.lower())


def transkript_laden(ordner, clip):
    ordner = Path(ordner)
    for n in (f"{clip}.json", f"IMG_{clip}.json"):
        if (ordner / n).exists():
            return json.loads((ordner / n).read_text())
    treffer = sorted(ordner.glob(f"*{clip}*.json"))
    if len(treffer) == 1:
        return json.loads(treffer[0].read_text())
    raise FileNotFoundError(f"Transkript zu Clip {clip!r} fehlt in {ordner} (analyse/transkript.py)")


def woerter_des_clips(tr):
    return [w for sg in tr["segmente"] for w in sg["woerter"]]


def finde(ws, phrase, ab=0.0):
    toks = [norm(x) for x in phrase.split() if norm(x)]
    wn = [norm(w["w"]) for w in ws]
    for i in range(len(ws) - len(toks) + 1):
        if ws[i]["s"] >= ab - 0.01 and wn[i:i + len(toks)] == toks:
            return i, i + len(toks) - 1
    raise ValueError(f"Phrase nicht im Transkript gefunden: „{phrase}“ (ab {ab} s)")


_ENV = {}


def huelle(clip):
    """Pegelkurve des Clip-Tons in dB (HZ Werte je s) aus $REEL_WORK/audio/<clip>.flac; None, wenn der Ton fehlt."""
    if clip not in _ENV:
        import kuerzen
        ton = WORK / "audio" / f"{clip}.flac"
        _ENV[clip] = kuerzen.huelle(kuerzen.lesen16(ton)) if ton.exists() else None
    return _ENV[clip]


def phrase(tr_ordner, clip, von, bis, per, ab=0.0, R=None, env=None, tr=None):
    """Quellzeit und Beats für eine gesprochene Phrase. Gibt dict: src, beats, dauer, s, e, worte, warn."""
    R = R or REGELN
    if not tr_ordner and tr is None:
        raise ValueError("TRANSKRIPT fehlt (Ordner mit <clip>.json aus analyse/transkript.py)")
    tr = tr or transkript_laden(tr_ordner, clip)
    ws = woerter_des_clips(tr)
    i, j = finde(ws, von, ab)
    if bis != von:
        _, j = finde(ws, bis, ws[i]["s"])
    w0, w1 = ws[i], ws[j]
    nach = ws[j + 1]["s"] if j + 1 < len(ws) else None
    vor_e = ws[i - 1]["e"] if i else 0.0
    env = env if env is not None else huelle(clip)
    warn = []
    s, e = w0["s"] - R["vorlauf"], w1["e"] + 0.3
    if env is not None:
        import kuerzen
        boden = float(np.percentile(env, 5))
        thr = boden + 5
        # Anfang: Ende der letzten Stille vor dem ersten Wort
        vor = [r for r in kuerzen.stille_laeufe(env, max(0.0, w0["s"] - 0.8), w0["s"] + 0.05, thr, 0.04) if r[1] <= w0["s"] + 0.1]
        if vor:
            s = max(vor[-1][0] + min(0.03, (vor[-1][1] - vor[-1][0]) / 2), vor[-1][1] - R["vorlauf"])
        else:
            warn.append(f"Anfang „{von}“ ohne Stille davor: angeschnitten möglich")
        # Ende: erste Stille nach dem letzten Wort
        stille = [r for r in kuerzen.stille_laeufe(env, w1["e"] - 0.1, w1["e"] + 1.0, thr, 0.06)]
        if stille:
            r0, r1 = stille[0]
            e = r0 + min(R["luft"], (r1 - r0) / 2)
        else:
            warn.append(f"Ende „{bis}“ ohne Stille danach: Wort möglicherweise angeschnitten")
    else:
        warn.append("Clip-Ton nicht gefunden (extract.py): Schnittpunkte nach den Wortzeiten von Whisper, nicht am Ton geprüft")
    s = max(0.0, s)
    rohe = (e - s) / per
    beats = max(1, math.ceil(rohe - 0.04))
    ende_beats = s + beats * per
    if nach is not None and nach < ende_beats - 0.03:
        # nächstes Wort beginnt schon im letzten Beat: lieber abrunden, wenn das letzte Wort noch ganz hineinpasst
        if beats > 1 and w1["e"] + 0.15 <= s + (beats - 1) * per:
            beats -= 1
            ende_beats = s + beats * per
        else:
            warn.append(f"nächstes Wort „{ws[j + 1]['w']}“ beginnt {ende_beats - nach:.2f} s vor dem Ende des letzten Beats: "
                        f"{beats + 1} Beats oder Schnitt von Hand (ende=)")
    worte = [dict(w=w["w"], s=w["s"], e=w["e"]) for w in ws[i:j + 1]]
    return dict(src=round(s, 3), beats=beats, dauer=round(beats * per, 3), s=round(s, 3), e=round(e, 3), worte=worte, warn=warn)


def dialog_shots(E):
    return [x for x in E["shots"] if x.get("dialog")]


def untertitel_woerter(E, tr_ordner=None):
    """Untertitel-Wörter auf der Reel-Zeitachse für alle Dialog-Shots: [{w, s, e}]."""
    ordner = tr_ordner or E.get("transkript")
    out, tr_cache = [], {}
    per = E["per"]
    for x in dialog_shots(E):
        if not ordner:
            raise SystemExit("Dialog-Shot, aber kein Transkript-Ordner in der Schnittliste (TRANSKRIPT)")
        tr = tr_cache.setdefault(x["clip"], transkript_laden(ordner, x["clip"]))
        a, b = x["src"], x["src"] + x["beats"] * per
        for w in woerter_des_clips(tr):
            m = (w["s"] + w["e"]) / 2
            if a - 0.02 <= m <= b + 0.02:
                kern = norm(w["w"])
                e = min(w["e"], w["s"] + max(0.45, 0.11 * len(kern)))     # von Whisper gedehnte Wörter kappen
                out.append(dict(w=w["w"], s=round(x["t"] + max(0.0, w["s"] - a), 3), e=round(x["t"] + min(e, b) - a, 3)))
    return out


def untertitel_ass(E, work=None, tr_ordner=None, name=None):
    """Schreibt die ASS-Datei der Dialog-Shots nach $REEL_WORK/dialog/ und gibt den Pfad zurück (None ohne Dialoge)."""
    if not dialog_shots(E):
        return None
    from untertitel import ass
    work = Path(work or WORK)
    (work / "dialog").mkdir(parents=True, exist_ok=True)
    pfad = work / "dialog" / f"{name or 'dialog'}.ass"
    dauer = E["beats"] * E["per"]
    ass(untertitel_woerter(E, tr_ordner), pfad, ende=dauer, max_breite=REGELN["text_breite"])
    return pfad


if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit("python3 dialog.py <transkript-ordner> <clip> <von-phrase> <bis-phrase> [per=0.4286]")
    r = phrase(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]) if len(sys.argv) > 5 else 60 / 140)
    print(json.dumps(r, ensure_ascii=False, indent=1))
