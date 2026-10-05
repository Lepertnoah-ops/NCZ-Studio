#!/usr/bin/env python3
"""Interview-Reel bauen: Schnitt an Wortgrenzen, Untertitel Wort für Wort, Song leise darunter.

    cd /home/user && python3 <projekt>/tools/pipeline/interview.py <reel>/schnitt/schnitt.json [--export]
    … --trocken: nur Phrasen auflösen und Teile mit Zeiten zeigen (Sekunden, ohne Rendern)
    … --enden: wie --trocken, dazu je Teil das letzte Wort mit Pegelverlauf und Schnittpunkt (Wortenden prüfen)
    … --plattform youtube: YouTube-Shorts-Fassung: Abspann ohne „LINK IN BIO“, Untertitel und Abspann
      höchstens 77 % der Breite (Rand rechts für die Bedienleiste), Export mit dem YouTube-Profil aus plattform.py
      (12/16 Mbit/s, GOP 15, −14 LUFS, True Peak −1 dBTP) als <name>_yt_mit_song.mp4, _yt_ohne_song.mp4 (Content-ID-sicher,
      nur Stimme), _yt_titelbild.jpg; Vorschau <name>_yt_vorschau.mp4. Teile und Zwischenbild bleiben gemeinsam
      genutzt, nur Abspann, Untertitel und Master sind eigene Dateien (…_yt). Instagram bleibt der Standard.
    … --titelbild <s>: nur das Titelbild neu ziehen (Sekunde im Reel, Bild ohne Untertitel aus dem letzten Lauf);
      ohne Angabe gilt titelbild aus schnitt.py, sonst 0,5 s. Ansehen: Augen offen, Blick in die Kamera, Gesicht im
      mittleren 1080×1440-Bereich (0,5 s ist oft ein Blinzeln)

Ohne --export: Vorschau zur Freigabe, <reel>/<name>_vorschau.mp4 (720×1280 plus Info-Leiste: Teil-Nr. wie im
Storyboard, Clip, Quellzeit, Text, Zeitleiste) und <reel>/<name>_storyboard.jpg (je Teil ein Bild mit Text).
Mit --export (erst nach dem OK des Nutzers): <name>_mit_song.mp4 (Stimme + Song), <name>_ohne_song.mp4 (nur Stimme, Song
dann in Instagram dazulegen), <name>_titelbild.jpg; alle 1080×1920, 30 fps, H.264 High 4.1 in 2 Pässen (18/25 Mbit/s,
wie export.py), AAC 320k, 48 kHz. Danach prüft
pruefen() jede Datei (Format, Länge Bild = Ton, 40–60 s, −14 LUFS, True Peak) und meldet OK oder PRÜFEN.

schnitt.json schreibt schnitt/schnitt.py im Reel (Vorlage: reels/_vorlage/interview/schnitt.py):
  name, clips {kürzel: Videodatei}, transkript (Ordner mit <kürzel>.json aus analyse/transkript.py),
  song {datei, start (s im Song), unter_sprache (dB unter der Stimme, Standard 14), in_pausen (dB, Standard 6),
        fade_ende (s, Standard 1,2)}, ersetzen {falsch: richtig} (Wortkorrekturen fürs ganze Reel),
  teile [{clip, von, bis (Quellzeit s, an Wortgrenzen), zoom (1 = ganzes Bild, bis ~1,6 bei 4K), fokus [x, y]
         (Gesicht, 0–1 im Hochformat; ohne: Gesicht automatisch, YuNet), text (ersetzt die Wörter dieses
         Teils; gleiche Wortzahl = Zeiten bleiben, „_“ blendet ein Wort aus; sonst verteilt), stil ("frage" =
         Frage hinter der Kamera, Text oben, blendet kopf_nach s (Standard 1,0) nach dem Ende der Frage weich aus,
         kopf = eigener Fragetext),
         untertitel (false = keine), anfang/ende (Schnittzeit in s Quellzeit, wenn die Pausensuche danebenliegt;
         die Untertitel bleiben bei den Wörtern der Phrase), plus (s nach dem Schnitt dranhängen), notiz,
         kuerzen (true oder {pause_max, pause_ziel, stark, zoegern}: Pausen und Füllwörter kürzen, teilt den Teil in Stücke
         „#7a, #7b“, siehe kuerzen.py; auch in der Konfiguration für alle Teile, false am Teil schaltet es aus),
         bild [{clip | kamera, src (Quellzeit im Bild-Clip), ab (s nach Teilanfang) oder bei (Quellzeit im Sprecherclip),
         dauer, zoom, fokus}] (B-Roll oder andere Kamera über die Stimme: das Bild wird ersetzt, der Ton des Teils läuft
         weiter, die Untertitel bleiben; kamera + sync: Zeit aus sync.json, siehe sync.py)}],
  sync (Pfad zu sync.json aus pipeline/sync.py, nur für bild mit kamera),
  abspann {zeilen [Zeilen der Einblendung, siehe abspann_rendern], mitte, mindestens (s nach dem letzten Teil,
           Standard 2,6; endet auf der nächsten Eins des Songs), blende (s Überblendung, Standard 0,6)}
Schnitt: Anfang am Ende der letzten Pause (ab 100 ms) vor dem ersten Wort. Ende: erste Pause ab 150 ms nach dem
letzten Wort (kürzere Lücken sind Verschlusslaute mitten im Wort, Whisper setzt Wortenden oft zu früh), dann bis
0,15 s Ausklang, mindestens 60 ms vor dem nächsten Einsatz; ohne Pause die leiseste Stelle an der Wortgrenze
und eine Warnung („ohne Pause geschnitten“): dann Spektrum ansehen und mit ende=/anfang= von Hand setzen.
Ton: Stimme je Teil auf gleiche Lautheit, Hochpass 100 Hz, leichte Entrauschung (afftdn 10 dB), sanfter
Kompressor, 8-ms-Blenden an jedem Schnitt;
Song ab start, unter Sprache -unter_sprache dB (Bezug: Stimme), in Pausen ab 0,6 s -in_pausen dB, Präsenz-Delle
2,8 kHz, am Ende fade_ende; Mix auf -14 LUFS, Spitze -1,5 dBFS. Bild: 4K-Quelle, Ausschnitt nach zoom/fokus
(Gesicht bei 50 % Breite, 38 % Höhe), 1080×1920, 30 fps, Look aus stil.json, Untertitel aus vfx/untertitel.py.
Prüft: Schnitt mitten im Wort, Teile unter 0,5 s, Länge, unsichere Wörter (p < 0,5) in genutzten Teilen.
Arbeitsdateien in $REEL_WORK/interview/ (Teile bleiben gültig, solange clip/von/bis/zoom/fokus gleich sind).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "vfx"))
from untertitel import FONTS, ass, sauber  # noqa: E402

WORK = Path(os.environ.get("REEL_WORK", "/home/user/reel"))
OUT = WORK / "interview"
import plattform as pf  # noqa: E402  (Profile: instagram Standard; --plattform youtube = Shorts-Fassung)
import kuerzen as pausen  # noqa: E402  (Pausen und Füllwörter kürzen; kuerzen heißt in main() schon eine Variable)

if "--plattform" in sys.argv and "," in sys.argv[sys.argv.index("--plattform") + 1]:
    sys.exit("interview.py: eine Plattform je Lauf (Untertitel und Abspann unterscheiden sich), nacheinander starten")
PROFIL = pf.profil(sys.argv[sys.argv.index("--plattform") + 1] if "--plattform" in sys.argv else "instagram")
SUFFIX = PROFIL["suffix"]                                   # "" bei Instagram, "_yt" bei YouTube
MAX_BREITE_PLATTFORM = PROFIL["text_breite"] if SUFFIX else None   # Instagram: Standard 0,84 der Untertitel-Bibliothek
W, H, FPS, SR = 1080, 1920, 30, 48000
ZIEL_STIMME = -16.0  # LUFS der Stimme vor dem Mix


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"Fehler: {' '.join(map(str, cmd))[:400]}\n{r.stderr[-1500:]}")
    return r


def look():
    """Look aus stil.json als ffmpeg-Filterliste (leer ohne Look), wie render.py."""
    from reelcfg import look_spec, looks_module
    p = looks_module().lut_path(look_spec())
    return [f"lut3d={p}:interp=tetrahedral"] if p else []


def lesen(p, kanaele=1, start=None, dauer=None):
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{start:.4f}"] if start is not None else []) + ["-i", str(p)]
    cmd += (["-t", f"{dauer:.4f}"] if dauer else []) + ["-f", "f32le", "-ac", str(kanaele), "-ar", str(SR), "-"]
    x = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32).copy()
    return x.reshape(-1, kanaele) if kanaele > 1 else x


def schreiben(p, x):
    x = np.asarray(x, np.float32)
    ch = 1 if x.ndim == 1 else x.shape[1]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ac", str(ch), "-ar", str(SR), "-i", "-",
                    "-c:a", "pcm_s24le", str(p)], input=x.tobytes(), check=True)


def lufs(x):
    """Integrierte Lautheit (BS.1770, gated, Stereo richtig gezählt) über ffmpeg ebur128; zu kurz -> RMS-Näherung."""
    tmp = OUT / "_mess.wav"
    schreiben(tmp, x)
    r = subprocess.run(["ffmpeg", "-nostats", "-i", str(tmp), "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    if m and float(m[-1]) > -69:
        return float(m[-1])
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9) - 0.7)


def kurzzeit(x, rate=100):
    """Kurzzeit-Lautheit (3 s, ebur128 S) als Kurve mit Steuerrate rate, auf die Fenstermitte geschoben."""
    tmp = OUT / "_mess.wav"
    schreiben(tmp, x)
    r = subprocess.run(["ffmpeg", "-nostats", "-i", str(tmp), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)  # Zeilen je 100 ms kommen nur ohne framelog=quiet
    tv = [(float(a), float(b)) for a, b in re.findall(r"t:\s*([\d.]+)\s.*?S:\s*(-?[\d.]+)", r.stderr)]
    t = np.array([a - 1.5 for a, b in tv])
    v = np.array([b for a, b in tv])
    ok = v > -70
    n = int(len(x) / SR * rate) + 1
    return np.interp(np.arange(n) / rate, t[ok], v[ok]) if ok.any() else np.full(n, -30.0)


def gesicht(datei, von, bis):
    """Mitte des größten Gesichts (x, y in 0–1 des Hochformats) aus 5 Frames (YuNet, modelle/yunet), sonst None."""
    import cv2
    modell = TOOLS / "modelle/yunet/face_detection_yunet_2023mar.onnx"
    if not hasattr(cv2, "FaceDetectorYN") or not modell.exists():
        return None
    det = cv2.FaceDetectorYN.create(str(modell), "", (540, 960), 0.7)
    pts = []
    for k in range(5):
        t = von + (bis - von) * (k + 0.5) / 5
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(datei), "-frames:v", "1", "-vf",
                            "scale=540:960", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR) if r.stdout else None
        if img is None:
            continue
        _, f = det.detect(img)
        if f is not None and len(f):
            x, y, w, h = max(f, key=lambda b: b[2] * b[3])[:4]
            pts.append(((x + w / 2) / 540, (y + h / 2) / 960))
    return [round(float(v), 3) for v in np.median(np.array(pts), axis=0)] if pts else None


def quelle(datei):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:"
             "stream_side_data=rotation", "-of", "json", datei])
    st = json.loads(r.stdout)["streams"][0]
    rot = next((abs(int(sd["rotation"])) for sd in st.get("side_data_list", []) if "rotation" in sd), 0)
    return (st["height"], st["width"]) if rot in (90, 270) else (st["width"], st["height"])


def ausschnitt(zoom, fokus, sw, sh):
    cw = int(round(min(sw, sh * 9 / 16) / zoom / 2) * 2)
    ch = int(round(cw * 16 / 9 / 2) * 2)
    fx, fy = fokus
    x0 = min(max(fx * sw - cw / 2, 0), sw - cw)
    y0 = min(max(fy * sh - 0.38 * ch, 0), sh - ch)
    return cw, ch, int(x0) // 2 * 2, int(y0) // 2 * 2


def woerter(tr, t, ersetzen):
    ws = [w for sg in tr["segmente"] for w in sg["woerter"]]
    # Wörter der Phrase nach Index (Ausklang und plus hängen nie ein Wort an), sonst nach Zeit
    sel = [dict(w) for k, w in enumerate(ws)
           if (k >= t["_w0"] if "_w0" in t else
               (w["e"] > t["von"] + 0.08 and (w["s"] >= t["von"] - 0.15 or (w["s"] + w["e"]) / 2 >= t["von"])))
           and (k <= t["_w1"] if "_w1" in t else w["s"] < t["bis"] - 0.08)
           and k not in t.get("_weg", ())]
    if t.get("text"):
        neu = t["text"].split()
        if len(neu) == len(sel):
            for w, x in zip(sel, neu):
                w["w"], w["p"] = x, 1.0
        else:  # Zeiten nach Zeichenzahl über die Sprechdauer verteilen
            s0 = sel[0]["s"] if sel else t["von"]
            e0 = sel[-1]["e"] if sel else t["bis"]
            gew = np.cumsum([0] + [len(x) + 1 for x in neu]) / (sum(len(x) + 1 for x in neu))
            sel = [dict(w=x, s=s0 + (e0 - s0) * gew[k], e=s0 + (e0 - s0) * gew[k + 1] - 0.02, p=1.0)
                   for k, x in enumerate(neu)]
    sel = [w for w in sel if w["w"] != "_"]  # „_“ im Ersatztext: Wort nicht untertiteln
    for w in sel:
        kern = re.sub(r"[^\wÄÖÜäöüß'-]", "", w["w"])
        w["e"] = min(w["e"], w["s"] + max(0.45, 0.11 * len(kern)))  # von Whisper gedehnte Wörter kappen
        for alt, neu in ersetzen.items():
            if kern.lower() == alt.lower():
                w["w"] = w["w"].replace(kern, neu)
        w["s"], w["e"] = max(w["s"], t["von"]), min(w["e"], t["bis"])
    return sel


def norm(x):
    return re.sub(r"[^\wÄÖÜäöüß]", "", x.lower())


def finde(ws, phrase, ab=0.0):
    """Index des ersten und letzten Worts der Phrase (erster Treffer ab Quellzeit ab)."""
    toks = [norm(x) for x in phrase.split() if norm(x)]
    wn = [norm(w["w"]) for w in ws]
    for i in range(len(ws) - len(toks) + 1):
        if ws[i]["s"] >= ab - 0.01 and wn[i:i + len(toks)] == toks:
            return i, i + len(toks) - 1
    sys.exit(f"Phrase nicht im Transkript gefunden: „{phrase}“ (ab {ab} s)")


_HUELLE = {}


def huelle_clip(clip, datei):
    """Pegel der Quelle in dB (RMS 30 ms, alle 5 ms)."""
    if clip not in _HUELLE:
        ton = WORK / "audio" / f"{clip}.flac"
        x = lesen(ton if ton.exists() else datei)
        hop, win = SR // 200, int(SR * 0.03)
        n = max(1, (len(x) - win) // hop)
        e = np.array([np.mean(x[k * hop:k * hop + win] ** 2) for k in range(n)])
        _HUELLE[clip] = 10 * np.log10(e + 1e-12)
    return _HUELLE[clip]


LUFT = 0.15  # s Ausklang nach dem letzten Wort, wenn die Pause lang genug ist (nie ins Wort schneiden)


def schnittpunkt(clip, datei, a, b, seite, rand=None):
    """Schnitt zwischen a und b (Quellzeit). Gesucht wird eine echte Pause (höchstens 4 dB über dem Grundrauschen
    des Clips): seite "von" nimmt das Ende der letzten Pause ab 100 ms vor dem Wort. seite "bis" nimmt die erste
    Pause ab 150 ms, die vor b beginnt (sie darf über b hinausgehen), und schneidet nach bis zu LUFT Ausklang,
    mindestens 60 ms vor ihrem Ende. Ohne Pause (Redefluss, leise Silben) die leiseste Stelle im Bereich
    rand = (von, bis) um die Wortgrenze von Whisper. Gibt (Zeit, Pegel dB, Pause gefunden) zurück."""
    env = huelle_clip(clip, datei)
    bis_ = seite != "von"
    i0 = max(0, int(a * 200))
    i1 = min(len(env), int((b + (0.6 if bis_ else 0)) * 200) + 1)
    ruhig = env[i0:i1] <= float(np.percentile(env, 5)) + 4
    laeufe, k = [], 0
    while k < len(ruhig):
        if ruhig[k]:
            j = k
            while j < len(ruhig) and ruhig[j]:
                j += 1
            if j - k >= (30 if bis_ else 20) and (not bis_ or k <= (b - a) * 200):
                laeufe.append((k, j))
            k = j
        k += 1
    if laeufe and not bis_:
        k = i0 + laeufe[-1][1] - 1
        return round(k / 200, 3), float(env[k]), True
    if laeufe:
        k, j = laeufe[0]
        luft = max(0.035, min(LUFT, (j - k) / 200 - 0.06))
        return round((i0 + k) / 200 + luft, 3), float(env[i0 + k]), True
    r0, r1 = rand or (a, b)
    j0, j1 = max(0, int(r0 * 200)), min(len(env), int(r1 * 200) + 1)
    if j1 - j0 < 2:
        return round((r0 + r1) / 2, 3), float(env[min(max(j0, 0), len(env) - 1)]), False
    k = j0 + int(np.argmin(env[j0:j1]))
    return round(k / 200 + 0.015, 3), float(env[k]), False


def aufloesen(t, ws, datei):
    """von/bis als Phrase -> Quellzeit. Gesucht wird eine ruhige Stelle zwischen dem Wort davor und dem ersten
    Wort (bis 30 % in das Wort hinein, falls die Wortzeiten von Whisper etwas daneben liegen), am Ende genauso.
    Legt t["_tiefe"] = Pegel an den Schnitten ab (für die Prüfung: ohne Pause wird im Redefluss geschnitten)."""
    tiefe, ohne = [], []
    if isinstance(t["von"], str):
        i, _ = finde(ws, t["von"], t.get("ab", 0.0))
        s, e = ws[i]["s"], ws[i]["e"]
        a = max(ws[i - 1]["s"] + 0.5 * (ws[i - 1]["e"] - ws[i - 1]["s"]), s - 0.35) if i else s - 0.35
        t["_von"], t["_w0"] = t["von"], i
        t["von"], lv, ok = schnittpunkt(t["clip"], datei, a, s + 0.3 * (e - s), "von",
                                        rand=(max(a, s - 0.3), s + 0.03))
        tiefe.append(lv)
        ohne += [] if ok else ["Anfang"]
    if t.get("anfang") is not None:
        t["von"] = float(t["anfang"])
    if isinstance(t["bis"], str):
        _, j = finde(ws, t["bis"], max(t["von"] - 0.3, t.get("ab", 0.0)))
        s, e = ws[j]["s"], ws[j]["e"]
        nx = ws[j + 1] if j + 1 < len(ws) else None
        b = min(nx["s"] + 0.3 * (nx["e"] - nx["s"]), e + 0.8) if nx else e + 0.8  # Pause muss hier beginnen
        eng = min(nx["s"] + 0.3 * (nx["e"] - nx["s"]), e + 0.35) if nx else e + 0.35  # ohne Pause: hier schneiden
        t["_bis"], t["_w1"] = t["bis"], j
        t["bis"], lb, ok = schnittpunkt(t["clip"], datei, s + 0.6 * (e - s), b, "bis", rand=(e - 0.05, eng))
        tiefe.append(lb)
        ohne += [] if ok else ["Ende"]
    if t.get("ende") is not None:
        t["bis"] = float(t["ende"])
    if t.get("plus"):
        t["bis"] = round(t["bis"] + float(t["plus"]), 3)
    t["_tiefe"], t["_ohne_pause"] = tiefe, ohne
    return t


def stueck_rendern(src, von, n, z, fokus, pfad):
    """n Bilder ab Quellzeit von, auf 1080×1920 bei 30 fps mit dem Look aus stil.json (nur Bild)."""
    sw, sh = quelle(src)
    vf = []
    if z > 1.001 or abs(sw / sh - 9 / 16) > 0.01:
        cw, ch, x0, y0 = ausschnitt(z, fokus or (0.5, 0.35), sw, sh)
        vf.append(f"crop={cw}:{ch}:{x0}:{y0}")
    vf += [f"scale={W}:{H}:flags=lanczos", f"fps={FPS}"] + look() + ["format=yuv420p"]
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{von:.3f}", "-i", src, "-map", "0:v:0", "-vf", ",".join(vf),
         "-frames:v", n, "-c:v", "libx264", "-preset", "fast", "-crf", 14, "-color_primaries", "bt709",
         "-color_trc", "bt709", "-colorspace", "bt709", pfad])


def teil_rendern(i, t, clips):
    src = clips[t["clip"]]
    n = max(1, round((t["bis"] - t["von"]) * FPS))
    z = float(t.get("zoom", 1.0))
    bild = t.get("bild") or []   # B-Roll oder andere Kamera über die Stimme: Bild ersetzt, Ton des Teils läuft weiter
    schl = [t["clip"], round(t["von"], 3), n, z, t.get("_fokus")]
    if bild:
        schl.append([[b["clip"], round(float(b["src"]), 3), round(float(b["ab"]), 3), round(float(b["dauer"]), 3),
                      float(b.get("zoom", 1.0)), b.get("fokus")] for b in bild])
    key = hashlib.md5(json.dumps(schl).encode()).hexdigest()[:10]
    v, a = OUT / f"teil_{i:02d}_{key}.mp4", OUT / f"teil_{i:02d}_{key}.wav"
    if not (v.exists() and a.exists()):
        d = n / FPS
        if not bild:
            sw, sh = quelle(src)
            vf = []
            if z > 1.001 or abs(sw / sh - 9 / 16) > 0.01:
                cw, ch, x0, y0 = ausschnitt(z, t.get("_fokus") or (0.5, 0.35), sw, sh)
                vf.append(f"crop={cw}:{ch}:{x0}:{y0}")
            vf += [f"scale={W}:{H}:flags=lanczos", f"fps={FPS}"] + look() + ["format=yuv420p"]
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t['von']:.3f}", "-i", src,
                 "-map", "0:v:0", "-vf", ",".join(vf), "-frames:v", n, "-c:v", "libx264", "-preset", "fast", "-crf", 14,
                 "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", v,
                 "-map", "0:a:0", "-af", f"atrim=0:{d:.6f}", "-ac", 1, "-ar", SR, "-c:a", "pcm_s24le", a])
        else:
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t['von']:.3f}", "-i", src, "-map", "0:a:0", "-af",
                 f"atrim=0:{d:.6f}", "-ac", 1, "-ar", SR, "-c:a", "pcm_s24le", a])
            stuecke, pos = [], 0     # (Quelle, Quellzeit, Bilder, Zoom, Fokus) in Reihenfolge, Bildzahl je Stück
            for b in sorted(bild, key=lambda x: float(x["ab"])):
                fa = min(n, max(pos, round(float(b["ab"]) * FPS)))
                nb = min(n - fa, max(1, round(float(b["dauer"]) * FPS)))
                if fa > pos:
                    stuecke.append((src, t["von"] + pos / FPS, fa - pos, z, t.get("_fokus")))
                if nb > 0:
                    stuecke.append((clips[b["clip"]], float(b["src"]), nb, float(b.get("zoom", 1.0)), b.get("fokus")))
                pos = fa + nb
            if pos < n:
                stuecke.append((src, t["von"] + pos / FPS, n - pos, z, t.get("_fokus")))
            liste, teile_ = [], []
            for k, (q, von, nn, zz, fk) in enumerate(stuecke):
                pf_ = OUT / f"teil_{i:02d}_{key}_{k}.mp4"
                stueck_rendern(q, von, nn, zz, fk, pf_)
                liste.append(f"file '{pf_}'\n")
                teile_.append(pf_)
            lp = OUT / f"teil_{i:02d}_{key}_liste.txt"
            lp.write_text("".join(liste))
            run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", 0, "-i", lp, "-c", "copy", v])
            for pf_ in teile_ + [lp]:
                pf_.unlink()
    return v, a, n


def huelle(maske, unten, oben, runter=0.12, rauf=0.5, rate=100):
    """Pegelkurve in dB (Steuerrate 100 Hz): Sprache -> unten, Pause -> oben, schnell runter, langsam rauf."""
    ziel = np.where(maske, unten, oben).astype(float)
    g = np.empty_like(ziel)
    cur = ziel[0]
    dr, du = abs(oben - unten) / (runter * rate), abs(oben - unten) / (rauf * rate)
    for k, z in enumerate(ziel):
        cur = max(cur - dr, z) if z < cur else min(cur + du, z)
        g[k] = cur
    return g


def ton(cfg, teile, audio, ns, alle_woerter, laenge, gesamt=None, blende=0.0):
    roh, gains, nahtlos = [], [], []
    for k, (t, a, n) in enumerate(zip(teile, audio, ns)):
        x = lesen(a)
        m = n * SR // FPS
        roh.append(np.pad(x, (0, max(0, m - len(x))))[:m])
        g = float(np.clip(ZIEL_STIMME - lufs(roh[-1]), -12, 15)) if m > SR * 0.3 else 0.0
        gains.append(10 ** (g / 20) * float(t.get("ton", 1.0)))
        v = teile[k - 1] if k else None  # nahtlos: selber Clip, geht genau am letzten Frame weiter
        nahtlos.append(bool(v and v["clip"] == t["clip"] and abs(t["von"] - (v["von"] + ns[k - 1] / FPS)) < 0.002))
    f = int(0.008 * SR)
    r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, f))
    for k, x in enumerate(roh):  # Blenden nur an echten Schnitten
        if not nahtlos[k]:
            x[:f] *= r
        if k + 1 == len(roh) or not nahtlos[k + 1]:
            x[-f:] *= r[::-1]
    s = np.concatenate(roh)
    kurve = np.concatenate([np.full(len(x), g, np.float32) for x, g in zip(roh, gains)])
    pos = np.cumsum([0] + [len(x) for x in roh])
    for k in range(1, len(roh)):  # an nahtlosen Übergängen die Verstärkung über 60 ms überblenden
        if nahtlos[k]:
            b, h = pos[k], int(0.03 * SR)
            kurve[b - h:b + h] = np.linspace(gains[k - 1], gains[k], 2 * h)
    s = s * kurve
    gesamt = gesamt or laenge
    if gesamt > laenge + 0.01:  # Abspann: O-Ton blendet mit dem Bild aus, danach nur noch der Song
        nb = max(1, int(blende * SR))
        s[-nb:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, nb))).astype(s.dtype)
        s = np.pad(s, (0, max(0, int(round(gesamt * SR)) - len(s))))
    schreiben(OUT / "stimme_roh.wav", s)
    run(["ffmpeg", "-v", "error", "-y", "-i", OUT / "stimme_roh.wav", "-af",
         "highpass=f=100,afftdn=nr=10:tn=1,acompressor=threshold=-24dB:ratio=2.5:attack=8:release=160:makeup=1.5",
         "-ar", SR, "-c:a", "pcm_s24le", OUT / "stimme.wav"])
    s = lesen(OUT / "stimme.wav")
    s *= 10 ** ((ZIEL_STIMME - lufs(s)) / 20)  # mono: so klingt sie später auf beiden Kanälen
    total = len(s)
    song = cfg["song"]
    mus = lesen(song["datei"], 2, song["start"], gesamt + 0.5)[:total]
    mus = np.pad(mus, ((0, total - len(mus)), (0, 0)))
    rate = 100
    kz = kurzzeit(mus, rate)  # Makro-Dynamik des Songs zu 70 % ausgleichen: Intro ohne 808 nicht zu leise,
    ref = float(np.median(kz))  # Beat nach dem Einsatz nicht zu laut unter der Stimme
    ausgleich = -0.7 * (kz - ref)
    maske = np.zeros(int(gesamt * rate) + 2, bool)
    for w in alle_woerter:
        maske[max(0, int((w["s"] - 0.1) * rate)):int((w["e"] + 0.2) * rate)] = True
    # Lücken unter 0,6 s bleiben „Sprache“ (kein Pumpen zwischen Wörtern)
    k = 0
    while k < len(maske):
        if not maske[k]:
            j = k
            while j < len(maske) and not maske[j]:
                j += 1
            if 0 < k and j < len(maske) and (j - k) < 0.6 * rate:
                maske[k:j] = True
            k = j
        k += 1
    stereo = ZIEL_STIMME + 3.0  # die Mono-Stimme liegt später auf beiden Kanälen: +3 LU
    unten = stereo - float(song.get("unter_sprache", 14)) - ref
    oben = stereo - float(song.get("in_pausen", 6)) - ref
    g_db = huelle(maske, unten, oben)
    g_db = g_db + ausgleich[:len(g_db)] if len(ausgleich) >= len(g_db) else g_db + np.pad(ausgleich, (0, len(g_db) - len(ausgleich)), mode="edge")
    tt = np.arange(total) / SR
    g = 10 ** (np.interp(tt, np.arange(len(g_db)) / rate, g_db) / 20)
    fe = float(song.get("fade_ende", 1.2))
    g *= np.clip((gesamt - tt) / fe, 0, 1) ** 1.5 if fe > 0 else 1
    g *= np.clip(tt / 0.03, 0, 1)
    schreiben(OUT / "musik_roh.wav", mus * g[:, None])
    run(["ffmpeg", "-v", "error", "-y", "-i", OUT / "musik_roh.wav", "-af", "equalizer=f=2800:t=o:w=1.2:g=-5",
         "-ar", SR, "-c:a", "pcm_s24le", OUT / "musik.wav"])
    mus = lesen(OUT / "musik.wav", 2)[:total]
    mix = mus + s[:, None]
    fertig = []
    for name, x in (("mix", mix), ("stimme_solo", np.repeat(s[:, None], 2, axis=1))):
        x = x * 10 ** ((-14.0 - lufs(x)) / 20)
        schreiben(OUT / f"{name}_vor.wav", x)
        run(["ffmpeg", "-v", "error", "-y", "-i", OUT / f"{name}_vor.wav", "-af",
             "alimiter=limit=0.84:attack=3:release=60:level=false", "-ar", SR, "-c:a", "pcm_s24le",
             OUT / f"{name}.wav"])
        fertig.append(OUT / f"{name}.wav")
    return fertig, float(np.mean(maske[:int(laenge * rate)]))


def abspann_fuer(absp, profil):
    """Abspann der Plattform: ohne die Zeile „LINK IN BIO“, wenn das Profil keine Link-Zeile hat (YouTube: Links in Shorts
    sind nicht klickbar); sonst unverändert."""
    if profil["link_zeile"] is not None:
        return absp
    return dict(absp, zeilen=[z for z in absp["zeilen"] if str(z.get("text", "")).strip().upper() != "LINK IN BIO"])


def abspann_rendern(absp, dauer, pfad, max_breite=None):
    """Abspann (nach der letzten Szene Fadeout zur Einblendung, Zeilen aus schnitt.py): weiße Schrift auf
    Markenschwarz, Zeile für Zeile aus absp["zeilen"] nacheinander einblendend (0,45 s, steigt 26 px auf), die letzten
    0,5 s Blende nach Schwarz. Die Überblendung aus dem letzten Teil macht xfade im Master.
    Zeile: text, art ("kond" = Antonio Bold mit 1 % Rand für Gewicht, Standard; "mono" = Courier Prime Bold),
    breite (px, Schriftgröße so, dass die Zeile so breit wird) oder cap (Höhe der Großbuchstaben in px),
    spur (Laufweite in em), abstand (px über der Zeile), start (s nach Beginn des Abspanns); oder nur linie (Breite
    in px) für eine dünne Linie. Der Block steht um absp["mitte"] (Anteil der Höhe) zentriert.
    max_breite (Anteil der Bildbreite, Standard keine Grenze): breitere Zeilen werden verkleinert (YouTube: 0,77)."""
    from PIL import Image, ImageDraw, ImageFont
    n = max(1, round(dauer * FPS))
    kond, mono = f"{FONTS}/Antonio-Bold.ttf", f"{FONTS}/CourierPrime-Bold.ttf"
    CAPEM = {kond: 1760 / 2048, mono: 1187 / 2048}  # Großbuchstabenhöhe in em
    ebenen, y = [], 0.0
    for z in absp["zeilen"]:
        y += float(z.get("abstand", 0))
        if "linie" in z:
            m = np.ones((3, int(z["linie"])), np.float32)
            base, hoehe = y + 3, 3
        else:
            art = mono if z.get("art") == "mono" else kond
            spur = float(z.get("spur", 0.0))

            def messen(gr):
                f = ImageFont.truetype(art, gr)
                sw = round(gr * 0.011) if art == kond else 0
                adv = [f.getlength(c) for c in z["text"]]
                for i in range(len(z["text"]) - 1):  # Kerning
                    adv[i] += f.getlength(z["text"][i:i + 2]) - f.getlength(z["text"][i]) - f.getlength(z["text"][i + 1])
                return f, sw, adv, sum(adv) + spur * gr * (len(z["text"]) - 1) + 2 * sw
            gr = z["cap"] / CAPEM[art] if "cap" in z else 100.0
            if "breite" in z:
                gr *= z["breite"] / messen(round(gr))[3]
            if max_breite and messen(round(gr))[3] > max_breite * W:
                gr *= max_breite * W / messen(round(gr))[3]
            gr = round(gr)
            f, sw, adv, w = messen(gr)
            cap = CAPEM[art] * gr
            pad = 6 + sw
            im = Image.new("L", (int(w) + 2 * pad, int(cap * 1.5) + 2 * pad), 0)
            d = ImageDraw.Draw(im)
            x = pad + sw
            for c, a_ in zip(z["text"], adv):
                d.text((x, pad + cap), c, font=f, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
                x += a_ + spur * gr
            m = np.asarray(im, dtype=np.float32) / 255
            base, hoehe = y + cap, cap
            m_oben = pad  # Abstand Bildoberkante -> Kappenoberkante
            ebenen.append(dict(m=m, x=(W - m.shape[1]) // 2, y=y - m_oben, start=float(z.get("start", 0)), h=hoehe))
            y += cap
            continue
        ebenen.append(dict(m=m, x=(W - m.shape[1]) // 2, y=y, start=float(z.get("start", 0)), h=hoehe))
        y += hoehe
    y0 = H * float(absp.get("mitte", 0.44)) - y / 2  # Block mittig
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "12",
                          "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
                          "-colorspace", "bt709", str(pfad)], stdin=subprocess.PIPE)
    for i in range(n):
        tt = i / FPS
        A = np.zeros((H, W), np.float32)
        for e in ebenen:
            q = min(1.0, max(0.0, (tt - e["start"]) / 0.45))
            if q <= 0:
                continue
            q = 1 - (1 - q) ** 3
            yy = int(round(y0 + e["y"] + (1 - q) * 26))
            m = e["m"]
            ys0, ys1 = max(0, yy), min(H, yy + m.shape[0])
            if ys1 > ys0:
                A[ys0:ys1, e["x"]:e["x"] + m.shape[1]] += m[ys0 - yy:ys1 - yy] * q
        aus = min(1.0, max(0.0, (dauer - tt) / 0.5))
        v = (12 + 243 * np.clip(A, 0, 1) * aus).astype(np.uint8)
        p.stdin.write(np.repeat(v[:, :, None], 3, axis=2).tobytes())
    p.stdin.close()
    if p.wait():
        sys.exit("Fehler beim Abspann")


def leiste(cfg, info, laenge, pfad):
    """Info-Leiste der Vorschau als ASS (720×1520): Teil-Nr., Clip, Quellzeit, Text, Zeitleiste, Abspielkopf."""
    from untertitel import zeit
    z = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 720", "PlayResY: 1520", "WrapStyle: 2",
         "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
         "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
         "MarginR, MarginV, Encoding",
         "Style: nr,Oswald,54,&H0000FFD8,&H0000FFD8,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
         "Style: tx,DejaVu Sans,19,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
         "Style: gr,DejaVu Sans,17,&H00A0A0A0,&H00A0A0A0,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
         "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    x0, x1, y = 16, 704, 1478
    ende = zeit(laenge + 1)
    for k, it in enumerate(info):
        a = x0 + (x1 - x0) * it["t0"] / laenge
        b = x0 + (x1 - x0) * it["t1"] / laenge
        farbe = "&H00505050&" if k % 2 else "&H00383838&"
        z.append(f"Dialogue: 0,{zeit(0)},{ende},gr,,0,0,0,,{{\\pos(0,0)\\an7\\p1\\c{farbe}}}"
                 f"m {a:.1f} {y} l {b:.1f} {y} {b:.1f} {y + 22} {a:.1f} {y + 22}{{\\p0}}")
        s0, s1 = zeit(it["t0"]), zeit(it["t1"])
        z.append(f"Dialogue: 1,{s0},{s1},gr,,0,0,0,,{{\\pos(0,0)\\an7\\p1\\c&H0000C8B0&}}"
                 f"m {a:.1f} {y} l {b:.1f} {y} {b:.1f} {y + 22} {a:.1f} {y + 22}{{\\p0}}")
        nr = str(it.get("nr", f"#{k + 1}"))
        lang = len(nr) > 3  # Abspann-Zeile („Logo“) kleiner, damit sie nicht in den Text läuft
        pos_nr = "\\pos(16,1302)\\fs38" if lang else "\\pos(16,1290)"
        z.append(f"Dialogue: 2,{s0},{s1},nr,,0,0,0,,{{{pos_nr}}}{nr}")
        z.append(f"Dialogue: 2,{s0},{s1},gr,,0,0,0,,{{\\pos(110,1296)}}{it['kopf']}")
        text = "\\N".join(textwrap.wrap(it["text"], 54)[:4])
        z.append(f"Dialogue: 2,{s0},{s1},tx,,0,0,0,,{{\\pos(110,1324)}}{text}")
    z.append(f"Dialogue: 3,{zeit(0)},{zeit(laenge)},gr,,0,0,0,,{{\\an7\\move({x0},{y - 5},{x1},{y - 5})\\p1"
             f"\\c&H00FFFFFF&}}m 0 0 l 3 0 3 32 0 32{{\\p0}}")
    Path(pfad).write_text("\n".join(z) + "\n", encoding="utf-8")


def storyboard(cfg, info, master, pfad, laenge, n_teile):
    from PIL import Image, ImageDraw, ImageFont
    fk = lambda n, b=False: ImageFont.truetype(  # noqa: E731
        "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if b else ""), n)
    osw = ImageFont.truetype(f"{FONTS}/Oswald-Bold.ttf", 64)
    osw_klein = ImageFont.truetype(f"{FONTS}/Oswald-Bold.ttf", 44)  # Abspann-Zeile („Logo“) statt #Nr.
    rh, tw, th = 340, 180, 320
    img = Image.new("RGB", (1080, 120 + rh * len(info)), (12, 12, 12))
    d = ImageDraw.Draw(img)
    d.text((24, 22), f"{cfg['name']}  ·  {laenge:.1f} s  ·  {n_teile} Teile" + (" + Logo" if len(info) > n_teile else ""),
           font=fk(40, True), fill="white")
    d.text((24, 74), cfg.get("untertitel_zeile", ""), font=fk(24), fill=(170, 170, 170))
    for k, it in enumerate(info):
        y = 120 + k * rh
        t = (it["t0"] + it["t1"]) / 2
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(master), "-frames:v", "1",
                            "-vf", f"scale={tw}:{th}", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        from io import BytesIO
        img.paste(Image.open(BytesIO(r.stdout)).convert("RGB"), (24, y + 10))
        nr = str(it.get("nr", f"#{k + 1}"))
        d.text((230, y + 4 if len(nr) <= 3 else y + 18), nr, font=osw if len(nr) <= 3 else osw_klein,
               fill=(216, 255, 0))
        d.text((340, y + 18), f"{it['t0']:.1f}–{it['t1']:.1f} s  ({it['t1'] - it['t0']:.1f} s)", font=fk(30, True),
               fill="white")
        d.text((340, y + 58), it["kopf"], font=fk(24), fill=(170, 170, 170))
        for j, zeile in enumerate(textwrap.wrap(it["text"], 44)[:6]):
            d.text((230, y + 104 + j * 36), zeile, font=fk(28), fill=(235, 235, 235))
        d.line((24, y + rh - 1, 1056, y + rh - 1), fill=(50, 50, 50), width=2)
    img.save(pfad, quality=85)


def enden_zeigen(teile, trs, cfg):
    """Wortenden prüfen (nie ein Wort abschneiden): je Teil das letzte Wort, der Schnitt und der Pegel
    in 40-ms-Schritten ab 0,3 s vor dem Wortende. Zeichen = dB über dem Grundrauschen des Clips: ' ' unter 2, '.' 4,
    ':' 8, '-' 14, '=' 20, '#' darüber; '|' = Schnitt, '^' = nächstes Wort setzt ein. Soll: nach dem Wort ein paar
    ruhige Zeichen (' ', '.', ':'), dann '|'. Steht '|' zwischen lauten Zeichen ('=' oder '#'), wird im Redefluss
    geschnitten und ein Wort ist angeschnitten oder das nächste hat schon begonnen: Spektrum ansehen, ende= von Hand."""
    print("Wortenden: |=Schnitt ^=nächstes Wort; ' ' <2 dB, . 4, : 8, - 14, = 20, # darüber (über dem Rauschen, 40 ms je Zeichen)")
    for n, t in enumerate(teile, 1):
        ws = [w for sg in trs[t["clip"]]["segmente"] for w in sg["woerter"]]
        bis = t["bis"] - float(t.get("plus") or 0)
        j = t.get("_w1")  # letztes Wort der Phrase; bei Quellzeit als bis: letztes Wort vor dem Schnitt
        if j is None:
            vor = [k for k, w in enumerate(ws) if w["s"] < bis - 0.02]
            if not vor:
                continue
            j = vor[-1]
        w = ws[j]
        nx = ws[j + 1] if j + 1 < len(ws) else None
        env = huelle_clip(t["clip"], cfg["clips"][t["clip"]])
        boden = float(np.percentile(env, 5))
        zeile = ""
        for k in range(int((w["e"] - 0.30) * 200), int(min(len(env) / 200, w["e"] + 0.9) * 200), 8):
            d = env[k] - boden
            ch = " " if d < 2 else "." if d < 4 else ":" if d < 8 else "-" if d < 14 else "=" if d < 20 else "#"
            if abs(k / 200 - bis) < 0.02:
                ch = "|"
            elif nx and abs(k / 200 - nx["s"]) < 0.02:
                ch = "^"
            zeile += ch
        print(f"#{n:2d} {w['w']:>14s} {w['s']:6.2f}-{w['e']:6.2f} Schnitt {bis:6.2f} ({bis - w['e']:+.2f}) "
              f"nächstes {nx['w'] if nx else '-':>10s} {nx['s'] if nx else 0:6.2f}  [{zeile}]")


def pruefen(datei, gesamt):
    """Export prüfen (wie verify.py bei den Varianten): Format, Länge, Lautheit, True Peak. True, wenn alles OK."""
    from fractions import Fraction
    pr = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", datei]).stdout)
    v = next(x for x in pr["streams"] if x["codec_type"] == "video")
    a = next(x for x in pr["streams"] if x["codec_type"] == "audio")
    r = subprocess.run(["ffmpeg", "-nostats", "-i", str(datei), "-af", "ebur128=peak=true:framelog=quiet", "-f", "null",
                        "-"], capture_output=True, text=True)
    lu, tp = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr), re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r.stderr)
    dv, da = float(v["duration"]), float(a["duration"])
    zeilen = [
        (v["width"] == W and v["height"] == H and Fraction(v["r_frame_rate"]) == FPS and v["codec_name"] == "h264"
         and v.get("profile") == "High" and v["pix_fmt"] == "yuv420p" and a["codec_name"] == "aac"
         and int(a["sample_rate"]) == SR,
         f"Format {v['width']}×{v['height']}, {float(Fraction(v['r_frame_rate'])):g} fps, {v['codec_name']} {v.get('profile')}, "
         f"{a['codec_name']} {a['sample_rate']} Hz"),
        (abs(dv - da) <= 0.05 and abs(dv - gesamt) <= 0.1 and 40 <= dv <= 60,
         f"Länge Bild {dv:.2f} s, Ton {da:.2f} s (Soll {gesamt:.2f} s, 40–60 s)"),
        (bool(lu) and abs(float(lu[-1]) + 14) <= 0.5, f"Lautheit {lu[-1] if lu else '?'} LUFS (Soll −14 ± 0,5)"),
        (bool(tp) and float(tp[-1]) <= -0.8, f"True Peak {tp[-1] if tp else '?'} dBTP (Soll höchstens −1, Toleranz 0,2)"),
    ]
    for ok, text in zeilen:
        print(("OK      " if ok else "PRÜFEN  ") + text)
    return all(ok for ok, _ in zeilen)


def tonquelle(clip, datei):
    ton_ = WORK / "audio" / f"{clip}.flac"
    return ton_ if ton_.exists() else datei


def bilder_pruefen(cfg, teile, warn):
    """Bild-Überlagerungen (B-Roll oder andere Kamera über die Stimme) prüfen und bei "kamera" die Quellzeit aus
    sync.json (pipeline/sync.py) bestimmen. Eintrag im Teil: bild = [{clip | kamera, src, ab, dauer, zoom, fokus}]."""
    S = None
    for k, t in enumerate(teile):
        d = max(1, round((t["bis"] - t["von"]) * FPS)) / FPS
        for b in t.get("bild") or []:
            if b.get("kamera"):
                if not cfg.get("sync"):
                    sys.exit(f"#{k + 1}: bild mit kamera braucht \"sync\": <sync.json> in der Konfiguration (pipeline/sync.py)")
                import sync
                S = S or sync.laden(cfg["sync"])
                b["clip"] = b["kamera"]
                x = sync.zeit_in(S, t["clip"], t["von"] + float(b["ab"]), b["kamera"])
                if x is None:
                    sys.exit(f"#{k + 1}: Kamera {b['kamera']} läuft bei {t['von'] + float(b['ab']):.2f} s nicht (außerhalb der Überlappung)")
                b["src"] = round(x, 3)
            if b.get("clip") not in cfg["clips"] or b.get("src") is None:
                sys.exit(f"#{k + 1}: bild braucht clip (in \"clips\") und src, bekam {b}")
            ab, dauer = float(b["ab"]), float(b["dauer"])
            if ab < 0 or ab >= d:
                sys.exit(f"#{k + 1}: bild ab {ab:g} s liegt außerhalb des Teils ({d:.2f} s)")
            if ab + dauer > d + 0.02:
                warn.append(f"#{k + 1}: Bild {b['clip']} ragt {ab + dauer - d:.2f} s über das Teilende, wird gekürzt")
            if ab < 0.4 and not b.get("kamera"):
                warn.append(f"#{k + 1}: B-Roll schon bei {ab:.2f} s: die ersten 0,4 s zeigen besser den Sprecher")
            if dauer < 0.6 or dauer > 6:
                warn.append(f"#{k + 1}: Bild {b['clip']} {dauer:.1f} s (sinnvoll 0,6 bis 6 s)")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cfg_pfad = Path(sys.argv[1])
    cfg = json.loads(cfg_pfad.read_text())
    reel = cfg_pfad.resolve().parent.parent
    name = cfg["name"]
    OUT.mkdir(parents=True, exist_ok=True)
    if "--titelbild" in sys.argv:  # nur das Titelbild neu ziehen, ohne neu zu rendern
        rest = sys.argv[sys.argv.index("--titelbild") + 1:]
        tb = float(rest[0]) if rest and not rest[0].startswith("-") else float(cfg.get("titelbild", 0.5))
        if not (OUT / "zusammen.mp4").exists():
            sys.exit("zusammen.mp4 fehlt: erst einmal bauen (Vorschau oder --export)")
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{tb:.3f}", "-i", OUT / "zusammen.mp4", "-frames:v", 1, "-q:v", 2,
             reel / f"{name}{SUFFIX}_titelbild.jpg"])
        print(f"-> {reel / f'{name}{SUFFIX}_titelbild.jpg'} (Sekunde {tb:g})")
        return
    trs = {}
    for c in cfg["clips"]:
        p = Path(cfg["transkript"]) / f"{c}.json"
        trs[c] = json.loads(p.read_text()) if p.exists() else {"segmente": []}
    fok = json.loads((OUT / "fokus.json").read_text()) if (OUT / "fokus.json").exists() else {}
    teile, warn = cfg["teile"], []
    for k, t in enumerate(teile):
        aufloesen(t, [w for sg in trs[t["clip"]]["segmente"] for w in sg["woerter"]], cfg["clips"][t["clip"]])
        v = teile[k - 1] if k else None  # nahtlos weiter im selben Clip: exakt am letzten Frame ansetzen
        if v and v["clip"] == t["clip"] and abs(t["von"] - v["bis"]) < 0.25:
            t["von"] = round(v["von"] + max(1, round((v["bis"] - v["von"]) * FPS)) / FPS, 4)
    for t in teile:     # bild mit bei (Quellzeit im Sprecherclip) -> ab (s nach dem Teilanfang)
        for b in t.get("bild") or []:
            if "bei" in b:
                b["ab"] = round(float(b["bei"]) - t["von"], 3)
    if cfg.get("kuerzen") or any(t.get("kuerzen") for t in teile):   # Pausen und Füllwörter kürzen (kuerzen.py)
        teile, erste, meld = pausen.expandieren(teile, trs, cfg, lambda c: huelle_clip(c, cfg["clips"][c]),
                                                 lambda c: pausen.lesen16(tonquelle(c, cfg["clips"][c])))
        cfg["teile"] = teile
        if cfg["song"].get("drop_teil"):
            cfg["song"]["drop_teil"] = erste[int(cfg["song"]["drop_teil"]) - 1] + 1
        for m in meld:
            print("Kürzen", m)
    bilder_pruefen(cfg, teile, warn)
    song = cfg["song"]
    if song.get("drop_takt") is not None:  # Songabschnitt am Schnitt ausrichten (grid.json aus song_analyse.py)
        g = json.loads(Path(song["grid"]).read_text())
        takt = lambda T: g["erste_eins"] + T * 4 * g["per"]  # noqa: E731
        dauer = lambda x: max(1, round((x["bis"] - x["von"]) * FPS)) / FPS  # noqa: E731
        t_drop = sum(dauer(x) for x in teile[:int(song.get("drop_teil", 1)) - 1])
        song["start"] = round(takt(song["drop_takt"]) - t_drop, 4)
        if song["start"] < 0:
            sys.exit(f"Song-Start {song['start']:.2f} s < 0: drop_takt später wählen")
        if song.get("ende_auf_phrase", True) and not cfg.get("abspann"):  # mit Abspann: der endet auf einer Eins
            ende = song["start"] + sum(dauer(x) for x in teile)
            kuerzen = float(song.get("max_kuerzen", 0.8))  # so viel darf der letzte Teil kürzer werden
            k = int(np.ceil((ende - kuerzen - takt(song["drop_takt"])) / (16 * g["per"])))
            ziel = takt(song["drop_takt"] + 4 * k)
            teile[-1]["bis"] = round(teile[-1]["bis"] + (ziel - ende), 4)
            song["ende_takt"] = song["drop_takt"] + 4 * k
            warn.append(f"letzter Teil für die Phrasengrenze um {ziel - ende:+.2f} s angepasst") if ziel - ende > 2.5 \
                else None
        print(f"Song ab {song['start']:.3f} s, Eins T{song['drop_takt']} auf Teil #{song.get('drop_teil', 1)} "
              f"(Reel {t_drop:.2f} s), Ende T{song.get('ende_takt', '?')}")
    for k, t in enumerate(teile):  # Pause = nahe am Grundrauschen des Clips oder 15 dB unter der Sprache
        env = huelle_clip(t["clip"], cfg["clips"][t["clip"]])
        sprache = float(np.percentile(env[int(t["von"] * 200):max(int(t["bis"] * 200), int(t["von"] * 200) + 2)], 90))
        boden = float(np.percentile(env, 5))
        nx = teile[k + 1] if k + 1 < len(teile) else None
        nahtlos = nx and nx["clip"] == t["clip"] and abs(nx["von"] - t["bis"]) < 0.3
        if "Ende" in t.get("_ohne_pause", []) and t.get("ende") is None and not t.get("plus") and not nahtlos:
            warn.append(f"#{k + 1}: Ende ohne Pause geschnitten (Redefluss, leise Silbe oder Wortende von Whisper zu "
                        f"früh): Spektrum prüfen, sonst ende= setzen")
        for lv, wo in zip(t.get("_tiefe", []), ("Anfang", "Ende")):
            if t.get({"Anfang": "anfang", "Ende": "ende"}[wo]) is not None:
                continue  # von Hand gesetzt
            if lv > sprache - 15 and lv > boden + 8:
                warn.append(f"#{k + 1}: {wo} im Redefluss ({sprache - lv:.0f} dB unter der Sprache, "
                            f"{lv - boden:.0f} dB über dem Rauschen), in der Vorschau abhören")
    if "--trocken" in sys.argv or "--enden" in sys.argv:  # nur auflösen und zeigen, nichts rendern
        t0 = 0.0
        for k, t in enumerate(teile):
            d = max(1, round((t["bis"] - t["von"]) * FPS)) / FPS
            ws = woerter(trs[t["clip"]], t, cfg.get("ersetzen", {}))
            print(f"{t.get('nr', f'#{k + 1}'):>5s} {t0:5.2f}–{t0 + d:5.2f} {t['clip']} {t['von']:6.2f}–{t['bis']:6.2f} "
                  f"{' '.join(w['w'] for w in ws)[:90]}" + "".join(
                      f"  [Bild {b['clip']} ab {b['ab']:g} s, {b['dauer']:g} s, Quelle {float(b['src']):.2f} s]" for b in t.get("bild") or []))
            t0 += d
        print(f"Länge {t0:.2f} s")
        for x in warn:
            print("WARNUNG", x)
        if "--enden" in sys.argv:
            enden_zeigen(teile, trs, cfg)
        return
    for t in teile:
        if t.get("fokus"):
            t["_fokus"] = list(t["fokus"])
        elif float(t.get("zoom", 1)) > 1.001:
            k = f"{t['clip']}:{t['von']:.2f}:{t['bis']:.2f}"
            if k not in fok:
                fok[k] = gesicht(cfg["clips"][t["clip"]], t["von"], t["bis"])
            t["_fokus"] = fok[k] or [0.5, 0.35]
    (OUT / "fokus.json").write_text(json.dumps(fok, indent=1))
    video, audio, ns, info, alle, sub, koepfe = [], [], [], [], [], [], []
    t0 = 0.0
    for i, t in enumerate(teile):
        v, a, n = teil_rendern(i, t, cfg["clips"])
        video.append(v), audio.append(a), ns.append(n)
        d = n / FPS
        ws = woerter(trs[t["clip"]], t, cfg.get("ersetzen", {}))
        if d < 0.5:
            warn.append(f"#{i + 1}: nur {d:.2f} s")
        for w in ws:
            if w.get("p", 1) < 0.5 and not t.get("text"):
                warn.append(f"#{i + 1}: unsicheres Wort „{w['w']}“ bei {w['s']:.2f} s (p {w['p']:.2f})")
            m = dict(w, s=w["s"] - t["von"] + t0, e=w["e"] - t["von"] + t0, teil=i)
            if t.get("stil"):
                m["stil"] = t["stil"]
            alle.append(m)
            if t.get("untertitel", True) is not False and t.get("stil") != "frage":
                sub.append(m)
        if t.get("stil") == "frage" and (ws or t.get("kopf")):
            s_k = (ws[0]["s"] - t["von"] + t0) if ws else t0
            nach = float(t.get("kopf_nach", cfg.get("kopf_nach", 1.0)))  # Frage weg, nach der Frage weich ausgeblendet
            koepfe.append(dict(text=t.get("kopf") or " ".join(w["w"] for w in ws), s=s_k,
                               e=max(t0 + d + nach, s_k + 1.2), aus=float(cfg.get("kopf_aus", 0.45))))
        info.append(dict(t0=t0, t1=t0 + d, text=" ".join(w["w"] for w in ws) or "(ohne Worte)",
                         **({"nr": t["nr"]} if t.get("nr") else {}),
                         kopf=f"{t['clip']} {t['von']:.2f}–{t['bis']:.2f} s"
                              + (f" · Zoom {float(t['zoom']):.2f}" if float(t.get("zoom", 1)) > 1.001 else "")
                              + "".join(f" · Bild {b['clip']} {float(b['src']):.1f} s" for b in t.get("bild") or [])
                              + (f" · {t['notiz']}" if t.get("notiz") else "")))
        t0 += d
    laenge = gesamt = t0  # Ende des letzten Teils; gesamt mit Abspann
    absp, blende = cfg.get("abspann"), 0.0
    absp = abspann_fuer(absp, PROFIL) if absp else absp
    if absp:
        blende = float(absp.get("blende", 0.6))
        mindestens = float(absp.get("mindestens", 2.6))
        if song.get("grid"):  # Ende auf der nächsten Eins des Songs, frühestens mindestens s nach dem letzten Teil
            g = json.loads(Path(song["grid"]).read_text())
            T = int(np.ceil((song["start"] + laenge + mindestens - g["erste_eins"]) / (4 * g["per"])))
            gesamt = g["erste_eins"] + T * 4 * g["per"] - song["start"]
            song["ende_takt"] = T
        else:
            gesamt = laenge + mindestens
        abspann_rendern(absp, gesamt - laenge + blende, OUT / f"abspann{SUFFIX}.mp4", MAX_BREITE_PLATTFORM)
        info.append(dict(t0=laenge - blende, t1=gesamt, nr="Logo", text=" · ".join(z["text"] for z in absp["zeilen"] if "text" in z),
                         kopf=f"Abspann, Überblendung {blende:.1f} s, endet auf Takt {song.get('ende_takt', '?')}"))
    ass(sub, OUT / f"untertitel{SUFFIX}.ass", ende=laenge, koepfe=koepfe, max_breite=MAX_BREITE_PLATTFORM)
    (OUT / "liste.txt").write_text("".join(f"file '{v}'\n" for v in video))
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", 0, "-i", OUT / "liste.txt", "-c", "copy",
         OUT / "zusammen.mp4"])
    master = WORK / f"master_{name}{SUFFIX}.mp4"
    unter = f"ass={OUT / f'untertitel{SUFFIX}.ass'}:fontsdir={FONTS}"
    run(["ffmpeg", "-v", "error", "-y", "-i", OUT / "zusammen.mp4"]
        + (["-i", OUT / f"abspann{SUFFIX}.mp4", "-filter_complex",
            f"[0:v]{unter}[u];[u][1:v]xfade=transition=fade:duration={blende:.3f}:offset={laenge - blende:.3f}[v]",
            "-map", "[v]"] if absp else ["-vf", unter])
        + ["-c:v", "libx264", "-preset", "medium", "-crf", 15, "-pix_fmt", "yuv420p", "-color_primaries", "bt709",
           "-color_trc", "bt709", "-colorspace", "bt709", master])
    (mix, solo), anteil = ton(cfg, teile, audio, ns, alle, laenge, gesamt, blende)
    print(f"{name}: {len(teile)} Teile, {laenge:.2f} s" + (f" + Abspann = {gesamt:.2f} s" if absp else "")
          + f", Sprache {anteil * 100:.0f} % der Zeit, {len(sub)} Wörter im Untertitel")
    for zl in info:
        print(f"  {zl['t0']:5.1f}–{zl['t1']:5.1f}  {zl['kopf'][:40]:40s}  {zl['text'][:70]}")
    if not 40 <= gesamt <= 60:
        warn.append(f"Länge {gesamt:.1f} s außerhalb 40–60 s")
    for x in warn:
        print("WARNUNG", x)
    if "--export" in sys.argv:
        ok_ = True
        tb = cfg.get("titelbild", info[0]["t0"] + 0.5)
        if SUFFIX:  # andere Plattform: Profil aus plattform.py (Bitrate, GOP, Lautheit), eigene Dateinamen mit _yt
            stumm = OUT / f"{PROFIL['kurz']}.mp4"
            pf.video_export(master, stumm, PROFIL)
            for art, ton_ in (("mit_song.mp4", mix), ("ohne_song.mp4", solo)):
                datei = reel / pf.dateiname(name, PROFIL, art)
                pf.mux(stumm, pf.ton_fuer(ton_, PROFIL), datei, PROFIL)
                print("->", datei)
                ok_ = pruefen(datei, gesamt) and ok_
                ok_ = pf.ausgeben(pf.pruefen(datei, PROFIL, tb, gesamt)) and ok_
        else:
            import export  # Instagram-Export in 2 Pässen wie bei allen Reels (Projektanweisungen Punkt 15: 18/25 Mbit/s)
            stumm = OUT / "instagram.mp4"
            export.instagram(master, stumm)
            for datei, ton_ in ((reel / f"{name}_mit_song.mp4", mix), (reel / f"{name}_ohne_song.mp4", solo)):
                # Bild und Ton sind gleich lang; kein -shortest: bei Stream-Copy schneidet es die letzten Bilder ab
                run(["ffmpeg", "-v", "error", "-y", "-i", stumm, "-i", ton_, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                     "-c:a", "aac", "-b:a", "320k", "-ar", SR, "-movflags", "+faststart", datei])
                print("->", datei)
                ok_ = pruefen(datei, gesamt) and ok_
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{tb:.3f}", "-i", OUT / "zusammen.mp4", "-frames:v", 1,
             "-q:v", 2, reel / f"{name}{SUFFIX}_titelbild.jpg"])
        print("-> Titelbild", reel / f"{name}{SUFFIX}_titelbild.jpg")
        print("Prüfung: " + ("alles OK" if ok_ else "PRÜFEN, siehe oben"))
        sys.exit(0 if ok_ else 1)
    leiste(cfg, info, gesamt, OUT / "leiste.ass")
    vor = reel / f"{name}{SUFFIX}_vorschau.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", master, "-i", mix, "-filter_complex",
         f"[0:v]scale=720:1280:flags=lanczos,pad=720:1520:0:0:color=0x0C0C0C,"
         f"ass={OUT / 'leiste.ass'}:fontsdir={FONTS}[v]", "-map", "[v]", "-map", "1:a", "-c:v", "libx264",
         "-preset", "medium", "-crf", 23, "-maxrate", "3500k", "-bufsize", "7000k", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", vor])
    storyboard(cfg, info, master, reel / f"{name}{SUFFIX}_storyboard.jpg", gesamt, len(teile))
    json.dump(dict(laenge=round(gesamt, 3), teile=[dict(nr=i_.get("nr", k + 1), t0=round(i_["t0"], 3),
                                                        t1=round(i_["t1"], 3), kopf=i_["kopf"], text=i_["text"])
                                                   for k, i_ in enumerate(info)]),
              open(cfg_pfad.parent / "schnitt_info.json", "w"), ensure_ascii=False, indent=1)
    print("->", vor, "\n->", reel / f"{name}{SUFFIX}_storyboard.jpg")


if __name__ == "__main__":
    main()
