# pages/home.py
import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any, Optional, Tuple
import datetime as _dt

from services.ui_theme import apply_theme, card, badge, kpi, FONTS, PALETTE
from services.session import require_user
from services.firebase_client import get_db
from services.firestore_compat import eq
from services.firebase_auth import is_superadmin

# ──────────────────────────────────────────────────────────
# Helpers (UNCHANGED)
# ──────────────────────────────────────────────────────────
def _company_keys(company_id_any: Any) -> List[Any]:
    keys: List[Any] = []
    s = str(company_id_any).strip()
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

def _merge_query_streams(col_or_query, field: str, key_candidates: List[Any]) -> List[Any]:
    seen: Dict[str, Any] = {}
    for k in key_candidates:
        try:
            for snap in eq(col_or_query, field, k).stream():
                seen[snap.id] = snap
        except Exception:
            pass
    return list(seen.values())

def _display_name(user: Dict[str, Any]) -> str:
    for k in ("name", "full_name", "display_name"):
        v = (user.get(k) or "").strip()
        if v:
            return v
    email = (user.get("email") or "").strip()
    return email.split("@", 1)[0] if email else "There"

def _company_name(company_doc_id: str) -> str:
    if not company_doc_id:
        return "—"
    try:
        snap = get_db().collection("companies").document(company_doc_id).get()
        if getattr(snap, "exists", False):
            d = snap.to_dict() or {}
            return (d.get("name") or d.get("company_name") or company_doc_id).strip()
    except Exception:
        pass
    return company_doc_id

def _as_epoch_s(ts: Any) -> Optional[float]:
    try:
        if hasattr(ts, "to_datetime"):
            return float(ts.to_datetime().timestamp())
        if hasattr(ts, "timestamp"):
            return float(ts.timestamp())
        if isinstance(ts, (int, float)):
            v = float(ts)
            return v/1000.0 if v > 1e12 else v
    except Exception:
        return None
    return None

def _today_bounds() -> Tuple[float, float, str]:
    now = _dt.datetime.now()
    start = _dt.datetime(now.year, now.month, now.day)
    end = start + _dt.timedelta(days=1)
    return start.timestamp(), end.timestamp(), start.strftime("%Y-%m-%d")

def _risk_human(v: str) -> str:
    t = (v or "").lower()
    if "helmet_and_vest" in t or "both" in t:
        return "Both Missing"
    if "helmet" in t:
        return "Helmet Missing"
    if "vest" in t:
        return "Vest Missing"
    return v or "—"

def _level_key(v: str) -> str:
    t = (v or "").strip().lower()
    if t in ("3", "high", "critical", "severe"): return "high"
    if t in ("2", "med", "medium"): return "medium"
    if t in ("1", "low"): return "low"
    return ""


# ──────────────────────────────────────────────────────────
# Simple bar chart (Canvas) for Low/Med/High counts (UNCHANGED)
# ──────────────────────────────────────────────────────────
class _Bars(tk.Canvas):
    def __init__(self, parent, *, bg=None, height=140, **kw):
        super().__init__(parent, bg=bg or PALETTE["card"], height=height, highlightthickness=0, **kw)
        self._counts = {"low": 0, "medium": 0, "high": 0}
        self.bind("<Configure>", lambda _e: self._draw())

    def set_counts(self, low: int, med: int, high: int):
        self._counts = {"low": max(0, low), "medium": max(0, med), "high": max(0, high)}
        self._draw()

    def _draw(self):
        self.delete("all")
        w = max(1, self.winfo_width()); h = max(1, self.winfo_height())
        pad = 16
        categories = [("Low", "low", "#fde68a"), ("Medium", "medium", "#fdba74"), ("High", "high", "#fecaca")]
        maxv = max(1, max(self._counts.values()) or 1)
        bar_w = (w - pad*2) / (len(categories)*1.6)
        gap = bar_w * 0.6
        x = pad + (w - pad*2 - (bar_w*3 + gap*2)) / 2

        for label, key, color in categories:
            v = self._counts.get(key, 0)
            bh = int((h - 40) * (v / maxv))
            y0 = h - 24 - bh
            self.create_rectangle(x, y0, x+bar_w, h-24, fill=color, outline=PALETTE["border"])
            self.create_text(x+bar_w/2, h-10, text=label, fill=PALETTE["muted"], font=("Segoe UI", 9))
            self.create_text(x+bar_w/2, y0-8, text=str(v), fill=PALETTE["fg"], font=("Segoe UI", 10, "bold"))
            x += bar_w + gap


