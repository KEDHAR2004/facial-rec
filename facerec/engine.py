"""Core face analysis engine.

Pipeline for every frame/image:
  1. Detect faces with YuNet (bounding box + 5 landmarks).
  2. Align each face and compute a 128-d SFace embedding.
  3. Match the embedding against the enrolled-person database
     (cosine similarity). Unknown faces can be auto-enrolled as
     "Person 1", "Person 2", ...
  4. Classify the facial expression with the FER+ model
     (8 classes: neutral, happiness, surprise, sadness, anger,
     disgust, fear, contempt).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
DETECTOR_MODEL = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
RECOGNIZER_MODEL = MODELS_DIR / "face_recognition_sface_2021dec.onnx"
EMOTION_MODEL = MODELS_DIR / "emotion-ferplus-8.onnx"

EMOTIONS = (
    "neutral",
    "happiness",
    "surprise",
    "sadness",
    "anger",
    "disgust",
    "fear",
    "contempt",
)

# Recommended cosine-similarity threshold for SFace (OpenCV Zoo).
COSINE_THRESHOLD = 0.363


@dataclass
class FaceResult:
    """Analysis result for a single detected face."""

    box: tuple[int, int, int, int]  # x, y, w, h
    landmarks: list[tuple[int, int]]
    detection_score: float
    name: str  # matched person or "Unknown"
    similarity: float  # cosine similarity to the matched person
    expression: str
    expression_scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "box": list(self.box),
            "landmarks": [list(p) for p in self.landmarks],
            "detection_score": round(self.detection_score, 3),
            "name": self.name,
            "similarity": round(self.similarity, 3),
            "expression": self.expression,
            "expression_scores": {
                k: round(v, 3) for k, v in self.expression_scores.items()
            },
        }


class FaceEngine:
    """Face detection + person recognition + expression analysis."""

    def __init__(
        self,
        db_path: str | Path = "data/faces_db.json",
        match_threshold: float = COSINE_THRESHOLD,
        auto_enroll: bool = False,
    ) -> None:
        for model in (DETECTOR_MODEL, RECOGNIZER_MODEL, EMOTION_MODEL):
            if not model.exists():
                raise FileNotFoundError(
                    f"Missing model {model.name}. "
                    "Run: python scripts/download_models.py"
                )

        self._detector = cv2.FaceDetectorYN.create(
            str(DETECTOR_MODEL), "", (320, 320), score_threshold=0.6
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(RECOGNIZER_MODEL), "")
        self._emotion_net = cv2.dnn.readNetFromONNX(str(EMOTION_MODEL))

        self.match_threshold = match_threshold
        self.auto_enroll = auto_enroll
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        # name -> list of embeddings (each a 128-d list of floats)
        self._db: dict[str, list[list[float]]] = {}
        self._load_db()

    # ------------------------------------------------------------------
    # Person database
    # ------------------------------------------------------------------
    def _load_db(self) -> None:
        if self._db_path.exists():
            self._db = json.loads(self._db_path.read_text())

    def _save_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path.write_text(json.dumps(self._db))

    @property
    def persons(self) -> dict[str, int]:
        """Enrolled persons mapped to their number of face samples."""
        with self._lock:
            return {name: len(embs) for name, embs in self._db.items()}

    def remove_person(self, name: str) -> bool:
        with self._lock:
            if name not in self._db:
                return False
            del self._db[name]
            self._save_db()
            return True

    def reset(self) -> None:
        with self._lock:
            self._db = {}
            self._save_db()

    def _next_auto_name(self) -> str:
        n = 1
        while f"Person {n}" in self._db:
            n += 1
        return f"Person {n}"

    def _enroll_embedding(self, embedding: np.ndarray, name: str | None) -> str:
        """Store an embedding under `name` (auto-named if None). Lock held by caller."""
        if not name:
            name = self._next_auto_name()
        self._db.setdefault(name, []).append(
            [float(x) for x in embedding.flatten()]
        )
        self._save_db()
        return name

    def _match_embedding(self, embedding: np.ndarray) -> tuple[str, float]:
        """Return (best matching person, cosine similarity). Lock held by caller."""
        best_name, best_sim = "Unknown", 0.0
        for name, embeddings in self._db.items():
            for stored in embeddings:
                sim = float(
                    self._recognizer.match(
                        embedding,
                        np.asarray(stored, dtype=np.float32).reshape(1, -1),
                        cv2.FaceRecognizerSF_FR_COSINE,
                    )
                )
                if sim > best_sim:
                    best_name, best_sim = name, sim
        if best_sim < self.match_threshold:
            return "Unknown", best_sim
        return best_name, best_sim

    # ------------------------------------------------------------------
    # Per-face helpers
    # ------------------------------------------------------------------
    def _detect(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(image)
        return faces if faces is not None else np.empty((0, 15), dtype=np.float32)

    def _embed(self, image: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        aligned = self._recognizer.alignCrop(image, face_row)
        return self._recognizer.feature(aligned)

    def _classify_expression(
        self, image: np.ndarray, box: tuple[int, int, int, int]
    ) -> tuple[str, dict[str, float]]:
        x, y, w, h = box
        # Expand the crop slightly; FER+ was trained on loose face crops.
        pad = int(0.1 * max(w, h))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(image.shape[1], x + w + pad), min(image.shape[0], y + h + pad)
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            return "unknown", {}

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
        blob = gray.astype(np.float32).reshape(1, 1, 64, 64)
        self._emotion_net.setInput(blob)
        logits = self._emotion_net.forward().flatten()

        exp = np.exp(logits - logits.max())
        probs = exp / exp.sum()
        scores = {label: float(p) for label, p in zip(EMOTIONS, probs)}
        top = max(scores, key=scores.get)
        return top, scores

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze(self, image: np.ndarray) -> list[FaceResult]:
        """Detect, identify and classify every face in a BGR image."""
        results: list[FaceResult] = []
        for face_row in self._detect(image):
            x, y, w, h = (int(v) for v in face_row[:4])
            x, y = max(0, x), max(0, y)
            landmarks = [
                (int(face_row[4 + 2 * i]), int(face_row[5 + 2 * i]))
                for i in range(5)
            ]
            embedding = self._embed(image, face_row)

            with self._lock:
                name, similarity = self._match_embedding(embedding)
                if name == "Unknown" and self.auto_enroll:
                    name = self._enroll_embedding(embedding, None)
                    similarity = 1.0

            expression, scores = self._classify_expression(image, (x, y, w, h))
            results.append(
                FaceResult(
                    box=(x, y, w, h),
                    landmarks=landmarks,
                    detection_score=float(face_row[14]),
                    name=name,
                    similarity=similarity,
                    expression=expression,
                    expression_scores=scores,
                )
            )
        return results

    def enroll(self, image: np.ndarray, name: str | None = None) -> str:
        """Enroll the most prominent face in the image.

        Returns the person's name ("Person N" when auto-named).
        Raises ValueError when no face is found.
        """
        faces = self._detect(image)
        if len(faces) == 0:
            raise ValueError("No face detected in the enrollment image.")
        # Most prominent face = largest bounding-box area.
        largest = max(faces, key=lambda f: float(f[2]) * float(f[3]))
        embedding = self._embed(image, largest)
        with self._lock:
            return self._enroll_embedding(embedding, name)

    @staticmethod
    def annotate(image: np.ndarray, results: list[FaceResult]) -> np.ndarray:
        """Draw boxes, names and expressions onto a copy of the image."""
        out = image.copy()
        for r in results:
            x, y, w, h = r.box
            known = r.name != "Unknown"
            color = (80, 200, 80) if known else (60, 76, 231)
            cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
            for px, py in r.landmarks:
                cv2.circle(out, (px, py), 2, (255, 200, 0), -1)

            conf = r.expression_scores.get(r.expression, 0.0)
            label = f"{r.name}  |  {r.expression} {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            ty = y - 8 if y - 8 > th else y + h + th + 8
            cv2.rectangle(
                out, (x, ty - th - 4), (x + tw + 6, ty + 4), color, -1
            )
            cv2.putText(
                out,
                label,
                (x + 3, ty),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        return out
