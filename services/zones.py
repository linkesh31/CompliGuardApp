# services/zones.py
from __future__ import annotations

import unicodedata
from urllib.parse import urlparse
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta

from firebase_admin import firestore
from .firebase_client import get_db
from .firestore_compat import eq

# ──────────────────────────────────────────────────────────────
# Validation constants
# ──────────────────────────────────────────────────────────────
MAX_NAME_LEN = 100
MAX_URL_LEN = 512
ALLOWED_SCHEMES = {"rtsp", "rtspu", "rtmp", "http", "https"}
# If you ever want uniqueness scoped to zone instead of company, set this False
UNIQUE_PER_COMPANY = True

# Zero-width / invisible characters we want to reject explicitly
_INVISIBLE_CHARS = {
    "\u200B",  # ZERO WIDTH SPACE
    "\u200C",  # ZERO WIDTH NON-JOINER
    "\u200D",  # ZERO WIDTH JOINER
    "\u2060",  # WORD JOINER
    "\uFEFF",  # ZERO WIDTH NO-BREAK SPACE
}

def _has_invisible(s: str) -> bool:
    return any(ch in _INVISIBLE_CHARS for ch in s or "")

def _has_control(s: str) -> bool:
    """True if any Unicode category starts with 'C' (control, format, surrogate, etc.)."""
    for ch in s or "":
        if unicodedata.category(ch).startswith("C"):
            return True
    return False

def _has_whitespace(s: str) -> bool:
    return any(ch.isspace() for ch in s or "")

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _company_keys(company_id_any: Any) -> List[Any]:
    keys: List[Any] = []
    s = str(company_id_any).strip()
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

