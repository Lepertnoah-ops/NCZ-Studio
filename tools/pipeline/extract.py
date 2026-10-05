#!/usr/bin/env python3
"""Frames für die Schnittliste ziehen: je Clip das Quellfenster aller Shots ±1,5 s als JPG.

    REEL_WORK=/home/user/reel REEL_EDL=<reel>/schnitt/edl.json python3 extract.py [--jobs 3]

Braucht die EDL, WORK/manifest.tsv und WORK/meta/ (ingest.py). Schreibt WORK/frames/<clip>/f_%05d.jpg
und times.json (Quellzeit je Frame). HDR wird getonemappt. Quellen bis 1300 px Breite -> 1080×1920,
4K -> 1440×2560 (Reserve für Zooms); das Seitenverhältnis bleibt, Überstand schneidet render.py ab.
Prüft die Frame-Zahl gegen die Fensterlänge und zieht bei Ausfall einmal neu
(Lernpunkt: ein Clip hatte beim ersten Lauf nur 93 Frames). Fotos (meta "photo") werden ein einziges
Bild in derselben Größe (times [0.0]); render.py zeigt es als Standbild mit den Effekten der fx.json.
Originalton (für O-Ton nach Stil-Leitfaden Regel 1): je Clip die ganze Tonspur als
WORK/audio/<clip>.flac (48 kHz Stereo); reel_audio.py schneidet daraus die "oton"-Stücke der audio_spec.json.
Liegen die Frames schon da, fehlt aber der Ton eines Clips mit O-Ton-Shot, kommt er aus der Sichtung
(ingest.py, WORK/audio/<stamm>.flac) oder wird dafür neu geladen.
Querformat-Clips (Breite > Höhe) bekommen eine Warnung in der Ausgabezeile: render.py schneidet die Mitte ab und zeigt
von 16:9 nur ~32 % der Breite; reframe.py setzt sie vorher mit Tracking auf 9:16 um.
"""
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
from reelcfg import WORK, download, load_edl, load_photo, log, manifest, run, stem_of, tonemap_for
from timing import windows

JOBS = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 3


def ton(path, out):
    """Ganze Tonspur als FLAC 48 kHz Stereo; False, wenn der Clip keinen Ton hat."""
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vn", "-map", "0:a:0?", "-ac", "2", "-ar", "48000",
         "-sample_fmt", "s16", "-c:a", "flac", out])
    if out.exists() and out.stat().st_size < 1000:
        out.unlink()
    return out.exists()


def ton_nachholen(c, stem, fid, name, size):
    out, sicht = WORK / "audio" / f"{c}.flac", WORK / "audio" / f"{stem}.flac"
    if sicht.exists() and sicht != out:
        try:
            os.link(sicht, out)
        except OSError:
            shutil.copyfile(sicht, out)
        return "Ton aus der Sichtung"
    path = WORK / "dl" / name
    if not download(fid, path, size, "extract"):
        return "Ton: Download fehlgeschlagen"
    ok = ton(path, out)
    path.unlink()
    return "Ton ok" if ok else "WARNUNG: Clip ohne Ton, O-Ton fällt weg"


def job(c, win, man, need):
    zeile = _job(c, win, man, need)
    m = json.load(open(WORK / "meta" / f"{stem_of(c, set(man))}.json"))
    if m["w"] > m["h"] and not m.get("photo"):      # Mitteschnitt in render.py: von 16:9 bleiben 32 % der Breite
        zeile += (f"  WARNUNG: Querformat {m['w']}×{m['h']}, der Mitteschnitt zeigt nur "
                  f"{100 * m['h'] * 9 / 16 / m['w']:.0f} % der Breite (reframe.py)")
    return zeile


