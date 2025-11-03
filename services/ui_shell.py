from __future__ import annotations
import os
import tkinter as tk
from tkinter import messagebox  # ⬅ added for confirmation popup
from typing import Callable, Optional
import customtkinter as ctk

from .ui_theme import PALETTE as _PALETTE, FONTS as _FONTS
from .session import get_current_user  # so we can hydrate controller.company_*

# ────────────────────────── palette / fonts ──────────────────────────
def _c(key: str, default: str):
    return _PALETTE.get(key, default)

def _f(key: str, default=("Segoe UI", 10)):
    return _FONTS.get(key, default)

PALETTE = {
    "background": "#F7EFE3",        # Light neutral background
    "surface": "#F0E4D5",
    "border": "#B59E85",
    "text_primary": "#3E2E1E",
    "text_secondary": "#6B5A48",
    "sidebar": "#C2A68C",
    "sidebar_active": "#B5977F",
    "sidebar_hover": "#CDB49A",
    "primary": "#3E2E1E",
}

SIDEBAR_WIDTH = 240
SIDEBAR_ROW_HEIGHT = 58
HEADER_HEIGHT = 88
ICON_SIZE = 32

# ────────────────────────── optional Pillow ──────────────────────────
try:
    from PIL import Image, ImageTk, ImageOps, ImageDraw, ImageFilter
except Exception:
    Image = None
    ImageTk = None
    ImageOps = None
    ImageDraw = None
    ImageFilter = None

# ────────────────────────── utilities ──────────────────────────
def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

def _first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None

# ────────────────────────── gradients ──────────────────────────
def _make_sidebar_gradient(width: int, height: int) -> Optional[tk.PhotoImage]:
    """Render a vertical gradient image for sidebar depth."""
    if not (Image and ImageTk):
        return None
    try:
        from PIL import Image as _Img, ImageDraw as _Draw
        im = _Img.new("RGB", (width, height), PALETTE["sidebar"])
        draw = _Draw.Draw(im)

        # soft beige gradient top -> bottom
        top = (188, 160, 130)
        bottom = (218, 200, 178)
        for y in range(height):
            t = y / max(1, height - 1)
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        return ImageTk.PhotoImage(im)
    except Exception:
        return None

def _make_header_glass(width: int, height: int) -> Optional[tk.PhotoImage]:
    """Subtle frosted-glass overlay for header."""
    if not (Image and ImageTk):
        return None
    try:
        from PIL import Image as _Img, ImageDraw as _Draw
        im = _Img.new("RGBA", (width, height), (255, 255, 255, 0))
        draw = _Draw.Draw(im)

        # light top-to-bottom alpha fade
        for y in range(height):
            alpha = int(80 - (y / height) * 40)
            draw.line([(0, y), (width, y)], fill=(255, 255, 255, alpha))

        return ImageTk.PhotoImage(im)
    except Exception:
        return None

# ────────────────────────── icon / avatar utils ──────────────────────────
_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".jfif")

def _icons_dir() -> str:
    return os.path.join(_project_root(), "data", "ui", "icons")

def _avatars_dir() -> str:
    return os.path.join(_project_root(), "data", "ui", "avatars")

def _resolve_asset(dirpath: str, base_name: str) -> Optional[str]:
    if not base_name:
        return None
    for ext in _EXTS:
        p = os.path.join(dirpath, base_name + ext)
        if os.path.exists(p):
            return p
    return None

def _load_image(path: str | None, size: int | tuple[int, int] | None) -> Optional[tk.PhotoImage]:
    if not path or not os.path.exists(path):
        return None
    if Image and ImageTk:
        try:
            im = Image.open(path)
            if size:
                if isinstance(size, int):
                    size = (size, size)
                im = im.resize(size, Image.LANCZOS)
            return ImageTk.PhotoImage(im)
        except Exception:
            pass
    try:
        from tkinter import PhotoImage
        return PhotoImage(file=path)
    except Exception:
        return None

