"""
services/messaging.py

Lightweight WhatsApp launcher (no Twilio).

Flow:
1. After admin selects the offender in LogsPage._identify_offender(),
   we call record_offender_on_violation() which:
   - updates the violation with offender info
   - logs a strike
   - counts total strikes

2. LogsPage then calls prepare_and_send_whatsapp(...) with:
   - violation_after (dict with offender info, zone, etc.)
   - strike_count (int)
   - company_name (STRING YOU WANT SHOWN IN THE MESSAGE)

3. We:
   - figure out target phone (offender_phone inside violation_after)
   - generate human-readable message text based on strike_count
     (1st = notice, 2nd = reminder, 3rd+ = warning)
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
    Convert a phone string (we store it like +60...) into wa.me format,
    which MUST be digits only, no '+', no spaces.

    Steps:
    - strip spaces, -, (, ), .
    - if starts with '+', drop it
    - make sure result is only digits
    - sanity check length

    Example:
      "+60123456789" -> "60123456789"
      "60123456789"  -> "60123456789"
    """
    p = (raw_phone or "").strip()

    for ch in (" ", "-", "(", ")", "."):
        p = p.replace(ch, "")

    if p.startswith("+"):
        p = p[1:]

    if not p.isdigit():
        raise ValueError(
            "Phone must be numeric with country code, e.g. +60123456789"
        )

    if len(p) < 8 or len(p) > 20:
        raise ValueError("Phone length looks invalid for WhatsApp")

    return p


def _fmt_ts_human(ts_any: Any) -> str:
    """
    Turn violation timestamp into "YYYY-MM-DD HH:MM".
    Handles:
      - epoch ms
      - epoch sec
      - datetime-like (has .timestamp)
      - else fallback to str()
    """
    try:
        # numeric timestamp?
        if isinstance(ts_any, (int, float)):
            val = float(ts_any)
            # if looks like ms (>= 1e12)
            if val > 1e12:
                val = val / 1000.0
            dt = datetime.datetime.fromtimestamp(val)
            return dt.strftime("%Y-%m-%d %H:%M")

        # datetime-like with .timestamp()
        if hasattr(ts_any, "timestamp"):
            val = ts_any.timestamp()
            dt = datetime.datetime.fromtimestamp(val)
            return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    # fallback
    return _s(ts_any)


