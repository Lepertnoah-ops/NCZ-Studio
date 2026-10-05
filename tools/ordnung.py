#!/usr/bin/env python3
"""Ordnung im Projektordner prüfen und Reel-Übersicht zeigen.

    python3 <projekt>/tools/ordnung.py          # nur prüfen
    python3 <projekt>/tools/ordnung.py --fix    # zusätzlich __pycache__ löschen (sonst wird nie etwas gelöscht)

Regeln aus README.md: im Root nur die festen Ordner und Dokumente; je Reel ein Ordner
reels/JJJJ-MM-TT_name/ mit README.md und schnitt/; oben nur die aktuelle Fassung, ältere in archiv/vN/; vor der
Wahl oben je Variante <name>_X_vorschau.mp4 und <name>_X_storyboard.jpg, danach in archiv/varianten/;
keine großen Zwischendaten (Frames, Downloads, Master, WAV-Mixe) im Projektordner.
"""
import re
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parent.parent
ROOT_OK = {"README.md", "CLAUDE.md", "EINRICHTUNG.md", ".gitignore", ".git", "Kurzanleitung.md",
           "Reel-Studio_Projektanweisungen.md", "Stil-Leitfaden.md", "stil.json", "reels", "referenz", "tools", "sfx",
           "uploads", ".notes"}
BIBLIOTHEK = {".mp4", ".mov", ".m4a", ".mp3", ".wav", ".jpg", ".jpeg", ".png", ".heic", ".pdf"}   # Uploads des Nutzers
ZWISCHEN = re.compile(r"(master|_mix|frames?|prev|raw_\d+|f_\d{5}|k_\d{4})", re.I)
VARIANTE = re.compile(r"_([A-Z])_(vorschau\.mp4|storyboard\.jpg)$")
YOUTUBE = re.compile(r"_yt_")   # Dateien der YouTube-Shorts-Fassung (plattform.py): <name>_yt_mit_song.mp4 …


def mb(p):
    return p.stat().st_size / 1e6


def main(fix=False):
    warn, bib = [], []
    for p in sorted(PROJECT.iterdir()):
        if p.name in ROOT_OK:
            continue
        if p.is_file() and p.suffix.lower() in BIBLIOTHEK:
            bib.append(p.name)            # über die Bibliothek hochgeladen, landet im Root; bleibt dort
        else:
            warn.append(f"Im Root, gehört woanders hin: {p.name}")
    caches = [p for p in PROJECT.rglob("__pycache__") if "uploads" not in p.parts]
    for c in caches:
        if fix:
            shutil.rmtree(c, ignore_errors=True)
    if caches:
        warn.append(f"{len(caches)} __pycache__-Ordner" + (" gelöscht" if fix else " (mit --fix löschen)"))
    for p in PROJECT.rglob("*"):
        if "uploads" in p.parts or not p.is_file():
            continue
        if p.suffix.lower() in (".wav",) and mb(p) > 20 and "sfx" not in p.parts:
            warn.append(f"Großer WAV-Mix im Projekt ({mb(p):.0f} MB): {p.relative_to(PROJECT)}")
        elif p.suffix.lower() in (".png", ".jpg") and re.match(r"(raw|f|k|g)_\d{3,5}\.", p.name):
            warn.append(f"Einzelframe im Projekt: {p.relative_to(PROJECT)}")
            break
        elif p.suffix.lower() in (".mp4", ".mov") and ZWISCHEN.search(p.stem) and "archiv" not in p.parts:
            warn.append(f"Zwischendatei im Projekt ({mb(p):.0f} MB): {p.relative_to(PROJECT)}")
    print("Reels:")
    reels = sorted(d for d in (PROJECT / "reels").iterdir() if d.is_dir() and d.name != "_vorlage")
    for d in reels:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_[a-z0-9äöüß_-]+", d.name):
            warn.append(f"Reel-Ordner nicht nach JJJJ-MM-TT_name benannt: {d.name}")
        readme = d / "README.md"
        status = "?"
        if readme.exists():
            m = re.search(r"^\|\s*Status\s*\|\s*(.+?)\s*\|", readme.read_text(), re.M)
            status = m.group(1) if m else "?"
        else:
            warn.append(f"{d.name}: README.md (Steckbrief) fehlt")
        if not (d / "schnitt").is_dir():
            warn.append(f"{d.name}: schnitt/ fehlt")
        top = sorted(p.name for p in d.glob("*_mit_song.mp4") if not YOUTUBE.search(p.name))
        top_yt = sorted(p.name for p in d.glob("*_yt_mit_song.mp4"))
        if len(top) > 1:
            warn.append(f"{d.name}: {len(top)} Fassungen oben ({', '.join(top)}), ältere nach archiv/vN/ verschieben")
        if len(top_yt) > 1:
            warn.append(f"{d.name}: {len(top_yt)} YouTube-Fassungen oben ({', '.join(top_yt)}), ältere nach archiv/vN/ verschieben")
        vor = sorted(p.name for p in d.glob("*_vorschau.mp4") if not VARIANTE.search(p.name) and not YOUTUBE.search(p.name))
        if len(vor) > 1:
            warn.append(f"{d.name}: {len(vor)} Vorschau-Videos oben ({', '.join(vor)}), ältere nach archiv/vN/ verschieben")
        var = sorted(p.name for p in d.iterdir() if VARIANTE.search(p.name))
        if var and (top or top_yt):
            warn.append(f"{d.name}: Varianten-Dateien oben, obwohl schon exportiert ({', '.join(var)}); nach der Wahl "
                        f"gehören sie nach archiv/varianten/ (macht varianten.py --wahl)")
        wahl = sorted({VARIANTE.search(n).group(1) for n in var})
        archiv = sorted(p.name for p in (d / "archiv").glob("v*")) if (d / "archiv").exists() else []
        aktuell = top[0] if top else (top_yt[0] if top_yt else (f"Varianten {', '.join(wahl)} zur Auswahl" if wahl else "–"))
        if top and top_yt:
            aktuell += " + YouTube"
        print(f"  {d.name:32s} {status[:60]:60s} aktuell: {aktuell}"
              + (f", Archiv: {' '.join(archiv)}" if archiv else ""))
    if bib:
        print(f"\nBibliothek (Uploads des Nutzers im Root, bleiben dort): {', '.join(bib)}")
    print("\nOrdnung:", "alles sauber" if not warn else f"{len(warn)} Hinweis(e)")
    for w in warn:
        print("  -", w)
    return not warn


if __name__ == "__main__":
    sys.exit(0 if main("--fix" in sys.argv) else 1)
