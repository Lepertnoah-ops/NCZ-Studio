#!/usr/bin/env python3
"""Synthetisches Soundeffekt-Grundkit für Reels (48 kHz, Stereo, WAV 24 bit).

Aufruf:  python3 make_sfx_kit.py [Zielordner] [--alle] [--ohne-vorschau]
         (Standard-Ziel: sfx/ im Projektordner)
Standardmäßig werden nur fehlende WAVs geschrieben (vorhandene bleiben bit-genau
gleich); --alle schreibt alle neu. README.md (alle Sounds, mit Hörprobe-Zeitpunkt)
und sfx_vorschau.mp3 werden immer neu gebaut (außer --ohne-vorschau).

Jeder Effekt hat einen definierten Ankerpunkt, damit reel_audio.py ihn
sample-genau auf einen Schnitt/Beat legen kann (align):
  whoosh, swoosh, reverse_swell, riser  -> "peak" bzw. "end" liegt auf dem Schnitt
  impact, punch, bass_drop, tick, shutter -> "start" liegt auf dem Hit
  Erweiterung (KIT_NEU): whoosh_soft, swipe_up/down, zoom_whoosh -> "peak",
  alle anderen neuen -> "start" (countdown: langer Startton bei +3,0 s)
Eigene SFX (MP3/WAV aus dem Drive-Ordner) funktionieren genauso.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import Pedalboard, Reverb, HighpassFilter, LowpassFilter
from scipy.signal import butter, hilbert, resample_poly, sosfilt

SR = 48000
rng = np.random.default_rng(7)


def t(d):
    return np.arange(int(d * SR)) / SR


def bandsweep(noise, f0, f1, q=2.0, steps=64):
    """Rauschen durch einen Bandpass, dessen Mittenfrequenz exponentiell von f0 nach f1 läuft."""
    n = len(noise)
    out = np.zeros(n)
    edges = np.linspace(0, n, steps + 1).astype(int)
    for i in range(steps):
        fc = f0 * (f1 / f0) ** ((i + 0.5) / steps)
        lo, hi = fc / (1 + 1 / q), min(fc * (1 + 1 / q), SR / 2 - 100)
        sos = butter(2, [lo, hi], btype="band", fs=SR, output="sos")
        a, b = max(edges[i] - 2048, 0), edges[i + 1]
        seg = sosfilt(sos, noise[a:b])
        out[edges[i]:b] = seg[edges[i] - a:]
    return out


def stereo(x, pan_from=0.0, pan_to=0.0):
    p = np.linspace(pan_from, pan_to, len(x))  # -1 links .. +1 rechts
    ang = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(ang), x * np.sin(ang)], axis=1)


def norm(x, peak_db=-1.0):
    return x / (np.max(np.abs(x)) + 1e-12) * 10 ** (peak_db / 20)


def fx(x, board):
    return board(x.T.astype(np.float32), SR).T


def whoosh(d=0.7, peak_at=0.62, f0=300, f1=4500):
    tt = t(d)
    env = np.where(tt < d * peak_at, (tt / (d * peak_at)) ** 2.2,
                   np.exp(-(tt - d * peak_at) / (d * 0.12)))
    x = bandsweep(rng.standard_normal(len(tt)), f0, f1, q=1.6) * env
    return fx(stereo(x, -0.6, 0.6), Pedalboard([Reverb(room_size=0.25, wet_level=0.15, dry_level=0.9)]))


def impact(d=1.8):
    tt = t(d)
    f = 34 + 46 * np.exp(-tt / 0.08)              # 80 Hz -> 34 Hz
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.45)
    crack = rng.standard_normal(len(tt)) * np.exp(-tt / 0.018)
    crack = sosfilt(butter(2, 900, btype="high", fs=SR, output="sos"), crack) * 0.6
    body = sosfilt(butter(2, [120, 900], btype="band", fs=SR, output="sos"),
                   rng.standard_normal(len(tt))) * np.exp(-tt / 0.12) * 0.9
    x = np.tanh(1.6 * (sub + crack + body))
    return fx(stereo(x), Pedalboard([Reverb(room_size=0.7, damping=0.6, wet_level=0.22, dry_level=0.9, width=1.0)]))


def punch(d=0.35):
    tt = t(d)
    f = 48 + 90 * np.exp(-tt / 0.025)
    thump = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.07)
    snap = sosfilt(butter(2, 1500, btype="high", fs=SR, output="sos"),
                   rng.standard_normal(len(tt))) * np.exp(-tt / 0.008) * 0.7
    return stereo(np.tanh(2.0 * (thump + snap)))


def bass_drop(d=1.2):
    tt = t(d)
    f = 38 + 110 * np.exp(-tt / 0.25)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(tt / 0.005, 1) * np.exp(-tt / 0.6)
    return stereo(np.tanh(1.8 * x))


def riser(d=3.0):
    tt = t(d)
    env = (tt / d) ** 2.5
    noise = bandsweep(rng.standard_normal(len(tt)), 400, 9000, q=1.2) * env
    f = 110 * (8 ** (tt / d))
    saw = 2 * ((np.cumsum(f) / SR) % 1.0) - 1
    saw = sosfilt(butter(2, 3000, btype="low", fs=SR, output="sos"), saw) * env * 0.35
    x = noise + saw
    x[-int(0.004 * SR):] *= np.linspace(1, 0, int(0.004 * SR))  # sauberer Abriss am Ende
    return fx(stereo(x, 0, 0), Pedalboard([Reverb(room_size=0.5, wet_level=0.2, dry_level=0.9, width=1.0)]))


def reverse_swell(d=1.5):
    tt = t(d)
    x = sosfilt(butter(2, 2500, btype="high", fs=SR, output="sos"), rng.standard_normal(len(tt)))
    x = x * np.exp(-tt / 0.35)                                   # "Becken"-Ausklang ...
    x = fx(stereo(x), Pedalboard([Reverb(room_size=0.8, wet_level=0.5, dry_level=0.6, width=1.0)]))
    x = x[::-1].copy()                                           # ... rückwärts
    x[-int(0.004 * SR):] *= np.linspace(1, 0, int(0.004 * SR))[:, None]
    return x


def tick(d=0.06):
    tt = t(d)
    x = np.sin(2 * np.pi * 2200 * tt) * np.exp(-tt / 0.008)
    x += sosfilt(butter(2, 4000, btype="high", fs=SR, output="sos"),
                 rng.standard_normal(len(tt))) * np.exp(-tt / 0.003) * 0.4
    return stereo(x)


def shutter(d=0.25):
    tt = t(d)
    click = lambda at, dec: np.where(tt >= at, np.exp(-(tt - at) / dec), 0)
    n = sosfilt(butter(2, [1500, 9000], btype="band", fs=SR, output="sos"), rng.standard_normal(len(tt)))
    x = n * (click(0.0, 0.006) + 0.7 * click(0.09, 0.01))
    return fx(stereo(x), Pedalboard([Reverb(room_size=0.15, wet_level=0.1)]))


KIT = {
    # name: (Funktion, Anker, Beschreibung)
    "whoosh": (lambda: whoosh(), "peak", "Übergang, Peak auf den Schnitt legen"),
    "swoosh_short": (lambda: whoosh(0.28, 0.7, 700, 7000), "peak", "kurzer, heller Swipe für schnelle Cuts"),
    "whoosh_low": (lambda: whoosh(0.9, 0.6, 120, 1600), "peak", "tiefer, schwerer Übergang"),
    "impact": (impact, "start", "cinematischer Einschlag mit Sub, für Titel/Payoff"),
    "punch": (punch, "start", "trockener Schlag, für Treffer/Slams"),
    "bass_drop": (bass_drop, "start", "Sub-Drop unter einen Drop/Hit"),
    "riser": (riser, "end", "3-s-Aufbau, Ende auf den Drop"),
    "reverse_swell": (reverse_swell, "end", "Rückwärts-Becken, Ende auf den Schnitt"),
    "tick": (tick, "start", "Klick für Text-Pops"),
    "shutter": (shutter, "start", "Kamera-Auslöser für Freeze-Frames"),
}


# ---------------------------------------------------------------------------
# Erweiterung: 18 weitere Sounds (dezent, sauber). Eigene Zufallsquelle rng2,
# die jede neue Funktion explizit bekommt -> die 10 Grundsounds oben bleiben
# bit-genau gleich (sie verbrauchen weiterhin nur rng, in derselben Reihenfolge).
# ---------------------------------------------------------------------------
rng2 = np.random.default_rng(11)


def filt(x, kind, f, order=2):
    return sosfilt(butter(order, f, btype=kind, fs=SR, output="sos"), x, axis=0)


def ramp(n, rising=True):
    """Halbe Kosinus-Rampe (klickfrei)."""
    r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))
    return r if rising else r[::-1]


def clean(x, hp=30, lp=None, fin=0.002, fout=0.01, hp_order=2):
    """Subs < hp und DC raus, optional Höhen zähmen, klickfreie Ränder (mono/stereo)."""
    x = filt(np.asarray(x, dtype=np.float64), "high", hp, hp_order)
    if lp:
        x = filt(x, "low", lp)
    x = x - x.mean(axis=0)
    a, b = max(int(fin * SR), 2), max(int(fout * SR), 2)
    shape = (-1,) + (1,) * (x.ndim - 1)
    x[:a] *= ramp(a).reshape(shape)
    x[-b:] *= ramp(b, False).reshape(shape)
    return x


def sweep_lowpass(x, fcs, steps=128):
    """Tiefpass mit zeitlich veränderlicher Grenzfrequenz (fcs: Array wie x)."""
    n = len(x)
    out = np.zeros(n)
    e = np.linspace(0, n, steps + 1).astype(int)
    for i in range(steps):
        fc = float(np.clip(np.mean(fcs[e[i]:e[i + 1]]), 40, SR / 2 - 200))
        a, b = max(e[i] - 2048, 0), e[i + 1]
        out[e[i]:b] = sosfilt(butter(2, fc, btype="low", fs=SR, output="sos"), x[a:b])[e[i] - a:]
    return out


def flatten(x, smooth=0.004, amount=0.8):
    """Hüllkurve von Rauschen glätten, damit der lauteste Sample auf dem Hüllkurven-Peak liegt."""
    w = int(smooth * SR)
    e = np.convolve(np.abs(hilbert(x)), np.ones(w) / w, mode="same")
    return x / (e + 1e-9) ** amount


def glide(f):
    """Sinus mit zeitlich veränderlicher Frequenz (Array in Hz)."""
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def room(x, size=0.3, damping=0.6, wet=0.15, dry=0.9, width=1.0):
    return fx(x, Pedalboard([Reverb(room_size=size, damping=damping, wet_level=wet, dry_level=dry, width=width)]))


def sub_hit(r, d=0.6):
    tt = t(d)
    x = glide(50 + 40 * np.exp(-tt / 0.035))                  # 90 Hz -> 50 Hz
    x = np.tanh(1.3 * x * np.minimum(tt / 0.004, 1) ** 2 * np.exp(-tt / 0.16)) / np.tanh(1.3)
    return stereo(clean(x, hp=30, lp=400, fout=0.03))


def soft_whoosh(r, d, peak_at, f0, f1, q, tau, lp, pan, verb):
    tt = t(d)
    tp = d * peak_at
    env = np.where(tt < tp, (tt / tp) ** 2.4, np.exp(-(tt - tp) / tau))
    x = flatten(bandsweep(r.standard_normal(len(tt)), f0, f1, q=q)) * env
    return clean(room(stereo(filt(x, "low", lp), *pan), **verb), hp=60, lp=lp, fout=0.02)


def whoosh_soft(r):
    return soft_whoosh(r, 0.8, 0.62, 180, 1500, 1.1, 0.085, 3500, (-0.4, 0.4),
                       dict(size=0.35, damping=0.7, wet=0.18, dry=0.85, width=0.8))


def swipe(r, f0, f1, pan):
    return soft_whoosh(r, 0.4, 0.68, f0, f1, 2.2, 0.03, 9000, pan,
                       dict(size=0.2, damping=0.6, wet=0.12, dry=0.9, width=0.9))


def zoom_whoosh(r, d=0.6, peak_at=0.75):
    tt = t(d)
    tp = d * peak_at
    env = np.where(tt < tp, (tt / tp) ** 2.6, np.exp(-(tt - tp) / 0.04))
    noise = flatten(bandsweep(r.standard_normal(len(tt)), 250, 3500, q=1.5)) * 0.3
    ph = 2 * np.pi * np.cumsum(180 * 5 ** np.minimum(tt / tp, 1.0)) / SR   # Ton 180 -> 900 Hz
    tone = filt(np.sin(ph) + 0.5 * np.sin(1.006 * ph + 1.0) + 0.25 * np.sin(2 * ph), "low", 2500) * 0.3
    x = flatten(noise + tone, amount=0.7) * env
    return clean(room(stereo(x, -0.3, 0.3), size=0.3, wet=0.15), hp=80, lp=8000, fout=0.02)


def glitch(r, d=0.35):
    n = len(t(d))
    out = np.zeros((n, 2))
    tb = t(0.08)
    src = (np.tanh(3 * np.sin(2 * np.pi * 330 * tb)) * 0.5 + np.sin(2 * np.pi * 990 * tb) * 0.3
           + filt(r.standard_normal(len(tb)), "band", [800, 5000]) * 0.6)
    # (Start, Länge, Pegel, Sample-and-Hold-Faktor, Bits, Tonhöhe, Panorama): 4 kleiner werdende Wiederholungen
    for at, ln, lvl, hold, bits, rate, pan in ((0.000, 0.060, 1.00, 6, 5, 1.00, -0.2),
                                               (0.075, 0.045, 0.75, 9, 4, 1.12, 0.25),
                                               (0.132, 0.032, 0.60, 12, 4, 0.94, -0.1),
                                               (0.176, 0.024, 0.45, 16, 3, 1.25, 0.15)):
        m = int(ln * SR)
        seg = np.interp(np.arange(m) * rate, np.arange(len(src)), src)
        seg = np.repeat(seg[::hold], hold)[:m]                                   # Samplerate runter
        q = 2 ** (bits - 1)
        seg = np.round(seg * q) / q                                               # Bitcrusher
        f = int(0.0015 * SR)
        seg[:f] *= ramp(f)
        seg[-f:] *= ramp(f, False)
        i = int(at * SR)
        out[i:i + m] += stereo(seg * lvl, pan, pan)
    out = filt(out, "low", 7000)
    return clean(room(out, size=0.15, wet=0.12, dry=0.95), hp=120, lp=8000, fin=0.001, fout=0.03)


def tape_stop(r, d=0.8, t_stop=0.68):
    tt = t(d)
    bt = t(1.2)
    buf = np.zeros(len(bt))
    for f in (110.0, 164.8, 220.0, 261.6, 329.6):                                # A-Moll-Pad
        for det in (-0.004, 0.004):
            ph = 2 * np.pi * f * (1 + det) * bt + r.uniform(0, 2 * np.pi)
            buf += sum(np.sin(k * ph) / k for k in range(1, int(5000 / f) + 1))     # bandbegrenzter Sägezahn
    buf /= np.max(np.abs(buf))
    rate = np.clip(1 - tt / t_stop, 0, 1) ** 1.3                                  # Band bremst bis 0
    pos = 0.1 * SR + np.cumsum(rate)
    y = np.interp(pos, np.arange(len(buf)), buf) * rate ** 0.4
    y = sweep_lowpass(y, 250 + 6500 * rate ** 1.5, steps=512)                     # Filter schließt mit
    return stereo(clean(y, hp=35, lp=8000, fin=0.004, fout=0.02, hp_order=4))


def rewind(r, d=0.9):
    tt = t(d)
    # "Musik" auf dem Band: zufällige Pentatonik-Töne + Bandrauschen
    bt = t(4.0)
    buf = np.zeros(len(bt))
    step = int(0.09 * SR)
    for i in range(0, len(bt), step):
        f = r.choice([220.0, 247.5, 277.2, 330.0, 370.0, 440.0, 495.0, 554.4, 660.0])
        nt = bt[:min(step * 2, len(bt) - i)]
        buf[i:i + len(nt)] += sum(np.sin(2 * np.pi * k * f * nt) / k for k in (1, 2, 3)) * np.exp(-nt / 0.07)
    buf += filt(r.standard_normal(len(bt)), "band", [1000, 4000]) * 0.15
    buf = filt(buf, "low", 1500, 4)                                               # Raum für die Beschleunigung
    fm = 5 + 11 * (tt / d) ** 1.2                                                 # Hin-und-her 5 -> 16 Hz
    rate = -(1.2 + 1.8 * tt / d) + 2.6 * np.sin(2 * np.pi * np.cumsum(fm) / SR)
    pos = (2.0 * SR + np.cumsum(rate)) % (len(buf) - 1)
    y = np.interp(pos, np.arange(len(buf)), buf) * np.minimum(np.abs(rate), 1) ** 0.5
    y = filt(filt(y, "high", 150), "low", 6000)
    y = y * np.minimum(tt / 0.02, 1) * np.minimum((d - tt) / 0.08, 1)
    return clean(room(stereo(y, -0.2, 0.2), size=0.2, wet=0.1, dry=0.95), hp=100, lp=7000, fin=0.003, fout=0.02)


def flash_pop(r, d=0.5):
    tt = t(d)
    pop = filt(r.standard_normal(len(tt)), "band", [1200, 7000]) * np.exp(-tt / 0.006)
    body = glide(160 + 200 * np.exp(-tt / 0.004)) * np.exp(-tt / 0.025) * 0.8
    whine = glide(6200 - 700 * (1 - np.exp(-tt / 0.15))) * np.minimum(tt / 0.01, 1) * np.exp(-tt / 0.12) * 0.07
    return clean(room(stereo(pop + body + whine), size=0.25, damping=0.5, wet=0.15), hp=80, lp=9500, fin=0.0015, fout=0.03)


def heartbeat(r, d=1.0):
    tt = t(d)
    x = np.zeros(len(tt))
    for at, amp, fh, fl, dec in ((0.0, 1.0, 95, 52, 0.07), (0.28, 0.75, 110, 60, 0.06)):   # lub - dub
        i = int(at * SR)
        s = tt[:len(tt) - i]
        att = np.minimum(s / 0.006, 1) ** 2
        th = glide(fl + (fh - fl) * np.exp(-s / 0.02)) * att * np.exp(-s / dec)
        body = filt(r.standard_normal(len(s)), "band", [70, 300]) * att * np.exp(-s / 0.03) * 0.35
        x[i:] += (th + body) * amp
    return stereo(clean(np.tanh(1.2 * x), hp=30, lp=450, fout=0.05))


def pop(r, d=0.12):
    tt = t(d)
    x = glide(280 + 700 * (1 - np.exp(-tt / 0.012))) * np.minimum(tt / 0.0015, 1) ** 2 * np.exp(-tt / 0.018)
    return stereo(clean(x, hp=120, lp=3000, fin=0.001, fout=0.02))


def typing(r, d=1.2, keys=9):
    n = len(t(d))
    out = np.zeros((n, 2))
    kt = t(0.06)
    at = 0.0
    for _ in range(keys):
        lvl, pan = r.uniform(0.55, 1.0), r.uniform(-0.2, 0.2)
        click = filt(r.standard_normal(len(kt)), "band", [r.uniform(1800, 2600), r.uniform(5000, 7000)])
        click *= np.exp(-kt / r.uniform(0.0025, 0.004))
        thock = np.sin(2 * np.pi * r.uniform(280, 420) * kt) * np.exp(-kt / 0.012) * 0.5
        i = int(at * SR)
        out[i:i + len(kt)] += stereo((click + thock) * lvl * np.minimum(kt / 0.0005, 1), pan, pan)
        at += r.uniform(0.075, 0.14)                                                # leicht unregelmäßig
    return clean(room(out, size=0.12, damping=0.7, wet=0.08, dry=1.0, width=0.6), hp=150, lp=8500, fin=0.0015, fout=0.05)


def boom_far(r, d=2.5):
    tt = t(d)
    sub = glide(42 + 33 * np.exp(-tt / 0.12)) * np.exp(-tt / 0.5)                  # 75 Hz -> 42 Hz
    rumble = filt(r.standard_normal(len(tt)), "low", 180, 4) * np.exp(-tt / 0.35) * 1.2
    x = filt(np.tanh(1.3 * (sub + rumble) * (1 - np.exp(-tt / 0.012))), "low", 900)   # weicher Anstieg = fern
    return clean(room(stereo(x), size=0.92, damping=0.85, wet=0.45, dry=0.75), hp=35, lp=1200, fin=0.003, fout=0.25, hp_order=4)


def downlifter(r, d=2.0):
    tt = t(d)
    env = np.minimum(tt / 0.03, 1) ** 2 * (1 - tt / d) ** 2.2
    x = bandsweep(r.standard_normal(len(tt)), 4500, 150, q=1.3, steps=96) * env
    x += glide(60 + 340 * np.exp(-tt / 0.45)) * env * 0.15                          # leiser fallender Ton
    return clean(room(stereo(x, 0.3, -0.3), size=0.5, wet=0.2, dry=0.85), hp=40, lp=8000, fout=0.1)


def vinyl_scratch(r, d=0.5, T=0.2, vmax=2.4):
    bt = t(1.0)
    ph = 2 * np.pi * np.cumsum(160 * (1 + 0.01 * np.sin(2 * np.pi * 5 * bt))) / SR
    saw = sum(np.sin(k * ph) / k for k in range(1, 50) if k * 160 < 9000)
    voc = sum(filt(saw, "band", [fc * 0.85, fc * 1.15]) * g for fc, g in ((730, 1.0), (1090, 0.6), (2440, 0.25)))
    voc = voc + filt(r.standard_normal(len(bt)), "band", [500, 4000]) * 0.05        # "Aah"-Sample
    tt = t(d)
    v = np.where(tt < 2 * T, vmax * np.sin(2 * np.pi * tt / T), 0.0)                 # 2x vor-zurück (Baby-Scratch)
    y = np.interp(0.15 * SR + np.cumsum(v), np.arange(len(voc)), voc) * np.abs(v / vmax) ** 0.6
    return clean(room(stereo(y), size=0.15, wet=0.08, dry=1.0), hp=90, lp=7000, fout=0.03)


def shimmer(r, d=1.5):
    tt = t(d)
    n = len(tt)
    out = np.zeros((n, 2))
    env = np.minimum(tt / 0.06, 1) ** 2 * np.exp(-tt / 0.45)
    for f in (2637.0, 3136.0, 3951.0, 5274.0, 6272.0):                               # E-Moll ganz hoch
        for ch in (0, 1):
            am = 1 + 0.3 * np.sin(2 * np.pi * r.uniform(3, 7) * tt + r.uniform(0, 2 * np.pi))
            out[:, ch] += (np.sin(2 * np.pi * f * (1 + r.uniform(-0.003, 0.003)) * tt + r.uniform(0, 2 * np.pi))
                           * am * env * (2637 / f) ** 0.5 * 0.2)
    gt = t(0.08)
    for _ in range(26):                                                               # kleine Glitzer-Pings
        i = int(r.uniform(0, 1) ** 1.6 * 1.1 * SR)
        g = (np.sin(2 * np.pi * r.uniform(3500, 8500) * gt) * np.minimum(gt / 0.002, 1)
             * np.exp(-gt / r.uniform(0.015, 0.04)) * r.uniform(0.05, 0.18))
        p = r.uniform(-0.8, 0.8)
        m = min(len(gt), n - i)
        out[i:i + m] += stereo(g, p, p)[:m]
    return clean(room(out, size=0.75, damping=0.4, wet=0.4, dry=0.7), hp=1000, lp=11000, fin=0.003, fout=0.15)


def startschuss(r, d=1.8):
    tt = t(d)
    n = len(tt)
    crack = filt(r.standard_normal(n) * np.exp(-tt / 0.0025), "band", [700, 7500]) * 1.4
    body = filt(r.standard_normal(n), "band", [250, 2500]) * np.exp(-tt / 0.02) * 0.6
    boom = glide(90 + 120 * np.exp(-tt / 0.005)) * np.exp(-tt / 0.03) * 0.5
    dry = np.tanh(1.2 * (crack + body + boom))
    x = stereo(dry)
    for dt, g, lpf, pan in ((0.16, 0.32, 3500, -0.4), (0.37, 0.18, 2500, 0.35),       # Echo von Wänden/Tribüne
                            (0.62, 0.09, 1800, -0.2), (0.95, 0.05, 1200, 0.2)):
        i = int(dt * SR)
        x[i:] += stereo(filt(dry, "low", lpf)[:n - i] * g, pan, pan)
    return clean(room(x, size=0.6, damping=0.7, wet=0.18, dry=0.9), hp=60, lp=8000, fin=0.0015, fout=0.2)


def countdown(r, d=4.0):
    x = np.zeros(len(t(d)))

    def beep(at, f, ln, amp):
        m = int(ln * SR)
        bt = np.arange(m) / SR
        s = np.sin(2 * np.pi * f * bt) + 0.12 * np.sin(4 * np.pi * f * bt) + 0.05 * np.sin(6 * np.pi * f * bt)
        e = np.ones(m)
        a, b = int(0.004 * SR), int(0.02 * SR)
        e[:a], e[-b:] = ramp(a), ramp(b, False)
        i = int(round(at * SR))
        x[i:i + m] += s * e * amp

    for k in range(3):
        beep(float(k), 880.0, 0.16, 0.8)                                             # 3 - 2 - 1
    beep(3.0, 1760.0, 0.6, 0.7)                                                       # Start!
    return clean(room(stereo(x), size=0.3, wet=0.1, dry=0.95, width=0.8), hp=200, lp=7000, fout=0.1)


KIT_NEU = {
    "sub_hit": (lambda: sub_hit(rng2), "start", "leiser Sub unter einen Zoom-Punch legen"),
    "whoosh_soft": (lambda: whoosh_soft(rng2), "peak", "sehr weicher, luftiger Übergang für ruhige Schnitte"),
    "swipe_up": (lambda: swipe(rng2, 500, 5000, (-0.5, 0.5)), "peak", "steigender Swipe für Slide-/Push-up-Übergänge"),
    "swipe_down": (lambda: swipe(rng2, 5000, 500, (0.5, -0.5)), "peak", "fallender Swipe für Slide-down-Übergänge"),
    "zoom_whoosh": (lambda: zoom_whoosh(rng2), "peak", "Whoosh mit steigendem Ton für Zoom-in-Übergänge"),
    "glitch": (lambda: glitch(rng2), "start", "kurzer, dezenter Digital-Glitch für Glitch-Cuts"),
    "tape_stop": (lambda: tape_stop(rng2), "start", "Tape-Stop/Power-down, z. B. vor einer Pause oder einem Musikstopp"),
    "rewind": (lambda: rewind(rng2), "start", "Zurückspulen für Rewind-/Rückblenden-Momente"),
    "flash_pop": (lambda: flash_pop(rng2), "start", "Blitz-Pop für Weißblitze/Flash-Übergänge"),
    "heartbeat": (lambda: heartbeat(rng2), "start", "zwei leise Herzschläge für Slow-Motion-Momente"),
    "pop": (lambda: pop(rng2), "start", "weicher Pop für Text-Einblendungen (sanfter als tick)"),
    "typing": (lambda: typing(rng2), "start", "Tastenklicks für Schreibmaschinen-Text"),
    "boom_far": (lambda: boom_far(rng2), "start", "ferner, dunkler Kino-Boom mit langem Hall"),
    "downlifter": (lambda: downlifter(rng2), "start", "fallendes Rauschen, lässt einen Drop/Hit ausklingen"),
    "vinyl_scratch": (lambda: vinyl_scratch(rng2), "start", "kurzer DJ-Scratch für Beat-Wechsel oder Rewinds"),
    "shimmer": (lambda: shimmer(rng2), "start", "sanftes Glitzern für Logo-/Titel-Reveals"),
    "startschuss": (lambda: startschuss(rng2), "start", "Startschuss mit Echo für den Rennstart"),
    "countdown": (lambda: countdown(rng2), "start",
                  "Zeitnahme-Pieptöne bei 0/1/2 s, langer Startton bei +3,0 s (at = Startmoment − 3 s)"),
}


def laenge(path):
    info = sf.info(str(path))
    return info.frames / info.samplerate


def zeit(s):
    s = round(s, 1)
    m = int(s // 60)
    return f"{m}:{s - 60 * m:04.1f}"


def vorschau(out, names, pause=0.8):
    """Alle Sounds hintereinander (je `pause` s Stille); gibt Audio und Startzeiten zurück."""
    parts, starts, pos = [], [], 0
    for name in names:
        y, sr = sf.read(str(out / f"{name}.wav"), dtype="float64", always_2d=True)
        if sr != SR:
            y = resample_poly(y, SR, sr, axis=0)
        y = np.repeat(y, 2, axis=1) if y.shape[1] == 1 else y[:, :2]
        starts.append(pos / SR)
        gap = np.zeros((int(round(pause * SR)), 2))
        parts += [y, gap]
        pos += len(y) + len(gap)
    return np.concatenate(parts), starts


def mp3(x, ziel):
    """Hörprobe als MP3 (48 kHz Stereo, 192 kbit/s); -2 dB Luft gegen MP3-Übersteuerung."""
    with tempfile.TemporaryDirectory() as tmp:
        wav, mp = Path(tmp) / "vorschau.wav", Path(tmp) / "vorschau.mp3"
        sf.write(wav, (x * 10 ** (-2 / 20)).astype(np.float32), SR, subtype="PCM_24")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-ar", str(SR), "-ac", "2",
                        "-c:a", "libmp3lame", "-b:a", "192k", str(mp)], check=True)
        shutil.copyfile(mp, ziel)


def main():
    ap = argparse.ArgumentParser(description="SFX-Kit erzeugen, README + Hörprobe aktualisieren")
    ap.add_argument("ziel", nargs="?", default=str(Path(__file__).resolve().parent.parent / "sfx"), help="Zielordner")
    ap.add_argument("--alle", action="store_true", help="alle WAVs neu schreiben (Standard: nur fehlende)")
    ap.add_argument("--ohne-vorschau", action="store_true", help="sfx_vorschau.mp3 nicht neu bauen")
    args = ap.parse_args()
    out = Path(args.ziel)
    out.mkdir(parents=True, exist_ok=True)
    kit = {**KIT, **KIT_NEU}
    rows = []
    for name, (fn, anchor, desc) in kit.items():
        path = out / f"{name}.wav"
        # immer berechnen, damit rng/rng2 in derselben Reihenfolge laufen (fehlende Dateien = identisch zu --alle)
        x = norm(np.asarray(fn(), dtype=np.float64), -1.0)
        neu = args.alle or not path.exists()
        if neu:
            sf.write(path, x.astype(np.float32), SR, subtype="PCM_24")
        rows.append((name, anchor, laenge(path), desc))
        print(f"{name:14s} {anchor:5s} {rows[-1][2]:5.2f}s  {'geschrieben' if neu else 'vorhanden, unverändert'}")
    audio, starts = vorschau(out, list(kit))
    if not args.ohne_vorschau:
        mp3(audio, out / "sfx_vorschau.mp3")
        print(f"sfx_vorschau.mp3  {len(audio) / SR:.1f} s")
    lines = ["# SFX-Grundkit (synthetisch, 48 kHz Stereo)", "",
             "Anker = welcher Punkt der Datei auf `at` gelegt wird (reel_audio.py `align`).", "",
             "Hörprobe ab = Zeitpunkt in `sfx_vorschau.mp3` (alle Sounds in Tabellenreihenfolge, je 0,8 s Pause).", "",
             "| Datei | Anker | Länge | Einsatz | Hörprobe ab |", "|---|---|---|---|---|"]
    for (name, anchor, dur, desc), s in zip(rows, starts):
        lines.append(f"| {name}.wav | {anchor} | {dur:.2f} s | {desc} | {zeit(s)} |")
    lines += ["", "Standard im Reel: keine oder höchstens 1–2 leise SFX, deutlich unter der Musik "
                  "(etwa −14 bis −18 dB, `gain_db` in reel_audio.py)."]
    (out / "README.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
