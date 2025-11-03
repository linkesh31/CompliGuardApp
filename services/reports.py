from __future__ import annotations

import csv
import os
import io
import datetime as dt
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, List, Tuple

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.reports import (
    fetch_violations,
    load_zones_meta,
    summarize_by_day,
    summarize_by_ppe,
    summarize_by_zone_level,
    summarize_offenders,
    generate_report_pdf,
)

# ───────────────────────── helpers ─────────────────────────
def _s(v: Any) -> str:
    return ("" if v is None else str(v)).strip()

def _today_ymd() -> str:
    return dt.date.today().strftime("%Y-%m-%d")

def _days_ago_ymd(n: int) -> str:
    return (dt.date.today() - dt.timedelta(days=n)).strftime("%Y-%m-%d")

def _ymd_to_ms(ymd: str, end_of_day: bool = False) -> int:
    try:
        d = dt.datetime.strptime(ymd.strip(), "%Y-%m-%d")
        if end_of_day:
            d = d.replace(hour=23, minute=59, second=59, microsecond=999000)
        return int(d.timestamp() * 1000.0)
    except Exception:
        return 0

def _risk_color(level: str) -> str:
    t = (level or "").lower()
    if t == "high":
        return "#ef4444"  # red-500
    if t == "medium":
        return "#f59e0b"  # amber-500
    if t == "low":
        return "#22c55e"  # green-500
    return "#64748b"     # slate-500

