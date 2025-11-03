# pages/profile.py
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
import re
from typing import List, Optional, Dict, Any

from services.ui_shell import PageShell               # CTk shell + persistent sidebar
from services.ui_theme import apply_theme, card, FONTS, PALETTE, badge
from services.session import require_user, get_current_user
from services.account import (
    get_profile,
    update_profile,
    change_password,
    start_password_reset,
    verify_password_reset,
    delete_account,
)
from services.firebase_client import get_db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ───────────────────────── helpers ─────────────────────────
def _pw_issues(pw: str) -> List[str]:
    problems: List[str] = []
    if len(pw) < 8: problems.append("• at least 8 characters")
    if not re.search(r"[a-z]", pw): problems.append("• a lowercase letter")
    if not re.search(r"[A-Z]", pw): problems.append("• an uppercase letter")
    if not re.search(r"[0-9]", pw): problems.append("• a number")
    if not re.search(r"[^A-Za-z0-9]", pw): problems.append("• a special character")
    return problems


def _lookup_company_name(company_id: str) -> str:
    if not company_id:
        return ""
    try:
        db = get_db()
        if not db:
            return ""
        snap = db.collection("companies").document(str(company_id)).get()
        if snap and getattr(snap, "exists", False):
            return str((snap.to_dict() or {}).get("name") or "")
    except Exception:
        pass
    return ""


def _company_display_name(controller, user: dict, prof: dict) -> str:
    name = getattr(controller, "current_company_name", "") or ""
    if name:
        return name
    for k in ("company_name", "company"):
        v = (user.get(k) or prof.get(k) or "")
        if v:
            return str(v)
    cid = str(user.get("company_id") or prof.get("company_id") or "").strip()
    return _lookup_company_name(cid) or (cid or "—")


# ───── bridge helpers (support multiple service signatures) ─────
def _bridge_update_profile(name: str, email: str) -> None:
    last = None
    try:
        return update_profile({"name": name, "email": email})  # type: ignore[arg-type]
    except Exception as e:
        last = e
    try:
        return update_profile(name=name, email=email)  # type: ignore[misc]
    except Exception as e:
        last = e
    try:
        return update_profile(name, email)  # type: ignore[misc]
    except Exception:
        raise last


def _bridge_change_password(email: str, old_pw: str, new_pw: str) -> None:
    last = None
    try:
        return change_password({"email": email, "old_password": old_pw, "new_password": new_pw})  # type: ignore[arg-type]
    except Exception as e:
        last = e
    try:
        return change_password(email=email, old_password=old_pw, new_password=new_pw)  # type: ignore[misc]
    except Exception as e:
        last = e
    try:
        return change_password(email, old_pw, new_pw)  # type: ignore[misc]
    except Exception:
        raise last


# ───────────────────────── callouts & small UI helpers ─────────────────────────
def _callout(parent, text: str, kind: str = "info"):
    colors = {
        "info":    {"bg": "#ecfeff", "fg": "#075985", "border": "#67e8f9"},
        "tip":     {"bg": "#eef2ff", "fg": "#3730a3", "border": "#c7d2fe"},
        "warning": {"bg": "#fffbeb", "fg": "#92400e", "border": "#fde68a"},
        "danger":  {"bg": "#fef2f2", "fg": "#7f1d1d", "border": "#fecaca"},
    }
    c = colors.get(kind, colors["info"])
    wrap = tk.Frame(parent, bg=c["bg"], highlightbackground=c["border"], highlightthickness=1)
    tk.Label(wrap, text=text, bg=c["bg"], fg=c["fg"], wraplength=560, justify="left").pack(
        padx=10, pady=8, anchor="w"
    )
    return wrap


