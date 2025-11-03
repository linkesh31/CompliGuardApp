# services/security.py
"""
Lightweight password hashing helper.
Prefers bcrypt; falls back to sha256 if bcrypt is unavailable.
"""

from __future__ import annotations
import hashlib

try:
    import bcrypt  # type: ignore
    _HAS_BCRYPT = True
except Exception:
    _HAS_BCRYPT = False


def hash_password(password: str) -> dict:
    """
    Returns a dict with:
      {
        "algo": "bcrypt"|"sha256",
        "hash": <str>,
      }
    """
    if not isinstance(password, str) or not password:
        raise ValueError("Password required.")

    if _HAS_BCRYPT:
        pw = password.encode("utf-8")
        h = bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12))
        return {"algo": "bcrypt", "hash": h.decode("utf-8")}
    else:
        # Fallback — less secure; keep only if environment lacks bcrypt
        h = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return {"algo": "sha256", "hash": h}


def verify_password(password: str, stored: dict) -> bool:
    algo = (stored or {}).get("algo")
    digest = (stored or {}).get("hash")
    if not algo or not digest:
        return False

    if algo == "bcrypt" and _HAS_BCRYPT:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), digest.encode("utf-8"))
        except Exception:
            return False
    elif algo == "sha256":
        return hashlib.sha256(password.encode("utf-8")).hexdigest() == digest
    return False
