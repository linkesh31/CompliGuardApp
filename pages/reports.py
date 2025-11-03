from __future__ import annotations

import io
import csv
import threading
import datetime as _dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.ui_shell import PageShell
from services.session import require_user
from services.firebase_client import get_db

# Zones + cameras (to exclude Entry-only zones)
try:
    from services.zones import list_zones, list_cameras_by_zone
except Exception:
    def list_zones(_company_id: str) -> List[Dict[str, Any]]:
        return []
    def list_cameras_by_zone(_zid: str) -> List[Dict[str, Any]]:
        return []

# Optional matplotlib (charts). If missing, PDF export will skip charts gracefully.
try:
    import matplotlib
    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt
    _HAVE_MPL = True
except Exception:
    _HAVE_MPL = False

# Optional PDF (reportlab)
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas as _rl_canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    _HAVE_RL = True
except Exception:
    _HAVE_RL = False


# ────────────────── helpers ──────────────────
def _s(v: Any) -> str:
    return ("" if v is None else str(v)).strip()

def _company_id_from(user: Dict[str, Any]) -> Optional[str]:
    for k in ("company_id", "companyId", "companyID", "company"):
        if k in user and _s(user[k]): return _s(user[k])
    return None

def _company_keys(cid_any: Any) -> List[Any]:
    keys: List[Any] = []
    s = _s(cid_any)
    if s:
        keys.append(s)
        if s.isdigit():
            try: keys.append(int(s))
            except Exception: pass
    if isinstance(cid_any, int) and cid_any not in keys:
        keys.append(cid_any)
    return keys

def _safe_epoch_s(ts: Any) -> Optional[float]:
    try:
        if hasattr(ts, "to_datetime"): return float(ts.to_datetime().timestamp())
        if hasattr(ts, "timestamp"): return float(ts.timestamp())
        if isinstance(ts, (int, float)):
            v = float(ts); return v/1000.0 if v > 1e12 else v
    except Exception:
        return None
    return None

def _ts_to_str(ts: Any) -> str:
    v = _safe_epoch_s(ts)
    if v is None: return _s(ts)
    return _dt.datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M:%S")

def _risk_tokens(v: str) -> Dict[str, bool]:
    t = _s(v).lower()
    return {
        "helmet": ("helmet" in t or "hardhat" in t or "hard_hat" in t),
        "vest": ("vest" in t or "safety vest" in t or "safety_vest" in t),
        "gloves": ("glove" in t or "gloves" in t or "hand_glove" in t),
        "boots": ("boot" in t or "boots" in t or "shoe" in t or "shoes" in t or "safety_shoe" in t),
    }

def _risk_human(v: str) -> str:
    t = _s(v).lower()
    if not t: return "—"
    flags = _risk_tokens(t)
    names = []
    if flags["helmet"]: names.append("Helmet")
    if flags["vest"]:   names.append("Vest")
    if flags["gloves"]: names.append("Gloves")
    if flags["boots"]:  names.append("Boots")
    if names: return f"{', '.join(names)} Missing"
    if "high" in t or t == "3":   return "High"
    if "med" in t or t == "2":    return "Medium"
    if "low" in t or t == "1":    return "Low"
    return v or "—"

def _level_key(v: str) -> str:
    t = (v or "").strip().lower()
    if t in ("3", "high", "critical", "severe"): return "high"
    if t in ("2", "med", "medium"): return "medium"
    if t in ("1", "low"): return "low"
    return ""

# camera helpers to exclude Entry zones
def _camera_source(cam: Dict[str, Any]) -> Optional[str]:
    if not cam or cam.get("active") is False: return None
    for k in ("rtsp_url", "http_url"):
        s = _s(cam.get(k))
        if s: return s
    return None

def _is_entry_camera(cam: Dict[str, Any]) -> bool:
    mode = (_s(cam.get("camera_mode")) or _s(cam.get("mode"))).lower()
    return mode == "entry"

def _zone_is_entry(z: Dict[str, Any]) -> bool:
    """Heuristic: treat zone as 'Entry' if it has any camera with entry mode OR name contains 'entry'."""
    zid = _s(z.get("id") or z.get("zone_id") or z.get("doc_id"))
    try:
        cams = list_cameras_by_zone(zid) or []
    except Exception:
        cams = []
    for c in cams:
        if _is_entry_camera(c) and _camera_source(c):
            return True
    name = _s(z.get("name") or z.get("display_name") or z.get("code") or "")
    return "entry" in name.lower()


@dataclass
class VRow:
    id: str
    ts: Any
    zone_id: str
    zone_name: str
    zone_level: str  # "high"/"medium"/"low" or ""
    camera: str
    risk_text: str   # raw PPE string or severity text
    offender_name: str
    offender_id: str


# ───────── tiny calendar (same UX as Logs page) ─────────
class MiniCalendar(tk.Toplevel):
    def __init__(self, parent, initial: Optional[str], on_pick):
        super().__init__(parent)
        self.title("Pick a date")
        self.configure(bg=PALETTE.get("card", "#ffffff"))
        you = self
        try:
            you.resizable(False, False)
        except Exception:
            pass
        you.transient(parent)
        you.grab_set()
        self.on_pick = on_pick

        today = _dt.date.today()
        try:
            if initial:
                y, m, d = map(int, initial.split("-"))
                cur = _dt.date(y, m, d)
            else:
                cur = today
        except Exception:
            cur = today
        self.cur_year, self.cur_month = cur.year, cur.month

        wrap = tk.Frame(self, bg=PALETTE.get("card", "#ffffff"))
        wrap.pack(padx=10, pady=10)

        top = tk.Frame(wrap, bg=PALETTE.get("card", "#ffffff"))
        top.pack(fill="x")
        ttk.Button(top, text="◀", width=3, command=lambda: self._move(-1)).pack(side="left")
        self.title_lbl = ttk.Label(top, text="", font=("Segoe UI", 10, "bold"))
        self.title_lbl.pack(side="left", expand=True)
        ttk.Button(top, text="▶", width=3, command=lambda: self._move(1)).pack(side="right")

        self.grid = tk.Frame(wrap, bg=PALETTE.get("card", "#ffffff"))
        self.grid.pack(pady=(6, 0))
        self._render()

    def _move(self, delta_month: int):
        y, m = self.cur_year, self.cur_month
        m += delta_month
        if m < 1:
            m, y = 12, y-1
        elif m > 12:
            m, y = 1, y+1
        self.cur_year, self.cur_month = y, m
        self._render()

    def _render(self):
        for w in self.grid.winfo_children():
            w.destroy()
        import calendar as _cal
        self.title_lbl.config(text=f"{_cal.month_name[self.cur_month]} {self.cur_year}")
        for i, wd in enumerate(["Mo","Tu","We","Th","Fr","Sa","Su"]):
            ttk.Label(self.grid, text=wd, width=3, anchor="center").grid(row=0, column=i, padx=2, pady=2)
        cal = _cal.Calendar(firstweekday=0)
        row = 1
        for week in cal.monthdayscalendar(self.cur_year, self.cur_month):
            for col, day in enumerate(week):
                if day == 0:
                    tk.Label(
                        self.grid, text="", width=3,
                        bg=PALETTE.get("card","#fff")
                    ).grid(row=row, column=col, padx=1, pady=1)
                else:
                    ttk.Button(
                        self.grid, text=str(day).rjust(2), width=3,
                        command=lambda d=day: self._pick(d)
                    ).grid(row=row, column=col, padx=1, pady=1)
            row += 1

    def _pick(self, day: int):
        ds = f"{self.cur_year:04d}-{self.cur_month:02d}-{day:02d}"
        try:
            self.on_pick(ds)
        finally:
            self.destroy()