# ───────────────────────── dialogs ─────────────────────────
class _BaseDialog(tk.Toplevel):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=PALETTE["bg"])
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        try: self.resizable(False, False)
        except Exception: pass
        apply_theme(self)

        # Dialog-local label styles with flat background (no gray pills)
        self._dlg_style = ttk.Style(self)
        self._dlg_style.configure("DialogKey.TLabel", background=PALETTE["card"], foreground="#333333",
                                  font=("Segoe UI", 10, "bold"))
        self._dlg_style.configure("DialogPlain.TLabel", background=PALETTE["card"], foreground="#333333",
                                  font=("Segoe UI", 10))
        # Button styles reused from page
        self._dlg_style.configure("Primary.TButton",
                                  font=("Segoe UI Semibold", 10), background="#1d4ed8",
                                  foreground="white", padding=(14, 6), borderwidth=0, relief="flat")
        self._dlg_style.map("Primary.TButton",
                            background=[("active", "#2563eb"), ("!disabled", "#1d4ed8")],
                            foreground=[("!disabled", "white")])
        self._dlg_style.configure("Accent.TButton",
                                  font=("Segoe UI Semibold", 10), background="#16a34a",
                                  foreground="white", padding=(10, 4), borderwidth=0, relief="flat")
        self._dlg_style.map("Accent.TButton",
                            background=[("active", "#22c55e"), ("!disabled", "#16a34a")],
                            foreground=[("!disabled", "white")])
        self._dlg_style.configure("Danger.TButton",
                                  font=("Segoe UI Semibold", 10), background="#dc2626",
                                  foreground="white", padding=(10, 4), borderwidth=0, relief="flat")
        self._dlg_style.map("Danger.TButton",
                            background=[("active", "#ef4444"), ("!disabled", "#dc2626")],
                            foreground=[("!disabled", "white")])

        outer, body = card(self)
        outer.pack(fill="both", expand=True, padx=12, pady=12)
        self.body = body

        tk.Label(self.body, text=title, font=FONTS["h3"], bg=PALETTE["card"])\
            .grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

    def _close(self):
        try: self.grab_release()
        except Exception: pass
        self.destroy()


class EditProfileDialog(_BaseDialog):
    def __init__(self, parent, name: str, email: str, on_saved):
        super().__init__(parent, "Edit Profile")
        self._on_saved = on_saved

        ttk.Label(self.body, text="Full Name", style="DialogKey.TLabel")\
            .grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.e_name = ttk.Entry(self.body); self.e_name.grid(row=1, column=1, sticky="ew", pady=4); self.e_name.insert(0, name)

        ttk.Label(self.body, text="Email", style="DialogKey.TLabel")\
            .grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        self.e_email = ttk.Entry(self.body); self.e_email.grid(row=2, column=1, sticky="ew", pady=4); self.e_email.insert(0, email)

        self.body.grid_columnconfigure(1, weight=1)
        self.status = ttk.Label(self.body, text="", style="DialogPlain.TLabel")
        self.status.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        btns = tk.Frame(self.body, bg=PALETTE["card"])
        btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", style="Danger.TButton", command=self._close).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Save", style="Primary.TButton", command=self._save).pack(side="right")

    def _save(self):
        name = (self.e_name.get() or "").strip()
        email = (self.e_email.get() or "").strip()
        if not name:
            self.status.configure(text="Name is required.", foreground=PALETTE.get("danger", "#b91c1c")); return
        if not email or not EMAIL_RE.match(email):
            self.status.configure(text="Valid email is required.", foreground=PALETTE.get("danger", "#b91c1c")); return
        try:
            _bridge_update_profile(name, email)
        except Exception as e:
            self.status.configure(text=str(e), foreground=PALETTE.get("danger", "#b91c1c")); return
        messagebox.showinfo("Profile", "Profile updated.")
        if callable(self._on_saved): self._on_saved()
        self._close()


