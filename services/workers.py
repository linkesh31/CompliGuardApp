from __future__ import annotations
import time
from typing import Any, Dict, List, Optional

from services.firebase_client import get_db

# Try to use your compat helpers (type-tolerant equality / IN). Fall back safely.
try:
    from services.firestore_compat import eq, any_in  # type: ignore
except Exception:
    eq = any_in = None  # type: ignore


# ───────────────────────── small utils ─────────────────────────
def _s(v: Any) -> str:
    return ("" if v is None else str(v)).strip()


def _company_keys(company_id_any: Any) -> List[Any]:
    """
    Normalize company_id to a small set of equivalent keys so we match
    both string '2' and integer 2 if the data was written inconsistently.
    """
    keys: List[Any] = []
    s = _s(company_id_any)
    if s:
        keys.append(s)
        if s.isdigit():
            try:
                keys.append(int(s))
            except Exception:
                pass
    if isinstance(company_id_any, int) and company_id_any not in keys:
        keys.append(company_id_any)
    return keys


def _clean_phone(phone_raw: str) -> str:
    """
    Basic phone normalizer/validator for WhatsApp use.

    Rules we enforce:
      - strip spaces, dashes, parentheses, dots
      - must start with '+'
      - rest must be digits
      - length must look reasonable (8 to ~20 chars)

    Raises ValueError if invalid.
    """
    p = (phone_raw or "").strip()

    # remove common formatting chars
    for ch in (" ", "-", "(", ")", "."):
        p = p.replace(ch, "")

    if not p:
        raise ValueError("Phone is required.")

    if not p.startswith("+"):
        raise ValueError("Phone must include country code (e.g. +60123456789).")

    digits_only = p[1:]
    if not digits_only.isdigit():
        raise ValueError("Phone must contain only digits after '+'.")

    if len(p) < 8 or len(p) > 20:
        raise ValueError("Phone number length looks invalid.")

    return p


