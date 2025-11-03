import re
import threading
import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk, messagebox
from typing import Any, List, Optional

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.users import list_users, create_admin_user
from services.config import SUPERADMIN_EMAIL
from services.session import require_user

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _safe_ts_to_dt(ts: Any) -> Optional[datetime]:
    try:
        if hasattr(ts, "to_datetime"):
            dt = ts.to_datetime()
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        if hasattr(ts, "timestamp"):
            return datetime.fromtimestamp(float(ts.timestamp()), tz=timezone.utc)
    except Exception:
        pass
    try:
        v = float(ts)
        if v > 1e12:
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except Exception:
        return None


def _safe_ts_to_str(ts: Any) -> str:
    dt = _safe_ts_to_dt(ts)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if dt else str(ts or "")


def _password_issues(pw: str) -> List[str]:
    problems: List[str] = []
    if len(pw) < 8:
        problems.append("• at least 8 characters")
    if not re.search(r"[a-z]", pw):
        problems.append("• a lowercase letter")
    if not re.search(r"[A-Z]", pw):
        problems.append("• an uppercase letter")
    if not re.search(r"[0-9]", pw):
        problems.append("• a number")
    if not re.search(r"[^A-Za-z0-9]", pw):
        problems.append("• a special character")
    return problems


def _current_company_id(controller) -> Optional[str]:
    cid = getattr(controller, "current_company_id", None)
    if cid is not None:
        s = str(cid).strip()
        if s:
            return s
    try:
        user = require_user() or {}
        s = str(user.get("company_id") or "").strip()
        if s:
            return s
    except Exception:
        pass
    return None


def _current_user_email(controller) -> str:
    e = (getattr(controller, "current_user_email", "") or "").strip().lower()
    if e:
        return e
    try:
        user = require_user() or {}
        e = (user.get("email") or "").strip().lower()
        return e
    except Exception:
        return ""


