# services/firebase_db.py
from typing import Dict, List, Optional
from firebase_admin import firestore
from .firebase_client import get_db

# --------- counters (transactional) ---------
_COUNTERS_DOC = ("meta", "counters")   # collection "meta", doc "counters"
_COUNTER_FIELD = "company_seq"

def _ensure_counters_doc(db):
    ref = db.collection(_COUNTERS_DOC[0]).document(_COUNTERS_DOC[1])
    snap = ref.get()
    if not snap.exists:
        ref.set({_COUNTER_FIELD: 0})

@firestore.transactional
def _next_company_seq_txn(transaction, db) -> int:
    ref = db.collection(_COUNTERS_DOC[0]).document(_COUNTERS_DOC[1])
    snapshot = ref.get(transaction=transaction)
    data = snapshot.to_dict() or {}
    current = int(data.get(_COUNTER_FIELD, 0))
    nxt = current + 1
    transaction.update(ref, {_COUNTER_FIELD: nxt})
    return nxt

def next_company_seq() -> int:
    db = get_db()
    _ensure_counters_doc(db)
    txn = db.transaction()
    return _next_company_seq_txn(txn, db)

# ---------- Companies ----------
def create_company(name: str, code: Optional[str] = None) -> str:
    """
    Create a company with an incremental numeric ID (1,2,3,...).
    Returns the string doc id (e.g., "1").
    """
    if not name or not name.strip():
        raise ValueError("Company name is required.")
    db = get_db()
    seq = next_company_seq()                 # 1, 2, 3, ...
    doc_id = str(seq)                        # use numeric id as document id
    ref = db.collection("companies").document(doc_id)
    data = {
        "id": seq,                            # store numeric id for queries/sorts
        "name": name.strip(),
        "code": (code or f"C{seq:04d}"),
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    ref.set(data)
    return doc_id

def list_companies() -> List[Dict]:
    """
    Returns companies sorted by numeric id ascending.
    [{id:int, name, code, created_at}, ...]
    """
    db = get_db()
    # Prefer ordering by 'id' (int). Fallback to name if old docs exist.
    snaps = db.collection("companies").order_by("id").stream()
    out: List[Dict] = []
    for s in snaps:
        d = s.to_dict() or {}
        # normalize id: if missing, try to parse doc id as int; else skip
        if "id" not in d:
            try:
                d["id"] = int(s.id)
            except Exception:
                d["id"] = None
        d["doc_id"] = s.id
        out.append(d)
    # final safety sort (local) in case mixed data
    out.sort(key=lambda x: (x.get("id") is None, x.get("id", 0)))
    return out

# ---------- Users (kept for reference; not used on this page) ----------
def create_company_admin(company_id: str, email: str, role: str = "company_admin"):
    """
    Mirror a company admin into 'users' (Auth integration handled elsewhere).
    """
    db = get_db()
    db.collection("users").document(email.lower()).set({
        "email": email.lower(),
        "role": role,
        "company_id": company_id,
        "active": True,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
