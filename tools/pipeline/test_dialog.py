#!/usr/bin/env python3
"""Test von dialog.py (Dialog im Reel) mit künstlicher Sprache, ohne Drive und ohne Whisper (~20 s).

    python3 test_dialog.py

Ton und Wörter wie in test_kuerzen.py („das erste Mal.“ mit Stille davor und danach). Prüft: Phrase -> Quellzeit in der
Stille und ganze Beats, Groß-/Kleinschreibung und Satzzeichen egal, unbekannte Phrase meldet einen Fehler; Untertitel-
Wörter auf der Reel-Zeitachse und ASS-Datei; Tonspur (Song −16 dB gefiltert, Stimme −4 LU, Dialog nicht mit einem
gewöhnlichen O-Ton-Moment verschmolzen); Prüfung edlcheck (Dialog zählt nicht als O-Ton-Moment, mehr als 3 Dialoge,
Zeitlupe, angeschnittenes Wort, fehlendes Transkript); Einbrennen der Untertitel in render.py master (helle Schrift im
Dialog-Shot, nicht davor). Arbeitet in einem Temp-Ordner.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.dont_write_bytecode = True
PIPE = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPE))
import dialog  # noqa: E402
import edlcheck  # noqa: E402
import kuerzen  # noqa: E402
import test_kuerzen as tk  # noqa: E402
import tonspur  # noqa: E402

PER = 60 / 140


def ok(text):
    print("OK  ", text, flush=True)


def shot(n, beat, beats, clip="T", **kw):
    return dict(n=n, beat=beat, beats=beats, t=round(beat * PER, 4), clip=clip, src=kw.pop("src", 0.0), mode="normal", fx=[], fxp={},
                desc="", prev=0.0, sec="K", szene=n, **kw)


def main():
    x, ws, dauer = tk.bauen()
    env = kuerzen.huelle(x, tk.SR)
    tr = dict(segmente=[dict(woerter=ws)])
    tmp = Path(tempfile.mkdtemp(prefix="testdialog_"))
    try:
        return lauf(tmp, x, ws, dauer, env, tr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def lauf(tmp, x, ws, dauer, env, tr):
    # 1. Phrase -> Quellzeit und Beats
    r = dialog.phrase(None, "T", "das erste", "MAL", PER, tr=tr, env=env)
    assert [w["w"] for w in r["worte"]] == ["das", "erste", "Mal."], r["worte"]
    assert 0.30 < r["src"] < 0.5 and r["beats"] == 6 and abs(r["dauer"] - 6 * PER) < 1e-3, r
    assert env[int(r["src"] * dialog.HZ)] < float(np.percentile(env, 5)) + 11, "Anfang liegt nicht in der Stille"
    ende = r["src"] + r["dauer"]
    assert 2.6 < ende < 3.4, ende                       # Wort endet bei 2,6 s, nächstes Wort erst bei 3,4 s
    assert not r["warn"], r["warn"]
    ok(f"„das erste Mal“: src {r['src']:.2f} s, {r['beats']} Beats bis {ende:.2f} s, Anfang in der Stille (Groß-/Kleinschreibung egal)")
    r1 = dialog.phrase(None, "T", "also", "gut", PER, tr=tr, env=env)
    assert r1["beats"] == 3 and abs(r1["src"] - (4.2 - 0.12)) < 0.1, r1        # 4,2–5,1 s plus Luft = 1,35 s -> 3 Beats
    # nächstes Wort beginnt im letzten Beat: Warnung oder ein Beat weniger
    ws2 = [dict(w=w["w"], s=w["s"], e=w["e"]) for w in ws]
    nach = dict(w="dann", s=round(r1["src"] + r1["dauer"] - 0.1, 3), e=round(r1["src"] + r1["dauer"] + 0.2, 3))
    tr2 = dict(segmente=[dict(woerter=sorted(ws2 + [nach], key=lambda q: q['s']))])
    r2 = dialog.phrase(None, "T", "also", "gut", PER, tr=tr2, env=env)
    assert r2["warn"] and "nächstes Wort" in r2["warn"][0] or r2["beats"] == 2, r2
    ok(f"nächstes Wort im letzten Beat: {'Warnung' if r2['warn'] else str(r2['beats']) + ' Beats'}")
    try:
        dialog.phrase(None, "T", "gibt es", "nicht", PER, tr=tr, env=env)
        raise AssertionError("keine Fehlermeldung")
    except ValueError as e:
        assert "nicht im Transkript" in str(e)
    ok("unbekannte Phrase: Fehlermeldung statt Raten")
    # 2. Untertitel-Wörter und ASS
    trd = tmp / "tr"
    trd.mkdir()
    (trd / "T.json").write_text(json.dumps(tr))
    E = dict(per=PER, beats=12, shots=[shot(1, 0, 4, src=0.0), shot(2, 4, 6, src=r["src"], oton="vorn", dialog=True),
                                      shot(3, 10, 2, src=1.0)], transkript=str(trd))
    uw = dialog.untertitel_woerter(E)
    assert [w["w"] for w in uw] == ["das", "erste", "Mal."], uw
    t0 = 4 * PER
    assert abs(uw[0]["s"] - (t0 + 0.5 - r["src"])) < 0.02 and uw[-1]["e"] <= t0 + 6 * PER + 1e-6, (uw, t0)
    ass = dialog.untertitel_ass(E, tmp / "w")
    assert ass.exists() and "erste" in ass.read_text(encoding="utf-8").lower(), ass
    ok(f"Untertitel: 3 Wörter ab {uw[0]['s']:.2f} s auf der Reel-Zeitachse, ASS-Datei geschrieben")
    # 3. Tonspur: Song −16 dB gefiltert, Stimme −4 LU; aneinandergrenzender Dialog und O-Ton-Moment nicht verschmolzen
    E3 = dict(E, einstieg=0, ausklang=0, auftakt=0, takte=3, einstieg_song="gedämpft",
              shots=[shot(1, 0, 4), shot(2, 4, 4, oton="vorn", dialog=True), shot(3, 8, 4, oton="vorn")])
    spec = tonspur.audio_spec(E3, "song.wav", 1.0)
    fx = [f for f in spec["music_fx"] if f.get("moment")]
    assert len(fx) == 2 and fx[0].get("dialog") and fx[0]["gain_db"] == -16 and fx[0]["lp_hz"] == 2500 and not fx[1].get("dialog"), fx
    lu = [o["level_lu"] for o in spec["oton"]]
    assert lu[0] == tonspur.DIALOG_STIMME and lu[1] == tonspur.pegel("vorn"), lu
    ok(f"Tonspur: Dialog Song {fx[0]['gain_db']:g} dB + Tiefpass {fx[0]['lp_hz']:g} Hz, Stimme {lu[0]:g} LU, O-Ton-Moment daneben getrennt")
    # 4. Prüfung
    base = dict(E3, shots=[shot(1, 0, 4), shot(2, 4, 4, oton="vorn", dialog=True, src=r["src"]), shot(3, 8, 4)])
    w = edlcheck.pruefen(base)
    assert not any("O-Ton-Moment" in m or "Dialog" in m and "Transkript" not in m for m in w), w
    ausser = dict(E3, shots=[shot(i + 1, 4 * i, 4, oton="vorn", dialog=True, src=r["src"]) for i in range(3)])
    assert not any("O-Ton-Moment" in m for m in edlcheck.pruefen(ausser)), edlcheck.pruefen(ausser)
    vier = dict(E3, beats=20, takte=5, shots=[shot(i + 1, 4 * i, 4, oton="vorn", dialog=True, src=r["src"]) for i in range(5)])
    assert any("5 Dialog-Szenen" in m for m in edlcheck.pruefen(vier)), edlcheck.pruefen(vier)
    zeitlupe = dict(base, shots=[base["shots"][0], dict(base["shots"][1], mode="speed", speed=0.5), base["shots"][2]])
    assert any("nicht in Echtzeit" in m for m in edlcheck.pruefen(zeitlupe)), edlcheck.pruefen(zeitlupe)
    mit = dict(base, transkript=str(trd))
    schief = dict(mit, shots=[mit["shots"][0], dict(mit["shots"][1], src=1.1), mit["shots"][2]])      # mitten in „erste“
    assert any("angeschnitten" in m for m in edlcheck.pruefen(schief)), edlcheck.pruefen(schief)
    gut = dict(mit, shots=[mit["shots"][0], dict(mit["shots"][1], src=r["src"], beats=6), mit["shots"][2]], beats=14, takte=14 // 4)
    assert not any("angeschnitten" in m for m in edlcheck.pruefen(gut)), edlcheck.pruefen(gut)
    assert any("ohne TRANSKRIPT" in m for m in edlcheck.pruefen(dict(base, transkript=None))), edlcheck.pruefen(dict(base, transkript=None))
    ok("Prüfung: Dialog zählt nicht als O-Ton-Moment; meldet mehr als 3 Dialoge, Zeitlupe, angeschnittenes Wort, fehlendes Transkript")
    # 5. Einbrennen: render.py master mit einem Dialog-Shot
    frames = tmp / "w" / "frames" / "T"
    frames.mkdir(parents=True)
    fps, n = 30, 110
    bild = np.full((1920, 1080, 3), 40, np.uint8)
    cv2.imwrite(str(frames / "f_00001.jpg"), bild)
    for j in range(2, n + 1):
        os.link(frames / "f_00001.jpg", frames / f"f_{j:05d}.jpg")
    (frames / "times.json").write_text(json.dumps(dict(fps=fps, times=[round(j / fps, 4) for j in range(n)])))
    Er = dict(E, einstieg=0, ausklang=0, beats=12, shots=[shot(1, 0, 4, src=0.0), shot(2, 4, 6, src=r["src"], oton="vorn", dialog=True),
                                                         shot(3, 10, 2, src=2.0)])
    (tmp / "edl.json").write_text(json.dumps(Er))
    (tmp / "fx.json").write_text(json.dumps({"1": {}, "2": {}, "3": {}}))
    env_ = dict(os.environ, REEL_WORK=str(tmp / "w"), REEL_EDL=str(tmp / "edl.json"), REEL_FX=str(tmp / "fx.json"),
                PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, PIPE / "render.py", "master", tmp / "m.mp4"], capture_output=True, text=True, env=env_)
    assert p.returncode == 0 and (tmp / "m.mp4").exists(), p.stdout[-800:] + p.stderr[-1500:]

    def hell(t):
        q = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(tmp / "m.mp4"), "-frames:v", "1", "-vf", "scale=270:480",
                            "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
        a = np.frombuffer(q, np.uint8).reshape(480, 270)
        return int((a[int(480 * 0.55):int(480 * 0.8)] > 200).sum())

    mitte = t0 + 0.5 - r["src"] + 0.45          # „erste“ wird gesprochen
    vorher, dabei = hell(1.0), hell(mitte)
    assert dabei > 150 and vorher < 10, (vorher, dabei)
    ok(f"render.py master brennt die Untertitel ein: {dabei} helle Pixel im Dialog-Shot, {vorher} davor")
    print("alle Tests grün")
    return 0


if __name__ == "__main__":
    sys.exit(main())
