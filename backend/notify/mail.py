from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from backend.config import ROOT, get_settings

logger = logging.getLogger("tracetrust")
OUTBOX = ROOT / "mail_outbox"


def _write_outbox(to_addrs: list[str], subject: str, body: str) -> Path:
    OUTBOX.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = OUTBOX / f"{stamp}.txt"
    path.write_text(
        f"To: {', '.join(to_addrs)}\nSubject: {subject}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def send_mail(to_addrs: list[str], subject: str, body: str) -> dict:
    recipients = []
    seen = set()
    for addr in to_addrs:
        text = str(addr or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        recipients.append(text)
    if not recipients:
        return {"queued": False, "to": [], "channel": None}
    path = _write_outbox(recipients, subject, body)
    get_settings.cache_clear()
    settings = get_settings()
    host = (settings.smtp_host or "").strip()
    user = (settings.smtp_user or "").strip()
    password = (settings.smtp_password or "").strip().replace(" ", "")
    sender = (settings.smtp_from or user or "tracetrust@localhost").strip()
    if not host:
        logger.info("SMTP not configured; suspicious alert stored in mail_outbox")
        return {"queued": True, "to": recipients, "channel": "outbox", "outbox": str(path.name)}
    if not user or not password:
        return {
            "queued": True,
            "to": recipients,
            "channel": "outbox",
            "error": "smtp_password_missing",
            "detail": "SMTP_USER and SMTP_PASSWORD must both be set. Use a 16-character Google App Password, not the account login.",
            "outbox": str(path.name),
        }
    if len(password) != 16 or not password.isalpha():
        return {
            "queued": True,
            "to": recipients,
            "channel": "outbox",
            "error": "smtp_app_password_required",
            "detail": (
                "Gmail rejected SMTP. SMTP_PASSWORD must be a 16-letter Google App Password "
                "(Google Account → Security → 2-Step Verification → App passwords), not the Gmail login. "
                "Turn on 2-Step Verification first, then paste the 16 letters with no spaces."
            ),
            "outbox": str(path.name),
        }
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(message)
    except Exception as exc:
        logger.exception("SMTP send failed; alert kept in mail_outbox")
        return {
            "queued": True,
            "to": recipients,
            "channel": "outbox",
            "outbox": str(path.name),
            "error": "smtp_failed",
            "detail": str(exc)[:500],
        }
    return {"queued": True, "to": recipients, "channel": "smtp"}


def _emails_for_orgs(conn, org_ids: list[int]) -> list[str]:
    wanted = [org_id for org_id in org_ids if org_id]
    if not wanted:
        return []
    placeholders = ",".join("?" for _ in wanted)
    rows = conn.execute(
        f"""
        SELECT email, username
        FROM users
        WHERE status='ACTIVE' AND organization_id IN ({placeholders})
          AND role IN ('MANUFACTURER','DISTRIBUTOR','RETAILER')
        """,
        wanted,
    ).fetchall()
    return [row["email"] or row["username"] for row in rows if row["email"] or row["username"]]


def _transfer_party_orgs(conn, *, product_uid: str | None = None, transfer_uid: str | None = None) -> tuple[list[int], str | None]:
    if transfer_uid:
        row = conn.execute(
            """
            SELECT sender_organization_id, recipient_organization_id, transfer_uid
            FROM transfers WHERE transfer_uid=?
            """,
            (transfer_uid,),
        ).fetchone()
    elif product_uid:
        row = conn.execute(
            """
            SELECT t.sender_organization_id, t.recipient_organization_id, t.transfer_uid
            FROM transfers t
            JOIN transfer_items i ON i.transfer_id = t.transfer_id
            JOIN products p ON p.product_id = i.product_id
            WHERE p.product_uid=?
            ORDER BY t.transfer_id DESC
            LIMIT 1
            """,
            (product_uid,),
        ).fetchone()
    else:
        row = None
    if row is None:
        return [], None
    return [row["sender_organization_id"], row["recipient_organization_id"]], row["transfer_uid"]


def _send_alert(to_addrs: list[str], subject: str, body: str) -> dict:
    try:
        return send_mail(to_addrs, subject, body)
    except Exception as exc:
        logger.exception("failed to send suspicious-event mail")
        detail = str(exc)
        if "gmail.com" in detail.lower() or "Authentication" in detail or "535" in detail or "530" in detail or "closed" in detail.lower():
            detail = (
                f"{detail} Gmail rejected the SMTP login. SMTP_PASSWORD must be a 16-character "
                "Google App Password for SMTP_USER, not the normal account password. "
                "College Google accounts often block App Passwords; if so, set SMTP_USER to a personal Gmail that has one."
            )
        return {"queued": False, "to": to_addrs, "channel": None, "error": "send_failed", "detail": detail[:700]}


def notify_suspicious(product_uid: str, result: dict, *, db_path=None) -> dict:
    if result.get("final_status") != "SUSPICIOUS":
        return
    from backend.db import connect

    conn = connect(db_path)
    try:
        product = conn.execute(
            """
            SELECT p.product_uid, p.serial_number, p.manufacturer_id, c.custodian_organization_id
            FROM products p
            LEFT JOIN custody c ON c.product_id = p.product_id
            WHERE p.product_uid=?
            """,
            (product_uid,),
        ).fetchone()
        if product is None:
            return {"queued": False, "to": [], "channel": None}
        org_ids, transfer_uid = _transfer_party_orgs(conn, product_uid=product_uid)
        if not org_ids:
            org_ids = [product["manufacturer_id"], product["custodian_organization_id"]]
        to_addrs = _emails_for_orgs(conn, org_ids)
    finally:
        conn.close()

    flags = result.get("restriction_flags") or {}
    reasons = [key for key, value in flags.items() if value is True or value == "COUNTERFEIT"]
    parties = "sender and recipient of the latest transfer" if transfer_uid else "manufacturer and current custodian"
    body = (
        f"A TraceTrust verification was flagged SUSPICIOUS.\n\n"
        f"Product UID: {product_uid}\n"
        f"Serial (masked): {result.get('serial_number_masked') or '—'}\n"
        f"Transfer: {transfer_uid or 'none yet'}\n"
        f"Notifying: {parties}\n"
        f"Flags: {', '.join(reasons) or 'restriction'}\n"
        f"Record integrity: {(result.get('record_integrity') or {}).get('status')}\n"
    )
    alert = _send_alert(to_addrs, "TraceTrust alert: suspicious verification", body)
    alert["parties"] = parties
    return alert


def notify_transfer_mismatch(
    transfer_uid: str,
    *,
    reason: str,
    location_check: str | None = None,
    db_path=None,
) -> None:
    from backend.db import connect

    conn = connect(db_path)
    try:
        org_ids, _ = _transfer_party_orgs(conn, transfer_uid=transfer_uid)
        to_addrs = _emails_for_orgs(conn, org_ids)
    finally:
        conn.close()
    body = (
        f"A TraceTrust handover was flagged as suspicious.\n\n"
        f"Transfer: {transfer_uid}\n"
        f"Reason: {reason}\n"
        f"location_check: {location_check or '—'}\n"
        f"This alert was sent to the transferring party and the receiving party.\n"
    )
    _send_alert(to_addrs, "TraceTrust alert: suspicious handover", body)
