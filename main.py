"""DrishtiX entry point.

Startup order matters for a windowed Windows build:

1. enable per-monitor DPI awareness before Tk creates a window,
2. configure the rotating log file so no traceback is ever lost,
3. show the approved DrishtiX splash,
4. launch the workspace and surface any startup failure in a real dialog.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageTk

from app_paths import LOG_PATH, asset_path, ensure_user_data
from core.logging_setup import configure_logging

logger = logging.getLogger("drishtix.main")


def enable_dpi_awareness() -> None:
    """Ask Windows for crisp per-monitor rendering before Tk is created."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _load_splash_image(width: int) -> ImageTk.PhotoImage | None:
    try:
        with Image.open(asset_path("drishtix_splash.png")) as opened:
            image = opened.convert("RGB")
        ratio = width / image.width
        image = image.resize(
            (width, max(1, round(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )
        return ImageTk.PhotoImage(image)
    except Exception:
        logger.warning("The approved splash image could not be loaded", exc_info=True)
        return None


def show_splash(duration_ms: int = 900) -> None:
    """Show the approved DrishtiX splash, centred and scaled to fit."""
    splash = tk.Tk()
    splash.overrideredirect(True)
    splash.configure(bg="#050914")
    splash.attributes("-topmost", True)

    screen_w = splash.winfo_screenwidth()
    screen_h = splash.winfo_screenheight()
    width = min(960, max(560, int(screen_w * 0.72)))
    photo = _load_splash_image(width)

    if photo is not None:
        height = photo.height()
        label = tk.Label(splash, image=photo, bg="#050914", bd=0)
        label.image = photo
        label.pack()
    else:
        width, height = 620, 340
        card = tk.Frame(splash, bg="#0b1424", padx=40, pady=40)
        card.pack(fill="both", expand=True)
        tk.Label(
            card,
            text="DrishtiX",
            bg="#0b1424",
            fg="#f2f6ff",
            font=("Segoe UI", 28, "bold"),
        ).pack(expand=True)
        tk.Label(
            card,
            text="Powered by TantraYantra",
            bg="#0b1424",
            fg="#98a8c2",
            font=("Segoe UI", 10),
        ).pack(pady=(4, 0))

    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2 - 30)
    splash.geometry(f"{width}x{height}+{x}+{y}")
    splash.after(duration_ms, splash.destroy)
    splash.mainloop()


def _install_excepthook() -> None:
    def handle(exc_type, exc_value, traceback_object) -> None:
        logger.critical(
            "Uncaught application error",
            exc_info=(exc_type, exc_value, traceback_object),
        )
        try:
            messagebox.showerror(
                "DrishtiX could not start",
                f"{exc_value}\n\nDetails were written to:\n{LOG_PATH}",
            )
        except Exception:
            pass

    sys.excepthook = handle


def main() -> None:
    enable_dpi_awareness()
    configure_logging()
    _install_excepthook()
    try:
        ensure_user_data()
        logger.info("DrishtiX starting")
        show_splash()
        from ui.app import DrishtiXApp

        app = DrishtiXApp()
        app.mainloop()
    except Exception:
        logger.exception("DrishtiX failed to start")
        try:
            messagebox.showerror(
                "DrishtiX could not start",
                "The application could not open its window.\n\n"
                f"Details were written to:\n{LOG_PATH}",
            )
        except Exception:
            pass
        raise
    finally:
        logging.shutdown()


if __name__ == "__main__":
    main()
