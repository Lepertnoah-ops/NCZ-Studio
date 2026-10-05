#!/usr/bin/env python3
"""Querformat-Clip auf 9:16 umsetzen (Reels und YouTube Shorts), der Ausschnitt folgt dem Geschehen.

    python3 reframe.py <clip> [--modus tracking|mitte|blur] [-o <ziel.mp4>] [--kontakt <bild.jpg>] [--manifest]
    python3 reframe.py <clip> --analyse          # nur Bahn und Kontaktbogen, kein Video (schnell)

Warum: extract.py skaliert Querformat mit force_original_aspect_ratio=increase und render.py schneidet die Mitte ab,
das sind bei 16:9 nur 32 % der Breite. Was am Rand passiert, fehlt, und die Mitte ist selten das Motiv.
Modi:
  tracking (Standard)  Fenster 9:16 in voller Höhe, das Personen (YOLOX, ../personen.py) und Bewegung folgt: Fenster mit
                       der meisten Person und Bewegung, Kamera bleibt in einer Toleranzzone stehen (15 % der Fensterbreite),
                       schwenkt danach höchstens mit 0,5 Fensterbreiten je Sekunde, dazu geglättet und 0,4 s vorausschauend;
                       Bewegung zählt nicht, wenn sich mehr als 35 % des Bildes ändern (Schwenk, Wackeln). Sub-Pixel-genau.
  mitte                fester Mittenausschnitt (der Weg ohne Tracking, zum Vergleichen)
  blur                 ganzes Bild in voller Breite, darüber und darunter derselbe Clip unscharf und abgedunkelt.
                       Nicht im Stil-Leitfaden, nur auf Wunsch des Nutzers.
Ausgabe: $REEL_WORK/reframe/<stamm>_9x16.mp4 (SDR, bt709, 1080×1920, ab 2000 px Quellhöhe 1440×2560, CRF 14,
AAC-Ton bleibt), HDR wird mit der Kette der Pipeline (tonemap_for) umgewandelt. Danach wie jeder Clip: --manifest trägt
die Datei als „local:“-Clip in $REEL_WORK/manifest.tsv ein, dann ingest.py, im Schnitt die Kürzel <stamm>_9x16.
Kontaktbogen: $REEL_WORK/ansicht/reframe_<stamm>.jpg, 6 Zeitpunkte, links Quelle mit rotem Fenster und grünen
Personen, rechts der Ausschnitt. Vor dem Rendern ansehen.
Qualität: ein 9:16-Fenster aus 1080p-Querformat hat nur 608 px Breite und wird 1,78-fach hochgerechnet, das wirkt weich;
aus 4K sind es 1215 px, das reicht. Die Ausgabe nennt den Faktor und rät bei mehr als 1,3 zu blur oder Ausschuss.
Dauer: Analyse ~0,3 s je Sekunde Clip (Personenerkennung), Rendern etwa in Echtzeit (4K HLG langsamer). Lange Clips im
Hintergrund starten.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter, uniform_filter1d

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
from reelcfg import WORK, run, tonemap_for

AN_FPS, AN_BREITE = 5.0, 960          # Analyse: 5 Bilder/s, 960 px breit
BEWEGUNG_SCHWELLE, KAMERA_ANTEIL = 14, 0.35
GEWICHT_BEWEGUNG = 0.5
TOLERANZ, VMAX, VORAUS, SIGMA = 0.15, 0.5, 0.4, 0.3     # Anteile der Fensterbreite, Fensterbreiten/s, s, s
VERHAELTNIS = 9 / 16


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default


# ---------------------------------------------------------------- Quelle

def sonde(pfad):
    j = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", pfad]).stdout or "{}")
    v = next((s for s in j.get("streams", []) if s["codec_type"] == "video"), None)
    if v is None:
        sys.exit(f"{pfad}: keine Videospur")
    rot = 0
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(sd["rotation"])
    w, h = v["width"], v["height"]
    if abs(rot) in (90, 270):
        w, h = h, w
    try:
        a, b = map(int, v.get("sample_aspect_ratio", "1:1").split(":"))
        sar = a / b if a > 0 and b > 0 else 1.0
    except ValueError:
        sar = 1.0
    if abs(sar - 1) > 0.01:                       # Anzeigebreite bei nicht quadratischen Pixeln
        w = int(round(w * sar / 2)) * 2
    num, den = map(int, v.get("avg_frame_rate", "30/1").split("/"))
    return dict(w=w, h=h, sar=sar, fps=round(num / den if den else 30.0, 3),
                dur=float(v.get("duration") or j["format"]["duration"]), trc=v.get("color_transfer", ""),
                cs=v.get("color_space", ""), ton=any(s["codec_type"] == "audio" for s in j["streams"]))


def dekodierer(pfad, m, vf_ende, breite=None):
    """ffmpeg-Prozess, der BGR-Rohbilder liefert (Drehung wird von ffmpeg angewandt)."""
    vf = ""
    if abs(m["sar"] - 1) > 0.01:
        vf += f"scale=w={m['w']}:h={m['h']},setsar=1,"
    vf += vf_ende
    return subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(pfad), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                            stdout=subprocess.PIPE, bufsize=1 << 24)


def bilder(proc, w, h):
    n = w * h * 3
    while True:
        puf = proc.stdout.read(n)
        if len(puf) < n:
            return
        yield np.frombuffer(puf, np.uint8).reshape(h, w, 3)


# ---------------------------------------------------------------- Analyse

def analysieren(pfad, m, an_kontakt=6):
    """(Zeiten, Fenster-Ziele in Quellpixeln (linke Kante, NaN = kein Anhaltspunkt), Kontakt-Frames, Statistik)."""
    import personen
    aw = min(AN_BREITE, m["w"])
    ah = round(aw * m["h"] / m["w"] / 2) * 2
    cw_an = round(ah * VERHAELTNIS)
    mit_personen = personen.verfuegbar()
    proc = dekodierer(pfad, m, f"fps={AN_FPS},scale={aw}:{ah},format=bgr24")
    zeilen, vorher, pcol, boxen_alt = [], None, np.zeros(aw), []
    n_geschaetzt = max(1, int(m["dur"] * AN_FPS))
    behalten = set(np.linspace(0, n_geschaetzt - 1, an_kontakt).round().astype(int)) if an_kontakt else set()
    speicher, hat_person = {}, []
    for k, bild in enumerate(bilder(proc, aw, ah)):
        g = cv2.GaussianBlur(cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        mcol = np.zeros(aw)
        if vorher is not None:
            d = cv2.absdiff(g, vorher) > BEWEGUNG_SCHWELLE
            if d.mean() < KAMERA_ANTEIL:
                mcol = d.mean(axis=0)
        vorher = g
        if mit_personen and k % 2 == 0:            # Personen ändern sich in 0,2 s kaum: jedes zweite Bild
            boxen_alt = personen.erkennen(bild)
            pcol = np.zeros(aw)
            for x, y, bw, bh, c in boxen_alt:
                pcol[int(x):int(x + bw) + 1] += c * bh / ah
        zeilen.append(GEWICHT_BEWEGUNG * mcol + pcol)
        hat_person.append(len(boxen_alt) > 0)
        if k in behalten:
            speicher[k] = (bild.copy(), list(boxen_alt))
    proc.wait()
    if not zeilen:
        sys.exit(f"{pfad}: keine Bilder gelesen")
    P = np.array(zeilen, np.float32)
    zeit = np.arange(len(P)) / AN_FPS
    Pg = uniform_filter1d(P, size=5, axis=0, mode="nearest")                       # 1 s Gedächtnis
    Pg = uniform_filter1d(Pg, size=max(3, aw // 48), axis=1, mode="nearest")
    C = np.concatenate([np.zeros((len(Pg), 1)), np.cumsum(Pg, axis=1)], axis=1)
    fenster = C[:, cw_an:] - C[:, :-cw_an]
    x0 = fenster.argmax(axis=1).astype(float)
    xs = np.arange(aw)
    ziele = np.full(len(P), np.nan)
    for i in range(len(P)):
        a = int(x0[i])
        wgt = Pg[i, a:a + cw_an]
        if Pg[i].sum() >= 0.5 and wgt.sum() > 1e-6:
            c = (xs[a:a + cw_an] * wgt).sum() / wgt.sum()                     # Mitte des Geschehens im Fenster
            ziele[i] = float(np.clip(c - cw_an / 2, 0, aw - cw_an))
    faktor = m["w"] / aw
    stat = dict(ohne_anhalt=float(np.isnan(ziele).mean()),
                mit_person=float(np.mean(hat_person)) if mit_personen else None, personen_modell=mit_personen)
    kontakt = [(k / AN_FPS, speicher[k][0], speicher[k][1]) for k in sorted(speicher)]
    return zeit, ziele * faktor, kontakt, stat, (aw, ah)


# ---------------------------------------------------------------- Bahn

def bahn(zeit, ziele, fps, n, breite, cw):
    """Fensterposition (linke Kante, Quellpixel) für jedes der n Ausgabebilder."""
    z = ziele.copy()
    if np.isnan(z).all():
        z[:] = (breite - cw) / 2
    else:
        ok = ~np.isnan(z)
        z = np.interp(zeit, zeit[ok], z[ok])                                    # Lücken: halten, am Rand verlängern
    t = np.arange(n) / fps
    zi = np.interp(t, zeit, z)
    zi = median_filter(zi, size=max(3, int(fps * 0.8) | 1), mode="nearest")     # Ausreißer
    lead = int(round(VORAUS * fps))
    ziel = np.concatenate([zi[lead:], np.repeat(zi[-1], lead)]) if lead else zi
    p, out = ziel[0], np.empty(n)
    toleranz, schritt = TOLERANZ * cw, VMAX * cw / fps
    for i, zz in enumerate(ziel):                                               # Kamera bleibt stehen, bis das Geschehen die Zone verlässt
        d = zz - p
        if abs(d) > toleranz:
            p += np.sign(d) * min(abs(d) - toleranz, schritt)
        out[i] = p
    out = gaussian_filter1d(out, SIGMA * fps, mode="nearest")
    return np.clip(out, 0, breite - cw)


# ---------------------------------------------------------------- Rendern

def ausgabegroesse(m):
    oh = 2560 if m["h"] >= 2000 else 1920
    return round(oh * VERHAELTNIS), oh


def blur_bild(bild, ow, oh):
    h, w = bild.shape[:2]
    kl = (ow // 6, oh // 6)
    s = max(kl[0] / w, kl[1] / h)                                               # Hintergrund: Bild füllt die Fläche
    klein = cv2.resize(bild, (max(kl[0], round(w * s)), max(kl[1], round(h * s))), interpolation=cv2.INTER_AREA)
    x0, y0 = (klein.shape[1] - kl[0]) // 2, (klein.shape[0] - kl[1]) // 2
    hg = cv2.GaussianBlur(klein[y0:y0 + kl[1], x0:x0 + kl[0]], (0, 0), 5)
    hg = cv2.convertScaleAbs(cv2.resize(hg, (ow, oh), interpolation=cv2.INTER_LINEAR), alpha=0.55)
    vh = round(h * ow / w)
    vg = cv2.resize(bild, (ow, vh), interpolation=cv2.INTER_AREA if ow < w else cv2.INTER_LANCZOS4)
    y = (oh - vh) // 2
    hg[y:y + vh] = vg[:oh - y] if y + vh > oh else vg
    return hg


def rendern(pfad, m, modus, x_bahn, ziel):
    ow, oh = ausgabegroesse(m)
    n_soll = int(round(m["dur"] * m["fps"]))
    vf = tonemap_for(m["trc"]) + f"fps={m['fps']},"
    if not m["cs"] and not m["trc"] and m["h"] >= 720:
        vf += "scale=in_color_matrix=bt709,"                                    # unmarkiertes HD ist bt709
    dec = dekodierer(pfad, m, vf + "format=bgr24")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{ow}x{oh}",
           "-framerate", str(m["fps"]), "-i", "-"]
    if m["ton"]:
        cmd += ["-i", str(pfad)]
    cmd += ["-map", "0:v"] + (["-map", "1:a:0?"] if m["ton"] else []) + [
        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "14", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(ziel)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    cw = m["h"] * VERHAELTNIS
    s = oh / m["h"]
    t0, n = time.time(), 0
    for i, bild in enumerate(bilder(dec, m["w"], m["h"])):
        if modus == "blur":
            aus = blur_bild(bild, ow, oh)
        else:
            x0 = x_bahn[min(i, len(x_bahn) - 1)]
            if s < 0.95:                                                        # Quelle größer als Ausgabe: erst flächig verkleinern
                bild = cv2.resize(bild, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            a = s if s >= 0.95 else 1.0
            aus = cv2.warpAffine(bild, np.array([[a, 0, -x0 * s], [0, a, 0]], np.float64), (ow, oh),
                                 flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)   # Sub-Pixel-Schwenk
        enc.stdin.write(aus.tobytes())
        n = i + 1
    dec.wait()
    enc.stdin.close()
    fehler = enc.stderr.read().decode()[-400:]
    if enc.wait() or not ziel.exists():
        sys.exit(f"Kodieren fehlgeschlagen: {fehler}")
    return n, n_soll, time.time() - t0, (ow, oh)


# ---------------------------------------------------------------- Kontaktbogen

def kontaktbogen(kontakt, x_bahn, zeit_bahn_fps, m, aw_ah, modus, out):
    import ansicht
    from PIL import Image
    aw, ah = aw_ah
    cw_an = ah * VERHAELTNIS
    kachel = []
    texte = []
    for t, bild, boxen in kontakt:
        i = min(int(round(t * zeit_bahn_fps)), len(x_bahn) - 1)
        x0 = x_bahn[i] * aw / m["w"] if modus == "tracking" else (aw - cw_an) / 2
        quelle = bild.copy()
        for x, y, bw, bh, c in boxen:
            cv2.rectangle(quelle, (int(x), int(y)), (int(x + bw), int(y + bh)), (60, 220, 60), 2)
        if modus == "blur":
            vorschau = blur_bild(bild, round(ah * VERHAELTNIS), ah)
        else:
            cv2.rectangle(quelle, (int(x0), 0), (int(x0 + cw_an), ah - 1), (40, 40, 255), 4)
            vorschau = bild[:, int(round(x0)):int(round(x0)) + int(round(cw_an))]
        q = cv2.resize(quelle, (320, round(320 * ah / aw)), interpolation=cv2.INTER_AREA)
        v = cv2.resize(vorschau, (round(q.shape[0] * VERHAELTNIS), q.shape[0]), interpolation=cv2.INTER_AREA)
        kachel.append(Image.fromarray(cv2.cvtColor(np.hstack([q, v]), cv2.COLOR_BGR2RGB)))
        texte.append(f"{t:.1f} s")
    ansicht.passend(ansicht.raster(kachel, texte, spalten=2)).save(out, quality=88)
    return out


# ---------------------------------------------------------------- Hauptteil

def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("-") and sys.argv[i - 1] not in ("--modus", "-o", "--kontakt")]
    if not pos:
        sys.exit(__doc__)
    quelle = Path(pos[0])
    modus = arg("--modus", "tracking")
    if modus not in ("tracking", "mitte", "blur"):
        sys.exit("--modus: tracking, mitte oder blur")
    m = sonde(quelle)
    print(f"Quelle   {quelle.name}: {m['w']}×{m['h']}, {m['fps']:g} fps, {m['dur']:.1f} s, {'HDR ' + m['trc'] if m['trc'] in ('arib-std-b67', 'smpte2084') else 'SDR'}"
          + ("" if m["ton"] else ", ohne Ton"))
    if m["h"] >= m["w"]:
        print("Ergebnis schon Hochformat, nichts zu tun")
        return
    cw = m["h"] * VERHAELTNIS
    ow, oh = ausgabegroesse(m)
    hoch = oh / m["h"]
    stamm = quelle.stem
    n_soll = int(round(m["dur"] * m["fps"]))
    kontakt_pfad = Path(arg("--kontakt", WORK / "ansicht" / f"reframe_{stamm}.jpg"))
    zeit, ziele, kontakt, stat, groesse, x_bahn = None, None, [], {}, None, None
    if modus == "tracking":
        t0 = time.time()
        zeit, ziele, kontakt, stat, groesse = analysieren(quelle, m)
        x_bahn = bahn(zeit, ziele, m["fps"], n_soll, m["w"], cw)
        personen_text = (f", Personen (YOLOX) in {100 * stat['mit_person']:.0f} % der Bilder" if stat["personen_modell"]
                         else ", ohne Personenmodell (nur Bewegung)")
        print(f"Analyse  {time.time() - t0:.0f} s{personen_text}; kein Anhaltspunkt in {100 * stat['ohne_anhalt']:.0f} % der Zeit")
        print(f"Bahn     Fensterkante {x_bahn.min():.0f} bis {x_bahn.max():.0f} px von {m['w'] - cw:.0f} möglichen, "
              f"Schwenkweg {np.abs(np.diff(x_bahn)).sum():.0f} px")
    else:
        x_bahn = np.full(n_soll, (m["w"] - cw) / 2)
        aw = min(AN_BREITE, m["w"])
        groesse = (aw, round(aw * m["h"] / m["w"] / 2) * 2)
        if "--kein-kontakt" not in sys.argv:
            kontakt = leichte_kontaktframes(quelle, m, groesse)
    if kontakt and "--kein-kontakt" not in sys.argv:
        kontakt_pfad.parent.mkdir(parents=True, exist_ok=True)
        kontaktbogen(kontakt, x_bahn, m["fps"], m, groesse, modus, kontakt_pfad)
        print(f"Ansicht  {kontakt_pfad}")
    if modus == "blur":
        print(f"Modus    blur: ganzes Bild {ow}×{round(m['h'] * ow / m['w'])} in der Mitte, Hintergrund unscharf")
    else:
        print(f"Modus    {modus}: Fenster {cw:.0f}×{m['h']} ({100 * cw / m['w']:.0f} % der Breite), Faktor {hoch:.2f} auf {ow}×{oh}"
              + (f", weich: {cw:.0f} px echte Breite; blur oder Ausschuss erwägen" if hoch > 1.3 else ""))
    if "--analyse" in sys.argv:
        return
    ziel = Path(arg("-o", WORK / "reframe" / f"{stamm}_9x16.mp4"))
    n, soll, sek, (ow, oh) = rendern(quelle, m, modus, x_bahn, ziel)
    print(f"Ausgabe  {ziel}: {ow}×{oh}, {n} Bilder (Quelle {soll}), {sek:.0f} s Rechenzeit, {ziel.stat().st_size / 1e6:.1f} MB")
    if abs(n - soll) > 2:
        print(f"WARNUNG  Bilderzahl weicht ab ({n} statt {soll}): Quelle mit wechselnder Bildrate? Ton kann leicht abweichen")
    if "--manifest" in sys.argv:
        mf = WORK / "manifest.tsv"
        alt = [z for z in (mf.read_text().splitlines(True) if mf.exists() else []) if z.split("\t")[1:2] != [ziel.name]]
        mf.parent.mkdir(parents=True, exist_ok=True)
        mf.write_text("".join(alt) + f"local:{ziel.resolve()}\t{ziel.name}\t{ziel.stat().st_size}\n")
        print(f"Manifest {mf}: {ziel.name} eingetragen (Kürzel im Schnitt: {ziel.stem})")


def leichte_kontaktframes(quelle, m, groesse, n=6):
    """Kontakt-Frames ohne Analyse (mitte, blur): n gleichmäßig verteilte Bilder."""
    aw, ah = groesse
    out = []
    for i in range(n):
        t = m["dur"] * (i + 0.5) / n
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(quelle), "-frames:v", "1", "-vf",
                            f"scale={aw}:{ah},format=bgr24", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
        if len(r.stdout) == aw * ah * 3:
            out.append((t, np.frombuffer(r.stdout, np.uint8).reshape(ah, aw, 3).copy(), []))
    return out


if __name__ == "__main__":
    main()
