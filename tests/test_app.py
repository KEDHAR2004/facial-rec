import base64

import cv2
import pytest

import app as webapp
from facial_rec.samples import astronaut_bgr


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolate captures to a temp dir so tests never touch the real gallery.
    monkeypatch.setattr(webapp, "CAPTURE_DIR", str(tmp_path))
    webapp.app.config.update(TESTING=True)
    return webapp.app.test_client()


def _sample_data_url() -> str:
    ok, buf = cv2.imencode(".png", astronaut_bgr())
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_api_detect_finds_face(client):
    resp = client.post("/api/detect", json={"image": _sample_data_url()})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] >= 1
    assert data["width"] > 0 and data["height"] > 0
    assert len(data["faces"]) == data["count"]
    f = data["faces"][0]
    assert {"x", "y", "w", "h"} <= set(f)


def test_api_detect_rejects_bad_input(client):
    resp = client.post("/api/detect", json={"image": "not-base64!!!"})
    assert resp.status_code == 400


def test_api_capture_saves_file(client, tmp_path):
    resp = client.post("/api/capture", json={"image": _sample_data_url()})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] >= 1
    assert data["filename"].endswith(".png")
    saved = list(tmp_path.iterdir())
    assert len(saved) == 1
    # Saved capture is served back and is a valid image.
    served = client.get(data["url"])
    assert served.status_code == 200


def test_gallery_lists_capture(client):
    client.post("/api/capture", json={"image": _sample_data_url()})
    resp = client.get("/gallery")
    assert resp.status_code == 200
    assert b"capture-" in resp.data


def test_index_sample_post(client):
    resp = client.post("/", data={"use_sample": "1"})
    assert resp.status_code == 200
    assert b"face(s) detected" in resp.data
