#!/usr/bin/env python3
"""Vorschau-Galerie: ein kurzes Demo-Video pro Effekt an einem eigenen fertigen Reel + Übersichtsbild.

    python3 gallery.py <reel>_ohne_ton.mp4 [zielordner] [effekt ...]

Das Reel sollte mindestens 14 s lang sein und bei 12,0 s einen Schnitt haben (bei 140 BPM: Beat 28).
Ausschnitt A (10,8–13,2 s, Schnitt bei 1,2 s) für Übergänge und Split, Ausschnitt B (0,857–3,257 s)
für alles andere. Tempo anderer Songs: PER unten anpassen (Sekunden pro Beat). Dezente Bild-Looks (Grain, Chroma, Bloom ...) laufen als Vorher/Nachher:
links ohne, rechts mit Effekt. Jede Demo trägt oben den Effektnamen.
"""
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reelvfx as rv  # noqa: E402

PER = 0.42858
FULL = None  # ganzes Reel-Video (für Split-Quellen), wird in main() gesetzt
CUT = 1.2
SPLIT_LOOKS = {"vignette", "grain", "chroma", "bloom", "halation", "sharpen", "exposure", "bw"}


@rv.effect("_caption", "Galerie", "text", "Beschriftung der Galerie", order=300, label="", info="")
def _caption(img, u, p, c):
    lay = rv.text_layer(p["label"], 48, "Bold", 2, shadow=0.6)
    img = rv.blit(img, lay, rv.W / 2, rv.H * 0.105, 1.0, 1.0)
    for k, line in enumerate(textwrap.wrap(p["info"], 44)[:3]):
        img = rv.blit(img, rv.text_layer(line, 28, "Medium", 0, shadow=0.7), rv.W / 2, rv.H * 0.105 + 58 + k * 38, 1.0, 0.95)
    return img


