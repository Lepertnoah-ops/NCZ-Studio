#!/usr/bin/env python3
"""
oton.py - O-Ton-Suche (Stil-Leitfaden Regel 1): was im Ton eines Clips zu hören ist und wo.

YAMNet (Google, AudioSet, 521 Klassen; ../modelle/yamnet/, läuft mit onnxruntime auf der CPU) hört den Ton in
Fenstern von 0,96 s alle 0,48 s. Die Klassen sind zu Gruppen zusammengefasst:
  Rufe (Rufen, Jubeln, Anfeuern), Klatschen, Lachen, Sprache, Atmen (Keuchen, Stöhnen), Training (Aufprall,
  Scheppern, Schritte, Seil), Musik, Wind, Stille.

Pro Clip, in oton.md (kurz) und oton.json (mit Zeitreihen):
  vorn      Stellen für oton="vorn" (O-Ton-Moment, Einstieg, Ausklang): Rufe, Jubel, Klatschen, Lachen, Keuchen,
            kurze Zurufe, mit Quellzeit von-bis und Spitze; die besten zuerst. Längere Sprache heißt „Gespräch“
            und passt nur in den Einstieg.
  leise     ob der Ton unter dem Song taugt (oton="leise"): Training, Atmen, Stimmen, ohne Wind und Musik.
  Hinweise  Musik aus der Box (O-Ton dann nur im Einstieg mit EINSTIEG_SONG = "aus", sonst laufen zwei Songs
            übereinander), Wind am Mikro, langes Gespräch, sehr leise, kein Ton.

Beispiele (aus /home/user; R = Reel-Ordner, Clip-Ton aus ingest.py/extract.py in $REEL_WORK/audio/):
  python3 /mnt/project-files/tools/analyse/oton.py -o $R/schnitt/analyse
  python3 /mnt/project-files/tools/analyse/oton.py --nur IMG_6166,IMG_3419 -o $R/schnitt/analyse
  python3 /mnt/project-files/tools/analyse/oton.py clip.MOV ton.flac -o /tmp/oton      # beliebige Dateien

Als Modul:
  from oton import laden, hoeren, auswerten
  wav = laden("IMG_3432.flac"); r = auswerten("IMG_3432", wav, hoeren(wav)); print(r["vorn"][:1], r["hinweise"])

Grenzen: YAMNet erkennt Geräuscharten, versteht aber keine Worte (was gerufen wird, weiß es nicht), und alles ist
gemessen, nicht gehört. O-Ton-Stellen vor der Abgabe im Vorschau-Video anhören.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

MODELL = Path(__file__).resolve().parent.parent / "modelle" / "yamnet"
SR = 16000
HOP = 0.48                # s zwischen zwei Fenstern
FENSTER = 0.96            # s pro Fenster

# Gruppe: AudioSet-Klassen (Namen wie in yamnet_class_map.csv) und Schwelle, ab der die Gruppe als hörbar zählt
GRUPPEN = {
    "Rufe": (["Shout", "Bellow", "Whoop", "Yell", "Children shouting", "Screaming", "Cheering", "Chant"], 0.15),
    "Klatschen": (["Clapping", "Applause", "Hands"], 0.2),
    "Lachen": (["Laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"], 0.15),
    "Sprache": (["Speech", "Conversation", "Narration, monologue", "Babbling", "Chatter", "Crowd",
                 "Hubbub, speech noise, speech babble"], 0.5),
    "Atmen": (["Breathing", "Gasp", "Pant", "Grunt", "Groan", "Wheeze", "Sigh", "Snort"], 0.1),
    "Training": (["Thump, thud", "Thunk", "Bang", "Slap, smack", "Whack, thwack", "Clang", "Clatter", "Chink, clink",
                  "Rattle", "Whip", "Walk, footsteps", "Run", "Bouncing", "Basketball bounce", "Whoosh, swoosh, swish",
                  "Scrape"], 0.1),
    "Musik": (["Music", "Hip hop music", "Rapping", "Singing"], 0.3),
    "Wind": (["Wind", "Wind noise (microphone)", "Rustling leaves"], 0.2),
    "Stille": (["Silence"], 0.5),
}
VORN = {"Rufe": 1.0, "Klatschen": 1.0, "Lachen": 1.0, "Atmen": 0.8, "Sprache": 0.6}   # Gewicht als O-Ton-Moment
NAMEN = {"Rufe": "Rufe/Jubel", "Atmen": "Keuchen/Atmen", "Sprache": "Zuruf"}
LEISE_GUT = ("Training", "Atmen", "Rufe", "Klatschen", "Lachen", "Sprache")


def _ort():
    """onnxruntime; fehlt es, einmal per pip nachinstallieren (braucht pypi im Netzwerk, wie pillow-heif in reelcfg.py)."""
    try:
        import onnxruntime
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--root-user-action=ignore",
                        "--break-system-packages", "onnxruntime==1.30.0"], check=True)
        import onnxruntime
    onnxruntime.set_default_logger_severity(3)
    return onnxruntime


_SITZUNG = {}


def _modell():
    if not _SITZUNG:
        ort = _ort()
        _SITZUNG["s"] = ort.InferenceSession(str(MODELL / "yamnet.onnx"), providers=["CPUExecutionProvider"])
        _SITZUNG["mel"] = np.load(MODELL / "mel_matrix.npy")
        import csv
        with open(MODELL / "yamnet_class_map.csv", newline="") as f:
            _SITZUNG["klassen"] = [r["display_name"] for r in csv.DictReader(f)]
    return _SITZUNG


def laden(pfad):
    """Ton einer Datei (Video oder Audio) als Mono, 16 kHz, float32; None ohne Tonspur."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(pfad), "-map", "0:a:0", "-ac", "1", "-ar", str(SR),
                        "-f", "f32le", "pipe:1"], capture_output=True)
    if r.returncode != 0 or len(r.stdout) < 4:
        return None
    return np.frombuffer(r.stdout, np.float32).copy()


