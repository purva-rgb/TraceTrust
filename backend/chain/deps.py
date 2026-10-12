from __future__ import annotations

from fastapi import Request

from backend.chain.adapter import ChainClient, Web3Chain
from backend.config import get_settings
from backend.db import get_connection
from backend.errors import api_error


def get_chain_optional(request: Request) -> ChainClient | None:
    try:
        return get_chain(request)
    except Exception:
        return None


def get_chain(request: Request) -> ChainClient:
    cached = getattr(request.app.state, "chain", None)
    if cached is not None:
        return cached
    settings = get_settings()
    address = settings.contract_address
    try:
        if not address:
            with get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT contract_address FROM chain_deployments
                    WHERE status='ACTIVE' ORDER BY created_at DESC LIMIT 1
                    """
                ).fetchone()
            if row is None:
                raise RuntimeError("no ACTIVE chain deployment")
            address = row["contract_address"]
        chain = Web3Chain(contract_address=address)
        request.app.state.chain = chain
        return chain
    except Exception as exc:
        raise api_error(503, "CHAIN_UNAVAILABLE", "chain is not available") from exc
