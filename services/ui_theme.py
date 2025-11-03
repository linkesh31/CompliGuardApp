from __future__ import annotations
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

# ──────────────────────────────────────────────
# Appearance / Theme  (LIGHT / BEIGE like Add Admin)
# ──────────────────────────────────────────────
APPEARANCE_DEFAULT = "light"   # force light for all pages using this theme

PALETTE = {
    # page / surfaces
    "bg":        "#F5EDE2",   # main page background (light beige)
    "card":      "#F0E4D5",   # card/surface
    "card2":     "#EFE0CE",
    "text":      "#1F1F1F",   # almost black
    "muted":     "#6B5A48",
    "border":    "#B59E85",

    # brand / states
    "primary":   "#2B63D9",   # Preview button blue
    "primary_h": "#1F53C1",
    "ok":        "#2B7A0B",
    "warning":   "#B45309",
    "danger":    "#B91C1C",

    # chips / accents
    "chip":      "#E8D9C6",
}

FONTS = {
    "h1":   ("Segoe UI Semibold", 22),
    "h2":   ("Segoe UI Semibold", 20),
    "h3":   ("Segoe UI Semibold", 16),
    "body": ("Segoe UI", 10),
    "small":("Segoe UI", 10),
    "mono": ("Consolas", 10),
    "label":("Segoe UI", 10, "bold"),
}

RADIUS = 12  # corner radius for CTk cards


def apply_theme(root: tk.Misc, appearance: str = APPEARANCE_DEFAULT, accent_hex: str = PALETTE["primary"]):
    """
    Global light beige theme.
    We keep ttk styling consistent for all pages.
    """
    # Force CustomTkinter light mode
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    # base bg for plain tk containers
    try:
        root.configure(bg=PALETTE["bg"])
    except Exception:
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    base_bg   = PALETTE["bg"]
    card_bg   = PALETTE["card"]
    text_fg   = PALETTE["text"]
    muted_fg  = PALETTE["muted"]
    border    = PALETTE["border"]
    primary   = accent_hex
    primary_h = PALETTE["primary_h"]

    # default text color = black-ish
    style.configure(
        ".",
        background=base_bg,
        foreground=text_fg,
        font=FONTS["body"],
    )
    style.configure("Muted.TLabel", foreground=muted_fg)
    style.configure("Strong.TLabel", font=("Segoe UI", 10, "bold"))

    # Primary button (blue) -> used for Preview
    style.configure(
        "Primary.TButton",
        font=FONTS["body"],
        padding=(14, 8),
        background=primary,
        foreground="#ffffff",
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "Primary.TButton",
        background=[("active", primary_h), ("pressed", primary_h)],
        foreground=[("disabled", "#ffffff")],
    )

    # Neutral buttons (CSV / PDF etc.)
    style.configure(
        "TButton",
        font=FONTS["body"],
        padding=(12, 7),
        background=card_bg,
        foreground=text_fg,
        bordercolor=border,
        relief="flat",
        borderwidth=1,
    )
    style.map(
        "TButton",
        background=[("active", _mix(card_bg, "#ffffff", 0.10))]
    )

    # Chip buttons (Today / Last 7 days / This month)
    style.configure(
        "Pill.TButton",
        padding=(14, 6),
        background="#FFFFFF",
        foreground="#1F1F1F",
        borderwidth=1,
        bordercolor=border,
        relief="flat",
    )
    style.map(
        "Pill.TButton",
        background=[("active", "#F7F4EE"), ("pressed", "#EFE8DC")]
    )

    # Entry / Combobox base (white field, brown border)
    style.configure(
        "TEntry",
        fieldbackground="#FFFFFF",
        background="#FFFFFF",
        foreground=text_fg,
        bordercolor=border,
        lightcolor=border,
        darkcolor=border,
        borderwidth=1,
        relief="flat",
        padding=8,
    )
    style.configure(
        "TCombobox",
        fieldbackground="#FFFFFF",
        background="#FFFFFF",
        foreground=text_fg,
        bordercolor=border,
        relief="flat",
        padding=6,
    )

    # Scrollbar look
    style.layout(
        "Vertical.TScrollbar",
        [("Vertical.Scrollbar.trough",
          {"children": [("Vertical.Scrollbar.thumb",
                         {"expand": True, "sticky": "nswe"})],
           "sticky": "ns"})]
    )
    style.configure("Vertical.TScrollbar", background=card_bg)
    style.configure("Vertical.TScrollbar.thumb", background=_mix("#c8c8c8", "#ffffff", 0.20))

    # Default Treeview style (other pages)
    style.configure(
        "Treeview",
        background="#FFFFFF",
        fieldbackground="#FFFFFF",
        bordercolor=border,
        borderwidth=1,
        rowheight=26,
        foreground=text_fg,
    )
    style.configure(
        "Treeview.Heading",
        font=("Segoe UI Semibold", 10),
        background=_mix(card_bg, "#FFFFFF", 0.25),
        foreground=text_fg,
        relief="flat"
    )
    style.map("Treeview", background=[("selected", "#F1E3D3")])
    style.map("Treeview.Heading", background=[])


