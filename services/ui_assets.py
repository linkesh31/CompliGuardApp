# services/ui_assets.py
import os
from functools import lru_cache

# Optional Pillow for resizing (recommended)
try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

# Resolve paths relative to this file (works no matter where you launch python)
_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_ICONS_DIR = os.path.join(_BASE, "data", "ui", "icons")
_AVATARS_DIR = os.path.join(_BASE, "data", "ui", "avatars")
_LOGOS_DIR = os.path.join(_BASE, "data", "ui", "logos")
_CARDS_DIR = os.path.join(_BASE, "data", "ui", "cards")

_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

def _first_existing(path_no_ext: str):
    for ext in _EXTS:
        p = path_no_ext + ext
        if os.path.exists(p):
            return p
    return None

@lru_cache(maxsize=256)
def _load_image(path: str, size: int | tuple[int, int] | None):
    """Return a Tk PhotoImage from disk. Uses Pillow if available for resize."""
    if not os.path.exists(path):
        return None
    # Try Pillow for proper resize
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
    # Fallback: Tk PhotoImage (PNG/GIF only, no resize)
    try:
        from tkinter import PhotoImage
        return PhotoImage(file=path)
    except Exception:
        return None

def get_icon(name: str, size: int = 18):
    """
    Look for data/ui/icons/<name>.(png|jpg|jpeg|gif|webp) and return PhotoImage or None.
    Cached and safe if file missing.
    """
    base = os.path.join(_ICONS_DIR, name)
    path = _first_existing(base)
    return _load_image(path, size) if path else None

def get_avatar(name: str = "user", size: int = 24):
    base = os.path.join(_AVATARS_DIR, name)
    path = _first_existing(base)
    return _load_image(path, size) if path else None

def get_logo(name: str = "logo", size: int = 24):
    base = os.path.join(_LOGOS_DIR, name)
    path = _first_existing(base)
    return _load_image(path, size) if path else None

def get_card_image(name_hint: str = "warehouse", size: tuple[int, int] | None = None):
    base = os.path.join(_CARDS_DIR, name_hint)
    path = _first_existing(base)
    return _load_image(path, size) if path else None
