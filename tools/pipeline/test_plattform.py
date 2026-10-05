#!/usr/bin/env python3
"""Test der Werkzeuge für YouTube Shorts ohne Drive (~1,5 min): plattform.py, export.py --plattform, reframe.py.

    python3 /mnt/project-files/tools/pipeline/test_plattform.py

plattform.py: Profile und Alias, Instagram-Filter und -Encoder gleich wie in export.py (Regression), YouTube-Export eines
Testmasters (−14 LUFS, True Peak, Keyframe-Abstand, Faststart), die Prüfung findet Querformat und zu laute Instagram-Dateien,
umwandeln (Video unverändert, Ton −14 LUFS), ui-Overlay. reframe.py: ein Testvideo (1920×1080) mit Motiv, das von links nach
rechts läuft: Tracking hält es im Ausschnitt, mitte und blur liefern 1080×1920, Hochformat wird nicht angefasst, --manifest
schreibt die Zeile. Arbeitet in einem Temp-Ordner, fasst nichts im Projekt an. Drive: test_drive.py, Interview: test_interview.py.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

PIPE = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPE))
sys.dont_write_bytecode = True


def sh(*cmd, env=None, ok=(0,)):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env)
    if r.returncode not in ok:
        sys.exit(f"FEHLER {' '.join(map(str, cmd[:3]))}…\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r.stdout + r.stderr


def rgb_frame(pfad, t, w, h):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(pfad), "-frames:v", "1", "-f", "rawvideo",
                        "-pix_fmt", "bgr24", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(h, w, 3)


def plattform_test(tmp):
    import export
    import plattform as pf
    import reel_audio as ra
    ig, yt = pf.profil("instagram"), pf.profil("youtube")
    assert pf.profil("shorts") is yt and pf.profil("IG") is ig and len(pf.plattformen("ig,yt,instagram")) == 2
    try:
        pf.profil("tiktok")
        raise AssertionError("unbekannte Plattform muss abbrechen")
    except SystemExit:
        pass
    assert pf.vf_kette(ig) == export.VF and pf.x264_args(ig) == export.X264, "Instagram-Export muss unverändert bleiben"
    assert pf.dateiname("reel", ig, "mit_song.mp4") == "reel_mit_song.mp4"
    assert pf.dateiname("reel", yt, "mit_song.mp4") == "reel_yt_mit_song.mp4"
    print("OK   plattform: Profile, Alias, Instagram-Filter und -Encoder unverändert, Dateinamen")

    master, wav = tmp / "master.mp4", tmp / "mix.wav"
    sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=6", "-c:v", "libx264",
       "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace",
       "bt709", master)
    sr = 48000
    t = np.arange(6 * sr) / sr
    x = 0.5 * np.sin(2 * np.pi * 110 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 2.3 * t)) + 0.15 * np.sin(2 * np.pi * 1800 * t)
    x = np.stack([x, x * 0.9], 1)
    x *= 10 ** ((-11.0 - ra.lufs(x)) / 20)
    sf.write(wav, x.astype(np.float32), sr, subtype="FLOAT")

    yt_stumm, yt_mit = tmp / "yt_stumm.mp4", tmp / "test_yt_mit_song.mp4"
    pf.video_export(master, yt_stumm, yt)
    pf.mux(yt_stumm, pf.ton_fuer(wav, yt, ra), yt_mit, yt)
    z = pf.pruefen(yt_mit, yt)
    assert not [s for s, _ in z if s in (pf.FAIL, pf.WARN)], z
    txt = " | ".join(t_ for _, t_ in z)
    lu = float(re.search(r"Lautheit (-?\d+\.\d) LUFS", txt).group(1))
    tp = float(re.search(r"True Peak (-?\d+\.\d+) dBTP", txt).group(1))
    assert abs(lu + 14) <= 0.5 and tp <= -1.0, (lu, tp)
    assert "Keyframe-Abstand höchstens 0.50 s" in txt and "Faststart" in txt, txt
    print(f"OK   plattform: YouTube-Export {lu} LUFS, True Peak {tp} dBTP, Keyframe ≤ 0,5 s, Faststart, Prüfung ohne Warnung")

    ig_stumm, ig_mit = tmp / "ig_stumm.mp4", tmp / "test_mit_song.mp4"
    export.instagram(master, ig_stumm)
    ra.mux(str(ig_stumm), str(wav), str(ig_mit))
    z = pf.pruefen(ig_mit, ig)
    assert not [s for s, _ in z if s == pf.FAIL], z
    z = pf.pruefen(ig_mit, yt)
    assert any(s == pf.WARN and "Lautheit" in t_ for s, t_ in z), z         # −11 LUFS gegen das YouTube-Ziel −14
    quer = tmp / "quer.mp4"
    sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=2", "-c:v", "libx264",
       "-preset", "ultrafast", "-pix_fmt", "yuv420p", quer)
    assert any(s == pf.FAIL and "Auflösung" in t_ for s, t_ in pf.pruefen(quer, yt))
    print("OK   plattform: Prüfung meldet Instagram-Pegel gegen YouTube und Querformat als Fehler")

    ziel = pf.umwandeln(ig_mit, yt, tmp / "umgewandelt_yt.mp4")
    a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=size", "-of", "csv=p=0",
                        str(ig_mit)], capture_output=True, text=True).stdout.split()
    b = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=size", "-of", "csv=p=0",
                        str(ziel)], capture_output=True, text=True).stdout.split()
    assert a == b, "umwandeln muss das Video unverändert lassen (Stream-Copy)"
    z = pf.pruefen(ziel, yt)
    assert re.search(r"Lautheit -1[34]\.\d LUFS", " | ".join(t_ for _, t_ in z)), z
    print("OK   plattform: umwandeln lässt das Video bitgleich und bringt den Ton auf −14 LUFS")

    bild = pf.ui_bild(yt_mit, yt, [1.0, 3.0], tmp / "ui.jpg")
    from PIL import Image
    w_, h_ = Image.open(bild).size
    assert w_ * h_ <= 1.15e6 and w_ <= 1568 and h_ <= 1568, (w_, h_)
    print(f"OK   plattform: ui-Overlay {w_}×{h_} px")

    c = sh("python3", PIPE / "plattform.py", "check", ig_mit, "--plattform", "youtube", ok=(0, 1))
    assert "WARNUNG" in c and "Ergebnis" in c
    s = sh("python3", PIPE / "plattform.py", "show")
    assert "YouTube Shorts" in s and "Instagram" in s
    print("OK   plattform.py Kommandozeile: check, show")


def testvideo(pfad, dauer=6, fps=30, breite=1920, hoehe=1080):
    """Statischer Hintergrund, orange Figur mit schwingenden Armen läuft von x=300 mit 200 px/s nach rechts."""
    import cv2
    rng = np.random.default_rng(3)
    bg = cv2.GaussianBlur(rng.integers(60, 120, (hoehe, breite, 3), dtype=np.uint8), (0, 0), 25)
    for x in range(0, breite, 120):
        cv2.line(bg, (x, 0), (x, hoehe), (90, 100, 110), 2)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{breite}x{hoehe}",
                            "-framerate", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "12", "-preset", "veryfast",
                            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc",
                            "bt709", str(pfad)], stdin=subprocess.PIPE)
    for i in range(fps * dauer):
        t = i / fps
        f = bg.copy()
        cx = int(300 + 200 * t)
        arm = int(70 * np.sin(2 * np.pi * 1.5 * t))
        cv2.ellipse(f, (cx, 620), (55, 200), 0, 0, 360, (30, 120, 255), -1)
        cv2.line(f, (cx - 50, 500), (cx - 110, 500 + arm), (30, 120, 255), 24)
        cv2.line(f, (cx + 50, 500), (cx + 110, 500 - arm), (30, 120, 255), 24)
        cv2.circle(f, (cx, 380), 45, (30, 120, 255), -1)
        enc.stdin.write(f.tobytes())
    enc.stdin.close()
    enc.wait()


def orange_mitte(bild):
    import cv2
    hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
    m = (hsv[..., 0] > 5) & (hsv[..., 0] < 20) & (hsv[..., 1] > 150) & (hsv[..., 2] > 150)
    xs = np.nonzero(m)[1]
    return xs.mean() if len(xs) else None


def reframe_test(tmp):
    quelle = tmp / "quer_lauf.mp4"
    testvideo(quelle)
    env = dict(os.environ, REEL_WORK=str(tmp / "reelwork"), PYTHONDONTWRITEBYTECODE="1")
    # Tracking
    out = sh("python3", PIPE / "reframe.py", quelle, "-o", tmp / "lauf_9x16.mp4", env=env)
    assert "Modus    tracking: Fenster 608×1080 (32 % der Breite), Faktor 1.78 auf 1080×1920" in out and "weich" in out, out
    assert "180 Bilder (Quelle 180)" in out, out
    assert (tmp / "reelwork" / "ansicht" / "reframe_quer_lauf.jpg").exists(), out
    fehler = []
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        x = orange_mitte(rgb_frame(tmp / "lauf_9x16.mp4", t, 1080, 1920))
        assert x is not None, f"Figur bei {t} s nicht im Ausschnitt"
        fehler.append(abs(x - 540) / 1.78)                 # Abweichung von der Mitte in Quellpixeln
    assert max(fehler) <= 120, fehler                      # Toleranzzone 91 px plus Glättung; Fenster ist ±304 px breit
    mitte = orange_mitte(rgb_frame(tmp / "lauf_9x16.mp4", 0.2, 1080, 1920))
    ende = orange_mitte(rgb_frame(tmp / "lauf_9x16.mp4", 5.8, 1080, 1920))
    assert mitte is not None and ende is not None
    print(f"OK   reframe tracking: Figur bleibt im Ausschnitt (Abweichung von der Mitte höchstens {max(fehler):.0f} Quellpixel), "
          f"Kontaktbogen, Bilderzahl gleich der Quelle")
    # mitte und blur
    for modus in ("mitte", "blur"):
        out = sh("python3", PIPE / "reframe.py", quelle, "--modus", modus, "-o", tmp / f"{modus}.mp4", "--kein-kontakt", env=env)
        wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,color_transfer",
                             "-of", "csv=p=0", str(tmp / f"{modus}.mp4")], capture_output=True, text=True).stdout.strip()
        assert wh.startswith("1080,1920"), (modus, wh, out)
    f = rgb_frame(tmp / "blur.mp4", 1.0, 1080, 1920)
    assert f[960 - 100:960 + 100].std() > 8 and f[:150].std() < f[960 - 100:960 + 100].std(), "blur: Mitte scharf, Rand unscharf"
    print("OK   reframe mitte und blur: 1080×1920, bei blur oben und unten unscharf")
    # Hochformat bleibt liegen, Manifest
    hoch = tmp / "hoch.mp4"
    sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=1", "-c:v", "libx264",
       "-preset", "ultrafast", "-pix_fmt", "yuv420p", hoch)
    out = sh("python3", PIPE / "reframe.py", hoch, env=env)
    assert "schon Hochformat" in out and not (tmp / "reelwork" / "reframe" / "hoch_9x16.mp4").exists(), out
    sh("python3", PIPE / "reframe.py", quelle, "--modus", "mitte", "--kein-kontakt", "--manifest", env=env)
    sh("python3", PIPE / "reframe.py", quelle, "--modus", "mitte", "--kein-kontakt", "--manifest", env=env)   # ersetzt, keine Doppelung
    zeilen = (tmp / "reelwork" / "manifest.tsv").read_text().splitlines()
    assert len(zeilen) == 1 and zeilen[0].startswith("local:") and "\tquer_lauf_9x16.mp4\t" in zeilen[0], zeilen
    p = sh("python3", PIPE / "drive.py", "pruefen", tmp / "reelwork" / "manifest.tsv", ok=(0, 1))
    assert "FEHLER" not in p, p
    print("OK   reframe: Hochformat unangetastet, --manifest trägt den Clip als local: ein (ohne Doppelung), drive.py pruefen ok")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="testplattform_"))
    plattform_test(tmp)
    reframe_test(tmp)
    print("test_plattform: alles OK", tmp)


if __name__ == "__main__":
    main()
