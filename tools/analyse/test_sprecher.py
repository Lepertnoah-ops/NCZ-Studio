#!/usr/bin/env python3
"""Test von sprecher.py ohne Drive und ohne echte Clips (~30 s ohne Modell-Download).

    cd /tmp && python3 /mnt/project-files/tools/analyse/test_sprecher.py

Teil 1 (immer, ohne Modell): Wortzuordnung und Segmentteilung mit erfundenen Turns, Fragesätze, Hinweis zum Fragesteller,
Pausen, Viterbi, sicherer Modell-Download gegen file://-Adressen (richtige Datei, falsche Größe, HTML statt Modell,
falsche Prüfsumme).
Teil 2 (nur mit sherpa-onnx, beiden Modellen in modelle/sprecher/ und espeak-ng, sonst SKIP mit Grund): künstlicher
Testton aus zwei klar verschiedenen Stimmen (espeak-ng, abwechselnd, bekannte Zeiten). Erwartet: 2 Sprecher, Wechsel auf
±0,3 s, richtige Wörter je Sprecher, CLI mit Stamm aus $REEL_WORK/audio. Das Werkzeug lädt im Test nichts nach.
Läuft in einem temporären REEL_WORK und hinterlässt nichts im Projektordner.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True
TMP = tempfile.mkdtemp(prefix="sprecher_test_")
os.environ["REEL_WORK"] = TMP
tempfile.tempdir = TMP          # auch die Sperrdateien des Downloads landen im Testordner und verschwinden mit ihm
HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
PYCACHE_VORHER = (HIER / "__pycache__").exists()
import numpy as np

import sprecher as sp

FEHLER = []


def pruefe(name, bedingung, detail=""):
    print(("ok      " if bedingung else "FEHLER  ") + name + (f"  ({detail})" if detail and not bedingung else ""))
    if not bedingung:
        FEHLER.append(name)


def w(text, s, e):
    return dict(w=text, s=s, e=e, p=0.9)


# ---------------------------------------------------------------- Teil 1: Logik ohne Modell

def test_zuordnung():
    turns = [dict(von=0.0, bis=2.0, sprecher="S1"), dict(von=2.3, bis=4.0, sprecher="S2"),
             dict(von=4.5, bis=4.9, sprecher="S1", unsicher=True), dict(von=5.5, bis=7.0, sprecher="S2")]
    ws = [w("Und", 0.0, 0.3), w("dir", 0.3, 0.6), w("schmeckt's?", 0.6, 1.5),      # S1
          w("Ja,", 2.4, 2.7), w("sehr", 2.7, 3.0), w("gut.", 3.0, 3.6),             # S2
          w("Wie", 4.55, 4.75),                                                     # unsicherer Turn
          w("ihr", 7.4, 7.6)]                                                       # weit weg von jedem Turn
    tr = dict(dauer=8.0, segmente=[dict(s=0.0, e=3.6, text="Und dir schmeckt's? Ja, sehr gut.", pegel=-20.0,
                                        woerter=ws[:6]),
                                   dict(s=4.55, e=7.6, text="Wie ihr", pegel=-30.0, woerter=ws[6:])])
    neu = sp.woerter_zuordnen(tr, turns)
    segs = neu["segmente"]
    pruefe("Segment an Sprecherwechsel geteilt (2 + 1 + 1 Segmente)", len(segs) == 3 and segs[0]["text"] == "Und dir schmeckt's?"
           and segs[1]["text"] == "Ja, sehr gut.", [s["text"] for s in segs])
    pruefe("Sprecher je Segment", [s["sprecher"] for s in segs[:2]] == ["S1", "S2"])
    pruefe("sichere Wörter tragen den Sprecher", [x["sprecher"] for x in segs[0]["woerter"]] == ["S1"] * 3
           and [x["sprecher"] for x in segs[1]["woerter"]] == ["S2"] * 3)
    wie, ihr = segs[2]["woerter"]
    pruefe("Wort im unsicheren Turn: ? mit Vermutung", wie["sprecher"] == "?" and wie.get("vermutet") == "S1", str(wie))
    pruefe("Wort ohne Sprache in der Nähe: ? ohne Vermutung", ihr["sprecher"] == "?" and "vermutet" not in ihr, str(ihr))
    pruefe("Original bleibt unverändert", "sprecher" not in tr["segmente"][0]["woerter"][0])
    # Wortgrenze: halb in S1, halb in S2
    grenz = dict(dauer=3.0, segmente=[dict(s=1.8, e=2.6, text="doch ja", pegel=-20.0,
                                           woerter=[w("doch", 1.8, 2.5), w("ja", 2.5, 2.6)])])
    n2 = sp.woerter_zuordnen(grenz, [dict(von=0.0, bis=2.15, sprecher="S1"), dict(von=2.15, bis=3.0, sprecher="S2")])
    doch = n2["segmente"][0]["woerter"][0]
    pruefe("Wort über die Wortgrenze: ? mit Vermutung", doch["sprecher"] == "?" and doch.get("vermutet") in ("S1", "S2"), str(doch))
    # Überlappung
    ueb = sp.woerter_zuordnen(dict(dauer=3.0, segmente=[dict(s=0.2, e=1.0, text="Ja", pegel=-20.0, woerter=[w("Ja", 0.2, 1.0)])]),
                              [dict(von=0.0, bis=3.0, sprecher="S1")], ueberlappung=[[0.1, 1.2]])
    pruefe("Wort in Überlappung: ?", ueb["segmente"][0]["woerter"][0]["sprecher"] == "?")


def test_teilen_und_saetze():
    def mk(*paare):
        return [dict(w=f"w{i}", s=i * 0.5, e=i * 0.5 + 0.3, sprecher=s, **({"vermutet": v} if v else {}))
                for i, (s, v) in enumerate(paare)]
    ws = mk(("S1", None), ("S1", None), ("?", "S2"), ("S1", None), ("S1", None))
    pruefe("einzelnes vermutetes Wort zwischen gleichen Sprechern ist kein Wechsel", len(sp._teilen(ws)) == 1)
    ws = mk(("S1", None), ("S1", None), ("?", "S2"), ("?", "S2"), ("S2", None))
    g = sp._teilen(ws)
    pruefe("Wechsel mit vermuteten Wörtern wird geteilt", len(g) == 2 and len(g[0]) == 2, str([len(x) for x in g]))
    # Schnitt an der größten Pause
    ws = [dict(w="a", s=0, e=1, sprecher="S1"), dict(w="b", s=1.1, e=1.5, sprecher="?", vermutet="S1"),
          dict(w="c", s=2.4, e=2.8, sprecher="?", vermutet="S2"), dict(w="d", s=2.85, e=3.0, sprecher="S2")]
    g = sp._teilen(ws)
    pruefe("Schnitt an der größten Pause", [len(x) for x in g] == [2, 2], str([len(x) for x in g]))
    tr = dict(segmente=[dict(woerter=[dict(w="Gut.", sprecher="S1"), dict(w="Kommt", sprecher="S2"), dict(w="ihr", sprecher="S2"),
                                      dict(w="wieder?", sprecher="S2"), dict(w="Ja", sprecher="S1")])])
    pruefe("Fragesätze je Sprecher", sp.fragen_je_sprecher(tr) == {"S2": 1}, str(sp.fragen_je_sprecher(tr)))
    pruefe("Text mit Bindestrich-Wörtern", sp._text([dict(w="Ich"), dict(w="-bin"), dict(w="-stärker"), dict(w="oder")]) == "Ich-bin-stärker oder")


def test_hinweis():
    kz = {"S1": dict(redezeit_s=5, pegel_db=-20.0, fragen=3), "S2": dict(redezeit_s=9, pegel_db=-28.0, fragen=0)}
    h = sp.hinweis_fragesteller(kz)
    pruefe("Hinweis: mehr Fragen und lauter", h and "wahrscheinlich S1" in h and "nur ein Hinweis" in h, str(h))
    kz["S2"]["pegel_db"] = -14.0
    h = sp.hinweis_fragesteller(kz)
    pruefe("Hinweis bei Widerspruch: unklar", h and "unklar" in h, str(h))
    pruefe("Hinweis bei einem Sprecher: keiner", sp.hinweis_fragesteller({"S1": dict(redezeit_s=5, pegel_db=-20.0)}) is None)
    pruefe("Hinweis ohne Unterschied: keiner", sp.hinweis_fragesteller(
        {"S1": dict(redezeit_s=5, pegel_db=-20.0, fragen=1), "S2": dict(redezeit_s=5, pegel_db=-20.5, fragen=1)}) is None)


def test_signal():
    # Viterbi: ein kurzer Ausreißer wird geglättet, ein langer Wechsel bleibt
    S = np.zeros((20, 2))
    S[:, 0] = 0.6
    S[:, 1] = 0.2
    S[5, :] = [0.2, 0.6]
    S[12:, :] = [0.2, 0.6]
    lab = sp._viterbi(S, 0.3)
    pruefe("Viterbi glättet Ausreißer, hält den Wechsel", list(lab[:12]) == [0] * 12 and list(lab[12:]) == [1] * 8, str(list(lab)))
    m = np.array([0, 1, 1, 0, 0, 0, 1, 1, 1, 1], bool)
    pruefe("Lücken füllen und kurze Abschnitte verwerfen", sp._luecken_fuellen(m, 1.0, 3.0, 2.0) == [(1, 10)]
           and sp._luecken_fuellen(m, 1.0, 1.0, 2.5) == [(6, 10)], str(sp._luecken_fuellen(m, 1.0, 1.0, 2.5)))
    # Pausen teilen: Rauschburst, Stille, Rauschburst
    rng = np.random.default_rng(3)
    x = np.concatenate([rng.standard_normal(16000) * 0.1, rng.standard_normal(4800) * 0.0003,
                        rng.standard_normal(16000) * 0.1]).astype(np.float32)
    teile = sp._pausen_teilen(x, [(0.0, 2.3)])
    pruefe("Region an der Pause geteilt", len(teile) == 2 and abs(teile[0][1] - 1.0) < 0.05 and abs(teile[1][0] - 1.3) < 0.05, str(teile))
    pruefe("Region ohne Pause bleibt", sp._pausen_teilen(x[:16000], [(0.0, 1.0)]) == [(0.0, 1.0)])
    t = sp._benennen([dict(von=0, bis=2, g=7, marge=0.3), dict(von=2.1, bis=2.4, g=3, marge=0.3), dict(von=3, bis=5, g=7, marge=0.3)])
    pruefe("Benennen nach erstem Auftritt, kurzer Turn unsicher", [a["sprecher"] for a in t] == ["S1", "S2", "S1"]
           and t[1].get("unsicher") and not t[0].get("unsicher"), str(t))


def test_download():
    """Sicherer Download gegen file://: Größe, Dateikopf, Prüfsumme."""
    d = Path(TMP) / "dl"
    d.mkdir()
    gut = b"\x08\x07\x12\x07pytorch" + b"\x00" * 5000
    (d / "gut.onnx").write_bytes(gut)
    (d / "html.onnx").write_bytes(b"<!DOCTYPE html><html>Fehler</html>".ljust(5000, b" "))
    sha = hashlib.sha256(gut).hexdigest()
    url = lambda n: "file://" + str(d / n)
    ziel = d / "ziel" / "m.onnx"
    sp._laden(url("gut.onnx"), ziel, len(gut), sha, sp._kopf_onnx)
    pruefe("Modell geladen und umbenannt", ziel.exists() and ziel.stat().st_size == len(gut) and not ziel.with_name("m.onnx.part").exists())
    mtime = ziel.stat().st_mtime_ns
    sp._laden(url("gut.onnx"), ziel, len(gut), sha, sp._kopf_onnx)
    pruefe("vorhandenes, geprüftes Modell wird nicht neu geladen", ziel.stat().st_mtime_ns == mtime)
    for name, args, grund in (("falsche Größe", (url("gut.onnx"), d / "z1.onnx", len(gut) + 1, sha), "Größe"),
                              ("HTML statt Modell", (url("html.onnx"), d / "z2.onnx", 5000, sha), "Dateikopf"),
                              ("falsche Prüfsumme", (url("gut.onnx"), d / "z3.onnx", len(gut), "0" * 64), "Prüfsumme"),
                              ("fehlende Datei", (url("fehlt.onnx"), d / "z4.onnx", 10, sha), "curl")):
        try:
            sp._laden(*args, sp._kopf_onnx)
            pruefe(f"Download-Fehler erkannt: {name}", False, "kein Fehler")
        except RuntimeError as e:
            pruefe(f"Download-Fehler erkannt: {name}", grund in str(e) or grund == "curl", str(e)[:80])
        pruefe(f"nichts Halbes liegen gelassen: {name}", not args[1].exists() and not args[1].with_name(args[1].name + ".part").exists())


