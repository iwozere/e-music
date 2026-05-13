import os
import threading
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api_constants import API_V1_PREFIX
from app.config import settings
from app.db import ensure_admin_roles, init_db
from app.error_handlers import register_exception_handlers
from app.indexer import run_indexer
from app.limiter_ext import limiter
from app.middleware.request_context import RequestContextMiddleware
from app.routers import ai, auth, playlists, public_config, system, tracks
from app.utils.logger import setup_logger
from app.watcher import start_watcher

_logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Lifecycle manager for the FastAPI application.
    Replaces deprecated 'startup' and 'shutdown' events.
    """
    _logger.info("Initializing MySpotify Backend...")
    init_db()
    ensure_admin_roles()

    # Run indexer on startup in background
    indexing_thread = threading.Thread(target=run_indexer, daemon=True)
    indexing_thread.start()

    # Start watcher in background
    watcher_thread = threading.Thread(
        target=start_watcher, args=(settings.MUSIC_PATH,), daemon=True
    )
    watcher_thread.start()

    # Print DB diagnostics
    from sqlmodel import Session, func, select

    from app.db import engine
    from app.models import Track

    with Session(engine) as session:
        count = session.exec(select(func.count(Track.id))).one()
        _logger.info("Database loaded. Total tracks indexed: %s", count)
        if count == 0:
            _logger.warning(
                "No tracks found in database! Please check your MUSIC_PATH or DB file."
            )

    # Remove any *.download files left over from a crashed/interrupted stream.
    import glob as _glob
    for _stale in _glob.glob(os.path.join(settings.TEMP_DIR, "*.download")) + \
                  _glob.glob(os.path.join(settings.CACHE_DIR, "*.download")):
        try:
            os.remove(_stale)
            _logger.info("Removed stale partial download: %s", _stale)
        except Exception:
            pass

    _logger.info("Startup complete")
    yield
    _logger.info("Shutting down MySpotify Backend...")


app = FastAPI(
    title="MySpotify API",
    description="Backend API for MySpotify music ecosystem.",
    lifespan=lifespan,
)

app.state.limiter = limiter
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:3000",
        f"https://{settings.DOMAIN}",
        f"https://api.{settings.DOMAIN}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestContextMiddleware)

# Versioned JSON API
app.include_router(public_config.router, prefix=API_V1_PREFIX)
app.include_router(auth.router, prefix=API_V1_PREFIX)
app.include_router(tracks.router, prefix=API_V1_PREFIX)
app.include_router(playlists.router, prefix=API_V1_PREFIX)
app.include_router(system.router, prefix=API_V1_PREFIX)
app.include_router(ai.router, prefix=API_V1_PREFIX)

# Health Check (Legacy support or simple ping)
@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}


# Mount the web frontend (Static HTML/JS/CSS)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def read_index():
        return FileResponse(os.path.join(static_dir, "index.html"))

else:
    _logger.warning(
        "Web static folder '%s' not found. Frontend will not be served.", static_dir
    )
