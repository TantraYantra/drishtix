"""Match a named person against already-indexed faces, without re-reading photos.

Every detected face carries a 512-dimensional AdaFace vector. Once one face is
named, the stored vectors are enough to find the same person in the rest of the
library: no image decode, no model download, no inference pass. Matching a
typical library therefore takes milliseconds instead of minutes.

A match is only labelled automatically when the *Automatic assignment* setting
is on, the score clears the auto threshold, and it also beats every other known
person by a safety margin. Everything else becomes a suggestion in Match Review,
so a look-alike can never silently steal a face.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app_paths import load_settings
from database import db

logger = logging.getLogger(__name__)

# Automatic labels must beat the runner-up person by this cosine margin.
AUTO_MARGIN = 0.08


def _unit_matrix(blobs: list[bytes]) -> np.ndarray | None:
    """Stack embeddings into a normalised matrix for fast cosine scoring."""
    vectors = []
    for blob in blobs:
        vector = np.frombuffer(blob, dtype=np.float32)
        if vector.size:
            vectors.append(vector)
    if not vectors:
        return None
    matrix = np.vstack(vectors).astype(np.float32, copy=False)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-8)


def match_person_across_library(person_id: int) -> dict[str, Any]:
    """Assign or queue every stored face that looks like ``person_id``.

    The returned counts let the caller report exactly what changed:

    ``compared``  unassigned faces with a usable vector,
    ``assigned``  faces labelled automatically,
    ``queued``    new suggestions written to Match Review.
    """
    settings = load_settings()
    auto_assign = bool(settings.get("auto_assign", False))
    auto_threshold = float(settings.get("auto_threshold", 0.52))
    review_threshold = float(settings.get("review_threshold", 0.38))

    person_vectors = _unit_matrix(db.person_embeddings(person_id))
    result: dict[str, Any] = {
        "person_id": int(person_id),
        "compared": 0,
        "assigned": 0,
        "queued": 0,
        "has_embeddings": person_vectors is not None,
    }
    if person_vectors is None:
        logger.info("Person %s has no stored face vectors to match", person_id)
        return result

    assign_ids: list[int] = []
    candidate_rows: list[tuple[int, int, float]] = []
    others: np.ndarray | None = None

    for face in db.unassigned_faces_with_embeddings():
        vector = np.frombuffer(face["embedding"], dtype=np.float32)
        if vector.size != person_vectors.shape[1]:
            continue
        result["compared"] += 1
        norm = float(np.linalg.norm(vector))
        if norm:
            vector = vector / norm
        score = float(np.max(person_vectors @ vector))
        if score < review_threshold:
            continue
        if auto_assign and score >= auto_threshold:
            if others is None:
                others = _unit_matrix(db.other_person_embeddings(person_id))
            best_other = float(np.max(others @ vector)) if others is not None else -1.0
            if score - best_other >= AUTO_MARGIN:
                assign_ids.append(int(face["id"]))
                continue
        candidate_rows.append((int(face["id"]), int(person_id), score))

    result["assigned"] = db.assign_faces(assign_ids, person_id)
    result["queued"] = db.add_candidates(candidate_rows)
    logger.info(
        "Matched person %s across %d stored faces: %d assigned, %d queued",
        person_id,
        result["compared"],
        result["assigned"],
        result["queued"],
    )
    return result
