"""
services/messaging.py

Lightweight WhatsApp launcher (no Twilio).

Flow:
1) After admin selects the offender in LogsPage._identify_offender(),
   we call record_offender_on_violation() which:
   - updates the violation with offender info
   - logs a strike
   - counts total strikes

2) LogsPage then calls prepare_and_send_whatsapp(...) with:
   - violation_after (dict with offender info, zone, etc.)
   - strike_count (int)
   - company_name (STRING YOU WANT SHOWN IN THE MESSAGE)

3) We:
   - figure out target phone (offender_phone inside violation_after)
   - generate human-readable message text based on strike_count
     (1st = notice, 2nd = reminder, 3rd+ = warning; 3rd is fully bold)
   - ALWAYS include an explicit "Risk Level: High/Medium/Low" line (or N/A)
   - open https://wa.me/<digits>?text=<encoded>
   - return debug info back to the caller
"""

from __future__ import annotations

import urllib.parse
import webbrowser
import datetime
from typing import Any, Dict, Optional


# ───────────────────────── basic helpers ─────────────────────────
def _s(v: Any) -> str:
    return ("" if v is None else str(v)).strip()


def _normalize_phone_for_wa(raw_phone: str) -> str:
    """
    Convert a phone string (we store it like +60...) into wa.me format:
    digits only, no '+', no spaces.
    """
    p = (raw_phone or "").strip()
    for ch in (" ", "-", "(", ")", "."):
        p = p.replace(ch, "")
    if p.startswith("+"):
        p = p[1:]
    if not p.isdigit():
        raise ValueError("Phone must be numeric with country code, e.g. +60123456789")
    if len(p) < 8 or len(p) > 20:
        raise ValueError("Phone length looks invalid for WhatsApp")
    return p


def _fmt_ts_human(ts_any: Any) -> str:
    """Return 'YYYY-MM-DD HH:MM' for various timestamp shapes."""
    try:
        if isinstance(ts_any, (int, float)):
            val = float(ts_any)
            if val > 1e12:  # ms -> s
                val = val / 1000.0
            dt = datetime.datetime.fromtimestamp(val)
            return dt.strftime("%Y-%m-%d %H:%M")
        if hasattr(ts_any, "timestamp"):
            val = ts_any.timestamp()
            dt = datetime.datetime.fromtimestamp(val)
            return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return _s(ts_any)


# ───────────────────────── risk parsing ─────────────────────────
def _parse_zone_level(raw: str) -> Dict[str, str]:
    """
    Parse only the area risk level (low/medium/high) from an arbitrary string.
    Returns {"zone_level": "", "zone_label": ""} if unknown.
    """
    t = _s(raw).lower()
    out = {"zone_level": "", "zone_label": ""}
    if not t:
        return out

    if "high" in t or t == "3" or "critical" in t or "severe" in t:
        out["zone_level"] = "high"
        out["zone_label"] = "High Risk Area"
    elif "med" in t or "medium" in t or t == "2":
        out["zone_level"] = "medium"
        out["zone_label"] = "Medium Risk Area"
    elif "low" in t or t == "1":
        out["zone_level"] = "low"
        out["zone_label"] = "Low Risk Area"
    return out


def _risk_parse_for_issue(raw_risk: str) -> Dict[str, Any]:
    """
    Build the 'Issue:' text focusing on which PPE items were missing.
    Also returns zone_level/label if present in the same string (backward-compat).
    """
    t = _s(raw_risk).lower()
    info = {
        "ppe_list": [],
        "zone_level": "",
        "zone_label": "",
        "pretty_issue": "",
    }
    if not t:
        return info

    # detect missing PPE
    if "helmet" in t or "hardhat" in t or "hard_hat" in t:
        info["ppe_list"].append("Helmet Missing")
    if "vest" in t or "safety_vest" in t or "safety vest" in t:
        info["ppe_list"].append("Vest Missing")
    if "glove" in t or "gloves" in t or "hand_glove" in t:
        info["ppe_list"].append("Gloves Missing")
    if "boot" in t or "boots" in t or "shoe" in t or "safety_shoe" in t:
        info["ppe_list"].append("Boots Missing")

    # also pick up level if the same field includes it
    level = _parse_zone_level(raw_risk)
    info["zone_level"] = level["zone_level"]
    info["zone_label"] = level["zone_label"]

    # build Issue:
    if info["ppe_list"]:
        info["pretty_issue"] = ", ".join(info["ppe_list"])
    else:
        # if no explicit PPE, fall back to generic risk if present
        if info["zone_level"] == "high":
            info["pretty_issue"] = "High Risk"
        elif info["zone_level"] == "medium":
            info["pretty_issue"] = "Medium Risk"
        elif info["zone_level"] == "low":
            info["pretty_issue"] = "Low Risk"
        else:
            info["pretty_issue"] = raw_risk or "—"

    return info


def _extract_zone_risk_from_violation(vio: Dict[str, Any]) -> Dict[str, str]:
    """
    Try multiple common keys / shapes to read the zone's risk level from the violation.
    """
    candidates = [
        "zone_risk",
        "zone_risk_level",
        "area_risk",
        "area_severity",
        "zone_level",
    ]
    for k in candidates:
        val = _s(vio.get(k))
        if val:
            return _parse_zone_level(val)

    # nested zone dict
    z = vio.get("zone") or {}
    if isinstance(z, dict):
        for k in ("risk", "risk_level", "severity", "level"):
            val = _s(z.get(k))
            if val:
                return _parse_zone_level(val)

    # final fallback to legacy fields (may mix PPE text + level)
    fallback = _s(vio.get("risk")) or _s(vio.get("risk_level")) or _s(vio.get("severity"))
    return _parse_zone_level(fallback)