def _risk_parse(raw_risk: str) -> Dict[str, Any]:
    """
    Read violation['risk' / 'risk_level' / 'severity'] string and return:
      {
        "ppe_list": ["Helmet Missing", "Vest Missing", ...],
        "zone_level": "high" | "medium" | "low" | "",
        "zone_label": "High Risk Area" | ... | "",
        "pretty_issue": "Helmet Missing, Vest Missing" | "High Risk" | ...
      }

    We split these two concepts:
    - PPE that was missing
    - Area risk level (high / medium / low)

    We'll use both in the WhatsApp message.
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

    # detect area severity
    if "high" in t or t == "3" or "critical" in t or "severe" in t:
        info["zone_level"] = "high"
        info["zone_label"] = "High Risk Area"
    elif "med" in t or "medium" in t or t == "2":
        info["zone_level"] = "medium"
        info["zone_label"] = "Medium Risk Area"
    elif "low" in t or t == "1":
        info["zone_level"] = "low"
        info["zone_label"] = "Low Risk Area"

    # build pretty_issue for human "Issue:" line
    if info["ppe_list"]:
        info["pretty_issue"] = ", ".join(info["ppe_list"])
    else:
        # fall back to generic level text if no explicit PPE list
        if info["zone_level"] == "high":
            info["pretty_issue"] = "High Risk"
        elif info["zone_level"] == "medium":
            info["pretty_issue"] = "Medium Risk"
        elif info["zone_level"] == "low":
            info["pretty_issue"] = "Low Risk"
        else:
            info["pretty_issue"] = raw_risk or "—"

    return info


def _ordinal(n: int) -> str:
    """
    1 -> 1st
    2 -> 2nd
    3 -> 3rd
    4 -> 4th
    etc.
    """
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


def _build_message_text(
    *,
    vio: Dict[str, Any],
    strike_count: Optional[int],
    company_name: str,
) -> str:
    """
    Make the WhatsApp body text we'll pre-fill.
    - strike_count decides tone:
        1st  => SAFETY NOTICE (polite)
        2nd  => SAFETY REMINDER (firm)
        3rd+ => SAFETY WARNING (formal warning)
    - includes which PPE was missing
    - includes zone + risk level wording "High Risk Area" etc
    """

    # offender
    name = _s(vio.get("offender_name"))
    wid = _s(vio.get("offender_id"))

    # zone
    zone = _s(
        vio.get("zone_name")
        or vio.get("zone_id")
        or ""
    )

    # raw risk string from violation
    raw_risk = (
        _s(vio.get("risk"))
        or _s(vio.get("risk_level"))
        or _s(vio.get("severity"))
    )
    risk_info = _risk_parse(raw_risk)

    # timestamp
    ts_any = (
        vio.get("ts")
        or vio.get("time")
        or vio.get("created_at")
    )
    when_txt = _fmt_ts_human(ts_any)

    # strike tone + body
    sc = strike_count if strike_count is not None else 1
    if sc <= 1:
        header = "SAFETY NOTICE"
        strike_line = (
            "You were just recorded without full PPE. "
            "Please correct this immediately."
        )
        closing_line = (
            "Please wear your safety helmet, vest, gloves and boots at all times. "
            "This is a safety requirement."
        )
    elif sc == 2:
        header = "SAFETY REMINDER"
        strike_line = (
            "This is your 2nd recorded safety violation. "
            "You must wear full PPE immediately."
        )
        closing_line = (
            "Continued non-compliance will lead to disciplinary action."
        )
    else:
        # 3rd or more
        header = "SAFETY WARNING"
        strike_line = (
            f"This is your { _ordinal(sc) } recorded safety violation. "
            "This is a formal warning."
        )
        closing_line = (
            "Further violations may result in removal from site. "
            "Wear full PPE now."
        )

    # "Issue:" line lets them know exact PPE problem
    issue_line = (
        f"Issue: {risk_info['pretty_issue']}"
        if risk_info["pretty_issue"]
        else None
    )

    # zone_line includes zone name plus risk label if we know
    if risk_info["zone_label"]:
        zone_line = f"Zone: {zone or 'N/A'} ({risk_info['zone_label']})"
    else:
        zone_line = f"Zone: {zone or 'N/A'}"

    lines = [
        f"⚠ {header} ⚠",
        f"Company/Site: {company_name}",  # <- always use provided company_name
        f"Worker: {name} (ID {wid})" if (name and wid) else f"Worker: {name or wid}",
    ]

    if issue_line:
        lines.append(issue_line)

    lines.extend(
        [
            zone_line,
            f"Time: {when_txt}",
            strike_line,
            "",
            closing_line,
        ]
    )

    # filter any accidental blanks
    return "\n".join([ln for ln in lines if _s(ln)])


# ───────────────────────── public entrypoint ─────────────────────────
def prepare_and_send_whatsapp(
    *,
    violation: Dict[str, Any],
    strike_count: Optional[int],
    company_name: str,
) -> Dict[str, Any]:
    """
    This is what LogsPage calls.

    Inputs:
      violation: dict after update (has offender_phone, offender_name, etc.)
      strike_count: int from record_offender_on_violation()
      company_name: EXACT company/site name you want shown in the message

    Behavior:
      1. Pull phone from violation["offender_phone"]
      2. Build message text (tone depends on strike_count)
      3. Open browser with wa.me link
      4. Return dict so UI can tell the admin what happened

    Return dict structure:
      {
        "ok": bool,
        "phone_used": str,
        "link": str,
        "message": str,
        "error": Optional[str]
      }
    """

    phone_raw = _s(violation.get("offender_phone"))
    out = {
        "ok": False,
        "phone_used": phone_raw,
        "link": "",
        "message": "",
        "error": None,
    }

    if not phone_raw:
        out["error"] = "No phone number on this worker."
        return out

    # normalize phone for wa.me
    try:
        wa_phone = _normalize_phone_for_wa(phone_raw)
    except Exception as e:
        out["error"] = f"Invalid phone for WhatsApp: {e}"
        return out

    # build message with tiered tone
    msg_text = _build_message_text(
        vio=violation,
        strike_count=strike_count,
        company_name=_s(company_name),  # <- no fallback "Site Safety"
    )
    encoded_msg = urllib.parse.quote(msg_text)

    # WhatsApp deep link (browser -> WhatsApp Desktop/Web)
    url = f"https://wa.me/{wa_phone}?text={encoded_msg}"

    # try to launch default browser (which should either show WhatsApp Web
    # or hand off to WhatsApp Desktop if installed/registered)
    try:
        webbrowser.open(url)
        out["ok"] = True
        out["link"] = url
        out["message"] = msg_text
        return out
    except Exception as e:
        out["error"] = f"Failed to open WhatsApp link: {e}"
        out["link"] = url      # still give link so user can copy manually
        out["message"] = msg_text
        return out
