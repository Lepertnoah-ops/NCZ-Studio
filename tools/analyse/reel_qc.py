#!/usr/bin/env python3
"""Reel-QC: prüft ein fertiges Reel (Format, Bild, Beat-Sync, Audio, Loop; Safe-Zones nur als Overlay mit den Instagram-Zonen, YouTube: pipeline/plattform.py check und ui).

Aufruf:
    python3 reel_qc.py REEL.mp4 [--song SONG.mp3] [--song-json song.json] [--src SEK]
                       [--edl edl.json] [-o OUTDIR] [--streng]

    from reel_qc import run_qc
    res = run_qc("reel.mp4", song="song.mp3", outdir="qc_out")   # Dict wie qc.json

- Ohne Song: Beat-Raster aus dem Reel-Ton (librosa + lineare Regression),
  808 = Onsets im Band < 120 Hz, Takt-"1" geschätzt (Clap auf 3).
- --song: Position des Reels im Song per Kreuzkorrelation (samplegenau), außer --src.
- --song-json: Ausgabe von song_analyse.py; Beats/Takte/808 von dort (um src verschoben).
- --edl: geplante Schnitte (shots[].t) gegen erkannte Schnitte.
- --streng: WARNUNG zählt wie FEHLER.

Ausgaben in OUTDIR (Standard: <reel>_qc neben dem Reel):
    qc.json, qc.md, qc_timeline.png, qc_shots.jpg
Exit-Code 0 = kein FEHLER, 1 = mindestens ein FEHLER.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
import traceback
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, find_peaks, resample_poly, sosfiltfilt

FPS = 30.0
FRAME = 1.0 / FPS
SR = 48000
W, H = 270, 480          # Analysegröße (Graustufen)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
OK, WARN, FAIL, INFO = "OK", "WARNUNG", "FEHLER", "INFO"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # tools/ für reel_audio und stil
from stil import STIL  # noqa: E402
MINB = float(STIL["budget"]["min_beats"])   # kürzeste Szene laut stil.json
try:
    from reel_audio import decode as _ra_decode
except Exception:  # pragma: no cover
    _ra_decode = None


# ---------------------------------------------------------------- Hilfen
class Checks:
    def __init__(self):
        self.items = []

    def add(self, gruppe, name, status, wert, detail=""):
        self.items.append({"gruppe": gruppe, "check": name, "status": status,
                           "wert": wert, "detail": detail})


def decode_audio(path):
    """float64 Stereo 48 kHz (ffmpeg-Decode, gleiche Zeitachse wie reel_audio.py)."""
    if _ra_decode is not None:
        try:
            return np.asarray(_ra_decode(str(path)), dtype=np.float64)
        except Exception:
            pass
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-map", "0:a:0",
                          "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def video_pts(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "packet=pts", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout
    v = []
    for ln in out.split():
        ln = ln.strip().strip(",")
        if ln and ln != "N/A":
            try:
                v.append(int(ln))
            except ValueError:
                pass
    return np.array(sorted(v), dtype=np.int64)


def atom_order(path):
    order, pos, total = [], 0, os.path.getsize(path)
    with open(path, "rb") as f:
        while pos < total and len(order) < 64:
            f.seek(pos)
            hdr = f.read(16)
            if len(hdr) < 8:
                break
            sz = int.from_bytes(hdr[:4], "big")
            typ = hdr[4:8].decode("latin1")
            if sz == 1:
                sz = int.from_bytes(hdr[8:16], "big")
            elif sz == 0:
                sz = total - pos
            order.append(typ)
            if sz < 8:
                break
            pos += sz
    return order


def blocks_db(x, ms=100):
    b = int(SR * ms / 1000)
    k = len(x) // b
    rms = np.sqrt(np.mean(x[: k * b].reshape(k, b, -1) ** 2, axis=(1, 2)))
    return 20 * np.log10(rms + 1e-12)


def runs(mask, min_len=1):
    """[(start, ende_exkl)] zusammenhängender True-Bereiche."""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(np.int8))
    st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    return [(int(a), int(b)) for a, b in zip(st, en) if b - a >= min_len]


def env_rms(x, win, hop):
    """Zentrierte RMS-Hüllkurve (Fenster win, Hop hop Samples)."""
    c = np.concatenate([[0.0], np.cumsum(x * x)])
    n = len(x) // hop
    cen = np.arange(n) * hop
    a = np.clip(cen - win // 2, 0, len(x))
    b = np.clip(cen + win // 2, 0, len(x))
    return np.sqrt((c[b] - c[a]) / np.maximum(b - a, 1))


def novelty(x, lo=None, hi=None):
    """Positive log-Ableitung der Bandhüllkurve (1-ms-Raster), über 9 ms summiert."""
    if hi and not lo:
        sos = butter(4, hi, "low", fs=SR, output="sos")
    else:
        sos = butter(4, [lo, hi], "band", fs=SR, output="sos")
    y = sosfiltfilt(sos, x)
    rms = env_rms(y, int(0.010 * SR), SR // 1000)
    floor = rms.max() * 10 ** (-50 / 20) + 1e-9
    L = np.log(rms + floor)
    d = np.maximum(np.diff(L, prepend=L[0]), 0)
    return uniform_filter1d(d, 9) * 9


def onsets_808(mono):
    s = novelty(mono, hi=120)
    pk, pr = find_peaks(s, height=0.6, distance=90)   # Log-Anstieg über 9 ms
    return pk / 1000.0, pr["peak_heights"], s


def fit_grid(bt):
    """Robuste Regression über Beat-Zeiten -> (Periode, Phase, Residuen der Inlier).

    Erst Periode/Phase per Phasen-Kohärenz (Kreismittel), dann lineare Regression
    nur über Beats, die < 40 ms am Raster liegen (Tempo-Aussetzer im Intro stören nicht)."""
    bt = np.asarray(bt, float)
    p0 = float(np.median(np.diff(bt)))
    pers = np.linspace(p0 * 0.97, p0 * 1.03, 1201)
    z = np.exp(2j * np.pi * bt[None, :] / pers[:, None]).mean(axis=1)
    j = int(np.argmax(np.abs(z)))
    per = float(pers[j])
    ph = float(np.angle(z[j]) / (2 * np.pi) * per)
    keep = np.ones(len(bt), bool)
    for lim in (0.04, 0.03, 0.02):
        k = np.round((bt - ph) / per)
        res = bt - (ph + per * k)
        keep = np.abs(res) < lim
        if keep.sum() < 4:
            break
        A = np.vstack([np.ones(keep.sum()), k[keep]]).T
        (ph, per), *_ = np.linalg.lstsq(A, bt[keep], rcond=None)
    k = np.round((bt - ph) / per)
    res = bt - (ph + per * k)
    return float(per), float(ph), res[np.abs(res) < 0.02]


def beat_track(mono):
    """Beat-Raster aus Audio: librosa beat_track + robuste Regression; Phase danach an den
    808-Onsets nachgezogen (librosa-Beats liegen typisch 20–30 ms zu spät)."""
    import librosa
    y = resample_poly(mono, 147, 320).astype(np.float32)          # 48k -> 22.05k
    _, bt = librosa.beat.beat_track(y=y, sr=22050, hop_length=256, units="time")
    if len(bt) < 8:
        raise RuntimeError("zu wenige Beats erkannt")
    per, ph, res = fit_grid(bt)
    if per > 0.6:                                                    # halbes Tempo erkannt
        per /= 2
    t8, s8, _ = onsets_808(mono)
    strong = t8[s8 >= np.median(s8)] if len(s8) else t8
    d = np.array([near(t, ph + per * np.round((t - ph) / per) + np.array([0.0])) for t in strong])
    d = d[np.abs(d) < 0.06]
    corr = float(np.median(d)) if len(d) >= 4 else 0.0
    return per, (ph + corr) % per, res, corr


def downbeat_guess(mono, per, ph, dur):
    """Takt-1 schätzen: Clap/Snare (1,5–6 kHz) liegt im Drill auf Zählzeit 3."""
    s = novelty(mono, 1500, 6000)
    k0, k1 = int(math.ceil(-ph / per)), int((dur - ph) / per)
    score = np.zeros(4)
    for k in range(k0, k1 + 1):
        i = int(round((ph + k * per) * 1000))
        seg = s[max(i - 40, 0): i + 40]
        if len(seg):
            score[k % 4] += seg.max()
    j = int(np.argmax(score))
    return (j - 2) % 4, score.tolist()


def find_src(reel_m, song_m):
    """Position des Reel-Tons im Song: grob 4 kHz (NCC per FFT), fein samplegenau bei 48 kHz."""
    from scipy.signal import correlate
    r = resample_poly(reel_m, 1, 12)
    s = resample_poly(song_m, 1, 12)
    if len(r) > len(s):
        raise RuntimeError("Reel länger als Song")
    c = correlate(s, r, mode="valid", method="fft")
    cs = np.concatenate([[0.0], np.cumsum(s * s)])
    e = np.sqrt(cs[len(r):] - cs[:-len(r)]) * np.linalg.norm(r) + 1e-9
    ncc = c / e
    lag = int(np.argmax(ncc))
    n = min(len(reel_m), 10 * SR)
    ref = reel_m[:n]
    best, bl = -1e9, lag * 12
    for L in range(max(lag * 12 - 36, 0), lag * 12 + 37):
        seg = song_m[L:L + n]
        if len(seg) < n:
            continue
        v = float(np.dot(ref, seg))
        if v > best:
            best, bl = v, L
    return bl / SR, float(ncc[lag])


def near(t, grid):
    """Abstand zum nächsten Rasterpunkt (vorzeichenbehaftet, t - Raster)."""
    grid = np.asarray(grid)
    if len(grid) == 0:
        return float("nan")
    i = int(np.argmin(np.abs(grid - t)))
    return float(t - grid[i])


def fmt_ms(x):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 1000:+.1f} ms"


# ---------------------------------------------------------------- Format
def check_format(qc, res, reel):
    G = "Format"
    info = probe(reel)
    vs = next((s for s in info["streams"] if s.get("codec_type") == "video"
               and not s.get("disposition", {}).get("attached_pic")), None)
    au = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    fmt = info.get("format", {})
    f = {}
    res["format"] = f
    if vs is None:
        qc.add(G, "Videospur", FAIL, "fehlt")
        return None, au
    w, h = vs.get("width"), vs.get("height")
    f.update(width=w, height=h, codec=vs.get("codec_name"), profile=vs.get("profile"),
             pix_fmt=vs.get("pix_fmt"))
    qc.add(G, "Auflösung", OK if (w, h) == (1080, 1920) else FAIL, f"{w}x{h}", "Soll 1080x1920")

    r, a = vs.get("r_frame_rate", "0/1"), vs.get("avg_frame_rate", "0/1")
    try:
        af = float(Fraction(a))
    except (ZeroDivisionError, ValueError):
        af = 0.0
    tb = Fraction(vs.get("time_base", "1/15360"))
    pts = video_pts(reel)
    irr = dup = 0
    if len(pts) > 2:
        d = np.diff(pts)
        exp = float(1 / (FPS * tb))
        irr = int(np.sum(np.abs(d - exp) > max(1.0, 0.02 * exp)))
        dup = int(np.sum(d == 0))
    f.update(r_frame_rate=r, avg_frame_rate=a, pts_unregelmaessig=irr, pts_doppelt=dup,
             frames=int(len(pts)))
    ok = r == "30/1" and abs(af - 30) < 0.03 and irr == 0 and dup == 0
    qc.add(G, "Bildrate 30 fps konstant", OK if ok else FAIL,
           f"r={r}, avg={a}, Sprünge={irr}, doppelt={dup}", "r_frame_rate 30/1, keine Lücken")

    codec, prof = vs.get("codec_name"), vs.get("profile")
    st = OK if codec == "h264" and prof == "High" else (WARN if codec == "h264" else FAIL)
    qc.add(G, "Codec H.264 High", st, f"{codec} {prof}")
    qc.add(G, "Pixelformat yuv420p", OK if vs.get("pix_fmt") == "yuv420p" else FAIL,
           str(vs.get("pix_fmt")))
    cols = [vs.get("color_space"), vs.get("color_transfer"), vs.get("color_primaries")]
    f["farbe"] = cols
    qc.add(G, "Farb-Tags bt709", OK if all(c == "bt709" for c in cols) else WARN,
           "/".join(str(c) for c in cols), "space/transfer/primaries")

    vdur = float(vs.get("duration") or fmt.get("duration") or 0)
    br = vs.get("bit_rate")
    br = float(br) if br else (os.path.getsize(reel) * 8 / max(vdur, 1e-6))
    f["video_bitrate"] = br
    st = FAIL if br > 25e6 else (WARN if br < 8e6 else OK)
    qc.add(G, "Video-Bitrate", st, f"{br / 1e6:.1f} Mbit/s", "Ziel ~18, max 25")

    if au is None:
        qc.add(G, "Audiospur", FAIL, "fehlt")
    else:
        sr = int(au.get("sample_rate", 0))
        acod = au.get("codec_name")
        st = OK if acod == "aac" and sr == 48000 else (WARN if acod == "aac" else FAIL)
        qc.add(G, "Audio AAC 48 kHz", st, f"{acod} {sr} Hz {au.get('channels')} ch "
               f"{float(au.get('bit_rate', 0)) / 1000:.0f} kbit/s")
        adur = float(au.get("duration") or 0)
        off = float(au.get("start_time", 0) or 0) - float(vs.get("start_time", 0) or 0)
        dd = adur - vdur
        f.update(video_dauer=vdur, audio_dauer=adur, audio_start_versatz=off)
        st = OK if abs(dd) < FRAME and abs(off) < FRAME else (WARN if abs(dd) < 2 * FRAME else FAIL)
        qc.add(G, "Dauer Audio = Video", st, f"Diff {dd * 1000:+.1f} ms, Start {off * 1000:+.1f} ms",
               "< 1 Frame")
    order = [o for o in atom_order(reel) if o in ("moov", "mdat")]
    fs_ok = len(order) >= 2 and order[0] == "moov"
    f["atome"] = order
    qc.add(G, "Faststart (moov vor mdat)", OK if fs_ok else WARN, " → ".join(order))
    size = os.path.getsize(reel)
    f["dateigroesse"] = size
    qc.add(G, "Dateigröße", OK if size < 250e6 else WARN, f"{size / 1e6:.1f} MB",
           f"{vdur:.2f} s")
    return vs, au


# ---------------------------------------------------------------- Bild
def analyse_frames(reel):
    """Einmal dekodieren: Differenz, Helligkeit, Skalierung (LK-Flow), Mini-Graubilder, JPEG-Thumbs."""
    import cv2
    cmd = ["ffmpeg", "-v", "error", "-threads", "2", "-i", str(reel), "-map", "0:v:0",
           "-fps_mode", "passthrough", "-vf", f"scale={W}:{H}:flags=area",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    fs = W * H * 3
    diff, bright, logs, inl, small, thumbs = [], [], [], [], [], []
    prev = None
    while True:
        buf = p.stdout.read(fs)
        if len(buf) < fs:
            break
        rgb = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        bright.append(float(g.mean()))
        small.append(cv2.resize(g, (W // 2, H // 2), interpolation=cv2.INTER_AREA))
        thumbs.append(cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                                   [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes())
        if prev is None:
            diff.append(0.0)
            logs.append(0.0)
            inl.append(0.0)
        else:
            diff.append(float(cv2.absdiff(g, prev).mean()))
            ls, ir = 0.0, 0.0
            try:
                pts = cv2.goodFeaturesToTrack(prev, maxCorners=160, qualityLevel=0.01,
                                              minDistance=9, blockSize=7)
                if pts is not None and len(pts) >= 12:
                    nx, stt, _ = cv2.calcOpticalFlowPyrLK(prev, g, pts, None, winSize=(21, 21),
                                                          maxLevel=3)
                    ok = stt.ravel() == 1
                    if ok.sum() >= 10:
                        M, mask = cv2.estimateAffinePartial2D(
                            pts[ok], nx[ok], method=cv2.RANSAC, ransacReprojThreshold=1.5)
                        if M is not None:
                            ls = math.log(max(math.hypot(M[0, 0], M[1, 0]), 1e-6))
                            ir = float(mask.sum()) / len(pts)
            except cv2.error:
                pass
            logs.append(ls)
            inl.append(ir)
        prev = g
    p.wait()
    return (np.array(diff), np.array(bright), np.array(logs), np.array(inl), small, thumbs)


def detect_visual(diff, bright, logs, inl, small):
    n = len(diff)
    # --- harte Schnitte: lokales Maximum, deutlich über den Nachbarn
    cand = []
    for i in range(1, n):
        win = diff[max(i - 2, 0): i + 3]
        base = np.median(diff[max(i - 6, 0): max(i - 1, 1)]) if i > 1 else 0.0
        if diff[i] >= win.max() and diff[i] > 4.0 and diff[i] / (base + 0.5) >= 1.8:
            cand.append(i)
    cuts, flashes, punches = [], [], []
    # --- Flashes: Helligkeitssprung, der in ~5 Frames abklingt
    for i in range(1, n - 2):
        jump = bright[i] - bright[i - 1]
        if jump < 15 or bright[i] < bright[min(i + 1, n - 1)] - 1:
            continue
        j = min(i + 6, n - 1)
        if bright[i] - bright[j] > 0.5 * jump and bright[min(i + 2, n - 1)] < bright[i]:
            flashes.append(i)

    if n > 6 and bright[0] - bright[5] > 15 and bright[1] <= bright[0] + 1:
        flashes.insert(0, 0)

    def mad(a, b):
        x = small[a].astype(np.float32)
        y = small[b].astype(np.float32)
        return float(np.abs((x - x.mean()) - (y - y.mean())).mean())

    trans = []
    for i in cand:
        # Animierter Übergang (Plateau hoher Differenzen, z. B. Split-Expand) statt hartem Schnitt
        flash_here = i in flashes or (i + 1) in flashes
        if 0 < i < n - 1 and not flash_here and min(diff[i - 1], diff[i + 1]) > 0.6 * diff[i]:
            a_ = i
            while a_ > max(i - 8, 0) and diff[a_ - 1] > 0.5 * diff[i]:
                a_ -= 1
            b_ = i
            while b_ < min(i + 8, n - 1) and diff[b_ + 1] > 0.5 * diff[i]:
                b_ += 1
            trans.append((a_, b_, i))
            continue
        # Kontinuierliche Bewegung (Punch/Schwenk) statt Schnitt: Flow passt gut
        if inl[i] >= 0.6 and abs(logs[i]) < 0.35:
            continue
        # Flash ohne Schnitt: Inhalt vor/nach dem Abklingen gleich
        if i in flashes or (i - 1) in flashes:
            j = min(i + 7, n - 1)
            if mad(i - 1, j) < 1.5 * mad(max(i - 9, 0), i - 1) + 2:
                continue
        if i < 3 or (cuts and i - cuts[-1] < 3):   # Effekte am Start / Doppel-Treffer
            continue
        cuts.append(i)
    cutset = set(cuts)
    # --- Zoom-Punches: Skalensprung, der über 0,1–0,3 s abklingt
    for i in range(1, n - 3):
        if i in cutset or (i - 1) in cutset:
            continue
        if logs[i] > 0.03 and inl[i] > 0.3 and logs[i] >= logs[max(i - 1, 0)] \
                and logs[i] >= logs[min(i + 1, n - 1)]:
            back = logs[i + 1: i + 10].sum()
            if back < -0.3 * logs[i]:
                punches.append({"frame": i, "t": i / FPS, "art": "Mitte", "skala": float(logs[i])})
    for c in cuts:
        seg = logs[c + 1: c + 9]
        if len(seg) >= 6 and seg.sum() < -0.04 and seg[0] < -0.006 and abs(seg[0]) > abs(seg[-1]):
            punches.append({"frame": c, "t": c / FPS, "art": "Schnitt", "skala": float(-seg.sum())})
    punches.sort(key=lambda p: p["frame"])
    black = runs(bright < 8)
    frozen = runs(np.concatenate([[False], diff[1:] < 0.05]), 3)
    frozen = [(a - 1, b) for a, b in frozen]
    # Übergangs-Kandidaten direkt nach/vor einem harten Schnitt = Punch/Flash-Nachlauf
    trans = [t_ for t_ in trans if min((abs(t_[2] - c) for c in cuts), default=99) > 6]
    return cuts, flashes, punches, black, frozen, trans


# ---------------------------------------------------------------- Bilder
def shot_sheet(path, thumbs, segs, per, title):
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    cw, ch, cols, lab = 216, 384, 6, 26
    n = len(segs)
    rows = max(1, math.ceil(n / cols))
    top = 54
    img = Image.new("RGB", (cols * (cw + 8) + 8, top + rows * (ch + lab + 8) + 8), (24, 24, 24))
    dr = ImageDraw.Draw(img)
    try:
        f1, f2 = ImageFont.truetype(FONT, 18), ImageFont.truetype(FONT, 14)
    except OSError:
        f1 = f2 = ImageFont.load_default()
    dr.text((8, 6), title, fill=(240, 240, 240), font=f1)
    dr.text((8, 30), "rot = IG-UI (oben 10 %, unten 20 %, rechts 10 %) · cyan = 3:4-Profilraster",
            fill=(170, 170, 170), font=f2)
    for k, (a, b) in enumerate(segs):
        m = min((a + b) // 2, len(thumbs) - 1)
        bgr = cv2.imdecode(np.frombuffer(thumbs[m], np.uint8), cv2.IMREAD_COLOR)
        th = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).resize((cw, ch), Image.LANCZOS)
        ov = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        red = (255, 40, 40, 80)
        od.rectangle([0, 0, cw, int(0.10 * ch)], fill=red)
        od.rectangle([0, int(0.80 * ch), cw, ch], fill=red)
        od.rectangle([int(0.90 * cw), int(0.10 * ch), cw, int(0.80 * ch)], fill=red)
        y1, y2 = int(0.125 * ch), int(0.875 * ch)
        od.rectangle([0, y1, cw - 1, y2], outline=(0, 230, 255, 230), width=2)
        th = Image.alpha_composite(th.convert("RGBA"), ov).convert("RGB")
        x = 8 + (k % cols) * (cw + 8)
        y = top + (k // cols) * (ch + lab + 8)
        img.paste(th, (x, y))
        kurz = bool(per) and (b - a) / FPS < 2 * per - FRAME - 1e-3
        txt = f"#{k + 1}  {a / FPS:.2f} s  " + (f"{(b - a) / FPS / per:.1f} Beats" if per
                                                 else f"{b - a} Frames")
        dr.text((x + 2, y + ch + 4), txt, fill=(255, 120, 120) if kurz else (230, 230, 230), font=f2)
    img.save(path, quality=88)


def timeline_png(path, mono, dur, grid, cuts, punches, flashes, o808, problems, diff, bright,
                 black, frozen, trans, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(18, 6.5), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1.3]})
    hop = SR // 200
    n = len(mono) // hop
    e = np.abs(mono[: n * hop]).reshape(n, hop).max(axis=1)
    t = (np.arange(n) + 0.5) * hop / SR
    ax.fill_between(t, -e, e, color="#9aa7b4", lw=0)
    for k, tb, bar in grid:
        ax.axvline(tb, color="#333333" if bar else "#bbbbbb", lw=1.4 if bar else 0.5, zorder=1)
    for c in cuts:
        ax.axvline(c / FPS, color="#d62728", lw=1.6, zorder=3)
    for p in punches:
        ax.plot(p["t"], 0.93, marker="v", color="#ff7f0e", ms=9, zorder=4)
    for a_, b_, _ in trans:
        ax.axvspan(a_ / FPS, (b_ + 1) / FPS, color="#9467bd", alpha=0.25, zorder=2)
    for fl in flashes:
        ax.plot(fl / FPS, 0.80, marker="*", color="#e6b800", ms=12, zorder=4)
    for o in o808:
        ax.plot([o, o], [-1.0, -0.82], color="#1f4fd6", lw=2, zorder=4)
    for tp, txt in problems:
        ax.plot(tp, 1.02, marker="X", color="#b00020", ms=10, zorder=5, clip_on=False)
    ax.set_ylim(-1.05, 1.08)
    ax.set_xlim(0, dur)
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_yticks([])
    from matplotlib.lines import Line2D
    leg = [Line2D([], [], color="#d62728", lw=2, label="Schnitt"),
           Line2D([], [], color="#ff7f0e", marker="v", ls="", label="Punch"),
           Line2D([], [], color="#e6b800", marker="*", ls="", ms=10, label="Flash"),
           Line2D([], [], color="#1f4fd6", lw=2, label="808"),
           Line2D([], [], color="#333333", lw=1.4, label="Takt"),
           Line2D([], [], color="#9467bd", lw=6, alpha=0.4, label="Übergang"),
           Line2D([], [], color="#b00020", marker="X", ls="", label="Problem")]
    ax.legend(handles=leg, loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=7, fontsize=8,
              frameon=False)
    tf = np.arange(len(diff)) / FPS
    bx.plot(tf, diff, color="#222222", lw=0.8, label="Bilddifferenz")
    bx.plot(tf, bright / 4, color="#8c6d31", lw=0.8, label="Helligkeit/4")
    for a, b in black:
        bx.axvspan(a / FPS, b / FPS, color="black", alpha=0.35)
    for a, b in frozen:
        bx.axvspan(a / FPS, b / FPS, color="#1f77b4", alpha=0.25)
    for c in cuts:
        bx.axvline(c / FPS, color="#d62728", lw=0.8, alpha=0.6)
    bx.legend(loc="upper right", fontsize=8, ncol=2)
    bx.set_xlabel("Zeit im Reel [s]  (blau = Standbild, schwarz = Schwarzbild)")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


# ---------------------------------------------------------------- Hauptablauf
def run_qc(reel, song=None, song_json=None, src=None, edl=None, outdir=None, streng=False,
           quiet=False):
    """Führt alle Checks aus, schreibt qc.json/qc.md/PNG/JPG und gibt das Ergebnis-Dict zurück."""
    t0 = time.time()
    reel = Path(reel)
    outdir = Path(outdir) if outdir else reel.with_name(reel.stem + "_qc")
    outdir.mkdir(parents=True, exist_ok=True)
    qc = Checks()
    res = {"reel": str(reel), "song": str(song) if song else None,
           "song_json": str(song_json) if song_json else None,
           "edl": str(edl) if edl else None, "streng": bool(streng)}
    problems = []

    def guard(name, fn, status=FAIL):
        try:
            return fn()
        except Exception as ex:  # Abschnitt fehlgeschlagen -> melden, weiter
            if os.environ.get("QC_DEBUG"):
                traceback.print_exc(file=sys.stderr)
            else:
                print(f"{name}: {type(ex).__name__}: {ex}", file=sys.stderr)
            qc.add("Analyse", name, status, f"Abbruch: {type(ex).__name__}: {ex}")
            return None

    fmt = guard("Format", lambda: check_format(qc, res, reel)) or (None, None)
    vdur = res.get("format", {}).get("video_dauer") or 0.0

    # ---- Audio laden
    x = guard("Audio dekodieren", lambda: decode_audio(reel))
    if x is None or len(x) == 0:
        x = np.zeros((int(max(vdur, 1) * SR), 2))
    mono = x.mean(axis=1)
    adur = len(x) / SR
    dur = vdur or adur
    a_off = res.get("format", {}).get("audio_start_versatz", 0.0) or 0.0

    # ---- Song / Raster
    sj = None
    if song_json:
        sj = json.loads(Path(song_json).read_text())
        if not song and sj.get("file") and Path(sj["file"]).exists():
            song = sj["file"]
    songx = None
    if song:
        songx = guard("Song dekodieren", lambda: decode_audio(song))
    g = {"quelle": None}
    res["raster"] = g
    if src is None and songx is not None:
        r = guard("Songposition", lambda: find_src(mono, songx.mean(axis=1)))
        if r:
            src, conf = r
            g["src_korrelation"] = round(conf, 4)
            st = OK if conf > 0.8 else (WARN if conf > 0.5 else FAIL)
            qc.add("Beat-Sync", "Songposition gefunden", st, f"src={src:.4f} s (NCC {conf:.3f})")
    if src is None and sj is not None:
        # nur song.json: 808-Folgen gegeneinander ausrichten
        def align808():
            ro, _, _ = onsets_808(mono)
            so = np.array([o["t"] for o in sj.get("onsets", {}).get("kick808", [])])
            best = (0, 0.0)
            for a in ro[:6]:
                for b in so:
                    off = b - a
                    m = sum(np.min(np.abs(so - (r_ + off))) < 0.015 for r_ in ro)
                    if m > best[0]:
                        best = (m, off)
            return best[1]
        src = guard("Songposition (808)", align808)
    g["src"] = src
    per = ph = None
    dboff = 0
    bar_known = False
    o808 = np.array([])
    o808_alle = None
    if sj is not None and src is not None:
        per, sph = float(sj["beat_period"]), float(sj["beat_phase"])
        ph = sph - src
        dboff = int(sj.get("downbeat_offset", 0))
        bar_known = True
        g["quelle"] = "song.json"
        k8 = sj.get("onsets", {}).get("kick808", [])
        o808_alle = np.array([o["t"] - src for o in k8])
        o808_alle = o808_alle[(o808_alle >= -0.05) & (o808_alle <= adur + 0.05)] + a_off
        o808 = np.array([o["t"] - src for o in k8 if "nachschlag" not in str(o.get("art", ""))])
        o808 = o808[(o808 >= -0.05) & (o808 <= adur + 0.05)]
        g["bpm"] = float(sj.get("bpm", 60 / per))
    elif songx is not None and src is not None:
        def songgrid():
            sm = songx.mean(axis=1)
            p_, h_, rs, cr = beat_track(sm)
            d_, sc = downbeat_guess(sm, p_, h_, len(sm) / SR)
            g["phase_korrektur_808_ms"] = round(cr * 1000, 1)
            return p_, h_, rs, d_, sc
        r = guard("Beat-Raster Song", songgrid)
        if r:
            per, sph, rs, dboff, sc = r
            ph = sph - src
            g.update(quelle="Song (librosa, geschätzt)", residuen_ms_max=float(np.abs(rs).max() * 1000),
                     residuen_ms_rms=float(np.sqrt(np.mean(rs ** 2)) * 1000), downbeat_score=sc)
            g["bpm"] = 60 / per
    if per is None:
        def reelgrid():
            p_, h_, rs, cr = beat_track(mono)
            d_, sc = downbeat_guess(mono, p_, h_, adur)
            g["phase_korrektur_808_ms"] = round(cr * 1000, 1)
            return p_, h_, rs, d_, sc
        r = guard("Beat-Raster Reel", reelgrid, WARN)   # kein Raster -> Beat-Checks entfallen
        if r:
            per, ph, rs, dboff, sc = r
            g.update(quelle="Reel-Ton (librosa, geschätzt)",
                     residuen_ms_max=float(np.abs(rs).max() * 1000),
                     residuen_ms_rms=float(np.sqrt(np.mean(rs ** 2)) * 1000), downbeat_score=sc)
            g["bpm"] = 60 / per
    if len(o808) == 0:
        t8, s8, _ = onsets_808(mono)
        o808 = t8
        g["808_quelle"] = "Reel-Ton (< 120 Hz)"
    else:
        g["808_quelle"] = "song.json"
    o808 = o808 + a_off          # Audio-Zeit -> Video-Zeit
    if o808_alle is None:
        o808_alle = o808
    grid, beats, halves = [], np.array([]), np.array([])
    if per:
        g.update(periode=per, phase_im_reel=ph, downbeat_offset=dboff)
        if "residuen_ms_max" in g:
            st = OK if g["residuen_ms_rms"] < 12 else WARN
            qc.add("Beat-Sync", "Beat-Raster", st,
                   f"{60 / per:.2f} BPM, Periode {per:.5f} s, Residuen RMS "
                   f"{g['residuen_ms_rms']:.1f} ms / max {g['residuen_ms_max']:.1f} ms",
                   g["quelle"] + f", Phase an 808 {g.get('phase_korrektur_808_ms', 0):+.1f} ms")
        else:
            qc.add("Beat-Sync", "Beat-Raster", OK, f"{60 / per:.2f} BPM, Periode {per:.5f} s",
                   g["quelle"])
        k0, k1 = int(math.floor((-ph - per) / per)), int(math.ceil((dur - ph + per) / per))
        for k in range(k0, k1 + 1):
            tb = ph + k * per + a_off
            grid.append((k, tb, (k - dboff) % 4 == 0))
        beats = np.array([t for _, t, _ in grid])
        halves = np.sort(np.concatenate([beats, beats + per / 2]))
        if src is not None:
            kk = -ph / per                    # Beat-Index des Reel-Starts im Song (ph = Songphase - src)
            ki = int(round(kk))
            bar = (ki - dboff) // 4           # Takt 0 = erste Eins im Song (Notation T<Takt>.<Schlag> wie song_analyse)
            bib = (ki - dboff) % 4 + 1
            pos = {"beat_index": round(kk, 3), "takt": bar, "zaehlzeit": bib,
                   "versatz_zum_beat_ms": round((kk - ki) * per * 1000, 1)}
            if sj is not None:
                for sec in sj.get("sections", []):
                    if sec.get("start", 0) - 0.05 <= src < sec.get("end", 0):
                        pos["section"] = sec.get("label")
            g["songposition"] = pos
            qc.add("Beat-Sync", "Position im Song", INFO,
                   f"src {src:.4f} s = T{bar}.{bib} ({pos['versatz_zum_beat_ms']:+.1f} ms)"
                   + (f", {pos.get('section')}" if pos.get("section") else ""))
    res["dauer"] = {"video": vdur, "audio": adur, "beats": (dur / per) if per else None}

    # ---- Bildanalyse
    fr = guard("Bildanalyse", lambda: analyse_frames(reel))
    cuts, flashes, punches, black, frozen, segs, trans = [], [], [], [], [], [], []
    thumbs, diff, bright = [], np.zeros(1), np.zeros(1)
    if fr:
        diff, bright, logs, inl, small, thumbs = fr
        vis = guard("Schnitterkennung", lambda: detect_visual(diff, bright, logs, inl, small))
        if vis:
            cuts, flashes, punches, black, frozen, trans = vis
        del small
        nfr = len(diff)
        tr_b = [p_ for _, _, p_ in trans if min((abs(p_ - c) for c in cuts), default=99) > 6]
        bounds = sorted(set([0] + cuts + tr_b + [nfr]))   # Übergang = Szenenwechsel (fern von Schnitten)
        segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
        G = "Bild"
        if black:
            longest = max(b - a for a, b in black)
            st = FAIL if longest >= 3 else WARN
            qc.add(G, "Schwarzbilder", st, f"{sum(b - a for a, b in black)} Frames",
                   ", ".join(f"{a / FPS:.2f}–{b / FPS:.2f} s" for a, b in black[:8]))
            problems += [(a / FPS, "Schwarz") for a, b in black]
        else:
            qc.add(G, "Schwarzbilder", OK, "0 Frames", "Mittelwert < 8")
        if frozen:
            planned = []
            if edl:
                try:
                    shots = json.loads(Path(edl).read_text()).get("shots", [])
                    for i_, s_ in enumerate(shots):
                        if str(s_.get("mode", "")).lower().startswith("freeze"):
                            t1 = shots[i_ + 1]["t"] if i_ + 1 < len(shots) else dur
                            planned.append((s_["t"], t1))
                except Exception:
                    pass
            unplanned = [(a, b) for a, b in frozen
                         if not any(pa - 0.1 <= a / FPS and b / FPS <= pb + 0.1 for pa, pb in planned)]
            st = WARN if unplanned else OK
            qc.add(G, "Standbilder", st, f"{len(frozen)} Bereich(e)"
                   + (f", {len(frozen) - len(unplanned)} geplant (EDL freeze)" if planned else ""),
                   ", ".join(f"{a / FPS:.2f}–{b / FPS:.2f} s" for a, b in frozen[:8]))
            problems += [(a / FPS, "Standbild") for a, b in unplanned]
        else:
            qc.add(G, "Standbilder", OK, "keine", "Diff < 0,05 über ≥ 3 Frames")
        qc.add(G, "Schnitte / Punches / Flashes", INFO,
               f"{len(cuts)} Schnitte, {len(punches)} Punches, {len(flashes)} Flashes, "
               f"{len(trans)} Übergänge",
               ("animierte Übergänge (kein harter Schnitt): " + ", ".join(
                   f"{a_ / FPS:.2f}–{(b_ + 1) / FPS:.2f} s" for a_, b_, _ in trans)) if trans else "")
        if per:
            lens = [(b - a) / FPS / per for a, b in segs]
            short = [(i, a, l) for i, ((a, b), l) in enumerate(zip(segs, lens))
                     if (b - a) / FPS < MINB * per - FRAME - 1e-3]   # Mindestlänge minus Frame-Rundung
            st = WARN if short else OK
            qc.add(G, f"Szenen ≥ {MINB:g} Beats", st,
                   f"kürzeste {min(lens):.2f} Beats" if lens else "–",
                   (f"keine neue Szene unter {MINB:g} Beats: " + ", ".join(
                       f"#{i + 1} @{a / FPS:.2f} s ({l:.2f})" for i, a, l in short)) if short else "")
            problems += [(a / FPS, "kurz") for i, a, l in short]
            beats_total = dur / per
            per16 = len(segs) * 64.0 / beats_total if beats_total else 0
            # Szenenlänge folgt der Aktion (ganze Wiederholung, ganzer Sprung): kein Richtwert, nur Info
            lo, hi = STIL["budget"]["segmente_16"]
            qc.add(G, "Szenen pro 16 Takte", INFO, f"{per16:.1f}", f"nur Info (Stil-Richtwert {lo}–{hi})")
            res["szenen"] = [{"n": i + 1, "start": a / FPS, "frames": b - a,
                              "beats": round((b - a) / FPS / per, 3)} for i, (a, b) in enumerate(segs)]
        # ---- Beat-Sync der Schnitte/Punches
        plan_fr = None
        if edl:
            try:
                plan_fr = [int(round(s_["t"] * FPS)) for s_ in
                           json.loads(Path(edl).read_text()).get("shots", [])]
            except Exception:
                plan_fr = None

        def unplanned(fr_):
            # mit EDL: Treffer ohne geplanten Schnitt = vermutlich Effekt/Übergang
            return plan_fr is not None and min((abs(fr_ - p_) for p_ in plan_fr), default=99) > 2

        def sync_status(lst):
            hard = [o for f_, o in lst if not unplanned(f_)]
            mx_h = max((abs(o) for o in hard), default=0.0)
            mx = max(abs(o) for _, o in lst)
            if mx <= FRAME + 1e-3:
                return OK
            return WARN if mx_h <= 1.5 * FRAME else FAIL

        if per:
            G = "Beat-Sync"
            offs = [(c, c / FPS, near(c / FPS, halves)) for c in cuts]
            if offs:
                mx = max(abs(o) for _, _, o in offs)
                st = sync_status([(c, o) for c, _, o in offs])
                bad = [(c, t, o) for c, t, o in offs if abs(o) > FRAME + 1e-3]
                qc.add(G, "Schnitte auf Beat/Halbbeat", st,
                       f"max {mx * 1000:.1f} ms = {mx * FPS:.2f} Frames ({len(offs)} Schnitte)",
                       ", ".join(f"{t:.2f} s ({o * 1000:+.0f} ms"
                                 + (", nicht in EDL: Effekt?" if unplanned(c) else "") + ")"
                                 for c, t, o in bad[:8]))
                problems += [(t, "Schnitt off-beat") for _, t, o in bad]
            if punches:
                po = [(p["frame"], near(p["t"], halves)) for p in punches]
                mx = max(abs(o) for _, o in po)
                st = sync_status(po)
                qc.add(G, "Punches auf Beat/Halbbeat", st, f"max {mx * 1000:.1f} ms ({len(po)} Punches)",
                       ", ".join(f"{f_ / FPS:.2f} s ({o * 1000:+.0f} ms)" for f_, o in po
                                 if abs(o) > FRAME + 1e-3))
            res["schnitte"] = [{"frame": c, "t": round(t, 4), "beat_versatz_ms": round(o * 1000, 1),
                                "beat": round((t - ph - a_off) / per, 3)} for c, t, o in offs]
        hits = sorted(set([c / FPS for c in cuts] + [p["t"] for p in punches]))
        if len(o808) and hits:
            G = "Beat-Sync"
            d8 = [(h_, near(h_, o808)) for h_ in hits]
            synced = [(h_, d) for h_, d in d8 if abs(d) <= 1.5 * FRAME + 1e-3]
            if synced:
                mx = max(abs(d) for _, d in synced)
                st = OK if mx <= FRAME + 1e-3 else WARN    # 1–1,5 Frames: evtl. Nachbar-808
                qc.add(G, "808 ↔ Schnitt/Punch", st,
                       f"max {mx * 1000:.1f} ms bei {len(synced)} von {len(hits)} Treffern",
                       "Projektregel max. 1 Frame (Treffer mit 808 im Umkreis von 1,5 Frames)")
            covered = sum(1 for o in o808 if hits and min(abs(np.array(hits) - o)) <= FRAME + 1e-3)
            qc.add(G, "808 mit Bild-Treffer", INFO, f"{covered} von {len(o808)} 808-Onsets")
            res["808_treffer"] = [{"t": round(h_, 4), "versatz_808_ms": round(d * 1000, 1)}
                                  for h_, d in d8]
        # ---- EDL
        if edl:
            def cmp_edl():
                shots = json.loads(Path(edl).read_text()).get("shots", [])
                plan = [int(round(s_["t"] * FPS)) for s_ in shots if s_.get("t", 0) > 0.01]
                cs = np.array(cuts)
                matched, missing = [], []
                via_tr = []
                for pf in plan:
                    if len(cs) and np.min(np.abs(cs - pf)) <= 2:
                        matched.append((pf, int(cs[np.argmin(np.abs(cs - pf))]) - pf))
                    elif any(a_ - 2 <= pf <= b_ + 2 for a_, b_, _ in trans):
                        via_tr.append(pf)
                    else:
                        missing.append(pf)
                extra = [int(c) for c in cuts if not plan or min(abs(c - p_) for p_ in plan) > 2]
                mo = max((abs(d) for _, d in matched), default=0)
                st = OK if not missing and mo <= 1 else WARN
                qc.add("Beat-Sync", "EDL geplant ↔ erkannt", st,
                       f"{len(matched)}/{len(plan)} gefunden"
                       + (f" (+{len(via_tr)} als Übergang)" if via_tr else "")
                       + f", max {mo} Frames, {len(extra)} extra",
                       ("fehlt: " + ", ".join(f"{p_ / FPS:.2f} s" for p_ in missing)
                        if missing else "") + ("; extra: " + ", ".join(f"{e_ / FPS:.2f} s"
                                                                        for e_ in extra[:10])
                                               if extra else ""))
                res["edl_vergleich"] = {"gefunden": matched, "fehlt": missing, "extra": extra,
                                        "als_uebergang": via_tr}
            guard("EDL-Vergleich", cmp_edl)

    # ---- Audio
    G = "Audio"

    def audio_checks():
        nonlocal problems
        import pyloudnorm as pyln
        a = {}
        res["audio"] = a
        lu = pyln.Meter(SR).integrated_loudness(x) if len(x) > 0.5 * SR else float("nan")
        up = resample_poly(x, 4, 1, axis=0)
        tp = 20 * math.log10(np.max(np.abs(up)) + 1e-12)
        del up
        a.update(lufs=lu, true_peak_db=tp)
        qc.add(G, "Lautheit integriert", INFO if -16 <= lu <= -6 else WARN, f"{lu:.1f} LUFS")
        qc.add(G, "True Peak ≤ −0,3 dBTP", OK if tp <= -0.3 else (WARN if tp <= 0.0 else FAIL),
               f"{tp:.2f} dBTP", "4x Oversampling")
        db = blocks_db(x)
        a["bloecke_db"] = [round(float(v), 2) for v in db]
        inner = db[1:-1] if len(db) > 2 else db
        sil = np.nonzero(inner < -60)[0]
        qc.add(G, "Keine stillen 100-ms-Blöcke", FAIL if len(sil) else OK,
               f"{len(sil)} Blöcke < −60 dBFS, min {inner.min():.1f} dB" if len(inner) else "–")
        problems += [((i + 1) * 0.1, "Stille") for i in sil[:10]]
        zero = np.max(np.abs(x), axis=1) < 1e-5
        zr = [(s_, e_) for s_, e_ in runs(zero, int(0.010 * SR))
              if s_ > int(0.02 * SR) and e_ < len(x) - int(0.02 * SR)]
        qc.add(G, "Keine Aussetzer", FAIL if zr else OK, f"{len(zr)} Nullstrecken > 10 ms",
               ", ".join(f"{s_ / SR:.3f} s" for s_, _ in zr[:6]))
        problems += [(s_ / SR, "Aussetzer") for s_, _ in zr[:10]]
        ex = None
        if songx is not None and src is not None:
            i0 = int(round(src * SR))
            ex = songx[i0: i0 + len(x)]
            if len(ex) < len(x):
                ex = np.pad(ex, ((0, len(x) - len(ex)), (0, 0)))
            sdb = blocks_db(ex)
            m = min(len(db), len(sdb))
            dd = db[:m] - sdb[:m]
            valid = np.zeros(m, bool)
            valid[1:m - 1] = sdb[1:m - 1] > -50
            if valid.any():
                j = int(np.argmax(np.abs(np.where(valid, dd, 0))))
                mx = float(abs(dd[j]))
                a.update(pegel_diff_max_db=mx, pegel_diff_bei_s=j * 0.1,
                         pegel_diff_mittel_db=float(np.mean(dd[valid])))
                st = OK if mx < 1.0 else (WARN if mx < 2.0 else FAIL)
                qc.add(G, "Pegel = Song-Ausschnitt", st,
                       f"max {mx:.2f} dB bei {j * 0.1:.1f} s (Mittel {np.mean(dd[valid]):+.2f} dB)",
                       "100-ms-Blöcke, < 1 dB")
                if mx >= 1.0:
                    problems.append((j * 0.1, "Pegel"))
            lus = pyln.Meter(SR).integrated_loudness(ex)
            a["song_lufs"] = lus
        # Fades: Verstärkung Reel/Song in 1-ms-Fenstern (mit Song), sonst Hüllkurve
        ms = SR // 1000
        n1 = min(len(x) // ms, 200)
        rr = np.sqrt(np.mean(x[: n1 * ms].reshape(n1, ms, 2) ** 2, axis=(1, 2)))
        re = np.sqrt(np.mean(x[len(x) - n1 * ms:].reshape(n1, ms, 2) ** 2, axis=(1, 2)))
        if ex is not None:
            sr_ = np.sqrt(np.mean(ex[: n1 * ms].reshape(n1, ms, 2) ** 2, axis=(1, 2)))
            se_ = np.sqrt(np.mean(ex[len(ex) - n1 * ms:].reshape(n1, ms, 2) ** 2, axis=(1, 2)))
            gin, gout = rr / (sr_ + 1e-9), re / (se_ + 1e-9)
            ref_note = "Reel/Song"
        else:
            gin = rr / (np.median(rr[30:80]) + 1e-9)
            gout = re / (np.median(re[-150:-60]) + 1e-9)
            ref_note = "Hüllkurve, Schätzung"
        gin = uniform_filter1d(gin, 3)
        gout = uniform_filter1d(gout, 3)
        hi = np.nonzero(gin >= 0.5)[0]
        fin = 3 * (hi[0] + 0.5) / 1000 if len(hi) else float("nan")   # Sinus-Fade: 50 % bei 1/3
        lo_ = np.nonzero(gout >= 0.5)[0]
        fout = 3 * (n1 - lo_[-1] - 0.5) / 1000 if len(lo_) else float("nan")  # Kosinus: 50 % bei 2/3
        first = float(np.max(np.abs(x[:24]))) if len(x) else 0
        last = float(np.max(np.abs(x[-24:]))) if len(x) else 0
        a.update(fade_in_ms=fin * 1000, fade_out_ms=fout * 1000, erster_sample=first,
                 letzter_sample=last)
        if ex is not None:
            st = OK if fin <= 0.012 and first < 0.2 else WARN
            qc.add(G, "Fade-in ≤ 10 ms", st, f"≈ {fin * 1000:.1f} ms, Start-Amplitude {first:.3f}",
                   ref_note)
            st = OK if 0.025 <= fout <= 0.045 and last < 0.1 else WARN
            qc.add(G, "Fade-out 30–40 ms", st, f"≈ {fout * 1000:.1f} ms, End-Amplitude {last:.3f}",
                   ref_note)
        else:   # ohne Song-Referenz ist die Fade-Länge nicht messbar -> nur Knackser prüfen
            a.update(fade_in_ms=None, fade_out_ms=None)
            qc.add(G, "Fade-in ≤ 10 ms", OK if first < 0.2 else WARN,
                   f"Start-Amplitude {first:.3f}", "ohne --song nur Knackser-Test")
            qc.add(G, "Fade-out 30–40 ms", OK if last < 0.05 else WARN,
                   f"End-Amplitude {last:.3f}", "ohne --song nur Knackser-Test")
        if per:
            bars = np.array([t for _, t, b in grid if b])
            d = near(adur + a_off, bars)
            st = OK if abs(d) <= 0.020 else (FAIL if bar_known else WARN)
            qc.add(G, "Ende auf Taktgrenze", st, f"{d * 1000:+.1f} ms",
                   "±20 ms" + ("" if bar_known else ", Takt-1 geschätzt"))
            a["ende_zur_taktgrenze_ms"] = d * 1000
            if abs(d) > 0.020:
                problems.append((adur, "Ende"))
        late = [o for o in o808_alle if adur + a_off - 0.150 < o < adur + a_off - 0.010]
        qc.add(G, "Keine 808 in letzten 150 ms", FAIL if late else OK,
               f"{len(late)} Onset(s)" + (f" bei {', '.join(f'{o:.3f}' for o in late)} s" if late else ""),
               "808 nie abschneiden")
        problems += [(o, "808 am Ende") for o in late]
        a["onsets_808"] = [round(float(o), 4) for o in o808]

    guard("Audio", audio_checks)

    # ---- Loop + Bilder
    if thumbs:
        def loop():
            import cv2
            h = []
            for j in (0, len(thumbs) - 1):
                im = cv2.imdecode(np.frombuffer(thumbs[j], np.uint8), cv2.IMREAD_COLOR)
                hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
                hh = cv2.calcHist([hsv], [0, 1, 2], None, [16, 8, 8], [0, 180, 0, 256, 0, 256])
                h.append(cv2.normalize(hh, hh).flatten())
            c = float(cv2.compareHist(h[0], h[1], cv2.HISTCMP_CORREL))
            res["loop_korrelation"] = c
            qc.add("Loop", "Letztes ↔ erstes Bild", INFO,
                   f"Histogramm-Korrelation {c:.2f}", "Loop-tauglich" if c >= 0.8 else "sichtbarer Loop-Sprung")
        guard("Loop", loop)
        guard("Shot-Sheet", lambda: shot_sheet(
            outdir / "qc_shots.jpg", thumbs, segs, per,
            f"{reel.name} · {len(segs)} Szenen · Mittelbild je Szene"))
    guard("Timeline", lambda: timeline_png(
        outdir / "qc_timeline.png", mono, dur, grid, cuts, punches, flashes, o808, problems,
        diff, bright, black, frozen, trans, f"{reel.name} · {g.get('quelle') or 'ohne Raster'}"
        + (f" · src {src:.3f} s" if src is not None else "")))

    res["flashes"] = [{"frame": int(f_), "t": round(f_ / FPS, 4),
                       "beat_versatz_ms": round(near(f_ / FPS, halves) * 1000, 1) if per else None}
                      for f_ in flashes]
    res["punches"] = punches
    res["uebergaenge"] = [{"start": a_ / FPS, "ende": (b_ + 1) / FPS, "peak_frame": int(p_)}
                          for a_, b_, p_ in trans]
    res["schwarz"] = [[a / FPS, b / FPS] for a, b in black]
    res["standbild"] = [[a / FPS, b / FPS] for a, b in frozen]
    res["checks"] = qc.items
    nf = sum(c["status"] == FAIL for c in qc.items)
    nw = sum(c["status"] == WARN for c in qc.items)
    bad = nf + (nw if streng else 0)
    verdict = ("ERGEBNIS: " + ("FEHLER" if nf else ("WARNUNG" if nw else "OK"))
               + f" – {nf} Fehler, {nw} Warnungen" + (" (streng)" if streng else ""))
    res.update(verdict=verdict, exit_code=1 if bad else 0, laufzeit_s=round(time.time() - t0, 1))
    (outdir / "qc.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=float))
    table = [f"| {c['gruppe']}: {c['check']} | {c['status']} | {c['wert']} |" for c in qc.items]
    md = [verdict, "", f"Reel: `{reel.name}` · Dauer {dur:.3f} s"
          + (f" · {dur / per:.2f} Beats" if per else "") + f" · Laufzeit {res['laufzeit_s']} s", "",
          "| Check | Ergebnis | Wert |", "|---|---|---|"] + table + ["", "## Details", ""]
    for c in qc.items:
        if c["detail"]:
            md.append(f"- **{c['check']}**: {c['detail']}")
    if res.get("schnitte"):
        md += ["", "### Schnitte", "", "| # | Frame | Zeit | Beat | Versatz |", "|---|---|---|---|---|"]
        md += [f"| {i + 1} | {s_['frame']} | {s_['t']:.3f} s | {s_['beat']:.2f} | "
               f"{s_['beat_versatz_ms']:+.1f} ms |" for i, s_ in enumerate(res["schnitte"])]
    if punches:
        md += ["", "### Punches", ""] + [f"- {p['t']:.3f} s ({p['art']}, Skala {p['skala']:.3f})"
                                         for p in punches]
    if res["flashes"]:
        md += ["", "### Flashes", ""] + [f"- {f_['t']:.3f} s (Beat-Versatz {f_['beat_versatz_ms']} ms)"
                                         for f_ in res["flashes"]]
    md += ["", "Bilder: `qc_timeline.png`, `qc_shots.jpg` · Rohdaten: `qc.json`"]
    (outdir / "qc.md").write_text("\n".join(md) + "\n")
    if not quiet:
        print(verdict)
        wg = max(len(f"{c['gruppe']}: {c['check']}") for c in qc.items) if qc.items else 10
        for c in qc.items:
            print(f"  {(c['gruppe'] + ': ' + c['check']).ljust(wg)}  {c['status']:<8} {c['wert']}")
        print(f"Bericht: {outdir / 'qc.md'}  ({res['laufzeit_s']} s)")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Qualitätsprüfung für fertige Reels (1080x1920, 30 fps).")
    ap.add_argument("reel", help="fertiges Reel (mp4)")
    ap.add_argument("--song", help="Song-Datei (mp3/wav) für Positions- und Pegelvergleich")
    ap.add_argument("--song-json", help="Ausgabe von song_analyse.py (Beats, Takte, 808)")
    ap.add_argument("--src", type=float, help="Startposition des Reels im Song in Sekunden")
    ap.add_argument("--edl", help="geplante Schnittliste (JSON mit shots[].t)")
    ap.add_argument("-o", "--outdir", help="Ausgabeordner (Standard: <reel>_qc)")
    ap.add_argument("--streng", action="store_true", help="WARNUNG zählt als FEHLER")
    a = ap.parse_args(argv)
    r = run_qc(a.reel, song=a.song, song_json=a.song_json, src=a.src, edl=a.edl, outdir=a.outdir,
               streng=a.streng)
    return r["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
