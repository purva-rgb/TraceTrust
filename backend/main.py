import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.auth.router import router as auth_router
from backend.config import get_settings
from backend.fusion.router import router as fusion_router
from backend.products.router import router as products_router
from backend.transfers.router import router as transfers_router
from backend.verify.router import router as verify_router

logger = logging.getLogger("tracetrust")


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        from backend.migrations.v5_email import apply_v5
        from backend.migrations.v6_fusion import apply_v6

        apply_v5(get_settings().database_path)
        apply_v6(get_settings().database_path)
        from backend.chain.local_demo import prepare_local_demo

        prepare_local_demo(application)
    except Exception:
        logger.exception("local demo setup skipped")
    try:
        from backend.chain.reconcile import reconcile_pending

        reconcile_pending(chain=getattr(application.state, "chain", None))
    except Exception:
        logger.exception("startup reconcile_pending skipped")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="TraceTrust", version="0.4.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    application.include_router(auth_router)
    application.include_router(products_router)
    application.include_router(transfers_router)
    application.include_router(verify_router)
    application.include_router(fusion_router)
    return application


app = create_app()
