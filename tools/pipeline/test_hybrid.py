#!/usr/bin/env python3
"""Test von Kürzen und Bild-Überlagerung in interview.py mit synthetischem Material (~1,5 min, ohne Drive, ohne Whisper).

    python3 /mnt/project-files/tools/pipeline/test_hybrid.py

Clip A: Hochkant-Testbild, Ton wie in test_kuerzen.py (lange Pausen, Füllwort „ähm“). Clip B: rote Fläche als B-Roll.
Ein Teil mit `kuerzen: true` und einem `bild` (B-Roll ab 4,3 s Quellzeit, 0,7 s). Prüft: --trocken teilt den Teil in Stücke
(#1a, #1b …) und zeigt das Bild, der Lauf baut durch, „ähm“ steht nicht im Untertitel, das Bild ist im richtigen Stück
rot (und sonst nicht), die Stimme läuft unter dem B-Roll weiter, die Gesamtlänge ist um die Ersparnis kürzer.
Dazu ein Teil mit `bild` einer zweiten Kamera (`kamera`, Zeit aus einer von Hand geschriebenen sync.json).
Arbeitet in einem Temp-Ordner und hinterlässt nichts im Projektordner.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.dont_write_bytecode = True
PIPE = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPE))
import test_kuerzen as tk  # noqa: E402
import kuerzen  # noqa: E402


def sh(*cmd, env=None, ok=(0,)):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env)
    if r.returncode not in ok:
        sys.exit(f"FEHLER {' '.join(map(str, cmd[:3]))}…\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r.stdout + r.stderr


def ok(text):
    print("OK  ", text, flush=True)


def bild_bei(video, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=90:160",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, np.uint8).reshape(-1, 3).astype(float)
    return x.mean(axis=0)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="testhybrid_"))
    work = tmp / "work"
    reel = tmp / "reels" / "2026-01-01_hy"
    (reel / "schnitt" / "transkript").mkdir(parents=True)
    x, ws, dauer = tk.bauen()
    x48 = np.interp(np.arange(int(dauer * 48000)) / 48000, np.arange(len(x)) / 16000, x).astype(np.float32)
    sf.write(tmp / "A.wav", x48, 48000)
    sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1080x1920:rate=30:duration={dauer}", "-i", tmp / "A.wav",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", tmp / "A.mp4")
    sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:size=1080x1920:rate=30:duration=8",
       "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-shortest", tmp / "B.mp4")
    (reel / "schnitt" / "transkript" / "A.json").write_text(json.dumps(dict(segmente=[dict(woerter=ws)])))
    sr = 48000
    tt = np.arange(24 * sr) / sr
    song = 0.3 * np.sin(2 * np.pi * 110 * tt) * (0.6 + 0.4 * np.sin(2 * np.pi * 2.3 * tt))
    sf.write(tmp / "song.wav", np.stack([song, song], 1).astype(np.float32), sr)
    cfg = dict(name="hy", clips={"A": str(tmp / "A.mp4"), "B": str(tmp / "B.mp4")}, transkript=str(reel / "schnitt" / "transkript"),
               song=dict(datei=str(tmp / "song.wav"), start=0.0, unter_sprache=13, in_pausen=6, fade_ende=1.0),
               kopf_nach=1.0, ersetzen={}, kuerzen=True,
               teile=[dict(clip="A", von=0.3, bis=round(dauer - 0.3, 3), notiz="Antwort",
                           bild=[dict(clip="B", src=1.0, ab=4.0, dauer=0.7)])])
    js = reel / "schnitt" / "schnitt.json"
    js.write_text(json.dumps(cfg))
    env = dict(os.environ, REEL_WORK=str(work), PYTHONDONTWRITEBYTECODE="1")
    # 1. --trocken: Stücke und Bild
    out = sh("python3", PIPE / "interview.py", js, "--trocken", env=env, ok=(0, 1))
    zeilen = [z for z in out.splitlines() if z.startswith("  #1") or " #1" in z[:8]]
    assert "#1a" in out and "#1b" in out, out[-1500:]
    assert out.count("[Bild B") == 1, out[-1500:]
    assert "Kürzen #1:" in out, out[-800:]
    ok(f"--trocken: {sum(1 for z in out.splitlines() if z.strip().startswith('#1'))} Stücke, ein Bild, Meldung zum Kürzen")
    # 2. Lauf
    out = sh("python3", PIPE / "interview.py", js, env=env, ok=(0, 1))
    info = json.loads((reel / "schnitt" / "schnitt_info.json").read_text())
    teile = info["teile"]
    assert len(teile) >= 4 and teile[0]["nr"] == "#1a", [t["nr"] for t in teile]
    texte = " ".join(t["text"] for t in teile).lower()
    assert "ähm" not in texte and "das erste mal" in texte, texte
    ass = (work / "interview" / "untertitel.ass").read_text(encoding="utf-8")
    assert "ähm" not in ass.lower() and "mal" in ass.lower()
    ok(f"Lauf: {len(teile)} Stücke, „ähm“ weder in der Liste noch im Untertitel, Länge {info['laenge']:.2f} s")
    # 3. Bild rot im richtigen Stück
    zus = work / "interview" / "zusammen.mp4"
    mit_bild = [t for t in teile if "Bild B" in t["kopf"]]
    assert len(mit_bild) == 1, [t["kopf"] for t in teile]
    tb = mit_bild[0]
    q = 4.3 - float(tb["kopf"].split()[1].split("–")[0])      # Sekunde im Stück: Quellzeit 4,3 s minus Stück-Anfang
    rot = bild_bei(zus, tb["t0"] + q + 0.3)
    davor = bild_bei(zus, tb["t0"] + 0.05)
    assert rot[0] > 150 and rot[1] < 60 and rot[2] < 60, rot
    assert not (davor[0] > 150 and davor[1] < 60), davor
    ok(f"B-Roll ist im Stück {tb['nr']} rot ({rot.round()}), davor und danach der Sprecher")
    # 4. Stimme läuft unter dem B-Roll weiter
    v, sr_ = sf.read(work / "interview" / "stimme_solo.wav")
    v = v.mean(axis=1) if v.ndim > 1 else v
    a = int((tb["t0"] + q + 0.1) * sr_)
    rms = float(np.sqrt(np.mean(v[a:a + int(0.4 * sr_)] ** 2)))
    assert rms > 0.02, rms
    ok(f"Stimme läuft unter dem B-Roll weiter (RMS {rms:.3f})")
    # 5. Länge = Quelle minus Ersparnis
    env_ = kuerzen.huelle(x, 16000)
    res = kuerzen.schnitte(ws, env_, 0.3, dauer - 0.3, kuerzen.REGELN, x)
    erwartet = (dauer - 0.6) - res["ersparnis"]
    assert abs(info["laenge"] - erwartet) < 0.25, (info["laenge"], erwartet)
    ok(f"Länge {info['laenge']:.2f} s = {dauer - 0.6:.2f} s minus {res['ersparnis']:.2f} s gekürzt")
    # 6. Andere Kamera über der Stimme: Zeit aus sync.json (A Offset 0, B Offset −1,5: Sekunde t in A ist t + 1,5 in B)
    syn = {"version": 1, "ref": "A", "clips": {
        "A": dict(offset_s=0.0, bezug_s=0.0, dauer_s=dauer, brauchbar=True, drift_ppm=0.0, drift_sicher=False),
        "B": dict(offset_s=-1.5, bezug_s=0.0, dauer_s=8.0, brauchbar=True, drift_ppm=0.0, drift_sicher=False)}}
    (reel / "schnitt" / "sync.json").write_text(json.dumps(syn))
    cfg2 = dict(cfg, sync=str(reel / "schnitt" / "sync.json"), kuerzen=False,
                teile=[dict(clip="A", von=0.3, bis=3.3, bild=[dict(kamera="B", ab=1.0, dauer=0.8)])])
    js.write_text(json.dumps(cfg2))
    out = sh("python3", PIPE / "interview.py", js, "--trocken", env=env, ok=(0, 1))
    assert "[Bild B ab 1 s, 0.8 s, Quelle 2.80 s]" in out, out[-800:]      # 0,3 + 1,0 + 1,5
    cfg3 = dict(cfg2, sync=str(tmp / "gibtsnicht.json"))
    js.write_text(json.dumps(cfg3))
    r = subprocess.run(["python3", str(PIPE / "interview.py"), str(js), "--trocken"], capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "gibtsnicht" in (r.stdout + r.stderr), r.stdout[-300:] + r.stderr[-300:]
    syn["clips"]["B"]["brauchbar"] = False
    (reel / "schnitt" / "sync.json").write_text(json.dumps(syn))
    js.write_text(json.dumps(cfg2))
    r = subprocess.run(["python3", str(PIPE / "interview.py"), str(js), "--trocken"], capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "läuft" in (r.stdout + r.stderr), r.stdout[-300:] + r.stderr[-300:]
    ok("kamera: Quellzeit aus sync.json (2,80 s); fehlendes sync.json und unbrauchbare Zuordnung (Musik mehrdeutig) stoppen mit Meldung")
    print("alle Tests grün")
    return 0


if __name__ == "__main__":
    sys.exit(main())
