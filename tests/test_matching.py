"""Instant cross-photo matching tests.

Naming one face must find the same person elsewhere using the vectors stored
during the scan — no image decoding, no model download, no re-index. These
tests use a temporary library and never touch real user data.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_ROOT = Path(tempfile.mkdtemp(prefix="peoplelens-match-"))
os.environ["LOCALAPPDATA"] = str(TEMP_ROOT)

import numpy as np  # noqa: E402

from app_paths import save_settings  # noqa: E402
from core import matching  # noqa: E402
from database import db  # noqa: E402


def vector(**weights: float) -> bytes:
    data = np.zeros(512, dtype=np.float32)
    for index, value in weights.items():
        data[int(index)] = value
    data /= np.linalg.norm(data)
    return data.tobytes()


def main() -> None:
    db.init_db()
    save_settings(
        {"auto_assign": False, "auto_threshold": 0.52, "review_threshold": 0.38}
    )

    photos = {
        index: db.add_photo(
            f"C:/match/{index}.jpg", f"match-{index}", 400, 400, 1.0
        )
        for index in range(6)
    }

    maya = db.create_person("Maya")
    anchor_embedding = vector(**{"0": 1.0})
    anchor = db.add_face(photos[0], anchor_embedding, (10, 10, 90, 90), 0.99)
    db.assign_face(anchor, maya)

    twin = db.add_face(photos[1], anchor_embedding, (10, 10, 90, 90), 0.98)
    lookalike = db.add_face(
        photos[2], vector(**{"0": 1.0, "1": 0.6}), (10, 10, 90, 90), 0.95
    )
    stranger = db.add_face(
        photos[3], vector(**{"2": 1.0}), (10, 10, 90, 90), 0.91
    )
    archived_face = db.add_face(photos[5], anchor_embedding, (10, 10, 90, 90), 0.97)
    db.set_archived(photos[5], True)

    # Default settings: suggestions only, never silent labels.
    result = matching.match_person_across_library(maya)
    assert result["compared"] == 3, result  # archived photo is excluded
    assert result["assigned"] == 0, result
    assert result["queued"] == 2, result
    pending = {row["face_id"] for row in db.pending_candidates()}
    assert twin in pending, "an identical face must be suggested"
    assert lookalike in pending, "a close face must be suggested"
    assert stranger not in pending, "an unrelated face must be ignored"
    assert archived_face not in pending, "archived photos are not queued"

    # Automatic assignment: high-confidence faces are labelled, stale
    # suggestions for those faces disappear.
    save_settings(
        {"auto_assign": True, "auto_threshold": 0.52, "review_threshold": 0.38}
    )
    result = matching.match_person_across_library(maya)
    assert result["assigned"] == 2, result
    assert result["queued"] == 0, result
    remaining = {row["face_id"] for row in db.pending_candidates()}
    assert not remaining, f"assigned faces left stale suggestions: {remaining}"
    with db.connect() as con:
        owners = {
            row[0]: row[1]
            for row in con.execute(
                "SELECT id,person_id FROM faces WHERE id IN (?,?)", (twin, lookalike)
            ).fetchall()
        }
    assert owners == {twin: maya, lookalike: maya}, owners

    # A look-alike person must not steal a face that already matches someone
    # else: the margin check queues it instead of assigning it.
    ana = db.create_person("Ana")
    ana_anchor = db.add_face(photos[0], anchor_embedding, (110, 10, 90, 90), 0.99)
    db.assign_face(ana_anchor, ana)
    contested = db.add_face(photos[4], anchor_embedding, (10, 10, 90, 90), 0.96)
    result = matching.match_person_across_library(ana)
    assert result["assigned"] == 0, "a tie between two people must be reviewed"
    assert result["queued"] == 1, result
    with db.connect() as con:
        owner = con.execute(
            "SELECT person_id FROM faces WHERE id=?", (contested,)
        ).fetchone()[0]
    assert owner is None, "the contested face must stay unassigned until reviewed"

    # Bulk confirmation labels every visible suggestion in one transaction.
    confirmed, assigned = db.confirm_all_pending_candidates()
    assert (confirmed, assigned) == (1, 1), (confirmed, assigned)
    with db.connect() as con:
        owner = con.execute(
            "SELECT person_id FROM faces WHERE id=?", (contested,)
        ).fetchone()[0]
    assert owner == ana, owner
    assert not db.pending_candidates(), "bulk confirmation must clear the queue"

    print("PeopleLens matching tests passed.")


if __name__ == "__main__":
    main()
