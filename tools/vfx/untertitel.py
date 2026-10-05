#!/usr/bin/env python3
"""Untertitel Wort für Wort als ASS-Datei (für ffmpeg ass=…:fontsdir=tools/fonts).

Grundstil (aus der Praxis, eigene Schrift: SCHRIFT, SCHRIFT_DATEI und CAP unten tauschen): sehr schmale, fette Schrift in
Großbuchstaben (Antonio Bold, dazu ein weißer Rand von ~1,5 px für mehr Gewicht), einheitlich weiß, kein schwarzer
Rand, keine zweite Farbe. Für die Lesbarkeit auf hellem Bild liegt hinter jedem Text ein weicher, dunkler Schein
(Halo, kein Rand). 1–3 Wörter auf einmal, nur so viele, wie in die Breite passen (gemessen mit der Schrift), das
gesprochene Wort wird kurz größer, jede neue Gruppe ploppt auf (90 ms). Satzzeichen außer ? und ! fallen weg.
Position: Bildmitte waagrecht, 65 % Höhe (über der Instagram-Leiste unten, frei von den Symbolen rechts).
Frage hinter der Kamera: kleiner, oben, bis 3 Zeilen, blendet nach der Frage weich aus (koepfe: e = Ende der
Ausblendung, aus = Dauer der Ausblendung in s).

Als Modul (Wörter schon auf der Reel-Zeitachse, Sekunden):
    from untertitel import ass
    ass([{"w": "Wir", "s": 0.20, "e": 0.41}, …], "untertitel.ass")        # optional je Wort "stil": "frage"
    ffmpeg … -vf "ass=untertitel.ass:fontsdir=<projekt>/tools/fonts" …
Gruppen: höchstens 3 Wörter und MAX_BREITE der Bildbreite, neue Gruppe nach Pause ≥ 0,35 s, nach . ? ! , und bei
Stil- oder Teilwechsel (je Wort optional „teil“), dazwischen gleichmäßig verteilt (4 Wörter = 2 + 2), keine Gruppe endet
auf Artikel oder Präposition, wenn es sich vermeiden lässt.
Größe: Großbuchstaben 96 px hoch, Fragen 54 px.
aktiv = Farbe des gesprochenen Worts (None = bleibt weiß, nur größer).
"""
import re
from functools import lru_cache
from pathlib import Path

FONTS = str(Path(__file__).resolve().parent.parent / "fonts")
SCHRIFT, SCHRIFT_DATEI = "Antonio", f"{FONTS}/Antonio-Bold.ttf"
# ASS-Farben: &HAABBGGRR (AA = Transparenz, 00 = deckend)
WEISS, SCHWARZ = "&H00FFFFFF", "&H00000000"
HALO = "&H80000000"  # Schwarz, etwa 50 % deckend: weicher Schein statt Rand
MAX_BREITE = 0.84  # Anteil der Bildbreite für eine Zeile (ohne das größere aktive Wort)
CAP = 0.86  # Höhe der Großbuchstaben in Vielfachen der Schrifthöhe (em) von Antonio Bold

