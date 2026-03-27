"""
Streaming service for MySpotify.

Uses subprocess.Popen (not asyncio.create_subprocess_exec) so it works on
both Windows SelectorEventLoop and Linux EpollEventLoop.
FastAPI automatically runs sync generators in a thread-pool executor.
"""
import os
import sys
import shutil
import subprocess
import threading
from typing import Dict, Generator

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from sqlmodel import Session, select

from app.models import Track
from app.db import engine
from app.config import settings
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

PERSISTENT_CACHE_DIR: str = settings.CACHE_DIR
TEMP_CACHE_DIR: str = settings.TEMP_DIR

# Registry to prevent duplicate yt-dlp processes for the same track
_active_downloads: Dict[str, threading.Event] = {}
_active_downloads_lock = threading.Lock()


def _find_executable(name: str) -> str:
    """Find an executable in PATH or the current venv's Scripts/bin directory."""
    found = shutil.which(name)
    if found:
        return found
    # Fallback: look next to the Python interpreter (inside venv)
    if sys.platform == "win32":
        venv_bin = os.path.join(os.path.dirname(sys.executable), f"{name}.exe")
    else:
        venv_bin = os.path.join(os.path.dirname(sys.executable), name)
    if os.path.exists(venv_bin):
        return venv_bin
    return name  # let the OS raise FileNotFoundError if missing


def validate_cache_file(path: str, min_size: int = 100 * 1024) -> bool:
    """Check if a file exists and is reasonably large (e.g., > 100KB for an MP3)."""
    if not os.path.exists(path):
        return False
    size = os.path.getsize(path)
    if size < min_size:
        _logger.warning("Cache file %s is suspiciously small (%d bytes). Deleting.", path, size)
        try:
            os.remove(path)
        except Exception:
            pass
        return False
    return True


async def stream_youtube(track_id: str) -> StreamingResponse:
    """
    Stream audio from YouTube using yt-dlp → ffmpeg pipeline.
    Returns a StreamingResponse backed by a synchronous generator so it is
    compatible with Windows SelectorEventLoop and Linux EpollEventLoop.
    """
    # 1. Serve from persistent cache
    persistent_path = os.path.join(PERSISTENT_CACHE_DIR, f"{track_id}.mp3")
    if validate_cache_file(persistent_path):
        _logger.info("Serving from healthy persistent cache: %s", track_id)
        return get_local_stream(persistent_path)

    # 2. Serve from temp cache
    temp_path = os.path.join(TEMP_CACHE_DIR, f"{track_id}.mp3")
    if validate_cache_file(temp_path):
        _logger.info("Serving from healthy temp cache: %s", track_id)
        return get_local_stream(temp_path)

    # 3. Wait if a download for this track_id is already running
    with _active_downloads_lock:
        existing_event = _active_downloads.get(track_id)

    if existing_event is not None:
        _logger.info("Download in progress for %s — waiting…", track_id)
        existing_event.wait(timeout=60)
        if os.path.exists(temp_path):
            return get_local_stream(temp_path)
        # Download failed for the other waiter; fall through and try ourselves

    # 4. Pre-flight checks
    yt_dlp_path = _find_executable("yt-dlp")
    ffmpeg_path  = _find_executable("ffmpeg")

    if not shutil.which(yt_dlp_path):
        _logger.error("yt-dlp not found at: %s", yt_dlp_path)
        raise HTTPException(status_code=503,
                            detail="yt-dlp missing — run: pip install yt-dlp")
    if not shutil.which(ffmpeg_path):
        _logger.error("ffmpeg not found at: %s", ffmpeg_path)
        raise HTTPException(status_code=503,
                            detail="ffmpeg missing — install it and add to PATH")

    # 5. Register download
    done_event = threading.Event()
    with _active_downloads_lock:
        _active_downloads[track_id] = done_event

    os.makedirs(PERSISTENT_CACHE_DIR, exist_ok=True)
    os.makedirs(TEMP_CACHE_DIR, exist_ok=True)

    yt_cmd = [
        yt_dlp_path,
        "-f", "bestaudio",
        "-o", "-",
        f"https://www.youtube.com/watch?v={track_id}",
    ]
    ffmpeg_cmd = [
        ffmpeg_path,
        "-i", "pipe:0",
        "-f", "mp3",
        "-acodec", "libmp3lame",
        "-ab", "128k",
        "-loglevel", "error",
        "pipe:1",
    ]

    download_path = f"{temp_path}.download"
    _logger.info("Starting yt-dlp+ffmpeg pipeline for: %s", track_id)

    def _stream_sync() -> Generator[bytes, None, None]:
        """
        Synchronous generator — FastAPI runs this in a threadpool executor.
        Pipes yt-dlp → ffmpeg → HTTP response, caching to disk simultaneously.
        """
        success = False
        bytes_yielded = 0
        yt_proc = None
        ff_proc  = None
        try:
            # Use CREATE_NO_WINDOW on Windows to suppress console pop-ups
            popen_kwargs: dict = {}
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            yt_proc = subprocess.Popen(
                yt_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **popen_kwargs,
            )
            ff_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=yt_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **popen_kwargs,
            )
            # Close yt_proc.stdout in the parent so ffmpeg gets EOF when yt-dlp exits
            if yt_proc.stdout:
                yt_proc.stdout.close()

            with open(download_path, "wb") as cache_file:
                while True:
                    chunk = ff_proc.stdout.read(16 * 1024)
                    if not chunk:
                        break
                    cache_file.write(chunk)
                    yield chunk
                    bytes_yielded += len(chunk)

            yt_proc.wait()
            ff_proc.wait()

            if yt_proc.returncode != 0:
                err = (yt_proc.stderr.read() or b"").decode(errors="replace").strip()
                _logger.error("yt-dlp exited %d: %s", yt_proc.returncode, err)
                return
            if ff_proc.returncode != 0:
                err = (ff_proc.stderr.read() or b"").decode(errors="replace").strip()
                _logger.error("ffmpeg exited %d: %s", ff_proc.returncode, err)
                return

            if bytes_yielded > 0 and os.path.exists(download_path):
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                os.rename(download_path, temp_path)
                success = True
                _logger.info("Cached %s (%d bytes)", track_id, bytes_yielded)

        except Exception:
            _logger.exception("Streaming pipeline error for %s", track_id)
        finally:
            # Kill processes if still running
            for proc in (ff_proc, yt_proc):
                if proc and proc.poll() is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass

            # Clean up partial download
            if not success and os.path.exists(download_path):
                try:
                    os.remove(download_path)
                except Exception:
                    pass

            # Signal waiting threads
            done_event.set()
            with _active_downloads_lock:
                _active_downloads.pop(track_id, None)

            # Update DB (we are already in a thread, so sync Session is fine)
            if success:
                try:
                    with Session(engine) as session:
                        track = session.exec(
                            select(Track).where(Track.remote_id == track_id)
                        ).first()
                        if track:
                            track.is_cached = True
                            track.local_path = temp_path
                            session.add(track)
                            session.commit()
                except Exception:
                    _logger.exception("Failed to update DB for %s", track_id)

    return StreamingResponse(_stream_sync(), media_type="audio/mpeg")


def get_local_stream(file_path: str) -> FileResponse:
    """Stream a local audio file with HTTP Range support."""
    _logger.info("Streaming local file: %s", file_path)
    return FileResponse(file_path, media_type="audio/mpeg")
