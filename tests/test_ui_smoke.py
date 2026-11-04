"""Headless-style UI smoke test.

Run with the project interpreter:

    python tests/test_ui_smoke.py

The test swaps LOCALAPPDATA for a temporary directory before importing the app,
seeds a realistic library, then visits every page and asserts that the All
Photos grid renders all 28 seeded items with live thumbnails. Any Tk callback
exception fails the test. No real user data or AI models are touched.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_ROOT = Path(tempfile.mkdtemp(prefix="drishtix-ui-"))
os.environ["LOCALAPPDATA"] = str(TEMP_ROOT)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from database import db  # noqa: E402
from ui import app as ui_app  # noqa: E402
from ui.widgets import AsyncImage  # noqa: E402


def walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk_widgets(child)


def seed_library() -> Path:
    photos_dir = TEMP_ROOT / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    db.init_db()
    active_ids: list[int] = []
    for index in range(27):
        image = Image.new(
            "RGB",
            (360, 260),
            ((index * 29) % 255, (index * 71) % 255, (index * 47) % 255),
        )
        drawing = ImageDraw.Draw(image)
        drawing.ellipse((120, 40, 240, 170), fill=(236, 222, 204))
        path = photos_dir / f"library_{index:02d}.jpg"
        image.save(path, quality=90)
        photo_id = db.add_photo(
            str(path),
            f"hash-{index}",
            360,
            260,
            time.time(),
            "image",
            None,
            None,
        )
        db.set_photo_date(photo_id, f"2025-{(index % 12) + 1:02d}-14 10:00:00")
        db.set_photo_category(photo_id, "People" if index % 3 else "No-face image")
        active_ids.append(photo_id)

    for photo_id in active_ids[:4]:
        db.toggle_favorite(photo_id)

    archived_ids = []
    for index in range(2):
        path = photos_dir / f"archived_{index}.jpg"
        image = Image.new("RGB", (200, 150), (30, 60, 90))
        image.save(path)
        photo_id = db.add_photo(str(path), f"archived-{index}", 200, 150, time.time())
        db.set_archived(photo_id, True)
        archived_ids.append(photo_id)

    for index in range(2):
        path = photos_dir / f"trash_{index}.jpg"
        image = Image.new("RGB", (200, 150), (90, 30, 30))
        image.save(path)
        photo_id = db.add_photo(str(path), f"trash-{index}", 200, 150, time.time())
        db.move_to_trash(photo_id)

    # A real, playable video record for the Videos page.
    import cv2

    video_path = photos_dir / "clip.avi"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (160, 120)
    )
    if writer.isOpened():
        for index in range(8):
            frame = np.zeros((120, 160, 3), dtype=np.uint8)
            frame[:, :, 2] = 20 + index * 20
            writer.write(frame)
        writer.release()
        db.add_photo(str(video_path), "video-hash", 160, 120, time.time(), "video", 0.8)
        db.set_photo_category(db.all_photos(media_type="Videos")[0]["id"], "Video")

    person_id = db.create_person("Maya")
    embedding = np.zeros(512, dtype=np.float32)
    embedding[0] = 1.0
    face_id = db.add_face(active_ids[0], embedding.tobytes(), (120, 40, 120, 130), 0.99)
    db.assign_face(face_id, person_id)
    unassigned_one = db.add_face(
        active_ids[1], embedding.tobytes(), (120, 40, 120, 130), 0.95
    )
    db.add_face(active_ids[2], embedding.tobytes(), (120, 40, 120, 130), 0.92)
    db.create_candidate(unassigned_one, person_id, 0.58)

    album_id = db.create_album("Weekend")
    for photo_id in active_ids[:3]:
        db.album_add_photo(album_id, photo_id)

    scan_id = db.create_scan(str(photos_dir))
    db.finish_scan(scan_id, 28, 3, 0, 0, "completed")
    return photos_dir


def main() -> None:
    errors: list[str] = []
    seed_library()

    messagebox = ui_app.messagebox
    original_showerror = messagebox.showerror
    original_showinfo = messagebox.showinfo
    original_askyesno = messagebox.askyesno
    messagebox.showerror = lambda title, message, **kwargs: errors.append(f"{title}: {message}")
    messagebox.showinfo = lambda *args, **kwargs: None
    messagebox.askyesno = lambda *args, **kwargs: True

    app = None
    try:
        app = ui_app.DrishtiXApp()
        app.withdraw()
        app.update()

        def settle(cycles: int = 12) -> None:
            for _ in range(cycles):
                app.update()
                time.sleep(0.02)

        app.show_all_photos()
        settle()
        grid = app.current_grid
        assert grid is not None, "All Photos must render a grid"
        assert len(grid.tiles) == 28, f"expected 28 tiles, got {len(grid.tiles)}"
        assert grid._rendered == 28
        for _ in range(80):
            app.update()
            time.sleep(0.03)
            if sum(1 for tile in grid.tiles if tile["frame"].image) >= 20:
                break
        loaded = sum(1 for tile in grid.tiles if getattr(tile["frame"], "image", None))
        assert loaded >= 20, f"only {loaded} thumbnails loaded"

        pages = [
            app.show_dashboard,
            app.show_videos,
            app.show_favorites,
            app.show_archive,
            app.show_trash,
            app.show_people,
            app.show_unassigned,
            app.show_review,
            app.show_other_photos,
            app.show_history,
            app.show_signature if hasattr(app, "show_signature") else None,
            app.show_settings,
            app.show_about,
            lambda: app.show_smart_search("Maya"),
            lambda: app.show_smart_search(""),
            app.show_albums,
        ]
        for page in pages:
            if page is not None:
                page()
                settle(6)

        # Unassigned face cards must render a real crop, not the fallback text.
        app.show_unassigned()
        face_widgets = []
        for _ in range(80):
            app.update()
            time.sleep(0.03)
            face_widgets = [
                widget for widget in walk_widgets(app.content) if isinstance(widget, AsyncImage)
            ]
            if face_widgets and all(
                widget.label.cget("image") for widget in face_widgets
            ):
                break
        assert len(face_widgets) >= 2, "Unassigned Faces must render its face cards"
        assert all(
            widget.label.cget("image") for widget in face_widgets
        ), "Unassigned face previews did not load"
        assert not any(
            "Preview" in str(widget.label.cget("text")) for widget in face_widgets
        ), "Unassigned face previews fell back to unavailable"

        # Naming a face must match stored vectors immediately instead of
        # starting a full AI re-index.
        target = db.unassigned_faces()[0]
        original_askstring = ui_app.simpledialog.askstring
        ui_app.simpledialog.askstring = lambda *args, **kwargs: "Nova"
        try:
            started = time.time()
            app.assign_new_person(target["face_id"])
            elapsed = time.time() - started
        finally:
            ui_app.simpledialog.askstring = original_askstring
        assert elapsed < 2.0, f"naming a face took {elapsed:.2f}s; it should not re-index"
        assert not app._task_active, "naming a face must not start a background re-index"
        nova = next(person for person in db.people_list() if person["name"] == "Nova")
        suggestions = [
            row for row in db.pending_candidates() if row["person_name"] == "Nova"
        ]
        assert suggestions, "naming a face must queue matches found in stored vectors"

        album = db.albums_list()[0]
        app.open_album(album["id"], album["name"])
        settle(6)
        assert app.current_grid is not None and len(app.current_grid.tiles) == 3

        person = db.people_list()[0]
        app.show_person(person["id"], person["name"])
        settle(6)
        assert app.current_grid is not None

        # A page refresh after the rewrite must stay on the album/person page.
        app.open_album(album["id"], album["name"])
        app._refresh_current_page()
        settle(4)
        assert app._current_page == "Album", app._current_page

        assert not errors, "Tk callback errors:\n" + "\n".join(errors)
        print("DrishtiX UI smoke tests passed.")
    finally:
        messagebox.showerror = original_showerror
        messagebox.showinfo = original_showinfo
        messagebox.askyesno = original_askyesno
        if app is not None:
            try:
                app.thumbnail_service.shutdown()
                app.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    main()
