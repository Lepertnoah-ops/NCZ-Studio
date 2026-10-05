#!/usr/bin/env python3
"""Szenenausschnitte wählen und prüfen (seit 30.09.2026): pro Clip die saubere Stelle, die Ruhepunkte und die ganzen
Aktionen finden, bessere Ausschnitte vorschlagen und eine Schnittliste dagegen prüfen. Nur Hinweise, bricht nie ab.

    python3 aktionen.py clip <clip> [--laenge 1.7] [--von S --bis S] [--bild] [--json]   # Befund und Vorschläge
    python3 aktionen.py edl <edl.json> [<edl.json> ...] [--ohne-personen] [--bild] [--nur 5,8]
    python3 aktionen.py selbsttest                                                        # ohne Drive, ~20 s

<clip> = Kürzel wie in der EDL ('6365', 'IMG_6365') oder eine Videodatei. Gemessen wird wie in clip_analyse.py mit
10 Bildern/s (Bewegung des Motivs ohne Kamerabewegung, Kamerageschwindigkeit, Schärfe, Schnitte im Clip). Nur die
Bereiche, die eine EDL braucht (plus 5 s Rand), werden gemessen; Ergebnis je Clip in $REEL_WORK/aktionen/<stamm>.json
(klein, bleibt liegen). Fehlt die Clip-Datei in $REEL_WORK/dl/, lädt das Werkzeug sie über manifest.tsv und löscht sie
danach wieder (--behalten: liegen lassen).

Was es sagt (Schwellen in REGELN):
- Unsauber: Schwenk, unscharf, Wackeln oder ein Schnitt im Clip innerhalb des Ausschnitts (die Stelle, die man sonst beim
  Sichten von Hand als „sauberes Fenster“ in tags.json festhält).
- Aktion: zusammenhängende Phase, in der sich das Motiv bewegt, dazwischen Ruhe. Der Ausschnitt soll davor und danach in
  Ruhe beginnen und enden (Anlauf und Landung sichtbar). Schneidet ein Anfang oder Ende mitten in eine Aktion, steht
  dort „Anlauf fehlt“ bzw. „Landung fehlt“ mit dem besseren In-Punkt und, wenn die Aktion länger als die Szene ist, den
  Beats, mit denen sie ganz passt. Dauerbewegung (Clip ohne Ruhe, z. B. Seilspringen) und Szenen mit den Stichwörtern
  der Regel 4 („durchgehend“ in edlcheck.py) bleiben ohne Anfang-Ende-Prüfung.
- Jump Cut im selben Clip: springt er von Ruhe zu Ruhe (zwischen ganzen Wiederholungen)?
- Personen (personen.py, nur wenn das Modell da ist): nur im Epic-Shot und im Finale, vier Stichproben, ob jemand den
  linken oder rechten Bildrand berührt. Ob jemand im Bild ist oder wechselt, sagt das Werkzeug nie: Erkennungen
  flackern (kopfstehende, kleine, verdeckte Personen), das entscheiden die sauberen Stellen und das Auge.

Was es nicht kann: einen gescheiterten Versuch (z. B. Muscle-up, der wieder runterkommt) erkennen. Die Bewegung sagt
nur, dass etwas passiert, nicht ob es gelingt. Das bleibt Sichtprüfung (ansicht.py szenen / --bild), ein Fehlversuch
kommt als „ausschuss“ in die Tags. Die Schwellen sind an Trainingsmaterial geeicht (Methode und Grenzen: referenz/studio/
fehlerquellen.md, Abschnitt 9).
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True      # kein __pycache__ im geteilten Projektordner
PIPE = Path(__file__).resolve().parent
TOOLS = PIPE.parent
for _p in (PIPE, TOOLS, TOOLS / "analyse"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import reelcfg  # noqa: E402
import timing  # noqa: E402

WORK = reelcfg.WORK
CACHE = WORK / "aktionen"
VERSION = 1

REGELN = dict(
    hz=10,                      # Messwerte je s (clip_analyse, der Schnell-Scan mit ~1 je s ist zu grob)
    glaetten=0.3,               # s, Glättung der Bewegung
    ruhe_anteil=0.35,           # Ruhe-Grenze = p10 + 35 % des Weges bis p90 der Bewegung im gemessenen Bereich
    start_anteil=0.15,          # Aktion beginnt erst, wenn die Bewegung die Ruhe-Grenze um diesen Anteil überschreitet
    min_hub=30.0,               # px/s (bei 1080 px Breite): p90 − p10 darunter = Clip ohne erkennbare Aktion
    min_aktion=0.3,             # s, kürzere Ausschläge sind Rauschen
    luecke=0.2,                 # s, Aktionen mit kürzerer Pause davor/dahinter gelten als eine
    dauer_ruhe=0.15,            # weniger Ruhe im Clip = Dauerbewegung
    kante=0.25,                 # s am Anfang und Ende des Ausschnitts, deren Bewegung zählt
    kern=0.5,                   # Höhepunkt einer Aktion: wo die Bewegung über der Hälfte zwischen Ruhe-Grenze und Spitze liegt
    tief=0.10,                  # s: so weit muss ein Schnitt im Höhepunkt stecken, um die Aktion anzuschneiden
    unscharf=0.45,              # Schärfe unter 45 % der Umgebung (80. Perzentil über ±1 s): kurzer Einbruch durch
                                # Bewegungsunschärfe oder Fokus. Ein dauerhaft niedriger Wert ist Bildinhalt (Gesicht
                                # nah, wenig Textur), kein Fehler; das meldet clip_analyse.py als Clip-Flag.
    schwenk=800.0,              # px/s Kamerageschwindigkeit (geglättet), darüber Schwenk (~75 % der Bildbreite je s)
    wackeln=250.0,              # px/s Wackeln (hochfrequenter Anteil der Kamerabewegung), darüber verwackelt
    aktion_max=2.5,             # s: längere Phasen sind Dauertätigkeit (Sparring, Laufen), kein Anlauf und keine Landung
    schnitt_rand=0.15,          # s um einen Schnitt im Clip
    unsauber_max=0.10,          # Anteil des Ausschnitts in unsauberen Stellen, darüber Hinweis
    unsauber_rand=0.30,         # s am Anfang oder Ende, die nicht unsauber sein dürfen
    suche=3.0,                  # s: so weit sucht der Vorschlag vom bisherigen In-Punkt
    zusatz_beats=4,             # so viele Beats mehr probiert der Vorschlag (und 2 weniger)
    sprung_min=1.0,             # s, wie edlcheck.py (Regel 4)
    person_min=0.40,            # Sicherheit, ab der eine Erkennung zählt
    person_hoehe=0.10,          # Anteil der Bildhöhe, darunter zählt eine Person nicht (Hintergrund)
    rand=0.012,                 # Anteil der Bildbreite: Person berührt den Rand
    rand_s=5.0,                 # s Rand, den eine EDL-Messung vor und hinter den Shots dazunimmt
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stil import STIL  # noqa: E402

DURCHGEHEND = STIL["stichwoerter"]["durchgehend"]   # wie edlcheck.py

_LOCK = threading.Lock()


def log(*a):
    with _LOCK:
        print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- Clip-Dateien und Messreihen

def _stamm_ok(stamm, clip):
    return stamm == clip or stamm == "IMG_" + clip or (len(clip) >= 4 and stamm.endswith(clip))


class Quellen:
    """Clip-Dateien in WORK/dl: vorhandene nehmen, fehlende aus manifest.tsv laden und am Ende wieder löschen."""

    def __init__(self, behalten=False):
        self.behalten, self.geladen = behalten, []

    def pfad(self, clip):
        if Path(str(clip)).is_file():
            return Path(clip)
        dl = WORK / "dl"
        treffer = sorted(p for p in dl.glob("*") if p.is_file() and _stamm_ok(p.stem, str(clip))) if dl.exists() else []
        if len(treffer) == 1:
            return treffer[0]
        if len(treffer) > 1:
            raise RuntimeError(f"Clip {clip!r}: {len(treffer)} Dateien passen in {dl}")
        try:
            man = reelcfg.manifest()
            fid, name, size = man[reelcfg.stem_of(str(clip), set(man))]
        except (OSError, KeyError) as e:
            raise RuntimeError(f"Clip {clip!r} liegt nicht in {dl} und steht nicht in manifest.tsv ({e}); "
                               f"mit drive.py holen <id> <ziel> laden") from e
        pfad = dl / name
        dl.mkdir(parents=True, exist_ok=True)
        if not reelcfg.download(fid, pfad, size, "aktionen"):
            raise RuntimeError(f"Download von {name} fehlgeschlagen (Grund: {WORK}/aktionen.log)")
        with _LOCK:
            self.geladen.append(pfad)
        return pfad

    def aufraeumen(self):
        if not self.behalten:
            for p in self.geladen:
                p.unlink(missing_ok=True)


def _cache_datei(pfad):
    return CACHE / f"{Path(pfad).stem}.json"


def messen(pfad, von=None, bis=None, threads=2):
    """Messreihen eines Clips (clip_analyse.analyse_clip mit 10 Bildern/s), von/bis in s (None = ganzer Clip)."""
    import clip_analyse as ca
    hz = REGELN["hz"]
    dur = ca.probe(str(pfad))["dur"]
    v, b = max(0.0, von if von is not None else 0.0), min(dur, bis if bis is not None else dur)
    teil = v > 0.05 or b < dur - 0.05
    info = ca.analyse_clip(str(pfad), sample_fps=hz, thumbs=False, threads=threads,
                           von=v if teil else None, bis=b if teil else None)
    info = {k: x for k, x in info.items() if not k.startswith("_")}
    info["aktionen_v"] = VERSION
    info["bereich"] = [round(v, 3), round(b, 3)]
    return info


def cache_datei(clip):
    """Cache-Datei zu einem Clip (Kürzel oder Dateipfad) oder None, wenn es noch keine gibt."""
    if Path(str(clip)).is_file():
        return _cache_datei(clip)
    if not CACHE.exists():
        return None
    treffer = [c for c in CACHE.glob("*.json") if _stamm_ok(c.stem, str(clip))]
    return treffer[0] if len(treffer) == 1 else None


def serie(clip, von, bis, quellen, threads=2):
    """Messreihen für [von, bis] aus dem Cache oder frisch gemessen. Reicht der Cache nicht, wird der vereinigte
    Bereich neu gemessen und ersetzt ihn."""
    cache, alt = cache_datei(clip), None
    if cache and cache.exists():
        try:
            alt = json.load(open(cache))
        except (OSError, ValueError):
            alt = None
        if alt and alt.get("modus") == "schnell":
            alt = None                                   # Schnell-Scan ist für Aktionen zu grob
    if alt:
        b0, b1 = alt.get("bereich") or [0.0, alt["dur"]]  # ohne Bereich: ganze Clip-Analyse aus clip_analyse.py
        if b0 <= max(0.0, von) + 0.05 and b1 >= min(alt["dur"], bis) - 0.05:
            return alt
        von, bis = min(von, b0), max(bis, b1)
    pfad = quellen.pfad(clip)
    info = messen(pfad, von, bis, threads)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = _cache_datei(pfad)
    json.dump(info, open(str(cache) + ".tmp", "w"), separators=(",", ":"))
    os.replace(str(cache) + ".tmp", cache)
    return info


# ---------------------------------------------------------------- Merkmale eines Clips

def _glatt(x, n):
    if n <= 1 or len(x) < 2:
        return x.copy()
    n = min(n, len(x))
    pad = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(pad, np.ones(n) / n, mode="valid")


def spannen(maske, t, dt, luecke=0.0, mindest=0.0):
    """Boolesche Reihe -> [(von, bis)] in s; Messwert i gilt für [t_i, t_i + dt]. Lücken < luecke werden zugeklebt."""
    out, i, n = [], 0, len(maske)
    while i < n:
        if maske[i]:
            j = i
            while j + 1 < n and maske[j + 1]:
                j += 1
            out.append([float(t[i]), float(t[j] + dt)])
            i = j + 1
        else:
            i += 1
    merged = []
    for s in out:
        if merged and s[0] - merged[-1][1] < luecke - 1e-9:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [(a, b) for a, b in merged if b - a >= mindest - 1e-9]


def merkmale(info, R=REGELN):
    """Messreihen -> Merkmale: Bewegung, Ruhe-Grenze, Aktionen, unsaubere Stellen. Wirft ValueError bei Schnell-Scan."""
    s = info["series"]
    t = np.array(s["t"], float)
    if len(t) < 5:
        raise ValueError("zu wenige Messwerte (Clip oder Bereich unter 0,5 s)")
    dt = float(np.median(np.diff(t)))
    if dt > 0.25:
        raise ValueError("Schnell-Scan (~1 Messwert je s) ist zu grob, bitte mit 10 Bildern/s messen")
    hz = 1.0 / dt
    g = max(1, int(round(R["glaetten"] * hz)))
    roh = 0.5 * np.array(s["motion"], float) + 0.5 * np.array(s["motion_top"], float) / 4.0   # wie clip_analyse
    a = _glatt(roh, g)
    cam = _glatt(np.array(s["camera"], float), g)
    shake = _glatt(np.array(s["shake"], float), g)
    sharp = np.array(s["sharp"], float)
    p10, p90 = float(np.percentile(a, 10)), float(np.percentile(a, 90))
    hub = p90 - p10
    rg = p10 + R["ruhe_anteil"] * hub
    rs = rg + R["start_anteil"] * hub
    # Aktionen: Schmitt-Trigger über der Ruhe-Grenze
    aktiv, an = np.zeros(len(a), bool), False
    for i, x in enumerate(a):
        an = (x > rg) if an else (x > rs)
        aktiv[i] = an
    akt = []
    for v, b in spannen(aktiv, t, dt, R["luecke"], R["min_aktion"]):
        m = (t >= v - 1e-6) & (t < b - 1e-6)
        k = int(np.argmax(np.where(m, a, -1)))
        grenze = rg + R["kern"] * (a[k] - rg)
        ueber = np.where(m & (a >= grenze))[0]            # erster bis letzter Wert über der Kern-Grenze (auch mehrere Höcker)
        akt.append(dict(von=round(v, 2), bis=round(b, 2), spitze=round(float(t[k] + dt / 2), 2),
                        hoehe=round(float(a[k]), 1), kern=[round(float(t[ueber[0]]), 2), round(float(t[ueber[-1]] + dt), 2)]))
    ruhe = spannen(a <= rg, t, dt, R["luecke"], 0.0)
    ruhe_anteil = float((a <= rg).mean())
    # unsaubere Stellen
    from scipy.ndimage import percentile_filter
    umgebung = percentile_filter(sharp, 80, size=max(3, int(round(2.0 * hz)) | 1), mode="nearest")
    gruende = {
        "unscharf": sharp < R["unscharf"] * umgebung,
        "Schwenk": cam > R["schwenk"],
        "Wackeln": shake > R["wackeln"],
        "Schnitt im Clip": np.zeros(len(t), bool),
    }
    gruende["unscharf"] = _dilate(gruende["unscharf"], 1)
    for c in info.get("scenes") or []:
        gruende["Schnitt im Clip"] |= (t + dt > c - R["schnitt_rand"]) & (t < c + R["schnitt_rand"])
    bad = np.zeros(len(t), bool)
    for m in gruende.values():
        bad |= m
    unsauber = []
    rel = sharp / np.maximum(umgebung, 1e-6)
    for v, b in spannen(bad, t, dt, 0.15, 0.0):
        m = (t + dt > v + 1e-6) & (t < b - 1e-6)
        grund = [k for k, mk in gruende.items() if (mk & m).any()]
        wert = {"Schwenk": f"{cam[m].max():.0f} px/s", "Wackeln": f"{shake[m].max():.0f} px/s",
                "unscharf": f"Schärfe {100 * rel[m].min():.0f} %"}
        unsauber.append(dict(von=round(v, 2), bis=round(b, 2), grund=grund,
                             text="+".join(f"{g} ({wert[g]})" if g in wert else g for g in grund)))
    return dict(t=t, dt=dt, hz=hz, a=a, cam=cam, shake=shake, sharp_rel=sharp / np.maximum(umgebung, 1e-6), bad=bad,
                p10=p10, p90=p90, rg=rg, hub=hub, aktionen=akt, ruhe=[(round(v, 2), round(b, 2)) for v, b in ruhe],
                ruhe_anteil=ruhe_anteil, unsauber=unsauber,
                statisch=hub < R["min_hub"], dauer=ruhe_anteil < R["dauer_ruhe"] and hub >= R["min_hub"],
                bereich=(float(t[0]), float(t[-1] + dt)), dur=info["dur"])


def _dilate(m, n):
    out = m.copy()
    for k in range(1, n + 1):
        out[k:] |= m[:-k]
        out[:-k] |= m[k:]
    return out


# ---------------------------------------------------------------- Ausschnitte bewerten und vorschlagen

def fenster_maske(M, s, e):
    return (M["t"] + M["dt"] > s + 1e-6) & (M["t"] < e - 1e-6)


def angeschnitten(M, s, e, R=REGELN):
    """Aktionen, in deren Höhepunkt (Kern) der Anfang oder das Ende des Ausschnitts [s, e] mehr als R['tief'] hineinreicht:
    [(aktion, 'anfang'|'ende')]. Ein Schnitt im Anlauf oder Ausklang einer Aktion zählt nicht, ebenso keine
    Dauertätigkeit (länger als R['aktion_max']) und keine Aktion, die bis an den Rand des gemessenen Bereichs reicht."""
    out = []
    lo, hi = M["bereich"]
    for k in M["aktionen"]:
        if k["bis"] - k["von"] > R["aktion_max"] or k["von"] <= lo + 0.05 or k["bis"] >= hi - 0.05:
            continue            # Dauertätigkeit oder bis zum Rand des Bereichs: Anfang und Ende unbekannt
        kv, kb = k["kern"]
        if kv + R["tief"] < s < kb - R["tief"]:
            out.append((k, "anfang"))
        if kv + R["tief"] < e < kb - R["tief"]:
            out.append((k, "ende"))
    return out


def unsauber_anteil(M, s, e):
    m = fenster_maske(M, s, e)
    return float(M["bad"][m].mean()) if m.any() else 0.0


def unsauber_rand(M, s, e, R=REGELN):
    """Gründe, wenn die ersten oder letzten R['unsauber_rand'] s des Ausschnitts unsauber sind."""
    out = []
    for lo, hi, wo in ((s, s + R["unsauber_rand"], "Anfang"), (e - R["unsauber_rand"], e, "Ende")):
        m = fenster_maske(M, lo, hi)
        if m.any() and M["bad"][m].mean() >= 0.5:
            out.append(wo)
    return out


def bewerten(M, s, e, s0=None, moment=None, R=REGELN):
    """Kosten eines Ausschnitts (kleiner = besser) und die Einzelwerte."""
    frei = M["dauer"] or M["statisch"]                    # ohne erkennbare Ruhe gibt es keinen Anlauf und keine Landung
    ang = [] if frei else angeschnitten(M, s, e, R)
    ganz = [] if frei else [k for k in M["aktionen"] if k["kern"][0] >= s - 0.05 and k["kern"][1] <= e + 0.05]
    u, ur = unsauber_anteil(M, s, e), unsauber_rand(M, s, e, R)
    kosten = 4.0 * len(ang) + 10.0 * max(0.0, u - R["unsauber_max"]) + 2.0 * len(ur) - 0.8 * min(2, len(ganz))
    if not M["statisch"]:                                 # bei sonst gleichem Befund lieber der bewegtere Ausschnitt
        m = fenster_maske(M, s, e)
        kosten -= 0.5 * min(1.2, float(M["a"][m].mean()) / max(M["p90"], 1e-6)) if m.any() else 0.0
    if moment is not None and not (s + 0.05 <= moment <= e - 0.05):
        kosten += 6.0
    if s0 is not None:
        kosten += 0.05 * abs(s - s0)            # bei gleichem Befund lieber nah am bisherigen In-Punkt bleiben
    return kosten, dict(angeschnitten=ang, ganz=len(ganz), unsauber=round(u, 2), unsauber_rand=ur)


def vorschlaege(M, laenge, s0=None, moment=None, n=3, R=REGELN):
    """Beste Ausschnitte der Länge `laenge` s: [(kosten, start, ende, einzelwerte)], nach Kosten sortiert, mindestens
    0,4 s auseinander. Ohne s0 wird der ganze gemessene Bereich durchsucht, sonst ±R['suche'] s um s0."""
    t, dt = M["t"], M["dt"]
    lo, hi = M["bereich"]
    if laenge > hi - lo + 1e-6:
        return []
    if s0 is None:
        starts = np.arange(lo, hi - laenge + 1e-6, dt)
    else:
        starts = np.arange(max(lo, s0 - R["suche"]), min(hi - laenge, s0 + R["suche"]) + 1e-6, dt)
    cand = []
    for s in starts:
        k, d = bewerten(M, float(s), float(s) + laenge, s0, moment, R)
        cand.append((k, round(float(s), 2), round(float(s) + laenge, 2), d))
    cand.sort(key=lambda c: (c[0], c[1]))
    out = []
    for c in cand:
        if all(abs(c[1] - o[1]) >= 0.4 for o in out):
            out.append(c)
        if len(out) >= n:
            break
    return out


def beats_vorschlag(M, beats, per, tempo, s0, moment=None, R=REGELN):
    """Kleinste Beat-Zahl (beats − 2 … beats + zusatz), mit der ein Ausschnitt ohne Befund möglich ist:
    (beats, start, ende) oder None. Dient der Aktion, die länger als die Szene ist."""
    for k in range(max(1, int(beats) - 2), int(beats) + R["zusatz_beats"] + 1):
        if k == beats:
            continue
        L = k * per * tempo
        v = vorschlaege(M, L, s0, moment, 1, R)
        if v and v[0][0] < 0.5:
            return k, v[0][1], v[0][2]
    return None


# ---------------------------------------------------------------- Personen (nur Hinweise)

def personen_stichproben(pfad, zeiten, R=REGELN):
    """Je Zeit: Liste (mitte_x, hoehe, links_anschnitt, rechts_anschnitt) der Personen, größte zuerst. None ohne Modell."""
    import personen
    if not personen.verfuegbar():
        return None
    out = []
    for t in zeiten:
        try:
            bild = personen._bild(str(pfad), t)
        except SystemExit:
            out.append([])
            continue
        H, W = bild.shape[:2]
        pl = [(x, y, w, h) for x, y, w, h, c in personen.erkennen(bild) if c >= R["person_min"] and
              h >= R["person_hoehe"] * H]
        pl.sort(key=lambda b: -b[2] * b[3])
        out.append([((x + w / 2) / W, h / H, x <= R["rand"] * W, x + w >= (1 - R["rand"]) * W) for x, y, w, h in pl])
    return out


def personen_hinweise(st, zeiten, R=REGELN):
    """Hinweise aus den Stichproben st (personen_stichproben), nur für Epic-Shot und Finale: berührt eine Person den
    linken oder rechten Bildrand (Stil-Leitfaden: niemanden am Rand anschneiden)? Die Personenzahl wechselt auch durch
    Erkennungsfehler (kopfstehende oder kleine Personen), daher nur zur Information, nie als Hinweis."""
    w = []
    for seite, idx in (("links", 2), ("rechts", 3)):
        treffer = [z for z, p in zip(zeiten, st) if any(q[idx] for q in p)]
        if treffer:
            w.append(f"Person am Bildrand {seite} angeschnitten (Stichprobe bei {', '.join(f'{z:.2f}' for z in treffer)} s, "
                     f"{len(treffer)} von {len(st)})")
    return w


# ---------------------------------------------------------------- Schnittliste prüfen

def quell_fenster(x, per):
    """[(clip, start, ende)] der Quellzeit, die der Shot verbraucht (Split: ein Streifen je Clip, Echtzeit)."""
    if x["clip"] == "split":
        return [(st["clip"], st["src"], st["src"] + x["beats"] * per) for st in x["strips"]]
    return [(x["clip"], x["src"], x["src"] + float(timing.src_curve(x, per)[1][-1]))]


def _tempo(x):
    return x.get("speed", 1.0) if x["mode"] == "speed" else {"fast": 1.5, "slow": 0.5}.get(x["mode"], 1.0)


def _foto(clip):
    return reelcfg.is_photo(str(clip)) if hasattr(reelcfg, "is_photo") else False


def pruefe_edl(E, quellen, personen_an=True, nur=None, jobs=2, R=REGELN):
    """Befund je Shot: [dict(n, clip, src, ende, hinweise=[…], vorschlag=…)]. Misst fehlende Bereiche nach."""
    per, S = E["per"], E["shots"]
    bedarf = {}
    for i, x in enumerate(S):
        if nur and x["n"] not in nur and not (i and S[i - 1]["n"] in nur and S[i - 1].get("jump")) \
                and not (i + 1 < len(S) and S[i + 1]["n"] in nur and S[i + 1].get("jump")):
            continue                                         # nur die gewünschten Shots (und Nachbarn eines Jump Cuts) messen
        for c, a, b in quell_fenster(x, per):
            if _foto(c):
                continue
            v = bedarf.get(c)
            bedarf[c] = (min(v[0], a - R["rand_s"]), max(v[1], b + R["rand_s"])) if v else (a - R["rand_s"], b + R["rand_s"])
    infos, fehler = {}, {}

    def hol(c):
        try:
            return c, serie(c, bedarf[c][0], bedarf[c][1], quellen, threads=max(1, 4 // jobs)), None
        except Exception as e:      # noqa: BLE001 - ein Clip ohne Messung darf die Prüfung nicht stoppen
            return c, None, f"{type(e).__name__}: {e}"

    with cf.ThreadPoolExecutor(jobs) as ex:
        for c, info, err in ex.map(hol, sorted(bedarf)):
            if err:
                fehler[c] = err
            else:
                infos[c] = info
    feat = {}
    for c, info in infos.items():
        try:
            feat[c] = merkmale(info, R)
        except ValueError as e:
            fehler[c] = str(e)
    ende_ausklang = E.get("beats", 0) - E.get("ausklang", 0)
    epic = next((x["n"] for x in S[:4] if _tempo(x) <= 0.5 and not x.get("cont")), None)
    finale = next((x["n"] for x in reversed(S) if x["beat"] < ende_ausklang and not x.get("cont")), None)
    res = []
    for i, x in enumerate(S):
        if nur and x["n"] not in nur:
            continue
        b = dict(n=x["n"], clip=x["clip"], beats=x["beats"], desc=x.get("desc", ""), hinweise=[], vorschlag=None,
                 epic=x["n"] == epic, finale=x["n"] == finale)
        res.append(b)
        if x["clip"] == "split":
            b["hinweise"].append("Split-Screen: nicht geprüft")
            continue
        if _foto(x["clip"]):
            continue
        c, a, e = quell_fenster(x, per)[0]
        b["src"], b["ende"] = round(a, 2), round(e, 2)
        if c not in feat:
            b["hinweise"].append(f"nicht gemessen: {fehler.get(c, 'Clip fehlt')}")
            continue
        M = feat[c]
        b["M"] = M
        durch = M["dauer"] or M["statisch"] or re.search(DURCHGEHEND, x.get("desc", ""), re.I)
        folge = S[i + 1] if i + 1 < len(S) else None
        s_frei = bool(x.get("cont"))                              # Fortsetzung: Anfang ist kein Schnitt
        e_frei = bool(folge and folge.get("cont"))                # danach geht es nahtlos weiter
        # 1. unsauber
        u = unsauber_anteil(M, a, e)
        ur = unsauber_rand(M, a, e, R)
        if u > R["unsauber_max"] or ur:
            stellen = [f"{k['von']:.1f}–{k['bis']:.1f} s {k['text']}" for k in M["unsauber"]
                       if k["von"] < e and k["bis"] > a]
            b["hinweise"].append(f"unsauber ({100 * u:.0f} % des Ausschnitts): {'; '.join(stellen)}"
                                 + (f"; {' und '.join(ur)} betroffen" if ur else ""))
        # 2. Anlauf und Landung
        ang = [] if durch else [(k, w) for k, w in angeschnitten(M, a, e, R)
                                if not (w == "anfang" and s_frei) and not (w == "ende" and e_frei)]
        for k, w in ang:
            if w == "anfang":
                b["hinweise"].append(f"Anlauf fehlt: Anfang liegt im Höhepunkt {k['kern'][0]:.1f}–{k['kern'][1]:.1f} s "
                                     f"(Aktion {k['von']:.1f}–{k['bis']:.1f} s)")
            else:
                b["hinweise"].append(f"Landung fehlt: Ende liegt im Höhepunkt {k['kern'][0]:.1f}–{k['kern'][1]:.1f} s "
                                     f"(Aktion {k['von']:.1f}–{k['bis']:.1f} s)")
        # 3. Vorschlag, wenn es etwas zu verbessern gibt
        if b["hinweise"]:
            m = fenster_maske(M, a, e)
            moment = float(M["t"][m][np.argmax(M["a"][m])] + M["dt"] / 2) if m.any() else None
            L = e - a
            cand = vorschlaege(M, L, a, moment, 3, R)
            if cand and cand[0][0] < bewerten(M, a, e, a, moment, R)[0] - 0.5:
                k0, s1, e1, d = cand[0]
                b["vorschlag"] = dict(src=s1, ende=e1, beats=x["beats"], rest=round(k0, 1))
            if ang:
                bv = beats_vorschlag(M, x["beats"], per, _tempo(x), a, moment, R)
                if bv and (b["vorschlag"] is None or b["vorschlag"]["rest"] >= 0.5):
                    b["vorschlag"] = dict(src=bv[1], ende=bv[2], beats=bv[0], rest=0.0)
        # 4. Jump Cut im selben Clip
        if x.get("jump") and i > 0 and S[i - 1]["clip"] == x["clip"] and not durch:
            v = S[i - 1]
            ve = v["src"] + float(timing.src_curve(v, per)[1][-1])
            sprung = x["src"] - ve
            heiss = [w for k, w in angeschnitten(M, ve, ve + 0.01, R)] + [w for k, w in angeschnitten(M, x["src"], x["src"] + 0.01, R)]
            if heiss:
                b["hinweise"].append(f"Jump Cut von {ve:.1f} auf {x['src']:.1f} s ({sprung:+.1f} s) schneidet in eine Aktion, "
                                     f"nicht von Ruhe zu Ruhe")
        b["durch"] = bool(durch)
    # 5. Personen: vier Stichproben im Epic-Shot und im Finale (Bildrand)
    if personen_an and any(b["epic"] or b["finale"] for b in res):
        try:
            import personen
            ok = personen.verfuegbar()
        except ImportError:
            ok = False
        for b in res:
            if "src" not in b or not (b["epic"] or b["finale"]):
                continue
            if not ok:
                b["hinweise"].append("Personenprüfung übersprungen: Modell fehlt (tools/modelle/yolox)")
                continue
            a, e = b["src"], b["ende"]
            zs = [a + 0.15, a + (e - a) / 3, a + 2 * (e - a) / 3, e - 0.15]
            st = personen_stichproben(quellen.pfad(b["clip"]), zs, R)
            b["personen"] = [len(p) for p in st]
            b["hinweise"] += personen_hinweise(st, zs, R)
    for b in res:
        b["fehler"] = None
    return res, fehler


def text_edl(res, name=""):
    """Kurzer Bericht: Kopfzeile, dann nur die Shots mit Hinweis."""
    pruef = [b for b in res if b["hinweise"]]
    z = [f"{name}: {len(res)} Shots geprüft, {len(res) - len(pruef)} ohne Befund, {len(pruef)} zum Nachsehen"]
    for b in pruef:
        rolle = " (Epic-Shot)" if b["epic"] else " (Finale)" if b["finale"] else ""
        z.append(f"#{b['n']} {b['clip']} {b['src']:.1f}–{b['ende']:.1f} s, {b['beats']:g} Beats{rolle}"
                 + (f", Personen je Stichprobe {b['personen']}" if b.get("personen") else "") if "src" in b
                 else f"#{b['n']} {b['clip']}")
        z += [f"   {h}" for h in b["hinweise"]]
        v = b.get("vorschlag")
        if v:
            z.append(f"   besser: {v['src']:.2f}–{v['ende']:.2f} s"
                     + (f" mit {v['beats']:g} statt {b['beats']:g} Beats" if v["beats"] != b["beats"] else ""))
    return "\n".join(z)


# ---------------------------------------------------------------- Befund je Clip

def befund_clip(clip, M, laenge=None, R=REGELN):
    z = [f"{clip}: gemessen {M['bereich'][0]:.1f}–{M['bereich'][1]:.1f} s von {M['dur']:.1f} s"]
    if M["statisch"]:
        z.append(f"Bewegung: kaum Aktion im Bild (Hub {M['hub']:.0f} px/s, Schwelle {R['min_hub']:.0f}), "
                 f"jeder Ausschnitt ist ruhig")
    elif M["dauer"]:
        z.append(f"Bewegung: Dauerbewegung (nur {100 * M['ruhe_anteil']:.0f} % Ruhe): keine Anfang-Ende-Prüfung, "
                 f"jeder Ausschnitt schneidet mitten in die Bewegung")
    else:
        z.append(f"Bewegung: Ruhe unter {M['rg']:.0f} px/s, {100 * M['ruhe_anteil']:.0f} % des Bereichs ruhig, "
                 f"{len(M['aktionen'])} Aktion(en)")
        z.append("Aktionen: " + ", ".join(f"{k['von']:.1f}–{k['bis']:.1f} s (Spitze {k['spitze']:.1f})"
                                          for k in M["aktionen"][:14]) + (" …" if len(M["aktionen"]) > 14 else ""))
    if M["unsauber"]:
        z.append("Unsauber: " + "; ".join(f"{k['von']:.1f}–{k['bis']:.1f} s {k['text']}" for k in M["unsauber"][:12]))
    else:
        z.append("Unsauber: keine Stelle")
    if laenge:
        cand = vorschlaege(M, laenge, None, None, 5, R)
        z.append(f"Ausschnitte von {laenge:g} s ohne Befund:")
        ok = [c for c in cand if c[0] < 0.5]
        for k, s, e, d in (ok or cand)[:5]:
            z.append(f"   {s:.2f}–{e:.2f} s" + ("" if k < 0.5 else f"  (Kosten {k:.1f}: " + "; ".join(
                [f"{w} in Aktion {q['von']:.1f}–{q['bis']:.1f}" for q, w in d['angeschnitten']] +
                ([f"unsauber {100 * d['unsauber']:.0f} %"] if d["unsauber"] > R["unsauber_max"] else [])) + ")"))
        if not ok:
            z.append("   keiner ohne Befund: Aktion länger als der Ausschnitt oder alles unsauber")
    return "\n".join(z)


# ---------------------------------------------------------------- Bild

def bild_clip(pfad, M, von, bis, marken, out, n=8, titel=""):
    """Ein Bild: oben Bewegungskurve mit Aktionen, unsauberen Stellen und Ausschnitten, unten n Bilder aus [von, bis].
    marken: [(start, ende, farbe, beschriftung)]."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    import ansicht
    fig, ax = plt.subplots(figsize=(14, 2.6), dpi=100)
    t, a = M["t"], M["a"]
    m = (t >= von - 0.3) & (t <= bis + 0.3)
    ax.plot(t[m], a[m], color="#2b8a3e", lw=1.6, label="Bewegung")
    ax.axhline(M["rg"], color="#2b8a3e", lw=0.8, ls=":")
    ax.plot(t[m], M["cam"][m] / 4, color="#1c7ed6", lw=0.9, alpha=0.6, label="Kamera/4")
    for k in M["unsauber"]:
        ax.axvspan(k["von"], k["bis"], color="#e03131", alpha=0.18)
    for k in M["aktionen"]:
        ax.plot([k["von"], k["bis"]], [-0.04 * M["p90"]] * 2, color="#f08c00", lw=4, solid_capstyle="butt")
    for s, e, farbe, text in marken:
        ax.axvspan(s, e, ymin=0.0, ymax=1.0, facecolor="none", edgecolor=farbe, lw=2)
        ax.text(s, ax.get_ylim()[1] * 0.92, text, color=farbe, fontsize=9, va="top")
    ax.set_xlim(von - 0.3, bis + 0.3)
    ax.set_ylabel("px/s")
    ax.set_title(titel, fontsize=10, loc="left")
    ax.legend(loc="upper right", fontsize=7, ncol=2)
    fig.tight_layout()
    fig.canvas.draw()
    kurve = Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).convert("RGB")
    plt.close(fig)
    zs = list(np.linspace(von, max(von, bis - 0.05), n))
    kacheln = [ansicht.frame(pfad, z, breite=170) for z in zs]
    w = kurve.width
    kw = w // n
    kh = int(kw * kacheln[0].height / kacheln[0].width)
    streifen = Image.new("RGB", (w, kh), (14, 14, 14))
    from PIL import ImageDraw
    d = ImageDraw.Draw(streifen)
    for i, (k, z) in enumerate(zip(kacheln, zs)):
        streifen.paste(k.convert("RGB").resize((kw, kh)), (i * kw, 0))
        d.text((i * kw + 4, 3), f"{z:.2f}", fill=(205, 255, 60), font=ansicht.font(14))
    bild = Image.new("RGB", (w, kurve.height + kh), (255, 255, 255))
    bild.paste(kurve, (0, 0))
    bild.paste(streifen, (0, kurve.height))
    bild = ansicht.passend(bild)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    bild.save(out, quality=88) if str(out).endswith(".jpg") else bild.save(out)
    return out


