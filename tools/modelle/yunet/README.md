# YuNet Gesichtserkennung (OpenCV Zoo)

- `face_detection_yunet_2023mar.onnx` aus github.com/opencv/opencv_zoo, `models/face_detection_yunet` (Git LFS, geladen über media.githubusercontent.com am 29.09.2026), MIT-Lizenz, 232 KB.
- Läuft mit `cv2.FaceDetectorYN` (OpenCV 5 im Container hat keine Haar-Kaskaden mehr).
- Nutzt `tools/pipeline/interview.py` für die Bildmitte beim Punch-in (Gesicht bei 50 % Breite, 38 % Höhe).
