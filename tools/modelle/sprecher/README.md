# Modelle für `tools/analyse/sprecher.py` (Sprecher trennen)

Beide Modelle sind ONNX-Dateien und laufen mit `sherpa-onnx` (PyPI, `pip install sherpa-onnx==1.13.8`, 4 MB) und `onnxruntime` (PyPI, 1.30.0) auf der CPU, ohne torch und ohne Hugging Face. Die Quelle ist jeweils ein GitHub-Release von k2-fsa/sherpa-onnx (am 30.09.2026 geladen, Adresse liefert HTTP 200). Hugging Face ist in manchen Umgebungen gesperrt.

## Segmentierung: `segmentierung_pyannote_3.0.onnx`

- Herkunft: pyannote/segmentation-3.0 (CNRS, MIT-Lizenz, Lizenztext im Archiv), von k2-fsa nach ONNX umgewandelt.
- Adresse: `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2`
- Archiv: 6 958 444 Bytes, SHA-256 `24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488`, Dateikopf `BZh`.
- Im Archiv `sherpa-onnx-pyannote-segmentation-3-0/model.onnx`: 5 992 913 Bytes, SHA-256 `220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079`, als `segmentierung_pyannote_3.0.onnx` abgelegt (unter 20 MB, kommt mit `repo_sync.py` ins Repository). Die int8-Variante im Archiv wird nicht genutzt.
- Eingang `[n, 1, 160000]` (10 s bei 16 kHz), Ausgang `[n, 589, 7]` als Log-Wahrscheinlichkeit: Stille, drei einzelne Sprecher, drei Paare (Überlappung). `sprecher.py` mittelt überlappende Fenster mit Hamming-Gewicht und gewinnt daraus Sprachabschnitte und gleichzeitiges Sprechen. Ohne onnxruntime fällt es auf `OfflineSpeakerDiarization` von sherpa-onnx zurück (etwa 15 s je Minute statt 1 s, ohne Überlappung).

## Sprecher-Einbettung: `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`

- Herkunft: CAM++ aus 3D-Speaker (Alibaba, nach Projektangabe Apache-2.0, den Lizenztext konnte der Container nicht laden), Sprecher-Verifikation Chinesisch und Englisch, 16 kHz, in das sherpa-onnx-Release umgewandelt.
- Adresse: `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`
- 28 281 164 Bytes, SHA-256 `aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2`, Dateikopf `08 07 12 07 pytorch`.
- Ausgabe: ein Vektor je Audiostück, `sprecher.py` normiert ihn und vergleicht per Kosinus. Laufzeit etwa 22 ms je 1-s-Fenster.
- **Nicht im GitHub-Repository** (`tools/repo_sync.py` lässt Dateien über 20 MB weg). `python3 tools/analyse/sprecher.py --vorbereiten` lädt fehlende Modelle sicher nach (Sperre gegen parallele Läufe, `.part`-Datei, Größe, Dateikopf und Prüfsumme, dann umbenennen). Von Hand: `curl -L -o tools/modelle/sprecher/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx <Adresse>`, danach Größe und SHA-256 prüfen. Ohne das Modell läuft `sprecher.py` mit dem deutlich schwächeren MFCC-Ersatz und meldet das.

## Warum CAM++ und nicht WeSpeaker

Verglichen mit `wespeaker_en_voxceleb_resnet34.onnx` (26 534 365 Bytes, SHA-256 `5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94`, Adresse wie oben mit diesem Dateinamen, nicht abgelegt) an den Stimmen eines fertigen Interview-Schnitts (deutsch, Handy-Ton, 17 Teile, davon 3 Fragen hinter der Kamera):

| | CAM++ | WeSpeaker ResNet34 |
|---|---|---|
| Kosinus Frage zu Frage (3 Fragen, je ganzer Teil) | 0,35 bis 0,54 | 0,81 bis 0,90 |
| Kosinus Frage zu Antwort (alle Gast-Teile) | meist unter 0,30, Ausreißer bis 0,47 | 0,57 bis 0,87 |
| Kosinus Teile aus demselben Quellclip (ein Gast) | 0,51 bis 0,69 | 0,81 bis 0,95 |
| Gruppierung der 1-s-Fenster, F1 für den Fragesteller (je nach Schwelle) | 0,71 bis 0,91 | höchstens 0,67, meist alles ein Sprecher |

WeSpeaker (Englisch, VoxCeleb) trennt deutsche Stimmen aus Handy-Ton hier nicht, alle Werte liegen eng beieinander. CAM++ trennt Fragesteller und Gäste und auch Gäste verschiedener Clips. Das ist an einem einzigen Schnitt mit wenigen Sprechern gemessen, nicht an den Originalclips und nicht gehört.

## Nutzer

`tools/analyse/sprecher.py` (Werkzeug), `tools/analyse/test_sprecher.py` (Test, lädt nichts nach und meldet SKIP, wenn ein Modell fehlt).
