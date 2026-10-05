#!/usr/bin/env python3
"""Song-Analyse für Reels: Beat-Raster, Takte, Phrasen, Songteile, Hook, 808/Clap-Akzente,
empfohlene Reel-Fenster.

    python3 song_analyse.py song.mp3 -o OUTDIR            # song.json, song.md, song.png, akzentkarte.png
    python3 song_analyse.py song.mp3 -o OUTDIR --bpm 140  # Tempo vorgeben (sonst automatisch)
    python3 song_analyse.py song.mp3 -o OUTDIR --eins 13.727   # Zeit einer Eins vorgeben (Taktlage)

Zeitachse = ffmpeg-Decode des Songs (dieselbe wie reel_audio.py "src").
Takt-Notation T<Takt>.<Schlag>, Takt 0 beginnt auf der ersten Eins ab Songstart.

Vorgehen (Projektanweisungen Phase 3):
- Beats: librosa beat_track, lineare Regression über die Beat-Nummern (Ausreißer raus),
  dann Tempo und Phase an einer 1-ms-Einsatzkurve feinjustiert. Residuen in ms im Bericht.
- Taktlage: Clap auf Schlag 3 (Halftime/Drill) bzw. Snare auf 2+4 und Kick auf 1.
- Songteile: taktweise Chroma/MFCC/Pegel, Self-Similarity, Grenzen auf 4-Takt-Phrasen.
  Hook = Teil, der sich wiederholt (Ähnlichkeit ≥ 0,9) und die meiste Energie hat.
- Akzente: 808 = Einsatz unter 120 Hz; 808-Nachschlag = 808 genau 1 Beat nach einem
  frischen 808; Clap = Einsatz 1,5–6 kHz auf dem Raster. Akzent-Karte pro Halbbeat mit
  Bild-Akzent (Standard-Zuordnung, Stil-Leitfaden „Akzente“).
- Reel-Fenster: ab der Eins der Hook 16 bzw. 8 Takte bis zur nächsten Eins, optional mit
  2-Beat-Auftakt; Prüfung "kein 808-Einsatz in den letzten 150 ms".
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import scipy.signal as ss
from scipy.ndimage import uniform_filter1d

SR = 48000
SR_LO = 22050
HB_NAMES = ["1", "1+", "2", "2+", "3", "3+", "4", "4+"]
BILD = {  # Standard-Zuordnung Ton -> Bild (Stil-Leitfaden „Akzente“)
    "808": "Schnitt oder Punch 0,14 mit Blur",
    "808_nachschlag": "2. Punch 0,12 im selben Shot",
    "clap": "Schnitt mit Mini-Punch 0,06",
    "eins": "harter Schnitt",
    "none": "",
}


def decode(path, sr=SR, mono=True):
    """Audio per ffmpeg (erste Audiospur, Cover-Bild ignoriert) als float32."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-map", "0:a:0",
                          "-ac", "1" if mono else "2", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    return x if mono else x.reshape(-1, 2)


def onset_curve(x, sr, band=None, win_ms=10):
    """Einsatzkurve mit 1-ms-Raster: RMS (10 ms) im Band, positive Log-Ableitung, geglättet."""
    if band is not None:
        lo, hi = band
        if lo is None:
            sos = ss.butter(4, hi, btype="lowpass", fs=sr, output="sos")
        else:
            sos = ss.butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos")
        x = ss.sosfiltfilt(sos, x)
    w, h = int(win_ms / 1000 * sr), int(0.001 * sr)
    e = np.sqrt(np.maximum(uniform_filter1d(x.astype(np.float64) ** 2, w), 0))[::h]
    de = np.maximum(0, np.diff(np.log(e + 1e-4), prepend=np.log(e[0] + 1e-4)))
    return np.convolve(de, np.ones(9), mode="same"), e


def peaks_ms(curve, height, distance_ms=90):
    pk, pr = ss.find_peaks(curve, height=height, distance=distance_ms)
    return pk / 1000.0, pr["peak_heights"]


