# services/firebase_auth.py
from __future__ import annotations

from typing import Optional, Dict, Any, Union

import bcrypt  # kept for legacy string/bytes bcrypt support

from .firebase_client import get_db
from .config import SUPERADMIN_EMAIL
from .security import verify_password  # handles {"algo": "...", "hash": "..."}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _s(v: Any) -> str:
    """I coerce any value to a trimmed string (empty if None)."""
    return ("" if v is None else str(v)).strip()


def _normalize_user(doc: Dict[str, Any], email_fallback: str) -> Dict[str, Any]:
    """
    I normalize the user dict so downstream code always finds expected keys.
    Notes:
      - I keep company_id type as-is (str or int).
      - I preserve password_hash format (dict or legacy str/bytes).
    """
    d = (doc or {}).copy()
    d.setdefault("email", (email_fallback or "").lower())
    d.setdefault("name", "")
    d.setdefault("role", "company_admin")  # default for older docs
    d.setdefault("company_id", None)       # may be "2" or 2; I don't coerce
    d.setdefault("active", True)
    d.setdefault("created_at", None)
    d.setdefault(
        "password_hash",
        b"" if isinstance(doc.get("password_hash"), (bytes, bytearray)) else ""
    )
    return d


def _get_user_doc(email: str) -> Optional[Dict[str, Any]]:
    """
    I load a Firestore user document by email (document id) and normalize it.
    Returns None if not found.
    """
    if not email:
        return None
    db = get_db()
    snap = db.collection("users").document(email.lower()).get()
    if not snap.exists:
        return None

    data = snap.to_dict() or {}
    data["id"] = snap.id
    return _normalize_user(data, email)


def _check_password(
    input_password: str,
    stored: Union[Dict[str, Any], str, bytes, None]
) -> bool:
    """
    I accept these formats for stored password:
      - dict {"algo": "...", "hash": "..."}            (new format via services.security)
      - str bcrypt hash (e.g. "$2b$12$...")            (legacy)
      - bytes bcrypt hash                               (legacy)
    """
    if not input_password:
        return False

    # New structured format (preferred)
    if isinstance(stored, dict):
        return verify_password(input_password, stored)

    # Legacy bcrypt string
    if isinstance(stored, str) and stored.startswith("$2"):
        try:
            return bcrypt.checkpw(input_password.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            return False

    # Legacy bcrypt bytes
    if isinstance(stored, (bytes, bytearray)):
        try:
            return bcrypt.checkpw(input_password.encode("utf-8"), bytes(stored))
        except Exception:
            return False

    # Unknown/empty
    return False


def _company_suspended_from_doc(d: Dict[str, Any]) -> Optional[bool]:
    """
    I normalize 'suspended' / 'active' / 'status' into a single boolean.
    Returns:
        True  -> suspended
        False -> active
        None  -> unknown / not found
    """
    if not isinstance(d, dict):
        return None
    if isinstance(d.get("suspended"), bool):
        return d["suspended"]
    if isinstance(d.get("active"), bool):
        return not d["active"]
    status = _s(d.get("status")).lower()
    if status in ("suspended", "inactive", "disabled"):
        return True
    if status in ("active",):
        return False
    return None


def is_company_suspended(company_id: Any) -> Optional[bool]:
    """
    I look up the company and return whether it is suspended.
    Checks in order: companies/{docId}, then where('id' == company_id),
    then where('company_id' == company_id). Returns True/False,
    or None if the record is missing.
    """
    if company_id is None or _s(company_id) == "":
        return None

    db = get_db()

    # 1) try document id exact
    try:
        snap = db.collection("companies").document(str(company_id)).get()
        if snap and snap.exists:
            return _company_suspended_from_doc(snap.to_dict() or {})
    except Exception:
        pass

    # 2) try 'id' / 'company_id' field matches
    for field in ("id", "company_id"):
        try:
            q = db.collection("companies").where(field, "==", company_id).limit(1).get()
            if q:
                return _company_suspended_from_doc(q[0].to_dict() or {})
        except Exception:
            pass

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Public API (I keep function names and logic unchanged)
# ──────────────────────────────────────────────────────────────────────────────

def authenticate_email_password(email: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Validate an email/password against credentials stored in Firestore.

    On success, I return a normalized user dict including:
      {
        'id', 'email', 'name', 'role', 'company_id', 'active',
        'password_hash', 'created_at', ...
      }
    Returns None on failure or if user is inactive.
    """
    user = _get_user_doc(email)
    if not user or not bool(user.get("active", True)):
        return None

    if not _check_password(password, user.get("password_hash")):
        return None

    # Keep essential fields normalized
    return {
        "id": user.get("id"),
        "email": (user.get("email") or email or "").lower(),
        "name": user.get("name") or user.get("email") or "",
        "role": user.get("role") or "company_admin",
        "company_id": user.get("company_id"),  # I preserve original type
        "active": bool(user.get("active", True)),
        "created_at": user.get("created_at"),
        "password_hash": user.get("password_hash"),
    }


def is_superadmin(user: Dict[str, Any]) -> bool:
    """
    True if:
      - role explicitly equals 'superadmin' (case-insensitive), OR
      - email matches configured SUPERADMIN_EMAIL.
    """
    if not isinstance(user, dict):
        return False
    role = (user.get("role") or "").lower()
    email = (user.get("email") or "").lower()
    if role == "superadmin":
        return True
    if SUPERADMIN_EMAIL and email == (SUPERADMIN_EMAIL or "").lower():
        return True
    return False


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Simple convenience wrapper to fetch a normalized user by email."""
    return _get_user_doc(email)


def company_block_reason_for(user: Dict[str, Any]) -> Optional[str]:
    """
    For non-superadmins, I check the company status and return a human message
    if the company is suspended. Otherwise I return None.
    """
    if not isinstance(user, dict):
        return None
    if is_superadmin(user):
        return None

    # find a company id on the user
    for k in ("company_id", "companyId", "companyID", "company"):
        cid = user.get(k)
        if _s(cid):
            suspended = is_company_suspended(cid)
            if suspended is True:
                return "Your company has been suspended. Please contact your superadmin."
            return None

    # No company recorded — I don't block.
    return None
