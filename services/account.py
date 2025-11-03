from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from services.session import require_user
from services.firebase_client import get_db
from services.firestore_compat import eq

# ─────────────────────────────────────────────────────────────
# Optional integrations (mailer + security)
# Mailer: use if available; otherwise fall back to dev logging.
try:
    from services.mailer import send_password_otp as _send_password_otp  # (email, code) -> None
except Exception:  # pragma: no cover - optional dep
    _send_password_otp = None  # type: ignore

# Security: prefer your project's helpers; else use a PBKDF2 fallback.
try:
    from services.security import hash_password as _hash_pw, verify_password as _verify_pw
except Exception:  # pragma: no cover - optional dep
    import hashlib, os, hmac, base64

    _PBKDF2_ITER = 100_000

    def _hash_pw(pw: str) -> str:
        """PBKDF2-HMAC-SHA256 fallback. Stored format: 'pbkdf2$<base64(salt+dk)>'."""
        if not isinstance(pw, str) or not pw:
            raise ValueError("Password must be a non-empty string.")
        salt = os.urandom(16)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _PBKDF2_ITER)
        return "pbkdf2$" + base64.b64encode(salt + dk).decode("ascii")

    def _verify_pw(pw: str, stored: str) -> bool:
        try:
            if not (isinstance(stored, str) and stored.startswith("pbkdf2$")):
                return False
            raw = base64.b64decode(stored.split("$", 1)[1].encode("ascii"))
            salt, dk = raw[:16], raw[16:]
            check = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _PBKDF2_ITER)
            return hmac.compare_digest(dk, check)
        except Exception:
            return False


# ─────────────────────────────────────────────────────────────
# Constants / helpers

_OTP_TTL_MINUTES = 10
_MIN_NAME_LEN = 2
_MIN_PASSWORD_LEN = 8


def _now_utc() -> datetime:
    """Timezone-aware UTC 'now'."""
    return datetime.now(timezone.utc)


def _norm_email(email: str) -> str:
    """Normalize email for lookups."""
    return (email or "").strip().lower()


def _users_query():
    """Firestore collection ref for users."""
    return get_db().collection("users")


def _find_user_by_email(email: str) -> Optional[Any]:
    """
    Return a Firestore document snapshot for this email (case-insensitive)
    or None if not found.
    """
    email_l = _norm_email(email)

    # Prefer a stored normalized field if available
    try:
        snaps = list(eq(_users_query(), "email_lower", email_l).stream())
        if snaps:
            return snaps[0]
    except Exception:
        pass

    # Fallback to exact match on 'email'
    try:
        snaps = list(eq(_users_query(), "email", email).stream())
        if snaps:
            return snaps[0]
    except Exception:
        pass

    return None


def _find_user_by_id(doc_id: Optional[str]) -> Optional[Any]:
    """Load user by Firestore document id."""
    if not doc_id:
        return None
    try:
        snap = _users_query().document(str(doc_id)).get()
        if snap and snap.exists:
            return snap
    except Exception:
        pass
    return None


def _update_session_cache(fields: Dict[str, Any]) -> None:
    """
    Best-effort push of updated fields into session so UI reflects immediately.
    Silently no-ops if session helpers are unavailable.
    """
    try:
        from services.session import set_current_user  # type: ignore
        cur = require_user() or {}
        set_current_user({**cur, **fields})
        return
    except Exception:
        pass
    try:
        from services.session import update_current_user  # type: ignore
        update_current_user(fields)
    except Exception:
        pass


def _require_non_empty(value: str, label: str) -> str:
    v = (value or "").strip()
    if not v:
        raise ValueError(f"{label} is required.")
    return v


# ─────────────────────────────────────────────────────────────
# Public API (used by pages/profile.py and others)

def get_profile() -> Dict[str, Any]:
    """
    Return the current user's profile merged from session + Firestore.

    Robustness:
      - If the session email is stale (e.g., right after an email change),
        we fall back to the session user's document ID.
    """
    user = require_user() or {}
    email = _norm_email(user.get("email", ""))
    uid = user.get("id") or user.get("uid") or user.get("doc_id")

    snap = _find_user_by_email(email)
    if not snap:
        snap = _find_user_by_id(uid)

    data = snap.to_dict() if snap else {}

    return {
        "email": data.get("email", user.get("email")),
        "name": data.get("name", user.get("name")),
        "role": data.get("role", user.get("role")),
        "company_id": data.get("company_id", user.get("company_id")),
        "company_name": data.get("company_name", user.get("company_name")),
        "status": data.get("status", "active"),
        "id": (snap.id if snap else user.get("id")),
    }


