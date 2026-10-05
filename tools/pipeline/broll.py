#!/usr/bin/env python3
"""B-Roll über die Stimme vorschlagen (seit 30.09.2026): zu den Stellen, an denen jemand spricht, passende Clips und Zeiten.

    cd /tmp && python3 broll.py <schnitt.json> --tags <tags.json>[,<tags2.json>] [--max 2] [--dauer 2.0]
                               [--meiden 6365,6370] [--genau] [--einsetzen] [--json vorschlaege.json]

Liest den Interview-Schnitt (`schnitt.json` von interview.py), das Transkript und die Tags der Rohclips (Format wie
`tools/analyse/tags_beispiel.json`: kapitel, tags, desc, moment, sauber, ausschuss). Für jeden Sprechteil ab 3 s
(keine Fragen, keine Teile, die schon ein `bild` haben) schlägt es bis zu `--max` Überlagerungen vor: B-Roll, die zum
Gesagten passt (Stichwörter im Text gegen Beschreibung und Tags der Clips), sonst ein sauberer Action-Clip. Eine
Überlagerung (`bei` = Quellzeit im Sprecherclip) beginnt auf einem Wortanfang, frühestens 0,8 s nach dem Teilanfang, und endet mindestens 0,6 s vor dem
Teilende (die Stimme läuft darunter weiter, die Untertitel bleiben). Jeder Clip kommt höchstens einmal vor, Clips aus
`--meiden` und die Sprecherclips nie.
Das Fenster im B-Roll-Clip: um den besten Moment (`moment`) und im sauberen Fenster (`sauber`) der Tags. Mit `--genau`
misst `aktionen.py` den Clip und legt Anfang und Ende auf Ruhepunkte, die ganze Aktion im Bild (lädt den Clip bei Bedarf
aus dem Drive und räumt ihn wieder weg; ohne `--genau` kein Download).
`--einsetzen` schreibt die Vorschläge als `bild` in die schnitt.json (nur in Teile ohne `bild`, Sicherung
schnitt.json.vor_broll) und trägt die Clips unter `clips` ein (lädt sie dafür bei Bedarf). Die Zuordnung Text zu Clip ist
Schlagwort-Abgleich, kein Verstehen: die Vorschläge sind Entwürfe, in der Vorschau ansehen.
Test ohne Drive: test_broll.py.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True      # kein __pycache__ im geteilten Projektordner
PIPE = Path(__file__).resolve().parent
for _p in (PIPE, PIPE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

REGELN = dict(
    mindest_teil=3.0,           # s: kürzere Sprechteile bekommen kein B-Roll
    ab_min=0.8,                 # s nach dem Teilanfang
    ende_min=0.6,               # s Sprecher vor dem Teilende
    dauer=2.0,                  # s Standardlänge
    dauer_min=1.0,
    abstand=1.2,                # s zwischen zwei Überlagerungen im selben Teil
    je_teil=2,
    zu_zweit=6.0,               # s: erst ab dieser Teillänge ein zweites B-Roll
)
STOP = set("""und oder aber dass dass eine einen einem einer eines ein der die das den dem des ist sind war waren wird
werden wurde wurden habe haben hat hatte hatten bin bist mal schon noch auch nur sehr ganz immer wieder dann wenn weil
also halt ja nee nein doch dort hier dies diese dieser dieses sich mich mir dich dir uns euch ihr wir ich du er sie es
mit für von aus bei nach vor über unter auf als wie was wer wo hab gut dabei jetzt heute gerade eigentlich einfach
richtig total echt mega voll schon mehr viel viele mal nächste nächsten letzte letzten""".split())
# Tag oder Stichwort der Clips -> Wortstämme (erste 5 Buchstaben) im Gesprochenen
SYNONYME = {
    "gruppe": ["crew", "grupp", "leute", "commu", "zusam", "team", "gemei", "freun", "mensc", "atmos", "spaß", "spass"],
    "crew": ["crew", "grupp", "leute", "commu", "zusam", "team", "gemei", "freun", "mensc"],
    "branding": ["flagg", "logo", "marke", "shirt", "banne"],
    "epic": ["stolz", "stark", "power", "gefüh", "emoti"],
    "action": ["train", "übung", "uebun", "anstr", "worko", "schwi", "kämpf", "kaemp", "muske", "zirke", "inten", "fitne",
               "sport", "belas", "kraft", "ausdau", "gepum", "gebal", "brutal", "fertig"],
    "explosiv": ["sprun", "sprin", "explo", "power", "kraft", "schne"],
    "durchgehend": ["seile", "seil", "ropes", "lauf", "renne", "tanz", "sprin"],
    "power": ["power", "kraft", "stark", "schwe", "gewic"],
    "schlag": ["boxen", "box", "schlag", "kampf", "handsc", "sparr", "kämpf", "treff"],
    "payoff": ["ziel", "gesch", "endsp", "wettk", "event", "erfol", "ergeb", "auftr", "medai"],
    "emotion": ["freu", "jubel", "lache", "glück", "glueck", "stolz", "fertig", "kaput", "erschö"],
    "nah": [], "langsam": [], "showpiece": ["stark", "kraft", "akrob", "trick"], "opener": [], "finale": [],
}


def stamm(w):
    return re.sub(r"[^\wäöüß]", "", w.lower())[:5]


def inhaltswoerter(ws):
    return [(w, stamm(w["w"])) for w in ws if len(re.sub(r"[^\wäöüß]", "", w["w"])) >= 4
            and re.sub(r"[^\wäöüß]", "", w["w"]).lower() not in STOP]


def clip_stichwoerter(tag):
    kw = set()
    for w in re.findall(r"[\wäöüß]+", (tag.get("desc") or "").lower()):
        if len(w) >= 4 and w not in STOP:
            kw.add(w[:5])
    for t in tag.get("tags", []):
        kw.update(SYNONYME.get(t, []))
    return kw


def tags_laden(pfade):
    tags = {}
    for p in pfade:
        for k, v in json.loads(Path(p).read_text()).items():
            if k != "_info" and isinstance(v, dict):
                tags[str(k)] = v
    return tags


def teilwoerter(t, ws):
    """Wörter eines Teils (von/bis als Sekunden oder Phrase) und die Zeiten."""
    def finde(phrase, ab):
        toks = [stamm(x) for x in phrase.split() if stamm(x)]
        wn = [stamm(w["w"]) for w in ws]
        for i in range(len(ws) - len(toks) + 1):
            if ws[i]["s"] >= ab - 0.01 and wn[i:i + len(toks)] == toks:
                return i, i + len(toks) - 1
        raise ValueError(f"Phrase nicht gefunden: {phrase!r}")
    if isinstance(t["von"], str):
        i, _ = finde(t["von"], t.get("ab", 0.0))
        von = ws[i]["s"] - 0.1
    else:
        von = float(t["von"])
    if isinstance(t["bis"], str):
        _, j = finde(t["bis"], max(von - 0.3, t.get("ab", 0.0)))
        bis = ws[j]["e"] + 0.15
    else:
        bis = float(t["bis"])
    if t.get("anfang") is not None:
        von = float(t["anfang"])
    if t.get("ende") is not None:
        bis = float(t["ende"])
    sel = [w for w in ws if von - 0.05 <= (w["s"] + w["e"]) / 2 <= bis + 0.05]
    return von, bis, sel


def fenster_im_clip(clip, tag, dauer, genau, quellen=None):
    """(start, ende) im B-Roll-Clip: um den besten Moment, im sauberen Fenster; genau = mit aktionen.py auf Ruhepunkte."""
    moment = float(tag.get("moment", 0.0))
    lo, hi = (float(tag["sauber"][0]), float(tag["sauber"][1])) if tag.get("sauber") else (0.0, 1e9)
    s = min(max(lo, moment - dauer / 2), max(lo, hi - dauer)) if hi - lo >= dauer else lo
    e = s + dauer
    if genau:
        import aktionen
        try:
            info = aktionen.serie(clip, max(lo, moment - 4.0), moment + 4.0, quellen)
            M = aktionen.merkmale(info)
            v = aktionen.vorschlaege(M, dauer, s0=s, moment=moment, n=1)
            if v:
                s, e = v[0][1], v[0][2]
        except (ValueError, RuntimeError) as ex:
            print(f"  (Clip {clip}: Messung nicht möglich, Fenster nach Tags: {ex})", file=sys.stderr)
    return round(max(0.0, s), 2), round(e, 2)


def vorschlagen(cfg, trs, tags, R=None, dauer=None, meiden=(), genau=False, quellen=None, je_teil=None):
    """Vorschläge je Teil: [{teil, bild: [{clip, src, ab, dauer, grund}]}]. ab zählt ab dem Teilanfang (Quellzeit)."""
    R = dict(REGELN, **({"dauer": dauer} if dauer else {}), **({"je_teil": je_teil} if je_teil else {}))
    benutzt = {str(c) for c in meiden} | {str(c) for c in cfg["clips"]}
    benutzt |= {str(c).replace("IMG_", "") for c in list(benutzt)}
    frei = {k: v for k, v in tags.items() if not v.get("ausschuss") and k not in benutzt and "IMG_" + k not in benutzt}
    schlagw = {k: clip_stichwoerter(v) for k, v in frei.items()}
    out = []
    for n, t in enumerate(cfg["teile"], 1):
        if t.get("stil") == "frage" or t.get("bild"):
            continue
        ws = [w for sg in trs[t["clip"]]["segmente"] for w in sg["woerter"]]
        try:
            von, bis, sel = teilwoerter(t, ws)
        except ValueError as e:
            out.append(dict(teil=n, bild=[], hinweis=str(e)))
            continue
        if bis - von < R["mindest_teil"] or not sel:
            continue
        maxn = R["je_teil"] if bis - von >= R["zu_zweit"] else 1
        inh = inhaltswoerter(sel)
        plan, letzter_ende = [], von
        kand = []
        for x, st in inh:   # Start knapp vor dem Stichwort, damit das Bild beim Wort da ist
            ab = max(R["ab_min"], x["s"] - 0.15 - von)
            if von + ab > x["s"] + 0.05 or von + ab + R["dauer_min"] > bis - R["ende_min"]:
                continue
            fenster = [(y, sy) for y, sy in inh if von + ab - 0.05 <= y["s"] <= von + ab + R["dauer"]]
            for k, sw in schlagw.items():
                if st in sw:
                    treffer = sorted({y["w"].strip(".,!?") for y, sy in fenster if sy in sw})
                    kand.append((len(treffer) + 0.01 * len(fenster), ab, k, treffer))
        kand.sort(key=lambda c: (-c[0], c[1]))
        gewaehlt = []
        for score, ab, k, treffer in kand:
            if k in benutzt or len(gewaehlt) >= maxn:
                continue
            if any(abs(ab - g[1]) < R["dauer"] + R["abstand"] for g in gewaehlt):
                continue
            gewaehlt.append((score, ab, k, treffer))
            benutzt.add(k)
        # ohne Stichwort-Treffer: ein sauberer Action-Clip in der Mitte des Teils
        if not gewaehlt:
            mitte = [w for w in sel if R["ab_min"] <= w["s"] - von <= (bis - von) - R["dauer"] - R["ende_min"]]
            akt = sorted((k for k, v in frei.items() if k not in benutzt and "action" in v.get("tags", [])
                          and "moment" in v), key=lambda k: (-float(frei[k].get("score", 0) or 0), k))
            if mitte and akt:
                w = mitte[len(mitte) // 2]
                gewaehlt.append((0.0, w["s"] - von, akt[0], []))
                benutzt.add(akt[0])
        bilder = []
        for score, ab, k, treffer in sorted(gewaehlt, key=lambda g: g[1]):
            d = min(R["dauer"], bis - R["ende_min"] - (von + ab))
            if d < R["dauer_min"]:
                continue
            s0, e0 = fenster_im_clip(k, frei[k], d, genau, quellen)
            bilder.append(dict(clip=k, src=s0, ab=round(ab, 2), bei=round(von + ab, 3), dauer=round(e0 - s0, 2),
                               grund=(f"Stichwort „{', '.join(treffer)}“ passt zu {frei[k].get('desc', k)}" if treffer
                                      else f"kein Stichwort, sauberer Action-Clip: {frei[k].get('desc', k)}")))
        if bilder:
            out.append(dict(teil=n, von=round(von, 2), bis=round(bis, 2), bild=bilder))
    return out


def main():
    ap = argparse.ArgumentParser(description="B-Roll über die Stimme vorschlagen")
    ap.add_argument("schnitt")
    ap.add_argument("--tags", required=True)
    ap.add_argument("--max", type=int)
    ap.add_argument("--dauer", type=float)
    ap.add_argument("--meiden", default="")
    ap.add_argument("--genau", action="store_true")
    ap.add_argument("--einsetzen", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    pfad = Path(a.schnitt)
    cfg = json.loads(pfad.read_text())
    trs = {c: (json.loads((Path(cfg["transkript"]) / f"{c}.json").read_text())
               if (Path(cfg["transkript"]) / f"{c}.json").exists() else {"segmente": []}) for c in cfg["clips"]}
    tags = tags_laden(a.tags.split(","))
    quellen = None
    if a.genau or a.einsetzen:
        import aktionen
        quellen = aktionen.Quellen(behalten=a.einsetzen)
    try:
        v = vorschlagen(cfg, trs, tags, dauer=a.dauer, meiden=[x for x in a.meiden.split(",") if x], genau=a.genau,
                        quellen=quellen, je_teil=a.max)
        for x in v:
            print(f"#{x['teil']}" + (f"  {x['von']:.2f}–{x['bis']:.2f} s" if "von" in x else "") + (f"  {x['hinweis']}" if "hinweis" in x else ""))
            for b in x["bild"]:
                print(f"    Bild {b['clip']} ab {b['ab']:.2f} s im Teil, {b['dauer']:.2f} s, Clip {b['src']:.2f}–{b['src'] + b['dauer']:.2f} s: {b['grund']}")
        if not v:
            print("Keine Vorschläge (keine Sprechteile ab 3 s ohne Bild, oder keine freien Clips in den Tags).")
        if a.json:
            Path(a.json).write_text(json.dumps(v, ensure_ascii=False, indent=1))
        if a.einsetzen and v:
            pfad.with_suffix(".json.vor_broll").write_text(pfad.read_text())
            for x in v:
                t = cfg["teile"][x["teil"] - 1]
                t["bild"] = [dict(clip=b["clip"], src=b["src"], bei=b["bei"], dauer=b["dauer"]) for b in x["bild"]]
                for b in x["bild"]:
                    if b["clip"] not in cfg["clips"]:
                        cfg["clips"][b["clip"]] = str(quellen.pfad(b["clip"]))
            pfad.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
            print(f"-> {pfad} ({sum(len(x['bild']) for x in v)} Bilder eingetragen, Sicherung {pfad.name}.vor_broll)")
    finally:
        if quellen:
            quellen.aufraeumen()


if __name__ == "__main__":
    main()
