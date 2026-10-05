#!/usr/bin/env python3
"""Gesamtablauf der Analyse in einem Aufruf (ruft die Einzelwerkzeuge in diesem Ordner auf).

    # vor dem Storyboard: Song + Clips analysieren, Shotliste vorschlagen
    python3 analyse.py vorbereiten --song song.mp3 --clips CLIPORDNER [--tags tags.json] -o OUT
    python3 analyse.py vorbereiten --song song.mp3 --manifest manifest.tsv --only IMG_6166,IMG_3419 --tags tags.json -o OUT

    # vor der Abgabe: fertiges Reel prüfen (Song-Analyse wird bei Bedarf erzeugt)
    python3 analyse.py pruefen reel_mit_song.mp4 --song song.mp3 [--edl shotliste.json] -o OUT

Ergebnis: OUT/song/ (song.json, song.md, song.png, akzentkarte.png), OUT/clips/ (clips.json,
clips.md, kontaktbogen_*.jpg), OUT/shotliste/ (shotliste.json, shotliste.md), OUT/qc/ (qc.md …).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(*cmd):
    print("»", " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([sys.executable, *map(str, cmd)], cwd=Path.home())   # nicht im Projektordner (FUSE) laufen
    return r.returncode


def song_json(song, out, bpm=None):
    sj = out / "song" / "song.json"
    if not sj.exists():
        extra = ["--bpm", bpm] if bpm else []
        if run(HERE / "song_analyse.py", song, "-o", out / "song", *extra):
            sys.exit("Song-Analyse fehlgeschlagen")
    return sj


def main():
    ap = argparse.ArgumentParser(description="Analyse-Gesamtablauf für Reels")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vorbereiten", help="Song + Clips analysieren, Shotliste vorschlagen")
    v.add_argument("--song", required=True)
    v.add_argument("--clips", nargs="*", default=[], help="Clip-Dateien oder Ordner")
    v.add_argument("--manifest", help="Drive-Manifest (id, name, size) zum Laden der Clips")
    v.add_argument("--only", help="nur diese Clips aus dem Manifest, z. B. IMG_6166,IMG_3419")
    v.add_argument("--tags", help="Tags je Clip (Format: tags_beispiel.json)")
    v.add_argument("--bpm", help="Tempo vorgeben")
    v.add_argument("--fenster", default="1")
    v.add_argument("--jobs", default="2")
    v.add_argument("--schnell", action="store_true", help="Clip-Analyse nur auf Keyframes (~8× schneller, grob)")
    v.add_argument("--vorschau", action="store_true", help="Vorschau-Storyboard aus den lokalen Clips zeichnen")
    v.add_argument("-o", "--out", required=True)
    p = sub.add_parser("pruefen", help="fertiges Reel prüfen")
    p.add_argument("reel")
    p.add_argument("--song")
    p.add_argument("--edl")
    p.add_argument("--bpm")
    p.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    for k in ("song", "manifest", "tags", "edl", "reel", "out"):          # Pfade absolut, Unterprozesse laufen in ~
        if getattr(a, k, None):
            setattr(a, k, str(Path(getattr(a, k)).resolve()))
    if getattr(a, "clips", None):
        a.clips = [str(Path(c).resolve()) for c in a.clips]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "vorbereiten":
        sj = song_json(a.song, out, a.bpm)
        cj = None
        dl_dirs = []
        if a.clips or a.manifest:
            extra = (["--manifest", a.manifest] if a.manifest else []) + (["--only", a.only] if a.only else []) + \
                (["--schnell"] if a.schnell else [])
            if a.manifest and a.vorschau:   # Vorschau braucht die Clips: Downloads im Container behalten (WORK/dl wie ingest.py)
                dl = Path(os.environ.get("REEL_WORK", "/home/user/reel")) / "dl"
                extra += ["--download-dir", str(dl), "--behalten"]
                dl_dirs = [str(dl)]
            if run(HERE / "clip_analyse.py", *a.clips, "-o", out / "clips", "--jobs", a.jobs, *extra) == 0:
                cj = out / "clips" / "clips.json"
        cmd = [HERE / "shotliste.py", "--song", sj, "--fenster", a.fenster, "-o", out / "shotliste"]
        if cj and cj.exists():
            cmd += ["--clips", cj]
        if a.tags:
            cmd += ["--tags", a.tags]
        run(*cmd)
        dirs = ([c for c in a.clips if Path(c).is_dir()] or sorted({str(Path(c).parent) for c in a.clips})) + dl_dirs
        if a.vorschau and dirs:
            run(HERE / "storyboard_vorschau.py", out / "shotliste" / "shotliste.json", "--clips", *dirs,
                "--song", sj, "-o", out / "shotliste" / "vorschau_storyboard.jpg")
        print(f"\nFertig: {out}/song/song.md, {out}/clips/clips.md, {out}/shotliste/shotliste.md")
    else:
        cmd = [HERE / "reel_qc.py", a.reel, "-o", out / "qc"]
        if a.song:
            cmd += ["--song", a.song, "--song-json", song_json(a.song, out, a.bpm)]
        if a.edl:
            cmd += ["--edl", a.edl]
        sys.exit(run(*cmd))


if __name__ == "__main__":
    main()
