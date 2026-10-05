#!/usr/bin/env python3
"""Personenerkennung (YOLOX-S, COCO-Klasse Person) mit cv2.dnn auf der CPU.

    import personen
    personen.erkennen(bild_bgr)          # [(x, y, breite, höhe, sicherheit), …] in Pixeln, sicherste zuerst
    python3 personen.py <bild-oder-video> [--t 3.0]      # Erkennungen eines Frames als Zeilen, ~1 s

Weite Bilder (Breite ≥ 1,4 × Höhe) laufen in überlappenden Quadraten, jedes mit 640×640: Personen im Querformat
bleiben so fast doppelt so groß wie bei einem einzigen Lauf über das ganze Bild. ~0,12 s je Lauf bei 4 Kernen.
Modell und Herkunft: modelle/yolox/. Fehlt das Modell, meldet verfuegbar() False; Aufrufer arbeiten dann nur mit der
Bewegung (reframe.py) oder zählen nicht (clip_analyse.py).
"""
import math
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
MODELL = Path(__file__).resolve().parent / "modelle/yolox/object_detection_yolox_2022nov.onnx"
GROESSE = 640
_LOCK = threading.Lock()        # cv2.dnn.Net ist nicht threadsicher
_CACHE = {}


def verfuegbar():
    try:
        import cv2
        return hasattr(cv2, "dnn") and MODELL.exists()
    except ImportError:
        return False


def _netz():
    import cv2
    if "netz" not in _CACHE:
        _CACHE["netz"] = cv2.dnn.readNetFromONNX(str(MODELL))
        gitter, schritte = [], []
        for s in (8, 16, 32):
            n = GROESSE // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            g = np.stack([xv, yv], -1).reshape(-1, 2)
            gitter.append(g)
            schritte.append(np.full((len(g), 1), s))
        _CACHE["gitter"], _CACHE["schritt"] = np.concatenate(gitter), np.concatenate(schritte)
    return _CACHE["netz"]


def _lauf(bild, schwelle):
    """Ein Lauf mit 640×640 (Seitenverhältnis erhalten, Bild oben links, Rand grau 114)."""
    import cv2
    h, w = bild.shape[:2]
    r = min(GROESSE / h, GROESSE / w)
    nw, nh = max(1, int(w * r)), max(1, int(h * r))
    flaeche = np.full((GROESSE, GROESSE, 3), 114, np.uint8)
    flaeche[:nh, :nw] = cv2.resize(bild, (nw, nh), interpolation=cv2.INTER_LINEAR if r >= 1 else cv2.INTER_AREA)
    with _LOCK:
        netz = _netz()
        netz.setInput(flaeche.transpose(2, 0, 1)[None].astype(np.float32))
        o = netz.forward()[0]
    sicher = o[:, 4] * o[:, 5]                      # Objekt-Sicherheit × Klasse 0 (Person)
    k = sicher > schwelle
    if not k.any():
        return []
    xy = (o[k, :2] + _CACHE["gitter"][k]) * _CACHE["schritt"][k]
    wh = np.exp(o[k, 2:4]) * _CACHE["schritt"][k]
    box = np.concatenate([xy - wh / 2, wh], 1) / r
    return [(float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(c)) for b, c in zip(box, sicher[k])]


def erkennen(bild, schwelle=0.35, iou=0.45):
    """Personen im BGR-Bild: [(x, y, breite, höhe, sicherheit), …] in Pixeln des Bildes, sicherste zuerst."""
    import cv2
    h, w = bild.shape[:2]
    roh = []
    if w >= 1.4 * h:
        n = max(2, math.ceil((w - h) / (0.65 * h)) + 1)
        for x0 in np.linspace(0, w - h, n).round().astype(int):
            roh += [(x + x0, y, bw, bh, c) for x, y, bw, bh, c in _lauf(bild[:, x0:x0 + h], schwelle)]
    else:
        roh = _lauf(bild, schwelle)
    if not roh:
        return []
    idx = cv2.dnn.NMSBoxes([list(b[:4]) for b in roh], [b[4] for b in roh], schwelle, iou)
    out = []
    for i in np.array(idx).flatten():
        x, y, bw, bh, c = roh[i]
        x0, y0 = max(0.0, x), max(0.0, y)
        out.append((x0, y0, min(w, x + bw) - x0, min(h, y + bh) - y0, c))
    return sorted(out, key=lambda b: -b[4])


def _bild(quelle, t):
    import cv2
    if str(quelle).lower().endswith((".jpg", ".jpeg", ".png")):
        return cv2.imread(str(quelle))
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(quelle), "-frames:v", "1", "-vf",
                        "scale=960:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    if not r.stdout:
        raise SystemExit(f"Kein Frame bei {t:.1f} s aus {quelle}")
    return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if not verfuegbar():
        sys.exit(f"Modell fehlt: {MODELL}")
    zeit = float(sys.argv[sys.argv.index("--t") + 1]) if "--t" in sys.argv else 1.0
    img = _bild(sys.argv[1], zeit)
    hh, ww = img.shape[:2]
    liste = erkennen(img)
    print(f"{len(liste)} Person(en) im Bild {ww}×{hh}")
    for x, y, bw, bh, c in liste[:12]:
        print(f"  Mitte {100 * (x + bw / 2) / ww:3.0f} % / {100 * (y + bh / 2) / hh:3.0f} %, Höhe {100 * bh / hh:3.0f} %, "
              f"Sicherheit {c:.2f}")
