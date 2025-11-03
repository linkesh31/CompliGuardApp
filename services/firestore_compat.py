# services/firestore_compat.py
"""
Compat helpers to use Firestore's new filter=FieldFilter API while gracefully
falling back to the old where(field, op, value) when FieldFilter isn't available.
"""

from typing import Any

# Try both import paths (SDK versions vary)
_HAS_FIELD_FILTER = False
FieldFilter = None  # type: ignore

try:
    from google.cloud.firestore_v1.base_query import FieldFilter as _FF  # type: ignore
    FieldFilter = _FF  # type: ignore
    _HAS_FIELD_FILTER = True
except Exception:
    try:
        from google.cloud.firestore_v1 import FieldFilter as _FF  # type: ignore
        FieldFilter = _FF  # type: ignore
        _HAS_FIELD_FILTER = True
    except Exception:
        _HAS_FIELD_FILTER = False


def _apply(q: Any, field: str, op: str, value: Any):
    """Apply a single filter: prefer new API, fallback to old .where()."""
    if _HAS_FIELD_FILTER and FieldFilter is not None:
        return q.where(filter=FieldFilter(field, op, value))
    return q.where(field, op, value)


# Public helpers for common operators
def eq(q: Any, field: str, value: Any):
    return _apply(q, field, "==", value)

def gt(q: Any, field: str, value: Any):
    return _apply(q, field, ">", value)

def gte(q: Any, field: str, value: Any):
    return _apply(q, field, ">=", value)

def lt(q: Any, field: str, value: Any):
    return _apply(q, field, "<", value)

def lte(q: Any, field: str, value: Any):
    return _apply(q, field, "<=", value)

def any_in(q: Any, field: str, values: list):
    return _apply(q, field, "in", values)

def not_in(q: Any, field: str, values: list):
    return _apply(q, field, "not-in", values)

def array_contains(q: Any, field: str, value: Any):
    return _apply(q, field, "array-contains", value)

def array_contains_any(q: Any, field: str, values: list):
    return _apply(q, field, "array-contains-any", values)
