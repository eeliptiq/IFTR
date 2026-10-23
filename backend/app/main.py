# app/main.py
# Entry file: python -m uvicorn app.main:app --reload

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.cors import allowed_origin_regex, allowed_origins
from app.database import init_db
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.restaurants import router as restaurants_router
from app.api.orders import router as orders_router
from app.api.admin import router as admin_router
from app.api.drivers import router as drivers_router
from app.api.impact import router as impact_router
from app.api.organizations import router as organizations_router
from app.api.payments import router as payments_router
from app.api.crypto import router as crypto_router
from app.api.surplus import router as surplus_router
from app.api.support import router as support_router
from app.api.uploads import UPLOAD_DIR, ensure_upload_dir, router as uploads_router
from app.crypto_watcher import watch_forever as watch_crypto_forever
from app.uploads_gc_scheduler import sweep_forever

# The app's own logs - the uploads sweep included - need somewhere to go.
# uvicorn configures only its own loggers and leaves the root logger at WARNING
# with no handler, so without this the background sweep would report into the
# void and a failure would look like nothing happening at all.
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(levelname)s:     %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize database tables, then keep two background tasks alongside.

    The uploads sweep reclaims files nothing references any more; the crypto
    watcher asks the wallets what has arrived, because nobody calls us back when
    somebody pays in Bitcoin. Both report through logging and are cancelled on
    shutdown; `UPLOADS_GC_INTERVAL_MINUTES=0` turns the first off and
    `CRYPTO_WATCH_INTERVAL_SECONDS=0` the second.
    """
    await init_db()

    tasks = [
        asyncio.create_task(sweep_forever(), name="uploads-sweep"),
        asyncio.create_task(watch_crypto_forever(), name="crypto-watch"),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="IFTR API",
    description="Independent Food Transport Revolution",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — see app/cors.py. The dev ports are always allowed; FRONTEND_ORIGINS
# adds exact origins (the published site, a test run's ephemeral port) and
# FRONTEND_ORIGIN_REGEX a pattern for the pull request previews, which have a
# hostname each. Never wildcarded: the app is served with credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(os.environ),
    allow_origin_regex=allowed_origin_regex(os.environ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers — all under /api so the React frontend (which targets
# `${REACT_APP_BACKEND_URL}/api`) can talk to this backend unchanged.
API_PREFIX = "/api"
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(restaurants_router, prefix=API_PREFIX)
app.include_router(orders_router, prefix=API_PREFIX)
app.include_router(drivers_router, prefix=API_PREFIX)
app.include_router(impact_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(organizations_router, prefix=API_PREFIX)
app.include_router(payments_router, prefix=API_PREFIX)
app.include_router(crypto_router, prefix=API_PREFIX)
app.include_router(surplus_router, prefix=API_PREFIX)
app.include_router(support_router, prefix=API_PREFIX)
app.include_router(uploads_router, prefix=API_PREFIX)

# User-uploaded images. Mounted outside /api because these are plain files the
# browser loads directly (<img src>), not JSON the client fetches.
ensure_upload_dir()
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/")
def read_root():
    return {"message": "IFTR API is running", "status": "ok"}
