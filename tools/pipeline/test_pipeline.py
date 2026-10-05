#!/usr/bin/env python3
"""Ende-zu-Ende-Test der Pipeline mit synthetischen Clips (~6 min, braucht kein Drive).

    python3 <projekt>/tools/pipeline/test_pipeline.py

Baut 5 Testclips (HLG 1080p 30 fps, 1440×2560 60 fps, Querformat 1920×1080 30 fps, zwei Hochkant-Clips; drei
davon mit Ton), ein iPhone-Foto (HEIC mit EXIF-Zeit) und einen 140-BPM-Song mit 808-Hits, dann: ingest -> extract ->
render master -> storyboard (Keyframes + Render) -> reel_audio mix -> export -> vorschau -> verify, danach
varianten.py mit zwei kurzen Varianten (Bauen, Unterschied-Check, Wahl mit Export und Aufräumen) und zuletzt die
Stil-Leitfaden mit der echten Vorlage reels/_vorlage/schnitt/edl.py: Einstieg im Video, Szene mit
Jump Cut, Überblendung, O-Ton leise und als Moment, Ausklang (tonspur.py, edlcheck.py, reel_audio music_fx/oton,
render.py ueber, verify.py). Deckt die Modi normal, ramp, split (mit Öffnung), speed 0,5×, das Foto als Standbild
mit Push-in und die Effekte push, punch, Mini-Punch, shake, flash ab. Die Wahl läuft mit --plattform instagram,youtube und prüft beide Fassungen (verify.py, YouTube
−14 LUFS). Weitere Tests: test_plattform.py, test_drive.py, test_interview.py.
Arbeitet in einem Temp-Ordner, fasst nichts im Projekt an.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

PIPE = Path(__file__).resolve().parent
PER = 60 / 140


def sh(*cmd, env=None):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env)
    if r.returncode:
        sys.exit(f"FEHLER {' '.join(map(str, cmd[:3]))}…\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r.stdout


def make_clip(path, w, h, fps, dur, extra=(), ton=False):
    """Testbild; ton=True: Stereo-Ton wie Stimmen (330/520 Hz, im Silbentakt moduliert, nichts unter 120 Hz)."""
    a = ["-f", "lavfi", "-i", f"aevalsrc='0.2*sin(2*PI*330*t)*(0.5+0.5*sin(2*PI*4*t))|0.2*sin(2*PI*520*t)"
                              f"*(0.5+0.5*sin(2*PI*3*t))':s=48000:d={dur}", "-c:a", "aac", "-shortest"] if ton else []
    sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps}:duration={dur}", *a,
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", *extra, path)


def make_photo(path):
    """HEIC wie vom iPhone (3:4 hochkant, EXIF-Aufnahmezeit), mit Struktur, damit der Push-in messbar ist."""
    import pillow_heif
    from PIL import Image
    pillow_heif.register_heif_opener()
    yy, xx = np.mgrid[0:1600, 0:1200]
    a = np.stack([(xx // 40 + yy // 40) % 2 * 160 + 40, xx * 200 // 1200 + 30, yy * 200 // 1600 + 30], -1)
    ex = Image.Exif()
    ex[306] = "2026:09:20 13:42:25"
    Image.fromarray(a.astype(np.uint8)).save(path, exif=ex.tobytes(), quality=90)


def make_song(path, dur, hits):
    sr = 48000
    t = np.arange(int(dur * sr)) / sr
    x = np.zeros_like(t)
    for b in np.arange(0, dur / PER):                      # Hi-Hat auf jedem Beat
        i = int(b * PER * sr)
        n = min(len(t) - i, 2000)
        x[i:i + n] += 0.05 * np.random.default_rng(int(b)).standard_normal(n) * np.exp(-np.arange(n) / 300)
    for hb in hits:                                        # 808: 50 Hz, abklingend, 12 ms Phase wie ein echter Song
        i = int((hb * PER + 0.012) * sr)
        tt = np.arange(len(t) - i) / sr
        x[i:] += 0.6 * np.sin(2 * np.pi * 50 * tt) * np.exp(-tt / 0.25)
    sf.write(path, np.stack([x, x], 1).astype(np.float32), sr)


def main():
    t0 = time.time()
    work = Path(tempfile.mkdtemp(prefix="reeltest_"))
    clips = work / "clips"
    clips.mkdir()
    make_clip(clips / "IMG_0001.MOV", 1080, 1920, 30, 5,
              ["-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc"], ton=True)
    make_clip(clips / "IMG_0002.MOV", 1440, 2560, 60, 6)
    make_clip(clips / "IMG_0003.MOV", 1920, 1080, 30, 5, ton=True)
    make_clip(clips / "IMG_0005.MOV", 1080, 1920, 30, 4, ton=True)
    make_clip(clips / "IMG_0006.MOV", 1080, 1920, 30, 4, ton=True)
    sys.path.insert(0, str(PIPE))
    sys.dont_write_bytecode = True                          # kein __pycache__ im geteilten Projektordner
    from reelcfg import _heif_opener
    _heif_opener()                                          # pillow-heif, sonst einmal nachinstallieren
    make_photo(clips / "IMG_0004.HEIC")
    (work / "manifest.tsv").write_text("".join(
        f"local:{p}\t{p.name}\t{p.stat().st_size}\n" for p in sorted(clips.glob("IMG_*"))))
    shots = [
        dict(beats=4, sec="EINSTIEG", clip="0001", src=0.2, mode="normal", fx=["Push-in", "Punch-in", "Flash"],
             desc="HLG-Clip mit Push-in", fxp=dict(push=[1.0, 1.06], punch=[[0, .14], [2, .06, 0]], flash=[[0, .55]])),
        dict(beats=4, sec="AUFBAU", clip="0002", src=0.5, mode="ramp", fx=["Speed-Ramp"], desc="60 fps Ramp",
             fxp=dict(punch=[[2, .126]])),
        dict(beats=4, sec="AUFBAU", clip="split", src=None, mode="split", fx=["Split-Screen"], desc="3er-Split",
             fxp=dict(expand=2.5), strips=[dict(clip="0003", src=0.3, y=0.5, zoom=1.0),
                                           dict(clip="0002", src=3.2, y=0.4, zoom=1.1),
                                           dict(clip="0001", src=3.0, y=0.5, zoom=1.2)]),
        dict(beats=4, sec="AUFBAU", clip="0004", src=0.0, mode="normal", fx=["Push-in"], desc="Foto mit Push-in",
             fxp=dict(push=[1.0, 1.08])),
        dict(beats=4, sec="FINALE", clip="0003", src=2.0, mode="speed", speed=0.5, fx=["Zeitlupe", "Shake"],
             desc="Querformat, 0,5× und Shake", fxp=dict(push=[1.0, 1.12], shake=[[0, 18, .6]])),
    ]
    b = 0
    for i, s in enumerate(shots):
        s.update(n=i + 1, beat=b, t=b * PER, prev=s["src"] if s["src"] is not None else 0)
        b += s["beats"]
    hits = [0, 2, 4, 6, 8, 12]
    E = dict(titel="Pipeline-Test", song="Testsong 140 BPM", per=PER, beats=b, hits=hits, shots=shots)
    (work / "edl.json").write_text(json.dumps(E, ensure_ascii=False))
    env = dict(os.environ, REEL_WORK=str(work), REEL_EDL=str(work / "edl.json"), PYTHONPATH=str(PIPE))
    py = sys.executable
    out = sh(py, PIPE / "ingest.py", "--keep", env=env)
    assert "QUERFORMAT 1 Clip(s): IMG_0003" in out and "FEHLT" not in out, out   # nur der Querformat-Testclip wird gemeldet
    metas = sorted((work / "meta").glob("*.json"))
    m1 = json.load(open(work / "meta" / "IMG_0001.json"))
    m4 = json.load(open(work / "meta" / "IMG_0004.json"))
    assert len(metas) == 6 and m1["trc"] == "arib-std-b67" and m1["kf_times"], "ingest"
    assert m4.get("photo") and (m4["w"], m4["h"]) == (1200, 1600) and m4["ctime"] == "2026-09-20T13:42:25", m4
    ton = sorted(p.stem for p in (work / "audio").glob("*.flac"))
    assert ton == ["IMG_0001", "IMG_0003", "IMG_0005", "IMG_0006"] and m1["ton"], ton
    print(f"OK   ingest: 5 Clips + HEIC-Foto, HLG erkannt, Keyframes, Aufnahmezeit, Ton je Clip, Querformat gemeldet ({time.time() - t0:.0f} s)")
    out = sh(py, PIPE / "extract.py", env=env)
    warn = [z for z in out.splitlines() if "WARNUNG" in z]
    assert len(warn) == 1 and warn[0].startswith("0003:") and "Querformat 1920×1080" in warn[0], out   # nur der Querformat-Clip
    assert len(list((work / "frames").glob("*/times.json"))) == 4, out
    w2 = json.load(open(work / "frames" / "0002" / "times.json"))["w"]
    assert w2 == 1440, w2
    print(f"OK   extract: Frames je Clip vollständig, 1440er-Quelle erkannt, Foto, Querformat gewarnt ({time.time() - t0:.0f} s)")
    master = work / "test_master.mp4"
    sh(py, PIPE / "render.py", "master", master, env=env)
    n = int(sh("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
               "stream=nb_read_frames", "-of", "csv=p=0", master).strip())
    assert n == round(b * PER * 30), n
    print(f"OK   render: Master {n} Frames, 1080×1920 ({time.time() - t0:.0f} s)")
    sh(py, PIPE / "storyboard.py", work / "sb_kf.jpg", env=env)
    sh(py, PIPE / "storyboard.py", work / "sb_render.jpg", "--render", env=env)
    print(f"OK   storyboard: Keyframe- und Render-Variante ({time.time() - t0:.0f} s)")
    make_song(work / "song.wav", b * PER + 2, hits + [b])
    spec = dict(duration=b * PER, music=[dict(file="song.wav", src=0.0, at=0.0, dur=b * PER, fade_in=0.004,
                                              fade_out=0.038)], sfx=[], match_loudness=False, ceiling_db=-0.3)
    (work / "spec.json").write_text(json.dumps(spec))
    ra = PIPE.parent / "reel_audio.py"
    sh(py, ra, "mix", work / "spec.json", work / "mix.wav")
    sh(py, PIPE / "export.py", master, work / "out" / "test", work / "mix.wav", "--titel", "10", env=env)
    for f in ("test_ohne_ton.mp4", "test_mit_song.mp4", "test_titelbild.jpg"):
        assert (work / "out" / f).exists(), f
    print(f"OK   export: Instagram 2-Pass, Ton, Titelbild ({time.time() - t0:.0f} s)")
    vor = work / "out" / "test_vorschau.mp4"
    sh(py, PIPE / "vorschau.py", master, vor, work / "mix.wav", "--loop", "4", env=env)
    pr = json.loads(sh("ffprobe", "-v", "error", "-count_frames", "-show_entries",
                       "stream=codec_type,width,height,nb_read_frames", "-of", "json", vor))["streams"]
    v = next(s for s in pr if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (720, 1520) and int(v["nb_read_frames"]) == n + round(4 * PER * 30), v
    assert any(s["codec_type"] == "audio" for s in pr), pr
    print(f"OK   vorschau: 720×1520 mit Info-Leiste, Loop, Ton ({time.time() - t0:.0f} s)")
    r = subprocess.run([py, PIPE / "verify.py", work / "out" / "test_mit_song.mp4"], capture_output=True, text=True,
                       env=env)
    print("\n".join("     " + ln for ln in r.stdout.strip().splitlines()))
    lines = r.stdout
    assert "Schnitte 4/4 sauber" in lines and "808 gegen Bild" in lines, lines + r.stderr
    frozen_ok = "OK      eingefrorene" in lines or "in Shot [5]" in lines   # 0,5× aus 30 fps doppelt Frames (gewollt)
    assert frozen_ok, lines
    print(f"OK   verify: Schnitte, 808-Versatz, Ende, Pegel ({time.time() - t0:.0f} s)")
    varianten_test(work, env, t0)
    stil4_test(work, env, t0)
    print(f"Pipeline-Test grün in {time.time() - t0:.0f} s. Dateien: {work}")


def varianten_test(work, env, t0):
    """Zwei kurze Varianten (je 8 Beats) in einem Test-Reel-Ordner: bauen, vergleichen, wählen."""
    reel = work / "reels" / "2026-01-01_test"
    defs = {"A": (0, [("0001", 0.2, "normal", {"push": [1.0, 1.06], "punch": [[0, .14]]}, ["Push-in", "Punch-in"]),
                      ("0004", 0.0, "normal", {"push": [1.0, 1.08]}, ["Push-in"])]),
            "B": (8, [("0002", 0.5, "ramp", {"punch": [[2, .126]]}, ["Speed-Ramp"]),
                      ("0003", 2.0, "speed", {"push": [1.0, 1.12]}, ["Zeitlupe", "Push-in"])])}
    for x, (start, shots) in defs.items():
        d = reel / "schnitt" / x
        d.mkdir(parents=True)
        S = [dict(n=i + 1, beat=4 * i, t=4 * i * PER, beats=4, sec="TEST", clip=c, src=src, mode=m, fx=tags, fxp=fxp,
                  desc=f"Variante {x}, Shot {i + 1}", prev=src, **({"speed": 0.5} if m == "speed" else {}))
             for i, (c, src, m, fxp, tags) in enumerate(shots)]
        E = dict(titel="Test", untertitel=f"Variante {x}", song="Testsong", per=PER, hook=start * PER, beats=8,
                 hits=[h - start for h in (0, 2, 4, 6, 8, 12) if 0 <= h - start < 8], shots=S, variante=x,
                 variante_name={"A": "Story", "B": "Power"}[x], hinweis=f"Testvariante {x}")
        (d / "edl.json").write_text(json.dumps(E, ensure_ascii=False))
        (d / "fx.json").write_text(json.dumps({str(s_["n"]): s_["fxp"] for s_ in S}))
        (d / "audio_spec.json").write_text(json.dumps(dict(
            duration=8 * PER, music=[dict(file=str(work / "song.wav"), src=start * PER, at=0.0, dur=8 * PER,
                                          fade_in=0.004, fade_out=0.038)], sfx=[], match_loudness=False,
            ceiling_db=-0.3)))
    py = sys.executable
    out = sh(py, PIPE / "varianten.py", reel, "--loop", "4", env=env)
    for f in ("test_A_vorschau.mp4", "test_A_storyboard.jpg", "test_B_vorschau.mp4", "test_B_storyboard.jpg"):
        assert (reel / f).exists(), f + "\n" + out
    assert "A/B: Song anders, Clips 0 gemeinsam" in out and "nur 2 Variante(n)" in out, out
    print(f"OK   varianten: 2 Varianten gebaut, Unterschied-Check ({time.time() - t0:.0f} s)")
    r = subprocess.run([py, PIPE / "varianten.py", reel, "--wahl", "A", "--titel", "5"], capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0 and "alles OK" in r.stdout, r.stdout + r.stderr
    for f in ("test_mit_song.mp4", "test_ohne_ton.mp4", "test_titelbild.jpg", "test_storyboard.jpg",
              "archiv/varianten/test_B_vorschau.mp4"):
        assert (reel / f).exists(), f
    assert not list(reel.glob("test_[AB]_*")), list(reel.glob("*"))
    print(f"OK   varianten --wahl A: Export, Prüfung alles OK, Varianten im Archiv ({time.time() - t0:.0f} s)")
    r = subprocess.run([py, PIPE / "varianten.py", reel, "--wahl", "A", "--fassung", "v2"], capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0 and (reel / "test_v2_mit_song.mp4").exists(), r.stdout + r.stderr
    print(f"OK   varianten --wahl A --fassung v2: Folgefassung als test_v2_… ({time.time() - t0:.0f} s)")
    r = subprocess.run([py, PIPE / "varianten.py", reel, "--wahl", "A", "--fassung", "v3", "--plattform",
                        "instagram,youtube"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.count("Ergebnis: alles OK") == 2, r.stdout + r.stderr
    for f in ("test_v3_mit_song.mp4", "test_v3_yt_mit_song.mp4", "test_v3_yt_ohne_ton.mp4", "test_v3_yt_titelbild.jpg"):
        assert (reel / f).exists(), f
    c = subprocess.run([py, PIPE / "plattform.py", "check", reel / "test_v3_yt_mit_song.mp4", "--streng"],
                       capture_output=True, text=True)
    import re
    lu = re.search(r"Lautheit (-?\d+\.\d) LUFS", c.stdout)
    assert c.returncode == 0 and lu and abs(float(lu.group(1)) + 14) <= 0.5, c.stdout + c.stderr
    print(f"OK   varianten --wahl A --plattform instagram,youtube: beide Dateisätze, YouTube {lu.group(1)} LUFS "
          f"({time.time() - t0:.0f} s)")


STIL4 = """# ---- pro Reel anpassen (Test Einstieg, Jump Cut, O-Ton) ----
TITEL, VARIANTE, VARIANTE_NAME, UNTERSCHIED = "stil4", "C", "Musikvideo", "Test Einstieg, Jump Cut, O-Ton"
UNTERTITEL = "Variante C · Musikvideo"
SONG, SONG_DATEI = "Testsong", "{song}"
START_TAKT, AUFTAKT, TAKTE, EINSTIEG, EINSTIEG_AUF, AUSKLANG, DECODER_VERSATZ = 1, 4, 4, 4, 0.03, 4, 0.0
EINSTIEG_SONG = "gedämpft"
HITS = [4, 8, 16]
K1, K4 = "EINSTIEG", "FINALE"
s(4, K1, "0005", 0.5, "normal", [], "Einstieg im Video: Leute reden", oton="vorn")
s(4, K1, "0002", 0.5, "speed", ["Zeitlupe", "Push-in", "Punch-in"], "Epic-Shot auf dem Drop",
  dict(push=[1.0, 1.06], punch=[[0, 0.14]]), speed=0.5)
