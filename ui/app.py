"""DrishtiX desktop workspace.

A local-first photo library for Windows 11. The interface is built with Tk/ttk
and deliberately keeps one scroll surface per page, background thumbnail
loading, and a single shared database path.
"""
from __future__ import annotations

import logging
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

import ctypes
import cv2
from PIL import Image, ImageOps, ImageTk

from app_paths import (
    LOG_PATH,
    USER_DATA_DIR,
    asset_path,
    ensure_user_data,
    format_timestamp,
    get_version,
    human_bytes,
    load_settings,
    save_settings,
    windows_prefers_light_theme,
)
from core.matching import match_person_across_library
from core.scanner import reindex_existing, scan_folder
from core.thumbnails import crop_face
from database import db
from ui.theme import Fonts, Theme, apply_ttk_styles, get_theme
from ui.widgets import (
    AsyncImage,
    EmptyState,
    PhotoGrid,
    ScrollFrame,
    SearchBox,
    SectionLabel,
    StatCard,
    ThumbnailService,
    bind_tree,
    display_date,
    human_duration,
    make_button,
    plural,
    truncate,
)

logger = logging.getLogger("drishtix.ui")


def enable_dpi_awareness() -> None:
    """Ask Windows for crisp per-monitor rendering before Tk is created."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class NavItem(tk.Frame):
    """A quiet navigation row with a left accent indicator."""

    def __init__(
        self,
        parent: tk.Misc,
        icon: str,
        label: str,
        command: Callable,
        app: "DrishtiXApp",
    ) -> None:
        super().__init__(parent, bg=app.sidebar_bg, cursor="hand2")
        self.app = app
        self.label = label
        self.command = command
        self._active = False
        self.indicator = tk.Frame(self, bg=app.sidebar_bg, width=3)
        self.indicator.pack(side="left", fill="y")
        self.icon = tk.Label(
            self,
            text=icon,
            bg=app.sidebar_bg,
            fg=app.sidebar_muted,
            font=app.fonts.icon(10),
            width=2,
            anchor="center",
        )
        self.icon.pack(side="left", padx=(10, 2), pady=7)
        self.text = tk.Label(
            self,
            text=label,
            bg=app.sidebar_bg,
            fg=app.sidebar_text,
            font=app.fonts.text(9),
            anchor="w",
        )
        self.text.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=7)
        bind_tree(self, "<Button-1>", self._click)
        bind_tree(self, "<Enter>", self._enter)
        bind_tree(self, "<Leave>", self._leave)
        bind_tree(self, "<space>", self._click)
        bind_tree(self, "<Return>", self._click)

    def _click(self, _event=None) -> None:
        self.command()

    def _enter(self, _event=None) -> None:
        if not self._active:
            self._paint(self.app.nav_hover_bg, self.app.sidebar_text)

    def _leave(self, _event=None) -> None:
        if not self._active:
            self._paint(self.app.sidebar_bg, self.app.sidebar_text)

    def _paint(self, background: str, foreground: str) -> None:
        for widget in (self, self.icon, self.text):
            widget.configure(bg=background)
        self.text.configure(fg=foreground)

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self._paint(self.app.nav_active_bg, self.app.theme.text)
            self.indicator.configure(bg=self.app.theme.accent)
            self.icon.configure(fg=self.app.theme.cyan)
            self.text.configure(font=self.app.fonts.text(9, "bold"))
        else:
            self._paint(self.app.sidebar_bg, self.app.sidebar_text)
            self.indicator.configure(bg=self.app.sidebar_bg)
            self.icon.configure(fg=self.app.sidebar_muted)
            self.text.configure(font=self.app.fonts.text(9))


class DrishtiXApp(tk.Tk):
    def __init__(self) -> None:
        enable_dpi_awareness()
        super().__init__()
        ensure_user_data()
        self.logger = logger
        self.settings = load_settings()
        # First launch: follow the Windows light/dark theme preference.
        if "theme" not in self.settings:
            self.settings["theme"] = "Light" if windows_prefers_light_theme() else "Dark"
        self.theme: Theme = get_theme(self.settings.get("theme", "Dark"))
        self.version = get_version()
        self.fonts = Fonts(self)

        self.sidebar_bg = self.theme.sidebar
        self.sidebar_text = "#b9c6dc" if self.theme.name != "Light" else "#b9c6dc"
        self.sidebar_muted = "#6f819e"
        self.nav_hover_bg = "#0d1728" if self.theme.name != "Ocean" else "#082333"
        self.nav_active_bg = "#131f35" if self.theme.name != "Ocean" else "#0f2c40"

        apply_ttk_styles(self, self.theme, self.fonts)
        self.title("DrishtiX — Your Photos. Your People. Your Memories.")
        self.configure(bg=self.theme.bg)
        self.minsize(1100, 720)
        self._center_window(1520, 940)
        self._set_icon()
        self._apply_titlebar_theme()

        try:
            db.init_db()
        except Exception as exc:
            logger.exception("Database initialization failed")
            messagebox.showerror(
                "DrishtiX could not open its library",
                "The local library database could not be opened.\n\n"
                f"Location:\n{db.DB_PATH}\n\n"
                f"Details: {exc}\n\n"
                "Your original photos were not modified. A safety backup is kept in\n"
                f"{USER_DATA_DIR / 'backups'}.",
            )
            raise

        self.thumbnail_service = ThumbnailService()
        self._task_queue: queue.Queue = queue.Queue()
        self._task_active = False
        self._task_kind: str | None = None
        self._cancel_requested = False
        self._current_page = "Dashboard"
        self._current_album: tuple[int, str] | None = None
        self._current_person: tuple[int, str] | None = None
        self.current_grid: PhotoGrid | None = None
        self._dashboard_scan_info: tk.Label | None = None
        self._dashboard_scan_bar: ttk.Progressbar | None = None
        self._debounce_jobs: dict[str, str] = {}
        self._showing_error = False
        self._viewer_windows: list[tk.Toplevel] = []

        self._build_shell()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.report_callback_exception = self._report_callback_exception
        self.bind_all("<Control-f>", lambda _event: self.show_smart_search())
        self.bind_all("<Control-o>", lambda _event: self.start_scan())
        self.bind_all("<Control-s>", lambda _event: self.start_scan())
        self.after(80, self._poll_tasks)
        self.show_dashboard()

    # ------------------------------------------------------------------ shell

    def _center_window(self, width: int, height: int) -> None:
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            # Fit comfortably on 1280 x 800 laptops as well as large monitors.
            width = min(width, max(1100, screen_w - 80))
            height = min(height, max(720, screen_h - 80))
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 2 - 10)
            self.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            self.geometry("1520x940")

    def _set_icon(self) -> None:
        icon = asset_path("drishtix_logo.ico")
        try:
            if icon.is_file():
                self.iconbitmap(str(icon))
        except Exception:
            logger.debug("Could not set the window icon", exc_info=True)

    def _apply_titlebar_theme(self) -> None:
        """Match the native Windows title bar to the application shell."""
        if not hasattr(ctypes, "windll"):
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            if not hwnd:
                return
            dark = 0 if self.theme.name == "Light" else 1
            value = ctypes.c_int(dark)
            applied = False
            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                )
                if result == 0:
                    applied = True
                    break
            if applied and dark:
                for attribute, colour in (
                    (35, self.theme.sidebar),
                    (36, self.theme.text),
                    (34, self.theme.border),
                ):
                    raw = colour.lstrip("#")
                    r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
                    colour_value = ctypes.c_uint(r | (g << 8) | (b << 16))
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd,
                        attribute,
                        ctypes.byref(colour_value),
                        ctypes.sizeof(colour_value),
                    )
        except Exception:
            logger.debug("Could not apply the native title-bar theme", exc_info=True)

    def _build_shell(self) -> None:
        shell = tk.Frame(self, bg=self.theme.bg)
        shell.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(
            shell,
            bg=self.sidebar_bg,
            width=252,
            highlightthickness=0,
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self._build_sidebar()

        self.main = tk.Frame(shell, bg=self.theme.bg)
        self.main.pack(side="left", fill="both", expand=True)
        self._build_topbar()
        self._build_content()
        self._build_statusbar()

    def _build_sidebar(self) -> None:
        brand = tk.Frame(self.sidebar, bg=self.sidebar_bg)
        brand.pack(fill="x", padx=18, pady=(20, 18))
        icon_path = asset_path("drishtix_icon.png")
        try:
            with Image.open(icon_path) as logo:
                logo = logo.convert("RGBA")
                logo.thumbnail((46, 46), Image.Resampling.LANCZOS)
                self.brand_logo = ImageTk.PhotoImage(logo)
            tk.Label(brand, image=self.brand_logo, bg=self.sidebar_bg).pack(side="left")
        except Exception:
            mark = tk.Canvas(
                brand, width=44, height=44, bg=self.sidebar_bg, highlightthickness=0
            )
            mark.pack(side="left")
            mark.create_oval(4, 4, 40, 40, outline=self.theme.cyan, width=2)
            mark.create_oval(11, 11, 33, 33, outline=self.theme.accent, width=2)
        namebox = tk.Frame(brand, bg=self.sidebar_bg)
        namebox.pack(side="left", padx=(10, 0), fill="x", expand=True)
        tk.Label(
            namebox,
            text="DRISHTIX",
            bg=self.sidebar_bg,
            fg=self.theme.text,
            font=self.fonts.display(12, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            namebox,
            text="PHOTO INTELLIGENCE",
            bg=self.sidebar_bg,
            fg=self.theme.cyan,
            font=self.fonts.text(6, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # Scrollable navigation so Settings never disappears on short screens.
        nav_canvas = tk.Canvas(self.sidebar, bg=self.sidebar_bg, highlightthickness=0, bd=0)
        nav_canvas.pack(side="top", fill="both", expand=True)
        nav_inner = tk.Frame(nav_canvas, bg=self.sidebar_bg)
        nav_window = nav_canvas.create_window((0, 0), window=nav_inner, anchor="nw")
        nav_inner.bind(
            "<Configure>",
            lambda _event: nav_canvas.configure(scrollregion=nav_canvas.bbox("all")),
        )
        nav_canvas.bind(
            "<Configure>",
            lambda event: nav_canvas.itemconfigure(nav_window, width=event.width),
        )
        self.sidebar_canvas = nav_canvas

        self.nav_items: dict[str, NavItem] = {}
        sections = [
            (
                "LIBRARY",
                [
                    ("Dashboard", "\uE80F", self.show_dashboard),
                    ("All Photos", "\uE91B", self.show_all_photos),
                    ("Videos", "\uE714", self.show_videos),
                    ("Albums", "\uE8B7", self.show_albums),
                    ("Favorites", "\uE734", self.show_favorites),
                    ("Archive", "\uE7B8", self.show_archive),
                    ("Trash", "\uE74D", self.show_trash),
                ],
            ),
            (
                "PEOPLE",
                [
                    ("People", "\uE716", self.show_people),
                    ("Unassigned Faces", "\uE77B", self.show_unassigned),
                    ("Match Review", "\uE8FB", self.show_review),
                ],
            ),
            (
                "ORGANISE",
                [
                    ("Smart Search", "\uE721", self.show_smart_search),
                    ("Other Photos", "\uE8B9", self.show_other_photos),
                    ("Scan History", "\uE81C", self.show_history),
                ],
            ),
        ]
        for section, entries in sections:
            tk.Label(
                nav_inner,
                text=section,
                bg=self.sidebar_bg,
                fg=self.sidebar_muted,
                font=self.fonts.text(7, "bold"),
                anchor="w",
            ).pack(fill="x", padx=22, pady=(15, 5))
            for label, icon, command in entries:
                item = NavItem(nav_inner, icon, label, command, self)
                item.pack(fill="x", padx=10, pady=1)
                self.nav_items[label] = item

        fixed = tk.Frame(self.sidebar, bg=self.sidebar_bg)
        fixed.pack(side="bottom", fill="x")
        tk.Frame(fixed, bg=self.theme.border_soft, height=1).pack(fill="x", padx=18, pady=(6, 5))
        for label, icon, command in (
            ("Settings", "\uE713", self.show_settings),
            ("About", "\uE946", self.show_about),
        ):
            item = NavItem(fixed, icon, label, command, self)
            item.pack(fill="x", padx=10, pady=1)
            self.nav_items[label] = item

        footer = tk.Frame(fixed, bg="#0c1424", padx=12, pady=10)
        footer.pack(fill="x", padx=12, pady=(10, 12))
        tk.Label(
            footer,
            text="●  LOCAL-FIRST MODE",
            bg="#0c1424",
            fg=self.theme.green,
            font=self.fonts.text(7, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            footer,
            text="Your library stays on this device",
            bg="#0c1424",
            fg=self.sidebar_muted,
            font=self.fonts.text(7),
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))
        tk.Label(
            fixed,
            text="Powered by TantraYantra",
            bg=self.sidebar_bg,
            fg=self.sidebar_muted,
            font=self.fonts.text(7),
        ).pack(pady=(0, 12))

    def _build_topbar(self) -> None:
        self.topbar = tk.Frame(self.main, bg=self.theme.bg)
        self.topbar.pack(fill="x", padx=30, pady=(20, 0))
        row = tk.Frame(self.topbar, bg=self.theme.bg)
        row.pack(fill="x")

        header = tk.Frame(row, bg=self.theme.bg)
        header.pack(side="left", fill="x", expand=True)
        self.page_title = tk.Label(
            header,
            text="",
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.fonts.display(23, "bold"),
            anchor="w",
        )
        self.page_title.pack(anchor="w")
        self.page_subtitle = tk.Label(
            header,
            text="",
            bg=self.theme.bg,
            fg=self.theme.muted,
            font=self.fonts.text(9),
            anchor="w",
        )
        self.page_subtitle.pack(anchor="w", pady=(3, 0))

        actions = tk.Frame(row, bg=self.theme.bg)
        actions.pack(side="right")
        self.top_status = tk.Label(
            actions,
            text="●  READY",
            bg=self.theme.panel2,
            fg=self.theme.green,
            font=self.fonts.text(7, "bold"),
            padx=10,
            pady=8,
        )
        self.top_status.pack(side="right")
        make_button(
            actions,
            "Search",
            self.show_smart_search,
            self.theme,
            self.fonts,
            "ghost",
            padx=12,
            pady=8,
        ).pack(side="right", padx=(0, 8))
        self.scan_button = make_button(
            actions,
            "+  Scan folder",
            self.start_scan,
            self.theme,
            self.fonts,
            "primary",
            padx=16,
            pady=9,
        )
        self.scan_button.pack(side="right", padx=(0, 8))
        self.cancel_button = make_button(
            actions,
            "Cancel",
            self._cancel_task,
            self.theme,
            self.fonts,
            "danger",
            padx=12,
            pady=8,
        )

        self.progress_wrap = tk.Frame(self.topbar, bg=self.theme.bg)
        self.progress = ttk.Progressbar(
            self.progress_wrap, mode="determinate", style="Horizontal.TProgressbar"
        )
        self.progress.pack(fill="x")
        self.progress_label = tk.Label(
            self.progress_wrap,
            text="",
            bg=self.theme.bg,
            fg=self.theme.muted,
            font=self.fonts.text(8),
            anchor="w",
        )
        self.progress_label.pack(anchor="w", pady=(5, 0))

    def _build_content(self) -> None:
        self.content_shell = tk.Frame(self.main, bg=self.theme.bg)
        self.content_shell.pack(fill="both", expand=True, padx=30, pady=(16, 0))
        self.content_canvas = tk.Canvas(
            self.content_shell, bg=self.theme.bg, highlightthickness=0, bd=0
        )
        self.content_scrollbar = ttk.Scrollbar(
            self.content_shell, orient="vertical", command=self.content_canvas.yview
        )
        self.content_canvas.configure(yscrollcommand=self.content_scrollbar.set)
        self.content_scrollbar.pack(side="right", fill="y")
        self.content_canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.content_canvas, bg=self.theme.bg)
        self.content_window = self.content_canvas.create_window(
            (0, 0), window=self.content, anchor="nw"
        )
        self.content.bind("<Configure>", self._update_scrollregion)
        self.content_canvas.bind("<Configure>", self._resize_content)
        self.bind_all("<MouseWheel>", self._route_mousewheel)
        self.bind_all("<Button-4>", self._route_mousewheel_linux)
        self.bind_all("<Button-5>", self._route_mousewheel_linux)

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self.main, bg=self.theme.bg)
        bar.pack(fill="x", padx=30, pady=(8, 10))
        tk.Frame(bar, bg=self.theme.border_soft, height=1).pack(fill="x")
        inner = tk.Frame(bar, bg=self.theme.bg)
        inner.pack(fill="x", pady=(7, 0))
        self.statusbar = tk.Label(
            inner,
            text="READY  /  Library stored locally on this device",
            bg=self.theme.bg,
            fg=self.theme.dim,
            font=self.fonts.mono(7),
            anchor="w",
        )
        self.statusbar.pack(side="left")
        self.statusbar_right = tk.Label(
            inner,
            text="",
            bg=self.theme.bg,
            fg=self.theme.dim,
            font=self.fonts.mono(7),
            anchor="e",
        )
        self.statusbar_right.pack(side="right")
        self._refresh_status_right()

    def _refresh_status_right(self) -> None:
        try:
            count = db.stats()["photos"]
            self.statusbar_right.config(
                text=f"v{self.version}   ·   {count:,} {plural(count, 'item')}   ·   {USER_DATA_DIR.name}"
            )
        except Exception:
            self.statusbar_right.config(text=f"v{self.version}")

    def _update_scrollregion(self, _event=None) -> None:
        self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))

    def _resize_content(self, event) -> None:
        self.content_canvas.itemconfigure(self.content_window, width=event.width)

    def _route_mousewheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return
        if str(widget).startswith(str(self.sidebar)):
            self.sidebar_canvas.yview_scroll(int(-event.delta / 120), "units")
            return
        if self._widget_has_own_scroll(widget):
            return
        self.content_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _route_mousewheel_linux(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return
        direction = -1 if event.num == 4 else 1
        if str(widget).startswith(str(self.sidebar)):
            self.sidebar_canvas.yview_scroll(direction, "units")
            return
        if self._widget_has_own_scroll(widget):
            return
        self.content_canvas.yview_scroll(direction, "units")

    def _widget_has_own_scroll(self, widget) -> bool:
        current = widget
        while current is not None and current is not self:
            if current.winfo_class() in ("Treeview", "Text", "Listbox", "TCombobox"):
                return True
            current = current.master
        return False

    def clear(self, title: str, subtitle: str = "", nav: str | None = None) -> None:
        self._current_page = nav or title
        self.page_title.config(text=title)
        self.page_subtitle.config(text=subtitle)
        for child in self.content.winfo_children():
            child.destroy()
        self.current_grid = None
        self._dashboard_scan_info = None
        self._dashboard_scan_bar = None
        self._set_active_nav(nav or title)
        self.after_idle(lambda: self.content_canvas.yview_moveto(0))
        self.after_idle(self._update_scrollregion)

    def _set_active_nav(self, label: str) -> None:
        for name, item in self.nav_items.items():
            item.set_active(name == label)

    def _panel(self, parent: tk.Misc, padx: int = 20, pady: int = 18):
        outer = tk.Frame(
            parent,
            bg=self.theme.panel,
            highlightthickness=1,
            highlightbackground=self.theme.border,
        )
        inner = tk.Frame(outer, bg=self.theme.panel, padx=padx, pady=pady)
        inner.pack(fill="both", expand=True)
        return outer, inner

    def _debounce(self, key: str, delay: int, callback: Callable[[], None]) -> None:
        previous = self._debounce_jobs.get(key)
        if previous:
            try:
                self.after_cancel(previous)
            except Exception:
                pass
        self._debounce_jobs[key] = self.after(delay, callback)

    # ----------------------------------------------------------------- tasks

    def _poll_tasks(self) -> None:
        try:
            while True:
                kind, event, payload = self._task_queue.get_nowait()
                if event == "progress":
                    self._on_task_progress(kind, payload)
                elif event == "done":
                    self._on_task_done(kind, payload)
                elif event == "error":
                    self._on_task_error(kind, payload)
        except queue.Empty:
            pass
        self.after(80, self._poll_tasks)

    def _begin_task(self, kind: str, title: str, worker: Callable) -> None:
        if self._task_active:
            messagebox.showinfo("Please wait", "Another library task is already running.")
            return
        self._task_active = True
        self._task_kind = kind
        self._cancel_requested = False
        self._set_task_ui(True, title)
        self._set_status(title, self.theme.cyan)
        self._set_top_status("●  WORKING", self.theme.cyan)

        def progress_adapter(index, total, name, seen, faces, skipped, errors):
            self._task_queue.put(
                (
                    "progress",
                    kind,
                    {
                        "index": index,
                        "total": total,
                        "name": name,
                        "seen": seen,
                        "faces": faces,
                        "skipped": skipped,
                        "errors": errors,
                    },
                )
            )

        def runner():
            try:
                result = worker(progress_adapter, lambda: self._cancel_requested)
            except Exception as exc:
                logger.exception("Background task failed")
                self._task_queue.put(("error", kind, exc))
            else:
                self._task_queue.put(("done", kind, result))

        threading.Thread(target=runner, daemon=True, name=f"pl-{kind}").start()

    def _set_task_ui(self, active: bool, title: str = "") -> None:
        if active:
            self.progress_wrap.pack(fill="x", pady=(12, 0))
            self.progress.configure(maximum=100, value=0)
            self.progress_label.configure(text=title)
            self.cancel_button.pack(side="right", padx=(0, 8))
            self.scan_button.configure(text="Working…", state="disabled")
        else:
            self.progress_wrap.pack_forget()
            self.cancel_button.pack_forget()
            self.scan_button.configure(text="+  Scan folder", state="normal")

    def _on_task_progress(self, kind: str, data: dict[str, Any]) -> None:
        index = int(data.get("index") or 0)
        total = int(data.get("total") or 1)
        self.progress.configure(maximum=max(1, total), value=index)
        self._set_top_status(f"●  {index:,} / {total:,}", self.theme.cyan)
        message = (
            f"{data.get('name','')}  ·  {data.get('seen',0)} indexed  ·  "
            f"{data.get('faces',0)} faces  ·  {data.get('skipped',0)} duplicates  ·  "
            f"{data.get('errors',0)} errors"
        )
        self.progress_label.configure(text=message)
        if self._dashboard_scan_info is not None:
            try:
                if self._dashboard_scan_info.winfo_exists():
                    self._dashboard_scan_info.configure(text=message)
                if self._dashboard_scan_bar is not None and self._dashboard_scan_bar.winfo_exists():
                    self._dashboard_scan_bar.configure(maximum=max(1, total), value=index)
            except tk.TclError:
                pass

    def _on_task_done(self, kind: str, result: dict[str, Any]) -> None:
        self._task_active = False
        self._task_kind = None
        self._set_task_ui(False)
        status = result.get("status", "completed")
        self._set_top_status("●  READY", self.theme.green)
        self._set_status(f"Task finished: {status}", self.theme.muted)
        self._refresh_status_right()
        self._refresh_current_page(scan_result=result if kind == "scan" else None)
        if kind == "scan":
            self._show_scan_summary(result)
        else:
            self._show_reindex_summary(result)

    def _on_task_error(self, kind: str, exc: Exception) -> None:
        self._task_active = False
        self._task_kind = None
        self._set_task_ui(False)
        self._set_top_status("●  NEEDS ATTENTION", self.theme.red)
        self._set_status(f"Task failed: {exc}", self.theme.red)
        logger.exception("Task %s failed", kind)
        messagebox.showerror(
            "DrishtiX could not finish that task",
            f"{exc}\n\nDetails were written to:\n{LOG_PATH}",
        )

    def _cancel_task(self) -> None:
        if not self._task_active:
            return
        self._cancel_requested = True
        self._set_status("Cancelling…", self.theme.amber)
        self._set_top_status("●  CANCELLING", self.theme.amber)
        self.cancel_button.configure(state="disabled")

    def _set_top_status(self, text: str, colour: str) -> None:
        try:
            self.top_status.configure(text=text, fg=colour)
        except tk.TclError:
            pass

    def _set_status(self, text: str, colour: str | None = None) -> None:
        try:
            self.statusbar.configure(text=text, fg=colour or self.theme.dim)
        except tk.TclError:
            pass

    def _refresh_current_page(self, scan_result: dict[str, Any] | None = None) -> None:
        page = self._current_page
        if page == "Dashboard":
            self.show_dashboard()
        elif page == "All Photos":
            self.show_all_photos()
        elif page == "Videos":
            self.show_videos()
        elif page == "Favorites":
            self.show_favorites()
        elif page == "Archive":
            self.show_archive()
        elif page == "Trash":
            self.show_trash()
        elif page == "Other Photos":
            self.show_other_photos()
        elif page == "People":
            self.show_people()
        elif page == "Unassigned Faces":
            self.show_unassigned()
        elif page == "Match Review":
            self.show_review()
        elif page == "Scan History":
            self.show_history()
        elif page == "Album" and self._current_album:
            self.open_album(*self._current_album)
        elif page == "Person" and self._current_person:
            self.show_person(*self._current_person)
        else:
            self._refresh_status_right()

    # ------------------------------------------------------------- dashboard

    def show_dashboard(self) -> None:
        self.clear(
            "Dashboard",
            "A clear view of your library, your people, and what needs attention.",
        )
        stats = db.stats()

        hero, hero_inner = self._panel(self.content, padx=28, pady=26)
        hero.pack(fill="x", pady=(0, 16))
        hero_left = tk.Frame(hero_inner, bg=self.theme.panel)
        hero_left.pack(side="left", fill="both", expand=True)
        tk.Label(
            hero_left,
            text="THE DRISHTIX WORKSPACE",
            bg=self.theme.panel,
            fg=self.theme.accent,
            font=self.fonts.text(7, "bold"),
            anchor="w",
        ).pack(anchor="w")
        title = "Your library, in focus." if stats["photos"] else "Start your library."
        tk.Label(
            hero_left,
            text=title,
            bg=self.theme.panel,
            fg=self.theme.text,
            font=self.fonts.display(22, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(7, 5))
        body = (
            "Explore, organise and recognise the people in your photo universe. "
            "Everything is indexed and searched on this device."
            if stats["photos"]
            else "Choose a folder and DrishtiX will index your photos and videos locally. "
            "Face recognition is optional and never uploads your library."
        )
        tk.Label(
            hero_left,
            text=body,
            bg=self.theme.panel,
            fg=self.theme.muted,
            font=self.fonts.text(9),
            wraplength=640,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(0, 16))
        hero_actions = tk.Frame(hero_left, bg=self.theme.panel)
        hero_actions.pack(anchor="w")
        make_button(
            hero_actions,
            "+  Scan a folder",
            self.start_scan,
            self.theme,
            self.fonts,
            "primary",
        ).pack(side="left")
        make_button(
            hero_actions,
            "View all photos",
            self.show_all_photos,
            self.theme,
            self.fonts,
            "secondary",
        ).pack(side="left", padx=(8, 0))

        orbit = tk.Canvas(
            hero_inner, width=230, height=150, bg=self.theme.panel, highlightthickness=0
        )
        orbit.pack(side="right", padx=(18, 0))
        orbit.create_oval(45, 8, 187, 150, outline=self.theme.border, width=1)
        orbit.create_oval(64, 27, 168, 131, outline=self.theme.accent, width=1)
        orbit.create_oval(86, 49, 146, 109, outline=self.theme.cyan, width=1)
        orbit.create_oval(110, 73, 122, 85, fill=self.theme.accent, outline="")
        orbit.create_oval(158, 28, 166, 36, fill=self.theme.cyan, outline="")
        orbit.create_oval(59, 91, 67, 99, fill=self.theme.accent_soft, outline="")
        orbit.create_text(
            116, 140, text="LOCAL AI  ·  ON-DEVICE", fill=self.theme.dim,
            font=self.fonts.text(6, "bold"),
        )

        cards = tk.Frame(self.content, bg=self.theme.bg)
        cards.pack(fill="x", pady=(0, 18))
        card_data = [
            (
                "Library",
                f'{stats["photos"]:,}',
                f'{stats["images"]:,} {plural(stats["images"], "photo")}  ·  '
                f'{stats["videos"]:,} {plural(stats["videos"], "video")}',
                self.theme.cyan,
                "\uE91B",
            ),
            (
                "People",
                f'{stats["people"]:,}',
                "Named profiles",
                self.theme.accent,
                "\uE716",
            ),
            (
                "Faces",
                f'{stats["faces"]:,}',
                "Detected locally",
                self.theme.green,
                "\uE77B",
            ),
            (
                "Review queue",
                f'{stats["pending"]:,}',
                "Possible matches to confirm",
                self.theme.amber,
                "\uE8FB",
            ),
        ]
        for index, (label, value, note, accent, glyph) in enumerate(card_data):
            card = StatCard(
                cards, self.theme, self.fonts, label, value, note, accent, glyph
            )
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 10) if index < 3 else 0)
            cards.grid_columnconfigure(index, weight=1)

        recent = db.all_photos(sort="Newest")[:12]
        if recent:
            header = SectionLabel(
                self.content,
                self.theme,
                self.fonts,
                "Recently added",
                "View all",
                self.show_all_photos,
            )
            header.pack(fill="x", pady=(2, 8))
            grid = PhotoGrid(
                self.content,
                self,
                recent,
                on_open=self.open_photo,
                page_size=12,
            )
            grid.pack(fill="x", pady=(0, 14))
            self.current_grid = grid

        bottom = tk.Frame(self.content, bg=self.theme.bg)
        bottom.pack(fill="x", pady=(4, 0))
        snapshot, snapshot_inner = self._panel(bottom)
        snapshot.pack(side="left", fill="both", expand=True, padx=(0, 10))
        tk.Label(
            snapshot_inner,
            text="LIBRARY SNAPSHOT",
            bg=self.theme.panel,
            fg=self.theme.accent,
            font=self.fonts.text(7, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(0, 10))
        for label, value in (
            ("Photos", stats["images"]),
            ("Videos", stats["videos"]),
            ("Favorites", self._favorite_count()),
            ("Albums", stats["albums"]),
            ("Archive", stats["archived"]),
            ("Trash", stats["trash"]),
        ):
            row = tk.Frame(snapshot_inner, bg=self.theme.panel)
            row.pack(fill="x", pady=2)
            tk.Label(
                row, text=label, bg=self.theme.panel, fg=self.theme.muted,
                font=self.fonts.text(9), anchor="w"
            ).pack(side="left")
            tk.Label(
                row, text=f"{value:,}" if isinstance(value, int) else str(value),
                bg=self.theme.panel, fg=self.theme.text, font=self.fonts.text(9, "bold"),
                anchor="e"
            ).pack(side="right")

        activity, activity_inner = self._panel(bottom)
        activity.pack(side="left", fill="both", expand=True)
        tk.Label(
            activity_inner,
            text="SCAN ACTIVITY",
            bg=self.theme.panel,
            fg=self.theme.accent,
            font=self.fonts.text(7, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(0, 10))
        last = stats.get("last_scan")
        if self._task_active:
            self._dashboard_scan_info = tk.Label(
                activity_inner,
                text="Working…",
                bg=self.theme.panel,
                fg=self.theme.muted,
                font=self.fonts.text(8),
                anchor="w",
            )
            self._dashboard_scan_info.pack(anchor="w", pady=(0, 8))
            self._dashboard_scan_bar = ttk.Progressbar(
                activity_inner, mode="determinate", style="Horizontal.TProgressbar"
            )
            self._dashboard_scan_bar.pack(fill="x", pady=(0, 10))
        elif last:
            tk.Label(
                activity_inner,
                text=last.get("folder", ""),
                bg=self.theme.panel,
                fg=self.theme.text,
                font=self.fonts.text(9, "bold"),
                anchor="w",
                wraplength=520,
                justify="left",
            ).pack(anchor="w")
            tk.Label(
                activity_inner,
                text=(
                    f"{format_timestamp(last.get('finished_at') or last.get('started_at'))}  ·  "
                    f"{last.get('photos_seen', 0)} indexed  ·  "
                    f"{last.get('faces_found', 0)} faces  ·  "
                    f"{last.get('skipped', 0)} duplicates  ·  "
                    f"{last.get('errors', 0)} errors"
                ),
                bg=self.theme.panel,
                fg=self.theme.muted,
                font=self.fonts.text(8),
                anchor="w",
                wraplength=520,
                justify="left",
            ).pack(anchor="w", pady=(5, 0))
        else:
            tk.Label(
                activity_inner,
                text="No scans yet. Scan a folder to bring your library together.",
                bg=self.theme.panel,
                fg=self.theme.muted,
                font=self.fonts.text(9),
                anchor="w",
                wraplength=520,
                justify="left",
            ).pack(anchor="w", pady=(0, 8))
        make_button(
            activity_inner,
            "Scan history",
            self.show_history,
            self.theme,
            self.fonts,
            "ghost",
            padx=10,
            pady=5,
        ).pack(anchor="w", pady=(12, 0))

        self._refresh_status_right()

    def _favorite_count(self) -> int:
        try:
            return len(db.all_photos(favorites_only=True))
        except Exception:
            return 0

    # ----------------------------------------------------------- library pages

    def show_all_photos(self) -> None:
        self._show_library_page(
            "All Photos",
            "Every photo and video in your local library.",
            media_type="All",
        )

    def show_videos(self) -> None:
        self._show_library_page(
            "Videos",
            "Locally indexed video clips with first-frame previews.",
            media_type="Videos",
            show_category=False,
        )

    def show_favorites(self) -> None:
        self._show_library_page(
            "Favorites",
            "The moments you marked to keep close.",
            favorites_only=True,
        )

    def show_archive(self) -> None:
        self._show_library_page(
            "Archive",
            "Hidden from the main library, still safely indexed.",
            include_archived=True,
            archived_only=True,
        )

    def show_trash(self) -> None:
        self._show_library_page(
            "Trash",
            "Removed from the library index. Original files are never deleted here.",
            trash_only=True,
        )

    def _show_library_page(
        self,
        title: str,
        subtitle: str,
        *,
        favorites_only: bool = False,
        include_archived: bool = False,
        archived_only: bool = False,
        trash_only: bool = False,
        media_type: str = "All",
        show_category: bool = True,
    ) -> None:
        self.clear(title, subtitle)
        toolbar = tk.Frame(self.content, bg=self.theme.bg)
        toolbar.pack(fill="x", pady=(0, 10))

        search = SearchBox(
            toolbar,
            self.theme,
            self.fonts,
            placeholder="Search file names, categories or dates…",
        )
        search.pack(side="left", fill="x", expand=True)
        count_label = tk.Label(
            toolbar,
            text="",
            bg=self.theme.bg,
            fg=self.theme.muted,
            font=self.fonts.text(8),
            padx=12,
        )
        count_label.pack(side="left")

        controls = tk.Frame(self.content, bg=self.theme.bg)
        controls.pack(fill="x", pady=(0, 12))
        category = tk.StringVar(value="All")
        sort = tk.StringVar(value="Newest")
        group = tk.BooleanVar(value=bool(self.settings.get("group_by_month", True)))
        if show_category:
            tk.Label(
                controls, text="Category", bg=self.theme.bg, fg=self.theme.muted,
                font=self.fonts.text(8)
            ).pack(side="left", padx=(0, 6))
            category_box = ttk.Combobox(
                controls,
                textvariable=category,
                state="readonly",
                width=15,
                values=["All", "People", "Screenshot", "No-face image", "Video", "Unclassified"],
            )
            category_box.pack(side="left", padx=(0, 14))
        tk.Label(
            controls, text="Sort", bg=self.theme.bg, fg=self.theme.muted,
            font=self.fonts.text(8)
        ).pack(side="left", padx=(0, 6))
        sort_box = ttk.Combobox(
            controls,
            textvariable=sort,
            state="readonly",
            width=13,
            values=["Newest", "Oldest", "Name A–Z", "Name Z–A", "Largest"],
        )
        sort_box.pack(side="left", padx=(0, 14))
        group_button = tk.Checkbutton(
            controls,
            text="Group by month",
            variable=group,
            indicatoron=False,
            bg=self.theme.panel2,
            fg=self.theme.muted,
            selectcolor=self.theme.active,
            activebackground=self.theme.elevated,
            activeforeground=self.theme.text,
            relief="flat",
            bd=0,
            font=self.fonts.text(8),
            padx=10,
            pady=6,
            cursor="hand2",
        )
        group_button.pack(side="left")
        if trash_only:
            tk.Label(
                controls,
                text="Restore returns an item to the library. Delete removes only the index record.",
                bg=self.theme.bg,
                fg=self.theme.dim,
                font=self.fonts.text(8),
            ).pack(side="right")

        area = tk.Frame(self.content, bg=self.theme.bg)
        area.pack(fill="both", expand=True)

        def open_item(photo):
            self.open_photo(photo)

        def restore_item(photo_id: int):
            db.restore_photo(photo_id)
            self.show_trash()

        def delete_item(photo_id: int):
            if messagebox.askyesno(
                "Delete from library",
                "Remove this item from the DrishtiX library permanently?\n\n"
                "The original file on disk will NOT be deleted.",
            ):
                db.permanently_delete_photo(photo_id)
                self.show_trash()

        def refresh(*_args) -> None:
            for child in area.winfo_children():
                child.destroy()
            rows = db.all_photos(
                search.get(),
                category.get(),
                sort.get(),
                include_archived,
                favorites_only,
                trash_only,
                media_type=media_type,
            )
            if archived_only:
                rows = [row for row in rows if row.get("is_archived")]
            count_label.configure(text=f"{len(rows):,} {plural(len(rows), 'item')}  ·  local")
            if not rows:
                total_library = db.stats()
                if total_library["photos"] + total_library["trash"] == 0:
                    EmptyState(
                        area,
                        self.theme,
                        self.fonts,
                        "\uE91B",
                        "Your library is ready for its first folder.",
                        "Scan a folder of photos or videos. DrishtiX indexes it on this device, "
                        "builds previews, and keeps your original files exactly where they are.",
                        "+  Scan a folder",
                        self.start_scan,
                    ).pack(anchor="w", pady=24)
                elif trash_only:
                    EmptyState(
                        area, self.theme, self.fonts, "\uE74D", "Trash is empty.",
                        "Items moved here keep their original files. Restore anything you want back in the library.",
                    ).pack(anchor="w", pady=24)
                else:
                    def clear_filters():
                        search.set("")
                        category.set("All")
                        sort.set("Newest")
                        refresh()

                    EmptyState(
                        area,
                        self.theme,
                        self.fonts,
                        "\uE721",
                        "No media matches these filters.",
                        "Try a different search term or clear the category filter to see the rest of your library.",
                        "Clear filters",
                        clear_filters,
                    ).pack(anchor="w", pady=24)
                return
            grid = PhotoGrid(
                area,
                self,
                rows,
                group_by_month=bool(group.get()) and sort.get() in ("Newest", "Oldest"),
                trash_mode=trash_only,
                on_open=open_item,
                on_restore=restore_item,
                on_delete=delete_item,
            )
            grid.pack(fill="x")
            self.current_grid = grid

        search.on_change = lambda _value: self._debounce("library", 180, refresh)
        category.trace_add("write", lambda *_: refresh())
        sort.trace_add("write", lambda *_: refresh())
        group_button.configure(command=refresh)
        refresh()
        self.after_idle(self._update_scrollregion)

    # ---------------------------------------------------------------- albums

    def show_albums(self) -> None:
        self.clear("Albums", "Curated collections from your local library.")
        top = tk.Frame(self.content, bg=self.theme.bg)
        top.pack(fill="x", pady=(0, 14))
        tk.Label(
            top,
            text="Your albums",
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.fonts.display(16, "bold"),
            anchor="w",
        ).pack(side="left")
        make_button(
            top,
            "+  New album",
            self.create_album_dialog,
            self.theme,
            self.fonts,
            "primary",
        ).pack(side="right")

        rows = db.albums_list()
        if not rows:
            EmptyState(
                self.content,
                self.theme,
                self.fonts,
                "\uE8B7",
                "Bring related moments together.",
                "Create an album, then add photos and videos from your library. "
                "Removing an item from an album never deletes the original file.",
                "+  Create your first album",
                self.create_album_dialog,
            ).pack(anchor="w", pady=22)
            return

        holder = tk.Frame(self.content, bg=self.theme.bg)
        holder.pack(fill="both", expand=True)
        cards: list[tk.Frame] = []

        def layout_cards(event=None):
            try:
                width = holder.winfo_width() or 900
                columns = max(2, min(3, width // 300))
                for index, card in enumerate(cards):
                    card.grid(
                        row=index // columns,
                        column=index % columns,
                        sticky="nsew",
                        padx=(0, 12) if index % columns < columns - 1 else 0,
                        pady=(0, 12),
                    )
                for column in range(columns):
                    holder.grid_columnconfigure(column, weight=1)
            except tk.TclError:
                # The page was rebuilt while this reflow was still queued.
                return

        for album in rows:
            card = tk.Frame(
                holder,
                bg=self.theme.panel,
                highlightthickness=1,
                highlightbackground=self.theme.border,
            )
            cover_photo = db.album_cover_photo(album["id"])
            if cover_photo:
                future = self.thumbnail_service.submit(cover_photo, (280, 158))
                cover = AsyncImage(
                    card,
                    self,
                    future,
                    (280, 158),
                    self.theme,
                    self.fonts,
                    glyph="\uE8B7",
                    bg=self.theme.panel2,
                )
                cover.pack(fill="x")
            else:
                placeholder = tk.Frame(
                    card, bg=self.theme.panel2, height=158, width=280
                )
                placeholder.pack(fill="x")
                placeholder.pack_propagate(False)
                tk.Label(
                    placeholder,
                    text="\uE8B7",
                    bg=self.theme.panel2,
                    fg=self.theme.dim,
                    font=self.fonts.icon(30),
                ).pack(expand=True)

            body = tk.Frame(card, bg=self.theme.panel, padx=14, pady=12)
            body.pack(fill="both", expand=True)
            tk.Label(
                body,
                text=album["name"],
                bg=self.theme.panel,
                fg=self.theme.text,
                font=self.fonts.display(12, "bold"),
                anchor="w",
            ).pack(anchor="w")
            tk.Label(
                body,
                text=f'{album["item_count"]:,} {plural(album["item_count"], "item")}',
                bg=self.theme.panel,
                fg=self.theme.muted,
                font=self.fonts.text(8),
                anchor="w",
            ).pack(anchor="w", pady=(3, 10))
            actions = tk.Frame(body, bg=self.theme.panel)
            actions.pack(fill="x")
            make_button(
                actions,
                "Open",
                lambda aid=album["id"], name=album["name"]: self.open_album(aid, name),
                self.theme,
                self.fonts,
                "primary",
                padx=12,
                pady=5,
            ).pack(side="left")
            make_button(
                actions,
                "Rename",
                lambda aid=album["id"], name=album["name"]: self.rename_album_dialog(aid, name),
                self.theme,
                self.fonts,
                "ghost",
                padx=8,
                pady=5,
            ).pack(side="left", padx=(4, 0))
            make_button(
                actions,
                "Delete",
                lambda aid=album["id"]: self.delete_album_action(aid),
                self.theme,
                self.fonts,
                "danger",
                padx=8,
                pady=5,
            ).pack(side="right")
            cards.append(card)
        holder.bind("<Configure>", layout_cards)
        self.after_idle(layout_cards)

    def create_album_dialog(self) -> None:
        name = simpledialog.askstring("Create album", "Album name:", parent=self)
        if not name:
            return
        try:
            db.create_album(name)
            self.show_albums()
        except Exception as exc:
            messagebox.showerror("Album", str(exc))

    def rename_album_dialog(self, album_id: int, old_name: str) -> None:
        name = simpledialog.askstring(
            "Rename album", "New album name:", initialvalue=old_name, parent=self
        )
        if not name:
            return
        try:
            db.rename_album(album_id, name)
            self.show_albums()
        except Exception as exc:
            messagebox.showerror("Album", str(exc))

    def delete_album_action(self, album_id: int) -> None:
        if messagebox.askyesno(
            "Delete album",
            "Delete this album? Photos and videos in your library will not be deleted.",
        ):
            db.delete_album(album_id)
            self.show_albums()

    def open_album(self, album_id: int, name: str) -> None:
        self._current_album = (album_id, name)
        rows = db.all_photos(album_id=album_id, include_archived=True)
        self.clear("Album", f"{name}  ·  {len(rows):,} {plural(len(rows), 'item')}", nav="Albums")
        self._current_page = "Album"
        self.page_title.configure(text=name)
        self.page_subtitle.configure(text=f"Album  ·  {len(rows):,} {plural(len(rows), 'item')}")
        top = tk.Frame(self.content, bg=self.theme.bg)
        top.pack(fill="x", pady=(0, 12))
        make_button(
            top,
            "←  Back to albums",
            self.show_albums,
            self.theme,
            self.fonts,
            "ghost",
        ).pack(side="left")
        make_button(
            top,
            "+  Add photos",
            lambda: self.add_to_album(album_id, name),
            self.theme,
            self.fonts,
            "primary",
        ).pack(side="left", padx=(8, 0))

        if not rows:
            EmptyState(
                self.content,
                self.theme,
                self.fonts,
                "\uE8B7",
                "This album is empty.",
                "Add photos or videos from your library. The originals stay in their folders.",
                "+  Add photos",
                lambda: self.add_to_album(album_id, name),
                "Back to albums",
                self.show_albums,
            ).pack(anchor="w", pady=22)
            return
        grid = PhotoGrid(
            self.content, self, rows, on_open=self.open_photo, group_by_month=True
        )
        grid.pack(fill="x", pady=(0, 18))
        self.current_grid = grid

        manage = tk.Frame(self.content, bg=self.theme.bg)
        manage.pack(fill="x", pady=(4, 0))
        SectionLabel(
            manage, self.theme, self.fonts, "Manage album items"
        ).pack(fill="x", pady=(0, 8))
        for item in rows:
            line = tk.Frame(
                manage,
                bg=self.theme.panel,
                highlightthickness=1,
                highlightbackground=self.theme.border_soft,
                padx=12,
                pady=7,
            )
            line.pack(fill="x", pady=2)
            tk.Label(
                line,
                text=truncate(Path(item["path"]).name, 70),
                bg=self.theme.panel,
                fg=self.theme.text,
                font=self.fonts.text(8),
                anchor="w",
            ).pack(side="left", fill="x", expand=True)
            make_button(
                line,
                "Set cover",
                lambda pid=item["id"]: self._set_album_cover(album_id, pid, name),
                self.theme,
                self.fonts,
                "ghost",
                padx=8,
                pady=3,
            ).pack(side="right", padx=(4, 0))
            make_button(
                line,
                "Remove",
                lambda pid=item["id"]: self._remove_album_item(album_id, pid, name),
                self.theme,
                self.fonts,
                "danger",
                padx=8,
                pady=3,
            ).pack(side="right")

    def _remove_album_item(self, album_id: int, photo_id: int, name: str) -> None:
        if messagebox.askyesno(
            "Remove from album",
            "Remove this item from the album? The original file stays in your library.",
        ):
            db.album_remove_photo(album_id, photo_id)
            self.open_album(album_id, name)

    def _set_album_cover(self, album_id: int, photo_id: int, name: str) -> None:
        try:
            db.set_album_cover(album_id, photo_id)
            self.open_album(album_id, name)
        except Exception as exc:
            messagebox.showerror("Album cover", str(exc))

    def add_to_album(self, album_id: int, name: str) -> None:
        rows = db.all_photos()
        if not rows:
            messagebox.showinfo("Add photos", "Scan a folder first.")
            return
        existing = {item["id"] for item in db.all_photos(album_id=album_id, include_archived=True)}
        available = [row for row in rows if row["id"] not in existing]
        if not available:
            messagebox.showinfo("Add photos", "Every library item is already in this album.")
            return

        window = tk.Toplevel(self)
        window.title(f"Add items to {name}")
        window.configure(bg=self.theme.bg)
        window.geometry("1040x760")
        window.transient(self)
        header = tk.Frame(window, bg=self.theme.bg, padx=24, pady=18)
        header.pack(fill="x")
        tk.Label(
            header,
            text=f"Add to {name}",
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.fonts.display(18, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Select any items below. Existing album items are hidden.",
            bg=self.theme.bg,
            fg=self.theme.muted,
            font=self.fonts.text(9),
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        scroll = ScrollFrame(window, self.theme)
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        footer = tk.Frame(window, bg=self.theme.bg)
        footer.pack(fill="x", padx=24, pady=(0, 18))
        selected_count = tk.Label(
            footer,
            text="0 selected",
            bg=self.theme.bg,
            fg=self.theme.muted,
            font=self.fonts.text(9),
        )
        selected_count.pack(side="left", pady=8)

        grid_holder: dict[str, PhotoGrid | None] = {"grid": None}

        def update_count(count: int) -> None:
            selected_count.configure(text=f"{count} selected")

        grid = PhotoGrid(
            scroll.inner,
            self,
            available,
            selectable=True,
            page_size=100,
            on_selection_change=update_count,
        )
        grid.pack(fill="x")
        grid_holder["grid"] = grid
        scroll.bind_wheel(window)

        make_button(
            footer,
            "Cancel",
            window.destroy,
            self.theme,
            self.fonts,
            "secondary",
        ).pack(side="right", pady=8)
        def save():
            selected = sorted(grid.selected)
            if not selected:
                messagebox.showinfo("Add photos", "Select at least one item.", parent=window)
                return
            for photo_id in selected:
                db.album_add_photo(album_id, photo_id)
            window.destroy()
            self.open_album(album_id, name)

        make_button(
            footer, "Add selected", save, self.theme, self.fonts, "primary"
        ).pack(side="right", padx=(0, 8), pady=8)

    # -------------------------------------------------------------- smart search

    def show_smart_search(self, initial: str = "") -> None:
        self.clear(
            "Smart Search",
            "Search filenames, people you have named, dates, categories and media types.",
        )
        bar = tk.Frame(self.content, bg=self.theme.bg)
        bar.pack(fill="x", pady=(0, 10))
        search = SearchBox(
            bar,
            self.theme,
            self.fonts,
            placeholder="Try “Maya”, “screenshots”, “videos”, “2025” or “favorites”…",
        )
        search.pack(fill="x", expand=True)
        if initial:
            search.set(initial)
        hints = tk.Frame(self.content, bg=self.theme.bg)
        hints.pack(fill="x", pady=(0, 14))
        for label, query in (
            ("This year", "this year"),
            ("Videos", "videos"),
            ("Favorites", "favorites"),
            ("People", "people"),
            ("Screenshots", "screenshots"),
        ):
            make_button(
                hints,
                label,
                lambda value=query: (search.set(value), run()),
                self.theme,
                self.fonts,
                "ghost",
                padx=9,
                pady=4,
            ).pack(side="left", padx=(0, 6))

        summary = tk.Label(
            self.content,
            text="",
            bg=self.theme.bg,
            fg=self.theme.muted,
            font=self.fonts.text(8),
            anchor="w",
        )
        summary.pack(anchor="w", pady=(0, 8))
        area = tk.Frame(self.content, bg=self.theme.bg)
        area.pack(fill="both", expand=True)

        def run(*_args) -> None:
            for child in area.winfo_children():
                child.destroy()
            query = search.get()
            rows = db.smart_search(query) if query else db.all_photos()
            summary.configure(text=f"{len(rows):,} results  ·  searched locally")
            if not rows:
                EmptyState(
                    area,
                    self.theme,
                    self.fonts,
                    "\uE721",
                    "No matches in this library.",
                    "Smart Search is metadata-aware: it searches filenames, people, dates, "
                    "categories, favorites and media types. It does not claim visual scene recognition.",
                ).pack(anchor="w", pady=22)
                return
            grid = PhotoGrid(
                area, self, rows, on_open=self.open_photo, group_by_month=False
            )
            grid.pack(fill="x")
            self.current_grid = grid

        search.on_change = lambda _value: self._debounce("search", 160, run)
        search.on_submit = lambda _value: run()
        run()

    # ----------------------------------------------------------------- people

    def show_people(self) -> None:
        self.clear("People", "Named people and the photos connected to them.")
        top = tk.Frame(self.content, bg=self.theme.bg)
        top.pack(fill="x", pady=(0, 12))
        search = SearchBox(
            top, self.theme, self.fonts, placeholder="Search people by name…"
        )
        search.pack(side="left", fill="x", expand=True)
        make_button(
            top,
            "+  Add person",
            self.add_person,
            self.theme,
            self.fonts,
            "primary",
        ).pack(side="right", padx=(10, 0))
        area = tk.Frame(self.content, bg=self.theme.bg)
        area.pack(fill="both", expand=True)
        cards: list[tk.Frame] = []

        def layout(event=None):
            try:
                width = area.winfo_width() or 900
                columns = max(2, min(4, width // 250))
                for index, card in enumerate(cards):
                    card.grid(
                        row=index // columns,
                        column=index % columns,
                        sticky="nsew",
                        padx=(0, 12) if index % columns < columns - 1 else 0,
                        pady=(0, 12),
                    )
                for column in range(columns):
                    area.grid_columnconfigure(column, weight=1)
            except tk.TclError:
                # The page was rebuilt while this reflow was still queued.
                return

        def refresh(*_args) -> None:
            for child in area.winfo_children():
                child.destroy()
            cards.clear()
            people = db.people_list(search.get())
            if not people:
                EmptyState(
                    area,
                    self.theme,
                    self.fonts,
                    "\uE716",
                    "No people yet.",
                    "People profiles grow from face recognition and the matches you confirm. "
                    "You can also add a person manually and assign faces later.",
                    "+  Add person",
                    self.add_person,
                    "Scan a folder",
                    self.start_scan,
                ).pack(anchor="w", pady=22)
                return
            for person in people:
                card = tk.Frame(
                    area,
                    bg=self.theme.panel,
                    highlightthickness=1,
                    highlightbackground=self.theme.border,
                    padx=16,
                    pady=14,
                )
                avatar = tk.Canvas(
                    card, width=64, height=64, bg=self.theme.panel, highlightthickness=0
                )
                avatar.create_oval(3, 3, 61, 61, outline=self.theme.border, width=1)
                avatar.create_oval(10, 10, 54, 54, outline=self.theme.accent, width=1)
                avatar.create_text(
                    32, 31, text=person["name"][:1].upper(), fill=self.theme.cyan,
                    font=self.fonts.display(20, "bold")
                )
                avatar.pack(anchor="w")
                tk.Label(
                    card,
                    text=person["name"],
                    bg=self.theme.panel,
                    fg=self.theme.text,
                    font=self.fonts.display(12, "bold"),
                    anchor="w",
                ).pack(anchor="w", pady=(10, 2))
                tk.Label(
                    card,
                    text=f'{person["photo_count"]:,} photos  ·  {person["face_count"]:,} faces',
                    bg=self.theme.panel,
                    fg=self.theme.muted,
                    font=self.fonts.text(8),
                    anchor="w",
                ).pack(anchor="w", pady=(0, 10))
                actions = tk.Frame(card, bg=self.theme.panel)
                actions.pack(fill="x")
                make_button(
                    actions,
                    "Open gallery",
                    lambda pid=person["id"], name=person["name"]: self.show_person(pid, name),
                    self.theme,
                    self.fonts,
                    "primary",
                    padx=10,
                    pady=5,
                ).pack(side="left")
                make_button(
                    actions,
                    "Rename",
                    lambda pid=person["id"]: self.rename_person(pid),
                    self.theme,
                    self.fonts,
                    "ghost",
                    padx=6,
                    pady=5,
                ).pack(side="left", padx=(4, 0))
                make_button(
                    actions,
                    "Delete",
                    lambda pid=person["id"]: self.remove_person(pid),
                    self.theme,
                    self.fonts,
                    "danger",
                    padx=6,
                    pady=5,
                ).pack(side="right")
                cards.append(card)
            layout()

        search.on_change = lambda _value: self._debounce("people", 160, refresh)
        area.bind("<Configure>", layout)
        refresh()

    def add_person(self) -> None:
        name = simpledialog.askstring("Add person", "Enter a person's name:", parent=self)
        if name and name.strip():
            try:
                db.create_person(name)
                self.show_people()
            except Exception as exc:
                messagebox.showerror("Could not add person", str(exc))

    def rename_person(self, person_id: int) -> None:
        current = next(
            (person["name"] for person in db.people_list() if person["id"] == person_id), ""
        )
        name = simpledialog.askstring(
            "Rename person", "New name:", initialvalue=current, parent=self
        )
        if name and name.strip():
            try:
                db.rename_person(person_id, name)
                self.show_people()
            except Exception as exc:
                messagebox.showerror("Could not rename person", str(exc))

    def remove_person(self, person_id: int) -> None:
        if messagebox.askyesno(
            "Delete person",
            "Delete this person profile? Assigned faces become unassigned; photos stay in the library.",
        ):
            db.delete_person(person_id)
            self.show_people()

    def show_person(self, person_id: int, name: str) -> None:
        self._current_person = (person_id, name)
        photos = db.person_photos(person_id)
        self.clear(
            "Person",
            f"{name}  ·  {len(photos):,} confirmed {plural(len(photos), 'photo')}",
            nav="People",
        )
        self._current_page = "Person"
        self.page_title.configure(text=name)
        self.page_subtitle.configure(
            text=f"People  ·  {len(photos):,} {plural(len(photos), 'photo')}"
        )
        make_button(
            self.content,
            "←  Back to people",
            self.show_people,
            self.theme,
            self.fonts,
            "ghost",
        ).pack(anchor="w", pady=(0, 14))
        if not photos:
            EmptyState(
                self.content,
                self.theme,
                self.fonts,
                "\uE716",
                "No confirmed photos for this person yet.",
                "Confirm a match in Match Review, or assign an unassigned face to this person.",
                "Open Match Review",
                self.show_review,
                "Back to people",
                self.show_people,
            ).pack(anchor="w", pady=18)
            return
        grid = PhotoGrid(self.content, self, photos, on_open=self.open_photo, group_by_month=True)
        grid.pack(fill="x")
        self.current_grid = grid

    # ------------------------------------------------------------ match review

    def show_review(self) -> None:
        self.clear("Match Review", "Visually verify possible face matches before assigning them.")
        rows = db.pending_candidates()
        if not rows:
            EmptyState(
                self.content,
                self.theme,
                self.fonts,
                "\uE73E",
                "You're all caught up.",
                "There are no possible matches waiting for confirmation. New suggestions appear "
                "after a scan, or instantly when you name an unassigned face.",
                "Open People",
                self.show_people,
                "Back to dashboard",
                self.show_dashboard,
            ).pack(anchor="w", pady=22)
            return
        self.review_rows = rows
        self.review_index = 0
        self.review_container = tk.Frame(self.content, bg=self.theme.bg)
        self.review_container.pack(fill="both", expand=True)
        self._render_review()

    def _render_review(self) -> None:
        for child in self.review_container.winfo_children():
            child.destroy()
        if self.review_index >= len(self.review_rows):
            EmptyState(
                self.review_container,
                self.theme,
                self.fonts,
                "\uE73E",
                "All suggestions reviewed.",
                "Your decisions are saved. Named people and their galleries are up to date.",
                "Back to dashboard",
                self.show_dashboard,
                "Open People",
                self.show_people,
            ).pack(anchor="w", pady=22)
            return
        row = self.review_rows[self.review_index]
        header = tk.Frame(self.review_container, bg=self.theme.bg)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(
            header,
            text=f"Suggestion {self.review_index + 1} of {len(self.review_rows)}",
            bg=self.theme.bg,
            fg=self.theme.accent,
            font=self.fonts.text(8, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header,
            text=f'Is this {row["person_name"]}?',
            bg=self.theme.bg,
            fg=self.theme.text,
            font=self.fonts.display(20, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(5, 3))
        tk.Label(
            header,
            text=f'Visual similarity signal: {row["similarity"] * 100:.1f}%  ·  Please verify visually',
            bg=self.theme.bg,
            fg=self.theme.muted,
            font=self.fonts.text(8),
            anchor="w",
        ).pack(anchor="w")

        images = tk.Frame(self.review_container, bg=self.theme.bg)
        images.pack(anchor="w", pady=(4, 16))
        try:
            original = ImageOps.exif_transpose(Image.open(row["photo_path"])).convert("RGB")
            original.thumbnail((460, 340), Image.Resampling.LANCZOS)
            p1 = ImageTk.PhotoImage(original)
            label = tk.Label(images, image=p1, bg=self.theme.panel)
            label.image = p1
            label.pack(side="left", padx=(0, 14))
        except Exception as exc:
            tk.Label(
                images,
                text=f"Unable to load photo: {exc}",
                bg=self.theme.bg,
                fg=self.theme.red,
                font=self.fonts.text(9),
            ).pack(side="left")
        try:
            face = crop_face(
                row["photo_path"],
                (row["x"], row["y"], row["w"], row["h"]),
                210,
            )
            if face is not None:
                p2 = ImageTk.PhotoImage(face)
                face_label = tk.Label(images, image=p2, bg=self.theme.panel)
                face_label.image = p2
                face_label.pack(side="left")
        except Exception:
            pass

        actions = tk.Frame(self.review_container, bg=self.theme.bg)
        actions.pack(anchor="w")
        make_button(
            actions,
            "Yes, same person",
            lambda: self._decide(True, row),
            self.theme,
            self.fonts,
            "primary",
            padx=18,
            pady=10,
        ).pack(side="left")
        make_button(
            actions,
            "No, different person",
            lambda: self._decide(False, row),
            self.theme,
            self.fonts,
            "secondary",
            padx=18,
            pady=10,
        ).pack(side="left", padx=(10, 0))
        make_button(
            actions,
            "Decide later",
            lambda: self._skip_review(),
            self.theme,
            self.fonts,
            "ghost",
            padx=12,
            pady=10,
        ).pack(side="left", padx=(10, 0))

        remaining = len(self.review_rows) - self.review_index
        if remaining > 1:
            bulk = tk.Frame(self.review_container, bg=self.theme.bg)
            bulk.pack(anchor="w", pady=(18, 0))
            make_button(
                bulk,
                f"Confirm all {remaining:,} remaining",
                self._confirm_all_review,
                self.theme,
                self.fonts,
                "ghost",
                padx=12,
                pady=8,
            ).pack(side="left")
            tk.Label(
                bulk,
                text="Labels every suggestion shown on this page.",
                bg=self.theme.bg,
                fg=self.theme.dim,
                font=self.fonts.text(8),
            ).pack(side="left", padx=(10, 0))

    def _confirm_all_review(self) -> None:
        remaining = len(self.review_rows) - self.review_index
        if remaining <= 0:
            return
        if not messagebox.askyesno(
            "Confirm all matches",
            f"Assign all {remaining:,} remaining suggestions to the named people?\n\n"
            "Only do this if you have checked the suggestions. You can still move a "
            "face to someone else from Unassigned Faces later.",
        ):
            return
        try:
            confirmed, assigned = db.confirm_all_pending_candidates()
        except Exception as exc:
            messagebox.showerror("Could not confirm matches", str(exc))
            return
        self.review_index = 0
        self.show_review()
        self._refresh_status_right()
        self._set_status(
            f"Confirmed {confirmed:,} matches; {assigned:,} faces assigned.",
            self.theme.green,
        )

    def _decide(self, yes: bool, row: dict[str, Any]) -> None:
        try:
            db.decide_candidate(row["candidate_id"], yes)
        except Exception as exc:
            messagebox.showerror("Could not save decision", str(exc))
            return
        self.review_index += 1
        self._render_review()
        self._refresh_status_right()

    def _skip_review(self) -> None:
        self.review_index += 1
        if self.review_index >= len(self.review_rows):
            self.review_index = 0
        self._render_review()

    # ----------------------------------------------------------- unassigned

    def show_unassigned(self) -> None:
        self.clear(
            "Unassigned Faces",
            "Detected faces waiting for a name. Assigning a face is always under your control.",
        )
        rows = db.unassigned_faces()
        if not rows:
            EmptyState(
                self.content,
                self.theme,
                self.fonts,
                "\uE77B",
                "No unassigned faces found.",
                "This is expected if no faces have been detected yet. Face detection runs locally "
                "and the model downloads once on first use. If your library already has photos, "
                "you can rebuild the face index now.",
                "Rebuild face index",
                self._start_reindex,
                "Scan a folder",
                self.start_scan,
            ).pack(anchor="w", pady=22)
            return
        people = db.people_list()
        tk.Label(
            self.content,
            text=f"{len(rows):,} detected faces are not assigned to a person yet.",
            bg=self.theme.bg,
            fg=self.theme.muted,
            font=self.fonts.text(9),
            anchor="w",
        ).pack(anchor="w", pady=(0, 12))
        holder = tk.Frame(self.content, bg=self.theme.bg)
        holder.pack(fill="both", expand=True)
        cards: list[tk.Frame] = []

        def layout(event=None):
            try:
                width = holder.winfo_width() or 900
                columns = max(2, min(4, width // 270))
                for index, card in enumerate(cards):
                    card.grid(
                        row=index // columns,
                        column=index % columns,
                        sticky="nsew",
                        padx=(0, 12) if index % columns < columns - 1 else 0,
                        pady=(0, 12),
                    )
                for column in range(columns):
                    holder.grid_columnconfigure(column, weight=1)
            except tk.TclError:
                # The page was rebuilt while this reflow was still queued.
                return

        for row in rows:
            card = tk.Frame(
                holder,
                bg=self.theme.panel,
                highlightthickness=1,
                highlightbackground=self.theme.border,
                padx=12,
                pady=12,
            )
            future = self.thumbnail_service.submit_face(
                row["path"],
                (row["x"], row["y"], row["w"], row["h"]),
                132,
            )
            face = AsyncImage(
                card,
                self,
                future,
                (132, 132),
                self.theme,
                self.fonts,
                glyph="\uE77B",
                bg=self.theme.panel2,
            )
            face.pack()
            tk.Label(
                card,
                text=truncate(Path(row["path"]).name, 28),
                bg=self.theme.panel,
                fg=self.theme.text,
                font=self.fonts.text(8, "bold"),
                anchor="w",
                wraplength=240,
                justify="left",
            ).pack(anchor="w", pady=(9, 7))
            if people:
                labels = [f'{person["id"]} — {person["name"]}' for person in people]
                choice = tk.StringVar(value=labels[0])
                ttk.Combobox(
                    card,
                    textvariable=choice,
                    state="readonly",
                    values=labels,
                    width=24,
                ).pack(fill="x", pady=(0, 6))
                make_button(
                    card,
                    "Assign",
                    lambda face_id=row["face_id"], var=choice: self._assign(face_id, var.get()),
                    self.theme,
                    self.fonts,
                    "primary",
                    padx=10,
                    pady=5,
                ).pack(fill="x")
            else:
                tk.Label(
                    card,
                    text="No people yet",
                    bg=self.theme.panel,
                    fg=self.theme.dim,
                    font=self.fonts.text(8),
                    anchor="w",
                ).pack(anchor="w", pady=(0, 6))
            make_button(
                card,
                "+  Create person & assign",
                lambda face_id=row["face_id"]: self.assign_new_person(face_id),
                self.theme,
                self.fonts,
                "ghost",
                padx=8,
                pady=4,
            ).pack(fill="x", pady=(5, 0))
            cards.append(card)
        holder.bind("<Configure>", layout)
        self.after_idle(layout)

    def _assign(self, face_id: int, selection: str) -> None:
        try:
            person_id = int(selection.split("—", 1)[0].strip())
            person_name = selection.split("—", 1)[1].strip() if "—" in selection else "this person"
            db.assign_face(face_id, person_id)
        except Exception as exc:
            messagebox.showerror("Assignment failed", str(exc))
            return
        self._match_stored_faces(person_id, person_name)
        self.show_unassigned()
        self._refresh_status_right()

    def assign_new_person(self, face_id: int) -> None:
        name = simpledialog.askstring(
            "Create person", "Enter the person's name:", parent=self
        )
        if not name or not name.strip():
            return
        name = name.strip()
        try:
            person_id = db.create_person(name)
            db.assign_face(face_id, person_id)
        except Exception as exc:
            messagebox.showerror("Could not create person", str(exc))
            return
        result = self._match_stored_faces(person_id, name)
        self.show_unassigned()
        self._refresh_status_right()
        self._report_person_search(name, result)

    def _match_stored_faces(
        self, person_id: int, person_name: str
    ) -> dict[str, Any] | None:
        """Compare one name against stored face vectors — no photos are re-read.

        Naming a person used to trigger a full AI re-index, which decodes every
        photo and re-runs detection. The vectors were already stored during the
        scan, so the same result is available instantly.
        """
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            result = match_person_across_library(person_id)
        except Exception:
            logger.exception("Could not match stored faces for person %s", person_id)
            messagebox.showerror(
                "Could not check stored faces",
                "The assignment was saved, but the rest of the library was not compared.\n\n"
                f"Details were written to:\n{LOG_PATH}",
            )
            return None
        finally:
            self.configure(cursor="")
        if result["assigned"] or result["queued"]:
            self._set_status(
                f"{person_name}: {result['assigned']:,} more faces assigned, "
                f"{result['queued']:,} waiting in Match Review.",
                self.theme.green,
            )
        elif result["compared"]:
            self._set_status(
                f"No other stored faces matched {person_name}.", self.theme.muted
            )
        return result

    def _report_person_search(self, name: str, result: dict[str, Any] | None) -> None:
        if result is None:
            return
        if not result["compared"]:
            if messagebox.askyesno(
                "No stored faces to compare",
                "There are no other detected faces in the local index yet.\n\n"
                "Run the AI face index now? It reads each photo once so future "
                "names can be matched instantly.",
            ):
                self._start_reindex()
            return
        lines = [
            f"{name} was created.",
            "",
            f"Faces labelled automatically: {result['assigned']:,}",
            f"Possible matches waiting in Match Review: {result['queued']:,}",
        ]
        if result["queued"]:
            lines.extend(
                [
                    "",
                    "Open Match Review to confirm them. If you trust very confident "
                    "matches, turn on automatic assignment in Settings.",
                ]
            )
        messagebox.showinfo("Person created", "\n".join(lines))

    # ------------------------------------------------------------ other photos

    def show_other_photos(self) -> None:
        self.clear(
            "Other Photos",
            "Images with no detected face. This does not prove there is no person in them.",
        )
        rows = db.other_photos()
        tk.Label(
            self.content,
            text=(
                f"{len(rows):,} images currently have no detected faces. Face detection can miss "
                "small, turned-away, or heavily cropped faces, so treat this as a helpful filter—not a guarantee."
            ),
            bg=self.theme.bg,
            fg=self.theme.muted,
            font=self.fonts.text(9),
            wraplength=900,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(0, 14))
        if rows:
            grid = PhotoGrid(
                self.content, self, rows, on_open=self.open_photo, group_by_month=True
            )
            grid.pack(fill="x")
            self.current_grid = grid
        else:
            EmptyState(
                self.content,
                self.theme,
                self.fonts,
                "\uE8B9",
                "No face-free images in the indexed library.",
                "Every indexed image either has a detected face or the library is still empty.",
                "Open All Photos",
                self.show_all_photos,
            ).pack(anchor="w", pady=22)

    # ----------------------------------------------------------- scan history

    def show_history(self) -> None:
        self.clear("Scan History", "A local record of folder scans and their results.")
        rows = db.history()
        if not rows:
            EmptyState(
                self.content,
                self.theme,
                self.fonts,
                "\uE81C",
                "No scans yet.",
                "Every folder scan is recorded here with its indexed count, detected faces, "
                "duplicates and errors.",
                "+  Scan a folder",
                self.start_scan,
            ).pack(anchor="w", pady=22)
            return
        columns = ("folder", "started_at", "status", "photos_seen", "faces_found", "skipped", "errors")
        labels = ("Folder", "Started", "Status", "Indexed", "Faces", "Duplicates", "Errors")
        tree = ttk.Treeview(self.content, columns=columns, show="headings")
        for column, label in zip(columns, labels):
            tree.heading(column, text=label)
            tree.column(column, width=340 if column == "folder" else 105, anchor="w")
        for row in rows:
            tree.insert(
                "",
                "end",
                values=tuple(row[column] for column in columns),
            )
        tree.pack(fill="both", expand=True, pady=(0, 8))
        make_button(
            self.content,
            "+  Scan a folder",
            self.start_scan,
            self.theme,
            self.fonts,
            "primary",
        ).pack(anchor="w", pady=(8, 0))

    # --------------------------------------------------------------- settings

    def show_settings(self) -> None:
        self.clear("Settings", "Appearance, recognition, and the location of your local data.")
        cfg = dict(self.settings)

        appearance, appearance_inner = self._panel(self.content)
        appearance.pack(fill="x", pady=(0, 12))
        tk.Label(
            appearance_inner, text="APPEARANCE", bg=self.theme.panel, fg=self.theme.accent,
            font=self.fonts.text(7, "bold"), anchor="w"
        ).pack(anchor="w", pady=(0, 8))
        tk.Label(
            appearance_inner, text="Theme", bg=self.theme.panel, fg=self.theme.text,
            font=self.fonts.text(9, "bold"), anchor="w"
        ).pack(anchor="w")
        theme_var = tk.StringVar(value=cfg.get("theme", "Dark"))
        ttk.Combobox(
            appearance_inner,
            textvariable=theme_var,
            state="readonly",
            values=["Dark", "Light", "Ocean"],
            width=18,
        ).pack(anchor="w", pady=(6, 4))
        tk.Label(
            appearance_inner,
            text="Theme changes take effect after restarting DrishtiX.",
            bg=self.theme.panel,
            fg=self.theme.muted,
            font=self.fonts.text(8),
            anchor="w",
        ).pack(anchor="w")

        recognition, recognition_inner = self._panel(self.content)
        recognition.pack(fill="x", pady=(0, 12))
        tk.Label(
            recognition_inner, text="RECOGNITION", bg=self.theme.panel, fg=self.theme.accent,
            font=self.fonts.text(7, "bold"), anchor="w"
        ).pack(anchor="w", pady=(0, 8))
        auto = tk.BooleanVar(value=bool(cfg.get("auto_assign", False)))
        tk.Checkbutton(
            recognition_inner,
            text="Automatically assign only very strong, unambiguous matches",
            variable=auto,
            bg=self.theme.panel,
            fg=self.theme.text,
            selectcolor=self.theme.panel2,
            activebackground=self.theme.panel,
            activeforeground=self.theme.text,
            font=self.fonts.text(9),
            anchor="w",
            cursor="hand2",
        ).pack(anchor="w", pady=(0, 10))
        review_var = tk.DoubleVar(value=float(cfg.get("review_threshold", 0.38)))
        auto_var = tk.DoubleVar(value=float(cfg.get("auto_threshold", 0.52)))

        def threshold_row(label: str, variable: tk.DoubleVar, low: float, high: float, note: str):
            row = tk.Frame(recognition_inner, bg=self.theme.panel)
            row.pack(fill="x", pady=(4, 2))
            tk.Label(
                row, text=label, bg=self.theme.panel, fg=self.theme.text,
                font=self.fonts.text(9), anchor="w"
            ).pack(side="left")
            value_label = tk.Label(
                row, text=f"{variable.get():.2f}", bg=self.theme.panel,
                fg=self.theme.cyan, font=self.fonts.mono(9, "bold")
            )
            value_label.pack(side="right")
            scale = ttk.Scale(
                recognition_inner,
                from_=low,
                to=high,
                variable=variable,
                orient="horizontal",
                length=440,
            )
            scale.pack(anchor="w", pady=(2, 0))
            variable.trace_add("write", lambda *_: value_label.configure(text=f"{variable.get():.2f}"))
            tk.Label(
                recognition_inner, text=note, bg=self.theme.panel, fg=self.theme.dim,
                font=self.fonts.text(8), anchor="w", justify="left", wraplength=760
            ).pack(anchor="w", pady=(2, 10))

        threshold_row(
            "Review threshold (cosine similarity)",
            review_var,
            0.25,
            0.80,
            "Matches above this score appear in Match Review. Higher values reduce suggestions.",
        )
        threshold_row(
            "Automatic assignment threshold",
            auto_var,
            0.40,
            0.90,
            "Only used when automatic assignment is enabled. Keep this high until you trust the results.",
        )
        tk.Label(
            recognition_inner,
            text="Similarity thresholds are model-dependent. Review suggestions visually; they are not identity verification.",
            bg=self.theme.panel,
            fg=self.theme.muted,
            font=self.fonts.text(8),
            wraplength=800,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(0, 10))

        data_card, data_inner = self._panel(self.content)
        data_card.pack(fill="x", pady=(0, 12))
        tk.Label(
            data_inner, text="LIBRARY & DATA", bg=self.theme.panel, fg=self.theme.accent,
            font=self.fonts.text(7, "bold"), anchor="w"
        ).pack(anchor="w", pady=(0, 8))
        info = db.database_info()
        for label, value in (
            ("Database", info["path"]),
            ("Size", human_bytes(info["size"])),
            ("Schema version", str(info["version"])),
            ("Thumbnail cache", str(USER_DATA_DIR / "thumbnails")),
        ):
            row = tk.Frame(data_inner, bg=self.theme.panel)
            row.pack(fill="x", pady=2)
            tk.Label(
                row, text=label, bg=self.theme.panel, fg=self.theme.muted,
                font=self.fonts.text(8), width=16, anchor="w"
            ).pack(side="left")
            tk.Label(
                row, text=value, bg=self.theme.panel, fg=self.theme.text,
                font=self.fonts.mono(8), anchor="w", wraplength=760, justify="left"
            ).pack(side="left", fill="x", expand=True)
        buttons = tk.Frame(data_inner, bg=self.theme.panel)
        buttons.pack(fill="x", pady=(10, 0))
        make_button(
            buttons, "Open data folder", self._open_data_folder, self.theme, self.fonts, "secondary"
        ).pack(side="left")
        make_button(
            buttons, "Check database", self._check_database, self.theme, self.fonts, "ghost"
        ).pack(side="left", padx=(6, 0))
        make_button(
            buttons, "Open log file", self._open_log, self.theme, self.fonts, "ghost"
        ).pack(side="left", padx=(6, 0))
        make_button(
            buttons,
            "Rebuild AI face index",
            self._start_reindex,
            self.theme,
            self.fonts,
            "secondary",
        ).pack(side="right")

        def save() -> None:
            cfg.update(
                {
                    "theme": theme_var.get(),
                    "auto_assign": bool(auto.get()),
                    "review_threshold": round(float(review_var.get()), 3),
                    "auto_threshold": round(float(auto_var.get()), 3),
                }
            )
            try:
                save_settings(cfg)
                self.settings = cfg
                messagebox.showinfo(
                    "Settings saved",
                    "Recognition settings saved. Restart DrishtiX to apply a theme change.",
                )
            except Exception as exc:
                messagebox.showerror("Could not save settings", str(exc))

        save_row = tk.Frame(self.content, bg=self.theme.bg)
        save_row.pack(fill="x", pady=(0, 16))
        make_button(
            save_row, "Save settings", save, self.theme, self.fonts, "primary"
        ).pack(side="left")
        make_button(
            save_row, "Open About", self.show_about, self.theme, self.fonts, "ghost"
        ).pack(side="left", padx=(8, 0))

    def _open_data_folder(self) -> None:
        try:
            os.startfile(str(USER_DATA_DIR))
        except Exception as exc:
            messagebox.showerror("Could not open folder", str(exc))

    def _open_log(self) -> None:
        try:
            if LOG_PATH.is_file():
                os.startfile(str(LOG_PATH))
            else:
                messagebox.showinfo("Log file", "The log file has not been created yet.")
        except Exception as exc:
            messagebox.showerror("Could not open log", str(exc))

    def _check_database(self) -> None:
        info = db.database_info(check_integrity=True)
        messagebox.showinfo(
            "Database check",
            f"Path:\n{info['path']}\n\n"
            f"Size: {human_bytes(info['size'])}\n"
            f"Schema version: {info['version']}\n"
            f"Integrity: {info['integrity']}",
        )

    # ----------------------------------------------------------------- about

    def show_about(self) -> None:
        self.clear("About DrishtiX", "A local-first product from TantraYantra.")
        card, inner = self._panel(self.content, padx=28, pady=26)
        card.pack(fill="x", pady=(0, 14))
        try:
            with Image.open(asset_path("drishtix_icon.png")) as logo:
                logo = logo.convert("RGBA")
                logo.thumbnail((86, 86), Image.Resampling.LANCZOS)
                self.about_logo = ImageTk.PhotoImage(logo)
            tk.Label(inner, image=self.about_logo, bg=self.theme.panel).pack(anchor="w")
        except Exception:
            logger.debug("About logo could not be loaded", exc_info=True)
        tk.Label(
            inner, text="DrishtiX", bg=self.theme.panel, fg=self.theme.text,
            font=self.fonts.display(24, "bold"), anchor="w"
        ).pack(anchor="w", pady=(10, 2))
        tk.Label(
            inner, text=f"Version {self.version}  ·  Windows 11 x64  ·  Local-first",
            bg=self.theme.panel, fg=self.theme.accent, font=self.fonts.text(9, "bold"),
            anchor="w"
        ).pack(anchor="w")
        tk.Label(
            inner, text="Your Photos. Your People. Your Memories.",
            bg=self.theme.panel, fg=self.theme.muted, font=self.fonts.text(9),
            anchor="w"
        ).pack(anchor="w", pady=(8, 0))
        tk.Label(
            inner,
            text="A product by TantraYantra  ·  Open source under the MIT License",
            bg=self.theme.panel,
            fg=self.theme.cyan,
            font=self.fonts.text(9, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(10, 0))

        links = tk.Frame(self.content, bg=self.theme.bg)
        links.pack(fill="x", pady=(0, 18))
        make_button(
            links,
            "TantraYantra website",
            lambda: webbrowser.open("https://tantrayantra.github.io/tantrayantra-website/"),
            self.theme,
            self.fonts,
            "secondary",
        ).pack(side="left")
        make_button(
            links,
            "GitHub organisation",
            lambda: webbrowser.open("https://github.com/TantraYantra"),
            self.theme,
            self.fonts,
            "ghost",
        ).pack(side="left", padx=(8, 0))
        make_button(
            links,
            "Licenses",
            lambda: webbrowser.open(
                "https://github.com/TantraYantra/drishtix/blob/main/NOTICE"
            ),
            self.theme,
            self.fonts,
            "ghost",
        ).pack(side="left", padx=(8, 0))

        sections = [
            (
                "Built local-first",
                "Your original photos and videos stay in their existing folders. DrishtiX stores a "
                "local library index, albums, thumbnails and face-recognition data on this computer. "
                "AI inference runs locally after its models have been downloaded.",
            ),
            (
                "Search scope",
                "Smart Search is metadata-aware. It searches filenames, people you have named, dates, "
                "categories, favorites and media types. It does not claim visual scene understanding "
                "and never sends your library off-device.",
            ),
            (
                "Data location",
                f"{USER_DATA_DIR}\nDatabase: {db.DB_PATH}\nLog: {LOG_PATH}",
            ),
            (
                "AI models and licenses",
                "RetinaFace (MobileNetV2) face detection, MIT, \u00a9 2024 Yakhyokhuja "
                "Valikhujaev. AdaFace IR-18 face recognition, MIT, \u00a9 2022 Minchul "
                "Kim. Both are distributed by the UniFace project. The full third-party "
                "notices ship with the application as NOTICE.",
            ),
        ]
        for title, body in sections:
            tk.Label(
                self.content, text=title, bg=self.theme.bg, fg=self.theme.cyan,
                font=self.fonts.display(12, "bold"), anchor="w"
            ).pack(anchor="w", pady=(6, 4))
            tk.Label(
                self.content, text=body, bg=self.theme.bg, fg=self.theme.muted,
                font=self.fonts.text(9), wraplength=900, justify="left", anchor="w"
            ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            self.content,
            text="This release is a local-first foundation. Semantic scene search, editing and memory generation are not included.",
            bg=self.theme.bg,
            fg=self.theme.dim,
            font=self.fonts.text(8),
            anchor="w",
        ).pack(anchor="w", pady=(14, 0))

    # ---------------------------------------------------------------- viewer

    def open_photo(self, photo: dict[str, Any] | str) -> None:
        if isinstance(photo, str):
            photo = db.photo_by_path(photo) or {"path": photo, "media_type": "image"}
        path = Path(str(photo.get("path", "")))
        if not path.is_file():
            if messagebox.askyesno(
                "File not found",
                f"The original file is no longer at:\n{path}\n\n"
                "Remove this record from the DrishtiX library? The original was not modified.",
            ):
                if photo.get("id"):
                    db.permanently_delete_photo(int(photo["id"]))
                    self._refresh_current_page()
            return
        window = tk.Toplevel(self)
        self._viewer_windows.append(window)
        window.title(path.name)
        window.configure(bg="#05080f")
        window.geometry("1180x860")
        window.minsize(720, 480)
        window.transient(self)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.bind("<Destroy>", lambda event: self._forget_viewer(event, window))

        top = tk.Frame(window, bg="#05080f", padx=18, pady=12)
        top.pack(fill="x")
        tk.Label(
            top,
            text=truncate(path.name, 80),
            bg="#05080f",
            fg="#f2f6ff",
            font=self.fonts.text(10, "bold"),
            anchor="w",
        ).pack(side="left")
        make_button(
            top, "Close", window.destroy, self.theme, self.fonts, "ghost", padx=10, pady=5
        ).pack(side="right")

        if photo.get("media_type") == "video":
            self._open_video(str(path), window)
        else:
            self._show_image_viewer(window, path)

        actions = tk.Frame(window, bg="#05080f", padx=18, pady=12)
        actions.pack(fill="x", side="bottom")
        photo_id = photo.get("id")
        meta_bits = []
        if photo.get("width") and photo.get("height"):
            meta_bits.append(f'{photo["width"]} × {photo["height"]}')
        if photo.get("media_type") == "video":
            duration = human_duration(photo.get("duration"))
            if duration:
                meta_bits.append(duration)
        if photo.get("category"):
            meta_bits.append(str(photo["category"]))
        if photo.get("date_taken"):
            meta_bits.append(display_date(photo["date_taken"]))
        tk.Label(
            actions,
            text="  ·  ".join(meta_bits),
            bg="#05080f",
            fg="#8ea0ba",
            font=self.fonts.text(8),
        ).pack(side="left")

        if photo_id:
            flags = db.photo_flags(int(photo_id))
            make_button(
                actions,
                "♥  Favorite" if flags.get("is_favorite") else "♡  Favorite",
                lambda: self._toggle_favorite_from_viewer(int(photo_id), window),
                self.theme,
                self.fonts,
                "secondary",
                padx=10,
                pady=6,
            ).pack(side="right", padx=(6, 0))
            make_button(
                actions,
                "Unarchive" if flags.get("is_archived") else "Archive",
                lambda: self._archive_from_viewer(int(photo_id), window, bool(flags.get("is_archived"))),
                self.theme,
                self.fonts,
                "secondary",
                padx=10,
                pady=6,
            ).pack(side="right", padx=(6, 0))
            if flags.get("deleted_at"):
                make_button(
                    actions,
                    "Restore",
                    lambda: self._restore_from_viewer(int(photo_id), window),
                    self.theme,
                    self.fonts,
                    "primary",
                    padx=10,
                    pady=6,
                ).pack(side="right", padx=(6, 0))
                make_button(
                    actions,
                    "Delete from library",
                    lambda: self._delete_index_from_viewer(int(photo_id), window),
                    self.theme,
                    self.fonts,
                    "danger",
                    padx=10,
                    pady=6,
                ).pack(side="right", padx=(6, 0))
            else:
                make_button(
                    actions,
                    "Move to trash",
                    lambda: self._trash_from_viewer(int(photo_id), window),
                    self.theme,
                    self.fonts,
                    "danger",
                    padx=10,
                    pady=6,
                ).pack(side="right", padx=(6, 0))
            make_button(
                actions,
                "Open file location",
                lambda: self._reveal_file(path),
                self.theme,
                self.fonts,
                "ghost",
                padx=10,
                pady=6,
            ).pack(side="right", padx=(6, 0))

    def _forget_viewer(self, event, window: tk.Toplevel) -> None:
        if event.widget is window and window in self._viewer_windows:
            self._viewer_windows.remove(window)

    def _show_image_viewer(self, window: tk.Toplevel, path: Path) -> None:
        holder = tk.Frame(window, bg="#05080f")
        holder.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        label = tk.Label(holder, bg="#05080f")
        label.pack(fill="both", expand=True)
        try:
            original = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        except Exception as exc:
            tk.Label(
                holder,
                text=f"Unable to display this image.\n{exc}",
                bg="#05080f",
                fg=self.theme.red,
                font=self.fonts.text(10),
                justify="left",
            ).pack(expand=True)
            return
        state = {"image": original, "after": None, "label": label}

        def render(event=None):
            if event is not None:
                width = max(200, event.width - 48)
                height = max(160, event.height - 24)
            else:
                width = max(200, holder.winfo_width() - 48)
                height = max(160, holder.winfo_height() - 24)
            copy = original.copy()
            copy.thumbnail((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(copy)
            label.configure(image=photo)
            label.image = photo

        def resize(event):
            if event.widget is not holder:
                return
            if state["after"]:
                try:
                    window.after_cancel(state["after"])
                except Exception:
                    pass
            state["after"] = window.after(120, render)

        holder.bind("<Configure>", resize)
        window.after(20, render)

    def _open_video(self, path: str, window: tk.Toplevel) -> None:
        holder = tk.Frame(window, bg="#05080f")
        holder.pack(fill="both", expand=True, padx=16, pady=16)
        screen = tk.Label(holder, bg="#05080f")
        screen.pack(fill="both", expand=True)
        capture = cv2.VideoCapture(path)
        if not capture.isOpened():
            tk.Label(
                holder,
                text="This video format could not be opened by the local video decoder.",
                bg="#05080f",
                fg=self.theme.red,
                font=self.fonts.text(10),
            ).pack(expand=True)
            return
        state = {"paused": False, "closed": False}

        def frame():
            if state["closed"] or not window.winfo_exists():
                return
            if not state["paused"]:
                ok, image = capture.read()
                if not ok:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, image = capture.read()
                if ok:
                    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    picture = Image.fromarray(rgb)
                    picture.thumbnail((1100, 680), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(picture)
                    screen.configure(image=photo)
                    screen.image = photo
            window.after(33, frame)

        controls = tk.Frame(holder, bg="#05080f")
        controls.pack(fill="x", pady=(8, 0))
        make_button(
            controls,
            "Pause / Play",
            lambda: state.update(paused=not state["paused"]),
            self.theme,
            self.fonts,
            "secondary",
            padx=10,
            pady=5,
        ).pack(side="left")
        make_button(
            controls,
            "Restart",
            lambda: capture.set(cv2.CAP_PROP_POS_FRAMES, 0),
            self.theme,
            self.fonts,
            "ghost",
            padx=10,
            pady=5,
        ).pack(side="left", padx=(6, 0))

        def close() -> None:
            state["closed"] = True
            capture.release()
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close)
        frame()

    def _toggle_favorite_from_viewer(self, photo_id: int, window: tk.Toplevel) -> None:
        db.toggle_favorite(photo_id)
        window.destroy()
        self._refresh_current_page()

    def _archive_from_viewer(self, photo_id: int, window: tk.Toplevel, archived: bool) -> None:
        db.set_archived(photo_id, not archived)
        window.destroy()
        self._refresh_current_page()

    def _trash_from_viewer(self, photo_id: int, window: tk.Toplevel) -> None:
        if messagebox.askyesno(
            "Move to trash",
            "Move this item to DrishtiX Trash? You can restore it later. "
            "The original file stays on disk.",
        ):
            db.move_to_trash(photo_id)
            window.destroy()
            self._refresh_current_page()

    def _restore_from_viewer(self, photo_id: int, window: tk.Toplevel) -> None:
        db.restore_photo(photo_id)
        window.destroy()
        self._refresh_current_page()

    def _delete_index_from_viewer(self, photo_id: int, window: tk.Toplevel) -> None:
        if messagebox.askyesno(
            "Delete from library",
            "Remove this item from the DrishtiX library permanently? "
            "The original file on disk will NOT be deleted.",
        ):
            db.permanently_delete_photo(photo_id)
            window.destroy()
            self._refresh_current_page()

    def _reveal_file(self, path: Path) -> None:
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except Exception as exc:
            messagebox.showerror("Could not open file location", str(exc))

    # ------------------------------------------------------------------ tasks

    def start_scan(self, folder: str | None = None) -> None:
        if self._task_active:
            messagebox.showinfo("Please wait", "Another library task is already running.")
            return
        if not folder:
            folder = filedialog.askdirectory(title="Choose a folder containing photos or videos")
        if not folder:
            return
        self._begin_task(
            "scan",
            f"Indexing {Path(folder).name or folder}",
            lambda progress, cancel: scan_folder(folder, progress, cancel),
        )

    def _start_reindex(self) -> None:
        if self._task_active:
            messagebox.showinfo("Please wait", "Another library task is already running.")
            return
        if not messagebox.askyesno(
            "Rebuild face index",
            "Rebuild the local face index for every indexed photo?\n\n"
            "Confirmed people are preserved when face boxes still overlap. This can take some time.",
        ):
            return
        self._begin_task(
            "reindex",
            "Rebuilding the local face index",
            lambda progress, cancel: reindex_existing(progress, cancel),
        )

    def _show_scan_summary(self, result: dict[str, Any]) -> None:
        status = result.get("status", "completed")
        cancelled = status == "cancelled"
        window = tk.Toplevel(self)
        window.title("Scan finished" if not cancelled else "Scan cancelled")
        window.configure(bg=self.theme.bg)
        window.geometry("520x430")
        window.transient(self)
        card, inner = self._panel(window, padx=24, pady=22)
        card.pack(fill="both", expand=True, padx=20, pady=20)
        tk.Label(
            inner,
            text="Scan complete" if not cancelled else "Scan cancelled",
            bg=self.theme.panel,
            fg=self.theme.text,
            font=self.fonts.display(18, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            inner,
            text=result.get("folder", ""),
            bg=self.theme.panel,
            fg=self.theme.muted,
            font=self.fonts.text(8),
            wraplength=440,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(4, 14))
        values = [
            ("New items indexed", result.get("seen", 0)),
            ("Faces detected", result.get("faces", 0)),
            ("Duplicates skipped", result.get("skipped", 0)),
            ("Errors", result.get("errors", 0)),
        ]
        for label, value in values:
            row = tk.Frame(inner, bg=self.theme.panel)
            row.pack(fill="x", pady=2)
            tk.Label(
                row, text=label, bg=self.theme.panel, fg=self.theme.muted,
                font=self.fonts.text(9), anchor="w"
            ).pack(side="left")
            tk.Label(
                row, text=f"{value:,}", bg=self.theme.panel, fg=self.theme.text,
                font=self.fonts.text(9, "bold"), anchor="e"
            ).pack(side="right")
        warning = result.get("ai_warning")
        if warning:
            tk.Label(
                inner,
                text=warning,
                bg=self.theme.panel,
                fg=self.theme.amber,
                font=self.fonts.text(8),
                wraplength=440,
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=(12, 0))
        if result.get("errors"):
            tk.Label(
                inner,
                text=f"{result['errors']} file(s) could not be read. Details are in the log file.",
                bg=self.theme.panel,
                fg=self.theme.muted,
                font=self.fonts.text(8),
                wraplength=440,
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=(8, 0))
        buttons = tk.Frame(inner, bg=self.theme.panel)
        buttons.pack(fill="x", pady=(18, 0))
        make_button(
            buttons,
            "View All Photos",
            lambda: (window.destroy(), self.show_all_photos()),
            self.theme,
            self.fonts,
            "primary",
        ).pack(side="left")
        make_button(
            buttons, "Close", window.destroy, self.theme, self.fonts, "secondary"
        ).pack(side="left", padx=(8, 0))

    def _show_reindex_summary(self, result: dict[str, Any]) -> None:
        messagebox.showinfo(
            "Face index rebuilt",
            f"Photos processed: {result.get('seen', 0):,}\n"
            f"Faces indexed: {result.get('faces', 0):,}\n"
            f"Errors: {result.get('errors', 0):,}"
            + (f"\n\n{result.get('ai_warning')}" if result.get("ai_warning") else ""),
        )

    # ------------------------------------------------------------------ close

    def _on_close(self) -> None:
        if self._task_active:
            if not messagebox.askyesno(
                "Task in progress",
                "A library task is still running. Cancel it and close DrishtiX?",
            ):
                return
            self._cancel_requested = True
        try:
            self.thumbnail_service.shutdown()
        except Exception:
            pass
        self.destroy()

    def _report_callback_exception(self, exc, value, tb) -> None:
        logger.error("Unhandled Tk callback exception", exc_info=(exc, value, tb))
        if self._showing_error:
            return
        self._showing_error = True
        try:
            messagebox.showerror(
                "DrishtiX encountered an error",
                f"{value}\n\nDetails were written to:\n{LOG_PATH}",
            )
        finally:
            self._showing_error = False


if __name__ == "__main__":
    DrishtiXApp().mainloop()
