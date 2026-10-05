#!/usr/bin/env python3
"""Vorschau-Video zur Freigabe: das echte Reel (Schnitte, Tempo, Effekte, Look) klein, mit Song und Info-Leiste.

    python3 vorschau.py <master.mp4> <reel>/<name>_vorschau.mp4 [mix.wav] [--loop 8] [--breite 720]

Liest die EDL ($REEL_EDL). Oben das Reel unverändert in 720×1280, darunter eine Leiste (240 px) mit Zeitleiste
(Shots in Kapitelfarben, 808-Hits, Abspielkopf), Shot-Nummer wie im Storyboard, Kapitel, Clip, Beats, Tempo, Zeit,
Takt mit 4 Schlag-Punkten (808-Schläge grün), Variante (EDL-Felder variante, variante_name) und den Effekt-Tags. Tags mit Zeitpunkt (Punch, Mini-Punch, Flash,
Shake, Ramp-Hit, Freeze) leuchten genau dann auf, wenn der Effekt kommt. Danach läuft der Anfang noch einmal
(--loop Beats, Standard 8 = 2 Takte, 0 = aus), so wie Instagram das Reel wiederholt: so sieht man, ob der Loop sitzt.
Ausgabe fürs Handy: H.264 yuv420p bt709 (~3 Mbit/s), AAC 160k, faststart, ~10 MB. Master: tools/pipeline/render.py.
"""
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
from reelcfg import FPS, load_edl, load_fx, total_beats
from storyboard import GREY, MODE, PALETTE, TAGC, font, tc

BG, FG, MUTED, NEON = (14, 14, 14), (240, 240, 240), (150, 150, 150), (205, 255, 60)
BAR = 240
GLOW = 0.35   # s, so lange leuchtet ein Tag nach seinem Effekt-Zeitpunkt


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def events(sh):
    """Tag -> Zeitpunkte (Beats ab Shot-Start), an denen der Effekt einsetzt; Tags ohne Zeitpunkt fehlen."""
    fx = sh.get("fxp") or {}
    punches = [p for p in fx.get("punch", [])] + [[b, a] for b, a in fx.get("split_punch", [])]
    big = [p[0] for p in punches if len(p) < 3 or p[2]]
    mini = [p[0] for p in punches if len(p) > 2 and not p[2]]
    ev = {"Punch-in": big, "Punch ½": big, "Mini-Punch": mini, "Flash": [f[0] for f in fx.get("flash", [])],
          "Shake": [s[0] for s in fx.get("shake", [])]}
    if sh["mode"] in ("ramp", "ramp_hold"):
        ev["Speed-Ramp"] = [2.0]
    if sh["mode"] == "freeze":
        ev["Freeze-Frame"] = [sh["freeze_at"]]
    if sh.get("jump"):
        ev["Jump Cut"] = [0.0]
    if sh.get("ueber") == "blende":
        ev["Blende"] = [0.0]
    return {k: v for k, v in ev.items() if v}


def dim(c, f):
    return tuple(int(v * f) for v in c)


