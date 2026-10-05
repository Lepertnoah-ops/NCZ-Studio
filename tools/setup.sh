#!/bin/bash
# KI-Reel-Studio: Werkzeuge für jeden neuen Thread bzw. jede neue Session (ffmpeg, Python-Pakete, Schriften).
# Gehört als Setup-Skript in die Umgebung des Projekts (EINRICHTUNG.md). Getestet am 2026-09-25, Laufzeit ca. 70 s.
# Braucht Netzwerkzugriff auf die Paketquellen (apt, pypi).
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq 2>/dev/null
apt-get install -y -qq --no-install-recommends \
  ffmpeg sox rubberband-cli fonts-dejavu-core fonts-montserrat fonts-inter >/dev/null
python3 -m pip install -q --no-cache-dir --root-user-action=ignore --break-system-packages \
  numpy==2.4.6 scipy==1.17.1 opencv-python-headless==5.0.0.93 librosa==0.11.0 \
  soundfile==0.14.0 pyloudnorm==0.2.0 pedalboard==0.9.25 pydub==0.25.1 \
  pillow==12.3.0 reportlab==5.0.1 matplotlib==3.11.2
command -v ffmpeg >/dev/null && command -v rubberband >/dev/null \
  && python3 -c "import cv2, librosa, soundfile, pyloudnorm, pedalboard, PIL, reportlab" \
  && echo "Reel-Studio bereit"