# ────────────────── Reports Page ──────────────────
class ReportsPage(PageShell):
    """
    Reports:
      1) Violations by Zone         (choose 1 zone or All)
      2) Violations by Risk Level   (choose Low/Medium/High or All)
      3) Violations by PPE          (choose Helmet/Vest/Gloves/BootS COMBINATION)
      4) Repeated Offenders         (aggregated list with violation types)

    Validation:
    - We block preview/export if any violations in range have blank offender_name,
      so you don't export "Unknown".
    """

    # Match AddAdmin visual language
    PAGE_BG = "#E6D8C3"
    TEXT_FG = "#000000"
    ACTIVE_ROW_BG = "#5D866C"
    ENTRY_BG = "#F5EEDF"
    CARD_BG = "#EFE3D0"
    ACCENT = "#0077b6"
    ACCENT_HOVER = "#00b4d8"
    BORDER_COLOR = "#DCCEB5"

    REPORT_TYPES = [
        "Violations by Zone",
        "Violations by Risk Level",
        "Violations by PPE",
        "Repeated Offenders",
    ]

    LEVEL_TYPES = ["All", "Low", "Medium", "High"]

    def __init__(self, parent, controller, user: Optional[dict] = None, **_):
        super().__init__(parent, controller, title="Reports", active_key="reports")
        self.controller = controller
        apply_theme(self)

        # Apply AddAdmin-like overrides to this page
        self._apply_page_theme_overrides()
        self._init_styles()

        # state
        self._bg_thread: Optional[threading.Thread] = None
        self._stop = False
        self._rows: List[VRow] = []        # raw events in range
        self._zones_map: Dict[str, Dict[str, Any]] = {}  # zone_id -> {name, level}
        self._zone_names: List[str] = []
        self._zname_to_id: Dict[str, str] = {}

        # PPE combo state (checkboxes)
        self.ppe_vars: Dict[str, tk.BooleanVar] = {}

        # build UI
        self._build(self.content)
        self.after(50, self._prime)

    # ───── AddAdmin-style theme overrides
    def _apply_page_theme_overrides(self):
        try:
            self.configure(bg=self.PAGE_BG)
            if hasattr(self, "content") and isinstance(self.content, tk.Frame):
                self.content.configure(bg=self.PAGE_BG)
        except Exception:
            pass
        self.option_add("*Background", self.PAGE_BG)
        self.option_add("*Foreground", self.TEXT_FG)
        self.option_add("*highlightBackground", self.PAGE_BG)
        self.option_add("*insertBackground", self.TEXT_FG)
        self.option_add("*troughColor", self.PAGE_BG)
        self.option_add("*selectBackground", "#2563eb")
        self.option_add("*selectForeground", "#FFFFFF")

    # ───── styles
    def _init_styles(self):
        style = ttk.Style(self)

        style.configure(
            "Modern.TButton",
            font=("Segoe UI Semibold", 10),
            background=self.ACCENT,
            foreground="white",
            padding=(14, 6),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Modern.TButton",
            background=[("active", self.ACCENT_HOVER)],
            relief=[("pressed", "sunken")],
        )

        style.configure(
            "Muted.TLabel",
            foreground="#333333",
            background=self.CARD_BG,
            font=FONTS.get("body", ("Segoe UI", 10)),
        )

        style.configure(
            "Admin.TCombobox",
            fieldbackground=self.CARD_BG,
            background=self.CARD_BG,
            foreground=self.TEXT_FG,
        )
        style.map(
            "Admin.TCombobox",
            fieldbackground=[("readonly", self.CARD_BG)],
            foreground=[("readonly", self.TEXT_FG)],
        )

        style.configure(
            "Admin.Treeview",
            background=self.CARD_BG,
            fieldbackground=self.CARD_BG,
            foreground=self.TEXT_FG,
            rowheight=28,
            borderwidth=0,
        )
        style.configure(
            "Admin.Treeview.Heading",
            font=FONTS.get("h6", ("Segoe UI Semibold", 10)),
            foreground=self.TEXT_FG,
            background=self.CARD_BG,
            borderwidth=0,
        )
        style.map(
            "Admin.Treeview",
            foreground=[("selected", "#000000")],
            background=[("selected", "#D7CBB8")],
        )

    def _make_entry(self, parent) -> tk.Entry:
        e = tk.Entry(
            parent,
            bg=self.ENTRY_BG,
            fg=self.TEXT_FG,
            insertbackground=self.TEXT_FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#CBBFA7",
            highlightcolor="#0096C7",
            font=FONTS.get("body", ("Segoe UI", 10)),
        )
        e.bind("<FocusIn>", lambda _e: e.configure(bg="#FFFFFF"))
        e.bind("<FocusOut>", lambda _e: e.configure(bg=self.ENTRY_BG))
        return e

    def _make_combo(self, parent, values: List[str]) -> ttk.Combobox:
        cb = ttk.Combobox(parent, values=values, state="readonly", style="Admin.TCombobox")
        cb.configure(font=FONTS.get("body", ("Segoe UI", 10)))
        return cb

    def _reset_ppe_checks(self) -> None:
        for v in self.ppe_vars.values():
            v.set(False)

    def _get_selected_ppe(self) -> List[str]:
        order = ["helmet", "vest", "gloves", "boots"]
        out: List[str] = []
        for key in order:
            var = self.ppe_vars.get(key)
            if var and var.get():
                out.append(key)
        return out

    def _selected_ppe_label_for_pdf(self) -> str:
        sel = self._get_selected_ppe()
        if not sel:
            return "all"
        return "+".join(sel)

    def _build(self, root: tk.Frame):
        header = tk.Frame(root, bg=self.PAGE_BG)
        header.pack(fill="x", padx=16, pady=(10, 6))
        tk.Label(
            header,
            text="Reports",
            font=FONTS.get("h2", ("Segoe UI Semibold", 18)),
            bg=self.PAGE_BG,
            fg="#222222",
        ).pack(anchor="w")

        # Filter card
        c, inner = card(
            root,
            fg=self.CARD_BG,
            border_color=self.BORDER_COLOR,
            border_width=2,
            pad=(16, 16),
        )
        c.pack(fill="x", padx=16, pady=(2, 10))
        c.configure(fg_color=self.CARD_BG)
        for i in range(6):
            inner.grid_columnconfigure(i, weight=1)

        def _label(parent, text, r, c):
            lbl = tk.Label(
                parent,
                text=text,
                font=("Segoe UI", 10, "bold"),
                bg=self.CARD_BG,
                fg="#333333",
            )
            lbl.grid(row=r, column=c, sticky="w")
            return lbl

        # Report type
        _label(inner, "Report Type", 0, 0)
        self.type_combo = self._make_combo(inner, self.REPORT_TYPES)
        self.type_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.type_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_type_change())

        # Date range
        _label(inner, "From (YYYY-MM-DD)", 0, 1)
        from_wrap = tk.Frame(inner, bg=self.CARD_BG)
        from_wrap.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(0, 8))
        from_wrap.grid_columnconfigure(0, weight=1)
        self.from_entry = self._make_entry(from_wrap)
        self.from_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            from_wrap,
            text="📅",
            width=3,
            style="Modern.TButton",
            command=lambda: self._open_calendar(self.from_entry),
        ).grid(row=0, column=1, padx=(6, 0))

        _label(inner, "To (YYYY-MM-DD)", 0, 2)
        to_wrap = tk.Frame(inner, bg=self.CARD_BG)
        to_wrap.grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=(0, 8))
        to_wrap.grid_columnconfigure(0, weight=1)
        self.to_entry = self._make_entry(to_wrap)
        self.to_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            to_wrap,
            text="📅",
            width=3,
            style="Modern.TButton",
            command=lambda: self._open_calendar(self.to_entry),
        ).grid(row=0, column=1, padx=(6, 0))

        # zone dropdown
        self.zone_wrap = tk.Frame(inner, bg=self.CARD_BG)
        _label(self.zone_wrap, "Zone", 0, 0)
        self.zone_combo = self._make_combo(self.zone_wrap, ["All"])
        self.zone_combo.grid(row=1, column=0, sticky="ew")

        # level dropdown
        self.level_wrap = tk.Frame(inner, bg=self.CARD_BG)
        _label(self.level_wrap, "Risk Level", 0, 0)
        self.level_combo = self._make_combo(self.level_wrap, self.LEVEL_TYPES)
        self.level_combo.grid(row=1, column=0, sticky="ew")

        # PPE combination checkboxes
        self.ppe_wrap = tk.Frame(inner, bg=self.CARD_BG)
        _label(self.ppe_wrap, "PPE (select combination)", 0, 0)
        ppe_checks = tk.Frame(self.ppe_wrap, bg=self.CARD_BG)
        ppe_checks.grid(row=1, column=0, sticky="w")

        # vars
        self.ppe_vars = {
            "helmet": tk.BooleanVar(value=False),
            "vest": tk.BooleanVar(value=False),
            "gloves": tk.BooleanVar(value=False),
            "boots": tk.BooleanVar(value=False),
        }

        def _mk_chk(txt: str, key: str):
            return tk.Checkbutton(
                ppe_checks,
                text=txt,
                variable=self.ppe_vars[key],
                onvalue=True,
                offvalue=False,
                bg=self.CARD_BG,
                fg=self.TEXT_FG,
                activebackground=self.CARD_BG,
                activeforeground=self.TEXT_FG,
                selectcolor=self.CARD_BG,
                font=FONTS.get("body", ("Segoe UI", 10)),
                highlightthickness=0,
                bd=0,
                padx=6,
                pady=2,
                cursor="hand2",
            )

        _mk_chk("Helmet", "helmet").pack(side="left")
        _mk_chk("Vest", "vest").pack(side="left")
        _mk_chk("Gloves", "gloves").pack(side="left")
        _mk_chk("Boots", "boots").pack(side="left")

        # Presets
        presets = tk.Frame(inner, bg=self.CARD_BG)
        presets.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(
            presets,
            text="Today",
            style="Modern.TButton",
            command=lambda: self._set_preset(0),
        ).pack(side="left")
        ttk.Button(
            presets,
            text="Last 7 days",
            style="Modern.TButton",
            command=lambda: self._set_preset(7),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            presets,
            text="This month",
            style="Modern.TButton",
            command=self._preset_month,
        ).pack(side="left", padx=(8, 0))

        # Actions
        actions = tk.Frame(inner, bg=self.CARD_BG)
        actions.grid(row=2, column=5, sticky="e")
        ttk.Button(
            actions,
            text="Preview",
            style="Modern.TButton",
            command=self._preview_async,
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Export CSV",
            style="Modern.TButton",
            command=self._export_csv,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            actions,
            text="Export PDF",
            style="Modern.TButton",
            command=self._export_pdf,
        ).pack(side="left", padx=(8, 0))

        # Status line
        self.status = tk.Label(
            inner,
            text="",
            bg=self.CARD_BG,
            fg=self.TEXT_FG,
            font=FONTS.get("body", ("Segoe UI", 10)),
        )
        self.status.grid(row=3, column=0, columnspan=6, sticky="w", pady=(8, 0))

        # Summary + preview cards
        sc, sin = card(
            root,
            fg=self.CARD_BG,
            border_color=self.BORDER_COLOR,
            border_width=2,
            pad=(16, 12),
        )
        sc.pack(fill="x", padx=16, pady=(2, 10))
        tk.Label(
            sin,
            text="Summary",
            font=FONTS.get("h3", ("Segoe UI Semibold", 14)),
            bg=self.CARD_BG,
            fg="#222222",
        ).pack(anchor="w")
        self.summary_lbl = tk.Label(
            sin,
            text="",
            bg=self.CARD_BG,
            fg="#333333",
            font=FONTS.get("body", ("Segoe UI", 10)),
        )
        self.summary_lbl.pack(anchor="w", pady=(2, 2))

        tc, tin = card(
            root,
            fg=self.CARD_BG,
            border_color=self.BORDER_COLOR,
            border_width=2,
            pad=(16, 12),
        )
        tc.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        top = tk.Frame(tin, bg=self.CARD_BG)
        top.pack(fill="x", pady=(0, 6))
        tk.Label(
            top,
            text="Preview",
            font=FONTS.get("h3", ("Segoe UI Semibold", 14)),
            bg=self.CARD_BG,
            fg="#222222",
        ).pack(side="left")

        # Treeview
        container = tk.Frame(tin, bg=self.CARD_BG)
        container.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            container,
            columns=(),
            show="headings",
            height=18,
            style="Admin.Treeview",
        )
        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        try:
            self.tree.tag_configure("zebra", background="#E9DCC9")
        except Exception:
            pass

    def _open_calendar(self, target_entry: tk.Entry):
        init = _s(target_entry.get())
        MiniCalendar(
            self,
            init,
            on_pick=lambda ds: (
                target_entry.delete(0, "end"),
                target_entry.insert(0, ds),
            ),
        )

    def _prime(self):
        """Load zones for current company and set defaults."""
        try:
            user = require_user()
        except Exception:
            user = {}
        cid = _company_id_from(user) or ""
        self._populate_zones(cid)

        self.type_combo.set(self.REPORT_TYPES[0])
        self._set_preset(7)  # last 7 days
        self.zone_combo.set("All")
        self.level_combo.set("All")
        self._reset_ppe_checks()
        self._on_type_change()

    def _populate_zones(self, cid: str):
        """Only Live Monitor zones (exclude 'Entry' zones)."""
        self._zones_map.clear()
        self._zname_to_id.clear()
        self._zone_names = []
        try:
            zones = list_zones(cid) or []
        except Exception:
            zones = []
        for z in zones:
            if _zone_is_entry(z):
                continue
            zid = _s(z.get("id") or z.get("zone_id") or z.get("doc_id"))
            zname = _s(
                z.get("name")
                or z.get("display_name")
                or z.get("code")
                or zid
                or "Zone"
            )
            zlevel = _level_key(
                _s(
                    z.get("risk_level")
                    or z.get("level")
                    or z.get("severity")
                    or ""
                )
            )

            self._zones_map[zid] = {"id": zid, "name": zname, "level": zlevel}
            self._zname_to_id[zname] = zid
            self._zone_names.append(zname)
        self.zone_combo["values"] = ["All"] + self._zone_names

    # presets
    def _set_preset(self, days: int):
        now = _dt.date.today()
        start = now if days == 0 else now - _dt.timedelta(days=days-1)
        self.from_entry.delete(0, "end")
        self.from_entry.insert(0, start.strftime("%Y-%m-%d"))
        self.to_entry.delete(0, "end")
        self.to_entry.insert(0, now.strftime("%Y-%m-%d"))

    def _preset_month(self):
        now = _dt.date.today()
        start = _dt.date(now.year, now.month, 1)
        end = (
            _dt.date(now.year+1, 1, 1)
            if now.month == 12
            else _dt.date(now.year, now.month+1, 1)
        ) - _dt.timedelta(days=1)
        self.from_entry.delete(0, "end")
        self.from_entry.insert(0, start.strftime("%Y-%m-%d"))
        self.to_entry.delete(0, "end")
        self.to_entry.insert(0, end.strftime("%Y-%m-%d"))

    def _parse_date(self, s: str) -> Optional[_dt.date]:
        try:
            if not s:
                return None
            y, m, d = map(int, s.split("-"))
            return _dt.date(y, m, d)
        except Exception:
            return None

    def _on_type_change(self):
        """Show only 1 filter dropdown based on report type and rebuild preview columns."""
        for f in (self.zone_wrap, self.level_wrap, self.ppe_wrap):
            f.grid_forget()
        t = self.type_combo.get()
        if t == "Violations by Zone":
            self.zone_wrap.grid(
                row=1,
                column=3,
                sticky="ew",
                padx=(8, 8),
                pady=(0, 8),
            )
        elif t == "Violations by Risk Level":
            self.level_wrap.grid(
                row=1,
                column=3,
                sticky="ew",
                padx=(8, 8),
                pady=(0, 8),
            )
        elif t == "Violations by PPE":
            self.ppe_wrap.grid(
                row=1,
                column=3,
                sticky="w",
                padx=(8, 8),
                pady=(0, 8),
            )
        self._setup_tree_columns([])  # clear until preview

    def _any_missing_offender_name(self, rows: List[VRow]) -> bool:
        return any(not _s(r.offender_name) for r in rows)

    def _preview_async(self):
        if (
            hasattr(self, "_bg_thread")
            and self._bg_thread
            and self._bg_thread.is_alive()
        ):
            return
        dfrom = self._parse_date(self.from_entry.get())
        dto = self._parse_date(self.to_entry.get())
        if not dfrom or not dto:
            messagebox.showerror(
                "Reports",
                "Please enter a valid date range (YYYY-MM-DD).",
            )
            return
        t0 = _dt.datetime(dfrom.year, dfrom.month, dfrom.day)
        t1 = _dt.datetime(dto.year, dto.month, dto.day) + _dt.timedelta(days=1)

        rtype = self.type_combo.get()
        zone_sel = (self.zone_combo.get() or "All")
        level_sel = (self.level_combo.get() or "All")
        ppe_selected_list = self._get_selected_ppe()

        self.status.config(text="Loading…")
        self._rows.clear()
        for r in self.tree.get_children():
            self.tree.delete(r)
        self.summary_lbl.config(text="")

        def _work():
            try:
                user = require_user()
            except Exception:
                user = {}
            cid = _company_id_from(user)
            db = get_db()
            if not (db and cid):
                return []
            keys = _company_keys(cid)

            # gather violations for all key forms of company_id
            seen: Dict[str, Any] = {}
            for k in keys:
                try:
                    q = db.collection("violations").where("company_id", "==", k)
                    rows = list(q.stream())
                except Exception:
                    rows = []
                for s in rows:
                    seen[s.id] = s

            out: List[VRow] = []
            for s in seen.values():
                d = s.to_dict() or {}
                ts = d.get("ts") or d.get("time") or d.get("created_at")
                ts_s = _safe_epoch_s(ts)
                if ts_s is None:
                    continue
                if not (t0.timestamp() <= ts_s < t1.timestamp()):
                    continue

                zid = _s(d.get("zone_id") or "")
                # skip zones that are entry-only
                zmeta = self._zones_map.get(zid)
                if zmeta is None and zid:
                    continue

                zname = _s(
                    d.get("zone_name")
                    or (zmeta["name"] if zmeta else zid)
                )
                lvl = _level_key(
                    _s(d.get("risk_level") or d.get("severity") or "")
                ) or (zmeta["level"] if zmeta else "")
                camera = _s(
                    d.get("camera_name") or d.get("camera_id") or ""
                )
                risk_t = _s(
                    d.get("risk")
                    or d.get("type")
                    or d.get("ppe_type")
                    or d.get("severity")
                    or ""
                )
                oname = _s(d.get("offender_name") or "")
                oid = _s(d.get("offender_id") or "")
                out.append(
                    VRow(
                        id=s.id,
                        ts=ts,
                        zone_id=zid,
                        zone_name=zname,
                        zone_level=lvl,
                        camera=camera,
                        risk_text=risk_t,
                        offender_name=oname,
                        offender_id=oid,
                    )
                )
            out.sort(
                key=lambda r: _safe_epoch_s(r.ts) or 0.0,
                reverse=True,
            )
            return out

        def _done(res):
            if isinstance(res, Exception):
                self.status.config(text="")
                messagebox.showerror("Reports", f"Load failed: {res}")
                return
            self._rows = res

            # block preview if any worker missing
            if self._any_missing_offender_name(self._rows):
                self.status.config(text="")
                messagebox.showerror(
                    "Reports",
                    "Some violations in this date range are missing the worker's name.\n\n"
                    "Please fill in every offender's name in the Logs page, then try again."
                )
                return

            if rtype == "Repeated Offenders":
                prepared = self._prepare_repeated_offenders(res)
                columns = [
                    ("Offender ID", 120),
                    ("Name", 180),
                    ("Violations", 110),
                    ("Violation Types", 360),
                    ("Last Seen", 170),
                    ("Top Zone", 200),
                ]
                self._setup_tree_columns(
                    [(c[0].lower().replace(" ","_"), c[1]) for c in columns]
                )
                self._setup_tree_headings([c[0] for c in columns])
                for i, p in enumerate(prepared):
                    iid = self.tree.insert(
                        "",
                        "end",
                        values=(
                            p["offender_id"],
                            p["offender_name"],
                            p["count"],
                            p["violations_list"],
                            p["last_seen"],
                            p["top_zone"],
                        ),
                    )
                    if i % 2 == 0:
                        self.tree.item(iid, tags=("zebra",))
                summary_text = self._summary_repeated_offenders(prepared)
            else:
                if rtype == "Violations by Zone":
                    columns = [
                        ("Timestamp",170),
                        ("Zone",220),
                        ("Violation",420),
                        ("Offender",220),
                    ]
                    schema = [
                        ("ts",170),
                        ("zone",220),
                        ("violation",420),
                        ("offender",220),
                    ]
                elif rtype == "Violations by Risk Level":
                    columns = [
                        ("Timestamp",170),
                        ("Zone Level",140),
                        ("Zone",240),
                        ("Violation",420),
                    ]
                    schema = [
                        ("ts",170),
                        ("level",140),
                        ("zone",240),
                        ("violation",420),
                    ]
                else:  # PPE
                    columns = [
                        ("Timestamp",170),
                        ("PPE Violation",320),
                        ("Zone",260),
                        ("Offender",220),
                    ]
                    schema = [
                        ("ts",170),
                        ("ppe_violation",320),
                        ("zone",260),
                        ("offender",220),
                    ]

                self._setup_tree_columns(schema)
                self._setup_tree_headings([c[0] for c in columns])

                filtered = self._filter_events(
                    res,
                    rtype,
                    zone_sel,
                    level_sel,
                    ppe_selected_list,
                )
                if rtype == "Violations by Zone":
                    for i, r in enumerate(filtered):
                        iid = self.tree.insert(
                            "",
                            "end",
                            values=(
                                _ts_to_str(r.ts),
                                r.zone_name or "—",
                                _risk_human(r.risk_text),
                                self._offender_display(r),
                            ),
                        )
                        if i % 2 == 0:
                            self.tree.item(iid, tags=("zebra",))
                    summary_text = self._summary_by_zone(filtered)

                elif rtype == "Violations by Risk Level":
                    lvlmap = {
                        "high":"High",
                        "medium":"Medium",
                        "low":"Low",
                        "":"—",
                    }
                    for i, r in enumerate(filtered):
                        iid = self.tree.insert(
                            "",
                            "end",
                            values=(
                                _ts_to_str(r.ts),
                                lvlmap.get(r.zone_level, "—"),
                                r.zone_name or "—",
                                _risk_human(r.risk_text),
                            ),
                        )
                        if i % 2 == 0:
                            self.tree.item(iid, tags=("zebra",))
                    summary_text = self._summary_by_level(
                        filtered,
                        level_sel,
                    )

                else:  # PPE combo
                    for i, r in enumerate(filtered):
                        iid = self.tree.insert(
                            "",
                            "end",
                            values=(
                                _ts_to_str(r.ts),
                                _risk_human(r.risk_text),
                                r.zone_name or "—",
                                self._offender_display(r),
                            ),
                        )
                        if i % 2 == 0:
                            self.tree.item(iid, tags=("zebra",))
                    summary_text = self._summary_by_ppe(
                        filtered,
                        ppe_selected_list,
                    )

            self.summary_lbl.config(text=summary_text)
            self.status.config(text="Preview ready")

        self._bg_thread = threading.Thread(
            target=lambda: self._bridge(_work, _done),
            daemon=True,
        )
        self._bg_thread.start()

    def _setup_tree_headings(self, labels: List[str]):
        cols = list(self.tree["columns"])
        for key, label in zip(cols, labels):
            self.tree.heading(key, text=label, anchor="center")
            self.tree.column(key, anchor="center")

    def _bridge(self, work_fn, done_fn):
        try:
            out = work_fn()
        except Exception as e:
            out = e
        if not self._stop and self.winfo_exists():
            try:
                self.after(
                    0,
                    lambda: (self.winfo_exists() and done_fn(out)),
                )
            except Exception:
                pass

    def _setup_tree_columns(self, schema: List[Tuple[str, int]]):
        cols = [k for k,_ in schema]
        self.tree["columns"] = cols
        for c in self.tree.get_children():
            self.tree.delete(c)
        for key, w in schema:
            self.tree.heading(key, text=key.title(), anchor="center")
            self.tree.column(key, width=w, anchor="center", stretch=True)

    def _filter_events(
        self,
        rows: List[VRow],
        rtype: str,
        zone_sel: str,
        level_sel: str,
        ppe_selected: List[str],
    ) -> List[VRow]:

        out: List[VRow] = []
        zone_sel = (zone_sel or "All")
        level_sel_lc = (level_sel or "All").lower()

        sel_zid = self._zname_to_id.get(zone_sel, "")

        for r in rows:
            if rtype == "Violations by Zone":
                if (
                    zone_sel != "All"
                    and r.zone_name != zone_sel
                    and r.zone_id != sel_zid
                ):
                    continue

            elif rtype == "Violations by Risk Level":
                if level_sel_lc != "all" and r.zone_level != level_sel_lc:
                    continue

            elif rtype == "Violations by PPE":
                tokens = _risk_tokens(r.risk_text)
                missing_list = [k for k, v in tokens.items() if v]

                if not ppe_selected:
                    if not missing_list:
                        continue
                else:
                    if len(missing_list) != len(ppe_selected):
                        continue
                    ok = True
                    for need in ppe_selected:
                        if need not in missing_list:
                            ok = False
                            break
                    if not ok:
                        continue

            out.append(r)
        return out

    def _offender_display(self, r: VRow) -> str:
        if r.offender_name and r.offender_id:
            return f"{r.offender_name} ({r.offender_id})"
        return r.offender_name or r.offender_id or "—"

    def _summary_by_zone(self, rows: List[VRow]) -> str:
        total = len(rows)
        if total == 0:
            return "No violations for selected zone/date."
        ppe = {"helmet":0,"vest":0,"gloves":0,"boots":0}
        by_day: Dict[str,int] = {}
        for r in rows:
            toks = _risk_tokens(r.risk_text)
            for k in ppe:
                ppe[k] += 1 if toks.get(k, False) else 0
            ds = _ts_to_str(r.ts)[:10]
            by_day[ds] = by_day.get(ds,0) + 1
        top_ppe = ", ".join(
            f"{k.title()} ({v})"
            for k,v in sorted(
                ppe.items(),
                key=lambda x:x[1],
                reverse=True,
            )
            if v>0
        ) or "—"
        peak_day = (
            max(by_day.items(), key=lambda x:x[1])[0]
            if by_day
            else "—"
        )
        return (
            f"Total violations: {total}\n"
            f"Top PPE: {top_ppe}\n"
            f"Peak day: {peak_day}"
        )

    def _summary_by_level(
        self,
        rows: List[VRow],
        level_sel: Optional[str] = "All",
    ) -> str:
        total = len(rows)
        if total == 0:
            return "No violations for selected level/date."
        by_zone: Dict[str,int] = {}
        for r in rows:
            by_zone[r.zone_name or "—"] = by_zone.get(
                r.zone_name or "—",
                0,
            ) + 1
        top_zone = (
            max(by_zone.items(), key=lambda x:x[1])[0]
            if by_zone
            else "—"
        )
        lvl_disp = (level_sel or "All").capitalize()
        if lvl_disp.lower() == "all":
            return (
                f"Total violations (all levels): {total}\n"
                f"Top zone: {top_zone}"
            )
        return (
            f"Total {lvl_disp} level violations: {total}\n"
            f"Top zone: {top_zone}"
        )

    def _summary_by_ppe(
        self,
        rows: List[VRow],
        ppe_selected: List[str],
    ) -> str:
        total = len(rows)
        if total == 0:
            return "No PPE violations for selection."

        label_map = {
            "helmet": "Helmet",
            "vest": "Vest",
            "gloves": "Gloves",
            "boots": "Boots",
        }

        if not ppe_selected:
            by_ppe = {"helmet":0,"vest":0,"gloves":0,"boots":0}
            for r in rows:
                toks = _risk_tokens(r.risk_text)
                for k in by_ppe:
                    by_ppe[k] += 1 if toks.get(k, False) else 0
            line = ", ".join(
                f"{label_map.get(k,k.title())} ({v})"
                for k,v in by_ppe.items()
                if v>0
            ) or "—"
            return (
                f"Total PPE violations: {total}\n"
                f"Breakdown: {line}"
            )

        by_zone: Dict[str,int] = {}
        for r in rows:
            by_zone[r.zone_name or "—"] = by_zone.get(
                r.zone_name or "—",
                0,
            ) + 1
        top_zone = (
            max(by_zone.items(), key=lambda x:x[1])[0]
            if by_zone
            else "—"
        )

        combo_text = " + ".join(
            label_map.get(p, p.title())
            for p in ppe_selected
        )
        return (
            f"Total {combo_text} violations: {total}\n"
            f"Top zone: {top_zone}"
        )

    def _prepare_repeated_offenders(
        self,
        rows: List[VRow],
    ) -> List[Dict[str, Any]]:
        agg: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            key = (
                r.offender_id
                or (("name:" + r.offender_name) if r.offender_name else "unknown")
            )
            a = agg.setdefault(
                key,
                {
                    "count":0,
                    "last":0.0,
                    "zones":{},
                    "ppe":{"helmet":0,"vest":0,"gloves":0,"boots":0},
                    "names":{},
                },
            )
            a["count"] += 1
            ts = _safe_epoch_s(r.ts) or 0.0
            if ts > a["last"]:
                a["last"] = ts
            zn = r.zone_name or "—"
            a["zones"][zn] = a["zones"].get(zn, 0) + 1
            toks = _risk_tokens(r.risk_text)
            for k in ("helmet","vest","gloves","boots"):
                if toks.get(k, False):
                    a["ppe"][k] += 1
            nm = (r.offender_name or "").strip()
            if nm:
                a["names"][nm] = a["names"].get(nm, 0) + 1

        out: List[Dict[str, Any]] = []
        for k, a in agg.items():
            best_name = (
                max(a["names"].items(), key=lambda x:x[1])[0]
                if a["names"]
                else ""
            )
            if k.startswith("name:"):
                offender_id = ""
                offender_name = k[5:] or best_name or "Unknown"
            elif k == "unknown":
                offender_id = ""
                offender_name = best_name or "Unknown"
            else:
                offender_id = k
                offender_name = best_name or ""
            top_zone = (
                max(a["zones"].items(), key=lambda x:x[1])[0]
                if a["zones"]
                else "—"
            )
            ppe_counts = a["ppe"]
            ordered = [
                (label, ppe_counts[key2])
                for label, key2 in (
                    ("Helmet","helmet"),
                    ("Vest","vest"),
                    ("Gloves","gloves"),
                    ("Boots","boots"),
                )
            ]
            ordered = [(lab,cnt) for lab,cnt in ordered if cnt > 0]
            violations_list = (
                ", ".join(
                    f"{lab} ({cnt})"
                    for lab,cnt in sorted(
                        ordered,
                        key=lambda x:x[1],
                        reverse=True,
                    )
                )
                or "—"
            )
            out.append(
                {
                    "offender_id": offender_id or "—",
                    "offender_name": offender_name or "—",
                    "count": a["count"],
                    "violations_list": violations_list,
                    "last_seen": _dt.datetime.fromtimestamp(
                        a["last"]
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    if a["last"]
                    else "—",
                    "top_zone": top_zone,
                }
            )
        out.sort(key=lambda x: x["count"], reverse=True)
        return out

    def _summary_repeated_offenders(
        self,
        prepared: List[Dict[str, Any]],
    ) -> str:
        if not prepared:
            return "No offenders in range."
        top = prepared[0]
        label = (
            top["offender_name"]
            if top.get("offender_name") and top["offender_name"] != "—"
            else top.get("offender_id","—")
        )
        return (
            f"Unique offenders: {len(prepared)}\n"
            f"Top offender: {label} ({top['count']} violations)"
        )

    # CSV / PDF exports respect the same validation
    def _export_csv(self):
        if self._any_missing_offender_name(self._rows):
            messagebox.showerror(
                "Export CSV",
                "Some violations are missing the worker's name.\n\n"
                "Please fill in every offender's name in the Logs page, then try again.",
            )
            return

        rtype = self.type_combo.get()
        data, columns = self._current_view_data_and_columns()
        if not data:
            messagebox.showinfo("Export CSV", "Run a Preview first.")
            return

        path = filedialog.asksaveasfilename(
            title="Save CSV",
            defaultextension=".csv",
            filetypes=[("CSV files","*.csv")],
            initialfile=self._suggest_filename(ext="csv", rtype=rtype),
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([c[0] for c in columns])  # headers
                for row in data:
                    w.writerow(row)
            messagebox.showinfo("Export CSV", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export CSV", str(e))

    def _export_pdf(self):
        if self._any_missing_offender_name(self._rows):
            messagebox.showerror(
                "Export PDF",
                "Some violations are missing the worker's name.\n\n"
                "Please fill in every offender's name in the Logs page, then try again.",
            )
            return

        rtype = self.type_combo.get()
        data, columns = self._current_view_data_and_columns()
        if not data:
            messagebox.showinfo("Export PDF", "Run a Preview first.")
            return
        if not _HAVE_RL:
            messagebox.showerror(
                "Export PDF",
                "Missing dependency: reportlab\n\nInstall with:\n  pip install reportlab",
            )
            return

        path = filedialog.asksaveasfilename(
            title="Save PDF",
            defaultextension=".pdf",
            filetypes=[("PDF files","*.pdf")],
            initialfile=self._suggest_filename(ext="pdf", rtype=rtype),
        )
        if not path:
            return

        summary_text = self.summary_lbl.cget("text")
        selected_filters = {
            "ppe_sel": self._selected_ppe_label_for_pdf(),
            "level_sel": (self.level_combo.get() or "All"),
        }

        try:
            self._write_pdf(
                path,
                rtype,
                data,
                columns,
                summary_text,
                selected_filters,
            )
            messagebox.showinfo("Export PDF", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export PDF", str(e))

    def _suggest_filename(
        self,
        ext="pdf",
        rtype: Optional[str] = None,
    ) -> str:
        r = rtype or self.type_combo.get() or "Report"
        r = r.replace(" ", "")
        f = (
            self.from_entry.get() or "from"
        ) + "_" + (self.to_entry.get() or "to")
        return f"Report_{r}_{f}.{ext}"

    def _current_view_data_and_columns(
        self,
    ) -> Tuple[List[List[str]], List[Tuple[str,int]]]:
        cols = list(self.tree["columns"])
        headers_widths = [
            (
                self.tree.heading(c, option="text"),
                self.tree.column(c, option="width"),
            )
            for c in cols
        ]
        rows: List[List[str]] = []
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, "values")
            rows.append(list(vals))
        return rows, headers_widths

    def _write_pdf(
        self,
        path: str,
        rtype: str,
        rows: List[List[str]],
        columns: List[Tuple[str,int]],
        summary_text: str,
        selected_filters: Optional[Dict[str,str]] = None,
    ):
        from reportlab.pdfbase import pdfmetrics  # type: ignore
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas as _rl_canvas
        from reportlab.lib.utils import ImageReader

        page_w, page_h = A4
        c = _rl_canvas.Canvas(path, pagesize=A4)

        # Header
        try:
            user = require_user()
        except Exception:
            user = {}
        company = _s(user.get("company_name") or "") or "Company"
        admin = _s(user.get("email") or "")

        def header():
            c.setFont("Helvetica-Bold", 14)
            c.setFillColorRGB(0.10, 0.12, 0.18)
            c.drawString(
                2*cm,
                page_h-2*cm,
                f"{company} — {rtype}",
            )
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(0.25, 0.28, 0.35)
            c.drawString(
                2*cm,
                page_h-2.6*cm,
                f"Generated: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            )
            c.drawString(
                10*cm,
                page_h-2.6*cm,
                f"By: {admin}",
            )
            c.setStrokeColorRGB(0.86,0.90,0.98)
            c.line(
                2*cm,
                page_h-2.9*cm,
                page_w-2*cm,
                page_h-2.9*cm,
            )

        def summary_block(y: float) -> float:
            c.setFont("Helvetica-Bold", 11)
            c.setFillColorRGB(0.12, 0.16, 0.24)
            c.drawString(2*cm, y, "Summary")
            c.setFont("Helvetica", 10)
            c.setFillColorRGB(0.15, 0.17, 0.22)
            y -= 0.4*cm
            for ln in summary_text.splitlines():
                c.drawString(2*cm, y, ln)
                y -= 0.45*cm
            return y - 0.2*cm

        def charts_block(y: float) -> float:
            if not _HAVE_MPL or not rows:
                return y
            ppe_sel = ((selected_filters or {}).get("ppe_sel") or "all").lower()
            level_sel = ((selected_filters or {}).get("level_sel") or "all").lower()
            try:
                if rtype == "Violations by Zone":
                    idx = [
                        i
                        for i,(h,_)
                        in enumerate(columns)
                        if h.lower().startswith("zone")
                    ]
                    if not idx:
                        return y
                    zi = idx[0]
                    counts: Dict[str,int] = {}
                    for r in rows:
                        z = r[zi] or "—"
                        counts[z] = counts.get(z,0)+1
                    data = sorted(
                        counts.items(),
                        key=lambda x:x[1],
                        reverse=True,
                    )[:6]
                    title = "Violations by Zone (Top 6)"

                elif rtype == "Violations by Risk Level":
                    if level_sel == "all":
                        idx = [
                            i
                            for i,(h,_)
                            in enumerate(columns)
                            if h.lower().startswith("zone level")
                        ]
                        if not idx:
                            return y
                        li = idx[0]
                        counts: Dict[str,int] = {}
                        for r in rows:
                            lv = r[li] or "—"
                            counts[lv] = counts.get(lv,0)+1
                        data = [
                            ("Low", counts.get("Low",0)),
                            ("Medium", counts.get("Medium",0)),
                            ("High", counts.get("High",0)),
                        ]
                        title = "Violations by Risk Level"
                    else:
                        idx = [
                            i
                            for i,(h,_)
                            in enumerate(columns)
                            if h.lower().startswith("zone")
                        ]
                        if not idx:
                            return y
                        zi = idx[0]
                        counts = {}
                        for r in rows:
                            z = r[zi] or "—"
                            counts[z] = counts.get(z,0)+1
                        data = sorted(
                            counts.items(),
                            key=lambda x:x[1],
                            reverse=True,
                        )[:8]
                        pretty = {
                            "low":"Low",
                            "medium":"Medium",
                            "high":"High",
                        }.get(level_sel, level_sel.title())
                        title = f"{pretty} Level Violations by Zone"

                elif rtype == "Violations by PPE":
                    if ppe_sel == "all":
                        idx = [
                            i
                            for i,(h,_)
                            in enumerate(columns)
                            if "PPE" in h
                        ]
                        if not idx:
                            return y
                        pi = idx[0]
                        counts = {
                            "Helmet":0,
                            "Vest":0,
                            "Gloves":0,
                            "Boots":0,
                        }
                        for r in rows:
                            txt = (r[pi] or "").lower()
                            for k in list(counts.keys()):
                                if k.lower() in txt:
                                    counts[k]+=1
                        data = sorted(
                            counts.items(),
                            key=lambda x:x[1],
                            reverse=True,
                        )
                        title = "PPE Violations"
                    else:
                        zi = next(
                            (
                                i
                                for i,(h,_)
                                in enumerate(columns)
                                if h.lower().startswith("zone")
                            ),
                            None,
                        )
                        if zi is None:
                            return y
                        counts: Dict[str,int] = {}
                        for r in rows:
                            z = r[zi] or "—"
                            counts[z] = counts.get(z,0) + 1
                        data = sorted(
                            counts.items(),
                            key=lambda x:x[1],
                            reverse=True,
                        )[:8]

                        label_map = {
                            "helmet": "Helmet",
                            "vest": "Vest",
                            "gloves": "Gloves",
                            "boots": "Boots",
                        }
                        parts = [
                            label_map.get(p.strip(), p.strip().title())
                            for p in ppe_sel.split("+")
                        ]
                        pretty = " + ".join(parts)
                        title = f"{pretty} Violations by Zone"

                elif rtype == "Repeated Offenders":
                    # indices for columns
                    name_i = next(
                        (
                            i
                            for i,(h,_)
                            in enumerate(columns)
                            if h.lower().startswith("name")
                        ),
                        None,
                    )
                    id_i = next(
                        (
                            i
                            for i,(h,_)
                            in enumerate(columns)
                            if h.lower().startswith("offender id")
                        ),
                        None,
                    )
                    cnt_i = next(
                        (
                            i
                            for i,(h,_)
                            in enumerate(columns)
                            if h.lower().startswith("violations")
                        ),
                        None,
                    )
                    if cnt_i is None or (name_i is None and id_i is None):
                        return y

                    # Build ( "Name (ID)" , count ) pairs
                    pairs = []
                    for r in rows:
                        try:
                            nm = (
                                r[name_i]
                                if name_i is not None and r[name_i]
                                else ""
                            )
                            oid = (
                                r[id_i]
                                if id_i is not None and r[id_i]
                                else ""
                            )
                            # final label logic:
                            if nm and oid and oid != "—":
                                label = f"{nm} ({oid})"
                            elif nm:
                                label = nm
                            else:
                                label = oid
                            pairs.append((label, int(r[cnt_i])))
                        except Exception:
                            pass

                    data = sorted(
                        pairs,
                        key=lambda x:x[1],
                        reverse=True,
                    )[:6]
                    title = "Top Offenders"

                else:
                    return y

                if not data:
                    return y

                # draw bar chart with our improved labels
                x = 2*cm
                w = page_w - 4*cm
                h_img = 6*cm
                fig, ax = plt.subplots(figsize=(w/96, h_img/96), dpi=96)
                labels = [k for k,_ in data]
                values = [v for _,v in data]
                ax.bar(range(len(values)), values)
                ax.set_xticks(range(len(values)))
                ax.set_xticklabels(labels, rotation=25, ha="right")
                ax.set_title(title)
                ax.grid(True, axis="y", linestyle="--", alpha=0.3)
                fig.tight_layout()
                buf = io.BytesIO()
                fig.savefig(buf, format="png", bbox_inches="tight")
                plt.close(fig)
                buf.seek(0)
                img = ImageReader(buf)
                if y - h_img < 4*cm:
                    c.showPage()
                    header()
                    y = page_h - 3.2*cm
                c.drawImage(
                    img,
                    x,
                    y - h_img,
                    width=w,
                    height=h_img,
                    preserveAspectRatio=True,
                    mask='auto',
                )
                y -= (h_img + 0.4*cm)

            except Exception:
                pass
            return y

        def wrap_text(
            text: str,
            font_name: str,
            font_size: float,
            max_width_pts: float,
        ) -> List[str]:
            words = (text or "").split()
            if not words:
                return [""]
            lines: List[str] = []
            cur = words[0]
            for w in words[1:]:
                trial = cur + " " + w
                wpx = pdfmetrics.stringWidth(
                    trial,
                    font_name,
                    font_size,
                )
                if wpx <= max_width_pts:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = w
            lines.append(cur)
            return lines

        def draw_cell(
            x: float,
            y: float,
            wcol: float,
            text: str,
            font_name="Helvetica",
            font_size=9,
        ) -> float:
            c.setFont(font_name, font_size)
            lines = []
            for ln in (text or "").splitlines() or [""]:
                lines.extend(
                    wrap_text(
                        ln,
                        font_name,
                        font_size,
                        wcol - 6,
                    )
                )
            line_h = font_size * 1.2
            used = 0.0
            for ln in lines:
                c.drawString(x, y - used, ln)
                used += line_h
            return used

        def table_block(y: float):
            base_defs = [
                (h, max(2.4*cm, 3.0*cm))
                for h,_ in columns
            ]

            x0 = 2*cm
            y0 = y
            c.setFillColorRGB(0.91, 0.96, 1.0)
            total_w = sum(w for _, w in base_defs)
            c.rect(
                x0,
                y0-0.45*cm,
                total_w,
                0.6*cm,
                stroke=0,
                fill=1,
            )
            c.setFillColorRGB(0.10, 0.12, 0.18)
            c.setFont("Helvetica-Bold", 10)
            x = x0
            for name, wcol in base_defs:
                c.drawString(x+3, y0-0.15*cm, name)
                x += wcol
            y = y0 - 0.8*cm

            font_name = "Helvetica"; font_size = 9
            row_gap = 0.15*cm
            max_rows = 2000
            shown = 0
            for idx, r in enumerate(rows):
                heights = []
                for (name, wcol), val in zip(base_defs, r):
                    lines = []
                    for ln in (str(val) if val is not None else "").splitlines() or [""]:
                        lines.extend(
                            wrap_text(
                                ln,
                                font_name,
                                font_size,
                                wcol - 6,
                            )
                        )
                    heights.append(
                        len(lines) * (font_size * 1.2)
                    )
                row_h = max(heights) + row_gap

                if y - row_h < 3*cm:
                    c.showPage()
                    header()
                    y = page_h - 3.2*cm
                    x = x0
                    c.setFillColorRGB(0.91, 0.96, 1.0)
                    c.rect(
                        x0,
                        y-0.45*cm,
                        total_w,
                        0.6*cm,
                        stroke=0,
                        fill=1,
                    )
                    c.setFillColorRGB(0.10, 0.12, 0.18)
                    c.setFont("Helvetica-Bold", 10)
                    for name, wcol in base_defs:
                        c.drawString(x+3, y-0.15*cm, name)
                        x += wcol
                    y -= 0.8*cm

                if idx % 2 == 0:
                    c.setFillColorRGB(0.98, 0.99, 1.0)
                    c.rect(
                        x0,
                        y - row_h + row_gap/2,
                        total_w,
                        row_h,
                        stroke=0,
                        fill=1,
                    )

                c.setFillColorRGB(0.13, 0.15, 0.20)
                x = x0
                for (name, wcol), val in zip(base_defs, r):
                    draw_cell(
                        x+3,
                        y - (font_size*1.0),
                        wcol-6,
                        str(val) if val is not None else "",
                        font_name,
                        font_size,
                    )
                    x += wcol
                y -= row_h
                shown += 1
                if shown >= max_rows:
                    c.setFont("Helvetica-Oblique", 9)
                    c.setFillColorRGB(0.25, 0.28, 0.35)
                    c.drawString(
                        2*cm,
                        y,
                        f"(Showing first {max_rows} rows. Export CSV for full dataset.)",
                    )
                    y -= 0.4*cm
                    break

        # Render PDF
        header()
        y = page_h - 3.2*cm
        y = summary_block(y)
        y = charts_block(y)
        table_block(y)
        c.save()

    def destroy(self):
        self._stop = True
        try:
            if self._bg_thread and self._bg_thread.is_alive():
                self._bg_thread.join(timeout=0.5)
        except Exception:
            pass
        super().destroy()