# ───────────────────────────────
# Page
# ───────────────────────────────
class AddAdminPage(tk.Frame):
    PAGE_BG = "#E6D8C3"
    TEXT_FG = "#000000"
    ACTIVE_ROW_BG = "#5D866C"
    ENTRY_BG = "#F5EEDF"
    CARD_BG = "#EFE3D0"

    def __init__(self, parent, controller, *_, **__):
        super().__init__(parent, bg=self.PAGE_BG)
        self.controller = controller
        apply_theme(self)

        self._apply_page_theme_overrides()
        self._init_styles()

        self._all_users_cache: List[dict] = []
        self._bg_thread: Optional[threading.Thread] = None
        self._stop_flag = False

        self._build(self)
        try:
            self.bind("<Visibility>", lambda _e: self._refresh_users_table())
        except Exception:
            pass

    def _apply_page_theme_overrides(self):
        self.option_add("*Background", self.PAGE_BG)
        self.option_add("*Foreground", self.TEXT_FG)
        self.option_add("*highlightBackground", self.PAGE_BG)
        self.option_add("*insertBackground", self.TEXT_FG)
        self.option_add("*troughColor", self.PAGE_BG)
        self.option_add("*selectBackground", "#2563eb")
        self.option_add("*selectForeground", "#FFFFFF")

    def _init_styles(self):
        self.style = ttk.Style(self)
        accent = "#0077b6"
        hover = "#00b4d8"

        self.style.configure(
            "Modern.TButton",
            font=("Segoe UI Semibold", 10),
            background=accent,
            foreground="white",
            padding=(14, 6),
            borderwidth=0,
            relief="flat"
        )
        self.style.map(
            "Modern.TButton",
            background=[("active", hover)],
            relief=[("pressed", "sunken")]
        )

        self.style.configure(
            "Admin.Treeview",
            background=self.PAGE_BG,
            fieldbackground=self.PAGE_BG,
            foreground=self.TEXT_FG,
            rowheight=28,
            borderwidth=0
        )
        self.style.configure(
            "Admin.Treeview.Heading",
            font=FONTS.get("h6", ("Segoe UI Semibold", 10)),
            foreground=self.TEXT_FG,
            background=self.PAGE_BG
        )

    def _make_entry(self, parent, show: str | None = None) -> tk.Entry:
        e = tk.Entry(
            parent,
            bg=self.ENTRY_BG,
            fg=self.TEXT_FG,
            insertbackground=self.TEXT_FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#CBBFA7",
            highlightcolor="#0096C7",
            font=("Segoe UI", 10)
        )
        if show:
            e.config(show=show)
        e.bind("<FocusIn>", lambda _e: e.configure(bg="#FFFFFF"))
        e.bind("<FocusOut>", lambda _e: e.configure(bg=self.ENTRY_BG))
        return e

    def _build(self, root: tk.Frame):
        body = tk.Frame(root, bg=self.PAGE_BG)
        body.pack(fill="both", expand=True, pady=(6, 0))

        # — Add Admin form —
        c, inner = card(body, fg=self.CARD_BG, border_color="#DCCEB5", border_width=2)
        c.pack(fill="x", padx=16, pady=(10, 14))
        c.configure(fg_color=self.CARD_BG)  # FIXED: use configure(), not config()

        tk.Label(inner, text="Add Admin", font=("Segoe UI Semibold", 16),
                 bg=self.CARD_BG, fg="#222222").grid(row=0, column=0, sticky="w",
                                                     pady=(0, 15), columnspan=6)

        def label(txt, r, c):
            lbl = tk.Label(inner, text=txt, font=("Segoe UI", 10, "bold"),
                           bg=self.CARD_BG, fg="#333333")
            lbl.grid(row=r, column=c, sticky="e", padx=(0, 8))
            return lbl

        label("Admin Email", 1, 0)
        self.nu_email = self._make_entry(inner)
        self.nu_email.grid(row=1, column=1, sticky="ew", pady=6)

        label("Password", 1, 2)
        self.nu_pw = self._make_entry(inner, show="•")
        self.nu_pw.grid(row=1, column=3, sticky="ew", pady=6)

        label("Admin Name", 2, 0)
        self.nu_name = self._make_entry(inner)
        self.nu_name.grid(row=2, column=1, sticky="ew", pady=6)

        label("Confirm Password", 2, 2)
        self.nu_cpw = self._make_entry(inner, show="•")
        self.nu_cpw.grid(row=2, column=3, sticky="ew", pady=6)

        btn_bar = tk.Frame(inner, bg=self.CARD_BG)
        btn_bar.grid(row=3, column=3, columnspan=2, sticky="e", pady=(8, 0))

        self.btn_register = ttk.Button(btn_bar, text="Register",
                                       style="Modern.TButton", command=self._add_admin)
        self.btn_clear = ttk.Button(btn_bar, text="Clear",
                                    style="Modern.TButton", command=self._clear_add_form)
        self.btn_clear.pack(side="right", padx=(10, 0))
        self.btn_register.pack(side="right")

        self.nu_status = tk.Label(inner, text="", bg=self.CARD_BG, fg=self.TEXT_FG, font=("Segoe UI", 9))
        self.nu_status.grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))

        inner.grid_columnconfigure(1, weight=1)
        inner.grid_columnconfigure(3, weight=1)
        for e in (self.nu_email, self.nu_name, self.nu_pw, self.nu_cpw):
            e.bind("<Return>", lambda _e: self._add_admin())

        # — Admins table —
        tc, tin = card(body, fg=self.CARD_BG, border_color="#DCCEB5", border_width=2)
        tc.pack(fill="both", expand=True, padx=16, pady=(5, 10))
        tc.configure(fg_color=self.CARD_BG)

        tk.Label(tin, text="Users (Admins)", font=("Segoe UI Semibold", 14),
                 bg=self.CARD_BG, fg="#222222").pack(anchor="w", pady=(0, 10))

        cols = ("email", "name", "status", "created_at")
        self.users_tree = ttk.Treeview(
            tin, columns=cols, show="headings", height=12, style="Admin.Treeview", selectmode="none"
        )
        for c_name, h, w in zip(cols, ("Email", "Name", "Status", "Created At"),
                                 (300, 200, 110, 170)):
            self.users_tree.heading(c_name, text=h, anchor="w")
            self.users_tree.column(c_name, width=w, anchor="w", stretch=True)
        self.users_tree.pack(fill="both", expand=True, pady=(2, 0), padx=6)

        for ev in ("<Button-1>", "<ButtonRelease-1>", "<space>", "<Return>"):
            self.users_tree.bind(ev, lambda e: "break")

        self.users_tree.tag_configure("row", foreground=self.TEXT_FG, background=self.CARD_BG)
        self.users_tree.tag_configure("me", background=self.ACTIVE_ROW_BG, foreground="#FFFFFF")

        self._refresh_users_table()

    def _clear_add_form(self):
        for e in (self.nu_email, self.nu_name, self.nu_pw, self.nu_cpw):
            e.delete(0, "end")
        self.nu_status.configure(text="", foreground=self.TEXT_FG)

    def _refresh_users_table(self):
        tree = getattr(self, "users_tree", None)
        if not tree or not tree.winfo_exists():
            return
        for row in tree.get_children():
            tree.delete(row)

        cid_str = _current_company_id(self.controller)
        if not cid_str:
            messagebox.showerror("Users", "Missing company context.")
            return

        try:
            data = list_users(company_id=None)
            self._all_users_cache = data[:]
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load users: {e}")
            return

        me_email = _current_user_email(self.controller).lower().strip()

        def include(u: dict) -> bool:
            if (u.get("email", "") or "").lower() == (SUPERADMIN_EMAIL or "").lower():
                return False
            return str(u.get("company_id")) == cid_str and (u.get("role") or "").lower() in ("admin", "company_admin")

        for u in filter(include, data):
            email_val = (u.get("email", "") or "")
            is_me = email_val.strip().lower() == me_email
            tags = ("me",) if is_me else ("row",)
            iid = self.users_tree.insert(
                "", "end",
                values=(email_val, u.get("name", ""), u.get("status", "active"), _safe_ts_to_str(u.get("created_at"))),
                tags=tags
            )
            self.users_tree.item(iid, tags=tags)

        self.users_tree.selection_remove(self.users_tree.selection())
        self.users_tree.focus("")
        self.after_idle(lambda: (self.users_tree.selection_remove(self.users_tree.selection()),
                                 self.users_tree.focus("")))

    def _email_taken(self, email: str) -> bool:
        email_l = email.lower().strip()
        for u in self._all_users_cache:
            if (u.get("email", "") or "").lower().strip() == email_l:
                return True
        return False

    def _add_admin(self):
        email = (self.nu_email.get() or "").strip().lower()
        name = (self.nu_name.get() or "").strip()
        pw, cpw = self.nu_pw.get(), self.nu_cpw.get()

        def err(msg: str):
            self.nu_status.configure(text=msg, foreground="#b91c1c")

        if not email or not name or not pw or not cpw:
            return err("Please fill all fields.")
        if not EMAIL_RE.match(email):
            return err("Invalid email format.")
        if self._email_taken(email):
            return err("Email already registered.")
        if len(name) < 2:
            return err("Name too short.")
        problems = _password_issues(pw)
        if problems:
            return err("Password must have:\n" + "\n".join(problems))
        if pw != cpw:
            return err("Passwords do not match.")

        cid = _current_company_id(self.controller)
        if not cid:
            return err("Missing company context.")
        inviter = _current_user_email(self.controller)

        try:
            create_admin_user(inviter_email=inviter, company_id=cid, email=email, name=name, password=pw)
        except Exception as e:
            return err(str(e))

        self.nu_status.configure(text="Admin created successfully.", foreground="#15803d")
        self._clear_add_form()
        messagebox.showinfo("Success", f"Admin '{email}' created.")
        self._refresh_users_table()

    def destroy(self):
        self._stop_flag = True
        try:
            if self._bg_thread and self._bg_thread.is_alive():
                self._bg_thread.join(timeout=0.5)
        except Exception:
            pass
        super().destroy()
