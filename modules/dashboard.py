# pages/dashboard.py
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional, Tuple
import datetime as _dt

import customtkinter as ctk

from services.ui_theme import FONTS, PALETTE, card
from services.ui_shell import PageShell
from services.session import get_current_user
from services.firebase_auth import is_superadmin

# Optional backend calls
try:
    from services.zones import list_zones
except Exception:
    def list_zones(_company_id: str) -> List[Dict[str, Any]]:
        return []

# Optional Firestore
try:
    from services.firebase_client import get_db
except Exception:
    def get_db():
        return None  # type: ignore

# Optional PIL (for future inline icons if needed)
try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


# ───────────────────────── helpers (UNCHANGED) ─────────────────────────
def _s(v: Any) -> str:
    return ("" if v is None else str(v)).strip()


def _company_id_from(user: Dict[str, Any]) -> Optional[str]:
    for k in ("company_id", "companyId", "companyID", "company"):
        if k in user and _s(user[k]):
            return _s(user[k])
    return None


def _company_name_from_user(user: Dict[str, Any]) -> Optional[str]:
    for k in ("company_name", "companyName", "company"):
        if k in user and _s(user[k]):
            return _s(user[k])
    return None


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


def _as_epoch_s(ts: Any) -> Optional[float]:
    try:
        if hasattr(ts, "to_datetime"):  # Firestore Timestamp
            return float(ts.to_datetime().timestamp())
        if hasattr(ts, "timestamp"):  # datetime
            return float(ts.timestamp())
        if isinstance(ts, (int, float)):  # epoch ms or s
            v = float(ts)
            return v / 1000.0 if v > 1e12 else v
    except Exception:
        return None
    return None


def _today_bounds() -> Tuple[float, float, str]:
    now = _dt.datetime.now()
    start = _dt.datetime(now.year, now.month, now.day)
    end = start + _dt.timedelta(days=1)
    return start.timestamp(), end.timestamp(), start.strftime("%Y-%m-%d")


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
    t = (v or "").strip().lower()
    if t in ("3", "high", "critical", "severe"):
        return "high"
    if t in ("2", "med", "medium"):
        return "medium"
    if t in ("1", "low"):
        return "low"
    return ""


# ───────────────────────── mini bars (UNCHANGED) ─────────────────────────
class _Bars(tk.Canvas):
    def __init__(self, parent, *, bg=None, height=140, **kw):
        bg = bg or PALETTE.get("card", "#161A22")
        super().__init__(parent, bg=bg, height=height, highlightthickness=0, **kw)
        self._counts = {"low": 0, "medium": 0, "high": 0}
        self.bind("<Configure>", lambda _e: self._draw())

    def set_counts(self, low: int, med: int, high: int):
        self._counts = {"low": max(0, low), "medium": max(0, med), "high": max(0, high)}
        self._draw()

    def _draw(self):
        self.delete("all")
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        pad = 16

        cats = [("Low", "low", "#d97706"), ("Medium", "medium", "#f97316"), ("High", "high", "#ef4444")]
        maxv = max(1, max(self._counts.values()) or 1)

        bar_w = (w - pad * 2) / (len(cats) * 1.6)
        gap = bar_w * 0.6
        x = pad + (w - pad * 2 - (bar_w * 3 + gap * 2)) / 2

        for label, key, color in cats:
            v = self._counts.get(key, 0)
            bh = int((h - 40) * (v / maxv))
            y0 = h - 24 - bh
            self.create_rectangle(
                x, y0, x + bar_w, h - 24,
                fill=color,
                outline=PALETTE.get("border", "#232a39")
            )
            self.create_text(x + bar_w / 2, h - 10, text=label,
                             fill=PALETTE.get("muted", "#9AA5B1"), font=("Segoe UI", 9))
            self.create_text(x + bar_w / 2, y0 - 8, text=str(v),
                             fill=PALETTE.get("text", "#E8ECF1"), font=("Segoe UI", 10, "bold"))
            x += bar_w + gap


# ───────────────────────── company helpers (UNCHANGED) ─────────────────────────
def get_company_name(company_id: Optional[str], user_fallback: Optional[str]) -> Optional[str]:
    name = _s(user_fallback or "")
    if name:
        return name
    if not company_id:
        return None
    db = get_db()
    if not db:
        return None
    try:
        snap = db.collection("companies").document(str(company_id)).get()
        if snap and snap.exists:
            d = snap.to_dict() or {}
            nm = _s(d.get("name") or d.get("display_name") or d.get("company_name") or "")
            if nm:
                return nm
    except Exception:
        pass
    for f in ("company_id", "id"):
        try:
            q = db.collection("companies").where(f, "==", company_id).limit(1).get()
            if q:
                d = q[0].to_dict() or {}
                nm = _s(d.get("name") or d.get("display_name") or d.get("company_name") or "")
                if nm:
                    return nm
        except Exception:
            pass
    return None


