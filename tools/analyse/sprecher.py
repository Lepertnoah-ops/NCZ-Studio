#!/usr/bin/env python3
"""Sprecher trennen: wer spricht wann (sherpa-onnx auf der CPU, kein torch), seit 30.09.2026.

    cd /tmp && python3 sprecher.py <clip_oder_ton> [...] -o <ordner> [--transkript <ordner mit <stamm>.json>] [--sprecher N]
    cd /tmp && python3 sprecher.py --vorbereiten        # nur sherpa-onnx und Modelle bereitstellen

Für Interview-Clips mit mehreren Stimmen: die Person hinter der Kamera fragt (meist lauter), ein bis drei Gäste
antworten, oft wechselt es schon innerhalb eines Whisper-Segments. Das Werkzeug findet die Sprecherwechsel und gibt
jedem Wort einen Sprecher. Damit lassen sich Fragen und Antworten trennen, Dialoge schneiden und Untertitel je
Sprecher setzen.

Eingabe: ein Stamm (IMG_5315, dann $REEL_WORK/audio/<stamm>.flac aus pipeline/ingest.py) oder eine Datei (Ton oder
Video, ffmpeg macht 16 kHz Mono daraus). Ohne --sprecher wird die Zahl der Sprecher geschätzt.
Schreibt je Clip <ordner>/<stamm>.sprecher.json und eine gemeinsame <ordner>/sprecher.md zum Lesen (je Sprecherwechsel
eine Zeile: von–bis, Sprecher, Pegel, Text). Die JSON enthält:
  turns     [{von, bis, sprecher: "S1"}] (unsicher: true bei kurzen oder knappen Turns)
  sprecher  {S1: {redezeit_s, pegel_db (mittlerer RMS der Turns), tonhoehe_hz (Median), fragen (nur mit Transkript)}}
  hinweis   "Fragesteller wahrscheinlich S1 …" (lauter und/oder mehr Fragesätze), nur ein Hinweis, nie automatisch
  segmente  nur mit Transkript: Format wie transkript.py, Segmente an Sprecherwechseln geteilt, je Wort "sprecher"
            ("S1" oder "?" bei Wortgrenze, Überlappung oder unsicherem Turn, dann "vermutet" mit der besten Annahme)
Sprecher heißen nach dem ersten Auftritt S1, S2 … Die Nummer sagt nichts über die Rolle.

Import:
    import sprecher
    turns = sprecher.sprecher_turns("IMG_5315.flac", n=None)       # [{von, bis, sprecher}]
    neu = sprecher.woerter_zuordnen(transkript_dict, turns)        # Wörter mit Sprecher, Segmente geteilt

Verfahren: Die pyannote-Segmentierung (über onnxruntime, 1 s je Minute) liefert Sprache und gleichzeitiges Sprechen,
ohne onnxruntime sherpa-onnx OfflineSpeakerDiarization. Sprachabschnitte werden an hörbaren Pausen geteilt, darin 1-s-
Fenster mit dem Sprecher-Modell CAM++ (3D-Speaker, sherpa-onnx) eingebettet, gruppiert (Mittelwert-Verknüpfung auf dem
Kosinus-Abstand, Schwelle 0,7) und mit einer Viterbi-Glättung zu Turns gemacht; Wechsel ohne Pause rücken auf die leiseste
Stelle. Die Gruppierung von sherpa selbst taugt bei kurzen Antworten nicht (sie ordnete Fragen von 1 s den Gästen zu).
Modelle und Herkunft: modelle/sprecher/README.md. Laufzeit: etwa 0,3 × Echtzeit auf 4 Kernen.
Fehlt sherpa-onnx oder ein Modell, lädt das Werkzeug es beim ersten Aufruf selbst nach (pip, GitHub-Releases, Größe und
Prüfsumme). Geht das nicht, läuft ein deutlich schwächerer Ersatz (MFCC statt Sprecher-Modell), im Ergebnis als
"verfahren" vermerkt.

Grenzen: Antworten unter etwa 0,7 s ("Ja") und Überlappung sind unsicher, zwei Gäste mit ähnlicher Stimme werden
leicht zu einem, und ein Gast mit wechselnder Stimme (Rufen, Lachen) wird leicht zu zwei. Turns von unter 1,5 s ohne
Pause davor (harte Schnitte) sind schwach. Tonhöhe und Pegel beschreiben nur, sie entscheiden nichts. Wer fragt, sagt das
Werkzeug nur als Hinweis. --sprecher N nur setzen, wenn die Zahl sicher ist.
"""
import argparse
import contextlib
import copy
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner

HIER = Path(__file__).resolve().parent
MODELLE = HIER.parent / "modelle" / "sprecher"
SR = 16000
SHERPA_PIP = "sherpa-onnx==1.13.8"
_REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
SEG = dict(datei="segmentierung_pyannote_3.0.onnx", bytes=5992913,
           sha256="220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079",     # model.onnx aus dem Archiv
           archiv=_REL + "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
           archiv_bytes=6958444, archiv_sha256="24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
           inhalt="sherpa-onnx-pyannote-segmentation-3-0/model.onnx")
EMB = dict(datei="3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx", bytes=28281164,
           sha256="aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2",
           url=_REL + "speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx")