def _normalize_zone(doc_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    d = (data or {}).copy()
    d.setdefault("name", "")
    d.setdefault("description", "")
    d.setdefault("company_id", None)
    d.setdefault("risk_level", "med")
    d.setdefault("created_at", None)
    d.setdefault("updated_at", None)
    d["id"] = doc_id
    return d

def camera_status(cam: dict, *, heartbeat_seconds: int = 120) -> tuple[str, str]:
    hb = cam.get("last_heartbeat")
    if hb is not None:
        try:
            now = datetime.now(timezone.utc)
            if getattr(hb, "tzinfo", None) is None:
                hb = hb.replace(tzinfo=timezone.utc)
            if now - hb <= timedelta(seconds=heartbeat_seconds):
                return ("Online •", "online")
            else:
                return ("Offline •", "offline")
        except Exception:
            pass
    if cam.get("online") is True:
        return ("Online •", "online")
    return ("Offline •", "offline")

# ──────────────────────────────────────────────────────────────
# Zones
# ──────────────────────────────────────────────────────────────
def list_zones(company_id: Any) -> List[Dict[str, Any]]:
    db = get_db()
    keys = _company_keys(company_id)
    seen: Dict[str, Dict[str, Any]] = {}
    for k in keys:
        try:
            for s in eq(db.collection("zones"), "company_id", k).stream():
                seen[s.id] = _normalize_zone(s.id, s.to_dict() or {})
        except Exception:
            pass
    for z in seen.values():
        z["camera_count"] = count_cameras_in_zone(z["id"])
    out = list(seen.values())
    out.sort(key=lambda x: x.get("name", "").lower())
    return out

def get_zone(zone_id: str) -> Optional[Dict[str, Any]]:
    if not zone_id:
        return None
    db = get_db()
    s = db.collection("zones").document(zone_id).get()
    if not s.exists:
        return None
    return _normalize_zone(s.id, s.to_dict() or {})

def create_zone(*, company_id: Any, name: str, description: str = "", risk_level: str = "med") -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Zone name is required.")
    rl = (risk_level or "med").lower()
    if rl not in ("low", "med", "high"):
        raise ValueError("risk_level must be one of: low, med, high.")
    db = get_db()
    taken = set()
    for k in _company_keys(company_id):
        try:
            for s in eq(db.collection("zones"), "company_id", k).stream():
                d = s.to_dict() or {}
                taken.add((d.get("name") or "").strip().lower())
        except Exception:
            pass
    if name.lower() in taken:
        raise ValueError(f"A zone named '{name}' already exists in this company.")
    payload = {
        "name": name,
        "description": description.strip(),
        "company_id": str(company_id).strip(),
        "risk_level": rl,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    ref = db.collection("zones").document()
    ref.set(payload)
    s = ref.get()
    return _normalize_zone(s.id, s.to_dict() or {})

def update_zone(zone_id: str, *, name: Optional[str] = None, description: Optional[str] = None, risk_level: Optional[str] = None) -> None:
    if not zone_id:
        raise ValueError("Zone id is required.")
    updates: Dict[str, Any] = {}
    if name is not None:
        nm = name.strip()
        if not nm:
            raise ValueError("Name cannot be empty.")
        updates["name"] = nm
    if description is not None:
        updates["description"] = description.strip()
    if risk_level is not None:
        rl = risk_level.strip().lower()
        if rl not in ("low", "med", "high"):
            raise ValueError("risk_level must be one of: low, med, high.")
        updates["risk_level"] = rl
    if not updates:
        return
    updates["updated_at"] = firestore.SERVER_TIMESTAMP
    db = get_db()
    ref = db.collection("zones").document(zone_id)
    if not ref.get().exists:
        raise ValueError("Zone not found.")
    ref.update(updates)

def delete_zone(zone_id: str, *, force: bool = False, reassign_to_zone_id: Optional[str] = None) -> None:
    if not zone_id:
        raise ValueError("Zone id is required.")
    db = get_db()
    zone_ref = db.collection("zones").document(zone_id)
    if not zone_ref.get().exists:
        raise ValueError("Zone not found.")
    cams = list_cameras_by_zone(zone_id)
    if cams:
        if reassign_to_zone_id:
            for c in cams:
                assign_camera_to_zone(c["id"], reassign_to_zone_id)
        elif force:
            for c in cams:
                unassign_camera(c["id"])
        else:
            raise ValueError("Zone has cameras assigned. Use force=True or pick a target zone.")
    zone_ref.delete()

# ──────────────────────────────────────────────────────────────
# Cameras: validation helpers
# ──────────────────────────────────────────────────────────────
def _camera_name_taken(*, company_id: Any, name_lower: str, exclude_camera_id: Optional[str] = None,
                       zone_id: Optional[str] = None) -> bool:
    db = get_db()
    if UNIQUE_PER_COMPANY or zone_id is None:
        for k in _company_keys(company_id):
            try:
                for s in eq(db.collection("cameras"), "company_id", k).stream():
                    if exclude_camera_id and s.id == exclude_camera_id:
                        continue
                    d = s.to_dict() or {}
                    nm = (d.get("name") or "").strip().lower()
                    if nm == name_lower:
                        return True
            except Exception:
                pass
        return False
    else:
        try:
            for s in eq(db.collection("cameras"), "zone_id", zone_id).stream():
                if exclude_camera_id and s.id == exclude_camera_id:
                    continue
                d = s.to_dict() or {}
                nm = (d.get("name") or "").strip().lower()
                if nm == name_lower:
                    return True
        except Exception:
            pass
        return False

def _validate_camera_name(*, company_id: Any, name: str, exclude_camera_id: Optional[str] = None,
                          zone_id: Optional[str] = None) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("Camera name is required.")
    if len(name) > MAX_NAME_LEN:
        raise ValueError(f"Camera name is too long (>{MAX_NAME_LEN} characters).")
    if _has_control(name) or _has_invisible(name):
        raise ValueError("Camera name contains control or invisible characters.")
    if _camera_name_taken(company_id=company_id, name_lower=name.lower(),
                          exclude_camera_id=exclude_camera_id, zone_id=zone_id):
        scope = "company" if UNIQUE_PER_COMPANY or zone_id is None else "zone"
        raise ValueError(f"A camera named '{name}' already exists in this {scope}.")
    return name

def _validate_rtsp_url(rtsp_url: str) -> str:
    u = (rtsp_url or "").strip()
    if not u:
        raise ValueError("RTSP / Source URL is required.")
    if len(u) > MAX_URL_LEN:
        raise ValueError(f"Source URL is too long (>{MAX_URL_LEN} characters).")
    if _has_whitespace(u) or _has_invisible(u):
        raise ValueError("Source URL contains whitespace or invisible characters.")
    parsed = urlparse(u)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        allowed = ", ".join(sorted(ALLOWED_SCHEMES))
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Allowed: {allowed}.")
    if not parsed.netloc:
        raise ValueError("Source URL must include a host (e.g., rtsp://host/stream).")
    if parsed.path is None or len(parsed.path) == 0:
        raise ValueError("Source URL must include a path (e.g., rtsp://host/stream).")
    return u

# ──────────────────────────────────────────────────────────────
# Cameras
# ──────────────────────────────────────────────────────────────
def list_cameras_by_company(company_id: Any) -> List[Dict[str, Any]]:
    db = get_db()
    keys = _company_keys(company_id)
    seen: Dict[str, Dict[str, Any]] = {}
    for k in keys:
        try:
            for s in eq(db.collection("cameras"), "company_id", k).stream():
                d = s.to_dict() or {}
                seen[s.id] = {
                    "id": s.id,
                    "name": d.get("name", s.id),
                    "zone_id": d.get("zone_id"),
                    "company_id": d.get("company_id"),
                    "rtsp_url": d.get("rtsp_url", ""),
                    "mode": (d.get("mode") or "monitor"),
                    "online": d.get("online"),
                    "status": d.get("status"),
                    "enabled": d.get("enabled"),
                    "last_heartbeat": d.get("last_heartbeat"),
                }
        except Exception:
            pass
    cams = list(seen.values())
    cams.sort(key=lambda x: (x.get("name") or "").lower())
    return cams

def list_cameras_by_zone(zone_id: str) -> List[Dict[str, Any]]:
    if not zone_id:
        return []
    db = get_db()
    out: List[Dict[str, Any]] = []
    try:
        for s in eq(db.collection("cameras"), "zone_id", zone_id).stream():
            d = s.to_dict() or {}
            out.append({
                "id": s.id,
                "name": d.get("name", s.id),
                "zone_id": d.get("zone_id"),
                "company_id": d.get("company_id"),
                "rtsp_url": d.get("rtsp_url", ""),
                "mode": (d.get("mode") or "monitor"),
                "online": d.get("online"),
                "status": d.get("status"),
                "enabled": d.get("enabled"),
                "last_heartbeat": d.get("last_heartbeat"),
            })
    except Exception:
        pass
    out.sort(key=lambda x: (x.get("name") or "").lower())
    return out

def count_cameras_in_zone(zone_id: str) -> int:
    return len(list_cameras_by_zone(zone_id))

def create_camera(*, company_id: Any, name: str, rtsp_url: str = "", zone_id: Optional[str] = None, mode: str = "monitor") -> Dict[str, Any]:
    valid_name = _validate_camera_name(company_id=company_id, name=name, zone_id=zone_id)
    valid_url = _validate_rtsp_url(rtsp_url)
    mode = (mode or "monitor").strip().lower()
    if mode not in ("monitor", "entry"):
        raise ValueError("Camera mode must be 'monitor' or 'entry'.")
    db = get_db()
    payload = {
        "name": valid_name,
        "company_id": str(company_id).strip(),
        "rtsp_url": valid_url,
        "zone_id": zone_id or None,
        "mode": mode,
        "online": False,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    ref = db.collection("cameras").document()
    ref.set(payload)
    s = ref.get()
    d = s.to_dict() or {}
    return {
        "id": s.id,
        "name": d.get("name", s.id),
        "zone_id": d.get("zone_id"),
        "company_id": d.get("company_id"),
        "rtsp_url": d.get("rtsp_url", ""),
        "mode": (d.get("mode") or "monitor"),
        "online": d.get("online"),
        "status": d.get("status"),
        "enabled": d.get("enabled"),
        "last_heartbeat": d.get("last_heartbeat"),
    }

def update_camera(camera_id: str, *, name: Optional[str] = None, rtsp_url: Optional[str] = None, mode: Optional[str] = None) -> None:
    if not camera_id:
        raise ValueError("camera_id required.")
    db = get_db()
    ref = db.collection("cameras").document(camera_id)
    snap = ref.get()
    if not snap.exists:
        raise ValueError("Camera not found.")
    cur = snap.to_dict() or {}
    company_id = cur.get("company_id")
    zone_id = cur.get("zone_id")
    updates: Dict[str, Any] = {}
    if name is not None:
        nm = _validate_camera_name(company_id=company_id, name=name,
                                   exclude_camera_id=camera_id, zone_id=zone_id)
        updates["name"] = nm
    if rtsp_url is not None:
        url = _validate_rtsp_url(rtsp_url)
        updates["rtsp_url"] = url
    if mode is not None:
        m = (mode or "").strip().lower()
        if m not in ("monitor", "entry"):
            raise ValueError("mode must be 'monitor' or 'entry'")
        updates["mode"] = m
    if not updates:
        return
    updates["updated_at"] = firestore.SERVER_TIMESTAMP
    ref.update(updates)

def delete_camera(camera_id: str) -> None:
    if not camera_id:
        raise ValueError("camera_id required.")
    db = get_db()
    ref = db.collection("cameras").document(camera_id)
    if not ref.get().exists:
        raise ValueError("Camera not found.")
    ref.delete()

def assign_camera_to_zone(camera_id: str, zone_id: Optional[str]) -> None:
    if not camera_id:
        raise ValueError("camera_id required.")
    db = get_db()
    ref = db.collection("cameras").document(camera_id)
    if not ref.get().exists:
        raise ValueError("Camera not found.")
    ref.update({"zone_id": zone_id or None, "updated_at": firestore.SERVER_TIMESTAMP})

def unassign_camera(camera_id: str) -> None:
    assign_camera_to_zone(camera_id, None)
