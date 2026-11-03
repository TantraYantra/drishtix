"""SQLite data access for PeopleLens.

All modules share the same database path from :mod:`app_paths`. The schema is
created and migrated in place, with a safety backup before an upgrade. User
photos are never copied, moved, or deleted by this module.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from app_paths import BACKUPS_DIR, DATABASE_PATH, ensure_user_data

SCHEMA_VERSION = 3
logger = logging.getLogger(__name__)

# Keep DB_PATH as a module-level variable so isolated tests can override it.
ensure_user_data()
DB_PATH: Path = DATABASE_PATH


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a short-lived connection with consistent safety settings.

    Every caller uses ``with connect() as con``. SQLite's own connection context
    manager commits but does not close the handle, so this wrapper closes it on
    exit; otherwise a long-running UI session leaks handles and locks the WAL
    files on Windows.
    """
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 8000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _database_version(conn: sqlite3.Connection) -> int:
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    except (sqlite3.DatabaseError, TypeError, IndexError):
        return 0


def _backup_database() -> Path | None:
    """Create a consistent backup before migrating an existing user database."""
    path = Path(DB_PATH)
    if not path.is_file() or path.stat().st_size == 0:
        return None
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = BACKUPS_DIR / f"peoplelens-{stamp}.db"
    try:
        source = sqlite3.connect(str(path), timeout=15)
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        backups = sorted(
            (item for item in BACKUPS_DIR.glob("peoplelens-*.db") if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old in backups[5:]:
            try:
                old.unlink()
            except OSError:
                logger.warning("Could not remove old backup %s", old, exc_info=True)
        return destination
    except (sqlite3.DatabaseError, OSError):
        logger.warning("Database backup failed; continuing without one", exc_info=True)
        try:
            if destination.exists():
                destination.unlink()
        except OSError:
            pass
        return None


def init_db() -> None:
    """Create or migrate the local database without losing existing data."""
    ensure_user_data()
    path = Path(DB_PATH)
    existing = path.is_file() and path.stat().st_size > 0
    version = 0
    if existing:
        try:
            with connect() as probe:
                version = _database_version(probe)
        except sqlite3.DatabaseError:
            logger.exception("Could not read the existing PeopleLens database")
            raise
    if existing and version < SCHEMA_VERSION:
        backup = _backup_database()
        if backup:
            logger.info("Database backup written to %s", backup)

    with connect() as con:
        try:
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.DatabaseError:
            logger.warning("WAL mode is unavailable for this database location", exc_info=True)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS photos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                file_hash TEXT NOT NULL,
                width INTEGER, height INTEGER, modified REAL,
                scanned_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS people(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS faces(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
                person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
                embedding BLOB NOT NULL,
                x INTEGER NOT NULL, y INTEGER NOT NULL, w INTEGER NOT NULL, h INTEGER NOT NULL,
                confidence REAL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                face_id INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
                person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                similarity REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                UNIQUE(face_id, person_id)
            );
            CREATE TABLE IF NOT EXISTS confirmations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                face_id INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
                person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                confirmed INTEGER NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scan_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT, folder TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT,
                photos_seen INTEGER DEFAULT 0, faces_found INTEGER DEFAULT 0,
                skipped INTEGER DEFAULT 0, errors INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            );
            CREATE TABLE IF NOT EXISTS albums(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                cover_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS album_items(
                album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
                photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
                added_at TEXT NOT NULL,
                PRIMARY KEY(album_id, photo_id)
            );
            """
        )
        cols = {row[1] for row in con.execute("PRAGMA table_info(photos)").fetchall()}
        migrations = {
            "category": "TEXT DEFAULT 'Unclassified'",
            "date_taken": "TEXT",
            "is_favorite": "INTEGER NOT NULL DEFAULT 0",
            "is_archived": "INTEGER NOT NULL DEFAULT 0",
            "deleted_at": "TEXT",
            "media_type": "TEXT NOT NULL DEFAULT 'image'",
            "duration": "REAL",
            "thumbnail_path": "TEXT",
        }
        for name, declaration in migrations.items():
            if name not in cols:
                con.execute(f"ALTER TABLE photos ADD COLUMN {name} {declaration}")
        con.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
            CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
            CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
            CREATE INDEX IF NOT EXISTS idx_album_items_photo ON album_items(photo_id);
            CREATE INDEX IF NOT EXISTS idx_photos_hash ON photos(file_hash);
            CREATE INDEX IF NOT EXISTS idx_photos_media ON photos(media_type);
            CREATE INDEX IF NOT EXISTS idx_photos_scanned ON photos(scanned_at);
            CREATE INDEX IF NOT EXISTS idx_photos_deleted ON photos(deleted_at);
            """
        )
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        logger.info("PeopleLens database ready at %s", DB_PATH)


def database_info(check_integrity: bool = False) -> dict[str, Any]:
    """Return diagnostics used by Settings and the About page."""
    path = Path(DB_PATH)
    info: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "size": path.stat().st_size if path.is_file() else 0,
        "version": 0,
        "integrity": "not checked",
    }
    if path.is_file():
        try:
            with connect() as con:
                info["version"] = _database_version(con)
                if check_integrity:
                    result = con.execute("PRAGMA quick_check").fetchone()
                    info["integrity"] = str(result[0]) if result else "unknown"
                else:
                    info["integrity"] = "available"
        except sqlite3.DatabaseError as exc:
            info["integrity"] = f"error: {exc}"
    return info


def set_photo_category(photo_id: int, category: str) -> None:
    with connect() as con:
        con.execute("UPDATE photos SET category=? WHERE id=?", (category, photo_id))


def set_photo_date(photo_id: int, date_taken: str | None) -> None:
    with connect() as con:
        con.execute("UPDATE photos SET date_taken=? WHERE id=?", (date_taken, photo_id))


def set_photo_thumbnail(photo_id: int, thumbnail_path: str | None) -> None:
    with connect() as con:
        con.execute("UPDATE photos SET thumbnail_path=? WHERE id=?", (thumbnail_path, photo_id))


def toggle_favorite(photo_id: int) -> None:
    with connect() as con:
        con.execute(
            "UPDATE photos SET is_favorite=CASE WHEN is_favorite=1 THEN 0 ELSE 1 END WHERE id=?",
            (photo_id,),
        )


def set_archived(photo_id: int, archived: bool = True) -> None:
    with connect() as con:
        con.execute("UPDATE photos SET is_archived=? WHERE id=?", (1 if archived else 0, photo_id))


def move_to_trash(photo_id: int) -> None:
    with connect() as con:
        con.execute(
            "UPDATE photos SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), photo_id),
        )


def restore_photo(photo_id: int) -> None:
    with connect() as con:
        con.execute("UPDATE photos SET deleted_at=NULL WHERE id=?", (photo_id,))


def permanently_delete_photo(photo_id: int) -> None:
    """Remove a record from the PeopleLens index. The original file is untouched."""
    with connect() as con:
        con.execute("DELETE FROM photos WHERE id=?", (photo_id,))


def photo_flags(photo_id: int) -> dict[str, Any]:
    with connect() as con:
        row = con.execute(
            "SELECT is_favorite,is_archived,deleted_at FROM photos WHERE id=?", (photo_id,)
        ).fetchone()
        return dict(row) if row else {}


def photo_by_id(photo_id: int) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        return dict(row) if row else None


def photo_by_path(path: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM photos WHERE path=?", (str(path),)).fetchone()
        return dict(row) if row else None


def photos_by_ids(ids: Iterable[int]) -> list[dict[str, Any]]:
    ids = [int(value) for value in ids]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with connect() as con:
        rows = con.execute(
            f"SELECT * FROM photos WHERE id IN ({placeholders})", ids
        ).fetchall()
        return [dict(row) for row in rows]


def faces_for_photo(photo_id: int) -> list[dict[str, Any]]:
    with connect() as con:
        return [
            dict(row)
            for row in con.execute(
                "SELECT id,person_id,x,y,w,h FROM faces WHERE photo_id=?", (photo_id,)
            ).fetchall()
        ]


def delete_faces_for_photo(photo_id: int) -> None:
    with connect() as con:
        con.execute(
            "DELETE FROM candidates WHERE face_id IN (SELECT id FROM faces WHERE photo_id=?)",
            (photo_id,),
        )
        con.execute(
            "DELETE FROM confirmations WHERE face_id IN (SELECT id FROM faces WHERE photo_id=?)",
            (photo_id,),
        )
        con.execute("DELETE FROM faces WHERE photo_id=?", (photo_id,))


def stats() -> dict[str, Any]:
    with connect() as con:
        row = con.execute(
            """
            SELECT
              SUM(CASE WHEN deleted_at IS NULL AND is_archived=0 THEN 1 ELSE 0 END) AS photos,
              SUM(CASE WHEN deleted_at IS NULL AND is_archived=0 AND COALESCE(media_type,'image')='image' THEN 1 ELSE 0 END) AS images,
              SUM(CASE WHEN deleted_at IS NULL AND is_archived=0 AND media_type='video' THEN 1 ELSE 0 END) AS videos,
              SUM(CASE WHEN deleted_at IS NULL AND is_archived=1 THEN 1 ELSE 0 END) AS archived,
              SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS trash
            FROM photos
            """
        ).fetchone()
        result = {key: int(row[key] or 0) for key in row.keys()}
        result["faces"] = con.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
        result["people"] = con.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        result["pending"] = con.execute(
            "SELECT COUNT(*) FROM candidates WHERE status='pending'"
        ).fetchone()[0]
        result["albums"] = con.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
        last = con.execute(
            "SELECT * FROM scan_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        result["last_scan"] = dict(last) if last else None
        return result


def create_scan(folder: str) -> int:
    with connect() as con:
        cursor = con.execute(
            "INSERT INTO scan_history(folder,started_at) VALUES(?,?)",
            (str(folder), datetime.now().isoformat(timespec="seconds")),
        )
        return int(cursor.lastrowid)


def finish_scan(
    scan_id: int,
    seen: int,
    faces: int,
    skipped: int,
    errors: int,
    status: str = "completed",
) -> None:
    with connect() as con:
        con.execute(
            "UPDATE scan_history SET finished_at=?,photos_seen=?,faces_found=?,"
            "skipped=?,errors=?,status=? WHERE id=?",
            (
                datetime.now().isoformat(timespec="seconds"),
                seen,
                faces,
                skipped,
                errors,
                status,
                scan_id,
            ),
        )


def add_photo(
    path: str,
    file_hash: str,
    width: int | None,
    height: int | None,
    modified: float | None,
    media_type: str = "image",
    duration: float | None = None,
    thumbnail_path: str | None = None,
) -> int:
    """Insert a new media record or refresh an existing record at the same path."""
    with connect() as con:
        con.execute(
            """
            INSERT INTO photos(path,file_hash,width,height,modified,scanned_at,
                               media_type,duration,thumbnail_path)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                file_hash=excluded.file_hash,
                width=excluded.width,
                height=excluded.height,
                modified=excluded.modified,
                scanned_at=excluded.scanned_at,
                media_type=excluded.media_type,
                duration=excluded.duration,
                thumbnail_path=COALESCE(excluded.thumbnail_path, photos.thumbnail_path)
            """,
            (
                str(path),
                file_hash,
                width,
                height,
                modified,
                datetime.now().isoformat(timespec="seconds"),
                media_type,
                duration,
                thumbnail_path,
            ),
        )
        row = con.execute("SELECT id FROM photos WHERE path=?", (str(path),)).fetchone()
        return int(row[0])


def photo_hash_exists(file_hash: str) -> bool:
    with connect() as con:
        return (
            con.execute("SELECT 1 FROM photos WHERE file_hash=? LIMIT 1", (file_hash,)).fetchone()
            is not None
        )


def photo_by_hash(file_hash: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM photos WHERE file_hash=? LIMIT 1", (file_hash,)).fetchone()
        return dict(row) if row else None


def add_face(
    photo_id: int,
    embedding: bytes,
    box: tuple[int, int, int, int],
    confidence: float | None = None,
) -> int:
    x, y, w, h = [int(value) for value in box]
    with connect() as con:
        cursor = con.execute(
            "INSERT INTO faces(photo_id,embedding,x,y,w,h,confidence,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                photo_id,
                sqlite3.Binary(embedding),
                x,
                y,
                w,
                h,
                confidence,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return int(cursor.lastrowid)


def unassigned_face_embeddings() -> list[dict[str, Any]]:
    with connect() as con:
        return [
            dict(row)
            for row in con.execute("SELECT id,embedding FROM faces WHERE person_id IS NULL").fetchall()
        ]


def get_known_embeddings(exclude_face_id: int | None = None) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT f.id,f.person_id,f.embedding,p.name FROM faces f "
            "JOIN people p ON p.id=f.person_id"
        ).fetchall()
        return [dict(row) for row in rows if row["id"] != exclude_face_id]


def person_embeddings(person_id: int) -> list[bytes]:
    """Stored face vectors for one named person (already normalised)."""
    with connect() as con:
        return [
            bytes(row["embedding"])
            for row in con.execute(
                "SELECT embedding FROM faces WHERE person_id=?", (person_id,)
            ).fetchall()
        ]


def other_person_embeddings(person_id: int) -> list[bytes]:
    """Vectors for everyone *except* this person, used for tie-breaking."""
    with connect() as con:
        return [
            bytes(row["embedding"])
            for row in con.execute(
                "SELECT embedding FROM faces WHERE person_id IS NOT NULL AND person_id<>?",
                (person_id,),
            ).fetchall()
        ]


def unassigned_faces_with_embeddings() -> list[dict[str, Any]]:
    """Unassigned faces in visible photos, with the vector needed to match them."""
    with connect() as con:
        return [
            dict(row)
            for row in con.execute(
                """
                SELECT f.id,f.embedding
                FROM faces f JOIN photos ph ON ph.id=f.photo_id
                WHERE f.person_id IS NULL
                  AND ph.deleted_at IS NULL AND ph.is_archived=0
                """
            ).fetchall()
        ]


def assign_faces(face_ids: Iterable[int], person_id: int) -> int:
    """Assign many faces at once and drop their now-stale suggestions."""
    payload = [(int(person_id), int(face_id)) for face_id in face_ids]
    if not payload:
        return 0
    with connect() as con:
        cursor = con.executemany(
            "UPDATE faces SET person_id=? WHERE id=?", payload
        )
        con.executemany(
            "DELETE FROM candidates WHERE face_id=? AND status='pending'",
            [(face_id,) for _, face_id in payload],
        )
        assigned = cursor.rowcount
    return assigned if assigned and assigned > 0 else 0


def add_candidates(rows: Iterable[tuple[int, int, float]]) -> int:
    """Queue possible matches in one transaction; duplicates are ignored."""
    payload = [
        (int(face_id), int(person_id), float(score), datetime.now().isoformat(timespec="seconds"))
        for face_id, person_id, score in rows
    ]
    if not payload:
        return 0
    with connect() as con:
        cursor = con.executemany(
            "INSERT OR IGNORE INTO candidates(face_id,person_id,similarity,status,created_at) "
            "VALUES(?,?,?,'pending',?)",
            payload,
        )
        queued = cursor.rowcount
    return queued if queued and queued > 0 else 0


def create_candidate(face_id: int, person_id: int, similarity: float) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO candidates(face_id,person_id,similarity,status,created_at) "
            "VALUES(?,?,?,'pending',?)",
            (
                face_id,
                person_id,
                float(similarity),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def pending_candidates() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT c.id candidate_id,c.face_id,c.person_id,c.similarity,
                   p.name person_name,ph.path photo_path,f.x,f.y,f.w,f.h
            FROM candidates c
            JOIN people p ON p.id=c.person_id
            JOIN faces f ON f.id=c.face_id
            JOIN photos ph ON ph.id=f.photo_id
            WHERE c.status='pending' AND ph.deleted_at IS NULL AND ph.is_archived=0
            ORDER BY c.created_at
            """
        ).fetchall()
        return [dict(row) for row in rows]


def decide_candidate(candidate_id: int, yes: bool) -> None:
    with connect() as con:
        row = con.execute(
            "SELECT face_id,person_id FROM candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if not row:
            return
        con.execute(
            "UPDATE candidates SET status=? WHERE id=?",
            ("confirmed" if yes else "rejected", candidate_id),
        )
        con.execute(
            "INSERT INTO confirmations(face_id,person_id,confirmed,created_at) VALUES(?,?,?,?)",
            (
                row["face_id"],
                row["person_id"],
                1 if yes else 0,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        if yes:
            con.execute(
                "UPDATE faces SET person_id=? WHERE id=?",
                (row["person_id"], row["face_id"]),
            )


def people_list(search: str = "") -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT p.id,p.name,p.created_at,
                   COUNT(DISTINCT f.photo_id) photo_count,
                   COUNT(f.id) face_count
            FROM people p
            LEFT JOIN faces f ON f.person_id=p.id
            WHERE p.name LIKE ?
            GROUP BY p.id
            ORDER BY p.name COLLATE NOCASE
            """,
            (f"%{search}%",),
        ).fetchall()
        return [dict(row) for row in rows]


def person_cover_face(person_id: int) -> dict[str, Any] | None:
    """Return one face crop for a person's avatar."""
    with connect() as con:
        row = con.execute(
            """
            SELECT f.id face_id,ph.path,f.x,f.y,f.w,f.h
            FROM faces f JOIN photos ph ON ph.id=f.photo_id
            WHERE f.person_id=? AND ph.deleted_at IS NULL AND ph.is_archived=0
            ORDER BY f.id LIMIT 1
            """,
            (person_id,),
        ).fetchone()
        return dict(row) if row else None


def create_person(name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Please enter a name.")
    with connect() as con:
        cursor = con.execute(
            "INSERT INTO people(name,created_at) VALUES(?,?)",
            (name, datetime.now().isoformat(timespec="seconds")),
        )
        return int(cursor.lastrowid)


def rename_person(person_id: int, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Please enter a name.")
    with connect() as con:
        con.execute("UPDATE people SET name=? WHERE id=?", (name, person_id))


def delete_person(person_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM people WHERE id=?", (person_id,))


def person_photos(person_id: int) -> list[dict[str, Any]]:
    with connect() as con:
        return [
            dict(row)
            for row in con.execute(
                """
                SELECT DISTINCT ph.id,ph.path,ph.width,ph.height,ph.date_taken,
                       ph.is_favorite,ph.is_archived,COALESCE(ph.media_type,'image') media_type,
                       ph.duration,ph.thumbnail_path,COALESCE(ph.category,'Unclassified') category,
                       ph.scanned_at
                FROM photos ph JOIN faces f ON f.photo_id=ph.id
                WHERE f.person_id=? AND ph.deleted_at IS NULL AND ph.is_archived=0
                ORDER BY COALESCE(ph.date_taken,ph.scanned_at) DESC
                """,
                (person_id,),
            ).fetchall()
        ]


def unassigned_faces() -> list[dict[str, Any]]:
    with connect() as con:
        return [
            dict(row)
            for row in con.execute(
                """
                SELECT f.id face_id,ph.path,ph.thumbnail_path,ph.media_type,
                       f.x,f.y,f.w,f.h
                FROM faces f JOIN photos ph ON ph.id=f.photo_id
                WHERE f.person_id IS NULL AND ph.deleted_at IS NULL AND ph.is_archived=0
                ORDER BY f.id DESC
                """
            ).fetchall()
        ]


def assign_face(face_id: int, person_id: int) -> None:
    with connect() as con:
        con.execute("UPDATE faces SET person_id=? WHERE id=?", (person_id, face_id))
        # A manual assignment makes any queued suggestion for this face obsolete.
        con.execute(
            "DELETE FROM candidates WHERE face_id=? AND status='pending'", (face_id,)
        )


def confirm_all_pending_candidates() -> tuple[int, int]:
    """Confirm every visible suggestion at once.

    Returns ``(confirmed, assigned)``. When one face has suggestions for more
    than one person the strongest score wins; the others are marked rejected so
    the review queue stays honest. A face that was assigned by hand in the
    meantime is never moved.
    """
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as con:
        rows = con.execute(
            """
            SELECT c.id,c.face_id,c.person_id,c.similarity,f.person_id current_person
            FROM candidates c
            JOIN faces f ON f.id=c.face_id
            JOIN photos ph ON ph.id=f.photo_id
            WHERE c.status='pending'
              AND ph.deleted_at IS NULL AND ph.is_archived=0
            """
        ).fetchall()
        if not rows:
            return 0, 0

        best: dict[int, sqlite3.Row] = {}
        for row in rows:
            chosen = best.get(row["face_id"])
            if chosen is None or row["similarity"] > chosen["similarity"]:
                best[row["face_id"]] = row

        confirm_ids: list[tuple[int]] = []
        reject_ids: list[tuple[int]] = []
        assignments: list[tuple[int, int]] = []
        confirmations: list[tuple[int, int, str]] = []
        for row in rows:
            won = row["id"] == best[row["face_id"]]["id"]
            already = row["current_person"]
            if won and (already is None or already == row["person_id"]):
                confirm_ids.append((row["id"],))
                confirmations.append((row["face_id"], row["person_id"], now))
                if already is None:
                    assignments.append((row["person_id"], row["face_id"]))
            else:
                reject_ids.append((row["id"],))

        assigned = 0
        if assignments:
            cursor = con.executemany(
                "UPDATE faces SET person_id=? WHERE id=? AND person_id IS NULL",
                assignments,
            )
            assigned = max(0, cursor.rowcount)
        if confirm_ids:
            con.executemany(
                "UPDATE candidates SET status='confirmed' WHERE id=?", confirm_ids
            )
        if reject_ids:
            con.executemany(
                "UPDATE candidates SET status='rejected' WHERE id=?", reject_ids
            )
        if confirmations:
            con.executemany(
                "INSERT INTO confirmations(face_id,person_id,confirmed,created_at) "
                "VALUES(?,?,1,?)",
                confirmations,
            )
    return len(confirm_ids), assigned


def history(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as con:
        return [
            dict(row)
            for row in con.execute(
                "SELECT * FROM scan_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        ]


def all_photos(
    search: str = "",
    category: str = "All",
    sort: str = "Newest",
    include_archived: bool = False,
    favorites_only: bool = False,
    trash_only: bool = False,
    include_deleted: bool = False,
    media_type: str = "All",
    album_id: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if trash_only:
        clauses.append("deleted_at IS NOT NULL")
    else:
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if not include_archived:
            clauses.append("is_archived=0")
    if search:
        clauses.append(
            "(path LIKE ? OR category LIKE ? OR COALESCE(date_taken,scanned_at) LIKE ?)"
        )
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])
    if category != "All":
        clauses.append("COALESCE(category,'Unclassified')=?")
        params.append(category)
    if favorites_only:
        clauses.append("is_favorite=1")
    if media_type == "Photos":
        clauses.append("COALESCE(media_type,'image')='image'")
    elif media_type == "Videos":
        clauses.append("media_type='video'")
    if album_id is not None:
        clauses.append("id IN (SELECT photo_id FROM album_items WHERE album_id=?)")
        params.append(album_id)
    order = "COALESCE(date_taken,scanned_at) DESC"
    if sort == "Oldest":
        order = "COALESCE(date_taken,scanned_at) ASC"
    elif sort == "Name A–Z":
        order = "path COLLATE NOCASE ASC"
    elif sort == "Name Z–A":
        order = "path COLLATE NOCASE DESC"
    elif sort == "Largest":
        order = "(COALESCE(width,0)*COALESCE(height,0)) DESC"
    query = (
        "SELECT id,path,width,height,COALESCE(category,'Unclassified') category,"
        "date_taken,scanned_at,is_favorite,is_archived,deleted_at,"
        "COALESCE(media_type,'image') media_type,duration,thumbnail_path FROM photos"
    )
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY " + order
    with connect() as con:
        return [dict(row) for row in con.execute(query, params).fetchall()]


def other_photos() -> list[dict[str, Any]]:
    with connect() as con:
        return [
            dict(row)
            for row in con.execute(
                """
                SELECT id,path,width,height,COALESCE(category,'Unclassified') category,
                       date_taken,scanned_at,is_favorite,is_archived,media_type,
                       duration,thumbnail_path
                FROM photos
                WHERE id NOT IN (SELECT DISTINCT photo_id FROM faces)
                  AND deleted_at IS NULL AND is_archived=0
                ORDER BY COALESCE(date_taken,scanned_at) DESC
                """
            ).fetchall()
        ]


def create_album(name: str, description: str = "") -> int:
    name = name.strip()
    if not name:
        raise ValueError("Album name cannot be empty.")
    with connect() as con:
        cursor = con.execute(
            "INSERT INTO albums(name,description,created_at) VALUES(?,?,?)",
            (name, description, datetime.now().isoformat(timespec="seconds")),
        )
        return int(cursor.lastrowid)


def albums_list() -> list[dict[str, Any]]:
    with connect() as con:
        return [
            dict(row)
            for row in con.execute(
                """
                SELECT a.*,COUNT(ai.photo_id) item_count,
                       COALESCE(a.cover_photo_id,
                           (SELECT photo_id FROM album_items
                            WHERE album_id=a.id ORDER BY added_at DESC LIMIT 1)) display_cover
                FROM albums a
                LEFT JOIN album_items ai ON ai.album_id=a.id
                GROUP BY a.id
                ORDER BY a.name COLLATE NOCASE
                """
            ).fetchall()
        ]


def album_cover_photo(album_id: int) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute(
            """
            SELECT ph.* FROM albums a
            JOIN photos ph ON ph.id=COALESCE(
                a.cover_photo_id,
                (SELECT ai.photo_id FROM album_items ai
                 WHERE ai.album_id=a.id ORDER BY ai.added_at DESC LIMIT 1)
            )
            WHERE a.id=?
            """,
            (album_id,),
        ).fetchone()
        return dict(row) if row else None


def album_add_photo(album_id: int, photo_id: int) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO album_items(album_id,photo_id,added_at) VALUES(?,?,?)",
            (album_id, photo_id, datetime.now().isoformat(timespec="seconds")),
        )
        con.execute(
            "UPDATE albums SET cover_photo_id=COALESCE(cover_photo_id,?) WHERE id=?",
            (photo_id, album_id),
        )


def album_remove_photo(album_id: int, photo_id: int) -> None:
    with connect() as con:
        con.execute(
            "DELETE FROM album_items WHERE album_id=? AND photo_id=?",
            (album_id, photo_id),
        )
        con.execute(
            "UPDATE albums SET cover_photo_id=NULL WHERE id=? AND cover_photo_id=?",
            (album_id, photo_id),
        )


def set_album_cover(album_id: int, photo_id: int) -> None:
    with connect() as con:
        exists = con.execute(
            "SELECT 1 FROM album_items WHERE album_id=? AND photo_id=?",
            (album_id, photo_id),
        ).fetchone()
        if not exists:
            raise ValueError("The selected item must belong to this album.")
        con.execute(
            "UPDATE albums SET cover_photo_id=? WHERE id=?", (photo_id, album_id)
        )


def delete_album(album_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM albums WHERE id=?", (album_id,))


def rename_album(album_id: int, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Album name cannot be empty.")
    with connect() as con:
        con.execute("UPDATE albums SET name=? WHERE id=?", (name, album_id))


def smart_search(query: str) -> list[dict[str, Any]]:
    """Local metadata search across names, dates, categories and media type.

    This deliberately does not claim visual/semantic scene understanding. It
    never sends the query or library contents off-device.
    """
    q = (query or "").strip().lower()
    if not q:
        return all_photos()

    today = date.today()
    terms = q.replace(",", " ").split()
    stopwords = {
        "a", "an", "the", "of", "in", "on", "at", "from", "with", "show",
        "find", "me", "my", "photos", "photo", "pictures", "picture",
        "images", "image", "please", "taken", "captured",
    }
    aliases = {
        "selfie": "people", "portraits": "people", "portrait": "people",
        "screenshots": "screenshot", "screen": "screenshot", "documents": "document",
        "pics": "photo", "videos": "video", "clips": "video", "clip": "video",
        "favourites": "favorite", "favourite": "favorite", "favs": "favorite",
        "persons": "people", "person": "people",
    }
    terms = [aliases.get(term, term) for term in terms if term not in stopwords]
    date_filters: list[tuple[str, str]] = []
    if "this year" in q:
        date_filters.append((f"{today.year}-01-01", f"{today.year + 1}-01-01"))
        terms = [term for term in terms if term not in {"this", "year"}]
    elif "last year" in q:
        date_filters.append((f"{today.year - 1}-01-01", f"{today.year}-01-01"))
        terms = [term for term in terms if term not in {"last", "year"}]
    if not terms and not date_filters:
        return all_photos()

    with connect() as con:
        rows = con.execute(
            """
            SELECT DISTINCT ph.id,ph.path,ph.width,ph.height,
                COALESCE(ph.category,'Unclassified') category,ph.date_taken,ph.scanned_at,
                ph.is_favorite,ph.is_archived,ph.deleted_at,
                COALESCE(ph.media_type,'image') media_type,ph.duration,ph.thumbnail_path
            FROM photos ph
            WHERE ph.deleted_at IS NULL AND ph.is_archived=0
            ORDER BY COALESCE(ph.date_taken,ph.scanned_at) DESC
            """
        ).fetchall()
        people_by_photo: dict[int, list[str]] = {}
        for row in con.execute(
            """
            SELECT f.photo_id,p.name FROM faces f
            JOIN people p ON p.id=f.person_id
            GROUP BY f.photo_id,p.name
            """
        ).fetchall():
            people_by_photo.setdefault(row["photo_id"], []).append(row["name"])

        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            people = people_by_photo.get(item["id"], [])
            stamp = item.get("date_taken") or item.get("scanned_at") or ""
            haystack = " ".join(
                [
                    item.get("path") or "",
                    item.get("category") or "",
                    stamp,
                    item.get("media_type") or "",
                ]
                + people
            ).lower()
            if any(not (start <= stamp[:10] < end) for start, end in date_filters):
                continue
            matched = True
            for term in terms:
                if term == "video":
                    ok = item.get("media_type") == "video"
                elif term in ("photo", "image"):
                    ok = item.get("media_type") == "image"
                elif term == "favorite":
                    ok = bool(item.get("is_favorite"))
                elif term == "people":
                    ok = bool(people) or "people" in (item.get("category") or "").lower()
                else:
                    ok = term in haystack
                if not ok:
                    matched = False
                    break
            if matched:
                output.append(item)
        return output