class ChangePasswordDialog(_BaseDialog):
    def __init__(self, parent, current_email: str):
        super().__init__(parent, "Change Password")
        self._email = current_email

        ttk.Label(self.body, text="Current Password", style="DialogKey.TLabel")\
            .grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        ttk.Label(self.body, text="New Password", style="DialogKey.TLabel")\
            .grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        ttk.Label(self.body, text="Confirm New", style="DialogKey.TLabel")\
            .grid(row=3, column=0, sticky="e", padx=(0, 8), pady=4)

        self.pw_old = ttk.Entry(self.body, show="•"); self.pw_old.grid(row=1, column=1, sticky="ew", pady=4)
        self.pw_new = ttk.Entry(self.body, show="•"); self.pw_new.grid(row=2, column=1, sticky="ew", pady=4)
        self.pw_cnf = ttk.Entry(self.body, show="•"); self.pw_cnf.grid(row=3, column=1, sticky="ew", pady=4)

        self.body.grid_columnconfigure(1, weight=1)
        self.status = ttk.Label(self.body, text="", style="DialogPlain.TLabel")
        self.status.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        btns = tk.Frame(self.body, bg=PALETTE["card"])
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", style="Danger.TButton", command=self._close).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Update Password", style="Primary.TButton", command=self._save).pack(side="right")

    def _save(self):
        old_pw = self.pw_old.get()
        new_pw = self.pw_new.get()
        cnf_pw = self.pw_cnf.get()

        def err(msg): self.status.configure(text=msg, foreground=PALETTE.get("danger", "#b91c1c"))

        if not old_pw or not new_pw or not cnf_pw: return err("Please fill all fields.")
        if new_pw != cnf_pw: return err("New passwords do not match.")
        issues = _pw_issues(new_pw)
        if issues: return err("Password must have:\n" + "\n".join(issues))
        try:
            _bridge_change_password(self._email, old_pw, new_pw)
        except Exception as e:
            return err(str(e))
        messagebox.showinfo("Password", "Password changed successfully.")
        self._close()


class ResetPasswordDialog(_BaseDialog):
    def __init__(self, parent, email_default: str):
        super().__init__(parent, "Reset Password (OTP)")
        self._otp_sent = False

        ttk.Label(self.body, text="Send OTP to", style="DialogKey.TLabel")\
            .grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.r_email = ttk.Entry(self.body); self.r_email.grid(row=1, column=1, sticky="ew", pady=4); self.r_email.insert(0, email_default)
        self.btn_send = ttk.Button(self.body, text="Send OTP", style="Accent.TButton", command=self._send_otp)
        self.btn_send.grid(row=1, column=2, sticky="w", padx=(8, 0))

        ttk.Label(self.body, text="OTP Code", style="DialogKey.TLabel")\
            .grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        self.r_otp = ttk.Entry(self.body); self.r_otp.grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(self.body, text="New Password", style="DialogKey.TLabel")\
            .grid(row=3, column=0, sticky="e", padx=(0, 8), pady=4)
        self.r_new = ttk.Entry(self.body, show="•"); self.r_new.grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(self.body, text="Confirm New", style="DialogKey.TLabel")\
            .grid(row=4, column=0, sticky="e", padx=(0, 8), pady=4)
        self.r_cnf = ttk.Entry(self.body, show="•"); self.r_cnf.grid(row=4, column=1, sticky="ew", pady=4)

        self.body.grid_columnconfigure(1, weight=1)
        self.status = ttk.Label(self.body, text="", style="DialogPlain.TLabel")
        self.status.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

        btns = tk.Frame(self.body, bg=PALETTE["card"])
        btns.grid(row=6, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", style="Danger.TButton", command=self._close).pack(side="right", padx=(8, 0))
        self.btn_apply = ttk.Button(btns, text="Apply Reset", style="Primary.TButton",
                                    command=self._apply_reset, state="disabled")
        self.btn_apply.pack(side="right")

        for w in (self.r_otp, self.r_new, self.r_cnf):
            w.configure(state="disabled")

    def _send_otp(self):
        email = (self.r_email.get() or "").strip()
        if not email or not EMAIL_RE.match(email):
            self.status.configure(text="Enter a valid email to send OTP.", foreground=PALETTE.get("danger", "#b91c1c")); return
        try:
            start_password_reset(email)
        except Exception as e:
            self.status.configure(text=str(e), foreground=PALETTE.get("danger", "#b91c1c")); return

        self._otp_sent = True
        for w in (self.r_otp, self.r_new, self.r_cnf):
            w.configure(state="normal")
        self.btn_apply.configure(state="normal")
        self.status.configure(text="OTP sent. Check your email.", foreground=PALETTE.get("ok", "#15803d"))

    def _apply_reset(self):
        if not self._otp_sent:
            self.status.configure(text="Send an OTP first.", foreground=PALETTE.get("danger", "#b91c1c")); return
        email = (self.r_email.get() or "").strip()
        otp = (self.r_otp.get() or "").strip()
        new_pw = self.r_new.get()
        cnf_pw = self.r_cnf.get()

        def err(msg): self.status.configure(text=msg, foreground=PALETTE.get("danger", "#b91c1c"))

        if not email or not EMAIL_RE.match(email): return err("Valid email required.")
        if not otp: return err("Enter the OTP code.")
        if not new_pw or not cnf_pw: return err("Enter new password and confirm.")
        if new_pw != cnf_pw: return err("New passwords do not match.")
        issues = _pw_issues(new_pw)
        if issues: return err("Password must have:\n" + "\n".join(issues))
        try:
            verify_password_reset(email, otp, new_pw)
        except Exception as e:
            return err(str(e))
        messagebox.showinfo("Password", "Password reset successfully.")
        self._close()


class DeleteAccountDialog(_BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, "Delete Account")
        ttk.Label(self.body, text='Type "DELETE" to confirm', style="DialogKey.TLabel")\
            .grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.e_confirm = ttk.Entry(self.body, width=18); self.e_confirm.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(self.body, text='Password', style="DialogKey.TLabel")\
            .grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        self.e_pw = ttk.Entry(self.body, show="•"); self.e_pw.grid(row=2, column=1, sticky="ew", pady=4)

        self.body.grid_columnconfigure(1, weight=1)
        btns = tk.Frame(self.body, bg=PALETTE["card"])
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", style="Danger.TButton", command=self._close).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Delete", style="Primary.TButton", command=self._delete).pack(side="right")

    def _delete(self):
        if (self.e_confirm.get() or "").strip().upper() != "DELETE":
            messagebox.showwarning("Delete", 'Type "DELETE" to confirm.'); return
        pw = self.e_pw.get()
        if not pw:
            messagebox.showwarning("Delete", "Enter your password."); return
        if not messagebox.askyesno("Delete", "This action is permanent. Delete your account?"):
            return
        try:
            delete_account(pw)
        except Exception as e:
            messagebox.showerror("Delete", str(e)); return
        messagebox.showinfo("Deleted", "Your account has been deleted.")
        try:
            self.master.master.controller.logout()
        except Exception:
            pass
        self._close()


