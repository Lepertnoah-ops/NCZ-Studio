#!/usr/bin/env python3
"""Shotlisten-Vorschlag nach Stil-Leitfaden: volle 4-Takt-Phrasen (Länge aus stil.json "laenge_s"), 4 Kapitel auf
Phrasengrenzen, Szenen meist 4–6 Beats (2 nur für durchgehende Bewegung), Opener und Epic-Shot (0,5×) am Anfang,
Finale 8 Beats, Bild-Akzent aus der Akzent-Karte, Clips nach Kapitel-Tags und Clip-Analyse.
Ohne --takte gilt die Länge nach Regel 2 (so viele Phrasen, dass es mindestens laenge_s[0] Sekunden sind).

    python3 shotliste.py --song OUT/song.json --tags tags.json -o OUTDIR
    python3 shotliste.py --song OUT/song.json --clips OUT/clips.json --tags tags.json --fenster 2 -o OUTDIR
    python3 shotliste.py --song OUT/song.json --tags tags.json --start-takt 8 --takte 8 --auftakt 0 -o OUTDIR
    python3 shotliste.py --song OUT/song.json --tags tags.json --fenster 2 --meiden <reel>/schnitt/A/edl.json -o B
      (Variante B: andere Songstelle, Clips von A nur, wenn sonst nichts passt)

Eingaben:
- song.json von song_analyse.py (Fenster 1 = Empfehlung; --fenster N oder --start-takt/--takte).
- clips.json von clip_analyse.py (optional): Dauer, Highlights (peak), Score je Clip.
- tags.json (optional, sonst nur grober Vorschlag): {"6166": {"kapitel": [3], "tags": ["showpiece", "explosiv"],
  "desc": "Sprung auf die Box", "moment": 6.4}, ...}; "epic" = mehrere Leute halten eine starke Pose (Slot 2),
  "explosiv"/"showpiece" = Highlight eines Kapitels, "durchgehend" = Bewegung ohne Anfang und Ende (darf 2 Beats);
  Schlüssel = Clipname ohne "IMG_" und Endung. Format und Tag-Liste: tags_beispiel.json daneben.

Ausgabe: shotliste.json (Felder der Render-EDL: n, beat, t, beats, clip, src, mode, fx, fxp, desc) und
shotliste.md mit Tabelle und Checkliste. Das ist ein Entwurf fürs Storyboard: Szenenlängen nach der ganzen Aktion
anpassen und In-Punkte an dichten Frames prüfen (Projektanweisungen Punkt 14). Speed-Ramps setzt der Vorschlag nie
(Stil-Leitfaden: nur als Ausnahme, von Hand).

Kapitel-Namen, Länge, Punch-Stärken und Budget kommen aus stil.json. Eigene Phrasen-Muster gehen dort unter
"shotliste": {"phrase": {"k1": [[4, "opener"], …], …}, "halb": {"1": […], …}, "slot_tags": {"slot": [["tag"], …]},
"tempo": {"slot": 0.75}}.
"""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stil import STIL  # noqa: E402

KAPITEL = STIL["kapitel"][:4]
# Slots einer Phrase (16 Beats): (Beats, Slot). Szene so lang wie die ganze Aktion, meist 4–6 Beats;
# 2 Beats nur im Slot durchgehend (Bewegung ohne Anfang und Ende, Stil-Leitfaden Regel 4).
# k1 … k4 = erste Phrase des Kapitels, k1+ … = jede weitere; im letzten Kapitel steht k4 (mit dem Finale) am Schluss.
PHRASE = {
    "k1": [(4, "opener"), (6, "epic"), (6, "branding")],
    "k1+": [(4, "branding"), (6, "action"), (6, "action")],
    "k2": [(4, "action"), (2, "durchgehend"), (6, "highlight"), (4, "action")],
    "k2+": [(6, "action"), (4, "action"), (2, "durchgehend"), (4, "nah")],
    "k3": [(4, "power"), (4, "power"), (2, "durchgehend"), (6, "highlight")],
    "k3+": [(4, "action"), (4, "power"), (4, "nah"), (4, "action")],
    "k4+": [(4, "payoff"), (4, "payoff"), (4, "emotion"), (4, "emotion")],
    "k4": [(4, "payoff"), (4, "emotion"), (8, "finale")],
}
# 8 Takte nur auf Wunsch des Nutzers (Teaser): 4 Kapitel à 2 Takte
HALB = {1: [(4, "opener"), (4, "epic")], 2: [(4, "action"), (4, "highlight")], 3: [(4, "power"), (4, "action")],
        4: [(4, "emotion"), (4, "finale")]}
