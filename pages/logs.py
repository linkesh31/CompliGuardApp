# pages/logs.py
import io
import base64
import threading
import datetime as _dt
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Any, Dict, List, Optional
from PIL import Image, ImageTk

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.session import require_user
from services.firebase_client import get_db

# Worker lookups
from services.workers import (
    find_worker_by_exact_name,
    find_workers_by_name,
)

# Violations + WhatsApp messaging
from services.violations import record_offender_on_violation
from services.messaging import prepare_and_send_whatsapp

# ───────── helpers ─────────
def _s(v: Any) -> str:
    return ("" if v is None else str(v)).strip()


def _company_keys(company_id_any: Any) -> List[Any]:
    keys: List[Any] = []
    s = _s(company_id_any)
    if s:
        keys.append(s)
        if s.isdigit():
            try:
                keys.append(int(s))
            except Exception:
                pass
    if isinstance(company_id_any, int) and company_id_any not in keys:
        keys.append(company_id_any)
    return keys


def _human_ts(ts_val: Any) -> str:
    try:
        if isinstance(ts_val, (int, float)):
            v = float(ts_val)
            if v > 1e12:  # ms
                v /= 1000.0
            return _dt.datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(ts_val, "timestamp"):
            return _human_ts(ts_val.timestamp() * 1000.0)
        if hasattr(ts_val, "strftime"):
            return ts_val.strftime("%Y-%m-%d %H:%M:%S")  # type: ignore[attr-defined]
    except Exception:
        pass
    return _s(ts_val)


def _as_epoch_ms(ts_val: Any) -> Optional[int]:
    try:
        if isinstance(ts_val, (int, float)):
            v = float(ts_val)
            return int(v if v > 1e12 else v * 1000.0)
        if hasattr(ts_val, "timestamp"):
            return int(ts_val.timestamp() * 1000.0)
        if hasattr(ts_val, "timetuple"):
            return int(_dt.datetime(*ts_val.timetuple()[:6]).timestamp() * 1000.0)  # type: ignore
    except Exception:
        return None
    return None


def _risk_tokens(v: str) -> Dict[str, bool]:
    t = _s(v).lower()
    return {
        "helmet": ("helmet" in t or "hardhat" in t or "hard_hat" in t),
        "vest": ("vest" in t or "safety_vest" in t or "safety vest" in t),
        "gloves": ("glove" in t or "gloves" in t or "hand_glove" in t),
        "boots": ("boot" in t or "boots" in t or "shoe" in t or "shoes" in t or "safety_shoe" in t),
    }


def _risk_human(v: str) -> str:
    t = _s(v).lower()
    if not t:
        return "—"
    flags = _risk_tokens(t)
    names = []
    if flags["helmet"]:
        names.append("Helmet")
    if flags["vest"]:
        names.append("Vest")
    if flags["gloves"]:
        names.append("Gloves")
    if flags["boots"]:
        names.append("Boots")
    if names:
        return f"{', '.join(names)} Missing"
    if "high" in t or t == "3":
        return "High"
    if "med" in t or t == "2":
        return "Medium"
    if "low" in t or t == "1":
        return "Low"
    return v or "—"


def _level_key(v: str) -> str:
    t = _s(v).lower()
    if t in ("3", "high", "critical", "severe"):
        return "high"
    if t in ("2", "med", "medium"):
        return "medium"
    if t in ("1", "low"):
        return "low"
    return ""


def _image_from_b64(s: str) -> Optional[Image.Image]:
    try:
        raw = base64.b64decode(s)
        return Image.open(io.BytesIO(raw))
    except Exception:
        return None


def _ts_for_sort(d: Dict[str, Any]) -> float:
    ts = d.get("ts") or d.get("time") or d.get("created_at")
    ems = _as_epoch_ms(ts)
    return (ems / 1000.0) if ems is not None else 0.0