# ---------------------------------------------------------------- Teil 2: espeak-ng und Modelle

SAETZE = [("A", "Und dir schmeckt es hier wirklich gut?"), ("B", "Ja, sehr gut, das Training ist richtig anstrengend."),
          ("A", "Ihr kommt nächste Woche wieder?"), ("B", "Auf jeden Fall, wir bringen noch Freunde mit."),
          ("A", "Wie findest du die Gruppe?"), ("B", "Die Leute sind super freundlich und helfen sich gegenseitig.")]
STIMME = {"A": ["-v", "de+m3", "-p", "20", "-s", "150"], "B": ["-v", "de+f3", "-p", "75", "-s", "160"]}


def testton():
    """(Ton float32 16 kHz, [(Stimme, von, bis, Text)]) aus zwei espeak-Stimmen mit 0,5 s Pausen."""
    teile, t, stuecke = [], 0.0, []
    for wer, text in SAETZE:
        wav = Path(TMP) / "s.wav"
        subprocess.run(["espeak-ng", *STIMME[wer], text, "-w", str(wav)], check=True, capture_output=True)
        x = sp.lade_ton(wav)
        stuecke += [np.zeros(8000, np.float32), x]
        teile.append((wer, t + 0.5, t + 0.5 + len(x) / sp.SR, text))
        t += 0.5 + len(x) / sp.SR
    stuecke.append(np.zeros(8000, np.float32))
    return np.concatenate(stuecke), teile