# Opener in leichter Zeitlupe (Regel 11), Epic-Shot und Finale 0,5× (Regeln 11, 12); sonst Echtzeit, nie schneller
# als 1,0×. Zeitlupe nur aus 60-fps-Material.
TEMPO = {"opener": 0.75, "epic": 0.5, "finale": 0.5 if STIL["finale"]["zeitlupe"] else 1.0}
RESERVIERT = {"epic": {"epic"}, "highlight": {"showpiece", "explosiv"}, "finale": {"finale"}}   # Clips für ihren Slot aufheben


def takte_regel2(per):
    """Regel 2: so viele 4-Takt-Phrasen, dass das Reel mindestens laenge_s[0] Sekunden lang ist (wie edlcheck.py)."""
    return 4 * max(1, int(-(-(STIL["laenge_s"][0] - 0.1) // (16 * per))))


def verteilung(n):
    """Phrasen je Kapitel (Regel 3: 1–3). Unter 4 Phrasen teilen sich Grind und Fight eine."""
    if n < 4:
        return [(1, [1], 1), (2, [2, 3], n - 2), (4, [4], 1)] if n == 3 else [(1, [1], 1), (4, [4], 1)]
    ph = {1: 1, 2: 1, 3: 1, 4: 1}
    for k in [2, 3, 3, 4, 2, 1, 4] * 4:
        if sum(ph.values()) == n:
            break
        if ph[k] < 3:
            ph[k] += 1
    ph[3] += n - sum(ph.values())   # mehr als 12 Phrasen: Rest in Fight & Power
    return [(k, [k], ph[k]) for k in range(1, 5)]


# Welche Tags ein Slot sucht (erste passende Gruppe gewinnt)
SLOT_TAGS = {
    "opener": [["opener"], ["branding", "gruppe"], ["branding"], ["gruppe"]],
    "epic": [["epic"], ["gruppe", "branding"], ["gruppe"], ["branding"]],
    "branding": [["branding"], ["gruppe"], ["action"]],
    "action": [["action"], ["durchgehend"], ["langsam"]],
    "durchgehend": [["durchgehend"], ["action"]],
    "nah": [["action", "nah"], ["nah"], ["action"]],
    "langsam": [["langsam"], ["action"]],
    "highlight": [["explosiv"], ["showpiece"], ["action"]],
    "power": [["power"], ["schlag"], ["action"]],
    "payoff": [["payoff"], ["emotion"], ["action"]],
    "emotion": [["emotion"], ["payoff"], ["gruppe"]],
    "finale": [["finale"], ["gruppe", "branding"], ["gruppe"]],
}
_eigen = STIL.get("shotliste", {})
PHRASE.update({k: [tuple(x) for x in v] for k, v in _eigen.get("phrase", {}).items()})
HALB.update({int(k): [tuple(x) for x in v] for k, v in _eigen.get("halb", {}).items()})
SLOT_TAGS.update(_eigen.get("slot_tags", {}))
TEMPO.update(_eigen.get("tempo", {}))
PUNCH = {"808": STIL["punch"]["808"], "808_nachschlag": STIL["punch"]["nachschlag"], "clap": STIL["punch"]["clap"]}
BUDGET = STIL["budget"]
MEIDEN = set()   # Clips anderer Varianten (--meiden): nur nehmen, wenn sonst nichts passt


def stem(name):
    s = Path(str(name)).stem
    return s[4:] if s.upper().startswith("IMG_") else s


def load_pool(clips_json, tags_json):
    pool = {}
    tags = json.loads(Path(tags_json).read_text()) if tags_json else {}
    for k, v in tags.items():
        if k.startswith("_") or "ausschuss" in v.get("tags", []):
            continue
        pool[k] = dict(clip=k, kapitel=v.get("kapitel", [1, 2, 3, 4]), tags=set(v.get("tags", [])),
                       desc=v.get("desc", ""), moment=v.get("moment"), sauber=v.get("sauber"), dur=None, fps=None, score=50.0,
                       highlights=[], analysiert=False)
    if clips_json:
        for c in json.loads(Path(clips_json).read_text()).get("clips", []):
            k = stem(c["name"])
            if tags and k not in pool:
                continue                       # mit Tags: nur getaggte, nicht als Ausschuss markierte Clips
            p = pool.setdefault(k, dict(clip=k, kapitel=[1, 2, 3, 4], tags={"action"}, desc=c["name"], moment=None))
            m = c.get("stats", {}).get("motion_mean", 0)
            p.update(dur=c.get("dur"), fps=c.get("fps"), score=float(c.get("score", 50)),
                     highlights=c.get("highlights", []), analysiert=True, motion=m, flags=c.get("flags", []))
            if not tags:                        # ohne Tags: grob nach Bewegung einteilen
                p["tags"] = {"action", "durchgehend"} if m > 0 else {"gruppe"}
    return pool


def pick(pool, used, kaps, slot, need_s):
    frei = lambda p: p["clip"] not in used and (p["dur"] is None or p["dur"] >= need_s) and \
        all(slot == s or not (tg & p["tags"]) for s, tg in RESERVIERT.items())
    for group in SLOT_TAGS[slot]:
        cands = [p for p in pool.values() if frei(p) and set(kaps) & set(p["kapitel"]) and set(group) <= p["tags"]]
        if not cands:
            cands = [p for p in pool.values() if frei(p) and set(group) <= p["tags"]
                     and not ({"payoff"} & p["tags"] and 4 not in kaps)]
        if cands:
            # analysierte zuerst, dann Score, dann bekannter Moment
            cands.sort(key=lambda p: (p["clip"] in MEIDEN, -p["analysiert"], -p["score"], p["moment"] is None))
            return cands[0], group
    # kein Tag passt (z. B. neuer Ordner ohne Tags): bester freier Clip statt Lücke
    rest = [p for p in pool.values() if frei(p) and not ({"payoff"} & p["tags"] and 4 not in kaps)]
    if rest:
        rest.sort(key=lambda p: (p["clip"] in MEIDEN, -p["analysiert"], -p["score"]))
        return rest[0], ["frei"]
    return None, None


def src_in(p, beats, per, hit_off_beats, speed_before=1.0, speed=1.0):
    """In-Punkt so wählen, dass der beste Moment auf dem Hit liegt. Vorrang: gesichteter Moment
    aus den Tags, dann Highlights der Clip-Analyse (nach Score), der erste, der ganz in den Clip passt."""
    need = beats * per * speed
    if p.get("sauber"):                                 # sauberes Fenster aus tags.json: In-Punkt darin halten
        lo, hi = p["sauber"]
        s, peak = src_in(dict(p, sauber=None), beats, per, hit_off_beats, speed_before, speed)
        return (round(min(max(s if s is not None else lo, lo), max(lo, hi - need)), 3), peak)
    peaks = ([p["moment"]] if p["moment"] is not None else []) + \
            [h["peak"] for h in sorted(p["highlights"], key=lambda h: -h.get("score", 0)) if h.get("peak") is not None]
    if not peaks:
        return (round(max(0.0, p["dur"] / 2 - need / 2), 3) if p["dur"] else None), None
    for peak in peaks:
        s = peak - hit_off_beats * per * speed_before
        if s >= 0 and (not p["dur"] or s + need <= p["dur"] - 0.05):
            return round(s, 3), round(peak, 3)
    peak = peaks[0]
    s = peak - hit_off_beats * per * speed_before
    if p["dur"]:
        s = min(s, p["dur"] - need - 0.05)
    return round(max(0.0, s), 3), round(peak, 3)


def build(song, pool, fenster=1, start_takt=None, takte=None, auftakt=None):
    per = song["beat_period"]
    bars = [b["t"] for b in song["bars"]]
    n_takte = takte or takte_regel2(per)
    if start_takt is not None:
        b0, auf = start_takt, auftakt or 0
    else:
        w = song["windows"][fenster - 1]           # Start des Fensters; Länge nach Regel 2 statt w["takte"]
        auf = w["auftakt_beats"]
        b0 = int(round((w["start"] + auf * per - bars[0]) / (4 * per)))
    t0 = bars[b0] - auf * per
    beats_total = n_takte * 4 + auf
    amap = {a["hb"]: a for a in song["accent_map"]}
    k808 = song["onsets"]["kick808"]
    slots, kapitel, bo = [], [], 0                  # (Kapitel, Tag-Kapitel, Beat ab der Eins, Beats, Slot)
    if n_takte <= 8:
        for k in range(1, 5):
            kapitel.append(dict(n=k, name=KAPITEL[k - 1], phrasen=0.5, start_s=round((bo + auf) * per, 3) if bo else 0.0))
            for bt, slot in HALB[k][:n_takte // 2]:
                slots.append((k, [k], bo, bt, slot))
                bo += bt
    else:
        for k, kaps, n_ph in verteilung(n_takte // 4):
            name = " & ".join(KAPITEL[i - 1].split(" & ")[0] for i in kaps) if len(kaps) > 1 else KAPITEL[k - 1]
            kapitel.append(dict(n=k, name=name, phrasen=n_ph, start_s=round((bo + auf) * per, 3) if bo else 0.0))
            art = f"k{k}"
            folge = [art] + [art + "+"] * (n_ph - 1)
            if k == 4:
                folge.reverse()                     # letztes Kapitel: die Phrase mit dem Finale zuletzt
            for f in folge:
                for bt, slot in PHRASE[f]:
                    slots.append((k, kaps, bo, bt, slot))
                    bo += bt
    if auf:                                         # Auftakt gehört zum ersten Shot (Opener)
        k, kaps, _, bt, slot = slots[0]
        slots[0] = (k, kaps, -auf, bt + auf, slot)
    used, shots = set(), []
    n_flash = n_shake = 0
    for n, (k, kaps, bo, bt, slot) in enumerate(slots, 1):
        speed = TEMPO.get(slot, 1.0)
        mode = "speed" if speed != 1.0 else "normal"
        need = bt * per * speed + 0.2
        p, group = pick(pool, used, kaps, slot, need)
        beat_abs = b0 * 4 + bo                      # Beat-Nummer ab Takt 0
        hb = beat_abs * 2
        acc = amap.get(hb, {}).get("kind", "none")
        fx, fxp = [], {}
        if speed != 1.0:
            fx.append(f"Zeitlupe {speed:g}×".replace(".", ","))
        if acc in PUNCH:
            fx.append({"808": "Punch-in", "808_nachschlag": "Punch-in 0,12", "clap": "Mini-Punch"}[acc])
            fxp["punch"] = [[0, PUNCH[acc]]]
        else:
            fx.append("harter Schnitt")
        # 808 im Shot (nicht auf dem Schnitt) -> Punch im selben Shot (höchstens 2)
        inner = [o for o in k808 if beat_abs + 0.25 <= o["beat"] < beat_abs + bt - 0.01]
        inner.sort(key=lambda o: -o["strength"])
        for o in inner[:2]:
            fxp.setdefault("punch", []).append([round(o["beat"] - beat_abs, 2), 0.05 if speed < 1 else PUNCH["808_nachschlag"]])
            fx.append(f"Punch@{o['beat'] - beat_abs:g}")
        if slot == "finale" and STIL["finale"]["push"]:
            fx.append("Push-in +12 %")
            fxp["push"] = [1.0, 1.12]
        if slot == "epic":
            fx.append("Push-in +8 %")
            fxp["push"] = [1.0, 1.08]
        if slot in ("opener", "branding") and "push" not in fxp:
            fx.append("Push-in +6 %")
            fxp["push"] = [1.0, 1.06]
        if p and "nah" in p["tags"] and slot in ("nah", "durchgehend", "action") and "push" not in fxp:
            fx.append("Push-in +10 %")
            fxp["push"] = [1.0, 1.10]
        if acc in ("808", "808_nachschlag") and n_flash < BUDGET["flashes"] and k == 4 and slot in ("payoff", "finale"):
            fx.append("Flash")
            fxp["flash"] = [[0, 0.55]]
            n_flash += 1
        if p and "schlag" in p["tags"] and acc in ("808", "808_nachschlag") and n_shake < BUDGET["shakes"]:
            fx.append("Shake")
            fxp["shake"] = [[0, 20]]
            n_shake += 1
        shot = dict(n=n, kapitel=k, kapitel_name=KAPITEL[k - 1], slot=slot, beat=bo + auf, beats=bt,
                    t=round(bo * per + auf * per, 4), song_t=round(t0 + (bo + auf) * per, 4),
                    takt=f"T{beat_abs // 4}.{beat_abs % 4 + 1}", akzent=acc, mode=mode, fx=fx, fxp=fxp)
        if mode == "speed":
            shot["speed"] = speed
        if p:
            used.add(p["clip"])
            s, peak = src_in(p, bt, per, 1.0, speed_before=speed, speed=speed)
            shot.update(clip=p["clip"], src=s, peak=peak, desc=p["desc"], passt=" + ".join(group),
                        analysiert=p["analysiert"])
            if slot == "highlight" and "explosiv" in p["tags"]:
                shot["hinweis"] = "Ramp möglich (Regel 8: ramp_hold, Hit auf einem 808 in HITS, Landung im Bild)"
        else:
            shot.update(clip=None, src=None, peak=None, desc=f"FEHLT: Clip für '{slot}'", passt="", analysiert=False)
        shots.append(shot)
    assert sum(s["beats"] for s in shots) == beats_total, "Slots decken das Reel nicht ab"
    # Checkliste Stil-Leitfaden Abschnitt 9
    checks = {
        "szenen": len(shots), "flashes": n_flash, "shakes": n_shake,
        "szenen_unter_4_beats": [s["n"] for s in shots if s["beats"] < 4],
        "clips_doppelt": len(used) != len([s for s in shots if s["clip"]]),
        "fehlende_clips": [s["n"] for s in shots if not s["clip"]],
        "finale_beats": shots[-1]["beats"],
        "ohne_analyse": [s["clip"] for s in shots if s["clip"] and not s["analysiert"]],
    }
    return dict(song=song["file"], per=per, bpm=song["bpm"], song_start=round(t0, 4), takte=n_takte, auftakt=auf,
                beats=beats_total, dauer=round(beats_total * per, 4), start_takt=b0, kapitel=kapitel,
                checks=checks, shots=shots)


def write_md(E, out):
    L = [f"# Shotlisten-Vorschlag ({E['takte']} Takte{' + Auftakt' if E['auftakt'] else ''}, {E['dauer']:.2f} s)", "",
         f"Song ab {E['song_start']:.3f} s (T{E['start_takt']}.1{' minus 2 Beats Auftakt' if E['auftakt'] else ''}), "
         f"{E['bpm']:.2f} BPM, {E['beats']} Beats. Entwurf: Szenenlänge nach der ganzen Aktion anpassen, "
         f"In-Punkte an dichten Frames prüfen.", "",
         "Kapitel: " + ", ".join(f"{k['name']} ab {k['start_s']:.1f} s ({k['phrasen']:g} Phrase{'n' if k['phrasen'] != 1 else ''})"
                                 for k in E["kapitel"]), "",
         "| # | Zeit | Takt | Beats | Kapitel | Clip | In (s) | Modus | Akzent | Effekte | Inhalt |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in E["shots"]:
        L.append(f"| {s['n']} | {s['t']:.2f} | {s['takt']} | {s['beats']} | {s['kapitel']} | {s['clip'] or '–'} | "
                 f"{'offen' if s['src'] is None else s['src']} | {s['mode']} | {s['akzent']} | {', '.join(s['fx'])} | "
                 f"{s['desc']}{' (' + s['hinweis'] + ')' if s.get('hinweis') else ''} |")
    c = E["checks"]
    L += ["", "## Checkliste", "",
          f"- Länge {E['dauer']:.1f} s (Regel 2: ab {STIL['laenge_s'][0]} s, bis ~{STIL['laenge_s'][1]} s); "
          f"{c['szenen']} Szenen (kein Richtwert)",
          f"- Szenen unter 4 Beats (nur durchgehende Bewegung oder kurze Reaktion): "
          f"{c['szenen_unter_4_beats'] or 'keine'}; Finale {c['finale_beats']} Beats",
          f"- Flashes {c['flashes']} (max. {BUDGET['flashes']}), Shakes {c['shakes']} (max. {BUDGET['shakes']}, nur auf "
          f"Schlägen), Ramps keine (Regel 8: nur von Hand)",
          f"- Fehlende Clips: {c['fehlende_clips'] or 'keine'}; ohne Clip-Analyse (In-Punkt geschätzt): "
          f"{', '.join(c['ohne_analyse']) or 'keine'}"]
    Path(out).write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(description="Shotlisten-Vorschlag nach Stil-Leitfaden")
    ap.add_argument("--song", required=True, help="song.json von song_analyse.py")
    ap.add_argument("--clips", help="clips.json von clip_analyse.py")
    ap.add_argument("--tags", help="Tags je Clip (z. B. <reel>/schnitt/tags.json, Format: tags_beispiel.json)")
    ap.add_argument("--fenster", type=int, default=1, help="Reel-Fenster aus song.json (1 = Empfehlung)")
    ap.add_argument("--start-takt", type=int, help="Takt laut song.md, auf dessen Eins das Reel beginnt")
    ap.add_argument("--takte", type=int, help="Vielfaches von 4; ohne: Länge nach Regel 2 (stil.json laenge_s)")
    ap.add_argument("--auftakt", type=int, default=0, help="Beats Auftakt vor der Eins (0 oder 2)")
    ap.add_argument("--meiden", help="Clips einer anderen Variante meiden: edl.json/shotliste.json oder Kürzel "
                                     "mit Komma (z. B. für Variante B: --meiden reel/schnitt/A/edl.json)")
    ap.add_argument("-o", "--out", default=".")
    a = ap.parse_args()
    if a.takte is not None and (a.takte % 4 or a.takte < 8):
        ap.error("--takte: Vielfaches von 4, mindestens 8 (Regel 2: volle 4-Takt-Phrasen)")
    for m in (a.meiden or "").split(","):
        if m.strip().endswith(".json"):
            for sh_ in json.loads(Path(m.strip()).read_text())["shots"]:
                MEIDEN.update([st["clip"] for st in sh_.get("strips", [])] if sh_["clip"] == "split" else [sh_["clip"]])
        elif m.strip():
            MEIDEN.add(stem(m.strip()))
    song = json.loads(Path(a.song).read_text())
    pool = load_pool(a.clips, a.tags)
    E = build(song, pool, a.fenster, a.start_takt, a.takte, a.auftakt if a.start_takt is not None else None)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "shotliste.json").write_text(json.dumps(E, ensure_ascii=False, indent=1))
    write_md(E, out / "shotliste.md")
    for s in E["shots"]:
        print(f"#{s['n']:<2} {s['t']:6.2f}s {s['takt']:>6} {s['beats']}B K{s['kapitel']} {str(s['clip']):>5} "
              f"in {s['src']}  {s['mode']:9s} {', '.join(s['fx'])}")
    print("Checkliste:", json.dumps(E["checks"], ensure_ascii=False))
    print(f"-> {out / 'shotliste.json'}, shotliste.md")


if __name__ == "__main__":
    main()
