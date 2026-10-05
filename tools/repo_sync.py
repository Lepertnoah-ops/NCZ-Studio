#!/usr/bin/env python3
"""Stand des Projektordners ins GitHub-Repository nachziehen (Sicherung mit Versionsverlauf).

    python3 /mnt/project-files/tools/repo_sync.py /home/user/<repository>    # Pfad = Repository-Kopie (git-Checkout)

Nur für den Betrieb als Claude-Projekt mit GitHub-Sicherung: Der Projektordner (/mnt/project-files, anders per
Umgebungsvariable STUDIO_PROJEKT) ist die Arbeitskopie, das private GitHub-Repository nur die Sicherung.
Das Skript liest den Projektordner nur und schreibt nur in die Repository-Kopie. Was nicht mitkommt, steht in
.gitignore im Projektordner (Videos, Musik außer sfx/, alles in reels/ außer Schnittlisten, Skripten und Steckbriefen,
uploads/, .notes/); Dateien über 20 MB werden zusätzlich übersprungen. Im Projektordner gelöschte Dateien verschwinden
auch aus der Kopie, im Verlauf bleiben sie; ganze Reel-Ordner, die nur im Repository liegen (etwa aus einer eigenen
Session), bleiben stehen und werden gemeldet. Committen und pushen macht danach der Thread (Befehl am Ende der Ausgabe).
"""
import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
QUELLE = Path(os.environ.get("STUDIO_PROJEKT", "/mnt/project-files")).resolve()
REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
MAX_MB = 20
NIE = {"uploads", ".notes", ".git"}  # Root-Ordner, die nie kopiert werden


def git(*args, eingabe=None):
    r = subprocess.run(["git", "-C", str(REPO), *args], input=eingabe, capture_output=True, check=False)
    if r.returncode not in (0, 1):  # check-ignore meldet 1, wenn nichts ausgeschlossen ist
        sys.exit(f"git {args[0]} fehlgeschlagen: {r.stderr.decode(errors='replace').strip()}")
    return [x for x in r.stdout.decode().split("\0") if x]


def dateien_im_projekt():
    for wurzel, ordner, namen in os.walk(QUELLE):
        rel = Path(wurzel).relative_to(QUELLE)
        ordner[:] = [o for o in ordner if o != "__pycache__" and not (rel == Path(".") and o in NIE)]
        for n in namen:
            p = Path(wurzel) / n
            if p.is_file() and not p.is_symlink():
                yield (rel / n).as_posix()


def main():
    if not (REPO / ".git").exists() or REPO == QUELLE:
        sys.exit("Pfad zur Repository-Kopie (git-Checkout) angeben, z. B. /home/user/<repository>.")
    regeln = QUELLE / ".gitignore"
    if not regeln.is_file():
        sys.exit(f"{regeln} fehlt; ohne Ausschlussliste käme jedes Video mit.")
    shutil.copy2(regeln, REPO / ".gitignore")  # zuerst, damit check-ignore die aktuellen Regeln nutzt

    alle = sorted(dateien_im_projekt())
    ausgeschlossen = set(git("check-ignore", "--no-index", "--stdin", "-z", eingabe="\0".join(alle).encode()))
    kopiert, zu_gross, mb = [], [], 0.0
    for rel in alle:
        if rel in ausgeschlossen:
            continue
        q, z = QUELLE / rel, REPO / rel
        if q.stat().st_size > MAX_MB * 1e6:
            zu_gross.append(f"{rel} ({q.stat().st_size / 1e6:.0f} MB)")
            continue
        kopiert.append(rel)
        mb += q.stat().st_size / 1e6
        if not (z.is_file() and filecmp.cmp(q, z, shallow=False)):
            z.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(q, z)

    im_projekt = set(kopiert) | {g.split(" (")[0] for g in zu_gross}  # zu große behalten ihre alte Fassung
    nur_im_repo = set()
    for rel in git("ls-files", "-z"):
        if rel in im_projekt or not (REPO / rel).is_file():
            continue
        teile = rel.split("/")
        if teile[0] == "reels" and len(teile) > 2 and not (QUELLE / "reels" / teile[1]).exists():
            nur_im_repo.add(f"reels/{teile[1]}")  # z. B. aus einer eigenen Session: nie still löschen
            continue
        (REPO / rel).unlink()

    status = git("status", "--porcelain", "-z", "--untracked-files=all")
    art = {"??": "neu", "M": "geändert", "D": "gelöscht"}
    zeilen = [(art.get(s[:2].strip(), s[:2].strip()), s[3:]) for s in status]
    fremd = [p for a, p in zeilen if a == "neu" and p not in im_projekt]
    print(f"Projektordner: {len(alle)} Dateien, davon {len(kopiert)} in der Sicherung ({mb:.0f} MB), "
          f"{len(ausgeschlossen)} ausgeschlossen (.gitignore)")
    for g in zu_gross:
        print(f"  zu groß, übersprungen: {g}")
    zaehl = {a: sum(1 for x, _ in zeilen if x == a) for a in ("neu", "geändert", "gelöscht")}
    print("Repository-Kopie: " + ", ".join(f"{n} {a}" for a, n in zaehl.items()))
    for a, p in zeilen[:25]:
        print(f"  {a:9s}{p}")
    if len(zeilen) > 25:
        print(f"  … und {len(zeilen) - 25} weitere")
    for p in fremd:
        print(f"  ACHTUNG, nur in der Kopie, nicht aus dem Projektordner: {p}")
    for r in sorted(nur_im_repo):
        print(f"  ACHTUNG, Reel nur im Repository, nicht gelöscht: {r} (in den Projektordner holen oder bewusst entfernen)")
    if zeilen:
        print(f'Weiter: git -C {REPO} add -A && git -C {REPO} commit -m "Stand aus dem Projektordner" && git -C {REPO} push')
    else:
        print("Nichts zu sichern, das Repository ist auf dem Stand des Projektordners.")


if __name__ == "__main__":
    main()
