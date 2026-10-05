#!/usr/bin/env python3
"""Plattform-Profile für Lieferdateien: Instagram Reels und YouTube Shorts.

Der Schnitt ist für beide Plattformen derselbe (Stil-Leitfaden; bis der Nutzer etwas anderes sagt).
Anders ist nur, was die Plattform braucht: Export-Einstellungen, Lautheit und True Peak, Grenzen, Safe Zones und die
Hinweise zur Lieferung. Alle Zahlen stehen in PROFILE; export.py, varianten.py und interview.py lesen sie von hier.

    python3 plattform.py show [instagram|youtube]                     # Profil und Lieferhinweise
    python3 plattform.py check <video.mp4> [--plattform youtube] [--titel-sekunde S] [--streng]
    python3 plattform.py ui <video.mp4|bild> [--plattform youtube] [--zeiten 3,20,40] [-o out.jpg]
    python3 plattform.py umwandeln <name_mit_song.mp4> [--nach youtube] [-o out.mp4]

check     Lieferdatei prüfen: Format (1080×1920, 30 fps konstant, H.264 High, yuv420p, bt709, Faststart), Länge,
          Ton (AAC, Lautheit, True Peak) gegen das Profil, dazu Hinweise (Song-Rechte). Exit-Code 1 bei FEHLER.
ui        Bilder mit eingezeichneten Safe Zones der Plattform (Titelzeile, Beschriftung, Buttons), höchstens ~1,1 MP,
          nach $REEL_WORK/ansicht/ui_<plattform>.jpg: Text und Logo dürfen nicht in die roten Bänder ragen.
umwandeln Aus einer gelieferten Instagram-Datei die Fassung für die andere Plattform: Video per Stream-Copy, Ton auf
          das Ziel der Plattform (YouTube: −14 LUFS, True Peak höchstens −1 dBTP, AAC 384k). Eingebrannte Texte
          (z. B. „LINK IN BIO“ im Abspann) bleiben: Interview-Reels dafür mit interview.py --plattform neu bauen.

YouTube-Zahlen (Stand 29.09.2026, aus Web-Recherche; support.google.com war im Container gesperrt, deshalb nicht am
Originaltext der YouTube-Hilfe geprüft): Short = hochkant oder quadratisch und höchstens 3 Minuten (seit 15.10.2024);
Empfehlung 1080×1920, H.264 High, 2 B-Frames, geschlossene GOP mit halber Bildrate, 8 Mbit/s bei 1080p30, AAC-LC 48 kHz
Stereo 384 kbit/s, bt709, Moov-Atom vorn. Lautheit: YouTube regelt lautere Dateien Richtung −14 LUFS herunter und hebt
leisere nicht an; True Peak unter −1 dBTP vermeidet Übersteuern beim erneuten Encode. Safe Zones (Web-Vorlagen):
oben ~180 px, unten ~390 px, rechts ~120 px, links ~60 px. Links in der Beschreibung eines Shorts sind nicht klickbar.
Die Instagram-Zahlen stehen in den Projektanweisungen (Punkt 15, 16) und in Stil-Leitfaden Abschnitt 9 (Checkliste).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner
TOOLS = Path(__file__).resolve().parent.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))          # reel_audio, ansicht
WORK = Path(os.environ.get("REEL_WORK", "/home/user/reel"))
OK, WARN, FAIL, INFO = "OK", "WARNUNG", "FEHLER", "INFO"

PROFILE = {
    "instagram": dict(
        name="Instagram Reels", kurz="instagram", suffix="", w=1080, h=1920, fps=30,
        # Projektanweisungen Punkt 15: 2 Pässe, leichtes Schärfen (Instagram macht sonst weiche Kanten), 18/25 Mbit/s
        video=dict(bitrate="18M", maxrate="25M", bufsize="50M", gop=60, bframes=3, preset="slow", tune="film",
                   level="4.1", schaerfe=0.4, mbit=(8, 25)),
        # ziel_lufs None: der Song-Pegel bleibt (Limiter-Decke −0,3 dBTP, Projektanweisungen Punkt 16)
        audio=dict(bitrate="320k", ziel_lufs=None, lufs_bereich=(-16.0, -6.0), tp_max=-0.3, tp_puffer=0.0),
        dauer=(None, None),
        zonen=dict(oben=0.10, unten=0.20, rechts=0.10, links=0.06),     # Projektanweisungen Abschnitt 3
        text_breite=0.84,          # Anteil der Bildbreite für mittig gesetzten Text (Untertitel, Abspann)
        link_zeile="LINK IN BIO",
        raster_34=True,            # das Profilraster zeigt die Mitte im 3:4-Ausschnitt (1080×1440)
    ),
    "youtube": dict(
        name="YouTube Shorts", kurz="youtube", suffix="_yt", w=1080, h=1920, fps=30,
        # YouTube kodiert neu: ab der Empfehlung (8 Mbit/s bei 1080p30) bringt mehr wenig; 12 Mbit/s lässt Reserve für
        # Schärfe und Bewegung. Kein Vorschärfen (YouTube behält Details), Empfehlung: GOP = halbe Bildrate, 2 B-Frames.
        video=dict(bitrate="12M", maxrate="16M", bufsize="32M", gop=15, bframes=2, preset="slow", tune="film",
                   level="4.1", schaerfe=None, mbit=(8, 30)),
        # YouTube senkt lautere Dateien auf etwa −14 LUFS und hebt leisere nicht an; −1 dBTP gegen Übersteuern nach dem
        # AAC-Encode (tp_puffer: der Encode überschwingt um etwa 0,15 dB)
        audio=dict(bitrate="384k", ziel_lufs=-14.0, lufs_bereich=(-15.0, -13.0), tp_max=-1.0, tp_puffer=0.25),
        dauer=(None, 180.0),       # Shorts bis 3 Minuten
        zonen=dict(oben=0.10, unten=0.21, rechts=0.115, links=0.06),
        text_breite=0.77,          # 1 − 2 × rechts: mittiger Text bleibt links von der Button-Spalte
        link_zeile=None,           # kein „Link in Bio“ auf YouTube (Links in Shorts sind nicht klickbar): Zeile weglassen
        raster_34=False,
    ),
}
ALIAS = {"instagram": "instagram", "ig": "instagram", "insta": "instagram", "reels": "instagram",
         "youtube": "youtube", "yt": "youtube", "shorts": "youtube"}

HINWEISE = {
    "instagram": [
        "Datei unverändert aufs Handy (Download aus Claude, Drive oder AirDrop, nicht WhatsApp).",
        "In Instagram „In höchster Qualität hochladen“ an, Upload über WLAN, keine Filter, kein Zuschneiden, keine Effekte.",
        "Eigenes Titelbild, Motiv im mittleren 1080×1440-Bereich.",
        "Stumme Version: Song in der Instagram-Musikbibliothek am Start des Ausschnitts ansetzen.",
        "Ordnerfreigabe wieder auf „Eingeschränkt“.",
    ],
    "youtube": [
        "Datei unverändert aufs Handy (Download aus Claude, Drive oder AirDrop, nicht WhatsApp).",
        "YouTube-App: + → Video hochladen → Datei wählen. Hochkant und höchstens 3 Minuten wird automatisch ein Short.",
        "Der Titel ist Pflicht (höchstens 100 Zeichen). Links in der Beschreibung eines Shorts sind nicht klickbar, "
        "Links gehören in das Kanalprofil.",
        "Titelbild: in der App im Bildwähler ein Bild aus dem Video wählen (die Sekunde nennt die Lieferung); "
        "ein eigenes Bild lässt sich nur am Computer in YouTube Studio hochladen, und nur für Kanäle mit Zugang.",
        "Song: Ist ein Song im Ton, prüft YouTube die Musikrechte (Content ID) und kann stumm schalten, sperren oder "
        "Einnahmen beanspruchen. Sicher ist die stumme Version: hochladen und den Sound in der App aus der YouTube-"
        "Bibliothek dazulegen. Das gilt auch für Musik aus einer Box, die im Clip-Ton hörbar ist.",
        "Ordnerfreigabe wieder auf „Eingeschränkt“.",
    ],
}


def profil(name="instagram"):
    k = ALIAS.get(str(name).strip().lower())
    if k is None:
        raise SystemExit(f"Unbekannte Plattform {name!r}; möglich: instagram (ig), youtube (yt, shorts)")
    return PROFILE[k]


def plattformen(text):
    """„instagram,youtube“ -> Liste von Profilen (Reihenfolge bleibt, ohne Doppelte)."""
    out = []
    for n in str(text).split(","):
        if n.strip() and profil(n) not in out:
            out.append(profil(n))
    return out


def dateiname(base, p, art):
    """<base>[_yt]_<art> mit art z. B. „mit_song.mp4“, „ohne_ton.mp4“, „titelbild.jpg“."""
    return f"{base}{p['suffix']}_{art}"


def zonen_px(p):
    z = p["zonen"]
    return dict(oben=round(z["oben"] * p["h"]), unten=round(z["unten"] * p["h"]),
                rechts=round(z["rechts"] * p["w"]), links=round(z["links"] * p["w"]))


# ---------------------------------------------------------------- Export

def vf_kette(p):
    s = p["video"]["schaerfe"]
    return (f"unsharp=5:5:{s}:5:5:0," if s else "") + ("scale=flags=lanczos+accurate_rnd+full_chroma_int:"
                                                        "out_color_matrix=bt709:out_range=tv,format=yuv420p")


def x264_args(p):
    v = p["video"]
    return ["-c:v", "libx264", "-preset", v["preset"], "-tune", v["tune"], "-profile:v", "high", "-level", v["level"],
            "-b:v", v["bitrate"], "-maxrate", v["maxrate"], "-bufsize", v["bufsize"], "-g", str(v["gop"]),
            "-bf", str(v["bframes"]), "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]


def video_export(master, out, p):
    """Master (yuv444p, crf 1) -> Lieferdatei in 2 Pässen ohne Ton, Einstellungen aus dem Profil."""
    with tempfile.TemporaryDirectory() as d:
        common = ["-vf", vf_kette(p), *x264_args(p), "-passlogfile", f"{d}/x264"]
        for n, tail in (("1", ["-an", "-f", "null", "-"]), ("2", ["-an", "-movflags", "+faststart", str(out)])):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(master), *common, "-pass", n, *tail], check=True)


def audio_normalisieren(x, p, ra):
    """Mix (float, n × 2) auf das Lautheitsziel des Profils bringen, True Peak höchstens tp_max − tp_puffer.
    Ohne ziel_lufs (Instagram) bleibt der Mix, wie er ist. Der Limiter senkt die Lautheit leicht: Pegel nachziehen."""
    a = p["audio"]
    z = a["ziel_lufs"]
    if z is None:
        return x
    decke = a["tp_max"] - a.get("tp_puffer", 0.0)
    y = x * 10 ** ((z - ra.lufs(x)) / 20)
    for _ in range(4):
        y = ra.limit(y, decke)[0]
        d = z - ra.lufs(y)
        if abs(d) <= 0.15:
            break
        y = y * 10 ** (d / 20)
    return ra.limit(y, decke)[0]


def mux(video, wav, out, p):
    """Video per Stream-Copy plus Ton als AAC. Kein -shortest: bei Stream-Copy schneidet es die letzten Bilder ab."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", p["audio"]["bitrate"], "-ar", "48000",
                    "-movflags", "+faststart", str(out)], check=True)


