#!/usr/bin/env python3
"""
clip_analyse.py - Rohclip-Analyse fuer Reels (1080x1920, 30 fps, Fenster-Standard 2 Beats bei 140 BPM).

Pro Clip: Metadaten (ffprobe), Motivbewegung ("Action", ohne Kamerabewegung),
Kamerabewegung/Wackeln/Zoom, Schaerfe, Belichtung, Szenenschnitte, Highlights
(Fenster = 2 Beats), Nutzbarkeits-Score 0-100, Qualitaets-Flags, Duplikate im
Batch und Kontaktboegen (JPG). HLG/PQ wird fuer Luma und Bilder getonemappt.

Beispiele:
  python3 clip_analyse.py clips/ -o out/
  python3 clip_analyse.py IMG_6166.MOV IMG_3419.MOV -o out/ --fps 10 --jobs 2
  python3 clip_analyse.py clips/ -o out/ --schnell        # nur Keyframes, grober Ordner-Scan
  python3 clip_analyse.py --manifest manifest.tsv --only IMG_6166,IMG_3419 -o out/

Als Modul:
  from clip_analyse import analyse_clip
  info = analyse_clip("IMG_6166.MOV", sample_fps=10)
  print(info["score"], info["flags"], info["highlights"][0]["peak"])

Ausgabe in OUTDIR: clips.json, clips.md, kontaktbogen_01.jpg, kontaktbogen_02.jpg, ...
Einheiten: motion/camera in px/s bei 1080 px Bildbreite, sharp = Laplace-Varianz
auf 320-px-Analysebild, luma 0-255 (nach Tonemapping).
"""

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tools/ für stil
from stil import STIL  # noqa: E402

MARKE = STIL["marke"] or "Reel-Studio"
VERSION = 1
ANALYSE_W = 320                     # Breite der Analyse-Frames (px)
REF_W = 1080                        # Bezugsbreite fuer px/s
BPM = 140
FENSTER_DEFAULT = round(2 * 60 / BPM, 2)   # 0.86 s = 2 Beats bei 140 BPM
VIDEO_EXT = (".mov", ".mp4", ".m4v")
THUMBS_PRO_ZEILE = 8
HASH_N = 6
DRIVE_URL = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"

TONEMAP = ("zscale=tin={tin}:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=100,format=gbrpf32le,"
           "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")

# Kalibrierung (auf echten Clips geprueft, siehe Bericht)
M0 = 120.0          # Action-Skala: 1-exp(-motion/M0)
SHAKE0 = 80.0       # Wackel-Skala: exp(-shake/SHAKE0)
CAM0 = 500.0        # Kameratempo-Skala fuer Highlights: 1/(1+camera/CAM0)
SHARP_OK = 500.0    # Laplace-Varianz (320 px) ab der ein Frame als scharf gilt
TH = {
    "motion_low": 25.0,     # motion_p90 darunter -> "kaum Bewegung"
    "shake_high": 70.0,     # shake_mean darueber -> "verwackelt"
    "sharp_low": 150.0,     # sharp_median darunter -> "unscharf"
    "luma_dark": 55.0, "luma_bright": 200.0,
    "clip_hi": 0.12, "clip_lo": 0.30,
    "scene_abs": 0.45, "scene_rel": 5.0,
}

FONT_DIRS = ["/usr/share/fonts/truetype/montserrat/", "/usr/share/fonts/truetype/dejavu/"]
_print_lock = threading.Lock()


def log(msg):
    """Thread-sichere Ausgabe."""
    with _print_lock:
        print(msg, flush=True)


# ---------------------------------------------------------------- Metadaten

def _ratio(s):
    try:
        n, d = str(s).split("/")
        n, d = float(n), float(d)
        return n / d if d else 0.0
    except (ValueError, TypeError):
        return 0.0


def _iso(s):
    """Apple-/ffprobe-Zeitstempel -> ISO 8601 (oder None)."""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"^(.*\d\d:\d\d:\d\d(?:\.\d+)?)([+-]\d\d)(\d\d)$", s)
    if m:
        s = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    s = s.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s).isoformat()
    except ValueError:
        return s


