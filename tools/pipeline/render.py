#!/usr/bin/env python3
"""Reel rendern: Frames aus WORK/frames/<clip>/ -> Effekte je Shot -> BGR-Pipe -> ffmpeg
(Look aus stil.json als LUT, lut3d tetraedrisch, yuv444p, x264 crf 1 = Master ohne Ton).

    python3 render.py master  <reel>_master.mp4       # ganzes Reel
    python3 render.py preview <frame> [<frame> …]      # Einzelbilder nach WORK/prev/g_*.jpg (mit LUT)

EDL/Effekte: $REEL_EDL / $REEL_FX (Standard WORK/edl.json, fx.json daneben). Danach Ton mit
tools/reel_audio.py mix + mux, Instagram-Export nach Projektanweisungen, Prüfung mit verify.py.
Look und Vignette: stil.json ("look", "vignette"); REEL_LOOK überschreibt den Look für einen Lauf.

Effekte je Shot in fx.json {"<n>": {...}}, Zeiten in Beats ab Shot-Start:
  push   [z0, z1]            Zoom über den Shot (weich), z. B. [1.0, 1.06] = Push-in 6 %
  punch  [[b, A(, blur)]…]   Zoom-Punch 1 + A·e^(−t/0,09 s); blur 0 = ohne Zoom-Blur (Mini-Punch auf dem Clap)
  shake  [[b, px, grad]…]    abklingender Shake (τ 0,14 s), Zoom +7 % solange Shake aktiv
  flash  [[b, A]…]           Weißblitz A·e^(−t/0,05 s)
  whip   true                Whip-Zoom zum Shot-Ende (Übergang)
  echo   true                Echo-Trail ab Beat 2
  focus  [x, y]              Bildausschnitt-Mitte (0–1) für Zooms
  gain   f                   Belichtung zusätzlich zur Automatik
  split_punch [[b, A]…], expand b    nur Split-Shots: Punch auf alle Streifen, ab Beat b öffnet die Mitte ins Vollbild
Shot-Felder: mode (siehe timing.py), freeze_at, cont (Fortsetzung eines Split-Streifens), strips (Split),
  ueber "blende"   Überblendung in diesen Shot (Stil-Leitfaden Regel 5): beginnt auf dem Schnitt,
                   dauert blende_frames (Standard 12 = 0,4 s, linear); der Shot davor läuft darunter in seinem Tempo weiter.
"""
import functools
import json
import multiprocessing as mp
import os
import subprocess
import sys

import cv2
import numpy as np

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
from reelcfg import FPS, H, STIL, W, WORK, load_edl, load_fx, look_spec, looks_module, total_beats
from timing import src_at

E = SH = FX = CUT = None
PER = N = 0


def init(edl=None, fx=None):
    """EDL und Effekte laden (vor dem Pool, die Worker erben sie per fork)."""
    global E, SH, FX, CUT, PER, N
    E = edl if isinstance(edl, dict) else load_edl(edl)
    SH, PER = E["shots"], E["per"]
    FX = fx if isinstance(fx, dict) else load_fx(E, fx)
    N = round(total_beats(E) * PER * FPS)
    CUT = [round(s["t"] * FPS) for s in SH] + [N]
    gain.cache_clear()
    strip_gain.cache_clear()
    SRCS.clear()


class Src:
    def __init__(self, clip):
        d = json.load(open(WORK / "frames" / clip / "times.json"))
        self.t = np.array(d["times"])
        self.fps = d["fps"]
        self.clip = clip

    @functools.lru_cache(maxsize=24)
    def frame(self, j):
        return cv2.imread(str(WORK / "frames" / self.clip / f"f_{j + 1:05d}.jpg"))

    def nearest(self, s):
        return int(np.clip(np.searchsorted(self.t, s - 0.5 / self.fps), 0, len(self.t) - 1))

    def sample(self, s, exp):
        """Bild zur Quellzeit s; exp > 1 Frame = Bewegungsunschärfe durch Mittelung (Belichtungszeit exp)."""
        if exp < 1 / self.fps * 0.999:
            return self.frame(self.nearest(s)).astype(np.float32) / 255
        a, b = s - exp / 2, s + exp / 2
        edges = np.append(self.t, self.t[-1] + 1 / self.fps)
        acc, wsum = 0, 0
        j0 = max(0, np.searchsorted(self.t, a) - 1)
        j1 = min(len(self.t) - 1, np.searchsorted(self.t, b))
        for j in range(j0, j1 + 1):
            w = max(0, min(b, edges[j + 1]) - max(a, edges[j]))
            if w > 0:
                acc = acc + w * self.frame(j).astype(np.float32)
                wsum += w
        if wsum == 0:
            return self.frame(self.nearest(s)).astype(np.float32) / 255
        return acc / wsum / 255