def ton_fuer(mix_wav, p, ra=None):
    """Pfad einer WAV mit dem Pegel des Profils (bei Instagram die Originaldatei), sonst eine neue WAV neben dem Mix."""
    if p["audio"]["ziel_lufs"] is None:
        return Path(mix_wav)
    import numpy as np
    import soundfile as sf
    ra = ra or _ra()
    y = audio_normalisieren(ra.decode(str(mix_wav)), p, ra)
    out = Path(mix_wav).with_name(f"{Path(mix_wav).stem}{p['suffix']}.wav")
    sf.write(out, y.astype(np.float32), ra.SR, subtype="FLOAT")
    return out


def _ra():
    import reel_audio
    return reel_audio


def yt_name(name, p):
    """Interview_mit_song.mp4 -> Interview_yt_mit_song.mp4 (Suffix vor die Art, bei Instagram unverändert)."""
    if not p["suffix"]:
        return name
    m = re.fullmatch(r"(.*?)_(mit_song|ohne_song|ohne_ton|titelbild)(\.\w+)", name)
    if m:
        return f"{m.group(1)}{p['suffix']}_{m.group(2)}{m.group(3)}"
    s = Path(name)
    return f"{s.stem}{p['suffix']}{s.suffix}"


def umwandeln(quelle, p, out=None):
    """Gelieferte Datei für die Plattform p neu abmischen (Video unverändert). Stumme Dateien werden nur kopiert."""
    import numpy as np
    import soundfile as sf
    quelle = Path(quelle)
    ziel = Path(out) if out else quelle.with_name(yt_name(quelle.name, p))
    if ziel.resolve() == quelle.resolve():
        raise SystemExit(f"{ziel}: Ziel ist die Quelle (Instagram-Datei? --nach youtube angeben)")
    if p["audio"]["ziel_lufs"] is None:
        raise SystemExit(f"{p['name']}: kein Lautheitsziel, nichts umzuwandeln")
    pr = _ffprobe(quelle)
    if not any(s["codec_type"] == "audio" for s in pr["streams"]):
        shutil.copy2(quelle, ziel)
        return ziel
    ra = _ra()
    with tempfile.TemporaryDirectory() as d:
        y = audio_normalisieren(ra.decode(str(quelle)), p, ra)
        wav = Path(d) / "ton.wav"
        sf.write(wav, y.astype(np.float32), ra.SR, subtype="FLOAT")
        mux(quelle, wav, ziel, p)
    return ziel