def _mix(a_hex: str, b_hex: str, t: float) -> str:
    """Blend two hex colors a→b by t (0..1)."""
    ax = _hex_to_rgb(a_hex)
    bx = _hex_to_rgb(b_hex)
    c = tuple(int(ax[i] + (bx[i] - ax[i]) * t) for i in range(3))
    return "#{:02x}{:02x}{:02x}".format(*c)

def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def set_appearance(mode: str = "light"):
    # kept for compatibility
    ctk.set_appearance_mode("light")

# ──────────────────────────────────────────────
# Card helper: rounded beige container
# ──────────────────────────────────────────────
def card(
    parent,
    pad=(24, 18),
    *,
    fg: str | None = None,
    border_color: str | None = None,
    border_width: int = 1,
):
    """
    Returns (outer_frame, inner_frame).
    outer_frame and inner_frame are CTkFrame.
    """
    fg = fg or PALETTE["card"]
    border_color = border_color or PALETTE["border"]

    outer = ctk.CTkFrame(
        parent,
        corner_radius=RADIUS,
        fg_color=fg,
        border_color=border_color,
        border_width=border_width,
    )
    inner = ctk.CTkFrame(
        outer,
        corner_radius=RADIUS-2,
        fg_color=fg,
    )
    inner.pack(padx=pad[0], pady=pad[1], fill="both", expand=True)
    return outer, inner


def elevated_card(parent, pad=(20, 16)):
    wrap = ctk.CTkFrame(parent, corner_radius=RADIUS, fg_color=PALETTE["bg"])
    outer = ctk.CTkFrame(
        wrap,
        corner_radius=RADIUS,
        fg_color=PALETTE["card"],
        border_color=PALETTE["border"],
        border_width=1,
    )

    # fake shadow
    shadow = tk.Frame(wrap, bg=_mix("#000000", PALETTE["bg"], 0.92))
    shadow.place(x=6, y=6, relwidth=1.0, relheight=1.0)
    shadow.lower(outer)

    inner = ctk.CTkFrame(
        outer,
        corner_radius=RADIUS-2,
        fg_color=PALETTE["card"],
    )
    inner.pack(padx=pad[0], pady=pad[1], fill="both", expand=True)

    outer.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
    return wrap, inner


def badge(parent, text, fg=None, bg=None):
    fg = fg or PALETTE["primary"]
    bg = bg or PALETTE["chip"]
    lbl = ctk.CTkLabel(
        parent,
        text=text,
        text_color=fg,
        fg_color=bg,
        corner_radius=RADIUS,
        padx=8,
        pady=4,
        font=("Segoe UI Semibold", 10),
    )
    return lbl


def kpi(parent, title: str, value: str, trend: str = "▲ 0.0%", trend_fg: str = "#2B7A0B"):
    outer, inner = card(parent, pad=(18, 14))
    ctk.CTkLabel(inner, text=title, font=("Segoe UI", 11),
                 text_color=PALETTE["muted"]).pack(anchor="w")
    ctk.CTkLabel(inner, text=value, font=("Segoe UI Semibold", 24),
                 text_color=PALETTE["text"]).pack(anchor="w", pady=(6, 0))
    b = badge(inner, trend, fg=trend_fg)
    b.pack(anchor="w", pady=(8, 0))
    return outer


def scrollable(parent):
    """
    Scrollable vertical area using tk.Canvas but beige-themed.
    """
    outer = tk.Frame(parent, bg=PALETTE["bg"])
    canvas = tk.Canvas(outer, bg=PALETTE["bg"], highlightthickness=0, bd=0)
    vsb = ttk.Scrollbar(
        outer,
        orient="vertical",
        command=canvas.yview,
        style="Vertical.TScrollbar"
    )
    viewport = tk.Frame(canvas, bg=PALETTE["bg"])

    viewport.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=viewport, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)

    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    return outer, canvas, viewport