# ---------------------------------------------------------------- Beat-Raster
def beat_grid(y_lo, env, dur, bpm=None):
    import librosa
    if bpm:
        per0 = 60.0 / bpm
        _, bt = librosa.beat.beat_track(y=y_lo, sr=SR_LO, hop_length=256, start_bpm=bpm, units="time")
    else:
        _, bt = librosa.beat.beat_track(y=y_lo, sr=SR_LO, hop_length=256, units="time")
        per0 = float(np.median(np.diff(bt)))
        while 60 / per0 < 90:
            per0 /= 2
        while 60 / per0 > 180:
            per0 *= 2
    # Regression über Beat-Nummern, Ausreißer (> 30 ms) raus
    k = np.round((bt - bt[0]) / per0)
    keep = np.ones(len(bt), bool)
    for _ in range(4):
        per, ph = np.polyfit(k[keep], bt[keep], 1)
        res = bt - (ph + per * k)
        keep = np.abs(res) < 0.030
    res_ms = np.abs(res[keep]) * 1000
    per_reg, ph_reg = per, ph
    # Feinjustage an der 1-ms-Einsatzkurve (Tempo ±0,15 %, Phase ±30 ms)
    n = int(dur / per) + 2
    best = (-1, per, ph)
    ks = np.arange(-2, n)
    from scipy.ndimage import maximum_filter1d
    envmax = maximum_filter1d(env, 5)
    for dp in np.linspace(-0.0015, 0.0015, 31):
        p = per * (1 + dp)
        for dph in np.arange(-0.030, 0.0305, 0.001):
            t = ph + dph + p * ks
            idx = np.round(t * 1000).astype(int)
            idx = idx[(idx >= 0) & (idx < len(envmax))]
            s = envmax[idx].mean()
            if s > best[0]:
                best = (s, p, ph + dph)
    _, per, ph = best
    ph = ph % per
    beats = ph + per * np.arange(int((dur - ph) / per) + 1)
    return per, ph, beats, dict(librosa_beats=len(bt), used=int(keep.sum()), phase_librosa=round(float(ph_reg % per_reg), 4),
                                phase_verschiebung_ms=round(float(((ph - ph_reg + per / 2) % per - per / 2) * 1000), 1),
                                residual_ms_median=round(float(np.median(res_ms)), 1),
                                residual_ms_p95=round(float(np.percentile(res_ms, 95)), 1))


def beat_strength(times, curve, tol_ms=25):
    from scipy.ndimage import maximum_filter1d
    m = maximum_filter1d(curve, 2 * tol_ms + 1)
    idx = np.clip(np.round(np.asarray(times) * 1000).astype(int), 0, len(m) - 1)
    return m[idx]


def downbeat_offset(beats, kick_c, clap_c):
    """Welcher Beat (0–3) ist die Eins? Clap auf 3 (Halftime) oder Snare 2+4 mit Kick auf 1."""
    K = beat_strength(beats, kick_c)
    C = beat_strength(beats, clap_c)
    kb = np.array([K[i::4].mean() for i in range(4)])
    cb = np.array([C[i::4].mean() for i in range(4)])
    o = np.argsort(cb)[::-1]
    if cb[o[0]] > 1.35 * cb[o[1]]:                     # ein Clap pro Takt -> Schlag 3
        off, how = (o[0] - 2) % 4, "Clap auf Schlag 3"
    else:                                               # Backbeat: Snare 2+4, Kick auf 1
        cand = [(o[0] + 1) % 4, (o[0] + 3) % 4]
        off, how = max(cand, key=lambda c: kb[c]), "Snare auf 2+4, Kick auf 1"
    return int(off), how, kb.round(3).tolist(), cb.round(3).tolist()


# ---------------------------------------------------------------- Struktur
def bar_features(y_lo, bar_t):
    import librosa
    hop = 512
    C = librosa.feature.chroma_cqt(y=y_lo, sr=SR_LO, hop_length=hop)
    M = librosa.feature.mfcc(y=y_lo, sr=SR_LO, n_mfcc=20, hop_length=hop)
    R = librosa.amplitude_to_db(librosa.feature.rms(y=y_lo, hop_length=hop), ref=1.0)
    ft = librosa.frames_to_time(np.arange(C.shape[1]), sr=SR_LO, hop_length=hop)

    def agg(F, edges):
        out = []
        for a, b in zip(edges[:-1], edges[1:]):
            m = (ft >= a) & (ft < b)
            out.append(F[:, m].mean(1) if m.any() else np.zeros(F.shape[0]))
        return np.array(out)
    return agg, C, M, R


def zfeat(Cb, Mb, Rb):
    F = np.hstack([Cb * 1.0, Mb[:, 1:] / (np.abs(Mb[:, 1:]).std(0) + 1e-6) * 0.5, ((Rb - Rb.mean()) / (Rb.std() + 1e-6))[:, None]])
    F = F - F.mean(0)
    return F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9)


def novelty(S, k=4):
    n = len(S)
    g = np.outer(np.r_[-np.ones(k), np.ones(k)], np.r_[-np.ones(k), np.ones(k)])   # Foote-Schachbrett
    nov = np.zeros(n)
    for i in range(k, n - k):
        nov[i] = (S[i - k:i + k, i - k:i + k] * g).sum()
    return np.maximum(nov, 0)