# ───────────────────────── Page ─────────────────────────
class ProfilePage(PageShell):
    """
    Always uses PageShell so the sidebar/header persist on all roles.
    Accepts optional `user=` kwarg to be compatible with App._swap_to(..., user=...).
    """

    # Match AddAdmin page theme
    PAGE_BG = "#E6D8C3"
    TEXT_FG = "#000000"
    CARD_BG = "#EFE3D0"

    def __init__(self, parent, controller, user: Optional[Dict[str, Any]] = None, **_):
        super().__init__(parent, controller, title="Profile", active_key="profile")
        self.controller = controller
        self.user = user or get_current_user() or {}

        apply_theme(self)
        self._apply_page_theme_overrides()
        self._init_styles()

        # Build UI inside the shell's content
        self._build(self.content)
        self._refresh()

        # refresh on show
        try:
            self.bind("<Visibility>", lambda _e: self._refresh())
        except Exception:
            pass

    # ── AddAdmin-like theming ──
    def _apply_page_theme_overrides(self):
        try:
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

    def _init_styles(self):
        try:
            ttk.Style().theme_use("clam")
        except Exception:
            pass

        self.style = ttk.Style(self)

        # Primary (blue)
        self.style.configure(
            "Primary.TButton",
            font=("Segoe UI Semibold", 10),
            background="#1d4ed8",
            foreground="white",
            padding=(14, 6),
            borderwidth=0,
            relief="flat",
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", "#2563eb"), ("!disabled", "#1d4ed8")],
            foreground=[("!disabled", "white")],
            relief=[("pressed", "sunken")],
        )
        # Accent (green) — used for Send OTP
        self.style.configure(
            "Accent.TButton",
            font=("Segoe UI Semibold", 10),
            background="#16a34a",
            foreground="white",
            padding=(10, 4),
            borderwidth=0,
            relief="flat",
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", "#22c55e"), ("!disabled", "#16a34a")],
            foreground=[("!disabled", "white")],
        )
        # Danger (red) — used for Cancel
        self.style.configure(
            "Danger.TButton",
            font=("Segoe UI Semibold", 10),
            background="#dc2626",
            foreground="white",
            padding=(10, 4),
            borderwidth=0,
            relief="flat",
        )
        self.style.map(
            "Danger.TButton",
            background=[("active", "#ef4444"), ("!disabled", "#dc2626")],
            foreground=[("!disabled", "white")],
        )

        # Value labels (right column)
        self.style.configure(
            "Muted.TLabel",
            background=self.CARD_BG,
            foreground="#333333",
            font=("Segoe UI", 10),
        )
        # Keys (left column) with no pill bg
        self.style.configure(
            "Key.TLabel",
            background=self.CARD_BG,
            foreground="#333333",
            font=("Segoe UI", 10, "bold"),
        )

    def _build(self, root: tk.Frame):
        # Header card
        hc, hv = card(root, fg=self.CARD_BG, border_color="#DCCEB5", border_width=2, pad=(16, 12))
        hc.pack(fill="x", pady=(8, 10))
        hc.configure(fg_color=self.CARD_BG)

        avatar = tk.Frame(hv, bg="#eef2ff"); avatar.pack(side="left")
        tk.Label(avatar, text="👤", bg="#eef2ff", font=("Segoe UI Emoji", 22)).pack(padx=14, pady=6)

        meta = tk.Frame(hv, bg=self.CARD_BG); meta.pack(side="left", padx=(12, 0), fill="x", expand=True)
        self.lbl_display = tk.Label(meta, text="", font=("Segoe UI", 18, "bold"), bg=self.CARD_BG, fg="#222222")
        self.lbl_display.pack(anchor="w")

        row = tk.Frame(meta, bg=self.CARD_BG); row.pack(anchor="w", pady=(4, 0))
        self.lbl_email = ttk.Label(row, text="", style="Muted.TLabel"); self.lbl_email.pack(side="left")

        self.badge_role = badge(meta, "Role", fg="#6d28d9", bg="#f3e8ff")
        self.badge_role.pack(side="left", padx=(8, 8), pady=(8, 0))
        self.badge_company = badge(meta, "Company", fg="#1d4ed8", bg="#e8f0ff")
        self.badge_company.pack(side="left", pady=(8, 0))

        # Body
        body = tk.Frame(root, bg=self.PAGE_BG); body.pack(fill="both", expand=True)

        acc_card, acc = card(body, fg=self.CARD_BG, border_color="#DCCEB5", border_width=2)
        acc_card.pack(side="left", fill="both", expand=True, padx=(0, 8))
        acc_card.configure(fg_color=self.CARD_BG)

        tk.Label(acc, text="Account Details", font=FONTS["h3"], bg=self.CARD_BG, fg="#222222").pack(anchor="w", pady=(0, 8))
        _callout(
            acc,
            "These details are visible to system administrators and are used for audit logs and notifications. "
            "Keep them accurate so your actions can be traced to the right person.",
            kind="tip",
        ).pack(fill="x", pady=(0, 10))

        grid = tk.Frame(acc, bg=self.CARD_BG); grid.pack(fill="x")

        def kv(r, label_text):
            lab = ttk.Label(grid, text=label_text, style="Key.TLabel")
            lab.grid(row=r, column=0, sticky="e", padx=(0, 10), pady=4)
            val = ttk.Label(grid, text="", style="Muted.TLabel")
            val.grid(row=r, column=1, sticky="w", pady=4)
            return lab, val

        self.kv_email_label, self.kv_email     = kv(0, "Email")
        self.kv_role_label, self.kv_role       = kv(1, "Role")
        self.kv_company_label, self.kv_company = kv(2, "Company")
        grid.grid_columnconfigure(1, weight=1)

        btns = tk.Frame(acc, bg=self.CARD_BG)
        btns.pack(anchor="e", fill="x", pady=(10, 0))
        ttk.Button(btns, text="Edit Profile", style="Primary.TButton", command=self._open_edit)\
            .pack(side="right")

        sec_card, sec = card(body, fg=self.CARD_BG, border_color="#DCCEB5", border_width=2)
        sec_card.pack(side="left", fill="both", expand=True, padx=(8, 0))
        sec_card.configure(fg_color=self.CARD_BG)

        tk.Label(sec, text="Security", font=FONTS["h3"], bg=self.CARD_BG, fg="#222222").pack(anchor="w", pady=(0, 8))
        _callout(
            sec,
            "Use a strong, unique password for CompliGuard. Avoid reusing passwords from other systems.",
            kind="info",
        ).pack(fill="x", pady=(0, 10))

        ttk.Label(sec, text="Password Management", style="Muted.TLabel").pack(anchor="w")
        sec_btns = tk.Frame(sec, bg=self.CARD_BG); sec_btns.pack(fill="x", pady=(6, 10))
        ttk.Button(sec_btns, text="Change Password", style="Primary.TButton", command=self._open_change_pw).pack(side="left")

        ttk.Separator(sec, orient="horizontal").pack(fill="x", pady=8)

        ttk.Label(sec, text="Forgot your password? Reset with a one-time code sent to your email.", style="Muted.TLabel")\
            .pack(anchor="w")
        ttk.Button(sec, text="Reset Password (OTP)", style="Primary.TButton", command=self._open_reset_pw)\
            .pack(anchor="w", pady=(6, 0))

        ttk.Separator(sec, orient="horizontal").pack(fill="x", pady=10)

        _callout(
            sec,
            "Danger zone: Deleting your account removes access immediately and cannot be undone.",
            kind="danger",
        ).pack(fill="x", pady=(0, 8))
        ttk.Button(sec, text="Delete Account", style="Primary.TButton", command=self._open_delete)\
            .pack(anchor="w")

        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

    def _refresh(self):
        try:
            user = require_user() or {}
        except Exception as e:
            messagebox.showerror("Profile", f"No session: {e}")
            return
        try:
            prof = get_profile() or {}
        except Exception:
            prof = {}

        name = prof.get("name") or user.get("name") or ""
        email = prof.get("email") or user.get("email") or ""
        role_raw = (prof.get("role") or user.get("role") or "")
        role = (role_raw or "").replace("_", " ").title()
        is_super = (role_raw or "").strip().lower() == "superadmin"

        self.lbl_display.configure(text=name or email or "Your account")
        self.lbl_email.configure(text=email or "—")
        self.badge_role.configure(text=role or "—")

        if is_super:
            try:
                self.badge_company.pack_forget()
            except Exception:
                pass
            self.kv_company_label.grid_remove()
            self.kv_company.grid_remove()
        else:
            comp = _company_display_name(self.controller, user, prof)
            self.kv_company_label.grid()
            self.kv_company.grid()
            self.badge_company.configure(text=comp or "—")
            self.kv_company.configure(text=comp or "—")

        self.kv_email.configure(text=email or "—")
        self.kv_role.configure(text=role or "—")

        self._name = name
        self._email = email

    def _on_profile_saved(self):
        self._refresh()
        try:
            prof = get_profile() or {}
        except Exception:
            prof = {}
        try:
            if hasattr(self.controller, "current_user_email"):
                self.controller.current_user_email = prof.get("email") or getattr(self.controller, "current_user_email", "")
        except Exception:
            pass
        try:
            if hasattr(self.controller, "notify_profile_updated") and callable(self.controller.notify_profile_updated):
                self.controller.notify_profile_updated()
        except Exception:
            pass

    # modal openers
    def _open_edit(self): EditProfileDialog(self, getattr(self, "_name", ""), getattr(self, "_email", ""), on_saved=self._on_profile_saved)
    def _open_change_pw(self): ChangePasswordDialog(self, getattr(self, "_email", ""))
    def _open_reset_pw(self): ResetPasswordDialog(self, getattr(self, "_email", ""))
    def _open_delete(self): DeleteAccountDialog(self)
