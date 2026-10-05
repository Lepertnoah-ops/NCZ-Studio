"""Gemeinsame Pfade, Konstanten und Hilfen der Reel-Pipeline (tools/pipeline/).

Arbeitsordner im Container (groß, gehört nicht in den Projektordner): $REEL_WORK, Standard /home/user/reel
  manifest.tsv        Clip-Liste <id>\t<name>\t<bytes>: drive.py manifest <search_files-Ausgabe> baut sie, drive.py pruefen prüft sie.
                      id "local:<pfad>" nimmt eine Datei aus dem Container statt aus Drive (Tests, schon geladene Clips).
  meta/<stamm>.json, kf/<stamm>/k_*.jpg      aus ingest.py
  frames/<clip>/f_*.jpg + times.json         aus extract.py
  luts/                                      eigene Looks aus stil.json (vfx/looks.py backt sie bei Bedarf)
Schnittliste und Effekte: $REEL_EDL / $REEL_FX (Standard WORK/edl.json, WORK/fx.json).
Sie entstehen mit schnitt/edl.py im Reel-Ordner (Vorlage: reels/_vorlage/schnitt/edl.py).
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

WORK = Path(os.environ.get("REEL_WORK", "/home/user/reel"))
PIPE = Path(__file__).resolve().parent
TOOLS = PIPE.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))          # stil, reel_audio
W, H, FPS = 1080, 1920, 30
from stil import STIL  # noqa: E402  (stil.json im Projektordner)

TONEMAP = ("zscale=tin=arib-std-b67:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=100,format=gbrpf32le,"
           "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
TONEMAP_PQ = TONEMAP.replace("arib-std-b67", "smpte2084")


PHOTO_EXT = (".heic", ".heif", ".jpg", ".jpeg", ".png")
PHOTO_DUR = 60.0   # Fotos gelten als Standbild-"Clip" dieser Länge (Bewegung kommt aus push/punch in der fx.json)


def is_photo(name):
    return str(name).lower().endswith(PHOTO_EXT)


def _heif_opener():
    """pillow-heif für HEIC vom iPhone; fehlt es, einmal per pip nachinstallieren (braucht Netzwerkzugriff auf pypi)."""
    try:
        import pillow_heif
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--root-user-action=ignore",
                        "--break-system-packages", "pillow-heif==1.8.0"], check=True)
        import pillow_heif
    pillow_heif.register_heif_opener()


def load_photo(path):
    """Foto (HEIC, JPG, PNG) als RGB-PIL-Bild in sRGB, nach EXIF gedreht (iPhone-Fotos sind Display P3)."""
    import io
    from PIL import Image, ImageCms, ImageOps
    if str(path).lower().endswith((".heic", ".heif")):
        _heif_opener()
    im = Image.open(path)
    icc = im.info.get("icc_profile")
    im = ImageOps.exif_transpose(im).convert("RGB")
    if icc:
        try:
            im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                           ImageCms.createProfile("sRGB"), outputMode="RGB")
        except (ImageCms.PyCMSError, OSError):
            pass
    return im


def photo_time(path):
    """Aufnahmezeit aus EXIF im Format der Videos (2026-09-20T13:42:25+0200) oder None."""
    from PIL import Image
    if str(path).lower().endswith((".heic", ".heif")):
        _heif_opener()
    try:
        ex = Image.open(path).getexif()
        sub = ex.get_ifd(0x8769)
        t, off = sub.get(36867) or ex.get(306), sub.get(36881) or ""
        d, h = t.split(" ")
        return d.replace(":", "-") + "T" + h + off.replace(":", "")
    except Exception:
        return None


def look_spec():
    """Look aus stil.json; REEL_LOOK (Name, .cube-Pfad, JSON-Objekt oder "none") überschreibt ihn für einen Lauf."""
    x = os.environ.get("REEL_LOOK")
    if x is None:
        return STIL["look"]
    return json.loads(x) if x.strip().startswith("{") else (None if x in ("", "none", "keiner") else x)


def looks_module():
    if str(TOOLS / "vfx") not in sys.path:
        sys.path.insert(0, str(TOOLS / "vfx"))
    import looks
    return looks


def grade_rgb(rgb):
    """Look auf ein float-RGB-Bild (0..1) anwenden, wie ihn der Master bekommt (Storyboard, Vorschaubilder)."""
    return looks_module().apply_rgb(rgb, look_spec())


def tonemap_for(trc):
    """ffmpeg-Filterkette (mit Komma) für HDR-Quellen (HLG, PQ), bei SDR leer."""
    return {"arib-std-b67": TONEMAP + ",", "smpte2084": TONEMAP_PQ + ","}.get(trc or "", "")


def log(name, *a):
    WORK.mkdir(parents=True, exist_ok=True)
    with open(WORK / f"{name}.log", "a") as f:
        print(time.strftime("%H:%M:%S"), *a, file=f, flush=True)


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)


def edl_path():
    return Path(os.environ.get("REEL_EDL", WORK / "edl.json"))


def load_edl(path=None):
    return json.load(open(path or edl_path()))


def load_fx(E, path=None):
    """Effekt-Parameter je Shot-Nummer: fx.json neben der EDL bzw. $REEL_FX, sonst 'fxp' aus der EDL."""
    p = Path(path or os.environ.get("REEL_FX", edl_path().with_name("fx.json")))
    if p.exists():
        return json.load(open(p))
    return {str(s["n"]): s.get("fxp", {}) for s in E["shots"]}


def total_beats(E):
    return E.get("beats") or sum(s["beats"] for s in E["shots"])


def manifest():
    """Dateistamm -> (id, name, bytes) aus WORK/manifest.tsv. Ein doppelter Stamm überschreibt still den ersten Clip:
    darum die Warnung (drive.py pruefen nennt die Zeilen)."""
    out = {}
    for line in open(WORK / "manifest.tsv"):
        if line.strip():
            fid, name, size = line.rstrip("\n").split("\t")[:3]
            stamm = os.path.splitext(name)[0]
            if stamm in out and out[stamm][0] != fid:
                print(f"WARNUNG manifest.tsv: {stamm} kommt mit zwei IDs vor, die letzte gilt (drive.py pruefen)",
                      file=sys.stderr)
            out[stamm] = (fid, name, int(size))
    return out


def stem_of(clip, stems):
    """Clip-Kürzel aus der EDL ('3419' oder 'IMG_3419') -> Dateistamm."""
    if clip in stems:
        return clip
    if "IMG_" + clip in stems:
        return "IMG_" + clip
    hits = [s for s in stems if s.endswith(clip)]
    if len(hits) == 1:
        return hits[0]
    raise KeyError(f"Clip {clip!r} nicht eindeutig gefunden ({len(hits)} Treffer)")


def meta(clip):
    """meta/<stamm>.json aus ingest.py zu einem Clip-Kürzel."""
    stems = [p.stem for p in (WORK / "meta").glob("*.json")]
    return json.load(open(WORK / "meta" / f"{stem_of(clip, stems)}.json"))


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def download(fid, path, size, logname="download"):
    """Drive-Download über drive.usercontent.google.com (Ordner-Freigabe "Jeder mit dem Link"). Seit 29.09.2026 in
    drive.py: Größe per Range-Abfrage, HTML-Fehlerseiten und falscher Dateikopf gelten als Fehler (früher zählte bei
    size <= 0 jede Antwort als Erfolg), Fortsetzen abgebrochener Übertragungen, endgültige Fehler ohne Wartezeit.
    size <= 0 = Manifest kennt die Größe nicht. Grund eines Fehlschlags: $REEL_WORK/<logname>.log."""
    import drive
    return drive.holen(fid, path, size, logname)
