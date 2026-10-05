#!/usr/bin/env python3
"""Test von kuerzen.py ohne Drive und ohne Whisper (~10 s): künstliche Sprache mit bekannten Pausen und Füllwort.

    python3 test_kuerzen.py

Der Ton (16 kHz, Grundrauschen, tonhafte „Wörter“ mit Silbenrhythmus) hat: eine lange Pause mitten im Satz (0,9 s),
eine lange Pause nach Satzende (0,8 s), ein Füllwort „ähm“ (0,5 s, Stille 0,8 s davor und 0,3 s danach), kurze Pausen
(0,15–0,2 s) und einen Zögerlaut ohne Wort im Transkript. Erwartung: lange Pausen werden auf das Ziel gekürzt, das
Füllwort samt Stille verschwindet, kurze Pausen bleiben, jeder Schnitt liegt in der Stille, die Wörter bleiben ganz,
expandieren() teilt einen Teil richtig (Wortbereiche ohne das Füllwort, Fragen unberührt).
"""
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kuerzen  # noqa: E402

SR = 16000


def ok(text):
    print("OK  ", text, flush=True)


def wort(d, f0=120.0, rs=None):
    t = np.arange(int(d * SR)) / SR
    ph = 2 * np.pi * np.cumsum(f0 * (1 + 0.12 * np.sin(2 * np.pi * 3.0 * t))) / SR   # Tonhöhe gleitet: kein Dauerton
    x = sum(np.sin(h * ph) / h for h in range(1, 6))
    am = 0.55 + 0.45 * np.sin(2 * np.pi * 4.5 * t + 1.0)
    fen = np.minimum(1, np.minimum(t / 0.03, (d - t) / 0.04))
    return 0.14 * x * am * fen


def dauerlaut(d, f0=130.0):
    t = np.arange(int(d * SR)) / SR
    fen = np.minimum(1, np.minimum(t / 0.05, (d - t) / 0.06))
    return 0.11 * sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 6)) * fen


def bauen():
    rs = np.random.RandomState(3)
    # (art, text, dauer) oder ("stille", dauer)
    plan = [("stille", 0.5), ("w", "das", 0.30), ("stille", 0.15), ("w", "erste", 0.35), ("stille", 0.90),
            ("w", "Mal.", 0.40), ("stille", 0.80), ("f", "ähm", 0.50), ("stille", 0.30), ("w", "also", 0.30),
            ("stille", 0.20), ("w", "gut", 0.40), ("stille", 0.70), ("z", "", 0.55), ("stille", 0.70), ("w", "weiter", 0.45),
            ("stille", 0.5)]
    stuecke, ws, t = [], [], 0.0
    for p in plan:
        if p[0] == "stille":
            stuecke.append(np.zeros(int(p[1] * SR)))
            t += p[1]
            continue
        art, text, d = p
        stuecke.append(dauerlaut(d) if art in "fz" else wort(d))
        if art != "z":        # Zögerlaut steht nicht im Transkript; Whisper-Wortenden liegen oft 0,1 s zu früh
            ws.append(dict(w=text, s=round(t, 3), e=round(t + d - 0.1, 3), p=0.9))
        t += d
    x = np.concatenate(stuecke) + rs.randn(int(t * SR) + 10)[:sum(len(s) for s in stuecke)] * 0.0006
    return x.astype(np.float32), ws, t


