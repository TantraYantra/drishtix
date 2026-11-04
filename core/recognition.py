"""Local face detection + AdaFace embeddings through UniFace.

AdaFace IR-18 produces normalized 512-dimensional embeddings. RetinaFace
provides five-point landmarks so faces can be aligned before recognition.
All inference is local; model files are downloaded on first use.
"""
from __future__ import annotations

import os
from pathlib import Path

# Keep model weights in the user's writable application-data directory.
# Set this before importing UniFace because its model store reads the
# environment variable during initialization.
_local_app_data = os.environ.get("LOCALAPPDATA")
if _local_app_data:
    _model_cache = Path(_local_app_data) / "TantraYantra" / "DrishtiX" / "models"
else:
    _model_cache = Path.home() / ".local" / "share" / "TantraYantra" / "DrishtiX" / "models"
_model_cache.mkdir(parents=True, exist_ok=True)
os.environ["UNIFACE_CACHE_DIR"] = str(_model_cache)

import numpy as np

_DETECTOR = None
_RECOGNIZER = None
_INIT_ERROR = None


def get_engine():
    """Initialize the CPU detector and AdaFace recognizer once."""
    global _DETECTOR, _RECOGNIZER, _INIT_ERROR
    if _DETECTOR is not None and _RECOGNIZER is not None:
        return _DETECTOR, _RECOGNIZER
    if _INIT_ERROR:
        raise RuntimeError(_INIT_ERROR)
    try:
        from uniface.detection import RetinaFace
        from uniface.recognition import AdaFace
        _DETECTOR = RetinaFace(providers=["CPUExecutionProvider"])
        # IR-18 is the lightweight 92 MB variant; IR-50/101 are larger.
        _RECOGNIZER = AdaFace(providers=["CPUExecutionProvider"])
        return _DETECTOR, _RECOGNIZER
    except Exception as exc:
        _INIT_ERROR = (
            f"Could not initialize AdaFace: {exc}. Install requirements and "
            "check your internet connection for the first model download."
        )
        raise RuntimeError(_INIT_ERROR) from exc


def extract_faces(image):
    """Return [(box, normalized 512-D embedding bytes, detector_score), ...]."""
    detector, recognizer = get_engine()
    detections = detector.detect(image)
    output = []
    for face in detections:
        box = np.asarray(face.bbox, dtype=np.float32).reshape(-1)
        if box.size < 4:
            continue
        x1, y1, x2, y2 = [int(round(v)) for v in box[:4]]
        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(image.shape[1], x2); y2 = min(image.shape[0], y2)
        if x2 <= x1 or y2 <= y1:
            continue
        landmarks = getattr(face, "landmarks", None)
        if landmarks is None:
            continue
        embedding = np.asarray(
            recognizer.get_normalized_embedding(image, landmarks), dtype=np.float32
        ).reshape(-1)
        if embedding.size != 512:
            continue
        norm = float(np.linalg.norm(embedding))
        if norm <= 1e-8:
            continue
        embedding = embedding / norm
        score = getattr(face, "confidence", getattr(face, "score", 0.0))
        output.append(((x1, y1, x2 - x1, y2 - y1), embedding.tobytes(), float(score)))
    return output


def detect_faces(image):
    return [box for box, _, _ in extract_faces(image)]


def make_embedding(image, box):
    x, y, w, h = box
    candidates = extract_faces(image)
    if not candidates:
        return None
    target = np.array([x, y, x + w, y + h], dtype=float)
    best = min(candidates, key=lambda item: np.linalg.norm(
        np.array([item[0][0], item[0][1], item[0][0] + item[0][2],
                  item[0][1] + item[0][3]]) - target))
    return best[1]


def similarity(blob_a, blob_b):
    a = np.frombuffer(blob_a, dtype=np.float32)
    b = np.frombuffer(blob_b, dtype=np.float32)
    if a.shape != b.shape or a.size == 0:
        return 0.0
    return float(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8), -1.0, 1.0))