# ---------------------------------------------------------------- Kommandozeile

def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def cmd_clip(a):
    clip = a[0]
    quellen = Quellen("--behalten" in sys.argv)
    try:
        von, bis = arg("--von"), arg("--bis")
        info = serie(clip, float(von) if von else 0.0, float(bis) if bis else 1e9, quellen, threads=4)
        M = merkmale(info)
        laenge = float(arg("--laenge")) if arg("--laenge") else None
        if "--json" in sys.argv:
            print(json.dumps({k: v for k, v in M.items() if k in ("aktionen", "unsauber", "ruhe", "rg", "hub", "dauer",
                                                                  "statisch", "bereich", "dur")}, ensure_ascii=False))
            return 0
        print(befund_clip(clip, M, laenge))
        if "--bild" in sys.argv:
            v0, v1 = float(von) if von else M["bereich"][0], float(bis) if bis else M["bereich"][1]
            marken = []
            if laenge:
                cand = [c for c in vorschlaege(M, laenge, None, None, 3) if c[0] < 0.5][:3]
                marken = [(s, e, "#2b8a3e", f"{i + 1}") for i, (k, s, e, d) in enumerate(cand)]
            pf = quellen.pfad(clip)
            out = WORK / "ansicht" / f"aktionen_{Path(pf).stem}.png"
            bild_clip(pf, M, v0, min(v1, v0 + 40), marken, out, titel=Path(pf).stem)
            print(f"Bild: {out}")
    finally:
        quellen.aufraeumen()
    return 0


