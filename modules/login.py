# modules/login.py
import os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Optional

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from pages.register_company import RegisterCompanyPage
from pages.forgot_password import ForgotPasswordPage  # <-- external page
from services.firebase_auth import authenticate_email_password, company_block_reason_for
from services.session import set_current_user
from services.async_ui import run_async  # non-blocking auth
from services.firebase_client import get_db  # <-- NEW

# optional icons (mail, lock, eye-open, eye-closed, etc.)
try:
    from services.ui_assets import get_icon
except Exception:
    def get_icon(_name: str, _size: int):
        return None

# optional PIL for logo
try:
    from PIL import Image, ImageTk
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False


def _card_bg_of(ctk_inner) -> str:
    """Read inner card color; fall back to palette card."""
    try:
        c = ctk_inner.cget("fg_color")
        if isinstance(c, (list, tuple)):
            return c[0]
        return c or PALETTE["card"]
    except Exception:
        return PALETTE["card"]


def _load_logo(max_w: int = 140, max_h: int = 140) -> Optional[tk.PhotoImage]:
    """
    Try to load the company logo image from data/ui/logos/logo.*
    Falls back to the D:\CompliGuardApp path you showed.
    Returns a PhotoImage or None.
    """
    candidates = [
        os.path.join("data", "ui", "logos", "logo.png"),
        os.path.join("data", "ui", "logos", "logo.jpg"),
        os.path.join("data", "ui", "logos", "logo.jpeg"),
        os.path.join("data", "ui", "logos", "logo.gif"),
        r"D:\CompliGuardApp\data\ui\logos\logo.png",
        r"D:\CompliGuardApp\data\ui\logos\logo.jpg",
        r"D:\CompliGuardApp\data\ui\logos\logo.jpeg",
        r"D:\CompliGuardApp\data\ui\logos\logo.gif",
    ]

    if not _HAVE_PIL:
        return None

    for p in candidates:
        if os.path.exists(p):
            try:
                img = Image.open(p)
                img.thumbnail((max_w, max_h))
                return ImageTk.PhotoImage(img)
            except Exception:
                pass
    return None