SRCS = {}


def src(c):
    if c not in SRCS:
        SRCS[c] = Src(c)
    return SRCS[c]


def warp(img, z, fx=0.5, fy=0.5, dx=0, dy=0, rot=0, ow=W, oh=H):
    """Quelle füllt ow×oh bei z=1 (Cover); Fokuspunkt (fx, fy) -> Ausgabemitte, ohne sichtbaren Rand."""
    hs, ws = img.shape[:2]
    k = max(ow / ws, oh / hs) * z
    if k < 1:
        img = cv2.resize(img, (round(ws * k), round(hs * k)), interpolation=cv2.INTER_AREA)
        k2 = 1.0
        hs, ws = img.shape[:2]
    else:
        k2 = k
    hw, hh = ow / 2 / k2, oh / 2 / k2
    cx = np.clip(fx * ws, hw, ws - hw) if ws >= 2 * hw else ws / 2
    cy = np.clip(fy * hs, hh, hs - hh) if hs >= 2 * hh else hs / 2
    M = cv2.getRotationMatrix2D((cx, cy), rot, k2)
    M[0, 2] += ow / 2 - cx + dx
    M[1, 2] += oh / 2 - cy + dy
    return cv2.warpAffine(img, M, (ow, oh), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)


yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
rr = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / np.sqrt(2)
VIG = (1 - float(STIL["vignette"]) * np.clip((rr - 0.35) / 0.65, 0, 1) ** 2)[..., None].astype(np.float32)
del yy, xx, rr


def luma_gain(im):
    Y = np.median(0.2126 * im[..., 2] + 0.7152 * im[..., 1] + 0.0722 * im[..., 0])
    return float(np.clip(0.44 / max(float(Y), 1e-3), 0.8, 1.35) ** 0.6)


@functools.lru_cache(maxsize=256)
def gain(k):
    s = SH[k]
    fx = FX.get(str(s["n"]), {})
    if s["clip"] == "split":
        return 1.0
    if s.get("cont"):
        return strip_gain(k - 1, 1)   # gleiche Belichtung wie der Split-Streifen, aus dem er kommt
    mid, _ = src_at(s, s["beats"] * PER / 2, PER)
    return luma_gain(src(s["clip"]).sample(mid, 0)) * fx.get("gain", 1.0)


@functools.lru_cache(maxsize=64)
def strip_gain(k, si):
    st = SH[k]["strips"][si]
    return luma_gain(src(st["clip"]).sample(st["src"] + SH[k]["beats"] * PER / 2, 0))


def env(u, t0, tau):
    """Hüllkurve eines Treffers bei t0: setzt auf dem Frame ein, der dem Treffer am nächsten liegt. So sitzt ein Punch
    auf Beat 0 immer auf dem Schnitt-Frame (CUT rundet genauso), auch wenn der Beat knapp hinter dem Frame liegt."""
    return np.exp(-max(0.0, u - t0) / tau) if u >= t0 - 0.5 / FPS - 1e-9 else 0.0


def shot_index(i):
    return max(j for j in range(len(SH)) if CUT[j] <= i)


BLENDE = 12   # Frames einer Überblendung (0,4 s, gemessen an Vorbild-Reels)


def src_ext(s, u):
    """Quellzeit und Tempo wie src_at, nach dem Shot-Ende im letzten Tempo weiter (Überblendung in den nächsten Shot)."""
    d = s["beats"] * PER
    if u <= d:
        return src_at(s, u, PER)
    sp, v = src_at(s, d, PER)
    return sp + (u - d) * v, v


