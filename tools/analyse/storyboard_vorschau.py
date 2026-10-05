#!/usr/bin/env python3
"""Schnelles Vorschau-Storyboard aus shotliste.json: ein Bild pro Shot am Hit-Moment, direkt aus
den Clips auf der Platte (kein Frame-Export nötig). Zum Durchsehen der Auswahl vor dem echten
Storyboard der Pipeline (tools/pipeline/storyboard.py).

    python3 storyboard_vorschau.py OUT/shotliste/shotliste.json --clips /home/user/reel/clips -o vorschau.jpg
    python3 storyboard_vorschau.py shotliste.json --clips DIR1 DIR2 --song song.json -o vorschau.jpg

1080 px breit, 4 Spalten, ein Abschnitt pro Kapitel, oben Zeitleiste mit Shots und 808-Markern.
Clips ohne Datei bekommen eine graue Kachel. HLG/PQ wird getonemappt.
"""
import argparse
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, COLS, GAP = 1080, 4, 8
TW = (W - GAP * (COLS + 1)) // COLS
TH = TW * 16 // 9
TXT = 74
KAP_FARBE = {1: (228, 87, 46), 2: (243, 167, 18), 3: (76, 159, 112), 4: (29, 112, 184)}
TONEMAP = ("zscale=tin={tin}:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=100,format=gbrpf32le,"
           "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")


def font(size, bold=False):
    for f in (f"/usr/share/fonts/truetype/montserrat/Montserrat-{'Bold' if bold else 'Medium'}.ttf",
              f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def fit(d, text, f, width):
    """Text auf Kachelbreite kürzen."""
    while text and d.textlength(text, font=f) > width - 4:
        text = text[:-2].rstrip(", ") + "…" if len(text) > 2 else ""
    return text


def find_clip(clip, dirs):
    for d in dirs:
        for pat in (f"IMG_{clip}.*", f"{clip}.*", f"*{clip}*.*"):
            hits = sorted(p for p in Path(d).glob(pat) if p.suffix.lower() in (".mov", ".mp4", ".m4v"))
            if hits:
                return hits[0]
    return None


def grab(path, t, out):
    trc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    tm = TONEMAP.format(tin=trc) if trc in ("arib-std-b67", "smpte2084") else ""
    vf = f"scale={TW * 2}:-2,{tm}scale={TW}:{TH}:force_original_aspect_ratio=increase,crop={TW}:{TH}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t):.3f}", "-i", str(path), "-frames:v", "1",
                    "-vf", vf, "-q:v", "3", str(out)], capture_output=True)
    return out if Path(out).exists() else None


