"""Visual language for DrishtiX.

The palette is deliberately restrained: near-black navy surfaces, thin cool
borders, and cyan/violet accents used only for orientation and action.
"""
from __future__ import annotations

from dataclasses import dataclass

from tkinter import font as tkfont
from tkinter import ttk


@dataclass(frozen=True)
class Theme:
    name: str
    dark: bool
    bg: str
    sidebar: str
    panel: str
    panel2: str
    elevated: str
    border: str
    border_soft: str
    text: str
    muted: str
    dim: str
    accent: str
    accent_soft: str
    cyan: str
    green: str
    red: str
    amber: str
    hover: str
    active: str
    selection: str
    on_accent: str


DARK = Theme(
    name="Dark",
    dark=True,
    bg="#080c15",
    sidebar="#070b13",
    panel="#0e1626",
    panel2="#121c30",
    elevated="#16223a",
    border="#1d2a44",
    border_soft="#152036",
    text="#f2f6ff",
    muted="#98a8c2",
    dim="#6b7c99",
    accent="#9b87ff",
    accent_soft="#bcadff",
    cyan="#4fd8ff",
    green="#45d6a0",
    red="#ff7a8c",
    amber="#f4c46b",
    hover="#121d31",
    active="#182642",
    selection="#213052",
    on_accent="#080c15",
)

LIGHT = Theme(
    name="Light",
    dark=False,
    bg="#f1f5fb",
    sidebar="#0b1220",
    panel="#ffffff",
    panel2="#eef3fa",
    elevated="#e5edf7",
    border="#d8e2ef",
    border_soft="#e7eef7",
    text="#17243a",
    muted="#5f708b",
    dim="#8b99ad",
    accent="#7357d8",
    accent_soft="#5e41c4",
    cyan="#1f7fd1",
    green="#15835f",
    red="#c8404d",
    amber="#9a6400",
    hover="#e9f0f9",
    active="#dfe8f5",
    selection="#d8e4f4",
    on_accent="#ffffff",
)

OCEAN = Theme(
    name="Ocean",
    dark=True,
    bg="#05131c",
    sidebar="#041019",
    panel="#0a2230",
    panel2="#0e2c3e",
    elevated="#12364b",
    border="#1a4358",
    border_soft="#123244",
    text="#eafaff",
    muted="#93b7c8",
    dim="#648a9d",
    accent="#9b87ff",
    accent_soft="#bcadff",
    cyan="#55dfff",
    green="#48d6aa",
    red="#ff8c9c",
    amber="#f4c46b",
    hover="#0c2737",
    active="#12384e",
    selection="#16445d",
    on_accent="#041019",
)

PALETTES = {"Dark": DARK, "Light": LIGHT, "Ocean": OCEAN}


def get_theme(name: str | None) -> Theme:
    return PALETTES.get(str(name or "Dark"), DARK)


class Fonts:
    """Resolve Windows 11 typography with graceful fallbacks."""

    def __init__(self, root) -> None:
        available = set(tkfont.families(root))
        self.display_family = (
            "Segoe UI Variable Display" if "Segoe UI Variable Display" in available else "Segoe UI"
        )
        self.text_family = (
            "Segoe UI Variable Text" if "Segoe UI Variable Text" in available else "Segoe UI"
        )
        if "Cascadia Mono" in available:
            self.mono_family = "Cascadia Mono"
        elif "Consolas" in available:
            self.mono_family = "Consolas"
        else:
            self.mono_family = "Courier New"
        if "Segoe Fluent Icons" in available:
            self.icon_family = "Segoe Fluent Icons"
        elif "Segoe MDL2 Assets" in available:
            self.icon_family = "Segoe MDL2 Assets"
        else:
            self.icon_family = "Segoe UI Symbol"

    def display(self, size: int, weight: str = "normal"):
        return (self.display_family, size, weight)

    def text(self, size: int, weight: str = "normal"):
        return (self.text_family, size, weight)

    def mono(self, size: int, weight: str = "normal"):
        return (self.mono_family, size, weight)

    def icon(self, size: int):
        """Segoe Fluent Icons / MDL2 glyph font used for navigation and controls."""
        return (self.icon_family, size)


def apply_ttk_styles(root, theme: Theme, fonts: Fonts) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background=theme.bg)
    style.configure("TLabel", background=theme.bg, foreground=theme.text, font=fonts.text(10))
    style.configure("Panel.TFrame", background=theme.panel)

    style.configure(
        "TCombobox",
        fieldbackground=theme.panel2,
        background=theme.panel2,
        foreground=theme.text,
        arrowcolor=theme.cyan,
        bordercolor=theme.border,
        lightcolor=theme.border,
        darkcolor=theme.border,
        borderwidth=1,
        relief="flat",
        padding=(10, 8),
        selectbackground=theme.selection,
        selectforeground=theme.text,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", theme.panel2), ("disabled", theme.panel2)],
        foreground=[("readonly", theme.text), ("disabled", theme.dim)],
        bordercolor=[("focus", theme.accent), ("hover", theme.border)],
        arrowcolor=[("disabled", theme.dim), ("active", theme.accent)],
    )

    style.configure(
        "Vertical.TScrollbar",
        background=theme.border,
        troughcolor=theme.bg,
        bordercolor=theme.bg,
        arrowcolor=theme.muted,
        width=12,
        relief="flat",
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", theme.accent), ("pressed", theme.accent)],
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=theme.border,
        troughcolor=theme.bg,
        bordercolor=theme.bg,
        arrowcolor=theme.muted,
        relief="flat",
    )

    style.configure(
        "Treeview",
        background=theme.panel,
        fieldbackground=theme.panel,
        foreground=theme.text,
        rowheight=42,
        borderwidth=0,
        font=fonts.text(10),
    )
    style.configure(
        "Treeview.Heading",
        background=theme.panel2,
        foreground=theme.cyan,
        font=fonts.text(9, "bold"),
        relief="flat",
        padding=(10, 10),
        borderwidth=0,
    )
    style.map(
        "Treeview",
        background=[("selected", theme.selection)],
        foreground=[("selected", theme.text)],
    )
    style.map("Treeview.Heading", background=[("active", theme.elevated)])

    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=theme.panel2,
        background=theme.accent,
        bordercolor=theme.panel2,
        lightcolor=theme.accent,
        darkcolor=theme.accent,
        thickness=4,
    )
