"""Reusable, dependency-light widgets for the DrishtiX interface."""
from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from PIL import Image, ImageTk
from tkinter import ttk

from core.thumbnails import DEFAULT_SIZE, crop_face, ensure_thumbnail
from ui.theme import Fonts, Theme


def truncate(text: str, limit: int = 32) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    if count == 1:
        return singular
    return plural_form or f"{singular}s"


def display_date(value: str | None) -> str:
    if not value:
        return "Unknown date"
    try:
        stamp = str(value).replace("Z", "")
        parsed = datetime.fromisoformat(stamp)
        return parsed.strftime("%b %Y")
    except ValueError:
        return str(value)[:7]


def human_duration(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def bind_tree(widget: tk.Misc, sequence: str, callback: Callable) -> None:
    """Bind an event to a widget tree, leaving interactive controls alone."""
    if widget.winfo_class() not in (
        "Button",
        "TButton",
        "TCombobox",
        "Entry",
        "TEntry",
        "Checkbutton",
        "TCheckbutton",
        "Scale",
        "TScale",
    ):
        widget.bind(sequence, callback)
    for child in widget.winfo_children():
        bind_tree(child, sequence, callback)


def make_button(
    parent: tk.Misc,
    text: str,
    command: Callable | None,
    theme: Theme,
    fonts: Fonts,
    kind: str = "secondary",
    padx: int = 14,
    pady: int = 8,
    width: int | None = None,
) -> tk.Button:
    """Create a flat, hover-aware button that matches the theme."""
    if kind == "primary":
        background, foreground = theme.accent, theme.on_accent
        hover, pressed = theme.cyan, theme.accent_soft
        highlight = theme.accent
        font = fonts.text(9, "bold")
    elif kind == "danger":
        background, foreground = theme.panel2, theme.red
        hover, pressed = theme.elevated, theme.panel2
        highlight = theme.border
        font = fonts.text(9, "bold")
    elif kind == "ghost":
        background, foreground = theme.panel, theme.muted
        hover, pressed = theme.hover, theme.panel2
        highlight = theme.border_soft
        font = fonts.text(9)
    elif kind == "link":
        background, foreground = theme.bg, theme.cyan
        hover, pressed = theme.bg, theme.bg
        highlight = theme.bg
        font = fonts.text(9, "bold")
    else:
        background, foreground = theme.panel2, theme.text
        hover, pressed = theme.elevated, theme.panel2
        highlight = theme.border
        font = fonts.text(9, "bold")

    button = tk.Button(
        parent,
        text=text,
        command=command,
        bg=background,
        fg=foreground,
        activebackground=pressed,
        activeforeground=foreground,
        disabledforeground=theme.dim,
        relief="flat",
        bd=0,
        highlightthickness=0 if kind == "link" else 1,
        highlightbackground=highlight,
        highlightcolor=highlight,
        font=font,
        padx=padx,
        pady=pady,
        cursor="hand2",
        takefocus=1,
    )
    if width is not None:
        button.configure(width=width)

    if command is not None:
        button.bind("<Enter>", lambda _event: button.configure(bg=hover))
        button.bind("<Leave>", lambda _event: button.configure(bg=background))
    return button


class SearchBox(tk.Frame):
    """Search field with a real placeholder and a visible focus ring."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        fonts: Fonts,
        placeholder: str = "Search photos, videos and categories…",
        on_change: Callable[[str], None] | None = None,
        on_submit: Callable[[str], None] | None = None,
        width: int = 340,
    ) -> None:
        super().__init__(
            parent,
            bg=theme.panel,
            highlightthickness=1,
            highlightbackground=theme.border,
            highlightcolor=theme.accent,
        )
        self.theme = theme
        self.on_change = on_change
        self.on_submit = on_submit
        self.placeholder = placeholder
        self._showing_placeholder = True

        icon = tk.Label(
            self,
            text="\uE721",
            bg=theme.panel,
            fg=theme.accent,
            font=fonts.icon(11),
            padx=10,
        )
        icon.pack(side="left")
        self.entry = tk.Entry(
            self,
            bg=theme.panel,
            fg=theme.dim,
            insertbackground=theme.text,
            relief="flat",
            bd=0,
            font=fonts.text(10),
            width=max(12, width // 9),
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 10))
        self._show_placeholder()
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.entry.bind("<KeyRelease>", self._key_release)
        self.entry.bind("<Return>", self._submit)

    def _show_placeholder(self) -> None:
        self._showing_placeholder = True
        self.entry.delete(0, "end")
        self.entry.insert(0, self.placeholder)
        self.entry.configure(fg=self.theme.dim)

    def _focus_in(self, _event=None) -> None:
        self.configure(highlightbackground=self.theme.accent)
        if self._showing_placeholder:
            self.entry.delete(0, "end")
            self.entry.configure(fg=self.theme.text)
            self._showing_placeholder = False

    def _focus_out(self, _event=None) -> None:
        self.configure(highlightbackground=self.theme.border)
        if not self.entry.get().strip():
            self._show_placeholder()

    def _key_release(self, _event=None) -> None:
        self._notify()

    def _submit(self, _event=None) -> None:
        if self.on_submit:
            self.on_submit(self.get())

    def _notify(self) -> None:
        if self.on_change:
            self.on_change(self.get())

    def get(self) -> str:
        if self._showing_placeholder:
            return ""
        return self.entry.get().strip()

    def set(self, value: str) -> None:
        if value:
            self._showing_placeholder = False
            self.entry.delete(0, "end")
            self.entry.insert(0, value)
            self.entry.configure(fg=self.theme.text)
        else:
            self._show_placeholder()

    def focus(self) -> None:
        self.entry.focus_set()
        self._focus_in()


class EmptyState(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        fonts: Fonts,
        glyph: str,
        title: str,
        body: str,
        action_text: str | None = None,
        action: Callable | None = None,
        secondary_text: str | None = None,
        secondary_action: Callable | None = None,
        wraplength: int = 560,
    ) -> None:
        super().__init__(parent, bg=theme.bg)
        badge = tk.Canvas(self, width=68, height=68, bg=theme.bg, highlightthickness=0)
        badge.create_oval(2, 2, 66, 66, outline=theme.border, width=1)
        badge.create_oval(12, 12, 56, 56, outline=theme.accent, width=1)
        badge.create_text(34, 33, text=glyph, fill=theme.cyan, font=fonts.icon(22))
        badge.pack(anchor="w", pady=(0, 16))
        tk.Label(
            self,
            text=title,
            bg=theme.bg,
            fg=theme.text,
            font=fonts.display(17, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            self,
            text=body,
            bg=theme.bg,
            fg=theme.muted,
            font=fonts.text(10),
            wraplength=wraplength,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(8, 16))
        if action_text and action:
            row = tk.Frame(self, bg=theme.bg)
            row.pack(anchor="w")
            make_button(row, action_text, action, theme, fonts, "primary").pack(side="left")
            if secondary_text and secondary_action:
                make_button(
                    row, secondary_text, secondary_action, theme, fonts, "secondary"
                ).pack(side="left", padx=(8, 0))


class SectionLabel(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        fonts: Fonts,
        text: str,
        action_text: str | None = None,
        action: Callable | None = None,
    ) -> None:
        super().__init__(parent, bg=theme.bg)
        tk.Label(
            self,
            text=text.upper(),
            bg=theme.bg,
            fg=theme.muted,
            font=fonts.text(8, "bold"),
        ).pack(side="left")
        if action_text and action:
            make_button(
                self, action_text, action, theme, fonts, "link", padx=2, pady=1
            ).pack(side="right")


class StatCard(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        fonts: Fonts,
        label: str,
        value: str | int,
        note: str,
        accent: str,
        glyph: str = "◈",
    ) -> None:
        super().__init__(
            parent,
            bg=theme.panel,
            highlightthickness=1,
            highlightbackground=theme.border,
        )
        inner = tk.Frame(self, bg=theme.panel, padx=18, pady=16)
        inner.pack(fill="both", expand=True)
        top = tk.Frame(inner, bg=theme.panel)
        top.pack(fill="x")
        tk.Label(
            top, text=glyph, bg=theme.panel, fg=accent, font=fonts.icon(12)
        ).pack(side="left")
        tk.Label(
            top,
            text=label.upper(),
            bg=theme.panel,
            fg=theme.muted,
            font=fonts.text(8, "bold"),
        ).pack(side="left", padx=(8, 0))
        tk.Label(
            inner, text=str(value), bg=theme.panel, fg=theme.text, font=fonts.display(27, "bold")
        ).pack(anchor="w", pady=(10, 0))
        tk.Label(
            inner, text=note, bg=theme.panel, fg=theme.dim, font=fonts.text(8)
        ).pack(anchor="w", pady=(1, 0))
        rule = tk.Frame(inner, bg=accent, height=2, width=28)
        rule.pack(anchor="w", pady=(12, 0))


class ThumbnailService:
    """Background thumbnail generation; Tk image objects stay on the main thread."""

    def __init__(self, workers: int = 3) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pl-thumb")
        self._closed = False

    def submit(self, photo: dict[str, Any], size: tuple[int, int] = DEFAULT_SIZE) -> Future:
        return self._executor.submit(ensure_thumbnail, dict(photo), size)

    def submit_face(self, path: str, box: tuple[int, int, int, int], size: int = 160) -> Future:
        return self._executor.submit(crop_face, path, box, size)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


class AsyncImage(tk.Frame):
    """A fixed-pixel-size frame that receives its image from a background future.

    The future may return either a filesystem path or an already-open PIL image
    (face crops are decoded in the worker and handed over this way).
    """

    def __init__(
        self,
        parent: tk.Misc,
        app,
        future: Future,
        size: tuple[int, int],
        theme: Theme,
        fonts: Fonts,
        glyph: str = "\uE91B",
        bg: str | None = None,
    ) -> None:
        background = bg or theme.panel2
        super().__init__(
            parent,
            width=size[0],
            height=size[1],
            bg=background,
            highlightthickness=0,
        )
        self.pack_propagate(False)
        self._app = app
        self._future = future
        self._size = size
        self._background = background
        self._theme = theme
        self._alive = True
        self.label = tk.Label(
            self,
            text=glyph,
            bg=background,
            fg=theme.dim,
            font=fonts.icon(min(20, max(10, size[0] // 8))),
        )
        self.label.pack(fill="both", expand=True)
        self.bind("<Destroy>", self._destroyed)
        self._poll()

    def _destroyed(self, event) -> None:
        if event.widget is self:
            self._alive = False

    def _poll(self) -> None:
        if not self._alive:
            return
        if not self._future.done():
            self._app.after(45, self._poll)
            return
        try:
            payload = self._future.result()
            if isinstance(payload, Image.Image):
                image = payload.convert("RGB")
                if image.size != self._size:
                    image = image.resize(self._size, Image.Resampling.LANCZOS)
            elif payload:
                with Image.open(payload) as opened:
                    image = opened.convert("RGB")
                    image = image.resize(self._size, Image.Resampling.LANCZOS)
            else:
                image = None
            if image is not None:
                photo = ImageTk.PhotoImage(image)
                self.label.configure(image=photo, text="")
                self.label.image = photo
            else:
                self.label.configure(
                    text="Preview\nunavailable",
                    font=self._app.fonts.text(8),
                    fg=self._theme.dim,
                )
        except Exception:
            self.label.configure(
                text="Preview\nunavailable",
                font=self._app.fonts.text(8),
                fg=self._theme.dim,
            )


class ScrollFrame(tk.Frame):
    """A reusable scrollable region for modal dialogs."""

    def __init__(self, parent: tk.Misc, theme: Theme, bg: str | None = None) -> None:
        background = bg or theme.bg
        super().__init__(parent, bg=background)
        self.theme = theme
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=background)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self._window, width=event.width),
        )

    def bind_wheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._wheel, add="+")
        widget.bind("<Button-4>", self._wheel_linux, add="+")
        widget.bind("<Button-5>", self._wheel_linux, add="+")

    def _wheel(self, event) -> str:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _wheel_linux(self, event) -> str:
        self.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
        return "break"



class PhotoGrid(tk.Frame):
    """Responsive, paged photo grid with lazy thumbnail loading.

    The grid uses the page's single outer scroll surface. It never creates a
    nested scrollbar, which keeps wheel scrolling predictable and avoids the
    blank-page failure that occurs when a nested canvas receives no height.
    """

    TILE_W = 248
    TILE_H = 176
    GAP = 12
    PAGE = 120

    def __init__(
        self,
        parent: tk.Misc,
        app,
        photos: Iterable[dict[str, Any]],
        *,
        group_by_month: bool = False,
        page_size: int = PAGE,
        trash_mode: bool = False,
        selectable: bool = False,
        on_open: Callable[[dict[str, Any]], None] | None = None,
        on_restore: Callable[[int], None] | None = None,
        on_delete: Callable[[int], None] | None = None,
        on_selection_change: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=app.theme.bg)
        self.app = app
        self.theme: Theme = app.theme
        self.fonts: Fonts = app.fonts
        self.photos = list(photos)
        self.group_by_month = group_by_month
        self.page_size = max(1, page_size)
        self.trash_mode = trash_mode
        self.selectable = selectable
        self.on_open = on_open
        self.on_restore = on_restore
        self.on_delete = on_delete
        self.on_selection_change = on_selection_change
        self._groups: list[dict[str, Any]] = []
        self._tiles: list[dict[str, Any]] = []
        self._rendered = 0
        self._pending: list[tuple[Future, dict[str, Any]]] = []
        self._columns = 0
        self._alive = True
        self._layout_dirty = True
        self._load_more: tk.Button | None = None
        self.selected: set[int] = set()
        self._poll_id = None

        self._render_next()
        self.bind("<Configure>", self._on_configure)
        self.bind("<Destroy>", self._destroyed)
        self._poll_id = self.after(45, self._poll)

    @property
    def tiles(self) -> list[dict[str, Any]]:
        return list(self._tiles)

    def _destroyed(self, event) -> None:
        if event.widget is not self:
            return
        self._alive = False
        if self._poll_id:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        for future, _tile in self._pending:
            future.cancel()
        self._pending.clear()

    def _month_key(self, photo: dict[str, Any]) -> str:
        stamp = photo.get("date_taken") or photo.get("scanned_at") or ""
        return str(stamp)[:7] if len(str(stamp)) >= 7 else "Unknown date"

    def _month_label(self, key: str) -> str:
        try:
            return datetime.strptime(key, "%Y-%m").strftime("%B %Y")
        except ValueError:
            return "Unknown date"

    def _create_group(self, key: str | None) -> dict[str, Any]:
        wrapper = tk.Frame(self, bg=self.theme.bg)
        wrapper.pack(fill="x", pady=(0, 8))
        if key and self.group_by_month:
            header = tk.Frame(wrapper, bg=self.theme.bg)
            header.pack(fill="x", pady=(10, 7))
            tk.Label(
                header,
                text=self._month_label(key),
                bg=self.theme.bg,
                fg=self.theme.text,
                font=self.fonts.display(13, "bold"),
            ).pack(side="left")
            tk.Frame(header, bg=self.theme.border_soft, height=1).pack(
                side="left", fill="x", expand=True, padx=(14, 0), pady=(8, 0)
            )
        holder = tk.Frame(wrapper, bg=self.theme.bg)
        holder.pack(fill="x")
        group = {"key": key, "wrapper": wrapper, "holder": holder, "tiles": []}
        self._groups.append(group)
        return group

    def _tile_height(self) -> int:
        extra = 64
        if self.trash_mode:
            extra += 32
        return self.TILE_H + extra

    def _create_tile(self, group: dict[str, Any], photo: dict[str, Any]) -> None:
        tile = tk.Frame(
            group["holder"],
            bg=self.theme.panel,
            width=self.TILE_W,
            height=self._tile_height(),
            highlightthickness=1,
            highlightbackground=self.theme.border,
            cursor="hand2",
        )
        tile.pack_propagate(False)

        media = tk.Frame(tile, bg=self.theme.panel2, width=self.TILE_W, height=self.TILE_H)
        media.pack(fill="x")
        media.pack_propagate(False)
        image_label = tk.Label(
            media,
            bg=self.theme.panel2,
            fg=self.theme.dim,
            text="\uE91B",
            font=self.fonts.icon(22),
        )
        image_label.pack(fill="both", expand=True)

        is_video = photo.get("media_type") == "video"
        if is_video:
            badge = tk.Label(
                media,
                text="▶  VIDEO",
                bg="#0a1a2a",
                fg=self.theme.cyan,
                font=self.fonts.text(7, "bold"),
                padx=7,
                pady=3,
            )
            badge.place(x=8, y=8)
            duration = human_duration(photo.get("duration"))
            if duration:
                tk.Label(
                    media,
                    text=duration,
                    bg="#0a1a2a",
                    fg=self.theme.text,
                    font=self.fonts.mono(7),
                    padx=6,
                    pady=2,
                ).place(relx=1.0, rely=1.0, x=-8, y=-8, anchor="se")
        if photo.get("is_favorite"):
            tk.Label(
                media,
                text="♥",
                bg="#241a36",
                fg="#ff9bb4",
                font=self.fonts.text(10, "bold"),
                padx=5,
                pady=1,
            ).place(relx=1.0, y=8, x=-8, anchor="ne")

        select_badge = None
        if self.selectable:
            select_badge = tk.Label(
                media,
                text="○" if photo["id"] not in self.selected else "✓",
                bg=self.theme.elevated,
                fg=self.theme.muted,
                font=self.fonts.text(9, "bold"),
                padx=5,
                pady=1,
            )
            select_badge.place(relx=1.0, rely=1.0, x=-8, y=-8, anchor="se")

        info = tk.Frame(tile, bg=self.theme.panel, padx=11, pady=7)
        info.pack(fill="both", expand=True)
        filename = tk.Label(
            info,
            text=truncate(Path(str(photo.get("path", ""))).name, 31),
            bg=self.theme.panel,
            fg=self.theme.text,
            font=self.fonts.text(8, "bold"),
            anchor="w",
        )
        filename.pack(fill="x")
        meta_bits = [str(photo.get("category") or "Photo")]
        stamp = photo.get("date_taken") or photo.get("scanned_at")
        if stamp:
            meta_bits.append(display_date(stamp))
        meta = tk.Label(
            info,
            text="  ·  ".join(meta_bits),
            bg=self.theme.panel,
            fg=self.theme.muted,
            font=self.fonts.text(7),
            anchor="w",
        )
        meta.pack(fill="x", pady=(3, 0))

        if self.trash_mode:
            actions = tk.Frame(info, bg=self.theme.panel)
            actions.pack(fill="x", pady=(6, 0))
            make_button(
                actions,
                "Restore",
                lambda pid=photo["id"]: self.on_restore and self.on_restore(pid),
                self.theme,
                self.fonts,
                "secondary",
                padx=8,
                pady=3,
            ).pack(side="left")
            make_button(
                actions,
                "Delete",
                lambda pid=photo["id"]: self.on_delete and self.on_delete(pid),
                self.theme,
                self.fonts,
                "danger",
                padx=8,
                pady=3,
            ).pack(side="right")

        tile_data = {
            "photo": photo,
            "frame": tile,
            "image": image_label,
            "select_badge": select_badge,
            "group": group,
        }
        group["tiles"].append(tile_data)
        self._tiles.append(tile_data)
        self._bind_tile(tile_data)
        future = self.app.thumbnail_service.submit(photo, (self.TILE_W, self.TILE_H))
        self._pending.append((future, tile_data))

    def _bind_tile(self, tile_data: dict[str, Any]) -> None:
        tile = tile_data["frame"]

        def enter(_event=None):
            if tile_data["photo"]["id"] in self.selected and self.selectable:
                return
            tile.configure(highlightbackground=self.theme.accent)

        def leave(_event=None):
            selected = self.selectable and tile_data["photo"]["id"] in self.selected
            tile.configure(
                highlightbackground=self.theme.accent if selected else self.theme.border
            )

        def click(_event=None):
            if self.selectable:
                self._toggle(tile_data)
            elif self.on_open:
                self.on_open(tile_data["photo"])

        bind_tree(tile, "<Enter>", enter)
        bind_tree(tile, "<Leave>", leave)
        bind_tree(tile, "<Button-1>", click)

    def _toggle(self, tile_data: dict[str, Any]) -> None:
        photo_id = int(tile_data["photo"]["id"])
        if photo_id in self.selected:
            self.selected.discard(photo_id)
        else:
            self.selected.add(photo_id)
        selected = photo_id in self.selected
        tile_data["frame"].configure(
            highlightbackground=self.theme.accent if selected else self.theme.border
        )
        badge = tile_data["select_badge"]
        if badge is not None:
            badge.configure(
                text="✓" if selected else "○",
                bg=self.theme.accent if selected else self.theme.elevated,
                fg=self.theme.on_accent if selected else self.theme.muted,
            )
        if self.on_selection_change:
            self.on_selection_change(len(self.selected))

    def _render_next(self) -> None:
        if not self._alive:
            return
        if self._load_more is not None:
            self._load_more.destroy()
            self._load_more = None
        chunk = self.photos[self._rendered : self._rendered + self.page_size]
        group = self._groups[-1] if self._groups else None
        for photo in chunk:
            key = self._month_key(photo) if self.group_by_month else None
            if group is None or (self.group_by_month and group["key"] != key):
                group = self._create_group(key)
            self._create_tile(group, photo)
        self._rendered += len(chunk)
        remaining = len(self.photos) - self._rendered
        if remaining > 0:
            self._load_more = make_button(
                self,
                f"Load more  ·  {remaining:,} remaining",
                self._render_next,
                self.theme,
                self.fonts,
                "secondary",
            )
            self._load_more.pack(anchor="w", pady=(14, 4))
        self._layout_dirty = True
        self.after_idle(self._relayout)

    def _on_configure(self, event) -> None:
        if event.widget is self:
            self.after_idle(self._relayout)

    def _relayout(self) -> None:
        if not self._alive:
            return
        width = self.winfo_width()
        if width <= 1:
            width = max(640, self.app.winfo_width() - 360)
        column = max(1, (width + self.GAP) // (self.TILE_W + self.GAP))
        if column == self._columns and not self._layout_dirty:
            return
        self._layout_dirty = False
        self._columns = column
        pad = self.GAP // 2
        for group in self._groups:
            holder = group["holder"]
            for index in range(max(column, 20)):
                holder.grid_columnconfigure(index, weight=1 if index < column else 0)
            for index, tile_data in enumerate(group["tiles"]):
                tile_data["frame"].grid(
                    row=index // column,
                    column=index % column,
                    padx=pad,
                    pady=pad,
                )

    def _poll(self) -> None:
        if not self._alive:
            return
        remaining: list[tuple[Future, dict[str, Any]]] = []
        completed = 0
        for future, tile_data in self._pending:
            if not future.done():
                remaining.append((future, tile_data))
                continue
            completed += 1
            try:
                path = future.result()
            except Exception:
                path = None
            if path and self._alive:
                try:
                    with Image.open(path) as opened:
                        image = opened.convert("RGB")
                        photo = ImageTk.PhotoImage(image)
                    label = tile_data["image"]
                    label.configure(image=photo, text="")
                    tile_data["frame"].image = photo
                except Exception:
                    tile_data["image"].configure(
                        text="Preview\nunavailable",
                        font=self.fonts.text(7),
                        fg=self.theme.dim,
                    )
            elif self._alive:
                tile_data["image"].configure(
                    text="Preview\nunavailable",
                    font=self.fonts.text(7),
                    fg=self.theme.dim,
                )
        self._pending = remaining
        if self._pending:
            self._poll_id = self.after(35 if completed else 60, self._poll)
        else:
            self._poll_id = self.after(200, self._poll)
