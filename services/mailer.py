"""
High-level, branded email helpers for CompliGuard.

Depends on services.emailer.send_email (which supports plaintext + HTML).
Use these helpers from your flows (admin registration, password reset, etc).
"""

from __future__ import annotations
from typing import Optional

from .emailer import send_email, EmailSendError  # delivery + friendly errors
from .config import SUPERADMIN_EMAIL  # not required, but available for CC/visibility


# ── Brand look & feel (tweak freely) ───────────────────────────────────────────
_BRAND = "CompliGuard"
_PRIMARY = "#1f5eff"
_BG = "#f6f7fb"
_CARD = "#ffffff"
_TEXT = "#111827"
_MUTED = "#6b7280"
_BORDER = "#e5e7eb"
_MONO_BG = "#0f172a"
_MONO_FG = "#e5e7eb"


def _shell_html(inner: str, title: str) -> str:
    """Minimal, responsive-ish HTML wrapper with inline styles (safe for most clients)."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
</head>
<body style="margin:0;padding:0;background:{_BG};font-family:Segoe UI,Arial,Helvetica,sans-serif;color:{_TEXT};">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{_BG};padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="width:560px;max-width:92%;background:{_CARD};border:1px solid {_BORDER};border-radius:12px;overflow:hidden;">
          <tr>
            <td style="padding:18px 20px;background:{_CARD};border-bottom:1px solid {_BORDER};">
              <div style="font-size:18px;font-weight:700;color:{_TEXT};">{_BRAND}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:22px 20px;background:{_CARD};">
              {inner}
            </td>
          </tr>
          <tr>
            <td style="padding:14px 20px;background:{_CARD};border-top:1px solid {_BORDER};">
              <div style="font-size:12px;color:{_MUTED};">
                This is an automated message from {_BRAND}. If you didn't request this, you can safely ignore it.
              </div>
            </td>
          </tr>
        </table>
        <div style="height:22px"></div>
        <div style="font-size:11px;color:{_MUTED};max-width:560px;">
          © { _BRAND }
        </div>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _code_block(code: str) -> str:
    return f"""\
<div style="margin:14px 0;">
  <div style="background:{_MONO_BG};color:{_MONO_FG};font-family:Consolas,Menlo,Monaco,monospace;font-size:20px;
              letter-spacing:3px;padding:12px 16px;border-radius:10px;text-align:center;">
    {code}
  </div>
</div>
"""


# ── Public helpers ─────────────────────────────────────────────────────────────

def send_password_otp(to_email: str, code: str, expires_minutes: int = 10) -> None:
    """
    Send a one-time code for password reset.
    """
    subject = f"{_BRAND} — Password Reset Code"
    text = (
        f"Your {_BRAND} password reset code is: {code}\n\n"
        f"This code expires in {expires_minutes} minute(s).\n"
        "If you did not request this, you can ignore this email."
    )
    html_inner = f"""\
<h2 style="margin:0 0 10px 0;font-size:20px;">Password Reset Code</h2>
<p style="margin:0 0 10px 0;color:{_MUTED};">Use the following code to reset your password.</p>
{_code_block(code)}
<p style="margin:8px 0 0 0;color:{_MUTED};font-size:14px;">
  This code expires in <strong>{expires_minutes} minute(s)</strong>.
</p>
"""
    html = _shell_html(html_inner, subject)
    send_email(to_email, subject, text, body_html=html)


def send_admin_created(to_email: str, company_name: str, temp_password: Optional[str] = None) -> None:
    """
    Notify a newly created admin account.
    """
    subject = f"{_BRAND} — Admin Account Created"
    lines = [
        f"Welcome to {_BRAND}!",
        f"You've been added as an admin for company: {company_name}.",
    ]
    if temp_password:
        lines.append(f"Temporary password: {temp_password}")
    lines.append("Please sign in and change your password promptly.")

    text = "\n".join(lines)

    pwd_html = f"<p style='margin:6px 0 0 0;'><strong>Temporary password:</strong> {temp_password}</p>" if temp_password else ""
    html_inner = f"""\
<h2 style="margin:0 0 10px 0;font-size:20px;">Welcome!</h2>
<p style="margin:0 0 6px 0;">You've been added as an admin for <strong>{company_name}</strong>.</p>
{pwd_html}
<p style="margin:10px 0 0 0;color:{_MUTED};font-size:14px;">Please sign in and change your password promptly.</p>
"""
    html = _shell_html(html_inner, subject)
    send_email(to_email, subject, text, body_html=html)


def send_test_email(to_email: str, note: str = "SMTP test from CompliGuard") -> None:
    """
    Simple diagnostic email to verify SMTP settings.
    """
    subject = f"{_BRAND} — SMTP Test"
    text = f"This is a test email from {_BRAND}.\n\nNote: {note}"
    html_inner = f"""\
<h2 style="margin:0 0 8px 0;font-size:20px;">SMTP Test</h2>
<p style="margin:0 0 8px 0;">This is a test email from {_BRAND}.</p>
<p style="margin:0;color:{_MUTED};font-size:14px;">Note: {note}</p>
"""
    html = _shell_html(html_inner, subject)
    send_email(to_email, subject, text, body_html=html)


# ── Convenience alias kept for backward compatibility (optional) ──────────────

def send_password_reset_email(email: str, code: str, expires_minutes: int = 10) -> None:
    """Alias for legacy callers."""
    send_password_otp(email, code, expires_minutes)