# Feineinstellung (an den Interview-Clips gemessen, Begründung in modelle/sprecher/README.md)
FENSTER = 1.0          # Länge der Einbettungsfenster in s
HOP = 0.125            # Schritt der Fenster in s
SCHWELLE = 0.7         # Kosinus-Abstand, ab dem zwei Gruppen verschiedene Sprecher sind (Mittelwert-Verknüpfung)
STRAFE = 0.3           # Viterbi: Kosten eines Sprecherwechsels (in Kosinus-Einheiten)
MIN_SPRECHER_S = 1.0   # Gruppen mit weniger Redezeit werden einer ähnlichen anderen zugeschlagen
AEHNLICH = 0.4         # Kosinus, ab dem eine kleine Gruppe als ähnlich genug gilt, um in einer anderen aufzugehen
MIN_SPRACHE = 0.25     # kürzere Sprachabschnitte zählen nicht
UNSICHER_MARGE = 0.08  # Turn gilt als unsicher, wenn sein Sprecher kaum besser passt als der zweitbeste
UNSICHER_DAUER = 0.6   # und wenn er kürzer ist als so viele Sekunden
LUECKE_TURN = 0.6      # gleicher Sprecher über so kurze Pausen bleibt ein Turn
PAUSEN = True          # Regionen an hörbaren Pausen teilen
FEINEN = True          # Wechsel ohne Pause auf die leiseste Stelle legen
WORT_SICHER = 0.7      # Anteil der Wortzeit beim Sprecher, ab dem das Wort sicher zugeordnet wird


# ---------------------------------------------------------------- Bereitstellung (pip, Modelle)

def _log(*a):
    print(*a, file=sys.stderr, flush=True)


def _sherpa():
    """sherpa_onnx importieren; fehlt es, einmal per pip nachinstallieren (braucht pypi im Netzwerk)."""
    try:
        import sherpa_onnx
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--root-user-action=ignore",
                        "--break-system-packages", SHERPA_PIP], check=True)
        import sherpa_onnx
    return sherpa_onnx


def _sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def _kopf_onnx(kopf):
    """ONNX ist Protobuf und beginnt mit dem Feld ir_version (Byte 0x08); HTML-Fehlerseiten beginnen mit '<'."""
    return kopf[:1] == b"\x08"