# ───────────────────────── CRUD (Firestore) ─────────────────────────
def list_workers(company_id: Any, search: str = "") -> List[Dict[str, Any]]:
    """
    Return workers for a company, optional case-insensitive substring search
    against worker_id, name, or phone.

    Each row shape:
      {
        "doc_id": str,
        "company_id": ...,
        "worker_id": str,
        "name": str,
        "phone": str,
        "active": bool,
        "created_at": int (ms),
      }
    """
    db = get_db()
    keys = _company_keys(company_id)
    q = db.collection("workers")

    # Prefer server-side filter when possible, otherwise fetch and filter locally
    try:
        if any_in and len(keys) > 1:
            q = any_in(q, "company_id", keys)
            docs = list(q.stream())
        elif eq and len(keys) == 1:
            q = eq(q, "company_id", keys[0])
            docs = list(q.stream())
        else:
            docs = list(q.stream())
    except Exception:
        docs = list(q.stream())

    needle = (search or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for d in docs:
        data = d.to_dict() or {}
        if data.get("company_id") not in keys:
            continue
        row = {
            "doc_id": d.id,
            "company_id": data.get("company_id"),
            "worker_id": _s(data.get("worker_id")),
            "name": _s(data.get("name")),
            "phone": _s(data.get("phone")),  # may be empty for old docs
            "active": bool(data.get("active", True)),
            "created_at": int(data.get("created_at", 0) or 0),
        }

        if needle:
            hay = f"{row['worker_id']} {row['name']} {row['phone']}".lower()
            if needle not in hay:
                continue

        out.append(row)

    out.sort(key=lambda x: (not x["active"], x["worker_id"]))
    return out


def _assert_unique_worker_id(company_id: Any, worker_id: str, exclude_doc_id: Optional[str] = None) -> None:
    """Raise ValueError if worker_id already exists in that company (excluding exclude_doc_id)."""
    db = get_db()
    keys = _company_keys(company_id)
    worker_id_l = _s(worker_id).lower()

    q = db.collection("workers")
    try:
        if any_in:
            q = any_in(q, "company_id", keys)
    except Exception:
        pass

    for d in q.stream():
        if exclude_doc_id and d.id == exclude_doc_id:
            continue
        dd = d.to_dict() or {}
        if dd.get("company_id") in keys and _s(dd.get("worker_id")).lower() == worker_id_l:
            raise ValueError(f"Worker ID '{worker_id}' already exists in this company.")


def create_worker(company_id: Any, worker_id: str, name: str, phone: str) -> str:
    """
    Create a worker (manual ID). Enforces uniqueness of worker_id per company.
    Requires phone.
    Returns the Firestore document id.
    """
    db = get_db()
    worker_id = _s(worker_id)
    name = _s(name)
    phone = _clean_phone(phone)

    if not worker_id or not name:
        raise ValueError("Worker ID and Name are required.")

    _assert_unique_worker_id(company_id, worker_id)

    keys = _company_keys(company_id)
    ref = db.collection("workers").document()
    ref.set({
        "company_id": keys[0],      # store canonical form (first resolved key)
        "worker_id": worker_id,
        "name": name,
        "phone": phone,
        "active": True,
        "created_at": int(time.time() * 1000),
    })
    return ref.id


def update_worker(
    doc_id: str,
    *,
    company_id: Any,
    worker_id: Optional[str] = None,
    name: Optional[str] = None,
    phone: Optional[str] = None,
) -> None:
    """
    Update worker fields. If worker_id changes, enforce uniqueness within the company.
    Also validates phone if provided.
    """
    db = get_db()
    updates: Dict[str, Any] = {}

    if name is not None:
        updates["name"] = _s(name)

    if worker_id is not None:
        new_id = _s(worker_id)
        if new_id:
            _assert_unique_worker_id(company_id, new_id, exclude_doc_id=doc_id)
        updates["worker_id"] = new_id

    if phone is not None:
        updates["phone"] = _clean_phone(phone)

    if not updates:
        return

    db.collection("workers").document(doc_id).update(updates)


def update_worker_name(doc_id: str, new_name: str) -> None:
    """Kept for backward-compat; not used by the new page but safe to keep."""
    get_db().collection("workers").document(doc_id).update({"name": _s(new_name)})


def set_worker_active(doc_id: str, active: bool) -> None:
    """Activate/deactivate the worker (soft toggle)."""
    get_db().collection("workers").document(doc_id).update({"active": bool(active)})


def delete_worker(doc_id: str) -> None:
    """Hard delete worker document."""
    get_db().collection("workers").document(doc_id).delete()


# ───────────────────────── Lookups for Logs / WhatsApp ─────────────────────────
def find_workers_by_name(company_id: Any, name_query: str, *, active_only: bool = False) -> List[Dict[str, Any]]:
    """
    Case-insensitive *substring* search by name within a company.
    Returns worker dicts in the same shape as list_workers().
    """
    q = _s(name_query).lower()
    if not q:
        return []
    matches: List[Dict[str, Any]] = []
    for w in list_workers(company_id):
        if active_only and not w["active"]:
            continue
        if q in (w["name"] or "").lower():
            matches.append(w)
    return matches


def find_worker_by_exact_name(company_id: Any, name: str, *, active_only: bool = False) -> Optional[Dict[str, Any]]:
    """
    Case-insensitive *exact* name match. Returns a single worker or None.
    If multiple workers share the same exact name, returns None (ambiguous).
    """
    n = _s(name).lower()
    if not n:
        return None
    exact = [
        w for w in list_workers(company_id)
        if (not active_only or w["active"]) and (w["name"].lower() == n)
    ]
    if len(exact) == 1:
        return exact[0]
    return None


def get_worker_by_worker_id(company_id: Any, worker_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch ONE worker in this company by their worker_id (e.g. 'W123').
    Returns same shape as list_workers() rows, or None if not found.

    This is what we'll use when we want to WhatsApp-message the offender:
    we know offender_id = 'W123' from the violation row, so we look up
    that worker to get their phone number.
    """
    target = _s(worker_id).lower()
    if not target:
        return None

    for w in list_workers(company_id):
        if _s(w["worker_id"]).lower() == target:
            return w
    return None
