"""Small, cached thumbnails for the library grid.

Full-size photos are never decoded repeatedly on the UI thread. During a scan a
thumbnail is generated once; older library records are upgraded lazily the
first time they are displayed. The cache lives under the user's application
data folder and can be deleted safely at any time.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app_paths import THUMBNAILS_DIR, ensure_user_data

logger = logging.getLogger(__name__)

# 2x the on-screen tile for crisp rendering at Windows display scaling.
DEFAULT_SIZE = (520, 360)


def _key(photo: dict[str, Any], size: tuple[int, int]) -> str:
    identity = (
        photo.get("file_hash")
        or f"{photo.get('path')}|{photo.get('modified')}|{photo.get('media_type')}"
    )
    payload = f"{identity}|{size[0]}x{size[1]}".encode("utf-8", "replace")
    return hashlib.sha1(payload).hexdigest()


def cache_path(photo: dict[str, Any], size: tuple[int, int] = DEFAULT_SIZE) -> Path:
    ensure_user_data()
    return THUMBNAILS_DIR / f"{_key(photo, size)}.jpg"


def _save_atomic(image: Image.Image, destination: Path, quality: int = 87) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    image.save(temporary, "JPEG", quality=quality, optimize=True)
    os.replace(temporary, destination)
    return destination


def fit_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Center-crop and resize without distorting the source image."""
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))


def save_image_thumbnail(
    image: Image.Image,
    identity: str,
    size: tuple[int, int] = DEFAULT_SIZE,
) -> Path | None:
    """Save a thumbnail from an already-decoded image (used by the scanner)."""
    try:
        payload = f"{identity}|{size[0]}x{size[1]}".encode("utf-8", "replace")
        name = hashlib.sha1(payload).hexdigest() + ".jpg"
        return _save_atomic(fit_image(image, size), THUMBNAILS_DIR / name)
    except (OSError, ValueError):
        logger.warning("Could not create a library thumbnail", exc_info=True)
        return None


def _first_video_frame(path: Path) -> Image.Image | None:
    try:
        import cv2

        capture = cv2.VideoCapture(str(path))
        try:
            ok, frame = capture.read()
            if not ok or frame is None:
                return None
            return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        finally:
            capture.release()
    except Exception:
        logger.warning("Could not read a video frame from %s", path, exc_info=True)
        return None


def ensure_thumbnail(
    photo: dict[str, Any],
    size: tuple[int, int] = DEFAULT_SIZE,
) -> Path | None:
    """Return a cached JPEG thumbnail, generating it from the source if needed."""
    destination = cache_path(photo, size)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination

    source: Path | None = None
    if photo.get("media_type") == "video":
        candidate = photo.get("thumbnail_path")
        if candidate and Path(candidate).is_file():
            source = Path(candidate)
        else:
            original = Path(str(photo.get("path") or ""))
            image = _first_video_frame(original) if original.is_file() else None
            if image is not None:
                return save_image_thumbnail(image, str(photo.get("file_hash") or original), size)
            return None
    else:
        candidate = Path(str(photo.get("path") or ""))
        if candidate.is_file():
            source = candidate

    if source is None:
        return None
    try:
        with Image.open(source) as opened:
            image = fit_image(opened, size)
        return _save_atomic(image, destination)
    except (OSError, ValueError):
        logger.warning("Could not generate thumbnail for %s", source, exc_info=True)
        return None


def crop_face(photo_path: str, box: tuple[int, int, int, int], size: int = 160) -> Image.Image | None:
    """Load a face crop for People and Unassigned Faces cards."""
    try:
        with Image.open(photo_path) as opened:
            x, y, w, h = box
            image = ImageOps.exif_transpose(opened).convert("RGB")
            # Add a little breathing room around the detected box.
            pad = int(max(w, h) * 0.18)
            crop = image.crop(
                (
                    max(0, x - pad),
                    max(0, y - pad),
                    min(image.width, x + w + pad),
                    min(image.height, y + h + pad),
                )
            )
            return ImageOps.fit(crop, (size, size), method=Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        logger.warning("Could not crop face from %s", photo_path, exc_info=True)
        return None