def get_company_suspended(company_id: Optional[str]) -> Optional[bool]:
    if not company_id:
        return None
    db = get_db()
    if not db:
        return None
    try:
        snap = db.collection("companies").document(str(company_id)).get()
        if snap and snap.exists:
            d = snap.to_dict() or {}
            status = _s(d.get("status"))
            active = d.get("active")
            suspended = d.get("suspended")
            if isinstance(suspended, bool):
                return suspended
            if isinstance(active, bool):
                return not active
            if status:
                return status.lower() in ("suspended", "inactive", "disabled")
    except Exception:
        pass
    for f in ("company_id", "id"):
        try:
            q = db.collection("companies").where(f, "==", company_id).limit(1).get()
            if q:
                d = q[0].to_dict() or {}
                status = _s(d.get("status"))
                active = d.get("active")
                suspended = d.get("suspended")
                if isinstance(suspended, bool):
                    return suspended
                if isinstance(active, bool):
                    return not active
                if status:
                    return status.lower() in ("suspended", "inactive", "disabled")
        except Exception:
            pass
    return None


# ───────────────────────── main ─────────────────────────
class Dashboard(PageShell):
    _DASH_SENTINEL = "__DASHBOARD__"

    def __init__(self, parent, controller, user: dict = None):
        super().__init__(parent, controller, title="CompliGuard — Dashboard", active_key="home")
        self.controller = controller
        self.user = user or get_current_user() or {}

        # widgets to hydrate
        self._zones_wrap: Optional[tk.Frame] = None
        self._tree: Optional[ttk.Treeview] = None
        self._vio_title_lbl: Optional[ctk.CTkLabel] = None
        self._vio_value_lbl: Optional[ctk.CTkLabel] = None
        self._vio_compliance_lbl: Optional[ctk.CTkLabel] = None
        self._bars: Optional[_Bars] = None

        # welcome row labels
        self._welcome_name_lbl: Optional[ctk.CTkLabel] = None
        self._welcome_company_lbl: Optional[ctk.CTkLabel] = None

        # suspended banner
        self._suspend_banner: Optional[ctk.CTkFrame] = None
        self._suspend_lbl: Optional[ctk.CTkLabel] = None

        # UI
        self._init_styles()
        self._build()

        # data hydrate
        self.after(80, self._start_async_hydrate)
        self._profile_bind_id = self.controller.bind(
            "<<ProfileUpdated>>",
            lambda e: self._on_profile_updated(),
            add="+",
        )
        self.bind("<Destroy>", self._cleanup_profile_binding, add="+")

    def _cleanup_profile_binding(self, _e=None):
        try:
            if getattr(self, "_profile_bind_id", None):
                self.controller.unbind("<<ProfileUpdated>>", self._profile_bind_id)
                self._profile_bind_id = None
        except Exception:
            pass

    def _init_styles(self):
        s = ttk.Style(self)
        s.configure(
            "Dash.Treeview",
            background=PALETTE["card"],
            fieldbackground=PALETTE["card"],
            foreground=PALETTE["text"],
            rowheight=28,
            borderwidth=0,
        )
        s.configure(
            "Dash.Treeview.Heading",
            font=FONTS.get("h6", ("Segoe UI Semibold", 10)),
            foreground=PALETTE["text"],
            background=PALETTE["card"],
        )
        s.map("Dash.Treeview", background=[("selected", "#2563eb")], foreground=[("selected", "#ffffff")])

    def _build(self):
        # Suspension banner
        self._suspend_banner = ctk.CTkFrame(self.content, fg_color="#3b0d0d", height=40, corner_radius=8)
        self._suspend_lbl = ctk.CTkLabel(self._suspend_banner, text="", text_color="#fca5a5",
                                         font=("Segoe UI", 11, "bold"))
        self._suspend_lbl.pack(padx=16, pady=8, anchor="w")
        self._suspend_banner.pack(fill="x", padx=16)
        self._suspend_banner.pack_forget()

        # Top row cards
        top = ctk.CTkFrame(self.content, fg_color=PALETTE["bg"])
        top.pack(fill="x", padx=16, pady=(12, 2))

        # Welcome card
        welcome_card, win = card(top, pad=(18, 16))
        welcome_card.pack(side="left", fill="x", expand=True, padx=(0, 12))

        ctk.CTkLabel(win, text="Welcome,", font=FONTS["h3"], text_color=PALETTE["muted"]).pack(anchor="w")

        who_row = ctk.CTkFrame(win, fg_color=PALETTE["card"])
        who_row.pack(anchor="w", pady=(6, 2))

        who = self.controller.current_user_email or self.user.get("email", "")
        name = (self.user.get("name") or who or "User")
        self._welcome_name_lbl = ctk.CTkLabel(
            who_row, text=_s(name), font=("Segoe UI", 20, "bold"), text_color=PALETTE["text"]
        )
        self._welcome_name_lbl.pack(side="left")

        initial_company = _company_name_from_user(self.user) or ""
        # >>> Bigger & more prominent company name
        self._welcome_company_lbl = ctk.CTkLabel(
            who_row,
            text=(f"— {initial_company}" if initial_company else ""),
            font=("Segoe UI Semibold", 22),
            text_color=PALETTE.get("primary", "#0f172a"),
        )
        self._welcome_company_lbl.pack(side="left", padx=(12, 0), pady=(2, 0))
        # <<<

        # Violations summary card
        vio_card, vio_inner = card(top, pad=(18, 14))
        vio_card.pack(side="left")

        self._vio_title_lbl = ctk.CTkLabel(
            vio_inner, text="Violations Today", font=FONTS["h3"], text_color=PALETTE["muted"]
        )
        self._vio_title_lbl.pack(anchor="w")

        self._vio_value_lbl = ctk.CTkLabel(
            vio_inner, text="0", font=("Segoe UI", 24, "bold"), text_color=PALETTE["text"]
        )
        self._vio_value_lbl.pack(anchor="w", pady=(6, 0))

        self._vio_compliance_lbl = ctk.CTkLabel(
            vio_inner, text="Compliance Today: —", font=("Segoe UI", 10, "bold"), text_color=PALETTE["text"]
        )
        self._vio_compliance_lbl.pack(anchor="w", pady=(4, 0))

        # Bottom layout
        bottom = ctk.CTkFrame(self.content, fg_color=PALETTE["bg"])
        bottom.pack(fill="both", expand=True, padx=16, pady=(12, 16))

        # Left card: Recent Violations
        left_card, left_inner = card(bottom)
        left_card.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(
            left_inner, text="Recent Violations", font=FONTS["h3"], text_color=PALETTE["text"]
        ).pack(anchor="w", pady=(0, 8))

        # Treeview + scrollbar
        tv_wrap = tk.Frame(left_inner, bg=PALETTE["card"])
        tv_wrap.pack(fill="both", expand=True)

        cols = ("date", "time", "zone", "level", "type", "offender")
        self._tree = ttk.Treeview(
            tv_wrap, columns=cols, show="headings", height=10, style="Dash.Treeview", selectmode="browse"
        )
        vs = ttk.Scrollbar(tv_wrap, orient="vertical", command=self._tree.yview)
        hs = ttk.Scrollbar(tv_wrap, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        for c_name, h in zip(cols, ("Date", "Time", "Zone", "Zone Level", "Type", "Offender")):
            self._tree.heading(c_name, text=h, anchor="w")
        self._tree.column("date", width=120, anchor="w")
        self._tree.column("time", width=80, anchor="w")
        self._tree.column("zone", width=160, anchor="w")
        self._tree.column("level", width=110, anchor="w")
        self._tree.column("type", width=320, anchor="w")
        self._tree.column("offender", width=180, anchor="w")

        self._tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        tv_wrap.grid_rowconfigure(0, weight=1)
        tv_wrap.grid_columnconfigure(0, weight=1)

        # Right column
        right_col = ctk.CTkFrame(bottom, fg_color=PALETTE["bg"])
        right_col.pack(side="left", fill="y", padx=(12, 0))

        zones_card, zones_inner = card(right_col, pad=(18, 14))
        zones_card.pack(fill="x")
        ctk.CTkLabel(zones_inner, text="Zones", font=FONTS["h3"], text_color=PALETTE["text"]).pack(anchor="w", pady=(0, 6))

        self._zones_wrap = tk.Frame(zones_inner, bg=PALETTE["card"])
        self._zones_wrap.pack(fill="x")

        role_card, role_inner = card(right_col, pad=(18, 14))
        role_card.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(role_inner, text="Role", font=FONTS["h3"], text_color=PALETTE["text"]).pack(anchor="w", pady=(0, 8))
        role_text = (getattr(self.controller, "current_user_role", "") or "User").replace("_", " ").title()
        self._pill(role_inner, role_text, fg="#111827", bg="#E5DEFF").pack(anchor="w")

        risk_card, risk_inner = card(right_col, pad=(18, 14))
        risk_card.pack(fill="x", pady=(12, 0))
        # Put the parenthetical on the next line so it never gets clipped
        ctk.CTkLabel(
            risk_inner,
            text="Violations by Zone Risk\n(Today)",
            font=FONTS["h3"],
            text_color=PALETTE["text"]
        ).pack(anchor="w", pady=(0, 6))
        self._bars = _Bars(risk_inner)
        self._bars.pack(fill="x", expand=True, pady=(4, 2))

    def _pill(self, parent, text: str, fg="#E8ECF1", bg="#2A2F3A"):
        wrap = ctk.CTkFrame(parent, fg_color=bg, corner_radius=999)
        ctk.CTkLabel(wrap, text=text, text_color=fg, font=("Segoe UI", 10, "bold")).pack(padx=10, pady=4)
        return wrap

    def _start_async_hydrate(self):
        threading.Thread(target=self._hydrate_worker, daemon=True).start()

    def _hydrate_worker(self):
        cid = _company_id_from(self.user)
        user_company_name = _company_name_from_user(self.user)
        company_name = get_company_name(cid, user_company_name)
        suspended = get_company_suspended(cid)

        zones: List[Dict[str, Any]] = []
        if cid:
            try:
                zones = list_zones(cid) or []
            except Exception:
                zones = []

        vio_today_cnt = 0
        day_label = ""
        comp_rate = 100
        recent_rows: List[Tuple[str, str, str, str, str, str]] = []
        risk_low = risk_med = risk_high = 0

        db = get_db()
        if db and cid:
            try:
                start_s, end_s, day_label = _today_bounds()

                zone_level: Dict[str, str] = {}
                zone_name_map: Dict[str, str] = {}
                try:
                    for zs in db.collection("zones").where("company_id", "==", cid).stream():
                        zd = zs.to_dict() or {}
                        zone_level[zs.id] = _level_key(
                            _s(zd.get("risk_level") or zd.get("level") or zd.get("severity") or "")
                        )
                        zone_name_map[zs.id] = _s(
                            zd.get("name") or zd.get("display_name") or zd.get("code") or zs.id
                        )
                except Exception:
                    pass

                snaps: Dict[str, Any] = {}
                for key in _company_keys(cid):
                    try:
                        for s in db.collection("violations").where("company_id", "==", key).stream():
                            snaps[s.id] = s
                    except Exception:
                        pass

                def _ts(s):
                    d = s.to_dict() or {}
                    return _as_epoch_s(d.get("ts") or d.get("time") or d.get("created_at")) or 0.0

                all_v = sorted(snaps.values(), key=_ts, reverse=True)

                # recent rows (top 8)
                for s in all_v[:8]:
                    d = s.to_dict() or {}
                    t = _as_epoch_s(d.get("ts") or d.get("time") or d.get("created_at"))
                    if t:
                        dt = _dt.datetime.fromtimestamp(t)
                        hhmm = dt.strftime("%H:%M")
                        dstr = dt.strftime("%Y-%m-%d")
                    else:
                        hhmm, dstr = "", ""
                    zid = _s(d.get("zone_id") or "")
                    zname = _s(d.get("zone_name") or zone_name_map.get(zid, zid))
                    lvl = _level_key(_s(d.get("risk_level") or d.get("severity") or ""))
                    if not lvl:
                        lvl = zone_level.get(zid, "")
                    lvl_text = {"high": "High", "medium": "Medium", "low": "Low"}.get(lvl, "—")
                    vtype = _risk_human(_s(d.get("risk") or d.get("type") or d.get("ppe_type") or ""))
                    oname = _s(d.get("offender_name") or "")
                    oid = _s(d.get("offender_id") or "")
                    offender = f"{oname} ({oid})" if oname and oid else (oname or oid or "—")
                    recent_rows.append((dstr, hhmm, zname, lvl_text, vtype, offender))

                # today counts
                for s in all_v:
                    d = s.to_dict() or {}
                    t = _as_epoch_s(d.get("ts") or d.get("time") or d.get("created_at"))
                    if t is None or not (start_s <= t < end_s):
                        continue
                    vio_today_cnt += 1
                    lvl = _level_key(_s(d.get("risk_level") or d.get("severity") or ""))
                    if not lvl:
                        lvl = zone_level.get(_s(d.get("zone_id") or ""), "")
                    if lvl == "low":
                        risk_low += 1
                    elif lvl == "medium":
                        risk_med += 1
                    elif lvl == "high":
                        risk_high += 1

                comp_rate = max(0, 100 - 10 * vio_today_cnt)
            except Exception:
                pass

        self.after(
            0,
            lambda: self._apply_hydrate(
                zones,
                vio_today_cnt,
                day_label,
                comp_rate,
                recent_rows,
                (risk_low, risk_med, risk_high),
                company_name,
                suspended,
            ),
        )

    def _apply_hydrate(
        self,
        zones: List[Dict[str, Any]],
        vio_today_cnt: int,
        day_label: str,
        comp_rate: int,
        recent_rows: List[Tuple[str, str, str, str, str, str]],
        risk_counts: Tuple[int, int, int],
        company_name: Optional[str],
        suspended: Optional[bool],
    ):
        if not is_superadmin(self.user) and suspended is True:
            if self._suspend_banner and self._suspend_lbl:
                self._suspend_lbl.configure(
                    text="Your company has been suspended by Super Admin. Access may be limited."
                )
                self._suspend_banner.pack(fill="x", padx=16)
        else:
            if self._suspend_banner:
                try:
                    self._suspend_banner.pack_forget()
                except Exception:
                    pass

        if company_name:
            if self._welcome_company_lbl and self._welcome_company_lbl.winfo_exists():
                self._welcome_company_lbl.configure(text=f"— {company_name}")

        if self._zones_wrap and self._zones_wrap.winfo_exists():
            for w in self._zones_wrap.winfo_children():
                try:
                    w.destroy()
                except Exception:
                    pass
            if not zones:
                tk.Label(self._zones_wrap, text="No zones yet.", bg=PALETTE["card"], fg=PALETTE["muted"]).pack(anchor="w")
            else:
                for z in zones:
                    name = _s(z.get("name") or z.get("display_name") or z.get("code") or z.get("id") or "Zone")
                    tk.Label(self._zones_wrap, text="• " + name, bg=PALETTE["card"], fg=PALETTE["text"]).pack(anchor="w", pady=2)

        if self._vio_title_lbl and self._vio_title_lbl.winfo_exists():
            self._vio_title_lbl.configure(
                text=f"Violations Today ({day_label})" if day_label else "Violations Today"
            )
        if self._vio_value_lbl and self._vio_value_lbl.winfo_exists():
            self._vio_value_lbl.configure(text=str(vio_today_cnt))
        if self._vio_compliance_lbl and self._vio_compliance_lbl.winfo_exists():
            self._vio_compliance_lbl.configure(text=f"Compliance Today: {comp_rate:.0f}%")

        if self._tree and self._tree.winfo_exists():
            for r in self._tree.get_children():
                self._tree.delete(r)

            # Define row-color tags (full-row backgrounds per risk level)
            self._tree.tag_configure("lvl_low", background="#FFF5B1")     # soft yellow
            self._tree.tag_configure("lvl_medium", background="#FFD3A8")  # soft orange
            self._tree.tag_configure("lvl_high", background="#FFC3C3")    # soft red

            # Fallback light zebra (no alpha!)
            self._tree.tag_configure("even", background="#f5f5f5")
            self._tree.tag_configure("odd", background=PALETTE["card"])

            for idx, (dstr, hhmm, zname, lvl_text, vtype, offender) in enumerate(recent_rows):
                level_tag = {
                    "Low": "lvl_low",
                    "Medium": "lvl_medium",
                    "High": "lvl_high",
                }.get(lvl_text, "even" if idx % 2 == 0 else "odd")
                self._tree.insert("", "end", values=(dstr, hhmm, zname, lvl_text, vtype, offender), tags=(level_tag,))

        if self._bars and self._bars.winfo_exists():
            low, med, high = risk_counts
            self._bars.set_counts(low, med, high)

    def _on_profile_updated(self):
        try:
            self.user = get_current_user() or self.user
        except Exception:
            pass

        who = self.controller.current_user_email or self.user.get("email", "")
        new_name = self.user.get("name") or who or "User"
        try:
            if self._welcome_name_lbl and self._welcome_name_lbl.winfo_exists():
                self._welcome_name_lbl.configure(text=_s(new_name))
        except Exception:
            pass

        maybe_company = _company_name_from_user(self.user)
        if maybe_company and self._welcome_company_lbl and self._welcome_company_lbl.winfo_exists():
            self._welcome_company_lbl.configure(text=f"— {maybe_company}")

        self._start_async_hydrate()
