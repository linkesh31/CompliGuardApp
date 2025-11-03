# pages/register_company.py
import re
import tkinter as tk
from tkinter import ttk, messagebox

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.firebase_registration import (
    begin_company_registration,
    confirm_company_registration,
    resend_company_otp,
)
from services.ui_assets import get_icon  # eye icons

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _card_bg_of(ctk_inner) -> str:
    """Read CTk inner frame color (fg_color) and fall back to palette card."""
    try:
        c = ctk_inner.cget("fg_color")
        if isinstance(c, (list, tuple)):
            return c[0]
        return c or PALETTE["card"]
    except Exception:
        return PALETTE["card"]


class RegisterCompanyPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg=PALETTE["bg"])
        self.controller = controller

        # state
        self.reg_id = None
        self.cooldown = 0
        self._show_pw = False
        self._show_cpw = False

        # widgets we toggle
        self.register_btn = None
        self.resend_btn = None
        self.status = None
        self.status2 = None
        self.otp_entry = None

        # icon images (keep refs on self so they don't get GC'd)
        self._eye_show = get_icon("show", 18)
        self._eye_hide = get_icon("hide", 18)

        # eye buttons
        self.pw_eye_btn = None
        self.cpw_eye_btn = None

        apply_theme(self)
        self._build_step1()

    # ───────────────────────── common ─────────────────────────
    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    def _back_to_login(self):
        if hasattr(self.controller, "_show_login"):
            self.controller._show_login()

    # ───────────────────────── Step 1 ─────────────────────────
    def _build_step1(self):
        self._clear()

        # RED accent style for Back button
        style = ttk.Style(self)
        red = PALETTE.get("danger", "#B91C1C")
        red_hover = "#991B1B"  # darker red on hover/press
        style.configure(
            "BackAccent.TButton",
            font=FONTS["body"],
            padding=(12, 7),
            background=red,
            foreground="#FFFFFF",
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "BackAccent.TButton",
            background=[("active", red_hover), ("pressed", red_hover)],
            foreground=[("disabled", "#FFFFFF")]
        )

        # Top bar
        top = tk.Frame(self, bg=PALETTE["bg"]); top.pack(fill="x")
        ttk.Button(top, text="← Back to Login", style="BackAccent.TButton",
                   command=self._back_to_login)\
            .pack(anchor="w", padx=8, pady=(12, 6))

        # Title + subtitle
        tk.Label(self, text="Register Company", font=FONTS["h2"], bg=PALETTE["bg"])\
            .pack(anchor="w", padx=16, pady=(2, 0))
        ttk.Label(self, text="Create a company account and the first admin user.",
                  style="Muted.TLabel").pack(anchor="w", padx=16, pady=(0, 8))

        # Card
        c, inner = card(self)
        c.pack(padx=12, pady=10, fill="x")

        card_bg = _card_bg_of(inner)
        content = tk.Frame(inner, bg=card_bg)
        content.pack(fill="x", expand=True)

        for i in range(4):
            content.grid_columnconfigure(i, weight=1)

        # Left column
        tk.Label(content, text="Company Name", bg=card_bg, fg=PALETTE["text"], font=FONTS["body"])\
            .grid(row=0, column=0, sticky="w")
        self.c_name = ttk.Entry(content)
        self.c_name.grid(row=1, column=0, sticky="ew", padx=(0, 18), pady=(0, 12))

        tk.Label(content, text="Admin Name", bg=card_bg, fg=PALETTE["text"], font=FONTS["body"])\
            .grid(row=2, column=0, sticky="w")
        self.a_name = ttk.Entry(content)
        self.a_name.grid(row=3, column=0, sticky="ew", padx=(0, 18), pady=(0, 12))

        # Right column
        tk.Label(content, text="Admin Email", bg=card_bg, fg=PALETTE["text"], font=FONTS["body"])\
            .grid(row=0, column=2, sticky="w")
        self.email = ttk.Entry(content)
        self.email.grid(row=1, column=2, columnspan=2, sticky="ew", pady=(0, 12))

        # Password row with eye toggle
        tk.Label(content, text="Password", bg=card_bg, fg=PALETTE["text"], font=FONTS["body"])\
            .grid(row=2, column=2, sticky="w")
        pw_row = tk.Frame(content, bg=card_bg)
        pw_row.grid(row=3, column=2, sticky="ew", pady=(0, 12))
        pw_row.grid_columnconfigure(0, weight=1)

        self.pw = ttk.Entry(pw_row, show="•")
        self.pw.grid(row=0, column=0, sticky="ew")

        self.pw_eye_btn = tk.Button(
            pw_row,
            image=(self._eye_show if self._eye_show else None),
            text=(" " if self._eye_show else "Show"),
            compound="left",
            command=self._toggle_pw,
            bg=card_bg, activebackground=card_bg,
            bd=0, relief="flat", highlightthickness=0, padx=6, pady=2
        )
        self.pw_eye_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))

        # Confirm password row with eye toggle
        tk.Label(content, text="Confirm Password", bg=card_bg, fg=PALETTE["text"], font=FONTS["body"])\
            .grid(row=2, column=3, sticky="w")
        cpw_row = tk.Frame(content, bg=card_bg)
        cpw_row.grid(row=3, column=3, sticky="ew", pady=(0, 12))
        cpw_row.grid_columnconfigure(0, weight=1)

        self.cpw = ttk.Entry(cpw_row, show="•")
        self.cpw.grid(row=0, column=0, sticky="ew")

        self.cpw_eye_btn = tk.Button(
            cpw_row,
            image=(self._eye_show if self._eye_show else None),
            text=(" " if self._eye_show else "Show"),
            compound="left",
            command=self._toggle_cpw,
            bg=card_bg, activebackground=card_bg,
            bd=0, relief="flat", highlightthickness=0, padx=6, pady=2
        )
        self.cpw_eye_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))

        # Status + actions
        self.status = tk.Label(content, text="", bg=card_bg,
                               fg=PALETTE.get("danger", "#b91c1c"), font=FONTS["body"])
        self.status.grid(row=4, column=0, columnspan=3, sticky="w", pady=(2, 0))

        self.register_btn = ttk.Button(content, text="Register", style="Primary.TButton",
                                       command=self._start_registration)
        self.register_btn.grid(row=4, column=3, sticky="e")

        # UX: enter-to-submit
        for e in (self.c_name, self.a_name, self.email, self.pw, self.cpw):
            e.bind("<Return>", lambda _e: self._start_registration())

        self.after(30, self.c_name.focus_set)

    def _toggle_pw(self):
        self._show_pw = not self._show_pw
        self.pw.config(show="" if self._show_pw else "•")
        if self._show_pw:
            if self._eye_hide: self.pw_eye_btn.config(image=self._eye_hide, text=" ")
            else: self.pw_eye_btn.config(text="Hide")
        else:
            if self._eye_show: self.pw_eye_btn.config(image=self._eye_show, text=" ")
            else: self.pw_eye_btn.config(text="Show")

    def _toggle_cpw(self):
        self._show_cpw = not self._show_cpw
        self.cpw.config(show="" if self._show_cpw else "•")
        if self._show_cpw:
            if self._eye_hide: self.cpw_eye_btn.config(image=self._eye_hide, text=" ")
            else: self.cpw_eye_btn.config(text="Hide")
        else:
            if self._eye_show: self.cpw_eye_btn.config(image=self._eye_show, text=" ")
            else: self.cpw_eye_btn.config(text="Show")

    def _start_registration(self):
        name = (self.c_name.get() or "").strip()
        aname = (self.a_name.get() or "").strip()
        email = (self.email.get() or "").strip().lower()
        pw = (self.pw.get() or "").strip()
        cpw = (self.cpw.get() or "").strip()

        # Validations
        if not all([name, aname, email, pw, cpw]):
            self.status.config(text="Please fill all fields.")
            return
        if not EMAIL_RE.match(email):
            self.status.config(text="Please enter a valid email address.")
            return
        if pw != cpw:
            self.status.config(text="Passwords do not match.")
            return
        if len(pw) < 8:
            self.status.config(text="Password must be at least 8 characters.")
            return

        # Submit
        try:
            self.register_btn.config(state="disabled", text="Sending…")
            self.reg_id = begin_company_registration(email, pw, name, aname)
            self._build_step2(email)
        except Exception as e:
            self.status.config(text=str(e))
            self.register_btn.config(state="normal", text="Register")

    # ───────────────────────── Step 2 ─────────────────────────
    def _build_step2(self, email_dest: str):
        self._clear()

        # keep the RED style for back button
        style = ttk.Style(self)
        red = PALETTE.get("danger", "#B91C1C")
        red_hover = "#991B1B"
        style.configure("BackAccent.TButton",
                        background=red, foreground="#FFFFFF", borderwidth=0, relief="flat")
        style.map("BackAccent.TButton",
                  background=[("active", red_hover), ("pressed", red_hover)],
                  foreground=[("disabled", "#FFFFFF")])

        top = tk.Frame(self, bg=PALETTE["bg"]); top.pack(fill="x")
        ttk.Button(top, text="← Back to Login", style="BackAccent.TButton", command=self._back_to_login)\
            .pack(anchor="w", padx=8, pady=(12, 6))

        tk.Label(self, text="Verify Email (OTP)", font=FONTS["h2"], bg=PALETTE["bg"])\
            .pack(anchor="w", padx=16, pady=(2, 0))
        ttk.Label(self, text="Enter the 6-digit code we sent to your email.",
                  style="Muted.TLabel").pack(anchor="w", padx=16, pady=(0, 8))

        c, inner = card(self)
        c.pack(padx=12, pady=10, fill="x")

        card_bg = _card_bg_of(inner)
        content = tk.Frame(inner, bg=card_bg)
        content.pack(fill="x", expand=True)
        content.grid_columnconfigure(1, weight=1)

        tk.Label(content, text=f"Email: {email_dest}", bg=card_bg,
                 fg=PALETTE["muted"], font=FONTS["body"])\
            .grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        tk.Label(content, text="OTP Code", bg=card_bg, fg=PALETTE["text"], font=FONTS["body"])\
            .grid(row=1, column=0, sticky="w")
        self.otp_entry = ttk.Entry(content, width=18)
        self.otp_entry.grid(row=1, column=1, sticky="w")

        self.status2 = tk.Label(content, text="", bg=card_bg,
                                fg=PALETTE.get("danger", "#b91c1c"), font=FONTS["body"])
        self.status2.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        row = tk.Frame(content, bg=card_bg)
        row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(8, 0))
        self.resend_btn = ttk.Button(row, text="Resend code", command=self._resend_otp, state="disabled")
        verify_btn = ttk.Button(row, text="Verify", style="Primary.TButton", command=self._verify_otp)
        self.resend_btn.pack(side="left", padx=(0, 8))
        verify_btn.pack(side="left")

        # UX
        self.otp_entry.bind("<Return>", lambda _e: self._verify_otp())
        self.after(40, self.otp_entry.focus_set)

        # Start resend cooldown
        self.cooldown = 30
        self._tick()

    def _tick(self):
        if not self.resend_btn:
            return
        if self.cooldown > 0:
            self.resend_btn.config(state="disabled", text=f"Resend code ({self.cooldown}s)")
            self.cooldown -= 1
            self.after(1000, self._tick)
        else:
            self.resend_btn.config(state="normal", text="Resend code")

    def _verify_otp(self):
        code = (self.otp_entry.get() or "").strip()
        if not code or not code.isdigit() or len(code) != 6:
            self.status2.config(text="Enter the 6-digit code.")
            return
        try:
            company_id = confirm_company_registration(self.reg_id, code)
            messagebox.showinfo(
                "Success",
                f"Company verified.\nID: {company_id}\nYou can now log in."
            )
            self._back_to_login()
        except Exception as e:
            self.status2.config(text=str(e))

    def _resend_otp(self):
        try:
            resend_company_otp(self.reg_id)
            self.cooldown = 30
            self._tick()
            self.status2.config(text="A new code was sent.", foreground=PALETTE.get("ok", "#15803d"))
        except Exception as e:
            self.status2.config(text=str(e), foreground=PALETTE.get("danger", "#b91c1c"))
