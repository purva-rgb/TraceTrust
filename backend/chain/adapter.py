from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from eth_account import Account
from hexbytes import HexBytes

from backend.chain.ids import tx_hash_hex
from backend.config import ROOT, get_settings

ARTIFACT_PATH = ROOT / "artifacts" / "contracts" / "TraceTrust.sol" / "TraceTrust.json"


@dataclass
class SignedTx:
    raw_signed_transaction: str
    tx_hash: str
    sender_address: str
    account_nonce: int


@dataclass
class ReceiptInfo:
    tx_hash: str
    status: int
    block_number: int
    block_hash: str
    contract_address: str | None
    logs: list[dict[str, Any]]
    raw_json: str


class ChainUnavailable(Exception):
    pass


@dataclass
class ProductOnChain:
    custodian: str
    lifecycle: int
    seq: int
    event_head: bytes
    reserved_transfer_id: bytes
    exists: bool


class ChainClient(Protocol):
    chain_id: int
    contract_address: str

    def sign_function_call(self, function_name: str, args: list[Any], private_key: str) -> SignedTx:
        ...

    def broadcast(self, signed: SignedTx) -> None:
        ...

    def get_receipt(self, tx_hash: str) -> ReceiptInfo | None:
        ...

    def get_code(self, address: str) -> bytes:
        ...

    def get_chain_id(self) -> int:
        ...

    def get_product(self, product_id: bytes) -> ProductOnChain:
        ...


def load_artifact() -> dict[str, Any]:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


class Web3Chain:
    def __init__(self, rpc_url: str | None = None, contract_address: str | None = None):
        from web3 import Web3

        settings = get_settings()
        self._w3 = Web3(Web3.HTTPProvider(rpc_url or settings.rpc_url))
        artifact = load_artifact()
        address = contract_address or settings.contract_address
        if not address:
            raise RuntimeError("contract_address is not configured")
        self.contract_address = Web3.to_checksum_address(address)
        self._contract = self._w3.eth.contract(address=self.contract_address, abi=artifact["abi"])
        self.chain_id = int(self._w3.eth.chain_id)

    def sign_function_call(self, function_name: str, args: list[Any], private_key: str) -> SignedTx:
        account = Account.from_key(private_key)
        fn = getattr(self._contract.functions, function_name)(*args)
        nonce = self._w3.eth.get_transaction_count(account.address)
        tx = fn.build_transaction(
            {
                "from": account.address,
                "nonce": nonce,
                "chainId": self.chain_id,
                "gas": 2_000_000,
                "gasPrice": self._w3.eth.gas_price,
            }
        )
        signed = account.sign_transaction(tx)
        raw = signed.raw_transaction
        raw_hex = raw.to_0x_hex() if hasattr(raw, "to_0x_hex") else HexBytes(raw).to_0x_hex()
        return SignedTx(
            raw_signed_transaction=raw_hex,
            tx_hash=tx_hash_hex(signed.hash),
            sender_address=account.address,
            account_nonce=nonce,
        )

    def broadcast(self, signed: SignedTx) -> None:
        self._w3.eth.send_raw_transaction(HexBytes(signed.raw_signed_transaction))

    def get_receipt(self, tx_hash: str) -> ReceiptInfo | None:
        try:
            receipt = self._w3.eth.get_transaction_receipt(HexBytes(tx_hash))
        except Exception:
            return None
        if receipt is None:
            return None
        block_hash = receipt["blockHash"]
        block_hex = block_hash.to_0x_hex() if hasattr(block_hash, "to_0x_hex") else "0x" + bytes(block_hash).hex()
        to_addr = receipt.get("to")
        raw = {
            "status": int(receipt["status"]),
            "blockNumber": int(receipt["blockNumber"]),
            "blockHash": block_hex,
            "to": to_addr,
            "logs": [
                {
                    "address": log["address"],
                    "topics": [t.hex() if hasattr(t, "hex") else str(t) for t in log["topics"]],
                }
                for log in receipt.get("logs", [])
            ],
        }
        return ReceiptInfo(
            tx_hash=tx_hash_hex(tx_hash),
            status=int(receipt["status"]),
            block_number=int(receipt["blockNumber"]),
            block_hash=block_hex,
            contract_address=to_addr,
            logs=raw["logs"],
            raw_json=json.dumps(raw, sort_keys=True),
        )

    def get_code(self, address: str) -> bytes:
        return bytes(self._w3.eth.get_code(address))

    def get_chain_id(self) -> int:
        return int(self._w3.eth.chain_id)

    def get_product(self, product_id: bytes) -> ProductOnChain:
        if self.get_code(self.contract_address) == b"":
            raise ChainUnavailable("contract code missing")
        try:
            result = self._contract.functions.getProduct(product_id).call()
        except Exception as exc:
            raise ChainUnavailable(str(exc)) from exc
        head = result[3]
        reserved = result[4]
        return ProductOnChain(
            custodian=result[0],
            lifecycle=int(result[1]),
            seq=int(result[2]),
            event_head=bytes(head),
            reserved_transfer_id=bytes(reserved),
            exists=bool(result[5]),
        )