def probe(path):
    """ffprobe-Metadaten eines Clips (rotationsbewusst)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", path], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("ffprobe-Fehler: " + r.stderr.decode(errors="replace")[:300])
    d = json.loads(r.stdout or b"{}")
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    if v is None:
        raise RuntimeError("kein Videostream")
    fmt = d.get("format", {})
    ftags = {k.lower(): val for k, val in (fmt.get("tags") or {}).items()}
    vtags = {k.lower(): val for k, val in (v.get("tags") or {}).items()}
    rot, dovi = 0.0, False
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = float(sd["rotation"])
        if "DOVI" in str(sd.get("side_data_type", "")):
            dovi = True
    if not rot and "rotate" in vtags:           # alter Tag, im Uhrzeigersinn
        rot = -float(vtags["rotate"])
    rot = int(round(rot)) % 360
    cw, ch = int(v.get("width") or 0), int(v.get("height") or 0)
    w, h = (ch, cw) if rot in (90, 270) else (cw, ch)
    fps = _ratio(v.get("avg_frame_rate")) or _ratio(v.get("r_frame_rate"))
    dur = float(fmt.get("duration") or v.get("duration") or 0.0)
    trc = (v.get("color_transfer") or "").lower()
    hdr = "hlg" if trc == "arib-std-b67" else "pq" if trc == "smpte2084" else "sdr"
    ct = (ftags.get("com.apple.quicktime.creationdate") or ftags.get("creation_time")
          or vtags.get("creation_time"))
    gps = ftags.get("com.apple.quicktime.location.iso6709") or ftags.get("location")
    return {
        "w": w, "h": h, "rotation": rot, "coded_w": cw, "coded_h": ch,
        "fps": round(fps, 3), "fps_nominal": round(_ratio(v.get("r_frame_rate")), 3),
        "dur": round(dur, 3), "codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
        "hdr": hdr, "dolby_vision": dovi, "creation_time": _iso(ct), "gps": gps,
        "model": ftags.get("com.apple.quicktime.model"),
        "audio": any(s.get("codec_type") == "audio" for s in streams),
        "size": os.path.getsize(path),
    }


# ---------------------------------------------------------------- Dekodieren

def _filter_chain(meta, sample_fps, schnell):
    """ffmpeg-Filter: fps -> verkleinern -> (Tonemap) -> drehen. Gibt (vf, breite, hoehe)."""
    rot, dw, dh = meta["rotation"], max(1, meta["w"]), max(1, meta["h"])
    aw = ANALYSE_W
    ah = max(2, int(round(aw * dh / dw / 2)) * 2)
    f = [] if schnell else [f"fps={sample_fps}"]
    f.append(f"scale={ah}:{aw}:flags=area" if rot in (90, 270) else f"scale={aw}:{ah}:flags=area")
    if meta["hdr"] in ("hlg", "pq"):
        f.append(TONEMAP.format(tin="arib-std-b67" if meta["hdr"] == "hlg" else "smpte2084"))
    if rot == 270:
        f.append("transpose=clock")
    elif rot == 90:
        f.append("transpose=cclock")
    elif rot == 180:
        f.append("hflip,vflip")
    return ",".join(f), aw, ah


def _keyframe_times(path):
    """Zeitpunkte der Keyframes (nur Pakete lesen, kein Dekodieren)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "packet=pts_time,flags", "-of", "csv=p=0", path], capture_output=True)
    ts = []
    for line in r.stdout.decode(errors="replace").splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and "K" in parts[1]:
            try:
                ts.append(float(parts[0]))
            except ValueError:
                pass
    return sorted(ts)


def iter_frames(path, meta, sample_fps=10, threads=2, schnell=False, von=None, bis=None):
    """Liefert kleine RGB-Frames (uint8, ~320 px breit) aus ffmpeg (Streaming). von/bis: nur dieser Bereich in s
    (bildgenau ab von, nur im Vollmodus), das erste Bild gehört dann zu von."""
    vf, aw, ah = _filter_chain(meta, sample_fps, schnell)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-threads", str(threads)]
    if schnell:
        cmd += ["-skip_frame", "nokey"]
    elif von is not None:
        cmd += ["-ss", f"{von:.3f}"] + (["-t", f"{max(0.1, bis - von):.3f}"] if bis is not None else [])
    cmd += ["-noautorotate", "-i", path, "-map", "0:v:0", "-an", "-sn", "-dn",
            "-filter_threads", "1", "-vf", vf]
    if schnell:
        cmd += ["-fps_mode", "passthrough"]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    fsize = aw * ah * 3
    with tempfile.TemporaryFile() as errf:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, bufsize=fsize * 2)
        n = 0
        try:
            while True:
                buf = p.stdout.read(fsize)
                if len(buf) < fsize:
                    break
                n += 1
                yield np.frombuffer(buf, np.uint8).reshape(ah, aw, 3)
        finally:
            p.stdout.close()
            p.wait()
            if n == 0:
                errf.seek(0)
                raise RuntimeError("ffmpeg lieferte keine Frames: " + errf.read().decode(errors="replace")[:400])


# ---------------------------------------------------------------- Einzelmetriken

def _grid(ah, aw, step=8, margin=8):
    ys, xs = np.mgrid[margin:ah - margin:step, margin:aw - margin:step]
    return xs.ravel(), ys.ravel()


