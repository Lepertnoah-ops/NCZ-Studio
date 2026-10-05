#!/usr/bin/env python3
"""Schnelltest der Reel-Studio-Umgebung (~30 s). Aufruf: python3 selftest.py

Prüft die komplette Kette aus den Projektanweisungen im Kleinen:
Look aus stil.json als LUT backen, OpenCV -> ffmpeg-Pipe (Master, lut3d tetraedrisch, yuv444p crf 1),
Instagram-Export in 2 Pässen, HDR-Tonemapping (HLG), Song-Decode trotz Cover-Bild,
librosa-Beat-Analyse, Mix mit SFX-Kit (reel_audio.py), Mux und Pegelprüfung.
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

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True                   # kein __pycache__ im geteilten Projektordner,
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"      # auch nicht in den Unterprozessen (Analyse-Test)
W, H, FPS, DUR = 1080, 1920, 30, 3.0


def sh(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def ok(msg):
    print(f"OK   {msg}")


def main():
    import librosa
    import reel_audio as ra

    d = Path(tempfile.mkdtemp(prefix="reel_selftest_"))
    os.chdir(d)  # librosa/numba braucht ein gültiges Arbeitsverzeichnis; im Projektordner (FUSE) kann getcwd kurz ausfallen
    try:
        v = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        ok(f"{v.split(' Copyright')[0]}, OpenCV {cv2.__version__}, librosa {librosa.__version__}, "
           f"rubberband {'da' if shutil.which('rubberband') else 'FEHLT'}")

        # Syntax aller Werkzeuge: im geteilten Projektordner fällt ein halb gespeicherter Edit sonst erst im langen Lauf auf
        import ast
        skripte, kaputt = sorted(Path(__file__).resolve().parent.rglob("*.py")), []
        for f in skripte:
            try:
                ast.parse(f.read_text(), str(f))
            except SyntaxError as e:
                kaputt.append(f"{f.name} Zeile {e.lineno}: {e.msg}")
        assert not kaputt, "Syntaxfehler in " + "; ".join(kaputt)
        ok(f"Syntax aller {len(skripte)} Werkzeug-Skripte")

        sys.path.insert(0, str(TOOLS / "vfx"))
        import looks
        import stil
        spec = stil.STIL["look"] or "clean"
        shutil.copy(looks.lut_path(spec), d / "look.cube")
        rnd = np.random.default_rng(1).random((32, 32, 3)).astype(np.float32)
        diff = np.abs(looks.apply_cube(rnd, looks.read_cube(d / "look.cube")) - looks.apply_rgb(rnd, spec)).max()
        assert diff < 0.02, f"LUT und Look weichen ab ({diff:.3f})"
        ok(f"Look aus stil.json: {stil.look_name(spec)}, LUT 33³ passt zur Formel (max. {diff:.4f})")

        # OpenCV-Frames (Verlauf + bewegter Kreis, Lanczos-Zoom) per Pipe an ffmpeg -> Master
        master = d / "master.mp4"
        p = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
             "-r", str(FPS), "-i", "-", "-vf",
             f"lut3d={d / 'look.cube'}:interp=tetrahedral,scale=out_color_matrix=bt709:out_range=tv,format=yuv444p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "1", str(master)], stdin=subprocess.PIPE)
        gx, gy = np.meshgrid(np.linspace(40, 220, 1440), np.linspace(30, 200, 2560))
        base = np.dstack([gx, gy, np.full_like(gx, 120)]).astype(np.uint8)
        for i in range(int(DUR * FPS)):
            f = base.copy()
            cv2.circle(f, (200 + i * 12, 1280), 160, (40, 90, 230), -1)
            z = 1 + 0.14 * np.exp(-(i % 30) / FPS / 0.09)                      # Punch-in-Rezept
            M = cv2.getRotationMatrix2D((720, 1280), 0, z)
            f = cv2.warpAffine(f, M, (1440, 2560), flags=cv2.INTER_LANCZOS4)
            p.stdin.write(cv2.resize(f, (W, H), interpolation=cv2.INTER_AREA).tobytes())
        p.stdin.close()
        assert p.wait() == 0
        ok("OpenCV -> ffmpeg Master (lut3d, yuv444p, crf 1)")

        # Instagram-Export, 2 Pässe (Abschnitt 2, Punkt 15)
        ig = d / "ig.mp4"
        common = ["-vf", "unsharp=5:5:0.4:5:5:0,scale=flags=lanczos+accurate_rnd+full_chroma_int:"
                         "out_color_matrix=bt709:out_range=tv,format=yuv420p",
                  "-c:v", "libx264", "-preset", "slow", "-tune", "film", "-profile:v", "high", "-level", "4.1",
                  "-b:v", "18M", "-maxrate", "25M", "-bufsize", "50M", "-g", "60", "-bf", "3",
                  "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                  "-passlogfile", str(d / "x264")]
        sh("ffmpeg", "-v", "error", "-y", "-i", str(master), *common, "-pass", "1", "-an", "-f", "null", "-")
        sh("ffmpeg", "-v", "error", "-y", "-i", str(master), *common, "-pass", "2", "-an", "-movflags", "+faststart", str(ig))
        ok("Instagram-Export 2-Pass (18 Mbit/s, bt709)")

        # HDR: HLG-10-bit-Testclip erzeugen und tonemappen
        hlg = d / "hlg.mov"
        sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=1:r=30", "-pix_fmt", "yuv420p10le",
           "-c:v", "libx265", "-x265-params", "log-level=error", "-color_primaries", "bt2020", "-color_trc", "arib-std-b67",
           "-colorspace", "bt2020nc", str(hlg))
        tm = ("zscale=tin=arib-std-b67:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=100,format=gbrpf32le,"
              "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
        sh("ffmpeg", "-v", "error", "-y", "-i", str(hlg), "-vf", tm, "-frames:v", "5", str(d / "tm_%02d.jpg"))
        ok("HDR-Tonemapping (HLG -> bt709) mit zscale")

        # Song mit Cover-Bild, Beat-Analyse, Mix mit SFX, Mux
        sr, bpm = 48000, 120
        t = np.arange(int(8 * sr)) / sr
        song = np.zeros_like(t)
        for k in range(int(8 * bpm / 60)):
            a = int(k * 60 / bpm * sr)
            tt = t[: int(0.3 * sr)]
            seg = np.sin(2 * np.pi * np.cumsum(45 + 120 * np.exp(-tt / 0.03)) / sr) * np.exp(-tt / 0.15)
            song[a:a + len(seg)] += seg[: len(song) - a]
        song = 0.8 * np.tanh(song + 0.1 * np.sin(2 * np.pi * 220 * t))
        import soundfile as sf
        sf.write(d / "s.wav", np.stack([song, song], 1), sr)
        sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=300x300", "-frames:v", "1", str(d / "c.jpg"))
        sh("ffmpeg", "-v", "error", "-y", "-i", str(d / "s.wav"), "-i", str(d / "c.jpg"), "-map", "0:a", "-map", "1:v",
           "-c:a", "libmp3lame", "-b:a", "320k", "-c:v", "mjpeg", "-disposition:v", "attached_pic", str(d / "song.mp3"))
        y = ra.decode(d / "song.mp3").mean(1).astype(np.float32)
        _, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        i = np.arange(len(beats))
        per, ph = np.polyfit(i, beats, 1)
        ok(f"Song mit Cover dekodiert, Beat-Regression {60 / per:.2f} BPM (Soll 120 oder 60)")

        spec = {"duration": DUR, "music": [{"file": "song.mp3", "src": 2.0, "at": 0, "dur": DUR,
                                            "fade_in": 0.004, "fade_out": 0.038}],
                "sfx": [{"file": "sfx/whoosh.wav", "at": 1.0, "align": "peak", "gain_db": -10},
                        {"file": "sfx/punch.wav", "at": 1.5, "gain_db": -8, "duck_db": 3}]}
        (d / "spec.json").write_text(json.dumps(spec))
        mix, report = ra.mix(spec, d)
        sf.write(d / "mix.wav", mix.astype(np.float32), sr, subtype="FLOAT")
        ra.mux(str(ig), str(d / "mix.wav"), str(d / "reel.mp4"))
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                           "stream=codec_name,width,height,r_frame_rate,duration",
                                           "-of", "json", str(d / "reel.mp4")], capture_output=True, text=True).stdout)
        s = {x["codec_name"]: x for x in probe["streams"]}
        assert s["h264"]["width"] == W and s["h264"]["height"] == H and s["h264"]["r_frame_rate"] == "30/1"
        assert abs(float(s["aac"]["duration"]) - DUR) < 0.05
        db = ra.blocks_db(ra.decode(d / "reel.mp4"))
        assert (db[:-1] > -50).all(), "stumme Stelle in der Tonspur"
        ok(f"Mix + Mux: 1080x1920 @30 fps, AAC {float(s['aac']['duration']):.2f} s, keine stummen Blöcke; {report[-1]}")

        # Analyse-Werkzeuge (analyse/selftest_analyse.py): Song, Shotliste, Clip, Reel-Prüfung
        r = subprocess.run([sys.executable, str(TOOLS / "analyse" / "selftest_analyse.py")], capture_output=True, text=True)
        print(r.stdout.rstrip())
        assert r.returncode == 0, "Analyse-Test fehlgeschlagen:\n" + r.stderr[-1500:]

        # VFX-Bibliothek (vfx/): alle Looks backbar, kleine Spec mit Punch, Übergang, Grain, Titel
        import reelvfx as rv
        rv.CACHE = d / "vfx_cache"
        for name in looks.LOOKS:
            assert np.isfinite(looks.apply_rgb(rnd, name)).all(), name
        vspec = {"video": str(master), "cuts": [1.5], "per": 0.5, "lut": None,
                 "fx": [{"fx": "punch", "beat": 1}, {"fx": "crossfade", "beat": 3}, {"fx": "grain"},
                        {"fx": "title", "text": "TEST", "beat": 4, "beats": 1}]}
        eng = rv.render(vspec, d / "vfx.mp4", d, quiet=True, procs=2)
        n = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=nb_read_frames",
                                "-of", "csv=p=0", str(d / "vfx.mp4")], capture_output=True, text=True).stdout.strip())
        assert n == eng.n == int(DUR * FPS), f"{n} Frames statt {int(DUR * FPS)}"
        f0 = rv.Engine(dict(vspec, fx=[]), d).render_frame(15)
        assert np.abs(f0.astype(int) - eng.render_frame(15).astype(int)).mean() > 1, "Punch ohne Wirkung"
        ok(f"VFX-Bibliothek: {len(rv.FX)} Effekte, {len(looks.LOOKS)} Looks, Render mit Punch/Übergang/Grain/Titel")

        # SFX-Kit: alle Dateien aus sfx/README.md vorhanden, 48 kHz Stereo
        import re
        import soundfile as sf
        sfx_dir = TOOLS.parent / "sfx"
        names = re.findall(r"^\| (\w+\.wav) \|", (sfx_dir / "README.md").read_text(), re.M)
        for nm in names:
            info = sf.info(sfx_dir / nm)
            assert info.samplerate == 48000 and info.channels == 2, nm
        assert len(names) >= 28, f"nur {len(names)} SFX im README"
        ok(f"SFX-Kit: {len(names)} Soundeffekte vorhanden, alle 48 kHz Stereo")
        print("\nAlles bereit.")
        if not (stil.STIL["eingerichtet"] and stil.STIL["marke"]):
            print("Hinweis: Stil noch nicht eingerichtet (python3 tools/stil.py), vor dem ersten Reel "
                  "Stil-Leitfaden.md, Abschnitt „Stil festlegen“.")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main()