def _cmp(name):
    fn = rv.FX[name]["fn"]

    def f(img, u, p, c):
        out = fn(img.copy(), u, p, c)
        res = img.copy(); res[:, rv.W // 2:] = out[:, rv.W // 2:]
        res[:, rv.W // 2 - 2:rv.W // 2 + 2] = 1.0
        return res
    return f


def demo_spec(name, src_a, src_b):
    m = rv.FX[name]; k = m["kind"]
    cap = {"fx": "_caption", "label": f"{name}  ·  {m['group']}", "info": m["desc"]}
    ev = {"fx": name}
    if k == "trans":
        return {"video": src_a, "cuts": [CUT], "per": PER, "beat0": CUT, "fx": [dict(ev, beat=0), cap]}, CUT + 0.02
    if k == "layout":
        full = {"file": str(FULL), "dur": 2.6}
        srcs = [dict(full, src=t) for t in {"split": [12.0, 18.0, 24.0], "grid": [12.0, 15.43, 18.0, 24.0], "pip": [18.0]}[name]]
        e = dict(ev, beat=0.3, sources=srcs, beats=5)
        if name == "split":
            e["expand_beats"] = 3.6
        return {"video": src_a, "per": PER, "fx": [e, cap]}, 1.3
    spec = {"video": src_b, "per": PER, "fx": [cap]}
    if name in SPLIT_LOOKS:
        rv.FX["_cmp_" + name] = dict(rv.FX[name], name="_cmp_" + name, fn=_cmp(name))
        spec["fx"].insert(0, {"fx": "_cmp_" + name}); cap["info"] = "links ohne | rechts mit. " + m["desc"]
        return spec, 1.0
    if k == "geo" and m["dur"] and m["dur"] < 1:
        spec["fx"].insert(0, dict(ev, at_beats=[1, 3]) if name not in ("zoom_step", "whip_zoom") else dict(ev, beat=1, beats=2))
        return spec, PER + 2 / 30
    if k == "geo":
        spec["fx"].insert(0, dict(ev, beat=0.5, beats=4)); return spec, 1.6
    if k == "time":
        spec["fx"].insert(0, dict(ev, beat=1, beats=3) if name != "freeze" else dict(ev, beat=1.5, beats=2)); return spec, 1.0
    if name in ("flash", "glow_pulse", "rgb_split", "glitch_light"):
        spec["fx"].insert(0, dict(ev, at_beats=[1, 3])); return spec, PER + 1 / 30
    if name == "fade":
        spec["fx"].insert(0, dict(ev, beat=2.5, beats=2)); return spec, 1.6
    if name == "safezones":
        spec["fx"].insert(0, ev); return spec, 1.0
    if k == "text":
        e = dict(ev, beat=0.5, beats=4.5) if name != "wordmark" else dict(ev, beat=0.3)
        if name == "kinetic":
            e["text"] = "DEIN TEXT HIER"
        spec["fx"].insert(0, e); return spec, 1.5 if name != "kinetic" else 1.3
    spec["fx"].insert(0, dict(ev, beat=0.5, beats=4)); return spec, 1.0


def main():
    global FULL
    src = Path(sys.argv[1]); FULL = src.resolve(); out = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "galerie"
    only = sys.argv[3:]
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="vfxgal_"))
    a, b = tmp / "exA.mp4", tmp / "exB.mp4"
    for dst, ss in ((a, 10.8), (b, 0.857)):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", "2.4", "-i", str(src), "-an", "-c:v", "libx264",
                        "-crf", "10", "-preset", "fast", "-pix_fmt", "yuv420p", str(dst)], check=True)
    names = [n for g in rv.GROUPS for n, m in rv.FX.items() if m["group"] == g and not n.startswith("_")]
    if only:
        names = [n for n in names if n in only]
    thumbs = []
    for i, n in enumerate(names):
        spec, ts = demo_spec(n, str(a), str(b))
        dst = out / f"{i + 1:02d}_{n}.mp4"
        rv.render(spec, dst, tmp, crf=23, quiet=True)
        eng = rv.Engine(spec, tmp)
        thumbs.append((n, rv.FX[n]["group"], eng.render_frame(int(round(ts * 30)))))
        print(f"{i + 1:02d} {n}", flush=True)
    sheet(thumbs, out / "galerie_uebersicht.jpg")
    lst = out / "liste.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in sorted(out.glob("[0-9][0-9]_*.mp4"))))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", "scale=540:960:flags=lanczos",
                    "-c:v", "libx264", "-crf", "27", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(out / "vfx_galerie_alle.mp4")], check=True)
    lst.unlink()


def sheet(thumbs, path, cols=6):
    from PIL import Image, ImageDraw, ImageFont
    tw, th, lab = 240, 427, 62
    rows = (len(thumbs) + cols - 1) // cols
    im = Image.new("RGB", (cols * tw + (cols + 1) * 12, rows * (th + lab) + (rows + 1) * 12 + 90), (18, 18, 18))
    d = ImageDraw.Draw(im)
    f1 = ImageFont.truetype(str(rv.FONT_DIR / "Montserrat-Bold.ttf"), 22)
    f2 = ImageFont.truetype(str(rv.FONT_DIR / "Montserrat-Medium.ttf"), 16)
    f0 = ImageFont.truetype(str(rv.FONT_DIR / "Montserrat-ExtraBold.ttf"), 40)
    d.text((12, 22), f"{rv.MARKE} VFX-Bibliothek · {len(thumbs)} Effekte", font=f0, fill=(240, 240, 240))
    for k, (n, g, fr) in enumerate(thumbs):
        r, c = divmod(k, cols); x = 12 + c * (tw + 12); y = 90 + 12 + r * (th + lab + 12)
        t = Image.fromarray(np.ascontiguousarray(fr[..., ::-1])).resize((tw, th), Image.LANCZOS)
        im.paste(t, (x, y))
        d.text((x, y + th + 6), n, font=f1, fill=(255, 255, 255))
        d.text((x, y + th + 34), g, font=f2, fill=(170, 170, 170))
    im.save(path, quality=88)


if __name__ == "__main__":
    main()
