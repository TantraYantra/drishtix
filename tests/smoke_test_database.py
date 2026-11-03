"""Isolated database smoke test.

Run from anywhere with the project's Python interpreter:

    python tests/smoke_test_database.py

The test never touches the real user library. It points the data layer at a
temporary database and verifies persistence, filters, albums, people, search
and cascading cleanup.
"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402


def embedding(seed: float) -> bytes:
    return struct.pack("8f", *([seed] * 8))


def main() -> None:
    temporary = tempfile.TemporaryDirectory(prefix="peoplelens-db-")
    original_db = db.DB_PATH
    original_backups = db.BACKUPS_DIR
    try:
        root = Path(temporary.name)
        db.DB_PATH = root / "peoplelens.db"
        db.BACKUPS_DIR = root / "backups"
        db.init_db()

        info = db.database_info(check_integrity=True)
        assert info["version"] == db.SCHEMA_VERSION, info
        assert info["integrity"] == "ok", info

        image_id = db.add_photo(
            "C:/Photos/beach_2025.jpg", "test-image", 1200, 800, 1.0
        )
        video_id = db.add_photo(
            "C:/Videos/family.mp4", "test-video", 1920, 1080, 2.0, "video", 12.5
        )
        assert db.add_photo(
            "C:/Photos/beach_2025.jpg", "test-image", 1200, 800, 1.0
        ) == image_id, "re-scanning the same path must not create a duplicate"

        db.set_photo_category(image_id, "People")
        db.set_photo_date(image_id, "2025-06-14 10:30:00")
        db.toggle_favorite(image_id)
        db.add_photo(
            "C:/Photos/beach_2025.jpg", "test-image", 1200, 800, 1.0
        )
        preserved = db.photo_by_id(image_id)
        assert preserved["category"] == "People"
        assert preserved["date_taken"] == "2025-06-14 10:30:00"
        assert preserved["is_favorite"] == 1

        stats = db.stats()
        assert stats["photos"] == 2, stats
        assert stats["images"] == 1, stats
        assert stats["videos"] == 1, stats
        assert stats["archived"] == 0 and stats["trash"] == 0, stats

        album_id = db.create_album("Family")
        db.album_add_photo(album_id, image_id)
        db.album_add_photo(album_id, video_id)
        db.set_album_cover(album_id, video_id)
        assert db.albums_list()[0]["display_cover"] == video_id
        assert len(db.all_photos(album_id=album_id, include_archived=True)) == 2

        db.album_remove_photo(album_id, video_id)
        remaining = db.albums_list()[0]
        assert remaining["item_count"] == 1
        assert remaining["display_cover"] == image_id, "cover falls back to remaining item"
        assert len(db.all_photos(album_id=album_id, include_archived=True)) == 1

        person_id = db.create_person("Maya")
        face_id = db.add_face(image_id, embedding(0.5), (10, 10, 80, 80), 0.99)
        db.assign_face(face_id, person_id)
        assert db.people_list()[0]["photo_count"] == 1
        assert db.person_photos(person_id)[0]["id"] == image_id
        assert db.person_cover_face(person_id)["path"] == "C:/Photos/beach_2025.jpg"

        assert [row["id"] for row in db.smart_search("Maya")] == [image_id]
        assert [row["id"] for row in db.smart_search("favorite")] == [image_id]
        assert [row["id"] for row in db.smart_search("video")] == [video_id]
        assert [row["id"] for row in db.smart_search("beach")] == [image_id]

        db.set_archived(video_id, True)
        assert [row["id"] for row in db.all_photos()] == [image_id]
        assert {row["id"] for row in db.all_photos(include_archived=True)} == {
            image_id,
            video_id,
        }
        db.set_archived(video_id, False)

        db.move_to_trash(video_id)
        assert [row["id"] for row in db.all_photos(trash_only=True)] == [video_id]
        db.restore_photo(video_id)
        assert db.photo_flags(video_id)["deleted_at"] is None

        candidate_id = db.create_candidate(face_id, person_id, 0.61)
        pending = db.pending_candidates()
        assert pending, "a pending candidate should be visible"
        candidate_id = pending[0]["candidate_id"]
        db.create_candidate(face_id, person_id, 0.61)  # duplicate is ignored
        assert len(db.pending_candidates()) == 1
        db.decide_candidate(candidate_id, True)
        with db.connect() as con:
            assigned = con.execute(
                "SELECT person_id FROM faces WHERE id=?", (face_id,)
            ).fetchone()[0]
        assert assigned == person_id

        # Deleting the index record must cascade to faces, candidates and album items.
        db.permanently_delete_photo(image_id)
        assert db.photo_by_id(image_id) is None
        with db.connect() as con:
            assert con.execute("SELECT COUNT(*) FROM faces").fetchone()[0] == 0
            assert con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0
            assert con.execute("SELECT COUNT(*) FROM album_items").fetchone()[0] == 0

        # Re-open the same file and confirm the video record persisted.
        reopened = db.all_photos(include_archived=True)
        assert [row["id"] for row in reopened] == [video_id]
        print("PeopleLens database smoke tests passed.")
    finally:
        db.DB_PATH = original_db
        db.BACKUPS_DIR = original_backups
        temporary.cleanup()


if __name__ == "__main__":
    main()