def merkmale(wav):
    """Log-Mel-Stücke 96×64 wie YAMNet (features.py): periodisches Hann 25 ms, Hop 10 ms, FFT 512, 64 Mel-Bänder
    125-7500 Hz, log(x + 0,001), Stücke 0,96 s alle 0,48 s. Gegen TensorFlow geprüft (Abweichung < 2e-6)."""
    n, mn, hop = len(wav), 15600, 7680
    pad = max(0, mn - n)
    after = max(n, mn) - mn
    pad += hop * int(np.ceil(after / hop)) - after
    w = np.pad(wav.astype(np.float32), (0, pad))
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(400) / 400)).astype(np.float32)
    nf = 1 + (len(w) - 400) // 160
    idx = np.arange(400)[None, :] + 160 * np.arange(nf)[:, None]
    mag = np.abs(np.fft.rfft(w[idx] * win, n=512)).astype(np.float32)
    lm = np.log(mag @ _modell()["mel"] + 0.001)
    k = 1 + (nf - 96) // 48
    return np.stack([lm[48 * i:48 * i + 96] for i in range(k)]).astype(np.float32)


def hoeren(wav):
    """YAMNet-Werte (0-1) je Fenster: Array Fenster × 521 Klassen."""
    m = _modell()
    return m["s"].run(None, {"patches": merkmale(wav)})[0]


def pruefsignal():
    """4 s fester Prüfton (16 kHz) für den Selbsttest gegen ../modelle/yamnet/pruefung.npy:
    Klang mit Obertönen, Stille, Gleitton 200-4000 Hz, Klicks alle 0,1 s."""
    t = np.arange(4 * SR) / SR
    x = np.zeros_like(t)
    a, b, c = t < 1, (t >= 2) & (t < 3), t >= 3
    x[a] = sum(0.2 / k * np.sin(2 * np.pi * 220 * k * t[a]) for k in range(1, 6))
    x[b] = 0.3 * np.sin(2 * np.pi * (200 * (t[b] - 2) + 1900 * (t[b] - 2) ** 2))
    x[c] = 0.5 * (((t[c] - 3) % 0.1) < 0.002)
    return x.astype(np.float32)


def _lufs(wav):
    try:
        import pyloudnorm as pyln
        L = pyln.Meter(SR).integrated_loudness(wav.astype(np.float64))
    except Exception:
        L = float("-inf")
    if not np.isfinite(L):
        rms = float(np.sqrt(np.mean(wav.astype(np.float64) ** 2)))
        L = 20 * np.log10(rms + 1e-12) - 0.691
    return float(L)


def pz(x):
    return f"{100 * x:.0f} %"


