"""Face detection using OpenCV's bundled Haar cascade classifier.

The default frontal-face cascade ships with the ``opencv-python-headless``
wheel, so detection works fully offline without downloading model weights.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class DetectedFace:
    """A single detected face as an axis-aligned bounding box."""

    x: int
    y: int
    width: int
    height: int

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    @property
    def area(self) -> int:
        return self.width * self.height


class FaceDetector:
    """Detects frontal faces in images using a Haar cascade classifier."""

    def __init__(self, cascade_path: str | None = None) -> None:
        if cascade_path is None:
            cascade_path = os.path.join(
                cv2.data.haarcascades, "haarcascade_frontalface_default.xml"
            )
        if not os.path.exists(cascade_path):
            raise FileNotFoundError(f"Haar cascade not found at {cascade_path!r}")

        self.cascade_path = cascade_path
        self._classifier = cv2.CascadeClassifier(cascade_path)
        if self._classifier.empty():
            raise RuntimeError(f"Failed to load Haar cascade from {cascade_path!r}")

    def detect(
        self,
        image: np.ndarray,
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        min_size: tuple[int, int] = (30, 30),
    ) -> list[DetectedFace]:
        """Return the faces detected in ``image`` (a BGR or grayscale array)."""

        if image is None or image.size == 0:
            raise ValueError("image is empty")

        gray = self._to_gray(image)
        gray = cv2.equalizeHist(gray)

        detections = self._classifier.detectMultiScale(
            gray,
            scaleFactor=scale_factor,
            minNeighbors=min_neighbors,
            minSize=min_size,
        )
        return [DetectedFace(int(x), int(y), int(w), int(h)) for (x, y, w, h) in detections]

    @staticmethod
    def _to_gray(image: np.ndarray) -> np.ndarray:
        if image.ndim == 2:
            return image
        if image.ndim == 3 and image.shape[2] == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if image.ndim == 3 and image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        raise ValueError(f"Unsupported image shape: {image.shape}")

    @staticmethod
    def annotate(
        image: np.ndarray,
        faces: list[DetectedFace],
        color: tuple[int, int, int] = (0, 200, 0),
        thickness: int = 3,
    ) -> np.ndarray:
        """Return a copy of ``image`` with rectangles drawn around each face."""

        annotated = image.copy()
        if annotated.ndim == 2:
            annotated = cv2.cvtColor(annotated, cv2.COLOR_GRAY2BGR)

        for i, face in enumerate(faces, start=1):
            x, y, w, h = face.box
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, thickness)
            label = f"face {i}"
            cv2.putText(
                annotated,
                label,
                (x, max(y - 10, 15)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                color,
                2,
                cv2.LINE_AA,
            )
        return annotated
