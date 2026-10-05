#!/usr/bin/env python3
"""Transkript mit Wort-Zeiten für Interviews und O-Ton (Whisper large-v3 auf der CPU).

    cd /home/user && python3 transkript.py <audio_oder_video> [...] -o <ordner> [--modell large-v3] [--sprache de]
                                            [--prompt "Wörter, die vorkommen"]

Schreibt je Datei <ordner>/<stamm>.json (Segmente mit Wörtern: w, s, e, p = Wahrscheinlichkeit, dazu Pegel je Segment)
und eine gemeinsame <ordner>/transkript.md zum Lesen und Auswählen: je Segment eine Zeile mit Quellzeit und Pegel.
Wörter mit p < 0,5 stehen dort mit (?), die gehören im Schnitt abgehört oder umschrieben. Der Pegel (dBFS, RMS)
hilft beim Trennen: wer hinter der Kamera fragt, ist meist deutlich lauter als die Person im Bild.

Audio: WORK/audio/<stamm>.flac aus pipeline/ingest.py oder direkt ein Video. Laufzeit bei 4 Kernen: etwa
2–3 × Echtzeit für large-v3, Modell lädt ~1 min. Also im Hintergrund starten.
Modell: openai-whisper (pip, zieht torch von PyPI, ~5 GB), Gewichte von openaipublic.azureedge.net nach
~/.cache/whisper (large-v3 3,1 GB). Hugging Face liefert in manchen Umgebungen keine großen Dateien (CDN gesperrt),
darum nicht faster-whisper. Nie zwei Downloads parallel in dieselbe Datei (Prüfsumme stimmt sonst nicht).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True  # kein __pycache__ im geteilten Projektordner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stil import STIL  # noqa: E402

# Wörter, die vorkommen (hilft Whisper bei Namen): Marke und Inhalt aus stil.json; --prompt überschreibt
PROMPT = " ".join(x for x in ("Interview.", STIL["marke"], STIL["inhalt"]) if x) or "Interview."


def pegel(audio, s, e, sr=16000):
    x = audio[int(s * sr):max(int(e * sr), int(s * sr) + 1)]
    return round(float(20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9)), 1) if len(x) else -99.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dateien", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--modell", default="large-v3")
    ap.add_argument("--sprache", default="de")
    ap.add_argument("--prompt", default=PROMPT)
    a = ap.parse_args()
    try:
        import whisper
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openai-whisper"], check=True)
        import whisper
    import torch
    torch.set_num_threads(max(1, torch.get_num_threads()))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    model = whisper.load_model(a.modell, device="cpu")
    md = [f"# Transkript ({a.modell}, Sprache {a.sprache})", "",
          "Zeilen: `von–bis` Quellzeit in s, [Pegel dBFS], Text; (?) = unsicheres Wort (p < 0,5).", ""]
    for f in a.dateien:
        stamm = Path(f).stem
        audio = whisper.load_audio(f)
        r = model.transcribe(audio, language=a.sprache, task="transcribe", word_timestamps=True,
                             initial_prompt=a.prompt, beam_size=5, best_of=5, fp16=False,
                             condition_on_previous_text=False)
        segs = []
        for sg in r["segments"]:
            words = [dict(w=w["word"].strip(), s=round(float(w["start"]), 3), e=round(float(w["end"]), 3),
                          p=round(float(w["probability"]), 3)) for w in sg.get("words", [])]
            if not words:
                continue
            segs.append(dict(s=words[0]["s"], e=words[-1]["e"], text=sg["text"].strip(),
                             pegel=pegel(audio, words[0]["s"], words[-1]["e"]),
                             logprob=round(float(sg["avg_logprob"]), 3), no_speech=round(float(sg["no_speech_prob"]), 3),
                             woerter=words))
        dur = round(len(audio) / 16000, 3)
        (out / f"{stamm}.json").write_text(json.dumps(dict(datei=str(f), dauer=dur, sprache=r.get("language"),
                                                           modell=a.modell, segmente=segs), ensure_ascii=False,
                                                      indent=1))
        md += [f"## {stamm} ({dur:.1f} s)", ""]
        for sg in segs:
            txt = " ".join(w["w"] + ("(?)" if w["p"] < 0.5 else "") for w in sg["woerter"])
            md.append(f"- `{sg['s']:.2f}–{sg['e']:.2f}` [{sg['pegel']:.0f}] {txt}")
        md.append("")
        print(f"{stamm}: {len(segs)} Segmente, {sum(len(s['woerter']) for s in segs)} Wörter", flush=True)
    (out / "transkript.md").write_text("\n".join(md) + "\n")
    print(f"-> {out}/transkript.md")


if __name__ == "__main__":
    main()