def get_icon(name: str, size: int = ICON_SIZE) -> Optional[tk.PhotoImage]:
    p = _resolve_asset(_icons_dir(), name)
    return _load_image(p, size)

def get_avatar(name: str = "user", size: int = 28, circle: bool = True) -> Optional[tk.PhotoImage]:
    p = _resolve_asset(_avatars_dir(), name)
    if not p:
        return None
    if not (Image and ImageTk):
        return _load_image(p, size)
    try:
        im = Image.open(p).convert("RGBA")
        if isinstance(size, int):
            size = (size, size)
        im = im.resize(size, Image.LANCZOS)
        if circle and ImageOps and ImageDraw:
            mask = Image.new("L", size, 0)
            d = ImageDraw.Draw(mask)
            d.ellipse((0, 0, size[0], size[1]), fill=255)
            im.putalpha(mask)
        return ImageTk.PhotoImage(im)
    except Exception:
        return _load_image(p, size)

_ICON_MAP = {
    "home": "dashboard",
    "companies": "companies",
    "zones": "zones",
    "workers": "workers",
    "profile": "profile",
    "entry": "entry",
    "live": "logs",
    "logs": "sanction",
    "reports": "reports",
    "add admin": "add-admin",
    "logout": "logout",
}

# ────────────────────────── Header ──────────────────────────
def build_header(parent, title: str, right_widget: tk.Widget | None = None):
    bg_hdr = PALETTE["surface"]

    bar = ctk.CTkFrame(
        parent,
        fg_color=bg_hdr,
        height=HEADER_HEIGHT,
        corner_radius=0,
        border_width=0,
    )
    bar.grid(row=0, column=0, columnspan=3, sticky="ew")
    bar.grid_propagate(False)

    # glass overlay for subtle shine
    glass = _make_header_glass(1600, HEADER_HEIGHT)
    if glass:
        overlay = tk.Label(bar, image=glass, bd=0)
        overlay.image = glass
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

    content = ctk.CTkFrame(bar, fg_color=bg_hdr, corner_radius=0)
    content.pack(fill="both", expand=True)

    title_lbl = ctk.CTkLabel(
        content,
        text=title.upper(),
        text_color=PALETTE["text_primary"],
        font=("Segoe UI Semibold", 19),
        padx=20,
        pady=18,
    )
    title_lbl.pack(side="left")

    if right_widget is not None:
        chip_bg = bg_hdr
        chip = tk.Frame(content, bg=chip_bg, bd=0)
        chip.pack(side="right", padx=18, pady=14)

        for child in right_widget.winfo_children():
            try:
                child.configure(bg=chip_bg, fg=PALETTE["text_primary"])
            except Exception:
                pass

        right_widget.pack(in_=chip, side="left", padx=10, pady=2)

    shadow = tk.Frame(bar, bg=PALETTE["border"], height=1)
    shadow.pack(side="bottom", fill="x")
    return bar

