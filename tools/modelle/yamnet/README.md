# YAMNet als ONNX (für `tools/analyse/oton.py`)

- Modell: YAMNet (Google, AudioSet, 521 Klassen), Apache-2.0-Lizenz, aus `tensorflow/models`, Ordner `research/audioset/yamnet` (Gewichte `yamnet.h5` von storage.googleapis.com/audioset).
- Am 28.09.2026 umgewandelt: nur das Netz ab den Log-Mel-Patches (Eingang `[n, 96, 64]`, Ausgang `[n, 521]` Wahrscheinlichkeiten) mit tf2onnx 1.17, Opset 17. Abweichung zum Original unter 2·10⁻⁶.
- `mel_matrix.npy`: Mel-Filterbank von TensorFlow (257 × 64, 125–7500 Hz); die Log-Mel-Merkmale rechnet `oton.py` damit in numpy nach (16 kHz mono, Fenster 25 ms, Hop 10 ms, Patch 0,96 s, Hop 0,48 s).
- `yamnet_class_map.csv`: Klassennamen.
- Laufzeit: nur `numpy` und `onnxruntime` (oton.py installiert onnxruntime beim ersten Lauf nach, ~15 MB), kein TensorFlow.