def cmd_edl(a):
    dateien = [x for x in a if x.endswith(".json")]
    nur = {int(x) for x in arg("--nur", "").split(",") if x} or None
    quellen = Quellen("--behalten" in sys.argv)
    try:
        for f in dateien:
            E = json.load(open(f))
            res, fehler = pruefe_edl(E, quellen, personen_an="--ohne-personen" not in sys.argv, nur=nur)
            print(text_edl(res, Path(f).parent.name if Path(f).name == "edl.json" else Path(f).name))
            for c, err in fehler.items():
                print(f"   Clip {c} nicht gemessen: {err}")
            if "--bild" in sys.argv:
                for b in [b for b in res if b["hinweise"] and "M" in b][:8]:
                    pf = quellen.pfad(b["clip"])
                    marken = [(b["src"], b["ende"], "#1c7ed6", f"#{b['n']}")]
                    if b.get("vorschlag"):
                        marken.append((b["vorschlag"]["src"], b["vorschlag"]["ende"], "#2b8a3e", "besser"))
                    von, bis = b["src"] - 1.0, b["ende"] + 1.0
                    out = WORK / "ansicht" / f"aktionen_{Path(f).parent.name}_{b['n']}_{b['clip']}.png"
                    bild_clip(pf, b["M"], max(0.0, von), bis, marken, out, titel=f"#{b['n']} {b['clip']}")
                    print(f"   Bild: {out}")
    finally:
        quellen.aufraeumen()
    return 0


MIT_WERT = ("--laenge", "--von", "--bis", "--nur")


def positional(a):
    """Argumente ohne Schalter und deren Werte."""
    out, skip = [], False
    for x in a:
        if skip:
            skip = False
        elif x in MIT_WERT:
            skip = True
        elif not x.startswith("--"):
            out.append(x)
    return out


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("clip", "edl", "selbsttest"):
        sys.exit(__doc__)
    if a[0] == "selbsttest":
        return subprocess.run([sys.executable, str(PIPE / "test_aktionen.py")]).returncode
    rest = positional(a[1:])
    if not rest:
        sys.exit(__doc__)
    return (cmd_clip if a[0] == "clip" else cmd_edl)(rest)


if __name__ == "__main__":
    sys.exit(main())