def main():
    x, ws, dauer = bauen()
    env = kuerzen.huelle(x, SR)
    boden = float(np.percentile(env, 5))
    thr = boden + 5
    R = dict(kuerzen.REGELN)
    res = kuerzen.schnitte(ws, env, 0.0, dauer, R, x)
    for c in res["schnitte"]:
        print(f"  {c['von']:.3f}–{c['bis']:.3f}  {c['grund']}")
    # 1. lange Pause mitten im Satz (Stille 1,4–2,3 s, Wort „erste“ endet im Ton bei 1,4 s): Rest ~ pause_ziel
    p1 = [c for c in res["schnitte"] if "Pause" in c["grund"] and 1.3 < c["von"] < 2.4]
    assert p1, res["schnitte"]
    rest1 = 0.90 - (p1[0]["bis"] - p1[0]["von"])
    assert abs(rest1 - R["pause_ziel"]) < 0.08, rest1
    ok(f"Pause 0,90 s mitten im Satz bleibt {rest1:.2f} s (Ziel {R['pause_ziel']} s)")
    # 2. Füllwort samt Stille: Schnitt deckt 4,05–4,55 s (ähm) ab, es bleiben ungefähr pause_fuell
    f = [c for c in res["schnitte"] if "Füllwort" in c["grund"]]
    assert len(f) == 1, res["schnitte"]
    t_ahm = [w for w in ws if w["w"] == "ähm"][0]["s"]
    assert f[0]["von"] < t_ahm + 0.05 and f[0]["bis"] > t_ahm + 0.4, (f, t_ahm)
    assert res["weg"] == [3], res["weg"]
    nach_f = ([w for w in ws if w["w"] == "also"][0]["s"]) - (([w for w in ws if w["w"] == "Mal."][0]["s"]) + 0.40)
    rest_f = nach_f - (f[0]["bis"] - f[0]["von"])
    assert 0.06 < rest_f < 0.5, rest_f
    ok(f"Füllwort „ähm“ samt Stille entfernt, zwischen „Mal.“ und „also“ bleiben {rest_f:.2f} s")
    # 3. kurze Pausen (0,15 s bei 0,8 s und 0,2 s bei 4,5 s) bleiben unberührt
    kurz = [c for c in res["schnitte"] if 0.7 < c["von"] < 1.0 or 4.4 < c["von"] < 4.8]
    assert not kurz, kurz
    ok("kurze Pausen bleiben")
    # 4. jeder Schnitt beginnt und endet in der Stille, die Wörter bleiben ganz
    for c in res["schnitte"]:
        for t in (c["von"], c["bis"]):
            assert env[int(t * kuerzen.HZ)] <= thr + 6, (t, env[int(t * kuerzen.HZ)], thr)
    for w in ws:
        if w["w"] == "ähm":
            continue
        s, e = w["s"] + 0.03, w["s"] + 0.25      # Kern des Worts
        assert not [c for c in res["schnitte"] if c["von"] < e and c["bis"] > s], (w, res["schnitte"])
    ok("alle Schnitte liegen in der Stille, kein Wort wird angeschnitten")
    # 5. Stücke: zusammengesetzt kürzer um die Ersparnis, Fugen leise
    kept = np.concatenate([x[int(a * SR):int(b * SR)] for a, b in res["keep"]])
    assert abs((dauer - len(kept) / SR) - res["ersparnis"]) < 0.03, (dauer, len(kept) / SR, res["ersparnis"])
    env2 = kuerzen.huelle(kept, SR)
    pos = np.cumsum([0] + [int((b - a) * SR) for a, b in res["keep"]])[1:-1]
    for p in pos:
        assert env2[min(len(env2) - 1, int(p / SR * kuerzen.HZ))] <= thr + 6, p
    ok(f"zusammengesetzt {len(kept) / SR:.2f} s statt {dauer:.2f} s, Fugen leise")
    # 6. Zögerlaut ohne Wort: nur mit zoegern
    assert not any("Zögerlaut" in c["grund"] for c in res["schnitte"])
    R2 = dict(R, zoegern=True)
    res2 = kuerzen.schnitte(ws, env, 0.0, dauer, R2, x)
    z = [c for c in res2["schnitte"] if "Zögerlaut" in c["grund"]]
    assert len(z) == 1 and 5.1 < z[0]["von"] < 5.8 and z[0]["bis"] > 6.3, res2["schnitte"]
    ok(f"--zoegern findet den Laut ohne Wort ({z[0]['von']:.2f}–{z[0]['bis']:.2f} s)")
    # 7. stark: „also“ steht allein nach einer Pause (Stille 0,3 s davor) und wird mit --stark entfernt
    res3 = kuerzen.schnitte(ws, env, 0.0, dauer, dict(R, stark=True), x)
    assert len(res3["weg"]) == 2, res3["weg"]
    ok("--stark nimmt „also“ dazu, ohne --stark bleibt es")
    # 8. expandieren: Teil wird geteilt, Wörter nach Index ohne Füllwort, Frage unberührt
    trs = {"T": dict(segmente=[dict(woerter=ws)])}
    teile = [dict(clip="T", von=0.3, bis=dauer - 0.3, notiz="Antwort"), dict(clip="T", von=0.3, bis=3.0, stil="frage")]
    neu, erste, meld = kuerzen.expandieren(teile, trs, dict(kuerzen=True), lambda c: env)
    assert len(neu) > 2 and neu[-1].get("stil") == "frage" and erste == {0: 0, 1: len(neu) - 1}, (len(neu), erste)
    assert all(t.get("_schnitt") for t in neu[:-1]) and neu[0]["nr"] == "#1a" and neu[1]["nr"] == "#1b", [t.get("nr") for t in neu]
    assert "notiz" in neu[0] and "notiz" not in neu[1]
    worte = []
    for t in neu[:-1]:
        worte += [ws[i]["w"] for i in range(t["_w0"], t["_w1"] + 1) if i not in t["_weg"]]
    assert worte == [w["w"] for w in ws if w["w"] != "ähm"], worte
    ok(f"expandieren: {len(neu) - 1} Stücke (1a, 1b …), Wörter ohne Füllwort, Frage bleibt ganz")
    # 9. aus: „kuerzen“: false am Teil
    neu2, _, _ = kuerzen.expandieren([dict(clip="T", von=0.3, bis=dauer - 0.3, kuerzen=False)], trs, dict(kuerzen=True), lambda c: env)
    assert len(neu2) == 1
    ok("kuerzen: false am Teil schaltet es aus")
    # 10. Füllwort mitten im Redefluss (keine Stille davor und dahinter, z. B. von Whisper erfunden): nicht geschnitten, gemeldet
    pad = np.zeros(int(0.4 * SR), np.float32)
    x2 = np.concatenate([pad, wort(0.6), wort(0.6), pad]).astype(np.float32) + np.random.RandomState(5).randn(int(2.0 * SR)).astype(np.float32) * 0.0006
    ws2 = [dict(w="das", s=0.4, e=0.9, p=0.9), dict(w="Äh,", s=0.95, e=1.15, p=0.4), dict(w="erste", s=1.15, e=1.5, p=0.9)]
    res4 = kuerzen.schnitte(ws2, kuerzen.huelle(x2, SR), 0.0, 2.0, dict(R, stueck_min=0.05), x2)
    assert not res4["weg"] and not any("Füllwort" in c["grund"] for c in res4["schnitte"]), res4
    assert any("nicht geschnitten" in m for m in res4["warn"]), res4["warn"]
    ok("Füllwort ohne Stille davor und dahinter wird nicht geschnitten, nur gemeldet")
    print("alle Tests grün")
    return 0


if __name__ == "__main__":
    sys.exit(main())
