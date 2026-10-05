#!/usr/bin/env python3
"""Storyboard als JPG (1080 px breit, 4 Spalten, Abschnitte = Kapitel) für den Pflicht-Stopp, zusammen mit vorschau.py.

    python3 storyboard.py <reel>/<name>_storyboard.jpg            # Kacheln aus den Keyframes der Sichtung
    python3 storyboard.py <reel>/<name>_storyboard.jpg --render      # Kacheln = echte Render-Frames (Shot-Mitte), Standard

Liest die EDL ($REEL_EDL). Optionale EDL-Felder für den Kopf: titel, untertitel, song, hinweis (1 Zeile),
hits (Beats der 808-Hits für die Zeitleiste). Pro Shot: n, t, beat, beats, sec (Kapitel), clip, desc,
fx (Tags), mode, prev (Quellzeit der Vorschau), clock (Aufnahmezeit, optional).
"""
import json
import sys
import textwrap

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
from reelcfg import WORK, grade_rgb, load_edl, look_spec, meta, stem_of, total_beats

MF = "/usr/share/fonts/truetype/montserrat/Montserrat-"
BG, FG, MUTED = (14, 14, 14), (240, 240, 240), (150, 150, 150)
NEON, CYAN, ORANGE, PINK, GREY = (205, 255, 60), (80, 210, 255), (255, 150, 60), (255, 110, 190), (190, 190, 190)
GOLD = (255, 214, 90)
TAGC = {"Punch-in": NEON, "Punch ½": NEON, "Mini-Punch": NEON, "Push-in": NEON, "Zoom-out": NEON, "Whip-Zoom": NEON,
        "Speed-Ramp": CYAN, "Zeitlupe": CYAN, "Freeze-Frame": CYAN, "Jump Cut": CYAN,
        "Flash": ORANGE, "Shake": ORANGE, "Split-Screen": ORANGE, "Echo-Trail": ORANGE, "Glitch": ORANGE, "Blende": ORANGE,
        "Whoosh": PINK, "Shutter": PINK, "SFX": PINK, "O-Ton": GOLD, "O-Ton vorn": GOLD}
PALETTE = [(255, 209, 102), (120, 220, 160), (255, 120, 90), (150, 170, 255), (80, 210, 255), (255, 110, 190)]
MODE = {"ramp": " · Ramp", "ramp_hold": " · Ramp", "slow": " · 0,5×", "fast": " · 1,5×", "freeze": " · Freeze"}


def font(w, s):
    return ImageFont.truetype(MF + w + ".ttf", s)


def tc(t):
    return f"{int(t // 60)}:{t % 60:04.1f}".replace(".", ",")


def kf(clip, t):
    """Keyframe der Sichtung, der t am nächsten liegt (RGB float)."""
    m = meta(clip)
    stems = [p.name for p in (WORK / "kf").iterdir()]
    ks = sorted((WORK / "kf" / stem_of(clip, stems)).glob("k_*.jpg"))
    i = int(np.argmin([abs(x - t) for x in m["kf_times"][:len(ks)]]))
    return cv2.cvtColor(cv2.imread(str(ks[i])), cv2.COLOR_BGR2RGB).astype(np.float32) / 255


def look(rgb):
    Y = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    return grade_rgb(np.clip(rgb * np.clip(0.44 / max(np.median(Y), 1e-3), 0.8, 1.35) ** 0.6, 0, 1))


def fit916(rgb, w, h):
    sh, sw = rgb.shape[:2]
    s = max(w / sw, h / sh)
    r = cv2.resize(rgb, (round(sw * s), round(sh * s)), interpolation=cv2.INTER_AREA)
    y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
    return r[y0:y0 + h, x0:x0 + w]


