
import os
import threading
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.db import init_db
from app.indexer import run_indexer
from app.watcher import start_watcher
from app.utils.logger import setup_logger
from app.routers import auth, tracks, playlists, system

_logger = setup_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Lifecycle manager for the FastAPI application.
    Replaces deprecated 'startup' and 'shutdown' events.
    """
    _logger.info("Initializing MySpotify Backend...")
    init_db()
    
    # Run indexer on startup in background
    indexing_thread = threading.Thread(target=run_indexer, daemon=True)
    indexing_thread.start()
    
    # Start watcher in background
    watcher_thread = threading.Thread(target=start_watcher, args=(settings.MUSIC_PATH,), daemon=True)
    watcher_thread.start()
    
    # Print DB diagnostics
    from sqlmodel import Session, select, func
    from app.models import Track
    from app.db import engine
    with Session(engine) as session:
        count = session.exec(select(func.count(Track.id))).one()
        _logger.info("Database loaded. Total tracks indexed: %s", count)
        if count == 0:
            _logger.warning("No tracks found in database! Please check your MUSIC_PATH or DB file.")
    
    _logger.info("Startup complete")
    yield
    _logger.info("Shutting down MySpotify Backend...")

app = FastAPI(
    title="MySpotify API",
    description="Backend API for MySpotify music ecosystem.",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:3000",
        f"https://{settings.DOMAIN}",
        f"https://api.{settings.DOMAIN}"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth.router)
app.include_router(tracks.router)
app.include_router(playlists.router)
app.include_router(system.router)

# Health Check (Legacy support or simple ping)
@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}

# Mount the web frontend (Static HTML/JS/CSS)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    # Catch-all for SPA: serve index.html for the root
    @app.get("/")
    async def read_index():
        return FileResponse(os.path.join(static_dir, "index.html"))
else:
    _logger.warning("Web static folder '%s' not found. Frontend will not be served.", static_dir)