def sections(Fb, rms_bar, k808_bar, clap_bar, nbars):
    S = Fb @ Fb.T
    nov = novelty(S, 4)
    # Phrasenlage: die meisten Grenzen auf Vielfachen von 4 Takten
    offs = [nov[o::4].sum() for o in range(4)]
    p_off = int(np.argmax(offs))
    cand = [b for b in range(p_off, nbars, 4) if 0 < b < nbars]
    thr = 0.30 * max(nov[cand].max() if cand else 1, 1e-9)
    bounds = [0] + [b for b in cand if nov[b] >= thr] + [nbars]
    bounds = sorted(set(bounds))
    segs = [(a, b) for a, b in zip(bounds[:-1], bounds[1:]) if b > a]

    def seg_sim(a, b):
        (a0, a1), (b0, b1) = a, b
        L = min(a1 - a0, b1 - b0)
        return float(np.mean([S[a0 + i, b0 + i] for i in range(L)]))
    # Gruppen gleicher Teile (A, B, C ...)
    group = [-1] * len(segs)
    g = 0
    for i in range(len(segs)):
        if group[i] >= 0:
            continue
        group[i] = g
        for j in range(i + 1, len(segs)):
            if group[j] < 0 and seg_sim(segs[i], segs[j]) >= 0.90:
                group[j] = g
        g += 1
    out = []
    for i, (a, b) in enumerate(segs):
        sims = [seg_sim(segs[i], segs[j]) for j in range(len(segs)) if j != i]
        out.append(dict(bar_start=a, bar_end=b, gruppe=chr(65 + group[i]),
                        energie_db=round(float(np.mean(rms_bar[a:b])), 1),
                        n808_pro_takt=round(float(np.mean(k808_bar[a:b])), 2),
                        clap_pro_takt=round(float(np.mean(clap_bar[a:b])), 2),
                        wiederholung=round(max(sims) if sims else 0.0, 3)))
    # Label: Hook = wiederholte Gruppe mit höchster Energie
    grp = {}
    for s in out:
        grp.setdefault(s["gruppe"], []).append(s)
    rep = {k: v for k, v in grp.items() if len(v) >= 2}
    hook_g = max(rep, key=lambda k: np.mean([s["energie_db"] + 2 * s["n808_pro_takt"] for s in rep[k]])) if rep else None
    if hook_g and np.mean([s["energie_db"] for s in rep[hook_g]]) < max(s["energie_db"] for s in out) - 4:
        hook_g = None                           # Wiederholung ist deutlich leiser als der lauteste Teil: keine Hook
    hook_e = np.mean([s["energie_db"] for s in rep[hook_g]]) if hook_g else max(s["energie_db"] for s in out)
    for i, s in enumerate(out):
        if s["gruppe"] == hook_g:
            s["label"] = "hook"
        elif s["n808_pro_takt"] < 0.3 and s["clap_pro_takt"] < 0.3:
            s["label"] = "intro" if i == 0 else "outro" if i == len(out) - 1 else "break"
        elif i == 0:
            s["label"] = "intro"
        elif s["energie_db"] < hook_e - 2.5 and s["bar_end"] - s["bar_start"] <= 8 and i < len(out) - 1:
            s["label"] = "break"
        elif i == len(out) - 1 and s["bar_end"] - s["bar_start"] <= 8:
            s["label"] = "outro"
        else:
            s["label"] = "strophe"
    return out, nov, p_off, S


# ---------------------------------------------------------------- Tonart
NOTEN = ["C", "Cis", "D", "Es", "E", "F", "Fis", "G", "As", "A", "B", "H"]
KS_DUR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MOLL = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
CAMELOT_DUR = ["8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B"]
CAMELOT_MOLL = ["5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A"]


def tonart(C):
    """Krumhansl-Schmuckler auf dem mittleren Chroma; Camelot-Code für Song-Übergänge (gleich/±1 passt)."""
    m = C.mean(1)
    best = (-2, 0, "dur")
    for r in range(12):
        for prof, art in ((KS_DUR, "dur"), (KS_MOLL, "moll")):
            c = np.corrcoef(m, np.roll(prof, r))[0, 1]
            if c > best[0]:
                best = (c, r, art)
    c, r, art = best
    name = f"{NOTEN[r]}-Dur" if art == "dur" else f"{NOTEN[r].lower()}-Moll"
    return dict(name=name, camelot=(CAMELOT_DUR if art == "dur" else CAMELOT_MOLL)[r], sicherheit=round(float(c), 2))


