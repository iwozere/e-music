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

# Registry to track active downloads and prevent duplicate yt-dlp processes
_active_downloads: typing.Dict[str, asyncio.Event] = {}

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

    # 3. Check if download is already in progress by another request
    if track_id in _active_downloads:
        _logger.info("Download already in progress for %s. Waiting for completion...", track_id)
        await _active_downloads[track_id].wait()
        # After waiting, the file should be in the temp cache
        if os.path.exists(temp_path):
            return get_local_stream(temp_path)
        # If it failed or was removed, fall through to start a new one

    # 4. Starting new download
    _logger.info("Initializing YouTube stream for track: %s", track_id)
    download_event = asyncio.Event()
    _active_downloads[track_id] = download_event
    
    # Ensure cache dirs exist
    os.makedirs(PERSISTENT_CACHE_DIR, exist_ok=True)
    os.makedirs(TEMP_CACHE_DIR, exist_ok=True)

    # Construct transcoding pipeline
    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "-o", "-", 
        f"https://www.youtube.com/watch?v={track_id}"
    ]

    ffmpeg_cmd = [
        "ffmpeg",
        "-i", "pipe:0",
        "-f", "mp3",
        "-acodec", "libmp3lame",
        "-ab", "128k",
        "pipe:1"
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        ffmpeg_process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdin=process.stdout,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as e:
        _logger.error("Required dependency (yt-dlp or ffmpeg) not found: %s", str(e))
        raise

    download_path = f"{temp_path}.download"

    async def iterate_stdout() -> AsyncGenerator[bytes, None]:
        """
        Stream from ffmpeg stdout and cache simultaneously.
        """
        success = False
        bytes_yielded = 0
        try:
            with open(download_path, "wb") as cache_file:
                while True:
                    chunk = await ffmpeg_process.stdout.read(16 * 1024) 
                    if not chunk:
                        break
                    cache_file.write(chunk)
                    yield chunk
                    bytes_yielded += len(chunk)
            
            # Wait for processes
            await asyncio.gather(process.wait(), ffmpeg_process.wait())
            
            if process.returncode != 0:
                _, stderr = await process.communicate()
                _logger.error("yt-dlp failed: %s", stderr.decode().strip())
                return

            if ffmpeg_process.returncode != 0:
                _logger.error("ffmpeg failed with code %s", ffmpeg_process.returncode)
                return

            # Atomic rename
            if os.path.exists(download_path) and bytes_yielded > 0:
                os.rename(download_path, temp_path)
                success = True
                _logger.info("Atomic cache complete: %s (%s bytes)", track_id, bytes_yielded)
            
            if success:
                # Update DB
                with Session(engine) as session:
                    statement = select(Track).where(Track.remote_id == track_id)
                    track = session.exec(statement).first()
                    if track:
                        track.is_cached = True
                        track.local_path = temp_path
                        session.add(track)
                        session.commit()
        except Exception:
            _logger.exception("Streaming error for track: %s", track_id)
        finally:
            download_event.set()
            _active_downloads.pop(track_id, None)
            if not success and os.path.exists(download_path):
                try: os.remove(download_path)
                except: pass

    # On Windows, we need to be careful with the mime-type if it's actually Opus/WebM.
    # However, Chrome handles most things. If it's failing, it's likely an empty stream.
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
