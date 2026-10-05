#!/usr/bin/env python3
"""Sichtung: Download -> ffprobe -> Paketprofil -> Keyframes (640 px) -> Original löschen.

    REEL_WORK=/home/user/reel python3 ingest.py [--keep] [--jobs 3]

Liest WORK/manifest.tsv (<id>\t<name>\t<bytes>; drive.py manifest baut sie aus der Ausgabe des Drive-Connectors
search_files mit parentId = Ordner-ID, drive.py pruefen prüft sie). Fotos (HEIC/JPG/PNG) nur, wenn der Nutzer sie ausdrücklich will: sie werden zum Standbild-Clip
(meta "photo": true, ein Keyframe, Aufnahmezeit aus EXIF), Bewegung dann per push/punch in der fx.json. Schreibt je Clip WORK/meta/<stamm>.json (Auflösung, Drehung, fps, Dauer,
HDR-Kurve, Aufnahmezeit, Keyframe-Zeiten, Paketgrößen als Bewegungs-Hinweis) und WORK/kf/<stamm>/k_*.jpg,
dazu die Tonspur als WORK/audio/<stamm>.flac (für tools/analyse/oton.py und O-Ton im Reel).
Schon gesichtete Clips werden übersprungen, kleine Dateien zuerst. Richtwert: 88 Clips (8,6 GB) dauerten
~4 min mit 3 parallelen Downloads. --keep behält die Originale in WORK/dl/.
Ein Clip mit Download- oder Lesefehler bricht die Sichtung der anderen nicht ab; die Zusammenfassung nennt die
fehlenden Clips mit Grund. Querformat-Clips (Breite > Höhe) werden gemeldet: der Mitteschnitt auf 9:16 zeigt nur
~32 % der Breite, dafür gibt es reframe.py.
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
from drive import laden
from reelcfg import PHOTO_DUR, WORK, is_photo, load_photo, log, manifest, md5, photo_time, run, tonemap_for

KEEP = "--keep" in sys.argv
JOBS = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 3
FEHLER = {}     # Clipname -> Grund, für die Zusammenfassung


def probe(path):
    pr = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_format",
                         "-of", "json", path]).stdout or "{}")
    if not pr.get("streams"):
        raise ValueError("keine Videospur (Datei defekt, abgeschnitten oder kein Video)")
    st = pr["streams"][0]
    w, h = st["width"], st["height"]
    rot = 0
    for sd in st.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if abs(rot) in (90, 270):
        w, h = h, w
    num, den = map(int, st.get("avg_frame_rate", "30/1").split("/"))
    tags = {k.lower(): v for k, v in pr["format"].get("tags", {}).items()}
    return dict(w=w, h=h, rot=rot, fps=round(num / den if den else 30, 3),
                dur=float(st.get("duration") or pr["format"]["duration"]),
                trc=st.get("color_transfer", ""), codec=st["codec_name"], pix=st.get("pix_fmt"),
                ctime=tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time"))


def packets(path):
    out = []
    for line in run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                     "packet=pts_time,size,flags", "-of", "csv=p=0", path]).stdout.splitlines():
        p = line.split(",")
        try:
            out.append((float(p[0]), int(p[1]), "K" in p[2]))
        except (ValueError, IndexError):
            pass
    return out


def process(item):
    try:
        _process(item)
    except Exception as e:      # noqa: BLE001 - ein defekter Clip darf die Sichtung der anderen nicht abbrechen
        FEHLER[item[1][1]] = f"{type(e).__name__}: {str(e)[:120]}"
        log("ingest", "FAIL", item[1][1], FEHLER[item[1][1]])


def _process(item):
    stem, (fid, name, size) = item
    mfile = WORK / "meta" / f"{stem}.json"
    if mfile.exists():
        return
    path = WORK / "dl" / name
    t0 = time.time()
    ok, grund = laden(fid, path, size)
    if not ok:
        FEHLER[name] = f"Download: {grund}"
        log("ingest", "FAIL download", name, grund)
        return
    tdl = time.time() - t0
    od = WORK / "kf" / stem
    od.mkdir(parents=True, exist_ok=True)
    if is_photo(name):
        im = load_photo(path)
        m = dict(w=im.width, h=im.height, rot=0, fps=30.0, dur=PHOTO_DUR, trc="", codec="photo", pix="rgb24",
                 ctime=photo_time(path), photo=True)
        im.thumbnail((640, 640))
        im.save(od / "k_0001.jpg", quality=90)
        meta = dict(id=fid, name=name, size=size, md5=md5(path), **m, kf_times=[0.0], packets=[],
                    t_dl=round(tdl, 1), t_all=round(time.time() - t0, 1))
        if not KEEP:
            path.unlink()
        (WORK / "meta").mkdir(parents=True, exist_ok=True)
        json.dump(meta, open(mfile, "w"))
        log("ingest", "ok", name, f"{m['w']}x{m['h']}", "Foto", m["ctime"] or "", f"dl {tdl:.1f}s")
        return
    m = probe(path)
    vf = tonemap_for(m["trc"]) + "scale=w=640:h=640:force_original_aspect_ratio=decrease,showinfo"
    r = run(["ffmpeg", "-v", "info", "-hide_banner", "-skip_frame", "nokey", "-i", path, "-vf", vf,
             "-fps_mode", "passthrough", "-q:v", "3", f"{od}/k_%04d.jpg"])
    times = [float(x) for x in re.findall(r"pts_time:\s*([0-9.]+)", r.stderr)]
    from extract import ton
    hat_ton = ton(path, WORK / "audio" / f"{stem}.flac")
    meta = dict(id=fid, name=name, size=size, md5=md5(path), **m, kf_times=times, packets=packets(path),
                ton=hat_ton, t_dl=round(tdl, 1), t_all=round(time.time() - t0, 1))
    if not KEEP:
        path.unlink()
    (WORK / "meta").mkdir(parents=True, exist_ok=True)
    json.dump(meta, open(mfile, "w"))
    log("ingest", "ok", name, f"{m['w']}x{m['h']}", f"{m['fps']}fps", f"{m['dur']:.1f}s", m["trc"] or "SDR",
        f"{len(times)}kf", m["ctime"] or "", f"dl {tdl:.1f}s")


if __name__ == "__main__":
    items = sorted(manifest().items(), key=lambda kv: kv[1][2])
    with ThreadPoolExecutor(JOBS) as ex:
        list(ex.map(process, items))
    metas = [json.load(open(f)) for f in sorted((WORK / "meta").glob("*.json"))]
    done = len(metas)
    log("ingest", "DONE", done, "von", len(items))
    print(f"ingest: {done}/{len(items)} Clips gesichtet, Log: {WORK / 'ingest.log'}")
    for name, grund in list(FEHLER.items())[:10]:
        print(f"  FEHLT  {name}: {grund}")
    if len(FEHLER) > 10:
        print(f"  … und {len(FEHLER) - 10} weitere, siehe Log")
    quer = sorted(m["name"] for m in metas if m.get("w", 0) > m.get("h", 0) and not m.get("photo"))
    if quer:
        print(f"  QUERFORMAT {len(quer)} Clip(s): {', '.join(quer[:6])}{' …' if len(quer) > 6 else ''}\n"
              f"    Der Mitteschnitt auf 9:16 zeigt nur ~32 % der Breite: reframe.py <clip> (Tracking) oder ausschließen.")
