#!/usr/bin/env python3
"""Kleine Ansichten für Claude: ein Bild statt vieler, nie größer als nötig (spart Nutzungslimit).

    python3 ansicht.py reel <video.mp4> [--edl edl.json] [-o out.jpg]   # 1 Frame pro Shot als Raster mit #Nr.
    python3 ansicht.py szenen <video.mp4> --edl edl.json [--von N] [--bis M] [--pro-bild 8]   # 4 Frames je Shot
    python3 ansicht.py clip <clip> <von> <bis> [--n 8] [-o out.jpg]       # dichte Frames eines Clips (Peak, Wiederholung)
    python3 ansicht.py bild <bild> [--teil 2/4] [-o out.jpg]              # Ausschnitt eines großen Bildes (Storyboard)

Ausgabe nach $REEL_WORK/ansicht/ (Standard /home/user/reel/ansicht), höchstens ~1,1 Megapixel und 1568 px pro Seite:
größer zeigt Claude ein Bild ohnehin nicht an, jedes Pixel mehr kostet nur. Das Bild dann einmal mit Read ansehen
und den Befund gleich notieren, nicht dasselbe Bild zweimal öffnen.
- reel: mit --edl (edl.json der Variante) ein Frame pro Shot, Shot-Mitte, bei Speed-Ramps der Hit (Beat 2 im Shot),
  beschriftet mit der Shot-Nummer wie im Storyboard. Ohne --edl alle 2 s ein Frame. Video: master_X.mp4 im
  Arbeitsordner (varianten.py) oder das fertige Reel.
- szenen: 4 Frames je Shot aus dem Master (kurz nach dem Schnitt, 1/3, 2/3, kurz vor dem Ende), 2 Shots pro Zeile,
  8 Shots pro Bild. Pflicht vor dem Vorlegen der Varianten (Stil-Leitfaden Regel 7): ist die ganze Aktion drin,
  kommt der Schnitt erst nach der Landung, bleibt die Szene im sauberen Fenster? --von/--bis für einzelne Shots.
- clip: <clip> = Kürzel mit gezogenen Frames in $REEL_WORK/frames/<clip>/ (extract.py) oder eine Videodatei;
  von/bis = Sekunden Quellzeit. Beschriftung = Quellzeit.
- bild: hohe Bilder (Storyboard 1080×5500 wäre auf einmal unlesbar) in n Teile schneiden; ohne --teil nur verkleinern.
"""
import json
import math
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.dont_write_bytecode = True
WORK = Path(os.environ.get("REEL_WORK", "/home/user/reel"))
MAX_SEITE, MAX_PIXEL = 1568, 1.1e6
FONTS = ("/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def font(size):
    for f in FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def passend(im):
    """Auf höchstens MAX_SEITE pro Seite und MAX_PIXEL verkleinern."""
    w, h = im.size
    s = min(1.0, MAX_SEITE / max(w, h), math.sqrt(MAX_PIXEL / (w * h)))
    return im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS) if s < 1 else im


