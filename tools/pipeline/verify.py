#!/usr/bin/env python3
"""Fertiges Reel gegen die EDL prüfen (vor der Abgabe; Projektanweisungen Punkt 17).

    python3 verify.py <reel>_mit_song.mp4 [song-ausschnitt.wav]

Prüft: Format (1080×1920, 30 fps, Frame-Zahl = EDL), jeder Soll-Schnitt ist ein sauberes Maximum der
Bilddifferenz genau auf seinem Frame (Jump Cuts im selben Clip mit kleinerer Schwelle, Überblendungen nicht),
schwarze und eingefrorene Frames (Zeitlupe aus 30 fps fällt hier auf), 808-Einsätze im Ton gegen die Hits der EDL
(Feld "hits", Beats; im Einstieg im Video ist der Song gedämpft, im Ausklang aus, dort nicht), kein 808-Einsatz in
den letzten 150 ms des Songs, Ton- gleich Bildlänge, Lautheit und True Peak (mit Referenz: Pegelabweichung zum Song in
100-ms-Blöcken; mit O-Ton und Einstieg weicht der Pegel dort gewollt ab).
Ergebnis: Zeilen mit OK / PRÜFEN, Exit-Code 1 bei PRÜFEN.
"""
import json
import subprocess
import sys

import numpy as np
import scipy.signal as ss
from scipy.ndimage import uniform_filter1d

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
from reelcfg import FPS, H, W, load_edl, run, total_beats

PROBLEMS = []


def say(ok, msg):
    print(("OK      " if ok else "PRÜFEN  ") + msg)
    if not ok:
        PROBLEMS.append(msg)


def gray_frames(path, w=270, h=480):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def onsets_808(x, sr=48000):
    """Einsätze unter 120 Hz (Sekunden), Auflösung 1 ms."""
    lo = ss.sosfiltfilt(ss.butter(4, 120, btype="lowpass", fs=sr, output="sos"), x)
    e = np.sqrt(uniform_filter1d(lo ** 2, int(0.010 * sr)))[::int(0.001 * sr)]
    de = np.convolve(np.maximum(0, np.diff(np.log(e + 1e-4), prepend=0)), np.ones(9), mode="same")
    pk, _ = ss.find_peaks(de, height=0.35, distance=90)
    return pk / 1000.0


def main(video, ref=None):
    import reel_audio as ra
    E = load_edl()
    per, shots = E["per"], E["shots"]
    N = round(total_beats(E) * per * FPS)
    pr = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", video]).stdout)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    num, den = map(int, v["avg_frame_rate"].split("/"))
    say((v["width"], v["height"]) == (W, H) and abs(num / den - FPS) < 0.01,
        f"Format {v['width']}×{v['height']} @ {num / den:.2f} fps, {v['codec_name']}")
    fr = gray_frames(video)
    n = len(fr)
    say(n == N, f"Frames {n} (EDL: {N})")
    diff = np.array([0] + [np.abs(fr[i] - fr[i - 1]).mean() for i in range(1, n)])
    # Fortsetzungen (cont, z. B. Split öffnet ins Vollbild) sind absichtlich kein sichtbarer Schnitt, Überblendungen
    # auch nicht; ein Jump Cut im selben Clip ändert oft nur die Pose, daher kleinere Schwelle
    cuts = [(s["n"], round(s["t"] * FPS), 1.2 if s.get("jump") and s["clip"] == shots[i]["clip"] else 1.8)
            for i, s in enumerate(shots[1:]) if not s.get("cont") and s.get("ueber") != "blende"]
    blenden = sum(s.get("ueber") == "blende" for s in shots[1:])
    bad = []
    for k, c, lim in cuts:
        if c >= n:
            bad.append((k, c, "hinter dem Ende"))
            continue
        lo = max(1, c - 2)
        pk = lo + int(np.argmax(diff[lo:c + 3]))
        ratio = diff[c] / (np.median(diff[max(1, c - 6):c - 1]) + 1e-3)
        if pk != c or ratio < lim:
            bad.append((k, c, f"Max bei {pk}, Faktor {ratio:.1f}"))
    say(not bad, f"Schnitte {len(cuts) - len(bad)}/{len(cuts)} sauber auf dem Frame" + (f": {bad}" if bad else "")
        + (f" ({blenden} Überblendung(en) nicht als Schnitt geprüft)" if blenden else ""))
    mean = fr.mean(axis=(1, 2))
    say(int((mean < 8).sum()) == 0, f"schwarze Frames: {int((mean < 8).sum())} (dunkelster Mittelwert {mean.min():.1f})")
    held = set()
    for s in shots:
        if s["mode"] == "freeze":
            held.update(range(round((s["t"] + s["freeze_at"] * per) * FPS) + 1, round((s["t"] + s["beats"] * per) * FPS)))
    frozen = [i for i in range(1, n) if diff[i] < 0.05 and i not in held]
    where = sorted({next(s["n"] for s in reversed(shots) if round(s["t"] * FPS) <= i) for i in frozen})
    say(not frozen, f"eingefrorene Frames außerhalb von Freeze-Shots: {len(frozen)}" + (f" in Shot {where}" if frozen else ""))
    if not any(s["codec_type"] == "audio" for s in pr["streams"]):
        print("        (kein Ton, Tonprüfung übersprungen)")
        return
    x = ra.decode(video).mean(1)
    dur_a = len(x) / ra.SR
    say(abs(dur_a - n / FPS) < 1 / FPS, f"Tonlänge {dur_a:.3f} s, Bildlänge {n / FPS:.3f} s")
    on = onsets_808(x)
    ein, aus = E.get("einstieg", 0), E.get("ausklang", 0)
    song_end = (total_beats(E) - aus) * per
    worst, missing = 0.0, []
    for hb in [h for h in E.get("hits", []) if ein <= h < total_beats(E) - aus]:
        t_exp = round(hb * per * FPS) / FPS
        near = on[np.abs(on - hb * per) < 0.12]
        if len(near):
            worst = max(worst, abs(near[np.argmin(np.abs(near - hb * per))] - t_exp) * FPS)
        else:
            missing.append(hb)
    if E.get("hits"):
        say(worst <= 1.0 and not missing, f"808 gegen Bild: max. {worst:.2f} Frames Versatz"
            + (f", ohne Einsatz: Beats {missing}" if missing else ""))
    tail = on[(on > song_end - 0.150) & (on < song_end)]
    wo = "vor dem Song-Ende (danach Ausklang)" if aus else "vor dem Ende"
    say(len(tail) == 0, f"kein 808-Einsatz in den letzten 150 ms {wo}" if len(tail) == 0
        else f"808-Einsatz {song_end - tail[0]:.3f} s {wo} (Ton endet mitten im Refrain?)")
    ra.check(video, ref)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:3])
    print("Ergebnis:", "alles OK" if not PROBLEMS else f"{len(PROBLEMS)} Punkt(e) prüfen")
    sys.exit(1 if PROBLEMS else 0)
