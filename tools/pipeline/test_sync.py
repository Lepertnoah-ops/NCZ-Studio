#!/usr/bin/env python3
"""Test von sync.py ohne Drive und ohne echte Clips (~30 s), alles in einem temporären REEL_WORK.

    cd /tmp && python3 /mnt/project-files/tools/pipeline/test_sync.py

Künstlicher Ton: sprachähnliches moduliertes Rauschen (Formanten, Silben, Pausen) plus eine Musik-Schleife (Kick,
Hi-Hat, Arpeggio), die sich exakt wiederholt wie ein Box-Song. Daraus Clips mit bekannten Versätzen (auch negativ), sehr
verschiedener Lautstärke, weißem Rauschen, Tiefpass, etwas Raumhall und Uhrendrift (100 ppm). Erwartung: Offsets auf
+-5 ms (gemessen meist unter 1 ms), Drift erkannt, Zuordnung über eine Kette, ein Clip nur mit der Musik-Schleife wird
als mehrdeutig gemeldet statt falsch zugeordnet, ein Clip ohne gemeinsamen Ton bleibt ohne Offset. Dazu Kürzel-Suche,
Aufnahmezeit als Vorwissen, Video mit verschobenem Tonstart, Kommandozeile und Zeitleiste. Fasst nichts im Projekt an.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
TMP = Path(tempfile.mkdtemp(prefix="testsync_", dir="/tmp"))
os.environ["REEL_WORK"] = str(TMP)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import soundfile as sf
from scipy import ndimage, signal

import sync

SR = 48000            # die Clips liegen wie in audio/*.flac bei 48 kHz, der Test geht also durch die Umrechnung auf 16 kHz
TOL_MS = 5.0


# ---------------------------------------------------------------- künstlicher Ton

def sprache(dauer, seed):
    """Sprachähnlich: Grundton-Pulse und Rauschen durch Formantfilter, Silbenhüllkurve mit Phrasenpausen."""
    rng = np.random.default_rng(seed)
    n = int(dauer * SR) + SR
    grob = ndimage.gaussian_filter1d(rng.standard_normal(n // 480 + 2), 40)         # 100 Werte je Sekunde, dann glatt
    g = np.interp(np.arange(n) / 480, np.arange(len(grob)), grob)
    f0 = (110 + 40 * rng.random()) * (1 + 0.12 * g / g.std())          # Tonhöhe wandert zufällig, nie periodisch
    puls = (np.sin(2 * np.pi * np.cumsum(f0) / SR) > 0.6).astype(float)
    anreg = 0.6 * rng.standard_normal(n) + 1.5 * puls
    out = np.zeros(n)
    for fc, bw, g in ((500, 120, 1.0), (1500, 200, 0.6), (2500, 300, 0.35), (3800, 400, 0.15)):
        out += g * signal.sosfilt(signal.butter(2, [fc - bw, fc + bw], "bandpass", fs=SR, output="sos"), anreg)
    env = np.zeros(n)
    pos = 0.0
    while pos < dauer:
        phrase = rng.uniform(1.0, 3.0)
        s = pos
        while s < pos + phrase:
            d = rng.uniform(0.08, 0.22)
            c, sg = int((s + d / 2) * SR), d * SR / 2.5
            a, b = max(0, int(c - 4 * sg)), min(n, int(c + 4 * sg))
            if b > a:
                env[a:b] += rng.uniform(0.5, 1.0) * np.exp(-0.5 * ((np.arange(a, b) - c) / sg) ** 2)
            s += d + rng.uniform(0.0, 0.05)
        pos += phrase + rng.uniform(0.4, 1.4)
    out = out[:int(dauer * SR)] * env[:int(dauer * SR)]
    return out / np.sqrt(np.mean(out ** 2))


def schleife(laenge, dauer, seed=7):
    """Musik-Schleife der Länge 'laenge' s, bis 'dauer' s wiederholt (exakt gleiche Wiederholungen)."""
    rng = np.random.default_rng(seed)
    n = int(laenge * SR)
    x = np.zeros(n)
    beat = laenge / 4
    for b in range(4):
        i0 = int(b * beat * SR)
        tt = np.arange(n - i0) / SR
        x[i0:] += 1.2 * np.sin(2 * np.pi * (55 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9)
        i1 = i0 + int(beat / 2 * SR)
        if i1 < n:
            h = signal.sosfilt(signal.butter(2, 6000, "highpass", fs=SR, output="sos"), rng.standard_normal(n - i1))
            x[i1:] += 0.5 * h * np.exp(-np.arange(n - i1) / SR * 55)
    for k, f in enumerate([220.0, 277.2, 329.6, 440.0, 329.6, 277.2, 392.0, 246.9]):
        i0 = int(k * laenge / 8 * SR)
        tt = np.arange(n - i0) / SR
        x[i0:] += 0.5 * signal.sawtooth(2 * np.pi * f * tt) * np.exp(-tt * 6)
    x /= np.sqrt(np.mean(x ** 2))
    return np.tile(x, int(np.ceil(dauer * SR / n)))[:int(dauer * SR)]


def clip_aus(x, start, dauer, drift_ppm=0.0, gain_db=0.0, snr_db=None, tiefpass=None, hall=False, seed=0):
    """Clip aus der Quelle x: Quellzeit s = start + (1 + drift) * t_clip. Mit Tiefpass (Entfernung), Raumhall, weißem
    Rauschen (SNR zum Clip) und Lautstärke. Liefert float32 mono bei 48 kHz."""
    rng = np.random.default_rng(1000 + seed)           # eigener Strom, nie derselbe wie in der Quelle
    n = int(dauer * SR)
    s = start + (1 + drift_ppm * 1e-6) * np.arange(n) / SR
    y = ndimage.map_coordinates(x, [s * SR], order=3, mode="constant")
    if hall:
        ir = np.zeros(int(0.12 * SR))
        tt = np.arange(len(ir)) / SR
        ir += 0.03 * rng.standard_normal(len(ir)) * np.exp(-tt * 35) * (tt > 0.002)
        ir[0] = 1
        y = signal.fftconvolve(y, ir)[:n]
    if tiefpass:
        y = signal.sosfilt(signal.butter(4, tiefpass, "lowpass", fs=SR, output="sos"), y)
    if snr_db is not None:
        y = y + rng.standard_normal(n) * (np.sqrt(np.mean(y ** 2)) + 1e-9) * 10 ** (-snr_db / 20)
    return (y * 10 ** (gain_db / 20)).astype(np.float32)


def ablegen(name, y):
    """Als 48-kHz-Stereo-FLAC nach $REEL_WORK/audio/<name>.flac, wie ingest.py es ablegt."""
    (TMP / "audio").mkdir(exist_ok=True)
    y = np.clip(y / max(1.0, np.abs(y).max() / 0.9), -1, 1)
    sf.write(str(TMP / "audio" / f"{name}.flac"), np.stack([y, y], axis=1), SR, subtype="PCM_16")


def meta(name, ctime, fps=30.0):
    (TMP / "meta").mkdir(exist_ok=True)
    json.dump(dict(name=name + ".MOV", ctime=ctime, fps=fps, dur=1.0), open(TMP / "meta" / f"{name}.json", "w"))


def ok(text):
    print("OK  ", text, flush=True)


def fehl_ms(soll, ist):
    return abs(soll - ist) * 1000


def ppm(x):
    return f"{round(x):+d}"


# ---------------------------------------------------------------- Prüfung

def main():
    t0 = time.time()
    sp = sprache(96, 3)
    mu = schleife(2.0, 96) * 10 ** (-8 / 20)
    quelle = sp + mu                     # Sprache mit Musik im Hintergrund

    # Quellzeit 10 bis 70 s ist die Referenz, ihre Zeit t_ref = Quellzeit - 10
    ablegen("IMG_9001", clip_aus(quelle, 10.0, 60, snr_db=30, seed=1))
    ablegen("IMG_9002", clip_aus(quelle, 22.3127, 60, gain_db=-12, snr_db=12, tiefpass=3500, hall=True, seed=2))   # +12,3127
    ablegen("IMG_9003", clip_aus(quelle, 1.9629, 40, gain_db=6, snr_db=20, tiefpass=2500, hall=True, seed=3))      # -8,0371
    ablegen("IMG_9004", clip_aus(quelle, 30.0, 55, drift_ppm=100, gain_db=-6, snr_db=15, tiefpass=4000, seed=4))   # 20 + 1e-4 t
    ablegen("IMG_9005", clip_aus(quelle, 74.0, 20, gain_db=-3, snr_db=15, tiefpass=3000, seed=5))                  # +64, nur mit 9002 überlappt
    ablegen("IMG_9006", clip_aus(mu * 2, 25.0, 40, snr_db=10, tiefpass=3000, hall=True, seed=6))                   # nur Musik (+15)
    print(f"     Ton erzeugt ({time.time() - t0:.1f} s)", flush=True)

    # ---- Hauptlauf: Kürzel statt Dateipfade, Referenz = 9001
    t1 = time.time()
    s = sync.sync_clips(["9001", "IMG_9002", "9003", "9004", "9005", "9006"], ref="9001")
    print(f"     sync_clips: {time.time() - t1:.1f} s", flush=True)
    c = s["clips"]
    assert s["ref"] == "IMG_9001" and list(c) == [f"IMG_900{i}" for i in range(1, 7)], list(c)
    assert c["IMG_9001"]["offset_s"] == 0.0 and c["IMG_9001"]["brauchbar"] and abs(c["IMG_9001"]["dauer_s"] - 60) < 0.01

    fehler = {}
    for name, soll in (("IMG_9002", 12.3127), ("IMG_9003", -8.0371), ("IMG_9005", 64.0)):
        e = c[name]
        fehler[name] = fehl_ms(soll, e["offset_s"])
        assert fehler[name] <= TOL_MS and e["brauchbar"] and not e["mehrdeutig"] and e["konfidenz"] >= 0.9, (name, e)
    ok(f"Offsets: 9002 +12,3127 s (Abweichung {fehler['IMG_9002']:.2f} ms, leise, Rauschen, Tiefpass, Hall), "
       f"9003 -8,0371 s (negativ, {fehler['IMG_9003']:.2f} ms), 9005 +64 s ({fehler['IMG_9005']:.2f} ms)")
    assert c["IMG_9005"]["ueber"] == "IMG_9002" and c["IMG_9005"]["ueberlappung"] is None, c["IMG_9005"]
    assert c["IMG_9005"]["gegen"] == "IMG_9002" and c["IMG_9002"]["gegen"] == "IMG_9001", (c["IMG_9005"], c["IMG_9002"])
    assert any("über IMG_9002" in w for w in c["IMG_9005"]["warnungen"]), c["IMG_9005"]["warnungen"]
    ok("9005 überlappt die Referenz nicht und wird über 9002 eingeordnet (Kette, Hinweis in den Warnungen)")

    e = c["IMG_9004"]
    wahr = 20.0 + 1e-4 * e["bezug_s"]                     # Versatz an der Bezugszeit (Drift + 100 ppm)
    assert fehl_ms(wahr, e["offset_s"]) <= TOL_MS, (wahr, e["offset_s"], e["bezug_s"])
    assert abs(e["drift_ppm"] - 100) <= 20 and e["drift_sicher"], e
    for n_ in ("IMG_9002", "IMG_9003"):
        assert abs(c[n_]["drift_ppm"]) < 25 and not c[n_]["drift_sicher"], (n_, c[n_]["drift_ppm"], c[n_]["drift_fehler_ppm"])
    ok(f"Drift: 9004 {ppm(e['drift_ppm'])} ppm (soll +100, Fehler {e['drift_fehler_ppm']:.0f} ppm, sicher), "
       f"Offset {fehl_ms(wahr, e['offset_s']):.2f} ms; 9002/9003 ohne Drift ({ppm(c['IMG_9002']['drift_ppm'])}, "
       f"{ppm(c['IMG_9003']['drift_ppm'])} ppm, nicht sicher)")

    # zeit_in rechnet die Drift ein: Anfang und Ende der Überlappung von 9004
    for tc in (0.5, 38.0):
        soll = 20.0 + (1 + 1e-4) * tc
        ist = sync.zeit_in(s, "9004", tc, "9001")
        assert ist is not None and fehl_ms(soll, ist) <= TOL_MS, (tc, soll, ist)
        assert abs(sync.zeit_in(s, "9001", ist, "9004") - tc) < 1e-6
        ohne = sync.zeit_in(s, "9004", tc, "9001", drift=False)
        assert ohne is not None and (tc < 30 or 0.0008 < abs(ohne - ist) < 0.005), (tc, ohne, ist)   # ohne Drift ~2 ms daneben
    assert sync.zeit_in(s, "9004", 50.0, "9001") is None, "Zeit außerhalb der Überlappung muss None sein"
    assert sync.zeit_in(s, "9003", 5.0, "9002") is None and sync.zeit_in(s, "9001", 100.0, "9002") is None
    z = sync.zeit_in(s, "9002", 10.0, "9003")
    assert fehl_ms(10.0 + 12.3127 + 8.0371, z) <= TOL_MS, z
    assert sync.deckt(s, 5.0) == ["IMG_9001", "IMG_9003"], sync.deckt(s, 5.0)
    assert sync.deckt(s, -5.0) == ["IMG_9003"] and sync.deckt(s, 80.0) == ["IMG_9005"], (sync.deckt(s, -5.0), sync.deckt(s, 80.0))
    assert sync.deckt(s, 70.0) == ["IMG_9002", "IMG_9004", "IMG_9005"], sync.deckt(s, 70.0)
    ok("zeit_in (mit Drift, außerhalb der Überlappung None, Rückweg), deckt (wer zeigt welchen Moment)")

    # ---- andere Referenz: alles verschiebt sich, die Kameras bleiben gleich zueinander
    sr_ = sync.sync_clips(["9001", "9002", "9003"], ref="IMG_9002")
    q_ = sr_["clips"]
    assert sr_["ref"] == "IMG_9002" and q_["IMG_9002"]["offset_s"] == 0.0, sr_["ref"]
    assert not [w for e in q_.values() for w in e["warnungen"]], [e["warnungen"] for e in q_.values()]      # auch keine Dreiecksprobe
    for name, soll in (("IMG_9001", -12.3127), ("IMG_9003", 1.9629 - 22.3127)):
        assert fehl_ms(soll, q_[name]["offset_s"]) <= TOL_MS and q_[name]["brauchbar"], (name, q_[name])
    assert fehl_ms(sync.zeit_in(sr_, "9001", 30.0, "9003"), sync.zeit_in(s, "9001", 30.0, "9003")) <= TOL_MS
    ok(f"Andere Referenz (9002): 9001 {q_['IMG_9001']['offset_s']:+.4f} s, 9003 {q_['IMG_9003']['offset_s']:+.4f} s; "
       "zeit_in zwischen zwei Kameras bleibt gleich")

    # ---- Musik-Schleife: mehrdeutig statt falsch zugeordnet
    m = c["IMG_9006"]
    assert m["mehrdeutig"] and not m["brauchbar"] and m["konfidenz"] < 0.5, m
    kand = [k["offset_s"] for k in m["kandidaten"]]
    rest = abs(kand[0] - kand[1]) % 2.0
    assert len(kand) >= 2 and min(rest, 2.0 - rest) < 0.01, kand                    # Spitzen im Abstand der 2-s-Schleife
    assert any("Mehrdeutig" in w for w in m["warnungen"]) and any("9006" in w for w in s["warnungen"]), (m["warnungen"], s["warnungen"])
    ok(f"Nur Musik-Schleife (9006): mehrdeutig, Konfidenz {m['konfidenz']:.2f}, Kandidaten im Schleifenabstand "
       f"{', '.join(f'{k:+.1f}' for k in kand)} s (nicht als sicher gemeldet)")

    # ---- Clip ohne gemeinsamen Ton: bleibt ohne Offset
    fremd = sprache(40, 99) + schleife(1.7, 40, seed=11) * 10 ** (-8 / 20)
    ablegen("IMG_9007", clip_aus(fremd, 0.0, 40, snr_db=20, seed=7))
    sf.write(str(TMP / "audio" / "IMG_9012.flac"), np.zeros((SR * 5, 2), np.float32), SR, subtype="PCM_16")
    (TMP / "meta").mkdir(exist_ok=True)
    json.dump(dict(name="IMG_9013.MOV", ctime="2026-09-20T13:00:00+0200", fps=30.0, dur=5.0, ton=False),
              open(TMP / "meta" / "IMG_9013.json", "w"))
    s2 = sync.sync_clips(["9001", "9007", "9012", "9013"])          # 9013: ingest kannte den Clip, er hatte keinen Ton
    assert s2["clips"]["IMG_9012"]["offset_s"] is None and any("stumm" in w for w in s2["clips"]["IMG_9012"]["warnungen"]), s2
    assert s2["clips"]["IMG_9013"]["offset_s"] is None and any("keinen Ton" in w for w in s2["clips"]["IMG_9013"]["warnungen"]), s2
    x = s2["clips"]["IMG_9007"]
    assert x["offset_s"] is None and not x["brauchbar"] and x["mehrdeutig"] and x["ueberlappung"] is None, x
    assert s2["warnungen"], s2
    assert sync.zeit_in(s2, "9007", 5.0, "9001") is None and sync.deckt(s2, 5.0) == ["IMG_9001"]
    ok("Clip ohne gemeinsamen Ton (anderes Gespräch, anderer Song): kein Offset, nicht eingeordnet; stummer Clip "
       "und Clip ohne Ton (meta: ton=false) brechen den Lauf nicht ab")

    # ---- große Drift: Warnung (mehr als ein halbes Bild über die Überlappung)
    ablegen("IMG_9008", clip_aus(quelle, 10.0, 60, drift_ppm=200, snr_db=20, seed=8))
    s3 = sync.sync_clips(["9001", "9008"])
    d = s3["clips"]["IMG_9008"]
    assert abs(d["drift_ppm"] - 200) <= 40 and d["drift_sicher"] and d["brauchbar"], d
    assert any("Uhrendrift" in w and "halbes Bild" in w for w in d["warnungen"]), d["warnungen"]
    assert not any("Uhrendrift" in w for w in c["IMG_9004"]["warnungen"]), "100 ppm über 40 s sind unter einem halben Bild"
    ok(f"Drift 200 ppm: {d['drift_ppm']:+.0f} ppm gemessen, Warnung über ein halbes Bild; 100 ppm ohne Warnung")

    # ---- Aufnahmezeit als Vorwissen: lange Schleife (12 s) wird über die Aufnahmezeit eindeutig
    mu12 = schleife(12.0, 96) * 10 ** (-8 / 20)
    ablegen("IMG_9010", clip_aus(mu12 * 2, 0.0, 50, snr_db=20, seed=10))
    ablegen("IMG_9011", clip_aus(mu12 * 2, 17.0, 40, snr_db=10, tiefpass=3500, seed=11))                           # +17
    s4 = sync.sync_clips(["9010", "9011"])
    a = s4["clips"]["IMG_9011"]
    assert a["mehrdeutig"] and a["aufnahmezeit_s"] is None, a
    meta("IMG_9010", "2026-09-20T13:00:00+0200")
    meta("IMG_9011", "2026-09-20T13:00:17+0200")
    s5 = sync.sync_clips(["9010", "9011"])
    b = s5["clips"]["IMG_9011"]
    assert b["aufnahmezeit_s"] == 17.0 and fehl_ms(17.0, b["offset_s"]) <= TOL_MS and b["mehrdeutig"] and not b["brauchbar"], b
    assert any("Aufnahmezeit" in w for w in b["warnungen"]), b["warnungen"]
    meta("IMG_9011", "2026-09-20T13:05:40+0200")                                   # Uhr des Handys falsch
    s6 = sync.sync_clips(["9010", "9011"])
    assert any("widerspricht" in w for w in s6["clips"]["IMG_9011"]["warnungen"]), s6["clips"]["IMG_9011"]["warnungen"]
    for n_ in ("IMG_9010", "IMG_9011"):
        (TMP / "meta" / f"{n_}.json").unlink()
    ok("Aufnahmezeit (meta/): entscheidet zwischen gleich starken Kandidaten (bleibt mehrdeutig, mit Warnung), "
       "Widerspruch wird gemeldet, ohne meta/ läuft alles wie vorher")

    # ---- Video mit verschobenem Tonstart (AAC in MP4) und Datei statt Kürzel
    y = clip_aus(quelle, 20.0, 12, snr_db=25, seed=12)
    sf.write(str(TMP / "v.wav"), y, SR, subtype="PCM_16")
    mp4 = TMP / "v.mp4"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=30:d=12", "-itsoffset",
                        "0.25", "-i", str(TMP / "v.wav"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", str(mp4)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-300:]
    s7 = sync.sync_clips(["9001", str(mp4)])
    v = s7["clips"]["v"]
    # Quelle ab 20 s, Ton im Video 0,25 s später als das Bild: Ton t_clip = 0,25 + Quellzeit - 20, Offset zur Referenz 10 - 0,25
    assert fehl_ms(10.0 - 0.25, v["offset_s"]) <= TOL_MS and v["brauchbar"], v
    assert any("Tonstart" in w or "Ton startet" in w for w in v["warnungen"]), v["warnungen"]
    ok(f"Videodatei (AAC, Ton 0,25 s nach dem Bild): Offset {v['offset_s']:+.4f} s (soll +9,7500), Tonstart eingerechnet")

    # ---- Kommandozeile und Zeitleiste
    out = TMP / "sync.json"
    r = subprocess.run([sys.executable, str(Path(sync.__file__)), "9001", "9002", "9003", "9004", "--ref", "9001", "--max", "120",
                        "-o", str(out)], capture_output=True, text=True, cwd="/tmp", env=dict(os.environ, REEL_WORK=str(TMP)))
    assert r.returncode == 0 and out.exists(), r.stdout + r.stderr
    j = sync.laden(out)
    assert j["ref"] == "IMG_9001" and fehl_ms(12.3127, j["clips"]["IMG_9002"]["offset_s"]) <= TOL_MS and j["max_s"] == 120, j
    assert "IMG_9003: -8.03" in r.stdout and "Drift +" in r.stdout, r.stdout
    assert not any("Dreiecksprobe" in w for e in j["clips"].values() for w in e["warnungen"]), j["clips"]
    import contextlib
    import io

    def cli(*argv):
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = sync.main(list(argv))
        return code, so.getvalue(), se.getvalue()

    code, txt, _ = cli("uebersicht", str(out))
    zeilen = txt.splitlines()
    assert code == 0 and zeilen[0].startswith("Zeitachse") and sum(z.startswith("IMG_900") for z in zeilen) == 4, txt
    assert all(len(z.split("|")[1]) == 40 for z in zeilen[1:6]), txt
    balken = {z.split()[0]: z.split("|")[1] for z in zeilen[1:5]}
    assert balken["IMG_9003"].startswith("#") and balken["IMG_9003"].endswith(".") and balken["IMG_9002"].startswith("."), balken
    assert balken["IMG_9001"].count("#") >= 27 and set(balken["IMG_9001"]) <= {"#", "."}, balken
    print(txt.rstrip(), flush=True)
    code, _, err = cli("9001", "gibtsnicht", "-o", str(TMP / "x.json"))
    assert code == 1 and "FEHLER" in err and "nicht gefunden" in err and not (TMP / "x.json").exists(), err
    ok("Kommandozeile: sync.json geschrieben und lesbar, Zeitleiste (uebersicht), Fehler bei fehlendem Clip mit Exit 1")

    # nichts im Projektordner: kein Bytecode von sync.py und diesem Test
    cache = Path(sync.__file__).resolve().parent / "__pycache__"
    assert not cache.exists() or not [f for f in cache.iterdir() if f.name.startswith(("sync.", "test_sync."))], list(cache.iterdir())
    print(f"test_sync: alles OK ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