# ──────────────────────────────────────────────────────────
# Page
# ──────────────────────────────────────────────────────────
class HomePage(tk.Frame):
    """Dashboard overview with today's KPIs + recent violations + risk-level bars."""
    def __init__(self, parent, controller):
        super().__init__(parent, bg=PALETTE["bg"])
        self.controller = controller
        apply_theme(self)
        self._init_styles()
        self._build()
        self._refresh()
        try: self.bind("<Visibility>", lambda _e: self._refresh())
        except Exception: pass

    def _init_styles(self):
        s = ttk.Style(self)
        s.configure("StatBig.TLabel", font=("Segoe UI", 26, "bold"), foreground=PALETTE["text"], background=PALETTE["card"])
        s.configure("Muted.TLabel", foreground=PALETTE["muted"], background=PALETTE["card"])
        s.configure("KPI.TLabel", font=("Segoe UI", 11, "bold"), foreground=PALETTE["text"], background=PALETTE["card"])

        s.configure(
            "Dashboard.Treeview",
            background=PALETTE["card"],
            fieldbackground=PALETTE["card"],
            foreground=PALETTE["text"],
            rowheight=28,
            borderwidth=0
        )
        s.configure(
            "Dashboard.Treeview.Heading",
            font=FONTS.get("h6", ("Segoe UI Semibold", 10)),
            foreground=PALETTE["text"],
            background=PALETTE["card"]
        )
        s.map("Dashboard.Treeview",
              background=[("selected", "#2563eb")],
              foreground=[("selected", "#ffffff")])

    def _build(self):
        header = tk.Frame(self, bg=PALETTE["bg"]); header.pack(fill="x", pady=(0, 8))
        tk.Label(header, text="Dashboard", font=FONTS["h2"], bg=PALETTE["bg"], fg=PALETTE["text"]).pack(side="left")

        comp = (getattr(self.controller, "current_company_name", "") or "").strip()
        if comp: badge(header, comp).pack(side="left", padx=(10, 0))

        tk.Frame(self, height=1, bg=PALETTE["border"]).pack(fill="x", pady=(6, 12))

        grid = tk.Frame(self, bg=PALETTE["bg"]); grid.pack(fill="both", expand=True)

        # top row (3 KPI cards)
        row1 = tk.Frame(grid, bg=PALETTE["bg"]); row1.pack(fill="x")
        self.c1, self.b1 = card(row1); self.c1.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=(0, 12))
        self.c2, self.b2 = card(row1); self.c2.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=(0, 12))
        self.c3, self.b3 = card(row1); self.c3.pack(side="left", fill="both", expand=True, padx=(0, 0),  pady=(0, 12))

        # bottom row (3 cards)
        row2 = tk.Frame(grid, bg=PALETTE["bg"]); row2.pack(fill="both", expand=True)
        self.c4, self.b4 = card(row2); self.c4.pack(side="left", fill="both", expand=True, padx=(0, 12))
        self.c5, self.b5 = card(row2); self.c5.pack(side="left", fill="both", expand=True, padx=(0, 12))
        self.c6, self.b6 = card(row2); self.c6.pack(side="left", fill="both", expand=True, padx=(0, 0))

        # bottom-left = Recent Violations (compact)
        tk.Label(self.b4, text="Recent Violations", font=FONTS["h3"], bg=PALETTE["card"], fg=PALETTE["text"]).pack(anchor="w", pady=(0, 6))

        tv_wrap = tk.Frame(self.b4, bg=PALETTE["card"]); tv_wrap.pack(fill="both", expand=True)
        self.tv = ttk.Treeview(tv_wrap, columns=("time", "type"), show="headings", height=7, style="Dashboard.Treeview")
        vs = ttk.Scrollbar(tv_wrap, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vs.set)

        self.tv.heading("time", text="Time", anchor="w"); self.tv.heading("type", text="Type", anchor="w")
        self.tv.column("time", width=160, anchor="w"); self.tv.column("type", width=260, anchor="w")

        self.tv.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        tv_wrap.grid_rowconfigure(0, weight=1)
        tv_wrap.grid_columnconfigure(0, weight=1)

        # bottom-middle = Risk-level bars
        tk.Label(self.b5, text="Violations by Zone Risk\n(Today)", font=FONTS["h3"], bg=PALETTE["card"], fg=PALETTE["text"]).pack(anchor="w", pady=(0, 6))
        self.bars = _Bars(self.b5); self.bars.pack(fill="both", expand=True)

        # bottom-right = Role / notes
        tk.Label(self.b6, text="Role", font=FONTS["h3"], bg=PALETTE["card"], fg=PALETTE["text"]).pack(anchor="w", pady=(0, 6))
        self.role_chip_holder = tk.Frame(self.b6, bg=PALETTE["card"]); self.role_chip_holder.pack(anchor="w")

    def _refresh(self):
        for box in (self.b1, self.b2, self.b3):
            for w in box.winfo_children(): w.destroy()
        for w in self.tv.get_children(): self.tv.delete(w)
        for w in self.role_chip_holder.winfo_children(): self.winfo_children()
        self.bars.set_counts(0, 0, 0)

        try:
            user = require_user()
        except Exception as e:
            tk.Label(self.b1, text="Session Error", font=FONTS["h3"], bg=PALETTE["card"], fg=PALETTE["text"]).pack(anchor="w")
            ttk.Label(self.b1, text=str(e), style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
            return

        role = (user.get("role") or "").lower()
        company_doc_id = str(user.get("company_id") or "").strip()

        if is_superadmin(user):
            self._render_superadmin()
        elif role == "company_admin":
            self._render_company_admin(user, company_doc_id)
        else:
            self._render_admin(user, company_doc_id)

    # Views (UNCHANGED)
    def _render_superadmin(self):
        db = get_db()
        companies_count = sum(1 for _ in db.collection("companies").stream())
        admins_count = sum(1 for _ in eq(db.collection("users"), "role", "admin").stream())
        admins_count += sum(1 for _ in eq(db.collection("users"), "role", "company_admin").stream())
        violations_count = sum(1 for _ in db.collection("violations").stream())

        k1 = kpi(self.b1, "Companies", str(companies_count), trend="• total", trend_fg=PALETTE["muted"])
        k1.configure(highlightbackground=PALETTE["border"])
        k2 = kpi(self.b2, "Admins (All)", str(admins_count), trend="• accounts", trend_fg=PALETTE["muted"])
        k2.configure(highlightbackground=PALETTE["border"])
        vio_fg = "#dc2626" if violations_count else "#16a34a"
        k3 = kpi(self.b3, "Violations (All)", str(violations_count), trend="overall", trend_fg=vio_fg)
        k3.configure(highlightbackground=PALETTE["border"])

        badge(self.role_chip_holder, "Superadmin", fg="#7c3aed", bg="#efe6ff").pack(anchor="w")

    def _render_company_admin(self, user: Dict[str, Any], company_doc_id: str):
        self._render_companyish(user, company_doc_id, company_role="Company Admin")

    def _render_admin(self, user: Dict[str, Any], company_doc_id: str):
        self._render_companyish(user, company_doc_id, company_role="Admin")

    def _render_companyish(self, user: Dict[str, Any], company_doc_id: str, company_role: str):
        db = get_db()
        keys = _company_keys(company_doc_id)
        name = _display_name(user)
        comp_name = _company_name(company_doc_id)

        admins_q1 = eq(db.collection("users"), "role", "admin")
        admins_q2 = eq(db.collection("users"), "role", "company_admin")
        admins_in_company = _merge_query_streams(admins_q1, "company_id", keys) \
                            + _merge_query_streams(admins_q2, "company_id", keys)

        vio_all = _merge_query_streams(db.collection("violations"), "company_id", keys)
        zones = _merge_query_streams(db.collection("zones"), "company_id", keys)
        zone_level: Dict[str, str] = {}
        for z in zones:
            d = z.to_dict() or {}
            zid = str(getattr(z, "id", d.get("id") or d.get("zone_id") or "")) or ""
            zone_level[zid] = _level_key(str(d.get("risk_level") or d.get("level") or d.get("severity") or ""))

        start_s, end_s, day_label = _today_bounds()
        vio_today: List[Any] = []
        for s in vio_all:
            d = s.to_dict() or {}
            ts_any = d.get("ts") or d.get("time") or d.get("created_at")
            t = _as_epoch_s(ts_any)
            if t is None:
                continue
            if start_s <= t < end_s:
                vio_today.append(s)

        # Welcome + BIG company name to utilize available space
        tk.Label(
            self.b1,
            text=f"Welcome, {name}",
            font=("Segoe UI", 18, "bold"),
            bg=PALETTE["card"],
            fg=PALETTE["text"]
        ).pack(anchor="w")

        tk.Label(
            self.b1,
            text=comp_name,
            font=("Segoe UI", 24, "bold"),   # ⟵ bigger company name
            bg=PALETTE["card"],
            fg=PALETTE["primary"]
        ).pack(anchor="w", pady=(6, 0))

        k_adm = kpi(self.b2, "Admins in Company", str(len(admins_in_company)), trend="• accounts", trend_fg=PALETTE["muted"])
        k_adm.configure(highlightbackground=PALETTE["border"])

        today_count = len(vio_today)
        vio_fg = "#dc2626" if today_count else "#16a34a"
        k_vio = kpi(self.b3, f"Violations Today ({day_label})", str(today_count),
                    trend=("active" if today_count else "✓ clean"), trend_fg=vio_fg)
        k_vio.configure(highlightbackground=PALETTE["border"])

        ttk.Label(self.b3, text=f"Compliance Today: {max(0, 100 - 10 * today_count):.0f}%",
                  style="KPI.TLabel").pack(anchor="w", pady=(6, 0))

        def _ts_sort(s):
            d = s.to_dict() or {}
            t = d.get("ts") or d.get("time") or d.get("created_at")
            v = _as_epoch_s(t)
            return v or 0.0
        vio_all_sorted = sorted(vio_all, key=_ts_sort, reverse=True)

        for idx, s in enumerate(vio_all_sorted[:8]):
            d = s.to_dict() or {}
            ts_any = d.get("ts") or d.get("time") or d.get("created_at")
            dt_s = ""
            try:
                t = _as_epoch_s(ts_any)
                if t is not None:
                    dt_s = _dt.datetime.fromtimestamp(t).strftime("%H:%M")
            except Exception:
                dt_s = str(ts_any or "")
            vtype = _risk_human(str(d.get("risk") or d.get("type") or d.get("ppe_type") or ""))
            iid = self.tv.insert("", "end", values=(dt_s, vtype))
            self.tv.tag_configure("even", background="#f5f5f5")
            self.tv.tag_configure("odd",  background=PALETTE["card"])
            self.tv.item(iid, tags=("even" if idx % 2 == 0 else "odd",))

        low = med = high = 0
        for s in vio_today:
            d = s.to_dict() or {}
            lvl = _level_key(str(d.get("risk_level") or d.get("severity") or ""))
            if not lvl:
                zid = str(d.get("zone_id") or "")
                lvl = zone_level.get(zid, "")
            if lvl == "low":   low += 1
            elif lvl == "medium": med += 1
            elif lvl == "high": high += 1
        self.bars.set_counts(low, med, high)

        badge(self.role_chip_holder, company_role,
              fg=("#6d28d9" if "Company" in company_role else "#1d4ed8"),
              bg=("#f3e8ff" if "Company" in company_role else "#e0e7ff")).pack(anchor="w")
