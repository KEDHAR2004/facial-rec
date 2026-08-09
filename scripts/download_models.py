"""Download the pretrained ONNX models used by the face engine.

Models:
  - YuNet   : face detection      (OpenCV Zoo)
  - SFace   : face recognition    (OpenCV Zoo)
  - FER+    : expression analysis (ONNX Model Zoo)
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx"
    ),
    "face_recognition_sface_2021dec.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx"
    ),
    "emotion-ferplus-8.onnx": (
        "https://github.com/onnx/models/raw/main/validated/vision/"
        "body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx"
    ),
}


def download(name: str, url: str) -> None:
    dest = MODELS_DIR / name
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] {name} already present ({dest.stat().st_size:,} bytes)")
        return
    print(f"[get ] {name} <- {url}")
    resp = requests.get(url, timeout=120, allow_redirects=True)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"[ok  ] {name} ({len(resp.content):,} bytes)")


def main() -> int:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in MODELS.items():
        download(name, url)
    print("All models ready in", MODELS_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