# ---------------------------------------------------------------- Prüfung

def _ffprobe(datei):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(datei)],
                       capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        raise SystemExit(f"{datei}: ffprobe kann die Datei nicht lesen: {r.stderr.strip()[-200:]}")
    return json.loads(r.stdout)


def _pakete(datei):
    """Zeitstempel aller Videopakete (sortiert) und der Keyframes."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
                        "-of", "csv=p=0", str(datei)], capture_output=True, text=True)
    pts, key = [], []
    for z in r.stdout.splitlines():
        a = z.split(",")
        try:
            t = float(a[0])
        except (ValueError, IndexError):
            continue
        pts.append(t)
        if len(a) > 1 and "K" in a[1]:
            key.append(t)
    return sorted(pts), sorted(key)


def _lautheit(datei):
    r = subprocess.run(["ffmpeg", "-nostats", "-i", str(datei), "-af", "ebur128=peak=true:framelog=quiet", "-f", "null",
                        "-"], capture_output=True, text=True)
    i, tp = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", r.stderr), re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", r.stderr)
    f = lambda t: float(t[-1]) if t and t[-1] != "-inf" else None  # noqa: E731
    return f(i), f(tp)


def _atome(datei):
    """Reihenfolge der obersten Boxen der MP4-Datei (moov vor mdat = Faststart)."""
    order, total = [], os.path.getsize(datei)
    with open(datei, "rb") as f:
        pos = 0
        while pos < total and len(order) < 16:
            f.seek(pos)
            h = f.read(8)
            if len(h) < 8:
                break
            size, typ = int.from_bytes(h[:4], "big"), h[4:8].decode("latin1")
            if size == 1:
                size = int.from_bytes(f.read(8), "big")
            elif size == 0:
                size = total - pos
            order.append(typ)
            if size < 8:
                break
            pos += size
    return order


def pruefen(datei, p, titel_s=None, gesamt=None):
    """Lieferdatei gegen das Profil prüfen. Gibt die Zeilen (Status, Text) zurück, druckt sie nicht."""
    z = []
    add = lambda s, t: z.append((s, t))  # noqa: E731
    pr = _ffprobe(datei)
    v = next((s for s in pr["streams"] if s["codec_type"] == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in pr["streams"] if s["codec_type"] == "audio"), None)
    fmt = pr["format"]
    if v is None:
        add(FAIL, "keine Videospur")
        return z
    w, h = v["width"], v["height"]
    if (w, h) == (p["w"], p["h"]):
        add(OK, f"Auflösung {w}×{h}")
    elif w * 16 == h * 9:
        add(WARN, f"Auflösung {w}×{h} ist 9:16, Soll {p['w']}×{p['h']}")
    else:
        add(FAIL, f"Auflösung {w}×{h} ist nicht 9:16 (Soll {p['w']}×{p['h']}): wird kein Hochkant-Short/-Reel")
    add(OK if v.get("sample_aspect_ratio", "1:1") in ("1:1", "0:1", "N/A") else WARN,
        f"Pixel-Seitenverhältnis {v.get('sample_aspect_ratio', '1:1')}")
    if any(int(sd.get("rotation", 0)) % 360 for sd in v.get("side_data_list", [])):
        add(FAIL, "Drehung in den Metadaten: Player drehen das Bild")
    pts, key = _pakete(datei)
    fps = float(Fraction(v.get("r_frame_rate", "0/1")))
    dt = [b - c for b, c in zip(pts[1:], pts)]
    irr = sum(abs(x - 1 / p["fps"]) > 0.25 / p["fps"] for x in dt)
    add(OK if abs(fps - p["fps"]) < 0.01 and irr == 0 else FAIL,
        f"{fps:g} fps, {len(pts)} Bilder, unregelmäßige Abstände: {irr}" + ("" if irr == 0 else " (variable Bildrate)"))
    add(OK if v["codec_name"] == "h264" and v.get("profile") == "High" else WARN,
        f"Codec {v['codec_name']} {v.get('profile', '')}")
    add(OK if v.get("pix_fmt") == "yuv420p" else FAIL, f"Pixelformat {v.get('pix_fmt')}")
    farbe = [v.get("color_space"), v.get("color_transfer"), v.get("color_primaries")]
    add(OK if all(c == "bt709" for c in farbe) else WARN, "Farb-Tags " + "/".join(str(c) for c in farbe))
    add(OK if v.get("field_order", "progressive") in ("progressive", "unknown") else WARN,
        f"Halbbilder: {v.get('field_order', 'progressive')}")
    dv = float(v.get("duration") or fmt.get("duration") or 0)
    br = float(v.get("bit_rate") or 0) or os.path.getsize(datei) * 8 / max(dv, 1e-6)
    lo, hi = p["video"]["mbit"]
    add(OK if lo <= br / 1e6 <= hi else WARN, f"Video-Bitrate {br / 1e6:.1f} Mbit/s (Soll {lo}–{hi})")
    if len(key) > 1:
        gop = max(b - c for b, c in zip(key[1:], key))
        soll = p["video"]["gop"] / p["fps"]
        add(OK if gop <= soll * 1.5 else INFO, f"Keyframe-Abstand höchstens {gop:.2f} s (Empfehlung {soll:.2f} s, kein Muss)")
    order = _atome(datei)
    fs = "moov" in order and "mdat" in order and order.index("moov") < order.index("mdat")
    add(OK if fs else WARN, "Faststart (moov vor mdat)" if fs else "kein Faststart: " + " → ".join(order))
    if pr["format"].get("nb_streams", 0) > (2 if a else 1):
        add(WARN, f"{fmt['nb_streams']} Spuren in der Datei (Video und Ton genügen)")
    mx = p["dauer"][1]
    if mx and dv > mx:
        add(FAIL, f"Länge {dv:.1f} s über dem Höchstwert {mx:.0f} s")
    else:
        add(OK, f"Länge {dv:.2f} s" + (f" (Höchstwert {mx:.0f} s)" if mx else ""))
    if gesamt is not None:
        add(OK if abs(dv - gesamt) <= 0.1 else FAIL, f"Länge gegen Schnitt: Soll {gesamt:.2f} s, Ist {dv:.2f} s")
    if a is None:
        add(INFO, "kein Ton (stumme Version)")
    else:
        da = float(a.get("duration") or dv)
        dd = da - dv
        add(OK if abs(dd) <= 1.2 / p["fps"] else (WARN if abs(dd) <= 0.1 else FAIL),
            f"Ton {da:.3f} s gegen Bild {dv:.3f} s ({dd * 1000:+.0f} ms)")
        sr = int(a.get("sample_rate", 0))
        add(OK if a["codec_name"] == "aac" and sr == 48000 else WARN,
            f"Ton {a['codec_name']} {sr} Hz {a.get('channels')} Kanäle {float(a.get('bit_rate', 0)) / 1000:.0f} kbit/s")
        au = p["audio"]
        L, tp = _lautheit(datei)
        if L is None:
            add(WARN, "Lautheit nicht messbar (Ton stumm?)")
        elif au["ziel_lufs"] is not None:
            add(OK if abs(L - au["ziel_lufs"]) <= 0.7 else WARN,
                f"Lautheit {L:.1f} LUFS (Ziel {au['ziel_lufs']:.0f} ± 0,7)")
        else:
            add(INFO if au["lufs_bereich"][0] <= L <= au["lufs_bereich"][1] else WARN, f"Lautheit {L:.1f} LUFS")
        if tp is not None:
            add(OK if tp <= au["tp_max"] + 0.2 else (WARN if tp <= 0.0 else FAIL),
                f"True Peak {tp:.2f} dBTP (höchstens {au['tp_max']:.1f}, Toleranz 0,2)")
        if p["kurz"] == "youtube":
            add(INFO, "Song im Ton: YouTube prüft Musikrechte (Content ID) und kann stumm schalten, sperren oder "
                      "Einnahmen beanspruchen; sicher: stumme Version und Sound aus der YouTube-Bibliothek")
    if p["kurz"] == "youtube" and (w, h) == (p["w"], p["h"]) and (not mx or dv <= mx):
        add(INFO, "wird als Short erkannt (hochkant, höchstens 3 Minuten)")
    if titel_s is not None:
        add(INFO, f"Titelbild: im Bildwähler die Sekunde {titel_s:g} wählen" if p["kurz"] == "youtube"
            else f"Titelbild aus dem Video bei {titel_s:g} s")
    return z


def ausgeben(zeilen, streng=False):
    for s, t in zeilen:
        print(f"{s:<8s}{t}")
    f = sum(s == FAIL for s, _ in zeilen)
    w = sum(s == WARN for s, _ in zeilen)
    print("Ergebnis: " + ("alles OK" if not f and not w else f"{f} Fehler, {w} Warnung(en)"))
    return not (f or (streng and w))


# ---------------------------------------------------------------- UI-Vorschau

def ui_bild(quelle, p, zeiten=None, out=None):
    """Frames mit den Safe Zones der Plattform als rote Bänder; ein Bild, höchstens ~1,1 MP."""
    from io import BytesIO

    from PIL import Image, ImageDraw
    import ansicht
    quelle = Path(quelle)
    if quelle.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
        frames, texte = [Image.open(quelle).convert("RGB")], [quelle.name[:18]]
    else:
        d = ansicht.dauer(quelle)
        if isinstance(zeiten, str):
            zeiten = zeiten.split(",")
        zs = [float(x) for x in zeiten] if zeiten else [d * 0.15, d * 0.5, d * 0.85]
        frames, texte = [ansicht.frame(quelle, t, breite=p["w"] // 2).convert("RGB") for t in zs], [f"{t:.1f}s" for t in zs]
    zp = zonen_px(p)
    bilder = []
    for im in frames:
        im = im.resize((p["w"] // 2, p["h"] // 2), Image.LANCZOS)
        k = 0.5
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(ov)
        rot = (255, 40, 40, 95)
        dr.rectangle((0, 0, im.width, zp["oben"] * k), fill=rot)
        dr.rectangle((0, im.height - zp["unten"] * k, im.width, im.height), fill=rot)
        dr.rectangle((im.width - zp["rechts"] * k, zp["oben"] * k, im.width, im.height - zp["unten"] * k), fill=rot)
        dr.rectangle((0, zp["oben"] * k, zp["links"] * k, im.height - zp["unten"] * k), fill=(255, 190, 40, 70))
        if p["raster_34"]:
            for y in ((p["h"] - p["w"] * 4 / 3) / 2, (p["h"] + p["w"] * 4 / 3) / 2):
                dr.line((0, y * k, im.width, y * k), fill=(60, 160, 255, 230), width=2)
        f = ansicht.font(max(11, im.width // 22))
        dr.text((6, 4), "Titelzeile", font=f, fill=(255, 255, 255, 230))
        dr.text((6, im.height - zp["unten"] * k + 4), "Beschriftung, Kanal, Musik", font=f, fill=(255, 255, 255, 230))
        bilder.append(Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB"))
    r = ansicht.raster(bilder, texte)
    out = Path(out) if out else WORK / "ansicht" / f"ui_{p['kurz']}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    ansicht.passend(r).save(out, quality=88)
    return out


# ---------------------------------------------------------------- Kommandozeile

def zeigen(p):
    v, a, z = p["video"], p["audio"], zonen_px(p)
    print(f"{p['name']}  ({p['w']}×{p['h']}, {p['fps']} fps, Dateiendung {p['suffix'] or '(keine)'}_mit_song.mp4)")
    print(f"  Video  H.264 High {v['level']}, 2 Pässe, {v['bitrate']} (Spitze {v['maxrate']}), GOP {v['gop']}, "
          f"{v['bframes']} B-Frames, " + (f"Vorschärfen {v['schaerfe']}" if v["schaerfe"] else "kein Vorschärfen"))
    print(f"  Ton    AAC {a['bitrate']} 48 kHz, " + (f"Ziel {a['ziel_lufs']:.0f} LUFS" if a["ziel_lufs"] is not None
                                                      else "Songpegel bleibt") + f", True Peak höchstens {a['tp_max']:.1f} dBTP")
    print(f"  Länge  " + (f"höchstens {p['dauer'][1]:.0f} s" if p["dauer"][1] else "keine feste Grenze im Studio"))
    print(f"  Safe Zones  oben {z['oben']} px, unten {z['unten']} px, rechts {z['rechts']} px, links {z['links']} px; "
          f"mittiger Text höchstens {p['text_breite'] * 100:.0f} % der Breite")
    print(f"  Abspann-Link  {p['link_zeile'] or '(Zeile entfällt)'}")
    print("Lieferung:")
    for h in HINWEISE[p["kurz"]]:
        print("  - " + h)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("show")
    s.add_argument("plattform", nargs="?", default="instagram,youtube")
    s = sp.add_parser("check")
    s.add_argument("datei")
    s.add_argument("--plattform", default=None)
    s.add_argument("--titel-sekunde", type=float)
    s.add_argument("--streng", action="store_true")
    s = sp.add_parser("ui")
    s.add_argument("quelle")
    s.add_argument("--plattform", default="youtube")
    s.add_argument("--zeiten")
    s.add_argument("-o", "--out")
    s = sp.add_parser("umwandeln")
    s.add_argument("datei")
    s.add_argument("--nach", default="youtube")
    s.add_argument("-o", "--out")
    a = ap.parse_args()
    if a.cmd == "show":
        for p in plattformen(a.plattform):
            zeigen(p)
            print()
    elif a.cmd == "check":
        name = a.plattform or ("youtube" if "_yt" in Path(a.datei).name else "instagram")
        p = profil(name)
        print(f"{Path(a.datei).name} gegen {p['name']}")
        sys.exit(0 if ausgeben(pruefen(a.datei, p, a.titel_sekunde), a.streng) else 1)
    elif a.cmd == "ui":
        print(ui_bild(a.quelle, profil(a.plattform), a.zeiten, a.out))
    elif a.cmd == "umwandeln":
        p = profil(a.nach)
        ziel = umwandeln(a.datei, p, a.out)
        print(f"-> {ziel}")
        print("Hinweis: Eingebrannte Instagram-Texte (z. B. „LINK IN BIO“ im Abspann) bleiben; "
              "Interview-Reels für YouTube mit interview.py --plattform youtube neu bauen.")
        sys.exit(0 if ausgeben(pruefen(ziel, p)) else 1)


if __name__ == "__main__":
    main()
