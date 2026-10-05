#!/usr/bin/env python3
"""Pausen und Füllwörter kürzen (seit 30.09.2026): aus einem gesprochenen Stück die Stellen schneiden, die man nicht hören will.

    cd /tmp && python3 kuerzen.py <clip_oder_ton> --transkript <ordner mit <stamm>.json> [--von S --bis S]
            [--pause-max 0.45] [--pause-ziel 0.22] [--stark] [--zoegern] [--json schnitte.json]

Im Interview-Schnitt (schnitt.json): am Teil oder in der Konfiguration `"kuerzen": true` oder mit eigenen Werten
(`{"pause_max": 0.4, "stark": true}`); interview.py teilt den Teil dann an den Schnittstellen in Stücke (Vorschau-
Nummer 7a, 7b …). `"kuerzen": false` am Teil schaltet es dort aus. Fragen (`stil: "frage"`) und Teile mit eigenem
`text` bleiben unberührt.

Was es macht (Schwellen in REGELN):
- Pausen: zwischen zwei Wörtern eine echte Stille (Pegel höchstens 5 dB über dem Grundrauschen des Clips, gemessen am
  Ton, nicht an den Wortzeiten von Whisper, die oft 0,2–0,55 s zu früh enden). Ist sie länger als `pause_max`
  (nach Satzende `pause_max_satz`), wird aus ihrer Mitte so viel herausgeschnitten, dass `pause_ziel` (nach
  Satzende `pause_ziel_satz`) stehen bleibt. Der Schnitt liegt immer mitten in der Stille, nie im Wort.
- Füllwörter: äh, ähm, ehm, öh, hm, mhm und ähnliche, die Whisper als Wort ausgibt, samt der Stille drumherum
  (es bleibt `pause_fuell` stehen). `--stark` nimmt zusätzlich also, halt, sozusagen, quasi, irgendwie, eigentlich,
  ne, aber nur, wo sie allein vor oder hinter einer Pause stehen (Claudes Auslegung, standardmäßig aus).
- `--zoegern`: Zögerlaute, die Whisper weggelassen hat (gleichmäßiger Vokal von 0,25–1,2 s zwischen zwei Wörtern, nach
  einer kurzen Absenkung). Ein Vorschlag aus dem Ton, nicht am Ohr geprüft; standardmäßig aus, `--zeige` listet sie.
Whisper lässt „äh“ oft ganz weg. Ein Prompt mit Füllwörtern (`transkript.py --prompt`) half in der Probe vom 30.09.
nicht verlässlich: auf einem Schnitt ohne Füllwörter erfand Whisper ein „Äh“ vor dem ersten „Ja“ (p 0,40). Darum wird ein
Füllwort ohne Stille davor und dahinter nicht geschnitten, sondern gemeldet.

Ausgabe: je Schnitt Zeit, Länge und Grund, dazu die Stücke, die bleiben, und die Ersparnis. Nur Vorschläge für den
Schnitt; wer es nicht will, lässt `kuerzen` weg. Test ohne Drive: test_kuerzen.py.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True      # kein __pycache__ im geteilten Projektordner
PIPE = Path(__file__).resolve().parent
TOOLS = PIPE.parent
for _p in (PIPE, TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

HZ = 200                            # Werte je s der Pegelkurve (RMS 30 ms, alle 5 ms), wie interview.py

REGELN = dict(
    pause_max=0.45,                 # s: Stille zwischen Wörtern darüber wird gekürzt
    pause_max_satz=0.60,            # s: nach Satzende (. ? !)
    pause_ziel=0.22,                # s: so viel Stille bleibt nach dem Kürzen
    pause_ziel_satz=0.32,           # s: nach Satzende
    pause_fuell=0.16,               # s: Stille, die nach dem Herausschneiden eines Füllworts bleibt
    luft_min=0.05,                  # s: auf jeder Seite eines Schnitts mindestens so viel Stille
    stille_db=5.0,                  # dB über dem Grundrauschen (5. Perzentil des Clips) gilt als Stille
    stille_min=0.04,                # s: so lang muss die Stille mindestens sein, um als Pause zu gelten
    stueck_min=0.12,                # s: kürzere übrig bleibende Stücke entfallen
    stark=False,                    # zusätzlich also, halt, sozusagen … (nur allein vor oder hinter einer Pause)
    zoegern=False,                  # Zögerlaute aus dem Ton
    zoegern_min=0.25,               # s
    zoegern_max=1.2,                # s
    viel=0.35,                      # Warnung, wenn mehr als dieser Anteil des Stücks herausfliegt
)
FUELL = {"äh", "ähm", "ähhm", "ääh", "äähm", "ehm", "öh", "öhm", "hm", "hmm", "hmmm", "mh", "mhm", "mhh", "aeh", "aehm"}
STARK = {"also", "halt", "sozusagen", "quasi", "irgendwie", "eigentlich", "ne", "nä"}
SATZENDE = ".?!…"


def norm(w):
    return re.sub(r"[^\wÄÖÜäöüß]", "", w.lower())


def einstellungen(x=None, basis=None):
    """REGELN mit den Werten aus x (True oder dict) überschrieben; x False/None = keine Änderung."""
    r = dict(REGELN if basis is None else basis)
    if isinstance(x, dict):
        for k, v in x.items():
            k = k.replace("-", "_")
            if k in r:
                r[k] = type(r[k])(v) if not isinstance(r[k], bool) else bool(v)
    return r


def lesen16(pfad):
    """Ton als float32 mono 16 kHz (ffmpeg)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(pfad), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode or not r.stdout:
        raise SystemExit(f"Ton nicht lesbar: {pfad}")
    return np.frombuffer(r.stdout, np.float32)