@contextlib.contextmanager
def _sperre(ziel):
    """Ein Lauf je Zieldatei: ein zweiter wartet hier, bis der erste fertig ist (nie zwei Downloads in dieselbe Datei)."""
    import fcntl
    name = "sprecher_" + hashlib.md5(str(ziel).encode()).hexdigest()[:10] + ".lock"
    with open(Path(tempfile.gettempdir()) / name, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _laden(url, ziel, groesse, sha256, kopf_ok):
    """Datei sicher laden: Sperre gegen parallele Läufe, .part-Datei, Größe, Dateikopf und Prüfsumme, dann umbenennen."""
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with _sperre(ziel):
        if ziel.exists() and ziel.stat().st_size == groesse and _sha256(ziel) == sha256:
            return
        teil = ziel.with_name(ziel.name + ".part")
        grund = ""
        for _ in range(3):
            teil.unlink(missing_ok=True)
            r = subprocess.run(["curl", "-sS", "-L", "--fail", "-m", "900", "-o", str(teil), url],
                               capture_output=True, text=True)
            if r.returncode or not teil.exists():
                grund = (r.stderr.strip() or f"curl {r.returncode}")[-200:]
                continue
            with open(teil, "rb") as f:
                kopf = f.read(16)
            if teil.stat().st_size != groesse:
                grund = f"Größe {teil.stat().st_size} statt {groesse} Bytes"
            elif not kopf_ok(kopf):
                grund = f"Dateikopf passt nicht (Anfang {kopf[:8]!r})"
            elif _sha256(teil) != sha256:
                grund = "Prüfsumme stimmt nicht"
            else:
                os.replace(teil, ziel)
                return
        teil.unlink(missing_ok=True)
        raise RuntimeError(f"Modell {ziel.name} nicht geladen: {grund} ({url})")


def _segmentierung_bereit():
    """model.onnx (pyannote-Segmentierung) aus dem Archiv der sherpa-onnx-Releases nach modelle/sprecher/."""
    ziel = MODELLE / SEG["datei"]

    def fertig():
        return ziel.exists() and ziel.stat().st_size == SEG["bytes"] and _sha256(ziel) == SEG["sha256"]

    if fertig():
        return ziel
    with tempfile.TemporaryDirectory() as td:
        archiv = Path(td) / "seg.tar.bz2"
        _laden(SEG["archiv"], archiv, SEG["archiv_bytes"], SEG["archiv_sha256"], lambda k: k[:3] == b"BZh")
        with tarfile.open(archiv) as t:
            data = t.extractfile(SEG["inhalt"]).read()
    if len(data) != SEG["bytes"] or not _kopf_onnx(data[:1]) or hashlib.sha256(data).hexdigest() != SEG["sha256"]:
        raise RuntimeError(f"Segmentierungsmodell im Archiv ist nicht das erwartete ({len(data)} statt {SEG['bytes']} Bytes)")
    MODELLE.mkdir(parents=True, exist_ok=True)
    with _sperre(ziel):
        if not fertig():
            teil = ziel.with_name(ziel.name + ".part")
            teil.write_bytes(data)
            os.replace(teil, ziel)
    return ziel


def modelle_bereit():
    """(Pfad Segmentierung, Pfad Einbettung); lädt Fehlendes nach. Wirft RuntimeError, wenn das nicht geht."""
    seg = _segmentierung_bereit()
    emb = MODELLE / EMB["datei"]
    _laden(EMB["url"], emb, EMB["bytes"], EMB["sha256"], _kopf_onnx)
    return seg, emb


def verfuegbar(nachladen=False):
    """(True, "") wenn sherpa-onnx und beide Modelle da sind, sonst (False, Grund). Mit nachladen=True wird ergänzt."""
    try:
        if nachladen:
            _sherpa()
            modelle_bereit()
        else:
            import importlib.util
            if importlib.util.find_spec("sherpa_onnx") is None:
                return False, "sherpa-onnx fehlt (pip install sherpa-onnx)"
            fehlt = [n for n, sz in ((SEG["datei"], SEG["bytes"]), (EMB["datei"], EMB["bytes"]))
                     if not (MODELLE / n).exists() or (MODELLE / n).stat().st_size != sz]
            if fehlt:
                return False, "Modell fehlt in modelle/sprecher/: " + ", ".join(fehlt)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- Ton

def _work():
    try:
        sys.path.insert(0, str(HIER.parent / "pipeline"))
        import reelcfg
        return Path(reelcfg.WORK)
    except Exception:
        return Path(os.environ.get("REEL_WORK", "/home/user/reel"))


def ton_pfad(eingabe):
    """Datei, wenn es sie gibt, sonst Stamm -> $REEL_WORK/audio/<stamm>.flac."""
    p = Path(eingabe)
    if p.is_file():
        return p
    stamm = p.stem if p.suffix.lower() in (".mov", ".mp4", ".flac", ".wav", ".m4a", ".mp3") else p.name
    f = _work() / "audio" / f"{stamm}.flac"
    if f.is_file():
        return f
    raise FileNotFoundError(f"Kein Ton für {eingabe}: weder die Datei noch {f}")


def lade_ton(datei):
    """16 kHz Mono als float32 (ffmpeg, Ton oder Video)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(datei), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode or not r.stdout:
        raise RuntimeError(f"ffmpeg konnte {datei} nicht lesen: {r.stderr.decode(errors='replace')[-200:]}")
    return np.frombuffer(r.stdout, np.float32).copy()


def _db(x):
    return float(20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9)) if len(x) else -99.0


# ---------------------------------------------------------------- Sprachabschnitte und Einbettung

def _ort():
    """onnxruntime (wie in oton.py); fehlt es, einmal per pip nachinstallieren."""
    try:
        import onnxruntime
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--root-user-action=ignore",
                        "--break-system-packages", "onnxruntime==1.30.0"], check=True)
        import onnxruntime
    return onnxruntime


def _luecken_fuellen(maske, schritt, luecke, mindest):
    """bool-Maske -> [(von, bis)] in s; Lücken bis luecke s werden geschlossen, Abschnitte unter mindest s fallen weg."""
    out, i, n = [], 0, len(maske)
    while i < n:
        if maske[i]:
            j = i
            while j < n and (maske[j] or maske[j:j + int(luecke / schritt) + 1].any()):
                j += 1
            while j > i and not maske[j - 1]:
                j -= 1
            if (j - i) * schritt >= mindest:
                out.append((i * schritt, j * schritt))
            i = j + 1
        else:
            i += 1
    return out


class _Sherpa:
    """Sprachabschnitte aus der pyannote-Segmentierung, Einbettungen mit CAM++ (sherpa-onnx)."""
    name = "sherpa-onnx (pyannote-Segmentierung, CAM++)"
    schwaecher = False

    def __init__(self, threads=4):
        so = _sherpa()
        self.so = so
        self.threads = threads
        self.seg, emb = modelle_bereit()
        self.ex = so.SpeakerEmbeddingExtractor(so.SpeakerEmbeddingExtractorConfig(model=str(emb), num_threads=threads))
        self.emb_pfad = emb

    def sprache(self, x):
        """([(von, bis)] Sprachabschnitte, [[von, bis]] gleichzeitiges Sprechen). Bevorzugt das Segmentierungsmodell
        direkt mit onnxruntime (1 s je Minute, liefert auch die Überlappung), sonst sherpa OfflineSpeakerDiarization
        (etwa 15 s je Minute, ohne Überlappung)."""
        try:
            return self._segmentierung_ort(x)
        except Exception as e:
            _log(f"Hinweis: Segmentierung mit onnxruntime nicht möglich ({type(e).__name__}: {str(e)[:100]}), "
                 "sherpa-Diarisierung ohne Überlappungs-Erkennung")
            return self._diarisierung_sherpa(x), []

    def _segmentierung_ort(self, x, fenster=10 * SR, schritt=int(2.5 * SR)):
        """pyannote-segmentation-3.0: 10-s-Fenster, je Bild (270 Samples) 7 Klassen (Stille, 3 einzelne Sprecher,
        3 Paare). Über überlappende Fenster gewichtet gemittelt; Sprache = nicht Stille, Überlappung = ein Paar."""
        if not hasattr(self, "_sess"):
            ort = _ort()
            o = ort.SessionOptions()
            o.intra_op_num_threads = self.threads
            self._sess = ort.InferenceSession(str(self.seg), o, providers=["CPUExecutionProvider"])
        bild, versatz = 270, 495
        starts = list(range(0, max(len(x) - fenster, 0) + 1, schritt))
        if starts[-1] + fenster < len(x):
            starts.append(len(x) - fenster)
        n = len(x) // bild + 2
        summe, zahl = np.zeros((n, 7)), np.zeros(n)
        for st in starts:
            teil = x[st:st + fenster]
            if len(teil) < fenster:
                teil = np.pad(teil, (0, fenster - len(teil)))
            y = np.exp(self._sess.run(None, {"x": teil[None, None, :].astype(np.float32)})[0][0])
            g = (st + versatz + bild * np.arange(len(y))) // bild
            ok = g < n
            gew = np.hamming(len(y))                   # Fenstermitte zählt mehr als der Rand (wie pyannote)
            np.add.at(summe, g[ok], (y * gew[:, None])[ok])
            np.add.at(zahl, g[ok], gew[ok])
        p = summe[zahl > 0] / zahl[zahl > 0, None]
        t = np.flatnonzero(zahl > 0)
        frame = np.zeros(n, int)                      # 0 Stille, 1 einer, 2 Überlappung
        frame[t] = np.where(p[:, 0] >= 0.5, 0, np.where(p[:, 4:].sum(1) >= 0.5, 2, 1))
        dt = bild / SR
        sprache = _luecken_fuellen(frame > 0, dt, 0.1, MIN_SPRACHE)
        ueb = _luecken_fuellen(frame == 2, dt, 0.05, 0.2)
        return sprache, [[round(a, 3), round(b, 3)] for a, b in ueb]

    def _diarisierung_sherpa(self, x):
        so = self.so
        cfg = so.OfflineSpeakerDiarizationConfig(
            segmentation=so.OfflineSpeakerSegmentationModelConfig(
                pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(self.seg)), num_threads=self.threads),
            embedding=so.SpeakerEmbeddingExtractorConfig(model=str(self.emb_pfad), num_threads=self.threads),
            clustering=so.FastClusteringConfig(num_clusters=1),      # die Sprecher entscheiden wir selbst
            min_duration_on=MIN_SPRACHE, min_duration_off=0.1)
        r = so.OfflineSpeakerDiarization(cfg).process(x).sort_by_start_time()
        return [(float(s.start), float(s.end)) for s in r]

    def vektor(self, x, a, b):
        st = self.ex.create_stream()
        st.accept_waveform(SR, x[int(a * SR):int(b * SR)])
        st.input_finished()
        v = np.array(self.ex.compute(st), np.float64)
        return v / (np.linalg.norm(v) + 1e-9)

    def nachbehandlung(self, E):
        return E


class _Mfcc:
    """Ersatz ohne Sprecher-Modell: Energie-Erkennung der Sprache, MFCC-Mittel und -Streuung je Fenster. Schwach."""
    name = "MFCC-Ersatz (ohne sherpa-onnx, deutlich schwächer)"
    schwaecher = True

    def sprache(self, x):
        hop = 160
        n = len(x) // hop - 1
        pegel = np.array([_db(x[i * hop:i * hop + 400]) for i in range(max(n, 0))])
        if not len(pegel):
            return [], []
        schwelle = max(np.percentile(pegel, 10) + 10, np.percentile(pegel, 95) - 28)
        return _luecken_fuellen(pegel > schwelle, 0.01, 0.15, MIN_SPRACHE), []

    def vektor(self, x, a, b):
        import librosa
        m = librosa.feature.mfcc(y=x[int(a * SR):int(b * SR)], sr=SR, n_mfcc=20, n_fft=512, hop_length=160)
        return np.concatenate([m.mean(1), m.std(1)])

    def nachbehandlung(self, E):
        E = E - E.mean(0)
        E = E / (E.std(0) + 1e-6)
        return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


def motor(ersatz=False):
    """Sherpa-Motor, sonst (oder mit ersatz=True) der schwache MFCC-Ersatz."""
    if not ersatz:
        try:
            return _Sherpa()
        except Exception as e:
            _log(f"WARNUNG sherpa-onnx nicht verfügbar ({type(e).__name__}: {str(e)[:150]}): MFCC-Ersatz, deutlich schwächer")
    return _Mfcc()


def _regionen(abschnitte, luecke=0.15):
    """Sprachabschnitte [(von, bis)] zu Regionen verbinden (Lücken bis luecke s schließen)."""
    out = []
    for a, b in sorted(abschnitte):
        if out and a - out[-1][1] <= luecke:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out if b - a >= MIN_SPRACHE]


def _pausen_teilen(x, regs, tiefe=20.0, mindest=0.12):
    """Regionen an hörbaren Pausen teilen (Pegel mindestens tiefe dB unter dem Sprachpegel der Region, mindest s lang).
    Nach einer Pause wechselt oft der Sprecher, und die Segmentierung übersieht kurze Pausen. Ein Schnitt im Redefluss
    schadet nicht: gleiche Sprecher werden später wieder zu einem Turn."""
    hop = 160
    n = len(x) // hop - 2
    if n < 10:
        return regs
    rms = np.array([_db(x[i * hop:i * hop + 400]) for i in range(n)])
    out = []
    for a, b in regs:
        i0, i1 = int(a * 100), min(int(b * 100), n)
        if i1 - i0 < 2 * int(mindest * 100) + 4:
            out.append((a, b))
            continue
        seg = rms[i0:i1]
        leise = seg < np.percentile(seg, 80) - tiefe
        start, i = a, 0
        while i < len(seg):
            if leise[i]:
                j = i
                while j < len(seg) and leise[j]:
                    j += 1
                if (j - i) / 100 >= mindest and i > 0 and j < len(seg):
                    out.append((start, (i0 + i) / 100))
                    start = (i0 + j) / 100
                i = j
            else:
                i += 1
        out.append((start, b))
    return [(a, b) for a, b in out if b - a >= MIN_SPRACHE]


def _fenster(mo, x, regs):
    """Fenster (von, bis) je Region und ihre Einbettungen. Kurze Regionen bekommen ein Fenster in Regionslänge.
    Rückgabe: Fenster, E, Indexbereiche je Region."""
    W, E, idx = [], [], []
    for a, b in regs:
        i0 = len(W)
        if b - a <= FENSTER + HOP:
            W.append((a, b))
        else:
            ts = list(np.arange(a, b - FENSTER + 1e-6, HOP))
            if b - FENSTER - ts[-1] > 0.02:
                ts.append(b - FENSTER)
            W += [(t, t + FENSTER) for t in ts]
        E += [mo.vektor(x, s, e) for s, e in W[i0:]]
        idx.append((i0, len(W)))
    return W, mo.nachbehandlung(np.array(E)), idx


def _viterbi(S, strafe):
    """Beste Gruppenfolge für eine Region: Summe der Ähnlichkeit minus Strafe je Wechsel. S: (Fenster, Gruppen)."""
    N, K = S.shape
    dp = S[0].copy()
    zur = np.zeros((N, K), int)
    ks = np.arange(K)
    for i in range(1, N):
        best = int(dp.argmax())
        wechsel = dp[best] - strafe
        bleibt = dp >= wechsel
        zur[i] = np.where(bleibt, ks, best)
        dp = np.where(bleibt, dp, wechsel) + S[i]
    k = int(dp.argmax())
    pfad = np.zeros(N, int)
    for i in range(N - 1, -1, -1):
        pfad[i] = k
        k = zur[i, k]
    return pfad


def _gruppieren(E, n, schwelle, h_max=1500):
    """Erste Gruppen: Mittelwert-Verknüpfung auf dem Kosinus-Abstand (bei vielen Fenstern auf einer Stichprobe)."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    schritt = max(1, int(np.ceil(len(E) / h_max)))
    P = E[::schritt]
    if len(P) < 2:
        return np.zeros(len(E), int), E[:1]
    D = np.clip(1 - P @ P.T, 0, None)
    np.fill_diagonal(D, 0)
    Z = linkage(squareform(D, checks=False), "average")
    c = fcluster(Z, n, "maxclust") if n else fcluster(Z, schwelle, "distance")
    cent = np.array([P[c == k].mean(0) for k in sorted(set(c))])
    return c, cent / np.linalg.norm(cent, axis=1, keepdims=True)


def _behalten(cent, lab):
    """Welche Gruppen bleiben? Gruppen mit weniger als MIN_SPRECHER_S Redezeit gehen an eine ähnliche andere (Mischfenster
    an Sprecherwechseln, Rauschen), bleiben aber, wenn sie keiner anderen ähneln: ein Gast, der nur "Ja" sagt."""
    zeit = np.array([(lab == k).sum() * HOP for k in range(len(cent))])
    C = cent @ cent.T
    bleibt = [k for k in range(len(cent)) if zeit[k] >= MIN_SPRECHER_S]
    for k in sorted((k for k in range(len(cent)) if 0 < zeit[k] < MIN_SPRECHER_S), key=lambda k: -zeit[k]):
        if not bleibt or max(C[k, j] for j in bleibt) < AEHNLICH:
            bleibt.append(k)
    return sorted(bleibt) or [int(np.argmax(zeit))]


def _turns_aus(mo, x, n=None, schwelle=None, strafe=None):
    """Kern: Turns mit Gruppennummern (int), Überlappungszeiten und Einzelheiten. n = feste Sprecherzahl oder None."""
    schwelle = SCHWELLE if schwelle is None else schwelle
    strafe = STRAFE if strafe is None else strafe
    ab, ueb = mo.sprache(x)
    regs = _pausen_teilen(x, _regionen(ab)) if PAUSEN else _regionen(ab)
    if not regs:
        return [], [], dict(n=0)
    W, E, idx = _fenster(mo, x, regs)
    if n == 1 or len(E) < 2:
        lab = np.zeros(len(E), int)
        cent = E.mean(0, keepdims=True)
        cent /= np.linalg.norm(cent, axis=1, keepdims=True)
    else:
        eff = schwelle if not mo.schwaecher else schwelle + 0.2
        _, cent = _gruppieren(E, n, eff)
        for _ in range(3):
            lab = np.zeros(len(E), int)
            S = E @ cent.T
            for i0, i1 in idx:
                lab[i0:i1] = _viterbi(S[i0:i1], strafe)
            if n:
                break
            behalten = _behalten(cent, lab)
            neu = np.array([E[lab == k].mean(0) for k in behalten])
            cent = neu / np.linalg.norm(neu, axis=1, keepdims=True)
        S = E @ cent.T
        lab = np.zeros(len(E), int)
        for i0, i1 in idx:
            lab[i0:i1] = _viterbi(S[i0:i1], strafe)
    S = E @ cent.T
    # Turns je Region aus den Fenstermitten (+- HOP/2), Regionsränder gelten bis zur Sprachgrenze
    roh = []
    for (a, b), (i0, i1) in zip(regs, idx):
        cur = None
        for i in range(i0, i1):
            m = (W[i][0] + W[i][1]) / 2
            s = a if i == i0 else m - HOP / 2
            e = b if i == i1 - 1 else m + HOP / 2
            if cur and cur["g"] == lab[i]:
                cur["bis"] = e
                cur["fenster"].append(i)
            else:
                if cur:
                    roh.append(cur)
                cur = dict(von=s, bis=e, g=int(lab[i]), fenster=[i])
        if cur:
            roh.append(cur)
    if FEINEN:
        _grenzen_feinen(x, roh)
    # Marge: wie viel besser passt der Sprecher als der zweitbeste
    for t in roh:
        s = S[t["fenster"]]
        zweit = np.partition(s, -2, axis=1)[:, -2] if s.shape[1] > 1 else np.full(len(s), -1.0)
        t["marge"] = float(np.mean(s[:, t["g"]] - zweit)) if s.shape[1] > 1 else 1.0
    # gleicher Sprecher über kurze Pausen, ohne dass ein anderer dazwischen spricht: ein Turn
    turns = []
    for t in roh:
        if turns and turns[-1]["g"] == t["g"] and t["von"] - turns[-1]["bis"] <= LUECKE_TURN:
            v = turns[-1]
            d0, d1 = v["bis"] - v["von"], t["bis"] - t["von"]
            v["marge"] = (v["marge"] * d0 + t["marge"] * d1) / max(d0 + d1, 1e-9)
            v["bis"] = t["bis"]
        else:
            turns.append(dict(von=t["von"], bis=t["bis"], g=t["g"], marge=t["marge"]))
    info = dict(n=len(set(t["g"] for t in turns)), fenster=len(W))
    return turns, ueb, info


def _grenzen_feinen(x, roh, radius=0.3):
    """Sprecherwechsel ohne Pause (Turns, die lückenlos aneinandergrenzen) auf die leiseste Stelle in +- radius s legen:
    die Fenster liefern nur etwa +- 0,3 s Genauigkeit, ein Wechsel liegt aber meist in einer Senke des Pegels."""
    hop = 160
    n = len(x) // hop - 2
    if n < 10:
        return
    rms = np.array([_db(x[i * hop:i * hop + 400]) for i in range(n)])
    rms = np.convolve(rms, np.ones(3) / 3, mode="same")
    for t0, t1 in zip(roh, roh[1:]):
        if abs(t1["von"] - t0["bis"]) > 0.02 or t0["g"] == t1["g"]:
            continue
        g = t0["bis"]
        lo = max(int((g - radius) * 100), int((t0["von"] + 0.25) * 100), 0)
        hi = min(int((g + radius) * 100), int((t1["bis"] - 0.25) * 100), n - 1)
        if hi <= lo:
            continue
        neu = (lo + int(np.argmin(rms[lo:hi + 1]))) / 100
        t0["bis"] = t1["von"] = neu


def _benennen(turns):
    """Gruppennummern -> S1, S2 … nach dem ersten Auftritt; fertige Turn-Dicts {von, bis, sprecher[, unsicher]}."""
    namen = {}
    out = []
    mehrere = len({t["g"] for t in turns}) > 1
    for t in turns:
        if t["g"] not in namen:
            namen[t["g"]] = f"S{len(namen) + 1}"
        d = dict(von=round(t["von"], 3), bis=round(t["bis"], 3), sprecher=namen[t["g"]])
        if mehrere and (t["marge"] < UNSICHER_MARGE or t["bis"] - t["von"] < UNSICHER_DAUER):
            d["unsicher"] = True
        out.append(d)
    return out


def sprecher_turns(ton_datei, n=None, ersatz=False):
    """Turns einer Ton- oder Videodatei (oder eines Stamms): [{von, bis, sprecher: "S1"[, unsicher: True]}], sortiert nach von.
    n = feste Sprecherzahl, sonst wird sie geschätzt. ersatz=True erzwingt den schwachen MFCC-Ersatz."""
    mo = motor(ersatz)
    x = lade_ton(ton_pfad(ton_datei))
    turns, _, _ = _turns_aus(mo, x, n)
    return _benennen(turns)


# ---------------------------------------------------------------- Wörter, Sätze, Segmente

def _satzende(w):
    return w.rstrip('"»“)').endswith((".", "!", "?", "…"))


def _text(woerter):
    """Wörter zu Text; Whisper trennt "Ich-bin-stärker" in "Ich", "-bin", "-stärker": ohne Leerzeichen zurück."""
    out = ""
    for w in woerter:
        t = w["w"]
        out += t if (not out or t[:1] in "-,.!?;:…") else " " + t
    return out


def woerter_zuordnen(transkript, turns, ton=None, ueberlappung=None):
    """Kopie des Transkripts (Format transkript.py) mit Sprecher je Wort und an Sprecherwechseln geteilten Segmenten.

    Je Wort: "sprecher" = "S1" …, wenn mindestens WORT_SICHER der Wortzeit in Turns desselben Sprechers liegt und der
    Turn nicht unsicher ist (Wörter ohne Sprachabschnitt: nächster Turn bis 0,25 s Abstand). Sonst "?" (Wortgrenze,
    Überlappung, unsicherer Turn, Pause) und "vermutet" mit der besten Annahme, falls es eine gibt.
    Segmente werden zwischen Wörtern verschiedener Sprecher (sicher oder vermutet) an der größten Pause geteilt.
    turns: Liste aus sprecher_turns(). ueberlappung: Zeiten [[von, bis], …] gleichzeitigen Sprechens (aus analyse()).
    ton: float32-Ton (16 kHz), damit geteilte Segmente einen eigenen Pegel bekommen; sonst erben sie den alten."""
    ueberlappung = ueberlappung or []
    tr = copy.deepcopy(transkript)
    ts = sorted(turns, key=lambda t: t["von"])
    von = np.array([t["von"] for t in ts] or [0.0])
    bis = np.array([t["bis"] for t in ts] or [0.0])

    def ordne(w):
        s, e = float(w["s"]), float(w["e"])
        dauer = max(e - s, 0.05)
        ueber = {}
        for t, a, b in zip(ts, von, bis):
            o = min(e, b) - max(s, a)
            if o > 0:
                ueber.setdefault(t["sprecher"], [0.0, False])
                ueber[t["sprecher"]][0] += o
                ueber[t["sprecher"]][1] = ueber[t["sprecher"]][1] or bool(t.get("unsicher"))
        gesamt = sum(v[0] for v in ueber.values())
        if gesamt >= 0.4 * dauer:
            best = max(ueber, key=lambda k: ueber[k][0])
            mitte = (s + e) / 2
            if ueber[best][0] / gesamt >= WORT_SICHER and not ueber[best][1] \
                    and not any(a <= mitte <= b for a, b in ueberlappung):
                return best, None
            return "?", best
        if not ts:
            return "?", None
        mitte = (s + e) / 2
        abst = np.maximum(np.maximum(von - mitte, mitte - bis), 0)
        i = int(abst.argmin())
        if abst[i] <= 0.25:
            return "?", ts[i]["sprecher"]
        return "?", None

    for sg in tr["segmente"]:
        for w in sg["woerter"]:
            w["sprecher"], vermutet = ordne(w)
            if vermutet:
                w["vermutet"] = vermutet
    neu = []
    for sg in tr["segmente"]:
        ws = sg["woerter"]
        gruppen = _teilen(ws)
        for teil in gruppen:
            k = dict(sg)
            k["woerter"] = teil
            k["s"], k["e"] = teil[0]["s"], teil[-1]["e"]
            k["text"] = _text(teil) if len(gruppen) > 1 else sg["text"]
            sichere = [w["sprecher"] for w in teil if w["sprecher"] != "?"]
            eff = sichere or [w["vermutet"] for w in teil if w.get("vermutet")]
            k["sprecher"] = max(set(eff), key=eff.count) if eff else "?"
            if len(sichere) * 2 < len(teil):
                k["unsicher"] = True
            if ton is not None and len(gruppen) > 1:
                k["pegel"] = round(_db(ton[int(k["s"] * SR):max(int(k["e"] * SR), int(k["s"] * SR) + 1)]), 1)
            neu.append(k)
    tr["segmente"] = neu
    return tr


def _teilen(ws):
    """Wörter eines Segments an Sprecherwechseln in Gruppen teilen. Es zählt der sichere Sprecher, sonst der vermutete.
    Ein einzelnes vermutetes Wort zwischen zwei gleichen Sprechern ist kein Wechsel. Geschnitten wird an der größten
    Pause zwischen den beiden Wörtern verschiedener Sprecher (bei Gleichstand an der früheren)."""
    eff = [w["sprecher"] if w["sprecher"] != "?" else w.get("vermutet") for w in ws]
    bekannt = [i for i, e in enumerate(eff) if e]
    for j in range(1, len(bekannt) - 1):
        i = bekannt[j]
        if ws[i]["sprecher"] == "?" and eff[bekannt[j - 1]] == eff[bekannt[j + 1]] != eff[i]:
            eff[i] = eff[bekannt[j - 1]]
    schnitte = []
    for a, b in zip(bekannt, bekannt[1:]):
        if eff[a] != eff[b]:
            luecken = [(ws[i + 1]["s"] - ws[i]["e"], -i) for i in range(a, b)]
            schnitte.append(-max(luecken)[1] + 1)
    gruppen, start = [], 0
    for c in schnitte + [len(ws)]:
        if ws[start:c]:
            gruppen.append(ws[start:c])
        start = c
    return gruppen


def saetze(transkript):
    """[(Text, Wörter)] über alle Segmente: ein Satz endet bei . ! ? oder … (auch über Segmentgrenzen)."""
    out, cur = [], []
    for sg in transkript["segmente"]:
        for w in sg["woerter"]:
            cur.append(w)
            if _satzende(w["w"]):
                out.append(cur)
                cur = []
    if cur:
        out.append(cur)
    return [(_text(ws), ws) for ws in out]


def fragen_je_sprecher(transkript_zugeordnet):
    """{S1: Zahl der Sätze mit ?}. Ein Satz zählt für den Sprecher mit den meisten Wörtern; sichere Wörter gelten 1,
    vermutete 0,6."""
    z = {}
    for text, ws in saetze(transkript_zugeordnet):
        if not text.rstrip('"»“) ').endswith("?"):
            continue
        gew = {}
        for w in ws:
            s = w.get("sprecher")
            if s == "?":
                s, g = w.get("vermutet"), 0.6
            else:
                g = 1.0
            if s:
                gew[s] = gew.get(s, 0.0) + g
        if gew:
            s = max(gew, key=gew.get)
            z[s] = z.get(s, 0) + 1
    return z


# ---------------------------------------------------------------- Kennzahlen, Hinweis, Ausgabe

def tonhoehe(x, turns, sprecher, max_s=20.0):
    """Median der Grundfrequenz (librosa.pyin) über die Turns eines Sprechers, höchstens max_s Sekunden."""
    try:
        import librosa
    except ImportError:
        return None
    stuecke, dauer = [], 0.0
    for t in sorted((t for t in turns if t["sprecher"] == sprecher), key=lambda t: t["von"] - t["bis"]):
        if dauer >= max_s:
            break
        a, b = int(t["von"] * SR), int(min(t["bis"], t["von"] + max_s - dauer) * SR)
        if b - a >= 0.4 * SR:
            stuecke.append(x[a:b])
            dauer += (b - a) / SR
    if not stuecke:
        return None
    f0s = []
    for y in stuecke:
        f0, _, _ = librosa.pyin(y, fmin=65, fmax=400, sr=SR, frame_length=1024, hop_length=320)
        f0s.append(f0[~np.isnan(f0)])
    f0s = np.concatenate(f0s)
    return round(float(np.median(f0s)), 1) if len(f0s) >= 10 else None


def kennzahlen(x, turns, fragen=None):
    """{S1: {redezeit_s, pegel_db, tonhoehe_hz[, fragen]}}"""
    out = {}
    for s in sorted({t["sprecher"] for t in turns}, key=lambda k: int(k[1:])):
        mine = [t for t in turns if t["sprecher"] == s]
        audio = np.concatenate([x[int(t["von"] * SR):int(t["bis"] * SR)] for t in mine])
        d = dict(redezeit_s=round(sum(t["bis"] - t["von"] for t in mine), 2), pegel_db=round(_db(audio), 1),
                 tonhoehe_hz=tonhoehe(x, turns, s))
        if fragen is not None:
            d["fragen"] = fragen.get(s, 0)
        out[s] = d
    return out


def hinweis_fragesteller(kz):
    """Text "Fragesteller wahrscheinlich S1 (…)" oder None. Nur ein Hinweis (mehr Fragesätze, lauter), nie eine Festlegung."""
    zaehlt = {s: d for s, d in kz.items() if d["redezeit_s"] >= 1.0}
    if len(zaehlt) < 2:
        return None
    lauter = sorted(zaehlt, key=lambda s: -zaehlt[s]["pegel_db"])
    abstand = zaehlt[lauter[0]]["pegel_db"] - zaehlt[lauter[1]]["pegel_db"]
    laut = lauter[0] if abstand >= 3.0 else None
    fr = sorted(zaehlt, key=lambda s: -zaehlt[s].get("fragen", 0))
    viel = fr[0] if zaehlt[fr[0]].get("fragen", 0) > zaehlt[fr[1]].get("fragen", 0) else None
    if viel and laut and viel == laut:
        return f"Fragesteller wahrscheinlich {viel} (mehr Fragesätze und lauter, nur ein Hinweis)"
    if viel and laut:
        return f"Fragesteller unklar: {viel} hat mehr Fragesätze, {laut} ist lauter (nur ein Hinweis)"
    if viel:
        return f"Fragesteller wahrscheinlich {viel} (mehr Fragesätze, nur ein Hinweis)"
    if laut:
        return f"Fragesteller wahrscheinlich {laut} (lauter um {abstand:.0f} dB, nur ein Hinweis)"
    return None


def analyse(eingabe, n=None, transkript_ordner=None, ersatz=False, mo=None):
    """Alles für einen Clip: dict für die <stamm>.sprecher.json (plus "segmente" mit Transkript)."""
    datei = ton_pfad(eingabe)
    stamm = Path(eingabe).stem if Path(eingabe).suffix else Path(eingabe).name
    mo = mo or motor(ersatz)
    x = lade_ton(datei)
    roh, ueb, info = _turns_aus(mo, x, n)
    turns = _benennen(roh)
    res = dict(datei=str(datei), dauer=round(len(x) / SR, 3), verfahren=mo.name, sprecher_angefragt=n,
               turns=turns, ueberlappung=ueb)
    fragen = None
    tr_pfad = Path(transkript_ordner) / f"{stamm}.json" if transkript_ordner else None
    if tr_pfad and tr_pfad.exists():
        tr = json.loads(tr_pfad.read_text())
        zu = woerter_zuordnen(tr, turns, x, ueb)
        fragen = fragen_je_sprecher(zu)
        res["transkript"] = str(tr_pfad)
        res["segmente"] = zu["segmente"]
    elif tr_pfad:
        _log(f"Hinweis: {tr_pfad} fehlt, {stamm} läuft ohne Transkript")
    res["sprecher"] = kennzahlen(x, turns, fragen)
    res["hinweis"] = hinweis_fragesteller(res["sprecher"])
    return res


def _zeilen(res):
    """[(von, bis, Sprecher, Text)] je Sprecherwechsel. Mit Transkript aus den geteilten Segmenten (benachbarte
    Segmente desselben Sprechers mit höchstens 1 s Pause werden eine Zeile, Wörter ohne sichere Zuordnung stehen als
    (S?)), sonst aus den Turns."""
    if "segmente" not in res:
        return [(t["von"], t["bis"], t["sprecher"], "(unsicher)" if t.get("unsicher") else "") for t in res["turns"]]
    zeilen = []
    for sg in res["segmente"]:
        ws = [dict(w=w["w"] + ("(S?)" if w["sprecher"] == "?" else "")) for w in sg["woerter"]]
        if zeilen and zeilen[-1][2] == sg["sprecher"] and sg["s"] - zeilen[-1][1] <= 1.0:
            zeilen[-1][1] = sg["e"]
            zeilen[-1][3] += ws
        else:
            zeilen.append([sg["s"], sg["e"], sg["sprecher"], ws])
    return [(v, b, s, _text(ws)) for v, b, s, ws in zeilen]


def _md(stamm, res):
    z = [f"## {stamm} ({res['dauer']:.1f} s), {len(res['sprecher'])} Sprecher", ""]
    for s, d in res["sprecher"].items():
        th = f"{d['tonhoehe_hz']:.0f} Hz" if d["tonhoehe_hz"] else "Tonhöhe unbekannt"
        fr = f", {d['fragen']} Fragesätze" if "fragen" in d else ""
        kurz = " (sehr kurz, vielleicht kein eigener Sprecher)" if d["redezeit_s"] < 1.5 else ""
        z.append(f"- **{s}** {d['redezeit_s']:.1f} s, {d['pegel_db']:.0f} dB, {th}{fr}{kurz}")
    if res["hinweis"]:
        z += ["", res["hinweis"]]
    z.append("")
    z += [f"- `{v:.2f}–{b:.2f}` **{s}** {t}".rstrip() for v, b, s, t in _zeilen(res)]
    return z + [""]


def main():
    ap = argparse.ArgumentParser(description="Sprecher trennen (wer spricht wann)")
    ap.add_argument("dateien", nargs="*", help="Stämme (IMG_5315), Ton- oder Videodateien")
    ap.add_argument("-o", "--out", help="Ausgabeordner")
    ap.add_argument("--transkript", help="Ordner mit <stamm>.json aus transkript.py (Wörter bekommen Sprecher)")
    ap.add_argument("--sprecher", type=int, help="Zahl der Sprecher, sonst geschätzt")
    ap.add_argument("--ersatz", action="store_true", help="MFCC-Ersatz statt sherpa-onnx (deutlich schwächer)")
    ap.add_argument("--vorbereiten", action="store_true", help="nur sherpa-onnx und Modelle bereitstellen")
    a = ap.parse_args()
    if a.vorbereiten:
        ok, grund = verfuegbar(nachladen=True)
        print("bereit" if ok else f"FEHLER {grund}")
        return 0 if ok else 1
    if not a.dateien or not a.out:
        ap.error("Dateien und -o <ordner> angeben")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mo = motor(a.ersatz)
    md = [f"# Sprecher ({mo.name})", "",
          "Zeilen: `von–bis` Quellzeit in s, Sprecher (S1, S2 … nach dem ersten Auftritt), Text. (S?) = Wort ohne sichere "
          "Zuordnung (Wortgrenze, Überlappung oder kurzer, unsicherer Turn). Der Hinweis zum Fragesteller ist nur ein Hinweis.", ""]
    fehler = 0
    for f in a.dateien:
        stamm = Path(f).stem if Path(f).suffix else Path(f).name
        try:
            res = analyse(f, a.sprecher, a.transkript, mo=mo)
        except (FileNotFoundError, RuntimeError) as e:
            print(f"FEHLER {f}: {e}", file=sys.stderr)
            fehler += 1
            continue
        (out / f"{stamm}.sprecher.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        md += _md(stamm, res)
        kurz = sum(1 for d in res["sprecher"].values() if d["redezeit_s"] < 1.0)
        print(f"{stamm}: {len(res['sprecher'])} Sprecher" + (f" (davon {kurz} unter 1 s)" if kurz else "")
              + f", {len(res['turns'])} Turns" + (f", {res['hinweis']}" if res["hinweis"] else ""))
    (out / "sprecher.md").write_text("\n".join(md))
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
