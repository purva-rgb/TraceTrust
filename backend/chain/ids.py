from __future__ import annotations

from eth_hash.auto import keccak


def uid_to_bytes32(uid: str) -> bytes:
    return keccak(uid.encode("utf-8"))


def sha256_to_bytes32(hex_hash: str) -> bytes:
    text = hex_hash[2:] if hex_hash.startswith("0x") else hex_hash
    raw = bytes.fromhex(text)
    if len(raw) != 32:
        raise ValueError("event hash must be 32 bytes")
    return raw


def to_0x(data: bytes) -> str:
    return "0x" + data.hex()


def tx_hash_hex(value: str | bytes) -> str:
    if isinstance(value, bytes):
        text = "0x" + value.hex()
    else:
        text = value if value.startswith("0x") else "0x" + value
    text = "0x" + text[2:].lower()
    if len(text) != 66:
        raise ValueError(f"tx_hash must be 32 bytes, got {len(text)}")
    return text