def schreibe_flac(x, pfad):
    wav = Path(pfad).with_suffix(".wav")
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sp.SR)
        f.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-ar", "48000", str(pfad)], check=True)
    wav.unlink()


def test_zwei_stimmen():
    if not shutil.which("espeak-ng"):
        print("SKIP    Zwei-Stimmen-Test: espeak-ng fehlt (apt-get install -y espeak-ng)")
        return
    ok, grund = sp.verfuegbar()
    if not ok:
        print(f"SKIP    Zwei-Stimmen-Test: {grund} (python3 sprecher.py --vorbereiten lädt nach)")
        return
    x, teile = testton()
    (Path(TMP) / "audio").mkdir()
    schreibe_flac(x, Path(TMP) / "audio" / "test_zwei.flac")
    # Transkript: Wörter gleichmäßig in jeder Äußerung; Frage und Antwort stehen, wie bei Whisper, in einem Segment
    woerter = []
    for wer, s, e, text in teile:
        toks = text.split()
        dt = (e - s) / len(toks)
        woerter += [dict(w=t, s=round(s + i * dt, 3), e=round(s + (i + 1) * dt, 3), p=0.9, wer=wer) for i, t in enumerate(toks)]
    segs = []
    for k in range(0, len(woerter), 12):          # grob in Stücken, die Sprecherwechsel überdecken
        ws = woerter[k:k + 12]
        segs.append(dict(s=ws[0]["s"], e=ws[-1]["e"], text=" ".join(v["w"] for v in ws), pegel=-20.0,
                         woerter=[{a: b for a, b in v.items() if a != "wer"} for v in ws]))
    trdir = Path(TMP) / "transkript"
    trdir.mkdir()
    (trdir / "test_zwei.json").write_text(json.dumps(dict(dauer=len(x) / sp.SR, segmente=segs)))

    # Importierte Funktionen
    turns = sp.sprecher_turns(Path(TMP) / "audio" / "test_zwei.flac")
    namen = sorted({t["sprecher"] for t in turns})
    pruefe("2 Sprecher erkannt", namen == ["S1", "S2"], str(namen))
    # Wechsel: jeder erwartete Beginn eines Sprechers liegt auf ±0,3 s an einem Turn-Beginn des passenden Sprechers
    abbild = {}
    treffer = 0
    for wer, s, e, _ in teile:
        mitte = (s + e) / 2
        t = next((t for t in turns if t["von"] <= mitte <= t["bis"]), None)
        if t:
            abbild.setdefault(wer, set()).add(t["sprecher"])
        if t and abs(t["von"] - s) <= 0.3:
            treffer += 1
    pruefe("jede Stimme genau einem Sprecher zugeordnet", all(len(v) == 1 for v in abbild.values()) and len(abbild) == 2
           and abbild["A"] != abbild["B"], str(abbild))
    pruefe("6 Wechsel auf ±0,3 s", treffer == 6, f"{treffer} von 6, Turns {[(t['von'], t['bis'], t['sprecher']) for t in turns]}")
    pruefe("Turns sortiert, ohne Überlappung", all(a["bis"] <= b["von"] + 1e-6 for a, b in zip(turns, turns[1:])))

    # CLI mit Stamm aus $REEL_WORK/audio und Transkript
    out = Path(TMP) / "ausgabe"
    env = dict(os.environ, REEL_WORK=TMP, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(HIER / "sprecher.py"), "test_zwei", "-o", str(out), "--transkript", str(trdir)],
                       capture_output=True, text=True, cwd=TMP, env=env)
    pruefe("CLI läuft", r.returncode == 0 and (out / "test_zwei.sprecher.json").exists() and (out / "sprecher.md").exists(),
           (r.stdout + r.stderr)[-300:])
    if not (out / "test_zwei.sprecher.json").exists():
        return
    res = json.loads((out / "test_zwei.sprecher.json").read_text())
    pruefe("JSON: turns, sprecher, hinweis, segmente", all(k in res for k in ("turns", "sprecher", "hinweis", "segmente", "verfahren")))
    pruefe("JSON: Kennzahlen je Sprecher", all(set(d) >= {"redezeit_s", "pegel_db", "tonhoehe_hz", "fragen"} for d in res["sprecher"].values()),
           str(res["sprecher"]))
    # Tonhöhe: A tief (-p 20), B hoch (-p 75)
    hz = {s: d["tonhoehe_hz"] for s, d in res["sprecher"].items()}
    a_sp, b_sp = sorted(abbild["A"])[0], sorted(abbild["B"])[0]
    pruefe("Tonhöhe: Stimme B höher als A", hz.get(a_sp) and hz.get(b_sp) and hz[b_sp] > hz[a_sp] * 1.15, str(hz))
    fr = {s: d["fragen"] for s, d in res["sprecher"].items()}
    pruefe("Fragesätze: A stellt 3 Fragen", fr.get(a_sp) == 3 and fr.get(b_sp) == 0, str(fr))
    pruefe("Hinweis nennt den Fragesteller", res["hinweis"] and a_sp in res["hinweis"], str(res["hinweis"]))
    # Wörter: alle mit Abstand ≥ 0,3 s zu den Äußerungsgrenzen haben den richtigen Sprecher
    richtig = falsch = unsicher = 0
    for sg in res["segmente"]:
        for v in sg["woerter"]:
            wer = next(t[0] for t in teile if t[1] - 0.05 <= v["s"] and v["e"] <= t[2] + 0.05)
            if v["sprecher"] == "?":
                unsicher += 1
            elif v["sprecher"] in abbild[wer]:
                richtig += 1
            else:
                falsch += 1
    pruefe("Wörter: keine falsche Zuordnung", falsch == 0 and richtig >= 0.8 * (richtig + unsicher), f"richtig {richtig}, falsch {falsch}, ? {unsicher}")
    pruefe("Segmente an den Wechseln geteilt", len(res["segmente"]) >= 6 and all(s["sprecher"] in ("S1", "S2") for s in res["segmente"]),
           str([(s["s"], s["sprecher"]) for s in res["segmente"]]))
    md = (out / "sprecher.md").read_text()
    pruefe("sprecher.md: je Sprecherwechsel eine Zeile mit Text", md.count("**S1**") >= 3 and "Auf jeden Fall" in md and "Fragesteller" in md)


def main():
    for f in (test_zuordnung, test_teilen_und_saetze, test_hinweis, test_signal, test_download, test_zwei_stimmen):
        try:
            f()
        except Exception as e:
            import traceback
            traceback.print_exc()
            pruefe(f"{f.__name__} ohne Ausnahme", False, f"{type(e).__name__}: {e}")
    pruefe("kein __pycache__ im Projektordner entstanden", PYCACHE_VORHER or not (HIER / "__pycache__").exists())
    shutil.rmtree(TMP, ignore_errors=True)
    print("ALLES OK" if not FEHLER else f"{len(FEHLER)} FEHLER: " + "; ".join(FEHLER))
    return 1 if FEHLER else 0


if __name__ == "__main__":
    sys.exit(main())