def render_frame(i):
    """Frame i des Reels; in den ersten Frames eines Shots mit ueber="blende" gemischt mit dem Shot davor."""
    k = shot_index(i)
    s = SH[k]
    nb = s.get("blende_frames", BLENDE) if s.get("ueber") == "blende" and k > 0 else 0
    j = i - CUT[k]
    if j >= nb:
        return render_shot(k, i)
    a = (j + 1) / (nb + 1)
    mix = (1 - a) * render_shot(k - 1, i).astype(np.float32) + a * render_shot(k, i).astype(np.float32)
    return (mix + 0.5).astype(np.uint8)


def render_shot(k, i):
    s = SH[k]
    fx = FX.get(str(s["n"]), {})
    u = i / FPS - s["t"]
    b = u / PER
    fxp, fyp = fx.get("focus", [0.5, 0.5])
    z = 1.0
    if "push" in fx:
        z0, z1 = fx["push"]
        x = np.clip(b / s["beats"], 0, 1)
        z = z0 + (z1 - z0) * (x * x * (3 - 2 * x) * 0.5 + x * 0.5)
    if "shake" in fx:
        z *= 1.07
    zoom_blur = None
    for p in fx.get("punch", []):
        bh, A = p[0], p[1]
        blur = p[2] if len(p) > 2 else 1
        uh = bh * PER
        ih = round((s["t"] + uh) * FPS)
        z *= 1 + A * env(u, uh, 0.09)
        if blur and 0 <= i - ih < 3:
            zoom_blur = (0.022, 3)
    dx = dy = rot = 0
    for bh, apx, adeg in fx.get("shake", []):
        uh = bh * PER
        if u >= uh - 0.5 / FPS - 1e-9:
            t = max(0.0, u - uh)
            e = np.exp(-t / 0.14)
            dx += apx * e * np.sin(2 * np.pi * 9 * t + 0.3)
            dy += apx * 0.7 * e * np.sin(2 * np.pi * 11 * t + 1.3)
            rot += adeg * e * np.sin(2 * np.pi * 7 * t + 0.5)
    if fx.get("whip"):
        x = np.clip(b / s["beats"], 0, 1)
        z *= 1 + 0.75 * x ** 3
        if x > 0.3:
            zoom_blur = (0.03 * x ** 2, 5)
    if s["mode"] == "freeze" and b >= s["freeze_at"]:
        z *= 1 + 0.05 * (b - s["freeze_at"]) / (s["beats"] - s["freeze_at"])
    g = gain(k)
    if s["clip"] == "split":
        return render_split(k, s, fx, u, b, dx)
    ss = src(s["clip"])
    sp, v = src_ext(s, u)
    exp = max(1 / ss.fps, abs(v) * 0.75 / FPS) if v > 0.05 else 0
    if v <= 1.0 and (ss.fps < 40 or s["mode"] in ("slow", "speed")):
        exp = 0   # Zeitlupe und Echtzeit aus 30 fps: Einzelbild, keine Mittelung
    im = ss.sample(sp, exp)
    if fx.get("echo") and b >= 2.0:
        w0 = min(1, (b - 2.0) / 0.25)
        acc, ws = im.copy(), 1.0
        for d, w in [(0.05, .6), (0.10, .4), (0.15, .25)]:
            acc += w0 * w * ss.sample(sp - d, 0)
            ws += w0 * w
        im = acc / ws
    im = np.clip(im * g, 0, 1)
    if zoom_blur:
        spread, n = zoom_blur
        out = sum(warp(im, z * (1 + spread * j / (n - 1) * 2), fxp, fyp, dx, dy, rot) for j in range(n)) / n
    else:
        out = warp(im, z, fxp, fyp, dx, dy, rot)
    return finish(out, u, fx, s)


