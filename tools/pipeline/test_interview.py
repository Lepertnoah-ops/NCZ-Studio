#!/usr/bin/env python3
"""Test von interview.py mit synthetischem Material (~2 min, braucht kein Drive und kein Whisper).

    python3 /mnt/project-files/tools/pipeline/test_interview.py

Ein 12-s-Testclip (Hochkant, Stimm-ähnlicher Ton), ein Transkript mit Wortzeiten, ein Song und ein Abspann mit der Zeile
„LINK IN BIO“ und einer sehr langen Zeile. Zwei Läufe mit --export: Standard (Instagram) und --plattform youtube. Prüft:
Instagram unverändert (Dateinamen, Link-Zeile bleibt im Abspann, Untertitel 0,84), YouTube (Dateinamen …_yt_…, keine Link-Zeile,
Abspann höchstens 77 % der Breite, Ton −14 LUFS, Profilprüfung aus plattform.py ohne Fehler; die Länge von 10 s liegt unter den
40–60 s des Interview-Stils, das meldet pruefen() erwartungsgemäß als PRÜFEN). Arbeitet in einem Temp-Ordner.
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


def sh(*cmd, env=None, ok=(0,)):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env)
    if r.returncode not in ok:
        sys.exit(f"FEHLER {' '.join(map(str, cmd[:3]))}…\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r.stdout + r.stderr


def main():
    tmp = Path(tempfile.mkdtemp(prefix="testinterview_"))
    work = tmp / "work"
    reel = tmp / "reels" / "2026-01-01_iv"
    (reel / "schnitt" / "transkript").mkdir(parents=True)
    # Clip: 1080×1920, 12 s, Ton mit Silben-Rhythmus
    sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=12",
       "-f", "lavfi", "-i", "aevalsrc='0.25*sin(2*PI*220*t)*(0.55+0.45*sin(2*PI*4*t))+0.1*sin(2*PI*1200*t)':s=48000:d=12",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", tmp / "A.mp4")
    woerter = "Hallo zusammen das ist ein kleiner Test für die Untertitel Verantwortungsbewusstsein und Gemeinschaft".split()
    ws, t = [], 0.6
    for w in woerter:
        d = 0.25 + 0.06 * len(w)
        ws.append(dict(w=w, s=round(t, 3), e=round(t + d, 3), p=0.95))
        t += d + 0.12
    (reel / "schnitt" / "transkript" / "A.json").write_text(json.dumps(dict(segmente=[dict(woerter=ws)])))
    sr = 48000
    tt = np.arange(24 * sr) / sr
    song = 0.3 * np.sin(2 * np.pi * 110 * tt) * (0.6 + 0.4 * np.sin(2 * np.pi * 2.3 * tt))
    sf.write(tmp / "song.wav", np.stack([song, song], 1).astype(np.float32), sr)
    cfg = dict(name="iv", clips={"A": str(tmp / "A.mp4")}, transkript=str(reel / "schnitt" / "transkript"),
               song=dict(datei=str(tmp / "song.wav"), start=0.0, unter_sprache=13, in_pausen=6, fade_ende=1.0),
               abspann=dict(mitte=0.44, mindestens=2.6, blende=0.6, zeilen=[
                   dict(text="MEINE.MARKE", breite=640, start=0.55),
                   dict(text="EIN SEHR LANGER EVENTNAME FUER DEN TEST", breite=1000, abstand=66, start=0.9),
                   dict(text="MEIN ORT", cap=64, abstand=52, start=1.4),
                   dict(text="LINK IN BIO", cap=42, spur=0.18, abstand=92, start=1.9)]),
               kopf_nach=1.0, ersetzen={},
               teile=[dict(clip="A", von=0.5, bis=4.6), dict(clip="A", von=5.2, bis=9.0)])
    (reel / "schnitt" / "schnitt.json").write_text(json.dumps(cfg))
    env = dict(os.environ, REEL_WORK=str(work), PYTHONDONTWRITEBYTECODE="1")
    js = reel / "schnitt" / "schnitt.json"
    # Instagram (Standard)
    out = sh("python3", PIPE / "interview.py", js, "--export", env=env, ok=(0, 1))
    for f in ("iv_mit_song.mp4", "iv_ohne_song.mp4", "iv_titelbild.jpg"):
        assert (reel / f).exists(), f + "\n" + out[-800:]
    assert not list(reel.glob("iv_yt_*")), list(reel.glob("*"))
    assert (work / "interview" / "abspann.mp4").exists() and not (work / "interview" / "abspann_yt.mp4").exists()
    assert "Länge Bild" in out and "PRÜFEN  Länge" in out, out[-800:]      # 10 s statt 40–60 s: gewollt
    print("OK   interview.py Standard: Instagram-Dateien, Link-Zeile im Abspann")
    # YouTube
    out = sh("python3", PIPE / "interview.py", js, "--export", "--plattform", "youtube", env=env, ok=(0, 1))
    for f in ("iv_yt_mit_song.mp4", "iv_yt_ohne_song.mp4", "iv_yt_titelbild.jpg"):
        assert (reel / f).exists(), f + "\n" + out[-800:]
    assert (work / "interview" / "abspann_yt.mp4").exists() and (work / "interview" / "untertitel_yt.ass").exists()
    for f in ("iv_yt_mit_song.mp4", "iv_yt_ohne_song.mp4"):
        c = sh("python3", PIPE / "plattform.py", "check", reel / f, "--plattform", "youtube")
        assert "FEHLER" not in c and re.search(r"Lautheit -1[34]\.\d LUFS", c), c
    print("OK   interview.py --plattform youtube: …_yt_-Dateien, ohne Link-Zeile, YouTube-Profil geprüft (−14 LUFS)")
    import interview
    import plattform
    texte = lambda a: [z.get("text") for z in a["zeilen"]]
    assert "LINK IN BIO" in texte(interview.abspann_fuer(cfg["abspann"], plattform.profil("instagram")))
    assert "LINK IN BIO" not in texte(interview.abspann_fuer(cfg["abspann"], plattform.profil("youtube")))
    assert len(cfg["abspann"]["zeilen"]) == 4, "abspann_fuer darf die Konfiguration nicht verändern"
    # Abspann-Breite: Instagram 1000 px, YouTube höchstens 77 % von 1080 = 831 px
    for pfad, mb, soll in (("a_ig.mp4", None, 1000), ("a_yt.mp4", 0.77, 831)):
        interview.abspann_rendern(cfg["abspann"], 5.0, tmp / pfad, mb)
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", "3.0", "-i", str(tmp / pfad), "-frames:v", "1", "-f", "rawvideo",
                            "-pix_fmt", "gray", "-"], capture_output=True)
        f = np.frombuffer(r.stdout, np.uint8).reshape(1920, 1080)
        spalten = np.nonzero((f > 128).any(axis=0))[0]
        breit = spalten.max() - spalten.min()
        assert abs(breit - soll) <= 30, (pfad, breit, soll)
    print("OK   abspann_rendern: Instagram 1000 px, YouTube auf 77 % der Breite verkleinert")
    from untertitel import ass
    ws2 = [dict(w=w["w"], s=w["s"], e=w["e"]) for w in ws]
    ass(ws2, tmp / "s84.ass", ende=12.0)
    ass(ws2, tmp / "s77.ass", ende=12.0, max_breite=0.77)
    a, b = (tmp / "s84.ass").read_text(), (tmp / "s77.ass").read_text()
    assert a != b and a.count("Dialogue") <= b.count("Dialogue"), "schmalere Untertitel müssen anders umbrechen"
    print("OK   untertitel.ass: max_breite 0,77 bricht enger um als der Standard 0,84")
    print("test_interview: alles OK", tmp)


if __name__ == "__main__":
    main()
