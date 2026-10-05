#!/usr/bin/env python3
"""Referenz-Analyse: zerlegt ein fertiges fremdes Reel (z. B. ein Vorbild-Reel des Nutzers) in Übergänge, Shots, Jump Cuts, Szenen,
Kamera-Bewegung und Tonschichten, damit sich sein Stil in Zahlen fassen lässt (Stil festlegen).

    python3 referenz_analyse.py VIDEO.mp4 [-o OUTDIR] [--bpm 103] [--eins SEK]

Ausgaben in OUTDIR (Standard: $REEL_WORK/referenz/<videoname>/):
    referenz.json   Shots, Übergänge, Szenen, Beat-Raster, Ton je 0,5 s (nicht mit cat ausgeben)
    referenz.md     Bericht: Kennzahlen, Szenen mit Jump Cuts, Shot-Tabelle
    zeitleiste.png  Spektrogramm + Tonkurven + Schnitt-Marken (rot Szenenwechsel, gelb Jump Cut, cyan Überblendung)
    edl.json        Shots im Format von ansicht.py: `ansicht.py szenen VIDEO --edl edl.json` zeigt 4 Bilder je Shot

Begriffe:
- Übergang: harter Schnitt (1 Frame) oder Überblendung (mehrere Mischframes). Erkannt mit TransNetV2
  (pip-Paket transnetv2-pytorch, Gewichte im Paket, läuft auf CPU); ohne das Paket nur harte Schnitte klassisch.
- Jump Cut: Übergang innerhalb derselben Einstellung (gleicher Ort und Blickwinkel, Hintergrund deckungsgleich),
  es fehlt nur ein Stück Zeit. Erkannt per ORB-Merkmalen und Homographie vor und nach dem Übergang.
- Szene: Folge von Shots, die nur durch Jump Cuts getrennt sind.
- Beat-Raster: librosa-Beats mit linearer Regression (konstantes Tempo); Eins aus dem Tiefbass geschätzt oder per --eins.
- Ton je 0,5 s: Pegel, Sub-Bass, Stereo-Kohärenz (Handy-O-Ton ist zwischen links und rechts kaum korreliert,
  Studio-Musik stark), Puls-Klarheit (fester Beat), Höhen-Grenze (Roll-off, zeigt Tiefpass-Filter).
"""
import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.dont_write_bytecode = True
WORK = Path(os.environ.get("REEL_WORK", "/home/user/reel"))
GW, GH = 180, 320          # Graustufen für ORB, Fluss
CW, CH = 45, 80            # Farbe für Histogramme
SR = 44100
HOP = 512


# ---------------------------------------------------------------- Einlesen
def probe(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(video)],
                       capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(num) / float(den), float(j["format"]["duration"])


def decode(video, w, h, pix, fps):
    cmd = ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={fps},scale={w}:{h}:flags=area,format={pix}",
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    c = 1 if pix == "gray" else 3
    n = len(raw) // (w * h * c)
    a = np.frombuffer(raw, np.uint8)[: n * w * h * c]
    return a.reshape(n, h, w) if c == 1 else a.reshape(n, h, w, 3)


