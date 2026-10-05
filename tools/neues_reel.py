#!/usr/bin/env python3
"""Neuen Reel-Ordner aus der Vorlage anlegen.

    python3 <projekt>/tools/neues_reel.py <name> [--datum JJJJ-MM-TT] [--interview]

Legt reels/<datum>_<name>/ an (Datum = heute, Name klein, ohne Leerzeichen), kopiert reels/_vorlage/
(README-Steckbrief) und legt die Schnittliste je Variante an: schnitt/A, schnitt/B, schnitt/C (Varianten zur Auswahl,
Namen und Ideen aus stil.json "varianten"). Bricht ab, wenn der Ordner schon existiert.
Mit --interview (Interview-Reel statt der drei Varianten): legt reels/<datum>_<name>/ mit README.md und
schnitt/schnitt.py aus reels/_vorlage/interview/ an (Stimme führt, Untertitel, Abspann; Kurzanleitung „Interview-Reels“).
"""
import datetime
import re
import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
VORLAGE = PROJECT / "reels" / "_vorlage"
sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
sys.path.insert(0, str(PROJECT / "tools"))
from stil import STIL  # noqa: E402

# Varianten aus stil.json: jedes Paar unterscheidet sich in mindestens 2 von 3 Punkten (Songabschnitt, Auswahl/Story,
# Tempo/Effekt-Dichte), alle bleiben im Stil-Leitfaden. Namen und Idee dürfen zum Material passen.
VARIANTEN = [(v["x"], v["name"], v.get("idee", ""), v.get("kurz", "")) for v in STIL["varianten"]]


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        sys.exit(__doc__)
    datum = args[args.index("--datum") + 1] if "--datum" in args else datetime.date.today().isoformat()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", datum), f"Datum {datum!r} bitte als JJJJ-MM-TT"
    name = re.sub(r"[^a-z0-9äöüß_-]+", "_", args[0].strip().lower()).strip("_")
    ziel = PROJECT / "reels" / f"{datum}_{name}"
    if ziel.exists():
        sys.exit(f"Gibt es schon: {ziel}")
    if "--interview" in args:
        (ziel / "schnitt").mkdir(parents=True)
        for quelle, dahin in ((VORLAGE / "interview" / "README.md", ziel / "README.md"),
                              (VORLAGE / "interview" / "schnitt.py", ziel / "schnitt" / "schnitt.py")):
            dahin.write_text(quelle.read_text().replace("{NAME}", name).replace("{DATUM}", datum))
        print(ziel)
        return
    shutil.copytree(VORLAGE, ziel, ignore=shutil.ignore_patterns("__pycache__", "*.json", "interview"))
    p = ziel / "README.md"
    p.write_text(p.read_text().replace("{NAME}", name).replace("{DATUM}", datum))
    edl = ziel / "schnitt" / "edl.py"
    vorlage = edl.read_text().replace("{NAME}", name).replace("{DATUM}", datum)
    for x, vname, idee, kurz in VARIANTEN:
        (ziel / "schnitt" / x).mkdir()
        (ziel / "schnitt" / x / "edl.py").write_text(vorlage.replace("{VARIANTE}", x).replace("{VARIANTE_NAME}", vname)
                                                     .replace("{VARIANTE_IDEE}", idee).replace("{VARIANTE_KURZ}", kurz))
    edl.unlink()
    print(ziel)


if __name__ == "__main__":
    main()
