"""
In-memory session for the signed-in user.

How it's used:
- After a successful login, call set_current_user({...})
  with a dict that at least includes:
    {
        "email": <user email>,
        "role": <"admin" / "superadmin" / etc>,
        "company_id": <company id for this user>,
        "company_name": <company/site display name>,
        ...anything else you want...
    }

- Pages later call require_user() or get_current_user() to know
  who's logged in and which company context to use.

This is process-local only (no disk persistence).
If you restart the app, this memory resets.
"""

from typing import Optional, Dict, Any

_current_user: Optional[Dict[str, Any]] = None


def set_current_user(user: Optional[Dict[str, Any]]) -> None:
    """
    Store the logged-in user's info in memory.

    You should pass a dict that contains:
      - "company_id": the company/site ID for this admin
      - "company_name": human-readable site/company name
      - "email": user's email
      - "role": user's role (admin / superadmin / etc)

    Example:
        set_current_user({
            "email": "boss@example.com",
            "role": "admin",
            "company_id": "ABC123",
            "company_name": "ABC Construction",
        })
    """
    global _current_user
    _current_user = user.copy() if user else None


def get_current_user() -> Optional[Dict[str, Any]]:
    """
    Return a shallow copy of the current user dict,
    or None if nobody is logged in.
    """
    return _current_user.copy() if _current_user else None


def require_user() -> Dict[str, Any]:
    """
    Return the current user dict, or raise if nobody is logged in.
    Helps pages fail fast instead of silently continuing.
    """
    u = get_current_user()
    if not u:
        raise RuntimeError(
            "No user in session. Did you call set_current_user after login?"
        )
    return u


# Optional convenience helpers (not strictly required, but handy)
def get_company_id() -> Optional[Any]:
    u = get_current_user()
    return u.get("company_id") if u else None


def get_company_name() -> Optional[str]:
    u = get_current_user()
    if not u:
        return None
    # prefer company_name, fallback company
    return (
        u.get("company_name")
        or u.get("company")
        or None
    )