# ────────────────────────── Sidebar Row ──────────────────────────
def _sidebar_row(parent, text: str, key: str, active_key: str, on_nav: Callable[[str], None]):
    row = tk.Frame(
        parent,
        bg=PALETTE["sidebar"],
        width=SIDEBAR_WIDTH,
        height=SIDEBAR_ROW_HEIGHT,
        highlightthickness=0,
        bd=0,
    )
    row.pack(fill="x")
    row.pack_propagate(False)

    bar = tk.Frame(row, width=4, bg=PALETTE["primary"])
    bar.place_forget()

    inner = tk.Frame(row, bg=row["bg"], highlightthickness=0)
    inner.pack(fill="both", expand=True, padx=12)

    icon_img = get_icon(_ICON_MAP.get(key, ""), size=ICON_SIZE)
    icon_lbl = None
    if icon_img:
        icon_lbl = tk.Label(inner, image=icon_img, bg=inner["bg"], bd=0)
        icon_lbl.image = icon_img
        icon_lbl.pack(side="left", padx=(4, 10), pady=6)

    lbl = tk.Label(
        inner,
        text=text,
        bg=inner["bg"],
        fg=PALETTE["text_primary"],
        anchor="w",
        padx=4,
        font=("Segoe UI", 11),
    )
    lbl.pack(fill="x", side="left")

    glow = tk.Frame(row, bg="#000000", height=1)
    glow.place_forget()

    def _apply(state: str):
        is_active = (key == active_key)
        if state == "hover" or is_active:
            color = PALETTE["sidebar_active"] if is_active else PALETTE["sidebar_hover"]
            row.configure(bg=color)
            inner.configure(bg=color)
            lbl.configure(bg=color)
            if icon_lbl:
                icon_lbl.configure(bg=color)
            if is_active:
                bar.place(x=0, y=0, width=4, relheight=1.0)
                glow.place(x=0, rely=0.9, relwidth=1, height=2)
                glow.configure(bg="#8B6F57")
            else:
                glow.place_forget()
        else:
            row.configure(bg=PALETTE["sidebar"])
            inner.configure(bg=PALETTE["sidebar"])
            lbl.configure(bg=PALETTE["sidebar"])
            if icon_lbl:
                icon_lbl.configure(bg=PALETTE["sidebar"])
            bar.place_forget()
            glow.place_forget()

    # Hover and click bindings
    widgets_to_bind = [row, inner, lbl] + ([icon_lbl] if icon_lbl else [])
    for w in widgets_to_bind:
        w.bind("<Enter>", lambda e: (_apply("hover"), row.configure(highlightbackground="#000", highlightthickness=1)))
        w.bind("<Leave>", lambda e: (_apply("normal"), row.configure(highlightthickness=0)))
        w.bind("<Button-1>", lambda _e: on_nav(key))
    _apply("normal")
    return row

# ────────────────────────── Sidebar Build ──────────────────────────
def build_sidebar(
    parent,
    on_nav: Callable[[str], None],
    active: str,
    current_role: str = "",
    current_email: str = "",
):
    wrap = tk.Frame(
        parent,
        bg=PALETTE["sidebar"],
        width=SIDEBAR_WIDTH,
        height=1000,
        bd=0,
    )
    wrap.grid(row=1, column=0, sticky="nsw")
    wrap.grid_propagate(False)

    # vertical shadow divider
    tk.Frame(
        parent,
        bg="#000000",
        width=1,
        height=1000,
        highlightthickness=0
    ).grid(row=1, column=1, sticky="ns")

    # background gradient fill
    gradient = _make_sidebar_gradient(SIDEBAR_WIDTH, 800)
    if gradient:
        bg_lbl = tk.Label(wrap, image=gradient, bd=0)
        bg_lbl.image = gradient
        bg_lbl.place(relx=0, rely=0, relwidth=1, relheight=1)
        # make sure bg_lbl stays behind everything
        try:
            bg_lbl.lower()
        except Exception:
            pass

    # menu_frame needs a stable bg color so it doesn't go black on restore
    menu_frame = tk.Frame(
        wrap,
        bg=PALETTE["sidebar"],
        highlightthickness=0,
    )
    menu_frame.pack(fill="both", expand=True)
    try:
        menu_frame.lift()
    except Exception:
        pass

    tk.Label(
        menu_frame,
        text="Menu",
        bg=PALETTE["sidebar"],
        fg=PALETTE["text_secondary"],
        font=("Segoe UI", 10, "bold"),
        padx=16,
        pady=8,
    ).pack(anchor="w")

    role = (current_role or "").strip().lower()
    is_superadmin = role == "superadmin"

    items = (
        [("Companies", "companies"), ("Profile", "profile"), ("Logout", "logout")]
        if is_superadmin
        else [
            ("Dashboard", "home"),
            ("Zones", "zones"),
            ("Workers", "workers"),
            ("Profile", "profile"),
            ("Entry", "entry"),
            ("Live Monitor", "live"),
            ("Logs", "logs"),
            ("Reports", "reports"),
            ("Add Admin", "add admin"),
            ("Logout", "logout"),
        ]
    )

    for text, key in items:
        _sidebar_row(menu_frame, text, key, active, on_nav)

    return wrap