class Leiste:
    """Zeichnet die Info-Leiste; der statische Teil wird pro Shot einmal gebaut."""

    def __init__(self, E, w, fxp):
        self.E, self.w, self.per = E, w, E["per"]
        self.shots, self.beats = E["shots"], total_beats(E)
        for sh in self.shots:
            sh["fxp"] = fxp.get(str(sh["n"]), sh.get("fxp", {}))   # dieselben Parameter wie render.py
        self.cut = [round(s["t"] * FPS) for s in self.shots]      # Schnitt-Frames wie render.py
        secc = dict(E.get("kapitel_farben", {}))
        for sh in self.shots:
            if sh["sec"] not in secc:
                secc[sh["sec"]] = PALETTE[len(secc) % len(PALETTE)]
        self.secc = {k: tuple(v) for k, v in secc.items()}
        self.hits = set(E.get("hits", []))
        v = E.get("variante")
        self.variante = f"{v} · {E['variante_name']}" if v and E.get("variante_name") else (v or "")
        self.x0, self.x1 = 16, w - 16
        self.cache = {}

    def bx(self, b):
        return self.x0 + (self.x1 - self.x0) * b / self.beats

    def static(self, k):
        if k in self.cache:
            return self.cache[k]
        sh, w = self.shots[k], self.w
        img = Image.new("RGB", (w, BAR), BG)
        d = ImageDraw.Draw(img)
        for j, o in enumerate(self.shots):                       # Zeitleiste: Shots, aktueller hell mit Rahmen
            a, b = self.bx(o["beat"]), self.bx(o["beat"] + o["beats"])
            c = dim(self.secc[o["sec"]], (1.0 if o["n"] % 2 else 0.8) * (1.0 if j == k else 0.42))
            d.rectangle([a + 1, 15, b - 1, 41], fill=c)
            if b - a > 20:
                d.text(((a + b) / 2, 28), str(o["n"]), font=font("Bold", 12),
                       fill=(20, 20, 20) if j == k else (10, 10, 10), anchor="mm")
        a, b = self.bx(sh["beat"]), self.bx(sh["beat"] + sh["beats"])
        d.rectangle([a, 14, b, 42], outline=FG, width=2)
        for hb in self.hits:                                     # 808-Hits als Dreiecke über der Zeitleiste
            x = self.bx(hb)
            d.polygon([(x - 4, 3), (x + 4, 3), (x, 10)], fill=MUTED)
        col = self.secc[sh["sec"]]
        d.text((16, 56), f"#{sh['n']}", font=font("ExtraBold", 44), fill=FG)
        nx = 16 + d.textlength(f"#{sh['n']}", font=font("ExtraBold", 44)) + 14
        d.text((nx, 58), sh["sec"], font=font("ExtraBold", 24), fill=col)
        clip = f"{len(sh['strips'])} Clips" if sh["clip"] == "split" else f"Clip {sh['clip']}"
        mode = MODE.get(sh["mode"], f" · {sh.get('speed')}×" if sh["mode"] == "speed" else "").replace(".", ",")
        d.text((nx, 88), f"{clip} · {sh['beats']:g} Beats{mode}", font=font("SemiBold", 17), fill=MUTED)
        for li, ln in enumerate(textwrap.wrap(sh.get("desc", ""), 40)[:2]):
            d.text((16, 120 + li * 26), ln, font=font("Medium", 21), fill=FG)
        self.cache[k] = img
        return img

    def frame(self, i, n_reel):
        loop = i >= n_reel
        t = (i - n_reel if loop else i) / FPS
        b = t / self.per
        k = max(j for j, c in enumerate(self.cut) if c <= (i - n_reel if loop else i))
        sh = self.shots[k]
        img = self.static(k).copy()
        d = ImageDraw.Draw(img)
        x = self.bx(b)                                           # Abspielkopf
        d.line([x, 14, x, 42], fill=(255, 255, 255), width=2)
        d.polygon([(x - 6, 51), (x + 6, 51), (x, 44)], fill=(255, 255, 255))
        d.text((self.w - 16, 56), tc(t), font=font("Bold", 32), fill=FG, anchor="ra")
        beat = int(b + 1e-6)
        d.text((self.w - 16, 100), f"Takt {beat // 4 + 1}", font=font("SemiBold", 17), fill=MUTED, anchor="ra")
        for s_ in range(4):                                      # Schlag-Punkte, 808-Schläge grün
            bb = beat - beat % 4 + s_
            cx, cy = self.w - 16 - 8 - (3 - s_) * 24, 138
            on = bb == beat
            c = NEON if bb in self.hits else FG
            r = 8 if on else 5
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c if on else dim(c, 0.35))
        rx = self.w - 16                                         # rechts: Variante, im Loop davor "LOOP"
        for txt, fill, fg in ([(self.variante, None, FG)] if self.variante else []) + \
                ([("LOOP", NEON, (15, 15, 15))] if loop else []):
            wd = d.textlength(txt, font=font("ExtraBold", 17)) + 20
            d.rounded_rectangle([rx - wd, 160, rx, 188], 8, fill=fill, outline=None if fill else FG, width=2)
            d.text((rx - wd / 2, 174), txt, font=font("ExtraBold", 17), fill=fg, anchor="mm")
            rx -= wd + 8
        ev = events(sh)
        u = t - sh["t"]
        px, py = 16, 202
        for tg in sh.get("fx", []):
            ft = font("Bold", 16)
            wd = d.textlength(tg, font=ft) + 16
            if px + wd > self.w - 16:
                break
            c = TAGC.get(tg, GREY)
            if tg in ev:                                         # Effekt-Marker: leuchtet ab dem Einsatz auf
                since = [u - e * self.per for e in ev[tg] if u >= e * self.per - 0.5 / FPS]
                glow = max([np.exp(-max(s_, 0) / GLOW) for s_ in since], default=0.0)
                c = dim(c, 0.35 + 0.65 * glow)
                if glow > 0.3:
                    d.rounded_rectangle([px - 3, py - 3, px + wd + 3, py + 29], 14, outline=FG, width=2)
            d.rounded_rectangle([px, py, px + wd, py + 26], 12, fill=c)
            d.text((px + 8, py + 4), tg, font=ft, fill=(15, 15, 15))
            px += wd + 9
        if not sh.get("fx"):
            d.text((px, py + 4), "ohne Effekt", font=font("Medium", 16), fill=MUTED)
        return img


