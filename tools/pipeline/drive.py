#!/usr/bin/env python3
"""Drive-Helfer: Manifest aus der Connector-Ausgabe bauen, Dateien sicher laden, Manifest prüfen .

    python3 drive.py manifest <search_files-Ausgabe.json>... [-o manifest.tsv] [--fotos]
    python3 drive.py holen <id> <ziel> [--groesse <bytes>]          # Clip, Foto oder Song
    python3 drive.py pruefen [manifest.tsv] [--online]

manifest: liest die JSON-Ausgabe von search_files (eine Datei je Seite, „-“ = Standardeingabe; auch die vom Werkzeug
  abgelegte Ergebnisdatei mit Textblöcken), lässt Google-Dokumente und Sonstiges weg, meldet Unterordner mit Name und
  ID (sie werden nicht durchsucht: eigene Suche mit parentId; Ordnertitel können Leerzeichen am Ende haben, also nie
  nach dem Titel suchen), nimmt Videos (mit --fotos auch Fotos) als <id>\\t<name>\\t<bytes> und listet Audio-Dateien zum
  Song. Dieselbe ID zweimal zählt einmal; gleicher Name und gleiche Größe unter anderer ID gilt als Duplikat (nicht
  aufgenommen, per MD5 nachprüfbar); gleicher Name mit anderer Größe bekommt „~<id-Anfang>“ im Namen, damit kein Clip
  den anderen überschreibt.
holen: Range-Vorabfrage (Gesamtgröße, HTTP-Status), Download in <ziel>.part mit Fortsetzen, danach Größe, HTML-Fehler-
  seite (Freigabe fehlt, Downloadlimit, falsche ID) und Dateikopf zur Endung prüfen; erst dann heißt die Datei <ziel>.
  Endgültige Fehler (404, 403, nicht freigegeben, Limit) brechen sofort ab, sonst 5 Versuche mit Wartezeit.
pruefen: manifest.tsv auf Format, doppelte IDs und Dateistämme, Endungen und Größen; --online fragt jede ID per Range
  ab (Erreichbarkeit, Freigabe, Größe gegen Drive). Exit 1 bei FEHLER.

Nur lesen: es wird nichts in Drive geändert. Die Funktion holen() ist auch reelcfg.download().
"""
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner

URL = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"
VIDEO_EXT = (".mov", ".mp4", ".m4v")
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
FOTO_EXT = (".heic", ".heif", ".jpg", ".jpeg", ".png")
ENDGUELTIG = (400, 401, 403, 404)          # kein Wiederholen: die Anfrage ist falsch oder nicht erlaubt
PAUSE = 1.0                                # Sekunden vor dem 2. Versuch, danach verdoppelt (Tests setzen 0,01)
OK, WARN, FAIL, INFO = "OK", "WARNUNG", "FEHLER", "INFO"


def _curl(args, timeout=None):
    return subprocess.run(["curl", "-sS", *[str(a) for a in args]], capture_output=True, text=True, timeout=timeout)


def _log(logname, *a):
    try:
        from reelcfg import log
        log(logname, *a)
    except Exception:
        pass


# ---------------------------------------------------------------- Abfrage und Prüfung

def _kopfzeilen(text):
    """curl -D bei -L: ein Block je Antwort; Liste (Status, {Name klein: Wert}), die letzte ist die endgültige."""
    out = []
    for block in re.split(r"\r?\n\r?\n", text.strip()):
        zeilen = block.splitlines()
        if not zeilen:
            continue
        st = re.match(r"HTTP/\S+\s+(\d+)", zeilen[0])
        h = {}
        for z in zeilen[1:]:
            if ":" in z:
                k, v = z.split(":", 1)
                h[k.strip().lower()] = v.strip()
        out.append((int(st.group(1)) if st else 0, h))
    return out


