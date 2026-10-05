#!/usr/bin/env python3
"""Lieferdateien aus dem Master: Instagram-Export in 2 Pässen (Projektanweisungen Punkt 15), Ton dazu, Titelbild.

    python3 export.py <master.mp4> <reel-ordner>/<name> [mix.wav] [--titel <frame>] [--plattform instagram,youtube]

Schreibt <name>_ohne_ton.mp4 (x264 high 4.1, 18/25 Mbit/s, unsharp leicht, bt709, faststart),
mit mix.wav zusätzlich <name>_mit_song.mp4 (Video per Stream-Copy, AAC 320k/48 kHz über reel_audio.mux)
und mit --titel <frame> <name>_titelbild.jpg (Frame aus dem Master, 1080×1920).
--plattform youtube (Profile in plattform.py): dieselben Dateien als <name>_yt_ohne_ton.mp4,
<name>_yt_mit_song.mp4 (Ton auf −14 LUFS, True Peak höchstens −1 dBTP, AAC 384k) und <name>_yt_titelbild.jpg;
danach prüft plattform.py die Dateien. Ohne --plattform bleibt alles wie bisher (Instagram).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
from reelcfg import FPS, run

VF = ("unsharp=5:5:0.4:5:5:0,scale=flags=lanczos+accurate_rnd+full_chroma_int:"
      "out_color_matrix=bt709:out_range=tv,format=yuv420p")
X264 = ["-c:v", "libx264", "-preset", "slow", "-tune", "film", "-profile:v", "high", "-level", "4.1",
        "-b:v", "18M", "-maxrate", "25M", "-bufsize", "50M", "-g", "60", "-bf", "3",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]


def instagram(master, out):
    with tempfile.TemporaryDirectory() as d:
        common = ["-vf", VF, *X264, "-passlogfile", f"{d}/x264"]
        for p, tail in (("1", ["-an", "-f", "null", "-"]), ("2", ["-an", "-movflags", "+faststart", str(out)])):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(master), *common, "-pass", p, *tail], check=True)


def main(args):
    import plattform as pf
    master, base = Path(args[0]), Path(args[1])
    mix = next((Path(a) for a in args[2:] if a.endswith(".wav")), None)
    profile = pf.plattformen(args[args.index("--plattform") + 1]) if "--plattform" in args else [pf.profil("instagram")]
    base.parent.mkdir(parents=True, exist_ok=True)
    ok = True
    for p in profile:
        stumm = base.parent / pf.dateiname(base.name, p, "ohne_ton.mp4")
        if p["kurz"] == "instagram":
            instagram(master, stumm)
        else:
            pf.video_export(master, stumm, p)
        print(stumm)
        if mix:
            import reel_audio as ra
            mit = base.parent / pf.dateiname(base.name, p, "mit_song.mp4")
            if p["kurz"] == "instagram":
                ra.mux(str(stumm), str(mix), str(mit))
            else:
                pf.mux(stumm, pf.ton_fuer(mix, p, ra), mit, p)
            ra.check(str(mit))
            print(mit)
        if "--titel" in args:
            i = int(args[args.index("--titel") + 1])
            jpg = base.parent / pf.dateiname(base.name, p, "titelbild.jpg")
            r = run(["ffmpeg", "-v", "error", "-y", "-i", master, "-vf", f"select=eq(n\\,{i}),"
                     "scale=out_color_matrix=bt709:out_range=pc", "-frames:v", "1", "-q:v", "2", jpg])
            assert r.returncode == 0, r.stderr
            print(jpg)
        if p["kurz"] != "instagram":
            ts = int(args[args.index("--titel") + 1]) / FPS if "--titel" in args else None
            dateien = [stumm] + ([mit] if mix else [])
            for datei in dateien:
                print(f"{datei.name} gegen {p['name']}")
                ok = pf.ausgeben(pf.pruefen(datei, p, ts if datei is dateien[-1] else None)) and ok
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
