"""Core face analysis engine.

Pipeline for every frame/image:
  1. Detect faces with YuNet (bounding box + 5 landmarks).
  2. Align each face and compute a 128-d SFace embedding.
  3. Match the embedding against the enrolled-person database
     (cosine similarity). Unknown faces can be auto-enrolled as
     "Person 1", "Person 2", ...
  4. Classify the facial expression across 8 classes (neutral,
     happiness, surprise, sadness, anger, disgust, fear, contempt)
     using an ensemble of two models: HSEmotion (EfficientNet-B0
     trained on AffectNet) and FER+. The ensemble is markedly more
     sensitive to non-neutral expressions than either model alone.
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
EMOTION_MODEL_2 = MODELS_DIR / "enet_b0_8_best_vgaf.onnx"

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
# Output order of the HSEmotion (AffectNet) model.
_ENET_LABELS = (
    "anger",
    "contempt",
    "disgust",
    "fear",
    "happiness",
    "neutral",
    "sadness",
    "surprise",
)
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
# Ensemble weight for HSEmotion vs FER+ (tuned on a labeled test set).
_ENET_WEIGHT = 0.6

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
        for model in (
            DETECTOR_MODEL,
            RECOGNIZER_MODEL,
            EMOTION_MODEL,
            EMOTION_MODEL_2,
        ):
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
        self._emotion_net2 = cv2.dnn.readNetFromONNX(str(EMOTION_MODEL_2))

        self.match_threshold = match_threshold
        self.auto_enroll = auto_enroll
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        # Serializes OpenCV net inference, which is not thread-safe.
        self._infer_lock = threading.Lock()
        # name -> list of embeddings (each a 128-d list of floats)
        self._db: dict[str, list[list[float]]] = {}
        self._db_stamp: tuple[int, int] = (0, 0)  # (mtime_ns, size)
        self._load_db()

    # ------------------------------------------------------------------
    # Person database
    #
    # The database lives in a JSON file so that multiple server processes
    # (e.g. gunicorn workers) share one source of truth: every write is
    # atomic, and readers reload whenever the file changes on disk.
    # ------------------------------------------------------------------
    def _file_stamp(self) -> tuple[int, int]:
        st = self._db_path.stat()
        return (st.st_mtime_ns, st.st_size)

    def _load_db(self) -> None:
        if self._db_path.exists():
            self._db = json.loads(self._db_path.read_text())
            self._db_stamp = self._file_stamp()

    def _maybe_reload_db(self) -> None:
        """Pick up changes written by other processes. Lock held by caller."""
        try:
            stamp = self._file_stamp()
        except OSError:
            return
        if stamp != self._db_stamp:
            try:
                self._db = json.loads(self._db_path.read_text())
                self._db_stamp = stamp
            except (OSError, json.JSONDecodeError):
                pass  # concurrent write in progress; next call will retry

    def _save_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._db_path.with_name(self._db_path.name + ".tmp")
        tmp.write_text(json.dumps(self._db))
        tmp.replace(self._db_path)
        try:
            self._db_stamp = self._file_stamp()
        except OSError:
            pass

    @property
    def persons(self) -> dict[str, int]:
        """Enrolled persons mapped to their number of face samples."""
        with self._lock:
            self._maybe_reload_db()
            return {name: len(embs) for name, embs in self._db.items()}

    def remove_person(self, name: str) -> bool:
        with self._lock:
            self._maybe_reload_db()
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
        query = embedding.flatten().astype(np.float32)
        qnorm = np.linalg.norm(query) or 1.0
        best_name, best_sim = "Unknown", 0.0
        for name, embeddings in self._db.items():
            for stored in embeddings:
                vec = np.asarray(stored, dtype=np.float32)
                sim = float(
                    np.dot(query, vec) / (qnorm * (np.linalg.norm(vec) or 1.0))
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
        with self._infer_lock:
            h, w = image.shape[:2]
            self._detector.setInputSize((w, h))
            _, faces = self._detector.detect(image)
        return faces if faces is not None else np.empty((0, 15), dtype=np.float32)

    def _embed(self, image: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        with self._infer_lock:
            aligned = self._recognizer.alignCrop(image, face_row)
            return self._recognizer.feature(aligned)

    @staticmethod
    def _crop(
        image: np.ndarray, box: tuple[int, int, int, int], pad_frac: float
    ) -> np.ndarray:
        x, y, w, h = box
        pad = int(pad_frac * max(w, h))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(image.shape[1], x + w + pad), min(image.shape[0], y + h + pad)
        return image[y0:y1, x0:x1]

    @staticmethod
    def _softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
        scaled = logits / temperature
        exp = np.exp(scaled - scaled.max())
        return exp / exp.sum()

    def _classify_expression(
        self, image: np.ndarray, box: tuple[int, int, int, int]
    ) -> tuple[str, dict[str, float]]:
        """Ensemble of HSEmotion (AffectNet) and FER+ probabilities.

        A softmax temperature > 1 softens the distributions so secondary
        expressions keep visible (non-zero) percentages; the top prediction
        of each model is unaffected.
        """
        temperature = 2.0
        crop = self._crop(image, box, 0.05)
        if crop.size == 0:
            return "unknown", {}

        # HSEmotion: 224x224 RGB, ImageNet normalization.
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        rgb = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA)
        blob = (rgb.astype(np.float32) / 255.0 - _IMAGENET_MEAN) / _IMAGENET_STD

        # FER+: 64x64 grayscale on a slightly looser crop.
        fer_crop = self._crop(image, box, 0.1)
        gray = cv2.cvtColor(fer_crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)

        with self._infer_lock:
            self._emotion_net2.setInput(blob.transpose(2, 0, 1)[None])
            enet_logits = self._emotion_net2.forward().flatten()
            self._emotion_net.setInput(gray.astype(np.float32).reshape(1, 1, 64, 64))
            fer_logits = self._emotion_net.forward().flatten()

        enet_probs = dict(zip(_ENET_LABELS, self._softmax(enet_logits, temperature)))
        fer_probs = dict(zip(EMOTIONS, self._softmax(fer_logits, temperature)))

        scores = {
            label: float(
                _ENET_WEIGHT * enet_probs[label]
                + (1.0 - _ENET_WEIGHT) * fer_probs[label]
            )
            for label in EMOTIONS
        }
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
                self._maybe_reload_db()
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
            self._maybe_reload_db()
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