def _job(c, win, man, need):
    stem = stem_of(c, set(man))
    fid, name, size = man[stem]
    m = json.load(open(WORK / "meta" / f"{stem}.json"))
    a, b = win[c]
    a0, b0 = max(0.0, a - 1.5), min(m["dur"], b + 1.5)
    od = WORK / "frames" / c
    tj = od / "times.json"
    if m.get("photo"):
        return photo(c, fid, name, size, m, od, tj)
    if tj.exists():
        t = json.load(open(tj))["times"]
        if t and t[0] <= max(0.0, a - 0.3) + 0.02 and t[-1] >= min(m["dur"] - 0.05, b + 0.3):
            if c in need and not (WORK / "audio" / f"{c}.flac").exists():
                return f"{c}: schon da, " + ton_nachholen(c, stem, fid, name, size)
            return f"{c}: schon da"
    path = WORK / "dl" / name
    if not download(fid, path, size, "extract"):
        log("extract", "FAIL download", c)
        return f"{c}: Download fehlgeschlagen"
    tw, th = (1440, 2560) if min(m["w"], m["h"]) > 1300 else (1080, 1920)
    vf = (tonemap_for(m["trc"]) + f"scale=w={tw}:h={th}:force_original_aspect_ratio=increase"
          ":force_divisible_by=2:flags=lanczos,showinfo")
    want = (b0 - a0) * m["fps"]
    for attempt in range(2):
        if od.exists():
            shutil.rmtree(od)
        od.mkdir(parents=True)
        r = run(["ffmpeg", "-v", "info", "-hide_banner", "-ss", f"{a0:.3f}", "-t", f"{b0 - a0:.3f}", "-i", path,
                 "-vf", vf, "-fps_mode", "passthrough", "-q:v", "3", f"{od}/f_%05d.jpg"])
        t = [a0 + float(x) for x in re.findall(r"pts_time:\s*([-0-9.]+)", r.stderr)]
        n = len(list(od.glob("f_*.jpg")))
        if n >= 0.97 * want - 2:
            break
        log("extract", "zu wenig Frames", c, n, "statt", round(want), "Versuch", attempt + 1)
    json.dump(dict(times=t[:n], fps=m["fps"], w=tw), open(tj, "w"))
    hat_ton = ton(path, WORK / "audio" / f"{c}.flac")
    path.unlink()
    log("extract", "ok", c, f"{a0:.2f}-{b0:.2f}", n, "frames", m["trc"] or "SDR", "Ton" if hat_ton else "ohne Ton")
    return f"{c}: {n} Frames" + ("" if n >= 0.97 * want - 2 else f"  WARNUNG: erwartet ~{round(want)}") + \
        ("" if hat_ton or c not in need else "  WARNUNG: Clip ohne Ton, O-Ton fällt weg")


def photo(c, fid, name, size, m, od, tj):
    if tj.exists():
        return f"{c}: schon da (Foto)"
    path = WORK / "dl" / name
    if not download(fid, path, size, "extract"):
        log("extract", "FAIL download", c)
        return f"{c}: Download fehlgeschlagen"
    im = load_photo(path)
    tw, th = (1440, 2560) if min(im.size) > 1300 else (1080, 1920)
    k = max(tw / im.width, th / im.height)          # wie force_original_aspect_ratio=increase
    im = im.resize((round(im.width * k / 2) * 2, round(im.height * k / 2) * 2), Image.Resampling.LANCZOS)
    od.mkdir(parents=True, exist_ok=True)
    im.save(od / "f_00001.jpg", quality=92)
    json.dump(dict(times=[0.0], fps=30.0, w=tw, photo=True), open(tj, "w"))
    path.unlink()
    log("extract", "ok", c, "Foto", im.size)
    return f"{c}: Foto {im.width}×{im.height}"


if __name__ == "__main__":
    E, man = load_edl(), manifest()
    win = windows(E)
    need = {s["clip"] for s in E["shots"] if s.get("oton") and s["clip"] != "split"}
    with ThreadPoolExecutor(JOBS) as ex:
        for line in ex.map(lambda c: job(c, win, man, need), sorted(win)):
            print(line, flush=True)
    log("extract", "DONE")
