"""Flask web UI for the facial-rec toolkit.

Features:
- Live camera detection: the browser captures webcam frames and posts them to
  ``/api/detect``, which returns face bounding boxes drawn live in the browser.
- Image upload / bundled sample: server-side detection with an annotated result.
- Capture gallery: frames saved via ``/api/capture`` are annotated, stored on
  disk under ``captures/``, and listed on ``/gallery``.
"""

from __future__ import annotations

import base64
import os
import time
from datetime import datetime

import cv2
import numpy as np
from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from facial_rec.detector import FaceDetector
from facial_rec.samples import astronaut_bgr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")
os.makedirs(CAPTURE_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB uploads
detector = FaceDetector()


def _encode_png(image: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("failed to encode image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _decode_data_url(data_url: str) -> np.ndarray | None:
    """Decode a base64 image (optionally a ``data:`` URL) into a BGR array."""

    if not data_url:
        return None
    if "," in data_url and data_url.strip().startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    try:
        raw = base64.b64decode(data_url)
    except (ValueError, TypeError):
        return None
    arr = np.frombuffer(raw, dtype=np.uint8)
    if arr.size == 0:
        return None
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _detect_and_render(image: np.ndarray):
    faces = detector.detect(image)
    annotated = detector.annotate(image, faces)
    return faces, _encode_png(annotated)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        use_sample = request.form.get("use_sample") == "1"
        image = None

        if use_sample:
            image = astronaut_bgr()
        else:
            upload = request.files.get("image")
            if upload is None or upload.filename == "":
                error = "Please choose an image file or use the sample."
            else:
                data = np.frombuffer(upload.read(), dtype=np.uint8)
                image = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if image is None:
                    error = "Could not decode the uploaded file as an image."

        if image is not None:
            faces, annotated_b64 = _detect_and_render(image)
            result = {
                "count": len(faces),
                "faces": [f.box for f in faces],
                "image_b64": annotated_b64,
            }

    return render_template("index.html", result=result, error=error)


@app.post("/api/detect")
def api_detect():
    """Detect faces in a posted frame; returns boxes in the frame's coordinates.

    Accepts either JSON ``{"image": "<data-url or base64>"}`` or a multipart
    ``image`` file. Used by the live camera view for per-frame detection.
    """

    image = None
    if request.is_json:
        image = _decode_data_url((request.get_json(silent=True) or {}).get("image", ""))
    elif "image" in request.files:
        data = np.frombuffer(request.files["image"].read(), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)

    if image is None:
        return jsonify(error="no valid image provided"), 400

    h, w = image.shape[:2]
    faces = detector.detect(image)
    return jsonify(
        count=len(faces),
        width=int(w),
        height=int(h),
        faces=[{"x": f.x, "y": f.y, "w": f.width, "h": f.height} for f in faces],
    )


@app.post("/api/capture")
def api_capture():
    """Detect faces in a posted frame, save the annotated image, return metadata."""

    payload = request.get_json(silent=True) or {}
    image = _decode_data_url(payload.get("image", ""))
    if image is None:
        return jsonify(error="no valid image provided"), 400

    faces = detector.detect(image)
    annotated = detector.annotate(image, faces)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"capture-{ts}-{int(time.time() * 1000) % 1000:03d}-{len(faces)}faces.png"
    path = os.path.join(CAPTURE_DIR, filename)
    if not cv2.imwrite(path, annotated):
        return jsonify(error="failed to save capture"), 500

    return jsonify(
        filename=filename,
        count=len(faces),
        url=url_for("serve_capture", filename=filename),
    )


def _list_captures() -> list[dict]:
    entries = []
    for name in os.listdir(CAPTURE_DIR):
        if not name.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        full = os.path.join(CAPTURE_DIR, name)
        entries.append({"name": name, "mtime": os.path.getmtime(full)})
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries


@app.get("/gallery")
def gallery():
    captures = [
        {"name": e["name"], "url": url_for("serve_capture", filename=e["name"])}
        for e in _list_captures()
    ]
    return render_template("gallery.html", captures=captures)


@app.get("/captures/<path:filename>")
def serve_capture(filename: str):
    safe = os.path.basename(filename)
    if safe != filename:
        abort(404)
    return send_from_directory(CAPTURE_DIR, safe)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
