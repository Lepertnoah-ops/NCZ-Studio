#!/usr/bin/env python3
"""Looks (Farbstile) für Reels als 33³-LUTs.

    python3 looks.py [Zielordner]      # alle Looks als .cube backen (Standard: ./luts)
    python3 looks.py vergleich <bild.jpg> [look …] [-o out.jpg]   # ein Standbild in allen (oder den genannten) Looks
                                       # nebeneinander, beschriftet; Standard-Ausgabe $REEL_WORK/ansicht/looks_vergleich.jpg

Welcher Look gilt, steht in stil.json ("look"): ein Name von unten, der Pfad zu einer eigenen .cube
(relativ zum Projektordner, z. B. "referenz/marke/mein_look.cube"), ein Parameter-Objekt
{"basis": "natural", "sat": 1.05, "warm": 0.01} (Werte wie in grade()) oder null (kein Look).
Anwenden am Ende der ffmpeg-Kette: lut3d=<datei>.cube:interp=tetrahedral (macht pipeline/render.py).
Nicht kombinieren und nicht übertreiben.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
LUT_DIR = HERE / "luts"
EIGEN_DIR = Path(os.environ.get("REEL_WORK", "/home/user/reel")) / "luts"   # gebackene eigene Looks (Parameter)

# Parameter je Look (Werte, die fehlen, nehmen die Standardwerte von grade()). "clean" ist der neutrale Grundstil.
LOOKS = {
    "moody": dict(sat=0.85, curve=0.65, shadows=-0.035, desc="Phonk/nachts: weniger Farbe, härter, dunklere Schatten"),
    "bold": dict(sat=1.10, teal=0.5, desc="House/Afrobeats: kräftiger, weniger Teal"),
    "natural": dict(curve=0.30, split=0.5, desc="Cinematic/R&B: weiche Kurve, halbes Split-Toning"),
    "film": dict(sat=0.92, curve=0.40, lift=0.045, split=0.8, warm=0.018, roll=0.35,
                 desc="warmer Film-Look, angehobene Schwarzwerte, weiche Lichter (gut mit Grain)"),
    "night": dict(sat=0.90, curve=0.55, split=1.3, shadows=-0.02, warm=-0.012,
                  desc="kühler für Abendaufnahmen und Kunstlicht"),
    "clean": dict(hue=0.0, split=0.0, curve=0.30, lift=0.012, skin=0.0,
                  desc="neutral: nur leichte Kontrastkurve, keine Farbverschiebung (Grundstil)"),
    "mono": dict(mono=True, curve=0.60, lift=0.03, split=0.25,
                 desc="Schwarzweiß mit Kontrast, z. B. für ein Freeze oder das Intro"),
}


def grade(rgb, sat=1.0, curve=0.55, lift=0.022, split=1.0, teal=1.0, shadows=0.0, warm=0.0,
          hue=1.0, skin=1.0, roll=0.0, mono=False, desc=None):
    """rgb float32 HxWx3 0..1 (bt709). Parameter: siehe LOOKS; hue/teal/skin verschieben Grün, Blau und Hauttöne,
    curve = S-Kurve, lift = matte Schwarzwerte, split = Split-Toning, warm = Farbtemperatur."""
    hsv = cv2.cvtColor(np.clip(rgb, 0, 1).astype(np.float32), cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    bump = lambda c, w: np.clip(1 - np.abs(((h - c + 180) % 360) - 180) / w, 0, 1) ** 1.5
    wg, wb, wk = bump(110, 55), bump(200, 35), bump(25, 22)
    h = (h - hue * 16 * wg - hue * teal * 14 * wb) % 360
    s = s * (1 - 0.40 * wg * (hue if hue < 1 else 1)) * (1 - 0.04 * wb * teal) * (1 + 0.12 * wk * skin) * 0.98 * sat
    x = np.clip(cv2.cvtColor(np.dstack([h, np.clip(s, 0, 1), v]).astype(np.float32), cv2.COLOR_HSV2RGB), 0, 1)
    if mono:
        Y = 0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2]
        x = np.repeat(Y[..., None], 3, axis=-1)
    x = (1 - curve) * x + curve * (x * x * (3 - 2 * x))           # S-Kurve
    if shadows:
        x = x + shadows * (1 - x) ** 3                             # Schatten dunkler (negativ)
    if roll:
        x = x - roll * 0.25 * np.clip(x - 0.7, 0, None) ** 2 / 0.09  # weiche Lichter
    x = lift + (0.977 - lift) * x                                  # matte Schwarzwerte (0.022 + 0.955 x)
    Y = (0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2])[..., None]
    x = x + split * ((1 - Y) ** 2 * np.array([-0.026, 0.006, 0.036]) + Y ** 2 * np.array([0.030, 0.010, -0.026]))
    if warm:
        x = x + warm * np.array([1.0, 0.25, -1.0])
    return np.clip(x, 0, 1).astype(np.float32)


def params(look):
    """Look-Name oder Parameter-Objekt ({"basis": "natural", "sat": 1.05}) -> Parameter für grade()."""
    if isinstance(look, dict):
        p = dict(LOOKS[look.get("basis", "clean")])
        p.update({k: v for k, v in look.items() if k != "basis"})
    else:
        p = LOOKS[look]
    return {k: v for k, v in p.items() if k != "desc"}


def bake(name, path=None, n=33):
    p = params(name)
    r = np.linspace(0, 1, n, dtype=np.float32)
    b, g, rr = np.meshgrid(r, r, r, indexing="ij")                 # Rot läuft am schnellsten
    rgb = np.stack([rr, g, b], -1).reshape(n * n, n, 3)
    out = grade(rgb, **p).reshape(-1, 3)
    path = Path(path or LUT_DIR / f"{name}.cube")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(f'TITLE "Reel-Studio {name if isinstance(name, str) else "eigen"}"\nLUT_3D_SIZE {n}\n')
        f.writelines(f"{x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in out)
    return path


def _cube_file(name):
    p = Path(str(name))
    return p if p.is_absolute() else PROJECT / p


def lut_path(name):
    """Pfad zur .cube eines Looks (wird bei Bedarf gebacken). Auch ein .cube-Pfad oder ein Parameter-Objekt geht."""
    if name is None or name in ("", "none", "keiner"):
        return None
    if isinstance(name, dict):
        key = hashlib.md5(json.dumps(name, sort_keys=True).encode()).hexdigest()[:10]
        p = EIGEN_DIR / f"eigen_{key}.cube"
        if not p.exists():
            bake(name, p)
        return p
    if str(name).endswith(".cube"):
        p = _cube_file(name)
        if not p.is_file():
            raise FileNotFoundError(f"Look-Datei fehlt: {p}")
        return p
    if name not in LOOKS:
        raise KeyError(f"Look {name!r} unbekannt, verfügbar: {', '.join(LOOKS)} (oder .cube-Pfad)")
    p = LUT_DIR / f"{name}.cube"
    if not p.exists():
        bake(name, p)
    return p


def read_cube(path):
    """.cube lesen -> Array [b][g][r][3] (Rot läuft in der Datei am schnellsten)."""
    n, vals = None, []
    for line in open(path):
        t = line.split()
        if not t or t[0].startswith("#"):
            continue
        if t[0] == "LUT_3D_SIZE":
            n = int(t[1])
        elif t[0][0] in "-.0123456789" and len(t) == 3:
            vals.append([float(x) for x in t])
    return np.array(vals, np.float32).reshape(n, n, n, 3)


def apply_cube(rgb, lut):
    """3D-LUT trilinear auf ein float-RGB-Bild (0..1) anwenden (Vorschau; ffmpeg rechnet im Video tetraedrisch)."""
    n = lut.shape[0]
    x = np.clip(rgb, 0, 1) * (n - 1)
    i0 = np.minimum(np.floor(x).astype(np.int32), n - 2)
    f = x - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    out = 0
    for db, wb in ((0, 1 - fb), (1, fb)):
        for dg, wg in ((0, 1 - fg), (1, fg)):
            for dr, wr in ((0, 1 - fr), (1, fr)):
                out = out + wb * wg * wr * lut[b0 + db, g0 + dg, r0 + dr]
    return out.astype(np.float32)


def apply_rgb(rgb, look):
    """Look (Name, Parameter-Objekt, .cube-Pfad oder None) auf ein float-RGB-Bild (0..1) anwenden."""
    if look is None or look in ("", "none", "keiner"):
        return np.clip(rgb, 0, 1).astype(np.float32)
    if isinstance(look, str) and look.endswith(".cube"):
        return apply_cube(rgb, _read_cube_cached(str(_cube_file(look))))
    return grade(rgb, **params(look))


_CUBES = {}


def _read_cube_cached(path):
    if path not in _CUBES:
        _CUBES[path] = read_cube(path)
    return _CUBES[path]


def apply_numpy(bgr, name):
    """Look direkt auf ein float-BGR-Bild anwenden (für Standbilder/Kontaktbögen, nicht für Videos)."""
    return apply_rgb(bgr[..., ::-1], name)[..., ::-1]


def vergleich(bild, namen=None, out=None, breite=300):
    """Ein Bild in mehreren Looks nebeneinander (Original zuerst), höchstens ~1,1 MP, damit Claude es günstig ansieht."""
    from PIL import Image, ImageDraw, ImageFont
    namen = namen or ["ohne"] + list(LOOKS)
    im = Image.open(bild).convert("RGB")
    h = round(breite * im.height / im.width)
    rgb = np.asarray(im.resize((breite, h), Image.LANCZOS), np.float32) / 255
    cols = min(4, len(namen))
    rows = -(-len(namen) // cols)
    tafel = Image.new("RGB", (cols * breite, rows * (h + 34)), (14, 14, 14))
    d = ImageDraw.Draw(tafel)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf", 20)
    except OSError:
        f = ImageFont.load_default()
    for i, n in enumerate(namen):
        x = rgb if n == "ohne" else apply_rgb(rgb, n)
        tile = Image.fromarray((np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8))
        cx, cy = (i % cols) * breite, (i // cols) * (h + 34)
        tafel.paste(tile, (cx, cy + 34))
        d.text((cx + 8, cy + 6), n if isinstance(n, str) else "eigen", font=f, fill=(240, 240, 240))
    k = min(1.0, (1.1e6 / (tafel.width * tafel.height)) ** 0.5)
    if k < 1:
        tafel = tafel.resize((round(tafel.width * k), round(tafel.height * k)), Image.LANCZOS)
    out = Path(out or Path(os.environ.get("REEL_WORK", "/home/user/reel")) / "ansicht" / "looks_vergleich.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    tafel.save(out, quality=88)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "vergleich":
        args = sys.argv[2:]
        ziel = args[args.index("-o") + 1] if "-o" in args else None
        rest = [a for i, a in enumerate(args) if a != "-o" and (i == 0 or args[i - 1] != "-o")]
        print(vergleich(rest[0], (["ohne"] + rest[1:]) if len(rest) > 1 else None, ziel))
        sys.exit(0)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else LUT_DIR
    for k in LOOKS:
        print(k.ljust(10), bake(k, out / f"{k}.cube"))