# ---------------------------------------------------------------- Hauptanalyse
def analyse(path, bpm=None, eins=None):
    import librosa
    t0 = time.time()
    x = decode(path, SR)
    y_lo = decode(path, SR_LO)
    dur = len(x) / SR
    full_c, _ = onset_curve(x, SR, band=(None, 6000))
    kick_c, kick_e = onset_curve(x, SR, band=(None, 120))
    mid_c, _ = onset_curve(x, SR, band=(120, 400))
    clap_c, _ = onset_curve(x, SR, band=(1500, 3000))   # 1,5–3 kHz trennt Clap am besten von Hats/Vocals

    per, ph, beats, reg = beat_grid(y_lo, 0.6 * full_c + 0.4 * kick_c, dur, bpm)
    if eins is not None:
        off = int(round((eins - ph) / per)) % 4
        how = "vorgegeben"
        kb = cb = None
    else:
        off, how, kb, cb = downbeat_offset(beats, kick_c, clap_c)
    d0 = ph + off * per                         # erste Eins
    if d0 - 4 * per > -0.02:                    # Takt 0 = erste Eins ab Songstart
        d0 -= 4 * per * int((d0 + 0.02) // (4 * per))
    nbars = int((dur - d0) / (4 * per))
    bar_t = d0 + 4 * per * np.arange(nbars + 1)

    # --- Einsätze
    kt, kh = peaks_ms(kick_c, 0.35)
    ct, ch = peaks_ms(clap_c, 0.35, 60)
    pos = lambda t: (t - d0) / per              # Beat-Nummer ab Takt 0
    # nur Einsätze nahe am 1/4-Beat-Raster
    def on_grid(ts, hs, tol=0.035):
        out = []
        for t, h in zip(ts, hs):
            q = round(pos(t) * 4) / 4
            dt = t - (d0 + q * per)
            if abs(dt) <= tol:
                out.append((float(t), float(h), q, dt))
        return out
    # 808: frisch ab Stärke 1,2 (Log-Ableitung, pegelunabhängig); Nachschlag = schwächerer
    # Einsatz (ab 0,6) genau 1 Beat nach einem frischen 808 (an einem Drill-Song mit 140 BPM geeicht)
    k_all = on_grid(kt, kh)
    kinds, k808 = {}, []
    strong = {q: h for t, h, q, dt in k_all}
    for t, h, q, dt in k_all:
        if h >= 1.2:
            kinds[q] = "808"
        elif h >= 0.6 and kinds.get(q - 1) == "808":
            kinds[q] = "808_nachschlag"
        else:
            continue
        k808.append((t, h, q, dt))
    # Clap: Stärke auf jedem Beat, muss deutlich über den Nachbar-Beats liegen
    bt_all = d0 + per * np.arange(int((dur - d0) / per) + 1)
    cs = beat_strength(bt_all, clap_c, 20)
    thr = max(1.2, 0.5 * np.percentile(cs, 90))
    claps = []
    for i in range(1, len(cs) - 1):
        if cs[i] >= thr and cs[i] >= 1.4 * 0.5 * (cs[i - 1] + cs[i + 1]):
            claps.append((float(bt_all[i]), float(cs[i]), float(i), 0.0))
    onsets = {
        "kick808": [dict(t=round(t, 4), strength=round(h, 2), beat=q, off_ms=round(dt * 1000, 1), art=kinds[q])
                    for t, h, q, dt in k808],
        "clap": [dict(t=round(t, 4), strength=round(h, 2), beat=q, off_ms=round(dt * 1000, 1)) for t, h, q, dt in claps],
    }
    onsets["nachschlag"] = [o for o in onsets["kick808"] if o["art"] == "808_nachschlag"]
    grid_off = [o["off_ms"] for o in onsets["kick808"] if o["strength"] > 1.0]

    # --- Akzent-Karte pro Halbbeat
    kq = {o["beat"]: o for o in onsets["kick808"]}
    cq = {o["beat"]: o for o in onsets["clap"]}
    amap = []
    for hb in range(nbars * 8):
        q = hb / 2
        bar, r = divmod(hb, 8)
        o = kq.get(q)
        c = cq.get(q)
        if o:
            kind, st = o["art"], o["strength"]
        elif c:
            kind, st = "clap", c["strength"]
        else:
            kind, st = "none", 0.0
        bild = BILD[kind] if kind != "none" else (BILD["eins"] if r == 0 else "")
        if kind == "clap" and r != 4:
            bild = "Mini-Punch 0,06 (Clap nicht auf 3)"
        amap.append(dict(hb=hb, t=round(d0 + q * per, 4), bar=bar, beat_in_bar=1 + r / 2,
                         name=f"T{bar}.{HB_NAMES[r]}", kind=kind, strength=st, bild=bild))
    # Zwischen-Einsätze (1/4-Beats) nicht verlieren
    extra = [o for o in onsets["kick808"] if abs(o["beat"] * 2 - round(o["beat"] * 2)) > 1e-6]

    # --- Struktur
    agg, C, M, R = bar_features(y_lo, bar_t)
    Cb, Mb, Rb = agg(C, bar_t), agg(M, bar_t), agg(R, bar_t)[:, 0]
    k808_bar = np.zeros(nbars)
    clap_bar = np.zeros(nbars)
    for o in onsets["kick808"]:
        b = int(o["beat"] // 4)
        if 0 <= b < nbars:
            k808_bar[b] += 1
    for o in onsets["clap"]:
        b = int(o["beat"] // 4)
        if 0 <= b < nbars:
            clap_bar[b] += 1
    key = tonart(C)
    Fb = zfeat(Cb, Mb, Rb)
    secs, nov, p_off, S = sections(Fb, Rb, k808_bar, clap_bar, nbars)
    for s in secs:
        s["start"] = round(float(bar_t[s["bar_start"]]), 3)
        s["end"] = round(float(bar_t[s["bar_end"]]), 3)
        s["takte"] = s["bar_end"] - s["bar_start"]
    hooks = [s for s in secs if s["label"] == "hook"]

    # Hook-Start beatgenau gegenprüfen (Ähnlichkeit Hook 1 vs Hook 2 pro Beat)
    beat_edges = d0 + per * np.arange(nbars * 4 + 1)
    Cbt, Mbt, Rbt = agg(C, beat_edges), agg(M, beat_edges), agg(R, beat_edges)[:, 0]
    Fbt = zfeat(Cbt, Mbt, Rbt)
    hook_check = None
    if len(hooks) >= 2:
        a, b = hooks[0]["bar_start"] * 4, hooks[1]["bar_start"] * 4
        sim = {j: round(float(Fbt[a + j] @ Fbt[b + j]), 3) for j in range(-4, 5)
               if 0 <= a + j < len(Fbt) and 0 <= b + j < len(Fbt)}
        hook_check = dict(vergleich=f"T{hooks[0]['bar_start']} vs T{hooks[1]['bar_start']}",
                          aehnlichkeit_pro_beat=sim,
                          vorher=round(float(np.mean([v for j, v in sim.items() if j < 0])), 3),
                          ab_eins=round(float(np.mean([v for j, v in sim.items() if j >= 0])), 3))

    # --- Reel-Fenster
    def win(name, b0, b1, auftakt=0):
        start = float(bar_t[b0] - auftakt * per)
        end = float(bar_t[b1])
        ks = [o for o in onsets["kick808"] if start - 0.01 <= o["t"] < end]
        tail = [o for o in onsets["kick808"] if end - 0.150 <= o["t"] < end - 0.004]
        last_bar_808 = [o for o in onsets["kick808"] if bar_t[b1 - 1] <= o["t"] < end]
        nxt = [o for o in onsets["kick808"] if abs(o["t"] - end) < 0.03]
        e = float(np.mean(Rb[b0:b1]) - np.mean(Rb))
        dur_w = end - start
        checks = {
            "start_auf_eins": auftakt == 0,
            "ende_auf_eins": True,
            "kein_808_in_letzten_150ms": not tail,
            "808_genau_auf_ende": bool(nxt),
            "letzter_takt_break": not last_bar_808,
        }
        score = e + 1.5 * len(ks) / max(1, (b1 - b0)) + (2 if checks["letzter_takt_break"] else 0) - (5 if tail else 0)
        return dict(name=name, start=round(start, 3), end=round(end, 3), dauer=round(dur_w, 3),
                    takte=b1 - b0, beats=(b1 - b0) * 4 + auftakt, auftakt_beats=auftakt,
                    takt_von=f"T{b0}.1" if not auftakt else f"T{b0 - 1}.3", takt_bis=f"T{b1}.1",
                    n808=len(ks), checks=checks, score=round(score, 2),
                    reel_audio=dict(file=str(path), src=round(start, 4), at=0.0, dur=round(dur_w, 4),
                                    fade_in=0.004, fade_out=0.038),
                    ffmpeg_af=(f"atrim=start={start:.4f}:duration={dur_w:.4f},asetpts=PTS-STARTPTS,"
                               f"afade=t=in:d=0.004,afade=t=out:st={dur_w - 0.038:.4f}:d=0.038"))
    windows = []
    for i, h in enumerate(hooks, 1):
        b0, b1 = h["bar_start"], h["bar_end"]
        L = b1 - b0
        if L >= 16:
            windows.append(win(f"Hook {i}, 16 Takte", b0, b0 + 16))
            windows.append(win(f"Hook {i}, 2. Hälfte (8 Takte)", b0 + 8, b0 + 16))
        if L >= 8:
            windows.append(win(f"Hook {i}, 8 Takte", b0, b0 + 8))
        # Auftakt: 808 auf Schlag 3 des Takts davor
        if b0 >= 1 and any(abs(o["beat"] - (b0 * 4 - 2)) < 0.01 for o in onsets["kick808"]):
            windows.append(win(f"Hook {i}, 16 Takte mit Auftakt", b0, b0 + min(16, L), auftakt=2))
    if not hooks:                               # keine Hook gefunden: energiereichste Phrasen-Fenster
        for L in (16, 8):
            starts = [b for b in range(p_off, nbars - L + 1, 4)]
            if starts:
                b0 = max(starts, key=lambda b: float(np.mean(Rb[b:b + L])) + 0.3 * float(np.mean(k808_bar[b:b + L])))
                windows.append(win(f"Energie-Fenster {L} Takte (keine Hook erkannt)", b0, b0 + L))
    windows.sort(key=lambda w: (-(w["takte"] >= 16), -w["score"]))   # Standard: 16 Takte Hook (Anweisungen Punkt 9)

    lufs = tp = None
    try:
        import pyloudnorm as pyln
        xs = decode(path, SR, mono=False)
        lufs = round(float(pyln.Meter(SR).integrated_loudness(xs)), 2)
        up = ss.resample_poly(xs, 4, 1, axis=0)
        tp = round(float(20 * np.log10(np.abs(up).max() + 1e-12)), 2)
    except Exception as e:  # noqa
        print("Lautheit nicht gemessen:", e, file=sys.stderr)

    return dict(
        file=str(path), duration=round(dur, 3), sr=SR,
        bpm=round(60 / per, 3), beat_period=round(per, 6), beat_phase=round(ph, 4),
        downbeat_offset=int(round((d0 - ph) / per)) % 4, erste_eins=round(float(d0), 4), taktlage=how,
        kick_pro_schlag=kb, clap_pro_schlag=cb, regression=reg,
        raster_vs_808_ms=dict(median=round(float(np.median(grid_off)), 1) if grid_off else None,
                              max=round(float(np.max(np.abs(grid_off))), 1) if grid_off else None),
        beats=[round(float(b), 4) for b in beats],
        bars=[dict(n=i, t=round(float(t), 4)) for i, t in enumerate(bar_t)],
        phrasen_offset_takte=p_off,
        phrases=[dict(n=i, bar=b, start=round(float(bar_t[b]), 3), end=round(float(bar_t[min(b + 4, nbars)]), 3))
                 for i, b in enumerate(range(p_off, nbars, 4))],
        sections=secs, hooks=hooks, hook_check=hook_check,
        onsets=onsets, zwischen_808=extra, accent_map=amap, windows=windows,
        loudness=dict(lufs=lufs, true_peak_db=tp), tonart=key,
        _intern=dict(novelty=nov.round(3).tolist(), rms_bar=Rb.round(2).tolist(), k808_bar=k808_bar.tolist(),
                     clap_bar=clap_bar.tolist(), laufzeit_s=round(time.time() - t0, 1)),
    )


# ---------------------------------------------------------------- Ausgabe
def tab_line(A, b):
    sym = {"808": "8", "808_nachschlag": "n", "clap": "c", "none": "."}
    return "".join(sym[a["kind"]] for a in A[b * 8:(b + 1) * 8])


def write_md(A, out):
    L = [f"# Song-Analyse: {Path(A['file']).name}", "",
         f"- **{A['bpm']:.2f} BPM**, Beat {A['beat_period'] * 1000:.2f} ms, erste Eins {A['erste_eins']:.3f} s "
         f"(Taktlage: {A['taktlage']}), Dauer {A['duration']:.2f} s, {len(A['bars']) - 1} Takte",
         f"- Regression: {A['regression']['used']}/{A['regression']['librosa_beats']} Beats, Residuen Median "
         f"{A['regression']['residual_ms_median']} ms, 95 % {A['regression']['residual_ms_p95']} ms; "
         f"808 gegen Raster: Median {A['raster_vs_808_ms']['median']} ms, max {A['raster_vs_808_ms']['max']} ms",
         f"- Lautheit {A['loudness']['lufs']} LUFS, True Peak {A['loudness']['true_peak_db']} dBTP; Tonart "
         f"{A['tonart']['name']} (Camelot {A['tonart']['camelot']}, Sicherheit {A['tonart']['sicherheit']})",
         f"- Einsätze: {len(A['onsets']['kick808'])}× 808 (davon {len(A['onsets']['nachschlag'])} Nachschläge), "
         f"{len(A['onsets']['clap'])}× Clap", "", "## Songteile", "",
         "| Teil | Takte | Zeit | Gruppe | Energie | 808/Takt | Clap/Takt |", "|---|---|---|---|---|---|---|"]
    for s in A["sections"]:
        L.append(f"| {s['label']} | T{s['bar_start']}–T{s['bar_end'] - 1} ({s['takte']}) | {s['start']:.2f}–{s['end']:.2f} s | "
                 f"{s['gruppe']} | {s['energie_db']} dB | {s['n808_pro_takt']} | {s['clap_pro_takt']} |")
    if A["hook_check"]:
        h = A["hook_check"]
        L += ["", f"Hook-Start gegengeprüft ({h['vergleich']}): Ähnlichkeit pro Beat vor der Eins {h['vorher']}, "
                  f"ab der Eins {h['ab_eins']}."]
    L += ["", "## Empfohlene Reel-Fenster", "",
          "| # | Fenster | Takte | Zeit im Song | Dauer | 808 | Ende frei | Letzter Takt Break | Score |",
          "|---|---|---|---|---|---|---|---|---|"]
    for i, w in enumerate(A["windows"], 1):
        c = w["checks"]
        L.append(f"| {i} | {w['name']} | {w['takt_von']}–{w['takt_bis']} | {w['start']:.3f}–{w['end']:.3f} s | "
                 f"{w['dauer']:.2f} s | {w['n808']} | {'ja' if c['kein_808_in_letzten_150ms'] else 'NEIN'} | "
                 f"{'ja' if c['letzter_takt_break'] else 'nein'} | {w['score']} |")
    if A["windows"]:
        w = A["windows"][0]
        L += ["", f"Tonspur für Fenster 1 (ffmpeg): `-af \"{w['ffmpeg_af']}\"`",
              f"reel_audio.py: `{json.dumps(w['reel_audio'], ensure_ascii=False)}`"]
    L += ["", "## Akzent-Karte (8 = 808, n = 808-Nachschlag, c = Clap, . = nichts; Spalten 1 1+ 2 2+ 3 3+ 4 4+)", "", "```"]
    lab = {}
    for s in A["sections"]:
        lab[s["bar_start"]] = s["label"]
    for b in range(len(A["bars"]) - 1):
        L.append(f"T{b:<3d} {A['bars'][b]['t']:7.3f}s  {tab_line(A['accent_map'], b)}  {lab.get(b, '')}")
    L += ["```", "", "Bild-Akzent (Standard): 808 = Schnitt oder Punch 0,14 mit Blur, Nachschlag = 2. Punch 0,12, "
          "Clap auf 3 = Schnitt mit Mini-Punch 0,06, Eins ohne Akzent = harter Schnitt."]
    if A["zwischen_808"]:
        L += ["", "808 zwischen den Halbbeats (Punch im Shot, kein Schnitt): " +
              ", ".join(f"{o['t']:.3f} s (Beat {o['beat']})" for o in A["zwischen_808"][:30])]
    Path(out).write_text("\n".join(L) + "\n")


def plot(A, out_png, out_map):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = decode(A["file"], 4000)
    t = np.arange(len(x)) / 4000
    col = {"intro": "#9aa5b1", "hook": "#e4572e", "strophe": "#4c9f70", "break": "#f3a712", "outro": "#6c757d"}
    fig, ax = plt.subplots(2, 1, figsize=(16, 6.5), gridspec_kw=dict(height_ratios=[3, 1.2]), sharex=True)
    ax[0].plot(t[::4], x[::4], lw=0.3, color="#333")
    for s in A["sections"]:
        ax[0].axvspan(s["start"], s["end"], color=col.get(s["label"], "#ccc"), alpha=0.18)
        ax[0].text((s["start"] + s["end"]) / 2, 0.93, f"{s['label']} T{s['bar_start']}", ha="center", fontsize=9,
                   transform=ax[0].get_xaxis_transform(), bbox=dict(fc="white", ec="none", alpha=0.8))
    for b in A["bars"]:
        ax[0].axvline(b["t"], color="#999", lw=0.8 if b["n"] % 4 == 0 else 0.25)
    for o in A["onsets"]["kick808"]:
        ax[0].plot(o["t"], -1.05, "v", ms=4, color="#d00" if o["art"] == "808" else "#f80")
    for o in A["onsets"]["clap"]:
        ax[0].plot(o["t"], 1.05, "^", ms=3, color="#06c")
    if A["windows"]:
        w = A["windows"][0]
        ax[0].axvspan(w["start"], w["end"], ymin=0, ymax=0.04, color="#e4572e")
    ax[0].set_ylim(-1.15, 1.15)
    fig.suptitle(f"{Path(A['file']).name}  ·  {A['bpm']:.2f} BPM  ·  808 rot, Nachschlag orange, Clap blau, "
                    f"Linien = Takte (dick = Phrase)", fontsize=10)
    nov = np.array(A["_intern"]["novelty"])
    bt = [b["t"] for b in A["bars"]][:len(nov)]
    ax[1].bar(bt, nov / (nov.max() + 1e-9), width=4 * A["beat_period"] * 0.9, align="edge", color="#888", label="Neuheit")
    ax[1].bar(bt, np.array(A["_intern"]["k808_bar"]) / 8, width=4 * A["beat_period"] * 0.4, align="edge",
              color="#d00", label="808/Takt ÷ 8")
    ax[1].legend(fontsize=8, loc="upper right")
    ax[1].set_xlabel("Sekunde im Song")
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    # Akzent-Karte als Raster
    nb = len(A["bars"]) - 1
    cm = {"808": "#d62828", "808_nachschlag": "#f77f00", "clap": "#1d70b8", "none": "#f1f1f1"}
    fig, ax = plt.subplots(figsize=(7, 0.22 * nb + 1.2))
    lab = {s["bar_start"]: s["label"] for s in A["sections"]}
    for a in A["accent_map"]:
        r, c = a["bar"], a["hb"] % 8
        ax.add_patch(plt.Rectangle((c, nb - 1 - r), 0.95, 0.9, color=cm[a["kind"]]))
    for b in range(nb):
        ax.text(-0.3, nb - 1 - b + 0.45, f"T{b} {A['bars'][b]['t']:.2f}s", ha="right", va="center", fontsize=6.5)
        if b in lab:
            ax.text(8.2, nb - 1 - b + 0.45, lab[b], va="center", fontsize=7, color="#444")
            ax.axhline(nb - b + 0 - 0.05, color="#333", lw=0.8)
    for c, n in enumerate(HB_NAMES):
        ax.text(c + 0.47, nb + 0.2, n, ha="center", fontsize=7)
    ax.set_xlim(-3.2, 9.5)
    ax.set_ylim(-0.3, nb + 0.8)
    ax.axis("off")
    ax.set_title("Akzent-Karte: rot 808, orange Nachschlag, blau Clap", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_map, dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Song-Analyse für Reels (Beat, Takte, Hook, Akzente, Fenster)")
    ap.add_argument("song")
    ap.add_argument("-o", "--out", default=".")
    ap.add_argument("--bpm", type=float, help="Tempo vorgeben, z. B. 140")
    ap.add_argument("--eins", type=float, help="Zeit (s) einer Eins vorgeben, falls die Taktlage falsch erkannt wird")
    ap.add_argument("--kein-bild", action="store_true", help="keine PNGs zeichnen")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    A = analyse(a.song, a.bpm, a.eins)
    (out / "song.json").write_text(json.dumps(A, ensure_ascii=False, indent=1))
    # Raster im Format der Pipeline (schnitt/grid.json)
    hook = A["hooks"][0]["start"] if A["hooks"] else None
    (out / "grid.json").write_text(json.dumps(dict(per=A["beat_period"], ph=A["beat_phase"], bpm=A["bpm"], dur=A["duration"],
                                                   erste_eins=A["erste_eins"], hook_eins=hook)))
    write_md(A, out / "song.md")
    if not a.kein_bild:
        plot(A, out / "song.png", out / "akzentkarte.png")
    print(f"Tonart {A['tonart']['name']} ({A['tonart']['camelot']}), {A['loudness']['lufs']} LUFS")
    print(f"{A['bpm']:.2f} BPM, Phase {A['beat_phase']:.4f} s, erste Eins {A['erste_eins']:.4f} s ({A['taktlage']}), "
          f"Residuen {A['regression']['residual_ms_median']} ms")
    for s in A["sections"]:
        print(f"  {s['label']:8s} T{s['bar_start']:>2}–T{s['bar_end'] - 1:<2} {s['start']:7.3f}–{s['end']:7.3f} s  "
              f"Gruppe {s['gruppe']}  {s['energie_db']} dB  808/T {s['n808_pro_takt']}")
    for w in A["windows"][:4]:
        print(f"  Fenster: {w['name']:34s} {w['start']:.3f}–{w['end']:.3f} s ({w['dauer']:.2f} s)  Score {w['score']}")
    print(f"-> {out / 'song.json'}, grid.json, song.md, song.png, akzentkarte.png  ({A['_intern']['laufzeit_s']} s)")


if __name__ == "__main__":
    main()
