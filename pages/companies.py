# pages/companies.py
import os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional, Tuple
import datetime as _dt

from services.ui_shell import PageShell
from services.ui_theme import apply_theme, card, FONTS, PALETTE, badge
from services.async_ui import run_async
from services.firebase_db import list_companies
from services.firebase_client import get_db
from services.firestore_compat import eq

# ───────────────────────── utils ─────────────────────────
def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()

def _bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool): return v
    t = _s(v).lower()
    if t in ("true", "1", "yes"): return True
    if t in ("false", "0", "no"): return False
    return None

def _status_from_company(d: Dict[str, Any]) -> Tuple[str, str]:
    """
    Returns (status_text, badge_bg)
    """
    # tolerate different field names
    suspended = _bool(d.get("suspended"))
    if suspended is True:
        return "Suspended", "#fee2e2"
    active = _bool(d.get("active"))
    status = _s(d.get("status")).lower()
    if active is False or status in ("disabled", "inactive"):
        return "Inactive", "#fde68a"
    return "Active", "#e7f7ed"

def _company_rows(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in raw:
        name = _s(c.get("name") or c.get("display_name") or c.get("company_name") or "")
        code = _s(c.get("code") or "")
        cid  = c.get("id")
        doc_id = _s(c.get("doc_id") or _s(c.get("docId")))
        created = c.get("created_at") or c.get("createdAt")
        created_str = ""
        try:
            if hasattr(created, "to_datetime"):
                created_str = created.to_datetime().strftime("%Y-%m-%d %H:%M")
            elif isinstance(created, _dt.datetime):
                created_str = created.strftime("%Y-%m-%d %H:%M")
            else:
                created_str = _s(created)
        except Exception:
            created_str = _s(created)
        status_text, status_bg = _status_from_company(c)
        out.append({
            "id": cid,
            "doc_id": doc_id,
            "name": name or "(no name)",
            "code": code,
            "created": created_str,
            "status_text": status_text,
            "status_bg": status_bg,
            # keep original for toggles
            "raw": c,
        })
    return out

# ─────────────────────── page ───────────────────────
class CompaniesPage(PageShell):
    """
    Superadmin Companies (Grid/List) WITHOUT admin counts.
    Right-side info panel also excludes Admins.
    """
    def __init__(self, parent, controller, *_, **__):
        super().__init__(parent, controller, title="Companies", active_key="companies")
        apply_theme(self)

        # state
        self._all_companies: List[Dict[str, Any]] = []
        self._view_mode = tk.StringVar(value="grid")  # grid | list
        self._filter_mode = tk.StringVar(value="all") # all | active | suspended
        self._search_var = tk.StringVar(value="")
        self._sort_mode = tk.StringVar(value="name_az")  # name_az, name_za, id_asc, id_desc, created_new, created_old
        self._selected_idx: Optional[int] = None   # index in filtered list

        # widgets
        self._grid_wrap: Optional[tk.Frame] = None
        self._list_tree: Optional[ttk.Treeview] = None
        self._right_panel: Optional[tk.Frame] = None
        self._info_fields: Dict[str, tk.Label] = {}

        # build
        self._build(self.content)
        self._refresh_async()

    # ───────────────── UI ─────────────────
    def _build(self, root: tk.Frame):
        # Toolbar
        bar = tk.Frame(root, bg=PALETTE["bg"])
        bar.pack(fill="x", pady=(0, 6))

        # filters
        def _rb(parent, text, val):
            rb = ttk.Radiobutton(parent, text=text, value=val, variable=self._filter_mode,
                                 command=self._rebuild_center)
            rb.pack(side="left", padx=(0, 8))
            return rb

        _rb(bar, "All", "all")
        _rb(bar, "Active", "active")
        _rb(bar, "Suspended", "suspended")

        # search
        tk.Label(bar, text="Search", bg=PALETTE["bg"]).pack(side="left", padx=(12, 6))
        ent = ttk.Entry(bar, textvariable=self._search_var, width=28)
        ent.pack(side="left")
        ent.bind("<KeyRelease>", lambda _e: self._rebuild_center())

        # spacer
        tk.Frame(bar, bg=PALETTE["bg"]).pack(side="left", expand=True)

        # sort
        tk.Label(bar, text="Sort", bg=PALETTE["bg"]).pack(side="left", padx=(0, 6))
        sort = ttk.Combobox(bar, state="readonly", width=14, textvariable=self._sort_mode,
                            values=("name_az", "name_za", "id_asc", "id_desc", "created_new", "created_old"))
        sort.pack(side="left")
        sort.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_center())

        # grid/list toggle
        ttk.Button(bar, text="Grid", command=lambda: self._set_mode("grid")).pack(side="left", padx=(12, 6))
        ttk.Button(bar, text="List", command=lambda: self._set_mode("list")).pack(side="left")

        # Body: center + right
        body = tk.Frame(root, bg=PALETTE["bg"])
        body.pack(fill="both", expand=True)

        # center area
        self._center = tk.Frame(body, bg=PALETTE["bg"])
        self._center.pack(side="left", fill="both", expand=True)

        # right info panel
        self._right_panel = tk.Frame(body, bg=PALETTE["bg"], width=320)
        self._right_panel.pack(side="left", fill="y", padx=(8, 0))
        self._build_right_panel(self._right_panel)

    def _build_right_panel(self, root: tk.Frame):
        # Card
        c, inner = card(root, pad=(14, 14))
        c.pack(fill="y", expand=False)
        tk.Label(inner, text="Information", font=FONTS["h3"], bg=PALETTE["card"]).pack(anchor="w", pady=(0, 10))

        # thumbnail
        thumb = tk.Canvas(inner, width=120, height=120, bg="#f8fafc", highlightthickness=0)
        thumb.pack(pady=(0, 10))
        # simple building glyph
        thumb.create_rectangle(20, 40, 100, 110, fill="#e5e7eb", outline="#cbd5e1")
        thumb.create_rectangle(50, 30, 70, 50, fill="#cbd5e1", outline="#94a3b8")

        # fields (NO 'Admins' field here)
        self._info_fields["name"] = self._info_row(inner, "Name")
        self._info_fields["cid"]  = self._info_row(inner, "Company ID")
        # self._info_fields["admins"]  --> intentionally omitted
        self._info_fields["status"] = self._info_row(inner, "Status")
        self._info_fields["created"] = self._info_row(inner, "Created")

        # action buttons
        btn_row = tk.Frame(inner, bg=PALETTE["card"]); btn_row.pack(fill="x", pady=(8, 0))
        self._suspend_btn = ttk.Button(btn_row, text="Suspend Company",
                                       command=self._toggle_suspend_async, style="Danger.TButton")
        self._suspend_btn.pack(side="left")

    def _info_row(self, parent, label) -> tk.Label:
        row = tk.Frame(parent, bg=PALETTE["card"]); row.pack(fill="x", pady=4)
        tk.Label(row, text=label, bg=PALETTE["card"], fg=PALETTE["muted"]).pack(side="left")
        val = tk.Label(row, text="—", bg=PALETTE["card"])
        val.pack(side="right")
        return val

    def _set_mode(self, mode: str):
        if mode not in ("grid", "list"): return
        self._view_mode.set(mode)
        self._rebuild_center()

    # ───────────── data fetch ─────────────
    def _refresh_async(self):
        def _work():
            return list_companies()
        def _done(result):
            if isinstance(result, Exception):
                messagebox.showerror("Companies", f"Failed to load companies:\n{result}")
                return
            self._all_companies = _company_rows(result or [])
            # default select first
            self._selected_idx = 0 if self._all_companies else None
            self._rebuild_center()
        run_async(_work, _done, self)

    # ───────────── filtering/sorting ─────────────
    def _filtered_sorted(self) -> List[Dict[str, Any]]:
        rows = list(self._all_companies)

        # filter
        mode = self._filter_mode.get()
        if mode != "all":
            keep = []
            for r in rows:
                st = r["status_text"].lower()
                if mode == "active" and st == "active":
                    keep.append(r)
                elif mode == "suspended" and st == "suspended":
                    keep.append(r)
            rows = keep

        # search
        q = self._search_var.get().strip().lower()
        if q:
            rows = [r for r in rows if q in f"{r['name']} {r['code']} {r['id']}".lower()]

        # sort
        mode = self._sort_mode.get()
        keyers = {
            "name_az":  (lambda r: (r["name"].lower(),  str(r["id"]))),
            "name_za":  (lambda r: (r["name"].lower(),  str(r["id"]))),
            "id_asc":   (lambda r: (str(r["id"]),       r["name"].lower())),
            "id_desc":  (lambda r: (str(r["id"]),       r["name"].lower())),
            "created_new": (lambda r: r["created"]),
            "created_old": (lambda r: r["created"]),
        }
        keyf = keyers.get(mode, keyers["name_az"])
        reverse = mode in ("name_za", "id_desc", "created_new")
        try:
            rows.sort(key=keyf, reverse=reverse)
        except Exception:
            pass
        return rows

    # ───────────── center rebuild ─────────────
    def _rebuild_center(self):
        for w in self._center.winfo_children():
            w.destroy()
        rows = self._filtered_sorted()
        if self._view_mode.get() == "grid":
            self._build_grid(rows)
        else:
            self._build_list(rows)
        self._update_right_panel(rows)

    def _build_grid(self, rows: List[Dict[str, Any]]):
        wrap = tk.Frame(self._center, bg=PALETTE["bg"])
        wrap.pack(fill="both", expand=True)
        self._grid_wrap = wrap

        # simple responsive grid (3 columns)
        cols = 3
        for idx, r in enumerate(rows):
            c_frame, inner = card(wrap, pad=(12, 10))
            c_frame.grid(row=idx // cols, column=idx % cols, padx=12, pady=12, sticky="n")
            # thumbnail
            canvas = tk.Canvas(inner, width=120, height=120, bg="#f8fafc", highlightthickness=0)
            canvas.pack()
            canvas.create_rectangle(20, 40, 100, 110, fill="#e5e7eb", outline="#cbd5e1")
            canvas.create_rectangle(50, 30, 70, 50, fill="#cbd5e1", outline="#94a3b8")

            # title
            tk.Label(inner, text=r["name"], font=("Segoe UI", 10, "bold"), bg=PALETTE["card"]).pack(pady=(6, 2))

            # BADGE: status only (NO admin count text here)
            b = badge(inner, r["status_text"], bg=r["status_bg"])
            b.pack()

            # selection behavior
            def _select(i=idx):
                self._selected_idx = i
                self._update_right_panel(rows)
            c_frame.bind("<Button-1>", lambda _e, i=idx: _select(i))
            inner.bind("<Button-1>", lambda _e, i=idx: _select(i))
            canvas.bind("<Button-1>", lambda _e, i=idx: _select(i))

    def _build_list(self, rows: List[Dict[str, Any]]):
        cols = ("id", "name", "code", "status", "created")
        headers = ("Company ID", "Company Name", "Code", "Status", "Created")
        widths = (110, 280, 140, 120, 200)
        tree = ttk.Treeview(self._center, columns=cols, show="headings", height=16)
        for c, h, w in zip(cols, headers, widths):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=("center" if c == "status" else "w"))
        tree.pack(fill="both", expand=True)
        self._list_tree = tree

        for i, r in enumerate(rows):
            tree.insert("", "end", values=(r["id"], r["name"], r["code"], r["status_text"], r["created"]))
        def _on_sel(_e=None):
            sel = tree.selection()
            if not sel:
                self._selected_idx = None
            else:
                # map selection order back to filtered list index
                iid = sel[0]
                pos = tree.index(iid)
                self._selected_idx = pos
            self._update_right_panel(rows)
        tree.bind("<<TreeviewSelect>>", _on_sel)
        if rows:
            tree.selection_set(tree.get_children()[0])

    # ───────────── right panel update ─────────────
    def _update_right_panel(self, rows: List[Dict[str, Any]]):
        r = rows[self._selected_idx] if (self._selected_idx is not None and 0 <= self._selected_idx < len(rows)) else None
        if not r:
            self._info_fields["name"].config(text="—")
            self._info_fields["cid"].config(text="—")
            self._info_fields["status"].config(text="—")
            self._info_fields["created"].config(text="—")
            self._suspend_btn.config(state="disabled")
            return
        self._info_fields["name"].config(text=r["name"])
        self._info_fields["cid"].config(text=_s(r["id"]))
        self._info_fields["status"].config(text=r["status_text"])
        self._info_fields["created"].config(text=r["created"])
        self._suspend_btn.config(state="normal")
        # button text
        if r["status_text"] == "Suspended":
            self._suspend_btn.config(text="Unsuspend Company")
        else:
            self._suspend_btn.config(text="Suspend Company")

    # ───────────── suspend/unsuspend ─────────────
    def _toggle_suspend_async(self):
        rows = self._filtered_sorted()
        if self._selected_idx is None or self._selected_idx >= len(rows):
            return
        r = rows[self._selected_idx]
        target_doc = r["doc_id"] or str(r["id"] or "")
        if not target_doc:
            messagebox.showerror("Company", "Missing company identifier.")
            return

        # decide desired state
        to_suspend = (r["status_text"] != "Suspended")

        def _work():
            db = get_db()
            if not db:
                raise RuntimeError("Firestore not configured")
            ref = db.collection("companies").document(target_doc)
            ref.update({"suspended": bool(to_suspend), "active": (not to_suspend)})
            return True

        def _done(result):
            if isinstance(result, Exception):
                messagebox.showerror("Company", f"Failed to update:\n{result}")
                return
            # refresh list
            self._refresh_async()

        run_async(_work, _done, self)
