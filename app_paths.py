"""Centralised paths and small persistence helpers for PeopleLens.

Installed application assets stay beside the executable (inside PyInstaller's
bundle directory). Mutable user data lives under
``%LOCALAPPDATA%\\TantraYantra\\PeopleLens`` on Windows so the app keeps working
when it is installed somewhere read-only such as ``Program Files``.

The functions in this module never delete user photos or overwrite an existing
user database.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

APP_NAME = "PeopleLens"
COMPANY_NAME = "TantraYantra"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Your Photos. Your People. Your Memories."

# Assets bundled with the application. In a PyInstaller onedir build this is
# the ``_internal`` directory that contains the collected ``assets`` folder.
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
EXE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else APP_DIR
IS_FROZEN = bool(getattr(sys, "frozen", False))

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "Dark",
    "auto_assign": False,
    "review_threshold": 0.38,
    "auto_threshold": 0.52,
    "group_by_month": True,
}

logger = logging.getLogger(__name__)


def get_user_data_dir() -> Path:
    """Return the per-user writable data directory for PeopleLens."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / COMPANY_NAME / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / COMPANY_NAME / APP_NAME
    return Path.home() / ".local" / "share" / COMPANY_NAME / APP_NAME


USER_DATA_DIR = get_user_data_dir()
SETTINGS_PATH = USER_DATA_DIR / "settings.json"
DATABASE_PATH = USER_DATA_DIR / "peoplelens.db"
VIDEO_THUMBNAILS_DIR = USER_DATA_DIR / "video_thumbnails"
THUMBNAILS_DIR = USER_DATA_DIR / "thumbnails"
MODELS_DIR = USER_DATA_DIR / "models"
BACKUPS_DIR = USER_DATA_DIR / "backups"
LOG_PATH = USER_DATA_DIR / "peoplelens.log"


def asset_path(*parts: str) -> Path:
    """Resolve a bundled asset path without relying on the current directory."""
    return APP_DIR.joinpath("assets", *parts)


def ensure_user_data() -> Path:
    """Create the user-data folders and migrate legacy project-local data once.

    A legacy file is copied only when its destination does not already exist.
    Existing user data is never overwritten.
    """
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for folder in (VIDEO_THUMBNAILS_DIR, THUMBNAILS_DIR, MODELS_DIR, BACKUPS_DIR):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Could not create data folder: %s", folder, exc_info=True)

    legacy_dir = APP_DIR / "data"
    if legacy_dir.is_dir() and legacy_dir != USER_DATA_DIR:
        for name in ("settings.json", "peoplelens.db"):
            source = legacy_dir / name
            destination = USER_DATA_DIR / name
            if source.is_file() and not destination.exists():
                try:
                    shutil.copy2(source, destination)
                    logger.info("Migrated legacy %s to %s", name, destination)
                except OSError:
                    logger.warning("Could not migrate legacy %s", source, exc_info=True)
        old_thumbnails = legacy_dir / "video_thumbnails"
        if old_thumbnails.is_dir():
            for item in old_thumbnails.iterdir():
                target = VIDEO_THUMBNAILS_DIR / item.name
                if item.is_file() and not target.exists():
                    try:
                        shutil.copy2(item, target)
                    except OSError:
                        logger.warning("Could not migrate thumbnail %s", item, exc_info=True)
    return USER_DATA_DIR


def load_settings() -> dict[str, Any]:
    """Load settings, merging them with safe defaults."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_PATH.is_file():
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                settings.update(raw)
    except (OSError, ValueError, TypeError):
        logger.warning("settings.json could not be read; using defaults", exc_info=True)
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    """Atomically save settings so a crash cannot leave a half-written file."""
    ensure_user_data()
    temporary = SETTINGS_PATH.with_suffix(".json.tmp")
    payload = json.dumps(settings, indent=2, ensure_ascii=False)
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, SETTINGS_PATH)


def get_version() -> str:
    """Read the bundled VERSION file, falling back to the code constant."""
    try:
        version = (APP_DIR / "VERSION").read_text(encoding="utf-8").strip()
        if version:
            return version
    except OSError:
        pass
    return APP_VERSION


def format_timestamp(value: str | None, fallback: str = "") -> str:
    """Format an ISO-ish database timestamp for display."""
    if not value:
        return fallback
    text = str(value).replace("T", " ")
    return text[:16]


def human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def utc_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")
