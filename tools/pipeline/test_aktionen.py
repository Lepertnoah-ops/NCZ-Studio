#!/usr/bin/env python3
"""Test von aktionen.py ohne Drive und ohne Originalclips (~20 s): ein künstlicher Clip mit bekannten Stellen.

    python3 test_aktionen.py            # oder: python3 aktionen.py selbsttest

Der Clip (360×640, 30 fps, 20 s, Hintergrund und Motiv mit Zufallstextur):
  Aktionen des Motivs    3,0–4,5 s   7,0–8,6 s   16,0–17,5 s   (Motiv pendelt seitlich, sonst Ruhe)
  Kameraschwenk          10,0–11,0 s (Bild läuft mit 290 px/s durch, ~870 px/s bei 1080 px Breite)
  Unschärfe              13,0–14,0 s (Gauß-Weichzeichner)
Erwartung: die drei Aktionen werden gefunden, Schwenk und Unschärfe als unsauber benannt, Ausschnitte mitten in der
Aktion bekommen „Anlauf fehlt“/„Landung fehlt“ samt Vorschlag, ganze Aktionen bleiben ohne Hinweis.
Läuft in einem eigenen $REEL_WORK (temporär), fasst den Projektordner nicht an.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
TMP = Path(tempfile.mkdtemp(prefix="aktionen_test_"))
os.environ["REEL_WORK"] = str(TMP)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
import cv2  # noqa: E402
import aktionen  # noqa: E402

FPS, W, H, DAUER = 30, 360, 640, 20.0
AKTIONEN = [(3.0, 4.5), (7.0, 8.6), (16.0, 17.5)]
SCHWENK, UNSCHARF = (10.0, 11.0), (13.0, 14.0)


def ok(text):
    print("OK  ", text, flush=True)


def kuenstlicher_clip(pfad):
    rs = np.random.RandomState(7)
    bg = cv2.GaussianBlur(rs.randint(0, 255, (H, W, 3)).astype(np.uint8), (0, 0), 1.2)
    sub = cv2.GaussianBlur(rs.randint(0, 255, (170, 100, 3)).astype(np.uint8), (0, 0), 1.2)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-an", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(pfad)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(int(DAUER * FPS)):
        t = f / FPS
        x = 130
        for a, b in AKTIONEN:
            if a <= t < b:
                x += int(60 * np.sin(2 * np.pi * (t - a) / 0.75))
        bild = bg.copy()
        bild[230:400, x:x + 100] = sub
        if t >= SCHWENK[0]:
            bild = np.roll(bild, int(290 * (min(t, SCHWENK[1]) - SCHWENK[0])), axis=1)
        if UNSCHARF[0] <= t < UNSCHARF[1]:
            bild = cv2.GaussianBlur(bild, (0, 0), 6)
        p.stdin.write(bild.tobytes())
    p.stdin.close()
    if p.wait():
        raise SystemExit("ffmpeg konnte den künstlichen Clip nicht schreiben")


def ueberlappt(a, b, tol=0.5):
    return a[0] < b[1] + tol and a[1] > b[0] - tol


def main():
    try:
        clip = TMP / "kuenstlich.mp4"
        kuenstlicher_clip(clip)
        quellen = aktionen.Quellen(behalten=True)
        info = aktionen.serie(str(clip), 0.0, 1e9, quellen, threads=2)
        M = aktionen.merkmale(info)
        ok(f"Messung {M['bereich'][0]:.1f}–{M['bereich'][1]:.1f} s, Ruhe-Grenze {M['rg']:.0f} px/s, "
           f"{len(M['aktionen'])} Aktion(en)")

        # 1. Aktionen gefunden, keine in den Ruhephasen
        for soll in AKTIONEN:
            treffer = [k for k in M["aktionen"] if ueberlappt((k["von"], k["bis"]), soll)]
            assert treffer, f"Aktion {soll} nicht gefunden: {M['aktionen']}"
        falsch = [k for k in M["aktionen"] if not any(ueberlappt((k["von"], k["bis"]), s) for s in AKTIONEN + [SCHWENK])]
        assert not falsch, f"Aktion in einer Ruhephase gemeldet: {falsch}"
        ok("drei Aktionen gefunden, keine in den Ruhephasen")

        # 2. unsaubere Stellen
        def grund(spanne, name):
            return any(ueberlappt((k["von"], k["bis"]), spanne, 0.2) and name in k["grund"] for k in M["unsauber"])
        assert grund(SCHWENK, "Schwenk"), M["unsauber"]
        assert grund(UNSCHARF, "unscharf"), M["unsauber"]
        ruhig = [k for k in M["unsauber"] if not any(ueberlappt((k["von"], k["bis"]), s, 0.3) for s in (SCHWENK, UNSCHARF))]
        assert not ruhig, f"unsaubere Stelle in ruhigem Material: {ruhig}"
        ok("Schwenk und Unschärfe benannt, sonst nichts unsauber")

        # 3. Bewertung: Ausschnitt mitten in der Aktion schlecht, ganze Aktion gut
        k_gut, d_gut = aktionen.bewerten(M, 2.6, 4.9)
        k_anf, d_anf = aktionen.bewerten(M, 3.9, 5.4)            # Anfang im Höhepunkt der Aktion (3,7–4,1 s)
        k_end, d_end = aktionen.bewerten(M, 1.9, 3.9)
        assert k_gut < 0.5 and not d_gut["angeschnitten"], (k_gut, d_gut)
        assert [w for _, w in d_anf["angeschnitten"]] == ["anfang"], d_anf
        assert [w for _, w in d_end["angeschnitten"]] == ["ende"], d_end
        k_vor, d_vor = aktionen.bewerten(M, 3.5, 5.0)             # Anfang im schwachen Anlauf: kein Befund
        assert not d_vor["angeschnitten"], d_vor
        ok("ganze Aktion ohne Befund, Anfang und Ende im Höhepunkt erkannt, Schnitt im Anlauf nicht")

        # 4. Vorschläge liegen in Ruhe, enthalten den Moment und bleiben nah am bisherigen In-Punkt
        v = aktionen.vorschlaege(M, 2.0, s0=3.6, moment=3.75, n=1)
        assert v and v[0][0] < 0.5, v
        s, e = v[0][1], v[0][2]
        assert s <= 3.0 + 0.15 and e >= 4.5 - 0.15, (s, e)
        ok(f"Vorschlag für 2,0 s um 3,6 s: {s:.1f}–{e:.1f} s (ganze Aktion 3,0–4,5 s)")
        bv = aktionen.beats_vorschlag(M, 1, 0.25, 1.0, 3.85, 3.85)     # 0,25 s Szene, Höhepunkt 0,4 s lang
        assert bv and bv[0] >= 2 and bv[1] <= 3.85 and bv[2] >= 4.0, bv
        ok(f"Höhepunkt länger als die Szene: {bv[0]} statt 1 Beat ({bv[1]:.1f}–{bv[2]:.1f} s)")
        gesamt = aktionen.vorschlaege(M, 1.0, None, None, 3)
        assert gesamt and gesamt[0][0] <= 0, gesamt
        ok("Clip-Befund ohne In-Punkt liefert Vorschläge")

        # 5. Schnittliste: ganze Aktion, angeschnittene Aktion, Schwenk, Jump Cut
        def shot(n, src, beats, **kw):
            return dict(n=n, beat=0, t=0.0, beats=beats, clip=str(clip), src=src, mode="normal", fx=[], fxp={},
                        desc=kw.pop("desc", "Motiv pendelt"), **kw)
        E = dict(per=0.5, beats=24, ausklang=0, shots=[
            shot(1, 6.6, 4),                          # ganze Aktion 7,0–8,6 s, Ende knapp danach: ohne Befund
            shot(2, 16.9, 2),                         # Anfang im Höhepunkt der Aktion 16,0–17,5 s
            shot(3, 10.1, 2),                         # im Schwenk
            shot(4, 2.6, 4, desc="Motiv pendelt"),    # 2,6–4,6 s: ganze Aktion
            shot(5, 3.9, 2, jump=True),               # Jump Cut von 4,6 zurück auf 3,9 s: Anfang im Höhepunkt der ersten Aktion
        ])
        res, fehler = aktionen.pruefe_edl(E, quellen, personen_an=False, jobs=1)
        assert not fehler, fehler
        nach = {b["n"]: b for b in res}
        assert not nach[1]["hinweise"], nach[1]["hinweise"]
        assert any("Anlauf fehlt" in h for h in nach[2]["hinweise"]), nach[2]
        v2 = nach[2]["vorschlag"]
        assert v2 and v2["src"] <= 16.8 and v2["ende"] >= 17.0, v2
        assert any("unsauber" in h and "Schwenk" in h for h in nach[3]["hinweise"]), nach[3]["hinweise"]
        assert not nach[4]["hinweise"], nach[4]["hinweise"]
        assert any("Anlauf fehlt" in h for h in nach[5]["hinweise"]), nach[5]["hinweise"]
        assert any("Jump Cut" in h for h in nach[5]["hinweise"]), nach[5]["hinweise"]
        ok("Schnittliste: ganze Aktion ok, angeschnittene Aktion mit Beat-Vorschlag, Schwenk, Anlauf")
        text = aktionen.text_edl(res, "Test")
        assert "zum Nachsehen" in text and "besser:" in text, text
        ok("Bericht: " + text.splitlines()[0])

        # 6. Dauerbewegung und Stichwort „durchgehend“ werden nicht geprüft
        E2 = dict(per=0.5, beats=4, ausklang=0, shots=[shot(1, 16.9, 2, desc="Seilspringen")])
        res2, _ = aktionen.pruefe_edl(E2, quellen, personen_an=False, jobs=1)
        assert not res2[0]["hinweise"], res2[0]["hinweise"]
        ok("Stichwort durchgehende Bewegung: keine Anfang-Ende-Prüfung")

        # 7. Cache: zweiter Lauf misst nicht noch einmal
        cache = aktionen.cache_datei(str(clip))
        assert cache and cache.exists()
        vor = cache.stat().st_mtime_ns
        aktionen.serie(str(clip), 2.0, 12.0, quellen)
        assert cache.stat().st_mtime_ns == vor
        ok("Cache wird wiederverwendet")
        print("alle Tests grün")
        return 0
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
