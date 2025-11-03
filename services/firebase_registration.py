# services/firebase_registration.py
from typing import Tuple
from datetime import datetime, timedelta, timezone
import random, bcrypt

from firebase_admin import firestore
from .firebase_client import get_db
from .emailer import send_email, EmailSendError

OTP_TTL_MINUTES = 10
RESEND_COOLDOWN_SECONDS = 30

def _utc_now():
    return datetime.now(timezone.utc)

def _generate_otp(n: int = 6) -> str:
    return "".join(str(random.randint(0,9)) for _ in range(n))

def _send_otp_email(to_email: str, otp: str, company_name: str):
    subject = "Your CompliGuard verification code"
    body = (
        f"Hello,\n\n"
        f"Use this code to verify your CompliGuard account for '{company_name}':\n\n"
        f"    {otp}\n\n"
        f"This code expires in {OTP_TTL_MINUTES} minutes.\n\n"
        f"If you didn’t request this, please ignore this email.\n\n"
        f"— CompliGuard"
    )
    send_email(to_email, subject, body)

def begin_company_registration(email: str, password_plain: str,
                               company_name: str, admin_name: str) -> str:
    """
    Creates a pending registration with an OTP, emails the OTP.
    If email fails, the registration doc is **deleted** and a friendly error is raised.
    Returns registration_id. (No OTP returned.)
    """
    if not email or "@" not in email:
        raise ValueError("Invalid email.")
    if not password_plain or len(password_plain) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if not company_name.strip():
        raise ValueError("Company name is required.")
    if not admin_name.strip():
        raise ValueError("Admin name is required.")

    db = get_db()
    # prevent duplicate active users
    existing_user = db.collection("users").document(email.lower()).get()
    if existing_user.exists:
        raise ValueError("An account already exists for this email.")

    otp = _generate_otp(6)
    expires_at = _utc_now() + timedelta(minutes=OTP_TTL_MINUTES)
    pw_hash = bcrypt.hashpw(password_plain.encode(), bcrypt.gensalt()).decode()

    reg_ref = db.collection("registrations").document()  # auto-id
    reg_id = reg_ref.id
    reg_ref.set({
        "email": email.lower(),
        "password_hash": pw_hash,
        "company_name": company_name.strip(),
        "admin_name": admin_name.strip(),
        "otp_code": otp,
        "otp_expires_at": expires_at.isoformat(),
        "resend_available_at": _utc_now().isoformat(),
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP,
    })

    try:
        _send_otp_email(email, otp, company_name)
    except EmailSendError as e:
        # roll back: delete pending registration
        try:
            reg_ref.delete()
        except Exception:
            pass
        # surface a friendly message to UI
        raise ValueError(str(e)) from e

    return reg_id

def resend_company_otp(registration_id: str):
    """
    Generates a new OTP, applies cooldown, and emails it.
    Raises a friendly ValueError for the UI.
    """
    db = get_db()
    ref = db.collection("registrations").document(registration_id)
    snap = ref.get()
    if not snap.exists:
        raise ValueError("Registration not found.")

    reg = snap.to_dict() or {}
    if reg.get("status") != "pending":
        raise ValueError("Registration is not pending.")

    now = _utc_now()
    try:
        last = datetime.fromisoformat(reg.get("resend_available_at"))
    except Exception:
        last = now
    delta = (now - last).total_seconds()
    if delta < RESEND_COOLDOWN_SECONDS:
        raise ValueError(f"Please wait {int(RESEND_COOLDOWN_SECONDS - delta)}s before requesting a new code.")

    new_otp = _generate_otp(6)
    expires_at = now + timedelta(minutes=OTP_TTL_MINUTES)

    try:
        _send_otp_email(reg["email"], new_otp, reg["company_name"])
    except EmailSendError as e:
        raise ValueError(str(e)) from e

    ref.update({
        "otp_code": new_otp,
        "otp_expires_at": expires_at.isoformat(),
        "resend_available_at": now.isoformat(),
    })

def confirm_company_registration(registration_id: str, otp_input: str) -> str:
    """
    Validates OTP (and expiry) and finalizes: creates companies/{id} and users/{email}.
    Returns company_id (doc id).
    """
    if not registration_id or not otp_input:
        raise ValueError("Missing registration or OTP.")

    db = get_db()
    reg_ref = db.collection("registrations").document(registration_id)
    snap = reg_ref.get()
    if not snap.exists:
        raise ValueError("Registration not found.")

    reg = snap.to_dict() or {}
    if reg.get("status") != "pending":
        raise ValueError("Registration is not pending.")

    # expiry check
    try:
        exp = datetime.fromisoformat(reg.get("otp_expires_at"))
    except Exception:
        exp = _utc_now() - timedelta(seconds=1)
    if _utc_now() > exp:
        raise ValueError("OTP has expired. Please resend a new code.")

    # code check
    if str(reg.get("otp_code")) != str(otp_input).strip():
        raise ValueError("Invalid OTP code.")

    # create company with incremental numeric id (via firebase_db)
    from .firebase_db import create_company  # lazy import to avoid cycle
    company_id = create_company(reg["company_name"])

    # create user (company admin) for Firestore login
    email = reg["email"].lower()
    db.collection("users").document(email).set({
        "email": email,
        "name": reg["admin_name"],
        "role": "company_admin",
        "company_id": company_id,
        "active": True,
        "password_hash": reg["password_hash"],
        "created_at": firestore.SERVER_TIMESTAMP,
    })

    # mark registration complete
    reg_ref.update({
        "status": "verified",
        "verified_at": firestore.SERVER_TIMESTAMP,
        "company_id": company_id,
    })

    return company_id
