# pages/superadmin_companies.py
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional, Tuple

from services.ui_shell import PageShell
from services.ui_theme import PALETTE as THEME_PALETTE, FONTS
from services.firebase_client import get_db

# ── palette (safe fallbacks) ──
BG_APP       = THEME_PALETTE.get("bg", "#f6f7fb")
BG_SURFACE   = THEME_PALETTE.get("card", "#ffffff")
TEXT_PRIMARY = THEME_PALETTE.get("text", "#111827")
TEXT_SECOND  = THEME_PALETTE.get("muted", "#6b7280")

# Friendly sort options (UI label → internal key)
SORT_OPTIONS: List[Tuple[str, str]] = [
    ("Name (A–Z)",        "name_asc"),
    ("Name (Z–A)",        "name_desc"),
    ("Status (Active→Susp.)", "status_active_first"),
    ("Status (Susp.→Active)", "status_suspended_first"),
]

# ────────────────────────── Optional Pillow for thumbnails ──────────────────────────
try:
    from PIL import Image, ImageTk
except Exception:
    Image, ImageTk = None, None


# ────────────────────────── Paths / image helpers ──────────────────────────
def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

def _icons_dir() -> str:
    return os.path.join(_project_root(), "data", "ui", "icons")

def _icon_path(name: str) -> Optional[str]:
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = os.path.join(_icons_dir(), f"{name}{ext}")
        if os.path.exists(p):
            return p
    return None

def _load_img(path: Optional[str], size: Tuple[int, int]) -> Optional[tk.PhotoImage]:
    if not path or not os.path.exists(path):
        return None
    if Image is None or ImageTk is None:
        return None
    try:
        im = Image.open(path).convert("RGBA").resize(size, Image.LANCZOS)
        return ImageTk.PhotoImage(im)
    except Exception:
        return None