# ────────────────────────── PageShell ──────────────────────────
class PageShell(ctk.CTkFrame):
    """
    Common shell used by pages.

    Also ensures controller has:
        controller.current_company_id
        controller.current_company_name
    so the rest of the app can just read them.
    """

    def __init__(self, parent, controller, title: str, active_key: str):
        super().__init__(parent, fg_color=PALETTE["background"], corner_radius=0)

        self.controller = controller

        # hydrate controller with company info if missing
        session_user = get_current_user() or {}
        if not hasattr(self.controller, "current_company_id") or self.controller.current_company_id is None:
            self.controller.current_company_id = session_user.get("company_id")
        if not hasattr(self.controller, "current_company_name") or not self.controller.current_company_name:
            self.controller.current_company_name = (
                session_user.get("company_name")
                or session_user.get("company")
                or "Site Safety"
            )

        email_text = getattr(controller, "current_user_email", "")
        role_text = getattr(controller, "current_user_role", "")

        # base layout grid
        self._bg_label = tk.Label(self, bd=0, bg=PALETTE["background"])
        self._bg_label.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # header chip (avatar + email)
        right_chip = tk.Frame(bg=PALETTE["surface"], bd=0)

        avatar_img = get_avatar("user", size=28, circle=True)
        if avatar_img:
            av = tk.Label(right_chip, image=avatar_img, bg=PALETTE["surface"], bd=0)
            av.image = avatar_img
            av.pack(side="left", padx=(10, 6))

        tk.Label(
            right_chip,
            text=email_text,
            bg=PALETTE["surface"],
            fg=PALETTE["text_primary"],
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=(0, 10))

        # header bar
        self._header = build_header(self, title, right_widget=right_chip)

        # sidebar
        build_sidebar(
            self,
            self._navigate,
            active_key,
            current_role=role_text,
            current_email=email_text,
        )

        # main content area
        self.content = ctk.CTkFrame(self, fg_color=PALETTE["background"])
        self.content.grid(row=1, column=2, sticky="nsew")

    def _confirm_and_logout(self):
        """
        Ask user to confirm logout. Works for admin / superadmin / normal.
        If they confirm, call controller.logout() (if it exists).
        """
        answer = messagebox.askyesno(
            "Confirm Logout",
            "Are you sure you want to log out?"
        )
        if not answer:
            return  # user cancelled, stay in app

        # user confirmed
        if hasattr(self.controller, "logout") and callable(self.controller.logout):
            try:
                self.controller.logout()
                return
            except Exception:
                # if controller.logout() throws, we still try fallback nav
                pass

        # fallback: try to go to login page if the app uses show_frame
        if hasattr(self.controller, "show_frame"):
            try:
                self.controller.show_frame("LoginPage")
                return
            except Exception:
                pass

        # last fallback: close entire window
        try:
            self.controller.destroy()
        except Exception:
            pass

    def _navigate(self, key: str):
        if key == "logout":
            self._confirm_and_logout()
            return

        if hasattr(self.controller, "navigate") and callable(self.controller.navigate):
            self.controller.navigate(key)
            return

        mapping = {
            "home": "Home",
            "companies": "Companies",
            "zones": "Zones",
            "profile": "Profile",
            "entry": "Entry",
            "live": "LiveMonitor",
            "logs": "Logs",
            "reports": "Reports",
            "add admin": "Add Admin",
            "workers": "Workers",
        }
        target = mapping.get(key)
        if target and hasattr(self.controller, "show_frame"):
            self.controller.show_frame(target)
