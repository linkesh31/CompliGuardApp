from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.ui_shell import PageShell
from services.session import require_user
from services.async_ui import run_async
from services.workers import (
    list_workers,
    create_worker,
    update_worker,      # edit worker_id, name, phone
    delete_worker,      # delete
)


def _clean_phone(p: str) -> str:
    """
    Basic phone normalizer for validation:
    - remove spaces, dashes, brackets, dots
    - keep leading '+' if present
    returns cleaned string
    """
    p = (p or "").strip()
    # keep '+' only if it's the first char
    if p.startswith("+"):
        prefix = "+"
        rest = p[1:]
    else:
        prefix = ""
        rest = p

    for ch in (" ", "-", "(", ")", "."):
        rest = rest.replace(ch, "")

    return prefix + rest


def _phone_is_plausible(p: str) -> bool:
    """
    Very light validation:
    - allow "+60123456789" or "60123456789"
    - after optional '+', must be digits only
    - length between 8 and 20
    """
    p2 = _clean_phone(p)

    if p2.startswith("+"):
        digits = p2[1:]
    else:
        digits = p2

    if not digits.isdigit():
        return False

    if len(digits) < 8 or len(digits) > 20:
        return False

    return True


class WorkersPage(PageShell):
    """
    Workers management page.

    CHANGES:
    - Removed 'Active' column completely.
    - All rows use the same green styling (no red rows).
    - Added success popups after Add / Edit / Delete.
    - Added basic phone validation.
    """
    def __init__(self, parent, controller, user: Optional[dict] = None, **_):
        super().__init__(parent, controller, title="Workers", active_key="workers")
        self.controller = controller
        apply_theme(self)

        self.company_id: Optional[Any] = getattr(self.controller, "current_company_id", None)
        self._rows: List[Dict[str, Any]] = []

        # form state
        self.search_var = tk.StringVar()
        self.id_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.phone_var = tk.StringVar()

        # widgets
        self.tree: Optional[ttk.Treeview] = None
        self._status_lbl: Optional[tk.Label] = None
        self._btn_refresh: Optional[ttk.Button] = None

        # column order (active removed)
        self._cols: List[str] = ["worker_id", "name", "phone", "created_at", "edit", "delete"]

        self._build(self.content)
        self._refresh_async()
        try:
            self.bind("<Visibility>", lambda _e: self._refresh_async())
        except Exception:
            pass

    # ───────────────────────── UI ─────────────────────────
    def _build(self, root: tk.Frame):
        # Styles
        try:
            s = ttk.Style()

            # Primary (blue) button
            s.configure(
                "Primary.TButton",
                padding=(12, 6),
                font=("Segoe UI", 10, "bold"),
                background="#2563eb",
                foreground="#ffffff",
                relief="flat",
            )
            s.map(
                "Primary.TButton",
                background=[("!disabled", "#2563eb"), ("active", "#1d4ed8")],
                foreground=[("!disabled", "#ffffff")],
            )

            # Success (green) button for Refresh
            s.configure(
                "Success.TButton",
                padding=(10, 6),
                font=("Segoe UI", 10, "bold"),
                background="#63A361",
                foreground="#ffffff",
                relief="flat",
            )
            s.map(
                "Success.TButton",
                background=[("!disabled", "#63A361"), ("active", "#4e8a50")],
                foreground=[("!disabled", "#ffffff")],
            )

            # Neutral button (used for dialog Cancel)
            s.configure(
                "Neutral.TButton",
                padding=(10, 6),
                font=("Segoe UI", 10),
            )

            # Destructive (red) button — style kept for reference
            s.configure(
                "Danger.TButton",
                padding=(12, 6),
                font=("Segoe UI", 10, "bold"),
                background="#dc2626",
                foreground="#ffffff",
                relief="flat",
            )
            s.map(
                "Danger.TButton",
                background=[("!disabled", "#dc2626"), ("active", "#b91c1c")],
                foreground=[("!disabled", "#ffffff")],
            )

            # Labels in the beige cards
            s.configure(
                "FormKey.TLabel",
                background=PALETTE.get("card", "#ffffff"),
                foreground="#333333",
                font=("Segoe UI", 10, "bold"),
            )

            s.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
            s.map(
                "Treeview",
                background=[("selected", "#dbeafe")],
                foreground=[("selected", "#0f172a")],
            )
        except Exception:
            pass

        wrap = tk.Frame(root, bg=PALETTE["bg"])
        wrap.pack(fill="both", expand=True, padx=20, pady=18)

        # Header row (title + refresh/search)
        head = tk.Frame(wrap, bg=PALETTE["bg"])
        head.pack(fill="x", pady=(0, 6))

        tk.Label(
            head,
            text="Workers",
            font=FONTS["h2"],
            bg=PALETTE["bg"],
        ).pack(side="left")

        right = tk.Frame(head, bg=PALETTE["bg"])
        right.pack(side="right")

        self._btn_refresh = ttk.Button(
            right,
            text="Refresh",
            style="Success.TButton",
            command=self._refresh_async,
        )
        self._btn_refresh.pack(side="left", padx=(0, 10))

        tk.Label(
            right,
            text="Search",
            bg=PALETTE["bg"],
            fg=PALETTE.get("muted", "#6b7280"),
        ).pack(side="left", padx=(6, 6))

        ent_s = ttk.Entry(right, textvariable=self.search_var, width=24)
        ent_s.pack(side="left")
        ent_s.bind("<Return>", lambda _e: self._refresh_async())

        # Add Worker form card
        form_card, form_inner = card(wrap, pad=(16, 14))
        form_card.pack(fill="x", pady=(10, 12))
        form = tk.Frame(form_inner, bg=PALETTE["card"])
        form.pack(fill="x")

        # grid columns
        for i in range(8):
            form.grid_columnconfigure(i, weight=1 if i in (1, 3, 5) else 0)

        ttk.Label(form, text="Worker ID", style="FormKey.TLabel").grid(
            row=0,
            column=0,
            sticky="e",
            padx=(2, 10),
            pady=8,
        )
        ttk.Entry(form, textvariable=self.id_var).grid(
            row=0,
            column=1,
            sticky="ew",
            pady=8,
        )

        ttk.Label(form, text="Name", style="FormKey.TLabel").grid(
            row=0,
            column=2,
            sticky="e",
            padx=(16, 10),
            pady=8,
        )
        ttk.Entry(form, textvariable=self.name_var).grid(
            row=0,
            column=3,
            sticky="ew",
            pady=8,
        )

        ttk.Label(form, text="Phone (+60…)", style="FormKey.TLabel").grid(
            row=0,
            column=4,
            sticky="e",
            padx=(16, 10),
            pady=8,
        )
        ttk.Entry(form, textvariable=self.phone_var).grid(
            row=0,
            column=5,
            sticky="ew",
            pady=8,
        )

        ttk.Button(
            form,
            text="Add Worker",
            style="Primary.TButton",
            command=self._on_add,
        ).grid(
            row=0,
            column=7,
            padx=(16, 2),
        )

        # Table card
        table_card, table_inner = card(wrap, pad=(10, 10))
        table_card.pack(fill="x")

        top = tk.Frame(table_inner, bg=PALETTE["card"])
        top.pack(fill="x", padx=10, pady=(6, 0))

        tk.Label(
            top,
            text="Workers List",
            font=FONTS["h3"],
            bg=PALETTE["card"],
        ).pack(side="left")

        self._status_lbl = tk.Label(
            top,
            text="",
            bg=PALETTE["card"],
            fg=PALETTE.get("muted", "#6b7280"),
        )
        self._status_lbl.pack(side="right")

        # Treeview without Active column
        tree = ttk.Treeview(
            table_inner,
            columns=self._cols,
            show="headings",
            height=1,  # we'll resize based on rows later
        )
        tree.pack(fill="x", padx=10, pady=10)

        headings = {
            "worker_id": "Worker Id",
            "name": "Name",
            "phone": "Phone",
            "created_at": "Created At",
            "edit": "Edit",
            "delete": "Delete",
        }

        for key in self._cols:
            tree.heading(key, text=headings[key], anchor="center")
            tree.column(key, anchor="center")

        # set widths
        tree.column("worker_id", width=110)
        tree.column("name", width=180)
        tree.column("phone", width=160)
        tree.column("created_at", width=160)
        tree.column("edit", width=80)
        tree.column("delete", width=80)

        # click handling for in-table actions
        tree.bind("<Button-1>", self._on_tree_click)
        tree.bind("<Double-1>", self._on_tree_double)

        self.tree = tree

    # ───────────────────────── actions ─────────────────────────
    def _on_tree_click(self, event):
        """Handle clicks on Edit/Delete columns."""
        if not self.tree:
            return
        row_iid = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)  # '#1', '#2', ...
        if not row_iid or not col_id:
            return

        col_index = int(col_id.replace("#", "")) - 1
        if col_index < 0 or col_index >= len(self._cols):
            return
        col_name = self._cols[col_index]

        row = None
        for r in self._rows:
            if r.get("_iid") == row_iid:
                row = r
                break
        if not row:
            return

        if col_name == "edit":
            self._open_edit_dialog(row)
        elif col_name == "delete":
            self._delete_row(row)

    def _on_tree_double(self, _e):
        """Double-click anywhere on a row opens Edit."""
        row = self._selected_row()
        if row:
            self._open_edit_dialog(row)

    def _selected_row(self) -> Optional[Dict[str, Any]]:
        if not self.tree:
            return None
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        for r in self._rows:
            if r.get("_iid") == iid:
                return r
        return None

    def _open_edit_dialog(self, row: Dict[str, Any]):
        top = tk.Toplevel(self)
        top.title("Edit Worker")
        try:
            top.resizable(False, False)
        except Exception:
            pass
        apply_theme(top)

        container = tk.Frame(top, bg=PALETTE["bg"])
        container.pack(fill="both", expand=True, padx=14, pady=12)

        ttk.Label(container, text="Worker ID").grid(
            row=0,
            column=0,
            sticky="e",
            padx=(2, 10),
            pady=6,
        )
        worker_id_var = tk.StringVar(value=row["worker_id"])
        ttk.Entry(container, textvariable=worker_id_var, width=28).grid(
            row=0,
            column=1,
            sticky="w",
            pady=6,
        )

        ttk.Label(container, text="Name").grid(
            row=1,
            column=0,
            sticky="e",
            padx=(2, 10),
            pady=6,
        )
        name_var = tk.StringVar(value=row["name"])
        ttk.Entry(container, textvariable=name_var, width=28).grid(
            row=1,
            column=1,
            sticky="w",
            pady=6,
        )

        ttk.Label(container, text="Phone (+60…)").grid(
            row=2,
            column=0,
            sticky="e",
            padx=(2, 10),
            pady=6,
        )
        phone_var = tk.StringVar(value=row.get("phone", ""))
        ttk.Entry(container, textvariable=phone_var, width=28).grid(
            row=2,
            column=1,
            sticky="w",
            pady=6,
        )

        btns = tk.Frame(container, bg=PALETTE["bg"])
        btns.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Button(
            btns,
            text="Save",
            style="Primary.TButton",
            command=lambda: _save(),
        ).pack(side="left")

        ttk.Button(
            btns,
            text="Cancel",
            style="Neutral.TButton",
            command=lambda: top.destroy(),
        ).pack(side="right")

        def _save():
            new_name = (name_var.get() or "").strip()
            new_id = (worker_id_var.get() or "").strip()
            new_phone = (phone_var.get() or "").strip()

            # validation
            if not new_id or not new_name or not new_phone:
                messagebox.showerror(
                    "Edit",
                    "Worker ID, Name, and Phone are required.",
                )
                return
            if not _phone_is_plausible(new_phone):
                messagebox.showerror(
                    "Edit",
                    "Please enter a valid phone number with country code (e.g. +60123456789).",
                )
                return

            def _work():
                update_worker(
                    row["doc_id"],
                    company_id=self.company_id,
                    worker_id=new_id,
                    name=new_name,
                    phone=new_phone,
                )
                return True

            def _done(res):
                if isinstance(res, Exception):
                    messagebox.showerror(
                        "Edit",
                        f"Failed to update worker:\n{res}",
                    )
                    return
                try:
                    top.destroy()
                except Exception:
                    pass

                # success popup
                messagebox.showinfo(
                    "Saved",
                    "Worker details updated.",
                )

                self._refresh_async()

            run_async(_work, _done, self)

    def _delete_row(self, row: Dict[str, Any]):
        if not messagebox.askyesno(
            "Delete Worker",
            f"Delete worker '{row['worker_id']} - {row['name']}'?",
        ):
            return

        def _work():
            delete_worker(row["doc_id"])
            return True

        def _done(res):
            if isinstance(res, Exception):
                messagebox.showerror(
                    "Delete",
                    f"Failed to delete worker:\n{res}",
                )
                return

            # success popup
            messagebox.showinfo(
                "Deleted",
                "Worker deleted.",
            )

            self._refresh_async()

        run_async(_work, _done, self)

    def _on_add(self):
        if not self.company_id:
            # re-resolve from session each time to avoid stale context
            try:
                sess_user = require_user()
                self.company_id = sess_user.get("company_id")
            except Exception:
                self.company_id = getattr(self.controller, "current_company_id", None)

        worker_id = (self.id_var.get() or "").strip()
        name = (self.name_var.get() or "").strip()
        phone = (self.phone_var.get() or "").strip()

        # validation
        if not self.company_id:
            messagebox.showerror("Workers", "No company selected.")
            return
        if not worker_id or not name or not phone:
            messagebox.showerror(
                "Workers",
                "Please enter Worker ID, Name, and Phone.",
            )
            return
        if not _phone_is_plausible(phone):
            messagebox.showerror(
                "Workers",
                "Please enter a valid phone number with country code (e.g. +60123456789).",
            )
            return

        def _work():
            return create_worker(self.company_id, worker_id, name, phone)

        def _done(res):
            if isinstance(res, Exception):
                messagebox.showerror(
                    "Add Worker",
                    f"Failed to add worker:\n{res}",
                )
                return

            # clear fields
            self.id_var.set("")
            self.name_var.set("")
            self.phone_var.set("")

            # success popup
            messagebox.showinfo(
                "Saved",
                "Worker added successfully.",
            )

            self._refresh_async()

        run_async(_work, _done, self)

    # ───────────────────────── data refresh ─────────────────────────
    def _refresh_async(self):
        # Always re-resolve company each refresh to avoid stale context
        try:
            sess_user = require_user()
            self.company_id = sess_user.get("company_id") or self.company_id
        except Exception:
            pass
        if not self.company_id:
            self.company_id = getattr(self.controller, "current_company_id", None)

        if not self.company_id:
            self._rows = []
            self._render_table([])
            return

        search = (self.search_var.get() or "").strip()

        if self._status_lbl:
            self._status_lbl.config(text="Loading…")
        if self._btn_refresh:
            try:
                self._btn_refresh.config(state="disabled")
            except Exception:
                pass

        def _work():
            return list_workers(self.company_id, search=search)

        def _done(result):
            try:
                if self._btn_refresh:
                    self._btn_refresh.config(state="normal")
            except Exception:
                pass

            if isinstance(result, Exception):
                if self._status_lbl:
                    self._status_lbl.config(text="")
                messagebox.showerror(
                    "Workers",
                    f"Failed to load workers:\n{result}",
                )
                return

            self._rows = result
            self._render_table(self._rows)
            if self._status_lbl:
                self._status_lbl.config(text=f"{len(self._rows)} worker(s)")

        run_async(_work, _done, self)

    def _render_table(self, rows: List[Dict[str, Any]]):
        if not self.tree:
            return
        tree = self.tree

        # clear old rows
        for r in tree.get_children():
            tree.delete(r)

        # insert fresh rows
        for row in rows:
            created = row.get("created_at", 0)
            if created:
                try:
                    import datetime as _dt
                    dt = _dt.datetime.fromtimestamp(created / 1000.0)
                    created_str = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    created_str = str(created)
            else:
                created_str = "-"

            vals = (
                row["worker_id"],
                row["name"],
                row.get("phone", ""),
                created_str,
                "✏ Edit",
                "🗑 Delete",
            )

            iid = tree.insert("", "end", values=vals)

            # Color row (always same light green style now)
            try:
                tree.item(iid, tags=("row_active",))
                tree.tag_configure(
                    "row_active",
                    background="#ecfdf5",   # light green bg
                    foreground="#065f46",   # dark green text
                )
            except Exception:
                pass

            row["_iid"] = iid

        # auto-fit height to however many rows we have
        try:
            tree.configure(height=max(1, len(rows)))
        except Exception:
            pass
