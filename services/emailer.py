# services/emailer.py
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

# I load .env if present so local dev "just works".
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


class EmailSendError(RuntimeError):
    """Raised when I fail to send an email so the UI can show a friendly message."""


# ── Config resolution ──────────────────────────────────────────
# I prefer pulling from services.config (single source of truth),
# but I fall back to environment variables so this file can run standalone.
def _coalesce_env(*keys: str, default: str = "") -> str:
    for k in keys:
        v = os.getenv(k)
        if v and v.strip():
            return v.strip()
    return default

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "").strip() or default)
    except Exception:
        return default

def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# Try to import the shared config; if it isn't available, I rely on envs.
try:
    from services.config import (  # type: ignore
        SMTP_HOST as CFG_HOST,
        SMTP_PORT as CFG_PORT,
        SMTP_USERNAME as CFG_USER,
        SMTP_PASSWORD as CFG_PASS,
        SMTP_FROM as CFG_FROM,
        SMTP_USE_TLS as CFG_USE_TLS,
        SMTP_USE_SSL as CFG_USE_SSL,
        SMTP_CONNECT_TIMEOUT as CFG_CONN_TO,
        SMTP_SEND_TIMEOUT as CFG_SEND_TO,
        APP_NAME as CFG_APP_NAME,
    )
except Exception:
    CFG_HOST = _coalesce_env("SMTP_HOST", default="")
    CFG_PORT = _env_int("SMTP_PORT", 587)
    # I accept both SMTP_USERNAME and SMTP_USER keys.
    CFG_USER = _coalesce_env("SMTP_USERNAME", "SMTP_USER", default="")
    CFG_PASS = _coalesce_env("SMTP_PASSWORD", "SMTP_PASS", default="")
    CFG_FROM = _coalesce_env("SMTP_FROM", default=CFG_USER)
    CFG_USE_TLS = _env_bool("SMTP_USE_TLS", True)
    CFG_USE_SSL = _env_bool("SMTP_USE_SSL", False)
    CFG_CONN_TO = _env_int("SMTP_CONNECT_TIMEOUT", 15)
    CFG_SEND_TO = _env_int("SMTP_SEND_TIMEOUT", 30)
    CFG_APP_NAME = os.getenv("APP_NAME", "CompliGuard")


SMTP_HOST: str = CFG_HOST
SMTP_PORT: int = int(CFG_PORT)
SMTP_USER: str = CFG_USER
SMTP_PASS: str = CFG_PASS
SMTP_FROM: str = CFG_FROM or CFG_USER
SMTP_USE_TLS: bool = bool(CFG_USE_TLS)
SMTP_USE_SSL: bool = bool(CFG_USE_SSL)
SMTP_CONNECT_TIMEOUT: int = int(CFG_CONN_TO)
SMTP_SEND_TIMEOUT: int = int(CFG_SEND_TO)
APP_NAME: str = str(CFG_APP_NAME or "CompliGuard")


def _validate_settings() -> None:
    missing = [k for k, v in {
        "SMTP_HOST": SMTP_HOST,
        "SMTP_PORT": SMTP_PORT,
        "SMTP_USER": SMTP_USER,
        "SMTP_PASS": SMTP_PASS,
        "SMTP_FROM": SMTP_FROM,
    }.items() if not v]
    if missing:
        raise EmailSendError(
            "Email isn't configured. Missing: " + ", ".join(missing) +
            ". Set them in environment variables or services/config.py."
        )


# ── Core sender ───────────────────────────────────────────────
def send_email(to_email: str, subject: str, body_text: str, body_html: Optional[str] = None) -> None:
    """
    Send an email using TLS (STARTTLS) or SSL depending on config.
    If body_html is provided, I send a multipart (plain + HTML); otherwise plain text.
    Raises EmailSendError on any failure.
    """
    _validate_settings()

    if not to_email or "@" not in to_email:
        raise EmailSendError("Invalid recipient email address.")

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject

    if body_html:
        msg.set_content(body_text or "")
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body_text or "")

    try:
        if SMTP_USE_SSL:
            # SSL on connect (e.g., port 465)
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_CONNECT_TIMEOUT, context=context) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        else:
            # STARTTLS upgrade (e.g., port 587)
            context = ssl.create_default_context()
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_CONNECT_TIMEOUT) as server:
                server.ehlo()
                if SMTP_USE_TLS:
                    server.starttls(context=context)
                    server.ehlo()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)

    except smtplib.SMTPAuthenticationError as e:
        raise EmailSendError("Email auth failed. Check SMTP_USER/SMTP_PASSWORD (use a Gmail App Password).") from e
    except smtplib.SMTPConnectError as e:
        raise EmailSendError("Couldn't connect to SMTP server. Verify SMTP_HOST/PORT and your network.") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise EmailSendError("The recipient address was rejected by the server.") from e
    except smtplib.SMTPException as e:
        raise EmailSendError(f"SMTP error: {e.__class__.__name__}: {e}") from e
    except Exception as e:
        raise EmailSendError(f"Failed to send email: {e.__class__.__name__}: {e}") from e


# ── Convenience helpers ───────────────────────────────────────
def send_password_otp(to_email: str, code: str) -> None:
    """
    Simple helper I use for password reset OTPs.
    """
    subject = f"{APP_NAME} Password Reset Code"
    body_text = (
        f"Your {APP_NAME} verification code is: {code}\n\n"
        "This code expires in 10 minutes. If you didn't request this, ignore this email."
    )
    body_html = f"""
    <div style="font-family:Segoe UI,Roboto,Arial,sans-serif;">
      <h2 style="margin:0 0 12px;">{APP_NAME} Password Reset</h2>
      <p>Your verification code is:</p>
      <p style="font-size:24px; letter-spacing:2px; font-weight:700; margin:8px 0;">{code}</p>
      <p style="color:#6b7280;">This code expires in 10 minutes.</p>
      <p style="color:#6b7280; font-size:12px;">If you didn't request this, you can safely ignore this email.</p>
    </div>
    """.strip()
    send_email(to_email, subject, body_text, body_html)
