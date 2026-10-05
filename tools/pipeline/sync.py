#!/usr/bin/env python3
"""Mehrkamera-Sync: mehrere Videos derselben Szene über den Ton auf eine gemeinsame Zeitachse legen (seit 30.09.2026).

    cd /tmp && python3 /mnt/project-files/tools/pipeline/sync.py <clip1> <clip2> [...] [--ref <kürzel>] [--max 300] [-o sync.json]
    python3 sync.py uebersicht sync.json [--breite 40]

Clips als Kürzel (`5315` oder `IMG_5315`: gesucht wird $REEL_WORK/audio/<stamm>.flac, sonst ein Video in
$REEL_WORK/dl/) oder als Datei (flac, wav, mov, mp4 ...). Die Referenz (--ref, Standard: der erste Clip) hat Versatz 0.
Die Clips müssen sich nicht alle mit der Referenz überlappen: fehlt ein direkter brauchbarer Treffer, läuft die
Zuordnung über einen anderen Clip (Kette, Feld "ueber"). Ein Clip ohne Ton (stumm, nicht lesbar) bricht den Lauf nicht
ab, er bleibt ohne Offset. Exit 1 nur bei Fehlern (Clip nicht gefunden, Referenz ohne Ton), sonst 0, auch mit Warnungen.

Definition (gilt überall): t_gemeinsam = t_clip + offset_s. Sekunde t_clip im Clip ist also Sekunde t_clip + offset_s
auf der Zeitachse der Referenz. Positiv = der Clip startet später als die Referenz, negativ = früher. t_clip zählt ab
Bildbeginn (Videodatei: ein Tonstart nach dem Bild wird eingerechnet, aus der .flac gilt Tonzeit = Clipzeit).
offset_s gilt genau bei der Clipzeit bezug_s (Mitte der Überlappung). Die Uhren zweier Handys laufen leicht verschieden:
drift_ppm > 0 heißt, die Uhr des Clips geht langsamer als die der Referenz, dann gilt genauer
t_gemeinsam = t_clip + offset_s + drift_ppm * 1e-6 * (t_clip - bezug_s). zeit_in/deckt rechnen das ein, sobald der
Drift sicher gemessen ist (drift_sicher: mindestens 3 Fenster auf einer Geraden, 3 Sigma, mindestens 5 ppm). Über wenige
Minuten macht er nur Millisekunden aus; die Warnung "Uhrendrift" kommt, wenn er über die Überlappung mehr als ein halbes
Bild ausmacht (Bildrate aus meta/, sonst 60 fps angenommen).

Verfahren: Ton auf 16 kHz Mono, GCC-PHAT über die ganze Länge (FFT; unabhängig von Lautstärke, Rauschen und Tiefpass
durch Entfernung; Band 150 bis 6000 Hz). Aus der Hauptspitze im Suchfenster (+-max_s) werden Konfidenz und
Mehrdeutigkeit bestimmt: Abstand zum Rauschpegel (mindestens 10 Sigma) und Verhältnis Hauptspitze zu zweiter Spitze
außerhalb von 50 ms (unter 1,5 = mehrdeutig). Ist der Treffer schwach (Uhrendrift zerstört bei langen Clips die
Kohärenz), folgt ein zweiter Anlauf in Blöcken von etwa 8 s. Dann wird in 3 bis 8 Fenstern über die Überlappung (Anfang
bis Ende) mit vierfacher Überabtastung nachgemessen (Genauigkeit unter 1 ms) und eine robuste Gerade durch die Fenster
gelegt: Offset in der Mitte, Drift als Steigung (bei merklicher Drift ein zweiter Durchgang mit entzerrten Fenstern).
Drei starke Fenster auf einer Geraden bestätigen auch einen schwachen globalen Treffer. Gegenprobe: Hüllkurven-Korrelation
(Lautstärkeverlauf in 8 Bändern); zeigt sie eindeutig woandershin, ist der Clip mehrdeutig. Liegen Aufnahmezeiten in
$REEL_WORK/meta/<stamm>.json (ingest.py), sind sie nur Vorwissen: das Suchfenster wird bei Bedarf erweitert, bei
gleich hohen Spitzen entscheidet die Nähe zur Aufnahmezeit (innerhalb 3 s, mit Warnung, mehrdeutig bleibt true), und
ein Widerspruch von mehr als 10 s wird gemeldet. Ohne meta/ läuft alles genauso, nur ohne diese Hilfe.

Musik aus einer Box: wiederholt sich ein Song oder ein Loop exakt, gibt es gleich hohe Spitzen im Abstand der Schleife.
Dann ist mehrdeutig=true, die Konfidenz klein und offset_s nur ein Vorschlag (brauchbar=false). Sprache oder ein
Klatscher im Bild macht den Treffer eindeutig. Grenzen: Mindestüberlappung 3 s (bei kürzeren Clips die Hälfte des
kürzeren); Drift bis etwa 300 ppm wird gemessen; ein Clip ohne gemeinsamen Ton mit den anderen wird nicht eingeordnet.
Laufzeit: zwei Clips à 1 Minute etwa 1 s, à 3 Minuten etwa 3 s, à 10 Minuten etwa 8 s und 0,7 GB Speicher (mit
Uhrendrift über 10 ppm bei 10 Minuten etwa 20 s); je weiterer Clip kommt ein Vergleich dazu.

sync.json:
  ref, sr, max_s, zeitachse [von, bis], warnungen [...],
  clips: { <stamm>: { pfad, offset_s (null = nicht eingeordnet), bezug_s, dauer_s, konfidenz (0..1), mehrdeutig,
           brauchbar (Treffer, eindeutig und Konfidenz >= 0,5), drift_ppm (null = nicht messbar), drift_fehler_ppm,
           drift_sicher, ueberlappung [von, bis] auf der Zeitachse der Referenz (null = keine), ueber (Kette, sonst
           null), gegen (Clip, mit dem verglichen wurde: die Referenz oder der Kettenclip), kandidaten [{offset_s,
           staerke}] (die stärksten Spitzen gegen "gegen", Offset und Stärke relativ zur größten), fenster [[t_clip,
           offset_s]] (die gewerteten Fenster), huellkurve {offset_s, einig}, aufnahmezeit_s (Versatz laut meta/
           gegen "gegen"), warnungen [...] } }

Python: laden(pfad), speichern(sync, pfad), sync_clips(clips, ref=None, max_s=300), zeit_in(sync, von_clip, t, nach_clip),
deckt(sync, t_gemeinsam), clip_zeit(sync, clip, t_gemeinsam), gemeinsam_zeit(sync, clip, t), uebersicht_text(sync).
Clips in sync werden mit Kürzel, Stamm oder Dateiname angesprochen. Clips mit brauchbar=false (mehrdeutig, schwach oder
ohne Treffer) liefern in zeit_in/deckt None, damit sie nicht still im Schnitt landen; unsicher=True gibt auch den
Vorschlag zurück (zum Anzeigen, nicht zum Schneiden). drift=False rechnet die Drift nicht ein.
Nur lesen: es wird nichts außer der Ausgabedatei geschrieben.
"""
import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner

