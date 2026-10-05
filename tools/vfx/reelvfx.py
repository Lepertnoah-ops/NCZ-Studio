#!/usr/bin/env python3
"""reelvfx: Effekt-Bibliothek + Renderer für Reels (1080x1920 @30 fps).

    python3 reelvfx.py list                         # alle Effekte mit Standardwerten
    python3 reelvfx.py check  spec.json             # Effekt-Budget laut stil.json prüfen
    python3 reelvfx.py render spec.json out.mp4 [--master] [--von S] [--bis S]
    python3 reelvfx.py stills spec.json ordner t1 t2 ...   # Standbilder (JPG) zu Zeitpunkten
    python3 reelvfx.py cuts video.mp4 [schwelle]    # Schnitte finden (Liste für "cuts")
    python3 reelvfx.py stabilize in.mp4 out.mp4 [glaettung]   # vidstab, 2 Pässe
    python3 reelvfx.py slowmo in.mp4 out.mp4 [faktor]         # Zeitlupe per optischem Fluss
    python3 reelvfx.py safezones bild.jpg out.jpg   # Instagram-Safe-Zones einzeichnen

Die spec (fx.json) ist beat-gesteuert. Zeiten: "beat" (Beats ab beat0) oder "t" (Sekunden).

{
  "per": 0.42858, "beat0": 0.0,          # Sekunden pro Beat, Reel-Zeit von Beat 0
  "video": "schnitt.mp4",                # A) fertiger Schnitt ...
  "cuts": [0.857, 2.571],                #    ... Schnittzeiten für Übergänge (oder "auto")
  "clips": [                             # B) oder Clips direkt aus dem Rohmaterial
    {"file": "IMG_6124.MOV", "src": 3.2, "beats": 4, "speed": "ramp", "focus": [0.5, 0.45],
     "push": [1.0, 1.06], "gain": "auto", "hdr": false}
  ],
  "lut": "clean",                        # Look aus looks.py oder .cube-Pfad, null = keiner (fehlt: stil.json)
  "erlaubt": ["text"],                   # was der Nutzer für dieses Reel ausdrücklich will (zusätzlich zu stil.json)
  "fx": [
    {"fx": "punch", "beat": 4},                          # Standardstärke
    {"fx": "mini_punch", "at_beats": [2, 6, 10]},        # mehrere Zeitpunkte
    {"fx": "zoom_in", "beat": 16, "beats": 1},           # Übergang auf dem Schnitt bei Beat 16
    {"fx": "grain"},                                     # ohne Zeit = ganzes Reel
    {"fx": "title", "text": "DEIN TITEL", "beat": 0, "beats": 4}
  ]
}
Alle Effekte arbeiten auf float32-BGR-Bildern (0..1) und lassen sich auch einzeln importieren:
    import reelvfx as rv;  img = rv.FX["grain"]["fn"](img, u, params, ctx)
"""
import functools
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import looks  # noqa: E402
from stil import STIL  # noqa: E402

MARKE = STIL["marke"] or "@deinaccount"

W, H, FPS = 1080, 1920, 30
CACHE = Path(os.environ.get("REELVFX_CACHE", "/tmp/reelvfx_cache"))
FONT_DIR = Path("/usr/share/fonts/truetype/montserrat")
cv2.setNumThreads(1)

# ---------------------------------------------------------------- Hilfsfunktionen


def _c(x):
    return min(max(float(x), 0.0), 1.0)


def smooth(x):
    x = _c(x); return x * x * (3 - 2 * x)


def ease_out(x):
    return 1 - (1 - _c(x)) ** 3


def ease_in(x):
    return _c(x) ** 3


def ease_io(x):
    x = _c(x); return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def back_out(x, s=1.7):
    x = _c(x) - 1; return 1 + (s + 1) * x ** 3 + s * x ** 2


CURVES = {"linear": _c, "smooth": smooth, "ease_out": ease_out, "ease_in": ease_in, "ease_io": ease_io}


def env(u, tau):
    return math.exp(-u / tau) if u >= 0 else 0.0


def lum(img):
    return 0.0722 * img[..., 0] + 0.7152 * img[..., 1] + 0.2126 * img[..., 2]