def update_profile(*, name: str, email: str) -> None:
    """
    Update name/email in Firestore for the signed-in user.
    Also refreshes the in-memory session cache for instant UI update.
    """
    user = require_user() or {}
    old_email = _norm_email(user.get("email", ""))
    uid = user.get("id") or user.get("uid") or user.get("doc_id")

    # Basic validation
    name = _require_non_empty(name, "Name")
    if len(name) < _MIN_NAME_LEN:
        raise ValueError("Name is too short.")
    email = _require_non_empty(email, "Email")
    email_l = _norm_email(email)

    # Prefer lookup by id (works even if email is changing)
    snap = _find_user_by_id(uid) or _find_user_by_email(old_email)
    if not snap:
        raise RuntimeError("Profile not found.")

    updates = {
        "name": name,
        "email": email,
        "email_lower": email_l,
        "updated_at": _now_utc(),
    }
    snap.reference.update(updates)

    # Session cache refresh
    _update_session_cache({"name": name, "email": email})


def change_password(old_password: str, new_password: str) -> None:
    """
    Validate the old password and set a new one.
    Assumes user doc stores 'password_hash'.
    """
    user = require_user() or {}
    email = _norm_email(user.get("email", ""))
    uid = user.get("id") or user.get("uid") or user.get("doc_id")

    snap = _find_user_by_email(email) or _find_user_by_id(uid)
    if not snap:
        raise RuntimeError("Profile not found.")

    data = snap.to_dict() or {}
    stored = data.get("password_hash", "")
    if not stored:
        raise RuntimeError("Password not set for this account.")

    if not _verify_pw(old_password, stored):
        raise ValueError("Current password is incorrect.")

    if not isinstance(new_password, str) or len(new_password) < _MIN_PASSWORD_LEN:
        raise ValueError(f"New password must be at least {_MIN_PASSWORD_LEN} characters long.")

    new_hash = _hash_pw(new_password)
    snap.reference.update({
        "password_hash": new_hash,
        "pw_changed_at": _now_utc(),
        # clear any pending reset
        "pw_reset": None,
    })


def start_password_reset(email: str) -> None:
    """
    Generate a 6-digit OTP, store in user doc with 10-min expiry,
    and send via services.mailer.send_password_otp if available.

    Behavior: if the email does NOT exist, raises ValueError so UI can show
    'Email doesn't exist.' (no fake success).
    """
    email = _require_non_empty(email, "Email")
    snap = _find_user_by_email(email)
    if not snap:
        raise ValueError("Email doesn't exist.")

    code = "".join(random.choices(string.digits, k=6))
    expires_at = _now_utc() + timedelta(minutes=_OTP_TTL_MINUTES)

    snap.reference.update({
        "pw_reset": {
            "code": code,
            "expires_at": expires_at,
            "sent_at": _now_utc(),
        }
    })

    if _send_password_otp:
        try:
            _send_password_otp(email, code)
        except Exception:
            # Dev fallback log (avoid crashing on mail failure)
            print(f"[OTP] send failed; {email=} {code=}")
    else:
        # Dev fallback log
        print(f"[OTP] {email=} {code=}")


def verify_password_reset(email: str, otp_code: str, new_password: str) -> None:
    """
    Check OTP and, if valid, set the new password and clear the reset state.
    """
    email = _require_non_empty(email, "Email")
    otp_code = _require_non_empty(otp_code, "OTP code")
    if not isinstance(new_password, str) or len(new_password) < _MIN_PASSWORD_LEN:
        raise ValueError(f"New password must be at least {_MIN_PASSWORD_LEN} characters long.")

    snap = _find_user_by_email(email)
    if not snap:
        # Don't reveal which part failed (generic error)
        raise ValueError("Invalid or expired OTP.")

    data = snap.to_dict() or {}
    pr = (data.get("pw_reset") or {})

    code = (pr.get("code") or "").strip()
    exp = pr.get("expires_at")

    if not code or not exp:
        raise ValueError("No reset request found.")
    if otp_code.strip() != code:
        raise ValueError("Incorrect OTP.")

    # Normalize timestamp (Firestore Timestamp or datetime)
    try:
        if hasattr(exp, "to_datetime"):
            exp = exp.to_datetime()
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
    except Exception:
        # If normalization fails, treat as expired rather than silently accept
        raise ValueError("OTP expired. Please request a new one.")

    if _now_utc() > exp:
        raise ValueError("OTP expired. Please request a new one.")

    new_hash = _hash_pw(new_password)
    snap.reference.update({
        "password_hash": new_hash,
        "pw_changed_at": _now_utc(),
        "pw_reset": None,
    })


def delete_account(password: str) -> None:
    """
    Verify password and delete the user document.
    If you also need to remove Firebase Auth user, extend here.
    """
    user = require_user() or {}
    email = _norm_email(user.get("email", ""))
    uid = user.get("id") or user.get("uid") or user.get("doc_id")

    snap = _find_user_by_email(email) or _find_user_by_id(uid)
    if not snap:
        raise RuntimeError("Profile not found.")

    data = snap.to_dict() or {}
    stored = data.get("password_hash", "")
    if not stored or not _verify_pw(password, stored):
        raise ValueError("Incorrect password.")

    # NOTE: If there are foreign references (zones, cameras, logs), handle cleanup here
    # before deleting the user doc to avoid dangling references.
    snap.reference.delete()
