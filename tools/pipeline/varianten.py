#!/usr/bin/env python3
"""Drei Varianten eines Reels zur Auswahl bauen (Pflicht-Stopp: der Nutzer wählt eine Variante).

    python3 varianten.py <reel-ordner>                    # alle Varianten in schnitt/A, schnitt/B, schnitt/C …
    python3 varianten.py <reel-ordner> --nur B            # nur B neu (nach Änderungen an schnitt/B/edl.py)
    python3 varianten.py <reel-ordner> --check            # nur Unterschied-Check der Schnittlisten, rendert nichts
    python3 varianten.py <reel-ordner> --wahl B [--titel <frame>]   # nach der Wahl: Export, Prüfung, Aufräumen
    python3 varianten.py <reel-ordner> --wahl B --fassung v2         # Feedback-Runde: Ausgabe als <name>_v2_…
    python3 varianten.py <reel-ordner> --wahl B --plattform instagram,youtube   # auch YouTube Shorts

Je Variante X (Ordner schnitt/X/ mit edl.json, fx.json, audio_spec.json aus edl.py): extract.py, render.py master
-> $REEL_WORK/master_X.mp4, Tonspur -> mix_X.wav, vorschau.py -> <reel>/<name>_X_vorschau.mp4 und
storyboard.py --render -> <reel>/<name>_X_storyboard.jpg. Vorher ingest.py (Sichtung) im selben $REEL_WORK.
Die Varianten laufen nacheinander im selben Arbeitsordner; Frames eines Clips werden bei Bedarf neu gezogen.

Unterschied-Check: Jedes Paar soll sich in mindestens 2 von 3 Punkten klar unterscheiden:
  Song      anderer Songabschnitt (Start > 1 Takt auseinander) oder andere Länge
  Auswahl   höchstens die Hälfte der Clips gleich (Jaccard < 0,5), ohne Opener und Finale: Marke, Epic-Shot
            (Zeitlupen-Shots am Anfang, Regel 11) und Gruppenfoto (Regel 12) dürfen in allen Varianten gleich sein
  Tempo     Shot-Länge im Schnitt ≥ 0,5 Beats anders oder Effekt-Dichte ≥ 30 % anders
--wahl X: export.py aus master_X/mix_X (Titelbild: Standard Mitte von Shot 1), verify.py gegen
schnitt/X/edl.json, Storyboard von X als <name>_storyboard.jpg nach oben, alle Varianten-Dateien nach archiv/varianten/.
--plattform (Standard instagram): youtube schreibt <name>_yt_mit_song.mp4, _yt_ohne_ton.mp4, _yt_titelbild.jpg (Ton
−14 LUFS, Profil in plattform.py) und prüft sie mit verify.py und plattform.py; beides geht mit Komma.
Änderungen an der gewählten Variante: schnitt/X/edl.py anpassen, --nur X, dann --wahl X (nach einer Lieferung vorher die
alte Fassung nach archiv/v1/ und --fassung v2).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from itertools import combinations
from pathlib import Path

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
from reelcfg import FPS, PIPE, TOOLS, WORK

EFFEKT_TAGS = ("Punch-in", "Punch ½", "Mini-Punch", "Speed-Ramp", "Flash", "Shake", "Zeitlupe", "Push-in")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def varianten(reel):
    return sorted(d for d in (reel / "schnitt").iterdir() if d.is_dir() and len(d.name) == 1 and d.name.isupper()
                  and (d / "edl.json").exists())


def kennzahlen(d):
    E = json.load(open(d / "edl.json"))
    shots = [s for s in E["shots"] if not s.get("cont")]
    k = next((i for i, s in enumerate(shots[:2]) if s["mode"] not in ("speed", "slow")), 2)   # Zeitlupen-Opener
    mitte = shots[max(1, k):-1] if len(shots) > 3 else shots   # Opener, Epic-Shot, Finale nach Regel 11/12 oft gleich
    clips = {st["clip"] for s in mitte if s["clip"] == "split" for st in s["strips"]} | \
            {s["clip"] for s in mitte if s["clip"] != "split"}
    beats = E.get("beats") or sum(s["beats"] for s in E["shots"])
    fx = sum(len(s.get("fxp", {}).get("punch", [])) + len(s.get("fxp", {}).get("flash", []))
             + len(s.get("fxp", {}).get("shake", [])) + (s["mode"] in ("ramp", "ramp_hold")) for s in E["shots"])
    return dict(name=d.name, label=E.get("variante_name", ""), hinweis=E.get("hinweis", ""), hook=E.get("hook", 0.0),
                per=E["per"], beats=beats, sek=beats * E["per"], shots=len(shots), clips=clips,
                beats_je_shot=beats / max(1, len(shots)), fx_je_16=fx * 64 / beats,
                ramps=sum(s["mode"] in ("ramp", "ramp_hold") for s in E["shots"]))


def check(reel):
    K = [kennzahlen(d) for d in varianten(reel)]
    print(f"{'':3}{'Variante':18}{'Song ab':>9}{'Länge':>8}{'Shots':>6}{'B/Shot':>7}{'FX/16T':>7}{'Ramps':>6}")
    for k in K:
        print(f"{k['name']:3}{k['label'][:17]:18}{k['hook']:8.2f}s{k['sek']:7.1f}s{k['shots']:6d}"
              f"{k['beats_je_shot']:7.1f}{k['fx_je_16']:7.1f}{k['ramps']:6d}   {k['hinweis'][:60]}")
    warn = []
    for a, b in combinations(K, 2):
        song = abs(a["hook"] - b["hook"]) > 4 * a["per"] or a["beats"] != b["beats"]
        jac = len(a["clips"] & b["clips"]) / max(1, len(a["clips"] | b["clips"]))
        tempo = abs(a["beats_je_shot"] - b["beats_je_shot"]) >= 0.5 or \
            abs(a["fx_je_16"] - b["fx_je_16"]) >= 0.3 * max(a["fx_je_16"], b["fx_je_16"], 1)
        n = song + (jac < 0.5) + tempo
        print(f"{a['name']}/{b['name']}: Song {'anders' if song else 'gleich'}, "
              f"Clips {len(a['clips'] & b['clips'])} gemeinsam ({jac:.0%}, ohne Opener/Finale), Tempo/Effekte {'anders' if tempo else 'ähnlich'}"
              f" -> {n} von 3")
        if n < 2:
            warn.append(f"{a['name']} und {b['name']} unterscheiden sich nur in {n} von 3 Punkten")
    if len(K) < 3:
        warn.append(f"nur {len(K)} Variante(n), Standard sind 3")
    print("\n".join("WARNUNG " + w for w in warn) or "Unterschied-Check: alle Varianten klar verschieden")
    return not warn


def sh(cmd, env, log):
    t0 = time.time()
    r = subprocess.run([str(c) for c in cmd], env=env, capture_output=True, text=True)
    (WORK / log).write_text(r.stdout + r.stderr)
    if r.returncode:
        sys.exit(f"FEHLER in {Path(str(cmd[1])).name} (Log {WORK / log}):\n{(r.stdout + r.stderr)[-1500:]}")
    return time.time() - t0, r.stdout


def bauen(reel, nur=None):
    name = reel.name.split("_", 1)[1] if "_" in reel.name else reel.name
    py, out = sys.executable, []
    for d in varianten(reel):
        x = d.name
        if nur and x not in nur:
            continue
        env = dict(os.environ, REEL_WORK=str(WORK), REEL_EDL=str(d / "edl.json"), REEL_FX=str(d / "fx.json"),
                   PYTHONDONTWRITEBYTECODE="1")
        master, mix = WORK / f"master_{x}.mp4", WORK / f"mix_{x}.wav"
        vor, sb = reel / f"{name}_{x}_vorschau.mp4", reel / f"{name}_{x}_storyboard.jpg"
        print(f"Variante {x}: Frames …", flush=True)
        t1, o = sh([py, PIPE / "extract.py"], env, f"extract_{x}.log")
        if "WARNUNG" in o or "fehlgeschlagen" in o:
            print(o)
        print(f"Variante {x}: Master …", flush=True)
        t2, _ = sh([py, PIPE / "render.py", "master", master], env, f"render_{x}.log")
        t3, _ = sh([py, TOOLS / "reel_audio.py", "mix", d / "audio_spec.json", mix], env, f"mix_{x}.log")
        t4, _ = sh([py, PIPE / "vorschau.py", master, vor, mix, "--loop", arg("--loop", "8")], env, f"vorschau_{x}.log")
        t5, _ = sh([py, PIPE / "storyboard.py", sb, "--render"], env, f"storyboard_{x}.log")
        print(f"Variante {x}: fertig (Frames {t1:.0f} s, Master {t2:.0f} s, Ton {t3:.0f} s, Vorschau {t4:.0f} s, "
              f"Storyboard {t5:.0f} s)", flush=True)
        out += [vor, sb]
    check(reel)
    print("Zum Anhängen:\n" + "\n".join(f"  {p}" for p in out))


def wahl(reel, x, fassung=None, plattform="instagram"):
    import plattform as pf
    profile = pf.plattformen(plattform)
    name = reel.name.split("_", 1)[1] if "_" in reel.name else reel.name
    stem = f"{name}_{fassung}" if fassung else name
    d = reel / "schnitt" / x
    master, mix = WORK / f"master_{x}.mp4", WORK / f"mix_{x}.wav"
    if not (master.exists() and mix.exists()):
        sys.exit(f"{master.name} oder {mix.name} fehlt (Container neu?): erst ingest.py, dann varianten.py {reel} --nur {x}")
    E = json.load(open(d / "edl.json"))
    titel = arg("--titel") or str(round(E["shots"][0]["beats"] * E["per"] * FPS / 2))
    env = dict(os.environ, REEL_WORK=str(WORK), REEL_EDL=str(d / "edl.json"), REEL_FX=str(d / "fx.json"),
               PYTHONDONTWRITEBYTECODE="1")
    py = sys.executable
    sh([py, PIPE / "export.py", master, reel / stem, mix, "--titel", titel, "--plattform", plattform], env, f"export_{x}.log")
    ok = True
    for p in profile:
        r = subprocess.run([py, PIPE / "verify.py", reel / pf.dateiname(stem, p, "mit_song.mp4")], env=env,
                           capture_output=True, text=True)
        print(r.stdout.strip())
        ok = ok and r.returncode == 0
    arch = reel / "archiv" / "varianten"
    arch.mkdir(parents=True, exist_ok=True)
    sb = reel / f"{name}_{x}_storyboard.jpg"
    if sb.exists():
        shutil.copy2(sb, reel / f"{stem}_storyboard.jpg")
    for p in sorted(reel.glob(f"{name}_[A-Z]_*")):
        shutil.move(str(p), arch / p.name)
    dateien = ", ".join(f"{pf.dateiname(stem, p, a)}" for p in profile for a in ("mit_song.mp4", "ohne_ton.mp4", "titelbild.jpg"))
    print(f"Variante {x} exportiert: {dateien} (Frame {titel}); Varianten-Dateien in {arch}")
    return ok


if __name__ == "__main__":
    pos = [a for a in sys.argv[1:] if not a.startswith("--") and a not in
           {arg(n) for n in ("--nur", "--wahl", "--titel", "--loop", "--fassung", "--plattform")}]
    if not pos:
        sys.exit(__doc__)
    reel = Path(pos[0]).resolve()
    if "--check" in sys.argv:
        sys.exit(0 if check(reel) else 1)
    if "--wahl" in sys.argv:
        sys.exit(0 if wahl(reel, arg("--wahl"), arg("--fassung"), arg("--plattform", "instagram")) else 1)
    bauen(reel, set(arg("--nur").split(",")) if arg("--nur") else None)