def tile_kf(sh, w, h):
    if sh["clip"] != "split":
        return look(fit916(kf(sh["clip"], sh["prev"]), w, h))
    parts, hs = [], [h // 3, h // 3, h - 2 * (h // 3)]
    for st, hh in zip(sh["strips"], hs):
        im = fit916(kf(st["clip"], st.get("prev", st["src"])), w, h)
        z = st.get("zoom", 1.0)
        big = cv2.resize(im, (round(w * z), round(h * z)), interpolation=cv2.INTER_CUBIC)
        cy, x0 = int(st.get("y", 0.5) * big.shape[0]), (big.shape[1] - w) // 2
        y0 = int(np.clip(cy - hh // 2, 0, big.shape[0] - hh))
        parts.append(look(big[y0:y0 + hh, x0:x0 + w]))
    out = np.vstack(parts)
    out[h // 3 - 1:h // 3 + 1] = 0
    out[2 * (h // 3) - 1:2 * (h // 3) + 1] = 0
    return out


def tile_render(k, w, h):
    import render
    i = (render.CUT[k] + render.CUT[k + 1]) // 2
    rgb = cv2.cvtColor(render.render_frame(i), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    return cv2.resize(grade_rgb(rgb), (w, h), interpolation=cv2.INTER_AREA)


def main(out, use_render=False):
    E = load_edl()
    per, shots, beats = E["per"], E["shots"], total_beats(E)
    if use_render:
        import render
        render.init(E)
    W, COLS, GAP = 1080, 4, 10
    TW = (W - GAP * (COLS + 1)) // COLS
    TH, TXT = round(TW * 16 / 9), 138
    secs = []
    for sh in shots:
        if not secs or secs[-1][0] != sh["sec"]:
            secs.append((sh["sec"], []))
        secs[-1][1].append(sh)
    secc = dict(E.get("kapitel_farben", {}))
    for i, (sec, _) in enumerate(secs):
        secc.setdefault(sec, PALETTE[i % len(PALETTE)])
    hint = E.get("hinweis")
    HEAD = 330 + (42 if hint else 0)
    height = HEAD + sum(46 + ((len(v) + COLS - 1) // COLS) * (TH + TXT + GAP) for _, v in secs) + 70
    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img)
    d.text((24, 22), E.get("titel", "REEL").upper(), font=font("Black", 54), fill=FG)
    d.text((24, 86), E.get("untertitel", "Storyboard zur Freigabe"), font=font("SemiBold", 24), fill=NEON)
    info = [E.get("song", ""), f"{60 / per:.0f} BPM", f"{beats / 4:g} Takte", f"{beats * per:.1f} s".replace(".", ","),
            f"{len(shots)} Shots"]
    d.text((24, 122), " · ".join(x for x in info if x), font=font("Medium", 20), fill=MUTED)
    if hint:
        d.text((24, 152), hint, font=font("SemiBold", 17), fill=FG)
    ty, th_ = 170 + (42 if hint else 0), 54
    x0, x1 = 24, W - 24

    def bx(b):
        return x0 + (x1 - x0) * b / beats

    for sh in shots:
        c = secc[sh["sec"]]
        a, b2 = bx(sh["beat"]), bx(sh["beat"] + sh["beats"])
        shade = 1.0 if sh["n"] % 2 else 0.72
        d.rectangle([a + 1, ty, b2 - 1, ty + th_], fill=tuple(int(v * shade) for v in c))
        if b2 - a > 22:
            d.text(((a + b2) / 2, ty + th_ / 2), str(sh["n"]), font=font("Bold", 15), fill=(20, 20, 20), anchor="mm")
    for b in range(0, int(beats) + 1, 4):
        d.line([bx(b), ty + th_ + 2, bx(b), ty + th_ + 9], fill=MUTED, width=2)
        if b % 16 == 0:
            d.text((bx(b), ty + th_ + 12), tc(b * per), font=font("Medium", 15), fill=MUTED, anchor="ma")
    for hb in E.get("hits", []):
        x = bx(hb)
        d.polygon([(x - 6, ty - 12), (x + 6, ty - 12), (x, ty - 2)], fill=FG)
    lx, ly = 24, ty + 98
    if E.get("hits"):
        d.polygon([(lx, ly + 3), (lx + 18, ly + 3), (lx + 9, ly + 16)], fill=FG)
        d.text((lx + 26, ly - 1), "808-Hit", font=font("Medium", 17), fill=FG)
        lx += 60 + d.textlength("808-Hit", font=font("Medium", 17))
    for lab, c in [("Bewegung/Zoom", NEON), ("Tempo/Schnitt", CYAN), ("Effekt/Übergang", ORANGE), ("Echter Ton", GOLD)]:
        d.rounded_rectangle([lx, ly, lx + 18, ly + 18], 4, fill=c)
        d.text((lx + 26, ly - 1), lab, font=font("Medium", 17), fill=FG)
        lx += 60 + d.textlength(lab, font=font("Medium", 17))
    y = HEAD
    for sec, lst in secs:
        c = secc[sec]
        a, b2 = lst[0]["beat"], lst[-1]["beat"] + lst[-1]["beats"]
        d.rectangle([GAP, y + 8, GAP + 6, y + 36], fill=c)
        d.text((GAP + 16, y + 6), sec, font=font("ExtraBold", 26), fill=c)
        tw = d.textlength(sec, font=font("ExtraBold", 26))
        t0, t1 = int(a // 4 + 1), int(-(-b2 // 4))
        takte = f"Takt {t0}" if t0 == t1 else f"Takt {t0}–{t1}"
        d.text((GAP + 32 + tw, y + 13), f"{takte} · {tc(a * per)}–{tc(b2 * per)}", font=font("Medium", 18), fill=MUTED)
        y += 46
        for i, sh in enumerate(lst):
            k = shots.index(sh)
            cx, cy = GAP + (i % COLS) * (TW + GAP), y + (i // COLS) * (TH + TXT + GAP)
            rgb = tile_render(k, TW, TH) if use_render else tile_kf(sh, TW, TH)
            img.paste(Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)), (cx, cy))
            d.rectangle([cx, cy, cx + TW - 1, cy + TH - 1], outline=(40, 40, 40))
            d.rounded_rectangle([cx + 8, cy + 8, cx + 62, cy + 40], 8, fill=(0, 0, 0))
            d.text((cx + 35, cy + 24), f"#{sh['n']}", font=font("ExtraBold", 20), fill=FG, anchor="mm")
            if sh.get("clock"):
                d.rounded_rectangle([cx + TW - 84, cy + 8, cx + TW - 8, cy + 40], 8, fill=(0, 0, 0))
                d.text((cx + TW - 46, cy + 24), sh["clock"], font=font("Bold", 17), fill=NEON, anchor="mm")
            ty2 = cy + TH + 6
            d.text((cx, ty2), tc(sh["t"]), font=font("Bold", 19), fill=FG)
            clip = f"{len(sh['strips'])} Clips" if sh["clip"] == "split" else sh["clip"]
            mode = MODE.get(sh["mode"], f" · {sh.get('speed')}×" if sh["mode"] == "speed" else "")
            d.text((cx + TW, ty2 + 2), f"{clip} · {sh['beats']:g} B{mode}", font=font("SemiBold", 15), fill=MUTED,
                   anchor="ra")
            for li, ln in enumerate(textwrap.wrap(sh["desc"], 27)[:2]):
                d.text((cx, ty2 + 28 + li * 20), ln, font=font("Medium", 16), fill=FG)
            px, py = cx, ty2 + 72
            for tg in sh.get("fx", []):
                ft = font("Bold", 13)
                w = d.textlength(tg, font=ft) + 14
                if px + w > cx + TW:
                    px, py = cx, py + 26
                d.rounded_rectangle([px, py, px + w, py + 21], 10, fill=TAGC.get(tg, GREY))
                d.text((px + 7, py + 3), tg, font=ft, fill=(15, 15, 15))
                px += w + 5
            if not sh.get("fx"):
                d.text((px, py + 2), "ohne Effekt", font=font("Medium", 13), fill=MUTED)
        y += ((len(lst) + COLS - 1) // COLS) * (TH + TXT + GAP)
    foot = "Bilder = echte Render-Frames" if use_render else "Bilder = Keyframes der Sichtung"
    import stil
    d.text((24, y + 14), f"Look: {stil.look_name(look_spec())} · {foot} · Tags streichen = Effekt fällt raus",
           font=font("Medium", 17), fill=MUTED)
    img = img.crop((0, 0, W, y + 60))
    img.save(out, quality=90)
    print(out, img.size)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], "--render" in sys.argv)