def abfrage(fid, timeout=40):
    """Range-Anfrage 0-0 (ein Byte): {status, gesamt, typ, fehler}. Nur den Kopf lesen, nie die ganze Datei."""
    with tempfile.TemporaryDirectory() as td:
        kopf = Path(td) / "kopf"
        r = _curl(["-L", "-r", "0-0", "--max-filesize", "1000000", "-m", timeout, "-D", kopf, "-o", os.devnull,
                   URL.format(id=fid)])
        bloecke = _kopfzeilen(kopf.read_text(errors="replace")) if kopf.exists() else []
    if not bloecke:
        return dict(status=0, gesamt=None, typ="", fehler=(r.stderr.strip() or "keine Antwort")[-200:])
    status, h = bloecke[-1]
    m = re.match(r"bytes\s+\d+-\d+/(\d+)", h.get("content-range", ""))
    gesamt = int(m.group(1)) if m else (int(h["content-length"]) if status == 200 and h.get("content-length", "").isdigit() else None)
    return dict(status=status, gesamt=gesamt, typ=h.get("content-type", "").split(";")[0].strip().lower(), fehler="")


def html_grund(text):
    """Was eine HTML-Seite statt der Datei bedeutet (für die Meldung an den Nutzer)."""
    t = text.lower()
    if "quota" in t or "too many users" in t or "zu viele nutzer" in t:
        return "Downloadlimit von Drive für diese Datei erreicht (Sperre bis zu 24 Stunden)"
    if "accounts.google.com" in t or "sign in" in t or "anmelden" in t:
        return "Datei ist nicht freigegeben (Anmeldeseite statt Datei): „Jeder mit dem Link“ fehlt"
    if "not found" in t or "nicht gefunden" in t or "error 404" in t:
        return "ID unbekannt oder Datei gelöscht"
    if "error 500" in t or "server error" in t:
        return "Serverfehler von Drive: ID falsch oder Drive gestört"
    return "Drive liefert eine HTML-Seite statt der Datei"


def ist_html(kopf):
    return kopf[:2048].lstrip().lower().startswith((b"<!doctype", b"<html", b"<?xml", b"<head", b"<body"))