def _ordinal(n: int) -> str:
    """1 -> 1st, 2 -> 2nd, 3 -> 3rd, 4 -> 4th, ..."""
    s = str(n)
    if n % 100 in (11, 12, 13):
        return s + "th"
    last = n % 10
    if last == 1:
        return s + "st"
    if last == 2:
        return s + "nd"
    if last == 3:
        return s + "rd"
    return s + "th"


def _boldify_whatsapp(text: str) -> str:
    """
    Wrap every non-empty line in *...* to make it bold in WhatsApp.
    Applies only when strike_count == 3 (exactly third violation).
    """
    lines = text.splitlines()
    return "\n".join([f"*{ln}*" if _s(ln) else ln for ln in lines])


# ───────────────────────── message builder ─────────────────────────
def _build_message_text(
    *,
    vio: Dict[str, Any],
    strike_count: Optional[int],
    company_name: str,
) -> str:
    """
    Build the WhatsApp body text.
    - Always include an explicit "Risk Level: ..." line (N/A if unknown).
    - Bold entire message only for exactly the 3rd violation.
    """

    # offender
    name = _s(vio.get("offender_name"))
    wid = _s(vio.get("offender_id"))

    # zone name
    zone = _s(vio.get("zone_name") or vio.get("zone_id") or "")

    # legacy risk field used for PPE 'Issue:' extraction
    raw_risk = _s(vio.get("risk")) or _s(vio.get("risk_level")) or _s(vio.get("severity"))
    issue_info = _risk_parse_for_issue(raw_risk)

    # zone risk level from broader set of keys
    zone_level_info = _extract_zone_risk_from_violation(vio)

    # timestamp
    ts_any = vio.get("ts") or vio.get("time") or vio.get("created_at")
    when_txt = _fmt_ts_human(ts_any)

    # tone by strike
    sc = strike_count if strike_count is not None else 1
    if sc <= 1:
        header = "SAFETY NOTICE"
        strike_line = "You were just recorded without full PPE. Please correct this immediately."
        closing_line = "Please wear your safety helmet, vest, gloves and boots at all times. This is a safety requirement."
    elif sc == 2:
        header = "SAFETY REMINDER"
        strike_line = "This is your 2nd recorded safety violation. You must wear full PPE immediately."
        closing_line = "Continued non-compliance will lead to disciplinary action."
    else:
        header = "SAFETY WARNING"
        strike_line = f"This is your { _ordinal(sc) } recorded safety violation. This is a formal warning."
        closing_line = "Further violations may result in removal from site. Wear full PPE now. Please contact your HR/Supervisor."

    # Lines
    lines = [
        f"⚠ {header} ⚠",
        f"Company/Site: {company_name}",
        f"Worker: {name} (ID {wid})" if (name and wid) else f"Worker: {name or wid}",
    ]

    if issue_info["pretty_issue"]:
        lines.append(f"Issue: {issue_info['pretty_issue']}")

    # Zone line + label (if known)
    zone_line = f"Zone: {zone or 'N/A'}"
    if issue_info["zone_label"]:  # from legacy risk string (if present)
        zone_line += f" ({issue_info['zone_label']})"
    elif zone_level_info["zone_label"]:
        zone_line += f" ({zone_level_info['zone_label']})"
    lines.append(zone_line)

    # Always show Risk Level line (capitalize if known, else N/A)
    if zone_level_info["zone_level"]:
        lines.append(f"Risk Level: {zone_level_info['zone_level'].capitalize()}")
    else:
        lines.append("Risk Level: N/A")

    lines.extend(
        [
            f"Time: {when_txt}",
            strike_line,
            "",
            closing_line,
        ]
    )

    # build text
    msg = "\n".join([ln for ln in lines if _s(ln)])

    # Bold entire message only for exactly the 3rd violation
    if sc == 3:
        msg = _boldify_whatsapp(msg)

    return msg


# ───────────────────────── public entrypoint ─────────────────────────
def prepare_and_send_whatsapp(
    *,
    violation: Dict[str, Any],
    strike_count: Optional[int],
    company_name: str,
) -> Dict[str, Any]:
    """
    Called by LogsPage after offender identification.
    """
    phone_raw = _s(violation.get("offender_phone"))
    out = {"ok": False, "phone_used": phone_raw, "link": "", "message": "", "error": None}

    if not phone_raw:
        out["error"] = "No phone number on this worker."
        return out

    # normalize phone for wa.me
    try:
        wa_phone = _normalize_phone_for_wa(phone_raw)
    except Exception as e:
        out["error"] = f"Invalid phone for WhatsApp: {e}"
        return out

    # build message
    msg_text = _build_message_text(
        vio=violation,
        strike_count=strike_count,
        company_name=_s(company_name),
    )
    encoded_msg = urllib.parse.quote(msg_text)
    url = f"https://wa.me/{wa_phone}?text={encoded_msg}"

    try:
        webbrowser.open(url)
        out.update(ok=True, link=url, message=msg_text)
        return out
    except Exception as e:
        out.update(error=f"Failed to open WhatsApp link: {e}", link=url, message=msg_text)
        return out