def render(E, dirs, out, song=None):
    shots = E["shots"]
    per = E["per"]
    tmp = Path(tempfile.mkdtemp(prefix="sbv_"))

    def job(s):
        if not s.get("clip"):
            return None
        p = find_clip(s["clip"], dirs)
        if not p:
            return None
        t = s["peak"] if s.get("peak") is not None else (s["src"] or 0) + 0.4 * s["beats"] * per
        return grab(p, t, tmp / f"{s['n']:03d}.jpg")
    with ThreadPoolExecutor(4) as ex:
        frames = list(ex.map(job, shots))
    # Layout: Kapitel beginnen in einer neuen Zeile
    rows, cur, kap_of_row = [], [], []
    for s, f in zip(shots, frames):
        if cur and (len(cur) == COLS or s["kapitel"] != cur[-1][0]["kapitel"]):
            rows.append(cur)
            cur = []
        cur.append((s, f))
    rows.append(cur)
    head_h, kap_h, row_h = 150, 34, TH + TXT + GAP
    n_kap = len({s["kapitel"] for s in shots})
    H = head_h + n_kap * kap_h + len(rows) * row_h + GAP
    img = Image.new("RGB", (W, H), (18, 18, 18))
    d = ImageDraw.Draw(img)
    f_t, f_b, f_s, f_k = font(30, True), font(15, True), font(13), font(19, True)
    d.text((GAP * 2, 10), "Vorschau-Storyboard", font=f_t, fill=(255, 255, 255))
    d.text((GAP * 2, 48), f"{len(shots)} Shots · {E['dauer']:.2f} s · {E['bpm']:.1f} BPM · Song ab {E['song_start']:.3f} s"
           f" · {E['takte']} Takte{' + Auftakt' if E.get('auftakt') else ''}", font=f_s, fill=(200, 200, 200))
    # Zeitleiste
    x0, x1, y0 = GAP * 2, W - GAP * 2, 80
    sx = (x1 - x0) / E["dauer"]
    for s in shots:
        a, b = x0 + s["t"] * sx, x0 + (s["t"] + s["beats"] * per) * sx
        d.rectangle([a, y0, b - 1, y0 + 30], fill=KAP_FARBE.get(s["kapitel"], (120, 120, 120)))
        d.text((a + 2, y0 + 8), str(s["n"]), font=f_s, fill=(0, 0, 0))
        if s["mode"].startswith("ramp"):
            h = x0 + (s["t"] + 2 * per) * sx
            d.line([h, y0 - 4, h, y0 + 34], fill=(255, 255, 255), width=2)
    if song:
        for o in song["onsets"]["kick808"]:
            t = o["t"] - E["song_start"]
            if 0 <= t <= E["dauer"]:
                d.polygon([(x0 + t * sx - 4, y0 + 36), (x0 + t * sx + 4, y0 + 36), (x0 + t * sx, y0 + 44)],
                          fill=(214, 40, 40) if o["art"] == "808" else (247, 127, 0))
    d.text((x0, y0 + 48), "Farben = Kapitel · weiße Linie = Ramp-Hit · Dreiecke = 808 (rot) / Nachschlag (orange)",
           font=f_s, fill=(170, 170, 170))
    y = head_h
    last_kap = None
    for row in rows:
        k = row[0][0]["kapitel"]
        if k != last_kap:
            d.rectangle([GAP, y + 4, W - GAP, y + kap_h - 4], fill=KAP_FARBE.get(k, (90, 90, 90)))
            d.text((GAP * 2, y + 7), f"Kapitel {k} · {row[0][0].get('kapitel_name', '')}", font=f_k, fill=(0, 0, 0))
            y += kap_h
            last_kap = k
        for c, (s, f) in enumerate(row):
            x = GAP + c * (TW + GAP)
            if f:
                img.paste(Image.open(f).convert("RGB"), (x, y))
            else:
                d.rectangle([x, y, x + TW, y + TH], fill=(60, 60, 60))
                d.text((x + 10, y + TH // 2), "kein Bild", font=f_b, fill=(220, 220, 220))
            d.rectangle([x, y, x + 44, y + 22], fill=(0, 0, 0))
            d.text((x + 4, y + 3), f"#{s['n']}", font=f_b, fill=(255, 255, 255))
            ty = y + TH + 4
            d.text((x, ty), f"{s['t']:.2f}s  {s['takt']}  {s['beats']}B  {s['mode']}", font=f_b, fill=(255, 255, 255))
            d.text((x, ty + 19), (f"IMG_{s['clip']} @ {s['src']:.2f} s" if s.get("src") is not None else f"IMG_{s['clip']}, In-Punkt offen")
                   if s.get("clip") else "Clip fehlt", font=f_s,
                   fill=(200, 200, 200))
            fx = ", ".join(s["fx"])
            d.text((x, ty + 36), fit(d, fx, f_s, TW), font=f_s, fill=(255, 196, 120))
            d.text((x, ty + 53), fit(d, s.get("desc") or "", f_s, TW), font=f_s, fill=(170, 170, 170))
        y += row_h
    img.save(out, quality=88)
    subprocess.run(["rm", "-rf", str(tmp)])
    return out, sum(f is not None for f in frames)


def main():
    ap = argparse.ArgumentParser(description="Vorschau-Storyboard aus shotliste.json")
    ap.add_argument("shotliste")
    ap.add_argument("--clips", nargs="+", required=True, help="Ordner mit den Clips (IMG_xxxx.MOV)")
    ap.add_argument("--song", help="song.json für die 808-Marker")
    ap.add_argument("-o", "--out", default="vorschau_storyboard.jpg")
    a = ap.parse_args()
    E = json.loads(Path(a.shotliste).read_text())
    song = json.loads(Path(a.song).read_text()) if a.song else None
    out, n = render(E, a.clips, a.out, song)
    print(f"{n}/{len(E['shots'])} Shots mit Bild -> {out}")


if __name__ == "__main__":
    main()
