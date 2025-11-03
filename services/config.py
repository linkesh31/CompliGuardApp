# services/config.py
"""
Central app config. Sane defaults with .env / environment overrides.
"""

from __future__ import annotations
import os

# ──────────────────────────────────────────────
# Load .env (even if this module is imported early)
# ──────────────────────────────────────────────
def _load_env() -> None:
    try:
        from dotenv import load_dotenv, find_dotenv
        # Prefer a .env in the current working dir (your project root)
        # Do NOT override already-set OS env vars
        path = find_dotenv(filename=".env", usecwd=True)
        load_dotenv(dotenv_path=path, override=False)
    except Exception:
        # Safe to continue without python-dotenv
        pass

_load_env()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1].strip()
    return s

def _env_str(key: str, default: str) -> str:
    v = os.getenv(key)
    if v is None:
        return default
    v = _strip_quotes(v)
    return v if v != "" else default

def _env_int(key: str, default: int) -> int:
    try:
        raw = os.getenv(key, "")
        raw = _strip_quotes(raw)
        return int(raw) if raw != "" else default
    except Exception:
        return default

def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    v = _strip_quotes(v).lower()
    return v in ("1", "true", "yes", "on")


# ──────────────────────────────────────────────
# Back-compat aliases (populate canonical keys from alternates)
# Run this AFTER loading .env so we can map values from .env if present.
# ──────────────────────────────────────────────
if os.getenv("SMTP_USERNAME") is None and os.getenv("SMTP_USER"):
    os.environ["SMTP_USERNAME"] = os.getenv("SMTP_USER", "")
if os.getenv("SMTP_PASSWORD") is None and os.getenv("SMTP_PASS"):
    os.environ["SMTP_PASSWORD"] = os.getenv("SMTP_PASS", "")


# ──────────────────────────────────────────────
# Branding / App
# ──────────────────────────────────────────────
APP_NAME: str = _env_str("APP_NAME", "CompliGuard")

# Single superadmin email for bootstrap flows.
SUPERADMIN_EMAIL: str = _env_str("SUPERADMIN_EMAIL", "linkeshjpr.25@gmail.com")


# ──────────────────────────────────────────────
# SMTP / Email (OTP, password reset, notifications)
# For Gmail:
#   SMTP_HOST=smtp.gmail.com
#   SMTP_PORT=587  (STARTTLS) or 465 (SSL)
#   SMTP_USERNAME=your@gmail.com
#   SMTP_PASSWORD=<16-char Google App Password>
#   SMTP_FROM=CompliGuard <your@gmail.com>
# ──────────────────────────────────────────────
SMTP_HOST: str = _env_str("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = _env_int("SMTP_PORT", 587)

SMTP_USERNAME: str = _env_str("SMTP_USERNAME", "linkeshjpr.25@gmail.com")
SMTP_PASSWORD: str = _env_str("SMTP_PASSWORD", "YOUR_APP_PASSWORD")  # replace via .env

# Default "CompliGuard <username>" if not provided
SMTP_FROM: str = _env_str("SMTP_FROM", f"{APP_NAME} <{SMTP_USERNAME}>")

# Transport flags. For Gmail: STARTTLS on 587 (TLS=True, SSL=False).
SMTP_USE_TLS: bool = _env_bool("SMTP_USE_TLS", True)
SMTP_USE_SSL: bool = _env_bool("SMTP_USE_SSL", False)

# Optional: timeouts (seconds)
SMTP_CONNECT_TIMEOUT: int = _env_int("SMTP_CONNECT_TIMEOUT", 15)
SMTP_SEND_TIMEOUT: int = _env_int("SMTP_SEND_TIMEOUT", 30)


# ──────────────────────────────────────────────
# Sanity checks (non-fatal)
# ──────────────────────────────────────────────
def _warn_if_insecure() -> None:
    try:
        if SMTP_USE_TLS and SMTP_USE_SSL:
            print("[config] WARNING: Both SMTP_USE_TLS and SMTP_USE_SSL are True. Choose one (TLS on 587 or SSL on 465).")
        if SMTP_PASSWORD == "YOUR_APP_PASSWORD" or SMTP_PASSWORD.strip() == "":
            print("[config] WARNING: SMTP_PASSWORD is missing or placeholder. Set env SMTP_PASSWORD.")
        if (SMTP_USERNAME or "").strip() == "":
            print("[config] WARNING: SMTP_USERNAME is empty. Set env SMTP_USERNAME.")
        if SMTP_USE_SSL and SMTP_PORT != 465:
            print("[config] WARNING: SMTP_USE_SSL=True but SMTP_PORT != 465.")
        if SMTP_USE_TLS and SMTP_PORT not in (587, 25):
            print("[config] NOTE: SMTP_USE_TLS=True; typical port is 587.")
    except Exception:
        # Never crash on config import
        pass

_warn_if_insecure()
