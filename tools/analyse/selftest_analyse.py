#!/usr/bin/env python3
"""Kleiner Test der Analyse-Werkzeuge (~25 s), wird von ../selftest.py aufgerufen.
Einzeln: python3 selftest_analyse.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import scipy.signal as ss
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def drill_beat(path, bars=16, bpm=140, off=0.25, sr=48000):
    """808 auf 1 + Nachschlag auf 2, Clap auf 3, Hats in Achteln; Takte 4–11 mit Melodie."""
    per = 60 / bpm
    n = int((off + bars * 4 * per + 1) * sr)
    y = np.zeros(n)
    rng = np.random.default_rng(1)

    def add(t, sig):
        a = int(t * sr)
        y[a:a + len(sig)] += sig[:max(0, n - a)]
    tt = np.arange(int(0.5 * sr)) / sr
    k808 = np.sin(2 * np.pi * np.cumsum(50 + 100 * np.exp(-tt / 0.02)) / sr) * np.exp(-tt / 0.25)
    tc = np.arange(int(0.15 * sr)) / sr
    clap = ss.sosfilt(ss.butter(4, [1200, 5000], btype="bandpass", fs=sr, output="sos"),
                      rng.standard_normal(len(tc))) * np.exp(-tc / 0.03) * 2
    th = np.arange(int(0.03 * sr)) / sr
    hat = ss.sosfilt(ss.butter(4, 7000, btype="highpass", fs=sr, output="sos"),
                     rng.standard_normal(len(th))) * np.exp(-th / 0.008) * 0.3
    for b in range(bars):
        t0 = off + b * 4 * per
        add(t0, 0.9 * k808)
        add(t0 + per, 0.5 * k808)
        add(t0 + 2 * per, clap)
        for h in range(8):
            add(t0 + h * per / 2, hat)
        if 4 <= b < 12:
            tm = np.arange(int(4 * per * sr)) / sr
            add(t0, 0.15 * np.sin(2 * np.pi * 440 * tm) * np.sin(np.pi * tm / (4 * per)))
    sf.write(path, np.stack([y, y], 1) * 0.5, sr)
    return off, per


def main():
    import song_analyse as sa
    import shotliste as sl
    d = Path(tempfile.mkdtemp(prefix="analyse_selftest_"))
    off, per = drill_beat(d / "drill.wav")
    A = sa.analyse(d / "drill.wav")
    assert abs(A["bpm"] - 140) < 0.3, A["bpm"]
    assert abs(A["erste_eins"] - off) < 0.015, A["erste_eins"]
    kinds = [o["art"] for o in A["onsets"]["kick808"]]
    assert kinds.count("808") >= 14 and kinds.count("808_nachschlag") >= 12, kinds
    assert len(A["onsets"]["clap"]) >= 12 and A["windows"], (len(A["onsets"]["clap"]), A["windows"])
    print(f"OK   song_analyse: {A['bpm']:.2f} BPM, erste Eins {A['erste_eins']:.3f} s (Soll {off}), "
          f"{kinds.count('808')}× 808, {kinds.count('808_nachschlag')}× Nachschlag, {len(A['onsets']['clap'])}× Clap")
    (d / "song.json").write_text(json.dumps(A))
    tags = {"1": {"kapitel": [1], "tags": ["opener", "gruppe", "branding"]}, "2": {"kapitel": [2], "tags": ["action"]},
            "3": {"kapitel": [3], "tags": ["schlag", "action"]}, "4": {"kapitel": [4], "tags": ["finale", "gruppe"]}}
    (d / "tags.json").write_text(json.dumps(tags))
    E = sl.build(A, sl.load_pool(None, d / "tags.json"), start_takt=0, auftakt=0)   # Länge nach Regel 2
    fin = E["shots"][-1]
    soll = 4
    while soll * 4 * per < sl.STIL["laenge_s"][0] - 0.01:
        soll += 4                                                                             # volle Phrasen bis laenge_s[0]
    assert E["takte"] == soll and abs(E["dauer"] - soll * 4 * per) < 0.01, (E["takte"], soll, E["dauer"])
    assert E["shots"][0]["speed"] == 0.75 and fin["beats"] == 8 and fin.get("speed", 1.0) == sl.TEMPO["finale"], (E["shots"][0], fin)
    assert all(s["beats"] >= 2 and s["mode"] in ("normal", "speed") for s in E["shots"])   # nie Ramp, nie Zeitraffer
    starts = [s["beat"] for i, s in enumerate(E["shots"]) if i and s["kapitel"] != E["shots"][i - 1]["kapitel"]]
    assert all(b % 16 == 0 for b in starts), starts                                          # Kapitel auf Phrasen
    print(f"OK   shotliste: {len(E['shots'])} Shots, 4 Kapitel, Finale {E['shots'][-1]['beats']} Beats")
    from clip_analyse import analyse_clip
    f = d / "t.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30:duration=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f)], check=True)
    c = analyse_clip(str(f), sample_fps=10)
    assert (c["w"], c["h"], c["hdr"]) == (540, 960, "sdr") and abs(c["dur"] - 3) < 0.1 and 25 <= len(c["series"]["t"]) <= 31
    assert 0 <= c["score"] <= 100 and c["highlights"] and c["stats"]["motion_mean"] > 0 and not c["scenes"]
    print(f"OK   clip_analyse: Score {c['score']:.0f}, Bewegung {c['stats']['motion_mean']:.0f} px/s, "
          f"{len(c['highlights'])} Highlights")
    from reel_qc import run_qc
    f = d / "reel.mp4"                                  # absichtlich falsches Format: 720x1280
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=4", "-f", "lavfi",
                    "-i", "sine=f=55:d=4:sample_rate=48000", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(f)], check=True)
    r = run_qc(str(f), outdir=str(d / "qc"), quiet=True)
    st = {c["check"]: c["status"] for c in r["checks"]}
    assert st["Auflösung"] == "FEHLER" and r["exit_code"] == 1 and (d / "qc" / "qc.md").exists(), st
    print(f"OK   reel_qc: {len(r['checks'])} Prüfungen, falsche Auflösung erkannt")
    import oton
    ref = np.load(oton.MODELL / "pruefung.npy")                # YAMNet in TensorFlow, 28.09.2026
    p = oton.hoeren(oton.pruefsignal())
    assert p.shape == ref.shape and np.abs(p - ref).max() < 1e-3, (p.shape, float(np.abs(p - ref).max()))
    a = d / "ton"
    a.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=3:sample_rate=48000",
                    str(a / "IMG_0001.flac")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=1", "-c:v",
                    "libx264", "-pix_fmt", "yuv420p", str(a / "IMG_0002.mp4")], check=True)
    r = subprocess.run([sys.executable, str(HERE / "oton.py"), str(a), "-o", str(d / "oton")], capture_output=True,
                       text=True)
    o = json.load(open(d / "oton" / "oton.json"))["clips"]
    assert r.returncode == 0 and [c["name"] for c in o] == ["IMG_0001", "IMG_0002"] and o[1].get("kein_ton") \
        and len(o[0]["zeit"]) == 6 and "IMG_0002 | kein Ton" in (d / "oton" / "oton.md").read_text(), r.stdout + r.stderr
    print(f"OK   oton: YAMNet wie TensorFlow (Abweichung {np.abs(p - ref).max():.0e}), oton.md/json, Clip ohne Ton erkannt")
    subprocess.run(["rm", "-rf", str(d)])


if __name__ == "__main__":
    main()