class LoginPage(tk.Frame):
    """
    Centered login with:
      • Bigger logo
      • Title + Welcome Back
      • Wider card
      • Clean inputs with icons + eye toggle for password
      • "Forgot password?" link
      • Primary Sign In button
      • Secondary 'Register a company' CTA
      • Inline status for errors
    """
    def __init__(self, parent, controller, auth=None):
        super().__init__(parent, bg=PALETTE["bg"])
        self.controller = controller
        self._busy = False

        self.email_var = tk.StringVar()
        self.pw_var = tk.StringVar()

        # keep icon refs on self so they don't get GC'ed
        self._eye_show = get_icon("show", 18)
        self._eye_hide = get_icon("hide", 18)
        self._mail_icn = get_icon("mail", 16)
        self._lock_icn = get_icon("lock", 16)

        # also keep logo ref
        self._logo_img = _load_logo()

        apply_theme(self)
        self._build()

    # ---------------- UI ----------------
    def _build(self):
        # full bg frame
        root = tk.Frame(self, bg=PALETTE["bg"])
        root.pack(fill="both", expand=True)

        # centered wrapper
        wrap = tk.Frame(root, bg=PALETTE["bg"])
        wrap.place(relx=0.5, rely=0.5, anchor="center")

        # Logo (if available)
        if self._logo_img is not None:
            tk.Label(
                wrap,
                image=self._logo_img,
                bg=PALETTE["bg"],
            ).pack(anchor="center", pady=(0, 12))

        # App name
        tk.Label(
            wrap,
            text="CompliGuard",
            bg=PALETTE["bg"],
            fg=PALETTE["text"],
            font=("Segoe UI", 26, "bold"),
        ).pack(anchor="center", pady=(0, 4))

        # Welcome text
        tk.Label(
            wrap,
            text="Welcome Back!",
            bg=PALETTE["bg"],
            fg=PALETTE["text"],
            font=FONTS["h1"],
        ).pack(anchor="center", pady=(0, 16))

        # Card form (wider)
        card_fr, inner = card(wrap, pad=(24, 20))

        # make card wider but let it auto-height
        try:
            card_fr.configure(width=460)
        except Exception:
            try:
                card_fr.config(width=460)
            except Exception:
                pass

        card_fr.pack(anchor="center", fill="x", pady=(0, 0))

        inner.grid_columnconfigure(0, weight=1, minsize=400)
        card_bg = _card_bg_of(inner)

        # Email label
        tk.Label(
            inner,
            text="Email",
            bg=card_bg,
            fg=PALETTE["text"],
            font=FONTS["body"],
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        # Email row (icon + entry)
        email_row = _input_with_icon(
            inner,
            icon_img=self._mail_icn,
            fallback_icon="✉",
            var=self.email_var,
            is_password=False,
            eye_imgs=None,
            card_bg=card_bg,
        )
        email_row.grid(row=1, column=0, sticky="ew")

        # Header row: "Password" left, "Forgot password?" right
        hdr = tk.Frame(inner, bg=card_bg)
        hdr.grid(row=2, column=0, sticky="ew", pady=(12, 6))
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)

        tk.Label(
            hdr,
            text="Password",
            bg=card_bg,
            fg=PALETTE["text"],
            font=FONTS["body"],
        ).grid(row=0, column=0, sticky="w")

        # "Forgot password?" link
        link_fg = PALETTE.get("link", "#2563EB")
        forgot_btn = tk.Button(
            hdr,
            text="Forgot password?",
            command=self._go_forgot,
            bg=card_bg,
            activebackground=card_bg,
            fg=link_fg,
            activeforeground=link_fg,
            bd=0,
            relief="flat",
            highlightthickness=0,
            font=(FONTS["body"][0], FONTS["body"][1], "underline"),
            cursor="hand2",
        )
        forgot_btn.grid(row=0, column=1, sticky="e")

        # Password row (icon + entry + eye)
        pwd_row = _input_with_icon(
            inner,
            icon_img=self._lock_icn,
            fallback_icon="🔒",
            var=self.pw_var,
            is_password=True,
            eye_imgs=(self._eye_show, self._eye_hide),
            card_bg=card_bg,
        )
        pwd_row.grid(row=3, column=0, sticky="ew")

        # Inline status (errors/progress)
        self.status = tk.Label(
            inner,
            text="",
            bg=card_bg,
            fg=PALETTE.get("danger", "#b91c1c"),
            font=FONTS["body"],
        )
        self.status.grid(row=4, column=0, sticky="w", pady=(10, 0))

        # Sign In button (full width)
        btn_row = tk.Frame(inner, bg=card_bg)
        btn_row.grid(row=5, column=0, sticky="ew", pady=(14, 0))

        self.signin_btn = ttk.Button(
            btn_row,
            text="Sign In",
            style="Primary.TButton",
            command=self._on_login,
        )
        self.signin_btn.pack(fill="x")

        # "Register a company" CTA
        _setup_cta_style(self)  # defines CTA.TButton style
        ttk.Button(
            wrap,
            text="Register a company",
            style="CTA.TButton",
            command=self._go_register,
        ).pack(anchor="center", pady=(16, 0))

        # Enter key triggers login
        email_row._entry.bind("<Return>", lambda _e: self._on_login())
        pwd_row._entry.bind("<Return>", lambda _e: self._on_login())

        # focus email first
        self.after(50, email_row._entry.focus_set)

    # ---------------- helpers/events ----------------
    def _set_busy(self, busy: bool, msg: str = ""):
        self._busy = busy
        try:
            self.signin_btn.configure(state=("disabled" if busy else "normal"))
        except Exception:
            try:
                self.signin_btn.config(state=("disabled" if busy else "normal"))
            except Exception:
                pass
        self.status.config(text=msg)

    def _on_login(self):
        if self._busy:
            return

        email = (self.email_var.get() or "").strip().lower()
        pw = (self.pw_var.get() or "").strip()

        if not email or not pw:
            self.status.config(text="Please enter both email and password.")
            return

        self._set_busy(True, "Signing in…")

        # --- run auth in background (non-blocking UI) ---
        def _work() -> Dict:
            """
            RETURN normalized user dict:
              {
                email,
                name,
                role,
                company_id,
                company_name,   # <--- we now fill this from Firestore
                active
              }

            Raises ValueError on bad creds or suspended company.
            """
            user = authenticate_email_password(email, pw)
            if not user:
                raise ValueError("Invalid email or password.")

            # block if company suspended (unless maybe superadmin, handled in company_block_reason_for)
            reason = company_block_reason_for(user)
            if reason:
                raise ValueError(reason)

            # figure out readable company name
            company_id = user.get("company_id")
            company_name_resolved = ""

            if company_id:
                try:
                    db = get_db()
                    doc = db.collection("companies").document(str(company_id)).get()
                    if doc.exists:
                        cdata = doc.to_dict() or {}
                        # pick best available field (customize this if your companies doc uses different field names)
                        company_name_resolved = (
                            cdata.get("name")
                            or cdata.get("company_name")
                            or cdata.get("display_name")
                            or cdata.get("site_name")
                            or str(company_id)
                        )
                except Exception:
                    # fail quietly, just leave company_name_resolved = ""
                    pass

            # fallback: if user dict already had something set for company_name
            if not company_name_resolved:
                company_name_resolved = (
                    user.get("company_name", "")
                    or str(company_id or "")
                )

            norm = {
                "email": (user.get("email") or email).lower(),
                "name": user.get("name", "") or email,
                "role": user.get("role", "admin"),
                "company_id": company_id,
                "company_name": company_name_resolved,
                "active": user.get("active", True),
            }
            return norm

        def _done(result: Dict | Exception):
            if isinstance(result, Exception):
                self._set_busy(False, "")
                # popup + inline status
                try:
                    messagebox.showerror("Sign in failed", str(result))
                except Exception:
                    pass
                self.status.config(text=str(result))
                return

            norm = result
            if not norm.get("active", True):
                self._set_busy(False, "")
                self.status.config(
                    text="Your account is disabled. Contact your company admin."
                )
                return

            # save session (used by LogsPage, WhatsApp message, etc.)
            try:
                set_current_user(norm)
            except Exception:
                pass

            # clear pw field
            self.pw_var.set("")

            # navigate to dashboard
            try:
                self.controller.show_dashboard(norm)
            finally:
                self._set_busy(False, "")

        run_async(_work, _done, self)

    def _go_register(self):
        # swap login page -> register company page
        for w in self.master.winfo_children():
            w.destroy()
        page = RegisterCompanyPage(self.master, controller=self.controller)
        page.pack(fill="both", expand=True)

    def _go_forgot(self):
        # swap login page -> forgot password page
        for w in self.master.winfo_children():
            w.destroy()
        ForgotPasswordPage(self.master, controller=self.controller).pack(
            fill="both", expand=True
        )