def main(master, out, mix=None):
    E = load_edl()
    fxp = load_fx(E)
    w = arg("--breite", 720)
    w -= w % 2
    vh = round(w * 16 / 9) // 2 * 2
    per = E["per"]
    n_reel = round(total_beats(E) * per * FPS)
    n_loop = min(n_reel, round(arg("--loop", 8.0) * per * FPS))
    leiste = Leiste(E, w, fxp)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        audio = []
        if mix:
            import reel_audio as ra
            import soundfile as sf
            x = ra.decode(str(mix))
            n_a = round(n_reel / FPS * ra.SR)
            x = np.concatenate([x[:n_a], x[:round(n_loop / FPS * ra.SR)]]) if n_loop else x[:n_a]
            f = min(len(x), round(0.03 * ra.SR))
            x[-f:] *= np.linspace(1, 0, f)[:, None]              # Loop-Ende weich ausblenden
            sf.write(f"{tmp}/ton.wav", x, ra.SR)
            audio = ["-i", f"{tmp}/ton.wav"]
        inputs = ["-i", str(master)] + (["-t", f"{n_loop / FPS:.4f}", "-i", str(master)] if n_loop else [])
        vid = "[0:v][1:v]concat=n=2:v=1:a=0," if n_loop else "[0:v]"
        bar_in = 2 if n_loop else 1
        graph = (f"{vid}scale={w}:{vh}:flags=area,format=yuv444p[v];"
                 f"[{bar_in}:v]scale=out_color_matrix=bt709:out_range=tv,format=yuv444p[bar];"
                 "[v][bar]vstack=inputs=2,format=yuv420p[out]")
        cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{BAR}",
               "-r", str(FPS), "-i", "-", *audio, "-filter_complex", graph, "-map", "[out]",
               *(["-map", f"{bar_in + 1}:a", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"] if audio else []),
               "-c:v", "libx264", "-preset", "medium", "-crf", "27", "-maxrate", "3M", "-bufsize", "6M",
               "-r", str(FPS), "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
               "-movflags", "+faststart", "-shortest", str(out)]
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(n_reel + n_loop):
            ff.stdin.write(leiste.frame(i, n_reel).tobytes())
        ff.stdin.close()
        assert ff.wait() == 0, "ffmpeg fehlgeschlagen"
    mb = out.stat().st_size / 1e6
    print(f"{out} ({w}×{vh + BAR}, {(n_reel + n_loop) / FPS:.1f} s davon Loop {n_loop / FPS:.1f} s, {mb:.1f} MB)")


if __name__ == "__main__":
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    for name in ("--loop", "--breite"):
        if name in sys.argv:
            pos.remove(sys.argv[sys.argv.index(name) + 1])
    if len(pos) < 2:
        sys.exit(__doc__)
    main(pos[0], pos[1], next((p for p in pos[2:] if p.endswith(".wav")), None))
