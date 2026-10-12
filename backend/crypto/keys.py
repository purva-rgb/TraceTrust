from __future__ import annotations

import json
from pathlib import Path

from eth_account import Account
from hexbytes import HexBytes

from backend.config import get_settings

ORG_KEY_ENV = {
    "MANUFACTURER": "org_private_key_manufacturer",
    "DISTRIBUTOR": "org_private_key_distributor",
    "RETAILER": "org_private_key_retailer",
}


class KeyError_(RuntimeError):
    pass


def _normalize_hex_sig(signature: HexBytes | bytes | str) -> str:
    if isinstance(signature, str):
        text = signature if signature.startswith("0x") else "0x" + signature
    else:
        hb = HexBytes(signature)
        text = hb.to_0x_hex() if hasattr(hb, "to_0x_hex") else "0x" + hb.hex()
    text = "0x" + text[2:].lower()
    if len(text) != 132:
        raise KeyError_(f"signature must be 65 bytes, got {len(text)}")
    return text


def load_org_private_key(organization_type: str, organization_id: int | None = None) -> str:
    settings = get_settings()
    keystore = {}
    if settings.keystore_path:
        path = Path(settings.keystore_path)
        if path.exists():
            keystore = json.loads(path.read_text(encoding="utf-8"))
    if organization_id is not None and str(organization_id) in keystore:
        return keystore[str(organization_id)]
    attr = ORG_KEY_ENV.get(organization_type)
    if attr:
        value = getattr(settings, attr)
        if value:
            return value
    if organization_type in keystore:
        return keystore[organization_type]
    raise KeyError_(f"no private key configured for {organization_type}")


def sign_event_hash(event_hash_hex: str, private_key: str) -> str:
    digest = bytes.fromhex(event_hash_hex)
    signed = Account.unsafe_sign_hash(digest, private_key=private_key)
    return _normalize_hex_sig(signed.signature)


def recover_signer_address(event_hash_hex: str, signature: str) -> str:
    digest = bytes.fromhex(event_hash_hex)
    return Account._recover_hash(digest, signature=HexBytes(signature))


def verify_event_signature(event_hash_hex: str, signature: str, eth_address: str) -> bool:
    try:
        recovered = recover_signer_address(event_hash_hex, signature)
    except Exception:
        return False
    return recovered.lower() == eth_address.lower()


def address_from_private_key(private_key: str) -> str:
    return Account.from_key(private_key).address