def huelle(x, sr=16000):
    """Pegelkurve in dB, HZ Werte je s (RMS 30 ms)."""
    hop, win = sr // HZ, int(sr * 0.03)
    n = max(1, (len(x) - win) // hop)
    x2 = x.astype(np.float64) ** 2
    c = np.concatenate([[0.0], np.cumsum(x2)])
    k = np.arange(n) * hop
    return 10 * np.log10((c[k + win] - c[k]) / win + 1e-12)


def stille_laeufe(env, a, b, thr, minlen):
    """Stille-Läufe (von, bis) in s zwischen a und b, in denen der Pegel höchstens thr ist, mindestens minlen lang."""
    i0, i1 = max(0, int(a * HZ)), min(len(env), int(b * HZ) + 1)
    ruhig = env[i0:i1] <= thr
    out, k = [], 0
    while k < len(ruhig):
        if ruhig[k]:
            j = k
            while j < len(ruhig) and ruhig[j]:
                j += 1
            if (j - k) / HZ >= minlen:
                out.append(((i0 + k) / HZ, (i0 + j) / HZ))
            k = j
        k += 1
    return out


def leiseste(env, a, b):
    i0, i1 = max(0, int(a * HZ)), max(int(a * HZ) + 1, min(len(env), int(b * HZ) + 1))
    return (i0 + int(np.argmin(env[i0:i1]))) / HZ


def zoegerlaute(x, env, ws, von, bis, thr, R, sr=16000):
    """Kandidaten für Zögerlaute in den Lücken zwischen Wörtern: [(von, bis)]. Gleichmäßiger, tonhafter Laut
    (Tonhöhe fast konstant, Spektrum tonal, deutlich über dem Rauschen) nach einer kurzen Absenkung nach dem Wort davor."""
    import librosa
    out = []
    for w0, w1 in zip(ws[:-1], ws[1:]):
        # Whisper lässt Wortenden zu früh enden: das erste Stück der Lücke gehört noch zum Wort davor
        a = max(w0["e"], w0["s"] + 0.11 * len(norm(w0["w"])) + 0.1) + 0.12
        b = w1["s"] - 0.05
        if b - a < R["zoegern_min"] or a < von or b > bis:
            continue
        seg = x[int(a * sr):int(b * sr)]
        if len(seg) < sr * 0.2:
            continue
        f0 = librosa.yin(seg, fmin=70, fmax=330, sr=sr, frame_length=1024, hop_length=160)
        flach = librosa.feature.spectral_flatness(y=seg, n_fft=1024, hop_length=160)[0]
        n = min(len(f0), len(flach))
        pegel = np.interp(np.arange(n) * 160 / sr + a, np.arange(len(env)) / HZ, env)
        ok = (flach[:n] < 0.08) & (pegel > thr + 8)
        k = 0
        while k < n:
            if ok[k]:
                j = k
                while j < n and ok[j]:
                    j += 1
                d = (j - k) * 160 / sr
                if R["zoegern_min"] <= d <= R["zoegern_max"]:
                    lauf = f0[k:j]
                    if float(np.std(lauf) / (np.median(lauf) + 1e-9)) < 0.12:
                        out.append((round(a + k * 160 / sr, 3), round(a + j * 160 / sr, 3)))
                k = j
            k += 1
    return out


def schnitte(ws, env, von, bis, R=None, x=None):
    """Schnittvorschläge für ein Stück [von, bis] (Quellzeit). ws: alle Wörter des Clips in Reihenfolge (w, s, e).
    Gibt dict: schnitte [{von, bis, grund}] (herauszuschneiden, sortiert, ohne Überlappung), keep [(a, b)] (bleibt),
    weg (Indizes der entfernten Wörter in ws), warn, ersparnis (s)."""
    R = R or REGELN
    boden = float(np.percentile(env, 5))
    sprache = float(np.percentile(env[int(von * HZ):max(int(bis * HZ), int(von * HZ) + 2)], 90))
    thr = min(boden + R["stille_db"], sprache - 12)
    warn, rohe, weg = [], [], []
    idx = [k for k, w in enumerate(ws) if von <= (w["s"] + w["e"]) / 2 <= bis]
    if not idx:
        return dict(schnitte=[], keep=[(von, bis)], weg=[], warn=["keine Wörter im Stück"], ersparnis=0.0)

    def ist_fuell(k):
        n = norm(ws[k]["w"])
        if n in FUELL:
            return "Füllwort"
        if R["stark"] and n in STARK:
            vor = ws[k]["s"] - ws[k - 1]["e"] if k > 0 else 9.0
            nach = ws[k + 1]["s"] - ws[k]["e"] if k + 1 < len(ws) else 9.0
            if max(vor, nach) >= 0.25 and len(idx) > 3:
                return "Füllwort (stark)"
        return None

    fuell = {k: g for k in idx if (g := ist_fuell(k))}
    # 1. Füllwörter samt Stille drumherum
    for k, grund in list(fuell.items()):
        w = ws[k]
        vor = [r for r in stille_laeufe(env, w["s"] - 0.7, w["s"] + 0.1, thr, R["stille_min"]) if w["s"] - 0.12 <= r[1] <= w["s"] + 0.15]
        nach = [r for r in stille_laeufe(env, w["e"] - 0.1, w["e"] + 0.7, thr, R["stille_min"]) if w["e"] - 0.15 <= r[0] <= w["e"] + 0.35]
        keep = max(R["luft_min"], R["pause_fuell"] / 2)
        if not vor and not nach:
            # weder davor noch danach Stille: das Füllwort steht mitten im Redefluss oder Whisper hat es erfunden (Probe
            # 30.09.: mit Prompt stand „Äh“ vor einem „Ja“, p 0,40). Nicht schneiden, sonst fehlt ein echtes Wort.
            warn.append(f"„{w['w']}“ bei {w['s']:.2f} s (p {w.get('p', 0):.2f}): keine Stille davor und dahinter, nicht geschnitten "
                        f"(mitten im Redefluss oder von Whisper erfunden; abhören)")
            fuell.pop(k)
            continue
        if vor:
            a = vor[-1][0] + min(keep, (vor[-1][1] - vor[-1][0]) / 2)
        else:
            a = leiseste(env, w["s"] - 0.06, w["s"] + 0.03)
            warn.append(f"„{w['w']}“ bei {w['s']:.2f} s: keine Stille davor, an der leisesten Stelle geschnitten")
        if nach:
            b = nach[0][1] - min(keep, (nach[0][1] - nach[0][0]) / 2)
        else:
            b = leiseste(env, w["e"] - 0.03, w["e"] + 0.08)
            warn.append(f"„{w['w']}“ bei {w['e']:.2f} s: keine Stille dahinter, an der leisesten Stelle geschnitten")
        if b > a + 0.05:
            rohe.append(dict(von=a, bis=b, grund=f"{grund} „{w['w'].strip('.,!?')}“ ({w['s']:.2f}–{w['e']:.2f} s)"))
            weg.append(k)
    # 2. Zögerlaute aus dem Ton
    if R["zoegern"] and x is not None:
        for a0, b0 in zoegerlaute(x, env, [ws[k] for k in idx], von, bis, thr, R):
            vor = [r for r in stille_laeufe(env, a0 - 0.6, a0 + 0.05, thr, R["stille_min"]) if r[1] <= a0 + 0.1]
            nach = [r for r in stille_laeufe(env, b0 - 0.05, b0 + 0.6, thr, R["stille_min"]) if r[0] >= b0 - 0.1]
            keep = max(R["luft_min"], R["pause_fuell"] / 2)
            a = vor[-1][0] + min(keep, (vor[-1][1] - vor[-1][0]) / 2) if vor else a0 - 0.02
            b = nach[0][1] - min(keep, (nach[0][1] - nach[0][0]) / 2) if nach else b0 + 0.03
            rohe.append(dict(von=a, bis=b, grund=f"Zögerlaut aus dem Ton ({a0:.2f}–{b0:.2f} s)"))
    # 3. lange Pausen zwischen den übrigen Wörtern
    rest = [k for k in idx if k not in fuell]
    for k0, k1 in zip(rest[:-1], rest[1:]):
        w0, w1 = ws[k0], ws[k1]
        satz = w0["w"].rstrip()[-1:] in SATZENDE
        pmax, ziel = (R["pause_max_satz"], R["pause_ziel_satz"]) if satz else (R["pause_max"], R["pause_ziel"])
        a = w0["s"] + 0.5 * (w0["e"] - w0["s"])
        b = w1["s"] + 0.3 * (w1["e"] - w1["s"])
        for r0, r1 in stille_laeufe(env, a, b, thr, pmax):
            if r1 - r0 <= pmax or any(r["von"] < r1 and r["bis"] > r0 for r in rohe):
                continue
            rest_s = max(ziel, 2 * R["luft_min"])
            rohe.append(dict(von=r0 + rest_s / 2, bis=r1 - rest_s / 2,
                             grund=f"Pause {r1 - r0:.2f} s auf {rest_s:.2f} s ({r0:.2f}–{r1:.2f} s)"))
    # zusammenfassen, auf das Stück beschneiden
    rohe = sorted((dict(r, von=max(r["von"], von), bis=min(r["bis"], bis)) for r in rohe if r["bis"] > von and r["von"] < bis),
                  key=lambda r: r["von"])
    cuts = []
    for r in rohe:
        if cuts and r["von"] <= cuts[-1]["bis"] + 0.02:
            cuts[-1]["bis"] = max(cuts[-1]["bis"], r["bis"])
            cuts[-1]["grund"] += " + " + r["grund"]
        elif r["bis"] - r["von"] >= 0.03:
            cuts.append(dict(r))
    keep, t = [], von
    for c in cuts:
        if c["von"] - t >= R["stueck_min"]:
            keep.append((round(t, 3), round(c["von"], 3)))
        else:
            warn.append(f"Stück {t:.2f}–{c['von']:.2f} s zu kurz, entfällt")
        t = c["bis"]
    if bis - t >= R["stueck_min"]:
        keep.append((round(t, 3), round(bis, 3)))
    sp = sum(c["bis"] - c["von"] for c in cuts)
    if sp > R["viel"] * (bis - von):
        warn.append(f"{sp / (bis - von) * 100:.0f} % des Stücks fliegen raus: Einstellungen prüfen")
    for c in cuts:
        c["von"], c["bis"] = round(c["von"], 3), round(c["bis"], 3)
    return dict(schnitte=cuts, keep=keep, weg=weg, warn=warn, ersparnis=round(sp, 3))


def expandieren(teile, trs, cfg, env_fn, audio_fn=None):
    """Teilt die Teile von interview.py an den Schnittvorschlägen. teile: Liste von Teilen mit von/bis in Sekunden
    (nach aufloesen), trs: {clip: Transkript}, cfg: schnitt.json (Feld "kuerzen"), env_fn(clip) -> Pegelkurve,
    audio_fn(clip) -> Ton (nur für --zoegern). Gibt (neue Teile, Zuordnung alt->erster neuer Index, Meldungen) zurück.
    Neue Teile tragen _schnitt=True (nicht wieder nahtlos zusammenziehen), _w0/_w1 (Wörter nach Index), _weg
    (entfernte Wörter) und nr (z. B. „7b“)."""
    neu, erste, meld = [], {}, []
    for k, t in enumerate(teile):
        opt = t.get("kuerzen", cfg.get("kuerzen"))
        erste[k] = len(neu)
        t.setdefault("nr", f"#{k + 1}")
        if not opt or t.get("stil") == "frage" or t.get("text"):
            neu.append(t)
            continue
        R = einstellungen(opt, einstellungen(cfg.get("kuerzen")))
        ws = [w for sg in trs[t["clip"]]["segmente"] for w in sg["woerter"]]
        x = audio_fn(t["clip"]) if R["zoegern"] and audio_fn else None
        res = schnitte(ws, env_fn(t["clip"]), t["von"], t["bis"], R, x)
        if not res["schnitte"]:
            neu.append(t)
            continue
        weg = set(res["weg"]) | set(t.get("_weg", ()))
        bilder = t.get("bild") or []
        for m, (a, b) in enumerate(res["keep"]):
            idx = [i for i, w in enumerate(ws) if a <= (w["s"] + w["e"]) / 2 <= b and i not in weg]
            s = {kk: vv for kk, vv in t.items() if kk not in ("_w0", "_w1", "_von", "_bis", "anfang", "ende", "plus")}
            s.update(von=a, bis=b, _schnitt=True, _weg=weg, _tiefe=[],
                     _ohne_pause=[x for x in t.get("_ohne_pause", []) if (x == "Anfang" and m == 0) or (x == "Ende" and m == len(res["keep"]) - 1)],
                     nr=f"#{k + 1}{chr(97 + m)}" if len(res["keep"]) > 1 else f"#{k + 1}")
            s.pop("bild", None)
            for bl in bilder:     # Bild über die Quellzeit verteilen: ab zählt ab dem ursprünglichen Teilanfang
                q0 = t["von"] + float(bl["ab"])
                q1 = q0 + float(bl["dauer"])
                u0, u1 = max(q0, a), min(q1, b)
                if u1 - u0 >= 0.25:
                    s.setdefault("bild", []).append(dict(bl, ab=round(u0 - a, 3), dauer=round(u1 - u0, 3),
                                                         **({"src": round(float(bl["src"]) + (u0 - q0), 3)} if "src" in bl else {})))
            if idx:
                s["_w0"], s["_w1"] = idx[0], idx[-1]
            else:
                s["_w0"], s["_w1"] = len(ws), len(ws) - 1       # keine Wörter (nur Atmer): nichts untertiteln
            if m:
                s.pop("notiz", None)
                s.pop("kopf", None)
            neu.append(s)
        meld.append(f"#{k + 1}: {len(res['schnitte'])} Schnitt(e), {res['ersparnis']:.2f} s gekürzt, "
                    f"{len(res['keep'])} Stück(e)" + (f", {len(res['weg'])} Füllwort/-wörter" if res["weg"] else ""))
        meld += [f"#{k + 1}: {w}" for w in res["warn"]]
    return neu, erste, meld


def main():
    ap = argparse.ArgumentParser(description="Pausen und Füllwörter kürzen")
    ap.add_argument("ton")
    ap.add_argument("--transkript", required=True, help="Ordner mit <stamm>.json aus transkript.py")
    ap.add_argument("--von", type=float)
    ap.add_argument("--bis", type=float)
    ap.add_argument("--pause-max", type=float)
    ap.add_argument("--pause-ziel", type=float)
    ap.add_argument("--stark", action="store_true")
    ap.add_argument("--zoegern", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    R = dict(REGELN, stark=a.stark, zoegern=a.zoegern)
    if a.pause_max:
        R["pause_max"] = a.pause_max
    if a.pause_ziel:
        R["pause_ziel"] = a.pause_ziel
    pfad = Path(a.ton)
    tr = json.loads((Path(a.transkript) / f"{pfad.stem}.json").read_text())
    ws = [w for sg in tr["segmente"] for w in sg["woerter"]]
    x = lesen16(pfad)
    env = huelle(x)
    von, bis = a.von or 0.0, a.bis or len(x) / 16000
    res = schnitte(ws, env, von, bis, R, x)
    print(f"{pfad.name}: {von:.2f}–{bis:.2f} s, {len(ws)} Wörter")
    for c in res["schnitte"]:
        print(f"  schneiden {c['von']:7.3f}–{c['bis']:7.3f} s ({c['bis'] - c['von']:.2f} s)  {c['grund']}")
    print("bleibt: " + ", ".join(f"{p:.2f}–{q:.2f}" for p, q in res["keep"]))
    print(f"Ersparnis {res['ersparnis']:.2f} s von {bis - von:.2f} s ({res['ersparnis'] / (bis - von) * 100:.0f} %), "
          f"{len(res['weg'])} Füllwörter")
    for w in res["warn"]:
        print("WARNUNG", w)
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=list))


if __name__ == "__main__":
    main()