def kopf_passt(kopf, endung):
    """Dateikopf passt zur Endung? Unbekannte Endungen gelten als passend (dann zählt nur der HTML-Test)."""
    e = endung.lower()
    if e in (".mov", ".mp4", ".m4v", ".heic", ".heif", ".m4a"):
        return kopf[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot")
    if e in (".jpg", ".jpeg"):
        return kopf[:3] == b"\xff\xd8\xff"
    if e == ".png":
        return kopf[:4] == b"\x89PNG"
    if e == ".mp3":
        return kopf[:3] == b"ID3" or (len(kopf) > 1 and kopf[0] == 0xFF and kopf[1] & 0xE0 == 0xE0)
    if e == ".wav":
        return kopf[:4] == b"RIFF" and kopf[8:12] == b"WAVE"
    if e == ".flac":
        return kopf[:4] == b"fLaC"
    if e == ".ogg":
        return kopf[:4] == b"OggS"
    return True


def _pruefe_datei(teil, endung, soll):
    """(ok, grund, endgueltig) für eine fertig geladene Teildatei."""
    n = teil.stat().st_size
    with open(teil, "rb") as f:
        kopf = f.read(4096)
    if ist_html(kopf):
        g = html_grund(kopf.decode("utf-8", "replace"))
        return False, g, "nicht freigegeben" in g or "Downloadlimit" in g or "unbekannt" in g
    if soll and n != soll:
        return False, f"Größe {n} statt {soll} Bytes", False
    if not soll and n < 1024:
        return False, f"nur {n} Bytes und keine Größenangabe, vermutlich eine Fehlerseite", False
    if not kopf_passt(kopf, endung):
        return False, f"Dateikopf passt nicht zu {endung} (Anfang {kopf[:12]!r})", False
    return True, "", False


# ---------------------------------------------------------------- Download

def laden(fid, path, size=0, versuche=5):
    """Datei laden und prüfen: (ok, Grund). size <= 0 = Manifest kennt die Größe nicht, dann zählt die Größe aus
    der Range-Abfrage, sonst nur Fehlerseite und Dateikopf."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fid.startswith("local:"):
        if path.exists() or path.is_symlink():
            path.unlink()
        path.symlink_to(Path(fid[6:]).resolve())
        return True, ""
    if path.exists() and size > 0 and path.stat().st_size == size:
        return True, "schon vorhanden, Größe wie im Manifest"
    if path.exists():
        path.unlink()                               # falsche Größe oder alte Fehlerseite
    q = None
    for i in range(3):
        q = abfrage(fid)
        if q["status"] in (200, 206) and q["typ"] != "text/html":
            break
        if q["status"] in ENDGUELTIG:
            break
        time.sleep(PAUSE * 2 ** i)
    if q["status"] not in (200, 206) or q["typ"] == "text/html":
        if q["typ"] == "text/html" or q["status"] >= 400:
            with tempfile.TemporaryDirectory() as td:
                _curl(["-L", "--max-filesize", "200000", "-m", "40", "-o", Path(td) / "seite", URL.format(id=fid)])
                seite = (Path(td) / "seite")
                text = seite.read_text(errors="replace") if seite.exists() else ""
            grund = html_grund(text) if text else "keine Datei"
            return False, f"HTTP {q['status']}: {grund}"
        return False, f"keine Verbindung zu Drive: {q['fehler']}"
    gesamt = q["gesamt"]
    warn = ""
    if size > 0 and gesamt and gesamt != size:
        warn = f" (Drive meldet {gesamt}, Manifest {size}: Drive gilt)"
    soll = gesamt or (size if size > 0 else 0)
    teil = path.with_name(path.name + ".part")
    grund = "unbekannt"
    for i in range(versuche):
        if not (teil.exists() and soll and teil.stat().st_size == soll):
            r = _curl(["-L", "--fail", "-C", "-", "-o", teil, URL.format(id=fid)])
            if r.returncode in (33, 36) or (r.returncode == 22 and "416" in r.stderr):
                teil.unlink(missing_ok=True)        # Fortsetzen geht nicht: von vorn
            elif r.returncode and not teil.exists():
                grund = (r.stderr.strip() or f"curl {r.returncode}")[-200:]
                _log("download", "retry", path.name, i, grund)
                time.sleep(PAUSE * 2 ** i)
                continue
        if not teil.exists():
            continue
        ok, grund, ende = _pruefe_datei(teil, path.suffix, soll)
        if ok:
            os.replace(teil, path)
            return True, warn.strip()
        _log("download", "retry", path.name, i, grund)
        if ende:
            teil.unlink(missing_ok=True)
            return False, grund
        if teil.stat().st_size > soll > 0 or "Dateikopf" in grund or "HTML" in grund:
            teil.unlink(missing_ok=True)            # unbrauchbar: neu beginnen; zu kurz: beim nächsten Versuch fortsetzen
        time.sleep(PAUSE * 2 ** i)
    teil.unlink(missing_ok=True)
    return False, grund


def holen(fid, path, size=0, logname="download"):
    """Wie früher reelcfg.download: True bei Erfolg. Der Grund eines Fehlschlags steht in $REEL_WORK/<logname>.log."""
    ok, grund = laden(fid, path, size)
    if not ok:
        _log(logname, "FEHLER", Path(path).name, grund)
    return ok


# ---------------------------------------------------------------- Manifest

def _dateien(obj):
    """Datei-Einträge aus search_files-Ausgaben: {files: [...]}, Liste, Textblöcke mit JSON darin."""
    import json
    if isinstance(obj, str):
        try:
            return _dateien(json.loads(obj))
        except ValueError:
            return []
    if isinstance(obj, list):
        return [f for x in obj for f in _dateien(x)]
    if isinstance(obj, dict):
        if "files" in obj:
            return _dateien(obj["files"])
        if "id" in obj and ("title" in obj or "name" in obj):
            return [obj]
        return [f for k in ("text", "content", "result") if k in obj for f in _dateien(obj[k])]
    return []


def art(f):
    name = f.get("title") or f.get("name") or ""
    mt = (f.get("mimeType") or "").lower()
    ext = os.path.splitext(name)[1].lower()
    if mt == "application/vnd.google-apps.folder":
        return "ordner"
    if mt.startswith("application/vnd.google-apps."):
        return "google"
    if mt.startswith("video/") or ext in VIDEO_EXT:
        return "video"
    if mt.startswith("image/") or ext in FOTO_EXT:
        return "foto"
    if mt.startswith("audio/") or ext in AUDIO_EXT:
        return "audio"
    return "sonst"


def manifest_bauen(quellen, fotos=False):
    """(Zeilen [(id, name, bytes)], Audio [(id, name, bytes)], Meldungen)."""
    import json
    roh = []
    for q in quellen:
        text = sys.stdin.read() if q == "-" else Path(q).read_text()
        roh += _dateien(json.loads(text))
    zeilen, audio, msg, ids, stems = [], [], [], set(), {}        # stems: Dateistamm -> (Bytes, ID)
    zaehler = dict(ordner=0, google=0, sonst=0, foto=0)
    unterordner = []                                              # (ID, Name): werden nicht durchsucht
    for f in roh:
        fid, name = str(f["id"]), f.get("title") or f.get("name")
        a = art(f)
        try:
            n = int(f.get("fileSize") or f.get("size") or 0)
        except ValueError:
            n = 0
        if fid in ids:
            continue
        ids.add(fid)
        if a == "audio":
            audio.append((fid, name, n))
            continue
        if a in zaehler and not (a == "foto" and fotos):
            zaehler[a] += 1
            if a == "ordner":
                unterordner.append((fid, name))
            continue
        stamm, ext = os.path.splitext(name)
        if stamm in stems:
            if stems[stamm][0] == n and n:
                msg.append((INFO, f"Duplikat nicht aufgenommen: {name} ({fid}), gleicher Name und Größe wie {stems[stamm][1]}; "
                                  f"bei Zweifel MD5 beider Kopien vergleichen"))
                continue
            neu = f"{stamm}~{fid[:6]}{ext}"
            msg.append((WARN, f"Name doppelt mit anderer Größe: {name} ({fid}) heißt jetzt {neu}"))
            name, stamm = neu, os.path.splitext(neu)[0]
        stems[stamm] = (n, fid)
        if n <= 0:
            msg.append((WARN, f"{name}: Größe fehlt, Download wird nur auf Fehlerseite und Dateikopf geprüft"))
        zeilen.append((fid, name, n))
    zeilen.sort(key=lambda z: z[1])
    kopf = f"{len(zeilen)} Clips" + (" (mit Fotos)" if fotos else "")
    name_von = dict(ordner="Ordner", google="Google-Dokument(e)", sonst="sonstige Datei(en)", foto="Foto(s), mit --fotos")
    rest = ", ".join(f"{v} {name_von[k]}" for k, v in zaehler.items() if v)
    msg.insert(0, (INFO, kopf + (f", nicht aufgenommen: {rest}" if rest else "")
                   + (f", Audio: {len(audio)}" if audio else "")))
    msg[1:1] = [(INFO, f"Unterordner nicht durchsucht: {(n or '').strip()} ({i}), eigene Suche mit parentId = '{i}'")
                for i, n in unterordner]
    return zeilen, audio, msg


# ---------------------------------------------------------------- Manifest prüfen

def pruefen(pfad=None, online=False):
    """Zeilen (Status, Text) zur manifest.tsv."""
    if pfad is None:
        from reelcfg import WORK
        pfad = WORK / "manifest.tsv"
    pfad = Path(pfad)
    if not pfad.exists():
        return [(FAIL, f"{pfad} fehlt: erst manifest bauen (drive.py manifest …)")]
    out, eintraege = [], []
    for nr, zeile in enumerate(open(pfad), 1):
        if not zeile.strip():
            continue
        t = zeile.rstrip("\n").split("\t")
        if len(t) < 3 or not t[0].strip() or not t[1].strip():
            out.append((FAIL, f"Zeile {nr}: erwartet <id>\\t<name>\\t<bytes>, steht: {zeile.strip()[:60]!r}"))
            continue
        try:
            n = int(t[2])
        except ValueError:
            out.append((FAIL, f"Zeile {nr}: Größe {t[2]!r} ist keine Zahl"))
            continue
        eintraege.append((nr, t[0].strip(), t[1].strip(), n))
    if not eintraege:
        return out + [(FAIL, "keine Clips im Manifest")]
    for titel, schluessel in (("ID", lambda e: e[1]), ("Dateistamm", lambda e: os.path.splitext(e[2])[0])):
        seen = {}
        for e in eintraege:
            seen.setdefault(schluessel(e), []).append(e)
        dopp = {k: v for k, v in seen.items() if len(v) > 1}
        for k, v in dopp.items():
            out.append((FAIL, f"{titel} doppelt: {k} in Zeile {', '.join(str(e[0]) for e in v)} "
                              f"(reelcfg.manifest() behält nur den letzten)"))
        if not dopp:
            out.append((OK, f"{titel} eindeutig ({len(eintraege)} Zeilen)"))
    fremd = [e[2] for e in eintraege if not e[2].lower().endswith(VIDEO_EXT + FOTO_EXT)]
    if fremd:
        out.append((WARN, f"Endung unbekannt: {', '.join(fremd[:5])}" + (" …" if len(fremd) > 5 else "")))
    fotos = [e[2] for e in eintraege if e[2].lower().endswith(FOTO_EXT)]
    if fotos:
        out.append((INFO, f"{len(fotos)} Foto(s) im Manifest (nur auf Wunsch des Nutzers)"))
    ohne = [e[2] for e in eintraege if e[3] <= 0 and not e[1].startswith("local:")]
    if ohne:
        out.append((WARN, f"Größe 0 oder fehlt bei {len(ohne)} Clip(s), z. B. {ohne[0]}: kein Größenvergleich möglich"))
    fehlt = [e[1] for e in eintraege if e[1].startswith("local:") and not Path(e[1][6:]).exists()]
    if fehlt:
        out.append((FAIL, f"lokale Datei fehlt: {fehlt[0]}"))
    if online:
        echte = [e for e in eintraege if not e[1].startswith("local:")]
        with cf.ThreadPoolExecutor(8) as ex:
            antworten = list(ex.map(lambda e: abfrage(e[1]), echte))
        schlecht = 0
        for e, q in zip(echte, antworten):
            if q["status"] not in (200, 206) or q["typ"] == "text/html":
                schlecht += 1
                out.append((FAIL, f"{e[2]} ({e[1]}): HTTP {q['status']} {q['typ'] or q['fehler']}; "
                                  f"ID falsch, nicht freigegeben oder Drive gestört"))
            elif e[3] > 0 and q["gesamt"] and q["gesamt"] != e[3]:
                schlecht += 1
                out.append((FAIL, f"{e[2]}: Drive meldet {q['gesamt']} Bytes, Manifest {e[3]}"))
        if not schlecht:
            out.append((OK, f"alle {len(echte)} IDs bei Drive erreichbar, Größen stimmen"))
    return out


def ausgeben(zeilen):
    for s, t in zeilen:
        print(f"{s:<8s}{t}")
    f = sum(s == FAIL for s, _ in zeilen)
    w = sum(s == WARN for s, _ in zeilen)
    print("Ergebnis: " + ("alles OK" if not f and not w else f"{f} Fehler, {w} Warnung(en)"))
    return not f


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        sys.exit(__doc__)

    def opt(name, standard=None):
        return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else standard

    pos = [x for i, x in enumerate(a[1:], 1) if (x == "-" or not x.startswith("-")) and a[i - 1] not in ("-o", "--groesse")]
    if a[0] == "manifest":
        if not pos:
            sys.exit(__doc__)
        from reelcfg import WORK
        zeilen, audio, msg = manifest_bauen(pos, "--fotos" in a)
        ziel = Path(opt("-o", WORK / "manifest.tsv"))
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text("".join(f"{i}\t{n}\t{b}\n" for i, n, b in zeilen))
        ausgeben(msg)
        for fid, name, n in audio:
            print(f"Audio   {fid}\t{name}\t{n}")
        print(f"-> {ziel}")
    elif a[0] == "holen":
        if len(pos) < 2:
            sys.exit(__doc__)
        ok, grund = laden(pos[0], pos[1], int(opt("--groesse", 0)))
        if ok:
            n = Path(pos[1]).stat().st_size
            print(f"OK      {pos[1]}: {n} Bytes, " + (grund if grund.startswith("schon") else
                                                   f"Größe gegen Drive geprüft {grund}".strip()))
        else:
            print(f"{FAIL:<8s}{pos[1]}: {grund}")
        sys.exit(0 if ok else 1)
    elif a[0] == "pruefen":
        sys.exit(0 if ausgeben(pruefen(pos[0] if pos else None, "--online" in a)) else 1)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