def audio(video):
    cmd = ["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy()


# ---------------------------------------------------------------- Bild
def hsv_hist(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()
    return (h / max(h.sum(), 1)).astype(np.float32)


_orb = cv2.ORB_create(nfeatures=700, fastThreshold=10)
_bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)


def orb(g):
    return _orb.detectAndCompute(g, None)


def kamera(k1, k2):
    """Globale Bewegung zwischen zwei Frames (Ähnlichkeitstransformation, RANSAC): Skala, Winkel, dx, dy, Inlier."""
    (p1, d1), (p2, d2) = k1, k2
    if d1 is None or d2 is None or len(p1) < 10 or len(p2) < 10:
        return None
    m = _bf.match(d1, d2)
    if len(m) < 10:
        return None
    a = np.float32([p1[x.queryIdx].pt for x in m])
    b = np.float32([p2[x.trainIdx].pt for x in m])
    M, inl = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None:
        return None
    s = math.hypot(M[0, 0], M[1, 0])
    return s, math.atan2(M[1, 0], M[0, 0]), float(M[0, 2]), float(M[1, 2]), int(inl.sum()), len(m)


def same_setup(k1, k2, size=(GW, GH)):
    """Gleiche Einstellung? Homographie über ORB. Rückgabe (Inlier, Anteil, Fläche der Inlier-Hülle relativ).
    Nur Treffer, die über das Bild verteilt sind, zählen (sonst passt z. B. nur ein Logo im Hintergrund)."""
    (p1, d1), (p2, d2) = k1, k2
    if d1 is None or d2 is None or len(p1) < 12 or len(p2) < 12:
        return 0, 0.0, 0.0
    m = _bf.match(d1, d2)
    if len(m) < 12:
        return 0, 0.0, 0.0
    a = np.float32([p1[x.queryIdx].pt for x in m])
    b = np.float32([p2[x.trainIdx].pt for x in m])
    H, mask = cv2.findHomography(a, b, cv2.RANSAC, 4.0)
    if H is None:
        return 0, 0.0, 0.0
    A2 = H[:2, :2]
    sc = math.sqrt(abs(np.linalg.det(A2)))
    if not (0.7 < sc < 1.4) or abs(H[0, 2]) > 0.35 * size[0] or abs(H[1, 2]) > 0.35 * size[1]:
        return 0, 0.0, 0.0
    inl = mask.ravel().astype(bool)
    hull = cv2.convexHull(a[inl]) if inl.sum() >= 3 else None
    area = float(cv2.contourArea(hull)) / (size[0] * size[1]) if hull is not None else 0.0
    return int(inl.sum()), inl.sum() / max(1, min(len(p1), len(p2))), area


def video_features(gray, col):
    n = len(gray)
    small = np.array([cv2.resize(g, (GW // 2, GH // 2), interpolation=cv2.INTER_AREA) for g in gray])
    hists = np.array([hsv_hist(c) for c in col])
    kp = [orb(g) for g in gray]
    luma = small.reshape(n, -1).mean(axis=1) / 255
    sat = np.array([cv2.cvtColor(c, cv2.COLOR_RGB2HSV)[..., 1].mean() / 255 for c in col])
    z = dict((k, np.zeros(n)) for k in ("dmc", "dh", "skala", "winkel", "dx", "dy", "aktion"))
    z["kam_ok"] = np.zeros(n, bool)
    win = cv2.createHanningWindow((GW // 2, GH // 2), cv2.CV_32F)
    yy, xx = np.mgrid[0:GH // 2, 0:GW // 2].astype(np.float32)
    for t in range(1, n):
        a, b = small[t - 1].astype(np.float32), small[t].astype(np.float32)
        (sx, sy), _ = cv2.phaseCorrelate(a.copy(), b.copy(), win)   # OpenCV 5 fenstert die Eingabe in place
        sx, sy = float(np.clip(sx, -20, 20)), float(np.clip(sy, -20, 20))
        aw = cv2.warpAffine(a, np.float32([[1, 0, sx], [0, 1, sy]]), (GW // 2, GH // 2), borderMode=cv2.BORDER_REPLICATE)
        m = int(max(abs(sx), abs(sy))) + 2
        z["dmc"][t] = np.mean(np.abs(aw[m:-m, m:-m] - b[m:-m, m:-m])) / 255
        z["dh"][t] = cv2.compareHist(hists[t - 1], hists[t], cv2.HISTCMP_BHATTACHARYYA)
        k = kamera(kp[t - 1], kp[t])
        if k and k[4] >= 15:
            s, w, dx, dy = k[:4]
            z["skala"][t], z["winkel"][t], z["dx"][t], z["dy"][t] = s, w, dx, dy
            z["kam_ok"][t] = True
            # Motiv-Bewegung: Farneback minus globale Bewegung (halbe Auflösung)
            fl = cv2.calcOpticalFlowFarneback(small[t - 1], small[t], None, 0.5, 3, 13, 3, 5, 1.1, 0)
            cx, cy = GW / 4, GH / 4
            gx = (s * math.cos(w) - 1) * (xx - cx) - s * math.sin(w) * (yy - cy) + dx / 2
            gy = s * math.sin(w) * (xx - cx) + (s * math.cos(w) - 1) * (yy - cy) + dy / 2
            r = np.hypot(fl[..., 0] - gx, fl[..., 1] - gy)[8:-8, 8:-8]
            z["aktion"][t] = float(np.mean(r))
        else:
            z["skala"][t] = 1.0
    z.update(luma=luma, sat=sat, hists=hists, kp=kp, small=small)
    return z


# ---------------------------------------------------------------- Übergänge
def transnet(video):
    try:
        import torch
        from transnetv2_pytorch import TransNetV2
    except Exception:
        return None
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", "scale=48:27", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 27, 48, 3).copy()
    m = TransNetV2(device="cpu")
    m.eval()
    with torch.no_grad():
        single, many = m.predict_frames(torch.from_numpy(fr), quiet=True)
    conv = lambda x: np.asarray(x.cpu() if hasattr(x, "cpu") else x, dtype=np.float32).ravel()
    return conv(single), conv(many)


def blend_fit(small, a, b):
    """Sind die Frames a..b Mischungen aus Frame a-1 und b+1? Rückgabe (Alpha-Liste, Restfehler relativ)."""
    n = len(small)
    if a - 1 < 0 or b + 1 >= n:
        return [], 9.0
    A = small[a - 1].astype(np.float32)
    B = small[b + 1].astype(np.float32)
    d = (B - A).ravel()
    dd = float(d @ d) + 1e-6
    md = float(np.mean(np.abs(d))) + 1e-6
    al, rs = [], []
    for k in range(a, b + 1):
        f = (small[k].astype(np.float32) - A).ravel()
        x = float(f @ d) / dd
        al.append(round(x, 2))
        rs.append(float(np.mean(np.abs(f - x * d))) / md)
    return al, float(np.mean(rs))


def find_transitions(F, tn, fps):
    n = len(F["dmc"])
    out = []
    if tn is not None:
        single, many = tn
        single, many = single[:n], many[:n]
        hot = (many > 0.5) | (single > 0.5)
        t = 0
        while t < n:
            if not hot[t]:
                t += 1
                continue
            u = t
            while u + 1 < n and hot[u + 1]:
                u += 1
            # Lücken von 1–2 Frames zwischen zwei heißen Läufen gehören zur selben Überblendung
            while u + 3 < n and not hot[u + 1] and (hot[u + 2] or hot[u + 3]):
                u += 2 if hot[u + 2] else 3
                while u + 1 < n and hot[u + 1]:
                    u += 1
            peak = t + int(np.argmax(single[t:u + 1]))
            out.append(dict(a=t, b=u, peak=peak, p=round(float(single[peak]), 2),
                            p_many=round(float(many[t:u + 1].max()), 2)))
            t = u + 1
    else:
        dmc = F["dmc"]
        for t in range(2, n - 1):
            lo = np.median(np.r_[dmc[max(1, t - 12):t - 1], dmc[t + 2:t + 13]])
            if dmc[t] > 0.03 and dmc[t] > 3.2 * (lo + 0.004) and dmc[t] >= dmc[t - 1] and dmc[t] >= dmc[t + 1]:
                out.append(dict(a=t, b=t, peak=t, p=None, p_many=None))
    # Typ bestimmen
    for c in out:
        a, b = c["a"], c["b"]
        # Überblendung: die Mischframes liegen zwischen den Randbildern, nicht auf einer Seite
        if b - a >= 2:
            al, r = blend_fit(F["small"], a, b)
            c["alpha"], c["rest"] = al, round(r, 2)
            mono = len(al) > 2 and np.all(np.diff(al) > -0.15)
            c["typ"] = "blende" if mono and r < 0.6 and al[0] < 0.6 and al[-1] > 0.4 else "schnitt"
            if c["typ"] == "schnitt":
                # harter Schnitt irgendwo im Lauf: größter Pixelsprung (TransNetV2 liegt oft 1 Frame daneben)
                lo = max(1, a - 2)
                c["peak"] = lo + int(np.argmax(F["dmc"][lo:min(n, b + 3)]))
        else:
            c["typ"] = "schnitt"
            lo = max(1, a - 2)
            c["peak"] = lo + int(np.argmax(F["dmc"][lo:min(n, b + 3)]))
        # Blitz: Helligkeit springt hoch und fällt zurück, Bild danach wie davor
        L = F["luma"]
        p = c["peak"]
        if p + 5 < n and p >= 1 and L[p] - L[p - 1] > 0.1:
            back = np.mean(np.abs(F["small"][p + 5].astype(np.float32) - F["small"][p - 1])) / 255
            if back < 0.5 * max(F["dmc"][p], 1e-3):
                c["typ"] = "flash"
    return out


# ---------------------------------------------------------------- Ton
def band_db(S, freqs, lo, hi):
    m = (freqs >= lo) & (freqs < hi)
    return 10 * np.log10(S[m].sum(axis=0) + 1e-10)


def audio_features(st):
    import librosa
    from scipy.signal import coherence
    mono = st.mean(axis=0)
    nfft = 2048
    Sm = np.abs(librosa.stft(mono, n_fft=nfft, hop_length=HOP)) ** 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=nfft)
    times = librosa.frames_to_time(np.arange(Sm.shape[1]), sr=SR, hop_length=HOP)
    mel = librosa.power_to_db(librosa.feature.melspectrogram(S=Sm, sr=SR, n_mels=128, fmax=16000), ref=np.max)
    bands = {k: band_db(Sm, freqs, lo, hi) for k, (lo, hi) in
             dict(sub=(20, 120), tief=(120, 500), mitte=(500, 2000), praesenz=(2000, 6000),
                  hoehen=(6000, 16000)).items()}
    total = 10 * np.log10(Sm.sum(axis=0) + 1e-10)
    roll = librosa.feature.spectral_rolloff(S=Sm, sr=SR, roll_percent=0.97)[0]
    onset = librosa.onset.onset_strength(S=librosa.power_to_db(Sm), sr=SR, hop_length=HOP)
    # Stereo-Kohärenz 200–4000 Hz je 0,25 s
    step = int(0.25 * SR)
    coh_t, coh = [], []
    for i in range(0, st.shape[1] - step, step):
        f, C = coherence(st[0, i:i + step], st[1, i:i + step], fs=SR, nperseg=1024)
        m = (f >= 200) & (f < 4000)
        coh_t.append((i + step / 2) / SR)
        coh.append(float(np.mean(C[m])) if np.isfinite(C[m]).all() else 1.0)
    return dict(times=times, mel=mel, bands=bands, total=total, roll=roll, onset=onset,
                coh_t=np.array(coh_t), coh=np.array(coh))


def beat_grid(onset, times, bpm_hint=None):
    import librosa
    kw = dict(onset_envelope=onset, sr=SR, hop_length=HOP, units="time", tightness=120)
    if bpm_hint:
        kw["start_bpm"] = bpm_hint
    _, beats = librosa.beat.beat_track(**kw)
    beats = np.asarray(beats)
    if len(beats) < 8:
        return None
    per = np.median(np.diff(beats))
    idx = np.round((beats - beats[0]) / per).astype(int)
    keep = np.ones(len(beats), bool)
    for _ in range(3):
        p = np.polyfit(idx[keep], beats[keep], 1)
        r = beats - np.polyval(p, idx)
        keep = np.abs(r) < max(0.03, 2.5 * np.std(r[keep]))
    per, t0 = float(p[0]), float(p[1])
    k0 = math.floor(-t0 / per)
    k1 = math.ceil((times[-1] - t0) / per)
    t0 = t0 + k0 * per                       # Index 0 = erster Beat im Video
    grid = t0 + per * np.arange(0, k1 - k0 + 1)
    grid = grid[grid <= times[-1] + 1e-3]
    res = beats - np.polyval(p, idx)
    return dict(bpm=round(60 / per, 2), per=per, t0=t0, grid=grid.tolist(), n_beats=len(beats),
                resid_ms=round(float(np.sqrt(np.mean(res[keep] ** 2)) * 1000), 1), treffer=int(keep.sum()))


def local_pulse(onset, per, fr):
    lag = int(round(per * fr))
    win = int(4 * fr)
    out = np.zeros_like(onset)
    o = onset - np.convolve(onset, np.ones(win) / win, mode="same")
    for i in range(0, len(o), 8):
        a, b = max(0, i - win // 2), min(len(o), i + win // 2)
        x = o[a:b]
        if len(x) <= 2 * lag + 2:
            continue
        c0 = float(x @ x) + 1e-9
        c1 = max(float(x[:-lag] @ x[lag:]), float(x[:-2 * lag] @ x[2 * lag:]))
        out[i:i + 8] = max(0.0, c1 / c0)
    return out


# ---------------------------------------------------------------- Hauptteil
def analyse(video, out, bpm=None, eins=None):
    video, out = Path(video), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    W, H, fps, dur = probe(video)
    print(f"{video.name}: {W}x{H}, {fps:g} fps, {dur:.2f} s", flush=True)
    gray = decode(video, GW, GH, "gray", fps)
    col = decode(video, CW, CH, "rgb24", fps)
    n = min(len(gray), len(col))
    gray, col = gray[:n], col[:n]
    F = video_features(gray, col)
    tn = transnet(video)
    print("Übergänge: " + ("TransNetV2" if tn is not None else "klassisch (TransNetV2 fehlt)"), flush=True)
    trans = find_transitions(F, tn, fps)

    # Shots: Grenze = Schnitt-Frame bzw. Mitte der Überblendung; Flashes sind keine Grenze
    bounds = [(0, None)]
    for c in trans:
        if c["typ"] == "flash":
            continue
        bounds.append(((c["a"] + c["b"] + 1) // 2 if c["typ"] == "blende" else c["peak"], c))
    bounds.append((n, None))
    shots = []
    for i in range(len(bounds) - 1):
        a, c = bounds[i]
        b = bounds[i + 1][0]
        if b - a < 1:
            continue
        s = dict(a=a, b=b, uebergang=None)
        if c:
            s["uebergang"] = "blende" if c["typ"] == "blende" else "schnitt"
            s["blende_frames"] = c["b"] - c["a"] + 1 if c["typ"] == "blende" else 0
            s["_c"] = c
        shots.append(s)

    # Jump Cut: Einstellung vor und nach dem Übergang gleich? Frames mit Abstand zum Übergang vergleichen
    # (Randframes sind oft doppelt oder unscharf); Treffer müssen über das Bild verteilt sein.
    for i in range(1, len(shots)):
        s, p = shots[i], shots[i - 1]
        c = s["_c"]
        ea = (c["a"] if c["typ"] == "blende" else s["a"]) - 1      # letztes reines Bild davor
        eb = (c["b"] + 1) if c["typ"] == "blende" else s["a"]      # erstes reines Bild danach
        best = (0, 0.0, 0.0)
        for k in (1, 2, 3):
            fa, fb = max(p["a"], ea - k), min(s["b"] - 1, eb + k)
            r = same_setup(F["kp"][fa], F["kp"][fb])
            if r[0] > best[0]:
                best = r
        s["orb"], s["orb_anteil"], s["orb_flaeche"] = best[0], round(best[1], 2), round(best[2], 2)
        s["jump"] = bool(best[0] >= 50 and best[1] >= 0.15 and best[2] >= 0.2)
    for i, s in enumerate(shots):
        s["mitte"] = (s["a"] + s["b"]) // 2
    for i, s in enumerate(shots):          # Rückkehr zu einer früheren Einstellung (Parallelmontage)
        s["wie"] = None
        for j in range(max(0, i - 10), i - 1):
            inl, frac, fl = same_setup(F["kp"][shots[j]["mitte"]], F["kp"][s["mitte"]])
            if inl >= 50 and frac >= 0.15 and fl >= 0.2:
                s["wie"] = j + 1
                break
    scene = 0
    for i, s in enumerate(shots):
        if i == 0 or not s.get("jump"):
            scene += 1
        s["szene"] = scene

    # Ton
    st = audio(video)
    A = audio_features(st)
    fr = SR / HOP
    bg = beat_grid(A["onset"], A["times"], bpm)
    pulse = local_pulse(A["onset"], bg["per"] if bg else 0.5, fr)
    if bg:
        grid = np.array(bg["grid"])
        if eins is not None:
            bg["eins_index"] = int(np.argmin(np.abs(grid - eins))) % 4
        else:
            sub = A["bands"]["sub"]
            e = np.array([sub[min(len(sub) - 1, int(round(t * fr)))] for t in grid])
            bg["eins_index"] = int(np.argmax([np.mean(e[k::4]) for k in range(4)]))

    def coh_at(t0, t1):
        m = (A["coh_t"] >= t0) & (A["coh_t"] < t1)
        return round(float(np.mean(A["coh"][m])), 2) if m.any() else None

    for k, s in enumerate(shots, 1):
        a, b = s["a"], s["b"]
        s["n"], s["t"], s["ende"] = k, round(a / fps, 3), round(b / fps, 3)
        s["dauer"] = round((b - a) / fps, 3)
        rng = slice(a + 1, b)
        ok = F["kam_ok"][rng]
        sk = F["skala"][rng][ok]
        s["zoom_pct"] = round(float((np.prod(sk) - 1) * 100), 1) if len(sk) else 0.0
        s["schwenk_px"] = round(float(np.mean(np.hypot(F["dx"][rng][ok], F["dy"][rng][ok]))), 2) if ok.any() else None
        dxy = np.c_[F["dx"][rng][ok], F["dy"][rng][ok]]
        s["wackel_px"] = round(float(np.mean(np.linalg.norm(np.diff(dxy, axis=0), axis=1))), 2) if len(dxy) > 3 else None
        s["aktion"] = round(float(np.mean(F["aktion"][rng][ok])), 2) if ok.any() else None
        s["stand_anteil"] = round(float(np.mean(F["dmc"][rng] < 0.002)), 2) if b - a > 1 else 0
        s["helligkeit"] = round(float(np.mean(F["luma"][a:b])), 3)
        s["saettigung"] = round(float(np.mean(F["sat"][a:b])), 3)
        if bg:
            bp = (s["t"] - bg["t0"]) / bg["per"]
            s["beat"] = round(bp, 2)
            s["beats"] = round(s["dauer"] / bg["per"], 2)
            nb = round(bp * 2) / 2
            s["versatz_ms"] = round((bp - nb) * bg["per"] * 1000)
            s["schlag"] = (int(round(bp)) - bg["eins_index"]) % 4 + 1 if abs(bp - round(bp)) < 0.25 else None
        i0, i1 = int(round(s["t"] * fr)), max(int(round(s["t"] * fr)) + 1, int(round(s["ende"] * fr)))
        s["ton_db"] = round(float(np.mean(A["total"][i0:i1])), 1)
        s["ton_sub_db"] = round(float(np.mean(A["bands"]["sub"][i0:i1])), 1)
        s["ton_puls"] = round(float(np.mean(pulse[i0:i1])), 2)
        s["ton_koh"] = coh_at(s["t"], s["ende"])
        s.pop("_c", None)

    # Zoom-Punches: Skala springt in wenigen Frames um > 4 % (nicht am Schnitt)
    events = [dict(typ="flash", t=round(c["peak"] / fps, 3)) for c in trans if c["typ"] == "flash"]
    logsk = np.cumsum(np.log(np.where(F["kam_ok"], F["skala"], 1.0)))
    starts = [s["a"] for s in shots]
    for t in range(2, n - 5):
        if any(-1 <= t - a <= 5 for a in starts[1:]):
            continue
        dz = logsk[t + 3] - logsk[t - 1]
        if abs(dz) > 0.04:
            nb = [abs(logsk[u + 3] - logsk[u - 1]) for u in range(max(1, t - 3), min(n - 4, t + 4))]
            if abs(dz) >= max(nb):
                events.append(dict(typ="punch" if dz > 0 else "zoom_raus", t=round(t / fps, 3),
                                   pct=round(float(math.expm1(dz)) * 100, 1)))
    events.sort(key=lambda e: e["t"])

    ton = []
    for t in np.arange(0, A["times"][-1], 0.5):
        i0, i1 = int(t * fr), int((t + 0.5) * fr)
        ton.append(dict(t=round(float(t), 2), db=round(float(np.mean(A["total"][i0:i1])), 1),
                        sub=round(float(np.mean(A["bands"]["sub"][i0:i1])), 1),
                        puls=round(float(np.mean(pulse[i0:i1])), 2), koh=coh_at(t, t + 0.5),
                        hoehen_khz=round(float(np.median(A["roll"][i0:i1])) / 1000, 1)))
    for s in shots:
        s.pop("mitte", None)
    res = dict(video=str(video), breite=W, hoehe=H, fps=fps, dauer=round(dur, 3), beat=bg, shots=shots,
               uebergaenge=[{k: v for k, v in c.items()} for c in trans], events=events, ton=ton,
               erkennung="TransNetV2" if tn is not None else "klassisch")
    (out / "referenz.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    per = bg["per"] if bg else 0.5
    edl = dict(per=per, shots=[dict(n=s["n"], t=s["t"], beats=s["dauer"] / per, clip=f"S{s['szene']}",
                                    mode="normal") for s in shots])
    (out / "edl.json").write_text(json.dumps(edl))
    zeitleiste(out / "zeitleiste.png", A, pulse, bg, shots, events, dur)
    bericht(out / "referenz.md", res, video)
    print(f"Fertig: {out}/referenz.md ({len(shots)} Shots, {shots[-1]['szene']} Szenen, "
          f"{sum(1 for s in shots if s.get('jump'))} Jump Cuts, "
          f"{sum(1 for s in shots if s.get('uebergang') == 'blende')} Überblendungen)")
    return res


def zeitleiste(path, A, pulse, bg, shots, events, dur):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(3, 1, figsize=(18, 7.2), dpi=100, sharex=True,
                            gridspec_kw=dict(height_ratios=[3, 1.3, 1.3]))
    t = A["times"]
    ax = axs[0]
    ax.imshow(A["mel"], origin="lower", aspect="auto", extent=[0, t[-1], 0, 128], cmap="magma", vmin=-80, vmax=0)
    ax.set_ylabel("Mel bis 16 kHz")
    for s in shots[1:]:
        c = "yellow" if s.get("jump") else ("cyan" if s.get("uebergang") == "blende" else "red")
        for a_ in axs:
            a_.axvline(s["t"], color=c, lw=1.1, alpha=0.85)
        ax.text(s["t"] + 0.05, 125, str(s["n"]), color="white", fontsize=7, ha="left", va="top")
    for e in events:
        ax.plot([e["t"]], [10], marker="v" if e["typ"] == "punch" else "*", color="lime", ms=7)
    if bg:
        k = bg.get("eins_index", 0)
        for i, x in enumerate(bg["grid"]):
            ax.plot([x, x], [0, 7 if (i - k) % 4 == 0 else 3], color="white", lw=1 if (i - k) % 4 == 0 else 0.5)
    ax.set_title(f"Spektrogramm · rot Schnitt, cyan Überblendung, gelb Jump Cut · {bg['bpm'] if bg else '?'} BPM, "
                 f"weiße Striche unten = Beats (lang = Eins)", fontsize=10)
    sm = lambda x, k=9: np.convolve(x, np.ones(k) / k, mode="same")
    ax = axs[1]
    ax.plot(t, sm(A["total"]) - A["total"].max(), color="k", lw=0.8, label="Pegel dB")
    ax.plot(t, sm(A["bands"]["sub"]) - A["total"].max(), color="purple", lw=0.8, label="Sub <120 Hz dB")
    ax.plot(t, sm(A["bands"]["hoehen"]) - A["total"].max(), color="green", lw=0.6, label="Höhen 6–16 kHz dB")
    ax.set_ylim(-50, 3)
    ax.legend(loc="lower right", fontsize=7, ncol=3)
    ax = axs[2]
    ax.plot(t, sm(pulse), color="orange", lw=1, label="Puls-Klarheit")
    ax.plot(A["coh_t"], A["coh"], color="teal", lw=1, label="Stereo-Kohärenz (niedrig = Handy-O-Ton)")
    ax.plot(t, sm(A["roll"]) / 16000, color="gray", lw=0.6, label="Höhen-Grenze / 16 kHz")
    ax.set_ylim(0, 1.05)
    ax.legend(loc="lower right", fontsize=7, ncol=3)
    ax.set_xlim(0, dur)
    ax.set_xticks(np.arange(0, dur, 2))
    ax.set_xlabel("Sekunden")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def bericht(path, res, video):
    shots, bg = res["shots"], res["beat"]
    L = [f"# Referenz-Analyse {video.name}", "",
         f"{res['breite']}x{res['hoehe']}, {res['fps']:g} fps, {res['dauer']:.2f} s, Übergänge per {res['erkennung']}"]
    if bg:
        L.append(f"Beat: {bg['bpm']} BPM, Periode {bg['per']*1000:.1f} ms, Rest {bg['resid_ms']} ms "
                 f"({bg['treffer']}/{bg['n_beats']} Beats auf dem Raster), Eins bei Beat-Index {bg['eins_index']} (geschätzt)")
    sc = {}
    for s in shots:
        sc.setdefault(s["szene"], []).append(s)
    jumps = sum(1 for s in shots if s.get("jump"))
    bl = sum(1 for s in shots if s.get("uebergang") == "blende")
    L += ["", f"**{len(shots)} Shots, {len(sc)} Szenen, {jumps} Jump Cuts, {bl} Überblendungen, "
              f"{sum(e['typ'] == 'punch' for e in res['events'])} Punches, "
              f"{sum(e['typ'] == 'flash' for e in res['events'])} Flashes**", ""]
    if bg:
        L.append(f"Shot-Länge Median {np.median([s['beats'] for s in shots]):.2f} Beats "
                 f"({np.median([s['dauer'] for s in shots]):.2f} s); Szenen-Länge Median "
                 f"{np.median([sum(x['beats'] for x in v) for v in sc.values()]):.1f} Beats")
        on = [s for s in shots[1:] if abs(s["versatz_ms"]) <= 45]
        L.append(f"Übergänge auf Beat oder Halbbeat (±45 ms): {len(on)} von {len(shots) - 1}")
    L += ["", "## Szenen", "", "| Szene | Shots | Start s | Dauer s | Beats | Jump Cuts | Shot-Beats |",
          "|---|---|---|---|---|---|---|"]
    for k, v in sc.items():
        L.append(f"| {k} | {v[0]['n']}–{v[-1]['n']} | {v[0]['t']:.2f} | {sum(x['dauer'] for x in v):.2f} | "
                 f"{sum(x.get('beats', 0) for x in v):.1f} | {len(v) - 1} | "
                 f"{' '.join(format(x.get('beats', 0), '.1f') for x in v)} |")
    L += ["", "## Shots", "",
          "| # | Start | Dauer | Beats | Beat | Schlag | Versatz ms | Übergang | Jump | ORB | Szene | wie | Zoom % | "
          "Schwenk | Wackel | Aktion | Ton dB | Sub dB | Puls | Kohärenz |",
          "|" + "---|" * 20]
    for s in shots:
        ue = s.get("uebergang") or "Start"
        if ue == "blende":
            ue = f"Blende {s['blende_frames']}f"
        L.append(f"| {s['n']} | {s['t']:.2f} | {s['dauer']:.2f} | {s.get('beats', 0):.2f} | {s.get('beat', 0):.2f} | "
                 f"{s.get('schlag') or ''} | {s.get('versatz_ms', '')} | {ue} | {'J' if s.get('jump') else ''} | "
                 f"{s.get('orb', '')} | {s['szene']} | {s.get('wie') or ''} | {s['zoom_pct']} | {s['schwenk_px']} | "
                 f"{s['wackel_px']} | {s['aktion']} | {s['ton_db']} | {s['ton_sub_db']} | {s['ton_puls']} | "
                 f"{s['ton_koh']} |")
    if res["events"]:
        L += ["", "## Punches, Flashes", ""] + [f"- {e['t']:.2f} s {e['typ']} {e.get('pct', '')}" for e in res["events"]]
    Path(path).write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("-o", "--out")
    ap.add_argument("--bpm", type=float, help="Tempo-Hinweis für die Beat-Erkennung")
    ap.add_argument("--eins", type=float, help="Zeit (s) einer Eins, legt die Taktphase fest")
    a = ap.parse_args()
    analyse(a.video, a.out or WORK / "referenz" / Path(a.video).stem, a.bpm, a.eins)


if __name__ == "__main__":
    main()