# ───────── tiny calendar ─────────
class MiniCalendar(tk.Toplevel):
    def __init__(self, parent, initial: Optional[str], on_pick):
        super().__init__(parent)
        self.title("Pick a date")
        self.configure(bg=PALETTE.get("card", "#ffffff"))
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
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
            m, y = 12, y - 1
        elif m > 12:
            m, y = 1, y + 1
        self.cur_year, self.cur_month = y, m
        self._render()

    def _render(self):
        for w in self.grid.winfo_children():
            w.destroy()
        import calendar as _cal
        self.title_lbl.config(text=f"{_cal.month_name[self.cur_month]} {self.cur_year}")
        for i, wd in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            ttk.Label(self.grid, text=wd, width=3, anchor="center").grid(row=0, column=i, padx=2, pady=2)
        cal = _cal.Calendar(firstweekday=0)
        row = 1
        for week in cal.monthdayscalendar(self.cur_year, self.cur_month):
            for col, day in enumerate(week):
                if day == 0:
                    tk.Label(
                        self.grid,
                        text="",
                        width=3,
                        bg=PALETTE.get("card", "#fff")
                    ).grid(row=row, column=col, padx=1, pady=1)
                else:
                    ttk.Button(
                        self.grid,
                        text=str(day).rjust(2),
                        width=3,
                        command=lambda d=day: self._pick(d)
                    ).grid(row=row, column=col, padx=1, pady=1)
            row += 1

    def _pick(self, day: int):
        ds = f"{self.cur_year:04d}-{self.cur_month:02d}-{day:02d}"
        try:
            self.on_pick(ds)
        finally:
            self.destroy()