import numpy as np
from scipy import fft, ndimage, signal

SR = 16000                      # Rechenrate (Hz)
BAND = (150.0, 6000.0)          # Band für GCC-PHAT (Hz)
MIN_UEB_S = 3.0                 # kürzere Überlappung zählt nicht als Treffer
EXKL_S = 0.05                   # zweite Spitze nur außerhalb dieses Abstands zur Hauptspitze
Z_MIN, Z_VOLL = 10.0, 30.0      # Spitze in Robust-Sigma über dem Rauschen: ab Z_MIN Treffer, ab Z_VOLL volle Konfidenz
RATIO_MEHRDEUTIG, RATIO_VOLL = 1.5, 2.0   # Hauptspitze / zweite Spitze: darunter mehrdeutig, ab RATIO_VOLL volle Konfidenz
MIN_KONF = 0.5                  # brauchbar ab dieser Konfidenz
Z_FENSTER = 8.0                 # Mindeststärke einer Fensterspitze
FENSTER_TOL_S = 0.002           # Fenster weiter als das von der Geraden: Ausreißer
PRIOR_TOL_S = 3.0               # Aufnahmezeit entscheidet zwischen gleich hohen Kandidaten nur innerhalb dieser Nähe
PRIOR_WARN_S = 10.0             # Widerspruch zwischen Ton und Aufnahmezeit, ab dem gewarnt wird
FPS_STANDARD = 60.0             # Bildrate, wenn unbekannt (streng, damit die Drift-Warnung eher kommt)
BLOCK_S, BLOCK_MAX = 8.0, 12    # zweiter Anlauf bei schwachem Treffer: Blocklänge (s), höchstens so viele Blöcke je Clip
ALLE_PAARE_BIS = 5              # bis zu so vielen Clips werden alle Paare gerechnet (Dreiecksprobe)
TON_EXT = (".flac", ".wav", ".ogg")
VIDEO_EXT = (".mov", ".mp4", ".m4v")


def _work():
    """Arbeitsordner wie reelcfg.WORK, aber bei jedem Aufruf neu gelesen (Tests setzen REEL_WORK nachträglich)."""
    return Path(os.environ.get("REEL_WORK", "/home/user/reel"))


# ---------------------------------------------------------------- Clips finden und laden

def finde_clip(spec):
    """Kürzel ('5315', 'IMG_5315') oder Datei -> (stamm, pfad). Kürzel: audio/<stamm>.flac, sonst Video in dl/."""
    spec = str(spec)
    p = Path(spec).expanduser()
    if p.is_file():
        return p.stem, p
    w = _work()
    tonordner, dl = w / "audio", w / "dl"
    if p.suffix.lower() in VIDEO_EXT + TON_EXT:
        spec = p.stem                                   # 'IMG_5315.MOV' ohne Datei: wie das Kürzel behandeln
    stamm_liste = [spec, "IMG_" + spec]
    if tonordner.is_dir():
        stamm_liste += sorted(f.stem for f in tonordner.glob("*.flac") if f.stem.endswith(spec) and f.stem not in stamm_liste)
    if dl.is_dir():
        stamm_liste += sorted(f.stem for f in dl.iterdir() if f.suffix.lower() in VIDEO_EXT and f.stem.endswith(spec)
                              and f.stem not in stamm_liste)
    for st in stamm_liste:
        f = tonordner / f"{st}.flac"
        if f.is_file():
            return st, f
        if dl.is_dir():
            for g in sorted(dl.iterdir()):
                if g.stem == st and g.suffix.lower() in VIDEO_EXT:
                    return st, g
    raise FileNotFoundError(f"Clip {spec!r} nicht gefunden (gesucht: Datei, {tonordner}/<stamm>.flac, {dl}/<stamm>.mov)")


