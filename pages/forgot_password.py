# pages/forgot_password.py
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.async_ui import run_async
from services.account import start_password_reset, verify_password_reset


def _card_bg_of(ctk_inner) -> str:
    """Read inner card color; fall back to palette card."""
    try:
        c = ctk_inner.cget("fg_color")
        if isinstance(c, (list, tuple)):
            return c[0]
        return c or PALETTE["card"]
    except Exception:
        return PALETTE["card"]


RED_BG = "#DC2626"         # red button bg
RED_BG_ACTIVE = "#B91C1C"  # darker red when pressed/active


class ForgotPasswordPage(tk.Frame):
    """
    2-step reset flow:
     Step 1: enter email → Send code
     Step 2: enter code + new password → Reset password

    - "Back to login" and "Back" buttons are red.
    - Primary actions ("Send code", "Reset password") keep your themed Primary.TButton.
    """
    def __init__(self, parent, controller):
        super().__init__(parent, bg=PALETTE["bg"])
        self.controller = controller
        self._busy = False

        # state vars shared across steps
        self.email_var = tk.StringVar()
        self.otp_var = tk.StringVar()
        self.pass1_var = tk.StringVar()
        self.pass2_var = tk.StringVar()

        apply_theme(self)
        self._build_step1()

    # ---------- shared helpers ----------
    def _set_busy(self, busy: bool, msg: str = ""):
        self._busy = busy
        try:
            self.primary_btn.configure(state=("disabled" if busy else "normal"))
        except Exception:
            try:
                self.primary_btn.config(state=("disabled" if busy else "normal"))
            except Exception:
                pass
        self.status.config(text=msg)

    def _go_login(self):
        """
        Swap this frame back to login.
        We import LoginPage lazily here to avoid circular import at module import time.
        """
        try:
            if hasattr(self.controller, "show_login"):
                # Some apps expose controller.show_login()
                self.controller.show_login()
                return
        except Exception:
            pass

        from modules.login import LoginPage  # lazy import only when needed
        for w in self.master.winfo_children():
            w.destroy()
        LoginPage(self.master, controller=self.controller).pack(
            fill="both", expand=True
        )

    # ---------- Step 1: enter email ----------
    def _build_step1(self):
        for w in self.winfo_children():
            w.destroy()

        wrap = tk.Frame(self, bg=PALETTE["bg"])
        wrap.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            wrap,
            text="Forgot your password?",
            font=FONTS["h1"],
            bg=PALETTE["bg"],
        ).pack(anchor="center", pady=(0, 6))

        ttk.Label(
            wrap,
            text="Enter your account email. We’ll send a 6-digit code.",
            style="Muted.TLabel",
        ).pack(anchor="center", pady=(0, 14))

        card_fr, inner = card(wrap, pad=(24, 20))

        # make card visually consistent width with login
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

        # Email label + entry
        tk.Label(
            inner,
            text="Email",
            bg=card_bg,
            fg=PALETTE["text"],
            font=FONTS["body"],
        ).grid(row=0, column=0, sticky="w")

        email_entry = ttk.Entry(inner, textvariable=self.email_var)
        email_entry.grid(row=1, column=0, sticky="ew", ipady=4)

        # status line
        self.status = tk.Label(
            inner,
            text="",
            bg=card_bg,
            fg=PALETTE.get("danger", "#b91c1c"),
            font=FONTS["body"],
        )
        self.status.grid(row=2, column=0, sticky="w", pady=(10, 0))

        # actions row
        actions = tk.Frame(inner, bg=card_bg)
        actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(0, weight=1)

        # RED "Back to login"
        back_btn = tk.Button(
            actions,
            text="Back to login",
            command=self._go_login,
            bg=RED_BG,
            fg="#FFFFFF",
            activebackground=RED_BG_ACTIVE,
            activeforeground="#FFFFFF",
            bd=0,
            relief="flat",
            highlightthickness=0,
            padx=14,
            pady=7,
            cursor="hand2",
        )
        back_btn.pack(side="left")

        # Themed primary "Send code"
        self.primary_btn = ttk.Button(
            actions,
            text="Send code",
            style="Primary.TButton",
            command=self._on_send_code,
        )
        self.primary_btn.pack(side="right")

        email_entry.bind("<Return>", lambda _e: self._on_send_code())
        self.after(50, email_entry.focus_set)

    def _on_send_code(self):
        if self._busy:
            return

        email = (self.email_var.get() or "").strip().lower()
        if not email or "@" not in email:
            self.status.config(text="Please enter a valid email address.")
            return

        self._set_busy(True, "Sending code…")

        def _work():
            # backend will now raise ValueError("Email doesn't exist.") if not found
            start_password_reset(email)

        def _done(err: Optional[Exception]):
            # always clear busy first
            self._set_busy(False, "")

            if isinstance(err, Exception):
                # show backend error (e.g. "Email doesn't exist.")
                self.status.config(text=str(err))
                return

            # success → go to step 2
            self._build_step2()

            messagebox.showinfo(
                "Check your inbox",
                "We’ve sent a 6-digit code.",
            )

        run_async(_work, _done, self)

    # ---------- Step 2: verify + reset ----------
    def _build_step2(self):
        for w in self.winfo_children():
            w.destroy()

        wrap = tk.Frame(self, bg=PALETTE["bg"])
        wrap.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            wrap,
            text="Verify code & reset",
            font=FONTS["h1"],
            bg=PALETTE["bg"],
        ).pack(anchor="center", pady=(0, 6))

        ttk.Label(
            wrap,
            text=f"Email: {self.email_var.get()}",
            style="Muted.TLabel",
        ).pack(anchor="center", pady=(0, 14))

        card_fr, inner = card(wrap, pad=(24, 20))

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

        # OTP label + entry
        tk.Label(
            inner,
            text="6-digit code",
            bg=card_bg,
            fg=PALETTE["text"],
            font=FONTS["body"],
        ).grid(row=0, column=0, sticky="w")

        otp_entry = ttk.Entry(inner, textvariable=self.otp_var)
        otp_entry.grid(row=1, column=0, sticky="ew", ipady=4, pady=(0, 8))

        # New password
        tk.Label(
            inner,
            text="New password",
            bg=card_bg,
            fg=PALETTE["text"],
            font=FONTS["body"],
        ).grid(row=2, column=0, sticky="w")

        pass1_entry = ttk.Entry(inner, textvariable=self.pass1_var, show="•")
        pass1_entry.grid(row=3, column=0, sticky="ew", ipady=4)

        # Confirm password
        tk.Label(
            inner,
            text="Confirm new password",
            bg=card_bg,
            fg=PALETTE["text"],
            font=FONTS["body"],
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))

        pass2_entry = ttk.Entry(inner, textvariable=self.pass2_var, show="•")
        pass2_entry.grid(row=5, column=0, sticky="ew", ipady=4)

        # status line
        self.status = tk.Label(
            inner,
            text="",
            bg=card_bg,
            fg=PALETTE.get("danger", "#b91c1c"),
            font=FONTS["body"],
        )
        self.status.grid(row=6, column=0, sticky="w", pady=(10, 0))

        # actions row
        actions = tk.Frame(inner, bg=card_bg)
        actions.grid(row=7, column=0, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(0, weight=1)

        # RED Back
        back_btn = tk.Button(
            actions,
            text="Back",
            command=self._build_step1,
            bg=RED_BG,
            fg="#FFFFFF",
            activebackground=RED_BG_ACTIVE,
            activeforeground="#FFFFFF",
            bd=0,
            relief="flat",
            highlightthickness=0,
            padx=14,
            pady=7,
            cursor="hand2",
        )
        back_btn.pack(side="left")

        # themed primary "Reset password"
        self.primary_btn = ttk.Button(
            actions,
            text="Reset password",
            style="Primary.TButton",
            command=self._on_reset_password,
        )
        self.primary_btn.pack(side="right")

        otp_entry.bind("<Return>", lambda _e: self._on_reset_password())
        pass2_entry.bind("<Return>", lambda _e: self._on_reset_password())
        self.after(50, otp_entry.focus_set)

    def _on_reset_password(self):
        if self._busy:
            return

        email = (self.email_var.get() or "").strip().lower()
        otp = (self.otp_var.get() or "").strip()
        p1 = (self.pass1_var.get() or "").strip()
        p2 = (self.pass2_var.get() or "").strip()

        if not otp or len(otp) != 6 or not otp.isdigit():
            self.status.config(text="Please enter the 6-digit code.")
            return
        if len(p1) < 8:
            self.status.config(text="Password must be at least 8 characters.")
            return
        if p1 != p2:
            self.status.config(text="Passwords do not match.")
            return

        self._set_busy(True, "Updating password…")

        def _work():
            verify_password_reset(email, otp, p1)

        def _done(err: Optional[Exception]):
            self._set_busy(False, "")

            if isinstance(err, Exception):
                self.status.config(text=str(err))
                return

            # clear sensitive fields
            self.otp_var.set("")
            self.pass1_var.set("")
            self.pass2_var.set("")

            messagebox.showinfo(
                "Password updated",
                "Your password has been reset. You can now sign in.",
            )
            self._go_login()

        run_async(_work, _done, self)