# ─────────────────────────────────────────
# Small UI helper (icon + entry with optional eye icons)
# ─────────────────────────────────────────
def _input_with_icon(
    parent,
    icon_img,               # PhotoImage or None
    fallback_icon: str,     # e.g. "✉" / "🔒"
    var: tk.StringVar,
    is_password: bool = False,
    eye_imgs: Optional[tuple] = None,   # (eye_open, eye_closed)
    card_bg: Optional[str] = None
):
    """
    A bordered row with a leading icon and a ttk.Entry.
    Returns the row frame with `_entry` attribute (for focus/Return binding).
    """
    card_bg = card_bg or PALETTE["card"]

    row = tk.Frame(parent, bg=card_bg)

    border = tk.Frame(
        row,
        bg=card_bg,
        highlightbackground=PALETTE["border"],
        highlightthickness=1,
        bd=0,
    )
    border.pack(fill="x")

    inner = tk.Frame(border, bg=card_bg)
    inner.pack(fill="x")

    if icon_img is not None:
        tk.Label(
            inner,
            image=icon_img,
            bg=card_bg,
        ).pack(side="left", padx=(10, 8), pady=6)
    else:
        tk.Label(
            inner,
            text=fallback_icon,
            bg=card_bg,
            fg=PALETTE["muted"],
            font=("Segoe UI Emoji", 12),
        ).pack(side="left", padx=(10, 8), pady=6)

    entry = ttk.Entry(inner, textvariable=var, show=("•" if is_password else ""))
    entry.pack(side="left", fill="x", expand=True, ipady=4, pady=4)

    # Eye icon toggle
    if is_password:
        eye_open, eye_closed = (eye_imgs or (None, None))
        state = {"visible": False}

        def _apply_eye():
            entry.config(show=("" if state["visible"] else "•"))
            if btn_img is not None:
                if state["visible"] and eye_closed:
                    btn.config(image=eye_closed)
                elif (not state["visible"]) and eye_open:
                    btn.config(image=eye_open)
            else:
                # fallback emoji if you don't have icons
                btn.config(text=("🫣" if state["visible"] else "👁"))

        def _toggle():
            state["visible"] = not state["visible"]
            _apply_eye()

        btn_img = eye_open or eye_closed
        btn = tk.Button(
            inner,
            image=(btn_img if btn_img else None),
            text=("👁" if not btn_img else " "),
            compound="left",
            command=_toggle,
            bg=card_bg,
            activebackground=card_bg,
            bd=0,
            relief="flat",
            highlightthickness=0,
            padx=6,
            pady=2,
            cursor="hand2",
        )
        btn.pack(side="right", padx=8)
        _apply_eye()

    row._entry = entry  # type: ignore[attr-defined]
    return row


def _setup_cta_style(widget: tk.Misc):
    """
    Create a modern accent button style (different from Primary.TButton)
    for 'Register a company'.
    We'll try PALETTE['accent'] first. If not there, fallback to teal-ish.
    """
    style = ttk.Style(widget)

    accent_bg = PALETTE.get("accent", "#0D9488")           # teal
    accent_hover = PALETTE.get("accent_hover", "#0B766B")  # darker teal

    style.configure(
        "CTA.TButton",
        font=FONTS["body"],
        padding=(14, 9),
        background=accent_bg,
        foreground="#FFFFFF",
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "CTA.TButton",
        background=[("active", accent_hover), ("pressed", accent_hover)],
        foreground=[("disabled", "#FFFFFF")],
    )
