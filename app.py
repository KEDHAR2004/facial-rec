"""Flask web UI for the facial-rec toolkit.

Upload an image (or use the bundled sample) and the app runs OpenCV face
detection, then renders the annotated result inline.
"""

from __future__ import annotations

import base64

import cv2
import numpy as np
from flask import Flask, render_template, request

from facial_rec.detector import FaceDetector
from facial_rec.samples import astronaut_bgr

app = Flask(__name__)
detector = FaceDetector()


def _encode_png(image: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("failed to encode image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