def render_split(k, s, fx, u, b, dx):
    """3er-Split: Streifen setzen im ½-Beat-Abstand ein; ab fx['expand'] öffnet der mittlere ins Vollbild."""
    out = np.zeros((H, W, 3), np.float32)
    ex, x = fx.get("expand"), 0.0
    if ex is not None and b > ex:
        x = float(np.clip((b - ex) / (s["beats"] - ex), 0, 1))
        x = x * x * (3 - 2 * x)
    d_up, d_dn = round(641 * x), round((H - 1279) * x)
    for si, st in enumerate(s["strips"]):
        ua = si * 0.5 * PER
        if u < ua - 1.0 / FPS:
            continue
        im = np.clip(src(st["clip"]).sample(st["src"] + u, 0.75 / FPS) * strip_gain(k, si), 0, 1)
        zz = st["zoom"] * (1 + 0.07 * env(u, ua, 0.09))
        for hb, A in fx.get("split_punch", []):
            zz *= 1 + A * env(u, hb * PER, 0.09)
        t = (u - ua) * FPS
        slide = (1 - min(1, (t + 1) / 4)) ** 3 * (1 if si % 2 == 0 else -1) * W
        if si == 1:
            y0, y1 = 641 - d_up, 1279 + d_dn
            zz = zz * (1 - x) + 1.0 * x
            fy = st["y"] * (1 - x) + 0.5 * x
            out[y0:y1] = warp(im, zz, 0.5, fy, dx=slide, ow=W, oh=y1 - y0)
        else:
            if x >= 0.999:
                continue
            strip = warp(im, zz, 0.5, st["y"], dx=slide, ow=W, oh=638)
            if si == 0:
                out[0:638 - d_up] = strip[d_up:]
            else:
                out[1282 + d_dn:1920] = strip[:638 - d_dn]
    return finish(out, u, fx)


def finish(out, u, fx, s=None):
    a = sum(A * env(u, bh * PER, 0.05) for bh, A in fx.get("flash", []))
    if s is not None and s["mode"] == "freeze":
        a += 0.35 * env(u, s["freeze_at"] * PER, 0.06)
    if a > 0:
        out = out + (1 - out) * min(a, 0.9)
    return (np.clip(out * VIG, 0, 1) * 255 + 0.5).astype(np.uint8)


def lut_filter():
    """ffmpeg-Filter für den Look (mit Komma am Ende) oder leer, wenn kein Look gilt."""
    p = looks_module().lut_path(look_spec())
    return f"lut3d={p}:interp=tetrahedral," if p else ""


def pool():
    return mp.get_context("fork").Pool(os.cpu_count() or 4)


def preview(idx):
    d = WORK / "prev"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*"):
        f.unlink()
    with pool() as p:
        for i, fr in zip(idx, p.imap(render_frame, idx)):
            cv2.imwrite(str(d / f"raw_{i:05d}.png"), fr)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", f"{d}/raw_*.png", "-vf",
                    lut_filter() + "null", "-q:v", "3", "-start_number", "0", f"{d}/g_%03d.jpg"],
                   check=True)
    return sorted(d.glob("g_*.jpg"))


def master(out):
    vf = lut_filter() + "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p"
    if any(s.get("dialog") for s in SH):     # Dialog-Szenen (dialog.py): Untertitel nach der LUT einbrennen
        import dialog
        from untertitel import FONTS
        vf += f",ass={dialog.untertitel_ass(E, WORK)}:fontsdir={FONTS}"
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-vf", vf,
                           "-c:v", "libx264", "-preset", "veryfast", "-crf", "1", "-color_primaries", "bt709",
                           "-color_trc", "bt709", "-colorspace", "bt709", str(out)], stdin=subprocess.PIPE)
    with pool() as p:
        for n, fr in enumerate(p.imap(render_frame, range(N), chunksize=4)):
            ff.stdin.write(fr.tobytes())
            if n % 100 == 0:
                print("frame", n, "/", N, flush=True)
    ff.stdin.close()
    assert ff.wait() == 0
    print("master ok", N, "Frames ->", out)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    init()
    if sys.argv[1] == "preview":
        print("\n".join(map(str, preview([int(x) for x in sys.argv[2:]]))))
    else:
        master(sys.argv[2])
