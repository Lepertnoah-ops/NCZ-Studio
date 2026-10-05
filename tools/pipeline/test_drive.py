#!/usr/bin/env python3
"""Test von drive.py ohne Drive (~10 s): lokaler Testserver statt drive.usercontent.google.com.

    python3 /mnt/project-files/tools/pipeline/test_drive.py

Der Server spielt die Fälle nach, die beim Laden aus Drive vorkamen oder vorkommen können: Datei mit Range-
Unterstützung, Server ohne Range, HTML-Fehlerseiten (Downloadlimit, Anmeldeseite, 404, 500), abgebrochene Übertragung
(muss per Range fortgesetzt werden), Datei mit falschem Kopf, winzige Antwort ohne Größenangabe. Dazu Manifest bauen
(Duplikate, Namensgleichheit, Ordner, Audio) und Manifest prüfen (offline und online). Fasst nichts im Projekt an.
"""
import hashlib
import http.server
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"   # Testserver nie über den Proxy
sys.path.insert(0, str(Path(__file__).resolve().parent))
import drive

GROSS = b"\x00\x00\x00\x18ftypmp42" + hashlib.sha256(b"studio").digest() * 90_000        # ~2,9 MB, Kopf wie MP4
TREFFER = {}          # id -> Liste (Range-Kopf oder None)


class Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):      # curl bricht bei --max-filesize ab: kein Traceback im Test
        pass


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def antwort(self, code, body, typ, extra=()):
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        fid = re.search(r"id=([^&]+)", self.path).group(1)
        rng = self.headers.get("Range")
        TREFFER.setdefault(fid, []).append(rng)
        html = lambda t, code=200: self.antwort(code, f"<!DOCTYPE html><html><title>x</title>{t}</html>".encode(),
                                                "text/html; charset=utf-8")
        if fid == "html_quota":
            return html("Sorry, you can't view or download this file at this time. Quota exceeded")
        if fid == "html_login":
            return html('<a href="https://accounts.google.com/ServiceLogin">Sign in</a>')
        if fid == "notfound":
            return html("Error 404 (Not Found)!!1", 404)
        if fid == "err500":
            return html("Error 500 (Server Error)!!1", 500)
        if fid == "unbekannt":                                  # keine Größenangabe (wie bei chunked-Antworten)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"\x02" * 100)
            self.close_connection = True
            return
        inhalt = {"kaputt": b"\x01" * 5000, "klein": b"\x02" * 100}.get(fid, GROSS)
        typ = "video/quicktime" if fid in ("ok", "norange", "abbruch", "kaputt") else "application/octet-stream"
        m = re.match(r"bytes=(\d+)-(\d*)$", rng or "")
        if m and fid != "norange":
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else len(inhalt) - 1
            if a >= len(inhalt):
                return self.antwort(416, b"", "text/plain", [("Content-Range", f"bytes */{len(inhalt)}")])
            return self.antwort(206, inhalt[a:b + 1], typ, [("Content-Range", f"bytes {a}-{b}/{len(inhalt)}")])
        if fid == "abbruch" and sum(1 for r in TREFFER[fid] if r is None) == 1:      # 1. Vollabruf: nach der Hälfte Ende
            self.send_response(200)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(len(inhalt)))
            self.end_headers()
            self.wfile.write(inhalt[:len(inhalt) // 2])
            self.wfile.flush()
            self.close_connection = True
            return
        self.antwort(200, inhalt, typ)


def md5(b):
    return hashlib.md5(b).hexdigest()


def main():
    drive.PAUSE = 0.01
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    drive.URL = f"http://127.0.0.1:{srv.server_address[1]}/get?id={{id}}"
    tmp = Path(tempfile.mkdtemp(prefix="testdrive_"))
    n = len(GROSS)

    def laden(fid, name="x.MOV", size=0):
        TREFFER.pop(fid, None)
        ok, g = drive.laden(fid, tmp / name, size)
        assert not list(tmp.glob("*.part")), "Teildatei blieb liegen"
        return ok, g

    ok, g = laden("ok", "a.MOV", n)
    assert ok and md5((tmp / "a.MOV").read_bytes()) == md5(GROSS) and not g, (ok, g)
    ok, g = laden("ok", "b.MOV", 0)
    assert ok and (tmp / "b.MOV").stat().st_size == n, (ok, g)
    ok, g = laden("ok", "c.MOV", 12345)
    assert ok and "Drive gilt" in g and (tmp / "c.MOV").stat().st_size == n, (ok, g)
    ok, g = laden("norange", "d.MOV", n)
    assert ok and md5((tmp / "d.MOV").read_bytes()) == md5(GROSS), (ok, g)
    print("OK   drive.laden: Größe aus Manifest, ohne Manifest-Größe, falsche Manifest-Größe, Server ohne Range")

    (tmp / "e.MOV").write_bytes(b"alte fehlerseite")
    ok, g = laden("ok", "e.MOV", n)
    assert ok and (tmp / "e.MOV").stat().st_size == n
    ok, g = laden("ok", "e.MOV", n)
    assert ok and g.startswith("schon vorhanden") and len(TREFFER.get("ok", [])) == 0
    print("OK   drive.laden: alte Fehlerdatei ersetzt, vorhandene Datei mit richtiger Größe nicht neu geladen")

    ok, g = laden("abbruch", "f.MOV", n)
    assert ok and md5((tmp / "f.MOV").read_bytes()) == md5(GROSS), (ok, g)
    assert any(r and not r.startswith("bytes=0-") for r in TREFFER["abbruch"]), TREFFER["abbruch"]
    print("OK   drive.laden: abgebrochene Übertragung per Range fortgesetzt, Datei identisch")

    for fid, wort in (("html_quota", "Downloadlimit"), ("html_login", "nicht freigegeben")):
        ok, g = laden(fid, "g.MOV", n)
        assert not ok and wort in g and not (tmp / "g.MOV").exists(), (fid, ok, g)
    ok, g = laden("notfound", "h.MOV", n)
    assert not ok and "HTTP 404" in g and len(TREFFER["notfound"]) <= 2, (g, TREFFER)
    ok, g = laden("err500", "i.MOV", n)
    assert not ok and "HTTP 500" in g and "Serverfehler" in g and len(TREFFER["err500"]) >= 3, (g, TREFFER)
    print("OK   drive.laden: Downloadlimit, Anmeldeseite, 404 (sofort), 500 (3 Versuche) mit klarer Meldung, nichts liegt herum")

    ok, g = laden("kaputt", "j.MOV", 5000)
    assert not ok and "Dateikopf" in g and not (tmp / "j.MOV").exists(), (ok, g)
    ok, g = laden("unbekannt", "k.bin", 0)
    assert not ok and "100 Bytes" in g, (ok, g)
    ok, g = laden("klein", "k.bin", 0)                     # Größe kommt per Range (100) und stimmt: gültig
    assert ok, (ok, g)
    ok, g = laden("local:" + str(tmp / "a.MOV"), "l.MOV", 0)
    assert ok and (tmp / "l.MOV").is_symlink() and (tmp / "l.MOV").stat().st_size == n
    print("OK   drive.laden: falscher Dateikopf, winzige Antwort ohne Größenangabe, lokale Datei als Verknüpfung")

    # ---- Manifest bauen
    def f(fid, name, size, mt="video/quicktime"):
        return dict(id=fid, title=name, mimeType=mt, fileSize=str(size), parentId="ORDNER")

    seite1 = dict(files=[f("A1aaaa", "IMG_1000.MOV", 100), f("A1aaaa", "IMG_1000.MOV", 100), f("B2bbbb", "IMG_1001.MOV", 200),
                         f("C3cccc", "IMG_1001.MOV", 200), f("D4dddd", "IMG_1000.MOV", 300)], nextPageToken="x")
    seite2 = [dict(type="text", text=json.dumps(dict(files=[
        f("F5eeee", "Rohmaterial", 0, "application/vnd.google-apps.folder"), f("G6ffff", "Notizen", 0, "application/vnd.google-apps.document"),
        f("H7gggg", "IMG_2000.HEIC", 900, "image/heic"), f("I8hhhh", "song.mp3", 5000, "audio/mpeg"),
        f("J9iiii", "notiz.txt", 10, "text/plain")])))]
    (tmp / "s1.json").write_text(json.dumps(seite1))
    (tmp / "s2.json").write_text(json.dumps(seite2))
    zeilen, audio, msg = drive.manifest_bauen([tmp / "s1.json", tmp / "s2.json"])
    namen = [z[1] for z in zeilen]
    assert namen == ["IMG_1000.MOV", "IMG_1000~D4dddd.MOV", "IMG_1001.MOV"], namen
    assert audio == [("I8hhhh", "song.mp3", 5000)], audio
    texte = " | ".join(t for _, t in msg)
    assert "Duplikat nicht aufgenommen: IMG_1001.MOV (C3cccc)" in texte and "heißt jetzt IMG_1000~D4dddd.MOV" in texte, texte
    assert "3 Clips, nicht aufgenommen: 1 Ordner, 1 Google-Dokument(e), 1 sonstige Datei(en), 1 Foto(s), mit --fotos, Audio: 1" in texte, texte
    assert "Unterordner nicht durchsucht: Rohmaterial (F5eeee), eigene Suche mit parentId = 'F5eeee'" in texte, texte
    zeilen2, _, _ = drive.manifest_bauen([tmp / "s1.json", tmp / "s2.json"], fotos=True)
    assert "IMG_2000.HEIC" in [z[1] for z in zeilen2]
    print("OK   drive.manifest_bauen: ID-Duplikat, Name+Größe-Duplikat, Namenskonflikt, Ordner, Dokument, Foto, Audio, Textblöcke")

    # ---- Manifest prüfen
    def manifest(*zeilen):
        p = tmp / "manifest.tsv"
        p.write_text("".join(z + "\n" for z in zeilen))
        return p

    def status(zeilen):
        return {s for s, _ in zeilen}

    gut = manifest(f"ok\tIMG_1.MOV\t{n}", f"norange\tIMG_2.MOV\t{n}")
    z = drive.pruefen(gut)
    assert drive.FAIL not in status(z) and drive.WARN not in status(z), z
    z = drive.pruefen(gut, online=True)
    assert drive.FAIL not in status(z) and any("alle 2 IDs" in t for _, t in z), z
    z = drive.pruefen(manifest(f"ok\tIMG_1.MOV\t{n}", f"ok\tIMG_2.MOV\t{n}"))
    assert any(s == drive.FAIL and "ID doppelt" in t for s, t in z), z
    z = drive.pruefen(manifest(f"ok\tIMG_1.MOV\t{n}", f"norange\tIMG_1.mp4\t{n}"))
    assert any(s == drive.FAIL and "Dateistamm doppelt" in t for s, t in z), z
    z = drive.pruefen(manifest("ok\tIMG_1.MOV", "ok2\tIMG_2.MOV\tviel"))
    assert any("Zeile 1: erwartet" in x for _, x in z) and any("Zeile 2: Größe 'viel'" in x for _, x in z), z
    z = drive.pruefen(manifest(f"ok\tIMG_1.MOV\t{n}", f"err500\tIMG_2.MOV\t{n}", f"norange\tIMG_3.MOV\t999"), online=True)
    tx = [t for s, t in z if s == drive.FAIL]
    assert any("IMG_2.MOV" in t and "HTTP 500" in t for t in tx) and any("IMG_3.MOV: Drive meldet" in t for t in tx), z
    z = drive.pruefen(manifest(f"ok\tIMG_1.MOV\t0", f"x\tnotiz.txt\t5", f"y\tfoto.HEIC\t7"))
    assert drive.WARN in status(z) and any("Foto" in t for _, t in z), z
    print("OK   drive.pruefen: Format, doppelte ID und Dateistämme, Größe fehlt, Fotos, online (Erreichbarkeit, Größe)")

    # ---- Kommandozeile
    import subprocess
    r = subprocess.run([sys.executable, str(Path(drive.__file__)), "manifest", str(tmp / "s1.json"), "-o", str(tmp / "m2.tsv")],
                       capture_output=True, text=True, env=dict(os.environ, REEL_WORK=str(tmp / "w")))
    assert r.returncode == 0 and (tmp / "m2.tsv").read_text().count("\n") == 3, r.stdout + r.stderr
    gut = manifest(f"ok\tIMG_1.MOV\t{n}", f"norange\tIMG_2.MOV\t{n}")
    r = subprocess.run([sys.executable, str(Path(drive.__file__)), "pruefen", str(gut)], capture_output=True, text=True)
    assert r.returncode == 0 and "Ergebnis: alles OK" in r.stdout, r.stdout + r.stderr
    print("OK   drive.py Kommandozeile: manifest, pruefen")
    print("test_drive: alles OK")


if __name__ == "__main__":
    main()
