"""Isolated scanner integration tests.

Run with the project interpreter:

    python tests/test_scanner.py

Covers the full All Photos workflow (decode -> persist -> thumbnail -> query ->
restart), duplicate handling, AI failure isolation, cancellation and video
metadata. No real user data or AI models are used.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from core import scanner, thumbnails  # noqa: E402
from database import db  # noqa: E402


def make_images(folder: Path, count: int) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        image = Image.new(
            "RGB",
            (320, 240),
            ((index * 37) % 255, (index * 91) % 255, (index * 53) % 255),
        )
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((40 + index, 40, 120 + index, 130), fill=(240, 225, 200))
        path = folder / f"photo_{index:02d}.jpg"
        image.save(path, quality=88)
        paths.append(path)
    return paths


def fake_faces(_image):
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1.0
    return [((40, 40, 90, 90), vector.tobytes(), 0.99)]


def main() -> None:
    temporary = tempfile.TemporaryDirectory(prefix="peoplelens-scan-")
    original_db = db.DB_PATH
    original_backups = db.BACKUPS_DIR
    original_thumbs = thumbnails.THUMBNAILS_DIR
    original_video_thumbs = scanner.VIDEO_THUMBNAILS_DIR
    original_settings = scanner._settings
    original_extract = scanner.extract_faces
    try:
        root = Path(temporary.name)
        db.DB_PATH = root / "peoplelens.db"
        db.BACKUPS_DIR = root / "backups"
        thumbnails.THUMBNAILS_DIR = root / "thumbnails"
        scanner.VIDEO_THUMBNAILS_DIR = root / "video_thumbnails"
        thumbnails.THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
        scanner.VIDEO_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
        db.init_db()

        settings = {"auto_assign": False, "review_threshold": 0.38, "auto_threshold": 0.52}
        scanner._settings = lambda: settings
        scanner.extract_faces = fake_faces

        photos = make_images(root / "photos", 28)
        (root / "photos" / "notes.txt").write_text("ignored", encoding="utf-8")

        progress_events = []
        result = scanner.scan_folder(
            root / "photos",
            lambda *args: progress_events.append(args),
            lambda: False,
        )
        assert result["status"] == "completed", result
        assert result["seen"] == 28, result
        assert result["faces"] == 28, result
        assert result["errors"] == 0, result
        assert result["skipped"] == 0, result
        assert result["ai_warning"] is None, result
        assert len(progress_events) == 28, progress_events

        rows = db.all_photos()
        assert len(rows) == 28, len(rows)
        assert {row["category"] for row in rows} == {"People"}
        assert all(Path(row["path"]).is_file() for row in rows)
        assert all(row["thumbnail_path"] for row in rows)

        stats = db.stats()
        assert stats["photos"] == 28 and stats["faces"] == 28, stats

        # The library must survive a completely fresh connection.
        assert db.stats()["photos"] == 28
        assert len(db.all_photos()) == 28

        # A second scan sees only duplicates and does not duplicate rows.
        second = scanner.scan_folder(
            root / "photos",
            lambda *args: None,
            lambda: False,
        )
        assert second["seen"] == 0, second
        assert second["skipped"] == 28, second
        assert len(db.all_photos()) == 28
        latest = db.history(1)[0]
        assert latest["status"] == "completed"
        assert latest["skipped"] == 28, latest

        # AI failure must never prevent indexing.
        db.DB_PATH = root / "ai_failure.db"
        db.init_db()
        make_images(root / "ai_photos", 5)

        def fail_ai(_image):
            raise RuntimeError("model unavailable in test")

        scanner.extract_faces = fail_ai
        failed = scanner.scan_folder(
            root / "ai_photos",
            lambda *args: None,
            lambda: False,
        )
        assert failed["status"] == "completed", failed
        assert failed["seen"] == 5, failed
        assert failed["faces"] == 0, failed
        assert failed["errors"] == 0, failed
        assert failed["ai_attempted"] is True
        assert failed["ai_warning"] and "unavailable" in failed["ai_warning"]
        assert len(db.all_photos()) == 5

        # Cancellation records history and keeps already-indexed items.
        db.DB_PATH = root / "cancel.db"
        db.init_db()
        make_images(root / "cancel_photos", 10)
        scanner.extract_faces = fake_faces
        calls = {"count": 0}

        def should_cancel() -> bool:
            calls["count"] += 1
            return calls["count"] > 3

        cancelled = scanner.scan_folder(
            root / "cancel_photos",
            lambda *args: None,
            should_cancel,
        )
        assert cancelled["status"] == "cancelled", cancelled
        assert 0 < cancelled["seen"] < 10, cancelled
        assert db.history(1)[0]["status"] == "cancelled"

        # Video indexing reads metadata and a first-frame thumbnail.
        db.DB_PATH = root / "video.db"
        db.init_db()
        video_dir = root / "videos"
        video_dir.mkdir(parents=True)
        video_path = video_dir / "clip.avi"
        import cv2

        writer = cv2.VideoWriter(
            str(video_path),
            cv2.VideoWriter_fourcc(*"MJPG"),
            12.0,
            (160, 120),
        )
        if writer.isOpened():
            for index in range(12):
                frame = np.zeros((120, 160, 3), dtype=np.uint8)
                frame[:, :, 1] = 20 + index * 15
                writer.write(frame)
            writer.release()
            video_result = scanner.scan_folder(
                video_dir,
                lambda *args: None,
                lambda: False,
            )
            assert video_result["seen"] == 1, video_result
            assert video_result["errors"] == 0, video_result
            video_row = db.all_photos()[0]
            assert video_row["media_type"] == "video", video_row
            assert video_row["category"] == "Video", video_row
            assert video_row["duration"] and video_row["duration"] > 0, video_row
            assert video_row["thumbnail_path"] and Path(video_row["thumbnail_path"]).is_file()
            assert db.stats()["videos"] == 1
        else:
            writer.release()
            print("Video codec unavailable; skipped the video sub-test.")

        print("PeopleLens scanner integration tests passed.")
    finally:
        db.DB_PATH = original_db
        db.BACKUPS_DIR = original_backups
        thumbnails.THUMBNAILS_DIR = original_thumbs
        scanner.VIDEO_THUMBNAILS_DIR = original_video_thumbs
        scanner._settings = original_settings
        scanner.extract_faces = original_extract
        temporary.cleanup()


if __name__ == "__main__":
    main()