KOPF = """[Script Info]
ScriptType: v4.00+
PlayResX: {bw}
PlayResY: {bh}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: studio,{schrift},{gr},{text},{text},{text},&H00000000,-1,0,0,0,100,100,0.5,0,1,{gewicht},0,5,40,40,0,1
Style: frage,{schrift},{gr2},{text},{text},{text},&H00000000,-1,0,0,0,100,100,0.5,0,1,{gewicht2},0,5,40,40,0,1
Style: halo,{schrift},{gr},{halo},{halo},{halo},&H00000000,-1,0,0,0,100,100,0.5,0,1,{schein},0,5,40,40,0,1
Style: halo_frage,{schrift},{gr2},{halo},{halo},{halo},&H00000000,-1,0,0,0,100,100,0.5,0,1,{schein2},0,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def zeit(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def sauber(w):
    """Anzeigeform: Großbuchstaben, ohne Satzzeichen außer ? und !, ß -> SS (so wie .upper())."""
    w = re.sub(r"[.,;:„“\"»«…–—]", "", w.strip())
    return w.upper()


def fontsize(cap_px):
    """ASS-Fontsize für eine Großbuchstabenhöhe in Pixeln (libass: Fontsize = Zellenhöhe, hier win-Ascent + Descent)."""
    return cap_px * 3054 / 1760


@lru_cache(maxsize=None)
def _schrift(groesse):
    """PIL-Schrift in der Größe, die libass für Fontsize groesse zeichnet (wie VSFilter: Fontsize = Zellenhöhe
    usWinAscent + usWinDescent, nicht das Geviert)."""
    from fontTools.ttLib import TTFont
    from PIL import ImageFont
    f = TTFont(SCHRIFT_DATEI)
    os2 = f["OS/2"]
    em = groesse * f["head"].unitsPerEm / (os2.usWinAscent + os2.usWinDescent)
    return ImageFont.truetype(SCHRIFT_DATEI, max(1, round(em)))


def breite(text, groesse):
    """Breite in Pixeln (PlayRes), wie libass die Zeile setzt (Spacing 0,5)."""
    return _schrift(groesse).getlength(text) + 0.5 * max(0, len(text) - 1)


BINDEWOERTER = set("der die das den dem des ein eine einen einem einer und oder aber auf mit von vom zu zum zur für "
                   "in im an am aus bei nach über unter vor dass weil wenn wie als".split())


def gruppen(woerter, max_w=3, max_px=900, groesse=120, pause=0.35):
    """1–3 Wörter je Gruppe, höchstens max_px breit. Harte Grenzen: Pause, . ? ! und Komma am Ende des vorigen Worts,
    Stil- oder Teilwechsel (Schnitt). Dazwischen werden die Wörter gleichmäßig verteilt (4 Wörter = 2 + 2 statt 3 + 1,
    5 = 2 + 3, 6 = 3 + 3), ein einzelnes Wort ist nur die Ausnahme, und eine Gruppe endet nicht auf Artikel,
    Präposition oder Bindewort, wenn es sich vermeiden lässt (kleinste Gesamtstrafe über alle Aufteilungen)."""
    segmente, seg = [], []
    for w in woerter:
        if seg:
            vor = seg[-1]
            if (w["s"] - vor["e"] >= pause or re.search(r"[.?!,]$", vor["w"].strip())
                    or w.get("stil") != vor.get("stil") or w.get("teil") != vor.get("teil")):
                segmente.append(seg)
                seg = []
        seg.append(w)
    if seg:
        segmente.append(seg)
    out = []
    for seg in segmente:
        n = len(seg)

        def strafe(i, j):  # Gruppe seg[i:j]
            k = j - i
            text = " ".join(sauber(x["w"]) for x in seg[i:j])
            if k > 1 and breite(text, groesse) > max_px:
                return None
            c = {1: 2.0, 2: 0.15, 3: 0.10}[k]
            if k > 1 and j < n and sauber(seg[j - 1]["w"]).lower() in BINDEWOERTER:
                c += 1.5
            return c
        best = [(0.0, -1)] + [(float("inf"), -1)] * n  # best[j] = (Strafe, Anfang der letzten Gruppe)
        for j in range(1, n + 1):
            for i in range(max(0, j - max_w), j):
                c = strafe(i, j)
                if c is not None and best[i][0] + c < best[j][0] - 1e-9:
                    best[j] = (best[i][0] + c, i)
        teile, j = [], n
        while j > 0:
            i = best[j][1]
            teile.append(seg[i:j])
            j = i
        out.extend(reversed(teile))
    return out


def kopfzeilen(text, groesse, max_px, max_zeilen=3):
    """Frage: Großbuchstaben, ohne Punkt (Komma und ? bleiben), nach Breite umbrochen; „|“ erzwingt einen Umbruch.
    Gibt (Liste der Zeilen, Maßstab in %) zurück: passt eine Zeile nicht, wird die ganze Frage kleiner."""
    zeilen = []
    for stueck in text.split("|"):
        z = ""
        for wort in re.sub(r"[.„“\"»«]", "", stueck).strip().upper().split():
            if z and breite(f"{z} {wort}", groesse) > max_px:
                zeilen.append(z)
                z = wort
            else:
                z = f"{z} {wort}".strip()
        if z:
            zeilen.append(z)
    zeilen = zeilen[:max_zeilen]
    b = max(breite(z, groesse) for z in zeilen) if zeilen else 0
    return zeilen, min(100, int(100 * max_px / b)) if b else 100


def ass(woerter, pfad, bw=1080, bh=1920, y=0.65, cap=96, frage_cap=54, stil_frage_y=0.16, ende=None,
        koepfe=(), aktiv=None, max_breite=None):
    """Schreibt die ASS-Datei. woerter: Liste {w, s, e[, stil]} auf der Reel-Zeitachse. ende = Reel-Länge.
    max_breite = Anteil der Bildbreite für eine Zeile (Standard MAX_BREITE 0,84; YouTube Shorts 0,77).
    cap = Höhe der Großbuchstaben in px (bei 1080 Breite). koepfe: Liste {text, s, e[, aus]}: Frage hinter der Kamera oben,
    blendet bis e aus (Ausblendung aus s lang, Standard 0,45)."""
    s = bw / 1080
    gr, gr2 = round(fontsize(cap * s)), round(fontsize(frage_cap * s))
    max_px = (max_breite or MAX_BREITE) * bw
    zeilen = [KOPF.format(bw=bw, bh=bh, schrift=SCHRIFT, gr=gr, gr2=gr2, text=WEISS, halo=HALO,
                          gewicht=round(1.5 * s * cap / 112, 1), gewicht2=round(1.5 * s * frage_cap / 112, 1),
                          schein=round((1.5 + 9) * s, 1), schein2=round((1.0 + 6) * s, 1))]
    blur, blur2 = f"\\blur{round(8 * s)}", f"\\blur{round(5.5 * s)}"

    def ev(start, ende_, text, pos_, stil, tags="", tags_halo=""):
        """Ein Ereignis mit Halo darunter (Schicht 0) und Text darüber (Schicht 1)."""
        halo_ = "halo_frage" if stil == "frage" else "halo"
        b_ = blur2 if stil == "frage" else blur
        zeilen.append(f"Dialogue: 0,{zeit(start)},{zeit(ende_)},{halo_},,0,0,0,,{{{pos_}{b_}{tags_halo}}}{text}")
        zeilen.append(f"Dialogue: 1,{zeit(start)},{zeit(ende_)},{stil},,0,0,0,,{{{pos_}{tags}}}{text}")

    for k in koepfe:
        zl, m = kopfzeilen(k["text"], gr2, max_px)
        a0 = round(m * 0.86)
        pitch = 1.5 * frage_cap * s  # Zeilenabstand: 1,5 × Großbuchstabenhöhe
        for j, z in enumerate(zl):
            pos = rf"\pos({bw // 2},{round(bh * stil_frage_y + (j - (len(zl) - 1) / 2) * pitch)})"
            anim = f"\\fad(90,{round(1000 * k.get('aus', 0.45))})\\fscx{a0}\\fscy{a0}\\t(0,110,\\fscx{m}\\fscy{m})"
            ev(k["s"] - 0.05, k["e"], z, pos, "frage", anim, anim)
    gs = gruppen([w for w in woerter if sauber(w["w"])], max_px=max_px, groesse=gr)
    for k, g in enumerate(gs):
        start = g[0]["s"] - 0.04
        nach = gs[k + 1][0]["s"] - 0.04 if k + 1 < len(gs) else (ende or g[-1]["e"] + 0.6)
        stop = min(nach, g[-1]["e"] + 0.45)
        stop = max(stop, start + 0.3)
        frage = g[0].get("stil") == "frage"
        pos = rf"\pos({bw // 2},{round(bh * (stil_frage_y if frage else y))})"
        # ein einzelnes Wort, das breiter ist als die Zeile: ganze Gruppe kleiner
        m = min(100, int(100 * max_px / breite(" ".join(sauber(w["w"]) for w in g), gr)))
        if frage:  # Frage als Untertitel: ganze Gruppe ruhig, ohne Wort-Pop
            txt = " ".join(sauber(w["w"]) for w in g)
            ev(start, stop, txt, pos, "frage", "\\fad(80,80)", "\\fad(80,80)")
            continue
        for i, w in enumerate(g):
            a = start if i == 0 else w["s"] - 0.02
            b = g[i + 1]["s"] - 0.02 if i + 1 < len(g) else stop
            if b - a < 0.02:
                continue
            teile = []  # erstes Ereignis der Gruppe: alles ploppt von 82 % auf; danach nur das aktive Wort
            for j, x in enumerate(g):
                t = sauber(x["w"])
                if j == i:
                    a0, a1 = round(m * (0.88 if i == 0 else 1.0)), round(m * 1.06)
                    teile.append(rf"{{\fscx{a0}\fscy{a0}\t(0,90,\fscx{a1}\fscy{a1})}}{t}")
                elif i == 0:
                    teile.append(rf"{{\fscx{round(m * 0.82)}\fscy{round(m * 0.82)}\t(0,90,\fscx{m}\fscy{m})}}{t}")
                else:
                    teile.append(rf"{{\fscx{m}\fscy{m}}}{t}")
            ev(a, b, " ".join(teile), pos, "studio")
    with open(pfad, "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")
    return len(gs)
