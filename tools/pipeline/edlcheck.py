#!/usr/bin/env python3
"""Stil-Leitfaden-Prüfung einer Schnittliste: nur Warnungen, bricht nie ab.

    python3 edlcheck.py <reel>/schnitt/A/edl.json [...]   # fertige Schnittlisten prüfen

schnitt/X/edl.py ruft bericht() nach dem Schreiben auf. So gilt eine Regeländerung an einer Stelle für alle Reels.
Regeln: Stil-Leitfaden.md (Einstieg im Video, Szenen mit Jump Cuts, O-Ton, Überblendung nur an ruhigen Stellen);
Schwellen und Stichwörter stehen in REGELN, die stilabhängigen kommen aus stil.json (laenge_s, budget, stichwoerter,
einstieg_im_video, epic_opener, erlaubt). Szenen: EDL-Feld "szene" (edl.py: s() neue Szene, j() Jump Cut); ältere
Schnittlisten ohne das Feld gelten als ein Shot je Szene.
Nicht hier prüfbar (braucht die Rohclips): ob eine Szene ihre ganze Aktion zeigt, ein Jump Cut zwischen ganzen
Wiederholungen springt und alles im sauberen Fenster bleibt: aktionen.py edl misst es (Hinweise, Vorschläge), ob ein
Versuch gelungen ist, sieht nur das Auge (tools/ansicht.py szenen); wie der O-Ton klingt (tools/analyse/oton.py, der Nutzer hört).
"""
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stil import STIL  # noqa: E402

_B = STIL["budget"]
_EXTRA = {"split": "Split-Screen", "freeze": "Freeze-Frame", "whip": "Whip-Zoom", "echo": "Echo-Trail",
          "glitch": "Glitch", "sfx": ("Whoosh", "SFX")}
REGELN = dict(
    min_s=STIL["laenge_s"][0] - 0.1,  # s, Regel 2: so viele volle Phrasen, dass es mindestens so lang ist, höchstens eine mehr
    min_beats=_B["min_beats"],   # Regel 6: kein Teil kürzer
    aktion_beats=_B.get("aktion_beats", 4),   # Regel 4: kürzer nur für durchgehende Bewegung und kurze Reaktionen
    durchgehend=STIL["stichwoerter"]["durchgehend"],
    explosiv=STIL["stichwoerter"]["explosiv"],                 # Regel 8: Ramp nur hier (oder Shot mit explosiv=True)
    boxen=STIL["stichwoerter"]["schlag"],                      # Regel 9: Shake nur auf Schlägen und Treffern
    max_ramps=_B["ramps"], max_flash=_B["flashes"], max_shake=_B["shakes"],   # Regeln 8, 9
    finale_beats=4, finale_tempo=0.6 if STIL["finale"]["zeitlupe"] else 1.0,  # Regel 12: mindestens 4 Beats (Standard 8)
    epic_tempo=0.5, epic_shots=4,                              # Regel 11: Epic-Shot in 0,5× unter den ersten 4 Shots
    ende_808=0.150,                                            # s, kein 808-Einsatz so kurz vor dem Ende
    nur_auf_wunsch=tuple(n for k, v in _EXTRA.items() if k not in STIL["erlaubt"]
                         for n in (v if isinstance(v, tuple) else (v,))),
    szene_max=16,                                              # Beats, Regel 4: Szene meist 8, Highlight bis 16
    sprung_min=1.0,                                            # s, Regel 4: Zeitsprung eines Jump Cuts im selben Clip
    salve_max=4,                                               # Regel 6: höchstens 4 Jump Cuts à 1 Beat, einmal pro Reel
    punch_jump=0.06,                                           # Regel 5: auf einem Jump Cut höchstens Mini-Punch
    max_blenden=_B["uebergaenge"],                             # Regel 5: Überblendungen nur an ruhigen Stellen
    max_momente=2,                                             # Regel 1: O-Ton-Momente (O-Ton vorn nach dem Einstieg)
    max_dialoge=3,                                             # Dialog-Szenen (dialog.py), zählen nicht als O-Ton-Momente
    einstieg_max=16, ausklang_max=8,                           # Beats, Regeln 11, 12
)
TEMPO = dict(fast=1.5, slow=0.5)   # feste Tempi der Modi wie in timing.py; speed: Feld "speed"; sonst 1,0


def tempo(x):
    return x.get("speed", 1.0) if x["mode"] == "speed" else TEMPO.get(x["mode"], 1.0)


