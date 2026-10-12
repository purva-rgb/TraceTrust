from __future__ import annotations

from backend.chain.adapter import ChainClient
from backend.db import get_connection
from backend.products.gps import gps_to_canonical
from backend.verify.engine import parse_qr_payload, token_lookup_hash, unknown_result, verify_product
from backend.verify.schemas import VerifyIn


def resolve_product_uid(body: VerifyIn, *, db_path=None) -> str | None:
    product_uid = body.product_uid
    token = body.token
    if body.qr_payload:
        parsed_uid, parsed_token = parse_qr_payload(body.qr_payload)
        product_uid = product_uid or parsed_uid
        token = token or parsed_token
    if product_uid and not token:
        return product_uid
    if token:
        digest = token_lookup_hash(token)
        with get_connection(db_path) as conn:
            if product_uid:
                row = conn.execute(
                    "SELECT product_uid FROM products WHERE product_uid=? AND qr_token=?",
                    (product_uid, digest),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT product_uid FROM products WHERE qr_token=?",
                    (digest,),
                ).fetchone()
        return row["product_uid"] if row else None
    return product_uid


def verify_request(body: VerifyIn, chain: ChainClient | None, *, db_path=None) -> dict:
    product_uid = resolve_product_uid(body, db_path=db_path)
    if not product_uid:
        return unknown_result()
    observer_gps = gps_to_canonical(body.gps) if body.gps is not None else None
    result = verify_product(product_uid, chain, db_path=db_path, observer_gps=observer_gps)
    if result.get("final_status") == "SUSPICIOUS":
        from backend.notify.mail import notify_suspicious

        result["mail_alert"] = notify_suspicious(product_uid, result, db_path=db_path)
    try:
        from backend.fusion.service import record_verification

        result["assessment"] = record_verification(product_uid, result, observer_gps, db_path=db_path)
    except Exception:
        import logging

        logging.getLogger("tracetrust").exception("fusion assessment skipped")
    return result