def _meta(stamm):
    """Aufnahmezeit (Sekunden seit Epoche) und Bildrate aus $REEL_WORK/meta/<stamm>.json; fehlt sie, leere Werte."""
    import datetime as dt
    out = dict(ctime=None, fps=None)
    try:
        m = json.load(open(_work() / "meta" / f"{stamm}.json"))
    except (OSError, ValueError):
        return out
    try:
        out["ctime"] = dt.datetime.strptime(m["ctime"], "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (KeyError, TypeError, ValueError):
        pass
    try:
        out["fps"] = float(m["fps"]) or None
    except (KeyError, TypeError, ValueError):
        pass
    return out


def _tonversatz(pfad):
    """Tonstart minus Bildstart einer Videodatei in s (ffprobe), 0 wenn unbekannt."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time", "-of", "json",
                            str(pfad)], capture_output=True, text=True, timeout=60)
        st = {}
        for s in json.loads(r.stdout).get("streams", []):
            st.setdefault(s.get("codec_type"), float(s["start_time"]))
        return st["audio"] - st["video"] if "audio" in st and "video" in st else 0.0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return 0.0


def lade_ton(pfad):
    """Ton einer Datei als float32-Mono bei 16 kHz und Liste von Hinweisen. Die Zeit läuft ab Bildbeginn.
    Alles über ffmpeg (schnell und sparsam, 10 Minuten in 1 bis 2 s und 40 MB); ohne ffmpeg nur flac/wav über soundfile."""
    pfad = Path(pfad)
    hinweise = []
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(pfad), "-vn", "-map", "0:a:0?", "-ac", "1", "-ar", str(SR),
                            "-f", "f32le", "-"], capture_output=True)
    except FileNotFoundError:
        r = None
    if r is None:                                        # kein ffmpeg im Pfad
        if pfad.suffix.lower() not in TON_EXT:
            raise ValueError(f"{pfad.name}: ffmpeg fehlt, nur {'/'.join(TON_EXT)} lesbar")
        import soundfile as sf
        d, sr = sf.read(str(pfad), dtype="float32", always_2d=True)
        x = d.mean(axis=1)
        g = math.gcd(int(sr), SR)
        x = x if sr == SR else signal.resample_poly(x, SR // g, int(sr) // g).astype(np.float32)
    else:
        if r.returncode != 0:
            raise ValueError(f"{pfad.name}: ffmpeg kann den Ton nicht lesen: {r.stderr.decode(errors='replace')[-200:]}")
        x = np.frombuffer(r.stdout, dtype="<f4").copy()
        v = _tonversatz(pfad) if pfad.suffix.lower() not in TON_EXT else 0.0
        if abs(v) >= 0.002 and len(x):
            n = int(round(abs(v) * SR))
            x = np.concatenate([np.zeros(n, np.float32), x]) if v > 0 else x[n:]
            hinweise.append(f"Ton startet {v * 1000:+.0f} ms gegen das Bild, eingerechnet")
    if len(x) < SR:
        raise ValueError(f"{pfad.name}: kein oder zu wenig Ton ({len(x) / SR:.1f} s)")
    x = x - np.float32(x.mean())
    if not np.isfinite(x).all():
        x = np.nan_to_num(x)
    if float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) < 1e-5:
        raise ValueError(f"{pfad.name}: Ton ist stumm")
    return x, hinweise


def _lade_clip(spec, benutzt):
    """Clip laden. Ohne Ton (stumm, zu kurz, nicht lesbar) bleibt ein Platzhalter mit 'fehler', die anderen Clips laufen weiter."""
    try:
        stamm, pfad = finde_clip(spec)
    except FileNotFoundError:
        for st in (str(spec), "IMG_" + str(spec)):                     # ingest.py kennt den Clip, hat aber keinen Ton gefunden
            try:
                if json.load(open(_work() / "meta" / f"{st}.json")).get("ton") is False:
                    name, k = st, 1
                    while name in benutzt:
                        k += 1
                        name = f"{st}_{k}"
                    return dict(spec=str(spec), name=name, stamm=st, pfad="", fehler=f"{st}: Clip hat keinen Ton", x=None,
                                dauer=0.0, hinweise=[], **_meta(st))
            except (OSError, ValueError):
                pass
        raise
    name, k = stamm, 1
    while name in benutzt:
        k += 1
        name = f"{stamm}_{k}"
    clip = dict(spec=str(spec), name=name, stamm=stamm, pfad=str(pfad), fehler=None, **_meta(stamm))
    try:
        x, hinweise = lade_ton(pfad)
    except ValueError as e:
        return dict(clip, x=None, dauer=0.0, hinweise=[], fehler=str(e))
    return dict(clip, x=x, dauer=len(x) / SR, hinweise=hinweise)


# ---------------------------------------------------------------- GCC-PHAT

def _phat(X, Y, nfft):
    """Kreuzspektrum aus den Spektren X, Y (Lag k: Summe x[n+k]*y[n]), auf Phase normiert und auf BAND begrenzt."""
    G = X * np.conj(Y)
    i0 = int(BAND[0] * nfft / SR)
    i1 = min(len(G), int(BAND[1] * nfft / SR))
    mag = np.abs(G[i0:i1])
    G[:i0] = 0
    G[i1:] = 0
    G[i0:i1] /= mag + np.float32(1e-3) * (mag.mean() + np.float32(1e-30))
    del mag
    for lo, n in ((i0, int(100 * nfft / SR)), (i1, -int(300 * nfft / SR))):     # weiche Bandkanten (Nachschwingen)
        if abs(n) > 2:
            rampe = (0.5 - 0.5 * np.cos(np.pi * np.linspace(0, 1, abs(n)))).astype(G.real.dtype)
            if n > 0:
                G[lo:lo + n] *= rampe
            else:
                G[lo + n:lo] *= rampe[::-1]
    return G


def _parabel(v0, v1, v2):
    """Scheitelverschiebung (in Abtastwerten, -1..1) einer Parabel durch drei Punkte um ein Maximum."""
    d = v0 - 2 * v1 + v2
    return 0.0 if d >= 0 or not np.isfinite(d) else float(np.clip(0.5 * (v0 - v2) / d, -1, 1))


def _robust(v):
    """Median und Robust-Sigma (1,4826 * MAD) eines Rauschpegels, aus jedem 7. Wert geschätzt (schnell bei 10 Minuten)."""
    w = v[::7] if len(v) > 50000 else v
    med = float(np.median(w))
    return med, 1.4826 * float(np.median(np.abs(w - med))) + 1e-30


def _spitzen(v, med, ex, n=6):
    """Bis zu n Spitzen (Index, Wert), die jeweils mindestens ex Indizes auseinander liegen, hoechste zuerst."""
    w = v.astype(np.float32, copy=True)
    out = []
    for _ in range(n):
        i = int(np.argmax(w))
        if not np.isfinite(w[i]) or w[i] <= med:
            break
        out.append((i, float(v[i])))
        w[max(0, i - ex):i + ex + 1] = -np.inf
    return out


def _global(x, y, lo_s, hi_s, min_ueb_s, blockweise=False):
    """GCC-PHAT der Clips, Offset-Achse in Abtastwerten (x[n + offset] ~ y[n]). Standard: die ganzen Clips auf einmal
    (beste Trennschärfe). blockweise=True (zweiter Anlauf): y in Blöcken von ~8 s gegen den ganzen x, auf der
    Offset-Achse addiert (je Block in Rausch-Sigma, Spitzenbreite +-25 ms). Das rettet den Treffer bei Uhrendrift:
    schon 10 ms Drift über die Länge zerstören die Kohärenz im Band (lange Clips, Handys mit 50 ppm Unterschied).
    Kandidaten: (Offset in s, Wert). Der Feinabgleich kommt danach aus den Fenstern."""
    nx, ny = len(x), len(y)
    lb = max(BLOCK_S, ny / SR / BLOCK_MAX)
    k_bl = int(math.ceil(ny / SR / lb)) if blockweise and ny > 1.5 * lb * SR else 1
    m = int(math.ceil(ny / k_bl))
    bloecke = [(b * m, min(ny, (b + 1) * m)) for b in range(k_bl)]
    min_ueb = int(min_ueb_s * SR)
    bereich = [(min(min_ueb, (e - s) // 2) - (e - s) - s, nx - min(min_ueb, (e - s) // 2) - s) for s, e in bloecke]
    olo = max(int(math.floor(lo_s * SR)), min(r[0] for r in bereich))
    ohi = min(int(math.ceil(hi_s * SR)), max(r[1] for r in bereich))
    if ohi <= olo:
        return None
    nfft = fft.next_fast_len(nx + m - 1, real=True)
    X = fft.rfft(x, nfft, workers=-1)
    n_o = ohi - olo + 3                                    # je ein Wert Rand für die Parabel
    S = np.zeros(n_o, np.float32)
    w = int(0.025 * SR) if k_bl > 1 else 0
    for (s, e), (blo, bhi) in zip(bloecke, bereich):
        G = _phat(X, fft.rfft(y[s:e], nfft, workers=-1), nfft)
        r = fft.irfft(G, nfft, workers=-1)
        del G
        v0, v1 = max(blo, olo - 1), min(bhi, ohi + 1)        # gültige Offsets dieses Blocks im Suchfenster
        if v1 - v0 < 10:
            del r
            continue
        k0, ln = (v0 + s) % nfft, v1 - v0 + 1                # Offset o liegt bei Lag o + s (zyklisch)
        v = np.concatenate([r[k0:k0 + ln], r[:max(0, k0 + ln - nfft)]]).astype(np.float32)
        del r
        med, sig = _robust(v)
        v = (v - med) / sig
        if w:
            v = ndimage.maximum_filter1d(v, 2 * w + 1)
        S[v0 - (olo - 1):v0 - (olo - 1) + ln] += v
    del X
    med, sig = _robust(S[1:-1])
    sp = _spitzen(S[1:-1], med, int(EXKL_S * SR))
    kand = []
    for i, val in sp:
        j = i + 1
        d = _parabel(S[j - 1], S[j], S[j + 1]) if k_bl == 1 else 0.0
        kand.append(((olo + i + d) / SR, val))
    return dict(kand=kand, med=med, sig=sig, n=ohi - olo + 1, bloecke=k_bl)


def _lokal(xs, ys, M, ueber=4):
    """GCC-PHAT eines Fensters: xs (Basis, je M Abtastwerte länger) gegen ys. Rückgabe (Abweichung in Abtastwerten
    zur Mitte, Stärke in Sigma) oder None."""
    nfft = fft.next_fast_len(len(xs) + len(ys) - 1, real=True)
    G = _phat(fft.rfft(xs, nfft, workers=-1), fft.rfft(ys, nfft, workers=-1), nfft)
    r = fft.irfft(G, ueber * nfft, workers=-1)[:2 * M * ueber + 1]
    med, sig = _robust(r[::ueber])
    i = int(np.argmax(r))
    if i < 2 or i > len(r) - 3:
        return None
    d = _parabel(r[i - 1], r[i], r[i + 1])
    return ((i + d) / ueber - M, (float(r[i]) - med) / sig)


def _gerade(tc, off):
    """Robuste Gerade off(t) = a + b*t. Rückgabe (Mittelwert t, Mittelwert off, Steigung, Steigungsfehler, n Inlier,
    Indizes der Inlier) oder None."""
    tc, off = np.asarray(tc, float), np.asarray(off, float)
    n = len(tc)
    if n < 2:
        return None
    inl = np.ones(n, bool)
    if n >= 3:
        st = [(off[j] - off[i]) / (tc[j] - tc[i]) for i in range(n) for j in range(i + 1, n) if tc[j] != tc[i]]
        b = float(np.median(st)) if st else 0.0
        a = float(np.median(off - b * tc))
        inl = np.abs(off - (a + b * tc)) <= FENSTER_TOL_S
    if inl.sum() < 2:
        return None
    t, o = tc[inl], off[inl]
    tm, om = t.mean(), o.mean()
    sxx = float(np.sum((t - tm) ** 2))
    if sxx < 1e-9:
        return None
    b = float(np.sum((t - tm) * (o - om)) / sxx)
    res = o - (om + b * (t - tm))
    s = math.sqrt(float(np.sum(res ** 2)) / (len(t) - 2)) if len(t) > 2 else 0.0
    s = max(s, 0.0002)                                    # Fensterfehler nie unter 0,2 ms annehmen
    return float(tm), float(om), b, s / math.sqrt(sxx), int(inl.sum()), np.flatnonzero(inl)


def _fenster(x, y, off_s, tb_lo, tb_hi, drift=0.0):
    """Offset in Fenstern über die Überlappung (Clipzeit tb_lo..tb_hi). Rückgabe Liste (t_clip, offset_s oder None, Stärke).
    Mit drift (Steigung, z. B. 1e-4) wird das Clip-Fenster vor dem Vergleich um 1 + drift gestreckt: die Drift
    verschmiert die Spitze sonst schon bei einigen 100 ppm; t_clip ist dann der Fensteranfang statt der Mitte."""
    lov = tb_hi - tb_lo
    if lov < 12:
        lw, n_w = lov, 1
    else:
        lw = min(20.0, max(4.0, lov / 4))
        n_w = max(3, min(8, int(math.ceil(lov / lw))))
    starts = np.linspace(tb_lo, tb_hi - lw, n_w) if n_w > 1 else [tb_lo]
    M = int(min(0.25, max(0.1, 0.0005 * lov)) * SR)
    m = int(lw * SR)
    l0 = int(round(off_s * SR))
    out = []
    for st in starts:
        s = int(round(st * SR))
        ys = y[s:s + m]
        if len(ys) < SR:
            continue
        if drift:
            ys = ndimage.map_coordinates(ys, [np.arange(int((len(ys) - 1) * (1 + drift)) + 1) / (1 + drift)], order=3,
                                         mode="nearest")
        a = s + l0 - M
        xs = np.zeros(len(ys) + 2 * M, np.float32)
        lo, hi = max(a, 0), min(a + len(xs), len(x))
        if hi - lo < SR:
            continue
        xs[lo - a:hi - a] = x[lo:hi]
        rr = _lokal(xs, ys, M)
        t = float(s / SR) if drift else float((s + len(ys) / 2) / SR)
        if rr is None or rr[1] < Z_FENSTER:
            out.append((t, None, rr[1] if rr else 0.0))
        else:
            out.append((t, (l0 + rr[0]) / SR, rr[1]))
    return out


# ---------------------------------------------------------------- Hüllkurven-Gegenprobe

def _huellen(x):
    """Lautstärkeverlauf in 8 Bändern (200 bis 6000 Hz), 100 Bilder je Sekunde, langsamer Pegel abgezogen."""
    f, _, S = signal.spectrogram(x, SR, window="hann", nperseg=512, noverlap=512 - 160, mode="psd")
    kanten = np.geomspace(200, 6000, 9)
    B = np.stack([S[(f >= lo) & (f < hi)].sum(axis=0) for lo, hi in zip(kanten[:-1], kanten[1:])])
    L = np.log(B + 1e-9 * (B.mean() + 1e-30))
    L -= ndimage.uniform_filter1d(L, 100, axis=1, mode="nearest")
    L /= L.std(axis=1, keepdims=True) + 1e-9
    return L.astype(np.float32)


def _huellkurve(x, y, lo_s, hi_s, off_s):
    """Korrelation der Hüllkurven. Rückgabe dict: kand [(offset_s, rho)], z_top (Stärke der höchsten Spitze in Sigma),
    z_bei (stärkste Stelle im Abstand bis 60 ms um off_s) oder None."""
    hop = 160 / SR
    Lx, Ly = _huellen(x), _huellen(y)
    nx, ny = Lx.shape[1], Ly.shape[1]
    min_ueb = int(MIN_UEB_S / hop)
    klo = max(min_ueb - ny, int(math.floor(lo_s / hop)))
    khi = min(nx - min_ueb, int(math.ceil(hi_s / hop)))
    if khi <= klo:
        return None
    nfft = fft.next_fast_len(nx + ny - 1, real=True)
    G = np.sum(fft.rfft(Lx, nfft, axis=1, workers=-1) * np.conj(fft.rfft(Ly, nfft, axis=1, workers=-1)), axis=0)
    r = fft.irfft(G, nfft, workers=-1)
    lags = np.arange(klo, khi + 1)
    n_ov = np.minimum(ny, nx - lags) - np.maximum(0, -lags)
    v = r[lags % nfft] / (Lx.shape[0] * np.sqrt(n_ov))           # Rauschen bleibt über alle Überlappungen gleich
    med, sig = _robust(v)
    sp = _spitzen(v, med, int(0.1 / hop), 4)
    if not sp:
        return None
    i0 = int(round(off_s / hop)) - klo
    nah = v[max(0, i0 - 6):max(0, i0 + 7)]
    z_bei = (float(nah.max()) - med) / sig if len(nah) else 0.0
    return dict(kand=[((klo + i) * hop, w) for i, w in sp], z_top=(sp[0][1] - med) / sig, z_bei=z_bei)


# ---------------------------------------------------------------- ein Paar

def _bewerte(g):
    """Stärke der Hauptspitze (Sigma), Verhältnis zur zweiten Spitze und Konfidenz 0..1 aus dem globalen Ergebnis."""
    if g is None or not g["kand"]:
        return None
    kand, med = g["kand"], g["med"]
    p1 = kand[0][1] - med
    z1 = p1 / g["sig"]
    p2 = kand[1][1] - med if len(kand) > 1 else 0.0
    ratio = min(99.0, p1 / p2) if p2 > 0 else 99.0
    k_ratio = float(np.clip((ratio - 1) / (RATIO_VOLL - 1), 0, 1))
    k_z = float(np.clip((z1 - Z_MIN) / (Z_VOLL - Z_MIN), 0, 1))
    return dict(z=z1, ratio=ratio, k_ratio=k_ratio, k_z=k_z, konf=min(k_ratio, k_z), kand=kand, med=med, p1=p1)


def _paar(a, b, max_s):
    """Versatz von Clip b zur Basis a: t_a = (1 + d) * t_b + B. Rückgabe die Kante als dict (treffer=False ohne Treffer)."""
    prior = None
    if a["ctime"] is not None and b["ctime"] is not None:
        prior = b["ctime"] - a["ctime"]         # Clip b startet laut Aufnahmezeit so viel später als a (auf 1 s genau)
    lo, hi = -max_s, max_s
    if prior is not None:
        lo, hi = min(lo, prior - 30), max(hi, prior + 30)
    min_ueb = min(MIN_UEB_S, 0.5 * min(a["dauer"], b["dauer"]))
    w = []
    kante = dict(i=a["name"], j=b["name"], treffer=False, mehrdeutig=True, konfidenz=0.0, warnungen=w)
    bew = _bewerte(_global(a["x"], b["x"], lo, hi, min_ueb))
    if (bew is None or bew["konf"] < MIN_KONF) and b["dauer"] > 1.5 * BLOCK_S:       # zweiter Anlauf gegen Uhrendrift
        bew2 = _bewerte(_global(a["x"], b["x"], lo, hi, min_ueb, blockweise=True))
        if bew2 is not None and (bew is None or bew2["konf"] > bew["konf"]):
            bew = bew2
    if bew is None:
        w.append("Keine ausreichende Überlappung im Suchfenster")
        return kante
    kand, med, z1, ratio, p1 = bew["kand"], bew["med"], bew["z"], bew["ratio"], bew["p1"]
    kante.update(z=round(z1, 1), verhaeltnis=round(ratio, 2),
                 kandidaten=[dict(offset_s=round(o, 5), staerke=round((v - med) / p1, 3)) for o, v in kand[:3]])
    if z1 < 5:
        w.append(f"Kein belastbarer Treffer (Spitze nur {z1:.1f}-fach über dem Rauschen, nötig {Z_MIN:.0f}): "
                 "keine gemeinsame Szene oder zu wenig gemeinsamer Ton")
        return kante
    wahl = kand[0][0]
    if prior is not None and ratio < RATIO_MEHRDEUTIG:
        stark = [o for o, v in kand if (v - med) >= 0.6 * p1]
        nah = [o for o in stark if abs(o - prior) <= PRIOR_TOL_S]
        if len(nah) == 1 and len(stark) > 1:
            wahl = nah[0]
            w.append(f"Mehrere gleich starke Spitzen, gewählt nach Aufnahmezeit ({prior:+.0f} s): {wahl:+.3f} s")
    # Überlappung und Feinabgleich in Fenstern (am gewählten Kandidaten)
    off0 = wahl
    tb_lo, tb_hi = max(0.0, -off0), min(b["dauer"], a["dauer"] - off0)
    fen = _fenster(a["x"], b["x"], off0, tb_lo, tb_hi) if tb_hi - tb_lo >= 1.0 else []
    gut = [(t, o, z) for t, o, z in fen if o is not None]
    gerade = _gerade([g[0] for g in gut], [g[1] for g in gut]) if len(gut) >= 2 else None
    if gerade is not None and abs(gerade[2]) >= 30e-6:            # merkliche Drift: zweiter Durchgang mit gestreckten Fenstern
        fen2 = _fenster(a["x"], b["x"], off0, tb_lo, tb_hi, drift=gerade[2])
        gut2 = [(t, o, z) for t, o, z in fen2 if o is not None]
        gerade2 = _gerade([g[0] for g in gut2], [g[1] for g in gut2]) if len(gut2) >= 2 else None
        if gerade2 is not None and gerade2[4] >= gerade[4]:
            fen, gut, gerade = fen2, gut2, gerade2
    n_in, zmed = 0, 0.0
    if gerade is not None:
        n_in = gerade[4]
        zmed = float(np.median([gut[k][2] for k in gerade[5]]))
    bestaetigt = n_in >= 3 and zmed >= 10.0                  # drei starke Fenster auf einer Geraden: kein Zufall
    z_ok = z1 >= Z_MIN or bestaetigt
    k_fenster = float(np.clip((zmed - Z_FENSTER) / 6.0, 0, 1)) if bestaetigt else 0.0
    konf = min(bew["k_ratio"], max(bew["k_z"], k_fenster))
    kante.update(treffer=z_ok, mehrdeutig=(not z_ok) or ratio < RATIO_MEHRDEUTIG, konfidenz=konf)
    if not z_ok:
        w.append(f"Kein belastbarer Treffer (Spitze nur {z1:.1f}-fach über dem Rauschen, nötig {Z_MIN:.0f}): "
                 "keine gemeinsame Szene oder zu wenig gemeinsamer Ton")
        return kante
    if ratio < RATIO_MEHRDEUTIG:
        w.append(f"Mehrdeutig: zweite Spitze bei {kand[1][0]:+.3f} s erreicht {100 / ratio:.0f} % der Hauptspitze "
                 "(Musik-Wiederholung?), Zuordnung nicht ungeprüft nutzen")
    if tb_hi - tb_lo < 1.0:
        w.append("Überlappung zu kurz für den Feinabgleich")
        tb_lo, tb_hi = 0.0, b["dauer"]
    tm = 0.5 * (tb_lo + tb_hi)
    drift = fehler = None
    sicher = False
    nuetz = []
    if gerade is not None:
        tmean, omean, slope, serr, n_in, inl = gerade
        off_bezug = omean + slope * (tm - tmean)
        nuetz = [gut[k][:2] for k in inl]
        if len(fen) >= 3:
            drift, fehler = slope * 1e6, serr * 1e6
            sicher = n_in >= 3 and abs(drift) >= 3 * fehler and abs(drift) >= 5.0
            if n_in < len(gut):
                w.append(f"{len(gut) - n_in} Fenster weichen von der Geraden ab (Ausreißer, nicht gewertet)")
    elif len(gut) == 1:
        off_bezug, tm = gut[0][1], gut[0][0]
        nuetz = [gut[0][:2]]
    else:
        off_bezug = off0
        if fen:
            w.append("Feinabgleich in den Fenstern nicht möglich, Genauigkeit etwa 1 ms")
    if drift is None and len(fen) >= 3:
        w.append("Drift nicht messbar (zu wenige brauchbare Fenster)")
    fps = max(a.get("fps") or 0, b.get("fps") or 0) or FPS_STANDARD
    if drift is not None and abs(drift) * 1e-6 * (tb_hi - tb_lo) > 0.5 / fps:
        w.append(f"Uhrendrift {drift:+.0f} ppm macht über die Überlappung {abs(drift) * 1e-6 * (tb_hi - tb_lo) * 1000:.0f} ms "
                 f"aus, mehr als ein halbes Bild ({500 / fps:.0f} ms): mit zeit_in umrechnen oder kürzere Stücke nutzen")
    kante.update(offset_s=float(off_bezug), bezug_s=float(tm), drift_ppm=drift, drift_fehler_ppm=fehler,
                 drift_sicher=bool(sicher), ueberlappung_s=float(tb_hi - tb_lo),
                 fenster=[[round(t, 3), round(o, 6)] for t, o in nuetz], prior=prior)
    # Gegenprobe Hüllkurve
    h = None
    try:
        h = _huellkurve(a["x"], b["x"], lo, hi, off_bezug)
    except (MemoryError, ValueError):
        pass
    hk = dict(offset_s=None, einig=None)
    if h is not None:
        hk["offset_s"] = round(h["kand"][0][0], 4)
        if h["z_bei"] >= 6.0:
            hk["einig"] = True
        elif h["z_top"] >= 12.0:                              # die Hüllkurve ist eindeutig, aber woanders: zwei Verfahren uneins
            hk["einig"] = False
            w.append(f"Hüllkurve zeigt auf {h['kand'][0][0]:+.2f} s statt {off_bezug:+.2f} s: nicht ungeprüft nutzen")
            kante["konfidenz"] = min(kante["konfidenz"], 0.3)
            kante["mehrdeutig"] = True
    kante["huellkurve"] = hk
    if prior is not None and abs(off_bezug - prior) > PRIOR_WARN_S:
        w.append(f"Aufnahmezeit widerspricht dem Ton: Ton {off_bezug:+.1f} s, Meta {prior:+.0f} s (Uhren der Handys?)")
    return kante


def _abb(k, von):
    """Abbildung (A, B) der Clipzeit von 'von' in die Clipzeit des anderen Clips der Kante (mit sicherem Drift),
    sowie die gemessene Steigung."""
    d = (k["drift_ppm"] or 0.0) * 1e-6
    de = d if k["drift_sicher"] else 0.0
    a, b = 1 + de, k["offset_s"] - de * k["bezug_s"]          # t_i = a * t_j + b
    am = 1 + d
    if von == k["j"]:
        return a, b, am
    return 1 / a, -b / a, 1 / am


# ---------------------------------------------------------------- mehrere Clips

def sync_clips(clips, ref=None, max_s=300, melde=None):
    """Clips (Kürzel oder Dateien) auf die Zeitachse der Referenz legen, Rückgabe wie sync.json (dict).
    ref: Kürzel/Datei aus clips (Standard der erste), max_s: Suchfenster +-max_s für den Versatz."""
    clips = list(clips)
    if len(clips) < 2:
        raise ValueError("Mindestens zwei Clips nötig")
    melde = melde or (lambda s: None)
    C = []
    for c in clips:
        melde(f"lade {c}")
        C.append(_lade_clip(c, {k["name"] for k in C}))
    ri = 0
    if ref is not None:
        namen = {str(ref), Path(str(ref)).stem, "IMG_" + str(ref)}
        treffer = [i for i, k in enumerate(C) if k["spec"] in namen or k["name"] in namen or k["stamm"] in namen
                   or k["stamm"].endswith(str(ref))]
        if len(treffer) != 1:
            raise ValueError(f"Referenz {ref!r} nicht eindeutig unter den Clips ({len(treffer)} Treffer)")
        ri = treffer[0]
    if C[ri]["fehler"]:
        raise ValueError(f"Referenz {C[ri]['name']}: {C[ri]['fehler']} (andere Referenz mit --ref wählen)")
    n = len(C)
    kanten = {}

    def kante(i, j):
        """Kante mit Basis i und Clip j; liegt das Paar schon andersherum vor, gilt die vorhandene (Namen in k['i'], k['j'])."""
        for key in ((i, j), (j, i)):
            if key in kanten:
                return kanten[key]
        melde(f"vergleiche {C[i]['name']} mit {C[j]['name']}")
        kanten[(i, j)] = _paar(C[i], C[j], max_s)
        return kanten[(i, j)]

    erreicht = {ri: dict(A=1.0, B=0.0, Am=1.0, konf=1.0, mehr=False, ueber=None, kante=None, nach=None)}
    offen = [u for u in range(n) if u != ri and C[u]["x"] is not None]

    def anhaengen(u, r, k):
        """Clip u über Kante k an den erreichten Clip r hängen (Abbildungen verketten, schwächstes Glied zählt)."""
        a, b, am = _abb(k, C[u]["name"])
        p = erreicht[r]
        erreicht[u] = dict(A=p["A"] * a, B=p["A"] * b + p["B"], Am=p["Am"] * am, konf=min(p["konf"], k["konfidenz"]),
                           mehr=p["mehr"] or k["mehrdeutig"], ueber=None if r == ri else C[r]["name"], kante=k, nach=r)

    def gut(k):
        return k["treffer"] and not k["mehrdeutig"] and k["konfidenz"] >= MIN_KONF

    # 1. direkte, brauchbare Treffer mit der Referenz
    for u in offen:
        if gut(kante(ri, u)):
            anhaengen(u, ri, kante(ri, u))
    # 2. übrige Clips über bereits erreichte (jeweils der sicherste Treffer zuerst)
    while True:
        beste = None
        for u in offen:
            if u in erreicht:
                continue
            for r in list(erreicht):
                k = kante(r, u)
                if gut(k) and (beste is None or k["konfidenz"] > beste[2]["konfidenz"]):
                    beste = (u, r, k)
        if beste is None:
            break
        anhaengen(*beste)
    # 3. Rest: bester vorhandener Treffer, auch wenn er mehrdeutig ist (wird als unsicher gemeldet)
    for u in offen:
        if u in erreicht:
            continue
        opt = [(kante(r, u), r) for r in list(erreicht) if kante(r, u)["treffer"]]
        if opt:
            k, r = max(opt, key=lambda e: e[0]["konfidenz"])
            anhaengen(u, r, k)
    # Dreiecksprobe: bei wenigen Clips alle Paare; ein Paar, das nicht zur Kette passt, wird gemeldet
    if n <= ALLE_PAARE_BIS:
        for i in range(n):
            for j in range(i + 1, n):
                if i in erreicht and j in erreicht:
                    kante(i, j)
    extra = {}
    for u in offen:                                  # nicht eingeordnet: Grund aus dem stärksten Vergleich nennen
        if u not in erreicht:
            opt = [k for (i, j), k in kanten.items() if u in (i, j) and k.get("z") is not None]
            if opt:
                extra.setdefault(C[u]["name"], []).extend(max(opt, key=lambda k: k["z"])["warnungen"][:1])
    for (i, j), k in kanten.items():
        if not (k["treffer"] and not k["mehrdeutig"] and i in erreicht and j in erreicht):
            continue
        if erreicht[j]["nach"] == i or erreicht[i]["nach"] == j:
            continue
        ai, bi, aj, bj = erreicht[i]["A"], erreicht[i]["B"], erreicht[j]["A"], erreicht[j]["B"]
        tj = k["bezug_s"]                                        # Clipzeit in j, dort gilt offset_s der Kante exakt
        abw = abs((tj + k["offset_s"]) - ((aj * tj + bj) - bi) / ai)
        if abw > 0.010:
            extra.setdefault(C[j]["name"], []).append(
                f"Dreiecksprobe: Versatz zu {C[i]['name']} weicht um {abw * 1000:.0f} ms von der Kette über die "
                "Referenz ab")
    return _ergebnis(C, ri, erreicht, extra, max_s)


def _leer():
    return dict(offset_s=None, bezug_s=None, konfidenz=0.0, mehrdeutig=True, brauchbar=False, drift_ppm=None,
                drift_fehler_ppm=None, drift_sicher=False, ueberlappung=None, ueber=None, gegen=None, kandidaten=[],
                fenster=[], huellkurve=dict(offset_s=None, einig=None), aufnahmezeit_s=None)


def _ergebnis(C, ri, erreicht, extra, max_s):
    """Clip-Einträge für sync.json aus den verketteten Abbildungen."""
    ref = C[ri]
    out, glob = {}, []
    for u, k in enumerate(C):
        e = erreicht.get(u)
        w = list(k["hinweise"]) + extra.get(k["name"], [])
        eintrag = dict(pfad=k["pfad"], dauer_s=round(k["dauer"], 3), **_leer())
        if u == ri:
            eintrag.update(offset_s=0.0, bezug_s=0.0, konfidenz=1.0, mehrdeutig=False, brauchbar=True, drift_ppm=0.0,
                           drift_fehler_ppm=0.0, ueberlappung=[0.0, round(k["dauer"], 3)])
        elif e is None:
            w.append(k["fehler"] or "Kein Treffer mit einem anderen Clip: nicht eingeordnet")
            glob.append(f"{k['name']}: nicht eingeordnet")
        else:
            kt = e["kante"]
            w += kt["warnungen"]
            name = k["name"]
            basis = kt["i"] == name                  # u ist die Basis der Kante (Normalfall: u ist der verglichene Clip)
            t0 = kt["bezug_s"]                       # Bezug in Clipzeit von u
            if basis:
                a, b, _ = _abb(kt, kt["j"])
                t0 = a * t0 + b
            off = e["A"] * t0 + e["B"] - t0
            g0, g1 = e["B"], e["A"] * k["dauer"] + e["B"]
            von, bis = max(0.0, g0), min(ref["dauer"], g1)
            brauch = bool(kt["treffer"] and not e["mehr"] and e["konf"] >= MIN_KONF)
            if kt["treffer"] and not e["mehr"] and not brauch:
                w.append(f"Konfidenz nur {e['konf']:.2f}")
            if e["nach"] != ri:
                w.append(f"Überlappt die Referenz nicht, eingeordnet über {e['ueber']}" if bis <= von else
                         f"Eingeordnet über {e['ueber']}: ein direkter brauchbarer Treffer mit der Referenz fehlt")
            elif bis <= von:
                w.append("Keine Überlappung mit der Referenz auf der Zeitachse")
            cand = kt.get("kandidaten", [])
            if basis:                                # Kandidaten und Fenster sind in Clipzeit des anderen Clips
                cand = [dict(offset_s=-c["offset_s"], staerke=c["staerke"]) for c in cand]
            eintrag.update(
                offset_s=round(off, 6), bezug_s=round(t0, 3), konfidenz=round(e["konf"], 3), mehrdeutig=bool(e["mehr"]),
                brauchbar=brauch, drift_ppm=None if kt.get("drift_ppm") is None else round((e["Am"] - 1) * 1e6, 1),
                drift_fehler_ppm=None if kt.get("drift_fehler_ppm") is None else round(kt["drift_fehler_ppm"], 1),
                drift_sicher=bool(abs(e["A"] - 1) > 0), ueberlappung=[round(von, 3), round(bis, 3)] if bis > von else None,
                ueber=e["ueber"], gegen=C[e["nach"]]["name"], kandidaten=cand,
                fenster=[] if basis else kt.get("fenster", []), huellkurve=kt.get("huellkurve", _leer()["huellkurve"]),
                aufnahmezeit_s=None if kt.get("prior") is None else round(kt["prior"], 1))
            if not brauch:
                glob.append(f"{name}: nicht eindeutig zugeordnet")
        eintrag["warnungen"] = w
        out[k["name"]] = eintrag
    xs = [(v["offset_s"], v["dauer_s"]) for v in out.values() if v["offset_s"] is not None]
    return dict(version=1, ref=ref["name"], sr=SR, max_s=max_s, warnungen=glob, clips=out,
                zeitachse=[round(min(o for o, _ in xs), 3), round(max(o + d for o, d in xs), 3)])


# ---------------------------------------------------------------- Nutzung von sync.json

def laden(pfad):
    """sync.json lesen (dict wie von sync_clips)."""
    with open(pfad) as f:
        return json.load(f)


def speichern(sync, pfad):
    with open(pfad, "w") as f:
        json.dump(sync, f, ensure_ascii=False, indent=1)


def _key(sync, clip):
    """Clip-Kürzel, Stamm oder Dateiname -> Schlüssel in sync['clips']."""
    cl = sync["clips"]
    c = str(clip)
    for k in (c, Path(c).stem, "IMG_" + c):
        if k in cl:
            return k
    treffer = [k for k in cl if k.endswith(c)]
    if len(treffer) == 1:
        return treffer[0]
    raise KeyError(f"Clip {clip!r} nicht in sync.json ({', '.join(cl)})")


def _abbildung(e, drift=True, unsicher=False):
    """(A, B) mit t_gemeinsam = A * t_clip + B aus einem Clip-Eintrag. None ohne Offset und, solange unsicher=False,
    bei einem Clip mit brauchbar=false (mehrdeutig oder zu schwache Konfidenz): der wird nie still im Schnitt benutzt."""
    if e.get("offset_s") is None or not (unsicher or e.get("brauchbar")):
        return None
    d = (e.get("drift_ppm") or 0.0) * 1e-6 if drift and e.get("drift_sicher") else 0.0
    return 1 + d, e["offset_s"] - d * (e.get("bezug_s") or 0.0)


def gemeinsam_zeit(sync, clip, t, drift=True, unsicher=False):
    """Zeit t im Clip -> Zeit auf der gemeinsamen Zeitachse (Referenz), None ohne brauchbaren Offset."""
    ab = _abbildung(sync["clips"][_key(sync, clip)], drift, unsicher)
    return None if ab is None else ab[0] * t + ab[1]


def clip_zeit(sync, clip, t_gemeinsam, drift=True, unsicher=False):
    """Zeit auf der gemeinsamen Zeitachse -> Zeit im Clip, None wenn der Clip den Moment nicht zeigt."""
    e = sync["clips"][_key(sync, clip)]
    ab = _abbildung(e, drift, unsicher)
    if ab is None:
        return None
    t = (t_gemeinsam - ab[1]) / ab[0]
    return t if 0.0 <= t <= e["dauer_s"] else None


def zeit_in(sync, von_clip, t, nach_clip, drift=True, unsicher=False):
    """Zeit t in Clip A entspricht welcher Zeit in Clip B? None, wenn t nicht in A liegt, B den Moment nicht zeigt oder
    einer der beiden Clips nicht brauchbar zugeordnet ist (unsicher=True nimmt auch den Vorschlag eines mehrdeutigen)."""
    ea = sync["clips"][_key(sync, von_clip)]
    if not 0.0 <= t <= ea["dauer_s"]:
        return None
    g = gemeinsam_zeit(sync, von_clip, t, drift, unsicher)
    return None if g is None else clip_zeit(sync, nach_clip, g, drift, unsicher)


def deckt(sync, t_gemeinsam, drift=True, unsicher=False):
    """Namen der Clips (sync-Schlüssel, Referenz zuerst), die den Moment t_gemeinsam zeigen. Nur brauchbar zugeordnete
    Clips, außer unsicher=True."""
    return [k for k in sync["clips"] if clip_zeit(sync, k, t_gemeinsam, drift, unsicher) is not None]


def uebersicht_text(sync, breite=40):
    """Textzeitleiste: eine Zeile je Clip, '#' = Kamera läuft, '?' = Zuordnung unsicher, '.' = aus."""
    cl = sync["clips"]
    ok = {k: e for k, e in cl.items() if e.get("offset_s") is not None}
    if not ok:
        return "Kein Clip eingeordnet."
    t0 = min(e["offset_s"] for e in ok.values())
    t1 = max(e["offset_s"] + e["dauer_s"] for e in ok.values())
    span = max(t1 - t0, 1e-6)
    sp = span / breite
    zeilen = [f"Zeitachse {t0:.1f} bis {t1:.1f} s (Ref {sync['ref']}), 1 Zeichen = {sp:.2f} s"]
    zaehler = [0] * breite
    lab = max(len(k) for k in cl) + 2
    for k, e in cl.items():
        if e.get("offset_s") is None:
            zeilen.append(f"{k:<{lab}}|{'-' * breite}| nicht eingeordnet")
            continue
        a, b = e["offset_s"], e["offset_s"] + e["dauer_s"]
        zeichen = "#" if e.get("brauchbar") else "?"
        bal = ""
        for c in range(breite):
            lo, hi = t0 + c * sp, t0 + (c + 1) * sp
            an = min(hi, b) - max(lo, a) > 0.3 * sp
            bal += zeichen if an else "."
            zaehler[c] += an
        ref = " Ref" if k == sync["ref"] else ""
        zeilen.append(f"{k:<{lab}}|{bal}| {a:+.1f} bis {b:+.1f} s{ref}")
    zeilen.append(f"{'Kameras':<{lab}}|{''.join(str(min(z, 9)) if z else '.' for z in zaehler)}|")
    skala = [" "] * breite
    schritt = next(s for s in (1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1800, 3600) if span / s <= breite / 6)
    tt = math.ceil(t0 / schritt) * schritt
    while tt < t1:
        c = int((tt - t0) / sp)
        txt = f"{tt:g}"
        if c + len(txt) <= breite:
            skala[c:c + len(txt)] = txt
        tt += schritt
    zeilen.append(f"{'s':<{lab}}|{''.join(skala)}|")
    for k, e in cl.items():
        for wtxt in e.get("warnungen", [])[:2]:
            zeilen.append(f"  {k}: {wtxt}")
    return "\n".join(zeilen)


def _kurz(sync):
    """Kurze Zusammenfassung für die Konsole (handyfreundlich)."""
    z = []
    for k, e in sync["clips"].items():
        if k == sync["ref"]:
            z.append(f"{k}: Referenz, {e['dauer_s']:.1f} s")
            continue
        if e["offset_s"] is None:
            z.append(f"{k}: NICHT eingeordnet")
            continue
        d = "" if e["drift_ppm"] is None else f", Drift {round(e['drift_ppm']):+d} ppm"
        m = "" if e["brauchbar"] else "  UNSICHER" + (" (mehrdeutig)" if e["mehrdeutig"] else "")
        z.append(f"{k}: {e['offset_s']:+.4f} s, Konfidenz {e['konfidenz']:.2f}{d}{m}")
    return "\n".join(z)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "uebersicht":
        ap = argparse.ArgumentParser(prog="sync.py uebersicht", description="Textzeitleiste aus sync.json")
        ap.add_argument("datei", nargs="?", default="sync.json")
        ap.add_argument("--breite", type=int, default=40)
        a = ap.parse_args(argv[1:])
        print(uebersicht_text(laden(a.datei), a.breite))
        return 0
    ap = argparse.ArgumentParser(prog="sync.py", description="Mehrkamera-Sync über den Ton (siehe Kopf der Datei)")
    ap.add_argument("clips", nargs="+", help="Kürzel (5315, IMG_5315) oder Dateien, mindestens zwei")
    ap.add_argument("--ref", help="Referenz (Kürzel), Standard der erste Clip")
    ap.add_argument("--max", type=float, default=300, help="Suchfenster +-Sekunden (Standard 300)")
    ap.add_argument("-o", "--out", default="sync.json")
    a = ap.parse_args(argv)
    try:
        s = sync_clips(a.clips, ref=a.ref, max_s=a.max, melde=lambda t: print(t, file=sys.stderr))
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"FEHLER {e}", file=sys.stderr)
        return 1
    speichern(s, a.out)
    print(_kurz(s))
    for k, e in s["clips"].items():
        for w in e["warnungen"]:
            print(f"WARNUNG {k}: {w}")
    print(f"geschrieben: {a.out}  (Zeitleiste: python3 sync.py uebersicht {a.out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