# ────────────────────────── Page ──────────────────────────
class SuperadminCompaniesPage(PageShell):
    """
    Superadmin UI:
      • Toolbar (tabs + search + sort + view toggle)
      • Left: scrollable grid/list of companies
      • Right: details panel (thumbnail + info + Suspend/Activate)
      • Async Firestore load
    """
    def __init__(self, parent, controller, *_, **__):
        super().__init__(parent, controller, title="Companies (Superadmin)", active_key="companies")

        # state
        self._all: List[Dict[str, Any]] = []
        self._filtered: List[Dict[str, Any]] = []
        self._selected: Optional[Dict[str, Any]] = None
        self._thumb_cache: Dict[str, tk.PhotoImage] = {}

        # layout
        self.content.grid_columnconfigure(0, weight=1)   # list/grid
        self.content.grid_columnconfigure(1, weight=0)   # details
        self.content.grid_rowconfigure(1, weight=1)

        # styles (colors + flat combobox)
        self._init_styles()

        self._build_toolbar(self.content)
        self._build_left(self.content)
        self._build_right(self.content)

        self._load_async()

    # ────────────────────────── Styles ──────────────────────────
    def _init_styles(self):
        style = ttk.Style(self)

        # Primary (blue) — Grid/List
        style.configure(
            "Primary.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(14, 6),
            background="#1d4ed8",
            foreground="white",
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#2563eb"), ("!disabled", "#1d4ed8")],
            foreground=[("!disabled", "white")],
        )

        # Success (green) — Activate
        style.configure(
            "Success.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(12, 6),
            background="#16a34a",
            foreground="white",
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Success.TButton",
            background=[("active", "#22c55e"), ("!disabled", "#16a34a")],
            foreground=[("!disabled", "white")],
        )

        # Danger (red) — Suspend
        style.configure(
            "Danger.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(12, 6),
            background="#dc2626",
            foreground="white",
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#ef4444"), ("!disabled", "#dc2626")],
            foreground=[("!disabled", "white")],
        )

        # Flat, light Combobox — no gray bg in any state
        style.configure(
            "Flat.TCombobox",
            fieldbackground=BG_SURFACE,
            background=BG_SURFACE,
            foreground=TEXT_PRIMARY,
            borderwidth=0,
            arrowsize=14,
        )
        style.map(
            "Flat.TCombobox",
            fieldbackground=[
                ("readonly", BG_SURFACE),
                ("!disabled", BG_SURFACE),
                ("focus", BG_SURFACE),
                ("active", BG_SURFACE),
            ],
            foreground=[
                ("readonly", TEXT_PRIMARY),
                ("!disabled", TEXT_PRIMARY),
                ("focus", TEXT_PRIMARY),
                ("active", TEXT_PRIMARY),
            ],
            background=[
                ("readonly", BG_SURFACE),
                ("!disabled", BG_SURFACE),
                ("focus", BG_SURFACE),
                ("active", BG_SURFACE),
            ],
        )

    # ────────────────────────── Toolbar ──────────────────────────
    def _build_toolbar(self, parent: tk.Widget):
        bar = tk.Frame(parent, bg=BG_SURFACE)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(8, 10))
        for i in range(8):
            bar.grid_columnconfigure(i, weight=0)
        bar.grid_columnconfigure(4, weight=1)

        # Tabs (All / Active / Suspended) — background removed & matches card color
        self._scope = tk.StringVar(value="all")
        tabs = tk.Frame(bar, bg=BG_SURFACE, bd=0, highlightthickness=0)
        tabs.grid(row=0, column=0, padx=(12, 8), pady=10, sticky="w")

        def _add_tab(text: str, val: str):
            rb = tk.Radiobutton(
                tabs,
                text=text,
                value=val,
                variable=self._scope,
                command=self._apply_filters,
                bg=BG_SURFACE,                 # ← match card color
                activebackground=BG_SURFACE,   # ← no hover halo
                fg=TEXT_PRIMARY,
                selectcolor=BG_SURFACE,        # ← indicator fill matches bg (no light box)
                highlightthickness=0,
                bd=0,
                padx=6, pady=2
            )
            rb.pack(side="left", padx=(0, 10))
        _add_tab("All", "all")
        _add_tab("Active", "active")
        _add_tab("Suspended", "suspended")

        # Search
        tk.Label(bar, text="Search", bg=BG_SURFACE, fg=TEXT_SECOND,
                 font=FONTS.get("body", ("Segoe UI", 10))).grid(row=0, column=2, padx=(8, 6))
        self._q = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self._q, width=30)
        ent.grid(row=0, column=3, sticky="w")
        ent.bind("<KeyRelease>", lambda _e: self._apply_filters())

        # spacer
        tk.Frame(bar, bg=BG_SURFACE).grid(row=0, column=4, sticky="ew")

        # Sort
        tk.Label(bar, text="Sort", bg=BG_SURFACE, fg=TEXT_SECOND,
                 font=FONTS.get("body", ("Segoe UI", 10))).grid(row=0, column=5, padx=(6, 6))
        self._sort_label = tk.StringVar(value="Name (A–Z)")
        sort_cb = ttk.Combobox(
            bar, textvariable=self._sort_label, width=22, state="readonly",
            values=[label for (label, _key) in SORT_OPTIONS],
            style="Flat.TCombobox",
        )
        sort_cb.grid(row=0, column=6, padx=(0, 10))
        sort_cb.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())

        # View mode (colored)
        self._view_mode = tk.StringVar(value="grid")
        ttk.Button(bar, text="Grid", style="Primary.TButton",
                   command=lambda: self._set_view("grid")).grid(row=0, column=7, padx=(4, 4))
        ttk.Button(bar, text="List", style="Primary.TButton",
                   command=lambda: self._set_view("list")).grid(row=0, column=8, padx=(0, 12))

    def _current_sort_key(self) -> str:
        label = self._sort_label.get()
        for lab, key in SORT_OPTIONS:
            if lab == label:
                return key
        return "name_asc"

    def _set_view(self, mode: str):
        self._view_mode.set(mode)
        self._render_cards()

    # ────────────────────────── Left (scrollable grid/list) ──────────────────────────
    def _build_left(self, parent: tk.Widget):
        wrap = tk.Frame(parent, bg=BG_APP)
        wrap.grid(row=1, column=0, sticky="nsew")

        self._canvas = tk.Canvas(wrap, bd=0, highlightthickness=0, bg=BG_APP)
        self._scroll = ttk.Scrollbar(wrap, orient="vertical", command=self._canvas.yview)
        self._inner = tk.Frame(self._canvas, bg=BG_APP)

        self._inner.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._canvas.configure(yscrollcommand=self._scroll.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        self._scroll.pack(side="right", fill="y")

    # ────────────────────────── Right (details panel) ──────────────────────────
    def _build_right(self, parent: tk.Widget):
        self._detail = tk.Frame(parent, bg=BG_SURFACE, width=320)
        self._detail.grid(row=1, column=1, sticky="ns")
        self._detail.grid_propagate(False)

        tk.Label(self._detail, text="Information", font=("Segoe UI", 12, "bold"),
                 bg=BG_SURFACE, fg=TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(16, 10))

        self._thumb_lbl = tk.Label(self._detail, bg=BG_SURFACE)
        self._thumb_lbl.pack(padx=16, pady=(0, 10))

        self._kv = tk.Frame(self._detail, bg=BG_SURFACE)
        self._kv.pack(fill="x", padx=16)

        # action buttons
        btns = tk.Frame(self._detail, bg=BG_SURFACE)
        btns.pack(fill="x", padx=16, pady=16)
        self._toggle_btn = ttk.Button(btns, text="Disable Company", command=self._toggle_active)
        self._toggle_btn.pack(fill="x", pady=4)

        self._render_details(None)

    def _render_details(self, c: Optional[Dict[str, Any]]):
        # clear
        for w in self._kv.winfo_children():
            w.destroy()
        self._thumb_lbl.configure(image=""); self._thumb_lbl.image = None

        if not c:
            tk.Label(self._kv, text="Select a company", bg=BG_SURFACE, fg=TEXT_SECOND).pack(anchor="w")
            self._toggle_btn.configure(text="Disable Company", state="disabled", style="Primary.TButton")
            return

        # thumbnail
        img = self._thumb_cache.get(c["id"])
        if img:
            self._thumb_lbl.configure(image=img); self._thumb_lbl.image = img

        # key-values
        def kv(k, v):
            row = tk.Frame(self._kv, bg=BG_SURFACE)
            tk.Label(row, text=k, bg=BG_SURFACE, fg=TEXT_SECOND).pack(side="left")
            tk.Label(row, text=v, bg=BG_SURFACE, fg=TEXT_PRIMARY).pack(side="right")
            row.pack(fill="x", pady=2)

        kv("Name", c.get("name", "—"))
        kv("Company ID", c.get("id", "—"))
        kv("Status", "Active" if c.get("active", True) else "Suspended")

        # set button color + text
        if c.get("active", True):
            self._toggle_btn.configure(text="Suspend Company", state="normal", style="Danger.TButton")
        else:
            self._toggle_btn.configure(text="Activate Company", state="normal", style="Success.TButton")

    # ────────────────────────── Data loading ──────────────────────────
    def _load_async(self):
        def work():
            db = get_db()
            rows: List[Dict[str, Any]] = []
            try:
                if not db:
                    raise RuntimeError("No Firestore client")

                # load companies only
                docs = db.collection("companies").get()
                for d in docs:
                    data = d.to_dict() or {}
                    rows.append({
                        "id": data.get("id") or d.id,
                        "doc_id": d.id,
                        "name": data.get("name") or data.get("company_name") or "Company",
                        "active": bool(data.get("active", True)),
                        "logo_path": None,
                    })
            except Exception:
                # fallback demo data
                rows = [
                    {"id": "c01", "doc_id": "c01", "name": "Acme Logistics", "active": True,  "logo_path": None},
                    {"id": "c02", "doc_id": "c02", "name": "North Dock",     "active": True,  "logo_path": None},
                    {"id": "c03", "doc_id": "c03", "name": "Site Bravo",      "active": False, "logo_path": None},
                ]
            return rows

        def done(rows: List[Dict[str, Any]]):
            self._all = rows
            self._build_thumbs(rows)
            self._apply_filters()

        threading.Thread(target=lambda: self._call_and(self, work, done), daemon=True).start()

    @staticmethod
    def _call_and(widget, fn, cb):
        try:
            res = fn()
        except Exception:
            res = []
        try:
            widget.after(0, lambda: cb(res))
        except Exception:
            pass

    def _build_thumbs(self, rows: List[Dict[str, Any]]):
        placeholder = _icon_path("companies")
        for r in rows:
            p = r.get("logo_path") or placeholder
            img = _load_img(p, size=(96, 96))
            if img:
                self._thumb_cache[r["id"]] = img

    # ────────────────────────── Filtering / sorting / rendering ──────────────────────────
    def _apply_filters(self):
        q = (getattr(self, "_q", tk.StringVar()).get() or "").strip().lower()
        scope = self._scope.get()
        out: List[Dict[str, Any]] = []

        for r in self._all:
            if q and q not in (r.get("name", "").lower()):
                continue
            if scope == "active" and not r.get("active", True):
                continue
            if scope == "suspended" and r.get("active", True):
                continue
            out.append(r)

        key = self._current_sort_key()
        if key.startswith("name"):
            reverse = (key == "name_desc")
            out.sort(key=lambda x: x.get("name", "").lower(), reverse=reverse)
        else:
            # status sorts
            if key == "status_active_first":
                out.sort(key=lambda x: 0 if x.get("active", True) else 1)
            else:
                out.sort(key=lambda x: 0 if not x.get("active", True) else 1)

        self._filtered = out
        self._render_cards()

    def _render_cards(self):
        for w in self._inner.winfo_children():
            w.destroy()

        mode = self._view_mode.get()
        if mode == "list":
            self._render_list()
            return

        # grid
        col_count = max(2, self._compute_grid_cols())
        for i in range(col_count):
            self._inner.grid_columnconfigure(i, weight=1)

        r, c = 0, 0
        for comp in self._filtered:
            card = self._make_card(self._inner, comp)
            card.grid(row=r, column=c, padx=12, pady=12, sticky="nsew")
            c += 1
            if c >= col_count:
                c = 0
                r += 1

    def _compute_grid_cols(self) -> int:
        width = max(1, self._canvas.winfo_width() or self._inner.winfo_width() or 800)
        cols = max(2, int(width / 260))  # ~240px card + gaps
        return min(cols, 5)

    def _make_card(self, parent: tk.Widget, comp: Dict[str, Any]) -> tk.Frame:
        card = tk.Frame(parent, bg=BG_SURFACE, bd=0, highlightthickness=0)
        card.grid_propagate(False)
        card.configure(width=240, height=200)

        img = self._thumb_cache.get(comp["id"])
        thumb = tk.Label(card, image=img, bg=BG_SURFACE)
        if img:
            thumb.image = img
        thumb.pack(padx=12, pady=(12, 8))

        name = comp.get("name", "Company")
        tk.Label(card, text=name, bg=BG_SURFACE, fg=TEXT_PRIMARY,
                 font=("Segoe UI", 10, "bold")).pack(anchor="center")

        meta = tk.Frame(card, bg=BG_SURFACE)
        meta.pack(pady=(6, 8))
        status = "Active" if comp.get("active", True) else "Suspended"
        tk.Label(meta, text=status, bg=BG_SURFACE,
                 fg=("#16a34a" if comp.get("active", True) else "#dc2626")).pack(side="left")

        def select(_e=None):
            self._selected = comp
            self._render_details(comp)
        card.bind("<Button-1>", select)
        thumb.bind("<Button-1>", select)
        return card

    def _render_list(self):
        header = tk.Frame(self._inner, bg=BG_APP)
        header.pack(fill="x", padx=12, pady=(8, 4))
        for txt, w in (("Name", 40), ("Status", 12)):
            tk.Label(header, text=txt, bg=BG_APP, fg=TEXT_SECOND,
                     width=w, anchor="w").pack(side="left")

        for comp in self._filtered:
            row = tk.Frame(self._inner, bg=BG_SURFACE)
            row.pack(fill="x", padx=12, pady=6)

            tk.Label(row, text=comp.get("name", "Company"), bg=BG_SURFACE,
                     fg=TEXT_PRIMARY, width=40, anchor="w").pack(side="left", padx=(8, 0))
            tk.Label(row, text=("Active" if comp.get("active", True) else "Suspended"),
                     bg=BG_SURFACE,
                     fg=("#16a34a" if comp.get("active", True) else "#dc2626"),
                     width=12, anchor="w").pack(side="left")

            row.bind("<Button-1>", lambda _e, c=comp: (setattr(self, "_selected", c), self._render_details(c)))

    # ────────────────────────── Actions ──────────────────────────
    def _toggle_active(self):
        if not self._selected:
            return
        db = get_db()
        sel = self._selected
        doc_id = sel.get("doc_id") or sel.get("id")
        new_val = not bool(sel.get("active", True))
        try:
            if db and doc_id:
                db.collection("companies").document(str(doc_id)).update({"active": new_val})
        except Exception:
            pass  # demo mode OK
        sel["active"] = new_val
        self._render_details(sel)
        self._apply_filters()