def fast_blur(img, sigma):
    """Gauss-Unschärfe; große Radien über verkleinertes Bild (schnell, für Übergänge/Glow)."""
    if sigma < 0.3:
        return img
    if sigma < 4:
        return cv2.GaussianBlur(img, (0, 0), sigma)
    f = int(sigma / 3) + 1
    h, w = img.shape[:2]
    s = cv2.resize(img, (max(1, w // f), max(1, h // f)), interpolation=cv2.INTER_AREA)
    s = cv2.GaussianBlur(s, (0, 0), sigma / f)
    return cv2.resize(s, (w, h), interpolation=cv2.INTER_LINEAR)


def warp(img, z=1.0, fx=0.5, fy=0.5, dx=0.0, dy=0.0, rot=0.0, ow=W, oh=H, interp=cv2.INTER_LANCZOS4):
    """Quelle so skalieren, dass sie ow x oh füllt (cover), mal Zoom z; Fokuspunkt (fx, fy) in die
    Mitte, ohne dass Rand sichtbar wird (bei z >= 1). Lanczos (scharfe Zooms)."""
    hs, ws = img.shape[:2]
    k = max(ow / ws, oh / hs) * z
    if k < 1:
        img = cv2.resize(img, (max(1, round(ws * k)), max(1, round(hs * k))), interpolation=cv2.INTER_AREA)
        hs, ws = img.shape[:2]; k2 = 1.0
    else:
        k2 = k
    hw, hh = ow / 2 / k2, oh / 2 / k2
    cx = np.clip(fx * ws, hw, ws - hw) if ws >= 2 * hw else ws / 2
    cy = np.clip(fy * hs, hh, hs - hh) if hs >= 2 * hh else hs / 2
    M = cv2.getRotationMatrix2D((float(cx), float(cy)), rot, k2)
    M[0, 2] += ow / 2 - cx + dx
    M[1, 2] += oh / 2 - cy + dy
    return cv2.warpAffine(img, M, (ow, oh), flags=interp, borderMode=cv2.BORDER_REFLECT)


def dir_blur(img, dx, dy):
    """Bewegungsunschärfe entlang (dx, dy) Pixel (Box, horizontal oder vertikal)."""
    L = int(math.hypot(dx, dy))
    if L < 2:
        return img
    k = L | 1
    return cv2.blur(img, (k, 1)) if abs(dx) >= abs(dy) else cv2.blur(img, (1, k))


def radial_blur(img, strength, n=8, fx=0.5, fy=0.5):
    """Zoom-Unschärfe um (fx, fy): Mittel aus n skalierten Kopien (halbe Auflösung, schnell)."""
    if strength < 0.004:
        return img
    h, w = img.shape[:2]
    s = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    cx, cy = fx * w / 2, fy * h / 2
    acc = np.zeros_like(s)
    for j in range(n):
        k = 1 + strength * j / (n - 1)
        M = np.float32([[k, 0, (1 - k) * cx], [0, k, (1 - k) * cy]])
        acc += cv2.warpAffine(s, M, (w // 2, h // 2), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return cv2.resize(acc / n, (w, h), interpolation=cv2.INTER_LINEAR)


def spin_blur(img, ang, spread, n=7):
    h, w = img.shape[:2]
    s = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    acc = np.zeros_like(s)
    for j in range(n):
        a = ang + spread * (j / (n - 1) - 0.5)
        M = cv2.getRotationMatrix2D((w / 4, h / 4), a, 1.0 + abs(ang) / 90)
        acc += cv2.warpAffine(s, M, (w // 2, h // 2), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return cv2.resize(acc / n, (w, h), interpolation=cv2.INTER_LINEAR)


def flow_interp(a, b, x):
    """Zwischenbild bei Anteil x (0..1) zwischen a und b per optischem Fluss (Farnebäck, 1/4 Auflösung)."""
    h, w = a.shape[:2]
    sw, sh = w // 4, h // 4
    ga = cv2.cvtColor(cv2.resize(a, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(cv2.resize(b, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    ga8, gb8 = (ga * 255).astype(np.uint8), (gb * 255).astype(np.uint8)
    fab = cv2.calcOpticalFlowFarneback(ga8, gb8, None, 0.5, 4, 19, 3, 5, 1.1, 0)
    fba = cv2.calcOpticalFlowFarneback(gb8, ga8, None, 0.5, 4, 19, 3, 5, 1.1, 0)
    fab = cv2.resize(fab, (w, h)) * 4
    fba = cv2.resize(fba, (w, h)) * 4
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    wa = cv2.remap(a, gx - x * fab[..., 0], gy - x * fab[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    wb = cv2.remap(b, gx - (1 - x) * fba[..., 0], gy - (1 - x) * fba[..., 1], cv2.INTER_LINEAR,
                   borderMode=cv2.BORDER_REFLECT)
    return (1 - x) * wa + x * wb


def screen(img, layer):
    return 1 - (1 - img) * (1 - np.clip(layer, 0, 1))


@functools.lru_cache(maxsize=8)
def _radius_map(w, h):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return (np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / math.sqrt(2)).astype(np.float32)


def _rng(ctx, salt=0):
    return np.random.default_rng((ctx.i * 7919 + salt * 104729 + 17) & 0xFFFFFFFF)


# ---------------------------------------------------------------- Registry

FX = {}
GROUPS = ["Übergang", "Motion", "Zeit", "Look", "Text", "Split"]


def effect(name, group, kind, desc, order=50, dur=None, **defaults):
    """kind: geo (Kamera), pix (Bild), trans (Übergang A->B), time (Zeit-Umbau), text, layout (Split)."""
    def deco(fn):
        FX[name] = dict(name=name, fn=fn, group=group, kind=kind, desc=desc, order=order, dur=dur,
                        defaults=defaults)
        return fn
    return deco


# ---------------------------------------------------------------- Motion (Kamera)
# geo-Funktionen liefern Beiträge: z (Zoomfaktor), dx/dy (px), rot (Grad), zb (Zoom-Blur), mb (Bewegungsunschärfe)

@effect("punch", "Motion", "geo", "Zoom-Punch auf 808: 1 + amp·e^(−t/τ), Zoom-Blur auf den ersten 3 Frames (Rezept)",
        dur=0.6, amp=0.14, tau=0.09, blur=3)
def _punch(u, p, c):
    if u < 0:
        return None
    out = {"z": 1 + p["amp"] * env(u, p["tau"])}
    if p["blur"] and u < (p["blur"] - 0.5) / c.fps:
        out["zb"] = (0.022, 3)
    return out


@effect("punch2", "Motion", "geo", "Zweiter Punch auf dem 808-Nachschlag (0,12 mit Blur)", dur=0.6, amp=0.12, tau=0.09, blur=3)
def _punch2(u, p, c):
    return _punch(u, p, c)


@effect("mini_punch", "Motion", "geo", "Mini-Punch auf den Clap: 1 + 0,06·e^(−t/0,09 s), ohne Blur, aus der Mitte",
        dur=0.5, amp=0.06, tau=0.09, blur=0)
def _mini(u, p, c):
    return _punch(u, p, c)


@effect("punch_rot", "Motion", "geo", "Punch mit leichter Drehung (1,2°), wirkt lebendiger als der gerade Punch",
        dur=0.6, amp=0.10, tau=0.09, rot=1.2, blur=2)
def _punch_rot(u, p, c):
    o = _punch(u, p, c)
    if o:
        o["rot"] = p["rot"] * env(u, p["tau"] * 1.3)
    return o


@effect("pulse", "Motion", "geo", "Weicher Zoom-Puls: steigt in 60 ms an und fällt wieder, kein Sprung (Groove statt Hit)",
        dur=0.5, amp=0.035, attack=0.06)
def _pulse(u, p, c):
    if u < 0:
        return None
    a = p["attack"]; return {"z": 1 + p["amp"] * (u / a) * math.exp(1 - u / a)}


@effect("zoom_step", "Motion", "geo", "Zoom-Stufe: springt in 2 Frames auf +12 % und bleibt bis zum Ende des Fensters",
        dur=0.857, amp=0.12, frames=2)
def _zoom_step(u, p, c):
    if u < 0:
        return None
    return {"z": 1 + p["amp"] * smooth((u + 1 / c.fps) / (p["frames"] / c.fps))}


@effect("push", "Motion", "geo", "Push-in über das Fenster (typisch +6 bis +12 %), Kurve linear/smooth/ease_out",
        dur=1.714, z0=1.0, z1=1.06, curve="linear")
def _push(u, p, c):
    x = CURVES[p["curve"]](u / max(c.dur, 1e-6))
    return {"z": p["z0"] + (p["z1"] - p["z0"]) * x}


@effect("pull", "Motion", "geo", "Pull-out: startet 8 % näher und zieht ruhig auf", dur=1.714, z0=1.08, z1=1.0, curve="ease_out")
def _pull(u, p, c):
    return _push(u, p, c)


@effect("drift", "Motion", "geo", "Ken-Burns-Schwenk (für Fotos/ruhige Shots): langsam verschieben bei leichtem Zoom",
        dur=1.714, dx0=-30, dx1=30, dy0=0, dy1=0, z=1.08, curve="smooth")
def _drift(u, p, c):
    x = CURVES[p["curve"]](u / max(c.dur, 1e-6))
    return {"z": p["z"], "dx": p["dx0"] + (p["dx1"] - p["dx0"]) * x, "dy": p["dy0"] + (p["dy1"] - p["dy0"]) * x}


@effect("shake", "Motion", "geo", "Shake auf Schlägen/Treffern: ~18 px, 0,6°, τ 0,14 s, Zoom +5 % mit gleichem Abklingen",
        dur=0.6, px=18, deg=0.6, tau=0.14, zoom=0.05)
def _shake(u, p, c):
    if u < 0:
        return None
    e = env(u, p["tau"])
    return {"z": 1 + max(p["zoom"] * e, 2.2 * p["px"] * e / W), "dx": p["px"] * e * math.sin(2 * math.pi * 9 * u + 0.3),
            "dy": p["px"] * 0.7 * e * math.sin(2 * math.pi * 11 * u + 1.3),
            "rot": p["deg"] * e * math.sin(2 * math.pi * 7 * u + 0.5)}


@effect("handheld", "Motion", "geo", "Sehr leichte Handkamera-Bewegung (5 px, 0,2°), macht Stative lebendig",
        dur=1.714, px=5.0, deg=0.2, speed=0.6, seed=3)
def _handheld(u, p, c):
    r = np.random.default_rng(int(p["seed"])).random(9) * 2 * math.pi
    f = p["speed"]
    n = lambda k: (math.sin(2 * math.pi * f * 1.0 * u + r[k]) * 0.6 + math.sin(2 * math.pi * f * 2.3 * u + r[k + 3]) * 0.3
                   + math.sin(2 * math.pi * f * 4.1 * u + r[k + 6]) * 0.1)
    fade = smooth(u / 0.3) * smooth((c.dur - u) / 0.3) if c.dur < 1e5 else 1.0
    return {"z": 1 + 2.3 * p["px"] / W, "dx": p["px"] * n(0) * fade, "dy": p["px"] * n(1) * fade, "rot": p["deg"] * n(2) * fade}


@effect("rotate", "Motion", "geo", "Langsames Kippen (Dutch Angle) von deg0 nach deg1 mit Zoom-Ausgleich",
        dur=1.714, deg0=0.0, deg1=2.0, curve="smooth")
def _rotate(u, p, c):
    a = p["deg0"] + (p["deg1"] - p["deg0"]) * CURVES[p["curve"]](u / max(c.dur, 1e-6))
    return {"rot": a, "z": 1 + abs(math.sin(math.radians(a))) * 1.9}


@effect("whip_zoom", "Motion", "geo", "Beschleunigter Zoom zum Shot-Ende mit Zoom-Blur (bisheriges 'whip' aus render.py)",
        dur=0.857, amp=0.75)
def _whip_zoom(u, p, c):
    x = _c(u / max(c.dur, 1e-6))
    o = {"z": 1 + p["amp"] * x ** 3}
    if x > 0.3:
        o["zb"] = (0.03 * x * x, 5)
    return o


# ---------------------------------------------------------------- Übergänge (A -> B, x = 0..1 über das Fenster)

def _split_pan(a, b, e, direction):
    """A und B nebeneinander, Fenster um e (0..1) verschoben."""
    if direction in ("left", "right"):
        strip = np.concatenate([a, b], axis=1) if direction == "left" else np.concatenate([b, a], axis=1)
        off = int(round(e * W)) if direction == "left" else int(round((1 - e) * W))
        return strip[:, off:off + W]
    strip = np.concatenate([a, b], axis=0) if direction == "up" else np.concatenate([b, a], axis=0)
    off = int(round(e * H)) if direction == "up" else int(round((1 - e) * H))
    return strip[off:off + H]


@effect("cut", "Übergang", "trans", "Harter Schnitt (Standard, zum Vergleich)", dur=1 / 30)
def _t_cut(a, b, x, p, c):
    return a if x < 0.5 else b


@effect("crossfade", "Übergang", "trans", "Weiche Überblendung (Cinematic/R&B, 1–2 Beats)", dur=0.857)
def _t_cross(a, b, x, p, c):
    m = smooth(x); return a * (1 - m) + b * m


@effect("dip_black", "Übergang", "trans", "Kurz über Schwarz (Kapitelwechsel, ruhig)", dur=0.857)
def _t_dipb(a, b, x, p, c):
    return a * (1 - smooth(x * 2)) if x < 0.5 else b * smooth(x * 2 - 1)


@effect("dip_white", "Übergang", "trans", "Kurz über Weiß (weicher als Flash)", dur=0.571)
def _t_dipw(a, b, x, p, c):
    if x < 0.5:
        m = smooth(x * 2); return a + (1 - a) * m
    m = 1 - smooth(x * 2 - 1); return b + (1 - b) * m


@effect("zoom_in", "Übergang", "trans", "Zoom-Durchflug: A zoomt mit Blur rein, B kommt aus dem Zoom (dezent: 35 %)",
        dur=0.428, zoom=0.35, blur=0.10)
def _t_zoomin(a, b, x, p, c):
    if x < 0.5:
        s = ease_in(x / 0.5); img = warp(a, 1 + p["zoom"] * s, interp=cv2.INTER_LINEAR)
    else:
        s = 1 - ease_out((x - 0.5) / 0.5); img = warp(b, 1 + p["zoom"] * s, interp=cv2.INTER_LINEAR)
    return radial_blur(img, p["blur"] * s)


@effect("zoom_out", "Übergang", "trans", "Zoom-Out mit gespiegelten Rändern, B kommt von klein", dur=0.428, zoom=0.25, blur=0.08)
def _t_zoomout(a, b, x, p, c):
    if x < 0.5:
        s = ease_in(x / 0.5); img = warp(a, 1 - p["zoom"] * s, interp=cv2.INTER_LINEAR)
    else:
        s = 1 - ease_out((x - 0.5) / 0.5); img = warp(b, 1 - p["zoom"] * s, interp=cv2.INTER_LINEAR)
    return radial_blur(img, p["blur"] * s)


@effect("whip", "Übergang", "trans", "Whip-Pan: Bild reißt seitlich weg, Bewegungsunschärfe proportional zum Tempo",
        dur=0.286, direction="left", blur=0.35)
def _t_whip(a, b, x, p, c):
    e = ease_io(x)
    v = 6 * x * (1 - x)  # ~ Tempo der Bewegung (max 1,5 bei x = 0,5)
    img = _split_pan(a, b, e, p["direction"])
    L = p["blur"] * v / 1.5 * (W if p["direction"] in ("left", "right") else H)
    return dir_blur(img, L if p["direction"] in ("left", "right") else 0, 0 if p["direction"] in ("left", "right") else L)


@effect("slide", "Übergang", "trans", "B schiebt A aus dem Bild (Push), wenig Unschärfe", dur=0.428, direction="up", blur=0.06)
def _t_slide(a, b, x, p, c):
    return _t_whip(a, b, x, p, c)


@effect("luma_wipe", "Übergang", "trans", "Helle Bildteile von A blenden zuerst zu B über (organisch, ruhig)", dur=0.857, soft=0.25)
def _t_luma(a, b, x, p, c):
    L = fast_blur(lum(a), 10)
    L = (L - L.min()) / max(float(L.max() - L.min()), 1e-3)
    thr = 1 - smooth(x) * (1 + p["soft"])
    m = np.clip((L - thr) / p["soft"], 0, 1)[..., None]
    return a * (1 - m) + b * m


@effect("wipe", "Übergang", "trans", "Weiche Wischblende in eine Richtung (Winkel in Grad, 90 = von oben)", dur=0.571, angle=90, soft=0.12)
def _t_wipe(a, b, x, p, c):
    ang = math.radians(p["angle"])
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    g = (xx / W - 0.5) * math.cos(ang) + (yy / H - 0.5) * math.sin(ang)
    g = (g - g.min()) / (g.max() - g.min())
    e = ease_io(x) * (1 + p["soft"])
    m = np.clip((e - g) / p["soft"], 0, 1)[..., None]
    return a * (1 - m) + b * m


@effect("iris", "Übergang", "trans", "Kreis öffnet sich aus der Mitte zu B", dur=0.571, soft=0.06, fx=0.5, fy=0.45)
def _t_iris(a, b, x, p, c):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt((xx - p["fx"] * W) ** 2 + (yy - p["fy"] * H) ** 2) / math.hypot(W, H)
    e = ease_in(x) * (1 + p["soft"])
    m = np.clip((e - r) / p["soft"], 0, 1)[..., None]
    return a * (1 - m) + b * m


@effect("blur_dip", "Übergang", "trans", "A wird unscharf, B wird scharf (weich, fast unsichtbar)", dur=0.571, sigma=36)
def _t_blur(a, b, x, p, c):
    m = smooth((x - 0.35) / 0.3)
    return fast_blur(a * (1 - m) + b * m, p["sigma"] * math.sin(math.pi * x))


def _leak_field(t, seed=1, w=54, h=96):
    """Warmes Lichtfeld (niedrige Auflösung), animiert über t."""
    r = np.random.default_rng(seed).random(12)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    acc = np.zeros((h, w, 3), np.float32)
    cols = [(0.20, 0.55, 1.0), (0.35, 0.35, 1.0), (0.55, 0.75, 1.0)]  # BGR: orange, rosa, gelblich
    for k in range(3):
        cx = w * (0.1 + 0.8 * (0.5 + 0.5 * math.sin(0.9 * t * (1 + r[k]) + 6 * r[k + 3])))
        cy = h * (0.1 + 0.8 * (0.5 + 0.5 * math.sin(0.7 * t * (1 + r[k + 6]) + 6 * r[k + 9])))
        s = w * (0.35 + 0.25 * r[k])
        g = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * s * s))
        acc += g[..., None] * np.array(cols[k], np.float32)
    return cv2.resize(acc / 1.4, (W, H), interpolation=cv2.INTER_CUBIC)


@effect("leak_cross", "Übergang", "trans", "Überblendung durch ein warmes Light-Leak (emotional)", dur=0.857, amount=0.7, seed=2)
def _t_leak(a, b, x, p, c):
    m = smooth((x - 0.3) / 0.4)
    return screen(a * (1 - m) + b * m, _leak_field(c.t, p["seed"]) * p["amount"] * math.sin(math.pi * x))


def _glitch(img, amount, rng):
    out = img.copy()
    n = int(3 + 6 * amount)
    for _ in range(n):
        y0 = int(rng.integers(0, H - 40)); hgt = int(rng.integers(12, 90))
        sh = int(rng.normal(0, 30 * amount))
        out[y0:y0 + hgt] = np.roll(out[y0:y0 + hgt], sh, axis=1)
    s = int(round(8 * amount))
    if s:
        out[..., 2] = np.roll(out[..., 2], s, axis=1); out[..., 0] = np.roll(out[..., 0], -s, axis=1)
    return out


@effect("glitch", "Übergang", "trans", "Glitch light: 2–3 Frames Zeilenversatz + RGB-Split um den Schnitt (nur auf Wunsch)",
        dur=0.2, amount=0.6)
def _t_glitch(a, b, x, p, c):
    base = a if x < 0.5 else b
    k = 1 - abs(x - 0.5) * 2
    return _glitch(base, p["amount"] * k, _rng(c, 5)) if k > 0.15 else base


@effect("flash_cut", "Übergang", "trans", "Schnitt mit Weißblitz (0,55·e^(−t/0,045 s)), zählt zum Flash-Budget", dur=0.3, amp=0.55, tau=0.045)
def _t_flash(a, b, x, p, c):
    if x < 0.5:
        return a
    f = p["amp"] * env((x - 0.5) * c.dur, p["tau"])
    return b + (1 - b) * min(f, 0.9)


@effect("spin", "Übergang", "trans", "Dreh-Übergang mit Rotationsunschärfe (20°), eher für Party/Afrobeats", dur=0.428, angle=20)
def _t_spin(a, b, x, p, c):
    if x < 0.5:
        s = ease_in(x / 0.5); return spin_blur(a, p["angle"] * s, p["angle"] * s * 0.5)
    s = 1 - ease_out((x - 0.5) / 0.5); return spin_blur(b, -p["angle"] * s, p["angle"] * s * 0.5)


@effect("doors", "Übergang", "trans", "A teilt sich in der Mitte und fährt nach oben/unten weg, dahinter B", dur=0.571)
def _t_doors(a, b, x, p, c):
    e = ease_io(x); off = int(round(e * H / 2)); out = b.copy(); hh = H // 2
    if off < hh:
        out[0:hh - off] = a[off:hh]; out[hh + off:H] = a[hh:H - off]
    return out


# ---------------------------------------------------------------- Look / Bild

@effect("flash", "Look", "pix", "Weißblitz 0,55·e^(−t/0,045 s), sparsam (Budget in stil.json), z. B. Kapitelstart, Finale", order=70, dur=0.3,
        amp=0.55, tau=0.045)
def _flash(img, u, p, c):
    a = p["amp"] * env(u, p["tau"])
    return img + (1 - img) * min(a, 0.9) if a > 0.003 else img


@effect("fade", "Look", "pix", "Ein-/Ausblenden über Schwarz (mode in/out)", order=80, dur=0.857, mode="out")
def _fade(img, u, p, c):
    x = smooth(u / max(c.dur, 1e-6))
    return img * (x if p["mode"] == "in" else 1 - x)


@effect("vignette", "Look", "pix", "Vignette 18 % ab 35 % des Radius", order=110, amount=0.18, start=0.35)
def _vig(img, u, p, c):
    rr = _radius_map(img.shape[1], img.shape[0])
    return img * (1 - p["amount"] * np.clip((rr - p["start"]) / (1 - p["start"]), 0, 1) ** 2)[..., None]


@effect("grain", "Look", "pix", "Film-Korn, fein und in den Mitten am stärksten (3,5 %)", order=100, amount=0.035, size=1.6)
def _grain(img, u, p, c):
    rng = _rng(c, 1); s = max(1.0, p["size"])
    n = rng.standard_normal((int(H / s), int(W / s))).astype(np.float32)
    n = cv2.resize(n, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
    Y = lum(img)
    return img + (p["amount"] * n * (0.35 + 2.6 * Y * (1 - Y)))[..., None]


@effect("chroma", "Look", "pix", "Chromatische Aberration am Bildrand (2,5 px), wie ein echtes Objektiv", order=40, px=2.5)
def _chroma(img, u, p, c):
    h, w = img.shape[:2]; s = p["px"] / (0.5 * math.hypot(w, h))
    out = img.copy()
    for ch, k in ((2, 1 + s), (0, 1 - s)):
        M = np.float32([[k, 0, (1 - k) * w / 2], [0, k, (1 - k) * h / 2]])
        out[..., ch] = cv2.warpAffine(img[..., ch], M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out


@effect("rgb_split", "Look", "pix", "RGB-Versatz auf dem Beat, klingt in ~0,1 s ab (Glitch-Akzent, nur auf Wunsch)", order=44,
        dur=0.4, px=10, tau=0.07)
def _rgbsplit(img, u, p, c):
    s = int(round(p["px"] * env(u, p["tau"])))
    if s < 1:
        return img
    out = img.copy(); out[..., 2] = np.roll(img[..., 2], s, axis=1); out[..., 0] = np.roll(img[..., 0], -s, axis=1)
    return out


@effect("glitch_light", "Look", "pix", "Kurzer Glitch im Shot (Zeilenversatz + RGB), 3 Frames (nur auf Wunsch)", order=45,
        dur=0.1, amount=0.5)
def _glitchl(img, u, p, c):
    return _glitch(img, p["amount"] * (1 - _c(u / max(c.dur, 1e-6)) * 0.5), _rng(c, 6))


@effect("bloom", "Look", "pix", "Weiches Leuchten der Lichter (Sonne, Himmel), dezent", order=50, amount=0.22, thr=0.72, radius=30)
def _bloom(img, u, p, c):
    Y = lum(img)
    hl = img * np.clip((Y - p["thr"]) / (1 - p["thr"]), 0, 1)[..., None]
    return screen(img, fast_blur(hl, p["radius"]) * p["amount"] * 2)


@effect("halation", "Look", "pix", "Film-Halation: rötlicher Schein um helle Kanten", order=55, amount=0.20, thr=0.75, radius=14)
def _halation(img, u, p, c):
    Y = lum(img)
    hl = np.clip((Y - p["thr"]) / (1 - p["thr"]), 0, 1)
    g = fast_blur(hl, p["radius"])[..., None] * np.array([0.15, 0.35, 1.0], np.float32)
    return screen(img, g * p["amount"] * 2)


@effect("light_leak", "Look", "pix", "Wandernder warmer Lichteinfall (Screen), im Fenster weich ein- und ausgeblendet",
        order=60, dur=1.714, amount=0.28, seed=1)
def _leak(img, u, p, c):
    k = math.sin(math.pi * _c(u / max(c.dur, 1e-6))) if c.dur < 1e5 else 1.0
    return screen(img, _leak_field(c.t, p["seed"]) * p["amount"] * k) if k > 0.01 else img


@effect("glow_pulse", "Look", "pix", "Kurzes Aufhellen auf dem Beat (+6 %), weicher Akzent ohne Zoom", order=30, dur=0.4,
        amp=0.06, tau=0.1)
def _glowp(img, u, p, c):
    a = p["amp"] * env(u, p["tau"]); return img * (1 + a) + a * 0.3


@effect("exposure", "Look", "pix", "Belichtung angleichen (gain) im Fenster", order=10, gain=1.0)
def _expo(img, u, p, c):
    return img * p["gain"]


@effect("bw", "Look", "pix", "Schwarzweiß (weich eingeblendet), z. B. unter einem Freeze", order=20, amount=1.0, fade=0.1)
def _bw(img, u, p, c):
    a = p["amount"] * smooth(u / max(p["fade"], 1e-3))
    Y = lum(img)[..., None]; return img * (1 - a) + Y * a


@effect("letterbox", "Look", "pix", "Kino-Balken fahren rein (9 % oben/unten), z. B. fürs Intro", order=90, dur=1.714,
        size=0.09, ramp=0.3)
def _lbox(img, u, p, c):
    k = smooth(u / p["ramp"]) * smooth((c.dur - u) / p["ramp"]) if c.dur < 1e5 else smooth(u / p["ramp"])
    b = int(round(H * p["size"] * k))
    if b > 0:
        img = img.copy(); img[:b] = 0; img[H - b:] = 0
    return img


@effect("sharpen", "Look", "pix", "Leichtes Nachschärfen gegen Instagram-Kompression", order=120, amount=0.35, sigma=1.2)
def _sharp(img, u, p, c):
    return img + p["amount"] * (img - cv2.GaussianBlur(img, (0, 0), p["sigma"]))


@effect("focus_pull", "Look", "pix", "Schärfe ziehen: startet unscharf und wird scharf (Intro/Kapitelstart)", order=35,
        dur=0.857, sigma=14, curve="ease_out")
def _fpull(img, u, p, c):
    s = p["sigma"] * (1 - CURVES[p["curve"]](u / max(c.dur, 1e-6)))
    return fast_blur(img, s) if s > 0.3 else img


# ---------------------------------------------------------------- Zeit (Umbau der Zeitachse im Shot)
# time-Funktionen bilden Reel-Zeit t auf Quell-Zeit ab (Liste aus (t', Gewicht)); sie bleiben im Shot.

@effect("freeze", "Zeit", "time", "Freeze-Frame mit Blitz 0,35 und Push +5 % (Shutter-SFX dazu), nur auf Wunsch", dur=0.857,
        flash=0.35, push=0.05, bw=False)
def _freeze(t, t0, p, c):
    return [(t0, 1.0)]


@effect("stutter", "Zeit", "time", "Stotter-Wiederholung: kurzes Stück (¼ Beat) mehrfach (808-Roll, nur auf Wunsch)",
        dur=0.857, slice_beats=0.25)
def _stutter(t, t0, p, c):
    L = max(p["slice_beats"] * c.per, 1 / c.fps); return [(t0 + ((t - t0) % L), 1.0)]


@effect("rewind", "Zeit", "time", "Rückspulen: spielt das Vorherige rückwärts (2×), passt zu rewind.wav", dur=0.857, speed=2.0)
def _rewind(t, t0, p, c):
    return [(t0 - (t - t0) * p["speed"], 1.0)]


def _velocity_map(shape, n=400):
    x = np.linspace(0, 1, n + 1)
    if shape == "hit":        # schnell rein, Zeitlupe um die Mitte, schnell raus
        v = 1.8 - 1.4 * np.exp(-((x - 0.5) / 0.16) ** 2)
    elif shape == "slow_end":  # schnell starten, weich in Zeitlupe enden
        v = 1.8 - 1.4 * smooth_arr((x - 0.35) / 0.4)
    elif shape == "slow_start":
        v = 0.4 + 1.4 * smooth_arr((x - 0.25) / 0.4)
    else:                      # "fast_mid"
        v = 0.6 + 1.2 * np.exp(-((x - 0.5) / 0.2) ** 2)
    cum = np.concatenate([[0], np.cumsum((v[1:] + v[:-1]) / 2 * np.diff(x))])
    return x, cum / cum[-1], v / cum[-1]


def smooth_arr(x):
    x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)


@effect("velocity", "Zeit", "time", "Velocity-Edit im Shot: schnell–langsam–schnell, Shot-Länge bleibt (Zwischenbilder per Fluss)",
        dur=1.714, shape="hit", interp="flow")
def _velocity(t, t0, p, c):
    x, g, _ = _velocity_map(p["shape"])
    return [(t0 + c.dur * float(np.interp((t - t0) / max(c.dur, 1e-6), x, g)), 1.0)]


@effect("echo", "Zeit", "time", "Echo-Nachzieher: 3 frühere Bilder durchscheinend (bisheriges 'echo', nur auf Wunsch)", dur=0.857,
        gap=0.05)
def _echo(t, t0, p, c):
    w0 = smooth((t - t0) / 0.1)
    return [(t, 1.0)] + [(t - p["gap"] * k, w0 * w) for k, w in ((1, .6), (2, .4), (3, .25))]


# ---------------------------------------------------------------- Text / Branding (Montserrat, Safe Zones)

SAFE = dict(top=0.10, bottom=0.20, right=0.10, left=0.06)


@functools.lru_cache(maxsize=512)
def text_layer(text, size, weight="ExtraBold", track=0, color=(255, 255, 255), shadow=0.35):
    """Text als (BGR float, Alpha float) mit weichem Schatten. track = Buchstabenabstand in px.
    weight = Montserrat-Schnitt ("ExtraBold") oder Dateiname aus tools/fonts/ ("BebasNeue-Bold", "LeagueSpartan-Black")."""
    from PIL import Image, ImageDraw, ImageFont
    fp = FONT_DIR / f"Montserrat-{weight}.ttf"
    for cand in (HERE.parent / "fonts" / f"{weight}.otf", HERE.parent / "fonts" / f"{weight}.ttf"):
        if cand.exists():
            fp = cand
    font = ImageFont.truetype(str(fp), int(size))
    asc, desc = font.getmetrics()
    widths = [font.getlength(ch) for ch in text]
    tw = int(sum(widths) + track * max(len(text) - 1, 0)) + 4
    pad = int(size * 0.35)
    im = Image.new("L", (tw + 2 * pad, asc + desc + 2 * pad), 0)
    d = ImageDraw.Draw(im)
    x = pad
    for ch, w in zip(text, widths):
        d.text((x, pad), ch, font=font, fill=255); x += w + track
    a = np.asarray(im, np.float32) / 255
    rgb = np.empty(a.shape + (3,), np.float32); rgb[:] = np.array(color[::-1], np.float32) / 255
    if shadow:
        sh = cv2.GaussianBlur(a, (0, 0), size * 0.06)
        sh = np.roll(sh, int(size * 0.04), axis=0) * shadow
        alpha = a + sh * (1 - a)
        rgb = rgb * (a / np.maximum(alpha, 1e-4))[..., None]
        return rgb, alpha
    return rgb, a


def blit(img, layer, cx, cy, scale=1.0, alpha=1.0, blur=0.0):
    rgb, a = layer
    if scale != 1.0:
        sz = (max(1, int(rgb.shape[1] * scale)), max(1, int(rgb.shape[0] * scale)))
        rgb = cv2.resize(rgb, sz, interpolation=cv2.INTER_LINEAR); a = cv2.resize(a, sz, interpolation=cv2.INTER_LINEAR)
    if blur > 0.3:
        rgb = cv2.GaussianBlur(rgb, (0, 0), blur); a = cv2.GaussianBlur(a, (0, 0), blur)
    h, w = a.shape
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + w, img.shape[1]), min(y0 + h, img.shape[0])
    if X1 <= X0 or Y1 <= Y0:
        return img
    aa = (a[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0] * alpha)[..., None]
    img[Y0:Y1, X0:X1] = img[Y0:Y1, X0:X1] * (1 - aa) + rgb[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0] * aa
    return img


def _fit_size(text, size, weight, track, maxw=W * (1 - SAFE["left"] - SAFE["right"])):
    rgb, a = text_layer(text, size, weight, track, shadow=0)
    w = a.shape[1] - 0.7 * size
    return int(size * min(1.0, maxw / max(w, 1)))


def _safe_y(y, hpx):
    return float(np.clip(y * H, SAFE["top"] * H + hpx / 2, (1 - SAFE["bottom"]) * H - hpx / 2))


@effect("title", "Text", "text", "Titel mit Animation (slide_up, fade, pop, track, blur), automatisch in der Safe Zone",
        order=200, dur=1.714, text="DEIN TITEL", size=110, y=0.42, weight="ExtraBold", anim="slide_up",
        t_in=0.35, t_out=0.25, track=4, color=[255, 255, 255])
def _title(img, u, p, c):
    size = _fit_size(p["text"], p["size"], p["weight"], p["track"])
    xi = ease_out(u / p["t_in"]); xo = smooth((c.dur - u) / p["t_out"]) if c.dur < 1e5 else 1.0
    alpha = min(smooth(u / (p["t_in"] * 0.7)), xo)
    track = p["track"] + (int(round((1 - xi) * 30)) if p["anim"] == "track" else 0)
    lay = text_layer(p["text"], size, p["weight"], track, tuple(p["color"]))
    cy = _safe_y(p["y"], lay[1].shape[0] * 0.6) + ((1 - xi) * 70 if p["anim"] == "slide_up" else 0)
    scale = back_out(u / p["t_in"]) * 0.2 + 0.8 if p["anim"] == "pop" else 1.0
    blur = (1 - xi) * 14 if p["anim"] == "blur" else 0
    return blit(img, lay, W * (1 - SAFE["right"] + SAFE["left"]) / 2, cy, scale, alpha, blur)


@effect("kinetic", "Text", "text", "Kinetic Type: ein Wort pro Beat mit Pop (max. 5 Wörter), replace oder stack",
        order=200, dur=1.714, text="DEIN TEXT HIER", size=150, y=0.42, weight="Black", step_beats=1.0, mode="replace",
        color=[255, 255, 255])
def _kinetic(img, u, p, c):
    words = p["text"].split()[:5]
    k = int(u // (p["step_beats"] * c.per))
    if k < 0:
        return img
    k = min(k, len(words) - 1)
    show = [k] if p["mode"] == "replace" else list(range(k + 1))
    n = len(show); lh = p["size"] * 1.05
    for j, wi in enumerate(show):
        uw = u - wi * p["step_beats"] * c.per
        size = _fit_size(words[wi], p["size"], p["weight"], 2)
        lay = text_layer(words[wi], size, p["weight"], 2, tuple(p["color"]))
        cy = _safe_y(p["y"], lh * n) - lh * (n - 1) / 2 + j * lh
        img = blit(img, lay, W * (1 - SAFE["right"] + SAFE["left"]) / 2, cy, 0.8 + 0.2 * back_out(uw / 0.14),
                   min(1.0, uw / 0.05))
    return img


@effect("typewriter", "Text", "text", "Schreibmaschinen-Text, Buchstabe für Buchstabe (typing.wav dazu)", order=200, dur=1.714,
        text="TAG EINS", size=90, y=0.42, weight="SemiBold", cps=14, cursor=True)
def _typew(img, u, p, c):
    n = int(max(0.0, u) * p["cps"]) + 1
    s = p["text"][:n]
    size = _fit_size(p["text"], p["size"], p["weight"], 3)
    full = text_layer(p["text"], size, p["weight"], 3)
    lay = text_layer(s + ("|" if p["cursor"] and (n < len(p["text"]) or int(u * 3) % 2 == 0) else " "), size, p["weight"], 3)
    x0 = W * (1 - SAFE["right"] + SAFE["left"]) / 2 - full[1].shape[1] / 2 + lay[1].shape[1] / 2
    return blit(img, lay, x0, _safe_y(p["y"], full[1].shape[0] * 0.6), 1.0, 1.0)


@effect("lower_third", "Text", "text", "Bauchbinde: Balken fährt rein, Name + Zeile darunter (über der unteren Safe Zone)",
        order=200, dur=2.571, title="NAME", sub=MARKE, y=0.72, size=64)
def _lower(img, u, p, c):
    xi = ease_out(u / 0.35); xo = smooth((c.dur - u) / 0.25) if c.dur < 1e5 else 1.0
    x0 = int(W * SAFE["left"]) + 8; yb = int(_safe_y(p["y"], p["size"] * 2.4))
    bw = int((W * 0.55) * xi)
    img = img.copy()
    if bw > 0:
        a = 0.9 * xo; y0b, y1b = yb - int(p["size"] * 0.9), yb + int(p["size"] * 1.25)
        img[y0b:y1b, x0:x0 + 8] = img[y0b:y1b, x0:x0 + 8] * (1 - a) + a
    t1 = text_layer(p["title"], p["size"], "ExtraBold", 3); t2 = text_layer(p["sub"], int(p["size"] * 0.55), "Medium", 2)
    sl = (1 - xi) * -40
    img = blit(img, t1, x0 + 34 + t1[1].shape[1] / 2 + sl, yb - p["size"] * 0.25, 1.0, min(xi, xo))
    img = blit(img, t2, x0 + 34 + t2[1].shape[1] / 2 + sl * 1.5, yb + p["size"] * 0.62, 1.0, min(smooth((u - 0.12) / 0.3), xo))
    return img


@effect("wordmark", "Text", "text", "Kleines Wortzeichen (Marke aus stil.json) oben links in der Safe Zone (Branding)",
        order=210, text=MARKE.upper(), size=34, opacity=0.85, track=6)
def _wordmark(img, u, p, c):
    lay = text_layer(p["text"], p["size"], "Bold", p["track"], shadow=0.5)
    a = p["opacity"] * smooth(u / 0.3)
    return blit(img, lay, W * SAFE["left"] + lay[1].shape[1] / 2, H * SAFE["top"] + lay[1].shape[0] / 2, 1.0, a)


@effect("counter", "Text", "text", "Zahl zählt hoch (z. B. 0 → 10 KM), ease_out über das Fenster", order=200, dur=1.714,
        start=0, end=10, suffix=" KM", decimals=0, size=160, y=0.42)
def _counter(img, u, p, c):
    v = p["start"] + (p["end"] - p["start"]) * ease_out(u / max(c.dur * 0.8, 1e-6))
    s = f"{v:.{int(p['decimals'])}f}{p['suffix']}"
    size = _fit_size(f"{p['end']:.{int(p['decimals'])}f}{p['suffix']}", p["size"], "Black", 2)
    lay = text_layer(s, size, "Black", 2)
    return blit(img, lay, W * (1 - SAFE["right"] + SAFE["left"]) / 2, _safe_y(p["y"], lay[1].shape[0] * 0.6), 1.0,
                smooth(u / 0.12))


@effect("safezones", "Text", "text", "Prüf-Overlay: Instagram-Safe-Zones rot (nie im fertigen Reel lassen)", order=250)
def _safez(img, u, p, c):
    img = img.copy(); red = np.array([0.1, 0.1, 0.9], np.float32)
    for sl in (np.s_[:int(H * SAFE["top"])], np.s_[int(H * (1 - SAFE["bottom"])):], np.s_[:, int(W * (1 - SAFE["right"])):]):
        img[sl] = img[sl] * 0.55 + red * 0.45
    return img


# ---------------------------------------------------------------- Split / Layout

def _cell(c, src, u, w, h, z=1.0, fy=0.5):
    im = c.source_frame(src, u)
    return warp(im, z, 0.5, fy, ow=w, oh=h)


@effect("split", "Split", "layout", "2er/3er-Split übereinander, Streifen fahren gestaffelt rein; mind. 4 Beats stehen lassen",
        dur=2.571, sources=[], gap=8, stagger_beats=0.5, expand_beats=None)
def _split(u, p, c):
    srcs = p["sources"]; n = max(1, len(srcs)); g = p["gap"]
    hs = (H - g * (n - 1)) // n
    out = np.zeros((H, W, 3), np.float32)
    ex = p["expand_beats"]; xe = smooth((u / c.per - ex) / 1.0) if ex is not None else 0.0
    for k, s in enumerate(srcs):
        ua = k * p["stagger_beats"] * c.per
        if u < ua - 0.5 / c.fps:
            continue
        slide = (1 - ease_out((u - ua) / 0.16)) * (1 if k % 2 == 0 else -1) * W
        z = 1 + 0.07 * env(u - ua, 0.09)
        y0 = k * (hs + g)
        if xe > 0 and k == n // 2:                   # mittlerer Streifen öffnet sich ins Vollbild
            y1 = int((y0 + hs) * (1 - xe) + H * xe); y0 = int(y0 * (1 - xe))
            out[y0:y1] = warp(c.source_frame(s, u), z, 0.5, 0.5, dx=slide, ow=W, oh=y1 - y0)
            continue
        if xe > 0.999:
            continue
        out[y0:y0 + hs] = warp(c.source_frame(s, u), z, 0.5, 0.5, dx=slide, ow=W, oh=hs)
    return out


@effect("grid", "Split", "layout", "2×2-Raster, jede Zelle ploppt auf einem Beat auf (4 Quellen)", dur=2.571, sources=[], gap=8,
        stagger_beats=1.0)
def _grid(u, p, c):
    g = p["gap"]; cw, ch = (W - g) // 2, (H - g) // 2
    out = np.zeros((H, W, 3), np.float32)
    for k, s in enumerate(p["sources"][:4]):
        ua = k * p["stagger_beats"] * c.per
        if u < ua - 0.5 / c.fps:
            continue
        sc = 0.85 + 0.15 * back_out((u - ua) / 0.18)
        cell = warp(c.source_frame(s, u), 1.0, ow=cw, oh=ch)
        if sc < 0.999:
            cell = _shrink(cell, sc)
        x0, y0 = (k % 2) * (cw + g), (k // 2) * (ch + g)
        out[y0:y0 + ch, x0:x0 + cw] = cell
    return out


def _shrink(cell, sc):
    h, w = cell.shape[:2]; small = cv2.resize(cell, (max(1, int(w * sc)), max(1, int(h * sc))), interpolation=cv2.INTER_AREA)
    out = np.zeros_like(cell); y0, x0 = (h - small.shape[0]) // 2, (w - small.shape[1]) // 2
    out[y0:y0 + small.shape[0], x0:x0 + small.shape[1]] = small
    return out


@effect("pip", "Split", "layout", "Bild-im-Bild mit runden Ecken und Schatten, fährt von unten rein", dur=2.571, sources=[],
        size=0.44, x=0.5, y=0.36, radius=28)
def _pip(u, p, c):
    base = c.base_frame()
    if not p["sources"]:
        return base
    iw = int(W * p["size"]); ih = int(iw * 16 / 9)
    inset = warp(c.source_frame(p["sources"][0], u), 1.0, ow=iw, oh=ih)
    e = ease_out(u / 0.35); xo = smooth((c.dur - u) / 0.25) if c.dur < 1e5 else 1.0
    cx = p["x"] * W; cy = p["y"] * H + (1 - e) * H * 0.7
    mask = np.zeros((ih, iw), np.float32)
    cv2.rectangle(mask, (p["radius"], 0), (iw - p["radius"], ih), 1, -1)
    cv2.rectangle(mask, (0, p["radius"]), (iw, ih - p["radius"]), 1, -1)
    for xx, yy in ((p["radius"], p["radius"]), (iw - p["radius"], p["radius"]), (p["radius"], ih - p["radius"]),
                   (iw - p["radius"], ih - p["radius"])):
        cv2.circle(mask, (xx, yy), p["radius"], 1, -1, lineType=cv2.LINE_AA)
    out = base.copy()
    shadow = np.zeros((H, W), np.float32)
    x0, y0 = int(cx - iw / 2), int(cy - ih / 2)
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + iw, W), min(y0 + ih, H)
    if X1 <= X0 or Y1 <= Y0:
        return out
    shadow[Y0:Y1, X0:X1] = mask[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    shadow = np.roll(fast_blur(shadow, 18), 14, axis=0) * 0.45 * xo
    out *= (1 - shadow[..., None])
    m = mask[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0, None] * xo
    out[Y0:Y1, X0:X1] = out[Y0:Y1, X0:X1] * (1 - m) + inset[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0] * m
    return out


# ---------------------------------------------------------------- Einzelaufruf (für eigene render.py-Pipelines)

class _MiniCtx:
    def __init__(self, i, dur, per, t):
        self.i, self.dur, self.per, self.fps, self.t = i, dur, per, FPS, t


def apply(name, img, u=0.0, i=0, dur=None, per=0.42858, b=None, **params):
    """Einen Effekt direkt anwenden, ohne spec. img = float32 BGR 0..1 (1080x1920).
    u = Sekunden seit Effektbeginn, i = Frame-Index (für Korn/Glitch-Zufall), b = zweites Bild bei Übergängen
    (dann ist u der Anteil 0..1). geo-Effekte liefern ein fertig gewarptes Bild.
        img = rv.apply("grain", img, i=frame)          img = rv.apply("punch", img, u=t - t_hit)
        img = rv.apply("zoom_in", a, u=x, b=b)
    """
    m = FX[name]; p = {**m["defaults"], **params}
    d = dur if dur is not None else (m["dur"] if m["dur"] is not None else 1e9)
    c = _MiniCtx(i, d, per, i / FPS)
    if m["kind"] == "trans":
        return m["fn"](img, b, float(u), p, c)
    if m["kind"] == "geo":
        o = m["fn"](u, p, c) or {}
        fo = p.get("focus", [0.5, 0.5])
        zb = o.get("zb")
        if zb:
            return sum(warp(img, o.get("z", 1.0) * (1 + zb[0] * j / (zb[1] - 1) * 2), fo[0], fo[1], o.get("dx", 0), o.get("dy", 0),
                            o.get("rot", 0)) for j in range(zb[1])) / zb[1]
        return warp(img, o.get("z", 1.0), fo[0], fo[1], o.get("dx", 0), o.get("dy", 0), o.get("rot", 0))
    if m["kind"] in ("pix", "text"):
        return m["fn"](img.copy(), u, p, c)
    raise ValueError(f"{name} ({m['kind']}) braucht die Engine (spec), nicht apply()")


# ---------------------------------------------------------------- Quellen

def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,duration:stream_side_data=rotation:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    j = json.loads(r.stdout); s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    dur = float(s.get("duration") or j["format"]["duration"])
    rot = 0
    for sd in s.get("side_data_list", []) or []:
        rot = int(sd.get("rotation", 0) or 0)
    w, h = int(s["width"]), int(s["height"])
    if abs(rot) in (90, 270):
        w, h = h, w
    return dict(w=w, h=h, fps=float(num) / float(den), dur=dur)


HLG = ("zscale=tin=arib-std-b67:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=100,format=gbrpf32le,"
       "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


class Video:
    """Ausschnitt einer Videodatei als uint8-Memmap (BGR), so skaliert, dass er 1080x1920 füllt."""

    def __init__(self, path, start=0.0, dur=None, hdr=False):
        self.path = Path(path); info = probe(self.path)
        self.fps = info["fps"]; self.start = max(0.0, float(start))
        self.dur = min(info["dur"] - self.start, dur if dur else 1e9)
        k = max(W / info["w"], H / info["h"])
        self.w, self.h = (info["w"], info["h"]) if k >= 1 else (int(round(info["w"] * k / 2) * 2), int(round(info["h"] * k / 2) * 2))
        st = self.path.stat()
        key = hashlib.sha1(f"{self.path.resolve()}|{st.st_size}|{st.st_mtime}|{self.start:.4f}|{self.dur:.4f}|{hdr}|{self.w}x{self.h}"
                           .encode()).hexdigest()[:16]
        CACHE.mkdir(parents=True, exist_ok=True)
        raw, meta = CACHE / f"{key}.bgr", CACHE / f"{key}.json"
        if not meta.exists():
            vf = (HLG + "," if hdr else "") + f"scale={self.w}:{self.h}:flags=lanczos"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{self.start:.4f}", "-t", f"{self.dur:.4f}", "-i", str(self.path),
                            "-vf", vf, "-pix_fmt", "bgr24", "-f", "rawvideo", str(raw)], check=True)
            n = raw.stat().st_size // (self.w * self.h * 3)
            meta.write_text(json.dumps({"n": int(n)}))
        self.n = json.loads(meta.read_text())["n"]
        self.mm = np.memmap(raw, np.uint8, "r", shape=(self.n, self.h, self.w, 3))

    def frame(self, j):
        return self.mm[int(np.clip(j, 0, self.n - 1))].astype(np.float32) / 255

    def at(self, ts, speed=1.0, interp="nearest"):
        """Bild zur Quellzeit ts (Sekunden in der Datei). Schnell (>1,3×): Frames im Shutter mitteln."""
        f = (ts - self.start) * self.fps
        span = abs(speed) * self.fps / FPS * 0.75
        if span > 1.3:
            j0, j1 = int(math.floor(f - span / 2)), int(math.ceil(f + span / 2))
            return sum(self.frame(j) for j in range(j0, j1 + 1)) / (j1 - j0 + 1)
        j = math.floor(f); fr = f - j
        if interp == "nearest" or fr < 0.12 or fr > 0.88 or j < 0 or j + 1 >= self.n:
            return self.frame(round(f))
        a, b = self.frame(j), self.frame(j + 1)
        return flow_interp(a, b, fr) if interp == "flow" else a * (1 - fr) + b * fr


# ---------------------------------------------------------------- Tempo-Kurven für Clips (in Beats)

def speed_fn(mode, b, n):
    if isinstance(mode, (int, float)):
        return float(mode)
    if isinstance(mode, list):                      # Keyframes [[beat, tempo], ...], smooth dazwischen
        ks = sorted(mode)
        if b <= ks[0][0]:
            return ks[0][1]
        for (b0, v0), (b1, v1) in zip(ks, ks[1:]):
            if b <= b1:
                return v0 + (v1 - v0) * smooth((b - b0) / max(b1 - b0, 1e-6))
        return ks[-1][1]
    b = min(max(b, 0.0), n)
    if mode in ("ramp", "ramp_hold"):               # Rezept (Projektanweisungen Abschnitt 4)
        if b < 2:
            return 1 + 1.2 * (b / 2) ** 2
        if b < 2.12:
            return 0.5 + 1.7 * 0.5 * (1 + math.cos(math.pi * (b - 2) / 0.12))
        if b < 3 or mode == "ramp_hold":
            return 0.5
        return 0.5 + 1.2 * (b - 3) ** 2
    if mode == "ramp_in":                           # beschleunigen, dann weich in 0,5× bleiben
        h = n / 2
        return 1 + 1.0 * (b / h) ** 2 if b < h else 0.5 + 1.5 * 0.5 * (1 + math.cos(math.pi * min((b - h) / 0.2, 1)))
    if mode == "ramp_out":                          # aus 0,5× heraus beschleunigen
        return 0.5 if b < n * 0.4 else 0.5 + 1.5 * ((b - n * 0.4) / (n * 0.6)) ** 2
    if mode == "slow_in":                           # in 1 Beat weich auf 0,5×
        return 1 - 0.5 * smooth(b)
    if mode == "bullet":                            # 0,25× (braucht 60 fps + Fluss-Zwischenbilder)
        return 1 - 0.75 * smooth(b / 0.25)
    if mode == "fast":
        return 2.0
    if mode == "slow":
        return 0.5
    return 1.0


class Clip:
    def __init__(self, d, t0, per, base, shared_video=None, pre=0.6, post=0.6):
        self.d = d; self.t0 = t0
        self.dur = float(d["dur"]) if "dur" in d else float(d["beats"]) * per
        self.t1 = t0 + self.dur; self.per = per
        self.src = float(d.get("src", 0.0)); self.mode = d.get("speed", 1.0)
        self.focus = d.get("focus", [0.5, 0.5]); self.push = d.get("push"); self.gain = d.get("gain", 1.0)
        self.interp = d.get("interp", "flow" if self.mode in ("bullet",) else "nearest")
        self.pre, self.post = (0.0, 0.0) if shared_video else (pre, post)
        n = self.dur / per
        self.uu = np.linspace(-self.pre, self.dur + self.post, 2000)
        v = np.array([speed_fn(self.mode, x / per, n) for x in self.uu])
        cum = np.concatenate([[0], np.cumsum((v[1:] + v[:-1]) / 2 * np.diff(self.uu))])
        self.cum = cum - np.interp(0.0, self.uu, cum); self.v = v
        if shared_video is not None:
            self.video = shared_video
        else:
            f = Path(d["file"]); f = f if f.is_absolute() else base / f
            lo = self.src + self.cum[0] - 0.1; hi = self.src + self.cum[-1] + 0.2
            self.video = Video(f, max(0.0, lo), hi - max(0.0, lo), d.get("hdr", False))
        self._gain = None

    def src_time(self, u):
        return self.src + float(np.interp(u, self.uu, self.cum))

    def speed(self, u):
        return float(np.interp(u, self.uu, self.v))

    def auto_gain(self):
        if self._gain is None:
            g = self.gain
            if g == "auto":
                im = self.video.at(self.src_time(self.dur / 2))
                Y = float(np.median(lum(im)))
                g = float(np.clip(0.44 / max(Y, 1e-3), 0.8, 1.35) ** 0.6)
            self._gain = float(g)
        return self._gain


# ---------------------------------------------------------------- Engine

RESERVED = {"fx", "beat", "t", "beats", "dur", "at_beats", "at", "every", "until", "hits", "kind", "song_start", "comment",
            "kommentar"}


class Event:
    def __init__(self, d, t0, dur, per):
        m = FX[d["fx"]]; self.name = d["fx"]; self.meta = m; self.kind = m["kind"]
        self.p = {**m["defaults"], **{k: v for k, v in d.items() if k not in RESERVED}}
        self.t0 = t0
        self.dur = dur if dur is not None else (m["dur"] if m["dur"] is not None else 1e9)
        if self.kind == "trans":
            self.a, self.b = self.t0 - self.dur / 2, self.t0 + self.dur / 2
        else:
            self.a, self.b = self.t0, self.t0 + self.dur

    def active(self, t, eps=1e-6):
        return self.a - eps <= t < self.b - eps


class Ctx:
    """Wird jedem Effekt übergeben: Frame-Index, Zeit, Beat-Länge, Dauer des Fensters, Zugriff auf Quellen."""

    def __init__(self, eng, i):
        self.eng = eng; self.i = i; self.fps = eng.fps; self.t = i / eng.fps; self.per = eng.per; self.dur = 1e9
        self._base = None

    def source_frame(self, src, u):
        if isinstance(src, (int, float)):           # Zeit im Eingangsvideo / Reel-Zeit
            return self.eng.frame_at_reel(float(src) + u)
        v = self.eng.video_for(src)
        return v.at(float(src.get("src", 0.0)) + u)

    def base_frame(self):
        return self._base if self._base is not None else self.eng.base(self.t, self, skip_layout=True)


class Engine:
    def __init__(self, spec, base_dir=".", window=None):
        """window = (von, bis) in Sekunden: im video-Modus nur diesen Bereich (±1 s) dekodieren."""
        self.spec = spec; self.root = Path(base_dir); b = self.root
        self.fps = spec.get("fps", FPS); self.per = float(spec.get("per", 60 / spec.get("bpm", 140)))
        self.beat0 = float(spec.get("beat0", 0.0))
        self._videos = {}
        if "video" in spec:
            vp = Path(spec["video"]); vp = vp if vp.is_absolute() else b / vp
            if window and window[1]:
                self.main = Video(vp, max(0.0, window[0] - 1.0), window[1] - window[0] + 2.0)
                full = probe(vp); dur = spec.get("duration", round(full["dur"] * full["fps"]) / full["fps"])
            else:
                self.main = Video(vp); dur = spec.get("duration", self.main.n / self.main.fps)
            cuts = spec.get("cuts", [])
            if cuts == "auto":
                cuts = detect_cuts(vp)
            cuts = sorted({0.0, *[round(float(x) * self.fps) / self.fps for x in cuts if 0 < x < dur]})
            ends = cuts[1:] + [dur]
            self.clips = [Clip({"dur": e - s, "src": s}, s, self.per, b, shared_video=self.main) for s, e in zip(cuts, ends)]
        else:
            self.clips = []; t = 0.0
            for d in spec["clips"]:
                c = Clip(d, t, self.per, b); self.clips.append(c); t = c.t1
            dur = spec.get("duration", t)
        self.duration = float(dur); self.n = int(round(self.duration * self.fps))
        self.events = self._expand(spec.get("fx", []))
        self.lut = looks.lut_path(spec.get("lut", None if "video" in spec else STIL["look"]))

    # --- Spec
    def T(self, beat):
        return self.beat0 + float(beat) * self.per

    def _expand(self, items):
        evs = []
        for d in items:
            if d.get("fx") not in FX:
                raise SystemExit(f"Unbekannter Effekt: {d.get('fx')}  (python3 reelvfx.py list)")
            dur = d["beats"] * self.per if "beats" in d else d.get("dur")
            times = []
            if "at_beats" in d:
                times = [self.T(x) for x in d["at_beats"]]
            elif "at" in d:
                times = [float(x) for x in d["at"]]
            elif "hits" in d:
                hp = Path(d["hits"]); hp = hp if hp.is_absolute() else self.root / hp
                hj = json.loads(hp.read_text()); kind = d.get("kind")
                if isinstance(hj, dict) and "accent_map" in hj:     # song.json aus analyse/song_analyse.py
                    hj = [a for a in hj["accent_map"] if kind is None and a.get("kind") != "none" or a.get("kind") == kind]
                elif isinstance(hj, dict):
                    hj = hj.get("hits", hj.get("times", hj))
                times = [float(x["t"] if isinstance(x, dict) else x) - float(d.get("song_start", 0.0)) for x in hj]
                times = [x for x in times if -1e-6 <= x < self.duration - 0.5 / self.fps]
            elif "every" in d:
                b = float(d.get("beat", 0)); end = float(d.get("until", self.duration / self.per))
                while b < end - 1e-6:
                    times.append(self.T(b)); b += float(d["every"])
            elif "beat" in d:
                times = [self.T(d["beat"])]
            elif "t" in d:
                times = [float(d["t"])]
            else:
                times = [0.0]; dur = dur if dur is not None else (self.duration if FX[d["fx"]]["dur"] is None else None)
            for t in times:
                t = round(t * self.fps) / self.fps
                ev = Event(d, t, dur, self.per); evs.append(ev)
                if ev.name == "freeze":                  # Makro: Push + Blitz (+ SW) gehören dazu
                    if ev.p["push"]:
                        evs.append(Event({"fx": "push", "z0": 1.0, "z1": 1 + ev.p["push"]}, t, ev.dur, self.per))
                    if ev.p["flash"]:
                        evs.append(Event({"fx": "flash", "amp": ev.p["flash"], "tau": 0.06}, t, None, self.per))
                    if ev.p["bw"]:
                        evs.append(Event({"fx": "bw"}, t, ev.dur, self.per))
        return evs

    def video_for(self, d):
        key = json.dumps(d, sort_keys=True)
        if key not in self._videos:
            f = Path(d["file"]); f = f if f.is_absolute() else self.root / f
            self._videos[key] = Video(f, max(0.0, float(d.get("src", 0)) - 0.2), float(d.get("dur", 6.0)) + 0.5, d.get("hdr", False))
        return self._videos[key]

    # --- Frames
    def clip_index(self, t):
        for k in range(len(self.clips) - 1, -1, -1):
            if self.clips[k].t0 <= t + 1e-6:
                return k
        return 0

    def clip_image(self, k, t, geo=None, tev=None, ctx=None):
        c = self.clips[k]; u = t - c.t0
        lo, hi = -c.pre, c.dur + c.post - 1 / self.fps
        samples = [(t, 1.0)]
        interp = c.interp
        if tev is not None:
            cc = Ctx(self, ctx.i); cc.dur = tev.dur
            samples = tev.meta["fn"](t, tev.t0, tev.p, cc); interp = tev.p.get("interp", "flow")
        acc = 0; ws = 0
        for ts, w in samples:
            uu = min(max(ts - c.t0, lo), hi)
            im = c.video.at(c.src_time(uu), c.speed(uu) if tev is None else 1.0, interp)
            acc = acc + w * im; ws += w
        im = acc / ws
        g = c.auto_gain()
        if g != 1.0:
            im = im * g
        z = 1.0
        if c.push:
            z = c.push[0] + (c.push[1] - c.push[0]) * _c(u / c.dur)
        fx_, fy_ = c.focus
        dx = dy = rot = 0.0; zb = None; mb = None
        if geo:
            z *= geo["z"]; dx, dy, rot, zb, mb = geo["dx"], geo["dy"], geo["rot"], geo["zb"], geo["mb"]
        return self._warp(im, z, fx_, fy_, dx, dy, rot, zb, mb)

    def _warp(self, im, z, fx_, fy_, dx, dy, rot, zb, mb):
        ident = (abs(z - 1) < 1e-6 and not dx and not dy and not rot and not zb and im.shape[:2] == (H, W))
        if ident:
            out = im
        elif zb:
            spread, n = zb
            out = sum(warp(im, z * (1 + spread * j / (n - 1) * 2), fx_, fy_, dx, dy, rot) for j in range(n)) / n
        else:
            out = warp(im, z, fx_, fy_, dx, dy, rot)
        if mb:
            out = dir_blur(out, *mb)
        return out

    def frame_at_reel(self, t):
        k = self.clip_index(t); return self.clip_image(k, t)

    def geo_at(self, t, ctx):
        g = {"z": 1.0, "dx": 0.0, "dy": 0.0, "rot": 0.0, "zb": None, "mb": None}; hit = False
        for e in self.events:
            if e.kind == "geo" and e.active(t):
                cc = Ctx(self, ctx.i); cc.dur = e.dur
                o = e.meta["fn"](t - e.t0, e.p, cc)
                if not o:
                    continue
                hit = True
                g["z"] *= o.get("z", 1.0); g["dx"] += o.get("dx", 0.0); g["dy"] += o.get("dy", 0.0); g["rot"] += o.get("rot", 0.0)
                if o.get("zb") and (g["zb"] is None or o["zb"][0] > g["zb"][0]):
                    g["zb"] = o["zb"]
                if o.get("mb"):
                    g["mb"] = o["mb"]
                if "focus" in e.p:
                    g["focus"] = e.p["focus"]
        return g if hit else None

    def base(self, t, ctx, skip_layout=False):
        geo = self.geo_at(t, ctx)
        tev = next((e for e in self.events if e.kind == "time" and e.active(t)), None)
        tr = next((e for e in self.events if e.kind == "trans" and e.active(t)), None)
        lay = None if skip_layout else next((e for e in self.events if e.kind == "layout" and e.active(t)), None)
        if lay is not None:
            ctx._base = self.base(t, ctx, skip_layout=True) if lay.name == "pip" else None
            cc = Ctx(self, ctx.i); cc.dur = lay.dur; cc._base = ctx._base
            img = lay.meta["fn"](t - lay.t0, lay.p, cc)
            if geo:
                fo = geo.get("focus", [0.5, 0.5])
                img = self._warp(img, geo["z"], fo[0], fo[1], geo["dx"], geo["dy"], geo["rot"], geo["zb"], geo["mb"])
            return img
        if tr is not None:
            kb = self.clip_index(tr.t0 + 1e-4); ka = max(kb - 1, 0)
            a = self.clip_image(ka, t, None, tev if tev and self.clips[ka].t0 <= tev.t0 < self.clips[ka].t1 else None, ctx)
            b = self.clip_image(kb, t, None, tev if tev and self.clips[kb].t0 <= tev.t0 < self.clips[kb].t1 else None, ctx)
            cc = Ctx(self, ctx.i); cc.dur = tr.dur
            img = tr.meta["fn"](a, b, _c((t - tr.a) / max(tr.dur, 1e-6)), tr.p, cc)
            if geo:
                fo = geo.get("focus", [0.5, 0.5])
                img = self._warp(img, geo["z"], fo[0], fo[1], geo["dx"], geo["dy"], geo["rot"], geo["zb"], geo["mb"])
            return img
        k = self.clip_index(t)
        if tev is not None and not (self.clips[k].t0 <= tev.t0 + 1e-6 < self.clips[k].t1 + 1e-6):
            tev = None
        return self.clip_image(k, t, geo, tev, ctx)

    def render_frame(self, i):
        ctx = Ctx(self, i); t = ctx.t
        img = self.base(t, ctx)
        for e in sorted((e for e in self.events if e.kind in ("pix", "text") and e.active(t)), key=lambda e: e.meta["order"]):
            cc = Ctx(self, i); cc.dur = e.dur
            img = e.meta["fn"](img, t - e.t0, e.p, cc)
        return (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)


# ---------------------------------------------------------------- Budget laut stil.json

NUR_AUF_WUNSCH = {"glitch", "glitch_light", "rgb_split", "freeze", "stutter", "echo", "whip", "whip_zoom", "split", "grid",
                  "pip", "spin", "rewind"}


def check_budget(spec, eng=None):
    """Warnungen, wenn die spec über dem Effekt-Budget aus stil.json liegt."""
    erlaubt = set(spec.get("erlaubt", [])) | set(STIL["erlaubt"])
    B = STIL["budget"]
    names = []
    for d in spec.get("fx", []):
        n = len(d.get("at_beats", d.get("at", []))) or 1
        names += [d["fx"]] * n
    warn = []
    fl = names.count("flash") + names.count("flash_cut")
    if fl > B["flashes"]:
        warn.append(f"{fl} Flashes (Budget {B['flashes']})")
    if names.count("shake") > B["shakes"]:
        warn.append(f"{names.count('shake')}× Shake (Budget {B['shakes']}, nur auf Schlägen/Treffern)")
    # nur Ramp-Kurven zählen (Namen oder Keyframe-Listen), feste Tempi wie 0.75 oder 0.5 sind Zeitlupe
    ramps = sum(1 for c in spec.get("clips", []) if isinstance(c.get("speed"), (str, list))
                and c["speed"] not in ("normal", "fast", "slow")) + names.count("velocity")
    schnell = [Path(str(c.get("file", "?"))).name for c in spec.get("clips", []) if c.get("speed") == "fast"
               or (isinstance(c.get("speed"), (int, float)) and c["speed"] > 1)]
    if schnell:
        warn.append(f"Zeitraffer in {schnell}: Aktionen nie schneller als 1,0× (Stil-Leitfaden, Handwerk)")
    if ramps > B["ramps"]:
        warn.append(f"{ramps} Speed-Ramps (Budget {B['ramps']}, nur auf explosiven Sprüngen, Landung im Bild)")
    for n in sorted(set(names)):
        g = FX[n]["group"]
        if (n in NUR_AUF_WUNSCH or g in ("Text", "Split")) and n not in erlaubt and g.lower() not in erlaubt and n != "safezones":
            warn.append(f"{n}: nur auf ausdrücklichen Wunsch (in \"erlaubt\" eintragen, wenn gewollt)")
        if n == "safezones":
            warn.append("safezones ist nur ein Prüf-Overlay, vor dem Export entfernen")
    tr = [n for n in names if FX[n]["kind"] == "trans" and n not in ("cut", "flash_cut")]
    if len(tr) > B["uebergaenge"]:
        warn.append(f"{len(tr)} Übergangseffekte (Budget {B['uebergaenge']}; Standard ist der harte Schnitt)")
    return warn


# ---------------------------------------------------------------- Rendern

_ENG = None


def _init(e):
    global _ENG
    _ENG = e


def _rf(i):
    return _ENG.render_frame(i)


def render(spec, out, base_dir=".", master=False, t_from=None, t_to=None, procs=4, crf=18, scale=None, quiet=False):
    from multiprocessing import get_context
    eng = Engine(spec, base_dir, (t_from or 0.0, t_to) if t_to else None)
    i0 = int(round((t_from or 0) * eng.fps)); i1 = min(int(round(t_to * eng.fps)), eng.n) if t_to else eng.n
    vf = []
    if eng.lut:
        vf.append(f"lut3d={eng.lut}:interp=tetrahedral")
    if scale:
        vf.append(f"scale={scale}:flags=lanczos")
    if master:
        vf.append("scale=out_color_matrix=bt709:out_range=tv,format=yuv444p")
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "1"]
    else:
        vf.append("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p")
        enc = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-movflags", "+faststart"]
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(eng.fps),
                           "-i", "-", "-vf", ",".join(vf), *enc, "-color_primaries", "bt709", "-color_trc", "bt709",
                           "-colorspace", "bt709", str(out)], stdin=subprocess.PIPE)
    _init(eng)
    with get_context("fork").Pool(procs, initializer=_init, initargs=(eng,)) as pool:
        for n, fr in enumerate(pool.imap(_rf, range(i0, i1), chunksize=2)):
            ff.stdin.write(fr.tobytes())
            if not quiet and n % 60 == 0:
                print(f"Frame {i0 + n}/{i1}", flush=True)
    ff.stdin.close()
    assert ff.wait() == 0, "ffmpeg-Fehler"
    return eng


def stills(spec, outdir, times, base_dir="."):
    ts = [float(x) for x in times]
    eng = Engine(spec, base_dir, (min(ts), max(ts) + 0.1)); outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in times:
        fr = eng.render_frame(int(round(float(t) * eng.fps)))
        p = outdir / f"still_{float(t):07.3f}.jpg"
        vf = f"lut3d={eng.lut}:interp=tetrahedral" if eng.lut else "null"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-i", "-",
                        "-vf", vf, "-q:v", "2", str(p)], input=fr.tobytes(), check=True)
        paths.append(p)
    return paths


# ---------------------------------------------------------------- Werkzeuge

def detect_cuts(path, thr=0.3):
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf", f"select='gt(scene,{thr})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [round(float(m), 3) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]


def stabilize(src, dst, smoothing=30, zoom=4):
    trf = CACHE / (hashlib.sha1(str(Path(src).resolve()).encode()).hexdigest()[:12] + ".trf"); CACHE.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", f"vidstabdetect=shakiness=6:accuracy=15:result={trf}",
                    "-f", "null", "-"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf",
                    f"vidstabtransform=input={trf}:smoothing={smoothing}:zoom={zoom}:optzoom=0:interpol=bicubic,unsharp=5:5:0.35:3:3:0",
                    "-c:v", "libx264", "-crf", "10", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", str(dst)], check=True)


def slowmo(src, dst, factor=2):
    """Zeitlupe durch Zwischenbilder (optischer Fluss). Ausgabe gleiche fps, factor-mal länger."""
    v = Video(src); factor = int(factor)
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{v.w}x{v.h}",
                           "-r", f"{v.fps}", "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(dst)],
                          stdin=subprocess.PIPE)
    for j in range(v.n - 1):
        a, b = v.frame(j), v.frame(j + 1)
        for k in range(factor):
            fr = a if k == 0 else flow_interp(a, b, k / factor)
            ff.stdin.write((np.clip(fr, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes())
    ff.stdin.close(); ff.wait()


def list_effects(md=False):
    lines = []
    for g in GROUPS:
        items = [m for m in FX.values() if m["group"] == g]
        if md:
            lines += [f"\n### {g} ({len(items)})\n", "| Effekt | Was | Standard |", "|---|---|---|"]
        else:
            lines.append(f"\n== {g} ({len(items)}) ==")
        for m in items:
            dfl = ", ".join(f"{k}={v}" for k, v in m["defaults"].items() if k not in ("sources",))
            if m["dur"] is not None and m["kind"] != "pix":
                dfl = (f"Dauer {m['dur']:.2f} s" + (", " if dfl else "")) + dfl
            if md:
                lines.append(f"| `{m['name']}` | {m['desc']} | {dfl.replace('|', '/')} |")
            else:
                lines.append(f"  {m['name']:13s} {m['desc']}\n  {'':13s} [{dfl}]")
    return "\n".join(lines)


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__); return
    cmd = argv[1]
    if cmd == "list":
        print(list_effects("--md" in argv))
    elif cmd == "check":
        spec = json.loads(Path(argv[2]).read_text()); w = check_budget(spec)
        print("\n".join("WARNUNG " + x for x in w) if w else "OK: innerhalb des Effekt-Budgets (stil.json)")
    elif cmd == "render":
        sp = Path(argv[2]); spec = json.loads(sp.read_text())
        opt = {a: argv[k + 1] for k, a in enumerate(argv) if a in ("--von", "--bis")}
        for x in check_budget(spec):
            print("WARNUNG", x)
        render(spec, argv[3], sp.parent, master="--master" in argv, t_from=float(opt.get("--von", 0)),
               t_to=float(opt["--bis"]) if "--bis" in opt else None)
        print("fertig:", argv[3])
    elif cmd == "stills":
        sp = Path(argv[2]); print("\n".join(map(str, stills(json.loads(sp.read_text()), argv[3], argv[4:], sp.parent))))
    elif cmd == "cuts":
        print(json.dumps(detect_cuts(argv[2], float(argv[3]) if len(argv) > 3 else 0.3)))
    elif cmd == "stabilize":
        stabilize(argv[2], argv[3], int(argv[4]) if len(argv) > 4 else 30); print("fertig:", argv[3])
    elif cmd == "slowmo":
        slowmo(argv[2], argv[3], int(argv[4]) if len(argv) > 4 else 2); print("fertig:", argv[3])
    elif cmd == "safezones":
        im = cv2.imread(argv[2]).astype(np.float32) / 255
        im = cv2.resize(im, (W, H)); c = Ctx.__new__(Ctx)
        cv2.imwrite(argv[3], (np.clip(_safez(im, 0, {}, c), 0, 1) * 255).astype(np.uint8)); print("fertig:", argv[3])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
