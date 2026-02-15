import os
import asyncio
import typing
from typing import AsyncGenerator, Any, Generator

from fastapi.responses import StreamingResponse, FileResponse
from sqlmodel import Session, select

from app.models import Track
from app.db import engine
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

from app.config import settings

PERSISTENT_CACHE_DIR: str = settings.CACHE_DIR
TEMP_CACHE_DIR: str = settings.TEMP_DIR

async def stream_youtube(track_id: str) -> StreamingResponse:
    """
    Stream audio from YouTube using yt-dlp and cache it locally in the background.

    Args:
        track_id: The YouTube video ID or remote ID.

    Returns:
        A FastAPI StreamingResponse.
    """
    # 1. Check if already in persistent cache
    persistent_path = os.path.join(PERSISTENT_CACHE_DIR, f"{track_id}.mp3")
    if os.path.exists(persistent_path):
        _logger.info("Serving track from persistent cache: %s", track_id)
        return get_local_stream(persistent_path)

    # 2. Check if in temp cache
    temp_path = os.path.join(TEMP_CACHE_DIR, f"{track_id}.mp3")
    if os.path.exists(temp_path):
        _logger.info("Serving track from temporary cache: %s", track_id)
        return get_local_stream(temp_path)

    _logger.info("Initializing YouTube stream for track: %s", track_id)
    
    # Ensure cache dirs exist
    os.makedirs(PERSISTENT_CACHE_DIR, exist_ok=True)
    os.makedirs(TEMP_CACHE_DIR, exist_ok=True)

    # Construct yt-dlp command to stream audio to stdout
    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "-o", "-",  # Output to stdout
        f"https://www.youtube.com/watch?v={track_id}"
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    async def iterate_stdout() -> AsyncGenerator[bytes, None]:
        """
        Background iterator to stream bytes and write to temp cache file simultaneously.
        """
        try:
            with open(temp_path, "wb") as cache_file:
                while True:
                    chunk = await process.stdout.read(64 * 1024)  # 64KB chunks
                    if not chunk:
                        break
                    cache_file.write(chunk)
                    yield chunk
            
            _logger.info("Temp cache complete for track: %s", track_id)
            
            # After completion, update DB
            with Session(engine) as session:
                statement = select(Track).where(Track.remote_id == track_id)
                track = session.exec(statement).first()
                if track:
                    track.is_cached = True
                    track.local_path = cache_path
                    session.add(track)
                    session.commit()
                    _logger.info("Database updated with cache path for: %s", track_id)
        except Exception:
            _logger.exception("Error while streaming/caching YouTube track: %s", track_id)

    return StreamingResponse(iterate_stdout(), media_type="audio/mpeg")

def get_local_stream(file_path: str) -> FileResponse:
    """
    Stream a local audio file using FileResponse for HTTP Range support.

    Args:
        file_path: Absolute path to the local audio file.

    Returns:
        A FastAPI FileResponse.
    """
    _logger.info("Streaming local file via FileResponse: %s", file_path)
    return FileResponse(file_path, media_type="audio/mpeg")
