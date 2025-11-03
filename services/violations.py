from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple, List

from services.firebase_client import get_db

# try to use helper operators if you already have them (for tolerant queries)
try:
    from services.firestore_compat import eq, any_in  # type: ignore
except Exception:
    eq = any_in = None  # type: ignore


# ───────────────────────── small utils ─────────────────────────
def _s(v: Any) -> str:
    """stringify + trim, never returns None."""
    return ("" if v is None else str(v)).strip()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _company_keys(company_id_any: Any) -> List[Any]:
    """
    Normalize company_id to a list of equivalent keys, so we match
    both string '2' and integer 2 if Firestore data isn't consistent.
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


# ───────────────────────── internal helpers ─────────────────────────
def _get_violation_doc(db, violation_id: str):
    """
    Return (snapshot, data_dict) or (None, None) if not found.
    """
    ref = db.collection("violations").document(violation_id)
    snap = ref.get()
    if not snap.exists:
        return None, None
    data = snap.to_dict() or {}
    return snap, data


def _ensure_strike_record(
    db,
    *,
    violation_id: str,
    worker_id: str,
    worker_name: str,
    company_id: Any,
) -> None:
    """
    Make sure there's a strike entry for this violation.
    We store 1 strike per violation for that worker.

    strikes doc shape (example):
    {
        "company_id": "123",
        "worker_id": "W001",
        "worker_name": "Ali",
        "violation_id": "<violation doc id>",
        "created_at": 1710000000000
    }
    """
    strikes_coll = db.collection("strikes")

    # check if already exists for this violation_id
    existing = list(strikes_coll.where("violation_id", "==", violation_id).stream())
    if existing:
        return  # already logged as a strike

    # if not, create
    doc_ref = strikes_coll.document()
    doc_ref.set(
        {
            "company_id": _company_keys(company_id)[0],
            "worker_id": worker_id,
            "worker_name": worker_name,
            "violation_id": violation_id,
            "created_at": _now_ms(),
        }
    )


def _count_worker_strikes(
    db,
    *,
    worker_id: str,
    company_id: Any,
) -> int:
    """
    Count how many strike docs exist for this worker in this company.
    """
    strikes_coll = db.collection("strikes")
    keys = _company_keys(company_id)

    # try to filter in Firestore first for perf
    # strategy: get strikes where worker_id == worker_id
    # then locally filter company match, because company_id may be "2" or 2
    query = strikes_coll.where("worker_id", "==", worker_id)

    docs = list(query.stream())
    count = 0
    for d in docs:
        data = d.to_dict() or {}
        if data.get("company_id") in keys:
            count += 1
    return count


# ───────────────────────── main entrypoint used by LogsPage ─────────────────────────
def record_offender_on_violation(
    *,
    violation_id: str,
    worker: Dict[str, Any],
    company_id: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[int], Optional[str]]:
    """
    Called by LogsPage._identify_offender() after admin picks a worker.

    1. Loads the violation doc
    2. Writes offender_name / offender_id / offender_phone
    3. Creates (or ensures) a "strike" record for this violation
    4. Counts total strikes for that worker in this company
    5. Returns updated violation dict (merged), strike_count, and error string (if any)

    Return shape:
        (
            violation_after_dict_or_None,
            strike_count_or_None,
            error_message_or_None
        )
    """

    db = get_db()

    # ---- 1. fetch violation ----
    snap, vio_data = _get_violation_doc(db, violation_id)
    if snap is None or vio_data is None:
        return None, None, f"Violation '{violation_id}' not found."

    # ---- 2. build updates for violation ----
    worker_name = _s(worker.get("name"))
    worker_id = _s(worker.get("worker_id"))
    worker_phone = _s(worker.get("phone"))

    if not worker_id:
        return None, None, "Worker record missing worker_id."
    # phone can be blank, but WhatsApp step might fail later if blank

    update_fields: Dict[str, Any] = {
        "offender_name": worker_name,
        "offender_id": worker_id,
        "offender_phone": worker_phone,
        "updated_at": _now_ms(),
    }

    # also store company_id on violation if it was somehow missing (defensive)
    if "company_id" not in vio_data or _s(vio_data.get("company_id")) == "":
        update_fields["company_id"] = _company_keys(company_id)[0]

    # push to Firestore
    try:
        db.collection("violations").document(violation_id).update(update_fields)
    except Exception as e:
        return None, None, f"Failed to update violation: {e}"

    # merge new state for returning to caller
    vio_after = dict(vio_data)
    vio_after.update(update_fields)

    # ---- 3. make sure there's a strike row ----
    try:
        _ensure_strike_record(
            db,
            violation_id=violation_id,
            worker_id=worker_id,
            worker_name=worker_name,
            company_id=company_id,
        )
    except Exception as e:
        # we won't block the rest just because strike failed,
        # but we do report it back
        return vio_after, None, f"Failed to record strike: {e}"

    # ---- 4. count strikes for this worker ----
    try:
        strike_count = _count_worker_strikes(
            db,
            worker_id=worker_id,
            company_id=company_id,
        )
    except Exception as e:
        return vio_after, None, f"Failed to count strikes: {e}"

    # ---- 5. return success ----
    return vio_after, strike_count, None