def flow_metrics(prev, cur, gx, gy):
    """Optischer Fluss: (Motivbewegung px, Kameravektor px, Skalierung, Top-5-%-Bewegung px)."""
    flow = cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 4, 15, 3, 5, 1.2, 0)
    fx, fy = flow[gy, gx, 0], flow[gy, gx, 1]
    src = np.stack([gx, gy], 1).astype(np.float32)
    dst = src + np.stack([fx, fy], 1)
    M = None
    try:
        M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=1.5,
                                           maxIters=300, confidence=0.98)
    except cv2.error:
        M = None
    h, w = prev.shape
    c = np.array([w / 2.0, h / 2.0], np.float32)
    if M is None:
        cam = np.array([np.median(fx), np.median(fy)], np.float32)
        camf = np.broadcast_to(cam, src.shape)
        scale = 1.0
    else:
        camf = src @ M[:, :2].T + M[:, 2] - src
        cam = c @ M[:, :2].T + M[:, 2] - c
        scale = float(math.hypot(M[0, 0], M[1, 0]))
    res = np.hypot(fx - camf[:, 0], fy - camf[:, 1])
    k = max(1, len(res) // 20)
    top = float(np.partition(res, len(res) - k)[-k:].mean())   # lokale Action (Top 5 %)
    return float(res.mean()), cam.astype(float), scale, top


def dhash(gray):
    """64-Bit-Differenz-Hash (bool-Array) eines Graubilds."""
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
    return (small[:, 1:] > small[:, :-1]).ravel()


def detect_people(frames):
    """HOG-Personendetektor, falls in dieser OpenCV-Version vorhanden; sonst None."""
    if not frames or not hasattr(cv2, "HOGDescriptor"):
        return None
    try:
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        best = 0
        for img in frames[:4]:
            g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            rects, _ = hog.detectMultiScale(g, winStride=(8, 8), padding=(8, 8), scale=1.05)
            best = max(best, len(rects))
        return int(best)
    except Exception:           # noqa: BLE001 - Detektor optional
        return None


def _movavg(x, n):
    if len(x) < 2 or n <= 1:
        return x.copy()
    n = min(n, len(x))
    k = np.ones(n) / n
    pad = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(pad, k, mode="valid")


# ---------------------------------------------------------------- Highlights & Score

def sample_quality(motion, sharp, luma, hi, lo, shake, camera=None):
    """Qualitaet pro Sample 0..1: viel Motivbewegung, scharf, gut belichtet, wenig Wackeln/Schwenk."""
    mot_f = 1.0 - np.exp(-motion / M0)
    sharp_f = np.clip(sharp / SHARP_OK, 0.35, 1.0)
    expo_f = np.clip(1.0 - np.maximum(0, 45 - luma) / 45 - np.maximum(0, luma - 215) / 40
                     - np.maximum(0, hi - 0.15) - np.maximum(0, lo - 0.35), 0.2, 1.0)
    shake_f = np.exp(-shake / SHAKE0)
    cam_f = 1.0 / (1.0 + camera / CAM0) if camera is not None else 1.0
    return mot_f * sharp_f * expo_f * shake_f * cam_f


def find_highlights(t, motion, q, sharp, cut_idx, sample_fps, fenster, dur, n_max=5, peak_series=None):
    """Top-N nicht ueberlappende Fenster (Laenge fenster) nach Qualitaet q; Peak = max. Action."""
    ps = motion if peak_series is None else peak_series
    n = len(t)
    if n < 2:
        return []
    win = max(2, int(round(fenster * sample_fps)))
    dt_s = 1.0 / sample_fps
    if n <= win:
        starts = [0]
        win = n
    else:
        starts = list(range(0, n - win + 1))
    cs = np.concatenate([[0.0], np.cumsum(q)])
    wscore = np.array([(cs[s + win] - cs[s]) / win for s in starts])
    for k, s in enumerate(starts):              # Fenster ueber Szenenschnitt abwerten
        if any(s < c < s + win for c in cut_idx):
            wscore[k] *= 0.5
    order = np.argsort(-wscore, kind="stable")
    picked = []
    for k in order:
        s = starts[k]
        if any(abs(s - p) < win for p, _ in picked):
            continue
        if len(picked) >= 3 and wscore[k] < 0.5 * picked[0][1]:
            break
        picked.append((s, float(wscore[k])))
        if len(picked) >= n_max:
            break
    out = []
    for s, sc in picked:
        seg = motion[s:s + win]
        i = s + int(np.argmax(ps[s:s + win]))
        start = float(t[s])
        end = min(start + fenster, dur) if dur > 0 else start + fenster
        peak = min(max(float(t[i]) + dt_s / 2, start), end)
        out.append({"start": round(start, 3), "end": round(end, 3), "peak": round(peak, 3),
                    "score": round(100 * sc, 1), "motion": round(float(seg.mean()), 1),
                    "sharp": round(float(np.mean(sharp[s:s + win])), 1)})
    return out


def clip_score_flags(info):
    """Nutzbarkeits-Score 0-100 und deutsche Qualitaets-Flags."""
    st = info["stats"]
    flags = []
    mot_f = 1.0 - math.exp(-st["motion_p90"] / M0)
    sharp_f = min(1.0, st["sharp_median"] / SHARP_OK)
    lm = st["luma_mean"]
    expo_f = max(0.0, min(1.0, 1 - max(0, 70 - lm) / 60 - max(0, lm - 190) / 50
                          - 2 * max(0, st["clip_hi"] - 0.05) - 1.5 * max(0, st["clip_lo"] - 0.10)))
    stab_f = math.exp(-st["shake_mean"] / SHAKE0)
    score = 100 * (0.40 * mot_f + 0.20 * sharp_f + 0.20 * expo_f + 0.20 * stab_f)
    if st["shake_mean"] > TH["shake_high"]:
        flags.append("verwackelt")
        score *= 0.85
    if st["sharp_median"] < TH["sharp_low"]:
        flags.append("unscharf")
    if lm < TH["luma_dark"] or st["clip_lo"] > TH["clip_lo"]:
        flags.append("zu dunkel")
    if lm > TH["luma_bright"] or st["clip_hi"] > TH["clip_hi"]:
        flags.append("überbelichtet")
    if st["motion_p90"] < TH["motion_low"]:
        flags.append("kaum Bewegung")
    if info["dur"] < 2.0:
        flags.append("sehr kurz (<2 s)")
        score *= 0.6
    if info["w"] > info["h"]:
        flags.append("Querformat")
        score *= 0.8
    if info["scenes"]:
        flags.append("Szenenschnitte im Clip (schon geschnitten?)")
        score *= 0.8
    if not info.get("audio", True):
        flags.append("ohne Ton")
    if info.get("modus") == "schnell":
        flags.append("Schnell-Scan (nur Keyframes)")
    return int(round(max(0.0, min(100.0, score)))), flags


# ---------------------------------------------------------------- Hauptanalyse

def analyse_clip(path, sample_fps=10, fenster=FENSTER_DEFAULT, threads=2, schnell=False,
                 name=None, thumbs=True, von=None, bis=None):
    """Analysiert einen Clip. Gibt ein JSON-faehiges dict (plus private Schluessel '_thumbs', '_hash').
    von/bis (s, nur Vollmodus): nur dieser Bereich; series.t bleibt die Zeit im Clip, info["bereich"] nennt ihn."""
    t0 = time.time()
    meta = probe(path)
    info = {"name": name or os.path.basename(path), "path": os.path.abspath(path)}
    info.update(meta)
    info["modus"] = "schnell" if schnell else "voll"
    if von is not None and schnell:
        raise ValueError("von/bis gibt es nur im Vollmodus")
    t_off = max(0.0, von or 0.0)
    if von is not None:
        info["bereich"] = [round(t_off, 3), round(min(meta["dur"], bis) if bis is not None else meta["dur"], 3)]
    key_ts = _keyframe_times(path) if schnell else None
    _, aw, ah = _filter_chain(meta, sample_fps, schnell)
    gx, gy = _grid(ah, aw)
    n_exp = max(1, len(key_ts) if schnell else int(meta["dur"] * sample_fps))
    stride = max(1, n_exp // 48)
    tw = 189                                    # Thumbnail-Breite fuer den Kontaktbogen
    th_ = max(2, int(round(tw * ah / aw)))

    motion, mtop, cam, zoom, sharp, luma, hi, lo, hist_d, times = [], [], [], [], [], [], [], [], [], []
    stored = []                                 # (t, thumb_rgb)
    prev_g = prev_h = None
    i = 0
    for rgb in iter_frames(path, meta, sample_fps, threads, schnell, von if von is None else t_off, bis):
        if schnell:
            t = key_ts[i] if i < len(key_ts) else (key_ts[-1] + 1.0 if key_ts else float(i))
        else:
            t = t_off + i / sample_fps
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        times.append(t)
        luma.append(float(g.mean()))
        hi.append(float((g > 250).mean()))
        lo.append(float((g < 5).mean()))
        sharp.append(float(cv2.Laplacian(g, cv2.CV_32F).var()))
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        if prev_g is not None:
            m, c, s, tp = flow_metrics(prev_g, g, gx, gy)
            dtp = max(1e-3, t - times[-2])
            k = (REF_W / aw) / dtp               # px/Sample -> px/s bei 1080 px Breite
            motion.append(m * k)
            mtop.append(tp * k)
            cam.append(c * k)
            zoom.append((s - 1.0) / dtp * 100.0)  # %/s
            hist_d.append(float(cv2.compareHist(prev_h, hist, cv2.HISTCMP_BHATTACHARYYA)))
        if thumbs and i % stride == 0:
            stored.append((t, cv2.resize(rgb, (tw, th_), interpolation=cv2.INTER_AREA)))
        prev_g, prev_h = g, hist
        i += 1
    n = len(times)
    t_arr = np.array(times, float)
    # Fluss-Werte gehoeren zum Intervall [t_i, t_i+1] -> Index i; letzter Wert kopiert
    if n >= 2:
        motion.append(motion[-1])
        mtop.append(mtop[-1])
        cam.append(cam[-1])
        zoom.append(zoom[-1])
    else:
        motion, mtop, cam, zoom = [0.0], [0.0], [np.zeros(2)], [0.0]
    motion = np.array(motion, float)
    mtop = np.array(mtop, float)
    cam = np.array(cam, float).reshape(-1, 2)
    zoom = np.array(zoom, float)
    sharp, luma = np.array(sharp, float), np.array(luma, float)
    hi, lo = np.array(hi, float), np.array(lo, float)

    # Szenenschnitte: Histogramm-Sprung (absolut und relativ zum Median)
    cut_idx = []
    if len(hist_d) >= 3:
        hd = np.array(hist_d)
        med = float(np.median(hd)) + 0.02
        for j, d in enumerate(hd):
            nb = np.concatenate([hd[max(0, j - 3):j], hd[j + 1:j + 4]])
            if (d > TH["scene_abs"] and d > TH["scene_rel"] * med
                    and (len(nb) == 0 or nb.max() < 0.5 * d)):
                cut_idx.append(j + 1)            # Schnitt vor Frame j+1 (isolierter Sprung)
    for c in cut_idx:                            # Schnitt-Frames nicht als Bewegung werten
        j = c - 1
        rep = j - 1 if j - 1 >= 0 else min(j + 1, n - 1)
        motion[j], mtop[j], cam[j], zoom[j] = motion[rep], mtop[rep], cam[rep], zoom[rep]

    camera = np.hypot(cam[:, 0], cam[:, 1])
    win_s = max(3, int(round(0.5 * (sample_fps if not schnell else 1))))
    smooth = np.stack([_movavg(cam[:, 0], win_s), _movavg(cam[:, 1], win_s)], 1)
    shake = np.hypot(*(cam - smooth).T)

    action = 0.5 * motion + 0.5 * mtop / 4.0      # Mischung global + lokal fuer Highlights
    q = sample_quality(action, sharp, luma, hi, lo, shake, camera)
    eff_fps = sample_fps if not schnell else max(0.2, (n - 1) / max(1e-3, t_arr[-1] - t_arr[0]) if n > 1 else 1.0)
    highlights = find_highlights(t_arr, motion, q, sharp, cut_idx, eff_fps, fenster, meta["dur"],
                                 peak_series=action)

    r1, r2, r3 = (lambda a: [round(float(x), 1) for x in a]), (lambda a: [round(float(x), 2) for x in a]), \
        (lambda a: [round(float(x), 3) for x in a])
    info["sample_fps"] = sample_fps if not schnell else round(float(eff_fps), 3)
    info["series"] = {"t": r3(t_arr), "motion": r1(motion), "motion_top": r1(mtop), "camera": r1(camera),
                      "shake": r1(shake),
                      "zoom": r2(zoom), "sharp": r1(sharp), "luma": r1(luma)}
    info["stats"] = {
        "motion_mean": round(float(motion.mean()), 1),
        "motion_p90": round(float(np.percentile(motion, 90)), 1),
        "motion_max": round(float(motion.max()), 1),
        "camera_mean": round(float(camera.mean()), 1),
        "shake_mean": round(float(shake.mean()), 1),
        "zoom_p90": round(float(np.percentile(np.abs(zoom), 90)), 2),
        "sharp_median": round(float(np.median(sharp)), 1),
        "luma_mean": round(float(luma.mean()), 1),
        "clip_hi": round(float(hi.mean()), 4),
        "clip_lo": round(float(lo.mean()), 4),
        "frames": n,
    }
    info["scenes"] = [round(float(t_arr[c]), 3) for c in cut_idx]
    info["people_max"] = detect_people([f for _, f in stored[::max(1, len(stored) // 4)]]) if stored else None
    info["highlights"] = highlights
    info["score"], info["flags"] = clip_score_flags(info)
    info["analyse_s"] = round(time.time() - t0, 2)
    if thumbs:
        sel = np.linspace(0, len(stored) - 1, HASH_N).round().astype(int) if stored else []
        info["_hash"] = np.array([dhash(cv2.cvtColor(stored[k][1], cv2.COLOR_RGB2GRAY)) for k in sel])
        info["_stored"] = stored
    return info


# ---------------------------------------------------------------- Duplikate

def find_duplicates(infos, min_sim=0.90):
    """Paare mit (fast) gleichem Inhalt: dHash mehrerer Frames + Dauer/Dateigroesse."""
    out = []
    for a in range(len(infos)):
        for b in range(a + 1, len(infos)):
            A, B = infos[a], infos[b]
            if A.get("error") or B.get("error"):
                continue
            if abs(A["dur"] - B["dur"]) > max(0.3, 0.03 * max(A["dur"], B["dur"])):
                continue
            ha, hb = A.get("_hash"), B.get("_hash")
            if ha is None or hb is None or len(ha) != len(hb) or len(ha) == 0:
                continue
            sim = 1.0 - float(np.mean(ha != hb))
            if A["size"] == B["size"] and abs(A["dur"] - B["dur"]) < 0.01 and sim > 0.97:
                sim = 1.0
            if sim >= min_sim:
                out.append([A["name"], B["name"], round(sim, 3)])
    return out


# ---------------------------------------------------------------- Kontaktbogen

def _font(size, bold=False):
    names = (["Montserrat-Bold.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["Montserrat-Medium.ttf", "Montserrat-Regular.ttf", "DejaVuSans.ttf"])
    for nm in names:
        for d in FONT_DIRS:
            p = os.path.join(d, nm)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _ts(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _pick_thumbs(info, n=THUMBS_PRO_ZEILE):
    st = info.get("_stored") or []
    if not st:
        return []
    dur = info["dur"] or (st[-1][0] + 0.1)
    out = []
    for k in range(n):
        target = (k + 0.5) / n * dur
        out.append(min(st, key=lambda x: abs(x[0] - target)))
    return out


def draw_sheets(infos, outdir, rows=6, width=1600):
    """Kontaktboegen: pro Clip eine Zeile mit 8 Frames, Fakten, Flags und Action-Sparkline."""
    infos = [i for i in infos if not i.get("error")]
    if not infos:
        return []
    bg, fg, dim, acc, bad = (17, 17, 17), (236, 236, 236), (150, 150, 150), (255, 122, 0), (255, 95, 95)
    f_title, f_txt, f_small, f_head = _font(24, True), _font(18), _font(15), _font(30, True)
    pad, gap = 16, 8
    tw = (width - 2 * pad - (THUMBS_PRO_ZEILE - 1) * gap) // THUMBS_PRO_ZEILE
    th = int(round(tw * 16 / 9))
    spark_h = 64
    row_h = 34 + 26 + th + 24 + spark_h + 26
    head_h = 60
    vmax_all = max(150.0, float(np.percentile(np.concatenate(
        [np.array(i["series"]["motion"]) for i in infos]), 98)))
    files = []
    now = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    n_sheets = (len(infos) + rows - 1) // rows
    for si in range(n_sheets):
        chunk = infos[si * rows:(si + 1) * rows]
        H = head_h + row_h * len(chunk) + pad
        img = Image.new("RGB", (width, H), bg)
        dr = ImageDraw.Draw(img)
        dr.text((pad, 14), f"{MARKE} · Kontaktbogen {si + 1}/{n_sheets}", font=f_head, fill=fg)
        dr.text((width - pad, 22), f"{now} · Action-Skala 0-{vmax_all:.0f} px/s", font=f_small,
                fill=dim, anchor="ra")
        for ri, info in enumerate(chunk):
            y0 = head_h + ri * row_h
            dr.line([(pad, y0), (width - pad, y0)], fill=(60, 60, 60), width=1)
            st = info["stats"]
            dr.text((pad, y0 + 6), info["name"], font=f_title, fill=fg)
            nx = pad + dr.textlength(info["name"], font=f_title) + 16
            ct = info.get("creation_time") or ""
            ct_s = ""
            if ct:
                try:
                    c = dt.datetime.fromisoformat(ct)
                    ct_s = c.strftime(" · %d.%m. %H:%M")
                except ValueError:
                    ct_s = ""
            facts = (f"{info['dur']:.1f} s · {info['fps']:.0f} fps · {info['w']}×{info['h']} · "
                     f"{(info.get('codec') or '?').upper()} · {info['hdr'].upper()}{ct_s} · "
                     f"Action Ø {st['motion_mean']:.0f} / p90 {st['motion_p90']:.0f} · "
                     f"Kamera Ø {st['camera_mean']:.0f} · Schärfe {st['sharp_median']:.0f} · "
                     f"Luma {st['luma_mean']:.0f}")
            dr.text((nx, y0 + 11), facts, font=f_txt, fill=dim)
            sc = info["score"]
            sc_col = (90, 200, 120) if sc >= 60 else acc if sc >= 40 else bad
            dr.text((width - pad, y0 + 6), f"Score {sc}", font=f_title, fill=sc_col, anchor="ra")
            hl = info["highlights"][0] if info["highlights"] else None
            line2 = ("Highlight " + f"{hl['start']:.2f}–{hl['end']:.2f} s (Peak {hl['peak']:.2f} s)"
                     if hl else "kein Highlight")
            dr.text((pad, y0 + 36), line2, font=f_txt, fill=acc)
            if info["flags"]:
                dr.text((pad + 380, y0 + 36), "Flags: " + ", ".join(info["flags"]), font=f_txt, fill=bad)
            ty = y0 + 34 + 26
            for k, (t, thumb) in enumerate(_pick_thumbs(info)):
                x = pad + k * (tw + gap)
                im = Image.fromarray(thumb)
                im.thumbnail((tw, th), Image.LANCZOS)
                ox, oy = x + (tw - im.width) // 2, ty + (th - im.height) // 2
                dr.rectangle([x, ty, x + tw - 1, ty + th - 1], fill=(0, 0, 0))
                img.paste(im, (ox, oy))
                if any(h["start"] <= t <= h["end"] for h in info["highlights"][:3]):
                    dr.rectangle([x, ty, x + tw - 1, ty + th - 1], outline=acc, width=3)
                dr.text((x + tw // 2, ty + th + 3), _ts(t), font=f_small, fill=fg, anchor="ma")
            # Sparkline: Action (weiss), Kamera (blau), Highlights (orange), Schnitte (rot)
            sy = ty + th + 24
            sx0, sx1 = pad, width - pad
            dr.rectangle([sx0, sy, sx1, sy + spark_h], fill=(28, 28, 28))
            ser = info["series"]
            dur = max(1e-3, info["dur"] or (ser["t"][-1] if ser["t"] else 1.0))

            def X(tt):
                return sx0 + (sx1 - sx0) * min(1.0, max(0.0, tt / dur))

            def Y(v):
                return sy + spark_h - 2 - (spark_h - 6) * min(1.0, max(0.0, v / vmax_all))
            for h in info["highlights"]:
                dr.rectangle([X(h["start"]), sy, X(h["end"]), sy + spark_h], fill=(90, 50, 10))
                px = X(h["peak"])
                dr.line([(px, sy), (px, sy + spark_h)], fill=acc, width=2)
            for c in info["scenes"]:
                dr.line([(X(c), sy), (X(c), sy + spark_h)], fill=bad, width=2)
            dt_s = 1.0 / max(0.1, float(info.get("sample_fps") or 10))
            if len(ser["t"]) >= 2:
                pts_c = [(X(t + dt_s / 2), Y(v)) for t, v in zip(ser["t"], ser["camera"])]
                pts_m = [(X(t + dt_s / 2), Y(v)) for t, v in zip(ser["t"], ser["motion"])]
                dr.line(pts_c, fill=(80, 140, 230), width=1)
                dr.line(pts_m, fill=fg, width=2)
            dr.text((sx0 + 4, sy + 2), "Action", font=f_small, fill=fg)
            dr.text((sx0 + 64, sy + 2), "Kamera", font=f_small, fill=(80, 140, 230))
            dr.text((sx1 - 4, sy + 2), f"max {st['motion_max']:.0f} px/s", font=f_small, fill=dim, anchor="ra")
        fn = os.path.join(outdir, f"kontaktbogen_{si + 1:02d}.jpg")
        img.save(fn, quality=88)
        files.append(fn)
    return files


# ---------------------------------------------------------------- Berichte

def _public(info):
    return {k: v for k, v in info.items() if not k.startswith("_")}


def write_outputs(infos, outdir, sample_fps, fenster, sheets=True, rows=6, width=1600):
    """Schreibt clips.json, clips.md und Kontaktboegen."""
    os.makedirs(outdir, exist_ok=True)
    dups = find_duplicates(infos)
    data = {"version": VERSION, "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "sample_fps": sample_fps, "fenster": fenster, "bpm": BPM,
            "modus": "schnell" if any(i.get("modus") == "schnell" for i in infos) else "voll",
            "clips": [_public(i) for i in infos], "duplicates": dups}
    with open(os.path.join(outdir, "clips.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    ok = sorted([i for i in infos if not i.get("error")], key=lambda i: -i["score"])
    L = [f"# Clip-Analyse {MARKE}", "",
         f"Erstellt: {data['created']} · Clips: {len(infos)} · Analyse-fps: {sample_fps} · "
         f"Fenster: {fenster} s (2 Beats @ {BPM} BPM)", "",
         "| # | Clip | Dauer | Format | HDR | Score | Action Ø/p90 | Kamera Ø | Wackeln | Schärfe | Luma "
         "| Bester Moment (Peak) | Flags |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, i in enumerate(ok, 1):
        st = i["stats"]
        hl = i["highlights"][0] if i["highlights"] else None
        hls = f"{hl['start']:.2f}–{hl['end']:.2f} s (Peak {hl['peak']:.2f})" if hl else "–"
        L.append(f"| {n} | {i['name']} | {i['dur']:.1f} s | {i['w']}×{i['h']} @{i['fps']:.0f} | "
                 f"{i['hdr'].upper()} | **{i['score']}** | {st['motion_mean']:.0f} / {st['motion_p90']:.0f} | "
                 f"{st['camera_mean']:.0f} | {st['shake_mean']:.0f} | {st['sharp_median']:.0f} | "
                 f"{st['luma_mean']:.0f} | {hls} | {', '.join(i['flags']) or '–'} |")
    err = [i for i in infos if i.get("error")]
    if err:
        L += ["", "## Fehler", ""] + [f"- {i['name']}: {i['error']}" for i in err]
    L += ["", "## Duplikate", ""]
    L += [f"- {a} ≈ {b} (Ähnlichkeit {s:.2f})" for a, b, s in dups] or ["- keine"]
    L += ["", "## Legende", "",
          "- **Action**: Motivbewegung (optischer Fluss minus Kamerabewegung), px/s bei 1080 px Breite.",
          "- **Kamera**: globale Bewegung (Schwenk/Wackeln) am Bildmittelpunkt, px/s bei 1080 px.",
          "- **Wackeln**: hochfrequenter Anteil der Kamerabewegung (Abweichung vom 0,5-s-Mittel).",
          "- **Schärfe**: Laplace-Varianz auf dem 320-px-Analysebild (< 20 = unscharf).",
          "- **Luma**: mittlere Helligkeit 0–255 nach HLG/PQ-Tonemapping.",
          "- **Score**: 40 % Action, 20 % Schärfe, 20 % Belichtung, 20 % Ruhe; Abzüge für kurz/quer/Schnitte.",
          "- **Peak**: Zeit der stärksten Motivbewegung im Fenster -> dort den Beat-Hit setzen."]
    with open(os.path.join(outdir, "clips.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    files = draw_sheets(infos, outdir, rows, width) if sheets else []
    return data, files


# ---------------------------------------------------------------- Batch / Manifest

def collect_inputs(paths):
    """Dateien und Ordner (rekursiv) -> sortierte Liste von Videodateien."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for fn in files:
                    if fn.lower().endswith(VIDEO_EXT) and not fn.startswith("."):
                        out.append(os.path.join(root, fn))
        elif os.path.isfile(p):
            out.append(p)
        else:
            log(f"WARNUNG: nicht gefunden: {p}")
    return sorted(dict.fromkeys(out), key=lambda x: (os.path.basename(x), x))


def _describe(info):
    kind = "4K" if max(info['w'], info['h']) >= 3000 else f"{min(info['w'], info['h'])}p"
    return f"{kind} {(info.get('codec') or '?').upper()} {info['hdr'].upper()} {info['fps']:.0f}fps {info['dur']:.1f}s"


def _safe_analyse(path, args, name=None):
    try:
        info = analyse_clip(path, args.fps, args.fenster, args.threads, args.schnell, name=name,
                            thumbs=True)
        log(f"OK  {info['name']:<18} {_describe(info):<32} Analyse {info['analyse_s']:6.1f} s  "
            f"Score {info['score']:3d}  Action Ø {info['stats']['motion_mean']:.0f}  "
            f"{', '.join(info['flags'])}")
        return info
    except Exception as e:  # noqa: BLE001 - ein kaputter Clip soll den Batch nicht stoppen
        log(f"FEHLER {name or os.path.basename(path)}: {e}")
        return {"name": name or os.path.basename(path), "path": os.path.abspath(path), "error": str(e)}


def run_files(paths, args):
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        return list(ex.map(lambda p: _safe_analyse(p, args), paths))


def read_manifest(path, only=None):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2 or not parts[0].strip() or parts[0].startswith("#"):
                continue
            size = int(parts[2]) if len(parts) > 2 and parts[2].strip().isdigit() else None
            rows.append((parts[0].strip(), parts[1].strip(), size))
    if only:
        want = {w.strip().lower() for w in only.split(",") if w.strip()}
        rows = [r for r in rows if r[0].lower() in want or r[1].lower() in want
                or os.path.splitext(r[1])[0].lower() in want]
    return rows


def run_manifest(args):
    rows = read_manifest(args.manifest, args.only)
    if not rows:
        log("Keine Clips im Manifest (Filter --only?).")
        return []
    dl_dir = args.download_dir or tempfile.mkdtemp(prefix="clip_dl_")
    os.makedirs(dl_dir, exist_ok=True)
    seen = {}
    jobs = []
    for did, name, size in rows:
        local = name
        if local.lower() in seen:
            stem, ext = os.path.splitext(name)
            local = f"{stem}__{did[:8]}{ext}"
        seen[local.lower()] = 1
        jobs.append((did, name, size, local))
    log(f"Manifest: {len(jobs)} Clips, Download nach {dl_dir}")

    def work(job):
        did, name, size, local = job
        fp = os.path.join(dl_dir, local)
        t0 = time.time()
        try:
            r = subprocess.run(["curl", "-sS", "-L", "--retry", "2", "-o", fp, DRIVE_URL.format(id=did)],
                               capture_output=True)
            got = os.path.getsize(fp) if os.path.exists(fp) else 0
            if r.returncode != 0 or (size and got != size):
                raise RuntimeError(f"Download fehlgeschlagen ({got} statt {size} Bytes) "
                                   + r.stderr.decode(errors="replace")[:200])
            log(f"DL  {local} {got / 1e6:.1f} MB in {time.time() - t0:.1f} s")
            info = _safe_analyse(fp, args, name=local)
            info["drive_id"] = did
            return info
        except Exception as e:  # noqa: BLE001
            log(f"FEHLER {local}: {e}")
            return {"name": local, "drive_id": did, "error": str(e)}
        finally:
            if not args.behalten and os.path.exists(fp):
                os.remove(fp)

    # max. 2 Originale gleichzeitig auf der Platte
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(2, args.jobs))) as ex:
        return list(ex.map(work, jobs))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Rohclip-Analyse (Action, Kamera, Schärfe, Belichtung, Highlights, Duplikate, Kontaktbogen).")
    ap.add_argument("inputs", nargs="*", help="Clips oder Ordner (MOV/MP4)")
    ap.add_argument("-o", "--out", required=True, help="Ausgabeordner")
    ap.add_argument("--fps", type=float, default=10, help="Analyse-Frames pro Sekunde (Standard 10)")
    ap.add_argument("--jobs", type=int, default=2, help="parallele Clips (Standard 2)")
    ap.add_argument("--threads", type=int, default=0, help="ffmpeg-Threads pro Clip (0 = auto)")
    ap.add_argument("--fenster", type=float, default=FENSTER_DEFAULT,
                    help=f"Highlight-Fensterlänge in s (Standard {FENSTER_DEFAULT} = 2 Beats @ {BPM} BPM)")
    ap.add_argument("--schnell", action="store_true",
                    help="nur Keyframes dekodieren (~8x schneller, Bewegung nur grob)")
    ap.add_argument("--manifest", help="TSV: drive_id<TAB>name<TAB>size_bytes -> laden, analysieren, löschen")
    ap.add_argument("--only", help="Komma-Liste von Namen/IDs aus dem Manifest, z. B. IMG_6166,IMG_3419")
    ap.add_argument("--download-dir", help="Download-Ordner für --manifest (Standard: Temp-Ordner)")
    ap.add_argument("--behalten", action="store_true", help="Downloads nach der Analyse nicht löschen")
    ap.add_argument("--keine-boegen", action="store_true", help="keine Kontaktbögen erzeugen")
    ap.add_argument("--zeilen", type=int, default=6, help="Clips pro Kontaktbogen (Standard 6)")
    ap.add_argument("--breite", type=int, default=1600, help="Breite der Kontaktbögen in px (Standard 1600)")
    args = ap.parse_args(argv)
    if args.threads <= 0:
        args.threads = max(1, (os.cpu_count() or 4) // max(1, args.jobs))
    cv2.setNumThreads(max(1, args.threads))
    if not args.inputs and not args.manifest:
        ap.error("Clips/Ordner oder --manifest angeben")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} nicht gefunden")
    t0 = time.time()
    infos = []
    if args.inputs:
        paths = collect_inputs(args.inputs)
        log(f"{len(paths)} Clips, {args.jobs} parallel, {args.threads} ffmpeg-Threads je Clip, "
            f"{'Schnell-Scan' if args.schnell else f'{args.fps:g} fps'}")
        infos += run_files(paths, args)
    if args.manifest:
        infos += run_manifest(args)
    data, files = write_outputs(infos, args.out, args.fps, args.fenster, not args.keine_boegen,
                                args.zeilen, args.breite)
    n_ok = sum(1 for i in infos if not i.get("error"))
    log(f"Fertig: {n_ok}/{len(infos)} Clips in {time.time() - t0:.1f} s -> {args.out} "
        f"(clips.json, clips.md, {len(files)} Kontaktbogen)")
    if data["duplicates"]:
        for a, b, s in data["duplicates"]:
            log(f"Duplikat: {a} ≈ {b} ({s:.2f})")
    return 0 if n_ok == len(infos) else 1


if __name__ == "__main__":
    sys.exit(main())