def _laeufe(maske):
    """[(erster, letzter)] zusammenhängender True-Fenster."""
    out, i, n = [], 0, len(maske)
    while i < n:
        if maske[i]:
            j = i
            while j + 1 < n and maske[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def auswerten(name, wav, werte, datei=None):
    """Gruppen-Zeitreihen, Anteile, O-Ton-Stellen (vorn), Eignung leise und Hinweise eines Clips."""
    klassen = _modell()["klassen"]
    dauer = len(wav) / SR
    n = len(werte)
    zeit = np.round(np.arange(n) * HOP, 2)                            # Fensteranfang in s (Quellzeit)
    pegel = np.array([20 * np.log10(np.sqrt(np.mean(wav[int(t * SR):int((t + FENSTER) * SR)] ** 2)) + 1e-9)
                      if int(t * SR) < len(wav) else -120.0 for t in zeit])
    G, norm = {}, {}
    for g, (namen, schwelle) in GRUPPEN.items():
        ids = [klassen.index(k) for k in namen]
        G[g] = werte[:, ids].max(axis=1)
        norm[g] = G[g] / schwelle
    stumm = pegel < -60
    anteile = {g: round(float(np.mean((norm[g] >= 1) & ~stumm)), 2) for g in GRUPPEN}
    anteile["Stille"] = round(float(np.mean((norm["Stille"] >= 1) | stumm)), 2)
    L = _lufs(wav)
    tonig = pegel[~stumm]
    median = float(np.median(tonig)) if len(tonig) else -120.0

    vorn = []
    kand = np.zeros(n, bool)
    for g in VORN:
        kand |= norm[g] >= 1
    kand &= ~stumm
    for i, j in _laeufe(kand):
        sl = slice(i, j + 1)
        spitzen = {g: float(norm[g][sl].max()) for g in VORN}
        was = max(VORN, key=lambda g: min(spitzen[g], 3.0) * VORN[g] if spitzen[g] >= 1 else 0.0)
        von, bis = float(zeit[i]), float(min(zeit[j] + FENSTER, dauer))
        kurve = np.max([norm[g][sl] * VORN[g] for g in VORN], axis=0)
        k = i + int(np.argmax(kurve))
        hervor = float(pegel[sl].max() - median)
        score = min(spitzen[was], 3.0) * VORN[was] + 0.1 * float(np.clip(hervor, -10, 10))
        stoert = [g for g in ("Musik", "Wind") if np.mean(norm[g][sl] >= 1) > 0.5]
        score *= 0.5 if "Musik" in stoert else 1.0
        score *= 0.7 if "Wind" in stoert else 1.0
        label = NAMEN.get(was, was)
        if was == "Sprache" and bis - von > 5:
            label = "Gespräch"
        elif was == "Sprache" and bis - von > 2.5:
            label = "Sprache"
        vorn.append(dict(von=round(von, 2), bis=round(bis, 2), spitze=round(float(zeit[k] + FENSTER / 2), 2),
                         was=label, staerke=round(float(G[was][sl].max()), 2), pegel_db=round(float(pegel[sl].max()), 1),
                         stoert=stoert, nur_einstieg=label == "Gespräch" or "Musik" in stoert or anteile["Musik"] >= 0.3,
                         score=round(score, 2)))
    vorn.sort(key=lambda m: -m["score"])

    hinweise = []
    if anteile["Musik"] >= 0.3:
        hinweise.append(f"Musik im Ton ({pz(anteile['Musik'])}), wohl aus der Box: O-Ton nur im Einstieg mit "
                        "EINSTIEG_SONG = \"aus\", sonst laufen zwei Songs übereinander")
    if anteile["Wind"] >= 0.25:
        hinweise.append(f"Wind am Mikro ({pz(anteile['Wind'])}): nur kurz und leise")
    sprache = [(i, j) for i, j in _laeufe((norm["Sprache"] >= 1) & ~stumm)]
    if sprache:
        i, j = max(sprache, key=lambda r: r[1] - r[0])
        lang = (j - i) * HOP + FENSTER
        if lang >= 5:
            hinweise.append(f"Gespräch ({lang:.0f} s am Stück ab {zeit[i]:.1f} s): vorn nur im Einstieg, "
                            "leise darunter wirkt unruhig")
    if L < -45 and anteile["Stille"] < 0.9:
        hinweise.append(f"sehr leise ({L:.0f} LUFS): beim Anheben kommt Rauschen mit")

    hoerbar = sorted((g for g in LEISE_GUT if anteile[g] >= 0.1), key=lambda g: -anteile[g])
    if anteile["Stille"] >= 0.9:
        leise = dict(ok=False, text="stumm")
    elif anteile["Musik"] >= 0.3:
        leise = dict(ok=False, text=f"nein, Musik {pz(anteile['Musik'])}")
    elif anteile["Wind"] >= 0.3:
        leise = dict(ok=False, text=f"eher nicht, Wind {pz(anteile['Wind'])}")
    else:
        leise = dict(ok=True, text="ja" + (": " + ", ".join(NAMEN.get(g, g) if g != "Sprache" else "Stimmen"
                                                            for g in hoerbar[:3]) if hoerbar else ", Atmo"))
    top = werte.mean(axis=0).argsort()[::-1][:6]
    return dict(name=name, datei=str(datei) if datei else None, dauer=round(dauer, 2), lufs=round(L, 1),
                anteile=anteile, leise=leise, vorn=vorn[:6], hinweise=hinweise,
                top_klassen=[[klassen[i], round(float(werte[:, i].mean()), 3)] for i in top],
                zeit=zeit.tolist(), pegel_db=np.round(pegel, 1).tolist(),
                gruppen={g: np.round(G[g], 3).tolist() for g in GRUPPEN})


def dateien(eingaben, nur):
    """Eingaben oder alle $REEL_WORK/audio/*.flac; Hardlinks (0001.flac = IMG_0001.flac) nur einmal, --nur filtert."""
    if eingaben:
        fs = []
        for e in map(Path, eingaben):
            fs += sorted(p for p in e.iterdir() if p.suffix.lower() in (".flac", ".wav", ".mov", ".mp4", ".m4a")) \
                if e.is_dir() else [e]
    else:
        d = Path(os.environ.get("REEL_WORK", "/home/user/reel")) / "audio"
        fs = sorted(d.glob("*.flac")) if d.is_dir() else []
    gesehen, out = {}, []
    for f in sorted(fs, key=lambda p: -len(p.stem)):                  # IMG_0001 vor 0001
        try:
            key = (os.stat(f).st_dev, os.stat(f).st_ino)
        except OSError:
            key = f
        if key in gesehen:
            continue
        gesehen[key] = f
        out.append(f)
    if nur:
        ws = [w.strip() for w in nur.split(",") if w.strip()]
        out = [f for f in out if any(f.stem == w or f.stem.endswith(w) or w in f.stem for w in ws)]
    return sorted(out, key=lambda p: p.stem)


def md(res):
    zeilen = [f"# O-Ton im Clip-Ton ({dt.date.today():%d.%m.%Y})", "",
              "Gemessen mit YAMNet, nicht angehört. vorn = Stellen für oton=\"vorn\" (O-Ton-Moment, Einstieg, "
              "Ausklang), Zeiten = Quellzeit im Clip (src), die besten zuerst; leise = taugt unter dem Song "
              "(oton=\"leise\").", "",
              "| Clip | Ton | leise | vorn (Quellzeit, Spitze) | Hinweise |", "|---|---|---|---|---|"]
    for r in res:
        if r.get("kein_ton"):
            zeilen.append(f"| {r['name']} | kein Ton | nein | | Clip ohne Tonspur |")
            continue
        v = " · ".join(f"{m['von']:.1f}–{m['bis']:.1f} s {m['was']} ({m['spitze']:.1f})"
                       + (" (nur Einstieg)" if m["nur_einstieg"] else "") for m in r["vorn"][:3])
        zeilen.append(f"| {r['name']} | {r['dauer']:.1f} s, {r['lufs']:.0f} LUFS | {r['leise']['text']} | {v or '–'} | "
                      f"{'; '.join(r['hinweise']) or '–'} |")
    return "\n".join(zeilen) + "\n"


def main():
    ap = argparse.ArgumentParser(description="O-Ton-Suche im Clip-Ton (YAMNet): Stellen für vorn, Eignung für leise")
    ap.add_argument("eingaben", nargs="*", help="Dateien oder Ordner; ohne Angabe alle $REEL_WORK/audio/*.flac")
    ap.add_argument("--nur", help="Komma-Liste von Clip-Namen, z. B. IMG_6166,IMG_3419 oder 6166")
    ap.add_argument("-o", "--out", required=True, help="Ausgabeordner für oton.md und oton.json")
    a = ap.parse_args()
    fs = dateien(a.eingaben, a.nur)
    if not fs:
        sys.exit("keine Tondateien gefunden (Clip-Ton liegt nach ingest.py/extract.py in $REEL_WORK/audio/)")
    res = []
    for f in fs:
        wav = laden(f)
        if wav is None or len(wav) < SR // 10:
            res.append(dict(name=f.stem, datei=str(f), kein_ton=True))
            print(f"{f.stem}: kein Ton")
            continue
        r = auswerten(f.stem, wav, hoeren(wav), f)
        res.append(r)
        best = r["vorn"][0] if r["vorn"] else None
        print(f"{f.stem}: {r['dauer']:.1f} s, {r['lufs']:.0f} LUFS, leise {r['leise']['text']}"
              + (f", vorn {best['von']:.1f}-{best['bis']:.1f} s {best['was']}" if best else ", nichts für vorn")
              + (f" ({'; '.join(r['hinweise'])})" if r["hinweise"] else ""))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "oton.json").write_text(json.dumps(dict(modell="YAMNet (AudioSet), Fenster 0,96 s alle 0,48 s",
                                                   gruppen={g: v[0] for g, v in GRUPPEN.items()}, clips=res),
                                              ensure_ascii=False))
    (out / "oton.md").write_text(md(res))
    print(f"-> {out / 'oton.md'}, {out / 'oton.json'}")


if __name__ == "__main__":
    main()