class MockChain:
    """In-process chain used by pipeline tests. No RPC."""

    def __init__(self, contract_address: str = "0x" + "11" * 20, chain_id: int = 31337):
        self.contract_address = contract_address
        self.chain_id = chain_id
        self._nonce: dict[str, int] = {}
        self._receipts: dict[str, ReceiptInfo] = {}
        self._raw_to_hash: dict[str, str] = {}
        self.broadcasts: list[str] = []
        self.revert_next = False
        self.hold_receipts = False
        self.code = b"\x60\x00"
        self._tx_counter = 0
        self._products: dict[bytes, ProductOnChain] = {}
        self._transfers: dict[bytes, dict[str, Any]] = {}

    def sign_function_call(self, function_name: str, args: list[Any], private_key: str) -> SignedTx:
        account = Account.from_key(private_key)
        nonce = self._nonce.get(account.address, 0)
        self._nonce[account.address] = nonce + 1
        self._tx_counter += 1
        from hashlib import sha256
        from uuid import uuid4

        digest = sha256(f"{function_name}:{self._tx_counter}:{nonce}:{uuid4().hex}".encode()).digest()
        txh = tx_hash_hex(digest)
        raw = "0x" + sha256(digest + b"raw").hexdigest() + sha256(digest + b"tail").hexdigest()[:8]
        signed = SignedTx(
            raw_signed_transaction=raw,
            tx_hash=txh,
            sender_address=account.address,
            account_nonce=nonce,
        )
        self._raw_to_hash[raw] = txh
        signed._function_name = function_name  # type: ignore[attr-defined]
        signed._args = args  # type: ignore[attr-defined]
        return signed

    def broadcast(self, signed: SignedTx) -> None:
        self.broadcasts.append(signed.tx_hash)
        if self.hold_receipts:
            return
        self._store_receipt(signed)

    def release_receipt(self, signed: SignedTx, *, reverted: bool | None = None) -> None:
        if reverted is not None:
            self.revert_next = reverted
        self._store_receipt(signed)

    def _store_receipt(self, signed: SignedTx) -> None:
        status = 0 if self.revert_next else 1
        self.revert_next = False
        block_hash = "0x" + "ab" * 32
        raw = {
            "status": status,
            "blockNumber": 1,
            "blockHash": block_hash,
            "to": self.contract_address,
            "logs": [{"address": self.contract_address, "topics": []}] if status == 1 else [],
        }
        self._receipts[signed.tx_hash] = ReceiptInfo(
            tx_hash=signed.tx_hash,
            status=status,
            block_number=1,
            block_hash=block_hash,
            contract_address=self.contract_address,
            logs=raw["logs"],
            raw_json=json.dumps(raw, sort_keys=True),
        )
        if status == 1:
            self._apply_state(signed)

    def get_receipt(self, tx_hash: str) -> ReceiptInfo | None:
        return self._receipts.get(tx_hash_hex(tx_hash))

    def get_code(self, address: str) -> bytes:
        return self.code

    def get_chain_id(self) -> int:
        return self.chain_id

    def get_product(self, product_id: bytes) -> ProductOnChain:
        if self.code == b"":
            raise ChainUnavailable("contract code missing")
        key = bytes(product_id)
        found = self._products.get(key)
        if found is None:
            return ProductOnChain(
                custodian="0x" + "00" * 20,
                lifecycle=0,
                seq=0,
                event_head=b"\x00" * 32,
                reserved_transfer_id=b"\x00" * 32,
                exists=False,
            )
        return found

    def _b32(self, value: Any) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            text = value[2:] if value.startswith("0x") else value
            return bytes.fromhex(text)
        return bytes(value)

    def _apply_state(self, signed: SignedTx) -> None:
        name = getattr(signed, "_function_name", None)
        args = getattr(signed, "_args", None) or []
        if name == "registerProduct" and len(args) >= 2:
            product_id = self._b32(args[0])
            self._products[product_id] = ProductOnChain(
                custodian=signed.sender_address,
                lifecycle=1,
                seq=0,
                event_head=self._b32(args[1]),
                reserved_transfer_id=b"\x00" * 32,
                exists=True,
            )
        elif name == "initiateTransfer" and len(args) >= 7:
            transfer_id = self._b32(args[0])
            product_ids = [self._b32(item) for item in args[2]]
            new_heads = [self._b32(item) for item in args[6]]
            self._transfers[transfer_id] = {
                "sender": signed.sender_address,
                "recipient": args[1],
                "product_ids": product_ids,
            }
            for product_id, head in zip(product_ids, new_heads):
                current = self._products.get(product_id)
                if current is None:
                    continue
                self._products[product_id] = ProductOnChain(
                    custodian=current.custodian,
                    lifecycle=current.lifecycle,
                    seq=current.seq + 1,
                    event_head=head,
                    reserved_transfer_id=transfer_id,
                    exists=True,
                )
        elif name == "acceptTransfer" and len(args) >= 3:
            transfer_id = self._b32(args[0])
            rec = self._transfers.get(transfer_id) or {}
            new_heads = [self._b32(item) for item in args[2]]
            for product_id, head in zip(rec.get("product_ids") or [], new_heads):
                current = self._products.get(product_id)
                if current is None:
                    continue
                self._products[product_id] = ProductOnChain(
                    custodian=rec.get("recipient") or signed.sender_address,
                    lifecycle=2,
                    seq=current.seq + 1,
                    event_head=head,
                    reserved_transfer_id=b"\x00" * 32,
                    exists=True,
                )

    def simulate_reset(self) -> None:
        self.code = b""
        self._receipts.clear()
        self._products.clear()
        self._transfers.clear()