def songdatei(ordner):
    """song.json neben der Schnittliste oder in schnitt/ (wie grid.json)."""
    return next((d / "song.json" for d in (ordner, ordner.parent) if (d / "song.json").exists()), None) if ordner else None


def pruefen(E, takte=None, auftakt=None, ordner=None, versatz=0.0):
    """E wie edl.json (shots, per, hook, beats, hits; dazu auftakt, takte, einstieg,
    einstieg_song, ausklang) -> Liste der Warnungen. Ohne takte/auftakt (ältere edl.json) aus beats: Auftakt = beats % 4.
    ordner: Ordner der Schnittliste (für song.json)."""
    R, S, per, beats, hits = REGELN, E["shots"], E["per"], E["beats"], set(E.get("hits") or [])
    ein, aus = E.get("einstieg", 0), E.get("ausklang", 0)
    auftakt = E.get("auftakt", (beats - aus) % 4) if auftakt is None else auftakt
    takte = E.get("takte", (beats - aus - auftakt) // 4) if takte is None else takte
    such = lambda k, x: re.search(R[k], x.get("desc", ""), re.I)
    nr = lambda xs: ", ".join(f"{x['n']} ({x['clip']})" for x in xs)
    w, dur = [], (beats - aus) * per          # Songlänge; der Ausklang läuft danach nur mit O-Ton
    szene = lambda x: x.get("szene", -x["n"])
    im_einstieg = lambda x: x["beat"] < ein
    im_ausklang = lambda x: aus and x["beat"] >= beats - aus

    # Länge, Phrasen, Kapitel (Regeln 2, 3); Phrasen zählen ab der Eins nach dem Auftakt, der Auftakt gehört zu Kapitel 1
    phr = 16 * per                                   # eine 4-Takt-Phrase in s
    n_min = -(-R["min_s"] // phr)                     # kleinste Phrasenzahl mit der Mindestlänge
    if not n_min <= takte / 4 <= n_min + 1:
        w.append(f"Länge {dur:.1f} s ({takte} Takte): Regel 2 will {n_min * 4:.0f} Takte ({n_min * phr:.1f} s), "
                 f"höchstens {n_min * 4 + 4:.0f} ({(n_min + 1) * phr:.1f} s); kürzer nur auf Wunsch des Nutzers")
    if takte % 4:
        w.append(f"{takte} Takte: keine vollen 4-Takt-Phrasen (Regel 2)")
    phrase = 8 if takte <= 8 else 16
    starts = {x["sec"]: x["beat"] for x in reversed(S)}
    for k, (sec, st) in enumerate(sorted(starts.items(), key=lambda kv: kv[1])):
        if k and (st - auftakt) % phrase and not (aus and st >= beats - aus):
            w.append(f"Kapitel {sec} startet auf Beat {st}, nicht auf einer Phrase ({phrase} Beats ab der Eins)")

    # Teile und Tempo (Regeln 4, 6, 7); ein Teil = Shot, eine Szene = Shots mit gleichem "szene"
    neu = [x for x in S if not x.get("cont")]
    kurz = [x for x in neu if x["beats"] < R["min_beats"]]
    salve = [x for x in kurz if x.get("jump") and such("durchgehend", x)]
    ok_salve = salve and len({szene(x) for x in salve}) == 1 and len(salve) <= R["salve_max"] and \
        max(x["n"] for x in salve) - min(x["n"] for x in salve) == len(salve) - 1
    kurz = [x for x in kurz if not (ok_salve and x in salve)]
    if kurz:
        w.append(f"Teile unter {R['min_beats']} Beats: Shot {nr(kurz)} (nur als eine Jump-Cut-Salve durchgehender "
                 f"Bewegung, höchstens {R['salve_max']}, Regel 6)")
    kurz = [x for x in neu if R["min_beats"] <= x["beats"] < R["aktion_beats"] and not such("durchgehend", x)]
    if kurz:
        w.append(f"Shot {nr(kurz)} unter {R['aktion_beats']} Beats: ganze Aktion? mit ansicht.py szenen prüfen")
    for x in S:
        if tempo(x) > 1:
            w.append(f"Shot {x['n']} ({x['clip']}): Zeitraffer {tempo(x):g}×, nie schneller als 1,0× (Regel 7)")

    # Szenen und Jump Cuts (Regeln 4, 5)
    lang = {}
    for x in neu:
        lang[szene(x)] = lang.get(szene(x), 0) + x["beats"]
    zu_lang = [k for k, v in lang.items() if v > R["szene_max"]]
    if zu_lang:
        w.append(f"{len(zu_lang)} Szene(n) über {R['szene_max']} Beats (Regel 4: meist 8, Highlight bis 16)")
    clips = {}
    for x in neu:
        for c in ([st["clip"] for st in x["strips"]] if x["clip"] == "split" else [x["clip"]]):
            clips.setdefault(c, set()).add(szene(x))
    mehr = sorted(c for c, z in clips.items() if len(z) > 1)
    if mehr:
        w.append(f"Clip in mehreren Szenen: {mehr} (mehrfach nur per Jump Cut in derselben Szene)")
    for i, x in enumerate(S):
        if not x.get("jump") or not i:
            continue
        v = S[i - 1]
        if v["clip"] == x["clip"] and v["clip"] != "split":
            ende = v["src"] + v["beats"] * per * tempo(v) if v["mode"] in ("normal", "speed", "slow", "fast") else None
            if ende is not None and x["src"] < ende - 0.05:
                w.append(f"Jump Cut Shot {x['n']} ({x['clip']}): beginnt bei {x['src']:.2f} s, vor dem Ende von Shot "
                         f"{v['n']} ({ende:.2f} s), zeigt Material doppelt")
            elif ende is not None and x["src"] - ende < R["sprung_min"]:
                w.append(f"Jump Cut Shot {x['n']} ({x['clip']}): nur {x['src'] - ende:.2f} s Zeitsprung, wirkt wie ein "
                         f"Ruckler (mindestens {R['sprung_min']:g} s, ganze Wiederholung überspringen, Regel 4)")
        big = [p for p in x["fxp"].get("punch", []) if p[0] == 0 and p[1] > R["punch_jump"]]
        if big:
            w.append(f"Jump Cut Shot {x['n']}: Punch {big[0][1]:g} auf dem Sprung; der Jump Cut ist der Akzent "
                     f"(höchstens Mini-Punch {R['punch_jump']:g}, Regel 5)")

    # Überblendungen nur an ruhigen Stellen (Regel 5)
    bl = [x for x in S if x.get("ueber") == "blende"]
    if len(bl) > R["max_blenden"]:
        w.append(f"{len(bl)} Überblendungen (max. {R['max_blenden']}, nur an ruhigen Stellen, Regel 5)")
    auf808 = [x for x in bl if x["beat"] in hits]
    if auf808:
        w.append(f"Überblendung auf einem 808: Shot {nr(auf808)} (dort harter Schnitt, Regel 5)")

    # Einstieg im Video, O-Ton, Ausklang (Regeln 1, 11, 12)
    if ein:
        if ein > R["einstieg_max"]:
            w.append(f"Einstieg {ein} Beats: länger als eine Phrase ({R['einstieg_max']} Beats, Regel 11)")
        drop = next((x for x in S if x["beat"] == ein), None)
        if drop is None:
            w.append(f"Drop auf Beat {ein}: dort beginnt kein Shot, der Song öffnet sich mitten in einer Szene (Regel 11)")
        elif drop.get("ueber") == "blende":
            w.append(f"Drop auf Beat {ein}: Überblendung statt hartem Schnitt (Regel 11)")
        song = E.get("einstieg_song", "gedämpft")
        if song not in ("gedämpft", "aus"):
            w.append(f"EINSTIEG_SONG {song!r}: erlaubt sind \"gedämpft\" und \"aus\" (Regel 11)")
        if not any(x.get("oton") for x in S if im_einstieg(x)):
            w.append("Einstieg im Video ohne O-Ton: der Song klingt dann nur gedämpft (Regel 11, oton=\"vorn\")"
                     if song != "aus" else "Einstieg mit Song aus, aber ohne O-Ton: stumm bis zum Drop (Regel 11)")
        elif song == "aus" and any(not x.get("oton") for x in S if im_einstieg(x)):
            w.append(f"Einstieg mit Song aus: Shot {nr([x for x in S if im_einstieg(x) and not x.get('oton')])} "
                     "ohne O-Ton, dort ist es still (Regel 11)")
    elif STIL["einstieg_im_video"] and not any(x.get("oton") for x in S):
        w.append("kein Einstieg im Video und kein O-Ton (Regeln 1 und 11; abschalten: stil.json einstieg_im_video)")
    momente, offen = [], False
    for x in S:
        vorn = x.get("oton") == "vorn" and not x.get("dialog") and not im_einstieg(x) and not im_ausklang(x)
        if vorn and not offen:
            momente.append([x])
        elif vorn:
            momente[-1].append(x)
        offen = vorn
    if len(momente) > R["max_momente"]:
        w.append(f"{len(momente)} O-Ton-Momente (max. {R['max_momente']}, Regel 1)")
    for m in momente:
        a, b = m[0]["beat"], m[-1]["beat"] + m[-1]["beats"]
        drin = sorted(h for h in hits if a < h < b)
        if drin:
            w.append(f"O-Ton-Moment Shot {m[0]['n']}–{m[-1]['n']} über 808 auf Beat {drin} (besser im Break, Regel 1)")
    dl = [x for x in S if x.get("dialog")]
    if dl:
        if len(dl) > R["max_dialoge"]:
            w.append(f"{len(dl)} Dialog-Szenen (max. {R['max_dialoge']}: Reel bleibt ein Action-Reel, dialog.py)")
        falsch = [x for x in dl if x["mode"] != "normal" or tempo(x) != 1 or x["clip"] == "split"]
        if falsch:
            w.append(f"Dialog nicht in Echtzeit (mode normal): Shot {nr(falsch)} (Stimme und Lippen laufen sonst auseinander)")
        if any(x["beat"] < ein or im_ausklang(x) for x in dl):
            w.append("Dialog im Einstieg oder im Ausklang: dort gilt O-Ton (oton), Dialog gehört in den Hauptteil")
        if E.get("transkript"):
            try:
                import dialog
                for x in dl:
                    ws = dialog.woerter_des_clips(dialog.transkript_laden(E["transkript"], x["clip"]))
                    a, b = x["src"], x["src"] + x["beats"] * per
                    cut = [q["w"] for q in ws if q["s"] < a - 0.02 < q["e"] - 0.05 or q["s"] < b - 0.03 < q["e"] - 0.1]
                    if cut:
                        w.append(f"Dialog Shot {x['n']} ({x['clip']}): Wort am Anfang oder Ende angeschnitten ({', '.join(cut[:3])}), "
                                 f"Beats oder src prüfen (dialog.py)")
            except (OSError, ValueError, KeyError) as e:
                w.append(f"Dialog: Transkript nicht prüfbar ({e})")
        else:
            w.append("Dialog-Szene ohne TRANSKRIPT in der Schnittliste: Untertitel und Wortprüfung fehlen")
    zl = [x for x in S if x.get("oton") and tempo(x) != 1 and not im_einstieg(x)]
    if zl:
        w.append(f"O-Ton auf Zeitlupe (läuft in Echtzeit, nur Atmo ohne sichtbares Sprechen): Shot {nr(zl)}")
    kein = [x for x in S if x.get("oton") and (x["clip"] == "split" or x["mode"] == "freeze")]
    if kein:
        w.append(f"O-Ton auf Split oder Freeze: Shot {nr(kein)} (hat keinen passenden Ton)")
    if aus:
        if aus > R["ausklang_max"]:
            w.append(f"Ausklang {aus} Beats: länger als {R['ausklang_max']} (Regel 12: 1 Takt)")
        if not any(x["beat"] == beats - aus for x in S):
            w.append(f"Ausklang: auf Beat {beats - aus} (Song-Ende) beginnt kein Shot (Regel 12)")
        stumm = [x for x in S if im_ausklang(x) and not x.get("oton")]
        if stumm:
            w.append(f"Ausklang ohne O-Ton: Shot {nr(stumm)} (dort ist der Song aus, Regel 12)")

    # Speed-Ramps nur als Ausnahme (Regel 8); Hit = Beat 2 im Shot
    ramps = [x for x in S if x["mode"] in ("ramp", "ramp_hold")]
    for x in ramps:
        if x["mode"] == "ramp":
            w.append(f"Ramp Shot {x['n']} ({x['clip']}): 'ramp' läuft im Zeitraffer an und aus, nur 'ramp_hold' (Regel 8)")
        if not (x.get("explosiv") or such("explosiv", x)):
            w.append(f"Ramp Shot {x['n']} ({x['clip']}, {x['desc']}): kein explosiver Sprung wie Salto oder Box-Jump "
                     f"(sonst explosiv=True setzen, Regel 8)")
        if x["beat"] + 2 not in hits:
            w.append(f"Ramp Shot {x['n']}: Hit auf Beat {x['beat'] + 2}, kein 808 in HITS (Regel 8)")
    if len(ramps) > R["max_ramps"]:
        w.append(f"{len(ramps)} Ramps (max. {R['max_ramps']}, nur explosive Sprünge, Regel 8)")

    # Flash auf Schnitt und 808, Shake nur auf Schlägen (Regel 9), Extras nur auf Wunsch (Regel 10)
    fl = [(x, f[0]) for x in S for f in x["fxp"].get("flash", [])]
    for x, o in fl:
        fehler = (["nicht auf dem Schnitt"] if o else []) + (["kein 808 in HITS"] if x["beat"] + o not in hits else [])
        if fehler:
            w.append(f"Flash Shot {x['n']} auf Beat {x['beat'] + o:g}: {', '.join(fehler)} (Regel 9)")
    if len(fl) > R["max_flash"]:
        w.append(f"{len(fl)} Flashes (max. {R['max_flash']})")
    sh = [x for x in S if x["fxp"].get("shake") or "Shake" in x["fx"]]
    if len(sh) > R["max_shake"]:
        w.append(f"{len(sh)} Shakes (max. {R['max_shake']}, nur auf Schlägen)")
    kein = [x for x in sh if not such("boxen", x)]
    if kein:
        w.append(f"Shake Shot {nr(kein)}: kein Schlag oder Treffer in der Beschreibung (Regel 9)")
    extra = [t for t in R["nur_auf_wunsch"] if any(t in x["fx"] for x in S)]
    if extra:
        w.append(f"nur auf Wunsch des Nutzers: {extra}")

    # Opener und Finale (Regeln 11, 12)
    if STIL["einstieg_im_video"] and S and tempo(S[0]) >= 1 and not (ein and S[0].get("oton")):
        w.append("Opener: Shot 1 weder Marke/Logo in leichter Zeitlupe (~0,75×) noch Einstieg im Video mit O-Ton (Regel 11)")
    if STIL["epic_opener"] and S and not any(tempo(x) <= R["epic_tempo"] for x in S[:R["epic_shots"]]):
        w.append(f"Opener: kein Epic-Shot in 0,5× unter den ersten {R['epic_shots']} Shots (Regel 11)")
    fin = next((x for x in reversed(S) if not im_ausklang(x)), None)
    if fin and (fin["beats"] < R["finale_beats"] or tempo(fin) > R["finale_tempo"]
                or (STIL["finale"]["push"] and "push" not in fin["fxp"])):
        w.append("Finale: mindestens 4 Beats (Standard 8), Zeitlupe 0,5× und Push-in laut stil.json (Regel 12)")

    # kein 808-Einsatz kurz vor dem Song-Ende (Regel 2); Zeitachse wie audio_spec.json: src + Dauer im Decode
    song = songdatei(ordner)
    if song:
        ende = round(E["hook"] - versatz, 4) + dur
        for o in json.load(open(song)).get("onsets", {}).get("kick808", []):
            if 0 <= ende - o["t"] < R["ende_808"]:
                w.append(f"808-Einsatz {(ende - o['t']) * 1000:.0f} ms vor dem Song-Ende ({o['t']:.3f} s im Song): "
                         f"eine Phrase weniger oder anderer Start (Regel 2)")
    return w


def bericht(E, takte=None, auftakt=None, ordner=None, versatz=0.0):
    """Ausgabe für edl.py: WARNUNG-Zeilen oder „keine Verstöße“, dazu was kein Werkzeug prüft."""
    w = pruefen(E, takte, auftakt, ordner, versatz)
    offen = "ganze Aktion, Jump Cuts zwischen ganzen Wiederholungen, sauberes Fenster -> aktionen.py edl, Versuch " \
        "gelungen -> ansicht.py szenen; O-Ton-Klang -> oton.py" + ("" if songdatei(ordner) else "; 808 am Ende: kein song.json")
    return ("\n".join("WARNUNG " + x for x in w) or "Stil-Leitfaden: keine Verstöße gefunden") + f"\n(nicht prüfbar: {offen})"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for f in map(Path, sys.argv[1:]):
        E, a = json.load(open(f)), f.parent / "audio_spec.json"
        v = E["hook"] - json.load(open(a))["music"][0]["src"] if a.exists() else 0.0   # DECODER_VERSATZ zurückrechnen
        print(f"== {f}\n" + bericht(E, ordner=f.resolve().parent, versatz=v))