def raster(bilder, texte, spalten=None):
    """Kacheln gleicher Form zu einem Raster, so groß wie die Grenzen erlauben (spalten: fest, z. B. 8 = 2 Shots à 4)."""
    n, ar = len(bilder), bilder[0].height / bilder[0].width
    best = None
    for c in ([spalten] if spalten else range(1, n + 1)):
        r = math.ceil(n / c)
        w = min(MAX_SEITE / c, MAX_SEITE / (r * ar), math.sqrt(MAX_PIXEL / (c * r * ar)))
        if best is None or w > best[0]:
            best = (w, c, r)
    w, c, r = best
    w, h = int(w), int(w * ar)
    out = Image.new("RGB", (c * w, r * h), (14, 14, 14))
    d, f = ImageDraw.Draw(out), font(max(11, w // 8))
    for i, (b, t) in enumerate(zip(bilder, texte)):
        x, y = (i % c) * w, (i // c) * h
        out.paste(b.convert("RGB").resize((w, h), Image.LANCZOS), (x, y))
        if t:
            x0, y0, x1, y1 = d.textbbox((x + 3, y + 2), t, font=f)
            d.rectangle((x0 - 2, y0 - 1, x1 + 2, y1 + 1), fill=(0, 0, 0))
            d.text((x + 3, y + 2), t, font=f, fill=(205, 255, 60))
    return out


def frame(video, t, breite=360):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={breite}:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "3", "-"],
                       capture_output=True)
    if r.returncode or not r.stdout:
        raise SystemExit(f"Kein Frame bei {t:.2f} s aus {video}: {r.stderr.decode()[-300:]}")
    return Image.open(BytesIO(r.stdout))


def dauer(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def reel(video, edl=None):
    if edl:
        E = json.load(open(edl))
        per, zeiten, texte = E["per"], [], []
        for s in E["shots"]:
            if s.get("cont"):
                continue
            t = s["t"] + (2 * per + 0.02 if s.get("mode") in ("ramp", "ramp_hold") else s["beats"] * per / 2)
            zeiten.append(t)
            texte.append(f"#{s['n']}")
    else:
        d = dauer(video)
        zeiten = [t + 0.5 for t in range(0, int(d), 2)]
        texte = [f"{t:.0f}s" for t in zeiten]
    return raster([frame(video, t) for t in zeiten], texte)


def frames_bei(video, idx, breite=160):
    """Mehrere Frames (Frame-Nummern bei 30 fps) in einem ffmpeg-Lauf statt einem Seek je Bild."""
    sel = "+".join(f"eq(n\\,{i})" for i in idx)
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"select='{sel}',scale={breite}:-2", "-vsync", "0",
                        "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "3", "-"], capture_output=True)
    teile = [b"\xff\xd8" + t for t in r.stdout.split(b"\xff\xd8")[1:]]
    if r.returncode or len(teile) != len(idx):
        raise SystemExit(f"{len(teile)} von {len(idx)} Frames aus {video}: {r.stderr.decode()[-300:]}")
    return [Image.open(BytesIO(t)) for t in teile]


def szenen(video, edl, von=1, bis=999, pro_bild=8):
    """4 Frames je Shot aus dem Master (Anfang, 1/3, 2/3, Ende), 2 Shots pro Zeile: ist die Aktion ganz drin?"""
    E = json.load(open(edl))
    shots = [s for s in E["shots"] if von <= s["n"] <= bis and not s.get("cont")]
    idx, texte = [], []
    for s in shots:
        a, b = round(s["t"] * 30), round((s["t"] + s["beats"] * E["per"]) * 30) - 1
        idx += [a + 1, round(a + (b - a) / 3), round(a + 2 * (b - a) / 3), b - 1]
        texte += [f"#{s['n']} {s['clip']} {s['beats']:g}B", "", "", "Ende"]
    bilder = frames_bei(video, idx)
    k = 4 * pro_bild
    return [raster(bilder[i:i + k], texte[i:i + k], spalten=8) for i in range(0, len(bilder), k)]


def clip(name, von, bis, n):
    ziele = [von + (bis - von) * i / max(1, n - 1) for i in range(n)]
    p = Path(name)
    if p.is_file():
        return raster([frame(p, t) for t in ziele], [f"{t:.2f}s" for t in ziele])
    d = WORK / "frames" / name
    if not (d / "times.json").exists():
        raise SystemExit(f"Keine Frames in {d} (extract.py gelaufen?) und keine Videodatei {name}")
    zeiten = json.load(open(d / "times.json"))["times"]
    if ziele[0] < zeiten[0] - 0.05 or ziele[-1] > zeiten[-1] + 0.05:
        print(f"Hinweis: Frames von {name} decken nur {zeiten[0]:.2f}–{zeiten[-1]:.2f} s ab")
    idx = sorted({min(range(len(zeiten)), key=lambda k: abs(zeiten[k] - t)) for t in ziele})
    return raster([Image.open(d / f"f_{k + 1:05d}.jpg") for k in idx], [f"{zeiten[k]:.2f}s" for k in idx])


def bild(pfad, teil=None):
    im = Image.open(pfad).convert("RGB")
    if teil:
        i, n = map(int, teil.split("/"))
        h = im.height / n
        im = im.crop((0, int(max(0, (i - 1) * h - 0.02 * h)), im.width, int(min(im.height, i * h + 0.02 * h))))
    return passend(im)


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ("reel", "szenen", "clip", "bild"):
        sys.exit(__doc__)
    modus, quelle = a[0], a[1]
    teil = arg("--teil")
    if modus == "szenen":
        if not arg("--edl"):
            sys.exit("szenen braucht --edl <reel>/schnitt/X/edl.json")
        stamm = Path(arg("--edl")).parent.name or Path(quelle).stem
        for j, im in enumerate(szenen(quelle, arg("--edl"), int(arg("--von", 1)), int(arg("--bis", 999)),
                                      int(arg("--pro-bild", 8))), 1):
            out = WORK / "ansicht" / f"szenen_{stamm}_{j:02d}.jpg"
            out.parent.mkdir(parents=True, exist_ok=True)
            im = passend(im)
            im.save(out, quality=85)
            print(f"{out}  {im.width}×{im.height}")
        return
    if modus == "reel":
        im = reel(quelle, arg("--edl"))
    elif modus == "clip":
        im = clip(quelle, float(a[2]), float(a[3]), int(arg("--n", 8)))
    else:
        im = bild(quelle, teil)
    im = passend(im)
    stamm = Path(quelle).stem + (f"_teil{teil.replace('/', 'von')}" if teil else "")
    out = Path(arg("-o") or WORK / "ansicht" / f"{modus}_{stamm}.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=85)
    print(f"{out}  {im.width}×{im.height}")


if __name__ == "__main__":
    main()
