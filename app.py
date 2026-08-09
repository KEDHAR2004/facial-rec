"""Flask web app: live webcam / image-upload face analysis with enrollment."""

from __future__ import annotations

import base64

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request

from facerec import FaceEngine

app = Flask(__name__)
engine = FaceEngine()


def _decode_image(req) -> np.ndarray | None:
    """Accept an image as a multipart file ("image") or base64 JSON ("image")."""
    if "image" in req.files:
        data = req.files["image"].read()
    else:
        payload = req.get_json(silent=True) or {}
        b64 = payload.get("image", "")
        if "," in b64:  # strip data-URL prefix
            b64 = b64.split(",", 1)[1]
        try:
            data = base64.b64decode(b64)
        except Exception:
            return None
    if not data:
        return None
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return img


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/analyze")
def analyze():
    img = _decode_image(request)
    if img is None:
        return jsonify({"error": "No valid image provided."}), 400

    results = engine.analyze(img)
    response: dict = {
        "faces": [r.to_dict() for r in results],
        "persons": engine.persons,
    }

    want_annotated = request.args.get("annotated") == "1"
    if want_annotated:
        annotated = FaceEngine.annotate(img, results)
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            response["annotated"] = "data:image/jpeg;base64," + base64.b64encode(
                buf.tobytes()
            ).decode()
    return jsonify(response)


@app.post("/api/enroll")
def enroll():
    img = _decode_image(request)
    if img is None:
        return jsonify({"error": "No valid image provided."}), 400
    name = (request.args.get("name") or "").strip() or None
    if name is None:
        payload = request.get_json(silent=True) or {}
        name = (payload.get("name") or "").strip() or None
    try:
        assigned = engine.enroll(img, name)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify({"enrolled": assigned, "persons": engine.persons})


@app.get("/api/persons")
def persons():
    return jsonify({"persons": engine.persons, "auto_enroll": engine.auto_enroll})


@app.delete("/api/persons/<name>")
def delete_person(name: str):
    if not engine.remove_person(name):
        return jsonify({"error": f"Unknown person: {name}"}), 404
    return jsonify({"persons": engine.persons})


@app.post("/api/reset")
def reset():
    engine.reset()
    return jsonify({"persons": engine.persons})


@app.post("/api/settings")
def settings():
    payload = request.get_json(silent=True) or {}
    if "auto_enroll" in payload:
        engine.auto_enroll = bool(payload["auto_enroll"])
    return jsonify({"auto_enroll": engine.auto_enroll})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