# Export helpers
def _rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    keys = ["timestamp", "zone_level", "zone", "violation", "offender"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Timestamp", "Zone Level", "Zone", "Violation", "Offender"])
    for r in rows:
        w.writerow([
            r.get("timestamp", ""),
            r.get("zone_level", ""),
            r.get("zone", ""),
            r.get("violation", ""),
            r.get("offender", "")
        ])
    return buf.getvalue()


# ───────────────────────── main page ─────────────────────────
class ReportsPage(tk.Frame):
    """
    A polished, high-contrast reports UI:
      • Filter bar w/ report type, date range, level, quick chips
      • Summary badges
      • Zebra Treeview with dark theme & bigger row height
      • CSV & PDF export
    """
    def __init__(self, parent, controller, *_, **__):
        super().__init__(parent, bg=PALETTE["bg"])
        self.controller = controller
        apply_theme(self)

        # state
        self._preview_rows: List[Dict[str, Any]] = []
        self._zones_meta: Dict[str, Dict[str, Any]] = {}

        self._build_ui(self)
        self.after(100, self._auto_boot)

    # ───────── UI build ─────────
    def _build_ui(self, root: tk.Frame):
        # Title area (use card spacing rhythm)
        top, top_in = card(root); top.pack(fill="x", padx=18, pady=(16, 0))
        tk.Label(top_in, text="Reports", font=FONTS["h2"], fg=PALETTE["text"], bg=PALETTE["card"]).pack(anchor="w")

        # Filter bar
        filt_card, filt = card(root)
        filt_card.pack(fill="x", padx=18, pady=(10, 10))

        tk.Label(filt, text="Report Type", font=FONTS["label"], bg=PALETTE["card"], fg="#cbd5e1") \
            .grid(row=0, column=0, sticky="w")
        self.cb_report = ttk.Combobox(
            filt,
            state="readonly",
            values=[
                "Violations by Risk Level",
                "Violations by Zone & Level",
                "Violations by PPE",
                "Offenders",
                "Daily Trend",
            ]
        )
        self.cb_report.current(0)
        self.cb_report.grid(row=1, column=0, padx=(0, 10), sticky="ew")

        tk.Label(filt, text="From (YYYY-MM-DD)", font=FONTS["label"], bg=PALETTE["card"], fg="#cbd5e1") \
            .grid(row=0, column=1, sticky="w")
        self.ent_from = ttk.Entry(filt, width=16)
        self.ent_from.grid(row=1, column=1, padx=(0, 10), sticky="w")

        tk.Label(filt, text="To (YYYY-MM-DD)", font=FONTS["label"], bg=PALETTE["card"], fg="#cbd5e1") \
            .grid(row=0, column=2, sticky="w")
        self.ent_to = ttk.Entry(filt, width=16)
        self.ent_to.grid(row=1, column=2, padx=(0, 10), sticky="w")

        tk.Label(filt, text="Risk Level", font=FONTS["label"], bg=PALETTE["card"], fg="#cbd5e1") \
            .grid(row=0, column=3, sticky="w")
        self.cb_level = ttk.Combobox(filt, state="readonly", values=["All", "Low", "Medium", "High"], width=12)
        self.cb_level.current(0)
        self.cb_level.grid(row=1, column=3, padx=(0, 10), sticky="w")

        # Quick chips
        chips = tk.Frame(filt, bg=PALETTE["card"])
        chips.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 2))
        for text, fn in (
            ("Today", self._set_today),
            ("Last 7 days", self._set_week),
            ("This month", self._set_month),
        ):
            ttk.Button(chips, text=text, style="Pill.TButton", command=fn).pack(side="left", padx=(0, 8))

        # Actions
        btns = tk.Frame(filt, bg=PALETTE["card"])
        btns.grid(row=1, column=4, rowspan=2, sticky="e")
        ttk.Button(btns, text="Preview", style="Primary.TButton", command=self._preview) \
            .pack(side="left", padx=(0, 10))
        ttk.Button(btns, text="Export CSV", command=self._export_csv).pack(side="left", padx=(0, 10))
        ttk.Button(btns, text="Export PDF", command=self._export_pdf).pack(side="left")

        for c in range(0, 5):
            filt.grid_columnconfigure(c, weight=1)

        # Summary strip
        sum_card, sum_in = card(root)
        sum_card.pack(fill="x", padx=18, pady=(0, 10))
        tk.Label(sum_in, text="Summary", font=FONTS["h4"], fg="#e2e8f0", bg=PALETTE["card"]) \
            .grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.badge_total = self._summary_badge(sum_in, "Total", "—", "#334155")
        self.badge_low   = self._summary_badge(sum_in, "Low", "—", _risk_color("low"))
        self.badge_med   = self._summary_badge(sum_in, "Medium", "—", _risk_color("medium"))
        self.badge_high  = self._summary_badge(sum_in, "High", "—", _risk_color("high"))
        self.badge_topz  = self._summary_badge(sum_in, "Top zone", "—", "#3b82f6")

        for i, w in enumerate((self.badge_total, self.badge_low, self.badge_med, self.badge_high, self.badge_topz)):
            w.grid(row=1, column=i, sticky="w", padx=(0 if i == 0 else 10, 0))

        # Preview table
        prev_card, prev = card(root)
        prev_card.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        tk.Label(prev, text="Preview", font=FONTS["h4"], fg="#e2e8f0", bg=PALETTE["card"]) \
            .pack(anchor="w", pady=(0, 8))

        self._style_treeview()
        cols = ("ts", "level", "zone", "violation")
        self.tree = ttk.Treeview(prev, columns=cols, show="headings", height=14)
        self.tree.heading("ts", text="Timestamp")
        self.tree.heading("level", text="Zone Level")
        self.tree.heading("zone", text="Zone")
        self.tree.heading("violation", text="Violation")

        self.tree.column("ts", width=220, anchor="w")
        self.tree.column("level", width=120, anchor="center")
        self.tree.column("zone", width=220, anchor="w")
        self.tree.column("violation", width=520, anchor="w")

        vsb = ttk.Scrollbar(prev, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(prev, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.pack(fill="both", expand=True, side="left")
        vsb.pack(side="left", fill="y", padx=(6, 0))
        hsb.pack(side="bottom", fill="x")

    # Better looking badges
    def _summary_badge(self, parent, label: str, value: str, color: str) -> tk.Frame:
        wrap = tk.Frame(parent, bg=PALETTE["card"])

        pill = tk.Frame(wrap, bg="#0b1220", highlightthickness=0)
        pill.grid(row=0, column=0, sticky="w")

        # chip
        chip = tk.Frame(pill, bg=color, height=20, bd=0, highlightthickness=0)
        chip.pack(side="left", padx=(0, 8))
        tk.Label(chip, text=label, bg=color, fg="#0b1220",
                 font=("Segoe UI", 9, "bold"), padx=10, pady=3).pack()

        # text
        val = tk.Label(pill, text=value, bg="#0b1220", fg="#e5e7eb",
                       font=("Segoe UI", 11, "bold"), padx=6, pady=3)
        val.pack(side="left", padx=(0, 10))

        wrap._value_lbl = val  # attach for later updates
        return wrap

    # Treeview dark style + zebra rows
    def _style_treeview(self):
        style = ttk.Style(self)

        # Base
        style.configure(
            "Treeview",
            background=PALETTE["bg"],
            fieldbackground=PALETTE["bg"],
            foreground="#E8ECF1",
            rowheight=28,
            bordercolor=PALETTE["border"],
            borderwidth=0
        )
        style.configure(
            "Treeview.Heading",
            background=PALETTE["surface"],
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold")
        )
        style.map("Treeview", background=[("selected", "#1f2937")])
        style.layout("Treeview", style.layout("Treeview"))  # keep default but ensure applied

    # ───────── boot & ranges ─────────
    def _auto_boot(self):
        # default range: last 7 days
        self._set_week()
        self._preview()

    def _set_today(self):
        t = _today_ymd()
        self.ent_from.delete(0, "end"); self.ent_from.insert(0, t)
        self.ent_to.delete(0, "end"); self.ent_to.insert(0, t)

    def _set_week(self):
        self.ent_from.delete(0, "end"); self.ent_from.insert(0, _days_ago_ymd(6))
        self.ent_to.delete(0, "end"); self.ent_to.insert(0, _today_ymd())

    def _set_month(self):
        first = dt.date.today().replace(day=1).strftime("%Y-%m-%d")
        self.ent_from.delete(0, "end"); self.ent_from.insert(0, first)
        self.ent_to.delete(0, "end"); self.ent_to.insert(0, _today_ymd())

    # ───────── data/preview ─────────
    def _preview(self):
        frm = _s(self.ent_from.get())
        to  = _s(self.ent_to.get())
        if not frm or not to:
            messagebox.showerror("Reports", "Please enter a valid date range (From & To).")
            return

        start_ms = _ymd_to_ms(frm)
        end_ms   = _ymd_to_ms(to, end_of_day=True) + 1  # [start, end)
        if start_ms <= 0 or end_ms <= 0 or end_ms <= start_ms:
            messagebox.showerror("Reports", "Invalid date range.")
            return

        cid = getattr(self.controller, "current_company_id", None)
        if not cid:
            messagebox.showerror("Reports", "Missing company context.")
            return

        try:
            rows_raw = fetch_violations(cid, start_ms, end_ms)
            self._zones_meta = load_zones_meta(cid)
        except Exception as e:
            messagebox.showerror("Reports", f"Failed to fetch data: {e}")
            return

        # Optional risk filter
        lev = (self.cb_level.get() or "all").lower()

        def zone_level_of(d: Dict[str, Any]) -> str:
            zid = _s(d.get("zone_id") or "")
            if zid and zid in self._zones_meta:
                return self._zones_meta[zid].get("level") or ""
            return (d.get("risk_level") or d.get("severity") or "").lower()

        rows_f: List[Dict[str, Any]] = []
        for d in rows_raw:
            lvl = zone_level_of(d)
            if lev in ("low", "medium", "high") and lvl != lev:
                continue

            ts = d.get("ts") or d.get("time") or d.get("created_at")
            try:
                if isinstance(ts, (int, float)):
                    ts_s = dt.datetime.fromtimestamp((ts if ts > 1e12 else ts * 1000) / 1000.0) \
                        .strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # support Firestore Timestamp
                    if hasattr(ts, "to_datetime"):
                        ts = ts.to_datetime()
                    ts_s = ts.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                ts_s = _s(ts)

            zone = _s(d.get("zone_name") or d.get("zone") or d.get("zone_id"))
            if not zone:
                zid = _s(d.get("zone_id") or "")
                if zid and zid in self._zones_meta:
                    zone = _s(self._zones_meta[zid].get("name") or "")

            vio = _s(d.get("risk") or d.get("violation") or d.get("type") or "—")
            off = _s(d.get("offender_name") or d.get("offender_id"))

            rows_f.append({
                "timestamp": ts_s,
                "zone_level": (lvl.capitalize() if lvl else "—"),
                "zone": zone or "—",
                "violation": vio,
                "offender": off or "—",
                "_lvl": lvl or "",
            })

        # fill table
        self._preview_rows = rows_f
        self._fill_tree(rows_f)
        self._update_summary(rows_f)

    def _fill_tree(self, rows: List[Dict[str, Any]]):
        self.tree.delete(*self.tree.get_children())

        # tags for zebra
        for i, r in enumerate(rows):
            tag = "odd" if i % 2 else "even"
            self.tree.insert(
                "",
                "end",
                values=(r["timestamp"], r["zone_level"], r["zone"], r["violation"]),
                tags=(tag, r.get("_lvl", ""))
            )

        # tag styles (must be set after widget is created)
        self.tree.tag_configure("even", background="#0f172a")  # slate-900
        self.tree.tag_configure("odd",  background="#111827")  # gray-900
        self.tree.tag_configure("low",     foreground=_risk_color("low"))
        self.tree.tag_configure("medium",  foreground=_risk_color("medium"))
        self.tree.tag_configure("high",    foreground=_risk_color("high"))

    def _update_summary(self, rows: List[Dict[str, Any]]):
        total = len(rows)
        low   = sum(1 for r in rows if r.get("_lvl") == "low")
        med   = sum(1 for r in rows if r.get("_lvl") == "medium")
        high  = sum(1 for r in rows if r.get("_lvl") == "high")

        # top zone by count
        zc: Dict[str, int] = {}
        for r in rows:
            z = r.get("zone") or "—"
            zc[z] = zc.get(z, 0) + 1
        topz = "—"
        if zc:
            topz = sorted(zc.items(), key=lambda x: (-x[1], x[0]))[0][0]

        for badge, text in (
            (self.badge_total, str(total)),
            (self.badge_low,   str(low)),
            (self.badge_med,   str(med)),
            (self.badge_high,  str(high)),
            (self.badge_topz,  topz),
        ):
            badge._value_lbl.configure(text=text)

    # ───────── exports ─────────
    def _export_csv(self):
        if not self._preview_rows:
            messagebox.showinfo("Export CSV", "Nothing to export. Click Preview first.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            title="Save CSV"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                f.write(_rows_to_csv(self._preview_rows))
            messagebox.showinfo("Export CSV", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export CSV", str(e))

    def _export_pdf(self):
        if not self._preview_rows:
            messagebox.showinfo("Export PDF", "Nothing to export. Click Preview first.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            title="Save PDF"
        )
        if not path:
            return

        # Convert current rows back to generator inputs
        rows_raw: List[Dict[str, Any]] = []
        for r in self._preview_rows:
            # keep strings; report builder only needs counts/labels
            rows_raw.append({
                "risk": r["violation"],
                "zone_name": r["zone"],
                "severity": r.get("_lvl"),
                "ts": r["timestamp"],
                "offender_name": r["offender"],
            })

        company_name = getattr(self.controller, "current_company_name", "") or "Company"
        period = f"{self.ent_from.get()} → {self.ent_to.get()}"

        try:
            generate_report_pdf(
                path,
                company_name=company_name,
                period_label=f"Period: {period}",
                include_overview=True,
                include_ppe=True,
                include_zone_level=True,
                include_offenders=True,
                rows=rows_raw,
                zones_meta=self._zones_meta,
            )
            messagebox.showinfo("Export PDF", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export PDF", str(e))
