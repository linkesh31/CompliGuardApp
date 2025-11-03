# services/users.py
from __future__ import annotations

from typing import List, Dict, Optional, Any
from firebase_admin import firestore

from services.firebase_client import get_db
from services.security import hash_password
from services.firestore_compat import eq  # ← compat helpers


# ────────────────────────────────────────────────────────────────
# Internal helpers
# ────────────────────────────────────────────────────────────────

def _norm_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("Email must be a string.")
    e = email.strip().lower()
    if "@" not in e:
        raise ValueError("Invalid email address.")
    return e


def _coerce_company_id_to_int(company_id: Any) -> int:
    """
    Firestore 'companies' documents store numeric field `id` (int).
    For validation we must compare with an int, but in user docs we keep the
    original value (str or int) to remain consistent with existing data.
    """
    try:
        return int(str(company_id).strip())
    except Exception:
        raise ValueError("company_id must be numeric (e.g. 2).")


def _get_company_by_id(company_id_any: Any) -> Optional[Dict]:
    """
    Loads a company by its numeric field 'id' (not the doc id).
    Returns the company dict if found, else None.
    """
    db = get_db()
    company_id_int = _coerce_company_id_to_int(company_id_any)
    q = eq(db.collection("companies"), "id", company_id_int).limit(1).stream()
    for d in q:
        obj = d.to_dict() or {}
        obj["__ref__"] = d.reference
        return obj
    return None


# ────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────

def list_users(company_id: Optional[Any] = None) -> List[Dict]:
    """
    List users. If company_id is provided, filter by that exact value.
    IMPORTANT: This uses the SAME TYPE as stored in user docs.
               If your user docs store "2" (string), pass "2".
    """
    db = get_db()
    col = db.collection("users")
    qs = eq(col, "company_id", company_id).stream() if company_id is not None else col.stream()

    out: List[Dict] = []
    for d in qs:
        obj = d.to_dict() or {}
        obj["__id__"] = d.id  # email as doc id
        out.append(obj)

    out.sort(key=lambda x: (x.get("email") or "").lower())
    return out


def create_admin_user(
    *,
    inviter_email: str,
    company_id: Any,   # ← str or int accepted
    email: str,
    name: str,
    password: str,
) -> Dict:
    """
    Directly creates an ADMIN user (no OTP) in the specified company.

    Writes users/{email} with:
      {
        email, name, role: "admin", company_id (original type),
        status: "active",
        password_hash: {"algo": "...", "hash": "..."},
        created_at: SERVER_TIMESTAMP,
        created_by: inviter_email
      }
    """
    db = get_db()

    email_n = _norm_email(email)
    name = (name or "").strip()
    inviter_email = (inviter_email or "").strip().lower()

    if not name:
        raise ValueError("Name is required.")
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    # Validate company exists (coerce to int for the lookup only)
    if not _get_company_by_id(company_id):
        raise ValueError(f"Company ID {company_id} not found.")

    # Ensure user doesn't already exist
    user_ref = db.collection("users").document(email_n)
    if user_ref.get().exists:
        raise ValueError("A user with this email already exists.")

    # Hash password
    pwd_hash = hash_password(password)  # -> {"algo": "...", "hash": "..."}

    payload = {
        "email": email_n,
        "name": name,
        "role": "admin",
        # Keep the original type for company_id (string or int) so future queries match
        "company_id": company_id,
        "status": "active",  # active | disabled
        "password_hash": pwd_hash,
        "created_at": firestore.SERVER_TIMESTAMP,
        "created_by": inviter_email,
    }

    user_ref.set(payload)

    return {
        "email": email_n,
        "name": name,
        "role": "admin",
        "company_id": company_id,
        "status": "active",
        "created_by": inviter_email,
        "doc_id": email_n,
    }


def disable_user(email: str) -> None:
    """Soft-disable a user by setting status='disabled'."""
    db = get_db()
    email_n = _norm_email(email)
    ref = db.collection("users").document(email_n)
    if not ref.get().exists:
        raise ValueError("User not found.")
    ref.update({"status": "disabled"})


def enable_user(email: str) -> None:
    """Re-enable a user by setting status='active'."""
    db = get_db()
    email_n = _norm_email(email)
    ref = db.collection("users").document(email_n)
    if not ref.get().exists:
        raise ValueError("User not found.")
    ref.update({"status": "active"})


def delete_user(email: str) -> None:
    """Permanently deletes a user document."""
    db = get_db()
    email_n = _norm_email(email)
    ref = db.collection("users").document(email_n)
    if not ref.get().exists:
        raise ValueError("User not found.")
    ref.delete()
