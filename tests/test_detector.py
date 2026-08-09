import numpy as np
import pytest

from facial_rec import FaceDetector
from facial_rec.samples import astronaut_bgr


@pytest.fixture(scope="module")
def detector():
    return FaceDetector()


def test_detects_face_in_sample(detector):
    image = astronaut_bgr()
    faces = detector.detect(image)
    assert len(faces) >= 1
    face = faces[0]
    assert face.width > 0 and face.height > 0
    assert face.area > 0


def test_annotate_returns_bgr_image(detector):
    image = astronaut_bgr()
    faces = detector.detect(image)
    annotated = detector.annotate(image, faces)
    assert annotated.shape == image.shape
    assert annotated.ndim == 3 and annotated.shape[2] == 3


def test_blank_image_has_no_faces(detector):
    blank = np.zeros((200, 200, 3), dtype=np.uint8)
    assert detector.detect(blank) == []


def test_empty_image_raises(detector):
    with pytest.raises(ValueError):
        detector.detect(np.empty((0, 0), dtype=np.uint8))