s(2, K1, "0001", 0.2, "normal", [], "Seilspringen, Teil 1", oton="leise")
j(2, "0001", 2.6, "normal", [], "Seilspringen, Teil 2", oton="leise")
s(4, K4, "0003", 1.0, "normal", ["Push-in"], "Gruppe feuert an", dict(push=[1.0, 1.05]), oton="vorn", ueber="blende")
s(4, K4, "0004", 0.0, "speed", ["Push-in"], "Finale: Foto mit Push-in", dict(push=[1.0, 1.1]), speed=0.5)
s(4, K4, "0006", 0.5, "normal", [], "Ausklang: echter Ton", oton="vorn")
"""


def stil4_test(work, env, t0):
    """Echte Vorlage: Einstieg im Video, Jump Cut, Überblendung, O-Ton-Moment, Ausklang."""
    reel = work / "reels" / "2026-01-02_stil4"
    d = reel / "schnitt" / "C"
    d.mkdir(parents=True)
    (work / "tools").symlink_to(PIPE.parent)             # edl.py sucht tools/pipeline in den Elternordnern
    (reel / "schnitt" / "grid.json").write_text(json.dumps(dict(per=PER, ph=0.0, erste_eins=0.0)))
    vorlage = (PIPE.parent.parent / "reels" / "_vorlage" / "schnitt" / "edl.py").read_text()
    a = vorlage.index("# ---- pro Reel anpassen")
    b = vorlage.index("\n# ------", a) + 1
    (d / "edl.py").write_text(vorlage[:a] + STIL4.format(song=work / "song4.wav") + vorlage[b:])
    make_song(work / "song4.wav", 26 * PER, [4, 8, 16, 20])
    py = sys.executable
    out = sh(py, d / "edl.py", env=env)
    E, spec = json.load(open(d / "edl.json")), json.load(open(d / "audio_spec.json"))
    assert "7 Shots in 6 Szenen" in out and not any(k in out for k in ("Jump Cut Shot", "Überblendung", "O-Ton-Moment",
                                                                          "Drop auf", "Ausklang", "Opener", "Finale")), out
    assert E["shots"][3]["jump"] and E["shots"][3]["szene"] == E["shots"][2]["szene"], E["shots"][3]
    assert abs(spec["music"][0]["dur"] - 20 * PER) < 1e-3 and abs(spec["duration"] - 24 * PER) < 1e-3, spec["music"]
    fx = spec["music_fx"]
    assert len(fx) == 2 and fx[0]["to"] == round(4 * PER, 4) and fx[1]["from"] == round(12 * PER, 4), fx
    assert len(spec["oton"]) == 5 and spec["oton"][1]["fade_out"] == 0.03 and spec["oton"][2]["fade_out"] > 0.39, \
        spec["oton"]
    import edlcheck
    import tonspur
    E2 = dict(E, einstieg_song="aus")                    # Einstieg nur mit echtem Ton, Song ab dem Drop
    m2, fx2 = tonspur.audio_spec(E2, "song.wav", 1.0)["music"][0], tonspur.audio_spec(E2, "song.wav", 1.0)["music_fx"]
    assert m2["at"] == round(4 * PER, 4) and m2["src"] == round(1.0 + 4 * PER, 4) and abs(m2["dur"] - 16 * PER) < 1e-3 \
        and len(fx2) == 1 and fx2[0].get("moment"), (m2, fx2)
    assert not any("Einstieg" in x for x in edlcheck.pruefen(E2)), edlcheck.pruefen(E2)
    E3 = dict(E2, shots=[dict(E["shots"][0], oton=None)] + E["shots"][1:])
    assert any("stumm bis zum Drop" in x for x in edlcheck.pruefen(E3)), edlcheck.pruefen(E3)
    print(f"OK   Stil 4: Vorlage mit Einstieg (gedämpft und aus), Jump Cut, Blende, O-Ton, Ausklang -> edl/audio_spec, "
          f"Prüfung ohne Stil-Warnung ({time.time() - t0:.0f} s)")
    out = sh(py, PIPE / "varianten.py", reel, "--loop", "4", env=env)
    mix = (work / "mix_C.log").read_text()
    assert mix.count("O-Ton ") == 5 and "weggelassen" not in mix and "Musik 0.00-1.71 s" in mix, mix
    assert (reel / "stil4_C_vorschau.mp4").exists() and (reel / "stil4_C_storyboard.jpg").exists(), out
    import scipy.signal as ss
    x = __import__("reel_audio").decode(work / "mix_C.wav").mean(1)
    hi = ss.sosfiltfilt(ss.butter(4, 5000, btype="highpass", fs=48000, output="sos"), x)
    rms = lambda y, a_, b_: 20 * np.log10(np.sqrt(np.mean(y[int(a_ * PER * 48000):int(b_ * PER * 48000)] ** 2)) + 1e-9)
    ein, voll, aus = rms(hi, 0.5, 3.5), rms(hi, 4.5, 7.5), rms(hi, 20.5, 23.5)   # Hi-Hats über 5 kHz
    assert ein < voll - 10 and aus < voll - 30 and rms(x, 20.5, 23.5) > -40, (ein, voll, aus, rms(x, 20.5, 23.5))
    print(f"OK   Stil 4: gebaut; Höhen im Einstieg {ein - voll:.0f} dB unter dem Drop, Ausklang nur O-Ton "
          f"({time.time() - t0:.0f} s)")
    r = subprocess.run([py, PIPE / "varianten.py", reel, "--wahl", "C", "--titel", "20"], capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0 and "alles OK" in r.stdout and "1 Überblendung(en)" in r.stdout, r.stdout + r.stderr
    print(f"OK   Stil 4 --wahl C: verify mit Jump Cut, Überblendung, Einstieg und Ausklang alles OK "
          f"({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