# ───────── LogsPage ─────────
class LogsPage(tk.Frame):
    # Match AddAdmin page theme
    PAGE_BG = "#E6D8C3"
    TEXT_FG = "#000000"
    CARD_BG = "#EFE3D0"

    def __init__(self, parent, controller, *_, **__):
        super().__init__(parent, bg=self.PAGE_BG)
        self.controller = controller
        apply_theme(self)

        # styles to match Add Admin
        self._apply_page_theme_overrides()
        self._init_styles()

        # state
        self._bg_thread: Optional[threading.Thread] = None
        self._stop_flag = False
        self._snaps_cache: List[Any] = []
        self._rowmap: Dict[str, Any] = {}
        self._zone_meta: Dict[str, Dict[str, Any]] = {}
        self._zone_name_to_id: Dict[str, str] = {}

        # filters
        self.risk_var = tk.StringVar(value="All")
        self.level_var = tk.StringVar(value="All")
        self.zone_var = tk.StringVar(value="All")
        self.date_from_var = tk.StringVar(value="")
        self.date_to_var = tk.StringVar(value="")

        # widgets that we assign later
        self.tree: ttk.Treeview
        self.status_lbl: ttk.Label
        self._xscroll: ttk.Scrollbar
        self._yscroll: ttk.Scrollbar
        self.zone_combo: ttk.Combobox

        # build + load
        self._build(self)
        self._refresh_async()

    # ---- theming like Add Admin ----
    def _apply_page_theme_overrides(self):
        self.option_add("*Background", self.PAGE_BG)
        self.option_add("*Foreground", self.TEXT_FG)
        self.option_add("*highlightBackground", self.PAGE_BG)
        self.option_add("*insertBackground", self.TEXT_FG)
        self.option_add("*troughColor", self.PAGE_BG)
        # global defaults for selection (Treeview overrides separately)
        self.option_add("*selectBackground", "#2563eb")
        self.option_add("*selectForeground", "#FFFFFF")

    def _init_styles(self):
        try:
            ttk.Style().theme_use("clam")
        except Exception:
            pass

        self.style = ttk.Style(self)
        accent = "#0077b6"
        hover = "#00b4d8"

        # Buttons
        self.style.configure(
            "Modern.TButton",
            font=("Segoe UI Semibold", 10),
            background=accent,
            foreground="white",
            padding=(14, 6),
            borderwidth=0,
            relief="flat",
        )
        self.style.map(
            "Modern.TButton",
            background=[("active", hover), ("!disabled", accent)],
            foreground=[("!disabled", "white")],
            relief=[("pressed", "sunken")],
        )

        # Alias style (same look)
        self.style.configure(
            "Primary.TButton",
            background=accent,
            foreground="white",
            padding=(14, 6),
            borderwidth=0,
            relief="flat",
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", hover), ("!disabled", accent)],
            foreground=[("!disabled", "white")],
        )

        # Labels inside beige card
        self.style.configure(
            "Muted.TLabel",
            background=self.CARD_BG,
            foreground="#333333",
            font=("Segoe UI", 10),
        )

        # Combobox — force white bg / black text
        self.style.configure(
            "Modern.TCombobox",
            fieldbackground="#FFFFFF",
            background="#FFFFFF",
            foreground="#000000",
            borderwidth=0,
            padding=4,
        )
        self.style.map(
            "Modern.TCombobox",
            fieldbackground=[
                ("readonly", "#FFFFFF"),
                ("focus", "#FFFFFF"),
                ("!disabled", "#FFFFFF"),
            ],
            background=[
                ("readonly", "#FFFFFF"),
                ("focus", "#FFFFFF"),
                ("!disabled", "#FFFFFF"),
            ],
            foreground=[
                ("readonly", "#000000"),
                ("focus", "#000000"),
                ("!disabled", "#000000"),
            ],
            selectbackground=[
                ("readonly", "#FFFFFF"),
                ("focus", "#FFFFFF"),
                ("!disabled", "#FFFFFF"),
            ],
            selectforeground=[
                ("readonly", "#000000"),
                ("focus", "#000000"),
                ("!disabled", "#000000"),
            ],
        )

        # Treeview base
        self.style.configure(
            "Logs.Treeview",
            background=self.CARD_BG,
            fieldbackground=self.CARD_BG,
            foreground=self.TEXT_FG,
            rowheight=28,
            borderwidth=0,
        )
        self.style.configure(
            "Logs.Treeview.Heading",
            font=FONTS.get("h6", ("Segoe UI Semibold", 10)),
            foreground=self.TEXT_FG,
            background=self.CARD_BG,
        )
        # selection colors (keep readable)
        self.style.map(
            "Logs.Treeview",
            foreground=[("selected", "#000000")],
            background=[("selected", "#D7CBB8")],
        )

    # ---- build UI ----
    def _build(self, root: tk.Frame):
        # Header card
        hc, hin = card(
            root,
            fg=self.CARD_BG,
            border_color="#DCCEB5",
            border_width=2,
            pad=(16, 10),
        )
        hc.pack(fill="x", pady=(6, 6), padx=16)
        hc.configure(fg_color=self.CARD_BG)
        tk.Label(
            hin,
            text="Logs",
            font=("Segoe UI Semibold", 18),
            bg=self.CARD_BG,
            fg="#222222",
        ).pack(anchor="w")

        # Toolbar card
        tbar, inner = card(
            root,
            fg=self.CARD_BG,
            border_color="#DCCEB5",
            border_width=2,
            pad=(16, 12),
        )
        tbar.pack(fill="x", pady=(4, 8), padx=16)
        tbar.configure(fg_color=self.CARD_BG)
        tb = inner

        # LEFT filter cluster
        left = tk.Frame(tb, bg=self.CARD_BG)
        left.pack(side="left", fill="x", expand=True)

        ttk.Label(left, text="Risk", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        risk = ttk.Combobox(
            left,
            textvariable=self.risk_var,
            state="readonly",
            width=18,
            style="Modern.TCombobox",
            values=[
                "All",
                "Helmet Missing",
                "Vest Missing",
                "Gloves Missing",
                "Boots Missing",
                "Multiple Missing",
            ],
        )
        risk.pack(side="left")
        risk.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())

        ttk.Label(left, text="  Level", style="Muted.TLabel").pack(side="left", padx=(12, 8))
        level = ttk.Combobox(
            left,
            textvariable=self.level_var,
            state="readonly",
            width=12,
            style="Modern.TCombobox",
            values=["All", "High", "Medium", "Low"],
        )
        level.pack(side="left")
        level.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())

        ttk.Label(left, text="  Zone", style="Muted.TLabel").pack(side="left", padx=(12, 8))
        self.zone_combo = ttk.Combobox(
            left,
            textvariable=self.zone_var,
            state="readonly",
            width=18,
            style="Modern.TCombobox",
            values=["All"],
        )
        self.zone_combo.pack(side="left")
        self.zone_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())

        ttk.Label(left, text="  From", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        self.from_entry = ttk.Entry(left, textvariable=self.date_from_var, width=11)
        self.from_entry.pack(side="left")
        ttk.Button(
            left,
            text="📅",
            width=3,
            style="Modern.TButton",
            command=lambda: self._open_calendar(self.from_entry),
        ).pack(side="left", padx=(2, 0))

        ttk.Label(left, text="  To", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        self.to_entry = ttk.Entry(left, textvariable=self.date_to_var, width=11)
        self.to_entry.pack(side="left")
        ttk.Button(
            left,
            text="📅",
            width=3,
            style="Modern.TButton",
            command=lambda: self._open_calendar(self.to_entry),
        ).pack(side="left", padx=(2, 0))

        # RIGHT side (status + Apply + Refresh)
        right = tk.Frame(tb, bg=self.CARD_BG)
        right.pack(side="right")

        # status label FIRST so it sits to the left of the buttons, not behind them
        self.status_lbl = ttk.Label(right, text="", style="Muted.TLabel")
        self.status_lbl.pack(side="left", padx=(0, 12))

        ttk.Button(
            right,
            text="Apply",
            style="Modern.TButton",
            command=self._apply_filters,
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            right,
            text="Refresh",
            style="Modern.TButton",
            command=self._refresh_async,
        ).pack(side="left")

        # Table card
        c, inner_tbl = card(
            root,
            fg=self.CARD_BG,
            border_color="#DCCEB5",
            border_width=2,
        )
        c.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        c.configure(fg_color=self.CARD_BG)

        tree_wrap = tk.Frame(inner_tbl, bg=self.CARD_BG)
        tree_wrap.pack(fill="both", expand=True)

        self.cols = (
            "rowno",
            "ts",
            "camera",
            "zone",
            "zone_level",
            "risk",
            "offender",
            "action",
            "snapshot",
            "delete",
        )
        headers = (
            "ID",
            "Timestamp",
            "Camera",
            "Zone",
            "Zone Level",
            "Risk",
            "Offender",
            "Action",
            "Snapshot",
            "Delete",
        )

        # scrollbars
        self._yscroll = ttk.Scrollbar(tree_wrap, orient="vertical")
        self._xscroll = ttk.Scrollbar(tree_wrap, orient="horizontal")

        self.tree = ttk.Treeview(
            tree_wrap,
            columns=self.cols,
            show="headings",
            height=12,
            style="Logs.Treeview",
            yscrollcommand=self._yscroll.set,
            xscrollcommand=self._xscroll.set,
        )
        self._yscroll.config(command=self.tree.yview)
        self._xscroll.config(command=self.tree.xview)

        widths = (60, 160, 120, 130, 120, 260, 180, 140, 110, 90)
        for name, head, w in zip(self.cols, headers, widths):
            self.tree.heading(name, text=head, anchor="center")
            self.tree.column(name, width=w, anchor="center", stretch=False)

        # layout table + scrollbars
        self.tree.grid(row=0, column=0, sticky="nsew")
        self._yscroll.grid(row=0, column=1, sticky="ns")
        self._xscroll.grid(row=1, column=0, sticky="ew")
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)

        # zebra alt row bg
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("odd", background="#f9fafb")

        # interactions
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-1>", self._on_single_click)

        # context menu (right click)
        self._ctx = tk.Menu(self, tearoff=0)
        self._ctx.add_command(label="Preview Snapshot", command=self._preview_selected)
        self._ctx.add_command(label="Identify Offender (by name)", command=self._identify_offender)
        self._ctx.add_command(label="Delete", command=self._delete_selected)
        self.tree.bind("<Button-3>", self._show_ctx)

    # ---- async load from Firestore ----
    def _refresh_async(self):
        # clear table first
        for r in self.tree.get_children():
            self.tree.delete(r)
        self._rowmap.clear()
        self.status_lbl.config(text="Loading…")

        try:
            user = require_user()
        except Exception as e:
            self.status_lbl.config(text="")
            messagebox.showerror("Error", f"No session: {e}")
            return

        company_doc_id = _s(user.get("company_id") or "")
        if not company_doc_id:
            self.status_lbl.config(text="")
            messagebox.showerror("Error", "Missing company id for current user.")
            return

        keys = _company_keys(company_doc_id)

        def _work():
            try:
                db = get_db()

                # fetch violations (dedupe across int/str company_id)
                coll_v = db.collection("violations")
                snaps = []
                for k in keys:
                    snaps.extend(list(coll_v.where("company_id", "==", k).stream()))
                seen = {}
                vio_unique = []
                for s in snaps:
                    if s.id not in seen:
                        seen[s.id] = True
                        vio_unique.append(s)
                vio_unique.sort(
                    key=lambda s: _ts_for_sort(s.to_dict() or {}),
                    reverse=True
                )

                # fetch zones metadata
                coll_z = db.collection("zones")
                zsnaps = []
                for k in keys:
                    zsnaps.extend(list(coll_z.where("company_id", "==", k).stream()))
                zone_meta: Dict[str, Dict[str, Any]] = {}
                name_to_id: Dict[str, str] = {}
                for z in zsnaps:
                    zd = z.to_dict() or {}
                    zid = z.id
                    zname = _s(
                        zd.get("name")
                        or zd.get("display_name")
                        or zd.get("code")
                        or zid
                    )
                    zlevel = _level_key(
                        _s(zd.get("risk_level") or zd.get("level") or zd.get("severity") or "")
                    )
                    zone_meta[zid] = {"id": zid, "name": zname, "level": zlevel}
                    name_to_id[_s(zname).lower()] = zid

                return (vio_unique, zone_meta, name_to_id)

            except Exception as e:
                return e

        def _done(result):
            if isinstance(result, Exception):
                self.status_lbl.config(text="")
                messagebox.showerror("Error", f"Failed to load logs: {result}")
                return

            vio_unique, zone_meta, name_to_id = result
            self._snaps_cache = vio_unique
            self._zone_meta = zone_meta
            self._zone_name_to_id = name_to_id

            # update Zone filter dropdown
            zones = ["All"]
            seen_z = set()
            for s in self._snaps_cache:
                d = s.to_dict() or {}
                zname = _s(d.get("zone_name") or d.get("zone_id") or "")
                zid = d.get("zone_id")
                if zid and zid in self._zone_meta:
                    zname = self._zone_meta[zid]["name"]
                if zname and zname not in seen_z:
                    seen_z.add(zname)
                    zones.append(zname)
            self.zone_combo["values"] = zones
            if self.zone_var.get() not in zones:
                self.zone_var.set("All")

            # apply current filters to table
            self._apply_filters()
            self.status_lbl.config(text=f"{len(self._snaps_cache)} records")

        self._bg_thread = threading.Thread(
            target=lambda: self._thread_bridge(_work, _done),
            daemon=True,
        )
        self._bg_thread.start()

    def _thread_bridge(self, work_fn, done_fn):
        res = work_fn()
        if not self._stop_flag:
            try:
                self.after(0, lambda: done_fn(res))
            except Exception:
                pass

    # ---- filtering / table ----
    def _parse_date(self, s: str) -> Optional[_dt.date]:
        try:
            if not s:
                return None
            y, m, d = map(int, s.split("-"))
            return _dt.date(y, m, d)
        except Exception:
            return None

    def _zone_level_for(self, zone_id: Optional[str], zone_name: str) -> str:
        if zone_id and zone_id in self._zone_meta:
            return self._zone_meta[zone_id].get("level") or ""
        key = _s(zone_name).lower()
        zid = self._zone_name_to_id.get(key)
        if zid and zid in self._zone_meta:
            return self._zone_meta[zid].get("level") or ""
        return ""

    def _apply_filters(self):
        rf = _s(self.risk_var.get()).lower()
        lf = _s(self.level_var.get()).lower()
        zone_f = _s(self.zone_var.get())

        d_from = self._parse_date(self.date_from_var.get())
        d_to = self._parse_date(self.date_to_var.get())
        from_ms = int(_dt.datetime(d_from.year, d_from.month, d_from.day).timestamp() * 1000) if d_from else None
        to_ms = int((_dt.datetime(d_to.year, d_to.month, d_to.day) + _dt.timedelta(days=1)).timestamp() * 1000) if d_to else None

        filtered: List[Any] = []
        for s in self._snaps_cache:
            d = s.to_dict() or {}
            zone_id = _s(d.get("zone_id") or "")
            zone_name = _s(d.get("zone_name") or zone_id)
            risk_raw = _s(d.get("risk") or d.get("risk_level") or d.get("severity") or "")
            flags = _risk_tokens(risk_raw)
            missing_count = sum(1 for on in flags.values() if on)

            # date range filter
            ts_ms = _as_epoch_ms(d.get("ts") or d.get("time") or d.get("created_at"))
            if from_ms is not None and (ts_ms is None or ts_ms < from_ms):
                continue
            if to_ms is not None and (ts_ms is None or ts_ms >= to_ms):
                continue

            # zone filter
            zdisplay = zone_name
            if zone_id and zone_id in self._zone_meta:
                zdisplay = self._zone_meta[zone_id]["name"]
            if zone_f and zone_f != "All" and zdisplay != zone_f:
                continue

            # risk filter (strict single-PPE match rule)
            if rf in ("helmet missing", "vest missing", "gloves missing", "boots missing"):
                key = rf.split()[0]
                if not (flags.get(key, False) and missing_count == 1):
                    continue
            elif rf == "multiple missing":
                if missing_count < 2:
                    continue

            # level filter
            v_level = _level_key(_s(d.get("risk_level") or d.get("severity") or ""))
            if not v_level:
                v_level = self._zone_level_for(zone_id, zone_name)
            if lf in ("high", "medium", "low") and v_level != lf:
                continue

            d["_display_zone"] = zdisplay
            d["_display_level"] = v_level
            filtered.append(s)

        self._populate_table(filtered)
        self.status_lbl.config(text=f"{len(filtered)} shown / {len(self._snaps_cache)} total")

    def _populate_table(self, snaps: List[Any]):
        # clear table
        for r in self.tree.get_children():
            self.tree.delete(r)
        self._rowmap.clear()

        for idx, s in enumerate(snaps, start=1):
            d = s.to_dict() or {}

            ts_str = _human_ts(d.get("ts") or d.get("time") or d.get("created_at"))
            risk_txt = _risk_human(_s(d.get("risk") or d.get("risk_level") or d.get("severity")))

            zone_id = _s(d.get("zone_id") or "")
            zdisplay = d.get("_display_zone") or _s(d.get("zone_name") or zone_id)
            if zone_id and zone_id in self._zone_meta:
                zdisplay = self._zone_meta[zone_id]["name"]

            v_level = d.get("_display_level") or self._zone_level_for(zone_id, zdisplay)
            if v_level == "high":
                level_badge = "🔴 High"
            elif v_level == "medium":
                level_badge = "🟠 Medium"
            elif v_level == "low":
                level_badge = "🟡 Low"
            else:
                level_badge = "—"

            offender_name = _s(d.get("offender_name") or "")
            offender_id = _s(d.get("offender_id") or "")
            offender_display = (
                f"{offender_name} ({offender_id})"
                if offender_name and offender_id
                else (offender_name or offender_id or "—")
            )

            action_cell = (
                "🟢 Identify"
                if not (offender_name or offender_id)
                else "🔵 Edit (by name)"
            )

            has_snap = bool(
                d.get("has_snapshot")
                or d.get("snapshot_b64")
                or d.get("snapshot")
                or d.get("image_path")
            )
            snap_cell = "🔍 Preview" if has_snap else "—"

            vals = (
                f"{idx:03d}",
                ts_str,
                _s(d.get("camera_name") or d.get("camera_id") or ""),
                zdisplay,
                level_badge,
                risk_txt,
                offender_display,
                action_cell,
                snap_cell,
                "🗑 Delete",
            )
            tag = "odd" if (idx % 2) else "even"
            item_id = self.tree.insert("", "end", values=vals, tags=(tag,))
            self._rowmap[item_id] = s

    # ---- interactions/actions ----
    def _open_calendar(self, target_entry: ttk.Entry):
        init = _s(target_entry.get())
        MiniCalendar(
            self,
            init,
            on_pick=lambda ds: (
                target_entry.delete(0, "end"),
                target_entry.insert(0, ds),
                self._apply_filters(),
            ),
        )

    def _selected_snapshot(self) -> Optional[Any]:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._rowmap.get(sel[0])

    def _on_double_click(self, _event=None):
        self._preview_selected()

    def _on_single_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.tree.identify_column(event.x)  # '#1'..'#10'
        row = self.tree.identify_row(event.y)
        if not row:
            return
        try:
            self.tree.selection_set(row)
        except Exception:
            pass
        vals = self.tree.item(row, "values")
        if not vals:
            return
        if column == "#8":              # Action col
            self._identify_offender()
        elif column == "#9":            # Snapshot col
            if str(vals[8]).lower().startswith("🔍") or "preview" in str(vals[8]).lower():
                self._preview_selected()
        elif column == "#10":           # Delete col
            self._delete_selected()

    def _preview_selected(self):
        s = self._selected_snapshot()
        if not s:
            messagebox.showinfo("Preview", "Select a row first.")
            return
        d = s.to_dict() or {}
        img: Optional[Image.Image] = None
        if d.get("snapshot_b64"):
            img = _image_from_b64(_s(d.get("snapshot_b64")))
        if img is None:
            messagebox.showinfo("Preview", "No snapshot image available for this record.")
            return

        top = tk.Toplevel(self)
        top.title("Snapshot")
        top.configure(bg="#000000")
        img.thumbnail((1220, 820))
        photo = ImageTk.PhotoImage(img)
        lbl = tk.Label(top, image=photo, bg="#000000")
        lbl.image = photo
        lbl.pack(padx=8, pady=8)

    def _delete_selected(self):
        s = self._selected_snapshot()
        if not s:
            messagebox.showinfo("Delete", "Select a row first.")
            return
        if not messagebox.askyesno("Delete Violation", "Delete this record permanently?"):
            return

        try:
            db = get_db()
            db.collection("violations").document(s.id).delete()
        except Exception as e:
            messagebox.showerror("Delete Failed", f"Could not delete:\n{e}")
            return

        sel = self.tree.selection()
        if sel:
            self.tree.delete(sel[0])
            self._rowmap.pop(sel[0], None)
        self._snaps_cache = [snap for snap in self._snaps_cache if snap.id != s.id]
        self.status_lbl.config(text=f"{len(self._snaps_cache)} records")
        messagebox.showinfo("Deleted", "Record deleted.")

    # --- offender identification (by NAME ONLY, then WhatsApp notify) ---
    def _identify_offender(self):
        """
        Flow when user clicks Identify:
          1. Ask for worker name
          2. Find worker in Firestore
          3. Save offender_id/offender_name into that violation via record_offender_on_violation()
          4. Count strikes
          5. Auto-open WhatsApp Web with prefilled message to that worker's phone
        """
        s = self._selected_snapshot()
        if not s:
            messagebox.showinfo("Identify Offender", "Select a row first.")
            return
        d = s.to_dict() or {}

        # initial value in dialog
        init = _s(d.get("offender_name") or "")
        entered = simpledialog.askstring(
            "Identify Offender",
            "Worker name (type to search):",
            initialvalue=init,
            parent=self,
        )
        if entered is None:
            return
        name_q = _s(entered)
        if not name_q:
            messagebox.showerror("Identify Offender", "Name cannot be empty.")
            return

        # figure out company context (id + name)
        company_id = getattr(self.controller, "current_company_id", None)
        company_name = getattr(self.controller, "current_company_name", None)

        try:
            user = require_user()
        except Exception:
            user = {}

        if not company_id:
            company_id = user.get("company_id")

        if not company_name:
            company_name = (
                user.get("company_name")
                or user.get("company")
                or user.get("org_name")
                or user.get("site_name")
                or user.get("site")
                or ""
            )

        if not company_id:
            messagebox.showerror("Identify Offender", "No company context available.")
            return
        if not company_name:
            messagebox.showerror("Identify Offender", "No company name found.")
            return

        # find worker by that name
        worker = find_worker_by_exact_name(company_id, name_q, active_only=False)
        if worker is None:
            candidates = find_workers_by_name(company_id, name_q, active_only=False)
            if len(candidates) == 0:
                messagebox.showerror("Identify Offender", f"Worker name not found: “{name_q}”.")
                return
            if len(candidates) > 1:
                picked = self._pick_worker_dialog(candidates)
                if not picked:
                    return
                worker = picked
            else:
                worker = candidates[0]

        # persist offender info + compute strike count
        violation_after, strike_count, err = record_offender_on_violation(
            violation_id=s.id,
            worker=worker,
            company_id=company_id,
        )
        if err:
            messagebox.showerror("Update Failed", f"Could not save details:\n{err}")
            return

        # ⬇⬇⬇ NEW: enrich with zone risk level so WhatsApp message always has it
        if violation_after is None:
            violation_after = {}
        # carry over existing zone info from table row snapshot if missing
        vio_zone_id = _s(violation_after.get("zone_id") or d.get("zone_id"))
        vio_zone_name = _s(violation_after.get("zone_name") or d.get("zone_name") or vio_zone_id)
        # compute level using our cached zone metadata
        zone_level_key = self._zone_level_for(vio_zone_id, vio_zone_name)
        if vio_zone_name and not _s(violation_after.get("zone_name")):
            violation_after["zone_name"] = vio_zone_name
        if zone_level_key:
            violation_after["zone_risk_level"] = zone_level_key
            # also put into nested zone dict for broader compatibility
            z = violation_after.get("zone")
            if not isinstance(z, dict):
                z = {}
            z["risk_level"] = zone_level_key
            violation_after["zone"] = z

        # attempt WhatsApp open
        if strike_count is not None:
            result = prepare_and_send_whatsapp(
                violation=violation_after,
                strike_count=strike_count,
                company_name=_s(company_name),
            )
        else:
            result = {
                "ok": False,
                "phone_used": _s(worker.get("phone")),
                "link": "",
                "message": "",
            }

        # update table row text to reflect new offender in UI
        sel = self.tree.selection()
        if sel:
            vals = list(self.tree.item(sel[0], "values"))
            vals[6] = f"{_s(worker['name'])} ({_s(worker['worker_id'])})"
            vals[7] = "🔵 Edit (by name)"
            self.tree.item(sel[0], values=tuple(vals))

        # tell user what happened (also shows phone/URL debug)
        phone_used = result.get("phone_used", "") or "N/A"
        if result.get("ok"):
            msg = (
                "Offender identified and violation updated.\n\n"
                f"WhatsApp chat opened to {phone_used}.\n"
                "Message is pre-filled. Please confirm and press Send in WhatsApp."
            )
        else:
            msg = (
                "Offender identified and violation updated.\n\n"
                f"Could not automatically open WhatsApp.\n"
                f"Target phone: {phone_used}\n"
                "You may need to contact this worker manually."
            )
        messagebox.showinfo("Saved", msg)

    def _pick_worker_dialog(self, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        top = tk.Toplevel(self)
        top.title("Select Worker")
        try:
            top.resizable(False, False)
        except Exception:
            pass
        apply_theme(top)

        tk.Label(
            top,
            text="Multiple matches found. Select the worker:",
            bg=PALETTE["bg"],
        ).pack(padx=12, pady=(12, 8), anchor="w")

        lb = tk.Listbox(top, height=min(10, len(candidates)), activestyle="dotbox")
        items = [f"{w['name']}  ({w['worker_id']})" for w in candidates]
        for it in items:
            lb.insert("end", it)
        lb.pack(padx=12, pady=(0, 8), fill="x")

        chosen: Optional[Dict[str, Any]] = None

        def _ok():
            nonlocal chosen
            i = lb.curselection()
            if not i:
                messagebox.showinfo("Select Worker", "Please pick a worker from the list.")
                return
            chosen = candidates[i[0]]
            top.destroy()

        def _cancel():
            top.destroy()

        btns = tk.Frame(top, bg=PALETTE["bg"])
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="OK", style="Primary.TButton", command=_ok).pack(side="left")
        ttk.Button(btns, text="Cancel", command=_cancel).pack(side="right")

        lb.bind("<Double-1>", lambda _e: _ok())
        top.transient(self)
        top.grab_set()
        self.wait_window(top)
        return chosen

    def _show_ctx(self, event):
        try:
            self._ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx.grab_release()

    # ---- lifecycle ----
    def destroy(self):
        self._stop_flag = True
        try:
            if self._bg_thread and self._bg_thread.is_alive():
                self._bg_thread.join(timeout=0.5)
        except Exception:
            pass
        super().destroy()
