"""Local folder scanner for DrishtiX.

The scanner deliberately persists each media record *before* running optional
face recognition. A missing model, an offline machine, or an inference error can
never prevent an indexed photo from appearing in the library.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from PIL import ExifTags, Image, ImageOps

from app_paths import (
    SETTINGS_PATH,
    VIDEO_THUMBNAILS_DIR,
    ensure_user_data,
    load_settings,
)
from core.recognition import extract_faces, similarity
from core.thumbnails import save_image_thumbnail
from database import db

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".webm"}
EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
IGNORED_FOLDERS = {
    ".venv", ".build-venv", "venv", "__pycache__", "node_modules",
    "dist", "build", "$recycle.bin", "system volume information",
}


class ScanCancelled(Exception):
    pass


def iter_images(folder: str | Path):
    """Yield supported media recursively in a stable order."""
    folder = Path(folder)
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(
            directory
            for directory in dirs
            if directory.lower() not in IGNORED_FOLDERS and not directory.startswith(".")
        )
        for name in sorted(names):
            if Path(name).suffix.lower() in EXTENSIONS:
                yield Path(root) / name


def _settings() -> dict[str, Any]:
    ensure_user_data()
    try:
        if SETTINGS_PATH.is_file():
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        logger.warning("Could not read recognition settings", exc_info=True)
    return load_settings()


def file_digest(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading a large video into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_image(path: Path, raw: bytes | None = None) -> tuple[np.ndarray | None, Image.Image | None]:
    """Decode an image safely, honouring EXIF orientation."""
    data = raw if raw is not None else path.read_bytes()
    try:
        with Image.open(io.BytesIO(data)) as opened:
            upright = ImageOps.exif_transpose(opened).convert("RGB")
            rgb = np.asarray(upright)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), upright
    except Exception:
        logger.debug("Pillow could not decode %s; trying OpenCV", path, exc_info=True)
    try:
        encoded = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is not None:
            height, width = image.shape[:2]
            return image, Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    except Exception:
        logger.warning("Could not decode image %s", path, exc_info=True)
    return None, None


def _exif_date(image: Image.Image) -> str | None:
    try:
        exif = image.getexif()
        tags = {ExifTags.TAGS.get(key, key): value for key, value in exif.items()}
        taken = tags.get("DateTimeOriginal") or tags.get("DateTime")
        if not taken:
            return None
        return datetime.strptime(str(taken), "%Y:%m:%d %H:%M:%S").isoformat(sep=" ")
    except (ValueError, OSError, AttributeError):
        return None


def _match_face(face_id: int, embedding: bytes) -> None:
    cfg = _settings()
    known = db.get_known_embeddings(exclude_face_id=face_id)
    best: dict[int, float] = {}
    for item in known:
        score = similarity(embedding, item["embedding"])
        person_id = item["person_id"]
        best[person_id] = max(best.get(person_id, 0.0), score)
    if not best:
        return
    ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
    person_id, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if (
        cfg.get("auto_assign", False)
        and score >= cfg.get("auto_threshold", 0.52)
        and score - second >= 0.08
    ):
        db.assign_face(face_id, person_id)
    elif score >= cfg.get("review_threshold", 0.38):
        db.create_candidate(face_id, person_id, score)


def _video_metadata(path: Path, digest: str) -> tuple[int | None, int | None, float | None, str | None, str | None]:
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        if not ok or frame is None:
            return None, None, None, None, "Could not read the first video frame"
        height, width = frame.shape[:2]
        fps = capture.get(cv2.CAP_PROP_FPS) or 0
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = (count / fps) if fps > 0 else None
        rgb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        library_thumb = save_image_thumbnail(rgb, digest)
        if library_thumb is not None:
            return width, height, duration, str(library_thumb), None
        VIDEO_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
        thumb_file = VIDEO_THUMBNAILS_DIR / f"{digest[:20]}.jpg"
        if cv2.imwrite(str(thumb_file), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
            return width, height, duration, str(thumb_file), None
        return width, height, duration, None, "Could not write a video thumbnail"
    finally:
        capture.release()


def scan_folder(
    folder: str | Path,
    progress: Callable[[int, int, str, int, int, int, int], None],
    should_cancel: Callable[[], bool],
) -> dict[str, Any]:
    folder = Path(folder).expanduser()
    scan_id = db.create_scan(str(folder))
    seen = face_count = skipped = errors = 0
    status = "completed"
    ai_warning: str | None = None
    ai_enabled = True
    ai_tried = False
    paths = list(iter_images(folder))
    total = max(1, len(paths))
    logger.info("Scanning %s (%d candidate media files)", folder, len(paths))

    try:
        for index, path in enumerate(paths, 1):
            if should_cancel():
                raise ScanCancelled()
            try:
                digest = file_digest(path)
                if db.photo_hash_exists(digest):
                    skipped += 1
                    progress(index, total, path.name, seen, face_count, skipped, errors)
                    continue

                media_type = "video" if path.suffix.lower() in VIDEO_EXTENSIONS else "image"
                width = height = None
                duration = None
                thumb_path = None
                exif_date = None
                image_bgr = None

                if media_type == "video":
                    width, height, duration, thumb_path, video_error = _video_metadata(path, digest)
                    if video_error:
                        errors += 1
                        logger.warning("[DrishtiX scan] %s: %s", path, video_error)
                        progress(index, total, path.name, seen, face_count, skipped, errors)
                        continue
                else:
                    raw = path.read_bytes()
                    image_bgr, pil_image = _read_image(path, raw)
                    if image_bgr is None or pil_image is None:
                        errors += 1
                        logger.warning("[DrishtiX scan] Could not decode image: %s", path)
                        progress(index, total, path.name, seen, face_count, skipped, errors)
                        continue
                    height, width = image_bgr.shape[:2]
                    exif_date = _exif_date(pil_image)
                    cached_thumb = save_image_thumbnail(pil_image, digest)
                    thumb_path = str(cached_thumb) if cached_thumb else None

                # Persist first. AI/model failures must never hide a photo.
                photo_id = db.add_photo(
                    str(path),
                    digest,
                    width,
                    height,
                    path.stat().st_mtime,
                    media_type,
                    duration,
                    thumb_path,
                )
                if exif_date:
                    db.set_photo_date(photo_id, exif_date)

                if media_type == "video":
                    db.set_photo_category(photo_id, "Video")
                else:
                    db.set_photo_category(photo_id, classify_photo(path, width, height, 0))
                    found_faces = []
                    # Attempt face detection on every file. A transient model
                    # failure on one photo must never disable AI for the rest.
                    try:
                        found_faces = extract_faces(image_bgr)
                        ai_tried = True
                    except RuntimeError as exc:
                        ai_tried = True
                        ai_enabled = False
                        ai_warning = (
                            "Face recognition is unavailable for this scan. Your photos "
                            "were still indexed. Details: " + str(exc)
                        )
                        logger.warning("[DrishtiX AI unavailable] %s", exc)
                    except Exception as exc:
                        ai_tried = True
                        errors += 1
                        logger.warning(
                            "[DrishtiX face detection] %s: %s", path, exc, exc_info=True
                        )
                    for box, embedding, det_score in found_faces:
                        try:
                            face_id = db.add_face(photo_id, embedding, box, det_score)
                            face_count += 1
                            _match_face(face_id, embedding)
                        except Exception as exc:
                            errors += 1
                            logger.warning(
                                "[DrishtiX face processing] %s: %s", path, exc, exc_info=True
                            )
                    if found_faces:
                        db.set_photo_category(photo_id, "People")

                seen += 1
            except ScanCancelled:
                raise
            except Exception as exc:
                errors += 1
                logger.warning(
                    "[DrishtiX scan error] %s: %s", path, exc, exc_info=True
                )
            progress(index, total, path.name, seen, face_count, skipped, errors)
    except ScanCancelled:
        status = "cancelled"
        logger.info("Scan cancelled by the user")
    except Exception as exc:
        status = "failed"
        logger.exception("Scan failed")
        ai_warning = ai_warning or f"Scan failed: {exc}"
    finally:
        try:
            db.finish_scan(scan_id, seen, face_count, skipped, errors, status)
        except Exception:
            logger.exception("Could not record scan history")

    result = {
        "seen": seen,
        "faces": face_count,
        "skipped": skipped,
        "errors": errors,
        "status": status,
        "total": len(paths),
        "folder": str(folder),
        "ai_warning": ai_warning,
        "ai_attempted": ai_tried,
    }
    logger.info("Scan finished: %s", result)
    return result


def classify_photo(path: str | Path, width: int, height: int, face_count: int = 0) -> str:
    """Conservative local categorization; not semantic scene understanding."""
    name = Path(path).name.lower()
    if any(keyword in name for keyword in ("screenshot", "screen shot", "capture", "snip")):
        return "Screenshot"
    if face_count:
        return "People"
    return "No-face image"


def _box_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


def reindex_existing(
    progress: Callable[[int, int, str, int, int, int, int], None] | None = None,
    should_cancel: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Rebuild face embeddings, preserving confirmed labels by box overlap.

    Videos are handled by extracting the first frame and running face detection
    on it, so videos indexed before AI was available are not skipped.
    """
    paths = db.all_photos(include_archived=True, include_deleted=True)
    total = max(1, len(paths))
    done = faces = errors = 0
    ai_warning: str | None = None
    rebuilt_face_ids: list[tuple[int, bytes]] = []
    ai_enabled = True

    for index, row in enumerate(paths, 1):
        if should_cancel():
            break
        try:
            if row.get("media_type") == "video":
                # Extract first frame for face detection on reindex.
                try:
                    capture = cv2.VideoCapture(str(row["path"]))
                    ok, frame = capture.read()
                    capture.release()
                    if ok and frame is not None:
                        found = extract_faces(frame)
                    else:
                        found = []
                except Exception as exc:
                    ai_enabled = False
                    ai_warning = f"Face recognition is unavailable: {exc}"
                    logger.warning("[DrishtiX reindex] AI unavailable: %s", exc)
                    found = []
                done += 1
                if progress:
                    progress(index, total, row["path"], done, faces, 0, errors)
                continue
            raw = Path(row["path"]).read_bytes()
            image, _ = _read_image(Path(row["path"]), raw)
            if image is None:
                errors += 1
                if progress:
                    progress(index, total, row["path"], done, faces, 0, errors)
                continue
            old_faces = db.faces_for_photo(row["id"])
            found = []
            if ai_enabled:
                try:
                    found = extract_faces(image)
                except Exception as exc:
                    ai_enabled = False
                    ai_warning = f"Face recognition is unavailable: {exc}"
                    logger.warning("[DrishtiX reindex] AI unavailable: %s", exc)
                    break
            db.delete_faces_for_photo(row["id"])
            restored: set[int] = set()
            for box, embedding, score in found:
                face_id = db.add_face(row["id"], embedding, box, score)
                faces += 1
                rebuilt_face_ids.append((face_id, embedding))
                candidates = [
                    (old, _box_iou(box, (old["x"], old["y"], old["w"], old["h"])))
                    for old in old_faces
                    if old.get("person_id") and old["id"] not in restored
                ]
                if candidates:
                    old, overlap = max(candidates, key=lambda item: item[1])
                    if overlap >= 0.30:
                        db.assign_face(face_id, old["person_id"])
                        restored.add(old["id"])
            db.set_photo_category(
                row["id"],
                "People"
                if found
                else classify_photo(Path(row["path"]), image.shape[1], image.shape[0], 0),
            )
            done += 1
        except Exception as exc:
            errors += 1
            logger.warning("[DrishtiX reindex] %s: %s", row["path"], exc, exc_info=True)
        if progress:
            progress(index, total, row["path"], done, faces, 0, errors)

    if done == len(paths) and errors == 0 and not should_cancel():
        unassigned_ids = {row["id"] for row in db.unassigned_face_embeddings()}
        for face_id, embedding in rebuilt_face_ids:
            if face_id in unassigned_ids:
                try:
                    _match_face(face_id, embedding)
                except Exception as exc:
                    errors += 1
                    logger.warning(
                        "[DrishtiX matching] face %s: %s", face_id, exc, exc_info=True
                    )
    return {
        "seen": done,
        "faces": faces,
        "errors": errors,
        "status": "cancelled" if should_cancel() else "completed",
        "ai_warning": ai_warning,
        "total": len(paths),
    }
